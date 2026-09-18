import pandas as pd

from src.infrastructure.role_eligibility import (
    _matching_credentials,
    _required_relevant_experience,
    eligible_external,
    eligible_internal,
    external_rejection_reason,
    leadership_experience,
    relevant_experience,
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
# relevant_experience() - role-history logic
# ----------------------------------------------------------------------

def _employment_row(employee_key, role_key, start, end=None):
    return {
        "Employee_Key": employee_key,
        "Role_Key": role_key,
        "Startdatum": start,
        "Einddatum": end,
    }


def test_relevant_experience_counts_time_in_the_target_role_itself():
    state = {
        "dim_role": pd.DataFrame({"Role_Key": [1], "Functie_Naam": ["Operator A"]}),
        "fact_employment": pd.DataFrame([
            _employment_row(1, 1, pd.Timestamp("2020-01-01")),
        ]),
    }
    target_role = pd.Series({"Functie_Naam": "Operator A"})

    exp = relevant_experience(state, 1, target_role, pd.Timestamp("2023-01-01"))

    assert 2.9 < exp < 3.1


def test_relevant_experience_counts_time_in_a_role_that_promotes_into_the_target():
    """Operator A -> Teamleider Productie is a configured logische_doorgroei,
    so time as an Operator A must count toward Teamleider Productie
    eligibility - the source role, not just the target itself."""
    config = _config({"Operator A": {"logische_doorgroei": ["Teamleider Productie"]}})
    state = {
        "dim_role": pd.DataFrame({
            "Role_Key": [1, 2],
            "Functie_Naam": ["Operator A", "Teamleider Productie"],
        }),
        "fact_employment": pd.DataFrame([
            _employment_row(1, 1, pd.Timestamp("2020-01-01")),
        ]),
    }
    target_role = pd.Series({"Functie_Naam": "Teamleider Productie"})

    exp = relevant_experience(state, 1, target_role, pd.Timestamp("2023-01-01"), config)

    assert 2.9 < exp < 3.1


def test_relevant_experience_counts_time_in_a_role_reachable_via_a_lateral_transfer():
    config = _config({"Monteur": {"laterale_transfers": ["QC Engineer"]}})
    state = {
        "dim_role": pd.DataFrame({
            "Role_Key": [1, 2],
            "Functie_Naam": ["Monteur", "QC Engineer"],
        }),
        "fact_employment": pd.DataFrame([
            _employment_row(1, 1, pd.Timestamp("2020-01-01")),
        ]),
    }
    target_role = pd.Series({"Functie_Naam": "QC Engineer"})

    exp = relevant_experience(state, 1, target_role, pd.Timestamp("2023-01-01"), config)

    assert 2.9 < exp < 3.1


def test_relevant_experience_ignores_time_in_an_unrelated_role():
    config = _config({"Operator A": {"logische_doorgroei": ["Teamleider Productie"]}})
    state = {
        "dim_role": pd.DataFrame({
            "Role_Key": [1, 2, 3],
            "Functie_Naam": ["Operator A", "Teamleider Productie", "HR Medewerker"],
        }),
        "fact_employment": pd.DataFrame([
            _employment_row(1, 3, pd.Timestamp("2020-01-01")),  # HR Medewerker
        ]),
    }
    target_role = pd.Series({"Functie_Naam": "Teamleider Productie"})

    exp = relevant_experience(state, 1, target_role, pd.Timestamp("2023-01-01"), config)

    assert exp == 0.0


def test_relevant_experience_only_counts_time_up_to_the_as_of_date_and_sums_multiple_rows():
    state = {
        "dim_role": pd.DataFrame({"Role_Key": [1], "Functie_Naam": ["Operator A"]}),
        "fact_employment": pd.DataFrame([
            _employment_row(1, 1, pd.Timestamp("2015-01-01"), pd.Timestamp("2017-01-01")),
            _employment_row(1, 1, pd.Timestamp("2018-01-01")),
        ]),
    }
    target_role = pd.Series({"Functie_Naam": "Operator A"})

    exp_mid_2017 = relevant_experience(state, 1, target_role, pd.Timestamp("2017-06-01"))
    exp_today = relevant_experience(state, 1, target_role, pd.Timestamp("2020-01-01"))

    # As of mid-2017 only the closed first stint (2015-2017, ~2 years) has
    # happened - the as-of date must clamp elapsed time, not count a stint
    # that hasn't started yet.
    assert 1.9 < exp_mid_2017 < 2.1
    # By 2020 both stints count: ~2 years (2015-2017) + ~2 years (2018-2020).
    assert 3.9 < exp_today < 4.1


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
