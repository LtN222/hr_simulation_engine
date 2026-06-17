class Config:
    def __init__(self, data: dict):
        self._data = data

        # 🔥 direct mappen naar attributen
        self.sector = data["sector"]
        self.simulation_weeks = data["simulation_weeks"]
        self.simulation_seed = data["simulation_seed"]
        self.simulation_mode = data["simulation_mode"]

        self.contract_rules = data["contract_rules"]
        self.special_arrangements = data.get("special_arrangements", {})
        self.employment_attributes = data.get("employment_attributes", {})

        self.dim_location = data["dim_location"]
        self.dim_hire_source = data["dim_hire_source"]
        self.dim_education_level = data["dim_education_level"]
        self.dim_event_type = data["dim_event_type"]
        self.dim_absence_type = data["dim_absence_type"]

        self.education_distribution_by_role = data.get(
            "education_distribution_by_role", {}
        )

        self.contract_hours_distribution = data.get(
            "contract_hours_distribution", {}
        )

        self.structure = data["structure"]
        self.baseline_headcount = data["baseline_headcount"]

        self.schema = data["schema"]
        self.database = data.get("database")
        self.start_year_simulation = data["start_year_simulation"]
        self.dim_reden_vertrek = data["dim_reden_vertrek"]
        self.absence = data["absence"]
        self.attrition = data.get("attrition", {})
        self.growth = data.get("growth", {})
        self.career_events = data.get("career_events", {})
        self.recruitment = data.get("recruitment", {})

    def get(self, key, default=None):
        return getattr(self, key, default)

    def __getitem__(self, key):
        return self._data[key]

    def __contains__(self, key):
        return key in self._data
