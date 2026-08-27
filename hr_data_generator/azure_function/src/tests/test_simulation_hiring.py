import pandas as pd

from src.simulation.simulation_hiring import HiringSimulator
from src.simulation.simulation_recruitment import NOT_SELECTED_REASON, RecruitmentSimulator


def _config():
    base = {"structure": {"Directie": {"CEO": {"max_count": 1}}}}
    return type("Config", (), base)()


def _simulator():
    return HiringSimulator(_config(), schema=None, rng=None, event_type_map={})


def test_has_capacity_for_hire_blocks_a_hire_into_an_already_full_capped_role():
    simulator = _simulator()

    assert simulator._has_capacity_for_hire(
        state={}, department_name="Directie", role_name="CEO",
        role_counts={2: 1}, role_key=2,
    ) is False


def test_has_capacity_for_hire_allows_a_hire_when_the_capped_seat_is_still_open():
    simulator = _simulator()

    assert simulator._has_capacity_for_hire(
        state={}, department_name="Directie", role_name="CEO",
        role_counts={2: 0}, role_key=2,
    ) is True


def test_has_capacity_for_hire_allows_a_hire_into_an_uncapped_role():
    simulator = _simulator()
    simulator.config.structure["Directie"]["CEO"] = {}  # no max_count configured

    assert simulator._has_capacity_for_hire(
        state={}, department_name="Directie", role_name="CEO",
        role_counts={2: 50}, role_key=2,
    ) is True


def test_close_vacancy_without_hire_closes_it_with_no_filled_employee():
    """The final backstop: a role filled up (e.g. via a direct internal
    promotion) while an offer for it was still in the recruitment funnel.
    The vacancy must be closed, but never attributed to an employee who was
    never actually hired through it."""
    simulator = _simulator()
    state = {
        "fact_vacancy": pd.DataFrame({
            "Vacancy_Key": [1, 2],
            "Status": ["Open", "Open"],
            "Closed_Date": [None, None],
        }),
    }

    simulator._close_vacancy_without_hire(state, vacancy_key=1, today=pd.Timestamp("2024-01-01"))

    vacancy = state["fact_vacancy"]
    closed = vacancy.loc[vacancy["Vacancy_Key"] == 1].iloc[0]
    assert closed["Status"] == "Gesloten"
    assert closed["Closed_Date"] == pd.Timestamp("2024-01-01")
    still_open = vacancy.loc[vacancy["Vacancy_Key"] == 2].iloc[0]
    assert still_open["Status"] == "Open"


def test_close_vacancy_without_hire_also_closes_out_the_rest_of_the_pipeline():
    """A vacancy closed this way (filled another way, offer moot) must not
    leave any other in-progress applications for it stuck 'In behandeling'
    forever - a closed vacancy is never visited by the funnel again."""
    simulator = _simulator()
    state = {
        "fact_vacancy": pd.DataFrame({
            "Vacancy_Key": [1], "Status": ["Open"], "Closed_Date": [None],
        }),
        "fact_recruitment": pd.DataFrame({
            "Recruitment_Key": [10, 11, 12],
            "Vacancy_Key": [1, 1, 2],
            "Status": [
                RecruitmentSimulator.IN_PROGRESS_STATUS,
                RecruitmentSimulator.IN_PROGRESS_STATUS,
                RecruitmentSimulator.IN_PROGRESS_STATUS,
            ],
            "RecruitmentStatus_Key": [None, None, None],
            "Decision_Date": [None, None, None],
            "RejectionReason_Key": [None, None, None],
        }),
        "dim_rejection_reason": pd.DataFrame({
            "Afwijzingsreden_Naam": [NOT_SELECTED_REASON],
            "RejectionReason_Key": [5],
        }),
        "dim_recruitment_status": pd.DataFrame({
            "Status_Naam": ["Afgewezen"],
            "RecruitmentStatus_Key": [2],
        }),
    }

    simulator._close_vacancy_without_hire(state, vacancy_key=1, today=pd.Timestamp("2024-01-01"))

    fact = state["fact_recruitment"].set_index("Recruitment_Key")
    assert fact.loc[10, "Status"] == RecruitmentSimulator.REJECTED_STATUS
    assert fact.loc[10, "RejectionReason_Key"] == 5
    assert fact.loc[10, "RecruitmentStatus_Key"] == 2
    assert fact.loc[11, "Status"] == RecruitmentSimulator.REJECTED_STATUS
    # A different vacancy's pipeline is left untouched.
    assert fact.loc[12, "Status"] == RecruitmentSimulator.IN_PROGRESS_STATUS
