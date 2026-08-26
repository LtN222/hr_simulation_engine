import pandas as pd
import numpy as np
import random
import pytest
from datetime import datetime

from src.core.config_loader import ConfigLoader
from src.infrastructure.database import write_to_sql
from src.application.employee_generation import generate_employees
from src.application.allocation import allocate_headcount
from src.infrastructure.manager_builder import assign_managers, build_dim_manager
from src.infrastructure.manager_assignment import (
    manager_as_of,
    sync_manager_assignments,
)
from src.infrastructure.dimensions import build_dim_department, build_dim_role
from src.infrastructure.dimension_factory import generate_dimensions
from src.infrastructure.employee_status import sync_employee_employment_status
from src.infrastructure.workforce_snapshot import build_workforce_snapshots
from src.infrastructure.departure_context import (
    sync_departure_satisfaction,
    sync_employment_hire_sources,
)
from src.infrastructure.absence_context import sync_absence_satisfaction
from src.infrastructure.salary_benchmark import SalaryBenchmarkBuilder
from src.infrastructure.salary_policy import SalaryPolicy
from src.infrastructure.satisfaction import SatisfactionModel
from src.infrastructure.engagement import EngagementModel
from src.infrastructure.relevant_experience import carried_experience, experience_as_of
from src.infrastructure.engagement import engagement_driver_key_for
from src.infrastructure.engagement import score_employee_engagement
from src.infrastructure.avatar import AvatarAssigner, ensure_employee_avatars
from src.run_simulation_incremental import _ensure_missing_static_dimensions
from src.generator.employment_factory import EmploymentFactory
from src.simulation.simulation_attrition import AttritionSimulator
from src.simulation.simulation_absence import AbsenceSimulator
from src.simulation.simulation_performance import PerformanceSimulator
from src.simulation.simulation_growth import calculate_growth_target
from src.simulation.simulation_career_events import _salary_review_week
from src.simulation.simulation_hiring import HiringSimulator
from src.simulation.simulation_recruitment import RecruitmentSimulator
from src.simulation.simulation_vacancy import VacancySimulator
from src.infrastructure.role_eligibility import credentials_for


# =====================================================
# 🔹 State builder
# =====================================================

def test_relevant_experience_accumulates_and_transfer_is_configurable():
    employment = pd.Series({
        "Startdatum": pd.Timestamp("2020-01-01"),
        "Relevante_Ervaring_Jaren_Bij_Start": 4.0,
    })
    config = type("Config", (), {
        "career_events": {"relevant_experience_transfer_ratio": 0.40}
    })()

    accrued = experience_as_of(employment, pd.Timestamp("2022-01-01"))

    assert 5.99 <= accrued <= 6.01
    assert carried_experience(employment, pd.Timestamp("2022-01-01"), True, config) == accrued
    assert carried_experience(employment, pd.Timestamp("2022-01-01"), False, config) == 2.4


def test_engagement_driver_matches_a_score_contribution():
    state = {
        "dim_engagement_driver": pd.DataFrame({
            "EngagementDriver_Key": list(range(1, 8)),
            "Driver_Name": [
                "Initiatief en verbeteren",
                "Kennisdeling en mentoring",
                "Samenwerking buiten de eigen rol",
                "Medewerkersstem en participatie",
                "Organisatieverbondenheid",
                "Rolverbondenheid/eigenaarschap",
                "Geen dominant aandachtspunt",
            ],
        }),
        "fact_employment": pd.DataFrame(),
    }

    model = EngagementModel(type("Config", (), {
        "engagement": {"driver_dominance_threshold": 0.0}
    })())
    contributions = model.constructive_contributions(
        state, 42, pd.Timestamp("2026-01-31"), 3.4
    )
    key = engagement_driver_key_for(
        state, 42, pd.Timestamp("2026-01-31"), 3.4, model
    )

    expected_name = max(contributions, key=contributions.get)
    expected_key = state["dim_engagement_driver"].loc[
        state["dim_engagement_driver"]["Driver_Name"] == expected_name,
        "EngagementDriver_Key",
    ].iloc[0]
    assert key == expected_key


def test_score_employee_engagement_caches_identical_resolved_inputs():
    state = {"fact_employment": pd.DataFrame()}
    model = EngagementModel(type("Config", (), {"engagement": {}})())
    employee = pd.Series({"Employee_Key": 1, "Manager_Key": 5})
    employment = pd.Series({
        "Employee_Key": 1,
        "Role_Key": 1,
        "Target_Compa_Ratio": 1.0,
    })

    first = score_employee_engagement(
        model, state, employee, employment, pd.Timestamp("2026-01-31"),
        satisfaction_score=7.0, performance_score=3.4,
    )
    second = score_employee_engagement(
        model, state, employee, employment, pd.Timestamp("2026-01-31"),
        satisfaction_score=7.0, performance_score=3.4,
    )

    assert first == second
    assert len(state["_engagement_cache"]) == 1
    # career_momentum_for is asked for twice per call (directly, and via
    # constructive_contributions) but only computed once per unique input.
    assert len(state["_engagement_momentum_cache"]) == 1


def test_candidate_quality_profile_has_explanatory_components_and_driver():
    config = ConfigLoader().load()
    simulator = RecruitmentSimulator(config, schema=None, rng=random.Random(42))
    source = {"HireSource_Name": "Vacaturebank"}

    profile = simulator._profile_from_quality(3.5, source)

    components = [
        "Candidate_Experience_Score",
        "Candidate_Education_Relevance_Score",
        "Candidate_Technical_Skills_Score",
        "Candidate_Soft_Skills_Score",
        "Candidate_Motivation_Score",
    ]
    assert all(1 <= profile[column] <= 5 for column in components)
    assert 1 <= profile["Candidate_Quality"] <= 5
    assert profile["CandidateQualityDriver_Key"] in range(1, 7)


def build_initial_state(config):
    # Unit tests use static avatar pools; Blob discovery belongs to integration
    # testing and must not make deterministic tests depend on network access.
    if hasattr(config, "avatar"):
        config.avatar = {
            **config.avatar,
            "auto_discover_from_blob": False
        }

    # 🔹 Roles uit config.structure halen
    roles = []
    role_key = 1

    for dept_name, roles_dict in config.structure.items():

        for role_name, role_cfg in roles_dict.items():

            roles.append({
                "Role_Key": role_key,
                "Role_Name": role_name,
                "Department_Name": dept_name,
                "Department_Key": hash(dept_name) % 1000,
                "Leidinggevend": role_cfg["leidinggevend"],
                "Salaris_min": role_cfg["salaris_range"][0],
                "Salaris_max": role_cfg["salaris_range"][1],
                "SalaryScale_Key": 1,
                "Ploegendienst_Flag": role_cfg.get("ploegendienst", False)
            })

            role_key += 1

    dim_role = pd.DataFrame(roles)

    # 🔹 Dimensions
    dim_hire_source = pd.DataFrame({
        "HireSource_Key": list(range(1, len(config.dim_hire_source) + 1))
    })

    dim_education = pd.DataFrame(config.dim_education)
    dim_education["Education_Key"] = list(range(1, len(dim_education) + 1))

    dim_location = pd.DataFrame({
        "Location_Name": list(config.dim_location.keys()),
        "Location_Key": list(range(1, len(config.dim_location) + 1))
    })

    dim_event_type = pd.DataFrame({
        "EventType": config.dim_event_type,
        "EventType_Key": list(range(1, len(config.dim_event_type) + 1))
    })
    dim_shift = pd.DataFrame(config.dim_shift)

    # 🔹 Allocation
    role_allocations = allocate_headcount(
        config.structure,
        config.baseline_headcount
    )

    state = {
        "dim_role": dim_role,
        "dim_hire_source": dim_hire_source,
        "dim_education": dim_education,
        "dim_location": dim_location,
        "dim_event_type": dim_event_type,
        "dim_shift": dim_shift,
        "role_allocations": role_allocations,

        # leeg (fresh run)
        "dim_employee": pd.DataFrame(),
        "fact_employment": pd.DataFrame()
    }

    return state


# =====================================================
# 🔹 Unit tests


def test_allocate_headcount_keeps_management_roles_above_minimum():
    structure = {
        "Productie": {
            "Medewerker": {
                "fte_ratio": 0.80,
                "leidinggevend": False
            },
            "Teamleider": {
                "fte_ratio": 0.02,
                "leidinggevend": True
            }
        },
        "Finance": {
            "Medewerker": {
                "fte_ratio": 0.0,
                "leidinggevend": False
            },
            "Manager": {
                "fte_ratio": 0.0,
                "leidinggevend": True
            }
        }
    }

    allocations = allocate_headcount(
        structure,
        total_employees=12,
        staffing_rules={"minimum_count_for_manager_role": 1}
    )
    counts = {
        (row["Department_Name"], row["Role_Name"]): row["count"]
        for row in allocations
    }

    assert sum(counts.values()) == 12
    assert counts[("Productie", "Teamleider")] >= 1
    assert counts[("Finance", "Manager")] >= 1


def test_initial_population_is_adult_on_first_employment_date():
    """Historical tenure must never make an employee a minor at hire."""
    config = ConfigLoader().load()
    state = build_initial_state(config)
    state = generate_employees(
        state=state,
        config=config,
        schema=None,
        rng=random.Random(42),
        today=pd.Timestamp("2017-01-01")
    )

    employees = state["dim_employee"][["Employee_Key", "Geboortedatum"]]
    employment = state["fact_employment"][["Employee_Key", "Startdatum"]]
    generated = employment.merge(employees, on="Employee_Key", how="inner")
    legal_birth_date = generated["Startdatum"] - pd.DateOffset(
        years=config.initial_population["minimum_hire_age"]
    )

    assert (generated["Geboortedatum"] <= legal_birth_date).all()


def test_generate_dimensions_supports_salary_scales():
    config = type("Config", (), {
        "get": lambda self, key, default=None: {
            "dim_salary_scale": [
                {
                    "SalaryScale_Code": "A",
                    "SalaryScale_Name": "Operationeel basis",
                    "Minimum_Salaris": 28000,
                    "Maximum_Salaris": 35999,
                    "Aantal_Treden": 6
                }
            ]
        }.get(key, default)
    })()
    schema = {
        "dim_salary_scale": {
            "df": "dim_salary_scale",
            "primary_key": "SalaryScale_Key",
            "types": {
                "SalaryScale_Key": "INT",
                "SalaryScale_Code": "NVARCHAR(10)",
                "SalaryScale_Name": "NVARCHAR(50)",
                "Minimum_Salaris": "INT",
                "Maximum_Salaris": "INT",
                "Aantal_Treden": "INT"
            }
        }
    }

    result = generate_dimensions(config, schema)["dim_salary_scale"]

    assert result.iloc[0].to_dict() == {
        "SalaryScale_Key": 1,
        "SalaryScale_Code": "A",
        "SalaryScale_Name": "Operationeel basis",
        "Minimum_Salaris": 28000,
        "Maximum_Salaris": 35999,
        "Aantal_Treden": 6
    }


def test_dim_role_stamps_department_name_for_hierarchical_visuals():
    structure = {
        "Productie": {
            "Operator": {
                "leidinggevend": False,
                "salaris_range": [30000, 35000]
            }
        }
    }
    departments = build_dim_department(structure)

    result = build_dim_role(structure, departments)

    assert result.iloc[0]["Department_Name"] == "Productie"


def test_sector_roles_use_their_explicit_salary_scale_codes():
    config = ConfigLoader().load()
    salary_scales = pd.DataFrame(config.dim_salary_scale)
    roles = build_dim_role(
        config.structure,
        build_dim_department(config.structure),
        salary_scales,
        config.salary_benchmark["market_median_by_role"],
        config.role_career_paths,
    )

    expected_codes = {
        "Productiemedewerker": "A",
        "QC Medewerker": "B",
        "Operator B": "C",
        "Controller": "D",
        "QA Manager": "E",
        "Operations Director": "G",
        "Managing Director": "G",
    }
    code_by_key = salary_scales.set_index("SalaryScale_Key")["SalaryScale_Code"]

    for role_name, expected_code in expected_codes.items():
        scale_key = roles.loc[
            roles["Role_Name"] == role_name,
            "SalaryScale_Key",
        ].iloc[0]
        assert code_by_key[scale_key] == expected_code

    for department_roles in config.structure.values():
        for role_name, role_config in department_roles.items():
            role_scale_key = roles.loc[
                roles["Role_Name"] == role_name,
                "SalaryScale_Key",
            ].iloc[0]
            assert code_by_key[role_scale_key] == role_config["salary_scale_code"]


def test_incremental_run_repairs_missing_configured_role_dimension_member():
    config = type("Config", (), {
        "structure": {
            "Productie": {
                "Operator": {
                    "leidinggevend": False,
                    "salaris_range": [35000, 45000]
                },
                "Teamleider": {
                    "leidinggevend": True,
                    "salaris_range": [50000, 65000]
                }
            }
        },
        "dim_departure_reason": {"vrijwillig": ["Nieuwe baan"]},
        "get": lambda self, key, default=None: default
    })()
    schema = {
        "dim_department": {"primary_key": "Department_Key", "types": {}},
        "dim_role": {"primary_key": "Role_Key", "types": {}},
        "dim_departure_reason": {
            "primary_key": "DepartureReason_Key", "types": {}
        }
    }
    state = {
        "dim_department": pd.DataFrame({
            "Department_Key": [1], "Department_Name": ["Productie"]
        }),
        "dim_role": pd.DataFrame({
            "Role_Key": [1], "Role_Name": ["Operator"]
        }),
        "dim_departure_reason": pd.DataFrame({
            "DepartureReason_Key": [1], "DepartureReason": ["Nieuwe baan"]
        })
    }

    _ensure_missing_static_dimensions(state, config, schema)

    assert set(state["dim_role"]["Role_Key"]) == {1, 2}
    assert state["dim_role"].loc[
        state["dim_role"]["Role_Key"] == 2,
        "Role_Name"
    ].iloc[0] == "Teamleider"


def test_allocate_headcount_fails_when_minimums_do_not_fit():
    structure = {
        "Directie": {
            "Managing Director": {
                "fte_ratio": 0.0,
                "leidinggevend": True
            },
            "Operations Director": {
                "fte_ratio": 0.0,
                "leidinggevend": True
            }
        }
    }

    with pytest.raises(ValueError, match="minimum staffing"):
        allocate_headcount(
            structure,
            total_employees=1,
            staffing_rules={"minimum_count_for_manager_role": 1}
        )


def test_employee_status_keeps_service_dates_across_internal_events():
    state = {
        "dim_employee": pd.DataFrame({"Employee_Key": [1]}),
        "fact_employment": pd.DataFrame({
            "Employment_Key": [1, 2],
            "Previous_Employment_Key": [None, 1],
            "Employee_Key": [1, 1],
            "Startdatum": pd.to_datetime(["2020-01-01", "2022-06-01"]),
            "Einddatum": pd.to_datetime(["2022-06-01", None]),
            "Dienstverband_status": ["Inactief", "Actief"]
        })
    }

    result = sync_employee_employment_status(state)["dim_employee"].iloc[0]

    assert result["Eerste_Indienst_Datum"] == pd.Timestamp("2020-01-01")
    assert result["Aaneengesloten_Indienst_Datum"] == pd.Timestamp("2020-01-01")
    assert pd.isna(result["Datum_uitdienst"])
    assert result["In_Dienst"]


def test_employee_status_follows_a_multi_event_employment_chain():
    """Internal events must retain the service date of the original hire."""
    state = {
        "dim_employee": pd.DataFrame({"Employee_Key": [398]}),
        "fact_employment": pd.DataFrame({
            "Employment_Key": [2502, 1713, 1070, 925],
            "Previous_Employment_Key": [1713, 1070, 925, None],
            "Employee_Key": [398, 398, 398, 398],
            "Startdatum": pd.to_datetime([
                "2026-03-09",
                "2025-03-10",
                "2024-03-11",
                "2023-12-04"
            ]),
            "Einddatum": pd.to_datetime([
                None,
                "2026-03-09",
                "2025-03-10",
                "2024-03-11"
            ]),
            "Dienstverband_status": [
                "Actief", "Inactief", "Inactief", "Inactief"
            ]
        })
    }

    result = sync_employee_employment_status(state)["dim_employee"].iloc[0]

    assert result["Eerste_Indienst_Datum"] == pd.Timestamp("2023-12-04")
    assert result["Aaneengesloten_Indienst_Datum"] == pd.Timestamp("2023-12-04")
    assert result["In_Dienst"]


def test_employee_status_resets_continuous_service_on_rehire():
    state = {
        "dim_employee": pd.DataFrame({"Employee_Key": [1]}),
        "fact_employment": pd.DataFrame({
            "Employment_Key": [1, 2],
            "Previous_Employment_Key": [None, None],
            "Employee_Key": [1, 1],
            "Startdatum": pd.to_datetime(["2020-01-01", "2023-03-01"]),
            "Einddatum": pd.to_datetime(["2021-01-31", None]),
            "Dienstverband_status": ["Uit dienst", "Actief"]
        })
    }

    result = sync_employee_employment_status(state)["dim_employee"].iloc[0]

    assert result["Eerste_Indienst_Datum"] == pd.Timestamp("2020-01-01")
    assert result["Aaneengesloten_Indienst_Datum"] == pd.Timestamp("2023-03-01")
    assert pd.isna(result["Datum_uitdienst"])
    assert result["In_Dienst"]
# =====================================================

def test_build_dim_manager_deduplicates_manager_rows():
    state = {
        "dim_employee": pd.DataFrame({
            "Employee_Key": [10, 20, 10, 30],
            "Voornaam": ["Romy", "Fem", "Romy", "Bastiaan"],
            "Achternaam": ["Chotzen", "van Oirschot", "Chotzen", "Rietveld"],
            "Manager_Key": [None, 10, None, 20]
        })
    }

    result = build_dim_manager(state)

    assert result["dim_manager"]["Manager_Key"].is_unique
    assert set(result["dim_manager"]["Manager_Key"]) == {10, 20}


def test_normalize_dataframe_values_removes_numpy_scalars():
    df = pd.DataFrame({
        "id": [np.int64(1), np.int64(2)],
        "score": [np.float64(1.5), np.float64(2.5)],
        "start_date": [pd.Timestamp("2024-01-01"), pd.NaT],
        "name": ["Alice", None]
    })

    normalized = write_to_sql._normalize_dataframe_for_sql(df)

    assert all(not isinstance(value, np.generic) for value in normalized["id"].tolist())
    assert all(not isinstance(value, np.generic) for value in normalized["score"].tolist())
    assert normalized.iloc[0]["start_date"] == pd.Timestamp("2024-01-01").to_pydatetime()
    assert normalized.iloc[1]["start_date"] is None
    assert normalized.iloc[1]["name"] is None


def test_normalize_dataframe_casts_schema_int_columns():
    df = pd.DataFrame({
        "Contract_ronde": [None, 5.0, np.int64(2)]
    })

    normalized = write_to_sql._normalize_dataframe_for_sql(
        df,
        {"Contract_ronde": "INT"}
    )

    assert normalized.iloc[0]["Contract_ronde"] is None
    assert normalized.iloc[1]["Contract_ronde"] == 5
    assert isinstance(normalized.iloc[1]["Contract_ronde"], int)
    assert normalized.iloc[2]["Contract_ronde"] == 2


def test_assign_managers_stays_in_same_department():
    dim_employee_df = pd.DataFrame({
        "Employee_Key": [1, 2, 3, 4, 5],
        "Manager_Key": [None, None, None, None, None]
    })

    fact_employment_df = pd.DataFrame({
        "Employment_Key": [1, 2, 3, 4, 5],
        "Employee_Key": [1, 2, 3, 4, 5],
        "Role_Key": [1, 2, 3, 4, 5],
        "Startdatum": pd.to_datetime([
            "2020-01-01",
            "2020-01-01",
            "2020-01-01",
            "2020-01-01",
            "2020-01-01"
        ])
    })

    dim_role = pd.DataFrame({
        "Role_Key": [1, 2, 3, 4, 5],
        "Department_Key": [10, 10, 20, 20, 20],
        "Leidinggevend": [False, True, False, True, False],
        "Salaris_max": [100, 200, 150, 250, 1000]
    })

    rng = random.Random(42)

    dim_employee_df = assign_managers(
        dim_employee_df,
        fact_employment_df,
        dim_role,
        rng,
        today=pd.Timestamp("2024-01-01")
    )

    assert dim_employee_df.loc[
        dim_employee_df["Employee_Key"] == 1,
        "Manager_Key"
    ].iloc[0] == 2

    assert dim_employee_df.loc[
        dim_employee_df["Employee_Key"] == 3,
        "Manager_Key"
    ].iloc[0] == 4


def test_assign_managers_prefers_higher_role_or_tenure():
    dim_employee_df = pd.DataFrame({
        "Employee_Key": [1, 2, 3],
        "Manager_Key": [None, None, None]
    })

    fact_employment_df = pd.DataFrame({
        "Employment_Key": [1, 2, 3],
        "Employee_Key": [1, 2, 3],
        "Role_Key": [1, 2, 3],
        "Startdatum": pd.to_datetime([
            "2023-01-01",
            "2018-01-01",
            "2022-01-01"
        ])
    })

    dim_role = pd.DataFrame({
        "Role_Key": [1, 2, 3],
        "Department_Key": [10, 10, 10],
        "Leidinggevend": [False, True, True],
        "Salaris_max": [100, 90, 150]
    })

    rng = random.Random(42)

    dim_employee_df = assign_managers(
        dim_employee_df,
        fact_employment_df,
        dim_role,
        rng,
        today=pd.Timestamp("2024-01-01")
    )

    manager_for_employee_1 = dim_employee_df.loc[
        dim_employee_df["Employee_Key"] == 1,
        "Manager_Key"
    ].iloc[0]

    assert manager_for_employee_1 in {2, 3}


def test_assign_managers_has_no_cycles_and_balances_staff():
    dim_employee_df = pd.DataFrame({
        "Employee_Key": list(range(1, 28)),
        "Manager_Key": [None] * 27
    })

    fact_employment_df = pd.DataFrame({
        "Employment_Key": list(range(1, 28)),
        "Employee_Key": list(range(1, 28)),
        "Role_Key": [1, 2, 3] + [4] * 24,
        "Startdatum": pd.to_datetime(["2020-01-01"] * 27),
        "Dienstverband_status": ["Actief"] * 27
    })

    dim_role = pd.DataFrame({
        "Role_Key": [1, 2, 3, 4],
        "Department_Key": [10, 10, 10, 10],
        "Role_Name": ["Director", "Teamlead A", "Teamlead B", "Medewerker"],
        "Leidinggevend": [True, True, True, False],
        "Salaris_min": [90000, 55000, 55000, 32000],
        "Salaris_max": [120000, 70000, 70000, 42000]
    })

    assigned = assign_managers(
        dim_employee_df,
        fact_employment_df,
        dim_role,
        random.Random(42),
        today=pd.Timestamp("2024-01-01")
    )

    manager_map = dict(zip(assigned["Employee_Key"], assigned["Manager_Key"]))

    for employee_key in assigned["Employee_Key"]:
        seen = set()
        current = employee_key

        while pd.notna(manager_map.get(current)):
            assert current not in seen
            seen.add(current)
            current = manager_map[current]

    report_counts = assigned["Manager_Key"].dropna().value_counts().to_dict()
    assert report_counts[2] >= 8
    assert report_counts[3] >= 8


def test_assign_managers_balances_parallel_team_leads():
    employee_keys = [1, 2] + list(range(3, 27))
    dim_employee_df = pd.DataFrame({
        "Employee_Key": employee_keys,
        "Manager_Key": [None] * len(employee_keys)
    })
    fact_employment_df = pd.DataFrame({
        "Employment_Key": employee_keys,
        "Employee_Key": employee_keys,
        "Role_Key": [1, 1] + [2] * 24,
        "Startdatum": pd.to_datetime(["2020-01-01"] * len(employee_keys)),
        "Dienstverband_status": ["Actief"] * len(employee_keys)
    })
    dim_role = pd.DataFrame({
        "Role_Key": [1, 2],
        "Department_Key": [10, 10],
        "Role_Name": ["Teamleider", "Medewerker"],
        "Leidinggevend": [True, False],
        "Salaris_min": [50000, 32000],
        "Salaris_max": [65000, 42000]
    })

    assigned = assign_managers(
        dim_employee_df,
        fact_employment_df,
        dim_role,
        random.Random(42),
        today=pd.Timestamp("2024-01-01")
    )

    report_counts = assigned["Manager_Key"].dropna().value_counts()
    assert report_counts[1] >= 8
    assert report_counts[2] >= 8


def test_assign_managers_keeps_historical_employees_connected():
    dim_employee_df = pd.DataFrame({
        "Employee_Key": [1, 2],
        "Manager_Key": [None, None]
    })

    fact_employment_df = pd.DataFrame({
        "Employment_Key": [1, 2],
        "Employee_Key": [1, 2],
        "Role_Key": [1, 2],
        "Startdatum": pd.to_datetime(["2020-01-01", "2020-01-01"]),
        "Einddatum": pd.to_datetime(["2022-01-01", None]),
        "Dienstverband_status": ["Uit dienst", "Actief"]
    })

    dim_role = pd.DataFrame({
        "Role_Key": [1, 2],
        "Department_Key": [10, 10],
        "Role_Name": ["Medewerker", "Teamleider"],
        "Leidinggevend": [False, True],
        "Salaris_min": [32000, 55000],
        "Salaris_max": [42000, 70000]
    })

    assigned = assign_managers(
        dim_employee_df,
        fact_employment_df,
        dim_role,
        random.Random(42),
        today=pd.Timestamp("2024-01-01")
    )

    assert assigned.loc[
        assigned["Employee_Key"] == 1,
        "Manager_Key"
    ].iloc[0] == 2


def test_salary_policy_places_initial_salary_near_its_benchmark():
    config = ConfigLoader().load()
    role = pd.Series({
        "Role_Key": 1,
        "Role_Name": "Productiemedewerker",
        "Salaris_min": 30000,
        "Salaris_max": 35000,
        "SalaryScale_Key": 1
    })
    factory = EmploymentFactory(config=config, rng=random.Random(42))
    salary, target_ratio = factory._choose_salary(
        role,
        "Productie",
        start_date=pd.Timestamp("2020-01-01"),
        today=pd.Timestamp("2024-01-01")
    )
    benchmark = factory.salary_policy.employee_benchmark(
        role,
        pd.Timestamp("2024-01-01"),
        pd.Timestamp("2020-01-01")
    )["Benchmark_Salaris"]

    assert 0.75 <= target_ratio <= 1.30
    assert salary == round(benchmark * target_ratio)


def test_salary_policy_keeps_all_benchmark_categories_visible():
    policy = SalaryPolicy(ConfigLoader().load())
    ratios = [
        policy.draw_target_ratio("Finance", random.Random(seed))
        for seed in range(1, 1001)
    ]
    category_counts = {
        "very_low": sum(ratio < 0.80 for ratio in ratios),
        "low": sum(0.80 <= ratio < 0.90 for ratio in ratios),
        "around": sum(0.90 <= ratio <= 1.10 for ratio in ratios),
        "high": sum(1.10 < ratio <= 1.20 for ratio in ratios),
        "very_high": sum(ratio > 1.20 for ratio in ratios)
    }

    assert all(count > 10 for count in category_counts.values())
    assert 0.99 < sum(ratios) / len(ratios) < 1.04


def test_generated_employment_contains_shift_and_salary_scale_context():
    config = ConfigLoader().load()
    state = build_initial_state(config)
    state = generate_employees(
        state,
        config,
        schema=None,
        rng=random.Random(42),
        today=pd.Timestamp("2020-01-01")
    )
    employment = state["fact_employment"]

    assert "fact_employment_attribute" not in state
    assert employment["Shift_Key"].notna().all()
    assert employment["SalaryScale_Key"].notna().all()
    assert employment["Target_Compa_Ratio"].between(0.75, 1.30).all()


def test_salary_review_weeks_are_spread_over_year():
    review_weeks = [
        _salary_review_week(employee_key)
        for employee_key in range(1, 101)
    ]

    assert min(review_weeks) >= 1
    assert max(review_weeks) <= 52
    assert len(set(review_weeks)) > 40


def test_workforce_snapshot_captures_historical_workforce_context():
    config = type("Config", (), {
        "salary_benchmark": {},
        "satisfaction": {
            "baseline_mean": 7.0,
            "individual_spread": 0.5,
            "monthly_variation_amplitude": 0.1
        },
        "workforce": {"full_time_weekly_hours": 40}
    })()
    state = {
        "dim_employee": pd.DataFrame({
            "Employee_Key": [1, 2],
            "HireSource_Key": [1, 2],
            "Education_Key": [2, 3],
            "Performance_Score": [3.0, 3.5],
            "Initial_Performance_Score": [3.0, 3.5],
            "Aaneengesloten_Indienst_Datum": pd.to_datetime([
                "2024-01-01", "2024-01-01"
            ])
        }),
        "dim_role": pd.DataFrame({
            "Role_Key": [1],
            "Department_Key": [10]
        }),
        "dim_department": pd.DataFrame({
            "Department_Key": [10],
            "Department_Name": ["IT"]
        }),
        "dim_salary_band": pd.DataFrame({
            "SalaryBand_Key": [3],
            "Minimum_Salaris": [45000],
            "Maximum_Salaris": [59999]
        }),
        "dim_satisfaction_band": pd.DataFrame({
            "SatisfactionBand_Key": [1, 2],
            "Minimum_Score": [1.0, 6.0],
            "Maximum_Score": [5.99, 10.0]
        }),
        "dim_absence_type": pd.DataFrame({
            "AbsenceType_Key": [1],
            "Telt_als_verzuim": [True]
        }),
        "fact_employment": pd.DataFrame({
            "Employment_Key": [1, 2],
            "Employee_Key": [1, 2],
            "Role_Key": [1, 1],
            "Location_Key": [3, 3],
            "Shift_Key": [0, 0],
            "SalaryScale_Key": [3, 3],
            "Target_Compa_Ratio": [1.0, 1.0],
            "Startdatum": pd.to_datetime(["2024-01-01", "2024-01-01"]),
            "Einddatum": [None, None],
            "Contracttype": ["Vast", "Vast"],
            "Contracturen": [40, 32],
            "Salaris": [50000, 50000]
        }),
        "fact_performance_review": pd.DataFrame({
            "Employee_Key": [1],
            "Review_Datum": [pd.Timestamp("2024-03-10")],
            "Performance_Score": [4.2]
        }),
        "fact_manager_assignment": pd.DataFrame({
            "ManagerAssignment_Key": [1, 2],
            "Employee_Key": [1, 2],
            "Manager_Key": [2, None],
            "Startdatum": pd.to_datetime(["2024-01-01", "2024-01-01"]),
            "Einddatum": [None, None]
        }),
        "fact_absence": pd.DataFrame({
            "Absence_Key": [1],
            "Employee_Key": [1],
            "AbsenceType_Key": [1],
            "Startdatum": [pd.Timestamp("2024-03-29")],
            "Einddatum": [pd.Timestamp("2024-04-02")]
        })
    }

    result = build_workforce_snapshots(
        state,
        schema=None,
        config=config,
        start_date=pd.Timestamp("2024-01-01"),
        end_date=pd.Timestamp("2024-03-31")
    )

    snapshots = result["fact_workforce_snapshot"]
    march_employee_one = snapshots[
        (snapshots["Snapshot_Date"] == pd.Timestamp("2024-03-31"))
        & (snapshots["Employee_Key"] == 1)
    ].iloc[0]

    assert len(snapshots) == 6
    assert snapshots["WorkforceSnapshot_Key"].is_unique
    assert march_employee_one["HireSource_Key"] == 1
    assert march_employee_one["Education_Key"] == 2
    assert march_employee_one["Performance_Score"] == 4.2
    assert march_employee_one["Manager_Key"] == 2
    assert march_employee_one["Dienstjaren"] == 0.25
    assert march_employee_one["Relevante_Ervaring_Jaren"] == 0.25
    assert march_employee_one["FTE"] == 1.0
    assert march_employee_one["SalaryBand_Key"] == 3
    assert march_employee_one["Beschikbare_Werkdagen"] == 21.0
    assert march_employee_one["Beschikbare_Uren"] == 168.0
    assert march_employee_one["Afwezige_Dagen"] == 3.0
    assert march_employee_one["Verzuim_Dagen"] == 3.0
    assert march_employee_one["Aantal_Afwezigheid_Episodes"] == 1
    assert march_employee_one["SatisfactionBand_Key"] == 2
    assert 1 <= march_employee_one["Tevredenheid_Score"] <= 10


def test_manager_assignments_are_effective_dated_when_manager_changes():
    state = {
        "dim_employee": pd.DataFrame({
            "Employee_Key": [1, 2, 3],
            "Manager_Key": [2, None, None]
        }),
        "fact_employment": pd.DataFrame({
            "Employee_Key": [1, 2, 3],
            "Startdatum": pd.to_datetime(["2024-01-01"] * 3),
            "Einddatum": [None, None, None],
            "Dienstverband_status": ["Actief"] * 3
        })
    }

    state = sync_manager_assignments(state, None, pd.Timestamp("2024-01-01"))
    state["dim_employee"].loc[
        state["dim_employee"]["Employee_Key"] == 1,
        "Manager_Key"
    ] = 3
    state = sync_manager_assignments(state, None, pd.Timestamp("2024-02-01"))

    assignments = state["fact_manager_assignment"]
    assert manager_as_of(assignments, 1, pd.Timestamp("2024-01-31")) == 2
    assert manager_as_of(assignments, 1, pd.Timestamp("2024-02-01")) == 3


@pytest.mark.parametrize(
    ("salary", "expected_status"),
    [
        (79, "Ver onder benchmark"),
        (80, "Onder benchmark"),
        (90, "Rond benchmark"),
        (110, "Rond benchmark"),
        (111, "Boven benchmark"),
        (120, "Boven benchmark"),
        (121, "Ver boven benchmark"),
    ]
)
def test_salary_benchmark_status_uses_five_configured_bands(
    salary,
    expected_status
):
    config = type("Config", (), {
        "salary_benchmark": {
            "benchmark_status_thresholds": {
                "ver_onder": 0.80,
                "onder": 0.90,
                "boven": 1.10,
                "ver_boven": 1.20
            }
        }
    })()
    builder = SalaryBenchmarkBuilder({}, None, config)

    assert builder._benchmark_status(salary, 100) == expected_status


def test_internal_recruitment_move_reuses_employee_and_requests_backfill():
    config = ConfigLoader().load()
    config.avatar = {**config.avatar, "auto_discover_from_blob": False}
    event_type_map = {
        event: index
        for index, event in enumerate(config.dim_event_type, start=1)
    }
    salary_scales = pd.DataFrame(config.dim_salary_scale)
    state = {
        "dim_employee": pd.DataFrame({
            "Employee_Key": [1],
            "Performance_Score": [4.0],
            "Aaneengesloten_Indienst_Datum": [pd.Timestamp("2020-01-01")]
        }),
        "dim_department": pd.DataFrame({
            "Department_Key": [1, 2],
            "Department_Name": ["Productie", "Techniek"]
        }),
        "dim_role": pd.DataFrame({
            "Role_Key": [1, 2],
            "Department_Key": [1, 2],
            "Role_Name": ["Operator A", "Monteur"],
            "SalaryScale_Key": [1, 2],
            "Salaris_min": [28000, 36000],
            "Salaris_max": [35999, 44999]
        }),
        "dim_salary_scale": salary_scales,
        "dim_shift": pd.DataFrame(config.dim_shift),
        "fact_employment": pd.DataFrame({
            "Employment_Key": [10],
            "Previous_Employment_Key": [None],
            "Employee_Key": [1],
            "HireSource_Key": [2],
            "Role_Key": [1],
            "Location_Key": [1],
            "Shift_Key": [None],
            "SalaryScale_Key": [1],
            "Target_Compa_Ratio": [0.90],
            "Startdatum": [pd.Timestamp("2020-01-01")],
            "Einddatum": [None],
            "Dienstverband_status": ["Actief"],
            "Salaris": [35000],
            "Contracttype": ["Vast"],
            "Contracturen": [40],
            "Contract_einddatum": [None],
            "Contract_ronde": [None]
        })
    }
    target_role = state["dim_role"].iloc[1]
    simulator = HiringSimulator(
        config,
        schema=None,
        rng=random.Random(42),
        event_type_map=event_type_map
    )

    record, backfill = simulator._move_internal_employee(
        state,
        employee_key=1,
        target_role=target_role,
        today=pd.Timestamp("2024-01-01"),
        employment_key=11
    )

    assert len(state["dim_employee"]) == 1
    assert state["fact_employment"].loc[0, "Dienstverband_status"] == "Inactief"
    assert record["Employee_Key"] == 1
    assert record["Previous_Employment_Key"] == 10
    assert record["Role_Key"] == 2
    assert record["EventType_Key"] == event_type_map["Transfer"]
    assert backfill == {
        "Role_Key": 1,
        "Department_Key": 1,
        "Vacancy_Reason": "Internal mobility backfill"
    }


def test_hiring_internal_application_does_not_create_a_second_employee():
    config = ConfigLoader().load()
    config.avatar = {**config.avatar, "auto_discover_from_blob": False}
    event_type_map = {
        event: index
        for index, event in enumerate(config.dim_event_type, start=1)
    }
    state = {
        "dim_employee": pd.DataFrame({
            "Employee_Key": [1],
            "Performance_Score": [4.0],
            "Aaneengesloten_Indienst_Datum": [pd.Timestamp("2020-01-01")]
        }),
        "dim_department": pd.DataFrame({
            "Department_Key": [1, 2],
            "Department_Name": ["Productie", "Techniek"]
        }),
        "dim_role": pd.DataFrame({
            "Role_Key": [1, 2],
            "Department_Key": [1, 2],
            "Role_Name": ["Operator A", "Monteur"],
            "SalaryScale_Key": [1, 2],
            "Salaris_min": [28000, 36000],
            "Salaris_max": [35999, 44999],
            "Leidinggevend": [False, False]
        }),
        "dim_salary_scale": pd.DataFrame(config.dim_salary_scale),
        "dim_shift": pd.DataFrame(config.dim_shift),
        "fact_employment": pd.DataFrame({
            "Employment_Key": [10],
            "Previous_Employment_Key": [None],
            "Employee_Key": [1],
            "HireSource_Key": [2],
            "Role_Key": [1],
            "Location_Key": [1],
            "Shift_Key": [None],
            "SalaryScale_Key": [1],
            "Target_Compa_Ratio": [0.90],
            "Startdatum": [pd.Timestamp("2020-01-01")],
            "Einddatum": [None],
            "Dienstverband_status": ["Actief"],
            "Salaris": [35000],
            "Contracttype": ["Vast"],
            "Contracturen": [40],
            "Contract_einddatum": [None],
            "Contract_ronde": [None]
        }),
        "fact_vacancy": pd.DataFrame({
            "Vacancy_Key": [20],
            "Role_Key": [2],
            "Department_Key": [2],
            "Vacancy_Reason": ["Growth"],
            "Status": ["Open"],
            "Filled_Employee_Key": [None]
        }),
        "fact_recruitment": pd.DataFrame({
            "Recruitment_Key": [30],
            "Employee_Key": [None]
        }),
        "_accepted_applications": [{
            "Recruitment_Key": 30,
            "Vacancy_Key": 20,
            "Role_Key": 2,
            "Department_Key": 2,
            "HireSource_Key": 5,
            "Vacancy_Reason": "Growth",
            "Employee_Key": 1,
            "Candidate_Quality": 4.2,
            "Is_Internal_Mobility": True
        }]
    }

    result = HiringSimulator(
        config,
        schema=None,
        rng=random.Random(42),
        event_type_map=event_type_map
    ).run(state, pd.Timestamp("2024-01-01"))

    assert result["dim_employee"]["Employee_Key"].tolist() == [1]
    assert len(result["fact_employment"]) == 2
    assert result["fact_vacancy"].loc[0, "Filled_Employee_Key"] == 1
    assert result["fact_recruitment"].loc[0, "Employee_Key"] == 1
    assert result["_vacancy_requests"] == [{
        "Role_Key": 1,
        "Department_Key": 1,
        "Vacancy_Reason": "Internal mobility backfill"
    }]


def test_credentials_for_reads_the_qualification_achievement_date_column():
    """Regression test: fact_employee_qualification's date column is
    Behaald_Datum. A prior typo (Behhaald_Datum) made this raise for any
    employee with a real qualification history."""
    state = {
        "dim_education": pd.DataFrame({
            "Education_Key": [1],
            "Education_Name": ["MBO Werktuigbouw"],
        }),
        "fact_employee_qualification": pd.DataFrame({
            "Employee_Key": [1],
            "Education_Key": [1],
            "Behaald_Datum": [pd.Timestamp("2020-01-01")],
        }),
    }

    assert credentials_for(state, 1, pd.Timestamp("2024-01-01")) == {"MBO Werktuigbouw"}


def test_experience_score_rewards_meeting_and_exceeding_the_requirement():
    config = type("Config", (), {"recruitment": {}})()
    simulator = RecruitmentSimulator(config, schema=None, rng=random.Random(7))

    below = simulator._experience_score(experience_years=0.0, required_years=8.0)
    meets = simulator._experience_score(experience_years=8.0, required_years=8.0)
    exceeds = simulator._experience_score(experience_years=20.0, required_years=8.0)

    assert below < meets < exceeds
    assert all(1 <= score <= 5 for score in (below, meets, exceeds))


def test_education_relevance_score_rewards_a_matching_sufficient_credential():
    config = type("Config", (), {
        "recruitment": {},
        "role_career_paths": {
            "Senior Monteur": {"relevante_opleidingen": ["MBO Werktuigbouw"]}
        }
    })()
    simulator = RecruitmentSimulator(config, schema=None, rng=random.Random(3))
    target_role = pd.Series({
        "Role_Name": "Senior Monteur",
        "Min_Opleidingsniveau": "MBO",
    })

    no_match = simulator._education_relevance_score(target_role, [])
    below_level = simulator._education_relevance_score(
        target_role,
        [{"Education_Name": "MBO Werktuigbouw", "Education_Level": "Geen"}]
    )
    meets = simulator._education_relevance_score(
        target_role,
        [{"Education_Name": "MBO Werktuigbouw", "Education_Level": "MBO"}]
    )

    assert no_match < below_level < meets


def test_hiring_external_candidate_uses_the_screened_profile_not_a_new_draw():
    config = ConfigLoader().load()
    config.avatar = {**config.avatar, "auto_discover_from_blob": False}
    event_type_map = {
        event: index for index, event in enumerate(config.dim_event_type, start=1)
    }
    state = build_initial_state(config)

    role_name = next(
        name for name in config.role_career_paths
        if name in config.education_distribution_by_role
    )
    role_row = state["dim_role"].loc[
        state["dim_role"]["Role_Name"] == role_name
    ].iloc[0]
    education_row = state["dim_education"].iloc[0]

    # An unrelated placeholder employee, purely so the "next key" lookups
    # HiringSimulator relies on have a non-empty column to read from.
    state["dim_employee"] = pd.DataFrame({
        "Employee_Key": [1],
        "Performance_Score": [3.0],
    })
    state["fact_employment"] = pd.DataFrame({
        "Employment_Key": [1],
        "Employee_Key": [1],
        "Role_Key": [role_row["Role_Key"]],
        "Dienstverband_status": ["Actief"],
    })
    state["fact_employee_qualification"] = pd.DataFrame({
        "EmployeeQualification_Key": [1],
        "Employee_Key": [1],
        "Education_Key": [education_row["Education_Key"]],
        "Behaald_Datum": [pd.Timestamp("2015-01-01")],
        "Verkregen_Tijdens_Dienstverband": [False],
    })
    state["dim_department"] = pd.DataFrame({
        "Department_Key": [role_row["Department_Key"]],
        "Department_Name": [role_row["Department_Name"]],
    })
    state["fact_vacancy"] = pd.DataFrame({
        "Vacancy_Key": [20],
        "Role_Key": [role_row["Role_Key"]],
        "Department_Key": [role_row["Department_Key"]],
        "Vacancy_Reason": ["Growth"],
        "Status": ["Open"],
        "Filled_Employee_Key": [None]
    })
    state["fact_recruitment"] = pd.DataFrame({
        "Recruitment_Key": [30],
        "Employee_Key": [None]
    })
    state["_accepted_applications"] = [{
        "Recruitment_Key": 30,
        "Vacancy_Key": 20,
        "Role_Key": role_row["Role_Key"],
        "Department_Key": role_row["Department_Key"],
        "HireSource_Key": 1,
        "Vacancy_Reason": "Growth",
        "Employee_Key": None,
        "Candidate_Quality": 4.0,
        "Education_Key": education_row["Education_Key"],
        "Relevante_Ervaring_Jaren": 6.5,
        "Is_Internal_Mobility": False
    }]

    result = HiringSimulator(
        config,
        schema=None,
        rng=random.Random(42),
        event_type_map=event_type_map
    ).run(state, pd.Timestamp("2024-01-01"))

    new_employee = result["dim_employee"].iloc[-1]
    new_employment = result["fact_employment"].iloc[-1]
    new_qualification = result["fact_employee_qualification"].iloc[-1]

    assert new_employee["Education_Key"] == education_row["Education_Key"]
    assert new_employment["Relevante_Ervaring_Jaren_Bij_Start"] == 6.5
    assert new_qualification["Employee_Key"] == new_employee["Employee_Key"]
    assert new_qualification["Education_Key"] == education_row["Education_Key"]


def test_growth_selection_does_not_always_pick_the_same_under_minimum_role():
    """Two departments each need their first manager. Across many seeds both
    should eventually get picked - not just whichever comes first by
    Role_Key, which would starve one department every time it happens."""
    config = type("Config", (), {
        "structure": {
            "A": {"Manager A": {"leidinggevend": True, "department_key": 1}},
            "B": {"Manager B": {"leidinggevend": True, "department_key": 2}},
        },
        "staffing": {"minimum_count_for_manager_role": 1},
        "workforce_planning": {},
    })()
    state = {
        "dim_role": pd.DataFrame({
            "Role_Key": [1, 2],
            "Role_Name": ["Manager A", "Manager B"],
            "Department_Key": [1, 2],
            "Department_Name": ["A", "B"],
        }),
        "dim_department": pd.DataFrame({
            "Department_Key": [1, 2],
            "Department_Name": ["A", "B"],
        }),
    }
    simulator = VacancySimulator(config, schema=None, rng=random.Random(0))

    picks = set()
    for seed in range(20):
        simulator.rng = random.Random(seed)
        role = simulator._choose_role_for_growth(
            state, role_counts={}, target_headcount=2, pending_by_role={}
        )
        picks.add(role["Role_Key"])

    assert picks == {1, 2}


def test_attrition_uses_fact_employment_salary():
    config = type("Config", (), {
        "dim_departure_reason": {"vrijwillig": ["Ontslag"], "werkgever": ["Ontslag"]},
        "attrition": {"Sales": 0.05}
    })()

    state = {
        "dim_department": pd.DataFrame({
            "Department_Key": [1],
            "Department_Name": ["Sales"]
        }),
        "dim_role": pd.DataFrame({
            "Role_Key": [1],
            "Department_Key": [1],
            "Role_Name": ["Analist"]
        }),
        "dim_employee": pd.DataFrame({
            "Employee_Key": [1],
            "Performance_Score": [4.0]
        }),
        "fact_employment": pd.DataFrame({
            "Employment_Key": [1],
            "Employee_Key": [1],
            "Role_Key": [1],
            "Salaris": [5000],
            "Dienstverband_status": ["Actief"],
            "Startdatum": [pd.Timestamp("2020-01-01")],
            "Einddatum": [None],
            "DepartureReason_Key": [None],
            "EventType_Key": [None]
        }),
        "vacancies": 0
    }

    simulator = AttritionSimulator(
        config,
        random.Random(42),
        {"Uit dienst": 1},
        {"Ontslag": 1}
    )

    result = simulator.run(state, pd.Timestamp("2024-01-01"))

    assert "fact_employment" in result
    assert result["fact_employment"]["Employee_Key"].tolist() == [1]


def test_retirement_exits_are_age_gated_and_use_pensioen_reason():
    config = type("Config", (), {
        "dim_departure_reason": {
            "vrijwillig": ["Pensioen", "Nieuwe baan elders"],
            "werkgever": ["Ontslag"]
        },
        "attrition": {"Productie": 0.0},
        "retirement": {
            "minimum_age": 50,
            "forced_retirement_age": 67,
            "age_bands": []
        }
    })()
    today = pd.Timestamp("2026-01-05")
    state = {
        "dim_department": pd.DataFrame({
            "Department_Key": [1], "Department_Name": ["Productie"]
        }),
        "dim_role": pd.DataFrame({
            "Role_Key": [1], "Department_Key": [1]
        }),
        "dim_employee": pd.DataFrame({
            "Employee_Key": [1, 2],
            "Geboortedatum": [
                pd.Timestamp("1958-01-01"),
                pd.Timestamp("1977-01-01")
            ],
            "Performance_Score": [3.0, 3.0]
        }),
        "fact_employment": pd.DataFrame({
            "Employment_Key": [1, 2],
            "Employee_Key": [1, 2],
            "Role_Key": [1, 1],
            "Salaris": [50000, 50000],
            "Dienstverband_status": ["Actief", "Actief"],
            "Startdatum": [
                pd.Timestamp("2010-01-01"),
                pd.Timestamp("2010-01-01")
            ],
            "Einddatum": [None, None],
            "DepartureReason_Key": [None, None],
            "EventType_Key": [None, None]
        })
    }

    simulator = AttritionSimulator(
        config,
        random.Random(42),
        {"Uit dienst": 1},
        {"Pensioen": 2, "Nieuwe baan elders": 3, "Ontslag": 4}
    )
    result = simulator.run(state, today)

    employment = result["fact_employment"].set_index("Employee_Key")
    assert employment.loc[1, "Dienstverband_status"] == "Uit dienst"
    assert employment.loc[1, "DepartureReason_Key"] == 2
    assert employment.loc[2, "Dienstverband_status"] == "Actief"


def test_absence_uses_enabled_types_and_respects_employment_end():
    class AlwaysIncidentRandom(random.Random):
        def random(self):
            return 0.0

    config = type("Config", (), {
        "absence": {
            "annual_event_rate": 1.0,
            "minimum_tenure_days": 0,
            "age_multipliers": {
                "<30": 1.0,
                "30-45": 1.0,
                "45-55": 1.0,
                "55+": 1.0
            },
            "ploegendienst_multipliers": {},
            "type_weights": {"Lang verzuim": 1.0},
            "duration_distribution_by_type": {
                "Lang verzuim": {"10": 1.0}
            }
        }
    })()
    state = {
        "dim_employee": pd.DataFrame({
            "Employee_Key": [1],
            "Geboortedatum": [pd.Timestamp("1985-01-01")]
        }),
        "fact_employment": pd.DataFrame({
            "Employment_Key": [1],
            "Employee_Key": [1],
            "Role_Key": [7],
            "Location_Key": [3],
            "Shift_Key": [2],
            "SalaryScale_Key": [3],
            "Salaris": [55000],
            "Startdatum": [pd.Timestamp("2020-01-01")],
            "Einddatum": [None],
            "Contract_einddatum": [pd.Timestamp("2024-01-05")],
            "Dienstverband_status": ["Actief"]
        }),
        "dim_role": pd.DataFrame({
            "Role_Key": [7],
            "Department_Key": [5]
        }),
        "dim_shift": pd.DataFrame({
            "Shift_Key": [0, 2],
            "Shift_Name": ["Niet van toepassing", "2-ploeg"]
        }),
        "dim_salary_band": pd.DataFrame({
            "SalaryBand_Key": [3],
            "Minimum_Salaris": [45000],
            "Maximum_Salaris": [59999]
        }),
        "dim_absence_type": pd.DataFrame({
            "AbsenceType_Key": [1, 2],
            "AbsenceType_Name": ["Vakantie", "Lang verzuim"],
            "Telt_als_verzuim": [False, True]
        }),
        "fact_absence": pd.DataFrame()
    }

    result = AbsenceSimulator(
        config,
        schema=None,
        rng=AlwaysIncidentRandom(42)
    ).run(state, pd.Timestamp("2024-01-01"))

    absence = result["fact_absence"]
    assert len(absence) == 1
    assert absence.iloc[0]["AbsenceType_Key"] == 2
    assert absence.iloc[0]["Role_Key"] == 7
    assert absence.iloc[0]["Department_Key"] == 5
    assert absence.iloc[0]["Location_Key"] == 3
    assert absence.iloc[0]["Salaris_bij_aanvang"] == 55000
    assert absence.iloc[0]["SalaryBand_Key"] == 3
    assert absence.iloc[0]["SalaryScale_Key"] == 3
    assert absence.iloc[0]["Shift_Key"] == 2
    assert absence.iloc[0]["Einddatum"] <= pd.Timestamp("2024-01-05")
    assert absence.iloc[0]["Duur_dagen"] == (
        absence.iloc[0]["Einddatum"] - absence.iloc[0]["Startdatum"]
    ).days + 1


def test_absence_does_not_overlap_existing_episode():
    config = type("Config", (), {
        "absence": {
            "annual_event_rate": 1.0,
            "minimum_tenure_days": 0,
            "age_multipliers": {},
            "ploegendienst_multipliers": {},
            "type_weights": {"Kort verzuim": 1.0},
            "duration_distribution_by_type": {"Kort verzuim": {"1": 1.0}}
        }
    })()
    state = {
        "dim_employee": pd.DataFrame({
            "Employee_Key": [1],
            "Geboortedatum": [pd.Timestamp("1985-01-01")]
        }),
        "fact_employment": pd.DataFrame({
            "Employment_Key": [1],
            "Employee_Key": [1],
            "Startdatum": [pd.Timestamp("2020-01-01")],
            "Einddatum": [None],
            "Contract_einddatum": [None],
            "Dienstverband_status": ["Actief"]
        }),
        "dim_absence_type": pd.DataFrame({
            "AbsenceType_Key": [1],
            "AbsenceType_Name": ["Kort verzuim"],
            "Telt_als_verzuim": [True]
        }),
        "fact_absence": pd.DataFrame({
            "Absence_Key": [8],
            "Employee_Key": [1],
            "AbsenceType_Key": [1],
            "Startdatum": [pd.Timestamp("2023-12-30")],
            "Einddatum": [pd.Timestamp("2024-01-03")],
            "Duur_dagen": [5]
        })
    }

    result = AbsenceSimulator(
        config,
        schema=None,
        rng=random.Random(42)
    ).run(state, pd.Timestamp("2024-01-01"))

    assert len(result["fact_absence"]) == 1
    assert result["fact_absence"]["Absence_Key"].tolist() == [8]


def test_absence_long_duration_ranges_avoid_fixed_duration_spikes():
    config = type("Config", (), {
        "absence": {
            "duration_ranges_by_type": {
                "Lang verzuim": [
                    {
                        "min_days": 7,
                        "mode_days": 10,
                        "max_days": 14,
                        "weight": 0.35
                    },
                    {
                        "min_days": 61,
                        "mode_days": 90,
                        "max_days": 120,
                        "weight": 0.10
                    }
                ]
            }
        }
    })()
    simulator = AbsenceSimulator(config, schema=None, rng=random.Random(42))

    durations = [
        simulator._choose_duration("Lang verzuim")
        for _ in range(100)
    ]

    assert all(7 <= duration <= 120 for duration in durations)
    assert len(set(durations)) > 20


def test_sickness_type_directly_identifies_duration_class_and_worktime():
    config = type("Config", (), {
        "absence": {
            "duration_ranges_by_type": {
                "Middellang verzuim": [{
                    "min_days": 7,
                    "mode_days": 10,
                    "max_days": 14,
                    "weight": 1.0,
                }]
            },
            "duration_distribution": {"1": 1.0},
        },
        "workforce": {"full_time_weekly_hours": 40},
    })()
    simulator = AbsenceSimulator(config, schema=None, rng=random.Random(42))
    state = {
        "dim_role": pd.DataFrame({"Role_Key": [1], "Department_Key": [1]}),
        "dim_salary_band": pd.DataFrame(),
    }
    employment = pd.Series({
        "Startdatum": pd.Timestamp("2024-01-01"),
        "Contracturen": 40,
        "Role_Key": 1,
        "Salaris": 45000,
    })
    sickness = {
        "AbsenceType_Key": 2,
        "AbsenceType_Name": "Middellang verzuim",
        "Telt_als_verzuim": True,
    }
    employee = {"Employee_Key": 1}

    record = simulator._generate_absence_record(
        employee,
        sickness,
        1,
        pd.Timestamp("2024-01-01"),
        employment,
        state,
    )

    assert 7 <= record["Duur_dagen"] <= 14
    assert record["AbsenceType_Key"] == 2
    assert record["Afwezigheid_Werkdagen"] > 0
    assert record["Verzuim_Werkdagen"] == record["Afwezigheid_Werkdagen"]
    assert record["Verzuim_Uren"] == record["Afwezigheid_Uren"]


def test_non_sickness_episode_has_no_sickness_hours():
    class StartOnFirstEligibleDayRandom(random.Random):
        def randint(self, lower, upper):
            return lower

    config = type("Config", (), {
        "absence": {"duration_distribution": {"1": 1.0}},
        "workforce": {"full_time_weekly_hours": 40},
    })()
    simulator = AbsenceSimulator(
        config,
        schema=None,
        rng=StartOnFirstEligibleDayRandom(42),
    )
    state = {
        "dim_role": pd.DataFrame({"Role_Key": [1], "Department_Key": [1]}),
        "dim_salary_band": pd.DataFrame(),
    }
    employment = pd.Series({
        "Startdatum": pd.Timestamp("2024-01-01"),
        "Contracturen": 32,
        "Role_Key": 1,
        "Salaris": 45000,
    })
    leave = {
        "AbsenceType_Key": 2,
        "AbsenceType_Name": "Bijzonder verlof",
        "Telt_als_verzuim": False,
    }

    record = simulator._generate_absence_record(
        {"Employee_Key": 1}, leave, 1, pd.Timestamp("2024-01-01"),
        employment, state,
    )

    assert record["Verzuim_Werkdagen"] == 0
    assert record["Verzuim_Uren"] == 0.0
    assert record["Afwezigheid_Uren"] == 6.4


def test_satisfaction_penalises_under_market_pay_more_than_over_market_pay():
    config = type("Config", (), {
        "satisfaction": {
            "baseline_mean": 7.0,
            "individual_spread": 0.0,
            "performance_midpoint": 3.4,
            "performance_effect": 0.0,
            "manager_effect_spread": 0.0,
            "tenure_adjustments": {},
        }
    })()
    model = SatisfactionModel(config)

    under_market = model.score(1, "2025-01-31", 3.4, compa_ratio=0.85)
    above_market = model.score(1, "2025-01-31", 3.4, compa_ratio=1.15)

    assert under_market < above_market
    assert above_market - under_market >= 0.8


def test_engagement_moves_with_satisfaction_and_stays_distinct():
    config = type("Config", (), {
        "engagement": {
            "baseline_mean": 6.7,
            "individual_spread": 0.0,
            "satisfaction_effect": 0.5,
            "performance_effect": 0.0,
            "manager_effect_spread": 0.0,
        }
    })()
    model = EngagementModel(config)

    low_satisfaction = model.score(1, 5.5, 3.4, compa_ratio=1.0)
    high_satisfaction = model.score(1, 8.0, 3.4, compa_ratio=1.0)

    assert low_satisfaction < high_satisfaction
    assert high_satisfaction - low_satisfaction == 1.25


def test_avatar_assignment_is_stable_gender_aware_and_uses_neutral_images():
    config = type("Config", (), {
        "avatar": {
            "base_url": "https://example.test/hr-avatars",
            "assignment_seed": "test-avatar-seed",
            "neutral_probability_for_binary_gender": 0.05,
        }
    })()
    assigner = AvatarAssigner(config)

    assert assigner.assign(42, "F") == assigner.assign(42, "F")
    assert assigner.assign(42, "F").url.startswith(
        "https://example.test/hr-avatars/"
    )
    assert assigner.assign(42, "Anders").file_name in {
        "neutral1.png", "neutral2.png"
    }
    assert assigner.assign(42, "Onbekend").file_name in {
        "neutral1.png", "neutral2.png"
    }

    avatars = [assigner.assign(key, "M").file_name for key in range(1, 10_001)]
    neutral_share = sum(name.startswith("neutral") for name in avatars) / len(avatars)
    assert 0.04 < neutral_share < 0.06


def test_avatar_backfill_preserves_existing_custom_urls():
    config = type("Config", (), {"avatar": {}})()
    state = {
        "dim_employee": pd.DataFrame({
            "Employee_Key": [1, 2],
            "Gender": ["M", "F"],
            "Avatar_URL": [None, "https://example.test/custom.png"],
        })
    }

    result = ensure_employee_avatars(state, config)["dim_employee"]

    assert result.loc[0, "Avatar_URL"].endswith((
        "male1.png", "male2.png", "male3.png", "male4.png", "neutral1.png", "neutral2.png"
    ))
    assert result.loc[1, "Avatar_URL"] == "https://example.test/custom.png"


def test_avatar_blob_discovery_and_reassignment_are_configurable(monkeypatch):
    config = type("Config", (), {
        "avatar": {
            "base_url": "https://example.test/hr-data/images",
            "auto_discover_from_blob": True,
            "reassign_existing_avatars": True,
            "neutral_probability_for_binary_gender": 0.0,
        }
    })()
    monkeypatch.setattr(
        AvatarAssigner,
        "_discover_blob_images",
        lambda self, _: {
            "male": ("male5.png",),
            "female": ("female5.png",),
            "neutral": ("neutral3.png",),
        },
    )

    state = {
        "dim_employee": pd.DataFrame({
            "Employee_Key": [1, 2, 3],
            "Gender": ["M", "F", "Anders"],
            "Avatar_URL": [
                "https://example.test/old.png",
                "https://example.test/old.png",
                "https://example.test/old.png",
            ],
        })
    }

    result = ensure_employee_avatars(state, config)["dim_employee"]

    assert result["Avatar_FileName"].tolist() == [
        "male5.png", "female5.png", "neutral3.png"
    ]
    assert result["Avatar_URL"].str.endswith(
        ("male5.png", "female5.png", "neutral3.png")
    ).all()


def test_engagement_effect_on_performance_review_is_capped():
    config = type("Config", (), {
        "engagement": {"performance_review_effect": 0.08}
    })()
    simulator = PerformanceSimulator(config, schema=None, rng=random.Random(42))

    low = simulator._engagement_review_effect(1.0)
    high = simulator._engagement_review_effect(10.0)

    assert low < -0.12
    assert high > 0.12
    assert max(-0.12, min(0.12, low)) == -0.12
    assert max(-0.12, min(0.12, high)) == 0.12


def test_absence_satisfaction_is_stamped_as_of_episode_start():
    config = type("Config", (), {
        "satisfaction": {
            "baseline_mean": 7.0,
            "individual_spread": 0.0,
            "performance_effect": 0.0,
            "manager_effect_spread": 0.0,
            "tenure_adjustments": {},
        }
    })()
    state = {
        "dim_employee": pd.DataFrame({
            "Employee_Key": [1],
            "Performance_Score": [3.4],
            "Aaneengesloten_Indienst_Datum": [pd.Timestamp("2020-01-01")],
            "Manager_Key": [None],
        }),
        "dim_role": pd.DataFrame({
            "Role_Key": [1], "Department_Key": [1]
        }),
        "dim_department": pd.DataFrame({
            "Department_Key": [1], "Department_Name": ["IT"]
        }),
        "dim_satisfaction_band": pd.DataFrame({
            "SatisfactionBand_Key": [1, 2],
            "Minimum_Score": [1.0, 6.0],
            "Maximum_Score": [5.99, 10.0],
        }),
        "fact_employment": pd.DataFrame({
            "Employment_Key": [1],
            "Employee_Key": [1],
            "Role_Key": [1],
            "Startdatum": [pd.Timestamp("2020-01-01")],
            "Einddatum": [None],
            "Target_Compa_Ratio": [1.0],
        }),
        "fact_absence": pd.DataFrame({
            "Absence_Key": [1],
            "Employee_Key": [1],
            "Startdatum": [pd.Timestamp("2025-03-01")],
        }),
        "fact_performance_review": pd.DataFrame(),
        "fact_manager_assignment": pd.DataFrame(),
    }

    result = sync_absence_satisfaction(state, config)
    episode = result["fact_absence"].iloc[0]

    assert pd.notna(episode["Tevredenheid_Score_Bij_Aanvang"])
    assert episode["SatisfactionBand_Key"] == 2


def test_absence_leave_eligibility_respects_gender_and_shift_work():
    config = type("Config", (), {"absence": {}})()
    simulator = AbsenceSimulator(config, schema=None, rng=random.Random(42))
    employment = pd.Series({
        "Employment_Key": 1,
        "Startdatum": pd.Timestamp("2020-01-01"),
        "Shift_Key": 3
    })
    state = {"dim_shift": pd.DataFrame({
        "Shift_Key": [0, 2, 3],
        "Shift_Name": ["Niet van toepassing", "2-ploeg", "3-ploeg"]
    })}
    empty_absence = pd.DataFrame(columns=[
        "Employee_Key", "AbsenceType_Key", "Startdatum"
    ])
    pregnancy_type = {
        "AbsenceType_Key": 4,
        "AbsenceType_Name": "Zwangerschap"
    }
    time_for_time_type = {
        "AbsenceType_Key": 9,
        "AbsenceType_Name": "Tijd voor tijd"
    }
    pregnancy_rule = {
        "genders": ["F"],
        "min_age": 20,
        "max_age": 45,
        "max_events_per_year": 1
    }
    time_for_time_rule = {
        "required_ploegendienst": ["2-ploeg", "3-ploeg"]
    }
    today = pd.Timestamp("2024-01-01")
    woman = {"Employee_Key": 1, "Gender": "F", "Geboortedatum": pd.Timestamp("1990-01-01")}
    man = {"Employee_Key": 2, "Gender": "M", "Geboortedatum": pd.Timestamp("1990-01-01")}

    assert simulator._eligible_for_leave_type(
        woman, employment, state, pregnancy_type, pregnancy_rule,
        empty_absence, [], today
    )
    assert not simulator._eligible_for_leave_type(
        man, employment, state, pregnancy_type, pregnancy_rule,
        empty_absence, [], today
    )
    assert simulator._eligible_for_leave_type(
        woman, employment, state, time_for_time_type, time_for_time_rule,
        empty_absence, [], today
    )


def test_absence_simulator_can_generate_non_sickness_leave():
    class AlwaysIncidentRandom(random.Random):
        def random(self):
            return 0.0

    config = type("Config", (), {
        "absence": {
            "annual_event_rate": 0.0,
            "age_multipliers": {},
            "ploegendienst_multipliers": {},
            "type_weights": {},
            "leave_type_rules": {
                "Vakantie": {
                    "annual_probability": 0.999,
                    "max_events_per_year": 1
                }
            },
            "duration_ranges_by_type": {
                "Vakantie": [{
                    "min_days": 14,
                    "mode_days": 21,
                    "max_days": 28,
                    "weight": 1.0
                }]
            }
        }
    })()
    simulator = AbsenceSimulator(config, schema=None, rng=AlwaysIncidentRandom(42))
    employee = {
        "Employee_Key": 1,
        "Gender": "F",
        "Geboortedatum": pd.Timestamp("1990-01-01")
    }
    employment = pd.Series({
        "Employment_Key": 1,
        "Startdatum": pd.Timestamp("2020-01-01")
    })
    vacation = {
        "AbsenceType_Key": 8,
        "AbsenceType_Name": "Vakantie",
        "Telt_als_verzuim": False
    }

    result = simulator._choose_incident_type(
        employee, employment, [vacation], {}, pd.DataFrame(), [],
        pd.Timestamp("2024-01-01")
    )

    assert result == vacation


def test_compound_growth_path_stays_far_below_capacity_in_2026():
    active_employment = pd.DataFrame({
        "Dienstverband_status": ["Actief"] * 50
    })
    config = {
        "start_year_simulation": 2020,
        "growth": {
            "economic_events": [{
                "start_date": "2020-03-01",
                "end_date": "2021-06-30",
                "target_multiplier": 0.90,
                "replacement_hiring_rate": 0.45
            }]
        }
    }

    covid_hiring = calculate_growth_target(
        active_employment, config, 50, 800, 2020, 20, 0.22, 0,
        random.Random(42)
    )
    hiring_in_2026 = calculate_growth_target(
        active_employment, config, 50, 800, 2026, 1, 0.22, 0,
        random.Random(42)
    )

    assert covid_hiring == 0
    assert 100 < hiring_in_2026 < 150


# =====================================================
# Database write order
# =====================================================

def test_departure_context_uses_original_source_and_last_known_satisfaction():
    state = {
        "dim_employee": pd.DataFrame({
            "Employee_Key": [1, 2],
            "HireSource_Key": [4, 2],
        }),
        "fact_employment": pd.DataFrame({
            "Employment_Key": [10, 20],
            "Employee_Key": [1, 2],
            "Dienstverband_status": ["Uit dienst", "Actief"],
            "Einddatum": pd.to_datetime(["2024-04-15", None]),
        }),
        "fact_workforce_snapshot": pd.DataFrame({
            "Employee_Key": [1, 1, 2],
            "Snapshot_Date": pd.to_datetime([
                "2024-03-31",
                "2024-04-30",
                "2024-03-31",
            ]),
            "Tevredenheid_Score": [5.8, 8.2, 7.4],
            "SatisfactionBand_Key": [2, 4, 3],
        }),
    }

    result = sync_employment_hire_sources(state)
    result = sync_departure_satisfaction(result)
    leaver = result["fact_employment"].iloc[0]

    assert leaver["HireSource_Key"] == 4
    assert leaver["Tevredenheid_Score_Bij_Uitdienst"] == 5.8
    assert leaver["SatisfactionBand_Key_Bij_Uitdienst"] == 2
    assert pd.isna(
        result["fact_employment"].iloc[1][
            "Tevredenheid_Score_Bij_Uitdienst"
        ]
    )


def test_insert_chunksize_stays_below_sql_server_parameter_limit():
    wide_fact = pd.DataFrame(columns=[f"column_{index}" for index in range(30)])
    narrow_dimension = pd.DataFrame(
        columns=[f"column_{index}" for index in range(10)]
    )

    assert write_to_sql.get_insert_chunksize(wide_fact) == 66
    assert write_to_sql.get_insert_chunksize(narrow_dimension) == 100


def test_table_write_order_respects_foreign_key_dependencies():
    schema = {
        "dim_role": {
            "foreign_keys": [
                ["SalaryScale_Key", "dim_salary_scale", "SalaryScale_Key"]
            ]
        },
        "dim_salary_scale": {},
        "fact_employment": {
            "foreign_keys": [
                ["Role_Key", "dim_role", "Role_Key"],
                ["Previous_Employment_Key", "fact_employment", "Employment_Key"],
            ]
        },
        "fact_workforce_snapshot": {
            "foreign_keys": [
                ["Employment_Key", "fact_employment", "Employment_Key"]
            ]
        },
        "simulation_state": {},
    }

    order = write_to_sql.get_table_write_order(schema)

    assert order.index("dim_salary_scale") < order.index("dim_role")
    assert order.index("dim_role") < order.index("fact_employment")
    assert order.index("fact_employment") < order.index("fact_workforce_snapshot")
    assert "simulation_state" not in order


# =====================================================
# 🔹 Debug run
# =====================================================

def run_debug():

    config = ConfigLoader().load()

    rng = random.Random(config.simulation_seed)
    today = pd.Timestamp(datetime.now())

    state = build_initial_state(config)

    schema = None  # build_record kan hiermee omgaan

    state = generate_employees(
        state=state,
        config=config,
        schema=schema,
        rng=rng,
        today=today
    )

    return state


# =====================================================
# 🔹 Main
# =====================================================

if __name__ == "__main__":

    state = run_debug()

# =====================================================
# 🔍 VALIDATIE CHECKS
# =====================================================

    dim_employee = state["dim_employee"]
    fact_employment = state["fact_employment"]

    assert dim_employee["Employee_Key"].is_unique, \
        "Employee_Key is niet uniek!"

    assert fact_employment["Employee_Key"].notnull().all(), \
        "Er zitten NULL Employee_Keys in fact_employment!"

    assert fact_employment["Employment_Key"].is_unique, \
        "Employment_Key is niet uniek!"

    assert "Manager_Key" in dim_employee.columns, \
        "Manager_Key ontbreekt in dim_employee!"

    assert dim_employee["Manager_Key"].notnull().any(), \
        "Geen managers zijn opgeslagen in dim_employee!"

    print("\n✅ VALIDATION PASSED")

# =====================================================
# 🔹 Output
# =====================================================

    print("\n=== DIM EMPLOYEE ===")
    print(state["dim_employee"].head())

    print("\n=== FACT EMPLOYMENT ===")
    print(state["fact_employment"].head())

    print("\n=== CHECKS ===")
    print("Employees:", len(state["dim_employee"]))
    print("Unique keys:", state["dim_employee"]["Employee_Key"].nunique())
    print("Nulls:\n", state["dim_employee"].isnull().sum())
