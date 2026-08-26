"""Maintain effective-dated manager assignments for historical reporting."""

import pandas as pd

from src.infrastructure.record_builder import build_record


def sync_manager_assignments(state, schema, effective_date):
    """Close changed assignments and open the manager relation active today.

    ``dim_employee[Manager_Key]`` remains the current operational assignment.
    This fact preserves its history so monthly workforce snapshots do not
    retrospectively show an employee's current manager in earlier periods.
    """
    today = pd.Timestamp(effective_date).normalize()
    employees = state.get("dim_employee", pd.DataFrame())
    employment = state.get("fact_employment", pd.DataFrame())
    existing = state.get("fact_manager_assignment", pd.DataFrame()).copy()

    if employees.empty or employment.empty:
        state["fact_manager_assignment"] = existing
        return state

    active_employee_keys = _active_employee_keys(employment, today)
    assignments = _current_assignments(employees, active_employee_keys)
    if existing.empty:
        existing = pd.DataFrame(columns=[
            "ManagerAssignment_Key", "Employee_Key", "Manager_Key",
            "Startdatum", "Einddatum"
        ])
    else:
        existing["Startdatum"] = pd.to_datetime(
            existing["Startdatum"],
            errors="coerce"
        )
        existing["Einddatum"] = pd.to_datetime(
            existing["Einddatum"],
            errors="coerce"
        )

    records = []
    next_key = _next_key(existing)
    open_rows = existing[existing["Einddatum"].isna()]

    # Employees who left no longer have an active assignment.
    for index, row in open_rows.iterrows():
        if int(row["Employee_Key"]) not in assignments:
            existing.loc[index, "Einddatum"] = today

    for employee_key, manager_key in assignments.items():
        employee_rows = open_rows[
            open_rows["Employee_Key"].astype("Int64") == employee_key
        ]
        if employee_rows.empty:
            records.append(_record(
                schema,
                next_key,
                employee_key,
                manager_key,
                today
            ))
            next_key += 1
            continue

        current = employee_rows.sort_values("Startdatum").iloc[-1]
        if _same_key(current.get("Manager_Key"), manager_key):
            continue

        current_index = current.name
        if pd.Timestamp(current["Startdatum"]).normalize() == today:
            # A repeated call on the same day should update the newly created
            # assignment instead of producing an invalid zero-day interval.
            existing.loc[current_index, "Manager_Key"] = manager_key
            continue

        existing.loc[current_index, "Einddatum"] = today - pd.Timedelta(days=1)
        records.append(_record(
            schema,
            next_key,
            employee_key,
            manager_key,
            today
        ))
        next_key += 1

    if records:
        existing = pd.concat([existing, pd.DataFrame(records)], ignore_index=True)

    state["fact_manager_assignment"] = existing
    return state


def manager_as_of(assignments, employee_key, snapshot_date):
    """Return the manager assigned to an employee on a given date."""
    if assignments.empty:
        return None

    date = pd.Timestamp(snapshot_date).normalize()
    matches = assignments[(assignments["Employee_Key"] == employee_key) & (
        assignments["Startdatum"] <= date
    ) & (
        assignments["Einddatum"].isna() | (assignments["Einddatum"] >= date)
    )]
    if matches.empty:
        return None

    value = matches.sort_values("Startdatum").iloc[-1].get("Manager_Key")
    return None if pd.isna(value) else int(value)


def _active_employee_keys(employment, today):
    current = employment.copy()
    current["Startdatum"] = pd.to_datetime(current["Startdatum"], errors="coerce")
    current["Einddatum"] = pd.to_datetime(current["Einddatum"], errors="coerce")
    current = current[(current["Startdatum"] <= today) & (
        current["Einddatum"].isna() | (current["Einddatum"] >= today)
    )]
    if "Dienstverband_status" in current.columns:
        current = current[current["Dienstverband_status"] == "Actief"]
    return set(current["Employee_Key"].dropna().astype(int))


def _current_assignments(employees, active_employee_keys):
    if "Manager_Key" not in employees.columns:
        return {}

    active = employees[employees["Employee_Key"].isin(active_employee_keys)]
    return {
        int(row["Employee_Key"]): _normalise_key(row.get("Manager_Key"))
        for _, row in active.iterrows()
    }


def _next_key(assignments):
    if assignments.empty or "ManagerAssignment_Key" not in assignments.columns:
        return 1
    values = pd.to_numeric(assignments["ManagerAssignment_Key"], errors="coerce")
    return int(values.max()) + 1 if values.notna().any() else 1


def _record(schema, key, employee_key, manager_key, start_date):
    return build_record(schema, "fact_manager_assignment", {
        "ManagerAssignment_Key": key,
        "Employee_Key": employee_key,
        "Manager_Key": manager_key,
        "Startdatum": start_date,
        "Einddatum": None
    })


def _normalise_key(value):
    return None if pd.isna(value) else int(value)


def _same_key(left, right):
    return _normalise_key(left) == _normalise_key(right)
