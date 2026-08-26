import pandas as pd
from src.infrastructure.role_eligibility import (
    eligible_internal,
    external_rejection_reason,
    LEVELS,
)

from src.infrastructure.record_builder import build_record

NOT_SELECTED_REASON = "Andere kandidaat gekozen"
BELOW_MINIMUM_QUALITY_REASON = "Kwaliteit onder minimumniveau"


def _numeric(value, default=0.0):
    """Coerce a role/profile field to a float, guarding NaN and missing values."""
    value = pd.to_numeric(value, errors="coerce")
    return default if pd.isna(value) else float(value)


class RecruitmentSimulator:
    """Simulate a source-aware, multi-stage recruitment funnel for open vacancies.

    Each application is a single `fact_recruitment` row that genuinely
    persists and gets updated in place across real simulated weeks as it
    moves through stages: Sollicitatie -> Screening -> Gesprek -> Aanbod ->
    a terminal outcome (Aangenomen / Afgewezen / Geweigerd). Screening and
    interview outcomes are causal (driven by the same eligibility/quality
    checks used elsewhere), not independently sampled; only the *timing* of
    each stage's resolution is probabilistic. Internal mobility uses the
    same fact and skips straight to Gesprek, since `eligible_internal` has
    already screened it - but still competes for the same single Aanbod
    slot per vacancy as any external candidate.
    """

    ACCEPTED_STATUS = "Aangenomen"
    REJECTED_STATUS = "Afgewezen"
    DECLINED_STATUS = "Geweigerd"
    IN_PROGRESS_STATUS = "In behandeling"

    STAGE_SOLLICITATIE = "Sollicitatie"
    STAGE_SCREENING = "Screening"
    STAGE_GESPREK = "Gesprek"
    STAGE_AANBOD = "Aanbod"

    def __init__(self, config, schema, rng):
        self.config = config
        self.schema = schema
        self.rng = rng
        self.recruitment_cfg = config.recruitment
        self._status_keys = {}
        self._stage_keys = {}
        self._decline_reason_keys = {}
        self._rejection_reason_keys = {}
        self._hire_source_names = {}

    def run(self, state, today):
        self._status_keys = self._build_reason_lookup(
            state, "dim_recruitment_status", "Status_Name", "RecruitmentStatus_Key"
        )
        self._stage_keys = self._build_reason_lookup(
            state, "dim_recruitment_stage", "Stage_Name", "Stage_Key"
        )
        self._decline_reason_keys = self._build_reason_lookup(
            state, "dim_decline_reason", "DeclineReason_Name", "DeclineReason_Key"
        )
        self._rejection_reason_keys = self._build_reason_lookup(
            state, "dim_rejection_reason", "RejectionReason_Name", "RejectionReason_Key"
        )
        self._hire_source_names = self._build_reason_lookup(
            state, "dim_hire_source", "HireSource_Key", "HireSource_Name"
        )

        if "fact_recruitment" not in state:
            state["fact_recruitment"] = pd.DataFrame()
        state.setdefault("_recruitment_pipeline_profiles", {})

        fact_recruitment = state["fact_recruitment"]
        next_key = (
            int(fact_recruitment["Recruitment_Key"].max()) + 1
            if not fact_recruitment.empty and "Recruitment_Key" in fact_recruitment.columns
            else 1
        )
        reserved_internal_employees = self._reserved_internal_employees(fact_recruitment)
        accepted_applications = []

        for _, vacancy in self._open_vacancies(state).iterrows():
            department_name = self._department_name(vacancy["Department_Key"], state)
            target_role = self._role_row(state, vacancy["Role_Key"])

            next_key = self._generate_new_applications(
                state, vacancy, target_role, department_name, today,
                reserved_internal_employees, next_key,
            )
            self._resolve_screening(state, vacancy, target_role, today)
            self._resolve_interview(state, vacancy, today)
            accepted = self._resolve_offer(state, vacancy, today)
            if accepted is not None:
                accepted_applications.append(accepted)
                self._close_out_remaining_pipeline(state, vacancy["Vacancy_Key"], today)

        state["_accepted_applications"] = accepted_applications
        return state

    # ------------------------------------------------------------------
    # Weekly stage machine
    # ------------------------------------------------------------------

    def _open_vacancies(self, state):
        vacancy = state.get("fact_vacancy", pd.DataFrame())
        if vacancy.empty or "Status" not in vacancy.columns:
            return vacancy
        return vacancy[vacancy["Status"] == "Open"]

    def _reserved_internal_employees(self, fact_recruitment):
        if fact_recruitment.empty or "Status" not in fact_recruitment.columns:
            return set()
        in_progress = fact_recruitment[fact_recruitment["Status"] == self.IN_PROGRESS_STATUS]
        return set(int(key) for key in in_progress["Employee_Key"].dropna())

    def _pipeline(self, state, vacancy_key):
        fact_recruitment = state["fact_recruitment"]
        if fact_recruitment.empty:
            return fact_recruitment
        return fact_recruitment[
            (fact_recruitment["Vacancy_Key"] == vacancy_key)
            & (fact_recruitment["Status"] == self.IN_PROGRESS_STATUS)
        ]

    def _generate_new_applications(
        self, state, vacancy, target_role, department_name, today,
        reserved_internal_employees, next_key,
    ):
        pipeline_profiles = state["_recruitment_pipeline_profiles"]
        average = float(
            self.recruitment_cfg.get("weekly_applications_by_department", {})
            .get(department_name, 1.0)
        )
        count = max(0, int(self.rng.normalvariate(average, max(0.1, average ** 0.5))))
        new_records = []

        for _ in range(count):
            source, employee_key, candidate_profile = self._choose_source(
                state, vacancy, target_role, department_name, reserved_internal_employees
            )
            if source is None:
                continue

            is_internal = self._is_internal_source(source)
            stage_name = self.STAGE_GESPREK if is_internal else self.STAGE_SOLLICITATIE
            new_records.append(self._new_pipeline_application(
                next_key, vacancy, today, source, employee_key, candidate_profile, stage_name
            ))
            if is_internal:
                reserved_internal_employees.add(employee_key)
            else:
                pipeline_profiles[next_key] = {
                    "Education_Key": candidate_profile.get("Education_Key"),
                    "Relevante_Ervaring_Jaren": candidate_profile.get("Relevante_Ervaring_Jaren"),
                    "Leidinggevende_Ervaring_Jaren": candidate_profile.get(
                        "Leidinggevende_Ervaring_Jaren"
                    ),
                    "Qualifications": candidate_profile.get("Qualifications", []),
                }
            next_key += 1

        if new_records:
            state["fact_recruitment"] = pd.concat(
                [state["fact_recruitment"], pd.DataFrame(new_records)],
                ignore_index=True,
            )
        return next_key

    def _resolve_screening(self, state, vacancy, target_role, today):
        pipeline_profiles = state["_recruitment_pipeline_profiles"]
        pending = self._pipeline(state, vacancy["Vacancy_Key"])
        if pending.empty:
            return
        pending = pending[pending["Stage_Key"] == self._stage_keys.get(self.STAGE_SOLLICITATIE)]
        if pending.empty:
            return

        rate = float(self.recruitment_cfg.get("screening_decision_rate", 0.6))
        for idx, row in pending.iterrows():
            if self.rng.random() >= rate:
                continue
            profile = pipeline_profiles.get(int(row["Recruitment_Key"]), {})
            reason = external_rejection_reason(self.config, target_role, profile)
            if reason is not None:
                self._finalize(
                    state, idx, self.REJECTED_STATUS, today,
                    rejection_reason=reason, date_columns=["Screening_Date"],
                )
            else:
                self._advance_to_stage(
                    state, idx, self.STAGE_GESPREK, date_columns=["Screening_Date"], today=today
                )

    def _resolve_interview(self, state, vacancy, today):
        vacancy_key = vacancy["Vacancy_Key"]
        pipeline = self._pipeline(state, vacancy_key)
        if pipeline.empty:
            return
        aanbod_key = self._stage_keys.get(self.STAGE_AANBOD)
        if (pipeline["Stage_Key"] == aanbod_key).any():
            # One offer already outstanding for this vacancy - nobody else
            # gets promoted (or even evaluated) until it resolves.
            return

        gesprek_key = self._stage_keys.get(self.STAGE_GESPREK)
        waiting = pipeline[pipeline["Stage_Key"] == gesprek_key]
        if waiting.empty:
            return

        # Longest-waiting-first: entry into Gesprek is Screening_Date for an
        # externally-screened candidate, or Application_Date for an
        # internal candidate who skipped straight there.
        entered_gesprek = waiting["Screening_Date"].fillna(waiting["Application_Date"])
        idx = entered_gesprek.sort_values().index[0]
        row = state["fact_recruitment"].loc[idx]

        rate = float(self.recruitment_cfg.get("interview_decision_rate", 0.3))
        if self.rng.random() >= rate:
            return

        source_name = self._hire_source_names.get(row["HireSource_Key"])
        minimum_quality = float(
            self._source_profile_by_name(source_name).get("minimum_offer_quality", 1.0)
        )
        if float(row["Candidate_Quality"]) < minimum_quality:
            self._finalize(
                state, idx, self.REJECTED_STATUS, today,
                rejection_reason=BELOW_MINIMUM_QUALITY_REASON, date_columns=["Interview_Date"],
            )
            return

        self._advance_to_stage(
            state, idx, self.STAGE_AANBOD,
            date_columns=["Interview_Date", "Offer_Date"], today=today,
        )
        decision_cfg = self.recruitment_cfg.get("decision_days", {})
        days_to_decision = self.rng.randint(
            decision_cfg.get("min", 3), decision_cfg.get("max", 28)
        )
        state["fact_recruitment"].loc[idx, "Days_To_Decision"] = days_to_decision

    def _resolve_offer(self, state, vacancy, today):
        pipeline = self._pipeline(state, vacancy["Vacancy_Key"])
        if pipeline.empty:
            return None
        pipeline = pipeline[pipeline["Stage_Key"] == self._stage_keys.get(self.STAGE_AANBOD)]
        if pipeline.empty:
            return None

        idx = pipeline.index[0]
        row = state["fact_recruitment"].loc[idx]
        days_to_decision = row.get("Days_To_Decision")
        if pd.isna(days_to_decision):
            return None
        offer_date = pd.Timestamp(row["Offer_Date"])
        if pd.Timestamp(today) < offer_date + pd.Timedelta(days=int(days_to_decision)):
            return None

        source_name = self._hire_source_names.get(row["HireSource_Key"])
        profile = self._source_profile_by_name(source_name)
        candidate_quality = float(row["Candidate_Quality"])
        decline_rate = float(profile.get("candidate_decline_rate", 0.0))
        # Strong candidates generally have more alternatives. The effect is
        # deliberately small so a good score still increases the hire chance.
        decline_rate += max(0.0, candidate_quality - 3.0) * float(
            profile.get("candidate_decline_per_quality_point", 0.0)
        )
        decline_rate = min(0.75, max(0.0, decline_rate))

        if self.rng.random() < decline_rate:
            self._finalize(
                state, idx, self.DECLINED_STATUS, today,
                decline_reason=self._sample_decline_reason(candidate_quality),
            )
            return None

        recruitment_key = int(row["Recruitment_Key"])
        pipeline_profile = state["_recruitment_pipeline_profiles"].get(recruitment_key, {})
        accepted = {
            "Recruitment_Key": recruitment_key,
            "Vacancy_Key": row["Vacancy_Key"],
            "Role_Key": row["Role_Key"],
            "Department_Key": row["Department_Key"],
            "HireSource_Key": row["HireSource_Key"],
            "Vacancy_Reason": row["Vacancy_Reason"],
            "Employee_Key": row["Employee_Key"],
            "Candidate_Quality": row["Candidate_Quality"],
            "Education_Key": pipeline_profile.get("Education_Key"),
            "Relevante_Ervaring_Jaren": pipeline_profile.get("Relevante_Ervaring_Jaren"),
            "Is_Internal_Mobility": pd.notna(row["Employee_Key"]),
        }
        self._finalize(state, idx, self.ACCEPTED_STATUS, today)
        return accepted

    def _close_out_remaining_pipeline(self, state, vacancy_key, today):
        pipeline = self._pipeline(state, vacancy_key)
        for idx in pipeline.index:
            self._finalize(
                state, idx, self.REJECTED_STATUS, today, rejection_reason=NOT_SELECTED_REASON
            )

    def _advance_to_stage(self, state, idx, stage_name, date_columns, today):
        fact_recruitment = state["fact_recruitment"]
        fact_recruitment.loc[idx, "Stage_Key"] = self._stage_keys.get(stage_name)
        for column in date_columns:
            fact_recruitment.loc[idx, column] = today

    def _finalize(self, state, idx, status, today, decline_reason=None, rejection_reason=None, date_columns=()):
        fact_recruitment = state["fact_recruitment"]
        for column in date_columns:
            fact_recruitment.loc[idx, column] = today
        fact_recruitment.loc[idx, "Decision_Date"] = today
        fact_recruitment.loc[idx, "Status"] = status
        fact_recruitment.loc[idx, "RecruitmentStatus_Key"] = self._status_keys.get(status)
        fact_recruitment.loc[idx, "DeclineReason_Key"] = self._decline_reason_keys.get(decline_reason)
        fact_recruitment.loc[idx, "RejectionReason_Key"] = self._rejection_reason_keys.get(rejection_reason)
        recruitment_key = fact_recruitment.loc[idx, "Recruitment_Key"]
        if pd.notna(recruitment_key):
            state["_recruitment_pipeline_profiles"].pop(int(recruitment_key), None)

    # ------------------------------------------------------------------
    # Candidate sourcing and profile generation
    # ------------------------------------------------------------------

    def _new_pipeline_application(
        self, recruitment_key, vacancy, today, source, employee_key, candidate_profile, stage_name
    ):
        candidate_fields = {
            key: value for key, value in candidate_profile.items()
            if key not in {"Qualifications", "Education_Key", "Relevante_Ervaring_Jaren",
                           "Leidinggevende_Ervaring_Jaren"}
        }
        return build_record(
            self.schema,
            "fact_recruitment",
            {
                "Recruitment_Key": recruitment_key,
                "Vacancy_Key": vacancy["Vacancy_Key"],
                "Application_Date": today,
                "Decision_Date": None,
                "Role_Key": vacancy["Role_Key"],
                "Department_Key": vacancy["Department_Key"],
                "HireSource_Key": source["HireSource_Key"],
                "Status": self.IN_PROGRESS_STATUS,
                "RecruitmentStatus_Key": self._status_keys.get(self.IN_PROGRESS_STATUS),
                "Employee_Key": employee_key,
                "Vacancy_Reason": vacancy["Vacancy_Reason"],
                "Stage_Key": self._stage_keys.get(stage_name),
                "Screening_Date": None,
                "Interview_Date": today if stage_name == self.STAGE_GESPREK else None,
                "Offer_Date": None,
                "Days_To_Decision": None,
                **candidate_fields,
                "DeclineReason_Key": None,
                "RejectionReason_Key": None,
            }
        )

    def _choose_source(self, state, vacancy, target_role, department_name, reserved_internal_employees):
        candidates = []
        weights = []

        for _, source in state["dim_hire_source"].iterrows():
            internal_employee_key, internal_quality = self._internal_candidate(
                state, vacancy, source, reserved_internal_employees
            )
            if self._is_internal_source(source) and internal_employee_key is None:
                continue

            profile = self._source_profile(source)
            weight = float(profile.get("application_volume_weight", 1.0))
            weight *= float(profile.get("department_weights", {}).get(department_name, 1.0))

            candidates.append((source, internal_employee_key, internal_quality))
            weights.append(max(0.01, weight))

        if not candidates:
            return None, None, None

        source, employee_key, internal_quality = self.rng.choices(candidates, weights=weights)[0]
        profile = self._build_candidate_profile(state, source, target_role, internal_quality)
        return source, employee_key, profile

    def _build_candidate_profile(self, state, source, target_role, internal_quality):
        """Build the candidate profile that both scores and gates the funnel.

        An internal candidate already passed ``eligible_internal`` in
        ``_internal_candidate``, and their known performance is a real signal,
        so their score profile keeps using it unchanged. An external
        candidate has no such history, so their profile is built from sampled
        real attributes (experience, leadership experience, education) which
        both drive the reporting scores and gate screening via
        ``external_rejection_reason``.
        """
        if internal_quality is not None:
            return self._profile_from_quality(internal_quality, source)
        return self._external_candidate_profile(state, target_role, source)

    def _internal_candidate(self, state, vacancy, source, reserved_internal_employees):
        if not self._is_internal_source(source):
            return None, None

        employment = state.get("fact_employment", pd.DataFrame())
        employees = state.get("dim_employee", pd.DataFrame())
        roles = state.get("dim_role", pd.DataFrame())
        if employment.empty or employees.empty or roles.empty:
            return None, None

        active = employment[employment["Dienstverband_status"] == "Actief"].copy()
        target_role = roles.loc[roles["Role_Key"] == vacancy["Role_Key"]]
        if active.empty or target_role.empty:
            return None, None

        target_role = target_role.iloc[0]
        employee_scores = employees.set_index("Employee_Key")["Performance_Score"]
        active["Performance_Score"] = active["Employee_Key"].map(employee_scores)
        eligible = active[
            ~active["Employee_Key"].isin(reserved_internal_employees)
        ].copy()
        role_lookup = roles.set_index("Role_Key")
        eligible = eligible[eligible.apply(
            lambda candidate: eligible_internal(
                self.config, state, int(candidate["Employee_Key"]),
                role_lookup.loc[candidate["Role_Key"]], target_role,
                vacancy["Created_Date"], candidate["Performance_Score"],
            ), axis=1)]
        if eligible.empty:
            return None, None

        # Known performance provides the main fit signal for an internal move.
        eligible["Selection_Weight"] = (
            eligible["Performance_Score"].fillna(2.7) - 2.3
        ).clip(lower=0.1)
        selected_index = self.rng.choices(
            list(eligible.index),
            weights=eligible["Selection_Weight"].tolist()
        )[0]
        selected = eligible.loc[selected_index]
        quality = self._clamp_quality(
            float(selected["Performance_Score"])
            + self.rng.normalvariate(0.25, 0.25)
        )
        return int(selected["Employee_Key"]), quality

    def _sample_decline_reason(self, candidate_quality):
        reasons = self.recruitment_cfg.get("decline_reasons", [])
        if not reasons:
            return None
        threshold = float(
            self.recruitment_cfg.get("decline_reason_high_quality_threshold", float("inf"))
        )
        is_high_quality = candidate_quality >= threshold
        weights = [
            float(reason.get("weight", 1.0)) + (
                float(reason.get("quality_weight_bonus", 0.0)) if is_high_quality else 0.0
            )
            for reason in reasons
        ]
        return self.rng.choices(reasons, weights=weights)[0]["name"]

    def _build_reason_lookup(self, state, table, name_column, key_column):
        rows = state.get(table, pd.DataFrame())
        if rows.empty or not {name_column, key_column}.issubset(rows.columns):
            return {}
        return dict(zip(rows[name_column], rows[key_column]))

    def _profile_from_quality(self, internal_quality, source):
        """Generate a transparent role-neutral quality profile."""
        profile = self._source_profile(source)
        baseline = internal_quality
        component_columns = {
            "Candidate_Experience_Score": "Relevante werkervaring",
            "Candidate_Education_Relevance_Score": "Relevante opleiding",
            "Candidate_Technical_Skills_Score": "Technische vaardigheden en kwalificaties",
            "Candidate_Soft_Skills_Score": "Rolrelevante soft skills",
            "Candidate_Motivation_Score": "Motivatie en voorbereiding",
        }
        weights = self.recruitment_cfg.get("candidate_quality_weights", {})
        values = {
            column: self._clamp_quality(baseline + self.rng.normalvariate(0, 0.45))
            for column in component_columns
        }
        total_weight = sum(float(weights.get(column, 1)) for column in values)
        quality = sum(
            values[column] * float(weights.get(column, 1))
            for column in values
        ) / total_weight
        driver_name = max(
            component_columns,
            key=lambda column: values[column] * float(weights.get(column, 1)),
        )
        return {
            **values,
            "Candidate_Quality": self._clamp_quality(quality),
            "CandidateQualityDriver_Key": self._driver_key(
                component_columns[driver_name]
            ),
        }

    def _external_candidate_profile(self, state, target_role, source):
        """Build an external candidate's profile from real, gate-relevant attributes.

        Relevant experience, leadership experience and education are sampled
        first. The reporting scores are then derived from those same
        attributes rather than generated independently, so a candidate that
        fails screening is also visibly the candidate with a low experience
        or education score, not an unrelated draw.
        """
        attributes = self._sample_external_candidate_attributes(state, target_role)
        profile = self._source_profile(source)
        mean = float(profile.get("candidate_quality_mean", 3.0))
        baseline = self._clamp_quality(self.rng.normalvariate(mean, 0.6))

        component_columns = {
            "Candidate_Experience_Score": self._experience_score(
                attributes["Relevante_Ervaring_Jaren"],
                _numeric(target_role.get("Min_Relevante_Ervaring_Jr"), 0.0),
            ),
            "Candidate_Education_Relevance_Score": self._education_relevance_score(
                target_role, attributes["Qualifications"]
            ),
            "Candidate_Technical_Skills_Score": self._clamp_quality(
                baseline + self.rng.normalvariate(0, 0.45)
            ),
            "Candidate_Soft_Skills_Score": self._clamp_quality(
                baseline + self.rng.normalvariate(0, 0.45)
            ),
            "Candidate_Motivation_Score": self._clamp_quality(
                baseline + self.rng.normalvariate(0, 0.45)
            ),
        }
        driver_labels = {
            "Candidate_Experience_Score": "Relevante werkervaring",
            "Candidate_Education_Relevance_Score": "Relevante opleiding",
            "Candidate_Technical_Skills_Score": "Technische vaardigheden en kwalificaties",
            "Candidate_Soft_Skills_Score": "Rolrelevante soft skills",
            "Candidate_Motivation_Score": "Motivatie en voorbereiding",
        }
        weights = self.recruitment_cfg.get("candidate_quality_weights", {})
        total_weight = sum(float(weights.get(column, 1)) for column in component_columns)
        quality = sum(
            value * float(weights.get(column, 1))
            for column, value in component_columns.items()
        ) / total_weight
        driver_name = max(
            component_columns,
            key=lambda column: component_columns[column] * float(weights.get(column, 1)),
        )
        return {
            **component_columns,
            "Candidate_Quality": self._clamp_quality(quality),
            "CandidateQualityDriver_Key": self._driver_key(
                driver_labels[driver_name]
            ),
            **attributes,
        }

    def _sample_external_candidate_attributes(self, state, target_role):
        """Sample the real attributes an external candidate is screened on.

        Attributes are centred just above the role's own requirement rather
        than on it, so a meaningful share of candidates plausibly fail
        screening instead of always clearing the bar by construction.
        """
        match_probability = float(
            self.recruitment_cfg.get("external_candidate_match_probability", 0.7)
        )
        required_experience = _numeric(target_role.get("Min_Relevante_Ervaring_Jr"), 0.0)
        experience = max(0.0, round(
            self.rng.normalvariate(required_experience + 1.0, 1.75), 2
        ))

        leadership_experience = 0.0
        if bool(target_role.get("Leidinggevend", False)):
            required_leadership = _numeric(
                target_role.get("Min_Leidinggevende_Ervaring_Jr"), 0.0
            )
            leadership_experience = max(0.0, round(
                self.rng.normalvariate(required_leadership + 0.5, 1.25), 2
            ))

        education_key, education_row = self._sample_candidate_education(
            state, target_role, match_probability
        )
        return {
            "Education_Key": education_key,
            "Relevante_Ervaring_Jaren": experience,
            "Leidinggevende_Ervaring_Jaren": leadership_experience,
            "Qualifications": [{
                "Education_Name": education_row.get("Education_Name"),
                "Education_Level": education_row.get("Education_Level"),
            }],
        }

    def _sample_candidate_education(self, state, target_role, match_probability):
        dim_education = state.get("dim_education", pd.DataFrame())
        if dim_education.empty:
            return None, {}

        required_names = set(
            getattr(self.config, "role_career_paths", {})
            .get(target_role["Role_Name"], {})
            .get("relevante_opleidingen", [])
        )
        matching = dim_education[dim_education["Education_Name"].isin(required_names)] \
            if required_names else dim_education.iloc[0:0]

        pool = (
            matching
            if not matching.empty and self.rng.random() < match_probability
            else dim_education
        )
        row = pool.sample(n=1, random_state=self.rng.randint(0, 100000)).iloc[0]
        return row["Education_Key"], row

    def _experience_score(self, experience_years, required_years):
        """Score relevant experience against the role's own requirement.

        Meeting the requirement exactly lands near the middle of the scale;
        roughly double the requirement approaches the top.
        """
        baseline = required_years if required_years > 0 else 2.0
        ratio = experience_years / baseline
        score = 1.0 + 2.0 * min(2.0, ratio)
        return self._clamp_quality(score + self.rng.normalvariate(0, 0.3))

    def _education_relevance_score(self, target_role, qualifications):
        required_names = set(
            getattr(self.config, "role_career_paths", {})
            .get(target_role["Role_Name"], {})
            .get("relevante_opleidingen", [])
        )
        min_niveau = target_role.get("Min_Opleidingsniveau", "Geen")
        min_niveau = "Geen" if pd.isna(min_niveau) else min_niveau
        min_level = LEVELS.get(min_niveau, 0)

        matches = [
            q for q in qualifications if q.get("Education_Name") in required_names
        ]
        meets_level = any(
            LEVELS.get(q.get("Education_Level"), 0) >= min_level for q in matches
        )
        baseline = 4.3 if meets_level else (3.0 if matches else 1.6)
        return self._clamp_quality(baseline + self.rng.normalvariate(0, 0.3))

    def _role_row(self, state, role_key):
        return state["dim_role"].loc[
            state["dim_role"]["Role_Key"] == role_key
        ].iloc[0]

    def _driver_key(self, name):
        drivers = getattr(self.config, "dim_candidate_quality_driver", [])
        for index, driver in enumerate(drivers, start=1):
            if driver.get("Driver_Name") == name:
                return driver.get("CandidateQualityDriver_Key", index)
        return None

    def _source_profile(self, source):
        source_name = source.get("HireSource_Name")
        return self._source_profile_by_name(source_name)

    def _source_profile_by_name(self, source_name):
        profiles = self.recruitment_cfg.get("source_profiles", {})
        return profiles.get(source_name, {})

    @staticmethod
    def _is_internal_source(source):
        flag = source.get("Is_Internal")
        if pd.notna(flag):
            return bool(flag)
        return source.get("HireSource_Name") == "Interne mobiliteit"

    def _department_name(self, department_key, state):
        return state["dim_department"].loc[
            state["dim_department"]["Department_Key"] == department_key,
            "Department_Name"
        ].iloc[0]

    @staticmethod
    def _clamp_quality(value):
        return round(max(1, min(5, value)), 2)
