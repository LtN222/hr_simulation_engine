import pandas as pd


def sync_recruitment_status_keys(state):
    """Backfill the recruitment status key for pre-dimension history.

    ``Status`` stays in the fact temporarily for backwards-compatible Power BI
    visuals. This helper lets incremental runs populate the new conformed key
    for rows created before ``dim_recruitment_status`` existed.
    """
    recruitment = state.get("fact_recruitment", pd.DataFrame())
    statuses = state.get("dim_recruitment_status", pd.DataFrame())
    if (
        recruitment.empty
        or "Status" not in recruitment.columns
        or not {"Status_Naam", "RecruitmentStatus_Key"}.issubset(
            statuses.columns
        )
    ):
        return state

    lookup = statuses.set_index("Status_Naam")["RecruitmentStatus_Key"]
    recruitment["RecruitmentStatus_Key"] = recruitment["Status"].map(lookup)
    state["fact_recruitment"] = recruitment
    return state
