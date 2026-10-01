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
            # An open-ended scale (Boven-CAO) has no maximum: keep it None.
            "Schaal_Max_Salaris": (
                None if pd.isna(scale["Maximum_Salaris"])
                else int(round(float(scale["Maximum_Salaris"]) * growth_factor))
            ),
            "Markt_P25": int(round(median * (1 - spread))),
            "Markt_Mediaan": median,
            "Markt_P75": int(round(median * (1 + spread)))
        }

    def initial_salary(self, role, department_name, today, service_start, rng, is_new_hire,
                       gender=None):
        """Draw a realistic pay position and return its matching salary."""
        target_ratio = self.draw_target_ratio(
            department_name,
            rng,
            is_new_hire=is_new_hire,
            gender=gender
        )
        benchmark = self.employee_benchmark(role, today, service_start)
        salary = self.salary_for_ratio(benchmark, target_ratio, today)
        return salary, target_ratio

    def salary_for_ratio(self, benchmark, target_ratio, date):
        """Return the full-time salary for a benchmark and compa-ratio, floored."""
        return self.apply_floor(
            int(round(benchmark["Benchmark_Salaris"] * target_ratio)), date
        )

    def apply_floor(self, salary, date):
        """Lift a full-time (1.0 FTE) salary to the legal minimum wage at `date`.

        `Salaris` is always a full-time amount; the part-time pro rata is applied
        by the consumer. Every path that sets a salary (initial, hire, review,
        promotion/transfer, internal mobility) goes through this helper.
        """
        return max(int(salary), self.legal_minimum(date))

    def legal_minimum(self, date):
        """Full-time legal minimum salary on `date`: a step function.

        Like the Dutch minimum wage it changes only on the configured
        indexation dates (`legal_minimum_salary.indexation_months`, default
        1 January and 1 July; day 1 of each month). On `date` the value of the
        most recent indexation date on or before it applies.

        The value is anchored at 1 January of `reference_year`
        (`annual_full_time_salary` times 1 + the sum of the allowances, rounded
        up) and indexed with the market growth factor at the indexation date,
        rounded up. The growth factor is flat before `base_date`, so every date
        before the burn-in start gets the same value as the first one.
        """
        policy = self.config.get("legal_minimum_salary")
        if not policy:
            return 0
        allowances = sum(float(v) for v in policy.get("allowances", {}).values())
        reference_floor = math.ceil(round(
            float(policy["annual_full_time_salary"]) * (1 + allowances), 6
        ))
        reference_date = pd.Timestamp(int(policy["reference_year"]), 1, 1)
        indexation_date = self._indexation_date(date, policy)
        index = self._growth_factor(indexation_date) / self._growth_factor(reference_date)
        return int(math.ceil(round(reference_floor * index, 6)))

    @staticmethod
    def _indexation_months(policy):
        return sorted({int(month) for month in policy.get("indexation_months", [1, 7])})

    def _indexation_date(self, date, policy):
        """The most recent indexation date on or before `date`."""
        months = self._indexation_months(policy)
        date = pd.Timestamp(date).normalize()
        for year in (date.year, date.year - 1):
            for month in reversed(months):
                candidate = pd.Timestamp(year, month, 1)
                if candidate <= date:
                    return candidate
        return pd.Timestamp(date.year - 1, months[0], 1)

    def indexation_date_in_week(self, today):
        """The indexation date in the 7 days ending on `today` (exclusive start), or None.

        The weekly runner simulates a week on its Monday, so a date that falls
        in (today - 7 days, today] is the one the week just finished with; its
        step value applies from `today` on.
        """
        policy = self.config.get("legal_minimum_salary")
        if not policy:
            return None
        months = set(self._indexation_months(policy))
        today = pd.Timestamp(today).normalize()
        for offset in range(7):
            day = today - pd.Timedelta(days=offset)
            if day.day == 1 and day.month in months:
                return day
        return None

    def draw_target_ratio(self, department_name, rng, is_new_hire=False, gender=None):
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
        ratio += self._gender_offset(gender, "female_starting_offset")
        return self.clamp_ratio(ratio + adjustment)

    def review_salary(self, role, department_name, service_start, today, current_salary,
                      target_ratio, performance, gender=None):
        """Advance salary toward the employee's market-aligned target position."""
        policy = self.config.get("compa_ratio", {})
        midpoint = float(policy.get("performance_midpoint", 3.5))
        movement = float(policy.get("annual_performance_ratio_movement", 0.004))
        adjusted_ratio = self.clamp_ratio(
            float(target_ratio) + (float(performance) - midpoint) * movement
            + self._gender_offset(gender, "female_review_offset")
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

        return self.apply_floor(new_salary, today), adjusted_ratio

    def _gender_offset(self, gender, key):
        """Small, deliberate compa-ratio nudge modeling an unexplained
        (function-corrected) gender pay gap - see maakindustrie.json's
        compa_ratio.gender_pay_gap. Only "F" carries a nonzero offset; every
        other value (including "Anders"/"Onbekend") stays at the baseline.
        """
        if gender != "F":
            return 0.0
        gap = self.config.get("compa_ratio", {}).get("gender_pay_gap", {})
        return float(gap.get(key, 0.0))

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
