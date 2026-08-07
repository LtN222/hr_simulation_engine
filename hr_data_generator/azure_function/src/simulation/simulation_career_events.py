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

    fact_employment, salary_next_key = _simulate_salary_reviews(
        fact_employment,
        dim_employee,
        dim_role,
        config,
        today,
        rng,
        event_type_map
    )

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
    next_key = max(int(fact_employment["Employment_Key"].max()) + 1, salary_next_key)

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
                    max(
                        current_salary * 1.08,
                        new_role_row["Salaris_min"]
                    )
                )
                new_salary = min(new_salary, int(new_role_row["Salaris_max"] * 1.05))

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
                    "Contract_einddatum": row.get("Contract_einddatum"),
                    "Contract_ronde": row.get("Contract_ronde"),
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
                "Contract_einddatum": row.get("Contract_einddatum"),
                "Contract_ronde": row.get("Contract_ronde"),
                "EventType_Key": event_type_map["Transfer"],
                "RedenVertrek_Key": None
            })

            next_key += 1

    if new_records:
        fact_employment = pd.concat(
            [fact_employment, pd.DataFrame(new_records)],
            ignore_index=True
        )

    state["fact_employment"] = fact_employment

    return state


def _simulate_salary_reviews(
    fact_employment,
    dim_employee,
    dim_role,
    config,
    today,
    rng,
    event_type_map
):
    salary_event_key = event_type_map.get("Salarisaanpassing")

    if salary_event_key is None:
        return fact_employment, int(fact_employment["Employment_Key"].max()) + 1

    career_cfg = config.get("career_events", {})
    salary_cfg = career_cfg.get("salary_growth", {})
    salary_increase_rate = career_cfg.get("salary_increase_rate", 1.0)

    inflation_min = salary_cfg.get("inflation_min", 0.018)
    inflation_max = salary_cfg.get("inflation_max", 0.035)
    performance_bonus_max = salary_cfg.get("performance_bonus_max", 0.018)
    cap_multiplier = salary_cfg.get("role_band_cap_multiplier", 1.08)

    active = fact_employment[
        fact_employment["Dienstverband_status"] == "Actief"
    ].copy()

    if active.empty:
        return fact_employment, int(fact_employment["Employment_Key"].max()) + 1

    role_lookup = dim_role.set_index("Role_Key")
    performance_lookup = dim_employee.set_index("Employee_Key")["Performance_Score"]
    next_key = int(fact_employment["Employment_Key"].max()) + 1
    new_records = []

    for idx, row in active.iterrows():
        employee_key = int(row["Employee_Key"])

        if today.isocalendar()[1] != _salary_review_week(employee_key):
            continue

        if rng.random() > salary_increase_rate:
            continue

        if pd.Timestamp(row["Startdatum"]).year == today.year:
            continue

        if _already_reviewed_this_year(
            fact_employment,
            employee_key,
            salary_event_key,
            today.year
        ):
            continue

        role = role_lookup.loc[row["Role_Key"]]
        performance = performance_lookup.get(employee_key, 3.0)
        inflation = rng.uniform(inflation_min, inflation_max)
        performance_factor = max(0, min(1, (performance - 3.0) / 2.0))
        raise_pct = inflation + performance_factor * performance_bonus_max
        salary_cap = int(role["Salaris_max"] * cap_multiplier)
        new_salary = min(int(round(row["Salaris"] * (1 + raise_pct))), salary_cap)

        if new_salary <= row["Salaris"]:
            continue

        fact_employment.loc[idx, "Einddatum"] = today
        fact_employment.loc[idx, "Dienstverband_status"] = "Inactief"

        new_records.append({
            "Employment_Key": next_key,
            "Previous_Employment_Key": row["Employment_Key"],
            "Employee_Key": employee_key,
            "Role_Key": row["Role_Key"],
            "Location_Key": row["Location_Key"],
            "Startdatum": today,
            "Einddatum": None,
            "Dienstverband_status": "Actief",
            "Salaris": new_salary,
            "Contracttype": row["Contracttype"],
            "Contracturen": row.get("Contracturen"),
            "Contract_einddatum": row.get("Contract_einddatum"),
            "Contract_ronde": row.get("Contract_ronde"),
            "EventType_Key": salary_event_key,
            "RedenVertrek_Key": None
        })
        next_key += 1

    if new_records:
        fact_employment = pd.concat(
            [fact_employment, pd.DataFrame(new_records)],
            ignore_index=True
        )

    return fact_employment, next_key


def _salary_review_week(employee_key):
    # Deterministic spread over the year. This avoids artificial BI spikes from
    # all salary reviews landing in January.
    return ((employee_key * 37) % 52) + 1


def _already_reviewed_this_year(
    fact_employment,
    employee_key,
    salary_event_key,
    year
):
    employee_records = fact_employment[
        (fact_employment["Employee_Key"] == employee_key)
        & (fact_employment["EventType_Key"] == salary_event_key)
    ]

    if employee_records.empty:
        return False

    review_years = pd.to_datetime(
        employee_records["Startdatum"],
        errors="coerce"
    ).dt.year

    return (review_years == year).any()
