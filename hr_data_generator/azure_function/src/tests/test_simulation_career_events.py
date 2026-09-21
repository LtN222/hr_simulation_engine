import pandas as pd

from src.simulation.simulation_career_events import (
    _is_active_role,
    _new_employment_record,
    _under_capacity,
)


class _StubSalaryPolicy:
    """A benchmark that returns a normal, realistic salary - any bug that
    lets some unrelated small integer (like a department key) leak into
    `_new_employment_record`'s salary must show up against this."""

    def employee_benchmark(self, role, today, service_start):
        return {"Benchmark_Salaris": 50000, "SalaryScale_Key": role["SalaryScale_Key"]}


def _config():
    base = {
        "structure": {
            "Directie": {"CEO": {"max_count": 1}},
        },
        "dim_location": {},
    }
    return type("Config", (), base)()


def _department_lookup():
    return pd.DataFrame({
        "Department_Key": [1],
        "Afdeling_Naam": ["Directie"],
    }).set_index("Department_Key")


def _target_role():
    return pd.Series({"Role_Key": 2, "Functie_Naam": "CEO", "Department_Key": 1})


def test_under_capacity_blocks_a_promotion_into_an_already_full_capped_role():
    config = _config()
    state = {}
    role_counts = {2: 1}  # CEO already filled its one seat

    assert _under_capacity(
        state, config, _department_lookup(), role_counts, _target_role()
    ) is False


def test_under_capacity_allows_a_promotion_when_the_capped_seat_is_still_open():
    config = _config()
    state = {}
    role_counts = {2: 0}

    assert _under_capacity(
        state, config, _department_lookup(), role_counts, _target_role()
    ) is True


def test_under_capacity_allows_a_promotion_into_an_uncapped_role():
    config = _config()
    config.structure["Directie"]["CEO"] = {}  # no max_count configured
    state = {}
    role_counts = {2: 50}

    assert _under_capacity(
        state, config, _department_lookup(), role_counts, _target_role()
    ) is True


def _dim_role_for_gate():
    return pd.DataFrame({
        "Role_Key": [1, 2],
        "Functie_Naam": ["Teamleider", "IT Manager"],
        "Afdeling_Naam": ["Directie", "IT"],
        "Department_Key": [1, 2],
    })


def test_is_active_role_blocks_an_internal_move_before_the_company_reaches_the_threshold():
    """Regression guard: a full production run found `Senior
    Applicatiebeheerder` (active_from_headcount 280) filled via an internal
    Promotie at company headcount ~165 - the growth-vacancy path already
    checks `role_is_active`, but nothing equivalent gated internal
    promotions/transfers, so a gated role could be reached ~2 years early."""
    config = type("Config", (), {
        "structure": {"IT": {"IT Manager": {"active_from_headcount": 280}}},
    })()
    target_role = pd.Series({
        "Role_Key": 2, "Functie_Naam": "IT Manager", "Department_Key": 2,
        "Afdeling_Naam": "IT",
    })

    assert _is_active_role(
        config, _dim_role_for_gate(), target_role,
        company_headcount=165, role_counts={1: 165},
    ) is False


def test_is_active_role_allows_an_internal_move_once_the_threshold_is_reached():
    config = type("Config", (), {
        "structure": {"IT": {"IT Manager": {"active_from_headcount": 280}}},
    })()
    target_role = pd.Series({
        "Role_Key": 2, "Functie_Naam": "IT Manager", "Department_Key": 2,
        "Afdeling_Naam": "IT",
    })

    assert _is_active_role(
        config, _dim_role_for_gate(), target_role,
        company_headcount=280, role_counts={1: 280},
    ) is True


def test_is_active_role_allows_a_role_with_no_configured_threshold():
    config = type("Config", (), {
        "structure": {"IT": {"IT Manager": {}}},
    })()
    target_role = pd.Series({
        "Role_Key": 2, "Functie_Naam": "IT Manager", "Department_Key": 2,
        "Afdeling_Naam": "IT",
    })

    assert _is_active_role(
        config, _dim_role_for_gate(), target_role,
        company_headcount=1, role_counts={},
    ) is True


def test_new_employment_record_computes_salary_from_the_benchmark_not_the_previous_department_key():
    """Regression guard for a positional-argument bug: the promotion and
    transfer call sites in `simulate_career_events` used to pass the
    employee's previous department key as a bare positional argument, which
    landed on `salary_override` (the next parameter in the signature)
    instead of `previous_department_key` (two further along). Since a
    department key is always a small truthy integer, `salary_override or
    ...` silently used it as the new salary on every promotion and transfer -
    e.g. an employee moving out of department 3 was paid a salary of 3."""
    previous_row = pd.Series({
        "Employment_Key": 10,
        "Employee_Key": 1,
        "HireSource_Key": 1,
        "Location_Key": 1,
        "Contracttype": "Vast",
        "Contracturen": 40,
        "Contract_einddatum": None,
        "Contract_ronde": None,
    })
    role = pd.Series({"Role_Key": 5, "Department_Key": 7, "SalaryScale_Key": 2})

    record = _new_employment_record(
        previous_row,
        employment_key=11,
        role=role,
        today=pd.Timestamp("2024-01-01"),
        event_type_key=99,
        salary_policy=_StubSalaryPolicy(),
        config=None,
        service_start=pd.Timestamp("2020-01-01"),
        target_ratio=1.0,
        ploegendienst_key=None,
        previous_department_key=3,  # the employee's OLD department key
    )

    assert record["Salaris"] == 50000
