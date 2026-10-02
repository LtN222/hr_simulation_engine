"""A synthetic population for scoring satisfaction/engagement directly (HP-04).

Narrow by design: it calls the score models on realistic inputs (compa-ratios
from SalaryPolicy, performance from the performance config, tenure from the
initial-population distribution, the department mix of the real allocation,
managers with ~8 reports, a few career moves) over month-ends, without the
weekly runner.
"""
import random

import numpy as np
import pandas as pd

from src.application.allocation import allocate_headcount
from src.infrastructure.engagement import EngagementModel
from src.infrastructure.salary_policy import SalaryPolicy
from src.infrastructure.satisfaction import SatisfactionModel

BAND_NAMES = ["Zeer laag", "Laag", "Neutraal", "Hoog", "Zeer hoog"]
CONTRIBUTIONS = [
    "initiative", "knowledge", "cross_role", "voice", "organisation", "ownership",
]


def month_ends(months):
    return pd.date_range("2024-01-31", periods=months, freq="ME")


def build_population(config, seed=7):
    rng = random.Random(seed)
    allocation = allocate_headcount(config.structure, 800, config.staffing, config.workforce_planning)
    departments = [a["Afdeling_Naam"] for a in allocation for _ in range(a["count"])]
    policy = SalaryPolicy(config, pd.DataFrame(config.dim_salary_scale))
    buckets = [
        (tuple(float(x) for x in key.split("-")), weight)
        for key, weight in config.initial_population["tenure_years_distribution"].items()
    ]
    performance = config.performance
    people, members = [], {}
    for key, department in enumerate(departments, start=1):
        (low, high), = rng.choices([b for b, _ in buckets], weights=[w for _, w in buckets])
        initial = min(5, max(1, rng.gauss(performance["initial_score_mean"], performance["initial_score_sd"])))
        mean = float(performance["initial_score_mean"])
        person = {
            "key": key, "department": department, "tenure": rng.uniform(low, high),
            "ratio": policy.draw_target_ratio(department, rng, gender="F" if rng.random() < 0.3 else "M"),
            "performance": [initial, min(5, max(1, mean + float(performance["year_to_year_persistence"]) * (initial - mean)
                                                + rng.gauss(0, float(performance["yearly_variation_sd"]))))],
            "moves": [
                (name, year * 12 + rng.randint(0, 11))
                for year in (0, 1)
                for name, rate in (("Promotie", 0.06), ("Transfer", 0.04)) if rng.random() < rate
            ],
        }
        people.append(person)
        members.setdefault(department, []).append(person)
    for department, group in members.items():
        for index, person in enumerate(group):
            person["manager"] = f"M{department}{index // 8}"
    return people


def _momentum(settings, person, month, performance, tenure):
    momentum = settings.get("career_momentum", {})
    window = max(1, int(momentum.get("momentum_months", 12)))
    recent = [(name, m) for name, m in person["moves"] if m <= month]
    if recent:
        name, moved = max(recent, key=lambda item: item[1])
        if month - moved <= window:
            effect = float(momentum["promotion_max_effect" if name == "Promotie" else "transfer_max_effect"])
            return effect * (1 - (month - moved) / window)
    if performance >= 4.0 and tenure >= float(momentum.get("high_performer_stagnation_after_years", 3)):
        return float(momentum.get("high_performer_stagnation_effect", 0.0))
    return 0.0


def score_population(config, people, months=12):
    satisfaction_model = SatisfactionModel(config)
    engagement_model = EngagementModel(config)
    rows = []
    for person in people:
        for month, date in enumerate(month_ends(months)):
            performance = person["performance"][0 if month < 12 else 1]
            tenure = person["tenure"] + month / 12
            explanation = satisfaction_model.explain(
                employee_key=person["key"], snapshot_date=date, performance_score=performance,
                compa_ratio=person["ratio"], department_name=person["department"],
                manager_key=person["manager"], tenure_years=tenure,
                career_momentum=_momentum(config.satisfaction, person, month, performance, tenure),
            )
            momentum = _momentum(config.engagement, person, month, performance, tenure)
            contributions = {
                purpose: (engagement_model._stable_value(person["key"], purpose) + 1) / 2
                for purpose in CONTRIBUTIONS
            }
            contributions["ownership"] = min(1.0, max(0.0, contributions["ownership"] + momentum))
            engagement = engagement_model.score(
                employee_key=person["key"], satisfaction_score=explanation.score,
                performance_score=performance, compa_ratio=person["ratio"],
                department_name=person["department"], manager_key=person["manager"],
                career_momentum=momentum, constructive_contributions=contributions, as_of_date=date,
            )
            observable = (
                explanation.components["Beloning"]
                + explanation.components["Carriere en opleidingsmogelijkheden"]
                + explanation.components["Werkcontext"]
            )
            parts = engagement_model.components(
                employee_key=person["key"], satisfaction_score=explanation.score,
                performance_score=performance, compa_ratio=person["ratio"],
                department_name=person["department"], manager_key=person["manager"],
                career_momentum=momentum, constructive_contributions=contributions, as_of_date=date,
            )
            inherited = float(engagement_model.settings.get("satisfaction_effect", 0.5))
            pay_via_satisfaction = inherited * explanation.components["Beloning"]
            rows.append({
                "key": person["key"], "department": person["department"], "month": month,
                "satisfaction": explanation.score, "engagement": engagement,
                "observable_satisfaction": observable, "pay_satisfaction": explanation.components["Beloning"],
                "driver": explanation.driver_name,
                # engagement variance decomposition (parts of the score)
                "e_contributions": parts["contributions"], "e_pay_direct": parts["pay"],
                "e_pay_via_satisfaction": pay_via_satisfaction,
                "e_satisfaction_other": parts["satisfaction"] - pay_via_satisfaction,
                "e_performance_career": parts["performance"] + parts["momentum"],
                "e_department": parts["department"], "e_personal": parts["personal"],
                "e_manager": parts["manager"], "e_time_varying": parts["time_varying"],
            })
    return pd.DataFrame(rows)


def band_shares(scores, bands):
    minimums = [float(band["Minimum_Score"]) for band in bands]
    index = np.clip(np.searchsorted(minimums, scores.to_numpy(), side="right") - 1, 0, len(minimums) - 1)
    return pd.Series(np.bincount(index, minlength=len(minimums)) / len(scores), index=BAND_NAMES)
