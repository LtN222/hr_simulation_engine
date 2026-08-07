import pandas as pd

from src.domain.contract import Contract
from src.domain.job import Job


class EmploymentFactory:
    def __init__(self, config, rng):
        self.config = config
        self.rng = rng

    def create(
        self,
        role_row,
        role_name,
        department_name,
        today,
        employment_start_date=None
    ):
        """Create employment data for an initial employee or a new hire.

        Initial population members receive a historical start date sampled
        from the configured tenure distribution. A new hire passes an explicit
        start date, which prevents a fictional tenure from affecting salary.
        """
        is_new_hire = employment_start_date is not None
        start_date = (
            pd.Timestamp(employment_start_date)
            if is_new_hire
            else self._choose_initial_start_date(today)
        )
        salary = self._choose_salary(
            role_row,
            start_date=start_date,
            today=today,
            is_new_hire=is_new_hire
        )
        performance = self._choose_performance()

        job = Job(
            role_key=role_row["Role_Key"],
            role_name=role_name,
            department_name=department_name,
            salary=salary
        )

        contract_rules = self.config.contract_rules
        afdeling_rules = contract_rules.get(
            department_name,
            contract_rules.get("default")
        )

        contract_type, end_date, contract_round = self._choose_contract(
            start_date,
            today,
            afdeling_rules
        )

        contract = Contract(
            contract_type=contract_type,
            start_date=start_date,
            end_date=end_date,
            hours=self._choose_contract_hours(role_name),
            contract_round=contract_round
        )

        return job, contract, performance

    def _choose_salary(
        self,
        role_row,
        start_date=None,
        today=None,
        is_new_hire=False
    ):
        salary_min = int(role_row["Salaris_min"])
        salary_max = int(role_row["Salaris_max"])
        if today is None:
            today = pd.Timestamp.today()

        if start_date is None:
            tenure_years = 0
        else:
            tenure_years = max(
                0,
                (pd.Timestamp(today) - pd.Timestamp(start_date)).days / 365.0
            )

        salary_cfg = self._salary_growth_config()
        band_width = salary_max - salary_min

        if is_new_hire:
            position_cfg = salary_cfg.get("new_hire_band_position", {})
            band_position = self.rng.uniform(
                position_cfg.get("min", 0.32),
                position_cfg.get("max", 0.42)
            )
        else:
            position_cfg = salary_cfg.get(
                "initial_population_band_position",
                {}
            )
            base_position = self.rng.uniform(
                position_cfg.get("min", 0.28),
                position_cfg.get("max", 0.40)
            )
            tenure_increment = position_cfg.get(
                "tenure_increment_per_year",
                0.035
            )
            band_position = min(
                position_cfg.get("max_position", 0.75),
                base_position + tenure_years * tenure_increment
            )

        band_position = max(0.05, min(0.95, band_position))

        return int(round(salary_min + band_width * band_position))

    def _choose_initial_start_date(self, today):
        initial_population = getattr(self.config, "initial_population", {})
        distribution = initial_population.get("tenure_years_distribution", {})

        if not distribution:
            return pd.Timestamp(today) - pd.DateOffset(
                days=self.rng.randint(0, 5 * 365)
            )

        tenure_range = self.rng.choices(
            list(distribution.keys()),
            weights=list(distribution.values()),
            k=1
        )[0]
        lower, upper = (float(value) for value in tenure_range.split("-", 1))
        tenure_years = self.rng.uniform(lower, upper)
        return pd.Timestamp(today) - pd.Timedelta(days=round(tenure_years * 365.2425))

    def _salary_growth_config(self):
        if self.config is None:
            return {}
        return self.config.career_events.get("salary_growth", {})

    def _choose_performance(self):
        score = round(self.rng.normalvariate(3.5, 0.5), 2)
        return max(1, min(5, score))

    def _choose_contract(self, start_date, today, contract_rules):
        contract_type = self.rng.choices(
            ["Vast", "Tijdelijk"],
            weights=[
                contract_rules["vast_kans"],
                contract_rules["tijdelijk_kans"]
            ]
        )[0]

        if contract_type == "Tijdelijk":
            tenure_years = (today - start_date).days // 365
            contract_round = tenure_years + 1
            end_date = start_date + pd.DateOffset(years=contract_round)
        else:
            end_date = None
            contract_round = None

        return contract_type, end_date, contract_round

    def _choose_contract_hours(self, role_name):
        hours_cfg = self.config.contract_hours_distribution
        role_dist = hours_cfg.get(role_name, hours_cfg.get("default"))

        if not role_dist:
            raise ValueError(f"No contract hours config for role: {role_name}")

        hours = self.rng.choices(
            list(role_dist.keys()),
            weights=list(role_dist.values())
        )[0]

        return int(hours)
