import random

import pandas as pd
import pytest

from src.infrastructure.salary_policy import SalaryPolicy


def _policy(allowances=None, growth=0.025, base_date="2020-01-01", medians=None, scales=None):
    config = type("Config", (), {
        "salary_benchmark": {
            "base_date": base_date,
            "annual_market_growth_rate": growth,
            "market_median_by_role": medians or {"Productiemedewerker": 30000},
            "compa_ratio": {"minimum_ratio": 0.75},
            "legal_minimum_salary": {
                "reference_year": 2026,
                "annual_full_time_salary": 31179,
                "allowances": {"vakantiegeld": 0.08} if allowances is None else allowances,
            },
        },
        "dim_salary_scale": scales or [
            {"SalaryScale_Key": 1, "Minimum_Salaris": 25000,
             "Maximum_Salaris": 40000, "Aantal_Treden": 1},
        ],
    })()
    return SalaryPolicy(config)


def _role(scale_key=1):
    return pd.Series({"Functie_Naam": "Productiemedewerker", "Salaris_min": 1,
                      "Salaris_max": 2, "SalaryScale_Key": scale_key})


def test_legal_minimum_in_the_reference_year_is_the_rounded_up_annual_amount_with_allowances():
    policy = _policy()

    assert policy.legal_minimum(pd.Timestamp("2026-01-01")) == 33674


def test_legal_minimum_is_indexed_back_with_the_market_growth_rate():
    policy = _policy()
    years = (pd.Timestamp("2026-01-01") - pd.Timestamp("2020-01-01")).days / 365.2425

    expected = 33674 / (1.025 ** years)

    assert policy.legal_minimum(pd.Timestamp("2020-01-01")) == pytest.approx(expected, abs=1)
    assert policy.legal_minimum(pd.Timestamp("2020-01-01")) < policy.legal_minimum(
        pd.Timestamp("2023-01-01")
    ) < 33674


def test_legal_minimum_is_flat_before_the_benchmark_base_date_and_grows_afterwards():
    policy = _policy()

    assert policy.legal_minimum(pd.Timestamp("2018-06-01")) == policy.legal_minimum(
        pd.Timestamp("2020-01-01")
    )
    assert policy.legal_minimum(pd.Timestamp("2027-01-01")) > 33674


def test_legal_minimum_allowances_add_up_including_extra_entries():
    policy = _policy(allowances={"vakantiegeld": 0.08, "eindejaarsuitkering": 0.04})

    # 31179 * 1.12 = 34920.48 -> rounded up
    assert policy.legal_minimum(pd.Timestamp("2026-01-01")) == 34921
    assert _policy(allowances={}).legal_minimum(pd.Timestamp("2026-01-01")) == 31179
    assert _policy(allowances={"vakantiegeld": 0.08, "eindejaarsuitkering": 0.0}).legal_minimum(
        pd.Timestamp("2026-01-01")
    ) == 33674


def test_legal_minimum_is_zero_without_configuration():
    policy = SalaryPolicy(type("Config", (), {
        "salary_benchmark": {},
        "dim_salary_scale": [{"SalaryScale_Key": 1, "Minimum_Salaris": 0,
                              "Maximum_Salaris": None, "Aantal_Treden": 1}],
    })())

    assert policy.apply_floor(1000, pd.Timestamp("2024-01-01")) == 1000


def test_every_salary_path_uses_the_date_dependent_floor():
    policy = _policy(medians={"Productiemedewerker": 20000})
    role = _role()
    start = pd.Timestamp("2020-01-01")
    for today in (pd.Timestamp("2020-06-01"), pd.Timestamp("2026-06-01")):
        floor = policy.legal_minimum(today)
        benchmark = policy.employee_benchmark(role, today, start)

        initial, _ = policy.initial_salary(role, "Productie", today, start, random.Random(3), True)
        reviewed, _ = policy.review_salary(role, None, start, today, 20000, 0.8, 3.5)

        assert initial == floor
        assert reviewed == floor
        assert policy.salary_for_ratio(benchmark, 0.8, today) == floor
        assert policy.apply_floor(45000, today) == 45000
    assert policy.legal_minimum(pd.Timestamp("2020-06-01")) < policy.legal_minimum(
        pd.Timestamp("2026-06-01")
    )


def test_role_benchmark_keeps_an_open_ended_scale_maximum_none():
    policy = _policy(
        medians={"Productiemedewerker": 120000},
        scales=[{"SalaryScale_Key": 1, "Minimum_Salaris": 105000,
                 "Maximum_Salaris": None, "Aantal_Treden": 10}],
    )

    benchmark = policy.role_benchmark(_role(), pd.Timestamp("2024-01-01"))

    assert benchmark["Schaal_Max_Salaris"] is None
    assert benchmark["Schaal_Min_Salaris"] > 105000
    assert benchmark["Markt_Mediaan"] > 120000
