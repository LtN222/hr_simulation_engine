import pandas as pd

from src.run_simulation_incremental import _normalize_date_columns


def _schema():
    return {
        "dim_candidate_quality_driver": {
            "types": {
                "CandidateQualityDriver_Key": "INT",
                "Factor_Naam": "NVARCHAR(100)",
            }
        },
        "fact_recruitment": {
            "types": {
                "Recruitment_Key": "INT",
                "Application_Date": "DATE",
                "Decision_Date": "DATE",
            }
        },
    }


def test_normalize_date_columns_does_not_corrupt_a_key_column_containing_date_as_a_substring():
    """Regression guard for a production incident: `CandidateQualityDriver_Key`
    contains the substring "date" (Candi-date-QualityDriver_Key), which a
    previous name-based heuristic (`"date" in col.lower()`) matched and then
    ran through `pd.to_datetime`, reinterpreting the small integer key values
    as nanosecond timestamps and corrupting them into indistinguishable
    1970-01-01 datetimes - which Azure SQL then rejected as an INT/datetime2
    type clash on every incremental run that needed to insert into this
    table. Which columns count as dates must come from the schema's own
    declared types, not a substring match on the column name."""
    state = {
        "dim_candidate_quality_driver": pd.DataFrame({
            "CandidateQualityDriver_Key": [1, 2, 3],
            "Factor_Naam": ["A", "B", "C"],
        }),
    }

    _normalize_date_columns(state, _schema())

    key_column = state["dim_candidate_quality_driver"]["CandidateQualityDriver_Key"]
    assert list(key_column) == [1, 2, 3]
    assert key_column.dtype.kind in "iu"


def test_normalize_date_columns_still_coerces_genuine_schema_declared_date_columns():
    state = {
        "fact_recruitment": pd.DataFrame({
            "Recruitment_Key": [1, 2],
            "Application_Date": ["2024-01-01", "2024-02-01"],
            "Decision_Date": [None, "2024-02-15"],
        }),
    }

    _normalize_date_columns(state, _schema())

    result = state["fact_recruitment"]
    assert pd.api.types.is_datetime64_any_dtype(result["Application_Date"])
    assert pd.api.types.is_datetime64_any_dtype(result["Decision_Date"])
    assert result["Application_Date"].iloc[0] == pd.Timestamp("2024-01-01")
    assert pd.isna(result["Decision_Date"].iloc[0])


def test_normalize_date_columns_ignores_tables_not_present_in_the_schema():
    state = {"vacancies": 0, "_recruitment_pipeline_profiles": {}}

    _normalize_date_columns(state, _schema())

    assert state["vacancies"] == 0
    assert state["_recruitment_pipeline_profiles"] == {}
