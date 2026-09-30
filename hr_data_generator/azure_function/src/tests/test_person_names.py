"""Name generation: display-name cap, gender/country-correct Expat names and
CP1252-safe output. Statistical, calling PersonFactory directly."""
import random

import pytest
from faker.providers.person import bg_BG, en_US, pl_PL, ro_RO

from src.core.config_loader import ConfigLoader
from src.generator.name_text import to_cp1252_latin
from src.generator.person_factory import (
    PersonFactory,
    _capitalized,
    _feminine_polish_surname,
    seed_person_names,
)

LOCALES = {"Polen": "pl_PL", "Roemenië": "ro_RO", "Bulgarije": "bg_BG"}
PROVIDERS = {"pl_PL": pl_PL.Provider, "ro_RO": ro_RO.Provider, "bg_BG": bg_BG.Provider}


def _config(countries=None, name_locales=None, max_length=20, probability=1.0):
    return type("Config", (), {
        "gender_ratio": {},
        "person_names": {"max_display_length": max_length} if max_length else {},
        "special_arrangements": {
            "Expat": {
                "probability": probability,
                "roles": ["Operator A"],
                "countries": countries or list(LOCALES),
                "name_locales": LOCALES if name_locales is None else name_locales,
            }
        },
    })()


def _factory(config, seed=1):
    return PersonFactory(config, random.Random(seed))


def _names(provider, *attributes):
    names = set()
    for attribute in attributes:
        values = getattr(provider, attribute, None)
        if values is not None:
            names.update(values.keys() if isinstance(values, dict) else values)
    return {_capitalized(to_cp1252_latin(name)) for name in names}


def _create(factory, gender, role="Operator A"):
    return factory.create(role, today="2024-01-01", gender=gender, department_name="Productie")


def test_every_display_name_fits_the_configured_maximum():
    seed_person_names(11)
    factory = _factory(ConfigLoader().load())

    people = [
        _create(factory, gender, role)
        for gender in ("M", "F", "Anders")
        for role in ("Productiemedewerker", "Operator A")
        for _ in range(1500)
    ]

    assert any(person["bijzondere_aanstelling"] == "Expat" for person in people)
    assert all(len(f"{p['first_name']} {p['last_name']}") <= 20 for p in people)


def test_dutch_names_need_a_redraw_only_occasionally():
    seed_person_names(12)
    factory = _factory(_config(probability=0.0))

    for _ in range(4000):
        factory._choose_name("M")

    rate = factory.name_redraws / factory.name_draws
    assert 0.02 < rate < 0.12  # about 6% of Dutch draws are over 20 characters


def test_a_name_that_cannot_fit_raises_instead_of_truncating():
    factory = _factory(_config(max_length=3, probability=0.0))

    with pytest.raises(ValueError, match="max_display_length"):
        factory._choose_name("M")


def test_no_cap_is_applied_when_the_setting_is_absent():
    factory = _factory(_config(max_length=None, probability=0.0))

    factory._choose_name("F")

    assert factory.name_redraws == 0


@pytest.mark.parametrize("country,locale", list(LOCALES.items()))
def test_expat_first_names_match_gender_and_country_locale(country, locale):
    seed_person_names(13)
    factory = _factory(_config(countries=[country]))
    provider = PROVIDERS[locale]
    male = _names(provider, "first_names_male")
    female = _names(provider, "first_names_female")
    everyone = _names(provider, "first_names")

    for _ in range(600):
        assert _create(factory, "M")["first_name"] in male
        assert _create(factory, "F")["first_name"] in female
        assert _create(factory, "Anders")["first_name"] in everyone
    assert male != female  # the locale really distinguishes the two lists


def test_polish_surnames_agree_with_gender():
    seed_person_names(14)
    factory = _factory(_config(countries=["Polen"]))

    men = [_create(factory, "M")["last_name"] for _ in range(1500)]
    women = [_create(factory, "F")["last_name"] for _ in range(1500)]

    assert not any(name.endswith(("ska", "cka", "dzka")) for name in men)
    assert not any(name.endswith(("ski", "cki", "dzki")) for name in women)
    assert any(name.endswith(("ski", "cki")) for name in men)
    assert any(name.endswith(("ska", "cka")) for name in women)
    assert _feminine_polish_surname("Kowalski") == "Kowalska"
    assert _feminine_polish_surname("Zieliński") == "Zielińska"
    assert _feminine_polish_surname("Nowacki") == "Nowacka"
    assert _feminine_polish_surname("Mazur") == "Mazur"


def test_expat_names_always_start_with_a_capital():
    """Faker's bg_BG first-name lists contain a few lowercase entries."""
    seed_person_names(18)
    factory = _factory(_config(countries=["Bulgarije"]))

    for gender in ("M", "F", "Anders"):
        for _ in range(800):
            person = _create(factory, gender)
            assert person["first_name"][0].isupper()
            assert person["last_name"][0].isupper()


def test_bulgarian_surnames_agree_with_gender():
    seed_person_names(15)
    factory = _factory(_config(countries=["Bulgarije"]))
    male = _names(bg_BG.Provider, "last_names_male")
    female = _names(bg_BG.Provider, "last_names_female")

    for _ in range(800):
        assert _create(factory, "M")["last_name"] in male
        assert _create(factory, "F")["last_name"] in female


def test_country_locale_mapping_is_used_and_an_unmapped_country_falls_back():
    seed_person_names(16)
    mapped = _factory(_config(countries=["Polen"], name_locales={"Polen": "pl_PL"}))
    fallback = _factory(_config(countries=["Duitsland"], name_locales={"Polen": "pl_PL"}))
    polish = _names(pl_PL.Provider, "first_names_male")
    english = _names(en_US.Provider, "first_names_male")

    assert all(_create(mapped, "M")["first_name"] in polish for _ in range(300))
    # Gender-aware fallback: en_US male first names only.
    assert all(_create(fallback, "M")["first_name"] in english for _ in range(300))
    assert all(
        _create(fallback, "F")["first_name"] in _names(en_US.Provider, "first_names_female")
        for _ in range(300)
    )


def test_every_expat_name_is_cp1252_safe_and_within_the_cap():
    seed_person_names(17)
    factory = _factory(_config())

    for gender in ("M", "F", "Anders"):
        for _ in range(1500):
            person = _create(factory, gender)
            display = f"{person['first_name']} {person['last_name']}"
            display.encode("cp1252")
            assert len(display) <= 20


def test_every_name_in_the_expat_locales_folds_to_cp1252():
    for provider in PROVIDERS.values():
        for name in _names(provider, "first_names", "first_names_male", "first_names_female",
                           "last_names", "last_names_male", "last_names_female",
                           "unisex_last_names", "male_last_names"):
            name.encode("cp1252")
    for surname in ("Kowalska", "Wiśniewska", "Łukasz"):
        to_cp1252_latin(surname).encode("cp1252")


def test_bulgarian_transliteration_follows_the_streamlined_system():
    assert to_cp1252_latin("Жанета Чолакова") == "Zhaneta Cholakova"
    assert to_cp1252_latin("Христо Ценов") == "Hristo Tsenov"
    assert to_cp1252_latin("Йордан Юруков") == "Yordan Yurukov"
    assert to_cp1252_latin("Щерьо Ъглов") == "Shteryo Aglov"
    assert to_cp1252_latin("Яна Шишманова") == "Yana Shishmanova"
    assert to_cp1252_latin("Мария") == "Maria"  # final -ия is written -ia
    assert to_cp1252_latin("Ивайло Георгиев") == "Ivaylo Georgiev"


def test_diacritics_cp1252_cannot_store_are_folded_to_ascii():
    assert to_cp1252_latin("Łukasz Śliwiński") == "Lukasz Sliwinski"
    assert to_cp1252_latin("Wiśniewska Ząbek Dębski") == "Wisniewska Zabek Debski"
    assert to_cp1252_latin("Ștefan Țurcanu Băsescu") == "Stefan Turcanu Basescu"
    assert to_cp1252_latin("Şerban Ţuţu") == "Serban Tutu"
    assert to_cp1252_latin("Żółć") == "Zólc"  # ó is CP1252-safe and stays


def test_characters_cp1252_can_store_are_left_alone():
    assert to_cp1252_latin("Chloë Müller Józef Cîrstea Zoë") == "Chloë Müller Józef Cîrstea Zoë"
    assert to_cp1252_latin("Van der Meer") == "Van der Meer"


def test_expat_names_are_reproducible_from_the_seed():
    def draw():
        seed_person_names(99)
        factory = _factory(_config(), seed=5)
        return [
            (p["first_name"], p["last_name"], p["country"])
            for p in (_create(factory, gender) for gender in ("M", "F", "Anders") for _ in range(60))
        ]

    first = draw()

    assert first == draw()
    assert {country for _, _, country in first} == set(LOCALES)
