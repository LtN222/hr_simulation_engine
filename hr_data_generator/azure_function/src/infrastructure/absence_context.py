"""Synchronise effective-dated employee context onto absence episodes."""

import pandas as pd

from src.infrastructure.manager_assignment import manager_as_of
from src.infrastructure.satisfaction import (
    SatisfactionModel,
    score_employee_satisfaction,
)


def sync_absence_satisfaction(state, config):
    """Stamp satisfaction as of each absence start date onto ``fact_absence``.

    Absence is an event fact, while satisfaction is a time-varying employee
    attribute. Persisting the event-time band gives Power BI one direct filter
    path from ``dim_satisfaction_band`` to absence without a fact-to-fact
    relationship or a filter that only changes a measure denominator.
    """
    absence = state.get("fact_absence", pd.DataFrame()).copy()
    employment = state.get("fact_employment", pd.DataFrame()).copy()
    employees = state.get("dim_employee", pd.DataFrame()).copy()
    bands = state.get("dim_satisfaction_band", pd.DataFrame())
    if absence.empty or employment.empty or employees.empty or bands.empty:
        return state

    required_columns = {"Employee_Key", "Startdatum"}
    if not required_columns.issubset(absence.columns):
        return state

    for column in (
        "Tevredenheid_Score_Bij_Aanvang",
        "SatisfactionBand_Key",
    ):
        if column not in absence.columns:
            absence[column] = None

    absence["Startdatum"] = pd.to_datetime(
        absence["Startdatum"], errors="coerce"
    ).dt.normalize()
    employment["Startdatum"] = pd.to_datetime(
        employment["Startdatum"], errors="coerce"
    ).dt.normalize()
    employment["Einddatum"] = pd.to_datetime(
        employment.get("Einddatum"), errors="coerce"
    ).dt.normalize()
    employee_lookup = employees.set_index("Employee_Key")
    performance_reviews = _normalise_reviews(
        state.get("fact_performance_review", pd.DataFrame())
    )
    manager_assignments = state.get(
        "fact_manager_assignment", pd.DataFrame()
    )
    satisfaction_model = SatisfactionModel(config)

    for index, episode in absence.dropna(subset=["Startdatum"]).iterrows():
        employee_key = episode.get("Employee_Key")
        if employee_key not in employee_lookup.index:
            continue
        episode_employment = _employment_as_of(
            employment,
            employee_key,
            episode["Startdatum"],
        )
        if episode_employment is None:
            continue

        employee = employee_lookup.loc[employee_key]
        performance = _performance_as_of(
            performance_reviews,
            employee_key,
            episode["Startdatum"],
            employee.get("Performance_Score", 3.4),
        )
        manager_key = manager_as_of(
            manager_assignments,
            employee_key,
            episode["Startdatum"],
        )
        score = score_employee_satisfaction(
            satisfaction_model,
            state,
            employee,
            episode_employment,
            episode["Startdatum"],
            performance_score=performance,
            manager_key=manager_key,
        )
        absence.loc[index, "Tevredenheid_Score_Bij_Aanvang"] = score
        absence.loc[index, "SatisfactionBand_Key"] = (
            satisfaction_model.band_key_for(bands, score)
        )

    state["fact_absence"] = absence
    return state


def _employment_as_of(employment, employee_key, date):
    matches = employment[(employment["Employee_Key"] == employee_key) & (
        employment["Startdatum"] <= date
    ) & (
        employment["Einddatum"].isna() | (employment["Einddatum"] >= date)
    )]
    if matches.empty:
        return None
    return matches.sort_values(["Startdatum", "Employment_Key"]).iloc[-1]


def _normalise_reviews(reviews):
    if reviews.empty:
        return reviews
    result = reviews.copy()
    result["Review_Datum"] = pd.to_datetime(
        result["Review_Datum"], errors="coerce"
    ).dt.normalize()
    return result.dropna(subset=["Review_Datum"])


def _performance_as_of(reviews, employee_key, date, fallback):
    if reviews.empty:
        return fallback
    matches = reviews[(reviews["Employee_Key"] == employee_key) & (
        reviews["Review_Datum"] <= date
    )]
    return fallback if matches.empty else matches.sort_values(
        "Review_Datum"
    ).iloc[-1]["Performance_Score"]
