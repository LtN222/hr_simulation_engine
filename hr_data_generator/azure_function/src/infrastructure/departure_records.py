"""Shared construction of a departure's terminal fact_employment row.

Departure is an instant (what happens at Einddatum), not a continuing
employment period like a hire/promotion/transfer/salary review. It therefore
gets its own terminal row instead of overwriting the row it closes - see
BACKLOG.md's "Departures" entry for the full rationale. Any simulator that
ends someone's employment (attrition, or a lapsed temporary contract) closes
the active row in place (Einddatum/Dienstverband_status only - its own
EventType_Key is left untouched) and appends the row this module builds.
"""
from src.infrastructure.record_builder import build_record


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
            "Relevante_Ervaring_Jaren_Bij_Start": employment.get(
                "Relevante_Ervaring_Jaren_Bij_Start"
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
