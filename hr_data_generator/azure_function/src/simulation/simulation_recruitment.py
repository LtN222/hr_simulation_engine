import pandas as pd

from src.infrastructure.record_builder import build_record


class RecruitmentSimulator:
    """Generate application records for hires and non-hires.

    The fact table models the recruitment funnel. Accepted applications are
    linked to an Employee_Key; rejected and refused applications intentionally
    keep Employee_Key empty because those candidates never enter HR master data.
    """

    def __init__(self, config, schema, rng):
        self.config = config
        self.schema = schema
        self.rng = rng
        self.recruitment_cfg = config.recruitment

    def run(self, state, today):
        existing = state.get("fact_recruitment", pd.DataFrame())
        records = []
        recruitment_key = (
            int(existing["Recruitment_Key"].max()) + 1
            if not existing.empty and "Recruitment_Key" in existing
            else 1
        )

        latest_hires = state.get("_latest_hires", [])

        for hire in latest_hires:
            records.append(
                self._build_application(
                    recruitment_key,
                    today,
                    hire["Role_Key"],
                    hire["Department_Key"],
                    hire["HireSource_Key"],
                    "Aangenomen",
                    hire["Employee_Key"],
                    hire["Vacancy_Reason"],
                    quality_bias=0.9
                )
            )
            recruitment_key += 1

            for _ in range(self._non_hire_count(hire["Department_Key"], state)):
                records.append(
                    self._build_non_hire_application(
                        recruitment_key,
                        today,
                        hire["Role_Key"],
                        hire["Department_Key"],
                        state,
                        hire["Vacancy_Reason"]
                    )
                )
                recruitment_key += 1

        for vacancy in range(int(state.get("vacancies", 0))):
            role = self._choose_role(state)
            department_key = role["Department_Key"]
            for _ in range(self._extra_open_application_count(department_key, state)):
                records.append(
                    self._build_non_hire_application(
                        recruitment_key,
                        today,
                        role["Role_Key"],
                        department_key,
                        state,
                        "Open vacancy"
                    )
                )
                recruitment_key += 1

        if records:
            state["fact_recruitment"] = pd.concat(
                [existing, pd.DataFrame(records)],
                ignore_index=True
            )
        elif "fact_recruitment" not in state:
            state["fact_recruitment"] = pd.DataFrame(records)

        state.pop("_latest_hires", None)
        return state

    def _build_non_hire_application(
        self,
        recruitment_key,
        today,
        role_key,
        department_key,
        state,
        vacancy_reason
    ):
        status_weights = self.recruitment_cfg.get(
            "status_weights",
            {"Afgewezen": 0.75, "Geweigerd": 0.25}
        )
        status = self.rng.choices(
            list(status_weights.keys()),
            weights=list(status_weights.values())
        )[0]

        hire_source_key = self.rng.choice(
            state["dim_hire_source"]["HireSource_Key"].tolist()
        )

        return self._build_application(
            recruitment_key,
            today,
            role_key,
            department_key,
            hire_source_key,
            status,
            None,
            vacancy_reason,
            quality_bias=0.45 if status == "Afgewezen" else 0.65
        )

    def _build_application(
        self,
        recruitment_key,
        today,
        role_key,
        department_key,
        hire_source_key,
        status,
        employee_key,
        vacancy_reason,
        quality_bias
    ):
        decision_cfg = self.recruitment_cfg.get("decision_days", {})
        days_to_decision = self.rng.randint(
            decision_cfg.get("min", 3),
            decision_cfg.get("max", 28)
        )
        application_date = today - pd.DateOffset(days=days_to_decision)
        decision_date = today
        quality = round(max(1, min(5, self.rng.normalvariate(quality_bias * 5, 0.7))), 2)

        return build_record(
            self.schema,
            "fact_recruitment",
            {
                "Recruitment_Key": recruitment_key,
                "Application_Date": application_date,
                "Decision_Date": decision_date,
                "Role_Key": role_key,
                "Department_Key": department_key,
                "HireSource_Key": hire_source_key,
                "Status": status,
                "Employee_Key": employee_key,
                "Vacancy_Reason": vacancy_reason,
                "Candidate_Quality": quality,
                "Days_To_Decision": days_to_decision
            }
        )

    def _non_hire_count(self, department_key, state):
        department_name = self._department_name(department_key, state)
        cfg = self.recruitment_cfg.get("applications_per_hire_by_department", {})
        average = cfg.get(department_name, 4)
        return max(0, int(self.rng.normalvariate(average - 1, 1.2)))

    def _extra_open_application_count(self, department_key, state):
        department_name = self._department_name(department_key, state)
        cfg = self.recruitment_cfg.get("extra_open_applications_by_department", {})
        average = cfg.get(department_name, 1)
        return max(0, int(self.rng.normalvariate(average, 0.8)))

    def _choose_role(self, state):
        role_rows = state["dim_role"].to_dict("records")
        weights = [
            self.config.structure[
                self._department_name(role["Department_Key"], state)
            ][role["Role_Name"]].get("fte_ratio", 0.01)
            for role in role_rows
        ]
        return self.rng.choices(role_rows, weights=weights)[0]

    def _department_name(self, department_key, state):
        return state["dim_department"].loc[
            state["dim_department"]["Department_Key"] == department_key,
            "Department_Name"
        ].iloc[0]
