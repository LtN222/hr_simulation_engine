"""Persist employee attributes that are needed to analyse departure events."""

import pandas as pd


def sync_employment_hire_sources(state):
    """Stamp the immutable original hire source onto every employment event.

    Hire source belongs to the employee, but is deliberately copied to the
    event fact as a degenerate event context. This gives departure measures a
    direct star-schema filter path from ``dim_hire_source`` to
    ``fact_employment``.
    """
    employment = state.get("fact_employment", pd.DataFrame()).copy()
    employees = state.get("dim_employee", pd.DataFrame())
    required_columns = {"Employee_Key", "HireSource_Key"}

    if employment.empty or not required_columns.issubset(employees.columns):
        return state

    source_by_employee = (
        employees.drop_duplicates(subset=["Employee_Key"], keep="last")
        .set_index("Employee_Key")["HireSource_Key"]
    )
    original_source = employment.get(
        "HireSource_Key",
        pd.Series(index=employment.index, dtype="object")
    )
    employment["HireSource_Key"] = employment["Employee_Key"].map(
        source_by_employee
    ).combine_first(original_source)
    state["fact_employment"] = employment
    return state


def sync_departure_satisfaction(state):
    """Copy each leaver's last available workforce snapshot onto its exit event.

    Workforce snapshots intentionally contain only employees who were active at
    month-end. At departure, the most recent snapshot on or before the exit
    date is therefore the last reported satisfaction observation. Persisting it
    on the departure event keeps attrition analysis independent of fact-to-fact
    relationships.
    """
    employment = state.get("fact_employment", pd.DataFrame()).copy()
    snapshots = state.get("fact_workforce_snapshot", pd.DataFrame()).copy()
    required_snapshot_columns = {
        "Employee_Key",
        "Snapshot_Date",
        "Tevredenheid_Score",
        "SatisfactionBand_Key",
    }

    if employment.empty or not required_snapshot_columns.issubset(snapshots.columns):
        return state
    has_engagement_context = {
        "Betrokkenheid_Score",
        "EngagementBand_Key",
    }.issubset(snapshots.columns)

    for column in (
        "Tevredenheid_Score_Bij_Uitdienst",
        "SatisfactionBand_Key_Bij_Uitdienst",
        "Betrokkenheid_Score_Bij_Uitdienst",
        "EngagementBand_Key_Bij_Uitdienst",
    ):
        if column not in employment.columns:
            employment[column] = None

    employment["Einddatum"] = pd.to_datetime(
        employment.get("Einddatum"), errors="coerce"
    )
    snapshots["Snapshot_Date"] = pd.to_datetime(
        snapshots["Snapshot_Date"], errors="coerce"
    )
    snapshots = snapshots.dropna(subset=["Snapshot_Date"])
    snapshots_by_employee = {
        employee_key: group.sort_values("Snapshot_Date")
        for employee_key, group in snapshots.groupby("Employee_Key")
    }

    departure_mask = (
        employment["Dienstverband_status"].eq("Uit dienst")
        & employment["Einddatum"].notna()
    )
    for index, departure in employment.loc[departure_mask].iterrows():
        existing_score = pd.to_numeric(
            departure.get("Tevredenheid_Score_Bij_Uitdienst"),
            errors="coerce"
        )
        existing_band = pd.to_numeric(
            departure.get("SatisfactionBand_Key_Bij_Uitdienst"),
            errors="coerce"
        )
        existing_engagement = pd.to_numeric(
            departure.get("Betrokkenheid_Score_Bij_Uitdienst"),
            errors="coerce"
        )
        existing_engagement_band = pd.to_numeric(
            departure.get("EngagementBand_Key_Bij_Uitdienst"),
            errors="coerce"
        )
        context_values = (
            existing_score,
            existing_band,
        ) + (
            (existing_engagement, existing_engagement_band)
            if has_engagement_context else ()
        )
        if all(pd.notna(value) for value in context_values):
            continue

        employee_snapshots = snapshots_by_employee.get(
            departure["Employee_Key"]
        )
        if employee_snapshots is None:
            continue

        known_snapshots = employee_snapshots[
            employee_snapshots["Snapshot_Date"] <= departure["Einddatum"]
        ]
        if known_snapshots.empty:
            continue

        last_snapshot = known_snapshots.iloc[-1]
        if pd.isna(existing_score):
            employment.loc[index, "Tevredenheid_Score_Bij_Uitdienst"] = (
                last_snapshot["Tevredenheid_Score"]
            )
        if pd.isna(existing_band):
            employment.loc[index, "SatisfactionBand_Key_Bij_Uitdienst"] = (
                last_snapshot["SatisfactionBand_Key"]
            )
        if has_engagement_context and pd.isna(existing_engagement):
            employment.loc[index, "Betrokkenheid_Score_Bij_Uitdienst"] = (
                last_snapshot["Betrokkenheid_Score"]
            )
        if has_engagement_context and pd.isna(existing_engagement_band):
            employment.loc[index, "EngagementBand_Key_Bij_Uitdienst"] = (
                last_snapshot["EngagementBand_Key"]
            )

    state["fact_employment"] = employment
    return state
