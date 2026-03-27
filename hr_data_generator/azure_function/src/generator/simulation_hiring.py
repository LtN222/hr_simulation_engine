import pandas as pd
from faker import Faker

fakeNL = Faker("nl_NL")
fakeINT = Faker()


def simulate_hiring(
    state,
    sector_config,
    schema,
    today,
    rng,
    event_type_map
):

    dim_employee = state["dim_employee"]
    fact_employment = state["fact_employment"]

    dim_role = state["dim_role"]
    dim_location = state["dim_location"]
    dim_hire_source = state["dim_hire_source"]
    dim_education_level = state["dim_education_level"]

    # -------------------------------------------------
    # 🔥 NIEUW: vacatures ophalen
    # -------------------------------------------------

    vacancies = state.get("vacancies", 0)

    if vacancies <= 0:
        return state

    # -------------------------------------------------
    # ⏳ Hiring delay (fill rate)
    # -------------------------------------------------

    # basis fill rate (hoe snel vacatures worden gevuld)
    fill_rate = rng.uniform(0.2, 0.6)

    hires_this_week = int(vacancies * fill_rate)

    # altijd minimaal 1 hire als er vacatures zijn
    if vacancies > 0 and hires_this_week == 0:
        hires_this_week = 1

    hires_this_week = min(hires_this_week, vacancies)

    # -------------------------------------------------
    # 🔽 Bestaande hiring logic (ongewijzigd)
    # -------------------------------------------------

    special_arrangements_config = sector_config.get(
        "special_arrangements", {}
    )

    max_emp_key = dim_employee["Employee_Key"].max()
    max_employment_key = fact_employment["Employment_Key"].max()

    role_keys = dim_role["Role_Key"].tolist()
    location_keys = dim_location["Location_Key"].tolist()

    for _ in range(hires_this_week):

        max_emp_key += 1
        max_employment_key += 1

        role_key = rng.choice(role_keys)

        role_row = dim_role.loc[
            dim_role["Role_Key"] == role_key
        ].iloc[0]

        role_name = role_row["Role_Name"]

        # -------------------------------------------------
        # Naam + gender
        # -------------------------------------------------

        gender = rng.choices(
            ["M", "F", "Anders", "Onbekend"],
            weights=[0.49, 0.49, 0.01, 0.01]
        )[0]

        if gender == "M":
            voornaam = fakeNL.first_name_male()
        elif gender == "F":
            voornaam = fakeNL.first_name_female()
        else:
            voornaam = fakeNL.first_name()

        achternaam = fakeNL.last_name()

        # -------------------------------------------------
        # Leeftijd
        # -------------------------------------------------

        leeftijd = rng.randint(18, 67)

        geboortedatum = today - pd.DateOffset(
            years=leeftijd,
            days=rng.randint(0, 365)
        )

        # -------------------------------------------------
        # Salaris
        # -------------------------------------------------

        salaris = rng.randint(
            role_row["Salaris_min"],
            role_row["Salaris_max"]
        )

        # -------------------------------------------------
        # Special arrangements
        # -------------------------------------------------

        bijzondere_aanstelling = None
        land = "Nederland"

        for regeling, cfg in special_arrangements_config.items():

            if role_name in cfg.get("roles", []):

                if rng.random() < cfg.get("probability", 0):

                    bijzondere_aanstelling = regeling

                    if regeling == "Expat":

                        land = rng.choice(
                            cfg.get("countries", ["Polen", "Roemenië"])
                        )

                        voornaam = fakeINT.first_name()
                        achternaam = fakeINT.last_name()

                    break

        # -------------------------------------------------
        # Hire source
        # -------------------------------------------------

        hire_source_key = rng.choice(
            dim_hire_source["HireSource_Key"].tolist()
        )

        # -------------------------------------------------
        # Education
        # -------------------------------------------------

        edu_cfg = sector_config.get(
            "education_distribution_by_role",
            {}
        ).get(
            role_name,
            {"MBO": 0.5, "HBO": 0.3, "WO": 0.2}
        )

        niveaus = list(edu_cfg.keys())
        gewichten = list(edu_cfg.values())

        gekozen_niveau = rng.choices(
            niveaus,
            weights=gewichten
        )[0]

        education_key = dim_education_level.loc[
            dim_education_level["EducationLevel"] == gekozen_niveau,
            "EducationLevel_Key"
        ].values[0]

        location_key = rng.choice(location_keys)

        # -------------------------------------------------
        # Employee toevoegen
        # -------------------------------------------------

        dim_employee = pd.concat([
            dim_employee,
            pd.DataFrame([{
                "Employee_Key": max_emp_key,
                "Voornaam": voornaam,
                "Achternaam": achternaam,
                "Gender": gender,
                "Geboortedatum": geboortedatum,
                "Leeftijd": leeftijd,
                "Land": land,
                "HireSource_Key": hire_source_key,
                "EducationLevel_Key": education_key,
                "Bijzondere_Aanstelling": bijzondere_aanstelling,
                "Manager_Key": None
            }])
        ], ignore_index=True)

        # -------------------------------------------------
        # Employment toevoegen
        # -------------------------------------------------

        fact_employment = pd.concat([
            fact_employment,
            pd.DataFrame([{
                "Employment_Key": max_employment_key,
                "Previous_Employment_Key": None,
                "Employee_Key": max_emp_key,
                "Role_Key": role_key,
                "Location_Key": location_key,
                "Startdatum": today,
                "Einddatum": None,
                "Dienstverband_status": "Actief",
                "Salaris": salaris,
                "Contracttype": "Vast",
                "EventType_Key": event_type_map["Aangenomen"]
            }])
        ], ignore_index=True)

    # -------------------------------------------------
    # 📉 Vacatures verlagen
    # -------------------------------------------------

    state["vacancies"] -= hires_this_week

    # -------------------------------------------------
    # State updaten
    # -------------------------------------------------

    state["dim_employee"] = dim_employee
    state["fact_employment"] = fact_employment

    return state