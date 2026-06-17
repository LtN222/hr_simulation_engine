import pandas as pd

from src.application.population import WorkforceGenerator


# =====================================================
# 🔹 Debug run
# =====================================================

def run_debug():

    generator = WorkforceGenerator(
        sector="maakindustrie",
        seed=42
    )

    state = generator.run()

    return state


# =====================================================
# 🔍 Validatie
# =====================================================

def validate_state(state):

    print("\n=== VALIDATION ===")

    dim_employee = state["dim_employee"]
    fact_employment = state["fact_employment"]

    # 🔹 Keys
    assert dim_employee["Employee_Key"].is_unique, \
        "❌ Employee_Key is niet uniek"

    assert fact_employment["Employment_Key"].is_unique, \
        "❌ Employment_Key is niet uniek"

    # 🔹 Null checks
    assert dim_employee["Employee_Key"].notnull().all(), \
        "❌ NULL Employee_Key"

    assert fact_employment["Employee_Key"].notnull().all(), \
        "❌ NULL Employee_Key in fact_employment"

    # 🔹 1-op-1 check
    assert len(dim_employee) == len(fact_employment), \
        "❌ Employees en employment mismatch"

    # 🔹 Manager sanity
    if "Manager_Key" in dim_employee.columns:
        null_managers = dim_employee["Manager_Key"].isnull().sum()
        print(f"ℹ️ Managers zonder manager (incl CEO): {null_managers}")

    print("✅ VALIDATION PASSED")


# =====================================================
# 🔹 Debug output
# =====================================================

def print_sample(state):

    print("\n=== DIM EMPLOYEE ===")
    print(state["dim_employee"].head())

    print("\n=== FACT EMPLOYMENT ===")
    print(state["fact_employment"].head())

    if "fact_employment_attribute" in state:
        print("\n=== ATTRIBUTES ===")
        print(state["fact_employment_attribute"].head())

    if "fact_absence" in state:
        print("\n=== ABSENCE ===")
        print(state["fact_absence"].head())

    if "fact_performance_review" in state:
        print("\n=== PERFORMANCE ===")
        print(state["fact_performance_review"].head())


# =====================================================
# 🔹 Optional: export
# =====================================================

def export_to_csv(state):

    for name, df in state.items():
        if isinstance(df, pd.DataFrame):
            df.to_csv(f"debug_{name}.csv", index=False)

    print("\n📁 CSV export gedaan")


def extra_checks(state):

    print("\n=== EXTRA CHECKS ===")

    dim_employee = state["dim_employee"]
    fact_employment = state["fact_employment"]
    fact_absence = state.get("fact_absence")
    fact_performance = state.get("fact_performance_review")

    # 🔹 Lookup voor snelheid
    employment_lookup = fact_employment.set_index("Employee_Key")

    # =====================================================
    # 1️⃣ Absence vóór employment check
    # =====================================================

    if fact_absence is not None:

        invalid_absence = []

        for _, row in fact_absence.iterrows():

            emp_key = row["Employee_Key"]
            start_absence = row["Startdatum"]

            employment_start = employment_lookup.loc[emp_key]["Startdatum"]

            if start_absence < employment_start:
                invalid_absence.append(emp_key)

        if invalid_absence:
            print(f"❌ Absence vóór employment bij employees: {set(invalid_absence)}")
        else:
            print("✅ Absence dates OK")

    # =====================================================
    # 2️⃣ Performance vóór employment check
    # =====================================================

    if fact_performance is not None:

        invalid_perf = []

        for _, row in fact_performance.iterrows():

            emp_key = row["Employee_Key"]
            review_date = row["Review_Datum"]

            employment_start = employment_lookup.loc[emp_key]["Startdatum"]

            if review_date < employment_start:
                invalid_perf.append(emp_key)

        if invalid_perf:
            print(f"❌ Performance vóór employment bij employees: {set(invalid_perf)}")
        else:
            print("✅ Performance dates OK")

    # =====================================================
    # 3️⃣ Manager sanity
    # =====================================================

    if "Manager_Key" in dim_employee.columns:

        self_managed = dim_employee[
            dim_employee["Employee_Key"] == dim_employee["Manager_Key"]
        ]

        if len(self_managed) > 0:
            print(f"❌ Employees die zichzelf managen: {len(self_managed)}")
        else:
            print("✅ Geen self-managed employees")

    # =====================================================
    # 4️⃣ Score range check
    # =====================================================

    if fact_performance is not None:

        if fact_performance["Performance_Score"].between(1, 5).all():
            print("✅ Performance scores binnen range 1–5")
        else:
            print("❌ Performance scores buiten range!")

    # =====================================================
    # 5️⃣ Absence duration sanity
    # =====================================================

    if fact_absence is not None:

        if (fact_absence["Duur_dagen"] > 0).all():
            print("✅ Absence duration OK")
        else:
            print("❌ Absence met 0 of negatieve duur gevonden")

# =====================================================
# 🔹 Main
# =====================================================

if __name__ == "__main__":

    state = run_debug()

    validate_state(state)

    print_sample(state)
    extra_checks(state)

    # 🔥 optioneel
    # export_to_csv(state)