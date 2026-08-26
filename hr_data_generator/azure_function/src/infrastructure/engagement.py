"""Engagement scoring shared by snapshots, performance and attrition."""

import hashlib

import pandas as pd

from src.infrastructure.satisfaction import _cache_scalar, _department_name, _interpolate
from src.infrastructure.employment_history import employment_history_for
from src.infrastructure.driver_selection import driver_key_for


class EngagementModel:
    """Calculate a stable 1-10 engagement score from employee context.

    Engagement is related to satisfaction but remains a distinct construct:
    it captures discretionary energy and connection to work. The model avoids
    artificial month-to-month waves; changes come from manager, reward and
    career context instead.
    """

    def __init__(self, config):
        self.settings = getattr(config, "engagement", {}) if config else {}
        self.settings = self.settings or {}

    def score(
        self,
        employee_key,
        satisfaction_score,
        performance_score,
        compa_ratio=None,
        department_name=None,
        manager_key=None,
        career_momentum=0.0,
        constructive_contributions=None,
    ):
        baseline = float(self.settings.get("baseline_mean", 6.7))
        spread = float(self.settings.get("individual_spread", 0.45))
        satisfaction_effect = float(self.settings.get("satisfaction_effect", 0.50))
        performance_midpoint = float(self.settings.get("performance_midpoint", 3.4))
        performance_effect = float(self.settings.get("performance_effect", 0.22))
        minimum = float(self.settings.get("minimum_score", 1.0))
        maximum = float(self.settings.get("maximum_score", 10.0))

        score = baseline + self._stable_value(employee_key, "engagement") * spread
        satisfaction = pd.to_numeric(satisfaction_score, errors="coerce")
        if pd.notna(satisfaction):
            score += (float(satisfaction) - 7.0) * satisfaction_effect

        performance = pd.to_numeric(performance_score, errors="coerce")
        if pd.notna(performance):
            score += (float(performance) - performance_midpoint) * performance_effect

        score += self._compa_ratio_component(compa_ratio)
        score += self.settings.get("department_adjustments", {}).get(
            department_name,
            0.0,
        )
        score += self._manager_component(manager_key)
        score += float(career_momentum or 0.0)
        # These voluntary, constructive signals also determine the one
        # reportable engagement driver; they are not social availability.
        contributions = constructive_contributions or {}
        if contributions:
            mean_signal = sum(contributions.values()) / len(contributions)
            effect = float(
                self.settings.get("constructive_contribution_effect", 0.70)
            )
            score += (mean_signal - 0.5) * effect
        return round(min(max(float(score), minimum), maximum), 2)

    def constructive_contributions(
        self, state, employee_key, as_of_date, performance_score
    ):
        """Return bounded signals for voluntary extra role contribution.

        Cached per (employee, date, performance): called both directly and
        from `score_employee_engagement`/`engagement_driver_key_for` for
        the same employee and date.
        """
        cache = state.setdefault("_constructive_contributions_cache", {})
        cache_key = (
            employee_key, _cache_scalar(as_of_date), _cache_scalar(performance_score)
        )
        if cache_key in cache:
            return cache[cache_key]

        purposes = {
            "Initiatief en verbeteren": "initiative",
            "Kennisdeling en mentoring": "knowledge",
            "Samenwerking buiten de eigen rol": "cross_role",
            "Medewerkersstem en participatie": "voice",
            "Organisatieverbondenheid": "organisation",
            "Rolverbondenheid/eigenaarschap": "ownership",
        }
        contributions = {
            name: (self._stable_value(employee_key, purpose) + 1) / 2
            for name, purpose in purposes.items()
        }
        momentum = career_momentum_for(
            state, employee_key, as_of_date, performance_score, self.settings
        )
        ownership = "Rolverbondenheid/eigenaarschap"
        contributions[ownership] = min(
            1.0, max(0.0, contributions[ownership] + momentum)
        )
        cache[cache_key] = contributions
        return contributions

    def band_key_for(self, bands, score):
        if bands is None or bands.empty or pd.isna(score):
            return None
        minimum = pd.to_numeric(bands["Minimum_Score"], errors="coerce")
        maximum = pd.to_numeric(bands["Maximum_Score"], errors="coerce")
        match = bands[(minimum <= score) & (maximum.isna() | (score <= maximum))]
        return int(match.iloc[0]["EngagementBand_Key"]) if not match.empty else None

    def _compa_ratio_component(self, compa_ratio):
        ratio = pd.to_numeric(compa_ratio, errors="coerce")
        if pd.isna(ratio):
            return 0.0
        adjustments = self.settings.get("compa_ratio_adjustments", {})
        very_low = float(adjustments.get("ver_onder", -0.45))
        low = float(adjustments.get("onder", -0.20))
        around = float(adjustments.get("rond", 0.0))
        high = float(adjustments.get("boven", 0.08))
        very_high = float(adjustments.get("ver_boven", 0.12))
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
        spread = float(self.settings.get("manager_effect_spread", 0.35))
        return self._stable_value(manager_key, "engagement_manager") * spread

    @staticmethod
    def _stable_value(identifier, purpose):
        digest = hashlib.sha256(f"{identifier}:{purpose}".encode()).digest()
        value = int.from_bytes(digest[:8], "big") / (2 ** 64 - 1)
        return value * 2 - 1


def score_employee_engagement(
    model,
    state,
    employee,
    employment,
    as_of_date,
    satisfaction_score,
    performance_score,
    compa_ratio=None,
    manager_key=None,
):
    """Score engagement using the effective employee and career context.

    Attrition and performance review both ask for the same employee's
    engagement on the same date within a single simulated week, so the
    result is cached per resolved input tuple rather than recomputed for
    each caller.
    """
    employee_key = employee.get("Employee_Key", employment.get("Employee_Key"))
    if pd.isna(employee_key):
        employee_key = employment.get("Employee_Key")
    if compa_ratio is None:
        compa_ratio = employment.get("Target_Compa_Ratio")
    if manager_key is None:
        manager_key = employee.get("Manager_Key")
    department_name = _department_name(state, employment.get("Role_Key"))

    cache = state.setdefault("_engagement_cache", {})
    cache_key = (
        employee_key,
        _cache_scalar(as_of_date),
        _cache_scalar(satisfaction_score),
        _cache_scalar(performance_score),
        _cache_scalar(compa_ratio),
        _cache_scalar(manager_key),
        department_name,
    )
    if cache_key in cache:
        return cache[cache_key]

    contributions = model.constructive_contributions(
        state, employee_key, as_of_date, performance_score
    )
    result = model.score(
        employee_key=employee_key,
        satisfaction_score=satisfaction_score,
        performance_score=performance_score,
        compa_ratio=compa_ratio,
        department_name=department_name,
        manager_key=manager_key,
        career_momentum=career_momentum_for(
            state,
            employee_key,
            as_of_date,
            performance_score,
            model.settings,
        ),
        constructive_contributions=contributions,
    )
    cache[cache_key] = result
    return result


def engagement_driver_key_for(
    state, employee_key, as_of_date, performance_score, model=None
):
    """Select one engagement contribution; social availability is excluded."""
    model = model or EngagementModel(None)
    candidates = model.constructive_contributions(
        state, employee_key, as_of_date, performance_score
    )
    name, value = max(candidates.items(), key=lambda item: item[1])
    if value < float(model.settings.get("driver_dominance_threshold", 0.70)):
        name = "Geen dominant aandachtspunt"
    return driver_key_for(state.get("dim_engagement_driver", pd.DataFrame()), name)


def career_momentum_for(
    state,
    employee_key,
    as_of_date,
    performance_score,
    engagement_settings=None,
):
    """Return a decaying reward for recent moves and a stagnation signal.

    Cached per (employee, date, performance): this employment-history scan
    is the expensive part, and is otherwise run twice per
    `score_employee_engagement` call (once directly, once via
    `constructive_contributions`) as well as by separate callers for the
    same employee and date.
    """
    cache = state.setdefault("_engagement_momentum_cache", {})
    cache_key = (employee_key, _cache_scalar(as_of_date), _cache_scalar(performance_score))
    if cache_key in cache:
        return cache[cache_key]
    result = _compute_career_momentum(
        state, employee_key, as_of_date, performance_score, engagement_settings
    )
    cache[cache_key] = result
    return result


def _compute_career_momentum(
    state, employee_key, as_of_date, performance_score, engagement_settings=None
):
    if pd.isna(employee_key):
        return 0.0
    date = pd.Timestamp(as_of_date).normalize()
    history = employment_history_for(state, employee_key).copy()
    if history.empty:
        return 0.0
    history["Startdatum"] = pd.to_datetime(
        history["Startdatum"], errors="coerce"
    ).dt.normalize()
    history = history[history["Startdatum"] <= date]
    if history.empty:
        return 0.0

    event_types = state.get("dim_event_type", pd.DataFrame())
    event_lookup = (
        event_types.set_index("EventType_Key")["EventType"].to_dict()
        if not event_types.empty else {}
    )
    event_keys = history.get(
        "EventType_Key",
        pd.Series(index=history.index, dtype="object"),
    )
    history["EventType"] = event_keys.map(event_lookup)
    momentum_cfg = (engagement_settings or {}).get("career_momentum", {})
    months = max(1, int(momentum_cfg.get("momentum_months", 12)))
    promotion_effect = float(momentum_cfg.get("promotion_max_effect", 0.35))
    transfer_effect = float(momentum_cfg.get("transfer_max_effect", 0.15))
    latest_move = history[history["EventType"].isin(["Promotie", "Transfer"])]
    if not latest_move.empty:
        move = latest_move.sort_values("Startdatum").iloc[-1]
        elapsed_months = max(0.0, (date - move["Startdatum"]).days / 30.4375)
        if elapsed_months <= months:
            effect = promotion_effect if move["EventType"] == "Promotie" else transfer_effect
            return effect * (1 - elapsed_months / months)

    performance = pd.to_numeric(performance_score, errors="coerce")
    first_start = history["Startdatum"].min()
    years_without_move = (date - first_start).days / 365.2425
    threshold = float(momentum_cfg.get("high_performer_stagnation_after_years", 3))
    if pd.notna(performance) and performance >= 4.0 and years_without_move >= threshold:
        return float(momentum_cfg.get("high_performer_stagnation_effect", -0.30))
    return 0.0
