import pandas as pd
import random
from datetime import datetime

from src.core.config_loader import ConfigLoader
from src.application.employee_generation import generate_employees
from src.application.allocation import allocate_headcount


# =====================================================
# 🔹 State builder
# =====================================================

def build_initial_state(config):

    # 🔹 Roles uit config.structure halen
    roles = []
    role_key = 1

    for dept_name, roles_dict in config.structure.items():

        for role_name, role_cfg in roles_dict.items():

            roles.append({
                "Role_Key": role_key,
                "Role_Name": role_name,
                "Department_Name": dept_name,
                "Department_Key": hash(dept_name) % 1000,
                "Leidinggevend": role_cfg["leidinggevend"],
                "Salaris_min": role_cfg["salaris_range"][0],
                "Salaris_max": role_cfg["salaris_range"][1],
                "Ploegendienst_Flag": role_cfg.get("ploegendienst", False)
            })

            role_key += 1

    dim_role = pd.DataFrame(roles)

    # 🔹 Dimensions
    dim_hire_source = pd.DataFrame({
        "HireSource_Key": list(range(1, len(config.dim_hire_source) + 1))
    })

    dim_education_level = pd.DataFrame({
        "EducationLevel": config.dim_education_level,
        "EducationLevel_Key": list(range(1, len(config.dim_education_level) + 1))
    })

    dim_location = pd.DataFrame({
        "Location_Name": list(config.dim_location.keys()),
        "Location_Key": list(range(1, len(config.dim_location) + 1))
    })

    dim_event_type = pd.DataFrame({
        "EventType": config.dim_event_type,
        "EventType_Key": list(range(1, len(config.dim_event_type) + 1))
    })

    # 🔹 Allocation
    role_allocations = allocate_headcount(
        config.structure,
        config.baseline_headcount
    )

    state = {
        "dim_role": dim_role,
        "dim_hire_source": dim_hire_source,
        "dim_education_level": dim_education_level,
        "dim_location": dim_location,
        "dim_event_type": dim_event_type,
        "role_allocations": role_allocations,

        # leeg (fresh run)
        "dim_employee": pd.DataFrame(),
        "fact_employment": pd.DataFrame()
    }

    return state


# =====================================================
# 🔹 Debug run
# =====================================================

def run_debug():

    config = ConfigLoader().load()

    rng = random.Random(config.simulation_seed)
    today = pd.Timestamp(datetime.now())

    state = build_initial_state(config)

    schema = None  # build_record kan hiermee omgaan

    state = generate_employees(
        state=state,
        config=config,
        schema=schema,
        rng=rng,
        today=today
    )

    return state


# =====================================================
# 🔹 Main
# =====================================================

if __name__ == "__main__":

    state = run_debug()

# =====================================================
# 🔍 VALIDATIE CHECKS
# =====================================================

    dim_employee = state["dim_employee"]
    fact_employment = state["fact_employment"]

    assert dim_employee["Employee_Key"].is_unique, \
        "Employee_Key is niet uniek!"

    assert fact_employment["Employee_Key"].notnull().all(), \
        "Er zitten NULL Employee_Keys in fact_employment!"

    assert fact_employment["Employment_Key"].is_unique, \
        "Employment_Key is niet uniek!"

    print("\n✅ VALIDATION PASSED")

# =====================================================
# 🔹 Output
# =====================================================

    print("\n=== DIM EMPLOYEE ===")
    print(state["dim_employee"].head())

    print("\n=== FACT EMPLOYMENT ===")
    print(state["fact_employment"].head())

    print("\n=== ATTRIBUTES ===")
    print(state["fact_employment_attribute"].head())

    print("\n=== CHECKS ===")
    print("Employees:", len(state["dim_employee"]))
    print("Unique keys:", state["dim_employee"]["Employee_Key"].nunique())
    print("Nulls:\n", state["dim_employee"].isnull().sum())