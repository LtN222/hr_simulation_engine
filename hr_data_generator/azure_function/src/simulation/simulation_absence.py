import pandas as pd

from src.infrastructure.record_builder import build_record


class AbsenceSimulator:
    """Generate absence events for active employees.

    The simulator is append-only: existing absence rows stay in state and new
    weekly events receive keys after the current maximum. That keeps full and
    incremental SQL writes aligned.
    """

    def __init__(self, config, schema, rng):
        self.config = config
        self.schema = schema
        self.rng = rng
        self.absence_cfg = config.absence

    def run(self, state, today):
        dim_employee = state["dim_employee"]
        fact_employment = state["fact_employment"]
        fact_employment_attribute = state["fact_employment_attribute"]
        dim_absence_type = state["dim_absence_type"]
        existing_absence = state.get("fact_absence", pd.DataFrame())

        active_employment = fact_employment[
            fact_employment["Dienstverband_status"] == "Actief"
        ]

        employment_lookup = active_employment.drop_duplicates(
            subset=["Employee_Key"],
            keep="last"
        ).set_index("Employee_Key")

        records = []
        absence_key = (
            int(existing_absence["Absence_Key"].max()) + 1
            if not existing_absence.empty and "Absence_Key" in existing_absence
            else 1
        )

        for _, emp in dim_employee.iterrows():
            employee_key = emp["Employee_Key"]

            if employee_key not in employment_lookup.index:
                continue

            employment_row = employment_lookup.loc[employee_key]
            employment_start = employment_row["Startdatum"]

            if (today - employment_start).days <= 10:
                continue

            probability = self._calculate_probability(
                emp,
                employment_row,
                fact_employment_attribute
            )

            # The config expresses an annual-ish absence chance. Weekly runs
            # scale it down to avoid producing a full year of events each week.
            events = self._draw_number_of_events(min(probability / 52, 0.95))

            for _ in range(events):
                records.append(
                    self._generate_absence_record(
                        emp,
                        dim_absence_type,
                        absence_key,
                        today,
                        employment_start
                    )
                )
                absence_key += 1

        if records:
            state["fact_absence"] = pd.concat(
                [existing_absence, pd.DataFrame(records)],
                ignore_index=True
            )
        elif "fact_absence" not in state:
            state["fact_absence"] = pd.DataFrame(records)

        return state

    def _calculate_probability(self, emp, employment_row, fact_employment_attribute):
        base_probability = self.absence_cfg["base_probability"]
        age_cfg = self.absence_cfg["age_multipliers"]
        attr_cfg = self.absence_cfg["attribute_multipliers"]

        leeftijd = emp["Leeftijd"]

        if leeftijd < 30:
            age_factor = age_cfg["<30"]
        elif leeftijd < 45:
            age_factor = age_cfg["30-45"]
        elif leeftijd < 55:
            age_factor = age_cfg["45-55"]
        else:
            age_factor = age_cfg["55+"]

        emp_attrs = fact_employment_attribute[
            fact_employment_attribute["Employment_Key"]
            == employment_row["Employment_Key"]
        ]

        attr_factor = 1.0

        for attr_name, values in attr_cfg.items():
            value_row = emp_attrs[emp_attrs["Attribute_Name"] == attr_name]

            if len(value_row) == 0:
                continue

            value = value_row.iloc[0]["Attribute_Value"]
            attr_factor *= values.get(value, 1.0)

        return base_probability * age_factor * attr_factor

    def _draw_number_of_events(self, probability):
        return self.rng.choices(
            [0, 1, 2],
            weights=[
                1 - probability,
                probability * 0.8,
                probability * 0.2
            ]
        )[0]

    def _generate_absence_record(
        self,
        emp,
        dim_absence_type,
        absence_key,
        today,
        employment_start
    ):
        duration_cfg = self.absence_cfg["duration_distribution"]

        duration = int(
            self.rng.choices(
                list(duration_cfg.keys()),
                weights=list(duration_cfg.values())
            )[0]
        )

        earliest_start = max(employment_start, today)
        latest_start = today + pd.DateOffset(days=6)
        max_offset = max(0, (latest_start - earliest_start).days)
        start = earliest_start + pd.DateOffset(days=self.rng.randint(0, max_offset))
        end = start + pd.DateOffset(days=duration)

        return build_record(
            self.schema,
            "fact_absence",
            {
                "Absence_Key": absence_key,
                "Employee_Key": emp["Employee_Key"],
                "AbsenceType_Key": self.rng.choice(
                    dim_absence_type["AbsenceType_Key"].tolist()
                ),
                "Startdatum": start,
                "Einddatum": end,
                "Duur_dagen": duration
            }
        )
