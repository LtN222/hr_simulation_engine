import pandas as pd

from src.generator.employee_person import (
    choose_gender_and_name,
    generate_age,
    choose_special_arrangement
)

from src.generator.employee_job import (
    choose_salary,
    choose_performance
)

from src.generator.employee_contract import (
    choose_contract,
    choose_contract_hours
)

from src.generator.employee_helpers import (
    choose_hire_source,
    choose_education,
    choose_location
)

from src.generator.employee_attributes import (
    generate_employment_attributes
)

from src.generator.record_builder import build_record


# =====================================================
# Employee generation orchestrator
# =====================================================

def generate_employees(state, config, schema, rng, today):

    # =====================================================
    # 1️⃣ Input data ophalen
    # =====================================================

    dim_role = state["dim_role"]
    dim_hire_source = state["dim_hire_source"]
    dim_education_level = state["dim_education_level"]
    dim_location = state["dim_location"]

    contract_rules = config["contract_rules"]

    employment_attributes_config = config.get(
        "employment_attributes", {}
    )

    special_arrangements_config = config.get(
        "special_arrangements", {}
    )

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
    employment_attributes = []

    # =====================================================
    # 2️⃣ Primary key startwaarden bepalen
    # =====================================================

    if "dim_employee" in state and not state["dim_employee"].empty:
        emp_key = state["dim_employee"]["Employee_Key"].max() + 1
    else:
        emp_key = 1

    if "fact_employment" in state and not state["fact_employment"].empty:
        employment_key = state["fact_employment"]["Employment_Key"].max() + 1
    else:
        employment_key = 1

    # =====================================================
    # 3️⃣ Employees genereren
    # =====================================================

    for allocation in role_allocations:

        role_row = dim_role.loc[
            dim_role["Role_Name"] == allocation["Role_Name"]
        ].iloc[0]

        role_key = role_row["Role_Key"]
        role_name = role_row["Role_Name"]

        afdeling_rules = contract_rules.get(
            allocation["Department_Name"],
            contract_rules.get("default")
        )

        for _ in range(allocation["count"]):

            gender, voornaam, achternaam = choose_gender_and_name(rng)

            leeftijd, geboortedatum = generate_age(today, rng)

            bijzondere_aanstelling, land, voornaam, achternaam = (
                choose_special_arrangement(
                    role_name,
                    special_arrangements_config,
                    rng,
                    voornaam,
                    achternaam
                )
            )

            salaris = choose_salary(role_row, rng)
            performance = choose_performance(rng)

            startdatum = today - pd.DateOffset(
                days=rng.randint(0, 5 * 365)
            )

            contract_type, contract_einddatum, contract_ronde = (
                choose_contract(
                    startdatum,
                    today,
                    afdeling_rules,
                    rng
                )
            )

            contract_hours = choose_contract_hours(
                role_name,
                config,
                rng
            )

            hire_source_key = choose_hire_source(
                dim_hire_source,
                rng
            )

            education_key = choose_education(
                role_name,
                config,
                dim_education_level,
                rng
            )

            location_key = choose_location(
                dim_location,
                config,
                rng
            )

            employees.append(

                build_record(
                    schema,
                    "dim_employee",
                    {
                        "Employee_Key": emp_key,
                        "Voornaam": voornaam,
                        "Achternaam": achternaam,
                        "Gender": gender,
                        "Geboortedatum": geboortedatum,
                        "Leeftijd": leeftijd,
                        "Land": land,
                        "HireSource_Key": hire_source_key,
                        "EducationLevel_Key": education_key,
                        "Location_Key": location_key,
                        "Bijzondere_Aanstelling": bijzondere_aanstelling,
                        "Manager_Key": None,
                        "Performance_Score": performance
                    }
                )

            )

            employment.append(

                build_record(
                    schema,
                    "fact_employment",
                    {
                        "Employment_Key": employment_key,
                        "Previous_Employment_Key": None,
                        "Employee_Key": emp_key,
                        "Role_Key": role_key,
                        "Location_Key": location_key,
                        "Startdatum": startdatum,
                        "Einddatum": None,
                        "Dienstverband_status": "Actief",
                        "Salaris": salaris,
                        "Contracttype": contract_type,
                        "Contracturen": contract_hours,
                        "Contract_einddatum": contract_einddatum,
                        "Contract_ronde": contract_ronde,
                        "EventType_Key": event_type_map.get("Aangenomen"),
                        "RedenVertrek_Key": None
                    }
                )

            )

            attrs = generate_employment_attributes(
                employment_key,
                role_row,
                employment_attributes_config,
                rng
            )

            for attr in attrs:

                employment_attributes.append(
                    build_record(
                        schema,
                        "fact_employment_attribute",
                        attr
                    )
                )

            emp_key += 1
            employment_key += 1

    # =====================================================
    # 4️⃣ DataFrames bouwen
    # =====================================================

    dim_employee_df = pd.DataFrame(employees)
    fact_employment_df = pd.DataFrame(employment)
    fact_employment_attribute_df = pd.DataFrame(employment_attributes)

    # =====================================================
    # 5️⃣ Manager hiërarchie
    # =====================================================

    emp_roles = fact_employment_df.merge(
        dim_role[["Role_Key", "Department_Key", "Leidinggevend"]],
        on="Role_Key",
        how="left"
    )

    top_role = dim_role.sort_values(
        "Salaris_max",
        ascending=False
    ).iloc[0]

    ceo_candidates = emp_roles[
        emp_roles["Role_Key"] == top_role["Role_Key"]
    ]

    if len(ceo_candidates) > 0:

        ceo_key = ceo_candidates.iloc[0]["Employee_Key"]

        dim_employee_df.loc[
            dim_employee_df["Employee_Key"] == ceo_key,
            "Manager_Key"
        ] = None

    else:
        ceo_key = None

    managers = emp_roles[
        emp_roles["Leidinggevend"] == True
    ]

    for _, emp in emp_roles.iterrows():

        emp_key_val = emp["Employee_Key"]

        if emp_key_val == ceo_key:
            continue

        dept = emp["Department_Key"]

        dept_managers = managers[
            managers["Department_Key"] == dept
        ]

        dept_managers = dept_managers[
            dept_managers["Employee_Key"] != emp_key_val
        ]

        if ceo_key is not None:

            dept_managers = dept_managers[
                dept_managers["Employee_Key"] != ceo_key
            ]

        if len(dept_managers) == 0:
            continue

        manager_key = rng.choice(
            dept_managers["Employee_Key"].tolist()
        )

        dim_employee_df.loc[
            dim_employee_df["Employee_Key"] == emp_key_val,
            "Manager_Key"
        ] = manager_key

    # =====================================================
    # 6️⃣ Resultaat opslaan
    # =====================================================

    state["dim_employee"] = dim_employee_df
    state["fact_employment"] = fact_employment_df
    state["fact_employment_attribute"] = fact_employment_attribute_df

    return state