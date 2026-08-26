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

from src.run_simulation import run_simulation
from src.run_simulation_incremental import run_incremental_simulation
from src.infrastructure.database.write_to_sql import write_dataset, get_engine
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

def run_hr_pipeline(mode: str):

    runtime_config = load_runtime_config()

    sector = runtime_config["sector"]
    sector_config = ConfigLoader().load()

    database_name = sector_config.database
    seed = runtime_config["simulation_seed"]

    engine = get_engine(database_name)

    logging.info("HR data generation triggered")
    logging.info(f"Simulation mode: {mode}")

    # -------------------------------------------------
    # Schema laden
    # -------------------------------------------------

    schema_name = sector_config.schema

    if not schema_name:
        raise ValueError("Sector config must contain a 'schema' field.")

    schema_config = load_schema(schema_name)

    logging.info(f"Using schema: {schema_name}")

    # -------------------------------------------------
    # Simulatie uitvoeren
    # -------------------------------------------------

    with acquire_simulation_lock(engine):
        if mode == "full":
            dataframes = run_simulation(engine, sector, seed)
        else:
            dataframes = run_incremental_simulation(engine, sector, seed)

        logging.info(
            f"Simulation finished. Tables generated: {list(dataframes.keys())}"
        )

        # -------------------------------------------------
        # Dataset schrijven
        # -------------------------------------------------

        summary = write_dataset(
            engine,
            dataframes,
            schema_config,
            reset=(mode == "full")
        )

    logging.info("Dataset successfully written to SQL")

    return dataframes, summary


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
        mode = runtime_config["simulation_mode"]

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

        # 👉 altijd incremental
        dataframes, summary = run_hr_pipeline("incremental")

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
        logging.exception("Weekly HR job failed")
