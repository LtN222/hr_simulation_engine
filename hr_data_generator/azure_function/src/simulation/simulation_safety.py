import pandas as pd

from src.infrastructure.record_builder import build_record
from src.infrastructure.salary_band import salary_band_key_for
from src.infrastructure.satisfaction import (
    SatisfactionModel,
    score_employee_satisfaction,
)

LOST_TIME_INCIDENT_TYPE = "Verzuimongeval"
LOST_TIME_ABSENCE_TYPE = "Bedrijfsongeval"


class SafetyIncidentSimulator:
    """Generate workplace safety incidents for active employees.

    Risk is driven by department (floor-facing roles carry most of it),
    shift work and tenure (new hires are disproportionately likely to be
    involved in an incident - a well-documented real pattern). Most
    incidents are near-misses or minor first aid; a small share cause real
    lost time, in which case this also creates the matching `fact_absence`
    episode (type Bedrijfsongeval) so safety incidents feed the same verzuim
    reporting as ordinary sickness rather than living in an isolated table.

    Runs after AbsenceSimulator in the weekly order, so it sees this week's
    sickness episodes too and never doubles someone up who is already off.
    """

    def __init__(self, config, schema, rng):
        self.config = config
        self.schema = schema
        self.rng = rng
        self.safety_cfg = getattr(config, "safety", {})
        self.satisfaction_model = SatisfactionModel(config)

    def run(self, state, today):
        today = pd.Timestamp(today).normalize()
        incident_types = self._available_incident_types(
            state.get("dim_incident_type", pd.DataFrame())
        )
        existing_incidents = state.get("fact_safety_incident", pd.DataFrame())
        if not incident_types:
            state["fact_safety_incident"] = existing_incidents
            return state

        existing_absence = state.get("fact_absence", pd.DataFrame())
        employment_lookup = self._active_employment_lookup(
            state.get("fact_employment", pd.DataFrame())
        )
        occupied_employees = self._overlapping_employee_keys(
            existing_absence, today, today + pd.Timedelta(days=6)
        )

        incident_records = []
        absence_records = []
        next_incident_key = self._next_key(existing_incidents, "Incident_Key")
        next_absence_key = self._next_key(existing_absence, "Absence_Key")

        for _, employee in state["dim_employee"].iterrows():
            employee_key = employee["Employee_Key"]
            if employee_key not in employment_lookup.index:
                continue
            if employee_key in occupied_employees:
                continue

            employment = employment_lookup.loc[employee_key]
            weekly_probability = self._weekly_probability(
                self._annual_rate(employment, state, today)
            )
            if weekly_probability <= 0 or self.rng.random() >= weekly_probability:
                continue

            incident_type = self._choose_incident_type(incident_types)
            incident_date = today + pd.Timedelta(days=self.rng.randint(0, 6))
            absence_key = None
            lost_workdays = 0

            if incident_type["Incidenttype_Naam"] == LOST_TIME_INCIDENT_TYPE:
                lost_workdays, absence_record = self._build_lost_time_absence(
                    employee, employment, state, incident_date, next_absence_key
                )
                if absence_record is not None:
                    absence_records.append(absence_record)
                    absence_key = next_absence_key
                    next_absence_key += 1
                    occupied_employees.add(employee_key)

            incident_records.append(self._build_incident_record(
                next_incident_key, employee_key, incident_type,
                employment, state, incident_date, lost_workdays, absence_key,
            ))
            next_incident_key += 1

        if incident_records:
            state["fact_safety_incident"] = pd.concat(
                [existing_incidents, pd.DataFrame(incident_records)],
                ignore_index=True,
            )
        elif "fact_safety_incident" not in state:
            state["fact_safety_incident"] = existing_incidents

        if absence_records:
            state["fact_absence"] = pd.concat(
                [existing_absence, pd.DataFrame(absence_records)],
                ignore_index=True,
            )

        return state

    # ------------------------------------------------------------------
    # Risk calculation
    # ------------------------------------------------------------------

    def _annual_rate(self, employment, state, today):
        department_name = self._department_name(state, employment.get("Role_Key"))
        base_rate = self.safety_cfg.get("annual_incident_rate_by_department", {}).get(
            department_name, 0.0
        )
        shift_factor = self._ploegendienst_factor(employment, state)
        tenure_factor = self._new_hire_factor(employment, today)
        return max(0.0, float(base_rate) * shift_factor * tenure_factor)

    def _ploegendienst_factor(self, employment, state):
        multipliers = self.safety_cfg.get("ploegendienst_multipliers", {})
        shifts = state.get("dim_shift", pd.DataFrame())
        shift_key = employment.get("Shift_Key")
        if not multipliers or shifts.empty or pd.isna(shift_key):
            return 1.0
        match = shifts.loc[
            shifts["Shift_Key"] == shift_key, "Ploegendienst_Naam"
        ]
        return float(multipliers.get(match.iloc[0], 1.0)) if not match.empty else 1.0

    def _new_hire_factor(self, employment, today):
        rule = self.safety_cfg.get("new_hire_multiplier", {})
        within_days = int(rule.get("within_days", 0) or 0)
        if within_days <= 0:
            return 1.0
        start = pd.to_datetime(employment.get("Startdatum"), errors="coerce")
        if pd.isna(start):
            return 1.0
        tenure_days = (pd.Timestamp(today) - start.normalize()).days
        return float(rule.get("multiplier", 1.0)) if 0 <= tenure_days <= within_days else 1.0

    @staticmethod
    def _weekly_probability(annual_rate):
        return min(0.5, max(0.0, annual_rate) / 52)

    def _choose_incident_type(self, incident_types):
        weights_cfg = self.safety_cfg.get("type_weights", {})
        weights = [
            float(weights_cfg.get(incident_type["Incidenttype_Naam"], 1.0))
            for incident_type in incident_types
        ]
        if sum(weights) <= 0:
            weights = [1.0] * len(incident_types)
        return self.rng.choices(incident_types, weights=weights, k=1)[0]

    # ------------------------------------------------------------------
    # Record construction
    # ------------------------------------------------------------------

    def _build_incident_record(
        self, incident_key, employee_key, incident_type, employment, state,
        incident_date, lost_workdays, absence_key,
    ):
        role_key = employment.get("Role_Key")
        return build_record(
            self.schema,
            "fact_safety_incident",
            {
                "Incident_Key": incident_key,
                "Employee_Key": employee_key,
                "IncidentType_Key": incident_type["IncidentType_Key"],
                "Role_Key": role_key,
                "Department_Key": self._department_for_role(state, role_key),
                "Location_Key": employment.get("Location_Key"),
                "Shift_Key": employment.get("Shift_Key"),
                "Incident_Date": incident_date,
                "Verloren_Werkdagen": lost_workdays,
                "Absence_Key": absence_key,
            }
        )

    def _build_lost_time_absence(self, employee, employment, state, start, absence_key):
        employment_end = self._employment_end(employment)
        if pd.notna(employment_end) and start > employment_end:
            return 0, None

        duration = self._choose_lost_workdays()
        end = start + pd.Timedelta(days=duration - 1)
        if pd.notna(employment_end):
            end = min(end, employment_end)
        duration = (end - start).days + 1

        role_key = employment.get("Role_Key")
        department_key = self._department_for_role(state, role_key)
        salary = pd.to_numeric(employment.get("Salaris"), errors="coerce")
        satisfaction = score_employee_satisfaction(
            self.satisfaction_model, state, employee, employment, start,
        )
        satisfaction_band_key = self.satisfaction_model.band_key_for(
            state.get("dim_satisfaction_band", pd.DataFrame()), satisfaction,
        )
        workdays = len(pd.bdate_range(start, end))
        hours_per_day = self._hours_per_workday(employment)
        hours = round(workdays * hours_per_day, 2)

        record = build_record(
            self.schema,
            "fact_absence",
            {
                "Absence_Key": absence_key,
                "Employee_Key": employee["Employee_Key"],
                "AbsenceType_Key": self._absence_type_key(state, LOST_TIME_ABSENCE_TYPE),
                "Role_Key": role_key,
                "Department_Key": department_key,
                "Location_Key": employment.get("Location_Key"),
                "Shift_Key": employment.get("Shift_Key"),
                "SalaryBand_Key": salary_band_key_for(
                    state.get("dim_salary_band", pd.DataFrame()), salary
                ),
                "SalaryScale_Key": employment.get("SalaryScale_Key"),
                "Salaris_bij_aanvang": int(salary) if pd.notna(salary) else None,
                "Tevredenheid_Score_Bij_Aanvang": satisfaction,
                "SatisfactionBand_Key": satisfaction_band_key,
                "Startdatum": start,
                "Einddatum": end,
                "Duur_dagen": duration,
                "Afwezigheid_Werkdagen": workdays,
                "Afwezigheid_Uren": hours,
                "Verzuim_Werkdagen": workdays,
                "Verzuim_Uren": hours,
            }
        )
        return duration, record

    def _choose_lost_workdays(self):
        rule = self.safety_cfg.get("lost_workdays_range", {})
        min_days = int(rule.get("min_days", 1))
        mode_days = int(rule.get("mode_days", min_days))
        max_days = int(rule.get("max_days", max(min_days, mode_days)))
        if not (min_days <= mode_days <= max_days):
            return max(1, min_days)
        return max(1, int(round(self.rng.triangular(min_days, max_days, mode_days))))

    def _hours_per_workday(self, employment):
        weekly_hours = pd.to_numeric(employment.get("Contracturen"), errors="coerce")
        if pd.isna(weekly_hours):
            weekly_hours = getattr(self.config, "workforce", {}).get(
                "full_time_weekly_hours", 40
            )
        return float(weekly_hours) / 5

    # ------------------------------------------------------------------
    # Lookups
    # ------------------------------------------------------------------

    def _active_employment_lookup(self, fact_employment):
        if fact_employment.empty:
            return pd.DataFrame().set_index(pd.Index([], name="Employee_Key"))
        active = fact_employment[
            fact_employment["Dienstverband_status"] == "Actief"
        ].copy()
        if active.empty:
            return active.set_index("Employee_Key")
        active["Startdatum"] = pd.to_datetime(active["Startdatum"], errors="coerce")
        if "Einddatum" in active.columns:
            active["Einddatum"] = pd.to_datetime(active["Einddatum"], errors="coerce")
        if "Contract_einddatum" in active.columns:
            active["Contract_einddatum"] = pd.to_datetime(
                active["Contract_einddatum"], errors="coerce"
            )
        return active.drop_duplicates(
            subset=["Employee_Key"], keep="last"
        ).set_index("Employee_Key")

    def _employment_end(self, employment):
        end = employment.get("Einddatum")
        contract_end = employment.get("Contract_einddatum")
        end = pd.Timestamp(end).normalize() if pd.notna(end) else pd.NaT
        contract_end = pd.Timestamp(contract_end).normalize() if pd.notna(contract_end) else pd.NaT
        if pd.isna(end):
            return contract_end
        if pd.isna(contract_end):
            return end
        return min(end, contract_end)

    @staticmethod
    def _overlapping_employee_keys(absence, window_start, window_end):
        if absence.empty:
            return set()
        starts = pd.to_datetime(absence["Startdatum"], errors="coerce")
        ends = pd.to_datetime(absence["Einddatum"], errors="coerce")
        overlap = absence[(starts <= window_end) & (ends >= window_start)]
        return set(overlap["Employee_Key"].dropna().tolist())

    def _available_incident_types(self, dim_incident_type):
        if dim_incident_type.empty:
            return []
        return dim_incident_type.to_dict(orient="records")

    def _absence_type_key(self, state, absence_type_name):
        types = state.get("dim_absence_type", pd.DataFrame())
        if types.empty or "Verzuim_Type_Naam" not in types.columns:
            return None
        match = types.loc[types["Verzuim_Type_Naam"] == absence_type_name, "AbsenceType_Key"]
        return match.iloc[0] if not match.empty else None

    @staticmethod
    def _department_for_role(state, role_key):
        roles = state.get("dim_role", pd.DataFrame())
        if roles.empty or pd.isna(role_key):
            return None
        role = roles.loc[roles["Role_Key"] == role_key, "Department_Key"]
        return role.iloc[0] if not role.empty else None

    def _department_name(self, state, role_key):
        roles = state.get("dim_role", pd.DataFrame())
        departments = state.get("dim_department", pd.DataFrame())
        if roles.empty or departments.empty or pd.isna(role_key):
            return None
        role = roles.loc[roles["Role_Key"] == role_key]
        if role.empty or "Department_Key" not in role.columns:
            return None
        department = departments.loc[
            departments["Department_Key"] == role.iloc[0]["Department_Key"]
        ]
        return department.iloc[0]["Afdeling_Naam"] if not department.empty else None

    @staticmethod
    def _next_key(dataframe, key_column):
        if dataframe.empty or key_column not in dataframe.columns:
            return 1
        keys = pd.to_numeric(dataframe[key_column], errors="coerce").dropna()
        return int(keys.max()) + 1 if not keys.empty else 1
