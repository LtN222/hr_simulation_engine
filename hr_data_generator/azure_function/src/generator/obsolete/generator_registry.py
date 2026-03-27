from src.generator.employees import generate_employees
from src.generator.absence_simulation import generate_absence_history
from src.generator.performance_simulation import generate_performance_reviews


FACT_GENERATORS = {

    "fact_employment": generate_employees,
    "fact_employment_attribute": generate_employees,

    "fact_absence": generate_absence_history,
    "fact_performance_review": generate_performance_reviews

}