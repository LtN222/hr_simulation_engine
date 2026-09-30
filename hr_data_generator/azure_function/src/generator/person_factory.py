from functools import lru_cache

import pandas as pd
from faker import Faker
from faker.providers.person import pl_PL as _faker_pl_PL

from src.generator.name_text import to_cp1252_latin

fakeNL = Faker("nl_NL")

# Faker's default locale, used for an Expat country without a configured
# name locale (still gender-aware).
FALLBACK_NAME_LOCALE = "en_US"
MAX_NAME_ATTEMPTS = 100

DEFAULT_GENDER_RATIO = {"male": 0.49, "female": 0.49}
# "Anders"/"Onbekend" stay a flat share regardless of role - only the M/F
# split within the remainder is informed by the configured ratio.
OTHER_GENDER_SHARE = 0.02


@lru_cache(maxsize=None)
def _faker_for(locale):
    """One Faker instance per locale, created once per process.

    Every instance draws from faker's single shared generator, so the one
    `seed_person_names` call also makes every locale reproducible.
    """
    return Faker(locale)


# Faker's pl_PL provider has no gendered surnames: `last_name_male`/`_female`
# both fall back to a single list with no -ski/-ska forms, and the masculine
# adjectival surnames sit in a separate `male_last_names` list. Build the
# gendered pools here so a Polish woman is a Kowalska, not a Kowalski.
_FEMININE_SUFFIXES = ("ska", "cka", "dzka")
_MASCULINE_SUFFIXES = ("ski", "cki", "dzki")
_ADJECTIVAL_FEMININE = (("dzki", "dzka"), ("ski", "ska"), ("cki", "cka"),
                        ("ny", "na"), ("ły", "ła"))


def _feminine_polish_surname(surname):
    for masculine, feminine in _ADJECTIVAL_FEMININE:
        if surname.endswith(masculine):
            return surname[: -len(masculine)] + feminine
    return surname


_PL_SURNAMES = tuple(dict.fromkeys(
    tuple(_faker_pl_PL.Provider.male_last_names)
    + tuple(_faker_pl_PL.Provider.unisex_last_names)
))
# Filter on the stored (folded) form: "Kośka" is stored as "Koska", which
# would read as a feminine -ska surname on a man.
_PL_MALE_SURNAMES = tuple(
    name for name in _PL_SURNAMES
    if not to_cp1252_latin(name).endswith(_FEMININE_SUFFIXES)
)
_PL_FEMALE_SURNAMES = tuple(dict.fromkeys(
    feminine for feminine in map(_feminine_polish_surname, _PL_SURNAMES)
    if not to_cp1252_latin(feminine).endswith(_MASCULINE_SUFFIXES)
))


def _capitalized(name):
    return name[:1].upper() + name[1:]


def seed_person_names(seed):
    """Seed the shared Faker generator used to draw employee names.

    `fakeNL`/`fakeINT` are process-wide singletons that both draw from
    `faker`'s single global random generator, not their own independent
    state - `Faker.seed()` reseeds that shared generator, so one call here
    covers every locale's `Faker()` instance in this process, not just
    `fakeNL`. Every other simulated value (role, salary, tenure, every
    weekly event) already comes from the `random.Random(seed)` instance
    threaded through the pipeline and was already reproducible; only names
    drawn through this module were not, since nothing seeded `faker`'s own
    generator from `simulation_seed`.

    Call this exactly once per run, near wherever `random.Random(seed)` is
    constructed (`run_simulation.py`/`run_simulation_incremental.py`) -
    before any name is drawn, not per employee or per week. Calling it more
    than once per employee/week would make every subsequent name repeat the
    same short sequence instead of continuing it.
    """
    Faker.seed(seed)


class PersonFactory:

    def __init__(self, config, rng):
        self.config = config
        self.rng = rng
        # Redraw statistics for the display-name length cap.
        self.name_draws = 0
        self.name_redraws = 0

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
        _, geboortedatum = self._generate_age(today, employment_start_date)

        bijzondere_aanstelling, land = self._choose_special_arrangement(role_name)

        if bijzondere_aanstelling == "Expat":
            voornaam, achternaam = self._choose_expat_name(gender, land)
        else:
            voornaam, achternaam = self._choose_name(gender)

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
        """Draw a Dutch name whose display name fits `max_display_length`."""
        def draw():
            if gender == "M":
                voornaam = fakeNL.first_name_male()
            elif gender == "F":
                voornaam = fakeNL.first_name_female()
            else:
                voornaam = fakeNL.first_name()
            return voornaam, fakeNL.last_name()

        return self._draw_fitting_name(draw)

    def _choose_expat_name(self, gender, country):
        """Draw a gender-correct name from the country's Faker locale.

        The result is romanized/folded for the CP1252 SQL columns before the
        length cap is checked, so the cap measures the name as it is stored.
        """
        locale = self._expat_config().get("name_locales", {}).get(
            country, FALLBACK_NAME_LOCALE
        )
        fake = _faker_for(locale)

        def draw():
            voornaam, achternaam = self._locale_name(fake, locale, gender)
            # Faker's bg_BG list holds a few lowercase first names; a display
            # name always starts with a capital.
            return tuple(
                _capitalized(to_cp1252_latin(part)) for part in (voornaam, achternaam)
            )

        return self._draw_fitting_name(draw)

    @staticmethod
    def _locale_name(fake, locale, gender):
        if gender == "M":
            voornaam = fake.first_name_male()
            achternaam = (
                fake.random_element(_PL_MALE_SURNAMES) if locale == "pl_PL"
                else fake.last_name_male()
            )
        elif gender == "F":
            voornaam = fake.first_name_female()
            achternaam = (
                fake.random_element(_PL_FEMALE_SURNAMES) if locale == "pl_PL"
                else fake.last_name_female()
            )
        else:
            voornaam, achternaam = fake.first_name(), fake.last_name()
        return voornaam, achternaam

    def _draw_fitting_name(self, draw):
        """Redraw the whole name until "Voornaam Achternaam" fits the cap."""
        maximum = self._max_display_length()
        for _ in range(MAX_NAME_ATTEMPTS):
            voornaam, achternaam = draw()
            self.name_draws += 1
            if maximum is None or len(f"{voornaam} {achternaam}") <= maximum:
                return voornaam, achternaam
            self.name_redraws += 1
        raise ValueError(
            f"No name of at most {maximum} characters found in "
            f"{MAX_NAME_ATTEMPTS} attempts (person_names.max_display_length)"
        )

    def _max_display_length(self):
        value = getattr(self.config, "person_names", {}).get("max_display_length")
        return None if value is None else int(value)

    def _expat_config(self):
        return getattr(self.config, "special_arrangements", {}).get("Expat", {})

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

    def _choose_special_arrangement(self, role_name):

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

                    break

        return bijzondere_aanstelling, land
