"""Satisfaction scoring shared by snapshot and event simulations."""

import hashlib
from dataclasses import dataclass

import pandas as pd

from src.infrastructure.employment_history import employment_history_for


@dataclass(frozen=True)
class SatisfactionExplanation:
    """The score and the single factor that is most meaningful to report."""

    score: float
    driver_name: str
    driver_direction: str
    components: dict[str, float]


class SatisfactionModel:
    """Calculate stable, explainable employee satisfaction scores on a 1-10 scale.

    The model deliberately uses only slowly changing employment conditions.
    A small employee-specific residual represents unobserved preferences, but
    it cannot overwhelm relative pay, manager quality or career conditions.
    """

    def __init__(self, config):
        settings = getattr(config, "satisfaction", {}) if config else {}
        self.settings = settings or {}

    def score(
        self,
        employee_key,
        snapshot_date,
        performance_score,
        compa_ratio=None,
        department_name=None,
        manager_key=None,
        tenure_years=None,
    ):
        """Return a reproducible score for the stated employment context."""
        return self.explain(
            employee_key=employee_key,
            snapshot_date=snapshot_date,
            performance_score=performance_score,
            compa_ratio=compa_ratio,
            department_name=department_name,
            manager_key=manager_key,
            tenure_years=tenure_years,
        ).score

    def explain(
        self,
        employee_key,
        snapshot_date,
        performance_score,
        compa_ratio=None,
        department_name=None,
        manager_key=None,
        tenure_years=None,
        career_momentum=0.0,
    ):
        """Score satisfaction and identify a stable, reportable primary driver.

        The individual residual remains part of the simulated score but is not
        reported as a driver: it represents information that HR would not know.
        Only observable or interpretable employment conditions are eligible.
        """
        baseline = float(self.settings.get("baseline_mean", 7.0))
        spread = float(self.settings.get("individual_spread", 0.45))
        midpoint = float(self.settings.get("performance_midpoint", 3.4))
        performance_effect = float(self.settings.get("performance_effect", 0.25))
        minimum = float(self.settings.get("minimum_score", 1.0))
        maximum = float(self.settings.get("maximum_score", 10.0))

        score = baseline + self._stable_value(employee_key, "preference") * spread

        performance = pd.to_numeric(performance_score, errors="coerce")
        career_component = self._tenure_component(tenure_years) + float(
            career_momentum or 0.0
        )
        if pd.notna(performance):
            career_component += (float(performance) - midpoint) * performance_effect

        components = {
            "Beloning": self._compa_ratio_component(compa_ratio),
            "Leiderschap": self._manager_component(manager_key),
            "Teamdynamiek": self._team_component(
                employee_key, manager_key, department_name
            ),
            "Cultuur en verbondenheid": self._culture_component(employee_key),
            "Carriere en opleidingsmogelijkheden": career_component,
            "Werkcontext": float(
                self.settings.get("department_adjustments", {}).get(
                    department_name,
                    0.0,
                )
            ),
        }
        score += sum(components.values())
        score = round(min(max(float(score), minimum), maximum), 2)
        driver_name, driver_direction = self._primary_driver(score, components)
        return SatisfactionExplanation(score, driver_name, driver_direction, components)

    def driver_key_for(self, drivers, explanation):
        """Resolve the explanation to the configuration-owned dimension key."""
        if drivers is None or drivers.empty or explanation is None:
            return None
        matches = drivers[(drivers["Driver_Name"] == explanation.driver_name) & (
            drivers["Direction"] == explanation.driver_direction
        )]
        return (
            int(matches.iloc[0]["SatisfactionDriver_Key"])
            if not matches.empty else None
        )

    def band_key_for(self, bands, score):
        """Return the reporting band containing a satisfaction score."""
        if bands is None or bands.empty or pd.isna(score):
            return None

        minimum = pd.to_numeric(bands["Minimum_Score"], errors="coerce")
        maximum = pd.to_numeric(bands["Maximum_Score"], errors="coerce")
        match = bands[(minimum <= score) & (maximum.isna() | (score <= maximum))]
        return int(match.iloc[0]["SatisfactionBand_Key"]) if not match.empty else None

    def _compa_ratio_component(self, compa_ratio):
        """Apply asymmetric pay fairness effects around the market benchmark."""
        ratio = pd.to_numeric(compa_ratio, errors="coerce")
        if pd.isna(ratio):
            return 0.0

        adjustments = self.settings.get("compa_ratio_adjustments", {})
        very_low = float(adjustments.get("ver_onder", -1.15))
        low = float(adjustments.get("onder", -0.55))
        around = float(adjustments.get("rond", 0.0))
        high = float(adjustments.get("boven", 0.15))
        very_high = float(adjustments.get("ver_boven", 0.25))
        ratio = float(ratio)

        if ratio < 0.80:
            return very_low
        if ratio < 0.90:
            return _interpolate(ratio, 0.80, 0.90, very_low, low)
        if ratio < 1.00:
            return _interpolate(ratio, 0.90, 1.00, low, around)
        if ratio <= 1.10:
            return _interpolate(ratio, 1.00, 1.10, around, high)
        if ratio <= 1.20:
            return _interpolate(ratio, 1.10, 1.20, high, very_high)
        return very_high

    def _manager_component(self, manager_key):
        if pd.isna(manager_key):
            return 0.0
        spread = float(self.settings.get("manager_effect_spread", 0.45))
        return self._stable_value(manager_key, "manager_quality") * spread

    def _team_component(self, employee_key, manager_key, department_name):
        """Represent stable team fit without introducing a separate team entity."""
        spread = float(self.settings.get("team_effect_spread", 0.20))
        identifier = f"{employee_key}:{manager_key}:{department_name}"
        return self._stable_value(identifier, "team_fit") * spread

    def _culture_component(self, employee_key):
        """Represent durable organisation fit rather than month-to-month noise."""
        spread = float(self.settings.get("culture_effect_spread", 0.15))
        return self._stable_value(employee_key, "culture_fit") * spread

    def _tenure_component(self, tenure_years):
        value = pd.to_numeric(tenure_years, errors="coerce")
        if pd.isna(value):
            return 0.0

        adjustments = self.settings.get("tenure_adjustments", {})
        if value < 0.5:
            return float(adjustments.get("under_half_year", 0.15))
        if value < 2:
            return float(adjustments.get("under_two_years", 0.05))
        if value < 5:
            return float(adjustments.get("two_to_five_years", -0.10))
        return float(adjustments.get("five_years_or_more", 0.0))

    def _primary_driver(self, score, components):
        """Choose a direction that explains low/high scores without fake precision."""
        selection = self.settings.get("driver_selection", {})
        minimum = float(selection.get("minimum_absolute_impact", 0.12))
        low_score = float(selection.get("low_score", 6.0))
        high_score = float(selection.get("high_score", 7.5))

        if score < low_score:
            candidates = [item for item in components.items() if item[1] <= -minimum]
            if candidates:
                name, _ = min(candidates, key=lambda item: item[1])
                return name, "Negatief"
        elif score > high_score:
            candidates = [item for item in components.items() if item[1] >= minimum]
            if candidates:
                name, _ = max(candidates, key=lambda item: item[1])
                return name, "Positief"
        else:
            candidates = [
                item for item in components.items() if abs(item[1]) >= minimum
            ]
            if candidates:
                name, value = max(candidates, key=lambda item: abs(item[1]))
                return name, "Positief" if value > 0 else "Negatief"

        return "Geen dominant aandachtspunt", "Neutraal"

    @staticmethod
    def _stable_value(identifier, purpose):
        digest = hashlib.sha256(f"{identifier}:{purpose}".encode()).digest()
        value = int.from_bytes(digest[:8], "big") / (2 ** 64 - 1)
        return value * 2 - 1


def score_employee_satisfaction(
    model,
    state,
    employee,
    employment,
    as_of_date,
    performance_score=None,
    compa_ratio=None,
    manager_key=None,
):
    """Score an employee using the same context across all simulated facts."""
    return explain_employee_satisfaction(
        model,
        state,
        employee,
        employment,
        as_of_date,
        performance_score=performance_score,
        compa_ratio=compa_ratio,
        manager_key=manager_key,
    ).score


def explain_employee_satisfaction(
    model,
    state,
    employee,
    employment,
    as_of_date,
    performance_score=None,
    compa_ratio=None,
    manager_key=None,
):
    """Return the score and the primary driver for an employee at a date.

    Attrition, performance review and absence all ask for the same
    employee's satisfaction on the same date with the same effective
    inputs within a single simulated week, so the result is cached per
    resolved (employee, date, performance, pay, manager, department,
    tenure) tuple rather than recomputed - including the career-momentum
    employment-history scan - for every caller.
    """
    employee_key = employee.get("Employee_Key", employment.get("Employee_Key"))
    if pd.isna(employee_key):
        employee_key = employment.get("Employee_Key")
    date = pd.Timestamp(as_of_date).normalize()
    service_start = pd.to_datetime(
        employee.get("Aaneengesloten_Indienst_Datum", employment.get("Startdatum")),
        errors="coerce",
    )
    tenure_years = (
        max(0.0, (date - service_start).days / 365.2425)
        if pd.notna(service_start)
        else None
    )
    if performance_score is None:
        performance_score = employee.get("Performance_Score", 3.4)
    if compa_ratio is None:
        compa_ratio = employment.get("Target_Compa_Ratio")
    if manager_key is None:
        manager_key = employee.get("Manager_Key")
    department_name = _department_name(state, employment.get("Role_Key"))

    cache = state.setdefault("_satisfaction_cache", {})
    cache_key = (
        employee_key,
        date,
        _cache_scalar(performance_score),
        _cache_scalar(compa_ratio),
        _cache_scalar(manager_key),
        department_name,
        _cache_scalar(tenure_years),
    )
    if cache_key in cache:
        return cache[cache_key]

    explanation = model.explain(
        employee_key=employee_key,
        snapshot_date=date,
        performance_score=performance_score,
        compa_ratio=compa_ratio,
        department_name=department_name,
        manager_key=manager_key,
        tenure_years=tenure_years,
        career_momentum=_career_momentum_for(
            state,
            employee_key,
            date,
            performance_score,
            model.settings,
        ),
    )
    cache[cache_key] = explanation
    return explanation


def _cache_scalar(value):
    """Normalise a value for use in a cache key - NaN/None become None."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _career_momentum_for(state, employee_key, as_of_date, performance_score, settings):
    """Model recent progression and prolonged high-performer stagnation.

    Cached per (employee, date, performance) for the same reason as
    `explain_employee_satisfaction` above - this is the expensive part.
    """
    cache = state.setdefault("_satisfaction_momentum_cache", {})
    cache_key = (employee_key, _cache_scalar(as_of_date), _cache_scalar(performance_score))
    if cache_key in cache:
        return cache[cache_key]
    result = _compute_career_momentum(state, employee_key, as_of_date, performance_score, settings)
    cache[cache_key] = result
    return result


def _compute_career_momentum(state, employee_key, as_of_date, performance_score, settings):
    if pd.isna(employee_key):
        return 0.0

    history = employment_history_for(state, employee_key).copy()
    if history.empty:
        return 0.0
    history["Startdatum"] = pd.to_datetime(
        history["Startdatum"], errors="coerce"
    ).dt.normalize()
    history = history[history["Startdatum"] <= as_of_date].dropna(
        subset=["Startdatum"]
    )
    if history.empty:
        return 0.0

    event_types = state.get("dim_event_type", pd.DataFrame())
    event_lookup = (
        event_types.set_index("EventType_Key")["EventType"].to_dict()
        if not event_types.empty else {}
    )
    history["EventType"] = history.get(
        "EventType_Key", pd.Series(index=history.index, dtype="object")
    ).map(event_lookup)
    momentum = settings.get("career_momentum", {})
    months = max(1, int(momentum.get("momentum_months", 12)))
    moves = history[history["EventType"].isin(["Promotie", "Transfer"])]
    if not moves.empty:
        move = moves.sort_values("Startdatum").iloc[-1]
        elapsed = max(0.0, (as_of_date - move["Startdatum"]).days / 30.4375)
        if elapsed <= months:
            maximum = float(momentum.get(
                "promotion_max_effect" if move["EventType"] == "Promotie"
                else "transfer_max_effect",
                0.18 if move["EventType"] == "Promotie" else 0.08,
            ))
            return maximum * (1 - elapsed / months)

    performance = pd.to_numeric(performance_score, errors="coerce")
    years = (as_of_date - history["Startdatum"].min()).days / 365.2425
    threshold = float(momentum.get("high_performer_stagnation_after_years", 3))
    if pd.notna(performance) and performance >= 4.0 and years >= threshold:
        return float(momentum.get("high_performer_stagnation_effect", -0.18))
    return 0.0


def _department_name(state, role_key):
    roles = state.get("dim_role", pd.DataFrame())
    departments = state.get("dim_department", pd.DataFrame())
    if roles.empty or departments.empty or pd.isna(role_key):
        return None

    role = roles.loc[roles["Role_Key"] == role_key]
    if role.empty or "Department_Key" not in role.columns:
        return None
    department = departments.loc[
        departments["Department_Key"] == role.iloc[0]["Department_Key"]
    ]
    return None if department.empty else department.iloc[0].get("Department_Name")


def _interpolate(value, left_x, right_x, left_y, right_y):
    progress = (value - left_x) / (right_x - left_x)
    return left_y + progress * (right_y - left_y)
