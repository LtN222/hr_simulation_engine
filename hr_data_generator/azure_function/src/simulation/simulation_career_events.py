import pandas as pd

from src.infrastructure.salary_policy import SalaryPolicy
from src.infrastructure.shift_assignment import assign_ploegendienst_key
from src.infrastructure.relevant_experience import carried_experience
from src.infrastructure.role_eligibility import eligible_internal
from src.infrastructure.location_assignment import resolve_location, effective_role_capacity


def simulate_career_events(
    state,
    config,
    schema,
    today,
    rng,
    event_type_map,
    promotion_rate,
    transfer_rate
):
    """Create salary, promotion and transfer employment events.

    Every new employment row carries the same conformed shift, salary-scale
    and target-compa fields. This makes the row self-contained for historical
    reporting and prevents later events from losing their pay context.
    """
    dim_role = state["dim_role"]
    dim_employee = state["dim_employee"]
    dim_department = state["dim_department"]
    fact_employment = state["fact_employment"]
    salary_policy = SalaryPolicy(config, state["dim_salary_scale"])

    fact_employment, salary_next_key = _simulate_salary_reviews(
        fact_employment,
        dim_employee,
        dim_role,
        salary_policy,
        config,
        today,
        rng,
        event_type_map
    )

    active = fact_employment[
        fact_employment["Dienstverband_status"] == "Actief"
    ].copy()
    if active.empty:
        state["fact_employment"] = fact_employment
        return state

    role_lookup = dim_role.set_index("Role_Key")
    department_lookup = dim_department.set_index("Department_Key")
    employee_lookup = dim_employee.set_index("Employee_Key")
    next_key = max(int(fact_employment["Employment_Key"].max()) + 1, salary_next_key)
    new_records = []
    # Tracks capacity-relevant role counts as promotions/transfers happen
    # within this same pass, so a second move into an already-just-filled
    # capped role (e.g. two Teamleiders promoted to the same Manager seat
    # in one week) is correctly refused, not just the first.
    role_counts = active["Role_Key"].value_counts().to_dict()

    for idx, row in active.iterrows():
        employee_key = int(row["Employee_Key"])
        role = role_lookup.loc[row["Role_Key"]]
        department_key = role["Department_Key"]
        department_name = department_lookup.loc[department_key, "Afdeling_Naam"]
        performance = employee_lookup.loc[employee_key, "Prestatie_Score"]
        service_start = employee_lookup.loc[
            employee_key,
            "Aaneengesloten_Indienst_Datum"
        ]
        target_ratio = _target_ratio_for_row(
            row,
            salary_policy,
            role,
            service_start,
            today
        )

        promotion_probability = (promotion_rate / 52) * _performance_factor(performance)
        if rng.random() < promotion_probability:
            target_names = config.role_career_paths.get(
                role["Functie_Naam"], {}
            ).get("logische_doorgroei", [])
            candidates = dim_role[dim_role["Functie_Naam"].isin(target_names)]
            candidates = candidates[candidates.apply(lambda target: eligible_internal(config, state, employee_key, role, target, today, performance), axis=1)]
            candidates = candidates[candidates.apply(
                lambda target: _under_capacity(
                    state, config, department_lookup, role_counts, target
                ),
                axis=1
            )]
            if not candidates.empty:
                new_role = candidates.sample(
                    n=1,
                    random_state=rng.randint(0, 100000)
                ).iloc[0]
                promoted_ratio = salary_policy.clamp_ratio(
                    target_ratio + 0.015 + max(0, float(performance) - 3.5) * 0.01
                )
                new_department_name = department_lookup.loc[
                    new_role["Department_Key"], "Afdeling_Naam"
                ]
                new_location_key = resolve_location(
                    state, config, rng, new_department_name, new_role["Functie_Naam"],
                    preferred_location_key=row["Location_Key"],
                )
                _close_employment(fact_employment, idx, today)
                new_records.append(_new_employment_record(
                    row,
                    next_key,
                    new_role,
                    today,
                    event_type_map["Promotie"],
                    salary_policy,
                    config,
                    service_start,
                    promoted_ratio,
                    assign_ploegendienst_key(new_role, state, config, rng),
                    previous_department_key=department_key,
                    location_key=new_location_key,
                ))
                next_key += 1
                role_counts[new_role["Role_Key"]] = role_counts.get(
                    new_role["Role_Key"], 0
                ) + 1
                continue

        target_names = config.role_career_paths.get(role["Functie_Naam"], {}).get("laterale_transfers", [])
        if rng.random() >= transfer_rate / 52 or not target_names:
            continue
        candidates = dim_role[dim_role["Functie_Naam"].isin(target_names)]
        candidates = candidates[candidates.apply(lambda target: eligible_internal(config, state, employee_key, role, target, today, performance), axis=1)]
        candidates = candidates[candidates.apply(
            lambda target: _under_capacity(
                state, config, department_lookup, role_counts, target
            ),
            axis=1
        )]
        if candidates.empty:
            continue

        new_role = candidates.sample(
            n=1,
            random_state=rng.randint(0, 100000)
        ).iloc[0]
        new_department_name = department_lookup.loc[
            new_role["Department_Key"], "Afdeling_Naam"
        ]
        new_location_key = resolve_location(
            state, config, rng, new_department_name, new_role["Functie_Naam"],
            preferred_location_key=row["Location_Key"],
        )
        _close_employment(fact_employment, idx, today)
        new_records.append(_new_employment_record(
            row,
            next_key,
            new_role,
            today,
            event_type_map["Transfer"],
            salary_policy,
            config,
            service_start,
            target_ratio,
            assign_ploegendienst_key(new_role, state, config, rng),
            previous_department_key=department_key,
            location_key=new_location_key,
        ))
        next_key += 1
        role_counts[new_role["Role_Key"]] = role_counts.get(new_role["Role_Key"], 0) + 1

    if new_records:
        fact_employment = pd.concat(
            [fact_employment, pd.DataFrame(new_records)],
            ignore_index=True
        )
    state["fact_employment"] = fact_employment
    return state


def _simulate_salary_reviews(
    fact_employment,
    dim_employee,
    dim_role,
    salary_policy,
    config,
    today,
    rng,
    event_type_map
):
    salary_event_key = event_type_map.get("Salarisaanpassing")
    if salary_event_key is None:
        return fact_employment, int(fact_employment["Employment_Key"].max()) + 1

    increase_rate = config.career_events.get("salary_increase_rate", 1.0)
    active = fact_employment[
        fact_employment["Dienstverband_status"] == "Actief"
    ].copy()
    if active.empty:
        return fact_employment, int(fact_employment["Employment_Key"].max()) + 1

    roles = dim_role.set_index("Role_Key")
    employees = dim_employee.set_index("Employee_Key")
    next_key = int(fact_employment["Employment_Key"].max()) + 1
    new_records = []

    for idx, row in active.iterrows():
        employee_key = int(row["Employee_Key"])
        if today.isocalendar()[1] != _salary_review_week(employee_key):
            continue
        if rng.random() > increase_rate or pd.Timestamp(row["Startdatum"]).year == today.year:
            continue
        if _already_reviewed_this_year(fact_employment, employee_key, salary_event_key, today.year):
            continue

        role = roles.loc[row["Role_Key"]]
        service_start = employees.loc[employee_key, "Aaneengesloten_Indienst_Datum"]
        performance = employees.loc[employee_key, "Prestatie_Score"]
        target_ratio = _target_ratio_for_row(
            row,
            salary_policy,
            role,
            service_start,
            today
        )
        new_salary, new_target_ratio = salary_policy.review_salary(
            role,
            None,
            service_start,
            today,
            int(row["Salaris"]),
            target_ratio,
            performance
        )
        if new_salary <= int(row["Salaris"]):
            continue

        _close_employment(fact_employment, idx, today)
        new_records.append(_new_employment_record(
            row,
            next_key,
            role,
            today,
            salary_event_key,
            salary_policy,
            config,
            service_start,
            new_target_ratio,
            row.get("Shift_Key"),
            salary_override=new_salary,
            previous_department_key=role["Department_Key"],
        ))
        next_key += 1

    if new_records:
        fact_employment = pd.concat(
            [fact_employment, pd.DataFrame(new_records)],
            ignore_index=True
        )
    return fact_employment, next_key


def _new_employment_record(
    previous_row,
    employment_key,
    role,
    today,
    event_type_key,
    salary_policy,
    config,
    service_start,
    target_ratio,
    ploegendienst_key,
    salary_override=None,
    previous_department_key=None,
    location_key=None,
):
    benchmark = salary_policy.employee_benchmark(role, today, service_start)
    salary = salary_override or int(round(
        benchmark["Benchmark_Salaris"] * target_ratio
    ))
    return {
        "Employment_Key": employment_key,
        "Previous_Employment_Key": previous_row["Employment_Key"],
        "Employee_Key": previous_row["Employee_Key"],
        "HireSource_Key": previous_row.get("HireSource_Key"),
        "Role_Key": role.get("Role_Key", role.name),
        "Location_Key": (
            previous_row["Location_Key"] if location_key is None else location_key
        ),
        "Shift_Key": ploegendienst_key,
        "SalaryScale_Key": role["SalaryScale_Key"],
        "Streef_Compa_Ratio": target_ratio,
        "Relevante_Ervaring_Jaren_Bij_Start": carried_experience(
            previous_row,
            today,
            previous_department_key == role["Department_Key"],
            config,
        ),
        "Startdatum": today,
        "Einddatum": None,
        "Dienstverband_status": "Actief",
        "Salaris": salary,
        "Contracttype": previous_row["Contracttype"],
        "Contracturen": previous_row.get("Contracturen"),
        "Contract_einddatum": previous_row.get("Contract_einddatum"),
        "Contract_ronde": previous_row.get("Contract_ronde"),
        "EventType_Key": event_type_key,
        "DepartureReason_Key": None,
        "Tevredenheid_Score_Bij_Uitdienst": None,
        "SatisfactionBand_Key_Bij_Uitdienst": None,
    }


def _under_capacity(state, config, department_lookup, role_counts, target_role):
    """Whether promoting/transferring someone into `target_role` is still
    allowed - i.e. it has no hard ceiling, or hasn't reached it yet."""
    department_name = department_lookup.loc[
        target_role["Department_Key"], "Afdeling_Naam"
    ]
    capacity = effective_role_capacity(
        state, config, department_name, target_role["Functie_Naam"]
    )
    if capacity is None:
        return True
    return role_counts.get(target_role["Role_Key"], 0) < capacity


def _target_ratio_for_row(row, salary_policy, role, service_start, today):
    value = pd.to_numeric(row.get("Streef_Compa_Ratio"), errors="coerce")
    if pd.notna(value):
        return salary_policy.clamp_ratio(value)
    benchmark = salary_policy.employee_benchmark(role, today, service_start)
    return salary_policy.clamp_ratio(int(row["Salaris"]) / benchmark["Benchmark_Salaris"])


def _close_employment(fact_employment, index, today):
    fact_employment.loc[index, "Einddatum"] = today
    fact_employment.loc[index, "Dienstverband_status"] = "Inactief"


def _performance_factor(performance):
    if performance >= 4:
        return 1.8
    if performance >= 3.5:
        return 1.3
    if performance < 2.5:
        return 0.5
    return 1.0


def _salary_review_week(employee_key):
    return ((employee_key * 37) % 52) + 1


def _already_reviewed_this_year(fact_employment, employee_key, salary_event_key, year):
    rows = fact_employment[
        (fact_employment["Employee_Key"] == employee_key)
        & (fact_employment["EventType_Key"] == salary_event_key)
    ]
    if rows.empty:
        return False
    review_years = pd.to_datetime(rows["Startdatum"], errors="coerce").dt.year
    return (review_years == year).any()
