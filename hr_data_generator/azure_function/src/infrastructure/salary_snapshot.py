import pandas as pd

from src.infrastructure.record_builder import build_record


def build_salary_snapshots(state, schema, start_date=None, end_date=None):
    """Build monthly salary snapshots for salary trend visuals.

    fact_employment is event/history oriented. Grouping salary by Startdatum
    shows the salaries of events that started in that month, not the salaries of
    all active employees in that month. This snapshot table gives Power BI a
    stable monthly grain: one active employee salary per month-end date.
    """

    fact_employment = state.get("fact_employment", pd.DataFrame())

    if fact_employment.empty:
        state["fact_salary_snapshot"] = pd.DataFrame()
        return state

    employment = fact_employment.copy()
    employment["Startdatum"] = pd.to_datetime(employment["Startdatum"])
    employment["Einddatum"] = pd.to_datetime(
        employment["Einddatum"],
        errors="coerce"
    )

    if start_date is None:
        start_date = employment["Startdatum"].min()

    if end_date is None:
        active_end = employment["Einddatum"].dropna().max()
        end_date = max(
            date
            for date in [pd.Timestamp.today(), active_end]
            if pd.notna(date)
        )

    snapshot_dates = pd.date_range(
        pd.Timestamp(start_date).to_period("M").to_timestamp("M"),
        pd.Timestamp(end_date).to_period("M").to_timestamp("M"),
        freq="ME"
    )

    records = []
    snapshot_key = 1

    for snapshot_date in snapshot_dates:
        active = employment[
            (employment["Startdatum"] <= snapshot_date)
            & (
                employment["Einddatum"].isna()
                | (employment["Einddatum"] >= snapshot_date)
            )
        ].copy()

        if active.empty:
            continue

        active = active.sort_values(["Employee_Key", "Startdatum"])
        active = active.drop_duplicates(subset=["Employee_Key"], keep="last")

        for _, row in active.iterrows():
            records.append(
                build_record(
                    schema,
                    "fact_salary_snapshot",
                    {
                        "SalarySnapshot_Key": snapshot_key,
                        "Snapshot_Date": snapshot_date,
                        "Employee_Key": row["Employee_Key"],
                        "Employment_Key": row["Employment_Key"],
                        "Role_Key": row["Role_Key"],
                        "Department_Key": _department_for_role(state, row["Role_Key"]),
                        "Salaris": row["Salaris"]
                    }
                )
            )
            snapshot_key += 1

    state["fact_salary_snapshot"] = pd.DataFrame(records)
    return state


def _department_for_role(state, role_key):
    dim_role = state["dim_role"]
    return dim_role.loc[
        dim_role["Role_Key"] == role_key,
        "Department_Key"
    ].iloc[0]
