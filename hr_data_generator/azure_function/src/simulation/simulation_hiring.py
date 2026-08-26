import pandas as pd

from src.generator.employee_factory import EmployeeFactory
from src.infrastructure.manager_builder import assign_managers
from src.infrastructure.record_builder import build_record
from src.infrastructure.avatar import AvatarAssigner, avatar_fields
from src.infrastructure.salary_policy import SalaryPolicy
from src.infrastructure.shift_assignment import assign_ploegendienst_key
from src.infrastructure.relevant_experience import (
    carried_experience,
    initial_relevant_experience,
)
from src.infrastructure.location_assignment import (
    effective_role_capacity,
    resolve_location,
)
from src.simulation.simulation_recruitment import NOT_SELECTED_REASON, RecruitmentSimulator


class HiringSimulator:
    """Convert accepted applications into employees and close vacancies."""

    def __init__(self, config, schema, rng, event_type_map):
        self.config = config
        self.schema = schema
        self.rng = rng
        self.event_type_map = event_type_map
        self.employee_factory = EmployeeFactory(config, rng)
        self.avatar_assigner = AvatarAssigner(config)

    def run(self, state, today):
        accepted_applications = state.get("_accepted_applications", [])

        if not accepted_applications:
            state["_latest_hires"] = []
            state["vacancies"] = self._open_vacancy_count(state)
            return state

        dim_employee = state["dim_employee"]
        fact_employment = state["fact_employment"]
        fact_qualification = state.get("fact_employee_qualification", pd.DataFrame())

        next_employee_key = int(dim_employee["Employee_Key"].max()) + 1
        next_employment_key = int(fact_employment["Employment_Key"].max()) + 1
        next_qualification_key = (
            int(fact_qualification["EmployeeQualification_Key"].max()) + 1
            if not fact_qualification.empty
            and "EmployeeQualification_Key" in fact_qualification.columns
            else 1
        )

        new_employees = []
        new_employments = []
        new_qualifications = []
        latest_hires = []
        recruitment_employee_updates = {}
        vacancy_employee_updates = {}
        role_counts = self._active_role_counts(state)

        for application in accepted_applications:
            role_row = self._role_row(state, application["Role_Key"])
            department_name = self._department_name(
                state,
                application["Department_Key"]
            )
            role_name = role_row["Role_Name"]
            role_key = role_row["Role_Key"]

            if not self._has_capacity_for_hire(state, department_name, role_name, role_counts, role_key):
                # The seat filled up through another path (e.g. a direct
                # internal promotion in simulate_career_events) while this
                # offer was still working through the recruitment funnel.
                # This is the final backstop behind the vacancy-creation
                # guards in simulation_vacancy.py: close the vacancy without
                # creating a hire rather than exceed a hard headcount ceiling.
                self._close_vacancy_without_hire(state, application["Vacancy_Key"], today)
                continue

            if application.get("Is_Internal_Mobility"):
                internal_employee_key = application.get("Employee_Key")
                if pd.isna(internal_employee_key):
                    continue

                employment_record, backfill_request = self._move_internal_employee(
                    state,
                    int(internal_employee_key),
                    role_row,
                    today,
                    next_employment_key
                )
                if employment_record is None:
                    continue

                new_employments.append(employment_record)
                if backfill_request:
                    state.setdefault("_vacancy_requests", []).append(
                        backfill_request
                    )
                latest_hires.append({
                    "Employee_Key": int(internal_employee_key),
                    "Role_Key": role_row["Role_Key"],
                    "Department_Key": role_row["Department_Key"],
                    "HireSource_Key": application["HireSource_Key"],
                    "Vacancy_Key": application["Vacancy_Key"],
                    "Vacancy_Reason": application["Vacancy_Reason"],
                    "Is_Internal_Mobility": True
                })
                recruitment_employee_updates[application["Recruitment_Key"]] = (
                    int(internal_employee_key)
                )
                vacancy_employee_updates[application["Vacancy_Key"]] = (
                    int(internal_employee_key)
                )
                next_employment_key += 1
                role_counts[role_key] = role_counts.get(role_key, 0) + 1
                if backfill_request:
                    previous_role_key = backfill_request["Role_Key"]
                    role_counts[previous_role_key] = max(
                        0, role_counts.get(previous_role_key, 0) - 1
                    )
                continue

            employee_obj = self.employee_factory.create(
                emp_key=next_employee_key,
                role_row=role_row,
                role_name=role_name,
                department_name=department_name,
                today=today,
                state=state,
                employment_start_date=today
            )
            employee_obj.hire_source_key = application["HireSource_Key"]
            employee_obj.performance = self._initial_performance_from_candidate(
                employee_obj.performance,
                application.get("Candidate_Quality")
            )

            # The candidate was already screened on a specific education and
            # relevant-experience profile before the offer. That profile must
            # land unchanged on the hire; regenerating it here would make the
            # preceding eligibility screen meaningless.
            profile_education_key = application.get("Education_Key")
            if profile_education_key is not None and pd.notna(profile_education_key):
                employee_obj.education_key = int(profile_education_key)

            profile_experience = application.get("Relevante_Ervaring_Jaren")
            relevant_experience_at_start = (
                float(profile_experience)
                if profile_experience is not None and pd.notna(profile_experience)
                else initial_relevant_experience(
                    employee_obj.person.birth_date, today, self.rng
                )
            )

            new_qualifications.append(build_record(
                self.schema,
                "fact_employee_qualification",
                {
                    "EmployeeQualification_Key": next_qualification_key,
                    "Employee_Key": employee_obj.employee_key,
                    "Education_Key": employee_obj.education_key,
                    "Behaald_Datum": today,
                    "Verkregen_Tijdens_Dienstverband": False,
                }
            ))
            next_qualification_key += 1

            new_employees.append(
                build_record(
                    self.schema,
                    "dim_employee",
                    {
                        "Employee_Key": employee_obj.employee_key,
                        "Voornaam": employee_obj.person.first_name,
                        "Achternaam": employee_obj.person.last_name,
                        "Gender": employee_obj.person.gender,
                        **avatar_fields(
                            self.config,
                            employee_obj.employee_key,
                            employee_obj.person.gender,
                            self.avatar_assigner,
                        ),
                        "Geboortedatum": employee_obj.person.birth_date,
                        "Land": employee_obj.person.country,
                        "HireSource_Key": employee_obj.hire_source_key,
                        "Education_Key": employee_obj.education_key,
                        "Location_Key": employee_obj.location_key,
                        "Bijzondere_Aanstelling": employee_obj.bijzondere_aanstelling,
                        "Manager_Key": employee_obj.manager_key,
                        "Performance_Score": employee_obj.performance,
                        "Initial_Performance_Score": employee_obj.performance,
                        "Eerste_Indienst_Datum": today,
                        "Aaneengesloten_Indienst_Datum": today,
                        "Datum_uitdienst": None,
                        "In_Dienst": True
                    }
                )
            )

            new_employments.append(
                build_record(
                    self.schema,
                    "fact_employment",
                    {
                        "Employment_Key": next_employment_key,
                        "Previous_Employment_Key": None,
                        "Employee_Key": employee_obj.employee_key,
                        "HireSource_Key": employee_obj.hire_source_key,
                        "Role_Key": employee_obj.job.role_key,
                        "Location_Key": employee_obj.location_key,
                        "Shift_Key": employee_obj.job.ploegendienst_key,
                        "SalaryScale_Key": role_row["SalaryScale_Key"],
                        "Target_Compa_Ratio": employee_obj.job.target_compa_ratio,
                        "Relevante_Ervaring_Jaren_Bij_Start": relevant_experience_at_start,
                        "Startdatum": today,
                        "Einddatum": None,
                        "Dienstverband_status": "Actief",
                        "Salaris": employee_obj.job.salary,
                        "Contracttype": employee_obj.contract.contract_type,
                        "Contracturen": employee_obj.contract.hours,
                        "Contract_einddatum": employee_obj.contract.end_date,
                        "Contract_ronde": employee_obj.contract.contract_round,
                        "EventType_Key": self.event_type_map["Aangenomen"],
                        "DepartureReason_Key": None,
                        "Tevredenheid_Score_Bij_Uitdienst": None,
                        "SatisfactionBand_Key_Bij_Uitdienst": None,
                    }
                )
            )

            latest_hires.append({
                "Employee_Key": employee_obj.employee_key,
                "Role_Key": employee_obj.job.role_key,
                "Department_Key": role_row["Department_Key"],
                "HireSource_Key": employee_obj.hire_source_key,
                "Vacancy_Key": application["Vacancy_Key"],
                "Vacancy_Reason": application["Vacancy_Reason"]
            })
            recruitment_employee_updates[application["Recruitment_Key"]] = (
                employee_obj.employee_key
            )
            vacancy_employee_updates[application["Vacancy_Key"]] = (
                employee_obj.employee_key
            )

            next_employee_key += 1
            next_employment_key += 1
            role_counts[role_key] = role_counts.get(role_key, 0) + 1

        state["dim_employee"] = pd.concat(
            [dim_employee, pd.DataFrame(new_employees)],
            ignore_index=True
        )
        state["fact_employment"] = pd.concat(
            [fact_employment, pd.DataFrame(new_employments)],
            ignore_index=True
        )
        if new_qualifications:
            state["fact_employee_qualification"] = pd.concat(
                [fact_qualification, pd.DataFrame(new_qualifications)],
                ignore_index=True
            )

        self._mark_recruitment_as_hired(state, recruitment_employee_updates)
        self._close_filled_vacancies(state, vacancy_employee_updates, today)

        state["dim_employee"] = assign_managers(
            state["dim_employee"],
            state["fact_employment"],
            state["dim_role"],
            self.rng,
            staffing_rules=self.config.staffing
        )
        state["vacancies"] = self._open_vacancy_count(state)
        state["_latest_hires"] = latest_hires
        state.pop("_accepted_applications", None)
        return state

    def _move_internal_employee(
        self,
        state,
        employee_key,
        target_role,
        today,
        employment_key
    ):
        """Close an employee's current record and create a career event.

        An internal move fills a recruitment vacancy, but must never create a
        second person. The original hire source remains immutable on the
        employment history; the recruitment fact records internal mobility as
        the source that filled this specific vacancy.
        """
        employment = state["fact_employment"]
        active_rows = employment[
            (employment["Employee_Key"] == employee_key)
            & (employment["Dienstverband_status"] == "Actief")
        ]
        if active_rows.empty:
            return None, None

        previous_index = active_rows.index[0]
        previous = active_rows.iloc[0]
        previous_role = self._role_row(state, previous["Role_Key"])
        salary_policy = SalaryPolicy(self.config, state["dim_salary_scale"])
        service_start = state["dim_employee"].loc[
            state["dim_employee"]["Employee_Key"] == employee_key,
            "Aaneengesloten_Indienst_Datum"
        ].iloc[0]
        previous_ratio = pd.to_numeric(
            previous.get("Target_Compa_Ratio"),
            errors="coerce"
        )
        if pd.isna(previous_ratio):
            previous_benchmark = salary_policy.employee_benchmark(
                previous_role,
                today,
                service_start
            )["Benchmark_Salaris"]
            previous_ratio = int(previous["Salaris"]) / previous_benchmark

        is_promotion = target_role["Role_Name"] in self.config.role_career_paths.get(
            previous_role["Role_Name"], {}
        ).get("logische_doorgroei", [])
        target_ratio = salary_policy.clamp_ratio(
            float(previous_ratio) + (0.02 if is_promotion else 0.0)
        )
        benchmark = salary_policy.employee_benchmark(
            target_role,
            today,
            service_start
        )

        employment.loc[previous_index, "Einddatum"] = today
        employment.loc[previous_index, "Dienstverband_status"] = "Inactief"
        event_name = "Promotie" if is_promotion else "Transfer"
        event_key = self.event_type_map[event_name]
        new_location_key = resolve_location(
            state,
            self.config,
            self.rng,
            target_role.get("Department_Name"),
            target_role["Role_Name"],
            preferred_location_key=previous["Location_Key"],
        )
        new_record = build_record(
            self.schema,
            "fact_employment",
            {
                "Employment_Key": employment_key,
                "Previous_Employment_Key": previous["Employment_Key"],
                "Employee_Key": employee_key,
                "HireSource_Key": previous.get("HireSource_Key"),
                "Role_Key": target_role["Role_Key"],
                "Location_Key": new_location_key,
                "Shift_Key": assign_ploegendienst_key(
                    target_role,
                    state,
                    self.config,
                    self.rng
                ),
                "SalaryScale_Key": target_role["SalaryScale_Key"],
                "Target_Compa_Ratio": target_ratio,
                "Relevante_Ervaring_Jaren_Bij_Start": carried_experience(
                    previous,
                    today,
                    previous_role["Department_Key"] == target_role["Department_Key"],
                    self.config,
                ),
                "Startdatum": today,
                "Einddatum": None,
                "Dienstverband_status": "Actief",
                "Salaris": int(round(
                    benchmark["Benchmark_Salaris"] * target_ratio
                )),
                "Contracttype": previous["Contracttype"],
                "Contracturen": previous.get("Contracturen"),
                "Contract_einddatum": previous.get("Contract_einddatum"),
                "Contract_ronde": previous.get("Contract_ronde"),
                "EventType_Key": event_key,
                "DepartureReason_Key": None,
                "Tevredenheid_Score_Bij_Uitdienst": None,
                "SatisfactionBand_Key_Bij_Uitdienst": None,
                "Betrokkenheid_Score_Bij_Uitdienst": None,
                "EngagementBand_Key_Bij_Uitdienst": None,
            }
        )
        backfill_request = {
            "Role_Key": previous["Role_Key"],
            "Department_Key": previous_role["Department_Key"],
            "Vacancy_Reason": "Internal mobility backfill"
        }
        return new_record, backfill_request

    @staticmethod
    def _initial_performance_from_candidate(factory_score, candidate_quality):
        """Blend selection quality into a new hire without making it destiny."""
        quality = pd.to_numeric(candidate_quality, errors="coerce")
        if pd.isna(quality):
            return factory_score
        return round(max(0, min(5, 0.7 * float(factory_score) + 0.3 * quality)), 2)

    def _mark_recruitment_as_hired(self, state, recruitment_employee_updates):
        recruitment = state.get("fact_recruitment", pd.DataFrame())
        if recruitment.empty:
            return

        for recruitment_key, employee_key in recruitment_employee_updates.items():
            recruitment.loc[
                recruitment["Recruitment_Key"] == recruitment_key,
                "Employee_Key"
            ] = employee_key

        state["fact_recruitment"] = recruitment

    def _close_filled_vacancies(self, state, vacancy_employee_updates, today):
        vacancy = state.get("fact_vacancy", pd.DataFrame())
        if vacancy.empty:
            return

        for vacancy_key, employee_key in vacancy_employee_updates.items():
            mask = vacancy["Vacancy_Key"] == vacancy_key
            vacancy.loc[mask, "Status"] = "Closed"
            vacancy.loc[mask, "Closed_Date"] = today
            vacancy.loc[mask, "Filled_Employee_Key"] = employee_key

        state["fact_vacancy"] = vacancy

    def _open_vacancy_count(self, state):
        vacancy = state.get("fact_vacancy", pd.DataFrame())
        if vacancy.empty or "Status" not in vacancy.columns:
            return 0
        return int((vacancy["Status"] == "Open").sum())

    def _active_role_counts(self, state):
        active = state["fact_employment"][
            state["fact_employment"]["Dienstverband_status"] == "Actief"
        ]
        return active["Role_Key"].value_counts().to_dict()

    def _has_capacity_for_hire(self, state, department_name, role_name, role_counts, role_key):
        capacity = effective_role_capacity(state, self.config, department_name, role_name)
        return capacity is None or role_counts.get(role_key, 0) < capacity

    def _close_vacancy_without_hire(self, state, vacancy_key, today):
        vacancy = state.get("fact_vacancy", pd.DataFrame())
        if not vacancy.empty:
            mask = vacancy["Vacancy_Key"] == vacancy_key
            vacancy.loc[mask, "Status"] = "Closed"
            vacancy.loc[mask, "Closed_Date"] = today
            state["fact_vacancy"] = vacancy
        self._close_out_remaining_pipeline(state, vacancy_key, today)

    def _close_out_remaining_pipeline(self, state, vacancy_key, today):
        """Closing a vacancy this way leaves any other in-progress pipeline
        applications for it (e.g. someone else still sitting in Gesprek)
        with nowhere to go - without this they'd stay "In behandeling"
        forever, since a closed vacancy is never visited again."""
        fact_recruitment = state.get("fact_recruitment", pd.DataFrame())
        if fact_recruitment.empty or "Status" not in fact_recruitment.columns:
            return
        pipeline = fact_recruitment[
            (fact_recruitment["Vacancy_Key"] == vacancy_key)
            & (fact_recruitment["Status"] == RecruitmentSimulator.IN_PROGRESS_STATUS)
        ]
        if pipeline.empty:
            return
        rejection_reason_keys = self._reason_lookup(
            state, "dim_rejection_reason", "RejectionReason_Name", "RejectionReason_Key"
        )
        status_keys = self._reason_lookup(
            state, "dim_recruitment_status", "Status_Name", "RecruitmentStatus_Key"
        )
        for idx in pipeline.index:
            fact_recruitment.loc[idx, "Status"] = RecruitmentSimulator.REJECTED_STATUS
            fact_recruitment.loc[idx, "RecruitmentStatus_Key"] = status_keys.get(
                RecruitmentSimulator.REJECTED_STATUS
            )
            fact_recruitment.loc[idx, "Decision_Date"] = today
            fact_recruitment.loc[idx, "RejectionReason_Key"] = rejection_reason_keys.get(
                NOT_SELECTED_REASON
            )
        state["fact_recruitment"] = fact_recruitment

    def _reason_lookup(self, state, table, name_column, key_column):
        rows = state.get(table, pd.DataFrame())
        if rows.empty or not {name_column, key_column}.issubset(rows.columns):
            return {}
        return dict(zip(rows[name_column], rows[key_column]))

    def _role_row(self, state, role_key):
        return state["dim_role"].loc[
            state["dim_role"]["Role_Key"] == role_key
        ].iloc[0]

    def _department_name(self, state, department_key):
        return state["dim_department"].loc[
            state["dim_department"]["Department_Key"] == department_key,
            "Department_Name"
        ].iloc[0]


def simulate_hiring(state, sector_config, schema, today, rng, event_type_map):
    return HiringSimulator(sector_config, schema, rng, event_type_map).run(state, today)
