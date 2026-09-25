import pandas as pd

from src.infrastructure.record_builder import build_record
from src.infrastructure.engagement import (
    EngagementModel,
    score_employee_engagement,
)
from src.infrastructure.satisfaction import (
    SatisfactionModel,
    score_employee_satisfaction,
)
from src.infrastructure.driver_selection import driver_key_for
from src.infrastructure.relevant_experience import experience_as_of


class PerformanceSimulator:

    def __init__(self, config, schema, rng):
        self.config = config
        self.schema = schema
        self.rng = rng

    # =====================================================
    # 🔹 Public API
    # =====================================================

    def run(self, state, today):

        dim_employee = state["dim_employee"]
        fact_employment = state["fact_employment"]
        dim_role = state["dim_role"]

        role_lookup = dim_role.set_index("Role_Key")

        records = []
        review_key = 1

        for _, emp in dim_employee.iterrows():

            employee_key = emp["Employee_Key"]

            employment_row = fact_employment.loc[
                fact_employment["Employee_Key"] == employee_key
            ].iloc[0]

            role = role_lookup.loc[employment_row["Role_Key"]]

            startdatum = employment_row["Startdatum"]

            reviews = self._generate_reviews(
                employee_key,
                startdatum,
                role,
                today,
                review_key,
                employment_row,
                state,
            )

            records.extend(reviews["records"])
            review_key = reviews["next_key"]

        state["fact_performance_review"] = pd.DataFrame(records)
        self._sync_latest_scores_to_employee(state)

        return state

    def run_weekly(self, state, today):
        """Append annual performance reviews when an employee is due."""

        existing = state.get("fact_performance_review", pd.DataFrame())
        dim_employee = state["dim_employee"]
        fact_employment = state["fact_employment"]
        dim_role = state["dim_role"]

        active = fact_employment[
            fact_employment["Dienstverband_status"] == "Actief"
        ].copy()

        if active.empty:
            return state

        active = active.sort_values(["Employee_Key", "Startdatum"])
        active = active.drop_duplicates(subset=["Employee_Key"], keep="last")

        role_lookup = dim_role.set_index("Role_Key")
        employee_lookup = dim_employee.set_index("Employee_Key")
        satisfaction_model = SatisfactionModel(self.config)
        engagement_model = EngagementModel(self.config)
        review_key = (
            int(existing["PerformanceReview_Key"].max()) + 1
            if not existing.empty and "PerformanceReview_Key" in existing.columns
            else 1
        )
        records = []

        for _, employment in active.iterrows():
            employee_key = employment["Employee_Key"]

            if today.isocalendar()[1] != self._review_week(employee_key):
                continue

            if self._already_reviewed_this_year(existing, employee_key, today.year):
                continue

            emp = employee_lookup.loc[employee_key]
            role = role_lookup.loc[employment["Role_Key"]]
            tenure_days = self._tenure_days(emp, today)

            if tenure_days < 180:
                continue

            previous_score = self._latest_score(existing, emp)
            satisfaction = score_employee_satisfaction(
                satisfaction_model,
                state,
                emp,
                employment,
                today,
                performance_score=previous_score,
            )
            engagement = score_employee_engagement(
                engagement_model,
                state,
                emp,
                employment,
                today,
                satisfaction_score=satisfaction,
                performance_score=previous_score,
            )
            score = self._calculate_score(
                role["Leidinggevend"],
                previous_score=previous_score,
                engagement_effect=self._engagement_review_effect(engagement),
                relevant_experience=experience_as_of(employment, today),
                employee_key=employee_key,
            )
            driver_key = self._performance_driver_key(
                state, employee_key, today, role["Leidinggevend"],
                experience_as_of(employment, today), engagement,
            )

            records.append(
                build_record(
                    self.schema,
                    "fact_performance_review",
                    {
                        "PerformanceReview_Key": review_key,
                        "Employee_Key": employee_key,
                        "Review_Datum": today,
                        "Prestatie_Score": score,
                        "PerformanceDriver_Key": driver_key,
                    }
                )
            )
            review_key += 1

        if records:
            state["fact_performance_review"] = pd.concat(
                [existing, pd.DataFrame(records)],
                ignore_index=True
            )
            self._sync_latest_scores_to_employee(state)
        elif "fact_performance_review" not in state:
            state["fact_performance_review"] = pd.DataFrame(records)

        return state

    # =====================================================
    # 🔹 Logic
    # =====================================================

    def _generate_reviews(
        self,
        employee_key,
        startdatum,
        role,
        today,
        review_key_start,
        employment,
        state,
    ):

        records = []
        review_key = review_key_start

        # ⛔ Skip als werknemer nog geen jaar in dienst is
        tenure_days = (today - startdatum).days
        if tenure_days < 365:
            return {
                "records": records,
                "next_key": review_key
            }

        tenure_years = tenure_days // 365
        review_count = min(tenure_years, 5)
        # Backfill the most recent anniversaries, not the first ones, so a
        # long-tenured employee's history ends just before the start date.
        first_anniversary = tenure_years - review_count + 1
        previous_score = None

        for i in range(review_count):

            review_date = startdatum + pd.DateOffset(
                years=first_anniversary + i,
                days=self.rng.randint(-30, 30)
            )

            # ✅ Extra guard (future-proof)
            if review_date < startdatum:
                continue

            if review_date > today:
                continue

            score = self._calculate_score(
                role["Leidinggevend"],
                previous_score=previous_score,
                relevant_experience=experience_as_of(employment, review_date),
                employee_key=employee_key,
            )
            previous_score = score

            records.append(
                build_record(
                    self.schema,
                    "fact_performance_review",
                    {
                        "PerformanceReview_Key": review_key,
                        "Employee_Key": employee_key,
                        "Review_Datum": review_date,
                        "Prestatie_Score": score,
                        "PerformanceDriver_Key": self._performance_driver_key(
                            state,
                            employee_key,
                            review_date,
                            role["Leidinggevend"],
                            experience_as_of(employment, review_date),
                            None,
                        ),
                    }
                )
            )

            review_key += 1

        return {
            "records": records,
            "next_key": review_key
        }
    
    def _calculate_score(
        self,
        is_manager,
        previous_score=None,
        engagement_effect=0.0,
        relevant_experience=0.0,
        employee_key=None,
    ):
        """Score = stable personal level + a partly persistent yearly deviation.

        Only the *deviation* from the personal level carries over between
        reviews. Carrying over the whole previous score (as an earlier version
        did) re-adds every bonus each year, so the long-run score drifted to
        baseline + 4x the bonuses and most long-tenured employees ended up
        pinned at the 5.0 cap. The configured values are calibrated so the
        population lands on a realistic Dutch distribution (mean ~3.35, ~7%
        at 4.0 or higher, well under 1% at 4.5 or higher).
        """
        settings = self._settings
        expected = self._expected_score(is_manager, relevant_experience, employee_key)

        persistence = float(settings.get("year_to_year_persistence", 0.35))
        variation = float(settings.get("yearly_variation_sd", 0.33))
        previous = pd.to_numeric(previous_score, errors="coerce")
        if pd.isna(previous):
            # No earlier review: draw from the stationary deviation spread.
            deviation = self.rng.normalvariate(
                0, variation / (1 - persistence ** 2) ** 0.5
            )
        else:
            max_carry = float(settings.get("max_carried_deviation", 1.0))
            carried = max(-max_carry, min(max_carry, float(previous) - expected))
            deviation = persistence * carried + self.rng.normalvariate(0, variation)

        # Keep engagement's forward effect small to avoid a feedback loop.
        cap = float(settings.get("engagement_effect_cap", 0.12))
        score = expected + deviation + max(-cap, min(cap, float(engagement_effect)))

        return round(max(1, min(5, score)), 2)

    def _expected_score(self, is_manager, relevant_experience, employee_key):
        settings = self._settings
        weights = settings.get("trait_weights", {})
        score = float(settings.get("baseline", 3.2))

        # These are bounded role-normalised behavioural signals; they do not
        # reward overtime, availability, absence, or a raw effort proxy.
        if employee_key is not None:
            stable = EngagementModel(None)._stable_value
            score += stable(employee_key, "execution") * float(
                weights.get("execution", 0.30)
            )
            score += stable(employee_key, "collaboration") * float(
                weights.get("collaboration", 0.19)
            )
            score += stable(employee_key, "initiative") * float(
                weights.get("initiative", 0.19)
            )
            score += stable(employee_key, "coaching") * float(
                weights.get("coaching_manager", 0.26) if is_manager
                else weights.get("coaching", 0.15)
            )

        if is_manager:
            score += float(settings.get("manager_effect", 0.10))

        # Relevant vakmanschap (prior plus in-role experience) is the single
        # experience signal; plain tenure is not counted separately on top.
        ramp = float(settings.get("experience_ramp_years", 6))
        experience = max(0.0, float(relevant_experience or 0.0))
        score += float(settings.get("experience_effect_max", 0.20)) * min(
            1.0, experience / ramp if ramp > 0 else 1.0
        )
        return score

    @property
    def _settings(self):
        return getattr(self.config, "performance", None) or {}

    def _performance_driver_key(
        self, state, employee_key, review_date, is_manager,
        relevant_experience, engagement,
    ):
        """Explain a review with one bounded, work-relevant dominant factor."""
        stable = EngagementModel(None)._stable_value
        candidates = {
            "Resultaat en werkuitvoering": stable(employee_key, "execution"),
            "Vakmanschap en relevante ervaring": min(1.0, relevant_experience / 8),
            "Samenwerking en flexibiliteit": stable(employee_key, "collaboration"),
            "Initiatief en verbeteren": stable(employee_key, "initiative"),
            "Coachen, kennisdeling en ontwikkeling van anderen": (
                stable(employee_key, "coaching") * (1.35 if is_manager else 1.0)
            ),
        }
        # No education-direction attribute exists yet. Consequently the
        # start-qualification driver is deliberately not inferred from level.
        if engagement is not None:
            candidates["Initiatief en verbeteren"] += max(
                -0.20, min(0.20, (float(engagement) - 6.7) * 0.08)
            )
        name = max(candidates, key=lambda candidate: abs(candidates[candidate]))
        return driver_key_for(
            state.get("dim_performance_driver", pd.DataFrame()), name
        )

    def _engagement_review_effect(self, engagement):
        coefficient = float(getattr(self.config, "engagement", {}).get(
            "performance_review_effect",
            0.08,
        ))
        return (float(engagement) - 6.7) * coefficient

    def _tenure_days(self, emp, today):
        """Days since the employee's true, continuous hire date.

        Deliberately not `employment["Startdatum"]`: that column is the
        current fact_employment *event's* start date, which a promotion,
        transfer or routine salary review resets every time it fires - using
        it here would make an employee look newly hired right after any such
        event, permanently blocking their annual review if that event's
        fixed week happens to fall within 180 days of their fixed review
        week (it did for roughly a third of employees before this fix).
        """
        hire_date = pd.to_datetime(emp["Aaneengesloten_Indienst_Datum"], errors="coerce")
        return (pd.Timestamp(today) - hire_date).days

    def _review_week(self, employee_key):
        return ((int(employee_key) * 31) % 52) + 1

    def _already_reviewed_this_year(self, reviews, employee_key, year):
        if reviews.empty:
            return False

        employee_reviews = reviews[reviews["Employee_Key"] == employee_key]
        if employee_reviews.empty:
            return False

        review_years = pd.to_datetime(
            employee_reviews["Review_Datum"],
            errors="coerce"
        ).dt.year
        return (review_years == year).any()

    def _latest_score(self, reviews, employee):
        if reviews.empty:
            return employee.get("Prestatie_Score", 3.4)

        employee_reviews = reviews[reviews["Employee_Key"] == employee.name]
        if employee_reviews.empty:
            return employee.get("Prestatie_Score", 3.4)

        latest = employee_reviews.sort_values("Review_Datum").iloc[-1]
        return latest["Prestatie_Score"]

    def _sync_latest_scores_to_employee(self, state):
        reviews = state.get("fact_performance_review", pd.DataFrame())
        if reviews.empty:
            return

        latest_scores = (
            reviews.sort_values("Review_Datum")
            .drop_duplicates(subset=["Employee_Key"], keep="last")
            .set_index("Employee_Key")["Prestatie_Score"]
        )

        dim_employee = state["dim_employee"].copy()
        dim_employee["Prestatie_Score"] = dim_employee.apply(
            lambda row: latest_scores.get(
                row["Employee_Key"],
                row["Prestatie_Score"]
            ),
            axis=1
        )
        state["dim_employee"] = dim_employee
