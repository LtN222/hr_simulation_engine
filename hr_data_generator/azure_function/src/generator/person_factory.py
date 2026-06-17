import pandas as pd
from faker import Faker

fakeNL = Faker("nl_NL")
fakeINT = Faker()


class PersonFactory:

    def __init__(self, config, rng):
        self.config = config
        self.rng = rng

    def create(self, role_name, today):

        gender, voornaam, achternaam = self._choose_gender_and_name()

        _, geboortedatum = self._generate_age(today)

        bijzondere_aanstelling, land, voornaam, achternaam = (
            self._choose_special_arrangement(
                role_name,
                voornaam,
                achternaam
            )
        )

        return {
            "gender": gender,
            "first_name": voornaam,
            "last_name": achternaam,
            "birth_date": geboortedatum,
            "country": land,
            "bijzondere_aanstelling": bijzondere_aanstelling
        }

    # -------------------------
    # intern
    # -------------------------

    def _choose_gender_and_name(self):

        gender = self.rng.choices(
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

    def _generate_age(self, today):

        leeftijd = self.rng.randint(18, 67)

        geboortedatum = today - pd.DateOffset(
            years=leeftijd,
            days=self.rng.randint(0, 365)
        )

        return leeftijd, geboortedatum

    def _choose_special_arrangement(
        self,
        role_name,
        voornaam,
        achternaam
    ):

        bijzondere_aanstelling = None
        land = "Nederland"

        for regeling, cfg in self.config.special_arrangements.items():

            if role_name in cfg.get("roles", []):

                if self.rng.random() < cfg.get("probability", 0):

                    bijzondere_aanstelling = regeling

                    if regeling == "Expat":

                        land = self.rng.choice(
                            cfg.get(
                                "countries",
                                ["Polen", "Roemenië", "Bulgarije"]
                            )
                        )

                        voornaam = fakeINT.first_name()
                        achternaam = fakeINT.last_name()

                    break

        return bijzondere_aanstelling, land, voornaam, achternaam