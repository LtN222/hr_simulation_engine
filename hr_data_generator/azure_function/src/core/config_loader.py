import json
import os

from config.runtime_config import load_runtime_config
from src.core.config import Config


class ConfigLoader:

    def __init__(self, base_path=None):
        self.base_path = base_path or os.path.dirname(
            os.path.dirname(os.path.dirname(__file__))
        )

    def load(self) -> Config:

        runtime_config = load_runtime_config()
        sector = runtime_config["sector"]

        json_config = self._load_sector_config(sector)

        # merge runtime + json
        config = {**json_config, **runtime_config}

        return Config(config)

    def _load_sector_config(self, sector):

        config_path = os.path.join(
            self.base_path,
            "config",
            f"{sector}.json"
        )

        with open(config_path, "r") as f:
            return json.load(f)
