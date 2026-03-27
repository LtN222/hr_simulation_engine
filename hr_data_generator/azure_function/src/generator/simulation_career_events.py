import pandas as pd


def simulate_career_events(
    state,
    config,
    schema,
    today,
    rng,
    event_type_map,
    promotion_rate,
    transfer_rate
):
    dim_role = state["dim_role"]
    dim_employee = state["dim_employee"]
    dim_department = state["dim_department"]
    fact_employment = state["fact_employment"]

    active = fact_employment[
        fact_employment["Dienstverband_status"] == "Actief"
    ]

    # lookup helpers
    role_lookup = dim_role.set_index("Role_Key")
    dept_lookup = dim_department.set_index("Department_Key")

    # 🔗 definieer logische transfers (simpel maar effectief)
    allowed_transfers = {
        "Productie": ["Techniek", "Logistiek"],
        "Techniek": ["Productie", "R&D"],
        "Logistiek": ["Productie"],
        "Kwaliteit": ["Productie", "R&D"],
        "R&D": ["Techniek", "Kwaliteit", "IT"],
        "IT": ["Finance", "R&D"],
        "Finance": ["Sales", "HR"],
        "HR": ["Finance", "Sales"],
        "Sales": ["Finance", "HR"],
        "Directie": []  # geen transfers omhoog
    }

    new_records = []
    next_key = fact_employment["Employment_Key"].max() + 1

    for idx, row in active.iterrows():

        employee_key = row["Employee_Key"]
        role_key = row["Role_Key"]

        role = role_lookup.loc[role_key]
        dept_key = role["Department_Key"]
        dept_name = dept_lookup.loc[dept_key]["Department_Name"]

        current_salary = row["Salaris"]

        # performance ophalen
        performance = dim_employee.loc[
            dim_employee["Employee_Key"] == employee_key,
            "Performance_Score"
        ].values[0]

        # -------------------------------------------------
        # 🎯 PROMOTIE (binnen afdeling)
        # -------------------------------------------------

        # performance multiplier
        perf_factor = 1.0
        if performance >= 4:
            perf_factor = 1.8
        elif performance >= 3.5:
            perf_factor = 1.3
        elif performance < 2.5:
            perf_factor = 0.5

        promotion_prob = (promotion_rate / 52) * perf_factor

        if rng.random() < promotion_prob:

            # alleen binnen dezelfde afdeling
            dept_roles = dim_role[
                dim_role["Department_Key"] == dept_key
            ]

            # alleen rollen met hogere salarisband
            possible_roles = dept_roles[
                dept_roles["Salaris_min"] > role["Salaris_min"]
            ]

            if len(possible_roles) > 0:

                new_role_row = possible_roles.sample(
                    n=1,
                    random_state=rng.randint(0, 100000)
                ).iloc[0]

                new_role_key = new_role_row["Role_Key"]

                # huidige employment afsluiten
                fact_employment.loc[idx, "Einddatum"] = today
                fact_employment.loc[idx, "Dienstverband_status"] = "Inactief"

                # salaris sprong binnen nieuwe band
                new_salary = int(
                    rng.uniform(
                        new_role_row["Salaris_min"],
                        new_role_row["Salaris_max"]
                    )
                )

                new_records.append({
                    "Employment_Key": next_key,
                    "Previous_Employment_Key": row["Employment_Key"],
                    "Employee_Key": employee_key,
                    "Role_Key": new_role_key,
                    "Location_Key": row["Location_Key"],
                    "Startdatum": today,
                    "Einddatum": None,
                    "Dienstverband_status": "Actief",
                    "Salaris": new_salary,
                    "Contracttype": row["Contracttype"],
                    "Contracturen": row.get("Contracturen"),
                    "EventType_Key": event_type_map["Promotie"],
                    "RedenVertrek_Key": None
                })

                next_key += 1
                continue

        # -------------------------------------------------
        # 🔁 TRANSFER (tussen afdelingen)
        # -------------------------------------------------

        transfer_prob = transfer_rate / 52

        if rng.random() < transfer_prob:

            possible_depts = allowed_transfers.get(dept_name, [])

            if not possible_depts:
                continue

            target_dept = rng.choice(possible_depts)

            target_dept_key = dim_department.loc[
                dim_department["Department_Name"] == target_dept,
                "Department_Key"
            ].values[0]

            # kies rol met vergelijkbare salary range
            candidate_roles = dim_role[
                dim_role["Department_Key"] == target_dept_key
            ]

            candidate_roles = candidate_roles[
                (candidate_roles["Salaris_min"] <= role["Salaris_max"] * 1.2) &
                (candidate_roles["Salaris_max"] >= role["Salaris_min"] * 0.8)
            ]

            if len(candidate_roles) == 0:
                continue

            new_role_row = candidate_roles.sample(
                n=1,
                random_state=rng.randint(0, 100000)
            ).iloc[0]

            # huidige afsluiten
            fact_employment.loc[idx, "Einddatum"] = today
            fact_employment.loc[idx, "Dienstverband_status"] = "Inactief"

            new_records.append({
                "Employment_Key": next_key,
                "Previous_Employment_Key": row["Employment_Key"],
                "Employee_Key": employee_key,
                "Role_Key": new_role_row["Role_Key"],
                "Location_Key": row["Location_Key"],
                "Startdatum": today,
                "Einddatum": None,
                "Dienstverband_status": "Actief",
                "Salaris": row["Salaris"],
                "Contracttype": row["Contracttype"],
                "Contracturen": row.get("Contracturen"),
                "EventType_Key": event_type_map["Transfer"],
                "RedenVertrek_Key": None
            })

            next_key += 1

    if new_records:
        state["fact_employment"] = pd.concat(
            [fact_employment, pd.DataFrame(new_records)],
            ignore_index=True
        )

    return state