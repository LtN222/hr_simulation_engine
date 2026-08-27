import math

import pandas as pd

from src.infrastructure.record_builder import build_record
from src.infrastructure.salary_band import salary_band_key_for
from src.infrastructure.satisfaction import (
    SatisfactionModel,
    score_employee_satisfaction,
)


class AbsenceSimulator:
    """Generate realistic absence events for active employees.

    The simulator models absence as an incident process.  The configured
    annual event rate is converted to a weekly hazard, so running the weekly
    pipeline does not accidentally multiply the annual rate by 52.  A person
    can have at most one absence episode at a time, and an episode is kept
    inside the employee's employment period.

    Rows are append-only.  This is important for incremental runs: historical
    absence facts must remain available for Power BI and existing keys must
    never be reused.
    """

    def __init__(self, config, schema, rng):
        self.config = config
        self.schema = schema
        self.rng = rng
        self.absence_cfg = config.absence
        self.satisfaction_model = SatisfactionModel(config)

    def run(self, state, today):
        today = pd.Timestamp(today).normalize()
        existing_absence = self._normalise_existing_absence(
            state.get("fact_absence", pd.DataFrame())
        )

        employment_lookup = self._active_employment_lookup(
            state.get("fact_employment", pd.DataFrame())
        )
        absence_types = self._available_absence_types(
            state.get("dim_absence_type", pd.DataFrame())
        )
        occupied_employees = self._overlapping_employee_keys(
            existing_absence,
            today,
            today + pd.Timedelta(days=6)
        )
        leave_event_counts = self._event_counts(existing_absence)

        records = []
        next_absence_key = self._next_key(existing_absence)

        if absence_types:
            for _, employee in state["dim_employee"].iterrows():
                employee_key = employee["Employee_Key"]
                if employee_key not in employment_lookup.index:
                    continue

                employment = employment_lookup.loc[employee_key]
                if not self._eligible_for_absence(employment, today):
                    continue

                if employee_key in occupied_employees:
                    continue

                absence_type = self._choose_incident_type(
                    employee,
                    employment,
                    absence_types,
                    state,
                    existing_absence,
                    records,
                    today,
                    leave_event_counts,
                )
                if absence_type is None:
                    continue

                record = self._generate_absence_record(
                    employee,
                    absence_type,
                    next_absence_key,
                    today,
                    employment,
                    state
                )
                if record is not None:
                    records.append(record)
                    leave_event_counts[(
                        employee_key,
                        record["AbsenceType_Key"],
                        pd.Timestamp(record["Startdatum"]).year,
                    )] = leave_event_counts.get((
                        employee_key,
                        record["AbsenceType_Key"],
                        pd.Timestamp(record["Startdatum"]).year,
                    ), 0) + 1
                    next_absence_key += 1

        if records:
            state["fact_absence"] = pd.concat(
                [existing_absence, pd.DataFrame(records)],
                ignore_index=True
            )
        elif "fact_absence" not in state:
            state["fact_absence"] = existing_absence
        else:
            state["fact_absence"] = existing_absence

        return state

    def _active_employment_lookup(self, fact_employment):
        if fact_employment.empty:
            return pd.DataFrame().set_index(pd.Index([], name="Employee_Key"))

        active = fact_employment[
            fact_employment["Dienstverband_status"] == "Actief"
        ].copy()
        if active.empty:
            return active.set_index("Employee_Key")

        active["Startdatum"] = pd.to_datetime(
            active["Startdatum"], errors="coerce"
        ).dt.normalize()
        if "Einddatum" in active.columns:
            active["Einddatum"] = pd.to_datetime(
                active["Einddatum"], errors="coerce"
            ).dt.normalize()
        if "Contract_einddatum" in active.columns:
            active["Contract_einddatum"] = pd.to_datetime(
                active["Contract_einddatum"], errors="coerce"
            ).dt.normalize()

        return active.drop_duplicates(
            subset=["Employee_Key"],
            keep="last"
        ).set_index("Employee_Key")

    def _normalise_existing_absence(self, absence):
        if absence.empty:
            return absence.copy()

        result = absence.copy()
        for column in ("Startdatum", "Einddatum"):
            if column in result.columns:
                result[column] = pd.to_datetime(
                    result[column], errors="coerce"
                ).dt.normalize()
        return result

    @staticmethod
    def _overlapping_employee_keys(absence, window_start, window_end):
        """Return employees with an episode overlapping this simulation week."""
        if absence.empty:
            return set()
        overlap = absence[(absence["Startdatum"] <= window_end) & (
            absence["Einddatum"] >= window_start
        )]
        return set(overlap["Employee_Key"].dropna().tolist())

    @staticmethod
    def _event_counts(absence):
        """Index historical leave events once instead of scanning per employee."""
        if absence.empty:
            return {}
        starts = pd.to_datetime(absence["Startdatum"], errors="coerce")
        indexed = absence.loc[starts.notna(), [
            "Employee_Key", "AbsenceType_Key"
        ]].copy()
        indexed["Year"] = starts.loc[starts.notna()].dt.year
        return indexed.groupby(
            ["Employee_Key", "AbsenceType_Key", "Year"]
        ).size().to_dict()

    def _next_key(self, absence):
        if absence.empty or "Absence_Key" not in absence.columns:
            return 1
        keys = pd.to_numeric(absence["Absence_Key"], errors="coerce").dropna()
        return int(keys.max()) + 1 if not keys.empty else 1

    def _eligible_for_absence(self, employment, today):
        start = pd.Timestamp(employment["Startdatum"]).normalize()
        minimum_tenure = int(
            self.absence_cfg.get("minimum_tenure_days", 10)
        )
        if today < start + pd.Timedelta(days=minimum_tenure):
            return False

        end = self._employment_end(employment)
        return pd.isna(end) or end >= today

    def _employment_end(self, employment):
        # Enddatum is authoritative after attrition.  For active temporary
        # contracts, Contract_einddatum prevents episodes after the contract.
        end = employment.get("Einddatum")
        contract_end = employment.get("Contract_einddatum")
        end = pd.Timestamp(end).normalize() if pd.notna(end) else pd.NaT
        contract_end = (
            pd.Timestamp(contract_end).normalize()
            if pd.notna(contract_end)
            else pd.NaT
        )
        if pd.isna(end):
            return contract_end
        if pd.isna(contract_end):
            return end
        return min(end, contract_end)

    def _calculate_probability(
        self,
        employee,
        employment,
        state,
        today=None
    ):
        """Return the expected annual number of sickness episodes.

        This is an incident *rate*, rather than the probability that someone
        has at least one episode. Employees can therefore have multiple short
        sickness episodes in a year, provided they do not overlap.
        """
        annual_rate = self.absence_cfg.get(
            "annual_sickness_episode_rate",
            self.absence_cfg.get(
                "annual_event_rate",
                self.absence_cfg.get("base_probability", 0.0)
            )
        )
        age_multipliers = self.absence_cfg.get("age_multipliers", {})
        age = self._current_age(employee, today)

        if age < 30:
            age_factor = age_multipliers.get("<30", 1.0)
        elif age < 45:
            age_factor = age_multipliers.get("30-45", 1.0)
        elif age < 55:
            age_factor = age_multipliers.get("45-55", 1.0)
        else:
            age_factor = age_multipliers.get("55+", 1.0)

        shift_factor = self._ploegendienst_factor(employment, state)
        department_factor = self._department_factor(employment, state)
        gender_factor = self.absence_cfg.get(
            "gender_multipliers",
            {}
        ).get(employee.get("Geslacht"), 1.0)
        seasonal_factor = self.absence_cfg.get(
            "seasonal_multipliers",
            {}
        ).get(str(pd.Timestamp(today).month), 1.0) if today is not None else 1.0
        satisfaction = score_employee_satisfaction(
            self.satisfaction_model,
            state,
            employee,
            employment,
            today,
        )
        satisfaction_factor = self._satisfaction_incident_multiplier(
            satisfaction
        )
        return max(
            0.0,
            min(
                4.0,
                float(annual_rate)
                * float(age_factor)
                * float(shift_factor)
                * float(department_factor)
                * float(gender_factor)
                * float(seasonal_factor)
                * satisfaction_factor
            )
        )

    def _satisfaction_incident_multiplier(self, satisfaction_score):
        """Keep satisfaction's effect on sickness risk modest and configurable."""
        multipliers = self.absence_cfg.get(
            "satisfaction_incident_multipliers",
            {}
        )
        score = pd.to_numeric(satisfaction_score, errors="coerce")
        if pd.isna(score):
            return 1.0
        if score < 6.0:
            return float(multipliers.get("low", 1.12))
        if score < 7.5:
            return float(multipliers.get("neutral", 1.0))
        return float(multipliers.get("high", 0.94))

    def _current_age(self, employee, today):
        birth_date = employee.get("Geboortedatum")
        if pd.notna(birth_date) and today is not None:
            birth_date = pd.Timestamp(birth_date)
            reference = pd.Timestamp(today)
            birthday_passed = (reference.month, reference.day) >= (
                birth_date.month,
                birth_date.day
            )
            return reference.year - birth_date.year - (0 if birthday_passed else 1)

        return 0

    def _ploegendienst_factor(self, employment, state):
        multipliers = self.absence_cfg.get("ploegendienst_multipliers", {})
        shifts = state.get("dim_shift", pd.DataFrame())
        shift_key = employment.get("Shift_Key")
        if not multipliers or shifts.empty or pd.isna(shift_key):
            return 1.0
        match = shifts.loc[
            shifts["Shift_Key"] == shift_key,
            "Ploegendienst_Naam"
        ]
        return float(multipliers.get(match.iloc[0], 1.0)) if not match.empty else 1.0

    def _department_factor(self, employment, state):
        multipliers = self.absence_cfg.get("department_multipliers", {})
        roles = state.get("dim_role", pd.DataFrame())
        departments = state.get("dim_department", pd.DataFrame())
        role_key = employment.get("Role_Key")
        if not multipliers or roles.empty or departments.empty or pd.isna(role_key):
            return 1.0

        role = roles.loc[roles["Role_Key"] == role_key]
        if role.empty or "Department_Key" not in role.columns:
            return 1.0
        department = departments.loc[
            departments["Department_Key"] == role.iloc[0]["Department_Key"]
        ]
        if department.empty:
            return 1.0
        return float(multipliers.get(
            department.iloc[0].get("Afdeling_Naam"),
            1.0
        ))

    def _available_absence_types(self, dim_absence_type):
        if dim_absence_type.empty:
            return []

        types = dim_absence_type.copy()
        if "Telt_als_verzuim" not in types.columns:
            types["Telt_als_verzuim"] = False
        return types[
            ["AbsenceType_Key", "Verzuim_Type_Naam", "Telt_als_verzuim"]
        ].to_dict(orient="records")

    def _choose_incident_type(
        self,
        employee,
        employment,
        absence_types,
        state,
        existing_absence,
        new_records,
        today,
        leave_event_counts=None,
    ):
        """Draw at most one weekly illness or leave episode per employee."""
        candidates = []
        sickness_types = [
            absence_type
            for absence_type in absence_types
            if bool(absence_type["Telt_als_verzuim"])
        ]
        if sickness_types:
            annual_probability = self._calculate_probability(
                employee,
                employment,
                state,
                today
            )
            sickness_probability = self._weekly_incident_probability(
                annual_probability
            )
            configured_weights = self.absence_cfg.get("type_weights", {})
            total_weight = sum(
                configured_weights.get(absence_type["Verzuim_Type_Naam"], 1.0)
                for absence_type in sickness_types
            )
            if total_weight <= 0:
                total_weight = float(len(sickness_types))
                configured_weights = {}
            for absence_type in sickness_types:
                weight = configured_weights.get(
                    absence_type["Verzuim_Type_Naam"],
                    1.0
                )
                candidates.append((
                    absence_type,
                    sickness_probability * weight / total_weight
                ))

        leave_rules = self.absence_cfg.get("leave_type_rules", {})
        for absence_type in absence_types:
            if bool(absence_type["Telt_als_verzuim"]):
                continue

            rule = leave_rules.get(absence_type["Verzuim_Type_Naam"])
            if not rule or not self._eligible_for_leave_type(
                employee,
                employment,
                state,
                absence_type,
                rule,
                existing_absence,
                new_records,
                today,
                leave_event_counts,
            ):
                continue

            probability = self._weekly_probability(
                float(rule.get("annual_probability", 0.0))
            )
            if probability > 0:
                candidates.append((absence_type, probability))

        total_probability = sum(probability for _, probability in candidates)
        if total_probability <= 0 or self.rng.random() >= min(0.95, total_probability):
            return None

        types, weights = zip(*candidates)
        return self.rng.choices(types, weights=weights, k=1)[0]

    @staticmethod
    def _weekly_probability(annual_probability):
        annual_probability = max(0.0, min(0.999, annual_probability))
        return 1 - math.pow(1 - annual_probability, 1 / 52)

    @staticmethod
    def _weekly_incident_probability(annual_rate):
        """Convert an expected annual episode rate into a weekly hazard."""
        return min(0.80, max(0.0, float(annual_rate) / 52))

    def _eligible_for_leave_type(
        self,
        employee,
        employment,
        state,
        absence_type,
        rule,
        existing_absence,
        new_records,
        today,
        leave_event_counts=None,
    ):
        age = self._current_age(employee, today)
        gender = employee.get("Geslacht")
        genders = rule.get("genders")
        if genders and gender not in genders:
            return False
        if age < int(rule.get("min_age", 0)):
            return False
        if age > int(rule.get("max_age", 120)):
            return False

        tenure_days = (today - pd.Timestamp(employment["Startdatum"])).days
        if tenure_days < int(rule.get("min_tenure_days", 0)):
            return False
        if not self._has_required_ploegendienst(
            employment,
            state,
            rule.get("required_ploegendienst")
        ):
            return False

        max_events = rule.get("max_events_per_year")
        event_count = (
            leave_event_counts.get((
                employee["Employee_Key"],
                absence_type["AbsenceType_Key"],
                today.year,
            ), 0)
            if leave_event_counts is not None
            else self._events_in_year(
                existing_absence,
                new_records,
                employee["Employee_Key"],
                absence_type["AbsenceType_Key"],
                today.year
            )
        )
        return (
            max_events is None
            or event_count < int(max_events)
        )

    @staticmethod
    def _has_required_ploegendienst(employment, state, required_names):
        if not required_names:
            return True
        shifts = state.get("dim_shift", pd.DataFrame())
        shift_key = employment.get("Shift_Key")
        if shifts.empty or pd.isna(shift_key):
            return False
        name = shifts.loc[
            shifts["Shift_Key"] == shift_key,
            "Ploegendienst_Naam"
        ]
        return not name.empty and name.iloc[0] in required_names

    @staticmethod
    def _events_in_year(
        existing_absence,
        new_records,
        employee_key,
        absence_type_key,
        year
    ):
        frames = [frame for frame in [existing_absence, pd.DataFrame(new_records)] if not frame.empty]
        if not frames:
            return 0

        absence = pd.concat(frames, ignore_index=True)
        starts = pd.to_datetime(absence["Startdatum"], errors="coerce")
        return int((
            (absence["Employee_Key"] == employee_key)
            & (absence["AbsenceType_Key"] == absence_type_key)
            & (starts.dt.year == year)
        ).sum())

    def _choose_absence_type(self, absence_types):
        """Choose a sickness type for backwards-compatible direct callers."""
        configured_weights = self.absence_cfg.get("type_weights", {})
        names = [absence_type["Verzuim_Type_Naam"] for absence_type in absence_types]
        weights = [configured_weights.get(name, 1.0) for name in names]
        if not weights or sum(weights) <= 0:
            weights = [1.0] * len(absence_types)
        return self.rng.choices(absence_types, weights=weights, k=1)[0]

    def _choose_duration(self, type_name):
        ranges = self.absence_cfg.get(
            "duration_ranges_by_type",
            {}
        ).get(type_name, [])
        if ranges:
            return self._choose_duration_from_ranges(ranges)

        distributions = self.absence_cfg.get(
            "duration_distribution_by_type",
            {}
        )
        distribution = distributions.get(
            type_name,
            self.absence_cfg.get("duration_distribution", {"1": 1.0})
        )
        if not distribution or sum(distribution.values()) <= 0:
            distribution = {"1": 1.0}
        durations = [int(value) for value in distribution.keys()]
        weights = list(distribution.values())
        return max(1, int(self.rng.choices(durations, weights=weights, k=1)[0]))

    def _choose_duration_from_ranges(self, ranges):
        """Sample a rounded duration from a configured weighted range."""
        valid_ranges = [
            duration_range
            for duration_range in ranges
            if int(duration_range["min_days"])
            <= int(duration_range["mode_days"])
            <= int(duration_range["max_days"])
            and float(duration_range.get("weight", 1.0)) > 0
        ]
        if not valid_ranges:
            raise ValueError("Absence duration ranges must have valid bounds.")

        weights = [duration_range.get("weight", 1.0) for duration_range in valid_ranges]
        selected = self.rng.choices(valid_ranges, weights=weights, k=1)[0]
        duration = self.rng.triangular(
            int(selected["min_days"]),
            int(selected["max_days"]),
            int(selected["mode_days"])
        )
        return max(1, int(round(duration)))

    def _generate_absence_record(
        self,
        employee,
        absence_type,
        absence_key,
        today,
        employment,
        state
    ):
        employment_start = pd.Timestamp(employment["Startdatum"]).normalize()
        employment_end = self._employment_end(employment)

        earliest_start = max(today, employment_start)
        latest_start = today + pd.Timedelta(days=6)
        if pd.notna(employment_end):
            latest_start = min(latest_start, employment_end)
        if earliest_start > latest_start:
            return None

        start_offset = self.rng.randint(0, (latest_start - earliest_start).days)
        start = earliest_start + pd.Timedelta(days=start_offset)
        type_key = absence_type["AbsenceType_Key"]
        type_name = absence_type["Verzuim_Type_Naam"]
        duration = self._choose_duration(type_name)
        satisfaction = score_employee_satisfaction(
            self.satisfaction_model,
            state,
            employee,
            employment,
            start,
        )
        satisfaction_band_key = self.satisfaction_model.band_key_for(
            state.get("dim_satisfaction_band", pd.DataFrame()),
            satisfaction,
        )

        # Dates are inclusive: a one-day absence starts and ends on the same
        # date, so Duur_dagen remains consistent with the date columns.
        end = start + pd.Timedelta(days=duration - 1)
        if pd.notna(employment_end):
            end = min(end, employment_end)
        duration = (end - start).days + 1
        employment_context = self._employment_context(state, employment)
        absence_workdays = len(pd.bdate_range(start, end))
        hours_per_day = self._hours_per_workday(employment)
        absence_hours = round(absence_workdays * hours_per_day, 2)
        is_sickness = bool(absence_type.get("Telt_als_verzuim", False))

        return build_record(
            self.schema,
            "fact_absence",
            {
                "Absence_Key": absence_key,
                "Employee_Key": employee["Employee_Key"],
                "AbsenceType_Key": type_key,
                "Role_Key": employment_context["Role_Key"],
                "Department_Key": employment_context["Department_Key"],
                "Location_Key": employment_context["Location_Key"],
                "Shift_Key": employment_context["Shift_Key"],
                "SalaryBand_Key": employment_context["SalaryBand_Key"],
                "SalaryScale_Key": employment_context["SalaryScale_Key"],
                "Salaris_bij_aanvang": employment_context["Salaris_bij_aanvang"],
                "Tevredenheid_Score_Bij_Aanvang": satisfaction,
                "SatisfactionBand_Key": satisfaction_band_key,
                "Startdatum": start,
                "Einddatum": end,
                "Duur_dagen": duration,
                "Afwezigheid_Werkdagen": absence_workdays,
                "Afwezigheid_Uren": absence_hours,
                "Verzuim_Werkdagen": absence_workdays if is_sickness else 0,
                "Verzuim_Uren": absence_hours if is_sickness else 0.0,
            }
        )

    def _hours_per_workday(self, employment):
        weekly_hours = pd.to_numeric(
            employment.get("Contracturen"),
            errors="coerce"
        )
        if pd.isna(weekly_hours):
            workforce_config = getattr(self.config, "workforce", {})
            weekly_hours = workforce_config.get(
                "full_time_weekly_hours",
                40
            )
        return float(weekly_hours) / 5

    def _employment_context(self, state, employment):
        """Capture conformed dimensions as they were when absence started."""
        role_key = employment.get("Role_Key")
        department_key = self._department_for_role(state, role_key)
        salary = pd.to_numeric(employment.get("Salaris"), errors="coerce")
        return {
            "Role_Key": role_key,
            "Department_Key": department_key,
            "Location_Key": employment.get("Location_Key"),
            "Shift_Key": employment.get("Shift_Key"),
            "SalaryBand_Key": salary_band_key_for(
                state.get("dim_salary_band", pd.DataFrame()),
                salary
            ),
            "SalaryScale_Key": employment.get("SalaryScale_Key"),
            "Salaris_bij_aanvang": int(salary)
        }

    @staticmethod
    def _department_for_role(state, role_key):
        roles = state.get("dim_role", pd.DataFrame())
        if roles.empty or pd.isna(role_key):
            return None

        role = roles.loc[roles["Role_Key"] == role_key, "Department_Key"]
        return role.iloc[0] if not role.empty else None

    def _has_overlap(
        self,
        existing_absence,
        new_records,
        employee_key,
        window_start,
        window_end
    ):
        rows = []
        if not existing_absence.empty:
            rows.append(existing_absence)
        if new_records:
            rows.append(pd.DataFrame(new_records))
        if not rows:
            return False

        absence = pd.concat(rows, ignore_index=True)
        employee_absences = absence[absence["Employee_Key"] == employee_key]
        if employee_absences.empty:
            return False

        return bool(
            (
                (employee_absences["Startdatum"] <= window_end)
                & (employee_absences["Einddatum"] >= window_start)
            ).any()
        )
