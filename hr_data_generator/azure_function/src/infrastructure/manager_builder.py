import math

import pandas as pd


MIN_TEAM_SIZE = 8
TARGET_TEAM_SIZE = 15
MAX_TEAM_SIZE = 22


def assign_managers(
    dim_employee_df: pd.DataFrame,
    fact_employment_df: pd.DataFrame,
    dim_role: pd.DataFrame,
    rng=None,
    today=None,
    staffing_rules=None
) -> pd.DataFrame:
    """Assign managers as an acyclic hierarchy, and refresh each employee's
    current role/department alongside it.

    The hierarchy is intentionally simple and BI-friendly:
    CEO -> department heads -> team leads -> employees. Manager_Key is stored on
    dim_employee because that is where the schema defines it. Role_Key and
    Department_Key are kept on dim_employee the same way and from the same
    role context - a current-state convenience column for reporting that
    needs "this employee's role right now" without joining through
    fact_employment, not a replacement for that history. Like Manager_Key,
    an employee with no active contract keeps their last known role rather
    than going blank (see `_current_employment_rows`).
    """

    dim_employee_df = dim_employee_df.copy()

    if "Manager_Key" not in dim_employee_df.columns:
        dim_employee_df["Manager_Key"] = None
    for column in ("Role_Key", "Department_Key"):
        if column not in dim_employee_df.columns:
            dim_employee_df[column] = None

    if fact_employment_df.empty or dim_role.empty or dim_employee_df.empty:
        return dim_employee_df

    emp_roles = _build_employee_role_context(
        dim_employee_df,
        fact_employment_df,
        dim_role,
        today
    )

    if emp_roles.empty:
        dim_employee_df["Manager_Key"] = None
        dim_employee_df["Role_Key"] = None
        dim_employee_df["Department_Key"] = None
        return dim_employee_df

    staffing_rules = staffing_rules or {}
    max_team_size = int(
        staffing_rules.get("max_team_size", MAX_TEAM_SIZE)
    )
    assignments = _build_manager_assignments(emp_roles, max_team_size)

    dim_employee_df["Manager_Key"] = dim_employee_df["Employee_Key"].map(
        assignments
    )
    dim_employee_df.loc[
        dim_employee_df["Employee_Key"] == dim_employee_df["Manager_Key"],
        "Manager_Key"
    ] = None

    current_role = emp_roles.set_index("Employee_Key")
    dim_employee_df["Role_Key"] = dim_employee_df["Employee_Key"].map(
        current_role["Role_Key"]
    )
    dim_employee_df["Department_Key"] = dim_employee_df["Employee_Key"].map(
        current_role["Department_Key"]
    )

    return dim_employee_df


def _build_employee_role_context(
    dim_employee_df,
    fact_employment_df,
    dim_role,
    today
):
    today = pd.Timestamp(today) if today is not None else pd.Timestamp.today()
    current_employment = _current_employment_rows(fact_employment_df)

    if current_employment.empty:
        return current_employment

    role_columns = [
        column
        for column in [
            "Role_Key",
            "Department_Key",
            "Role_Name",
            "Leidinggevend",
            "Salaris_min",
            "Salaris_max"
        ]
        if column in dim_role.columns
    ]

    context = current_employment.merge(
        dim_role[role_columns],
        on="Role_Key",
        how="left"
    )

    context = context.merge(
        dim_employee_df[["Employee_Key"]],
        on="Employee_Key",
        how="inner"
    )

    context["Tenure_Years"] = (
        (today - pd.to_datetime(context["Startdatum"])).dt.days / 365.0
        if "Startdatum" in context.columns
        else 0.0
    )
    context["Is_Active"] = (
        context["Dienstverband_status"].eq("Actief")
        if "Dienstverband_status" in context.columns
        else True
    )
    context["Leidinggevend"] = context["Leidinggevend"].fillna(False).astype(bool)

    if "Salaris_max" not in context.columns:
        context["Salaris_max"] = 0

    return context


def _current_employment_rows(fact_employment_df: pd.DataFrame) -> pd.DataFrame:
    current = fact_employment_df.copy()

    if current.empty:
        return current

    if "Startdatum" in current.columns:
        current = current.sort_values(["Employee_Key", "Startdatum"])

    if "Dienstverband_status" not in current.columns:
        return current.drop_duplicates(subset=["Employee_Key"], keep="last")

    # Prefer the current active contract. For employees without an active
    # contract, keep their latest historical contract so dim_employee remains
    # connected to the management hierarchy in historical BI views.
    active = current[current["Dienstverband_status"] == "Actief"]
    inactive_latest = current[
        ~current["Employee_Key"].isin(active["Employee_Key"])
    ].drop_duplicates(subset=["Employee_Key"], keep="last")

    combined = pd.concat([active, inactive_latest], ignore_index=True)
    return combined.drop_duplicates(subset=["Employee_Key"], keep="last")


def _build_manager_assignments(emp_roles, max_team_size=MAX_TEAM_SIZE):
    assignments = {}
    leaders = emp_roles[emp_roles["Leidinggevend"]].copy()

    if leaders.empty:
        return assignments

    active_leaders = leaders[leaders["Is_Active"]].copy()
    management_leaders = active_leaders if not active_leaders.empty else leaders

    ceo_key = _select_top_leader(management_leaders)
    assignments[ceo_key] = None
    report_counts = {ceo_key: 0}

    for department_key, dept_employees in emp_roles.groupby("Department_Key"):
        dept_leaders = management_leaders[
            management_leaders["Department_Key"] == department_key
        ].copy()
        if dept_leaders.empty:
            dept_leaders = leaders[leaders["Department_Key"] == department_key].copy()

        dept_non_leaders = dept_employees[
            ~dept_employees["Employee_Key"].isin(dept_leaders["Employee_Key"])
        ].copy()

        if dept_leaders.empty:
            _assign_to_manager(
                assignments,
                report_counts,
                dept_non_leaders["Employee_Key"].tolist(),
                ceo_key
            )
            continue

        # If a department only has one management role, its managers are
        # parallel team leads. Selecting one as department head would leave
        # the other teams unused and concentrate all staff under one person.
        if dept_leaders["Role_Key"].nunique() == 1:
            peer_manager_keys = dept_leaders["Employee_Key"].tolist()
            _assign_to_manager(
                assignments,
                report_counts,
                peer_manager_keys,
                ceo_key
            )
            for manager_key in peer_manager_keys:
                report_counts.setdefault(manager_key, 0)

            _assign_balanced(
                assignments,
                report_counts,
                dept_non_leaders["Employee_Key"].tolist(),
                peer_manager_keys,
                max_team_size
            )
            continue

        dept_head = _select_department_head(dept_leaders, ceo_key)
        team_leads = dept_leaders[
            ~dept_leaders["Employee_Key"].isin([dept_head, ceo_key])
        ].copy()

        if dept_head != ceo_key:
            assignments[dept_head] = ceo_key
            report_counts[ceo_key] = report_counts.get(ceo_key, 0) + 1
            report_counts.setdefault(dept_head, 0)

        for _, team_lead in team_leads.iterrows():
            assignments[team_lead["Employee_Key"]] = dept_head
            report_counts[dept_head] = report_counts.get(dept_head, 0) + 1
            report_counts.setdefault(team_lead["Employee_Key"], 0)

        staff_manager_pool = team_leads["Employee_Key"].tolist()

        if len(dept_non_leaders) > len(staff_manager_pool) * max_team_size:
            staff_manager_pool.append(dept_head)

        if not staff_manager_pool:
            staff_manager_pool = [dept_head]

        staff_keys = dept_non_leaders["Employee_Key"].tolist()
        _assign_balanced(
            assignments,
            report_counts,
            staff_keys,
            staff_manager_pool,
            max_team_size
        )

    return _remove_cycles(assignments)


def _select_top_leader(leaders):
    return leaders.sort_values(
        ["Is_Active", "Salaris_max", "Tenure_Years", "Employee_Key"],
        ascending=[False, False, False, True]
    ).iloc[0]["Employee_Key"]


def _select_department_head(dept_leaders, ceo_key):
    sorted_leaders = dept_leaders.sort_values(
        ["Is_Active", "Salaris_max", "Tenure_Years", "Employee_Key"],
        ascending=[False, False, False, True]
    )

    non_ceo = sorted_leaders[sorted_leaders["Employee_Key"] != ceo_key]

    if not non_ceo.empty:
        return non_ceo.iloc[0]["Employee_Key"]

    return ceo_key


def _assign_to_manager(assignments, report_counts, employee_keys, manager_key):
    for employee_key in employee_keys:
        if employee_key == manager_key:
            continue

        assignments[employee_key] = manager_key
        report_counts[manager_key] = report_counts.get(manager_key, 0) + 1


def _assign_balanced(
    assignments,
    report_counts,
    employee_keys,
    manager_pool,
    max_team_size=MAX_TEAM_SIZE
):
    if not employee_keys or not manager_pool:
        return

    required_managers = max(1, math.ceil(len(employee_keys) / TARGET_TEAM_SIZE))
    active_pool = manager_pool[:required_managers] or manager_pool

    for employee_key in employee_keys:
        candidates = [
            manager_key
            for manager_key in active_pool
            if manager_key != employee_key
            and report_counts.get(manager_key, 0) < max_team_size
        ]

        if not candidates:
            candidates = [
                manager_key
                for manager_key in manager_pool
                if manager_key != employee_key
            ]

        if not candidates:
            continue

        manager_key = sorted(
            candidates,
            key=lambda key: (report_counts.get(key, 0), key)
        )[0]

        assignments[employee_key] = manager_key
        report_counts[manager_key] = report_counts.get(manager_key, 0) + 1


def _remove_cycles(assignments):
    cleaned = assignments.copy()

    for employee_key in list(cleaned.keys()):
        seen = set()
        current = employee_key

        while current in cleaned and cleaned[current] is not None:
            manager_key = cleaned[current]

            if manager_key in seen or manager_key == employee_key:
                cleaned[employee_key] = None
                break

            seen.add(current)
            current = manager_key

    return cleaned


def build_dim_manager(state):
    dim_employee = state["dim_employee"].copy()

    if dim_employee.empty or "Manager_Key" not in dim_employee.columns:
        state["dim_manager"] = pd.DataFrame(
            columns=["Manager_Key", "Voornaam", "Achternaam"]
        )
        return state

    manager_keys = set(dim_employee["Manager_Key"].dropna().astype(int))
    assignment_history = state.get("fact_manager_assignment", pd.DataFrame())
    if not assignment_history.empty and "Manager_Key" in assignment_history.columns:
        manager_keys.update(
            assignment_history["Manager_Key"].dropna().astype(int)
        )
    dim_manager = dim_employee[
        dim_employee["Employee_Key"].isin(manager_keys)
    ][[
        "Employee_Key",
        "Voornaam",
        "Achternaam"
    ]].copy()

    dim_manager = dim_manager.drop_duplicates(
        subset=["Employee_Key"],
        keep="first"
    ).rename(columns={
        "Employee_Key": "Manager_Key"
    })

    state["dim_manager"] = dim_manager
    return state
