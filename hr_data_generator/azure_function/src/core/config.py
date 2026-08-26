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
        self.ploegendienst_assignment = data.get("ploegendienst_assignment", {})

        self.dim_location = data["dim_location"]
        self.dim_hire_source = data["dim_hire_source"]
        self.dim_recruitment_status = data.get("dim_recruitment_status", [])
        self.dim_recruitment_stage = data.get("dim_recruitment_stage", [])
        self.dim_decline_reason = data.get("dim_decline_reason", [])
        self.dim_rejection_reason = data.get("dim_rejection_reason", [])
        self.dim_education = data["dim_education"]
        self.dim_event_type = data["dim_event_type"]
        self.dim_absence_type = data["dim_absence_type"]
        self.dim_incident_type = data.get("dim_incident_type", [])
        self.dim_satisfaction_band = data["dim_satisfaction_band"]
        self.dim_satisfaction_driver = data.get("dim_satisfaction_driver", [])
        self.dim_engagement_band = data["dim_engagement_band"]
        self.dim_performance_driver = data.get("dim_performance_driver", [])
        self.dim_engagement_driver = data.get("dim_engagement_driver", [])
        self.dim_candidate_quality_driver = data.get(
            "dim_candidate_quality_driver", []
        )
        self.dim_salary_band = data["dim_salary_band"]
        self.dim_salary_scale = data["dim_salary_scale"]
        self.dim_shift = data["dim_shift"]

        self.education_distribution_by_role = data.get(
            "education_distribution_by_role", {}
        )
        self.role_career_paths = data.get("role_career_paths", {})

        self.contract_hours_distribution = data.get(
            "contract_hours_distribution", {}
        )

        self.structure = data["structure"]
        self.department_relocation = data.get("department_relocation", {})
        self.baseline_headcount = data["baseline_headcount"]
        self.staffing = data.get("staffing", {})
        self.workforce_planning = data.get("workforce_planning", {})
        self.initial_population = data.get("initial_population", {})

        self.schema = data["schema"]
        self.database = data.get("database")
        self.start_year_simulation = data["start_year_simulation"]
        self.dim_departure_reason = data["dim_departure_reason"]
        self.absence = data["absence"]
        self.safety = data.get("safety", {})
        self.attrition = data.get("attrition", {})
        self.retirement = data.get("retirement", {})
        self.growth = data.get("growth", {})
        self.career_events = data.get("career_events", {})
        self.satisfaction = data.get("satisfaction", {})
        self.engagement = data.get("engagement", {})
        self.workforce = data.get("workforce", {})
        self.salary_benchmark = data.get("salary_benchmark", {})
        self.recruitment = data.get("recruitment", {})
        self.avatar = data.get("avatar", {})

    def get(self, key, default=None):
        return getattr(self, key, default)

    def __getitem__(self, key):
        return self._data[key]

    def __contains__(self, key):
        return key in self._data
