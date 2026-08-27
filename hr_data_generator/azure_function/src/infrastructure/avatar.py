"""Stable avatar assignment for the employee dimension.

The reporting layer consumes public Blob Storage URLs.  Avatar selection is
derived from the employee key plus a configured seed rather than the simulation
RNG, so a full rebuild and future incremental runs keep the same portrait.
"""

from dataclasses import dataclass
from hashlib import sha256
import os
from urllib.parse import urlparse

import pandas as pd


DEFAULT_BASE_URL = (
    "https://stdemodashboards.blob.core.windows.net/hr-data/images"
)
DEFAULT_ASSIGNMENT_SEED = "hr-demo-avatar-v1"
DEFAULT_IMAGE_POOLS = {
    "male": ("male1.png", "male2.png", "male3.png", "male4.png"),
    "female": ("female1.png", "female2.png", "female3.png", "female4.png"),
    "neutral": ("neutral1.png", "neutral2.png"),
}


@dataclass(frozen=True)
class Avatar:
    """The persistent avatar fields stored for one employee."""

    file_name: str
    url: str


class AvatarAssigner:
    """Assign a stable, gender-aware avatar from the configured image set."""

    def __init__(self, config):
        avatar_config = getattr(config, "avatar", {}) or {}
        self.base_url = avatar_config.get("base_url", DEFAULT_BASE_URL).rstrip("/")
        self.seed = str(avatar_config.get("assignment_seed", DEFAULT_ASSIGNMENT_SEED))
        self.neutral_probability = float(
            avatar_config.get("neutral_probability_for_binary_gender", 0.05)
        )
        self.reassign_existing = bool(
            avatar_config.get("reassign_existing_avatars", False)
        )
        self.image_pools = self._image_pools(config, avatar_config)

        if not 0.0 <= self.neutral_probability <= 1.0:
            raise ValueError(
                "avatar.neutral_probability_for_binary_gender must be between 0 and 1."
            )

    def assign(self, employee_key, gender) -> Avatar:
        """Return the same avatar for an employee across all simulation runs."""
        gender_group = _gender_group(gender)
        if gender_group in {"male", "female"} and (
            self._unit_interval(employee_key, "neutral")
            < self.neutral_probability
        ):
            gender_group = "neutral"

        images = self.image_pools[gender_group]
        file_name = images[self._integer(employee_key, "image") % len(images)]
        return Avatar(file_name=file_name, url=f"{self.base_url}/{file_name}")

    def _image_pools(self, config, avatar_config):
        """Resolve pools once per simulation run, including optional Blob discovery."""
        cached_pools = getattr(config, "_resolved_avatar_image_pools", None)
        if cached_pools is not None:
            return cached_pools

        pools = {
            group: tuple(avatar_config.get(f"{group}_images", defaults))
            for group, defaults in DEFAULT_IMAGE_POOLS.items()
        }
        if avatar_config.get("auto_discover_from_blob", False):
            discovered_pools = self._discover_blob_images(avatar_config)
            for group, images in discovered_pools.items():
                if images:
                    pools[group] = images

        missing_groups = [group for group, images in pools.items() if not images]
        if missing_groups:
            raise ValueError(
                "Avatar image pools cannot be empty: " + ", ".join(missing_groups)
            )

        setattr(config, "_resolved_avatar_image_pools", pools)
        return pools

    def _discover_blob_images(self, avatar_config):
        """List PNG avatars from Azure Blob Storage, grouped by filename prefix.

        Public container listing works without credentials. For a private
        container, set ``HR_AVATAR_BLOB_CONNECTION_STRING`` in Function App
        settings; it is deliberately not kept in the repository config.
        """
        try:
            from azure.storage.blob import BlobServiceClient
        except ImportError as exc:
            raise RuntimeError(
                "Install azure-storage-blob to enable avatar Blob discovery."
            ) from exc

        container_name = avatar_config.get("blob_container", "hr-data")
        prefix = avatar_config.get("blob_prefix", "images/").strip("/")
        prefix = f"{prefix}/" if prefix else ""
        connection_string = os.environ.get("HR_AVATAR_BLOB_CONNECTION_STRING")

        if connection_string:
            container_client = BlobServiceClient.from_connection_string(
                connection_string
            ).get_container_client(container_name)
        else:
            parsed_url = urlparse(self.base_url)
            account_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
            container_client = BlobServiceClient(
                account_url=account_url,
                credential=None,
            ).get_container_client(container_name)

        pools = {group: [] for group in DEFAULT_IMAGE_POOLS}
        try:
            blobs = container_client.list_blobs(name_starts_with=prefix)
            for blob in blobs:
                file_name = blob.name.removeprefix(prefix)
                if "/" in file_name or not file_name.casefold().endswith(".png"):
                    continue
                group = _image_group(file_name)
                if group:
                    pools[group].append(file_name)
        except Exception as exc:
            raise RuntimeError(
                "Could not list avatar images from Blob Storage. Make the "
                "container listable or configure HR_AVATAR_BLOB_CONNECTION_STRING."
            ) from exc

        return {
            group: tuple(sorted(images, key=str.casefold))
            for group, images in pools.items()
        }

    def _integer(self, employee_key, purpose):
        value = f"{self.seed}:{employee_key}:{purpose}".encode("utf-8")
        return int.from_bytes(sha256(value).digest()[:8], byteorder="big")

    def _unit_interval(self, employee_key, purpose):
        return self._integer(employee_key, purpose) / float(2**64)


def avatar_fields(config, employee_key, gender, assigner=None):
    """Return schema-ready avatar values for an employee record."""
    avatar = (assigner or AvatarAssigner(config)).assign(employee_key, gender)
    return {
        "Avatar_FileName": avatar.file_name,
        "Avatar_URL": avatar.url,
    }


def ensure_employee_avatars(state, config):
    """Backfill avatar fields for employees loaded from an older database.

    Existing non-empty URLs are retained. This makes the migration safe when a
    report or an administrator has deliberately supplied a custom portrait.
    """
    employees = state.get("dim_employee", pd.DataFrame()).copy()
    if employees.empty or "Employee_Key" not in employees.columns:
        return state

    if "Avatar_FileName" not in employees.columns:
        employees["Avatar_FileName"] = None
    if "Avatar_URL" not in employees.columns:
        employees["Avatar_URL"] = None

    assigner = AvatarAssigner(config)
    for index, employee in employees.iterrows():
        existing_url = employee.get("Avatar_URL")
        if (
            not assigner.reassign_existing
            and pd.notna(existing_url)
            and str(existing_url).strip()
        ):
            continue

        avatar = assigner.assign(employee["Employee_Key"], employee.get("Geslacht"))
        employees.at[index, "Avatar_FileName"] = avatar.file_name
        employees.at[index, "Avatar_URL"] = avatar.url

    state["dim_employee"] = employees
    return state


def _gender_group(gender):
    normalized = str(gender or "").strip().casefold()
    if normalized in {"m", "male", "man"}:
        return "male"
    if normalized in {"f", "female", "vrouw"}:
        return "female"
    return "neutral"


def _image_group(file_name):
    """Map documented filename prefixes to an avatar pool.

    Check ``female`` before ``male`` because the word "female" ends in
    "male". New discovered files should therefore use names such as
    ``female5.png``, ``male5.png`` or ``neutral3.png``.
    """
    normalized = file_name.casefold()
    if normalized.startswith("female"):
        return "female"
    if normalized.startswith("male"):
        return "male"
    if normalized.startswith("neutral"):
        return "neutral"
    return None
