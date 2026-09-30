import azure.functions as func
import logging
import sys
import os


# -----------------------------------------------------
# 0️⃣ Project modules beschikbaar maken
# -----------------------------------------------------

sys.path.append(
    os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..")
    )
)

# -----------------------------------------------------
# 1️⃣ Project modules importeren
# -----------------------------------------------------

from datetime import datetime

from src.application.pipeline import run_pipeline, validate_mode
from src.application.run_options import resolve_run_options
from src.infrastructure.database.write_to_sql import get_engine
from src.infrastructure.state.store import SqlStore
from src.infrastructure.database.schema_loader import load_schema
from src.infrastructure.database.simulation_lock import (
    SimulationAlreadyRunningError,
    acquire_simulation_lock
)
from src.core.config_loader import ConfigLoader
from config.runtime_config import load_runtime_config

# -----------------------------------------------------
# 2️⃣ Function app initialiseren
# -----------------------------------------------------

app = func.FunctionApp()


# =====================================================
# 🔹 CORE PIPELINE (gedeeld)
# =====================================================

def run_hr_pipeline(mode: str, use_validation_settings: bool = True):
    """Run the pipeline. The validation settings (HR_SIMULATION_AS_OF and
    HR_SIMULATION_DRY_RUN) are ignored when `use_validation_settings` is False
    (the timer: always the real date, always commit)."""

    runtime_config = dict(load_runtime_config())
    if not use_validation_settings:
        runtime_config["simulation_dry_run"] = False
        runtime_config["simulation_as_of"] = None

    # Validate the options before anything touches SQL.
    mode, dry_run, today = resolve_run_options(
        mode,
        runtime_config["simulation_dry_run"],
        runtime_config["simulation_as_of"],
    )

    sector = runtime_config["sector"]
    seed = runtime_config["simulation_seed"]

    # Config and schema are loaded exactly once per run and passed down.
    sector_config = ConfigLoader().load(sector)
    database_name = sector_config.database

    engine = get_engine(database_name)

    logging.info("HR data generation triggered")
    logging.info(f"Simulation mode: {mode}, as of {today:%Y-%m-%d}, dry run: {dry_run}")

    # -------------------------------------------------
    # Schema laden
    # -------------------------------------------------

    schema_name = sector_config.schema

    if not schema_name:
        raise ValueError("Sector config must contain a 'schema' field.")

    schema_config = load_schema(schema_name)

    logging.info(f"Using schema: {schema_name}")

    # -------------------------------------------------
    # Simulatie uitvoeren en schrijven (een pipeline voor beide modi)
    # -------------------------------------------------

    with acquire_simulation_lock(engine):
        dataframes, summary = run_pipeline(
            mode,
            sector_config,
            schema_config,
            seed,
            SqlStore(engine, schema_config, dry_run=dry_run),
            today
        )

    if dry_run:
        logging.info(f"DRY RUN - nothing was changed. Rows per table: {summary}")
    else:
        logging.info(
            f"Dataset successfully written to SQL. "
            f"Tables generated: {list(dataframes.keys())}"
        )

    return dataframes, summary


def _describe_changes(summary):
    """One line per table with changes: added/updated/deleted (unchanged omitted)."""
    parts = []
    for table, counts in summary.items():
        if counts.get("added") or counts.get("updated") or counts.get("deleted"):
            parts.append(
                f"{table}: +{counts.get('added', 0)} ~{counts.get('updated', 0)} "
                f"-{counts.get('deleted', 0)}"
            )
    return "; ".join(parts) or "No table has changes."


# =====================================================
# 🔹 HTTP endpoint (manual trigger)
# =====================================================

@app.route(
    route="generate_hr_data",
    auth_level=func.AuthLevel.FUNCTION
)
def generate_hr_data(req: func.HttpRequest) -> func.HttpResponse:

    try:

        runtime_config = load_runtime_config()
        mode = validate_mode(runtime_config["simulation_mode"])

        dataframes, summary = run_hr_pipeline(mode)

        # -------------------------------------------------
        # Response bouwen
        # -------------------------------------------------

        if mode == "incremental":

            employees_added = summary.get("dim_employee", {}).get("added", 0)
            employments_added = summary.get("fact_employment", {}).get("added", 0)

            message = (
                f"Incremental update complete: "
                f"+{employees_added} employees, "
                f"+{employments_added} employments."
            )
            if runtime_config["simulation_dry_run"]:
                message = (
                    "DRY RUN - rolled back, nothing was changed. "
                    + _describe_changes(summary)
                )

        else:
            total = len(dataframes["dim_employee"])

            message = f"Full HR dataset generated ({total} employees)."

        return func.HttpResponse(message, status_code=200)

    except SimulationAlreadyRunningError as exc:
        return func.HttpResponse(str(exc), status_code=409)

    except Exception as e:

        logging.exception("HR data generation failed")

        return func.HttpResponse(
            f"Error during HR data generation: {str(e)}",
            status_code=500
        )


# =====================================================
# 🔹 TIMER TRIGGER (wekelijkse incremental)
# =====================================================

@app.timer_trigger(
    schedule="%HR_TIMER_SCHEDULE%",  # elke maandag 02:00
    arg_name="timer",
    run_on_startup=False
)
def weekly_hr_run(timer: func.TimerRequest):

    logging.info("Weekly HR incremental job triggered")

    try:

        runtime_config = load_runtime_config()
        if runtime_config["simulation_dry_run"] or runtime_config["simulation_as_of"]:
            logging.warning(
                "HR_SIMULATION_AS_OF / HR_SIMULATION_DRY_RUN are set but are ignored "
                "for the timer: it always runs as of the real date and always commits. "
                "Remove them from the app settings after validation."
            )

        # 👉 altijd incremental, altijd de echte datum, altijd committen
        dataframes, summary = run_hr_pipeline("incremental", use_validation_settings=False)

        employees_added = summary.get("dim_employee", {}).get("added", 0)
        employments_added = summary.get("fact_employment", {}).get("added", 0)

        logging.info(
            f"Weekly incremental complete: "
            f"+{employees_added} employees, "
            f"+{employments_added} employments."
        )

    except SimulationAlreadyRunningError:
        logging.info("Weekly HR run skipped because another run is in progress")

    except Exception:
        # Re-raise after logging: a caught-and-swallowed exception here still
        # returns normally, so Azure Functions has no way to know the run
        # failed and marks the invocation Succeeded regardless.
        logging.exception("Weekly HR job failed")
        raise
