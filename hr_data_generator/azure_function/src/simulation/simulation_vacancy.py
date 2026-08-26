import pandas as pd

from src.application.allocation import (
    minimum_count_for_role,
    role_is_active,
    role_target_ratio,
    scope_headcount,
    team_lead_requirement,
    team_lead_role_name,
)
from src.infrastructure.location_assignment import effective_role_capacity
from src.infrastructure.record_builder import build_record
from src.simulation.simulation_growth import economic_event_for_date


class VacancySimulator:
    """Maintain an explicit vacancy backlog.

    Vacancy demand comes from two sources:
    - replacement requests raised by attrition, with the leaver's role;
    - growth demand from the headcount target curve, assigned to roles that are
      below their configured workforce mix.
    """

    def __init__(self, config, schema, rng):
        self.config = config
        self.schema = schema
        self.rng = rng

    def run(self, state, today, growth_vacancies):
        existing = state.get("fact_vacancy", pd.DataFrame())
        records = []
        vacancy_key = (
            int(existing["Vacancy_Key"].max()) + 1
            if not existing.empty and "Vacancy_Key" in existing.columns
            else 1
        )

        economic_event = economic_event_for_date(self.config.growth, today)
        replacement_hiring_rate = float(
            economic_event.get("replacement_hiring_rate", 1.0)
            if economic_event
            else 1.0
        )

        role_counts = self._active_role_counts(state)
        # Open vacancies already in flight from earlier weeks - a role's
        # active headcount alone understates real demand for it while one of
        # its seats is still being recruited. Without this, a slow-to-fill
        # capped role (e.g. a single-seat CFO) gets re-flagged as understaffed
        # every week its one pending vacancy remains open, piling up several
        # concurrent vacancies that can each independently end up filled and
        # push the role past its hard ceiling.
        pending_by_role = self._open_vacancy_counts_by_role(existing)

        for request in state.get("_vacancy_requests", []):
            if (
                request.get("Vacancy_Reason", "Replacement") == "Replacement"
                and self.rng.random() > replacement_hiring_rate
            ):
                continue
            role_key = request["Role_Key"]
            department_name = self._department_name(request["Department_Key"], state)
            role_name = self._role_name_for_key(state, role_key)
            if not self._has_room_for_another_vacancy(
                state, role_key, department_name, role_name, role_counts, pending_by_role
            ):
                continue
            records.append(
                self._build_vacancy(
                    vacancy_key,
                    today,
                    role_key,
                    request["Department_Key"],
                    request.get("Vacancy_Reason", "Replacement")
                )
            )
            vacancy_key += 1
            pending_by_role[role_key] = pending_by_role.get(role_key, 0) + 1

        target_headcount = sum(role_counts.values()) + max(0, int(growth_vacancies))

        for _ in range(max(0, int(growth_vacancies))):
            role = self._choose_role_for_growth(
                state,
                role_counts,
                target_headcount,
                pending_by_role,
            )
            if role is None:
                # Every active role is already at its hard cap (or fully
                # covered by vacancies already open for it) - nothing left
                # to grow into this week.
                break
            role_key = role["Role_Key"]
            department_name = self._department_name(role["Department_Key"], state)
            if not self._has_room_for_another_vacancy(
                state, role_key, department_name, role["Role_Name"], role_counts, pending_by_role
            ):
                # The selection step already accounts for pending demand, so
                # this should not normally trigger - kept as a safety net
                # rather than trusting that step alone.
                continue
            records.append(
                self._build_vacancy(
                    vacancy_key,
                    today,
                    role_key,
                    role["Department_Key"],
                    "Growth"
                )
            )
            vacancy_key += 1
            pending_by_role[role_key] = pending_by_role.get(role_key, 0) + 1

        if records:
            state["fact_vacancy"] = pd.concat(
                [existing, pd.DataFrame(records)],
                ignore_index=True
            )
        elif "fact_vacancy" not in state:
            state["fact_vacancy"] = pd.DataFrame(records)

        state["vacancies"] = self._open_vacancy_count(state)
        state.pop("_vacancy_requests", None)
        return state

    def _build_vacancy(self, vacancy_key, today, role_key, department_key, reason):
        target_days = self.rng.randint(14, 56)
        return build_record(
            self.schema,
            "fact_vacancy",
            {
                "Vacancy_Key": vacancy_key,
                "Created_Date": today,
                "Closed_Date": None,
                "Role_Key": role_key,
                "Department_Key": department_key,
                "Vacancy_Reason": reason,
                "Status": "Open",
                "Target_Start_Date": today + pd.DateOffset(days=target_days),
                "Filled_Employee_Key": None
            }
        )

    def _choose_role_for_growth(self, state, role_counts, target_headcount, pending_by_role):
        dim_role = state["dim_role"]
        company_headcount = sum(role_counts.values())
        department_headcounts = self._department_headcounts_by_name(dim_role, role_counts)
        active_structure = self._active_structure(company_headcount, department_headcounts)

        def covered_count(role_key):
            # Active headcount plus vacancies already open for this role -
            # demand already in flight, not just demand already filled.
            return role_counts.get(role_key, 0) + pending_by_role.get(role_key, 0)

        def has_room(role_row):
            department_name = self._department_name(role_row["Department_Key"], state)
            capacity = effective_role_capacity(
                state, self.config, department_name, role_row["Role_Name"]
            )
            return capacity is None or covered_count(role_row["Role_Key"]) < capacity

        under_minimum = dim_role[
            dim_role.apply(
                lambda role: (
                    covered_count(role["Role_Key"])
                    < self._minimum_for_role(state, role, role_counts)
                    and has_room(role)
                )
                if self._is_active_role(state, role, company_headcount, department_headcounts)
                else False,
                axis=1
            )
        ]
        if not under_minimum.empty:
            # Correct structural shortages before following the long-term
            # workforce mix. This also repairs a manager role after attrition.
            # Picking randomly among every current shortfall - rather than
            # always the first one in Role_Key order - stops several roles
            # crossing their minimum around the same time from being resolved
            # in one fixed, deterministic order every single week. `has_room`
            # keeps this branch from repeatedly re-flagging a role that is
            # already fully covered by a vacancy still being recruited (or
            # genuinely at a hard ceiling) - without it, growth demand would
            # be wasted on a pick that can never be acted on, every week,
            # instead of reaching a role that still has room.
            return under_minimum.sample(
                n=1,
                random_state=self.rng.randint(0, 100000)
            ).iloc[0]

        weighted_roles = []
        weights = []

        for _, role in dim_role.iterrows():
            if not self._is_active_role(state, role, company_headcount, department_headcounts):
                continue
            if not has_room(role):
                # A hard ceiling (e.g. exactly one Managing Director), or a
                # role already fully covered by vacancies still being
                # recruited - unlike an ordinary over-target role, this must
                # never be selected again, not even with a small residual
                # chance.
                continue
            current_count = covered_count(role["Role_Key"])
            target_share = self._target_ratio_for_role(
                state,
                role,
                active_structure,
            )
            target_count = target_share * max(1, target_headcount)
            gap = target_count - current_count
            weight = 1 + max(0, gap)

            if gap < -1:
                weight = 0.05

            weighted_roles.append(role)
            weights.append(weight)

        if not weighted_roles:
            # Every active role is at its cap, or already fully covered by
            # pending vacancies - nothing to grow into this week.
            return None

        return self.rng.choices(weighted_roles, weights=weights)[0]

    def _department_headcounts_by_name(self, dim_role, role_counts):
        """Sum current headcount per Department_Name.

        Named (not keyed by Department_Key) so it can also answer
        `department_group` scope questions, which reference departments by
        name across a role's `active_from_departments` list.
        """
        totals = {}
        for _, role in dim_role.iterrows():
            department_name = role["Department_Name"]
            totals[department_name] = (
                totals.get(department_name, 0)
                + role_counts.get(role["Role_Key"], 0)
            )
        return totals

    def _minimum_for_role(self, state, role_row, role_counts):
        department_name = self._department_name(
            role_row["Department_Key"],
            state
        )
        department_structure = self.config.structure[department_name]
        role_config = department_structure[role_row["Role_Name"]]
        staffing_rules = getattr(self.config, "staffing", {})
        flat_minimum = minimum_count_for_role(
            department_name,
            role_row["Role_Name"],
            role_config,
            staffing_rules
        )

        manager_roles = [
            (name, cfg) for name, cfg in department_structure.items()
            if cfg.get("leidinggevend", False)
        ]
        if team_lead_role_name(manager_roles) != role_row["Role_Name"]:
            return flat_minimum

        # The department's team-lead role scales with its actual current
        # span of control rather than a flat "at least one" floor - without
        # this, a department that has grown well past `max_team_size` per
        # lead never gets flagged as understaffed on leads, and one that
        # never needed more than its flat floor keeps getting nominated
        # anyway once the weighted lottery also wants more of it.
        non_manager_headcount = self._non_manager_headcount_for_department(
            state, department_name, role_counts
        )
        team_lead_minimum = team_lead_requirement(
            non_manager_headcount,
            int(staffing_rules.get("max_team_size", 0))
        )
        if team_lead_minimum is None:
            return flat_minimum
        return max(flat_minimum, team_lead_minimum)

    def _non_manager_headcount_for_department(self, state, department_name, role_counts):
        dim_role = state["dim_role"]
        department_roles = dim_role[dim_role["Department_Name"] == department_name]
        department_structure = self.config.structure[department_name]
        total = 0
        for _, role in department_roles.iterrows():
            if department_structure[role["Role_Name"]].get("leidinggevend", False):
                continue
            total += role_counts.get(role["Role_Key"], 0)
        return total

    def _active_role_counts(self, state):
        active = state["fact_employment"][
            state["fact_employment"]["Dienstverband_status"] == "Actief"
        ]
        return active["Role_Key"].value_counts().to_dict()

    def _open_vacancy_counts_by_role(self, vacancy_df):
        if vacancy_df.empty or "Status" not in vacancy_df.columns:
            return {}
        open_vacancies = vacancy_df[vacancy_df["Status"] == "Open"]
        return open_vacancies["Role_Key"].value_counts().to_dict()

    def _has_room_for_another_vacancy(
        self, state, role_key, department_name, role_name, role_counts, pending_by_role
    ):
        capacity = effective_role_capacity(state, self.config, department_name, role_name)
        if capacity is None:
            return True
        covered = role_counts.get(role_key, 0) + pending_by_role.get(role_key, 0)
        return covered < capacity

    def _role_name_for_key(self, state, role_key):
        return state["dim_role"].loc[
            state["dim_role"]["Role_Key"] == role_key, "Role_Name"
        ].iloc[0]

    def _open_vacancy_count(self, state):
        vacancy = state.get("fact_vacancy", pd.DataFrame())
        if vacancy.empty or "Status" not in vacancy.columns:
            return 0
        return int((vacancy["Status"] == "Open").sum())

    def _target_ratio_for_role(self, state, role_row, active_structure):
        department_name = self._department_name(role_row["Department_Key"], state)
        role_name = role_row["Role_Name"]
        return role_target_ratio(
            active_structure,
            department_name,
            role_name,
            self.config.workforce_planning,
        )

    def _active_structure(self, company_headcount, department_headcounts):
        return {
            department: {
                role_name: role_config
                for role_name, role_config in roles.items()
                if role_is_active(
                    role_config,
                    company_headcount,
                    scope_headcount(role_config, department, department_headcounts),
                )
            }
            for department, roles in self.config.structure.items()
        }

    def _is_active_role(self, state, role_row, company_headcount, department_headcounts):
        department_name = self._department_name(role_row["Department_Key"], state)
        role_config = self.config.structure[department_name][role_row["Role_Name"]]
        return role_is_active(
            role_config,
            company_headcount,
            scope_headcount(role_config, department_name, department_headcounts),
        )

    def _department_name(self, department_key, state):
        return state["dim_department"].loc[
            state["dim_department"]["Department_Key"] == department_key,
            "Department_Name"
        ].iloc[0]
