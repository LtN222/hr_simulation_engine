import pandas as pd

from src.infrastructure.role_eligibility import eligible_external, external_rejection_reason


def _config(role_career_paths=None):
    return type("Config", (), {"role_career_paths": role_career_paths or {}})()


def _role(**overrides):
    base = {
        "Role_Name": "Monteur",
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
