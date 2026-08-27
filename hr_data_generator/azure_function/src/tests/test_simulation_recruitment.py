import random

import pandas as pd

from src.core.config_loader import ConfigLoader
from src.simulation.simulation_recruitment import (
    BELOW_MINIMUM_QUALITY_REASON,
    NOT_SELECTED_REASON,
    RecruitmentSimulator,
)


def _config(**recruitment_overrides):
    recruitment = {
        "decline_reasons": [
            {"name": "Ander aanbod geaccepteerd", "weight": 1.0, "quality_weight_bonus": 5.0},
            {"name": "Persoonlijke omstandigheden", "weight": 1.0},
        ],
        "decline_reason_high_quality_threshold": 3.7,
        "decision_days": {"min": 1, "max": 1},
        "source_profiles": {
            "Vacaturebank": {"minimum_offer_quality": 1.0, "candidate_decline_rate": 0.0},
        },
    }
    recruitment.update(recruitment_overrides)
    return type("Config", (), {"recruitment": recruitment, "role_career_paths": {}})()


def _dim_role():
    return pd.DataFrame({
        "Role_Key": [1],
        "Functie_Naam": ["Monteur"],
        "Afdeling_Naam": ["Techniek"],
        "Department_Key": [1],
    })


def _dim_stages():
    return pd.DataFrame({
        "Stage_Key": [1, 2, 3, 4],
        "Fase_Naam": ["Sollicitatie", "Screening", "Gesprek", "Aanbod"],
    })


def _dim_status():
    return pd.DataFrame({
        "RecruitmentStatus_Key": [1, 2, 3, 4],
        "Status_Naam": ["Aangenomen", "Afgewezen", "Geweigerd", "In behandeling"],
    })


def _pipeline_row(**overrides):
    base = {
        "Recruitment_Key": 1,
        "Vacancy_Key": 100,
        "Role_Key": 1,
        "Department_Key": 1,
        "HireSource_Key": 1,
        "Vacature_Reden": "Groei",
        "Employee_Key": None,
        "Status": RecruitmentSimulator.IN_PROGRESS_STATUS,
        "RecruitmentStatus_Key": 4,
        "Stage_Key": 1,
        "Application_Date": pd.Timestamp("2024-01-01"),
        "Screening_Date": None,
        "Interview_Date": None,
        "Offer_Date": None,
        "Decision_Date": None,
        "Dagen_Tot_Beslissing": None,
        "Kandidaat_Kwaliteit": 4.0,
        "DeclineReason_Key": None,
        "RejectionReason_Key": None,
    }
    base.update(overrides)
    return base


def _state_with_pipeline(rows):
    return {
        "dim_role": _dim_role(),
        "dim_department": pd.DataFrame({"Department_Key": [1], "Afdeling_Naam": ["Techniek"]}),
        "dim_hire_source": pd.DataFrame({
            "HireSource_Key": [1, 2],
            "Bron_Naam": ["Vacaturebank", "Interne mobiliteit"],
            "Is_Internal": [False, True],
        }),
        "dim_recruitment_status": _dim_status(),
        "dim_recruitment_stage": _dim_stages(),
        "fact_recruitment": pd.DataFrame(rows),
        "_recruitment_pipeline_profiles": {},
    }


def _vacancy(vacancy_key=100):
    return pd.Series({
        "Vacancy_Key": vacancy_key, "Role_Key": 1, "Department_Key": 1,
        "Vacature_Reden": "Groei", "Status": "Open",
        "Created_Date": pd.Timestamp("2024-01-01"),
    })


def _prime_lookups(simulator, state):
    simulator._status_keys = simulator._build_reason_lookup(
        state, "dim_recruitment_status", "Status_Naam", "RecruitmentStatus_Key"
    )
    simulator._stage_keys = simulator._build_reason_lookup(
        state, "dim_recruitment_stage", "Fase_Naam", "Stage_Key"
    )
    simulator._hire_source_names = simulator._build_reason_lookup(
        state, "dim_hire_source", "HireSource_Key", "Bron_Naam"
    )
    simulator._decline_reason_keys = {}
    simulator._rejection_reason_keys = {NOT_SELECTED_REASON: 5, BELOW_MINIMUM_QUALITY_REASON: 4}


def test_sample_decline_reason_favours_the_high_quality_bonus_reason():
    """A candidate above the quality threshold should overwhelmingly land on
    the reason carrying the quality bonus, not the flat 50/50 the base
    weights alone would produce."""
    simulator = RecruitmentSimulator(_config(), schema=None, rng=random.Random(1))

    picks = [simulator._sample_decline_reason(candidate_quality=4.5) for _ in range(200)]

    # Weight ratio is 6.0:1.0 (base 1.0 + bonus 5.0 vs. base 1.0), so the
    # expected share is ~86%; a generous floor keeps this from being flaky.
    assert picks.count("Ander aanbod geaccepteerd") > 150


def test_sample_decline_reason_ignores_the_bonus_below_the_quality_threshold():
    simulator = RecruitmentSimulator(_config(), schema=None, rng=random.Random(1))

    picks = [simulator._sample_decline_reason(candidate_quality=2.0) for _ in range(200)]
    count = picks.count("Ander aanbod geaccepteerd")

    # Without the bonus, both reasons carry weight 1.0 - roughly even split.
    assert 60 < count < 140


def test_sample_decline_reason_returns_none_when_unconfigured():
    simulator = RecruitmentSimulator(_config(decline_reasons=[]), schema=None, rng=random.Random(1))

    assert simulator._sample_decline_reason(candidate_quality=4.5) is None


def test_new_pipeline_application_routes_internal_candidates_straight_to_gesprek():
    """Internal candidates are already screened by eligible_internal before
    a candidate is even chosen, so they must skip Sollicitatie/Screening -
    unlike external candidates, who start at Sollicitatie."""
    simulator = RecruitmentSimulator(_config(), schema=None, rng=random.Random(1))
    state = _state_with_pipeline([])
    _prime_lookups(simulator, state)
    vacancy = _vacancy()
    source_internal = pd.Series({"HireSource_Key": 2, "Bron_Naam": "Interne mobiliteit"})
    source_external = pd.Series({"HireSource_Key": 1, "Bron_Naam": "Vacaturebank"})

    internal_row = simulator._new_pipeline_application(
        1, vacancy, pd.Timestamp("2024-02-01"), source_internal, 42,
        {"Kandidaat_Kwaliteit": 4.0}, RecruitmentSimulator.STAGE_GESPREK,
    )
    external_row = simulator._new_pipeline_application(
        2, vacancy, pd.Timestamp("2024-02-01"), source_external, None,
        {"Kandidaat_Kwaliteit": 3.0}, RecruitmentSimulator.STAGE_SOLLICITATIE,
    )

    assert internal_row["Stage_Key"] == simulator._stage_keys["Gesprek"]
    assert internal_row["Interview_Date"] == pd.Timestamp("2024-02-01")
    assert internal_row["Employee_Key"] == 42
    assert external_row["Stage_Key"] == simulator._stage_keys["Sollicitatie"]
    assert external_row["Interview_Date"] is None


def test_resolve_screening_advances_an_eligible_candidate_to_gesprek():
    simulator = RecruitmentSimulator(_config(), schema=None, rng=random.Random(1))
    state = _state_with_pipeline([
        _pipeline_row(Stage_Key=1, Application_Date=pd.Timestamp("2024-01-01")),
    ])
    state["_recruitment_pipeline_profiles"][1] = {
        "Relevante_Ervaring_Jaren": 10.0, "Qualifications": [],
    }
    _prime_lookups(simulator, state)
    target_role = pd.Series({
        "Functie_Naam": "Monteur", "Min_Relevante_Ervaring_Jr": 0.0,
        "Formele_Kwalificatie_Vereist": False, "Leidinggevend": False,
    })

    simulator._resolve_screening(state, _vacancy(), target_role, pd.Timestamp("2024-01-08"))

    row = state["fact_recruitment"].iloc[0]
    assert row["Stage_Key"] == simulator._stage_keys["Gesprek"]
    assert row["Screening_Date"] == pd.Timestamp("2024-01-08")
    assert row["Status"] == RecruitmentSimulator.IN_PROGRESS_STATUS
    # The profile must survive screening - it's still needed if this
    # candidate is eventually hired.
    assert 1 in state["_recruitment_pipeline_profiles"]


def test_resolve_screening_rejects_an_ineligible_candidate_with_the_causal_reason():
    simulator = RecruitmentSimulator(_config(), schema=None, rng=random.Random(1))
    state = _state_with_pipeline([
        _pipeline_row(Stage_Key=1, Application_Date=pd.Timestamp("2024-01-01")),
    ])
    state["_recruitment_pipeline_profiles"][1] = {
        "Relevante_Ervaring_Jaren": 0.0, "Qualifications": [],
    }
    _prime_lookups(simulator, state)
    simulator._rejection_reason_keys["Onvoldoende relevante werkervaring"] = 1
    target_role = pd.Series({
        "Functie_Naam": "Monteur", "Min_Relevante_Ervaring_Jr": 8.0,
        "Formele_Kwalificatie_Vereist": False, "Leidinggevend": False,
    })

    simulator._resolve_screening(state, _vacancy(), target_role, pd.Timestamp("2024-01-08"))

    row = state["fact_recruitment"].iloc[0]
    assert row["Status"] == RecruitmentSimulator.REJECTED_STATUS
    assert row["RejectionReason_Key"] == 1
    assert row["Decision_Date"] == pd.Timestamp("2024-01-08")
    # A terminal application's transient profile is cleaned up.
    assert 1 not in state["_recruitment_pipeline_profiles"]


def test_resolve_interview_promotes_the_longest_waiting_candidate_first():
    simulator = RecruitmentSimulator(_config(), schema=None, rng=random.Random(1))
    state = _state_with_pipeline([
        _pipeline_row(
            Recruitment_Key=1, Stage_Key=3, Kandidaat_Kwaliteit=4.0,
            Screening_Date=pd.Timestamp("2024-01-10"),
        ),
        _pipeline_row(
            Recruitment_Key=2, Stage_Key=3, Kandidaat_Kwaliteit=4.0,
            Screening_Date=pd.Timestamp("2024-01-05"),
        ),
    ])
    _prime_lookups(simulator, state)

    simulator._resolve_interview(state, _vacancy(), pd.Timestamp("2024-01-15"))

    fact = state["fact_recruitment"].set_index("Recruitment_Key")
    assert fact.loc[2, "Stage_Key"] == simulator._stage_keys["Aanbod"]
    assert fact.loc[2, "Interview_Date"] == pd.Timestamp("2024-01-15")
    assert fact.loc[2, "Offer_Date"] == pd.Timestamp("2024-01-15")
    assert pd.notna(fact.loc[2, "Dagen_Tot_Beslissing"])
    # The other waiting candidate is untouched this week.
    assert fact.loc[1, "Stage_Key"] == 3


def test_resolve_interview_does_nothing_while_an_offer_is_already_outstanding():
    simulator = RecruitmentSimulator(_config(), schema=None, rng=random.Random(1))
    state = _state_with_pipeline([
        _pipeline_row(Recruitment_Key=1, Stage_Key=4, Offer_Date=pd.Timestamp("2024-01-10")),
        _pipeline_row(Recruitment_Key=2, Stage_Key=3, Screening_Date=pd.Timestamp("2024-01-05")),
    ])
    _prime_lookups(simulator, state)

    simulator._resolve_interview(state, _vacancy(), pd.Timestamp("2024-01-15"))

    fact = state["fact_recruitment"].set_index("Recruitment_Key")
    assert fact.loc[2, "Stage_Key"] == 3  # never even evaluated


def test_resolve_interview_rejects_a_candidate_below_the_quality_bar():
    config = _config(source_profiles={"Vacaturebank": {"minimum_offer_quality": 4.5}})
    simulator = RecruitmentSimulator(config, schema=None, rng=random.Random(1))
    state = _state_with_pipeline([
        _pipeline_row(Stage_Key=3, Kandidaat_Kwaliteit=2.0, Screening_Date=pd.Timestamp("2024-01-05")),
    ])
    _prime_lookups(simulator, state)

    simulator._resolve_interview(state, _vacancy(), pd.Timestamp("2024-01-15"))

    row = state["fact_recruitment"].iloc[0]
    assert row["Status"] == RecruitmentSimulator.REJECTED_STATUS
    assert row["RejectionReason_Key"] == simulator._rejection_reason_keys[BELOW_MINIMUM_QUALITY_REASON]
    assert row["Interview_Date"] == pd.Timestamp("2024-01-15")


def test_resolve_offer_waits_until_the_scheduled_decision_date():
    simulator = RecruitmentSimulator(_config(), schema=None, rng=random.Random(1))
    state = _state_with_pipeline([
        _pipeline_row(Stage_Key=4, Offer_Date=pd.Timestamp("2024-01-10"), Dagen_Tot_Beslissing=5),
    ])
    _prime_lookups(simulator, state)

    accepted = simulator._resolve_offer(state, _vacancy(), pd.Timestamp("2024-01-12"))

    assert accepted is None
    assert state["fact_recruitment"].iloc[0]["Status"] == RecruitmentSimulator.IN_PROGRESS_STATUS


def test_resolve_offer_accepts_once_the_decision_date_arrives():
    config = _config()
    simulator = RecruitmentSimulator(config, schema=None, rng=random.Random(1))
    state = _state_with_pipeline([
        _pipeline_row(
            Recruitment_Key=7, Stage_Key=4, Offer_Date=pd.Timestamp("2024-01-10"),
            Dagen_Tot_Beslissing=5, Kandidaat_Kwaliteit=4.0,
        ),
    ])
    state["_recruitment_pipeline_profiles"][7] = {
        "Education_Key": 3, "Relevante_Ervaring_Jaren": 6.0,
    }
    _prime_lookups(simulator, state)

    accepted = simulator._resolve_offer(state, _vacancy(), pd.Timestamp("2024-01-15"))

    assert accepted["Recruitment_Key"] == 7
    assert accepted["Education_Key"] == 3
    assert accepted["Relevante_Ervaring_Jaren"] == 6.0
    row = state["fact_recruitment"].iloc[0]
    assert row["Status"] == RecruitmentSimulator.ACCEPTED_STATUS
    assert row["Decision_Date"] == pd.Timestamp("2024-01-15")
    assert 7 not in state["_recruitment_pipeline_profiles"]


def test_resolve_offer_declines_and_samples_a_reason():
    config = _config(source_profiles={"Vacaturebank": {"candidate_decline_rate": 1.0}})
    simulator = RecruitmentSimulator(config, schema=None, rng=random.Random(1))
    simulator._decline_reason_keys = {"Ander aanbod geaccepteerd": 1, "Persoonlijke omstandigheden": 2}
    state = _state_with_pipeline([
        _pipeline_row(Stage_Key=4, Offer_Date=pd.Timestamp("2024-01-10"), Dagen_Tot_Beslissing=5),
    ])
    _prime_lookups(simulator, state)
    simulator._decline_reason_keys = {"Ander aanbod geaccepteerd": 1, "Persoonlijke omstandigheden": 2}

    accepted = simulator._resolve_offer(state, _vacancy(), pd.Timestamp("2024-01-15"))

    assert accepted is None
    row = state["fact_recruitment"].iloc[0]
    assert row["Status"] == RecruitmentSimulator.DECLINED_STATUS
    assert row["DeclineReason_Key"] in {1, 2}


def test_close_out_remaining_pipeline_rejects_everyone_else_as_not_selected():
    simulator = RecruitmentSimulator(_config(), schema=None, rng=random.Random(1))
    state = _state_with_pipeline([
        _pipeline_row(Recruitment_Key=1, Stage_Key=1),
        _pipeline_row(Recruitment_Key=2, Stage_Key=3),
    ])
    _prime_lookups(simulator, state)

    simulator._close_out_remaining_pipeline(state, 100, pd.Timestamp("2024-01-20"))

    fact = state["fact_recruitment"]
    assert (fact["Status"] == RecruitmentSimulator.REJECTED_STATUS).all()
    assert (fact["RejectionReason_Key"] == simulator._rejection_reason_keys[NOT_SELECTED_REASON]).all()


def test_full_funnel_hires_someone_over_several_simulated_weeks():
    """End-to-end regression guard: with realistic config, running the
    simulator week over week should carry at least one application all the
    way through Sollicitatie -> Screening -> Gesprek -> Aanbod -> Aangenomen,
    with every stage/reason column populated consistently."""
    config = ConfigLoader().load()
    state = {
        "dim_department": pd.DataFrame({"Department_Key": [1], "Afdeling_Naam": ["Techniek"]}),
        "dim_role": pd.DataFrame({
            "Role_Key": [1], "Department_Key": [1], "Functie_Naam": ["Monteur"],
            "SalaryScale_Key": [1], "Leidinggevend": [False],
            "Min_Relevante_Ervaring_Jr": [0.0], "Formele_Kwalificatie_Vereist": [False],
            "Min_Opleidingsniveau": ["Geen"], "Min_Leidinggevende_Ervaring_Jr": [0.0],
        }),
        "dim_hire_source": pd.DataFrame(config.dim_hire_source),
        "dim_recruitment_status": pd.DataFrame(config.dim_recruitment_status),
        "dim_recruitment_stage": pd.DataFrame(config.dim_recruitment_stage),
        "dim_decline_reason": pd.DataFrame(config.dim_decline_reason),
        "dim_rejection_reason": pd.DataFrame(config.dim_rejection_reason),
        "dim_education": pd.DataFrame(config.dim_education),
        "dim_candidate_quality_driver": pd.DataFrame(config.dim_candidate_quality_driver),
        "fact_employment": pd.DataFrame(),
        "fact_vacancy": pd.DataFrame({
            "Vacancy_Key": [1], "Created_Date": [pd.Timestamp("2024-01-01")], "Closed_Date": [None],
            "Role_Key": [1], "Department_Key": [1], "Vacature_Reden": ["Groei"], "Status": ["Open"],
            "Target_Start_Date": [pd.Timestamp("2024-02-01")], "Filled_Employee_Key": [None],
        }),
        "fact_recruitment": pd.DataFrame(),
    }
    rng = random.Random(3)
    hired = False
    for week in range(30):
        state = RecruitmentSimulator(config, schema=None, rng=rng).run(
            state, pd.Timestamp("2024-01-01") + pd.Timedelta(weeks=week)
        )
        if state["_accepted_applications"]:
            hired = True
            break

    assert hired, "no application reached Aangenomen within 30 simulated weeks"
    fact = state["fact_recruitment"]
    assert (fact.loc[fact["Status"] == "Aangenomen", "Stage_Key"] == 4).all()
    # Every terminal row has a Decision_Date; every rejected row has a reason.
    terminal = fact[fact["Status"] != RecruitmentSimulator.IN_PROGRESS_STATUS]
    assert terminal["Decision_Date"].notna().all()
    assert fact.loc[fact["Status"] == "Afgewezen", "RejectionReason_Key"].notna().all()
