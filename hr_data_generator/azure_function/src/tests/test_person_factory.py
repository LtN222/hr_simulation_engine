import random

from src.generator.person_factory import PersonFactory


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
