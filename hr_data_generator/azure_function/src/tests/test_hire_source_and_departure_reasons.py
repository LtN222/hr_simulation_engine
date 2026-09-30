"""AR-44 (weighted initial hire source) and AR-41 (departure-reason semantics)."""
import random
from collections import Counter

import pandas as pd

from src.core.config_loader import ConfigLoader
from src.generator.employee_helpers import choose_hire_source
from src.infrastructure.config_validation import validate_role_configuration
from src.simulation.simulation_attrition import AttritionSimulator


def _sources():
    return pd.DataFrame({
        "HireSource_Key": [1, 2, 3, 4],
        "Bron_Naam": ["Referral", "Vacaturebank", "Campus", "Interne mobiliteit"],
        "Is_Internal": [False, False, False, True],
    })


def _config(weights=None):
    initial = {"hire_source_weights": weights} if weights is not None else {}
    return type("Config", (), {"initial_population": initial})()


def test_initial_hire_source_follows_the_configured_weights():
    config = _config({"Vacaturebank": 60, "Referral": 30, "Campus": 10})
    rng = random.Random(3)

    counts = Counter(choose_hire_source(config, _sources(), rng) for _ in range(20000))

    assert 0.57 < counts[2] / 20000 < 0.63
    assert 0.27 < counts[1] / 20000 < 0.33
    assert 0.08 < counts[3] / 20000 < 0.12
    assert counts[4] == 0  # internal mobility is never an original source


def test_a_source_missing_from_the_weights_gets_weight_zero():
    config = _config({"Vacaturebank": 1})

    keys = {choose_hire_source(config, _sources(), random.Random(seed)) for seed in range(200)}

    assert keys == {2}


def test_without_configured_weights_the_choice_stays_uniform_over_external_sources():
    config = _config()
    rng = random.Random(4)

    counts = Counter(choose_hire_source(config, _sources(), rng) for _ in range(12000))

    assert set(counts) == {1, 2, 3}
    assert all(3500 < count < 4500 for count in counts.values())


def test_choosing_a_hire_source_uses_exactly_one_rng_draw():
    config = _config({"Vacaturebank": 60, "Referral": 30, "Campus": 10})
    rng, untouched = random.Random(9), random.Random(9)

    choose_hire_source(config, _sources(), rng)
    untouched.choices([1, 2, 3], weights=[1, 1, 1], k=1)

    assert rng.random() == untouched.random()


def test_the_real_config_weights_only_reference_existing_external_sources():
    config = ConfigLoader().load()

    assert validate_role_configuration(config) == []
    assert set(config.initial_population["hire_source_weights"]) == {
        "Vacaturebank", "Campus", "Interne recruiter", "Referral", "Recruitmentbureau",
    }


def test_validation_flags_an_unknown_or_internal_weighted_hire_source():
    config = type("Config", (), {
        "structure": {},
        "initial_population": {"hire_source_weights": {
            "Referral": 1, "Bestaat Niet": 1, "Interne mobiliteit": 1,
        }},
        "dim_hire_source": [
            {"Bron_Naam": "Referral", "Is_Internal": False},
            {"Bron_Naam": "Interne mobiliteit", "Is_Internal": True},
        ],
    })()

    problems = validate_role_configuration(config)

    assert any("'Bestaat Niet' is not in dim_hire_source" in p for p in problems)
    assert any("'Interne mobiliteit' is an internal source" in p for p in problems)
    assert not any("'Referral'" in p for p in problems)


# ---------------------------------------------------------------------------
# AR-41
# ---------------------------------------------------------------------------

def _attrition(**settings):
    config = type("Config", (), {
        "attrition": settings,
        "dim_departure_reason": {
            "vrijwillig": ["Eigen initiatief"],
            "werkgever": ["Ontslag", "Disfunctioneren", "No-show"],
            "tijdelijk": ["Contract niet verlengd", "Seizoenswerker"],
        },
    })()
    return AttritionSimulator(config, None, random.Random(1), {}, {})


def _weight(simulator, reason, tenure_days):
    return simulator._reason_weight(reason, 3.4, tenure_days / 365.2425, 1.0, 7.0)


def test_no_show_is_only_possible_for_a_new_hire():
    simulator = _attrition()

    assert _weight(simulator, "No-show", 5) == 0.02
    assert _weight(simulator, "No-show", 29) == 0.02
    assert _weight(simulator, "No-show", 30) == 0.0
    assert _weight(simulator, "No-show", 3650) == 0.0


def test_the_no_show_window_is_read_from_config():
    simulator = _attrition(no_show_max_tenure_days=90)

    assert _weight(simulator, "No-show", 60) == 0.02
    assert _weight(simulator, "No-show", 91) == 0.0


def test_a_veteran_is_never_drawn_as_a_no_show():
    simulator = _attrition()

    reasons = {simulator._choose_reason("werkgever", 3.4, 10.0, 1.0, 7.0) for _ in range(3000)}

    assert "No-show" not in reasons
    assert reasons == {"Ontslag", "Disfunctioneren"}


def test_a_new_hire_can_still_be_a_no_show():
    simulator = _attrition()

    reasons = Counter(simulator._choose_reason("werkgever", 3.4, 0.02, 1.0, 7.0) for _ in range(3000))

    assert reasons["No-show"] > 0


def test_attrition_never_uses_the_tijdelijk_reasons():
    """`Contract niet verlengd` and `Seizoenswerker` belong to the `tijdelijk`
    category, which attrition never draws (contract lapses go through
    ContractLifecycleSimulator), so `_reason_weight` needs no branch for them."""
    simulator = _attrition()
    categories = {
        simulator._departure_category(3.4, tenure, satisfaction, engagement)
        for tenure in (0.1, 3.0, 12.0)
        for satisfaction in (4.0, 7.0, 9.0)
        for engagement in (5.0, 7.0)
        for _ in range(20)
    }

    assert categories <= {"vrijwillig", "werkgever"}
