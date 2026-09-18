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


def test_the_real_maakindustrie_configuration_passes_validation():
    """The actual production sector config, not a synthetic fixture - this is
    the regression guard for the 55-role structure itself."""
    config = ConfigLoader().load()

    problems = validate_role_configuration(config)

    assert problems == [], "\n".join(problems)
