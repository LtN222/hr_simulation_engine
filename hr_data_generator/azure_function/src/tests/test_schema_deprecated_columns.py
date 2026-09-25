from src.infrastructure.database.schema_loader import load_schema


def test_known_legacy_columns_stay_marked_deprecated():
    """Regression test for AR-07 (see BACKLOG.md "Architecture review"):
    these columns were renamed in the schema at some point but the SQL
    columns themselves were never dropped, because a full run only inserts
    and `_ensure_table_columns` only adds columns - nothing ever removes a
    column that is no longer in the schema except `_drop_deprecated_columns`,
    which only acts on names listed here. If one of these is ever removed
    from `deprecated_columns` without the column having actually been
    confirmed gone from SQL, the leftover NULL column silently comes back."""
    schema = load_schema("hr_maakindustrie_schema")

    expected = {
        "dim_employee": {"Leeftijd", "EducationLevel_Key"},
        "fact_absence": {"AbsenceDuration_Key", "Ploegendienst_Key"},
        "fact_employment": {
            "Target_Compa_Ratio", "RedenVertrek_Key", "Ploegendienst_Key"
        },
        "fact_safety_incident": {"Absence_Key", "Ploegendienst_Key"},
        "fact_workforce_snapshot": {
            "Performance_Score", "SalaryStep", "EducationLevel_Key",
            "Ploegendienst_Key",
        },
    }

    for table, columns in expected.items():
        deprecated = set(schema[table].get("deprecated_columns", []))
        assert columns <= deprecated, (
            f"{table} is missing deprecated_columns entries for "
            f"{columns - deprecated}"
        )


def test_deprecated_columns_are_not_also_declared_as_live_columns():
    """A column cannot be both deprecated and part of the live schema - that
    would make `_ensure_table_columns` re-add the very column
    `_drop_deprecated_columns` just removed."""
    schema = load_schema("hr_maakindustrie_schema")

    for table, config in schema.items():
        if not isinstance(config, dict):
            continue
        deprecated = set(config.get("deprecated_columns", []))
        live = set(config.get("types", {}))
        overlap = deprecated & live
        assert not overlap, f"{table} declares {overlap} as both live and deprecated"
