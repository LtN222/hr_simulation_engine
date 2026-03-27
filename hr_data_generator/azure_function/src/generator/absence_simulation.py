import pandas as pd

from src.generator.record_builder import build_record

def generate_absence_history(state, config, schema, rng, today):

    dim_employee = state["dim_employee"]
    fact_employment = state["fact_employment"]
    fact_employment_attribute = state["fact_employment_attribute"]
    dim_absence_type = state["dim_absence_type"]

    absence_cfg = config["absence"]

    base_probability = absence_cfg["base_probability"]
    age_cfg = absence_cfg["age_multipliers"]
    attr_cfg = absence_cfg["attribute_multipliers"]
    duration_cfg = absence_cfg["duration_distribution"]

    durations = list(duration_cfg.keys())
    duration_weights = list(duration_cfg.values())

    records = []
    absence_key = 1

    for _, emp in dim_employee.iterrows():

        leeftijd = emp["Leeftijd"]

        if leeftijd < 30:
            age_factor = age_cfg["<30"]
        elif leeftijd < 45:
            age_factor = age_cfg["30-45"]
        elif leeftijd < 55:
            age_factor = age_cfg["45-55"]
        else:
            age_factor = age_cfg["55+"]

        attr_factor = 1.0

        employment_row = fact_employment.loc[
            fact_employment["Employee_Key"] == emp["Employee_Key"]
        ].iloc[0]

        emp_attrs = fact_employment_attribute[
            fact_employment_attribute["Employment_Key"]
            == employment_row["Employment_Key"]
        ]

        for attr_name, values in attr_cfg.items():

            value_row = emp_attrs[
                emp_attrs["Attribute_Name"] == attr_name
            ]

            if len(value_row) == 0:
                continue

            value = value_row.iloc[0]["Attribute_Value"]

            attr_factor *= values.get(value, 1.0)

        probability = base_probability * age_factor * attr_factor

        events = rng.choices(
            [0, 1, 2],
            weights=[
                1 - probability,
                probability * 0.8,
                probability * 0.2
            ]
        )[0]

        for _ in range(events):

            start = today - pd.DateOffset(
                days=rng.randint(0, 365)
            )

            duration = int(
                rng.choices(
                    durations,
                    weights=duration_weights
                )[0]
            )

            end = start + pd.DateOffset(days=duration)

            records.append(

                build_record(
                    schema,
                    "fact_absence",
                    {
                        "Absence_Key": absence_key,
                        "Employee_Key": emp["Employee_Key"],
                        "AbsenceType_Key": rng.choice(
                            dim_absence_type["AbsenceType_Key"].tolist()
                        ),
                        "Startdatum": start,
                        "Einddatum": end,
                        "Duur_dagen": duration
                    }
                )

            )

            absence_key += 1

    state["fact_absence"] = pd.DataFrame(records)

    return state