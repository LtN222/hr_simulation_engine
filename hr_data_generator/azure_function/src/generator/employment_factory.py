import pandas as pd

from src.domain.job import Job
from src.domain.contract import Contract


class EmploymentFactory:

    def __init__(self, config, rng):
        self.config = config
        self.rng = rng

    def create(
        self,
        role_row,
        role_name,
        department_name,
        today
    ):
        # =====================================================
        # 1️⃣ Job
        # =====================================================

        salary = self._choose_salary(role_row)
        performance = self._choose_performance()

        job = Job(
            role_key=role_row["Role_Key"],
            role_name=role_name,
            department_name=department_name,
            salary=salary
        )

        # =====================================================
        # 2️⃣ Contract
        # =====================================================

        start_date = today - pd.DateOffset(
            days=self.rng.randint(0, 5 * 365)
        )

        contract_rules = self.config.contract_rules

        afdeling_rules = contract_rules.get(
            department_name,
            contract_rules.get("default")
        )

        contract_type, end_date, contract_round = (
            self._choose_contract(
                start_date,
                today,
                afdeling_rules
            )
        )

        hours = self._choose_contract_hours(role_name)

        contract = Contract(
            contract_type=contract_type,
            start_date=start_date,
            end_date=end_date,
            hours=hours,
            contract_round=contract_round
        )

        return job, contract, performance

    # =====================================================
    # 🔹 intern
    # =====================================================

    def _choose_salary(self, role_row):

        return self.rng.randint(
            role_row["Salaris_min"],
            role_row["Salaris_max"]
        )

    def _choose_performance(self):

        score = round(self.rng.normalvariate(3.5, 0.5), 2)
        return max(1, min(5, score))

    def _choose_contract(
        self,
        start_date,
        today,
        contract_rules
    ):

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

            end_date = start_date + pd.DateOffset(
                years=contract_round
            )

        else:
            end_date = None
            contract_round = None

        return contract_type, end_date, contract_round

    def _choose_contract_hours(self, role_name):

        hours_cfg = self.config.contract_hours_distribution

        role_dist = hours_cfg.get(
            role_name,
            hours_cfg.get("default")
        )

        if not role_dist:
            raise ValueError(
                f"No contract hours config for role: {role_name}"
            )

        hours = self.rng.choices(
            list(role_dist.keys()),
            weights=list(role_dist.values())
        )[0]

        return int(hours)