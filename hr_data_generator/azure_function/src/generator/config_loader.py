import json
from pathlib import Path


def load_config(sector: str) -> dict:
    """
    Deze functie laadt de sectorconfig uit /config/<sector>.json
    """
    base_path = Path(__file__).resolve().parents[2]  # project root
    config_path = base_path / "config" / f"{sector}.json"

    if not config_path.exists():
        raise FileNotFoundError(f"Config niet gevonden: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    return config