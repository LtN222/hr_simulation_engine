import pandas as pd

from src.generator.employee_attributes import generate_employment_attributes
from src.generator.employee_factory import EmployeeFactory
from src.infrastructure.record_builder import build_record


class HiringSimulator:
    """Fill open vacancies and add the resulting employees to HR state."""

    def __init__(self, config, schema, rng, event_type_map):
        self.config = config
        self.schema = schema
        self.rng = rng
        self.event_type_map = event_type_map
        self.employee_factory = EmployeeFactory(config, rng)

    def run(self, state, today):
        vacancies = int(state.get("vacancies", 0))

        if vacancies <= 0:
            state["_latest_hires"] = []
            return state

        fill_rate = self.rng.uniform(0.2, 0.6)
        hires_this_week = min(vacancies, max(1, int(vacancies * fill_rate)))

        dim_employee = state["dim_employee"]
        fact_employment = state["fact_employment"]
        fact_employment_attribute = state["fact_employment_attribute"]

        next_employee_key = int(dim_employee["Employee_Key"].max()) + 1
        next_employment_key = int(fact_employment["Employment_Key"].max()) + 1

        new_employees = []
        new_employments = []
        new_attributes = []
        latest_hires = []

        for vacancy_reason in self._vacancy_reasons(state, hires_this_week):
            role_row = self._choose_role_for_vacancy(state)
            department_name = self._department_name_for_role(state, role_row)
            role_name = role_row["Role_Name"]

            employee_obj = self.employee_factory.create(
                emp_key=next_employee_key,
                role_row=role_row,
                role_name=role_name,
                department_name=department_name,
                today=today,
                state=state
            )

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
                        "Leeftijd": employee_obj.person.age(today),
                        "Land": employee_obj.person.country,
                        "HireSource_Key": employee_obj.hire_source_key,
                        "EducationLevel_Key": employee_obj.education_key,
                        "Location_Key": employee_obj.location_key,
                        "Bijzondere_Aanstelling": employee_obj.bijzondere_aanstelling,
                        "Manager_Key": employee_obj.manager_key,
                        "Performance_Score": employee_obj.performance
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

            latest_hires.append(
                {
                    "Employee_Key": employee_obj.employee_key,
                    "Role_Key": employee_obj.job.role_key,
                    "Department_Key": role_row["Department_Key"],
                    "HireSource_Key": employee_obj.hire_source_key,
                    "Vacancy_Reason": vacancy_reason
                }
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

        state["vacancies"] = vacancies - hires_this_week
        state["_latest_hires"] = latest_hires
        return state

    def _vacancy_reasons(self, state, hires_this_week):
        replacement_count = min(hires_this_week, int(state.get("_attrition_vacancies", 0)))
        return (
            ["Replacement"] * replacement_count
            + ["Growth"] * (hires_this_week - replacement_count)
        )

    def _choose_role_for_vacancy(self, state):
        dim_role = state["dim_role"]
        active = state["fact_employment"][
            state["fact_employment"]["Dienstverband_status"] == "Actief"
        ]

        role_counts = active["Role_Key"].value_counts().to_dict()

        weighted_roles = []
        weights = []
        for _, role in dim_role.iterrows():
            target_ratio = self._target_ratio_for_role(state, role)
            current_count = role_counts.get(role["Role_Key"], 0)
            gap_weight = max(0.2, target_ratio * 100 - current_count)
            weighted_roles.append(role)
            weights.append(gap_weight)

        return self.rng.choices(weighted_roles, weights=weights)[0]

    def _target_ratio_for_role(self, state, role_row):
        department_name = self._department_name_for_role(state, role_row)
        role_name = role_row["Role_Name"]
        return self.config.structure[department_name][role_name].get("fte_ratio", 0.01)

    def _department_name_for_role(self, state, role_row):
        department = state["dim_department"].loc[
            state["dim_department"]["Department_Key"] == role_row["Department_Key"]
        ].iloc[0]
        return department["Department_Name"]


def simulate_hiring(state, sector_config, schema, today, rng, event_type_map):
    return HiringSimulator(sector_config, schema, rng, event_type_map).run(state, today)
