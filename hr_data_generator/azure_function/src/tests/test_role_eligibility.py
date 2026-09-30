import pandas as pd
import pytest

from src.infrastructure.role_eligibility import (
    _matching_credentials,
    _required_relevant_experience,
    credential_records_for,
    eligible_external,
    eligible_internal,
    external_rejection_reason,
    internal_relevant_experience,
    leadership_experience,
    movement_type,
    qualification_and_experience_reason,
)


def _config(role_career_paths=None):
    return type("Config", (), {"role_career_paths": role_career_paths or {}})()


def _role(**overrides):
    base = {
        "Functie_Naam": "Monteur",
        "Min_Relevante_Ervaring_Jr": 3.0,
        "Formele_Kwalificatie_Vereist": False,
        "Min_Opleidingsniveau": "Geen",
        "Leidinggevend": False,
        "Min_Leidinggevende_Ervaring_Jr": 0.0,
    }
    base.update(overrides)
    return pd.Series(base)


def test_external_rejection_reason_is_none_when_candidate_meets_every_requirement():
    role = _role()
    profile = {"Relevante_Ervaring_Jaren": 5.0, "Qualifications": []}

    assert external_rejection_reason(_config(), role, profile) is None
    assert eligible_external(_config(), role, profile) is True


def test_external_rejection_reason_flags_missing_formal_qualification():
    config = _config({"Monteur": {"relevante_opleidingen": ["MBO Monteur"]}})
    role = _role(Formele_Kwalificatie_Vereist=True, Min_Opleidingsniveau="MBO")
    profile = {"Relevante_Ervaring_Jaren": 5.0, "Qualifications": []}

    assert external_rejection_reason(config, role, profile) == "Opleiding of kwalificatie onvoldoende"
    assert eligible_external(config, role, profile) is False


def test_external_rejection_reason_flags_insufficient_experience():
    role = _role(Min_Relevante_Ervaring_Jr=8.0)
    profile = {"Relevante_Ervaring_Jaren": 1.0, "Qualifications": []}

    assert external_rejection_reason(_config(), role, profile) == "Onvoldoende relevante werkervaring"


def test_external_rejection_reason_flags_insufficient_leadership_experience():
    role = _role(Leidinggevend=True, Min_Leidinggevende_Ervaring_Jr=5.0)
    profile = {
        "Relevante_Ervaring_Jaren": 10.0,
        "Leidinggevende_Ervaring_Jaren": 1.0,
        "Qualifications": [],
    }

    assert external_rejection_reason(_config(), role, profile) == "Onvoldoende leidinggevende ervaring"


def test_external_rejection_reason_checks_requirements_in_the_same_order_as_eligible_external():
    """The reported reason must always be the first requirement actually
    failed, not an independently sampled label - a candidate failing both
    the qualification and experience bar should be reported for the
    qualification, since that's checked first."""
    config = _config({"Monteur": {"relevante_opleidingen": ["MBO Monteur"]}})
    role = _role(
        Formele_Kwalificatie_Vereist=True,
        Min_Opleidingsniveau="MBO",
        Min_Relevante_Ervaring_Jr=8.0,
    )
    profile = {"Relevante_Ervaring_Jaren": 0.0, "Qualifications": []}

    assert external_rejection_reason(config, role, profile) == "Opleiding of kwalificatie onvoldoende"


# ----------------------------------------------------------------------
# _required_relevant_experience - the WO "senior" experience exception
# ----------------------------------------------------------------------

def test_required_relevant_experience_ignores_the_wo_exception_for_a_non_senior_role():
    config = _config({"Monteur": {"relevante_opleidingen": ["WO Werktuigbouwkunde"]}})
    role = _role(Functie_Naam="Monteur", Min_Relevante_Ervaring_Jr=5.0)
    credentials = [{"Opleiding_Naam": "WO Werktuigbouwkunde", "Opleidingsniveau": "WO"}]

    assert _required_relevant_experience(config, role, credentials) == 5.0


def test_required_relevant_experience_relaxes_for_a_senior_role_with_a_matching_wo_credential():
    config = _config({"Senior Monteur": {"relevante_opleidingen": ["WO Werktuigbouwkunde"]}})
    role = _role(Functie_Naam="Senior Monteur", Min_Relevante_Ervaring_Jr=5.0)
    credentials = [{"Opleiding_Naam": "WO Werktuigbouwkunde", "Opleidingsniveau": "WO"}]

    assert _required_relevant_experience(config, role, credentials) == 2.0


def test_required_relevant_experience_never_raises_the_bar_above_the_configured_minimum():
    """A senior role whose own Min_Relevante_Ervaring_Jr is already below the
    2-year WO exception cap must keep its own (lower) requirement."""
    config = _config({"Senior Monteur": {"relevante_opleidingen": ["WO Werktuigbouwkunde"]}})
    role = _role(Functie_Naam="Senior Monteur", Min_Relevante_Ervaring_Jr=1.0)
    credentials = [{"Opleiding_Naam": "WO Werktuigbouwkunde", "Opleidingsniveau": "WO"}]

    assert _required_relevant_experience(config, role, credentials) == 1.0


def test_required_relevant_experience_keeps_the_full_bar_for_a_senior_role_without_a_matching_wo_credential():
    config = _config({"Senior Monteur": {"relevante_opleidingen": ["WO Werktuigbouwkunde"]}})
    role = _role(Functie_Naam="Senior Monteur", Min_Relevante_Ervaring_Jr=5.0)

    # HBO-level credential in the right subject does not qualify for the exception.
    hbo_credential = [{"Opleiding_Naam": "WO Werktuigbouwkunde", "Opleidingsniveau": "HBO"}]
    assert _required_relevant_experience(config, role, hbo_credential) == 5.0

    # WO-level credential in an unrelated subject does not qualify either.
    unrelated_wo = [{"Opleiding_Naam": "WO Rechten", "Opleidingsniveau": "WO"}]
    assert _required_relevant_experience(config, role, unrelated_wo) == 5.0

    assert _required_relevant_experience(config, role, []) == 5.0


# ----------------------------------------------------------------------
# _matching_credentials - education-direction / diploma matching
# ----------------------------------------------------------------------

def test_matching_credentials_only_returns_credentials_in_the_targets_relevante_opleidingen():
    config = _config({"QC Engineer": {"relevante_opleidingen": ["HBO Chemie", "HBO Biologie"]}})
    role = _role(Functie_Naam="QC Engineer")
    credentials = [
        {"Opleiding_Naam": "HBO Chemie", "Opleidingsniveau": "HBO"},
        {"Opleiding_Naam": "HBO Werktuigbouwkunde", "Opleidingsniveau": "HBO"},
    ]

    matches = _matching_credentials(config, role, credentials)

    assert [c["Opleiding_Naam"] for c in matches] == ["HBO Chemie"]


def test_matching_credentials_returns_nothing_when_the_target_role_has_no_configured_educations():
    role = _role(Functie_Naam="QC Engineer")
    credentials = [{"Opleiding_Naam": "HBO Chemie", "Opleidingsniveau": "HBO"}]

    assert _matching_credentials(_config(), role, credentials) == []


def test_matching_credentials_handles_empty_or_missing_credentials():
    config = _config({"QC Engineer": {"relevante_opleidingen": ["HBO Chemie"]}})
    role = _role(Functie_Naam="QC Engineer")

    assert _matching_credentials(config, role, []) == []
    assert _matching_credentials(config, role, None) == []


def test_matching_credentials_accepts_a_dataframe_of_credentials_the_same_as_a_list():
    config = _config({"QC Engineer": {"relevante_opleidingen": ["HBO Chemie"]}})
    role = _role(Functie_Naam="QC Engineer")
    credentials_df = pd.DataFrame([
        {"Opleiding_Naam": "HBO Chemie", "Opleidingsniveau": "HBO"},
        {"Opleiding_Naam": "HBO Biologie", "Opleidingsniveau": "HBO"},
    ])

    matches = _matching_credentials(config, role, credentials_df)

    assert [c["Opleiding_Naam"] for c in matches] == ["HBO Chemie"]


def test_matching_credentials_accepts_an_empty_dataframe_of_credentials():
    config = _config({"QC Engineer": {"relevante_opleidingen": ["HBO Chemie"]}})
    role = _role(Functie_Naam="QC Engineer")

    assert _matching_credentials(config, role, pd.DataFrame()) == []


# ----------------------------------------------------------------------
# helpers for the internal-eligibility tests
# ----------------------------------------------------------------------

def _employment_row(employee_key, role_key, start, end=None, base_experience=0.0):
    return {
        "Employee_Key": employee_key,
        "Role_Key": role_key,
        "Startdatum": start,
        "Einddatum": end,
        "Relevante_Ervaring_Jaren_Bij_Start": base_experience,
    }


# ----------------------------------------------------------------------
# leadership_experience() and eligible_internal()'s further-leadership-move gate
# ----------------------------------------------------------------------

def test_leadership_experience_only_counts_time_in_leidinggevend_roles():
    state = {
        "dim_role": pd.DataFrame({
            "Role_Key": [1, 2],
            "Functie_Naam": ["Operator A", "Teamleider Productie"],
            "Leidinggevend": [False, True],
        }),
        "fact_employment": pd.DataFrame([
            _employment_row(1, 1, pd.Timestamp("2018-01-01"), pd.Timestamp("2020-01-01")),
            _employment_row(1, 2, pd.Timestamp("2020-01-01")),
        ]),
    }

    exp = leadership_experience(state, 1, pd.Timestamp("2024-01-01"))

    assert 3.9 < exp < 4.1  # only the 2020-2024 Teamleider stint counts


def _leadership_move_state(tenure_years_as_teamleider):
    start = pd.Timestamp("2024-01-01") - pd.DateOffset(
        days=round(tenure_years_as_teamleider * 365.2425)
    )
    return {
        "dim_role": pd.DataFrame({
            "Role_Key": [1, 2],
            "Functie_Naam": ["Teamleider Productie", "Productiemanager"],
            "Leidinggevend": [True, True],
        }),
        "fact_employment": pd.DataFrame([
            _employment_row(1, 1, start),
        ]),
    }


def test_eligible_internal_rejects_a_further_leadership_move_below_the_discounted_bar():
    config = _config({
        "Teamleider Productie": {"logische_doorgroei": ["Productiemanager"]},
        "Productiemanager": {},
    })
    config.career_events = {"internal_leadership_experience_discount": 0.6}
    source_role = _role(Functie_Naam="Teamleider Productie", Leidinggevend=True)
    target_role = _role(
        Functie_Naam="Productiemanager", Leidinggevend=True,
        Min_Relevante_Ervaring_Jr=0.0, Min_Leidinggevende_Ervaring_Jr=5.0,
        SalaryScale_Key="E",
    )
    source_role["SalaryScale_Key"] = "D"

    # 2 years as Teamleider is below the discounted bar (0.6 * 5 = 3 years).
    state = _leadership_move_state(tenure_years_as_teamleider=2.0)

    assert eligible_internal(
        config, state, 1, source_role, target_role, pd.Timestamp("2024-01-01")
    ) is False


def test_eligible_internal_accepts_a_further_leadership_move_above_the_discounted_bar():
    config = _config({
        "Teamleider Productie": {"logische_doorgroei": ["Productiemanager"]},
        "Productiemanager": {},
    })
    config.career_events = {"internal_leadership_experience_discount": 0.6}
    source_role = _role(Functie_Naam="Teamleider Productie", Leidinggevend=True)
    target_role = _role(
        Functie_Naam="Productiemanager", Leidinggevend=True,
        Min_Relevante_Ervaring_Jr=0.0, Min_Leidinggevende_Ervaring_Jr=5.0,
        SalaryScale_Key="E",
    )
    source_role["SalaryScale_Key"] = "D"

    # 4 years as Teamleider clears the discounted bar (0.6 * 5 = 3 years) -
    # well under the full 5-year bar external hiring would require.
    state = _leadership_move_state(tenure_years_as_teamleider=4.0)

    assert eligible_internal(
        config, state, 1, source_role, target_role, pd.Timestamp("2024-01-01")
    ) is True


def test_eligible_internal_still_uses_the_original_three_year_rule_for_a_first_leadership_move():
    """The pre-existing exception for a *first* move into management (a
    general relevant-experience proxy, since there's no leadership tenure to
    measure yet) must be unaffected by the new further-leadership-move gate."""
    config = _config({
        "Operator A": {"logische_doorgroei": ["Teamleider Productie"]},
        "Teamleider Productie": {},
    })
    config.career_events = {"internal_leadership_experience_discount": 0.6}
    source_role = _role(Functie_Naam="Operator A", Leidinggevend=False, SalaryScale_Key="B")
    target_role = _role(
        Functie_Naam="Teamleider Productie", Leidinggevend=True,
        Min_Relevante_Ervaring_Jr=0.0, Min_Leidinggevende_Ervaring_Jr=1.0,
        SalaryScale_Key="D",
    )
    state = {
        "dim_role": pd.DataFrame({
            "Role_Key": [1],
            "Functie_Naam": ["Operator A"],
            "Leidinggevend": [False],
        }),
        "fact_employment": pd.DataFrame([
            _employment_row(1, 1, pd.Timestamp("2022-01-01")),  # 2 years, < 3
        ]),
    }

    assert eligible_internal(
        config, state, 1, source_role, target_role, pd.Timestamp("2024-01-01")
    ) is False


# ----------------------------------------------------------------------
# movement_type
# ----------------------------------------------------------------------

def test_movement_type_distinguishes_promotion_transfer_and_neither():
    config = _config({
        "Operator A": {
            "logische_doorgroei": ["Teamleider Productie"],
            "laterale_transfers": ["QC Medewerker"],
        },
    })

    assert movement_type(config, "Operator A", "Teamleider Productie") == "Promotie"
    assert movement_type(config, "Operator A", "QC Medewerker") == "Transfer"
    assert movement_type(config, "Operator A", "HR Manager") is None
    assert movement_type(config, "Onbekende Rol", "Teamleider Productie") is None


# ----------------------------------------------------------------------
# internal eligibility now follows the external policy (AR-09 / AR-37)
# ----------------------------------------------------------------------

DATE = pd.Timestamp("2024-01-01")

_EDUCATION = pd.DataFrame({
    "Education_Key": [1, 2, 3],
    "Opleiding_Naam": ["MBO Techniek", "HBO Techniek", "WO Techniek"],
    "Opleidingsniveau": ["MBO", "HBO", "WO"],
})


def _career_config(**career_events):
    config = _config({
        "Operator A": {"logische_doorgroei": ["Senior Operator", "Teamleider Productie"]},
        "Senior Operator": {"relevante_opleidingen": ["MBO Techniek", "HBO Techniek", "WO Techniek"]},
        "Senior QA Officer": {"relevante_opleidingen": ["MBO Techniek", "HBO Techniek", "WO Techniek"]},
    })
    config.career_events = {"relevant_experience_transfer_ratio": 0.45, **career_events}
    return config


def _internal_state(base_experience=0.0, start=pd.Timestamp("2023-01-01"), qualification_keys=()):
    return {
        "dim_role": pd.DataFrame({
            "Role_Key": [1], "Functie_Naam": ["Operator A"], "Leidinggevend": [False],
        }),
        "dim_education": _EDUCATION,
        "fact_employment": pd.DataFrame([
            _employment_row(1, 1, start, base_experience=base_experience),
        ]),
        "fact_employee_qualification": pd.DataFrame({
            "Employee_Key": [1] * len(qualification_keys),
            "Education_Key": list(qualification_keys),
            "Behaald_Datum": [pd.Timestamp("2020-01-01")] * len(qualification_keys),
        }),
    }


def _source(department_key=1, **overrides):
    return _role(
        Functie_Naam="Operator A", Department_Key=department_key, SalaryScale_Key="B", **overrides
    )


def _target(name="Senior Operator", department_key=1, **overrides):
    values = {
        "Functie_Naam": name, "Department_Key": department_key, "SalaryScale_Key": "C",
        "Min_Relevante_Ervaring_Jr": 5.0,
    }
    values.update(overrides)
    return _role(**values)


def test_internal_experience_includes_the_experience_brought_from_before_the_hire():
    state = _internal_state(base_experience=4.0)  # + 1 year in the row = 5 years
    config = _career_config()

    experience = internal_relevant_experience(state, config, 1, _source(), _target(), DATE)

    assert experience == pytest.approx(5.0, abs=0.01)
    assert eligible_internal(config, state, 1, _source(), _target(), DATE) is True
    # the old definition (time in the feeder role only) would have seen 1 year
    assert eligible_internal(
        config, _internal_state(base_experience=0.0), 1, _source(), _target(), DATE
    ) is False


def test_the_cross_department_ratio_applies_to_internal_experience():
    state = _internal_state(base_experience=10.0, start=DATE)
    config = _career_config()

    same = internal_relevant_experience(state, config, 1, _source(1), _target(department_key=1), DATE)
    across = internal_relevant_experience(state, config, 1, _source(1), _target(department_key=2), DATE)

    assert same == pytest.approx(10.0)
    assert across == pytest.approx(4.5)  # 10 * relevant_experience_transfer_ratio
    assert eligible_internal(config, state, 1, _source(1), _target(department_key=1), DATE) is True
    assert eligible_internal(config, state, 1, _source(1), _target(department_key=2), DATE) is False


def test_the_minimum_education_level_now_applies_to_internal_moves():
    config = _career_config()
    target = _target(
        Min_Relevante_Ervaring_Jr=0.0, Formele_Kwalificatie_Vereist=True, Min_Opleidingsniveau="HBO",
    )

    mbo_only = _internal_state(qualification_keys=[1])
    hbo = _internal_state(qualification_keys=[1, 2])
    nothing = _internal_state()

    assert eligible_internal(config, mbo_only, 1, _source(), target, DATE) is False
    assert eligible_internal(config, hbo, 1, _source(), target, DATE) is True
    assert eligible_internal(config, nothing, 1, _source(), target, DATE) is False


def test_the_senior_wo_rule_now_applies_to_internal_moves():
    config = _career_config()
    config.role_career_paths["Operator A"]["logische_doorgroei"].append("Senior QA Officer")
    target = _target("Senior QA Officer", Min_Relevante_Ervaring_Jr=5.0)
    # 2 years of relevant experience: enough only with a relevant WO degree (needs 2)
    base = dict(base_experience=1.0)

    with_wo = _internal_state(qualification_keys=[3], **base)
    with_hbo = _internal_state(qualification_keys=[2], **base)

    assert eligible_internal(config, with_wo, 1, _source(), target, DATE) is True
    assert eligible_internal(config, with_hbo, 1, _source(), target, DATE) is False


def test_internal_and_external_candidates_are_judged_by_the_same_helper():
    config = _career_config()
    target = _target(
        Min_Relevante_Ervaring_Jr=3.0, Formele_Kwalificatie_Vereist=True, Min_Opleidingsniveau="HBO",
    )
    credentials = [{"Opleiding_Naam": "MBO Techniek", "Opleidingsniveau": "MBO"}]

    assert qualification_and_experience_reason(config, target, credentials, 5.0) == (
        "Opleiding of kwalificatie onvoldoende"
    )
    assert external_rejection_reason(
        config, target, {"Relevante_Ervaring_Jaren": 5.0, "Qualifications": credentials}
    ) == "Opleiding of kwalificatie onvoldoende"
    assert qualification_and_experience_reason(
        config, target, credentials + [{"Opleiding_Naam": "HBO Techniek", "Opleidingsniveau": "HBO"}], 1.0
    ) == "Onvoldoende relevante werkervaring"


def test_the_internal_performance_floor_is_read_from_config():
    state = _internal_state(base_experience=5.0)
    target = _target(Min_Relevante_Ervaring_Jr=0.0)

    default = _career_config()
    strict = _career_config(internal_min_performance=3.5)

    assert eligible_internal(default, state, 1, _source(), target, DATE, performance=3.0) is True
    assert eligible_internal(default, state, 1, _source(), target, DATE, performance=2.6) is False
    assert eligible_internal(strict, state, 1, _source(), target, DATE, performance=3.0) is False


def test_the_first_leadership_experience_threshold_is_read_from_config():
    state = _internal_state(base_experience=0.0, start=DATE - pd.DateOffset(years=2))
    target = _target(
        "Teamleider Productie", Min_Relevante_Ervaring_Jr=0.0,
        Leidinggevend=True, Min_Leidinggevende_Ervaring_Jr=1.0,
    )
    source = _source(Leidinggevend=False)

    assert eligible_internal(_career_config(), state, 1, source, target, DATE) is False  # 2 < 3
    assert eligible_internal(
        _career_config(internal_first_leadership_min_experience_years=1.5),
        state, 1, source, target, DATE,
    ) is True


def test_credential_records_carry_name_and_level_and_respect_the_date():
    state = _internal_state(qualification_keys=[1, 2])

    records = credential_records_for(state, 1, DATE)

    assert {(r["Opleiding_Naam"], r["Opleidingsniveau"]) for r in records} == {
        ("MBO Techniek", "MBO"), ("HBO Techniek", "HBO"),
    }
    assert credential_records_for(state, 1, pd.Timestamp("2019-01-01")) == []
    assert credential_records_for({}, 1, DATE) == []
