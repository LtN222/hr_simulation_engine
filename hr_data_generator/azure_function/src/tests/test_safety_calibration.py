import pytest

from src.core.config_loader import ConfigLoader
from src.infrastructure import safety_calibration as calibration


def _config(**overrides):
    base = {
        "structure": {
            "Productie": {
                "Operator": {"role_key": 1, "department_key": 1, "target_weight": 3, "ploegendienst": True},
                "Planner": {"role_key": 2, "department_key": 1, "target_weight": 1, "ploegendienst": False},
            },
        },
        "staffing": {},
        "workforce_planning": {},
        "growth": {"max_capacity": 40},
        "ploegendienst_assignment": {
            "values": ["Dag", "2-ploeg"], "weights": [0.5, 0.5],
        },
        "safety": {
            "annual_incident_rate_by_department": {"Productie": 0.2},
            "ploegendienst_multipliers": {"Dag": 1.0, "2-ploeg": 1.2},
            "new_hire_multiplier": {"within_days": 180, "multiplier": 1.5},
            "calibration": {"new_hire_share_by_department": {"Productie": 0.2}},
            "target_incident_rate_by_department": {"Productie": 0.3},
        },
    }
    base.update(overrides)
    return type("Config", (), base)()


def test_expected_rate_combines_base_shift_mix_and_new_hire_factor():
    config = _config()

    assert calibration.flagged_role_share(config, "Productie") == pytest.approx(0.75)
    # flagged roles: 0.5 * 1.0 + 0.5 * 1.2 = 1.1; company mix 0.25 * 1.0 + 0.75 * 1.1
    assert calibration.expected_shift_factor(config, "Productie") == pytest.approx(1.075)
    assert calibration.expected_new_hire_factor(config, 0.2) == pytest.approx(1.1)
    assert calibration.expected_annual_incident_rate(config, "Productie") == pytest.approx(
        0.2 * 1.075 * 1.1
    )


def test_calibrated_base_rate_realizes_the_target():
    config = _config()

    base = calibration.calibrated_base_rate(config, "Productie")

    assert calibration.expected_annual_incident_rate(
        config, "Productie", base_rate=base
    ) == pytest.approx(0.3)


def test_no_flagged_roles_or_no_new_hire_window_means_no_uplift():
    config = _config()
    config.safety["new_hire_multiplier"] = {"within_days": 0, "multiplier": 1.8}
    config.structure["Productie"]["Operator"]["ploegendienst"] = False

    assert calibration.expected_annual_incident_rate(config, "Productie") == pytest.approx(0.2)


def test_the_real_config_realizes_the_configured_incident_rate_targets():
    """Fails loudly when a shift mix, multiplier or base rate change moves the
    realized rate away from the targets (re-derive with `calibrated_base_rate`)."""
    config = ConfigLoader().load()
    targets = config.safety["target_incident_rate_by_department"]

    assert {"Productie", "Techniek", "Logistiek"} <= set(targets)
    for department, target in targets.items():
        realized = calibration.expected_annual_incident_rate(config, department)
        assert realized == pytest.approx(target, rel=0.10), department


def test_lost_time_incidents_per_100_fte_is_a_plausible_company_figure():
    config = ConfigLoader().load()

    rate = calibration.expected_lost_time_incidents_per_100_fte(config)

    assert 1.0 < rate < 3.0
