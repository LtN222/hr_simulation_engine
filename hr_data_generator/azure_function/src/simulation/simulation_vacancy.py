import pandas as pd

from src.application.allocation import minimum_count_for_role
from src.infrastructure.record_builder import build_record
from src.simulation.simulation_growth import economic_event_for_date


class VacancySimulator:
    """Maintain an explicit vacancy backlog.

    Vacancy demand comes from two sources:
    - replacement requests raised by attrition, with the leaver's role;
    - growth demand from the headcount target curve, assigned to roles that are
      below their configured workforce mix.
    """

    def __init__(self, config, schema, rng):
        self.config = config
        self.schema = schema
        self.rng = rng

    def run(self, state, today, growth_vacancies):
        existing = state.get("fact_vacancy", pd.DataFrame())
        records = []
        vacancy_key = (
            int(existing["Vacancy_Key"].max()) + 1
            if not existing.empty and "Vacancy_Key" in existing.columns
            else 1
        )

        economic_event = economic_event_for_date(self.config.growth, today)
        replacement_hiring_rate = float(
            economic_event.get("replacement_hiring_rate", 1.0)
            if economic_event
            else 1.0
        )

        for request in state.get("_vacancy_requests", []):
            if (
                request.get("Vacancy_Reason", "Replacement") == "Replacement"
                and self.rng.random() > replacement_hiring_rate
            ):
                continue
            records.append(
                self._build_vacancy(
                    vacancy_key,
                    today,
                    request["Role_Key"],
                    request["Department_Key"],
                    request.get("Vacancy_Reason", "Replacement")
                )
            )
            vacancy_key += 1

        role_counts = self._active_role_counts(state)
        target_headcount = sum(role_counts.values()) + max(0, int(growth_vacancies))

        for _ in range(max(0, int(growth_vacancies))):
            role = self._choose_role_for_growth(state, role_counts, target_headcount)
            records.append(
                self._build_vacancy(
                    vacancy_key,
                    today,
                    role["Role_Key"],
                    role["Department_Key"],
                    "Growth"
                )
            )
            vacancy_key += 1
            role_counts[role["Role_Key"]] = role_counts.get(role["Role_Key"], 0) + 1

        if records:
            state["fact_vacancy"] = pd.concat(
                [existing, pd.DataFrame(records)],
                ignore_index=True
            )
        elif "fact_vacancy" not in state:
            state["fact_vacancy"] = pd.DataFrame(records)

        state["vacancies"] = self._open_vacancy_count(state)
        state.pop("_vacancy_requests", None)
        return state

    def _build_vacancy(self, vacancy_key, today, role_key, department_key, reason):
        target_days = self.rng.randint(14, 56)
        return build_record(
            self.schema,
            "fact_vacancy",
            {
                "Vacancy_Key": vacancy_key,
                "Created_Date": today,
                "Closed_Date": None,
                "Role_Key": role_key,
                "Department_Key": department_key,
                "Vacancy_Reason": reason,
                "Status": "Open",
                "Target_Start_Date": today + pd.DateOffset(days=target_days),
                "Filled_Employee_Key": None
            }
        )

    def _choose_role_for_growth(self, state, role_counts, target_headcount):
        dim_role = state["dim_role"]

        under_minimum = dim_role[
            dim_role.apply(
                lambda role: role_counts.get(role["Role_Key"], 0)
                < self._minimum_for_role(state, role),
                axis=1
            )
        ]
        if not under_minimum.empty:
            # Correct structural shortages before following the long-term
            # workforce mix. This also repairs a manager role after attrition.
            return under_minimum.iloc[0]

        total_ratio = self._total_structure_ratio()
        weighted_roles = []
        weights = []

        for _, role in dim_role.iterrows():
            target_ratio = self._target_ratio_for_role(state, role)
            target_share = target_ratio / total_ratio
            target_count = target_share * max(1, target_headcount)
            current_count = role_counts.get(role["Role_Key"], 0)
            gap = target_count - current_count
            weight = 1 + max(0, gap)

            if gap < -1:
                weight = 0.05

            weighted_roles.append(role)
            weights.append(weight)

        return self.rng.choices(weighted_roles, weights=weights)[0]

    def _minimum_for_role(self, state, role_row):
        department_name = self._department_name(
            role_row["Department_Key"],
            state
        )
        role_config = self.config.structure[department_name][
            role_row["Role_Name"]
        ]
        return minimum_count_for_role(
            department_name,
            role_row["Role_Name"],
            role_config,
            getattr(self.config, "staffing", {})
        )

    def _active_role_counts(self, state):
        active = state["fact_employment"][
            state["fact_employment"]["Dienstverband_status"] == "Actief"
        ]
        return active["Role_Key"].value_counts().to_dict()

    def _open_vacancy_count(self, state):
        vacancy = state.get("fact_vacancy", pd.DataFrame())
        if vacancy.empty or "Status" not in vacancy.columns:
            return 0
        return int((vacancy["Status"] == "Open").sum())

    def _total_structure_ratio(self):
        total_ratio = sum(
            role_cfg.get("fte_ratio", 0)
            for roles in self.config.structure.values()
            for role_cfg in roles.values()
        )
        return total_ratio or 1

    def _target_ratio_for_role(self, state, role_row):
        department_name = self._department_name(role_row["Department_Key"], state)
        role_name = role_row["Role_Name"]
        return self.config.structure[department_name][role_name].get("fte_ratio", 0.01)

    def _department_name(self, department_key, state):
        return state["dim_department"].loc[
            state["dim_department"]["Department_Key"] == department_key,
            "Department_Name"
        ].iloc[0]
