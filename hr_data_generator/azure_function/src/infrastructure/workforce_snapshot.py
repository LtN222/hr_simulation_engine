"""Build monthly workforce snapshots for historically correct HR analysis."""

import pandas as pd

from src.infrastructure.record_builder import build_record
from src.infrastructure.manager_assignment import manager_as_of
from src.infrastructure.salary_band import salary_band_key_for
from src.infrastructure.salary_benchmark import SalaryBenchmarkBuilder
from src.infrastructure.relevant_experience import experience_as_of
from src.infrastructure.satisfaction import (
    SatisfactionModel,
    explain_employee_satisfaction,
)
from src.infrastructure.engagement import (
    EngagementModel,
    score_employee_engagement,
    engagement_driver_key_for,
)


def build_workforce_snapshots(
    state,
    schema,
    config=None,
    start_date=None,
    end_date=None
):
    """Create one active employee record for every month-end snapshot."""
    employment = state.get("fact_employment", pd.DataFrame()).copy()
    if employment.empty:
        state["fact_workforce_snapshot"] = pd.DataFrame()
        return state

    employment["Startdatum"] = pd.to_datetime(employment["Startdatum"])
    employment["Einddatum"] = pd.to_datetime(
        employment["Einddatum"],
        errors="coerce"
    )
    snapshot_dates = _snapshot_dates(employment, start_date, end_date)
    employee_lookup = _indexed(state.get("dim_employee", pd.DataFrame()), "Employee_Key")
    role_lookup = _indexed(state.get("dim_role", pd.DataFrame()), "Role_Key")
    department_lookup = _indexed(
        state.get("dim_department", pd.DataFrame()),
        "Department_Key"
    )
    performance_reviews = _performance_reviews(
        state.get("fact_performance_review", pd.DataFrame())
    )
    manager_assignments = _manager_assignments(
        state.get("fact_manager_assignment", pd.DataFrame())
    )
    absence = _absence_episodes(
        state.get("fact_absence", pd.DataFrame()),
        state.get("dim_absence_type", pd.DataFrame())
    )
    benchmark_builder = SalaryBenchmarkBuilder(state, schema, config)
    satisfaction_model = SatisfactionModel(config)
    engagement_model = EngagementModel(config)
    records = []

    for snapshot_date in snapshot_dates:
        active = _active_employment(employment, snapshot_date)
        absence_metrics = _absence_metrics_for_month(absence, snapshot_date)
        for _, row in active.iterrows():
            employee = employee_lookup.get(row["Employee_Key"], {})
            role = role_lookup.get(row["Role_Key"], {})
            department_key = role.get("Department_Key")
            department = department_lookup.get(department_key, {})
            performance = _performance_as_of(
                performance_reviews,
                row["Employee_Key"],
                snapshot_date,
                employee.get("Prestatie_Score", 3.4)
            )
            performance_driver_key = _performance_driver_as_of(
                performance_reviews, row["Employee_Key"], snapshot_date
            )
            benchmark_fields = _benchmark_fields(
                benchmark_builder,
                row,
                snapshot_date
            )
            compa_ratio = _compa_ratio(
                row.get("Salaris"),
                benchmark_fields.get("Benchmark_Salaris"),
                row.get("Streef_Compa_Ratio")
            )
            manager_key = manager_as_of(
                manager_assignments,
                row["Employee_Key"],
                snapshot_date
            )
            satisfaction_explanation = explain_employee_satisfaction(
                satisfaction_model,
                state,
                employee,
                row,
                snapshot_date,
                performance_score=performance,
                compa_ratio=compa_ratio,
                manager_key=manager_key,
            )
            satisfaction = satisfaction_explanation.score
            engagement = score_employee_engagement(
                engagement_model,
                state,
                employee,
                row,
                snapshot_date,
                satisfaction_score=satisfaction,
                performance_score=performance,
                compa_ratio=compa_ratio,
                manager_key=manager_key,
            )
            service_start = pd.to_datetime(
                employee.get("Aaneengesloten_Indienst_Datum"),
                errors="coerce"
            )
            absence_for_employee = absence_metrics.get(
                int(row["Employee_Key"]),
                _empty_absence_metrics()
            )
            capacity = _monthly_capacity(row, snapshot_date, config)

            record = {
                "WorkforceSnapshot_Key": _snapshot_key(
                    snapshot_date,
                    row["Employee_Key"]
                ),
                "Snapshot_Date": snapshot_date,
                "Employee_Key": row["Employee_Key"],
                "Employment_Key": row["Employment_Key"],
                "Manager_Key": manager_key,
                "Role_Key": row["Role_Key"],
                "Department_Key": department_key,
                "Location_Key": row.get("Location_Key"),
                "HireSource_Key": employee.get("HireSource_Key"),
                "Education_Key": employee.get("Education_Key"),
                "Shift_Key": row.get("Shift_Key"),
                "SalaryScale_Key": row.get("SalaryScale_Key"),
                "SalaryBand_Key": salary_band_key_for(
                    state.get("dim_salary_band", pd.DataFrame()),
                    row.get("Salaris")
                ),
                "Contracttype": row.get("Contracttype"),
                "Contracturen": row.get("Contracturen"),
                "FTE": _fte(row.get("Contracturen"), config),
                "Salaris": row.get("Salaris"),
                "Prestatie_Score": performance,
                "Aaneengesloten_Indienst_Datum": service_start,
                "Dienstjaren": _service_years(service_start, snapshot_date),
                "Relevante_Ervaring_Jaren": experience_as_of(row, snapshot_date),
                "Tevredenheid_Score": satisfaction,
                "SatisfactionBand_Key": satisfaction_model.band_key_for(
                    state.get("dim_satisfaction_band", pd.DataFrame()),
                    satisfaction
                ),
                "SatisfactionDriver_Key": satisfaction_model.driver_key_for(
                    state.get("dim_satisfaction_driver", pd.DataFrame()),
                    satisfaction_explanation,
                ),
                "Betrokkenheid_Score": engagement,
                "EngagementBand_Key": engagement_model.band_key_for(
                    state.get("dim_engagement_band", pd.DataFrame()),
                    engagement
                ),
                "EngagementDriver_Key": engagement_driver_key_for(
                    state, row["Employee_Key"], snapshot_date, performance,
                    engagement_model,
                ),
                "PerformanceDriver_Key": performance_driver_key,
                **capacity,
                **absence_for_employee,
                **benchmark_fields
            }
            records.append(build_record(schema, "fact_workforce_snapshot", record))

    state["fact_workforce_snapshot"] = pd.DataFrame(records)
    # Benchmarks remain a separate, role-and-step level fact. They are useful
    # for salary-scale analysis but no longer require a duplicate employee
    # salary snapshot table.
    state["fact_salary_benchmark"] = benchmark_builder.build_fact(snapshot_dates)
    return state


def _snapshot_dates(employment, start_date, end_date):
    start = pd.Timestamp(start_date or employment["Startdatum"].min())
    if end_date is None:
        latest_end = employment["Einddatum"].dropna().max()
        end = max(
            date for date in [pd.Timestamp.today(), latest_end] if pd.notna(date)
        )
    else:
        end = pd.Timestamp(end_date)
    return pd.date_range(
        start.to_period("M").to_timestamp("M"),
        end.to_period("M").to_timestamp("M"),
        freq="ME"
    )


def _active_employment(employment, snapshot_date):
    active = employment[(employment["Startdatum"] <= snapshot_date) & (
        employment["Einddatum"].isna() | (employment["Einddatum"] >= snapshot_date)
    )].copy()
    return active.sort_values(["Employee_Key", "Startdatum", "Employment_Key"]).drop_duplicates(
        subset=["Employee_Key"],
        keep="last"
    )


def _indexed(dataframe, key):
    if dataframe.empty or key not in dataframe.columns:
        return {}
    return dataframe.drop_duplicates(subset=[key], keep="last").set_index(key).to_dict("index")


def _performance_reviews(reviews):
    if reviews.empty:
        return reviews
    result = reviews.copy()
    result["Review_Datum"] = pd.to_datetime(result["Review_Datum"], errors="coerce")
    return result.dropna(subset=["Review_Datum"]).sort_values("Review_Datum")


def _performance_as_of(reviews, employee_key, snapshot_date, fallback):
    fallback = pd.to_numeric(fallback, errors="coerce")
    fallback = float(fallback) if pd.notna(fallback) else 3.4
    if reviews.empty:
        return fallback
    matches = reviews[(reviews["Employee_Key"] == employee_key) & (
        reviews["Review_Datum"] <= snapshot_date
    )]
    return fallback if matches.empty else float(matches.iloc[-1]["Prestatie_Score"])


def _performance_driver_as_of(reviews, employee_key, snapshot_date):
    if reviews.empty or "PerformanceDriver_Key" not in reviews.columns:
        return None
    matches = reviews[(reviews["Employee_Key"] == employee_key) & (
        reviews["Review_Datum"] <= snapshot_date
    )]
    if matches.empty:
        return None
    key = pd.to_numeric(matches.iloc[-1].get("PerformanceDriver_Key"), errors="coerce")
    return int(key) if pd.notna(key) else None


def _benchmark_fields(builder, employment, snapshot_date):
    if not builder.enabled:
        return {}
    return builder.for_employee(
        employment["Employee_Key"],
        employment["Role_Key"],
        employment.get("Salaris"),
        snapshot_date
    )


def _manager_assignments(assignments):
    if assignments.empty:
        return assignments
    result = assignments.copy()
    result["Startdatum"] = pd.to_datetime(result["Startdatum"], errors="coerce")
    result["Einddatum"] = pd.to_datetime(result["Einddatum"], errors="coerce")
    return result.dropna(subset=["Startdatum"])


def _absence_episodes(absence, absence_types):
    if absence.empty:
        return absence
    result = absence.copy()
    result["Startdatum"] = pd.to_datetime(result["Startdatum"], errors="coerce")
    result["Einddatum"] = pd.to_datetime(result["Einddatum"], errors="coerce")
    result = result.dropna(subset=["Employee_Key", "Startdatum", "Einddatum"])
    if absence_types.empty or "Telt_als_verzuim" not in absence_types.columns:
        result["Telt_als_verzuim"] = False
        return result
    flags = absence_types[["AbsenceType_Key", "Telt_als_verzuim"]]
    return result.merge(flags, on="AbsenceType_Key", how="left").assign(
        Telt_als_verzuim=lambda frame: frame["Telt_als_verzuim"].fillna(False)
    )


def _absence_metrics_for_month(absence, snapshot_date):
    if absence.empty:
        return {}
    month_end = pd.Timestamp(snapshot_date).normalize()
    month_start = month_end.to_period("M").to_timestamp()
    relevant = absence[(absence["Startdatum"] <= month_end) & (
        absence["Einddatum"] >= month_start
    )]
    metrics = {}
    for _, episode in relevant.iterrows():
        employee_key = int(episode["Employee_Key"])
        value = metrics.setdefault(employee_key, _empty_absence_metrics())
        overlap_start = max(pd.Timestamp(episode["Startdatum"]), month_start)
        overlap_end = min(pd.Timestamp(episode["Einddatum"]), month_end)
        calendar_days = (overlap_end - overlap_start).days + 1
        workdays = len(pd.bdate_range(overlap_start, overlap_end))
        total_workdays = pd.to_numeric(
            episode.get("Afwezigheid_Werkdagen"),
            errors="coerce"
        )
        total_hours = pd.to_numeric(
            episode.get("Afwezigheid_Uren"),
            errors="coerce"
        )
        hours_per_workday = (
            float(total_hours) / float(total_workdays)
            if pd.notna(total_workdays) and total_workdays > 0
            and pd.notna(total_hours)
            else 8.0
        )
        value["Afwezige_Dagen"] += calendar_days
        value["Afwezigheid_Werkdagen"] += workdays
        value["Afwezigheid_Uren"] += workdays * hours_per_workday
        value["Aantal_Afwezigheid_Episodes"] += 1
        if bool(episode.get("Telt_als_verzuim", False)):
            value["Verzuim_Dagen"] += calendar_days
            value["Verzuim_Werkdagen"] += workdays
            value["Verzuim_Uren"] += workdays * hours_per_workday
            value["Aantal_Verzuimgevallen"] += 1
    return metrics


def _monthly_capacity(employment, snapshot_date, config):
    """Return the scheduled monthly capacity used as a verzuim denominator."""
    month_end = pd.Timestamp(snapshot_date).normalize()
    month_start = month_end.to_period("M").to_timestamp()
    workdays = len(pd.bdate_range(month_start, month_end))
    full_time_hours = getattr(config, "workforce", {}).get(
        "full_time_weekly_hours",
        40
    ) if config else 40
    contract_hours = pd.to_numeric(
        employment.get("Contracturen"),
        errors="coerce"
    )
    if pd.isna(contract_hours):
        contract_hours = full_time_hours
    fte = float(contract_hours) / float(full_time_hours)
    return {
        "Beschikbare_Werkdagen": round(workdays * fte, 2),
        "Beschikbare_Uren": round(workdays * float(contract_hours) / 5, 2),
    }


def _empty_absence_metrics():
    return {
        "Afwezige_Dagen": 0.0,
        "Verzuim_Dagen": 0.0,
        "Afwezigheid_Werkdagen": 0.0,
        "Verzuim_Werkdagen": 0.0,
        "Afwezigheid_Uren": 0.0,
        "Verzuim_Uren": 0.0,
        "Aantal_Afwezigheid_Episodes": 0,
        "Aantal_Verzuimgevallen": 0
    }


def _compa_ratio(salary, benchmark, fallback):
    salary = pd.to_numeric(salary, errors="coerce")
    benchmark = pd.to_numeric(benchmark, errors="coerce")
    if pd.notna(salary) and pd.notna(benchmark) and benchmark > 0:
        return float(salary / benchmark)
    fallback = pd.to_numeric(fallback, errors="coerce")
    return float(fallback) if pd.notna(fallback) else None


def _service_years(service_start, snapshot_date):
    if pd.isna(service_start):
        return None
    return round(max(0, (pd.Timestamp(snapshot_date) - service_start).days) / 365.2425, 2)


def _fte(contract_hours, config):
    hours = pd.to_numeric(contract_hours, errors="coerce")
    workforce = getattr(config, "workforce", {}) if config else {}
    full_time_hours = pd.to_numeric(
        workforce.get("full_time_weekly_hours", 40),
        errors="coerce"
    )
    if pd.isna(hours) or pd.isna(full_time_hours) or full_time_hours <= 0:
        return None
    return round(float(hours) / float(full_time_hours), 2)


def _snapshot_key(snapshot_date, employee_key):
    """Use a stable monthly surrogate so incremental loads can append safely."""
    employee_key = int(employee_key)
    if employee_key >= 10_000:
        raise ValueError("WorkforceSnapshot_Key supports Employee_Key values below 10,000.")
    return int(pd.Timestamp(snapshot_date).strftime("%Y%m")) * 10_000 + employee_key
