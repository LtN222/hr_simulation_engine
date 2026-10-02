"""The HTTP error reply: generic when deployed, full text on a local `func start`."""
import contextlib
import logging

import pytest

import function_app

SECRET = "pyodbc.Error: Login failed on server hr-secret.database.windows.net, database db_hr_demo"


def _call_http(monkeypatch):
    monkeypatch.setattr(function_app, "load_runtime_config", lambda: {"simulation_mode": "incremental"})

    def failing_pipeline(mode, use_validation_settings=True):
        raise RuntimeError(SECRET)

    monkeypatch.setattr(function_app, "run_hr_pipeline", failing_pipeline)
    handler = function_app.generate_hr_data._function.get_user_function()
    response = handler(object())
    return response.status_code, response.get_body().decode()


def test_the_deployed_app_returns_a_generic_500_with_a_reference_and_logs_the_full_error(monkeypatch, caplog):
    monkeypatch.delenv("AZURE_FUNCTIONS_ENVIRONMENT", raising=False)

    with caplog.at_level(logging.ERROR):
        status, body = _call_http(monkeypatch)

    assert status == 500
    assert "hr-secret" not in body and "db_hr_demo" not in body and "Login failed" not in body
    assert "reference " in body and " UTC" in body
    reference = body.split("reference ")[1].rstrip(".")
    assert reference in caplog.text                       # the log carries the same reference
    assert SECRET in caplog.text                          # logging.exception keeps the full error and traceback
    assert "Traceback" in caplog.text


def test_a_local_func_start_returns_the_full_error_text_and_still_logs_it(monkeypatch, caplog):
    monkeypatch.setenv("AZURE_FUNCTIONS_ENVIRONMENT", "Development")

    with caplog.at_level(logging.ERROR):
        status, body = _call_http(monkeypatch)

    assert status == 500
    assert body == f"Error during HR data generation: {SECRET}"
    assert SECRET in caplog.text and "Traceback" in caplog.text


@pytest.mark.parametrize("environment", ["Production", "development", ""])
def test_only_the_exact_development_value_counts_as_local(monkeypatch, environment):
    monkeypatch.setenv("AZURE_FUNCTIONS_ENVIRONMENT", environment)

    status, body = _call_http(monkeypatch)

    assert status == 500 and SECRET not in body


def test_the_lock_is_handed_to_the_sql_store(monkeypatch):
    seen = {}
    lock = object()
    monkeypatch.setattr(function_app, "load_runtime_config", lambda: {
        "sector": "x", "simulation_seed": 1, "simulation_dry_run": False, "simulation_as_of": None})
    monkeypatch.setattr(function_app, "get_engine", lambda database: object())
    monkeypatch.setattr(function_app, "load_schema", lambda name: {})
    monkeypatch.setattr(function_app, "ConfigLoader", lambda: type("L", (), {
        "load": lambda self, sector=None: type("C", (), {"database": "db", "schema": "s"})()})())
    monkeypatch.setattr(function_app, "acquire_simulation_lock", lambda engine: contextlib.nullcontext(lock))
    monkeypatch.setattr(function_app, "SqlStore",
                        lambda engine, schema, dry_run=False, lock=None: seen.update(lock=lock))
    monkeypatch.setattr(function_app, "run_pipeline", lambda *args: ({}, {}))

    function_app.run_hr_pipeline("incremental")

    assert seen["lock"] is lock
