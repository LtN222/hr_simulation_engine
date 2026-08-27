"""Shared salary policy for employment generation and benchmark reporting."""

import math

import pandas as pd


class SalaryPolicy:
    """Calculate market benchmarks and stable employee pay positions.

    The same benchmark formula is deliberately used when an employment starts,
    during salary reviews and in reporting. This prevents internal salaries and
    the displayed benchmark from gradually becoming two unrelated models.
    """

    def __init__(self, config, scales=None):
        self.config = getattr(config, "salary_benchmark", {}) if config else {}
        configured_scales = getattr(config, "dim_salary_scale", []) if config else []
        self.scales = self._normalise_scales(
            scales if scales is not None and not scales.empty else configured_scales
        )

    def employee_benchmark(self, role, snapshot_date, service_start):
        """Return the market benchmark for one role and employee tenure."""
        benchmark = self.role_benchmark(role, snapshot_date)
        step = self._step_for_service(service_start, snapshot_date, benchmark)
        benchmark["Salaris_Trede"] = step
        benchmark["Benchmark_Salaris"] = self.step_salary(benchmark, step)
        return benchmark

    def role_benchmark(self, role, snapshot_date):
        """Return the role-level market range before assigning a salary step."""
        role_name = role.get("Functie_Naam", "")
        medians = self.config.get("market_median_by_role", {})
        base_median = float(medians.get(
            role_name,
            (float(role["Salaris_min"]) + float(role["Salaris_max"])) / 2
        ))
        scale = self._scale_for_role(role, base_median)
        growth_factor = self._growth_factor(snapshot_date)
        spread = float(self.config.get("market_percentile_spread", 0.10))
        median = int(round(base_median * growth_factor))

        return {
            "SalaryScale_Key": int(scale["SalaryScale_Key"]),
            "Aantal_Treden": int(scale["Aantal_Treden"]),
            "Schaal_Min_Salaris": int(round(
                float(scale["Minimum_Salaris"]) * growth_factor
            )),
            "Schaal_Max_Salaris": int(round(
                float(scale["Maximum_Salaris"]) * growth_factor
            )),
            "Markt_P25": int(round(median * (1 - spread))),
            "Markt_Mediaan": median,
            "Markt_P75": int(round(median * (1 + spread)))
        }

    def initial_salary(self, role, department_name, today, service_start, rng, is_new_hire):
        """Draw a realistic pay position and return its matching salary."""
        target_ratio = self.draw_target_ratio(
            department_name,
            rng,
            is_new_hire=is_new_hire
        )
        benchmark = self.employee_benchmark(role, today, service_start)
        salary = int(round(benchmark["Benchmark_Salaris"] * target_ratio))
        return salary, target_ratio

    def draw_target_ratio(self, department_name, rng, is_new_hire=False):
        """Draw from configured benchmark-status bands instead of a narrow mean."""
        policy = self.config.get("compa_ratio", {})
        distribution_key = (
            "new_hire_distribution"
            if is_new_hire else "initial_population_distribution"
        )
        distribution = policy.get(distribution_key, [])
        if not distribution:
            distribution = [{"minimum": 0.90, "maximum": 1.10, "weight": 1.0}]

        weights = [float(item.get("weight", 1.0)) for item in distribution]
        selected = rng.choices(distribution, weights=weights, k=1)[0]
        ratio = rng.uniform(
            float(selected["minimum"]),
            float(selected["maximum"])
        )
        adjustment = float(
            policy.get("department_adjustments", {}).get(department_name, 0.0)
        )
        return self.clamp_ratio(ratio + adjustment)

    def review_salary(self, role, department_name, service_start, today, current_salary,
                      target_ratio, performance):
        """Advance salary toward the employee's market-aligned target position."""
        policy = self.config.get("compa_ratio", {})
        midpoint = float(policy.get("performance_midpoint", 3.5))
        movement = float(policy.get("annual_performance_ratio_movement", 0.004))
        adjusted_ratio = self.clamp_ratio(
            float(target_ratio) + (float(performance) - midpoint) * movement
        )
        benchmark = self.employee_benchmark(role, today, service_start)
        target_salary = int(round(benchmark["Benchmark_Salaris"] * adjusted_ratio))
        minimum_raise = float(policy.get("minimum_annual_raise", 0.005))

        if current_salary < target_salary:
            # Existing pay tracks its market target. A small floor prevents an
            # unreasonably flat salary when a rounded benchmark barely moves.
            new_salary = max(
                int(round(float(current_salary) * (1 + minimum_raise))),
                target_salary
            )
        else:
            # Salaries never decrease; an above-target employee receives a
            # restrained increase until market growth catches up.
            new_salary = int(round(float(current_salary) * (1 + minimum_raise)))

        return new_salary, adjusted_ratio

    def clamp_ratio(self, ratio):
        policy = self.config.get("compa_ratio", {})
        minimum = float(policy.get("minimum_ratio", 0.75))
        maximum = float(policy.get("maximum_ratio", 1.30))
        return max(minimum, min(maximum, float(ratio)))

    def _scale_for_role(self, role, median):
        if "SalaryScale_Key" in role and pd.notna(role["SalaryScale_Key"]):
            matching = self.scales[
                self.scales["SalaryScale_Key"] == int(role["SalaryScale_Key"])
            ]
            if not matching.empty:
                return matching.iloc[0]

        inside = self.scales[
            (self.scales["Minimum_Salaris"] <= median)
            & (self.scales["Maximum_Salaris"].isna()
               | (self.scales["Maximum_Salaris"] >= median))
        ]
        if not inside.empty:
            return inside.sort_values("SalaryScale_Key").iloc[0]

        midpoints = (
            self.scales["Minimum_Salaris"]
            + self.scales["Maximum_Salaris"].fillna(median)
        ) / 2
        return self.scales.loc[(midpoints - median).abs().idxmin()]

    def _growth_factor(self, snapshot_date):
        base_date = pd.Timestamp(self.config.get("base_date", "2020-01-01"))
        years = max(0.0, (pd.Timestamp(snapshot_date) - base_date).days / 365.2425)
        rate = float(self.config.get("annual_market_growth_rate", 0.025))
        return (1 + rate) ** years

    def _step_for_service(self, service_start, snapshot_date, benchmark):
        service_start = pd.to_datetime(service_start, errors="coerce")
        if pd.isna(service_start):
            return 1
        tenure_years = max(
            0.0,
            (pd.Timestamp(snapshot_date) - service_start).days / 365.2425
        )
        years_per_step = max(1, int(self.config.get("years_per_step", 3)))
        return min(
            int(benchmark["Aantal_Treden"]),
            1 + math.floor(tenure_years / years_per_step)
        )

    @staticmethod
    def step_salary(benchmark, step):
        step_count = int(benchmark["Aantal_Treden"])
        if step_count <= 1:
            return int(benchmark["Markt_Mediaan"])
        progress = (int(step) - 1) / (step_count - 1)
        return int(round(
            benchmark["Markt_P25"]
            + (benchmark["Markt_P75"] - benchmark["Markt_P25"]) * progress
        ))

    @staticmethod
    def _normalise_scales(scales):
        dataframe = pd.DataFrame(scales).copy()
        if dataframe.empty:
            dataframe = pd.DataFrame([{
                "SalaryScale_Key": 1,
                "Minimum_Salaris": 0,
                "Maximum_Salaris": None,
                "Aantal_Treden": 1
            }])
        if "SalaryScale_Key" not in dataframe.columns:
            dataframe.insert(0, "SalaryScale_Key", range(1, len(dataframe) + 1))
        for column in ("Minimum_Salaris", "Maximum_Salaris", "Aantal_Treden"):
            dataframe[column] = pd.to_numeric(dataframe[column], errors="coerce")
        return dataframe
