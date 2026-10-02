"""HP-04: satisfaction/engagement are normally spread, move over time and agree with attrition."""
import copy
import random

import numpy as np
import pandas as pd
import pytest

from src.core.config_loader import ConfigLoader
from src.infrastructure.config_validation import validate_role_configuration
from src.infrastructure.band_thresholds import band_minimums
from src.infrastructure.engagement import EngagementModel
from src.infrastructure.satisfaction import SatisfactionModel
from src.infrastructure.stable_random import (
    lag_correlation,
    smoothed_monthly_normal,
    stable_normal,
    stable_uniform,
    time_varying_component,
)
from src.simulation.simulation_absence import AbsenceSimulator
from src.simulation.simulation_attrition import AttritionSimulator
from src.tests.score_population import band_shares, build_population, score_population

D = pd.Timestamp


# ---------------------------------------------------------------------------
# the deterministic normal draw
# ---------------------------------------------------------------------------

def test_stable_normal_is_deterministic_and_differs_per_identifier_and_purpose():
    assert stable_normal(42, "preference") == stable_normal(42, "preference")
    assert stable_normal(42, "preference") != stable_normal(43, "preference")
    assert stable_normal(42, "preference") != stable_normal(42, "manager_quality")


def test_stable_normal_is_standard_normal():
    values = np.array([stable_normal(key, "preference") for key in range(1, 20001)])

    assert abs(values.mean()) < 0.03
    assert values.std() == pytest.approx(1.0, abs=0.03)
    assert abs(((values - values.mean()) ** 3).mean()) < 0.08                      # symmetric
    assert (np.abs(values) < 1.96).mean() == pytest.approx(0.95, abs=0.01)
    assert (values > 2.33).mean() == pytest.approx(0.01, abs=0.004)               # real tails
    assert np.isfinite(values).all()


def test_the_old_uniform_value_is_still_available_and_bounded():
    values = np.array([stable_uniform(key, "x") for key in range(1, 5001)])

    assert values.min() >= -1 and values.max() <= 1
    assert values.std() == pytest.approx(0.577, abs=0.02)
    assert SatisfactionModel._stable_value(7, "x") == EngagementModel._stable_value(7, "x") == stable_uniform(7, "x")


# ---------------------------------------------------------------------------
# the time-varying component
# ---------------------------------------------------------------------------

TV = {"sd": 1.0, "window_months": 6, "shared_fraction": 0.0}


def test_the_smoothed_value_is_deterministic_has_unit_variance_and_the_expected_autocorrelation():
    keys = range(1, 4001)
    this_month = np.array([smoothed_monthly_normal(k, D("2024-06-15"), "satisfaction", 6) for k in keys])
    next_month = np.array([smoothed_monthly_normal(k, D("2024-07-15"), "satisfaction", 6) for k in keys])
    three_months = np.array([smoothed_monthly_normal(k, D("2024-09-15"), "satisfaction", 6) for k in keys])
    far = np.array([smoothed_monthly_normal(k, D("2025-03-15"), "satisfaction", 6) for k in keys])

    assert smoothed_monthly_normal(5, D("2024-06-15"), "satisfaction", 6) == this_month[4]
    assert this_month.std() == pytest.approx(1.0, abs=0.04)
    assert np.corrcoef(this_month, next_month)[0, 1] == pytest.approx(lag_correlation(6, 1), abs=0.04)   # 0.77
    assert np.corrcoef(this_month, three_months)[0, 1] == pytest.approx(lag_correlation(6, 3), abs=0.04)
    assert abs(np.corrcoef(this_month, far)[0, 1]) < 0.06                      # window over: independent


def test_lag_correlations_have_the_closed_form_for_the_linear_window():
    assert lag_correlation(6, 0) == pytest.approx(1.0)
    assert lag_correlation(6, 1) == pytest.approx(70 / 91)
    assert lag_correlation(6, 6) == 0.0
    assert lag_correlation(1, 1) == 0.0


def test_the_component_depends_only_on_the_month_so_every_consumer_agrees():
    early = time_varying_component(17, D("2024-03-04"), TV, "satisfaction")
    late = time_varying_component(17, D("2024-03-31"), TV, "satisfaction")

    assert early == late
    assert time_varying_component(17, D("2024-04-01"), TV, "satisfaction") != early
    assert time_varying_component(17, None, TV, "satisfaction") == 0.0
    assert time_varying_component(17, D("2024-03-04"), {"sd": 0.0}, "satisfaction") == 0.0
    assert time_varying_component(17, D("2024-03-04"), None, "satisfaction") == 0.0


def test_the_models_give_the_same_score_for_any_day_of_the_same_month():
    config = ConfigLoader().load()
    satisfaction, engagement = SatisfactionModel(config), EngagementModel(config)
    kwargs = dict(employee_key=17, performance_score=3.4, compa_ratio=0.95, department_name="Productie",
                  manager_key="M1", tenure_years=2.5)

    first = satisfaction.explain(snapshot_date=D("2024-03-04"), **kwargs).score
    last = satisfaction.explain(snapshot_date=D("2024-03-29"), **kwargs).score
    other_month = satisfaction.explain(snapshot_date=D("2024-04-29"), **kwargs).score
    eng = lambda date: engagement.score(
        employee_key=17, satisfaction_score=first, performance_score=3.4, compa_ratio=0.95,
        department_name="Productie", manager_key="M1", as_of_date=date)

    assert first == last != other_month
    assert eng(D("2024-03-04")) == eng(D("2024-03-29")) != eng(D("2024-04-29"))


def test_satisfaction_and_engagement_share_the_configured_fraction_of_the_time_varying_draw():
    keys = range(1, 4001)
    both = {"sd": 1.0, "window_months": 6}
    date = D("2024-06-15")

    def correlation(shared):
        sat = np.array([time_varying_component(k, date, {**both, "shared_fraction": shared}, "satisfaction") for k in keys])
        eng = np.array([time_varying_component(k, date, {**both, "shared_fraction": shared}, "engagement") for k in keys])
        return np.corrcoef(sat, eng)[0, 1], sat.std()

    assert correlation(0.0)[0] == pytest.approx(0.0, abs=0.05)
    assert correlation(0.5)[0] == pytest.approx(0.5, abs=0.05)
    assert correlation(1.0)[0] == pytest.approx(1.0, abs=0.001)
    assert correlation(0.5)[1] == pytest.approx(1.0, abs=0.04)                  # sd stays the configured sd


# ---------------------------------------------------------------------------
# the distributions hit the HP-04 targets
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def scored():
    config = ConfigLoader().load()
    return config, score_population(config, build_population(config), months=12)


def test_satisfaction_hits_the_targets(scored):
    config, df = scored
    shares = band_shares(df["satisfaction"], config.dim_satisfaction_band)

    assert df["satisfaction"].mean() == pytest.approx(6.75, abs=0.15)
    assert df["satisfaction"].std() == pytest.approx(1.2, abs=0.15)
    for share, target in zip(shares, (0.03, 0.24, 0.47, 0.19, 0.07)):
        assert share == pytest.approx(target, abs=0.04)
    assert shares["Zeer laag"] > 0.015 and shares["Zeer hoog"] > 0.04        # the outer bands exist


def test_engagement_hits_the_targets(scored):
    config, df = scored
    shares = band_shares(df["engagement"], config.dim_engagement_band)

    assert df["engagement"].mean() == pytest.approx(6.4, abs=0.15)
    assert df["engagement"].std() == pytest.approx(1.2, abs=0.15)
    for share, target in zip(shares, (0.06, 0.31, 0.45, 0.14, 0.04)):
        assert share == pytest.approx(target, abs=0.04)


def test_satisfaction_and_engagement_correlate_but_stay_distinct(scored):
    _, df = scored

    assert 0.5 <= df["satisfaction"].corr(df["engagement"]) <= 0.7


def test_the_observable_factors_explain_a_quarter_to_a_third_of_satisfaction(scored):
    _, df = scored

    assert 0.22 <= df["observable_satisfaction"].var() / df["satisfaction"].var() <= 0.38


OBSERVABLE_ENGAGEMENT_SOURCES = [
    "e_contributions", "e_pay_direct", "e_pay_via_satisfaction", "e_satisfaction_other",
    "e_performance_career", "e_department",
]


def test_the_contribution_signals_are_the_largest_observable_source_of_engagement_variance(scored):
    _, df = scored
    shares = {column: df[column].var() / df["engagement"].var() for column in OBSERVABLE_ENGAGEMENT_SOURCES}

    largest = max(shares, key=shares.get)

    assert largest == "e_contributions", shares
    assert shares["e_contributions"] > 0.10
    assert shares["e_contributions"] > 2 * max(v for k, v in shares.items() if k != "e_contributions")


def test_pay_weighs_at_most_about_half_as_much_in_engagement_as_in_satisfaction(scored):
    _, df = scored
    satisfaction_pay_share = df["pay_satisfaction"].var() / df["satisfaction"].var()
    engagement_pay = df["e_pay_direct"] + df["e_pay_via_satisfaction"]
    engagement_pay_share = engagement_pay.var() / df["engagement"].var()

    assert engagement_pay_share <= 0.5 * satisfaction_pay_share
    assert engagement_pay_share < 0.06


def test_the_engagement_parts_add_up_to_the_score(scored):
    config, _ = scored
    model = EngagementModel(config)
    parts = model.components(employee_key=5, satisfaction_score=6.0, performance_score=3.8, compa_ratio=0.85,
                             department_name="Productie", manager_key="M1", career_momentum=0.1,
                             constructive_contributions={"a": 0.9, "b": 0.7}, as_of_date=D("2024-05-31"))
    score = model.score(employee_key=5, satisfaction_score=6.0, performance_score=3.8, compa_ratio=0.85,
                        department_name="Productie", manager_key="M1", career_momentum=0.1,
                        constructive_contributions={"a": 0.9, "b": 0.7}, as_of_date=D("2024-05-31"))

    assert score == round(config.engagement["baseline_mean"] + sum(parts.values()), 2)
    assert set(parts) == {"personal", "time_varying", "satisfaction", "performance", "pay",
                          "department", "manager", "momentum", "contributions"}


def test_the_personal_part_shares_the_configured_fraction_with_satisfactions_preference():
    model = EngagementModel(type("Config", (), {"engagement": {"individual_shared_fraction": 0.5}})())
    keys = range(1, 4001)
    engagement_draw = np.array([model._personal_draw(k) for k in keys])
    preference = np.array([stable_normal(k, "preference") for k in keys])

    assert engagement_draw.std() == pytest.approx(1.0, abs=0.04)
    assert np.corrcoef(engagement_draw, preference)[0, 1] == pytest.approx(0.5 ** 0.5, abs=0.04)
    independent = EngagementModel(type("Config", (), {"engagement": {}})())
    assert independent._personal_draw(7) == stable_normal(7, "engagement")


# ---------------------------------------------------------------------------
# pay is bounded context for engagement
# ---------------------------------------------------------------------------

def test_total_pay_effect_on_engagement_is_at_most_55_percent_of_satisfactions_for_every_compa_band():
    config = ConfigLoader().load()
    satisfaction, engagement = SatisfactionModel(config), EngagementModel(config)
    inherited = float(config.engagement["satisfaction_effect"])
    knots = [0.70, 0.80, 0.85, 0.90, 0.95, 1.00, 1.05, 1.10, 1.15, 1.20, 1.30]

    for ratio in knots + list(np.arange(0.7, 1.3, 0.01)):
        pay_on_satisfaction = satisfaction._compa_ratio_component(ratio)
        total_on_engagement = engagement._compa_ratio_component(ratio) + inherited * pay_on_satisfaction
        assert abs(total_on_engagement) <= 0.55 * abs(pay_on_satisfaction) + 1e-9, ratio
    # the named bands, as configured
    for band in ("ver_onder", "onder", "rond", "boven", "ver_boven"):
        direct = config.engagement["compa_ratio_adjustments"][band]
        indirect = inherited * config.satisfaction["compa_ratio_adjustments"][band]
        assert abs(direct + indirect) <= 0.55 * abs(config.satisfaction["compa_ratio_adjustments"][band]) + 1e-9, band


def test_engagements_direct_pay_effects_keep_their_original_values():
    config = ConfigLoader().load()

    assert config.engagement["compa_ratio_adjustments"] == {
        "ver_onder": -0.45, "onder": -0.2, "rond": 0.0, "boven": 0.08, "ver_boven": 0.12}


def test_scores_move_over_time_so_people_pass_through_other_bands(scored):
    config, df = scored
    minimums = [float(b["Minimum_Score"]) for b in config.dim_satisfaction_band]
    df = df.assign(band=np.clip(np.searchsorted(minimums, df["satisfaction"].to_numpy(), side="right") - 1, 0, 4))
    per_employee = df.groupby("key")["satisfaction"]
    within = np.sqrt(per_employee.var().mean())
    between = per_employee.mean().std()

    assert within > 0.4 and within / np.sqrt(within ** 2 + between ** 2) > 0.3
    modal = df.groupby("key")["band"].agg(lambda s: s.mode().iloc[0])
    outside = (df["band"] != df["key"].map(modal)).groupby(df["key"]).sum()
    assert (outside >= 3).mean() > 0.5                                         # visibly many people travel
    assert (df.groupby("key")["band"].nunique() >= 3).mean() > 0.10          # 12 months; 35% over 24


def test_the_most_common_driver_is_not_the_neutral_no_driver_label(scored):
    _, df = scored

    assert (df["driver"] == "Geen dominant aandachtspunt").mean() < 0.10


# ---------------------------------------------------------------------------
# attrition and absence read their cut-offs from the band dimensions
# ---------------------------------------------------------------------------

def _config_with_satisfaction_minimums(*minimums):
    config = copy.deepcopy(ConfigLoader().load())
    names = ["Zeer laag", "Laag", "Neutraal", "Hoog", "Zeer hoog"]
    config.dim_satisfaction_band = [
        {"Tevredenheidsband_Naam": name, "Minimum_Score": low,
         "Maximum_Score": (minimums[i + 1] - 0.01) if i < 4 else 10.0}
        for i, (name, low) in enumerate(zip(names, minimums))
    ]
    return config


def test_band_minimums_are_named_by_position_and_default_without_bands():
    config = ConfigLoader().load()

    assert band_minimums(config, "dim_satisfaction_band") == {
        "zeer_laag": 1.0, "laag": 4.5, "neutraal": 6.0, "hoog": 7.5, "zeer_hoog": 8.5}
    assert band_minimums(object(), "dim_satisfaction_band")["zeer_hoog"] == 8.5


def test_attrition_cutoffs_follow_the_satisfaction_bands():
    default = AttritionSimulator(ConfigLoader().load(), None, random.Random(1), {}, {})
    shifted = AttritionSimulator(_config_with_satisfaction_minimums(1.0, 4.0, 5.0, 8.0, 9.0), None,
                                 random.Random(1), {}, {})
    multipliers = ConfigLoader().load().attrition["satisfaction_attrition_multipliers"]

    assert default._satisfaction_multiplier(4.2) == multipliers["zeer_laag"]       # below 4.5
    assert shifted._satisfaction_multiplier(4.2) == multipliers["laag"]            # 4.0 is now where "Laag" starts
    assert default._satisfaction_multiplier(5.5) == multipliers["laag"]
    assert shifted._satisfaction_multiplier(5.5) == multipliers["neutraal"]       # 5.0 is now "Neutraal"
    assert default._satisfaction_multiplier(8.6) == multipliers["zeer_hoog"]
    assert shifted._satisfaction_multiplier(8.6) == multipliers["hoog"]           # 9.0 is now "Zeer hoog"
    assert default._satisfaction_multiplier(3.9) == multipliers["zeer_laag"]
    assert shifted._satisfaction_multiplier(3.9) == multipliers["zeer_laag"]


def test_the_zero_laag_and_zeer_hoog_multipliers_now_apply():
    simulator = AttritionSimulator(ConfigLoader().load(), None, random.Random(1), {}, {})
    multipliers = simulator.config.attrition["satisfaction_attrition_multipliers"]

    assert simulator._satisfaction_multiplier(3.0) == multipliers["zeer_laag"] == 1.8
    assert simulator._satisfaction_multiplier(9.0) == multipliers["zeer_hoog"] == 0.7


def test_attrition_categories_and_reasons_use_the_band_cutoffs_too():
    shifted = AttritionSimulator(_config_with_satisfaction_minimums(1.0, 4.5, 5.0, 8.0, 9.0), None,
                                 random.Random(1), {}, {})
    default = AttritionSimulator(ConfigLoader().load(), None, random.Random(1), {}, {})

    assert default.satisfaction_cutoffs["neutraal"] == 6.0 and shifted.satisfaction_cutoffs["neutraal"] == 5.0
    # satisfaction 5.5 is "laag" by default (reason weights lean to leaving) but "neutraal" when the band moves
    low = default._reason_weight("Hoger salaris", 3.4, 3.0, 0.8, 5.5)
    neutral = shifted._reason_weight("Hoger salaris", 3.4, 3.0, 0.8, 5.5)
    assert low > neutral


def test_absence_cutoffs_follow_the_satisfaction_bands():
    default = AbsenceSimulator(ConfigLoader().load(), None, random.Random(1))
    shifted = AbsenceSimulator(_config_with_satisfaction_minimums(1.0, 4.5, 5.0, 8.0, 9.0), None, random.Random(1))
    multipliers = default.absence_cfg["satisfaction_incident_multipliers"]

    assert default._satisfaction_incident_multiplier(5.5) == multipliers["low"]
    assert shifted._satisfaction_incident_multiplier(5.5) == multipliers["neutral"]
    assert default._satisfaction_incident_multiplier(7.8) == multipliers["high"]
    assert shifted._satisfaction_incident_multiplier(7.8) == multipliers["neutral"]


# ---------------------------------------------------------------------------
# the band validation rule
# ---------------------------------------------------------------------------

def _validation_config(satisfaction=None, engagement=None, **extra):
    good = [
        {"Minimum_Score": 1.0, "Maximum_Score": 4.49}, {"Minimum_Score": 4.5, "Maximum_Score": 5.99},
        {"Minimum_Score": 6.0, "Maximum_Score": 7.49}, {"Minimum_Score": 7.5, "Maximum_Score": 8.49},
        {"Minimum_Score": 8.5, "Maximum_Score": 10.0},
    ]
    return type("Config", (), {
        "structure": {},
        "dim_satisfaction_band": satisfaction or good,
        "dim_engagement_band": engagement or good,
        **extra,
    })()


def test_the_real_bands_and_a_good_chain_pass_the_validation():
    assert validate_role_configuration(ConfigLoader().load()) == []
    assert validate_role_configuration(_validation_config()) == []


def test_the_validation_flags_a_gap_an_overlap_wrong_order_and_a_wrong_count():
    gap = _validation_config(satisfaction=[
        {"Minimum_Score": 1.0, "Maximum_Score": 4.49}, {"Minimum_Score": 5.0, "Maximum_Score": 5.99},
        {"Minimum_Score": 6.0, "Maximum_Score": 7.49}, {"Minimum_Score": 7.5, "Maximum_Score": 8.49},
        {"Minimum_Score": 8.5, "Maximum_Score": 10.0}])
    overlap = _validation_config(engagement=[
        {"Minimum_Score": 1.0, "Maximum_Score": 4.8}, {"Minimum_Score": 4.5, "Maximum_Score": 5.99},
        {"Minimum_Score": 6.0, "Maximum_Score": 7.49}, {"Minimum_Score": 7.5, "Maximum_Score": 8.49},
        {"Minimum_Score": 8.5, "Maximum_Score": 10.0}])
    unordered = _validation_config(satisfaction=list(reversed(_validation_config().dim_satisfaction_band)))
    short = _validation_config(satisfaction=_validation_config().dim_satisfaction_band[:4])

    assert any("dim_satisfaction_band: bands are not ordered and contiguous at 4.49 -> 5.0" in p
               for p in validate_role_configuration(gap))
    assert any("dim_engagement_band: bands are not ordered and contiguous" in p
               for p in validate_role_configuration(overlap))
    assert any("not ordered and contiguous" in p for p in validate_role_configuration(unordered))
    assert any("exactly 5 bands" in p for p in validate_role_configuration(short))


def test_the_validation_flags_invalid_time_varying_settings():
    config = _validation_config()
    config.satisfaction = {"time_varying": {"sd": -1, "window_months": 0, "shared_fraction": 1.5}}

    problems = validate_role_configuration(config)

    assert any("time_varying.sd must be >= 0" in p for p in problems)
    assert any("window_months must be >= 1" in p for p in problems)
    assert any("shared_fraction must be between 0 and 1" in p for p in problems)
