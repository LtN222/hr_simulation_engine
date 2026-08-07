"""Synchronise employee-level service dates and employment status.

``fact_employment`` contains an event history: promotions, transfers and salary
reviews create a new employment record for the same employee.  The employee
dimension therefore owns the stable service dates and current employment flag.
"""

import pandas as pd


EMPLOYEE_STATUS_COLUMNS = {
    "Eerste_Indienst_Datum": pd.NaT,
    "Aaneengesloten_Indienst_Datum": pd.NaT,
    "Datum_uitdienst": pd.NaT,
    "In_Dienst": False
}


def sync_employee_employment_status(state):
    """Derive current employee status from the complete employment history.

    ``Eerste_Indienst_Datum`` never changes for a known employee.  The
    continuous-service date follows the active chain through
    ``Previous_Employment_Key`` so internal employee events do not reset it.
    A later rehire starts a new continuous-service period while retaining the
    original first-employment date.
    """
    employees = state.get("dim_employee", pd.DataFrame()).copy()
    employment = state.get("fact_employment", pd.DataFrame()).copy()

    if employees.empty:
        state["dim_employee"] = employees
        return state

    for column, default in EMPLOYEE_STATUS_COLUMNS.items():
        if column not in employees.columns:
            employees[column] = default

    if employment.empty:
        employees["In_Dienst"] = False
        state["dim_employee"] = employees
        return state

    employment["Startdatum"] = pd.to_datetime(
        employment["Startdatum"], errors="coerce"
    ).dt.normalize()
    if "Einddatum" in employment.columns:
        employment["Einddatum"] = pd.to_datetime(
            employment["Einddatum"], errors="coerce"
        ).dt.normalize()
    else:
        employment["Einddatum"] = pd.NaT

    updates = {}
    for employee_key, history in employment.groupby("Employee_Key"):
        history = history.sort_values(
            ["Startdatum", "Employment_Key"],
            na_position="last"
        )
        active = history[
            history["Dienstverband_status"] == "Actief"
        ]
        current = active.iloc[-1] if not active.empty else history.iloc[-1]
        first_start = history["Startdatum"].min()
        is_employed = not active.empty

        updates[employee_key] = {
            "Eerste_Indienst_Datum": first_start,
            "Aaneengesloten_Indienst_Datum": _continuous_service_start(
                current,
                history
            ),
            "Datum_uitdienst": (
                pd.NaT
                if is_employed
                else history["Einddatum"].max()
            ),
            "In_Dienst": is_employed
        }

    for column in EMPLOYEE_STATUS_COLUMNS:
        employees[column] = employees["Employee_Key"].map(
            {key: values[column] for key, values in updates.items()}
        ).where(
            employees["Employee_Key"].isin(updates),
            employees[column]
        )

    state["dim_employee"] = employees
    return state


def _continuous_service_start(current, history):
    """Follow one employment-event chain back to its service-period start."""
    # Keep the key as a column as well as the index.  Rows retrieved through
    # ``.loc`` must retain their own key for the cycle detection below.
    rows_by_key = history.set_index("Employment_Key", drop=False)
    chain_starts = []
    row = current
    seen_keys = set()

    while True:
        chain_starts.append(row["Startdatum"])
        employment_key = row.get("Employment_Key")
        previous_key = row.get("Previous_Employment_Key")

        if (
            pd.isna(previous_key)
            or employment_key in seen_keys
            or previous_key not in rows_by_key.index
        ):
            break

        seen_keys.add(employment_key)
        row = rows_by_key.loc[previous_key]

    return min(date for date in chain_starts if pd.notna(date))
