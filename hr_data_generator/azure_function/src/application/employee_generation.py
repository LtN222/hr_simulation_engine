import pandas as pd

from src.generator.employee_factory import EmployeeFactory
from src.infrastructure.record_builder import build_record
from src.infrastructure.manager_builder import assign_managers
from src.infrastructure.avatar import AvatarAssigner, avatar_fields
from src.infrastructure.relevant_experience import initial_relevant_experience


# =====================================================
# 🔹 Helpers
# =====================================================

def _get_start_keys(state):

    if "dim_employee" in state and not state["dim_employee"].empty:
        emp_key = state["dim_employee"]["Employee_Key"].max() + 1
    else:
        emp_key = 1

    if "fact_employment" in state and not state["fact_employment"].empty:
        employment_key = state["fact_employment"]["Employment_Key"].max() + 1
    else:
        employment_key = 1

    return emp_key, employment_key


def _generate_employee_records(
    state,
    config,
    schema,
    rng,
    today
):

    dim_role = state["dim_role"]
    role_allocations = state["role_allocations"]
    dim_event_type = state["dim_event_type"]

    event_type_map = dict(
        zip(
            dim_event_type["EventType"],
            dim_event_type["EventType_Key"]
        )
    )

    employees = []
    employment = []
    qualifications = []

    emp_key, employment_key = _get_start_keys(state)

    factory = EmployeeFactory(config, rng)
    avatar_assigner = AvatarAssigner(config)

    for allocation in role_allocations:

        role_row = dim_role.loc[
            dim_role["Role_Name"] == allocation["Role_Name"]
        ].iloc[0]

        role_name = role_row["Role_Name"]

        for _ in range(allocation["count"]):

            employee_obj = factory.create(
                emp_key=emp_key,
                role_row=role_row,
                role_name=role_name,
                department_name=allocation["Department_Name"],
                today=today,
                state=state
            )

            # 🔹 dim_employee
            employees.append(
                build_record(
                    schema,
                    "dim_employee",
                    {
                        "Employee_Key": employee_obj.employee_key,
                        "Voornaam": employee_obj.person.first_name,
                        "Achternaam": employee_obj.person.last_name,
                        "Gender": employee_obj.person.gender,
                        **avatar_fields(
                            config,
                            employee_obj.employee_key,
                            employee_obj.person.gender,
                            avatar_assigner,
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
                        "Eerste_Indienst_Datum": employee_obj.contract.start_date,
                        "Aaneengesloten_Indienst_Datum": employee_obj.contract.start_date,
                        "Datum_uitdienst": None,
                        "In_Dienst": True
                    }
                )
            )

            # 🔹 fact_employment
            employment.append(
                build_record(
                    schema,
                    "fact_employment",
                    {
                        "Employment_Key": employment_key,
                        "Previous_Employment_Key": None,
                        "Employee_Key": employee_obj.employee_key,
                        "HireSource_Key": employee_obj.hire_source_key,
                        "Role_Key": employee_obj.job.role_key,
                        "Location_Key": employee_obj.location_key,
                        "Shift_Key": employee_obj.job.ploegendienst_key,
                        "SalaryScale_Key": role_row["SalaryScale_Key"],
                        "Target_Compa_Ratio": employee_obj.job.target_compa_ratio,
                        "Relevante_Ervaring_Jaren_Bij_Start": initial_relevant_experience(
                            employee_obj.person.birth_date,
                            employee_obj.contract.start_date,
                            rng,
                        ),
                        "Startdatum": employee_obj.contract.start_date,
                        "Einddatum": None,
                        "Dienstverband_status": "Actief",
                        "Salaris": employee_obj.job.salary,
                        "Contracttype": employee_obj.contract.contract_type,
                        "Contracturen": employee_obj.contract.hours,
                        "Contract_einddatum": employee_obj.contract.end_date,
                        "Contract_ronde": employee_obj.contract.contract_round,
                        "EventType_Key": event_type_map.get("Aangenomen"),
                        "DepartureReason_Key": None,
                        "Tevredenheid_Score_Bij_Uitdienst": None,
                        "SatisfactionBand_Key_Bij_Uitdienst": None,
                    }
                )
            )
            qualifications.append(build_record(schema, "fact_employee_qualification", {
                "EmployeeQualification_Key": len(qualifications) + 1,
                "Employee_Key": employee_obj.employee_key,
                "Education_Key": employee_obj.education_key,
                "Behaald_Datum": employee_obj.contract.start_date,
                "Verkregen_Tijdens_Dienstverband": False,
            }))

            # 🔹 attributes
            emp_key += 1
            employment_key += 1

    return employees, employment, qualifications


# =====================================================
# 🔹 Public API
# =====================================================

def generate_employees(state, config, schema, rng, today):

    employees, employment, qualifications = (
        _generate_employee_records(
            state,
            config,
            schema,
            rng,
            today
        )
    )

    dim_employee_df = pd.DataFrame(employees)
    fact_employment_df = pd.DataFrame(employment)

    # 🔹 manager logica (nu netjes extern)
    dim_employee_df = assign_managers(
        dim_employee_df,
        fact_employment_df,
        state["dim_role"],
        rng,
        staffing_rules=config.staffing
    )

    state["dim_employee"] = dim_employee_df
    state["fact_employment"] = fact_employment_df
    state["fact_employee_qualification"] = pd.DataFrame(qualifications)

    return state
