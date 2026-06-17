import pandas as pd

from src.infrastructure.record_builder import build_record


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
        dim_education_level = state["dim_education_level"]

        role_lookup = dim_role.set_index("Role_Key")
        edu_lookup = dim_education_level.set_index("EducationLevel_Key")

        records = []
        review_key = 1

        for _, emp in dim_employee.iterrows():

            employee_key = emp["Employee_Key"]

            employment_row = fact_employment.loc[
                fact_employment["Employee_Key"] == employee_key
            ].iloc[0]

            role = role_lookup.loc[employment_row["Role_Key"]]

            education = edu_lookup.loc[
                emp["EducationLevel_Key"]
            ]["EducationLevel"]

            startdatum = employment_row["Startdatum"]

            reviews = self._generate_reviews(
                employee_key,
                startdatum,
                role,
                education,
                today,
                review_key
            )

            records.extend(reviews["records"])
            review_key = reviews["next_key"]

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
        education,
        today,
        review_key_start
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

        for i in range(review_count):

            review_date = startdatum + pd.DateOffset(
                years=i + 1,
                days=self.rng.randint(-30, 30)
            )

            # ✅ Extra guard (future-proof)
            if review_date < startdatum:
                continue

            if review_date > today:
                continue

            score = self._calculate_score(
                tenure_years,
                education,
                role["Leidinggevend"]
            )

            records.append(
                build_record(
                    self.schema,
                    "fact_performance_review",
                    {
                        "PerformanceReview_Key": review_key,
                        "Employee_Key": employee_key,
                        "Review_Datum": review_date,
                        "Performance_Score": score
                    }
                )
            )

            review_key += 1

        return {
            "records": records,
            "next_key": review_key
        }
    
    def _calculate_score(self, tenure_years, education, is_manager):

        score = self.rng.normalvariate(3.4, 0.6)

        # Minder ervaren medewerkers iets lagere score
        if tenure_years < 2:
            score -= 0.3

        # Opleidingseffect
        if education == "WO":
            score += 0.1
        elif education == "PhD":
            score += 0.2

        # Leidinggevenden iets hoger
        if is_manager:
            score += 0.15

        # 🔥 NIEUW: tenure-based groei (max +0.3)
        score += min(0.3, tenure_years * 0.05)

        # 🔥 NIEUW: kleine jaarlijkse fluctuatie
        score += self.rng.normalvariate(0, 0.1)

        # Clamp tussen 1 en 5
        return round(max(1, min(5, score)), 2)