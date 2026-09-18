import pandas as pd
from faker import Faker

fakeNL = Faker("nl_NL")
fakeINT = Faker()

DEFAULT_GENDER_RATIO = {"male": 0.49, "female": 0.49}
# "Anders"/"Onbekend" stay a flat share regardless of role - only the M/F
# split within the remainder is informed by the configured ratio.
OTHER_GENDER_SHARE = 0.02


class PersonFactory:

    def __init__(self, config, rng):
        self.config = config
        self.rng = rng

    def create(
        self,
        role_name,
        today,
        employment_start_date=None,
        gender=None,
        department_name=None,
    ):

        if gender is None:
            gender = self.choose_gender(role_name, department_name)
        voornaam, achternaam = self._choose_name(gender)

        _, geboortedatum = self._generate_age(today, employment_start_date)

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

    def choose_gender(self, role_name=None, department_name=None):
        """Draw a gender using the role/department-informed ratio.

        Exposed separately from `create` so callers that need gender before
        the rest of a person's details are known (e.g. to apply it to salary
        determination) can draw it once and pass it back into `create`.
        """
        ratio = self._gender_ratio(role_name, department_name)
        male_share = float(ratio.get("male", DEFAULT_GENDER_RATIO["male"]))
        female_share = float(ratio.get("female", DEFAULT_GENDER_RATIO["female"]))
        remainder = max(0.0, 1 - OTHER_GENDER_SHARE)

        return self.rng.choices(
            ["M", "F", "Anders", "Onbekend"],
            weights=[
                male_share * remainder,
                female_share * remainder,
                OTHER_GENDER_SHARE / 2,
                OTHER_GENDER_SHARE / 2,
            ]
        )[0]

    # -------------------------
    # intern
    # -------------------------

    def _gender_ratio(self, role_name, department_name):
        config = getattr(self.config, "gender_ratio", {})
        overrides = config.get("role_overrides", {})
        if role_name in overrides:
            return overrides[role_name]
        if department_name in config:
            return config[department_name]
        return config.get("default", DEFAULT_GENDER_RATIO)

    def _choose_name(self, gender):
        if gender == "M":
            voornaam = fakeNL.first_name_male()
        elif gender == "F":
            voornaam = fakeNL.first_name_female()
        else:
            voornaam = fakeNL.first_name()

        achternaam = fakeNL.last_name()

        return voornaam, achternaam

    def _generate_age(self, today, employment_start_date=None):
        """Generate a date of birth compatible with employment start.

        Initial-population contracts can predate the simulation start by many
        years. Sampling an age relative to ``today`` alone can therefore make
        a person a minor on their first employment date. The feasible birth
        date range is bounded by both the current age distribution and the
        legal minimum age at the start of employment.
        """
        today = pd.Timestamp(today).normalize()
        minimum_current_age = 18
        maximum_current_age = 67
        minimum_hire_age = int(
            getattr(self.config, "initial_population", {}).get(
                "minimum_hire_age", 18
            )
        )

        oldest_birth_date = today - pd.DateOffset(years=maximum_current_age)
        latest_birth_date = today - pd.DateOffset(years=minimum_current_age)

        if employment_start_date is not None:
            latest_birth_date = min(
                latest_birth_date,
                pd.Timestamp(employment_start_date).normalize()
                - pd.DateOffset(years=minimum_hire_age)
            )

        if latest_birth_date < oldest_birth_date:
            raise ValueError(
                "Employment start date is incompatible with the configured "
                "employee age range."
            )

        span_days = (latest_birth_date - oldest_birth_date).days
        geboortedatum = oldest_birth_date + pd.Timedelta(
            days=self.rng.randint(0, span_days)
        )
        leeftijd = (today - geboortedatum).days // 365

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
