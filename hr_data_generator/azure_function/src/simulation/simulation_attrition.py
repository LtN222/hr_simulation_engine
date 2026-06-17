import math


class AttritionSimulator:

    def __init__(self, config, rng, event_type_map, reden_vertrek_map):
        self.config = config
        self.rng = rng
        self.event_type_map = event_type_map
        self.reden_vertrek_map = reden_vertrek_map

    # =====================================================
    # 🔹 Public API
    # =====================================================

    def run(self, state, today):

        dim_department = state["dim_department"]
        dim_role = state["dim_role"]
        dim_employee = state["dim_employee"]
        fact_employment = state["fact_employment"]

        active_employment = fact_employment[
            fact_employment["Dienstverband_status"] == "Actief"
        ]

        vertrek_cfg = self.config.dim_reden_vertrek

        # 🔥 Lookup tables (performance boost)
        role_lookup = dim_role.set_index("Role_Key")
        dept_lookup = dim_department.set_index("Department_Key")
        employee_lookup = dim_employee.set_index("Employee_Key")

        # -------------------------------------------------
        # 🔁 Cyclic pressure
        # -------------------------------------------------

        week = today.isocalendar()[1]
        cyclic_factor = 1 + 0.25 * math.sin(2 * math.pi * week / 52)

        # -------------------------------------------------
        # 💥 Shock event
        # -------------------------------------------------

        shock_multiplier = 1.0

        if self.rng.random() < 0.02:
            shock_multiplier = self.rng.uniform(1.5, 3.0)

        # -------------------------------------------------
        # 🔁 Salary data
        # -------------------------------------------------

        # Merge employee + employment om salary + role te koppelen
        salary_df = fact_employment.merge(
            dim_employee[["Employee_Key", "Salary"]],
            on="Employee_Key",
            how="left"
        )

        # Gemiddeld salaris per rol
        avg_salary_per_role = (
            salary_df.groupby("Role_Key")["Salary"]
            .mean()
            .to_dict()
        )

        # -------------------------------------------------
        # 🔄 Loop employees
        # -------------------------------------------------

        for idx, row in active_employment.iterrows():

            role = role_lookup.loc[row["Role_Key"]]
            dept = dept_lookup.loc[role["Department_Key"]]

            dept_name = dept["Department_Name"]

            # base attrition
            attrition_rate = self.config.attrition.get(dept_name, 0.05)
            weekly_attrition = attrition_rate / 52

            # -------------------------------------------------
            # 📈 Performance effect
            # -------------------------------------------------

            perf = employee_lookup.loc[row["Employee_Key"]]["Performance_Score"]

            if perf < 2.5:
                weekly_attrition *= 1.8
            elif perf > 4:
                weekly_attrition *= 0.7

            # -------------------------------------------------
            # ⏳ Tenure effect
            # -------------------------------------------------

            tenure_years = (today - row["Startdatum"]).days / 365

            if tenure_years < 1:
                weekly_attrition *= 1.5
            elif tenure_years > 10:
                weekly_attrition *= 0.7

            # -------------------------------------------------
            #  Salary effect
            # -------------------------------------------------

            employee = employee_lookup.loc[row["Employee_Key"]]
            salary = employee["Salary"]

            role_key = row["Role_Key"]
            avg_salary = avg_salary_per_role.get(role_key, salary)  # fallback

            salary_ratio = salary / avg_salary if avg_salary > 0 else 1

            if salary_ratio < 0.85:
                weekly_attrition *= 1.4
            elif salary_ratio < 0.95:
                weekly_attrition *= 1.15
            elif salary_ratio > 1.15:
                weekly_attrition *= 0.85

            elif reden == "Hoger salaris":
                if salary_ratio < 0.9:
                    weights.append(0.25)
                elif salary_ratio < 1.0:
                    weights.append(0.15)
                else:
                    weights.append(0.05)

            if perf > 4 and salary_ratio < 0.95:
                weekly_attrition *= 1.2

            # nieuwe medewerker verdient bijna hetzelfde als senior
            if tenure_years > 5 and salary_ratio < 1.2:
                weekly_attrition *= 1.2

            # -------------------------------------------------
            # 🌊 Apply cyclic + shock
            # -------------------------------------------------

            weekly_attrition *= cyclic_factor * shock_multiplier

            # -------------------------------------------------
            # 🎯 Check exit
            # -------------------------------------------------

            if self.rng.random() >= weekly_attrition:
                continue

            # -------------------------------------------------
            # 🚪 EXIT EVENT
            # -------------------------------------------------

            fact_employment.loc[idx, "Dienstverband_status"] = "Uit dienst"
            fact_employment.loc[idx, "Einddatum"] = today

            state["vacancies"] = state.get("vacancies", 0) + 1

            # -------------------------------------------------
            # 🧠 Categorie bepalen
            # -------------------------------------------------

            if perf < 2.5:
                categorie = "werkgever"
            elif tenure_years < 1:
                categorie = self.rng.choices(
                    ["vrijwillig", "werkgever"],
                    weights=[0.8, 0.2]
                )[0]
            else:
                categorie = self.rng.choices(
                    ["vrijwillig", "werkgever"],
                    weights=[0.75, 0.25]
                )[0]

            # -------------------------------------------------
            # 🎲 Reden kiezen
            # -------------------------------------------------

            redenen = vertrek_cfg[categorie]

            weights = []

            for reden in redenen:

                if reden == "No-show":
                    weights.append(0.02)

                elif reden == "Medisch":
                    weights.append(0.05)

                elif reden == "Pensioen":
                    if tenure_years > 15:
                        weights.append(0.15)
                    else:
                        weights.append(0.01)

                elif reden == "Disfunctioneren":
                    weights.append(0.3 if perf < 2.5 else 0.05)

                elif reden == "Ontslag":
                    weights.append(0.2)

                elif reden == "Contract niet verlengd":
                    # 🔥 FIX: categorie bestaat niet → gebruik tenure
                    weights.append(0.25 if tenure_years < 2 else 0.05)

                else:
                    weights.append(1.0)

            # normaliseren
            total = sum(weights)
            weights = [w / total for w in weights]

            reden = self.rng.choices(redenen, weights=weights)[0]

            fact_employment.loc[idx, "RedenVertrek_Key"] = self.reden_vertrek_map[reden]
            fact_employment.loc[idx, "EventType_Key"] = self.event_type_map["Uit dienst"]

        state["fact_employment"] = fact_employment

        return state