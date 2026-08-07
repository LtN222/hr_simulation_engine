import pandas as pd

from src.infrastructure.record_builder import build_record


class RecruitmentSimulator:
    """Generate applications for open vacancies before employees are hired."""

    def __init__(self, config, schema, rng):
        self.config = config
        self.schema = schema
        self.rng = rng
        self.recruitment_cfg = config.recruitment

    def run(self, state, today):
        existing = state.get("fact_recruitment", pd.DataFrame())
        records = []
        accepted_applications = []
        recruitment_key = (
            int(existing["Recruitment_Key"].max()) + 1
            if not existing.empty and "Recruitment_Key" in existing.columns
            else 1
        )

        open_vacancies = self._open_vacancies_without_acceptance(state, existing)

        for _, vacancy in open_vacancies.iterrows():
            department_name = self._department_name(vacancy["Department_Key"], state)
            hire_source_key = self._choose_hire_source(state, department_name)
            accepted_this_week = self._is_accepted_this_week(vacancy, today, department_name)

            if accepted_this_week:
                records.append(
                    self._build_application(
                        recruitment_key,
                        vacancy,
                        today,
                        hire_source_key,
                        "Aangenomen",
                        None,
                        quality_bias=0.9
                    )
                )
                accepted_applications.append({
                    "Recruitment_Key": recruitment_key,
                    "Vacancy_Key": vacancy["Vacancy_Key"],
                    "Role_Key": vacancy["Role_Key"],
                    "Department_Key": vacancy["Department_Key"],
                    "HireSource_Key": hire_source_key,
                    "Vacancy_Reason": vacancy["Vacancy_Reason"]
                })
                recruitment_key += 1
                non_hire_count = self._non_hire_count(department_name)
            else:
                non_hire_count = self._extra_open_application_count(department_name)

            for _ in range(non_hire_count):
                records.append(
                    self._build_non_hire_application(
                        recruitment_key,
                        vacancy,
                        today,
                        state
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

        state["_accepted_applications"] = accepted_applications
        return state

    def _open_vacancies_without_acceptance(self, state, existing):
        vacancy = state.get("fact_vacancy", pd.DataFrame())
        if vacancy.empty:
            return vacancy

        open_vacancies = vacancy[vacancy["Status"] == "Open"].copy()
        if existing.empty or "Vacancy_Key" not in existing.columns:
            return open_vacancies

        accepted_vacancy_keys = existing.loc[
            existing["Status"] == "Aangenomen",
            "Vacancy_Key"
        ].dropna().unique()

        return open_vacancies[
            ~open_vacancies["Vacancy_Key"].isin(accepted_vacancy_keys)
        ]

    def _is_accepted_this_week(self, vacancy, today, department_name):
        created_date = pd.Timestamp(vacancy["Created_Date"])
        age_weeks = max(0, (pd.Timestamp(today) - created_date).days // 7)
        applications_per_hire = self._applications_per_hire(department_name)

        # Scarce roles with many applications per hire fill more slowly. The
        # age term lets persistent open vacancies become progressively easier
        # to close without making every new vacancy instantly successful.
        base_probability = min(0.45, 1.8 / max(1, applications_per_hire))
        aging_boost = min(0.35, age_weeks * 0.035)
        return self.rng.random() < min(0.8, base_probability + aging_boost)

    def _build_non_hire_application(self, recruitment_key, vacancy, today, state):
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
            vacancy,
            today,
            hire_source_key,
            status,
            None,
            quality_bias=0.45 if status == "Afgewezen" else 0.65
        )

    def _build_application(
        self,
        recruitment_key,
        vacancy,
        today,
        hire_source_key,
        status,
        employee_key,
        quality_bias
    ):
        decision_cfg = self.recruitment_cfg.get("decision_days", {})
        days_to_decision = self.rng.randint(
            decision_cfg.get("min", 3),
            decision_cfg.get("max", 28)
        )
        decision_date = today if status != "In behandeling" else None
        quality = round(max(1, min(5, self.rng.normalvariate(quality_bias * 5, 0.7))), 2)

        return build_record(
            self.schema,
            "fact_recruitment",
            {
                "Recruitment_Key": recruitment_key,
                "Vacancy_Key": vacancy["Vacancy_Key"],
                "Application_Date": today - pd.DateOffset(days=days_to_decision),
                "Decision_Date": decision_date,
                "Role_Key": vacancy["Role_Key"],
                "Department_Key": vacancy["Department_Key"],
                "HireSource_Key": hire_source_key,
                "Status": status,
                "Employee_Key": employee_key,
                "Vacancy_Reason": vacancy["Vacancy_Reason"],
                "Candidate_Quality": quality,
                "Days_To_Decision": days_to_decision
            }
        )

    def _non_hire_count(self, department_name):
        average = self._applications_per_hire(department_name)
        return max(0, int(self.rng.normalvariate(average - 1, 1.2)))

    def _extra_open_application_count(self, department_name):
        cfg = self.recruitment_cfg.get("extra_open_applications_by_department", {})
        average = cfg.get(department_name, 1)
        return max(0, int(self.rng.normalvariate(average, 0.8)))

    def _applications_per_hire(self, department_name):
        cfg = self.recruitment_cfg.get("applications_per_hire_by_department", {})
        return max(1, cfg.get(department_name, 4))

    def _choose_hire_source(self, state, department_name):
        sources = state["dim_hire_source"]
        source_names = (
            sources["HireSource"].tolist()
            if "HireSource" in sources.columns
            else sources["HireSource_Key"].tolist()
        )
        source_keys = sources["HireSource_Key"].tolist()

        if department_name in {"Productie", "Logistiek", "Techniek"}:
            preferred = {"Vacaturebank": 2.0, "Referral": 1.4, "Recruiter": 1.1}
        elif department_name in {"IT", "R&D", "Finance"}:
            preferred = {"Recruiter": 1.8, "Referral": 1.5, "Vacaturebank": 1.0}
        else:
            preferred = {"Recruiter": 1.5, "Referral": 1.2, "Campus": 1.0}

        weights = [preferred.get(name, 1.0) for name in source_names]
        return self.rng.choices(source_keys, weights=weights)[0]

    def _department_name(self, department_key, state):
        return state["dim_department"].loc[
            state["dim_department"]["Department_Key"] == department_key,
            "Department_Name"
        ].iloc[0]
