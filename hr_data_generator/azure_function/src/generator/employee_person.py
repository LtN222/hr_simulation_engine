import pandas as pd
from faker import Faker

fakeNL = Faker("nl_NL")
fakeINT = Faker()


def choose_gender_and_name(rng):

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

    return gender, voornaam, achternaam


def generate_age(today, rng):

    leeftijd = rng.randint(18, 67)

    geboortedatum = today - pd.DateOffset(
        years=leeftijd,
        days=rng.randint(0, 365)
    )

    return leeftijd, geboortedatum


def choose_special_arrangement(
    role_name,
    special_arrangements_config,
    rng,
    voornaam,
    achternaam
):

    bijzondere_aanstelling = None
    land = "Nederland"

    for regeling, cfg in special_arrangements_config.items():

        if role_name in cfg.get("roles", []):

            if rng.random() < cfg.get("probability", 0):

                bijzondere_aanstelling = regeling

                if regeling == "Expat":

                    land = rng.choice(
                        cfg.get(
                            "countries",
                            ["Polen", "Roemenië", "Bulgarije"]
                        )
                    )

                    voornaam = fakeINT.first_name()
                    achternaam = fakeINT.last_name()

                break

    return bijzondere_aanstelling, land, voornaam, achternaam