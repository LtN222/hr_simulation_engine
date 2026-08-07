import pandas as pd

from src.generator.employee_attributes import generate_employment_attributes
from src.generator.employee_factory import EmployeeFactory
from src.infrastructure.manager_builder import assign_managers
from src.infrastructure.record_builder import build_record


class HiringSimulator:
    """Convert accepted applications into employees and close vacancies."""

    def __init__(self, config, schema, rng, event_type_map):
        self.config = config
        self.schema = schema
        self.rng = rng
        self.event_type_map = event_type_map
        self.employee_factory = EmployeeFactory(config, rng)

    def run(self, state, today):
        accepted_applications = state.get("_accepted_applications", [])

        if not accepted_applications:
            state["_latest_hires"] = []
            state["vacancies"] = self._open_vacancy_count(state)
            return state

        dim_employee = state["dim_employee"]
        fact_employment = state["fact_employment"]
        fact_employment_attribute = state["fact_employment_attribute"]

        next_employee_key = int(dim_employee["Employee_Key"].max()) + 1
        next_employment_key = int(fact_employment["Employment_Key"].max()) + 1

        new_employees = []
        new_employments = []
        new_attributes = []
        latest_hires = []
        recruitment_employee_updates = {}
        vacancy_employee_updates = {}

        for application in accepted_applications:
            role_row = self._role_row(state, application["Role_Key"])
            department_name = self._department_name(
                state,
                application["Department_Key"]
            )
            role_name = role_row["Role_Name"]

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

            new_employees.append(
                build_record(
                    self.schema,
                    "dim_employee",
                    {
                        "Employee_Key": employee_obj.employee_key,
                        "Voornaam": employee_obj.person.first_name,
                        "Achternaam": employee_obj.person.last_name,
                        "Gender": employee_obj.person.gender,
                        "Geboortedatum": employee_obj.person.birth_date,
                        "Land": employee_obj.person.country,
                        "HireSource_Key": employee_obj.hire_source_key,
                        "EducationLevel_Key": employee_obj.education_key,
                        "Location_Key": employee_obj.location_key,
                        "Bijzondere_Aanstelling": employee_obj.bijzondere_aanstelling,
                        "Manager_Key": employee_obj.manager_key,
                        "Performance_Score": employee_obj.performance,
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
                        "Role_Key": employee_obj.job.role_key,
                        "Location_Key": employee_obj.location_key,
                        "Startdatum": today,
                        "Einddatum": None,
                        "Dienstverband_status": "Actief",
                        "Salaris": employee_obj.job.salary,
                        "Contracttype": employee_obj.contract.contract_type,
                        "Contracturen": employee_obj.contract.hours,
                        "Contract_einddatum": employee_obj.contract.end_date,
                        "Contract_ronde": employee_obj.contract.contract_round,
                        "EventType_Key": self.event_type_map["Aangenomen"],
                        "RedenVertrek_Key": None
                    }
                )
            )

            for attr in generate_employment_attributes(
                next_employment_key,
                role_row,
                self.config.employment_attributes,
                self.rng
            ):
                new_attributes.append(
                    build_record(self.schema, "fact_employment_attribute", attr)
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

        state["dim_employee"] = pd.concat(
            [dim_employee, pd.DataFrame(new_employees)],
            ignore_index=True
        )
        state["fact_employment"] = pd.concat(
            [fact_employment, pd.DataFrame(new_employments)],
            ignore_index=True
        )

        if new_attributes:
            state["fact_employment_attribute"] = pd.concat(
                [fact_employment_attribute, pd.DataFrame(new_attributes)],
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
