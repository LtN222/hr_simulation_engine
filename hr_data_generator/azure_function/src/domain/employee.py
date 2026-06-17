class Employee:
    def __init__(
        self,
        employee_key,
        person,
        job,
        contract,
        hire_source_key,
        education_key,
        location_key,
        performance,
        bijzondere_aanstelling=None,
        manager_key=None
    ):
        self.employee_key = employee_key
        self.person = person
        self.job = job
        self.contract = contract
        self.hire_source_key = hire_source_key
        self.education_key = education_key
        self.location_key = location_key
        self.performance = performance
        self.bijzondere_aanstelling = bijzondere_aanstelling
        self.manager_key = manager_key