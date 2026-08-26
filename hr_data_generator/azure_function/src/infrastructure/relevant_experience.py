"""Relevant-experience rules shared by employment events and reviews."""

import pandas as pd


def initial_relevant_experience(birth_date, start_date, rng):
    """Simulate prior relevant experience; age only caps what is plausible."""
    age = max(18.0, (pd.Timestamp(start_date) - pd.Timestamp(birth_date)).days / 365.2425)
    potential_years = max(0.0, age - 19.0)
    return round(max(0.0, min(
        potential_years,
        rng.normalvariate(potential_years * 0.55, 2.0),
    )), 2)


def experience_as_of(employment, as_of_date):
    """Return experience relevant to this employment row at an effective date."""
    start = pd.to_datetime(employment.get("Startdatum"), errors="coerce")
    base = pd.to_numeric(
        employment.get("Relevante_Ervaring_Jaren_Bij_Start", 0.0),
        errors="coerce",
    )
    base = float(base) if pd.notna(base) else 0.0
    if pd.isna(start):
        return round(max(0.0, base), 2)
    elapsed = max(0.0, (pd.Timestamp(as_of_date) - start).days / 365.2425)
    return round(max(0.0, base + elapsed), 2)


def carried_experience(previous_employment, event_date, same_department, config):
    """Carry all experience within a domain and only a configured share across it."""
    experience = experience_as_of(previous_employment, event_date)
    if same_department:
        return experience
    settings = getattr(config, "career_events", {}) if config else {}
    ratio = float(settings.get("relevant_experience_transfer_ratio", 0.45))
    return round(experience * min(1.0, max(0.0, ratio)), 2)
