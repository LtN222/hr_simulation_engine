"""Build role-level market salary benchmarks and employee comparisons."""

import math

import pandas as pd

from src.infrastructure.record_builder import build_record
from src.infrastructure.salary_policy import SalaryPolicy


class SalaryBenchmarkBuilder:
    """Create deterministic monthly salary benchmarks from sector settings.

    Benchmark values are configured independently from employee salaries. A
    role has a market median in the benchmark base year; that median grows at
    a fixed market rate. Salary steps are based on continuous tenure so an
    employee cannot obtain a more favourable benchmark merely through salary.
    """

    def __init__(self, state, schema, config):
        self.state = state
        self.schema = schema
        self.config = getattr(config, "salary_benchmark", {}) if config else {}
        self.roles = state.get("dim_role", pd.DataFrame())
        self.scales = state.get("dim_salary_scale", pd.DataFrame())
        self.employees = state.get("dim_employee", pd.DataFrame())
        self.policy = (
            SalaryPolicy(config, self.scales)
            if not self.scales.empty else None
        )

    @property
    def enabled(self):
        return (
            bool(self.config)
            and not self.roles.empty
            and not self.scales.empty
        )

    def build_fact(self, snapshot_dates):
        """Return one benchmark row per role, month and salary step."""
        if not self.enabled:
            return pd.DataFrame()

        records = []
        benchmark_key = 1
        for snapshot_date in snapshot_dates:
            for _, role in self.roles.sort_values("Role_Key").iterrows():
                benchmark = self.for_role(role, snapshot_date)
                for step in range(1, benchmark["Aantal_Treden"] + 1):
                    records.append(
                        build_record(
                            self.schema,
                            "fact_salary_benchmark",
                            {
                                "SalaryBenchmark_Key": benchmark_key,
                                "Benchmark_Date": snapshot_date,
                                "Role_Key": int(role["Role_Key"]),
                                "SalaryScale_Key": benchmark["SalaryScale_Key"],
                                "SalaryStep": step,
                                "Scale_Min_Salaris": benchmark[
                                    "Scale_Min_Salaris"
                                ],
                                "Scale_Max_Salaris": benchmark[
                                    "Scale_Max_Salaris"
                                ],
                                "Market_P25": benchmark["Market_P25"],
                                "Market_Median": benchmark["Market_Median"],
                                "Market_P75": benchmark["Market_P75"],
                                "Benchmark_Salaris": self._step_salary(
                                    benchmark,
                                    step
                                )
                            }
                        )
                    )
                    benchmark_key += 1

        return pd.DataFrame(records)

    def for_employee(self, employee_key, role_key, salary, snapshot_date):
        """Return the benchmark fields stored on a salary snapshot."""
        role = self.roles.loc[
            self.roles["Role_Key"] == role_key
        ].iloc[0]
        employee = self.employees.loc[
            self.employees["Employee_Key"] == employee_key
        ]
        service_start = (
            employee.iloc[0].get("Aaneengesloten_Indienst_Datum")
            if not employee.empty else None
        )
        benchmark = self.policy.employee_benchmark(
            role,
            snapshot_date,
            service_start
        )
        step = benchmark["SalaryStep"]
        benchmark_salary = benchmark["Benchmark_Salaris"]
        difference = int(round(int(salary) - benchmark_salary))
        status = self._benchmark_status(salary, benchmark_salary)

        return {
            "SalaryScale_Key": benchmark["SalaryScale_Key"],
            "SalaryStep": step,
            "Benchmark_Salaris": benchmark_salary,
            "Benchmark_Verschil": difference,
            "Benchmark_Status": status
        }

    def for_role(self, role, snapshot_date):
        """Return market values and scale assignment for one role and month."""
        return self.policy.role_benchmark(role, snapshot_date)

    def _growth_factor(self, snapshot_date):
        base_date = pd.Timestamp(
            self.config.get("base_date", "2020-01-01")
        )
        elapsed_years = max(
            0.0,
            (pd.Timestamp(snapshot_date) - base_date).days / 365.2425
        )
        annual_rate = float(
            self.config.get("annual_market_growth_rate", 0.025)
        )
        return (1 + annual_rate) ** elapsed_years

    def _scale_for_median(self, median):
        scales = self.scales.copy()
        inside = scales[
            (scales["Minimum_Salaris"] <= median)
            & (scales["Maximum_Salaris"] >= median)
        ]
        if not inside.empty:
            return inside.sort_values("SalaryScale_Key").iloc[0]

        midpoints = (
            scales["Minimum_Salaris"] + scales["Maximum_Salaris"]
        ) / 2
        return scales.loc[(midpoints - median).abs().idxmin()]

    def _employee_step(self, employee_key, snapshot_date, benchmark):
        employee = self.employees.loc[
            self.employees["Employee_Key"] == employee_key
        ]
        if employee.empty:
            return 1

        service_start = pd.to_datetime(
            employee.iloc[0].get("Aaneengesloten_Indienst_Datum"),
            errors="coerce"
        )
        if pd.isna(service_start):
            return 1

        tenure_years = max(
            0.0,
            (pd.Timestamp(snapshot_date) - service_start).days / 365.2425
        )
        years_per_step = max(
            1,
            int(self.config.get("years_per_step", 3))
        )
        step = 1 + math.floor(tenure_years / years_per_step)
        return min(int(benchmark["Aantal_Treden"]), step)

    @staticmethod
    def _step_salary(benchmark, step):
        step_count = int(benchmark["Aantal_Treden"])
        if step_count <= 1:
            return int(benchmark["Market_Median"])

        progress = (step - 1) / (step_count - 1)
        return int(round(
            benchmark["Market_P25"]
            + (benchmark["Market_P75"] - benchmark["Market_P25"]) * progress
        ))

    def _benchmark_status(self, salary, benchmark_salary):
        """Classify salary against its benchmark using configurable bands.

        The boundaries intentionally form contiguous intervals: 90% and 110%
        are classified as ``Rond benchmark``. This makes the category useful
        as the expected pay range instead of a very narrow rounding tolerance.
        """
        thresholds = self.config.get("benchmark_status_thresholds", {})
        very_low = float(thresholds.get("ver_onder", 0.80))
        low = float(thresholds.get("onder", 0.90))
        high = float(thresholds.get("boven", 1.10))
        very_high = float(thresholds.get("ver_boven", 1.20))
        ratio = float(salary) / float(benchmark_salary)

        if ratio < very_low:
            return "Ver onder benchmark"
        if ratio < low:
            return "Onder benchmark"
        if ratio <= high:
            return "Rond benchmark"
        if ratio <= very_high:
            return "Boven benchmark"
        return "Ver boven benchmark"
