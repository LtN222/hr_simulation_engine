from src.generator.record_builder import build_record
import pandas as pd

def generate_performance_reviews(state, config, schema, rng, today):

    dim_employee = state["dim_employee"]
    fact_employment = state["fact_employment"]
    dim_role = state["dim_role"]
    dim_education_level = state["dim_education_level"]

    records = []
    review_key = 1

    role_lookup = dim_role.set_index("Role_Key")
    edu_lookup = dim_education_level.set_index("EducationLevel_Key")

    for _, emp in dim_employee.iterrows():

        employee_key = emp["Employee_Key"]

        employment_row = fact_employment.loc[
            fact_employment["Employee_Key"] == employee_key
        ].iloc[0]

        role_key = employment_row["Role_Key"]
        role = role_lookup.loc[role_key]

        education_key = emp["EducationLevel_Key"]
        education = edu_lookup.loc[education_key]["EducationLevel"]

        startdatum = employment_row["Startdatum"]

        tenure_years = max(1, (today - startdatum).days // 365)

        review_count = min(tenure_years, 5)

        for i in range(review_count):

            review_date = startdatum + pd.DateOffset(
                years=i + 1
            )

            if review_date > today:
                continue

            score = rng.normalvariate(3.4, 0.6)

            if tenure_years < 2:
                score -= 0.3

            if education == "WO":
                score += 0.1
            elif education == "PhD":
                score += 0.2

            if role["Leidinggevend"]:
                score += 0.15

            score = round(max(1, min(5, score)), 2)

            records.append(

                build_record(
                    schema,
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

    state["fact_performance_review"] = pd.DataFrame(records)

    return state