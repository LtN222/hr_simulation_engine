import pandas as pd

from src.infrastructure.workforce_snapshot import _active_employment

D = pd.Timestamp


def _row(key, employee, start, end, status="Actief", event="Aanname"):
    return {
        "Employment_Key": key, "Employee_Key": employee,
        "Startdatum": D(start), "Einddatum": D(end) if end else pd.NaT,
        "Dienstverband_status": status, "EventType": event,
    }


def _leaver(first_key, employee, hired, left):
    """A closed employment row plus the zero-length terminal 'Uit dienst' row."""
    return [
        _row(first_key, employee, hired, left, status="Inactief"),
        _row(first_key + 1, employee, left, left, status="Uit dienst", event="Uit dienst"),
    ]


def _employees(employment, date):
    active = _active_employment(pd.DataFrame(employment), D(date))
    return set(active["Employee_Key"])


def test_a_leaver_on_the_month_end_is_not_in_that_months_snapshot():
    employment = _leaver(1, 1, "2020-01-01", "2024-01-31")

    assert _employees(employment, "2023-12-31") == {1}
    assert _employees(employment, "2024-01-31") == set()
    assert _employees(employment, "2024-02-29") == set()


def test_a_leaver_mid_month_is_gone_at_that_month_end():
    employment = _leaver(1, 1, "2020-01-01", "2024-01-15")

    assert _employees(employment, "2023-12-31") == {1}
    assert _employees(employment, "2024-01-31") == set()


def test_the_terminal_uit_dienst_row_is_never_the_snapshot_row():
    employment = _leaver(1, 1, "2020-01-01", "2024-01-31")
    frame = pd.DataFrame(employment)

    for date in ("2023-12-31", "2024-01-31", "2024-02-29"):
        active = _active_employment(frame, D(date))
        assert "Uit dienst" not in set(active["Dienstverband_status"])


def test_a_hire_on_the_month_end_is_counted_in_that_months_snapshot():
    employment = [_row(1, 1, "2024-01-31", None)]

    assert _employees(employment, "2023-12-31") == set()
    assert _employees(employment, "2024-01-31") == {1}


def test_a_promotion_on_the_month_end_still_gives_one_row_the_new_one():
    employment = [
        _row(1, 1, "2020-01-01", "2024-01-31", status="Inactief"),
        _row(2, 1, "2024-01-31", None, event="Promotie"),
    ]
    active = _active_employment(pd.DataFrame(employment), D("2024-01-31"))

    assert list(active["Employment_Key"]) == [2]


def test_stock_flow_reconciles_headcount_over_consecutive_month_ends():
    employment = (
        [_row(1, 1, "2020-01-01", None), _row(2, 2, "2020-01-01", None)]
        + _leaver(3, 3, "2021-01-01", "2024-01-31")     # leaves exactly on a month-end
        + _leaver(5, 4, "2021-01-01", "2024-02-10")     # leaves mid-month
        + [_row(7, 5, "2024-02-29", None)]              # hired on a month-end
        + [_row(8, 6, "2024-02-05", None)]              # hired mid-month
        + _leaver(9, 7, "2024-02-12", "2024-02-29")     # hired and left within the month
    )
    month_ends = ["2023-12-31", "2024-01-31", "2024-02-29", "2024-03-31"]
    headcount = [len(_employees(employment, date)) for date in month_ends]
    frame = pd.DataFrame(employment)

    def hires(start, end):
        first = frame[frame["EventType"] == "Aanname"].groupby("Employee_Key")["Startdatum"].min()
        return int(((first > D(start)) & (first <= D(end))).sum())

    def leavers(start, end):
        gone = frame[frame["Dienstverband_status"] == "Uit dienst"]["Startdatum"]
        return int(((gone > D(start)) & (gone <= D(end))).sum())

    for index in range(1, len(month_ends)):
        start, end = month_ends[index - 1], month_ends[index]
        assert headcount[index] == headcount[index - 1] + hires(start, end) - leavers(start, end)
