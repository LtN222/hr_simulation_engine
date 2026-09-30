import pytest

from src.infrastructure.database.schema_loader import load_schema
from src.infrastructure.database.write_to_sql import _column_dependency_drop_commands


class _FakeCatalogConnection:
    """Answers the catalog queries of `_column_dependency_drop_commands` in order:
    foreign keys, indexes, default constraints, user-created statistics."""

    def __init__(self, foreign_keys=(), indexes=(), defaults=(), statistics=()):
        self._answers = [list(foreign_keys), list(indexes), list(defaults), list(statistics)]

    def execute(self, statement, parameters=None):
        rows = self._answers.pop(0)
        return type("Result", (), {"fetchall": lambda self: rows})()


def test_dependent_objects_are_dropped_before_the_column():
    """Regression test for the first real AR-07 run, which failed with
    "The index 'IX_fact_absence_Ploegendienst_Key' is dependent on column"."""
    conn = _FakeCatalogConnection(
        foreign_keys=[("FK_fact_absence_Ploegendienst_Key",)],
        indexes=[
            ("IX_fact_absence_Ploegendienst_Key", False, False),
            ("UQ_fact_absence_Ploegendienst_Key", False, True),
        ],
        defaults=[("DF_fact_absence_Ploegendienst_Key",)],
        statistics=[("ST_fact_absence_Ploegendienst_Key",)],
    )

    commands = _column_dependency_drop_commands(conn, "fact_absence", "Ploegendienst_Key")

    assert commands == [
        "ALTER TABLE [fact_absence] DROP CONSTRAINT [FK_fact_absence_Ploegendienst_Key]",
        "DROP INDEX [IX_fact_absence_Ploegendienst_Key] ON [fact_absence]",
        "ALTER TABLE [fact_absence] DROP CONSTRAINT [UQ_fact_absence_Ploegendienst_Key]",
        "ALTER TABLE [fact_absence] DROP CONSTRAINT [DF_fact_absence_Ploegendienst_Key]",
        "DROP STATISTICS [fact_absence].[ST_fact_absence_Ploegendienst_Key]",
    ]


def test_a_column_without_dependencies_needs_no_extra_statements():
    assert _column_dependency_drop_commands(
        _FakeCatalogConnection(), "fact_employment", "Target_Compa_Ratio"
    ) == []


def test_a_deprecated_primary_key_column_is_refused():
    conn = _FakeCatalogConnection(indexes=[("PK_fact_absence", True, False)])
    with pytest.raises(ValueError, match="primary key"):
        _column_dependency_drop_commands(conn, "fact_absence", "Absence_Key")


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
