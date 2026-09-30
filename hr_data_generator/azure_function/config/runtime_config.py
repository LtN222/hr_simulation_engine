import os

def load_runtime_config():

    config = {}

    config["sector"] = os.environ.get(
        "HR_SECTOR",
        "maakindustrie"
    )

    config["simulation_weeks"] = int(
        os.environ.get("HR_SIMULATION_WEEKS", 104)
    )

    config["simulation_seed"] = int(
        os.environ.get("HR_SIMULATION_SEED", 42)
    )

    config["simulation_mode"] = str(
        os.environ.get("HR_SIMULATION_MODE", "incremental")
    )

    # Validation helpers (see README "Lokaal draaien"): a dry run executes the
    # whole write transaction and rolls it back; an as-of date replaces "today".
    config["simulation_dry_run"] = os.environ.get(
        "HR_SIMULATION_DRY_RUN", "false"
    ).strip().lower() in ("1", "true", "yes")

    config["simulation_as_of"] = os.environ.get("HR_SIMULATION_AS_OF") or None

    return config