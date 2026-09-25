import random

from faker import Faker

from src.generator.person_factory import PersonFactory, seed_person_names


def _config(gender_ratio):
    return type("Config", (), {
        "gender_ratio": gender_ratio,
        "special_arrangements": {},
    })()


def test_choose_gender_uses_the_departments_configured_ratio():
    config = _config({
        "default": {"male": 0.49, "female": 0.49},
        "Productie": {"male": 0.80, "female": 0.20},
    })
    factory = PersonFactory(config, random.Random(1))

    genders = [
        factory.choose_gender("Productiemedewerker", "Productie")
        for _ in range(2000)
    ]
    male_share = genders.count("M") / len(genders)

    assert 0.74 <= male_share <= 0.84


def test_choose_gender_role_override_takes_precedence_over_department():
    config = _config({
        "default": {"male": 0.49, "female": 0.49},
        "R&D": {"male": 0.55, "female": 0.45},
        "role_overrides": {
            "Productontwikkelaar": {"male": 0.35, "female": 0.65},
        },
    })
    factory = PersonFactory(config, random.Random(2))

    genders = [
        factory.choose_gender("Productontwikkelaar", "R&D")
        for _ in range(2000)
    ]
    male_share = genders.count("M") / len(genders)

    # Role override (35% male) should win over the R&D department default (55%).
    assert 0.29 <= male_share <= 0.41


def test_choose_gender_falls_back_to_default_for_an_unconfigured_department():
    config = _config({"default": {"male": 0.49, "female": 0.49}})
    factory = PersonFactory(config, random.Random(3))

    genders = [
        factory.choose_gender("Onbekende Rol", "Onbekende Afdeling")
        for _ in range(2000)
    ]
    male_share = genders.count("M") / len(genders)

    assert 0.43 <= male_share <= 0.55


def test_create_uses_a_pre_chosen_gender_without_redrawing_it():
    config = _config({"default": {"male": 0.49, "female": 0.49}})
    factory = PersonFactory(config, random.Random(4))

    person = factory.create(
        "Productiemedewerker",
        today="2024-01-01",
        gender="F",
        department_name="Productie",
    )

    assert person["gender"] == "F"


def test_seed_person_names_makes_drawn_names_reproducible():
    """Regression test for AR-32 (see BACKLOG.md "Architecture review"):
    names were drawn from faker's own unseeded generator, so two runs with
    the same simulation_seed produced different names every time even though
    every other simulated value (role, salary, tenure, every weekly event)
    already was reproducible via random.Random(seed)."""
    config = _config({"default": {"male": 0.49, "female": 0.49}})

    def draw_names():
        seed_person_names(99)
        factory = PersonFactory(config, random.Random(1))
        return [
            factory.create(
                "Productiemedewerker",
                today="2024-01-01",
                gender="M",
                department_name="Productie",
            )["first_name"]
            for _ in range(20)
        ]

    assert draw_names() == draw_names()


def test_seed_person_names_reseeds_the_shared_generator_used_by_every_locale():
    """`fakeNL` and `fakeINT` (used for the Expat special-arrangement branch)
    both draw from faker's single shared global generator, not independent
    per-instance state - one `seed_person_names` call must make both
    reproducible, not just the default-locale instance."""
    seed_person_names(7)
    first_nl = Faker("nl_NL").first_name()
    first_international = Faker().first_name()

    seed_person_names(7)
    second_nl = Faker("nl_NL").first_name()
    second_international = Faker().first_name()

    assert first_nl == second_nl
    assert first_international == second_international
