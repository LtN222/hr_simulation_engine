"""Ketenregeling: the Dutch chain rule for temporary (tijdelijk) contracts.

By law, an employee may have at most `max_contract_rounds` temporary
contracts, or `max_temporary_years` of consecutive temporary employment,
whichever comes first - the next contract at that point must be permanent
(vast), not another temporary renewal. This simulator is the only place that
resolves what happens when an active Tijdelijk contract reaches its
Contract_einddatum: renew, convert to Vast, or let it lapse (a genuine
departure, using the same terminal-row mechanism attrition uses).

Runs before AttritionSimulator in the weekly order, so a lapsed contract is
already resolved as a departure before attrition's own independent weekly
roll would otherwise consider that employee.
"""
import pandas as pd

from src.infrastructure.departure_records import build_departure_row
from src.infrastructure.record_builder import build_record
from src.infrastructure.satisfaction import (
    SatisfactionModel,
    score_employee_satisfaction,
)
from src.infrastructure.engagement import (
    EngagementModel,
    score_employee_engagement,
)

NON_RENEWAL_REASON = "Contract niet verlengd"


class ContractLifecycleSimulator:

    def __init__(self, config, schema, rng, event_type_map, departure_reason_map):
        self.config = config
        self.schema = schema
        self.rng = rng
        self.event_type_map = event_type_map
        self.departure_reason_map = departure_reason_map
        self.chain_cfg = getattr(config, "career_events", {}).get("chain_rule", {})

    def run(self, state, today):
        today = pd.Timestamp(today).normalize()
        fact_employment = state["fact_employment"]
        dim_employee = state["dim_employee"]

        active = fact_employment[
            fact_employment["Dienstverband_status"] == "Actief"
        ].copy()
        if active.empty:
            return state

        active["Contract_einddatum"] = pd.to_datetime(
            active.get("Contract_einddatum"), errors="coerce"
        )
        due = active[
            (active["Contracttype"] == "Tijdelijk")
            & active["Contract_einddatum"].notna()
            & (active["Contract_einddatum"] <= today)
        ]
        if due.empty:
            return state

        role_lookup = state.get("dim_role", pd.DataFrame())
        role_lookup = (
            role_lookup.set_index("Role_Key") if not role_lookup.empty else role_lookup
        )
        department_lookup = state.get("dim_department", pd.DataFrame())
        department_lookup = (
            department_lookup.set_index("Department_Key")
            if not department_lookup.empty else department_lookup
        )
        employee_lookup = dim_employee.set_index("Employee_Key")
        performance_p90 = self._top_performer_threshold(employee_lookup, active)

        satisfaction_model = SatisfactionModel(self.config)
        satisfaction_bands = state.get("dim_satisfaction_band", pd.DataFrame())
        engagement_model = EngagementModel(self.config)
        engagement_bands = state.get("dim_engagement_band", pd.DataFrame())

        next_key = int(fact_employment["Employment_Key"].max()) + 1
        new_records = []
        departure_records = []

        for index, employment in due.iterrows():
            employee_key = employment["Employee_Key"]
            employee = employee_lookup.loc[employee_key]
            role = (
                role_lookup.loc[employment["Role_Key"]]
                if not role_lookup.empty else None
            )
            department_name = self._department_name(role, department_lookup)

            performance = pd.to_numeric(
                employee.get("Prestatie_Score"), errors="coerce"
            )
            performance = float(performance) if pd.notna(performance) else 3.4

            service_start = pd.to_datetime(
                employee.get("Aaneengesloten_Indienst_Datum"), errors="coerce"
            )
            temporary_years = (
                max(0.0, (today - service_start).days / 365.2425)
                if pd.notna(service_start) else 0.0
            )
            contract_round = int(pd.to_numeric(
                employment.get("Contract_ronde"), errors="coerce"
            ) or 0)
            cap_reached = (
                contract_round >= int(self.chain_cfg.get("max_contract_rounds", 3))
                or temporary_years >= float(self.chain_cfg.get("max_temporary_years", 3.0))
            )

            outcome = self._choose_outcome(
                cap_reached, performance, performance_p90, department_name
            )

            if outcome == "renew":
                fact_employment.loc[index, "Dienstverband_status"] = "Inactief"
                fact_employment.loc[index, "Einddatum"] = today
                new_records.append(self._renewed_record(employment, next_key, today))
                next_key += 1
                continue

            if outcome == "convert":
                fact_employment.loc[index, "Dienstverband_status"] = "Inactief"
                fact_employment.loc[index, "Einddatum"] = today
                new_records.append(self._converted_record(employment, next_key, today))
                next_key += 1
                continue

            # outcome == "depart": the contract lapses without renewal.
            satisfaction = score_employee_satisfaction(
                satisfaction_model, state, employee, employment, today,
                performance_score=performance,
            )
            satisfaction_band_key = satisfaction_model.band_key_for(
                satisfaction_bands, satisfaction,
            )
            engagement = score_employee_engagement(
                engagement_model, state, employee, employment, today,
                satisfaction_score=satisfaction, performance_score=performance,
            )
            engagement_band_key = engagement_model.band_key_for(
                engagement_bands, engagement,
            )

            fact_employment.loc[index, "Dienstverband_status"] = "Inactief"
            fact_employment.loc[index, "Einddatum"] = today

            departure_reason_key = self.departure_reason_map.get(
                NON_RENEWAL_REASON,
                next(iter(self.departure_reason_map.values())),
            )
            departure_records.append(build_departure_row(
                self.schema,
                employment,
                next_key,
                today,
                self.event_type_map["Uit dienst"],
                departure_reason_key,
                satisfaction,
                satisfaction_band_key,
                engagement,
                engagement_band_key,
            ))
            next_key += 1

            dim_employee.loc[
                dim_employee["Employee_Key"] == employee_key, "In_Dienst",
            ] = False
            dim_employee.loc[
                dim_employee["Employee_Key"] == employee_key, "Datum_uitdienst",
            ] = today

            state["vacancies"] = state.get("vacancies", 0) + 1
            state.setdefault("_vacancy_requests", []).append({
                "Role_Key": employment["Role_Key"],
                "Department_Key": (
                    role.get("Department_Key") if role is not None else None
                ),
                "Vacature_Reden": "Vervanging",
            })

        if new_records or departure_records:
            fact_employment = pd.concat(
                [fact_employment, pd.DataFrame(new_records + departure_records)],
                ignore_index=True,
            )

        state["fact_employment"] = fact_employment
        state["dim_employee"] = dim_employee
        return state

    # ------------------------------------------------------------------
    # Outcome selection
    # ------------------------------------------------------------------

    def _top_performer_threshold(self, employee_lookup, active):
        percentile = float(self.chain_cfg.get("top_performer_percentile", 0.90))
        scores = pd.to_numeric(
            employee_lookup.loc[
                employee_lookup.index.isin(active["Employee_Key"]), "Prestatie_Score"
            ],
            errors="coerce",
        ).dropna()
        return float(scores.quantile(percentile)) if not scores.empty else None

    def _department_name(self, role, department_lookup):
        if role is None or department_lookup.empty:
            return None
        department_key = role.get("Department_Key")
        if department_key not in department_lookup.index:
            return None
        return department_lookup.loc[department_key, "Afdeling_Naam"]

    def _department_rule(self, department_name, key, default):
        rules = getattr(self.config, "contract_rules", {})
        department_rules = rules.get(department_name, rules.get("default", {}))
        return float(department_rules.get(key, default))

    def _choose_outcome(self, cap_reached, performance, performance_p90, department_name):
        if cap_reached:
            # Only two outcomes are legally valid once the chain-rule cap is
            # reached: convert to Vast, or the contract lapses.
            conversion_kans = self._department_rule(
                department_name, "keten_conversion_kans", 0.6
            )
            return self.rng.choices(
                ["convert", "depart"],
                weights=[conversion_kans, max(0.0, 1 - conversion_kans)],
                k=1,
            )[0]

        is_top_performer = (
            performance_p90 is not None and performance >= performance_p90
        )
        convert_weight = (
            float(self.chain_cfg.get("top_performer_conversion_kans", 0.6))
            if is_top_performer
            else float(getattr(self.config, "career_events", {}).get(
                "contract_change_rate", 0.03
            ))
        )
        depart_weight = 0.15 * (1.8 if performance < 2.5 else 1.0)
        renew_weight = max(0.0, 1 - convert_weight - depart_weight)

        return self.rng.choices(
            ["renew", "convert", "depart"],
            weights=[renew_weight, convert_weight, depart_weight],
            k=1,
        )[0]

    # ------------------------------------------------------------------
    # Record construction
    # ------------------------------------------------------------------

    def _renewed_record(self, employment, next_key, today):
        contract_round = int(pd.to_numeric(
            employment.get("Contract_ronde"), errors="coerce"
        ) or 0) + 1
        renewal_years = float(self.chain_cfg.get("renewal_duration_years", 1.0))
        return build_record(
            self.schema,
            "fact_employment",
            {
                **self._carried_context(employment),
                "Employment_Key": next_key,
                "Previous_Employment_Key": employment["Employment_Key"],
                "Startdatum": today,
                "Einddatum": None,
                "Dienstverband_status": "Actief",
                "Contracttype": "Tijdelijk",
                "Contract_ronde": contract_round,
                "Contract_einddatum": today + pd.DateOffset(
                    days=round(renewal_years * 365.2425)
                ),
                "EventType_Key": self.event_type_map["Contract verlengd"],
                "DepartureReason_Key": None,
            }
        )

    def _converted_record(self, employment, next_key, today):
        return build_record(
            self.schema,
            "fact_employment",
            {
                **self._carried_context(employment),
                "Employment_Key": next_key,
                "Previous_Employment_Key": employment["Employment_Key"],
                "Startdatum": today,
                "Einddatum": None,
                "Dienstverband_status": "Actief",
                "Contracttype": "Vast",
                "Contract_ronde": None,
                "Contract_einddatum": None,
                "EventType_Key": self.event_type_map["Contract omgezet naar vast"],
                "DepartureReason_Key": None,
            }
        )

    @staticmethod
    def _carried_context(employment):
        """Fields that stay the same across a renewal/conversion - this is
        not a role, pay or location change, just a contract-status change."""
        return {
            "Employee_Key": employment["Employee_Key"],
            "HireSource_Key": employment.get("HireSource_Key"),
            "Role_Key": employment["Role_Key"],
            "Location_Key": employment.get("Location_Key"),
            "Shift_Key": employment.get("Shift_Key"),
            "SalaryScale_Key": employment.get("SalaryScale_Key"),
            "Streef_Compa_Ratio": employment.get("Streef_Compa_Ratio"),
            "Relevante_Ervaring_Jaren_Bij_Start": employment.get(
                "Relevante_Ervaring_Jaren_Bij_Start"
            ),
            "Salaris": employment.get("Salaris"),
            "Contracturen": employment.get("Contracturen"),
        }
