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

    return config