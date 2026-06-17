from datetime import datetime

from src.simulation.simulation_absence import AbsenceSimulator
from src.simulation.simulation_attrition import AttritionSimulator
from src.simulation.simulation_career_events import simulate_career_events
from src.simulation.simulation_growth import calculate_growth_target
from src.simulation.simulation_hiring import HiringSimulator
from src.simulation.simulation_recruitment import RecruitmentSimulator


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
        transfer_rate
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

    def run_week(self, state, year, week):
        today = datetime.fromisocalendar(year, week, 1)
        event_type_map = self._map_dimension(
            state["dim_event_type"],
            "EventType",
            "EventType_Key"
        )
        reden_vertrek_map = self._map_dimension(
            state["dim_reden_vertrek"],
            "RedenVertrek",
            "RedenVertrek_Key"
        )

        before_attrition_vacancies = int(state.get("vacancies", 0))
        state = AttritionSimulator(
            self.config,
            self.rng,
            event_type_map,
            reden_vertrek_map
        ).run(state, today)
        state["_attrition_vacancies"] = max(
            0,
            int(state.get("vacancies", 0)) - before_attrition_vacancies
        )

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
        state["vacancies"] = int(state.get("vacancies", 0)) + hires_needed

        state = HiringSimulator(
            self.config,
            self.schema,
            self.rng,
            event_type_map
        ).run(state, today)

        state = RecruitmentSimulator(
            self.config,
            self.schema,
            self.rng
        ).run(state, today)

        state = AbsenceSimulator(
            self.config,
            self.schema,
            self.rng
        ).run(state, today)

        state.pop("_attrition_vacancies", None)
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
    transfer_rate
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
        transfer_rate
    ).run_week(state, year, week)
