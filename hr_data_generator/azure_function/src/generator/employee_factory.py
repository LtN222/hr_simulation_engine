from src.generator.employee_helpers import (
    choose_hire_source,
    choose_education,
    choose_location
)

from src.domain.employee import Employee
from src.domain.person import Person
from src.generator.person_factory import PersonFactory
from src.generator.employment_factory import EmploymentFactory  # straks

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
        state
    ):
        # =====================================================
        # 1️⃣ Person
        # =====================================================

        person_data = self.person_factory.create(role_name, today)

        person = Person(
            gender=person_data["gender"],
            first_name=person_data["first_name"],
            last_name=person_data["last_name"],
            birth_date=person_data["birth_date"],
            country=person_data["country"]
        )

        bijzondere_aanstelling = person_data["bijzondere_aanstelling"]

        # =====================================================
        # 2️⃣ Job + contract
        # =====================================================


        job, contract, performance = self.employment_factory.create(
            role_row=role_row,
            role_name=role_name,
            department_name=department_name,
            today=today
        )

        # =====================================================
        # 4️⃣ Keys / dimensions
        # =====================================================

        hire_source_key = choose_hire_source(
            self.config,                 # 🔥 aangepast!
            state["dim_hire_source"],
            self.rng
        )

        education_key = choose_education(
            role_name,
            self.config,
            state["dim_education_level"],
            self.rng
        )

        location_key = choose_location(
            state["dim_location"],
            self.config,
            self.rng
        )

        # =====================================================
        # 5️⃣ Employee object
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