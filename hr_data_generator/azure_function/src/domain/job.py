class Job:
    def __init__(
        self,
        role_key,
        role_name,
        department_name,
        salary,
        target_compa_ratio=None,
        ploegendienst_key=None
    ):
        self.role_key = role_key
        self.role_name = role_name
        self.department_name = department_name
        self.salary = salary
        self.target_compa_ratio = target_compa_ratio
        self.ploegendienst_key = ploegendienst_key
