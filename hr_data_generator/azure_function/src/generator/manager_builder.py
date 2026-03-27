def build_dim_manager(state):

    dim_employee = state["dim_employee"]

    # managers = iedereen die als manager voorkomt
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