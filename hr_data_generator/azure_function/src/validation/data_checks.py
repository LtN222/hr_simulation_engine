def validate_headcount(state):

    employees = state["dim_employee"]

    if len(employees) == 0:
        raise ValueError("No employees generated")


