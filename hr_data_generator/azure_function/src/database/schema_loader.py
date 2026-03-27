import json
import os


def load_schema(schema_name):

    # Bepaal project root (2 niveaus omhoog vanaf src/database)
    base_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..")
    )

    path = os.path.join(
        base_dir,
        "config",
        "schemas",
        f"{schema_name}.json"
    )

    with open(path, "r") as f:
        return json.load(f)