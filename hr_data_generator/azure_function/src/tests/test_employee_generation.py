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
from src.infrastructure.dimension_factory import generate_dimensions
from src.infrastructure.employee_status import sync_employee_employment_status
from src.infrastructure.salary_snapshot import build_salary_snapshots
from src.generator.employment_factory import EmploymentFactory
from src.simulation.simulation_attrition import AttritionSimulator
from src.simulation.simulation_absence import AbsenceSimulator
from src.simulation.simulation_growth import calculate_growth_target
from src.simulation.simulation_career_events import _salary_review_week
from src.simulation.simulation_recruitment import RecruitmentSimulator


# =====================================================
# 🔹 State builder
# =====================================================

def build_initial_state(config):

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
                "Ploegendienst_Flag": role_cfg.get("ploegendienst", False)
            })

            role_key += 1

    dim_role = pd.DataFrame(roles)

    # 🔹 Dimensions
    dim_hire_source = pd.DataFrame({
        "HireSource_Key": list(range(1, len(config.dim_hire_source) + 1))
    })

    dim_education_level = pd.DataFrame({
        "EducationLevel": config.dim_education_level,
        "EducationLevel_Key": list(range(1, len(config.dim_education_level) + 1))
    })

    dim_location = pd.DataFrame({
        "Location_Name": list(config.dim_location.keys()),
        "Location_Key": list(range(1, len(config.dim_location) + 1))
    })

    dim_event_type = pd.DataFrame({
        "EventType": config.dim_event_type,
        "EventType_Key": list(range(1, len(config.dim_event_type) + 1))
    })

    # 🔹 Allocation
    role_allocations = allocate_headcount(
        config.structure,
        config.baseline_headcount
    )

    state = {
        "dim_role": dim_role,
        "dim_hire_source": dim_hire_source,
        "dim_education_level": dim_education_level,
        "dim_location": dim_location,
        "dim_event_type": dim_event_type,
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


def test_generate_dimensions_supports_salary_band_ranges():
    config = type("Config", (), {
        "get": lambda self, key, default=None: {
            "dim_salary_band": [
                {
                    "SalaryBand_Name": "Onder EUR 35.000",
                    "Minimum_Salaris": 0,
                    "Maximum_Salaris": 34999
                }
            ]
        }.get(key, default)
    })()
    schema = {
        "dim_salary_band": {
            "df": "dim_salary_band",
            "primary_key": "SalaryBand_Key",
            "types": {
                "SalaryBand_Key": "INT",
                "SalaryBand_Name": "NVARCHAR(50)",
                "Minimum_Salaris": "INT",
                "Maximum_Salaris": "INT"
            }
        }
    }

    result = generate_dimensions(config, schema)["dim_salary_band"]

    assert result.iloc[0].to_dict() == {
        "SalaryBand_Key": 1,
        "SalaryBand_Name": "Onder EUR 35.000",
        "Minimum_Salaris": 0,
        "Maximum_Salaris": 34999
    }


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


def test_salary_increases_with_tenure():
    role_row = {
        "Salaris_min": 4000,
        "Salaris_max": 6000
    }

    factory_new = EmploymentFactory(config=None, rng=random.Random(42))
    factory_old = EmploymentFactory(config=None, rng=random.Random(42))

    salary_new = factory_new._choose_salary(
        role_row,
        start_date=pd.Timestamp("2023-01-01"),
        today=pd.Timestamp("2024-01-01")
    )
    salary_old = factory_old._choose_salary(
        role_row,
        start_date=pd.Timestamp("2020-01-01"),
        today=pd.Timestamp("2024-01-01")
    )

    assert salary_old > salary_new


def test_new_hire_salary_uses_actual_start_date_not_fictional_tenure():
    role_row = {
        "Salaris_min": 40000,
        "Salaris_max": 60000
    }
    today = pd.Timestamp("2024-01-01")

    factory_with_old_date = EmploymentFactory(
        config=None,
        rng=random.Random(42)
    )
    factory_with_today_date = EmploymentFactory(
        config=None,
        rng=random.Random(42)
    )

    salary_with_old_date = factory_with_old_date._choose_salary(
        role_row,
        start_date=pd.Timestamp("2019-01-01"),
        today=today,
        is_new_hire=True
    )
    salary_with_today_date = factory_with_today_date._choose_salary(
        role_row,
        start_date=today,
        today=today,
        is_new_hire=True
    )

    assert salary_with_old_date == salary_with_today_date


def test_salary_review_weeks_are_spread_over_year():
    review_weeks = [
        _salary_review_week(employee_key)
        for employee_key in range(1, 101)
    ]

    assert min(review_weeks) >= 1
    assert max(review_weeks) <= 52
    assert len(set(review_weeks)) > 40


def test_salary_snapshot_uses_active_salary_per_month():
    state = {
        "dim_role": pd.DataFrame({
            "Role_Key": [1],
            "Department_Key": [10]
        }),
        "fact_employment": pd.DataFrame({
            "Employment_Key": [1, 2, 3],
            "Previous_Employment_Key": [None, 1, None],
            "Employee_Key": [1, 1, 2],
            "Role_Key": [1, 1, 1],
            "Startdatum": pd.to_datetime([
                "2024-01-01",
                "2024-03-01",
                "2024-01-01"
            ]),
            "Einddatum": pd.to_datetime([
                "2024-03-01",
                None,
                None
            ]),
            "Dienstverband_status": ["Inactief", "Actief", "Actief"],
            "Salaris": [40000, 42000, 50000]
        })
    }

    result = build_salary_snapshots(
        state,
        schema=None,
        start_date=pd.Timestamp("2024-01-01"),
        end_date=pd.Timestamp("2024-03-31")
    )

    snapshots = result["fact_salary_snapshot"]
    march = snapshots[
        snapshots["Snapshot_Date"] == pd.Timestamp("2024-03-31")
    ]

    assert len(march) == 2
    assert set(march["Salaris"]) == {42000, 50000}
    assert march["Salaris"].median() == 46000


def test_recruitment_acceptances_are_driven_by_open_vacancies():
    config = type("Config", (), {
        "recruitment": {
            "applications_per_hire_by_department": {"Productie": 1},
            "extra_open_applications_by_department": {"Productie": 0},
            "status_weights": {"Afgewezen": 1.0},
            "decision_days": {"min": 1, "max": 1}
        },
        "structure": {
            "Productie": {
                "Operator": {"fte_ratio": 1.0}
            }
        }
    })()

    state = {
        "dim_department": pd.DataFrame({
            "Department_Key": [1],
            "Department_Name": ["Productie"]
        }),
        "dim_role": pd.DataFrame({
            "Role_Key": [1],
            "Department_Key": [1],
            "Role_Name": ["Operator"]
        }),
        "dim_hire_source": pd.DataFrame({
            "HireSource_Key": [1]
        }),
        "fact_employment": pd.DataFrame({
            "Employee_Key": [10],
            "Role_Key": [1],
            "Dienstverband_status": ["Actief"]
        }),
        "fact_vacancy": pd.DataFrame({
            "Vacancy_Key": [1, 2],
            "Created_Date": pd.to_datetime(["2023-10-01", "2023-10-01"]),
            "Closed_Date": [None, None],
            "Role_Key": [1, 1],
            "Department_Key": [1, 1],
            "Vacancy_Reason": ["Growth", "Replacement"],
            "Status": ["Open", "Open"],
            "Target_Start_Date": pd.to_datetime(["2024-01-01", "2024-01-01"]),
            "Filled_Employee_Key": [None, None]
        }),
        "fact_recruitment": pd.DataFrame()
    }

    result = RecruitmentSimulator(
        config,
        schema=None,
        rng=random.Random(42)
    ).run(state, pd.Timestamp("2024-01-01"))

    accepted = result["fact_recruitment"][
        result["fact_recruitment"]["Status"] == "Aangenomen"
    ]

    assert len(accepted) >= 1
    assert accepted["Employee_Key"].isna().all()
    assert set(accepted["Vacancy_Key"]).issubset({1, 2})
    assert len(result["_accepted_applications"]) == len(accepted)


def test_attrition_uses_fact_employment_salary():
    config = type("Config", (), {
        "dim_reden_vertrek": {"vrijwillig": ["Ontslag"], "werkgever": ["Ontslag"]},
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
            "RedenVertrek_Key": [None],
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
        "dim_reden_vertrek": {
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
            "RedenVertrek_Key": [None, None],
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
    assert employment.loc[1, "RedenVertrek_Key"] == 2
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
            "attribute_multipliers": {},
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
            "Salaris": [55000],
            "Startdatum": [pd.Timestamp("2020-01-01")],
            "Einddatum": [None],
            "Contract_einddatum": [pd.Timestamp("2024-01-05")],
            "Dienstverband_status": ["Actief"]
        }),
        "fact_employment_attribute": pd.DataFrame(),
        "dim_role": pd.DataFrame({
            "Role_Key": [7],
            "Department_Key": [5]
        }),
        "dim_salary_band": pd.DataFrame({
            "SalaryBand_Key": [3],
            "Minimum_Salaris": [45000],
            "Maximum_Salaris": [59999]
        }),
        "dim_absence_type": pd.DataFrame({
            "AbsenceType_Key": [1, 2],
            "AbsenceType_Name": ["Ziek", "Lang verzuim"],
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
            "attribute_multipliers": {},
            "type_weights": {"Ziek": 1.0},
            "duration_distribution_by_type": {"Ziek": {"1": 1.0}}
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
        "fact_employment_attribute": pd.DataFrame(),
        "dim_absence_type": pd.DataFrame({
            "AbsenceType_Key": [1],
            "AbsenceType_Name": ["Ziek"],
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


def test_absence_leave_eligibility_respects_gender_and_shift_work():
    config = type("Config", (), {"absence": {}})()
    simulator = AbsenceSimulator(config, schema=None, rng=random.Random(42))
    employment = pd.Series({
        "Employment_Key": 1,
        "Startdatum": pd.Timestamp("2020-01-01")
    })
    attributes = pd.DataFrame({
        "Employment_Key": [1],
        "Attribute_Name": ["Ploegendienst"],
        "Attribute_Value": ["3-ploeg"]
    })
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
        "required_attribute": {
            "name": "Ploegendienst",
            "values": ["2-ploeg", "3-ploeg"]
        }
    }
    today = pd.Timestamp("2024-01-01")
    woman = {"Employee_Key": 1, "Gender": "F", "Geboortedatum": pd.Timestamp("1990-01-01")}
    man = {"Employee_Key": 2, "Gender": "M", "Geboortedatum": pd.Timestamp("1990-01-01")}

    assert simulator._eligible_for_leave_type(
        woman, employment, attributes, pregnancy_type, pregnancy_rule,
        empty_absence, [], today
    )
    assert not simulator._eligible_for_leave_type(
        man, employment, attributes, pregnancy_type, pregnancy_rule,
        empty_absence, [], today
    )
    assert simulator._eligible_for_leave_type(
        woman, employment, attributes, time_for_time_type, time_for_time_rule,
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
            "attribute_multipliers": {},
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
        employee, employment, [vacation], pd.DataFrame(), pd.DataFrame(), [],
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

    print("\n=== ATTRIBUTES ===")
    print(state["fact_employment_attribute"].head())

    print("\n=== CHECKS ===")
    print("Employees:", len(state["dim_employee"]))
    print("Unique keys:", state["dim_employee"]["Employee_Key"].nunique())
    print("Nulls:\n", state["dim_employee"].isnull().sum())
