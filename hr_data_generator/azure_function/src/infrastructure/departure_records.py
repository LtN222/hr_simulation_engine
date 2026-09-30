"""Shared construction of a departure's terminal fact_employment row.

Departure is an instant (what happens at Einddatum), not a continuing
employment period like a hire/promotion/transfer/salary review. It therefore
gets its own terminal row instead of overwriting the row it closes - see
BACKLOG.md's "Departures" entry for the full rationale. Any simulator that
ends someone's employment (attrition, or a lapsed temporary contract) closes
the active row in place (Einddatum/Dienstverband_status only - its own
EventType_Key is left untouched) and appends the row this module builds.
"""
import pandas as pd

from src.infrastructure.absence_calendar import duration_days, workdays_between
from src.infrastructure.record_builder import build_record
from src.infrastructure.relevant_experience import carried_experience


def build_departure_row(
    schema,
    employment,
    next_key,
    today,
    event_type_key,
    departure_reason_key,
    satisfaction,
    satisfaction_band_key,
    engagement,
    engagement_band_key,
):
    """Return a self-contained terminal row for a closing employment period."""
    return build_record(
        schema,
        "fact_employment",
        {
            "Employment_Key": next_key,
            "Previous_Employment_Key": employment["Employment_Key"],
            "Employee_Key": employment["Employee_Key"],
            "HireSource_Key": employment.get("HireSource_Key"),
            "Role_Key": employment["Role_Key"],
            "Location_Key": employment.get("Location_Key"),
            "Shift_Key": employment.get("Shift_Key"),
            "SalaryScale_Key": employment.get("SalaryScale_Key"),
            "Streef_Compa_Ratio": employment.get("Streef_Compa_Ratio"),
            # Rolled forward to the departure date: this terminal row starts
            # at `today`, so the closing row's starting value would understate it.
            "Relevante_Ervaring_Jaren_Bij_Start": carried_experience(
                employment, today, True, None
            ),
            "Startdatum": today,
            "Einddatum": today,
            "Dienstverband_status": "Uit dienst",
            "Salaris": employment.get("Salaris"),
            "Contracttype": employment.get("Contracttype"),
            "Contracturen": employment.get("Contracturen"),
            "Contract_einddatum": employment.get("Contract_einddatum"),
            "Contract_ronde": employment.get("Contract_ronde"),
            "EventType_Key": event_type_key,
            "DepartureReason_Key": departure_reason_key,
            "Tevredenheid_Score_Bij_Uitdienst": satisfaction,
            "SatisfactionBand_Key_Bij_Uitdienst": satisfaction_band_key,
            "Betrokkenheid_Score_Bij_Uitdienst": engagement,
            "EngagementBand_Key_Bij_Uitdienst": engagement_band_key,
        }
    )


def close_open_absence(state, employee_key, departure_date, config=None):
    """End every absence episode of a leaver on the departure date.

    An episode is created with its full planned length, so one still running
    when the employee leaves would keep counting sickness days (and hours)
    after they are gone. Every episode with `Startdatum <= departure_date` and
    `Einddatum > departure_date` is shortened to end on `departure_date`
    (dates are inclusive, like everywhere else in fact_absence), and its
    duration, workdays and hours are recomputed with the shared absence
    calendar. Hours per workday are the episode's own (hours / workdays at the
    time it started), so a change of contract hours is not rewritten.
    Episodes that ended before the departure are untouched. Returns the number
    of episodes shortened.
    """
    absence = state.get("fact_absence")
    if absence is None or absence.empty or "Einddatum" not in absence.columns:
        return 0

    departure = pd.Timestamp(departure_date).normalize()
    starts = pd.to_datetime(absence["Startdatum"], errors="coerce")
    ends = pd.to_datetime(absence["Einddatum"], errors="coerce")
    open_episodes = absence.index[
        (absence["Employee_Key"] == employee_key)
        & (starts <= departure)
        & (ends > departure)
    ]

    for index in open_episodes:
        start = starts.loc[index]
        old_workdays = absence.at[index, "Afwezigheid_Werkdagen"]
        old_hours = absence.at[index, "Afwezigheid_Uren"]
        workdays = workdays_between(start, departure)
        if pd.notna(old_workdays) and old_workdays > 0:
            hours = round(workdays * float(old_hours) / float(old_workdays), 2)
        else:
            hours = 0.0
        is_sickness = (
            pd.notna(absence.at[index, "Verzuim_Werkdagen"])
            and absence.at[index, "Verzuim_Werkdagen"] > 0
        )
        absence.at[index, "Einddatum"] = departure
        absence.at[index, "Duur_dagen"] = duration_days(start, departure)
        absence.at[index, "Afwezigheid_Werkdagen"] = workdays
        absence.at[index, "Afwezigheid_Uren"] = hours
        absence.at[index, "Verzuim_Werkdagen"] = workdays if is_sickness else 0
        absence.at[index, "Verzuim_Uren"] = hours if is_sickness else 0.0

    return len(open_episodes)
