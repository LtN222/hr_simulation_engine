from datetime import datetime

from src.simulation.simulation_absence import AbsenceSimulator
from src.simulation.simulation_attrition import AttritionSimulator
from src.simulation.simulation_career_events import simulate_career_events
from src.simulation.simulation_growth import calculate_growth_target
from src.simulation.simulation_hiring import HiringSimulator
from src.simulation.simulation_location_transfer import simulate_location_transfers
from src.simulation.simulation_performance import PerformanceSimulator
from src.simulation.simulation_recruitment import RecruitmentSimulator
from src.simulation.simulation_safety import SafetyIncidentSimulator
from src.simulation.simulation_vacancy import VacancySimulator
from src.infrastructure.location_assignment import open_locations
from src.infrastructure.manager_builder import assign_managers
from src.infrastructure.manager_assignment import sync_manager_assignments


class WeeklySimulationRunner:
    """Coordinates all HR simulation events for a single ISO week."""

    def __init__(
        self,
        config,
        schema,
        rng,
        baseline_headcount,
        max_capacity,
        annual_growth_rate,
        weeks_before_peak_growth,
        promotion_rate,
        transfer_rate,
        simulation_start_date=None
    ):
        self.config = config
        self.schema = schema
        self.rng = rng
        self.baseline_headcount = baseline_headcount
        self.max_capacity = max_capacity
        self.annual_growth_rate = annual_growth_rate
        self.weeks_before_peak_growth = weeks_before_peak_growth
        self.promotion_rate = promotion_rate
        self.transfer_rate = transfer_rate
        self.simulation_start_date = simulation_start_date

    def run_week(self, state, year, week):
        today = datetime.fromisocalendar(year, week, 1)
        simulation_start = self.simulation_start_date or datetime(
            self.config.start_year_simulation,
            1,
            1
        )

        if today < simulation_start:
            today = simulation_start

        # Satisfaction/engagement are cached per resolved-input tuple within
        # a week (see satisfaction.py/engagement.py) since several
        # simulators ask for the same employee's score on the same date.
        # Clearing per week keeps the cache from growing for the entire run.
        for cache_key in (
            "_satisfaction_cache",
            "_satisfaction_momentum_cache",
            "_engagement_cache",
            "_engagement_momentum_cache",
            "_constructive_contributions_cache",
        ):
            state[cache_key] = {}

        event_type_map = self._map_dimension(
            state["dim_event_type"],
            "Gebeurtenis",
            "EventType_Key"
        )
        departure_reason_map = self._map_dimension(
            state["dim_departure_reason"],
            "Vertrekreden",
            "DepartureReason_Key"
        )

        state = open_locations(state, self.config, self.schema, today, event_type_map)

        state = AttritionSimulator(
            self.config,
            self.rng,
            event_type_map,
            departure_reason_map
        ).run(state, today)

        state = PerformanceSimulator(
            self.config,
            self.schema,
            self.rng
        ).run_weekly(state, today)

        state = simulate_career_events(
            state,
            self.config,
            self.schema,
            today,
            self.rng,
            event_type_map,
            self.promotion_rate,
            self.transfer_rate
        )

        state = simulate_location_transfers(
            state,
            self.config,
            self.schema,
            today,
            self.rng,
            event_type_map
        )

        hires_needed = calculate_growth_target(
            state["fact_employment"],
            self.config,
            self.baseline_headcount,
            self.max_capacity,
            year,
            week,
            self.annual_growth_rate,
            self.weeks_before_peak_growth,
            self.rng
        )

        state = VacancySimulator(
            self.config,
            self.schema,
            self.rng
        ).run(state, today, hires_needed)

        state = RecruitmentSimulator(
            self.config,
            self.schema,
            self.rng
        ).run(state, today)

        state = HiringSimulator(
            self.config,
            self.schema,
            self.rng,
            event_type_map
        ).run(state, today)

        # Attrition can make a previous manager unavailable in a week where
        # no replacement has been hired yet. Rebuild the acyclic assignments
        # every week so active employees never retain stale manager links.
        state["dim_employee"] = assign_managers(
            state["dim_employee"],
            state["fact_employment"],
            state["dim_role"],
            self.rng,
            today=today,
            staffing_rules=self.config.staffing
        )
        state = sync_manager_assignments(state, self.schema, today)

        state = AbsenceSimulator(
            self.config,
            self.schema,
            self.rng
        ).run(state, today)

        # Runs after AbsenceSimulator so a lost-time incident never doubles
        # someone up with an overlapping sickness episode from this same week.
        state = SafetyIncidentSimulator(
            self.config,
            self.schema,
            self.rng
        ).run(state, today)

        return state

    def _map_dimension(self, dataframe, label_col, key_col):
        return dict(zip(dataframe[label_col], dataframe[key_col]))


def simulate_week(
    state,
    config,
    schema,
    year,
    week,
    baseline_headcount,
    max_capacity,
    annual_growth_rate,
    weeks_before_peak_growth,
    rng,
    promotion_rate,
    transfer_rate,
    simulation_start_date=None
):
    return WeeklySimulationRunner(
        config,
        schema,
        rng,
        baseline_headcount,
        max_capacity,
        annual_growth_rate,
        weeks_before_peak_growth,
        promotion_rate,
        transfer_rate,
        simulation_start_date
    ).run_week(state, year, week)
