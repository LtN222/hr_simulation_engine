import random

import pandas as pd

from src.simulation.simulation_contracts import ContractLifecycleSimulator

EVENT_TYPE_MAP = {
    "Uit dienst": 1,
    "Contract verlengd": 2,
    "Contract omgezet naar vast": 3,
}
DEPARTURE_REASON_MAP = {"Contract niet verlengd": 1}


class ForcedChoice(random.Random):
    """Forces rng.choices(...) to always return a fixed outcome, regardless
    of the weights passed in - used to deterministically test one specific
    branch's mechanics rather than relying on probability."""

    def __init__(self, forced_value):
        super().__init__()
        self.forced_value = forced_value

    def choices(self, population, weights=None, k=1, cum_weights=None):
        return [self.forced_value] * k


def _config(**overrides):
    base = {
        "career_events": {
            "chain_rule": {
                "max_contract_rounds": 3,
                "max_temporary_years": 3.0,
                "renewal_duration_years": 1.0,
                "top_performer_percentile": 0.90,
                "top_performer_conversion_kans": 0.6,
            },
            "contract_change_rate": 0.03,
        },
        "contract_rules": {
            "default": {"keten_conversion_kans": 0.6},
        },
        "satisfaction": {},
        "engagement": {},
    }
    base.update(overrides)
    return type("Config", (), base)()


def _base_state(
    contract_einddatum,
    contract_ronde=1,
    hire_date=pd.Timestamp("2023-01-01"),
    row_startdatum=None,
    performance=3.5,
    contracttype="Tijdelijk",
    employee_key=1,
):
    return {
        "dim_employee": pd.DataFrame({
            "Employee_Key": [employee_key],
            "Prestatie_Score": [performance],
            "Aaneengesloten_Indienst_Datum": [hire_date],
            "In_Dienst": [True],
            "Manager_Key": [None],
        }),
        "fact_employment": pd.DataFrame({
            "Employment_Key": [1],
            "Employee_Key": [employee_key],
            "Role_Key": [1],
            "Location_Key": [None],
            "Shift_Key": [None],
            "SalaryScale_Key": [1],
            "Streef_Compa_Ratio": [1.0],
            "Relevante_Ervaring_Jaren_Bij_Start": [0.0],
            "Startdatum": [row_startdatum or hire_date],
            "Einddatum": [None],
            "Dienstverband_status": ["Actief"],
            "Salaris": [40000],
            "Contracttype": [contracttype],
            "Contracturen": [40],
            "Contract_einddatum": [contract_einddatum],
            "Contract_ronde": [contract_ronde],
            "HireSource_Key": [None],
        }),
        "dim_role": pd.DataFrame({
            "Role_Key": [1], "Department_Key": [1], "Functie_Naam": ["Operator A"],
        }),
        "dim_department": pd.DataFrame({
            "Department_Key": [1], "Afdeling_Naam": ["Productie"],
        }),
        "dim_satisfaction_band": pd.DataFrame({
            "SatisfactionBand_Key": [1], "Tevredenheidsband_Naam": ["Neutraal"],
            "Minimum_Score": [0], "Maximum_Score": [10],
        }),
        "dim_engagement_band": pd.DataFrame({
            "EngagementBand_Key": [1], "Betrokkenheidsband_Naam": ["Neutraal"],
            "Minimum_Score": [0], "Maximum_Score": [10],
        }),
    }


def test_renewal_increments_contract_round_and_extends_einddatum():
    config = _config()
    state = _base_state(contract_einddatum=pd.Timestamp("2024-01-01"), contract_ronde=1)
    simulator = ContractLifecycleSimulator(
        config, schema=None, rng=ForcedChoice("renew"),
        event_type_map=EVENT_TYPE_MAP, departure_reason_map=DEPARTURE_REASON_MAP,
    )

    state = simulator.run(state, pd.Timestamp("2024-01-01"))

    employment = state["fact_employment"]
    old_row = employment[employment["Employment_Key"] == 1].iloc[0]
    new_row = employment[employment["Dienstverband_status"] == "Actief"].iloc[0]

    assert old_row["Dienstverband_status"] == "Inactief"
    assert new_row["Contracttype"] == "Tijdelijk"
    assert new_row["Contract_ronde"] == 2
    days_extended = (new_row["Contract_einddatum"] - pd.Timestamp("2024-01-01")).days
    assert 360 <= days_extended <= 370  # ~1 year, per renewal_duration_years
    assert new_row["EventType_Key"] == EVENT_TYPE_MAP["Contract verlengd"]
    assert new_row["Previous_Employment_Key"] == 1


def test_conversion_clears_contract_round_and_sets_vast():
    config = _config()
    state = _base_state(contract_einddatum=pd.Timestamp("2024-01-01"), contract_ronde=1)
    simulator = ContractLifecycleSimulator(
        config, schema=None, rng=ForcedChoice("convert"),
        event_type_map=EVENT_TYPE_MAP, departure_reason_map=DEPARTURE_REASON_MAP,
    )

    state = simulator.run(state, pd.Timestamp("2024-01-01"))

    new_row = state["fact_employment"][
        state["fact_employment"]["Dienstverband_status"] == "Actief"
    ].iloc[0]

    assert new_row["Contracttype"] == "Vast"
    assert pd.isna(new_row["Contract_ronde"])
    assert pd.isna(new_row["Contract_einddatum"])
    assert new_row["EventType_Key"] == EVENT_TYPE_MAP["Contract omgezet naar vast"]


def test_non_renewal_creates_a_departure_via_the_shared_terminal_row():
    config = _config()
    state = _base_state(contract_einddatum=pd.Timestamp("2024-01-01"), contract_ronde=1)
    simulator = ContractLifecycleSimulator(
        config, schema=None, rng=ForcedChoice("depart"),
        event_type_map=EVENT_TYPE_MAP, departure_reason_map=DEPARTURE_REASON_MAP,
    )

    state = simulator.run(state, pd.Timestamp("2024-01-01"))

    employment = state["fact_employment"]
    assert len(employment) == 2
    terminal = employment[employment["Dienstverband_status"] == "Uit dienst"].iloc[0]
    assert terminal["Startdatum"] == terminal["Einddatum"] == pd.Timestamp("2024-01-01")
    assert terminal["EventType_Key"] == EVENT_TYPE_MAP["Uit dienst"]
    assert terminal["DepartureReason_Key"] == DEPARTURE_REASON_MAP["Contract niet verlengd"]
    assert terminal["Previous_Employment_Key"] == 1

    employee = state["dim_employee"].iloc[0]
    assert not employee["In_Dienst"]
    assert employee["Datum_uitdienst"] == pd.Timestamp("2024-01-01")


def test_cap_reached_by_contract_round_never_renews():
    config = _config()
    state = _base_state(contract_einddatum=pd.Timestamp("2024-01-01"), contract_ronde=3)

    for seed in range(30):
        trial_state = {key: value.copy() for key, value in state.items()}
        simulator = ContractLifecycleSimulator(
            config, schema=None, rng=random.Random(seed),
            event_type_map=EVENT_TYPE_MAP, departure_reason_map=DEPARTURE_REASON_MAP,
        )
        result = simulator.run(trial_state, pd.Timestamp("2024-01-01"))
        active_rows = result["fact_employment"][
            result["fact_employment"]["Dienstverband_status"] == "Actief"
        ]
        if not active_rows.empty:
            # Only a conversion may still be "Actief" at the cap - never
            # another Tijdelijk round.
            assert active_rows.iloc[0]["Contracttype"] == "Vast"


def test_cap_reached_by_temporary_years_even_with_a_low_contract_round():
    """The 3-contracts-OR-3-years rule: an employee can hit the cap on
    cumulative tenure alone, even on their first or second round."""
    config = _config()
    state = _base_state(
        contract_einddatum=pd.Timestamp("2024-01-01"),
        contract_ronde=1,
        hire_date=pd.Timestamp("2020-01-01"),  # 4 years of continuous tenure
    )

    for seed in range(30):
        trial_state = {key: value.copy() for key, value in state.items()}
        simulator = ContractLifecycleSimulator(
            config, schema=None, rng=random.Random(seed),
            event_type_map=EVENT_TYPE_MAP, departure_reason_map=DEPARTURE_REASON_MAP,
        )
        result = simulator.run(trial_state, pd.Timestamp("2024-01-01"))
        active_rows = result["fact_employment"][
            result["fact_employment"]["Dienstverband_status"] == "Actief"
        ]
        if not active_rows.empty:
            assert active_rows.iloc[0]["Contracttype"] == "Vast"


def test_uses_continuous_tenure_not_the_current_rows_reset_startdatum():
    """A promotion/salary review resets the active row's own Startdatum, but
    must not reset the ketenregeling clock - it must use
    Aaneengesloten_Indienst_Datum (true continuous tenure) instead."""
    config = _config()
    state = _base_state(
        contract_einddatum=pd.Timestamp("2024-01-01"),
        contract_ronde=1,
        hire_date=pd.Timestamp("2020-01-01"),  # true tenure: 4 years, over the cap
        row_startdatum=pd.Timestamp("2023-11-01"),  # this row reset 2 months ago
    )

    for seed in range(30):
        trial_state = {key: value.copy() for key, value in state.items()}
        simulator = ContractLifecycleSimulator(
            config, schema=None, rng=random.Random(seed),
            event_type_map=EVENT_TYPE_MAP, departure_reason_map=DEPARTURE_REASON_MAP,
        )
        result = simulator.run(trial_state, pd.Timestamp("2024-01-01"))
        active_rows = result["fact_employment"][
            result["fact_employment"]["Dienstverband_status"] == "Actief"
        ]
        if not active_rows.empty:
            assert active_rows.iloc[0]["Contracttype"] == "Vast"


def test_ignores_a_vast_contract_and_a_not_yet_due_tijdelijk_contract():
    config = _config()

    vast_state = _base_state(contract_einddatum=None, contracttype="Vast")
    not_due_state = _base_state(contract_einddatum=pd.Timestamp("2030-01-01"))

    for state in (vast_state, not_due_state):
        simulator = ContractLifecycleSimulator(
            config, schema=None, rng=ForcedChoice("convert"),
            event_type_map=EVENT_TYPE_MAP, departure_reason_map=DEPARTURE_REASON_MAP,
        )
        result = simulator.run(state, pd.Timestamp("2024-01-01"))
        assert len(result["fact_employment"]) == 1
        assert result["fact_employment"].iloc[0]["Dienstverband_status"] == "Actief"


def test_top_performers_convert_early_far_more_often_than_average_performers():
    """The pre-cap early-conversion decision must actually track live
    performance, not just apply a flat random chance regardless of it."""
    config = _config()

    def _convert_rate(performance, trials=300):
        conversions = 0
        for seed in range(trials):
            state = _base_state(
                contract_einddatum=pd.Timestamp("2024-01-01"),
                contract_ronde=1,
                performance=performance,
            )
            # A large peer population sets a stable top-10% bar; the
            # candidate being decided is deliberately excluded from it so
            # their own score can't shift their own threshold.
            # A realistic spread (not all identical) so the 90th percentile
            # actually sits meaningfully above the "average" test case - an
            # all-identical peer population would make every candidate look
            # like a top performer by definition, regardless of their score.
            peer_scores = [2.8 + 0.035 * i for i in range(50)]  # spreads ~2.8-4.5
            peers = pd.DataFrame({
                "Employee_Key": range(2, 52),
                "Prestatie_Score": peer_scores,
                "Aaneengesloten_Indienst_Datum": [pd.Timestamp("2023-01-01")] * 50,
                "In_Dienst": [True] * 50,
                "Manager_Key": [None] * 50,
            })
            state["dim_employee"] = pd.concat(
                [state["dim_employee"], peers], ignore_index=True
            )
            peer_employment = pd.DataFrame({
                "Employment_Key": range(2, 52),
                "Employee_Key": range(2, 52),
                "Role_Key": [1] * 50,
                "Location_Key": [None] * 50,
                "Shift_Key": [None] * 50,
                "SalaryScale_Key": [1] * 50,
                "Streef_Compa_Ratio": [1.0] * 50,
                "Relevante_Ervaring_Jaren_Bij_Start": [0.0] * 50,
                "Startdatum": [pd.Timestamp("2023-01-01")] * 50,
                "Einddatum": [None] * 50,
                "Dienstverband_status": ["Actief"] * 50,
                "Salaris": [40000] * 50,
                "Contracttype": ["Vast"] * 50,
                "Contracturen": [40] * 50,
                "Contract_einddatum": [None] * 50,
                "Contract_ronde": [None] * 50,
                "HireSource_Key": [None] * 50,
            })
            state["fact_employment"] = pd.concat(
                [state["fact_employment"], peer_employment], ignore_index=True
            )

            simulator = ContractLifecycleSimulator(
                config, schema=None, rng=random.Random(seed),
                event_type_map=EVENT_TYPE_MAP, departure_reason_map=DEPARTURE_REASON_MAP,
            )
            result = simulator.run(state, pd.Timestamp("2024-01-01"))
            row = result["fact_employment"][
                (result["fact_employment"]["Employee_Key"] == 1)
                & (result["fact_employment"]["Dienstverband_status"] == "Actief")
            ]
            if not row.empty and row.iloc[0]["Contracttype"] == "Vast":
                conversions += 1
        return conversions / trials

    average_performer_rate = _convert_rate(performance=3.5)
    top_performer_rate = _convert_rate(performance=5.0)  # comfortably above a 3.5-peer p90

    assert average_performer_rate < 0.10
    assert top_performer_rate > 0.40
    assert top_performer_rate > average_performer_rate * 3
