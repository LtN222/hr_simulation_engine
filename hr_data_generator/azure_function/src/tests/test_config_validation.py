from src.core.config_loader import ConfigLoader
from src.infrastructure.config_validation import validate_role_configuration


def _config(**overrides):
    base = {
        "structure": {
            "Productie": {
                "Operator": {
                    "role_key": 1, "department_key": 1,
                    "salary_scale_code": "B", "target_weight": 8,
                },
                "Teamleider Productie": {
                    "role_key": 2, "department_key": 1,
                    "salary_scale_code": "D", "target_weight": 1,
                },
            },
            "Kwaliteit": {
                "QC Medewerker": {
                    "role_key": 3, "department_key": 2,
                    "salary_scale_code": "B", "target_weight": 3,
                },
            },
        },
        "role_career_paths": {
            "Operator": {
                "logische_doorgroei": ["Teamleider Productie"],
                "laterale_transfers": ["QC Medewerker"],
                "relevante_opleidingen": ["MBO Techniek"],
            },
        },
        "growth": {"max_capacity": 800},
        "dim_education": [
            {"Opleiding_Naam": "MBO Techniek"},
        ],
    }
    base.update(overrides)
    return type("Config", (), base)()


def test_validate_role_configuration_reports_nothing_for_a_consistent_config():
    assert validate_role_configuration(_config()) == []


def test_validate_role_configuration_flags_a_duplicate_role_key():
    config = _config(structure={
        "Productie": {
            "Operator": {"role_key": 1, "department_key": 1},
            "Operator B": {"role_key": 1, "department_key": 1},
        },
    })

    problems = validate_role_configuration(config)

    assert any("role_key 1 is used by both" in p for p in problems)


def test_validate_role_configuration_flags_a_department_key_disagreement_within_a_department():
    config = _config(structure={
        "Productie": {
            "Operator": {"role_key": 1, "department_key": 1},
            "Teamleider Productie": {"role_key": 2, "department_key": 99},
        },
    })

    problems = validate_role_configuration(config)

    assert any("roles disagree on department_key" in p for p in problems)


def test_validate_role_configuration_flags_a_department_key_shared_across_departments():
    config = _config(structure={
        "Productie": {"Operator": {"role_key": 1, "department_key": 1}},
        "Kwaliteit": {"QC Medewerker": {"role_key": 2, "department_key": 1}},
    })

    problems = validate_role_configuration(config)

    assert any("department_key 1 is used by both" in p for p in problems)


def test_validate_role_configuration_flags_a_dangling_logische_doorgroei_target():
    config = _config(role_career_paths={
        "Operator": {"logische_doorgroei": ["Rol Die Niet Bestaat"]},
    })

    problems = validate_role_configuration(config)

    assert any(
        "logische_doorgroei references unknown role 'Rol Die Niet Bestaat'" in p
        for p in problems
    )


def test_validate_role_configuration_flags_a_dangling_laterale_transfers_target():
    config = _config(role_career_paths={
        "Operator": {"laterale_transfers": ["Rol Die Niet Bestaat"]},
    })

    problems = validate_role_configuration(config)

    assert any(
        "laterale_transfers references unknown role 'Rol Die Niet Bestaat'" in p
        for p in problems
    )


def test_validate_role_configuration_flags_a_lateral_transfer_across_salary_scales():
    config = _config(
        structure={
            "Productie": {"Operator": {"role_key": 1, "department_key": 1, "salary_scale_code": "B"}},
            "Kwaliteit": {"QC Medewerker": {"role_key": 2, "department_key": 2, "salary_scale_code": "C"}},
        },
        role_career_paths={
            "Operator": {"laterale_transfers": ["QC Medewerker"]},
        },
    )

    problems = validate_role_configuration(config)

    assert any("salary scales differ" in p for p in problems)


def test_validate_role_configuration_does_not_flag_a_lateral_transfer_on_the_same_scale():
    config = _config(
        structure={
            "Productie": {"Operator": {"role_key": 1, "department_key": 1, "salary_scale_code": "B"}},
            "Kwaliteit": {"QC Medewerker": {"role_key": 2, "department_key": 2, "salary_scale_code": "B"}},
        },
        role_career_paths={
            "Operator": {"laterale_transfers": ["QC Medewerker"]},
        },
    )

    assert validate_role_configuration(config) == []


def test_validate_role_configuration_flags_an_unreachable_role():
    config = _config(structure={
        "Productie": {
            "Toekomstige Rol": {
                "role_key": 1, "department_key": 1,
                "target_weight": 1, "active_from_headcount": 5000,
            },
        },
    })

    problems = validate_role_configuration(config)

    assert any("unreachable" in p for p in problems)


def test_validate_role_configuration_does_not_flag_a_zero_weight_role_with_a_high_threshold():
    """A role that isn't part of the long-run mix at all (target_weight 0)
    isn't 'unreachable' in any meaningful sense - there's nothing to reach."""
    config = _config(
        structure={
            "Productie": {
                "Nooit Bedoeld": {
                    "role_key": 1, "department_key": 1,
                    "target_weight": 0, "active_from_headcount": 5000,
                },
            },
        },
        role_career_paths={},
    )

    assert validate_role_configuration(config) == []


def test_validate_role_configuration_flags_an_unresolved_relevante_opleidingen_entry():
    config = _config(role_career_paths={
        "Operator": {"relevante_opleidingen": ["Opleiding Die Niet Bestaat"]},
    })

    problems = validate_role_configuration(config)

    assert any(
        "relevante_opleidingen references unknown education 'Opleiding Die Niet Bestaat'" in p
        for p in problems
    )


def _salary_config(**benchmark_overrides):
    benchmark = {
        "base_date": "2020-01-01",
        "annual_market_growth_rate": 0.025,
        "market_percentile_spread": 0.10,
        "market_median_by_role": {
            "Operator": 40000, "Teamleider Productie": 60000, "QC Medewerker": 42000,
        },
        "legal_minimum_salary": {
            "reference_year": 2026, "annual_full_time_salary": 31179,
            "allowances": {"vakantiegeld": 0.08},
        },
    }
    benchmark.update(benchmark_overrides)
    return _config(
        salary_benchmark=benchmark,
        dim_salary_scale=[
            {"Salarisschaal_Code": "B", "Minimum_Salaris": 30000, "Maximum_Salaris": 50000, "Aantal_Treden": 10},
            {"Salarisschaal_Code": "D", "Minimum_Salaris": 50000, "Maximum_Salaris": None, "Aantal_Treden": 10},
        ],
    )


def test_validate_role_configuration_accepts_a_consistent_salary_setup_with_an_open_ended_scale():
    assert validate_role_configuration(_salary_config()) == []


def test_validate_role_configuration_flags_a_role_without_a_market_median():
    config = _salary_config(market_median_by_role={"Operator": 40000, "QC Medewerker": 42000})

    problems = validate_role_configuration(config)

    assert any("Teamleider Productie: no market median" in p for p in problems)


def test_validate_role_configuration_flags_a_market_range_outside_its_scale():
    config = _salary_config(market_median_by_role={
        "Operator": 50000,  # P75 55,000 exceeds scale B's maximum 50,000
        "Teamleider Productie": 50000,  # P25 45,000 is below scale D's minimum 50,000
        "QC Medewerker": 42000,
    })

    problems = validate_role_configuration(config)

    assert any("Operator: market P75" in p and "above the maximum" in p for p in problems)
    assert any("Teamleider Productie: market P25" in p and "below the minimum" in p for p in problems)


def test_validate_role_configuration_only_checks_the_minimum_of_an_open_ended_scale():
    config = _salary_config(market_median_by_role={
        "Operator": 40000, "Teamleider Productie": 900000, "QC Medewerker": 42000,
    })

    assert validate_role_configuration(config) == []


def test_validate_role_configuration_flags_a_lowest_scale_below_the_indexed_legal_minimum():
    config = _salary_config()
    config.dim_salary_scale[0]["Minimum_Salaris"] = 20000
    config.salary_benchmark["market_median_by_role"]["Operator"] = 25000

    problems = validate_role_configuration(config)

    assert any("below the indexed legal minimum" in p for p in problems)


def test_validate_role_configuration_flags_a_lost_time_type_that_is_still_randomly_drawn():
    config = _config(
        dim_absence_type={"Kort verzuim": True, "Bedrijfsongeval": True},
        absence={"excluded_from_random_draw": []},
    )

    problems = validate_role_configuration(config)

    assert any("excluded_from_random_draw must list 'Bedrijfsongeval'" in p for p in problems)


def test_validate_role_configuration_flags_a_missing_lost_time_absence_type():
    config = _config(
        dim_absence_type={"Kort verzuim": True},
        absence={"excluded_from_random_draw": ["Bedrijfsongeval"]},
    )

    problems = validate_role_configuration(config)

    assert any("no 'Bedrijfsongeval'" in p for p in problems)


def test_validate_role_configuration_accepts_a_correct_lost_time_setup():
    config = _config(
        dim_absence_type={"Kort verzuim": True, "Bedrijfsongeval": True},
        absence={"excluded_from_random_draw": ["Bedrijfsongeval"]},
    )

    assert validate_role_configuration(config) == []


def test_validate_role_configuration_flags_an_unknown_voluntary_reason_key():
    config = _config(
        attrition={"voluntary_reason_satisfaction_multipliers": {
            "Eigen initiatief": {}, "Carri\u00c3\u00a8re switch": {},
        }},
        dim_departure_reason={"vrijwillig": ["Eigen initiatief", "Carri\u00e8re switch"]},
    )

    problems = validate_role_configuration(config)

    assert len(problems) == 1 and "Carri\u00c3\u00a8re switch" in problems[0]


def test_the_real_maakindustrie_configuration_passes_validation():
    """The actual production sector config, not a synthetic fixture - this is
    the regression guard for the 55-role structure itself."""
    config = ConfigLoader().load()

    problems = validate_role_configuration(config)

    assert problems == [], "\n".join(problems)
