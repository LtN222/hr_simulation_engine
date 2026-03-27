import math


def simulate_attrition(
    state,
    sector_config,
    schema,
    today,
    rng,
    event_type_map,
    reden_vertrek_map
):

    dim_department = state["dim_department"]
    dim_role = state["dim_role"]
    dim_employee = state["dim_employee"]
    fact_employment = state["fact_employment"]

    active_employment = fact_employment[
        fact_employment["Dienstverband_status"] == "Actief"
    ]

    vertrek_cfg = sector_config["dim_reden_vertrek"]

    # -------------------------------------------------
    # 🔁 Cyclic pressure (seizoensinvloed)
    # -------------------------------------------------

    week = today.isocalendar()[1]

    cyclic_factor = 1 + 0.25 * math.sin(2 * math.pi * week / 52)

    # -------------------------------------------------
    # 💥 Shock event (macro)
    # -------------------------------------------------

    shock_multiplier = 1.0

    if rng.random() < 0.02:  # 2% kans op event week
        shock_multiplier = rng.uniform(1.5, 3.0)

    # -------------------------------------------------
    # 🔄 Loop employees
    # -------------------------------------------------

    for idx, row in active_employment.iterrows():

        role_key = row["Role_Key"]

        dept_key = dim_role.loc[
            dim_role["Role_Key"] == role_key,
            "Department_Key"
        ].values[0]

        dept_name = dim_department.loc[
            dim_department["Department_Key"] == dept_key,
            "Department_Name"
        ].values[0]

        # base attrition
        attrition_rate = sector_config["attrition"].get(dept_name, 0.05)
        weekly_attrition = attrition_rate / 52

        # -------------------------------------------------
        # 📈 Performance effect
        # -------------------------------------------------

        perf = dim_employee.loc[
            dim_employee["Employee_Key"] == row["Employee_Key"],
            "Performance_Score"
        ].values[0]

        if perf < 2.5:
            weekly_attrition *= 1.8
        elif perf > 4:
            weekly_attrition *= 0.7

        # -------------------------------------------------
        # ⏳ Tenure effect
        # -------------------------------------------------

        tenure_years = (today - row["Startdatum"]).days / 365

        if tenure_years < 1:
            weekly_attrition *= 1.5
        elif tenure_years > 10:
            weekly_attrition *= 0.7

        # -------------------------------------------------
        # 🌊 Apply cyclic + shock
        # -------------------------------------------------

        weekly_attrition *= cyclic_factor * shock_multiplier

        # -------------------------------------------------
        # 🎯 Check exit
        # -------------------------------------------------

        if rng.random() >= weekly_attrition:
            continue

        # -------------------------------------------------
        # 🚪 EXIT EVENT
        # -------------------------------------------------

        fact_employment.loc[idx, "Dienstverband_status"] = "Uit dienst"
        fact_employment.loc[idx, "Einddatum"] = today
        state["vacancies"] += 1

        # -------------------------------------------------
        # 🧠 Categorie bepalen (logischer)
        # -------------------------------------------------

        if perf < 2.5:
            categorie = "werkgever"
        elif tenure_years < 1:
            categorie = rng.choices(
                ["vrijwillig", "werkgever"],
                weights=[0.8, 0.2]
            )[0]
        else:
            categorie = rng.choices(
                ["vrijwillig", "werkgever"],
                weights=[0.75, 0.25]
            )[0]

        # -------------------------------------------------
        # 🎲 Reden kiezen met weights
        # -------------------------------------------------

        redenen = vertrek_cfg[categorie]

        # basis weights (fallback)
        weights = []

        for reden in redenen:

            if reden in ["No-show"]:
                weights.append(0.02)

            elif reden in ["Medisch"]:
                weights.append(0.05)

            elif reden in ["Pensioen"]:
                # alleen relevant bij hoge tenure
                if tenure_years > 15:
                    weights.append(0.15)
                else:
                    weights.append(0.01)

            elif reden in ["Disfunctioneren"]:
                weights.append(0.3 if perf < 2.5 else 0.05)

            elif reden in ["Ontslag"]:
                weights.append(0.2)

            elif reden in ["Contract niet verlengd"]:
                weights.append(0.25 if categorie == "tijdelijk" else 0.05)

            else:
                weights.append(1.0)

        # normaliseren
        total = sum(weights)
        weights = [w / total for w in weights]

        reden = rng.choices(redenen, weights=weights)[0]

        fact_employment.loc[idx, "RedenVertrek_Key"] = reden_vertrek_map[reden]
        fact_employment.loc[idx, "EventType_Key"] = event_type_map["Uit dienst"]

    state["fact_employment"] = fact_employment

    return state