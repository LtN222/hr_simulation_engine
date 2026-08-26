from src.generator.employee_helpers import (
    choose_hire_source,
    choose_education
)
from src.infrastructure.location_assignment import resolve_location

from src.domain.employee import Employee
from src.domain.person import Person
from src.generator.person_factory import PersonFactory
from src.generator.employment_factory import EmploymentFactory  # straks
from src.infrastructure.shift_assignment import assign_ploegendienst_key

class EmployeeFactory:

    def __init__(
            self, 
            config, 
            rng,
            person_factory=None,
            employment_factory=None
            ):
        self.config = config
        self.rng = rng
        self.person_factory = person_factory or PersonFactory(config, rng)
        self.employment_factory = employment_factory or EmploymentFactory(config, rng)

    def create(
        self,
        emp_key,
        role_row,
        role_name,
        department_name,
        today,
        state,
        employment_start_date=None
    ):
        # =====================================================
        # 1️⃣ Job + contract
        # =====================================================

        # =====================================================
        # 2️⃣ Person
        # =====================================================


        job, contract, performance = self.employment_factory.create(
            role_row=role_row,
            role_name=role_name,
            department_name=department_name,
            today=today,
            employment_start_date=employment_start_date
        )
        job.ploegendienst_key = assign_ploegendienst_key(
            role_row,
            state,
            self.config,
            self.rng
        )

        # Contract start is needed to keep the person legally employable on
        # their first day, including the historical initial population.
        person_data = self.person_factory.create(
            role_name,
            today,
            employment_start_date=contract.start_date
        )

        person = Person(
            gender=person_data["gender"],
            first_name=person_data["first_name"],
            last_name=person_data["last_name"],
            birth_date=person_data["birth_date"],
            country=person_data["country"]
        )

        bijzondere_aanstelling = person_data["bijzondere_aanstelling"]

        # =====================================================
        # 3️⃣ Keys / dimensions
        # =====================================================

        hire_source_key = choose_hire_source(
            self.config,                 # 🔥 aangepast!
            state["dim_hire_source"],
            self.rng
        )

        education_key = choose_education(
            role_name,
            self.config,
            state["dim_education"],
            self.rng
        )

        location_key = resolve_location(
            state,
            self.config,
            self.rng,
            department_name,
            role_name
        )

        # =====================================================
        # 4️⃣ Employee object
        # =====================================================

        employee = Employee(
            employee_key=emp_key,
            person=person,
            job=job,
            contract=contract,
            hire_source_key=hire_source_key,
            education_key=education_key,
            location_key=location_key,
            performance=performance,
            bijzondere_aanstelling=bijzondere_aanstelling,
            manager_key=None
        )

        return employee
