import pandas as pd


# =====================================================
# 🔹 Manager assignment (business logic)
# =====================================================

def assign_managers(
    dim_employee_df: pd.DataFrame,
    fact_employment_df: pd.DataFrame,
    dim_role: pd.DataFrame,
    rng
) -> pd.DataFrame:

    emp_roles = fact_employment_df.merge(
        dim_role[["Role_Key", "Department_Key", "Leidinggevend"]],
        on="Role_Key",
        how="left"
    )

    # 🔹 CEO bepalen (hoogste salaris rol)
    top_role = dim_role.sort_values(
        "Salaris_max",
        ascending=False
    ).iloc[0]

    ceo_candidates = emp_roles[
        emp_roles["Role_Key"] == top_role["Role_Key"]
    ]

    if len(ceo_candidates) > 0:
        ceo_key = ceo_candidates.iloc[0]["Employee_Key"]

        dim_employee_df.loc[
            dim_employee_df["Employee_Key"] == ceo_key,
            "Manager_Key"
        ] = None
    else:
        ceo_key = None

    # 🔹 Managers per afdeling
    managers = emp_roles[
        emp_roles["Leidinggevend"] == True
    ]

    for _, emp in emp_roles.iterrows():

        emp_key_val = emp["Employee_Key"]

        if emp_key_val == ceo_key:
            continue

        dept = emp["Department_Key"]

        dept_managers = managers[
            managers["Department_Key"] == dept
        ]

        # zichzelf uitsluiten
        dept_managers = dept_managers[
            dept_managers["Employee_Key"] != emp_key_val
        ]

        # CEO uitsluiten
        if ceo_key is not None:
            dept_managers = dept_managers[
                dept_managers["Employee_Key"] != ceo_key
            ]

        if len(dept_managers) == 0:
            continue

        manager_key = rng.choice(
            dept_managers["Employee_Key"].tolist()
        )

        dim_employee_df.loc[
            dim_employee_df["Employee_Key"] == emp_key_val,
            "Manager_Key"
        ] = manager_key

    return dim_employee_df


# =====================================================
# 🔹 Build dim_manager (mapping)
# =====================================================

def build_dim_manager(state):

    dim_employee = state["dim_employee"]

    manager_keys = dim_employee["Manager_Key"].dropna().unique()

    dim_manager = dim_employee[
        dim_employee["Employee_Key"].isin(manager_keys)
    ][[
        "Employee_Key",
        "Voornaam",
        "Achternaam"
    ]].copy()

    dim_manager.rename(columns={
        "Employee_Key": "Manager_Key"
    }, inplace=True)

    state["dim_manager"] = dim_manager

    return state