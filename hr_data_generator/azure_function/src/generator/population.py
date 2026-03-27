import random
from datetime import datetime

from src.generator.config_loader import load_config
from src.database.schema_loader import load_schema

from src.generator.dimension_factory import generate_dimensions

from src.generator.dimensions import (
    build_dim_department,
    build_dim_role,
    build_dim_reden_vertrek
)

from src.generator.allocation import allocate_headcount
from src.generator.employees import generate_employees

from src.generator.absence_simulation import generate_absence_history
from src.generator.performance_simulation import generate_performance_reviews


# =====================================================
# INITIAL WORKFORCE GENERATOR (t = 0)
# =====================================================
# Bouwt een volledige initiële HR dataset:
#
# 1️⃣ Structure dimensions
# 2️⃣ Headcount allocatie
# 3️⃣ Structure facts (employees + employment)
# 4️⃣ Historical facts (absence + performance)
# =====================================================

def generate_initial_workforce(
    sector: str = "maakindustrie",
    seed: int = 42
):

    rng = random.Random(seed)

    # -------------------------------------------------
    # Config + schema laden
    # -------------------------------------------------

    config = load_config(sector)
    schema = load_schema(config["schema"])

    total_employees = config["baseline_headcount"]
    year = config["start_year_simulation"]

    structure = config["structure"]

    today = datetime(year, 1, 1)

    # -------------------------------------------------
    # Centrale container voor alle dataframes
    # -------------------------------------------------

    state = {}

    # =====================================================
    # 1️⃣ Dimensions genereren
    # =====================================================

    # automatisch gegenereerde dims (config based)
    auto_dims = generate_dimensions(config, schema)

    state.update(auto_dims)

    # structure dims (organisatie)
    state["dim_department"] = build_dim_department(structure)

    state["dim_role"] = build_dim_role(
        structure,
        state["dim_department"]
    )

    # vertrekredenen
    state["dim_reden_vertrek"] = build_dim_reden_vertrek(
        config["dim_reden_vertrek"]
    )

    # =====================================================
    # 2️⃣ Headcount allocatie
    # =====================================================

    role_allocations = allocate_headcount(
        structure,
        total_employees
    )

    state["role_allocations"] = role_allocations

    # =====================================================
    # 3️⃣ Employees + employment genereren
    # =====================================================

    state = generate_employees(
        state,
        config,
        schema,
        rng,
        today
    )

    # role_allocations is helper → verwijderen
    state.pop("role_allocations", None)

    # =====================================================
    # 4️⃣ Historical facts
    # =====================================================

    state = generate_absence_history(
        state,
        config,
        schema,
        rng,
        today
    )

    state = generate_performance_reviews(
        state,
        config,
        schema,
        rng,
        today
    )

    # =====================================================
    # 5️⃣ Resultaat
    # =====================================================

    return state