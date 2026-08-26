"""Weekly attrition simulation with retirement and satisfaction context."""

import math

import pandas as pd

from src.infrastructure.satisfaction import (
    SatisfactionModel,
    score_employee_satisfaction,
)
from src.infrastructure.engagement import (
    EngagementModel,
    score_employee_engagement,
)


class AttritionSimulator:
    """Simulate employee exits while retaining their event-time context."""

    def __init__(self, config, rng, event_type_map, departure_reason_map):
        self.config = config
        self.rng = rng
        self.event_type_map = event_type_map
        self.departure_reason_map = departure_reason_map

    def run(self, state, today):
        dim_department = state["dim_department"]
        dim_role = state["dim_role"]
        dim_employee = state["dim_employee"]
        fact_employment = state["fact_employment"]

        if "Datum_uitdienst" not in dim_employee.columns:
            dim_employee["Datum_uitdienst"] = None
        if "In_Dienst" not in dim_employee.columns:
            dim_employee["In_Dienst"] = True
        for column in (
            "Tevredenheid_Score_Bij_Uitdienst",
            "SatisfactionBand_Key_Bij_Uitdienst",
            "Betrokkenheid_Score_Bij_Uitdienst",
            "EngagementBand_Key_Bij_Uitdienst",
        ):
            if column not in fact_employment.columns:
                fact_employment[column] = None

        active_employment = fact_employment[
            fact_employment["Dienstverband_status"] == "Actief"
        ]
        if active_employment.empty:
            return state

        role_lookup = dim_role.set_index("Role_Key")
        department_lookup = dim_department.set_index("Department_Key")
        employee_lookup = dim_employee.set_index("Employee_Key")
        salary_by_role = (
            fact_employment.groupby("Role_Key")["Salaris"].mean().to_dict()
        )
        satisfaction_model = SatisfactionModel(self.config)
        satisfaction_bands = state.get("dim_satisfaction_band", pd.DataFrame())
        engagement_model = EngagementModel(self.config)
        engagement_bands = state.get("dim_engagement_band", pd.DataFrame())

        week = today.isocalendar()[1]
        cyclic_factor = 1 + 0.25 * math.sin(2 * math.pi * week / 52)
        shock_multiplier = (
            self.rng.uniform(1.5, 3.0)
            if self.rng.random() < 0.02
            else 1.0
        )

        for index, employment in active_employment.iterrows():
            employee = employee_lookup.loc[employment["Employee_Key"]]
            role = role_lookup.loc[employment["Role_Key"]]
            department = department_lookup.loc[role["Department_Key"]]
            department_name = department["Department_Name"]
            performance = pd.to_numeric(
                employee.get("Performance_Score"), errors="coerce"
            )
            performance = float(performance) if pd.notna(performance) else 3.4
            satisfaction = score_employee_satisfaction(
                satisfaction_model,
                state,
                employee,
                employment,
                today,
                performance_score=performance,
            )
            satisfaction_band_key = satisfaction_model.band_key_for(
                satisfaction_bands,
                satisfaction,
            )
            engagement = score_employee_engagement(
                engagement_model,
                state,
                employee,
                employment,
                today,
                satisfaction_score=satisfaction,
                performance_score=performance,
            )
            engagement_band_key = engagement_model.band_key_for(
                engagement_bands,
                engagement,
            )

            weekly_attrition = (
                float(self.config.attrition.get(department_name, 0.05)) / 52
            )
            weekly_attrition *= self._performance_multiplier(performance)
            tenure_years = max(
                0.0,
                (pd.Timestamp(today) - pd.Timestamp(employment["Startdatum"])).days
                / 365.2425,
            )
            weekly_attrition *= self._tenure_multiplier(tenure_years)

            salary_ratio = self._salary_ratio(
                employment,
                salary_by_role.get(employment["Role_Key"]),
            )
            weekly_attrition *= self._salary_multiplier(
                salary_ratio,
                performance,
                tenure_years,
            )
            weekly_attrition *= self._satisfaction_multiplier(satisfaction)
            weekly_attrition *= self._engagement_multiplier(engagement)
            weekly_attrition *= cyclic_factor * shock_multiplier

            retirement_probability = self._retirement_weekly_probability(
                employee,
                today,
            )
            is_retirement = self.rng.random() < retirement_probability
            if not is_retirement and self.rng.random() >= weekly_attrition:
                continue

            category = self._departure_category(
                performance,
                tenure_years,
                satisfaction,
                engagement,
            )
            reason = self._choose_reason(
                category,
                performance,
                tenure_years,
                salary_ratio,
                satisfaction,
            )
            if is_retirement:
                reason = "Pensioen"

            fact_employment.loc[index, "Dienstverband_status"] = "Uit dienst"
            fact_employment.loc[index, "Einddatum"] = today
            fact_employment.loc[index, "DepartureReason_Key"] = (
                self.departure_reason_map.get(
                    reason,
                    next(iter(self.departure_reason_map.values())),
                )
            )
            fact_employment.loc[index, "EventType_Key"] = self.event_type_map[
                "Uit dienst"
            ]
            fact_employment.loc[index, "Tevredenheid_Score_Bij_Uitdienst"] = (
                satisfaction
            )
            fact_employment.loc[index, "SatisfactionBand_Key_Bij_Uitdienst"] = (
                satisfaction_band_key
            )
            fact_employment.loc[index, "Betrokkenheid_Score_Bij_Uitdienst"] = (
                engagement
            )
            fact_employment.loc[index, "EngagementBand_Key_Bij_Uitdienst"] = (
                engagement_band_key
            )
            dim_employee.loc[
                dim_employee["Employee_Key"] == employment["Employee_Key"],
                "In_Dienst",
            ] = False
            dim_employee.loc[
                dim_employee["Employee_Key"] == employment["Employee_Key"],
                "Datum_uitdienst",
            ] = today

            state["vacancies"] = state.get("vacancies", 0) + 1
            state.setdefault("_vacancy_requests", []).append({
                "Role_Key": employment["Role_Key"],
                "Department_Key": role["Department_Key"],
                "Vacancy_Reason": "Replacement",
            })

        state["fact_employment"] = fact_employment
        state["dim_employee"] = dim_employee
        return state

    @staticmethod
    def _performance_multiplier(performance):
        if performance < 2.5:
            return 1.8
        if performance > 4.0:
            return 0.7
        return 1.0

    @staticmethod
    def _tenure_multiplier(tenure_years):
        if tenure_years < 1:
            return 1.5
        if tenure_years > 10:
            return 0.7
        return 1.0

    @staticmethod
    def _salary_ratio(employment, role_average_salary):
        target_ratio = pd.to_numeric(
            employment.get("Target_Compa_Ratio"), errors="coerce"
        )
        if pd.notna(target_ratio):
            return float(target_ratio)
        salary = pd.to_numeric(employment.get("Salaris"), errors="coerce")
        if pd.isna(salary) or not role_average_salary or role_average_salary <= 0:
            return 1.0
        return float(salary) / float(role_average_salary)

    @staticmethod
    def _salary_multiplier(salary_ratio, performance, tenure_years):
        multiplier = 1.0
        if salary_ratio < 0.85:
            multiplier *= 1.4
        elif salary_ratio < 0.95:
            multiplier *= 1.15
        elif salary_ratio > 1.15:
            multiplier *= 0.85
        if performance > 4.0 and salary_ratio < 0.95:
            multiplier *= 1.2
        if tenure_years > 5 and salary_ratio < 1.2:
            multiplier *= 1.2
        return multiplier

    def _satisfaction_multiplier(self, satisfaction):
        multipliers = self.config.attrition.get(
            "satisfaction_attrition_multipliers",
            {},
        )
        if satisfaction < 4.5:
            return float(multipliers.get("zeer_laag", 1.80))
        if satisfaction < 6.0:
            return float(multipliers.get("laag", 1.35))
        if satisfaction < 7.5:
            return float(multipliers.get("neutraal", 1.05))
        if satisfaction < 8.5:
            return float(multipliers.get("hoog", 0.85))
        return float(multipliers.get("zeer_hoog", 0.70))

    def _engagement_multiplier(self, engagement):
        """Apply a small retention effect without eclipsing satisfaction."""
        multipliers = self.config.attrition.get(
            "engagement_attrition_multipliers",
            {},
        )
        if engagement < 6.0:
            return float(multipliers.get("laag", 1.18))
        if engagement < 7.5:
            return float(multipliers.get("neutraal", 1.0))
        return float(multipliers.get("hoog", 0.92))

    def _departure_category(
        self,
        performance,
        tenure_years,
        satisfaction,
        engagement,
    ):
        """Choose who initiates the exit after its probability was drawn."""
        if performance < 2.5:
            voluntary_weight, employer_weight = 0.35, 0.65
        elif satisfaction < 6.0 or engagement < 6.0:
            voluntary_weight, employer_weight = 0.90, 0.10
        elif satisfaction >= 8.5:
            voluntary_weight, employer_weight = 0.60, 0.40
        elif tenure_years < 1:
            voluntary_weight, employer_weight = 0.80, 0.20
        else:
            voluntary_weight, employer_weight = 0.75, 0.25
        return self.rng.choices(
            ["vrijwillig", "werkgever"],
            weights=[voluntary_weight, employer_weight],
            k=1,
        )[0]

    def _choose_reason(
        self,
        category,
        performance,
        tenure_years,
        salary_ratio,
        satisfaction,
    ):
        reasons = self.config.dim_departure_reason[category]
        weights = [
            self._reason_weight(
                reason,
                performance,
                tenure_years,
                salary_ratio,
                satisfaction,
            )
            for reason in reasons
        ]
        if sum(weights) <= 0:
            return reasons[0]
        return self.rng.choices(reasons, weights=weights, k=1)[0]

    def _reason_weight(
        self,
        reason,
        performance,
        tenure_years,
        salary_ratio,
        satisfaction,
    ):
        if reason == "Pensioen":
            return 0.0
        if reason == "No-show":
            return 0.02
        if reason == "Medisch":
            return 0.05
        if reason == "Disfunctioneren":
            return 0.30 if performance < 2.5 else 0.05
        if reason == "Ontslag":
            return 0.20
        if reason == "Contract niet verlengd":
            return 0.25 if tenure_years < 2 else 0.05

        settings = self.config.attrition.get(
            "voluntary_reason_satisfaction_multipliers",
            {},
        )
        satisfaction_group = (
            "laag" if satisfaction < 6.0
            else "hoog" if satisfaction >= 7.5
            else "neutraal"
        )
        factor = float(settings.get(reason, {}).get(satisfaction_group, 1.0))

        if reason == "Hoger salaris":
            if salary_ratio < 0.90:
                factor *= 1.80
            elif salary_ratio < 1.0:
                factor *= 1.25
            elif salary_ratio >= 1.10:
                factor *= 0.65
        elif reason == "CarriÃ¨re switch" and performance >= 4.0:
            factor *= 1.20
        return factor

    def _retirement_weekly_probability(self, employee, today):
        """Return the retirement probability for one simulation week."""
        config = getattr(self.config, "retirement", {})
        birth_date = pd.to_datetime(
            employee.get("Geboortedatum"), errors="coerce"
        )
        if pd.isna(birth_date):
            return 0.0

        reference_date = pd.Timestamp(today).normalize()
        age = reference_date.year - birth_date.year - (
            (reference_date.month, reference_date.day)
            < (birth_date.month, birth_date.day)
        )
        if age < int(config.get("minimum_age", 50)):
            return 0.0
        if age >= int(config.get("forced_retirement_age", 67)):
            return 1.0

        for band in config.get("age_bands", []):
            if band["min_age"] <= age <= band["max_age"]:
                annual_probability = float(band["annual_probability"])
                return 1 - (1 - annual_probability) ** (1 / 52)
        return 0.0
