import random
from datetime import datetime

from src.core.config_loader import ConfigLoader
from src.infrastructure.database.schema_loader import load_schema

from src.infrastructure.dimension_factory import generate_dimensions
from src.infrastructure.dimensions import (
    build_dim_department,
    build_dim_role,
    build_dim_reden_vertrek
)

from src.application.allocation import allocate_headcount
from src.application.employee_generation import generate_employees

from src.simulation.simulation_absence import AbsenceSimulator
from src.simulation.simulation_performance import PerformanceSimulator


class WorkforceGenerator:

    def __init__(self, sector="maakindustrie", seed=42):

        self.config = ConfigLoader().load()
        self.schema = load_schema(self.config.get("schema"))

        self.rng = random.Random(seed)

        self.today = datetime(
            self.config.start_year_simulation,
            1,
            1
        )
        self.absence_simulator = AbsenceSimulator(
            self.config,
            self.schema,
            self.rng
        )
        self.performance_simulator = PerformanceSimulator(
            self.config,
            self.schema,
            self.rng
        )
        

    # =====================================================
    # 🔹 Public API
    # =====================================================

    def run(self, include_history=True):

        state = {}

        self._generate_dimensions(state)
        self._allocate_headcount(state)
        self._generate_employees(state)
        self._generate_history(state)

        return state

    # =====================================================
    # 🔹 Steps
    # =====================================================

    def _generate_dimensions(self, state):

        auto_dims = generate_dimensions(self.config, self.schema)
        state.update(auto_dims)

        structure = self.config.structure

        state["dim_department"] = build_dim_department(structure)

        state["dim_role"] = build_dim_role(
            structure,
            state["dim_department"]
        )

        state["dim_reden_vertrek"] = build_dim_reden_vertrek(
            self.config.dim_reden_vertrek
        )

    def _allocate_headcount(self, state):

        role_allocations = allocate_headcount(
            self.config.structure,
            self.config.baseline_headcount
        )

        state["role_allocations"] = role_allocations

    def _generate_employees(self, state):

        state.update(generate_employees(
            state,
            self.config,
            self.schema,
            self.rng,
            self.today
        ))

        state.pop("role_allocations", None)

    def _generate_history(self, state):

        state = self.absence_simulator.run(state, self.today)
        state = self.performance_simulator.run(state, self.today)

        return state