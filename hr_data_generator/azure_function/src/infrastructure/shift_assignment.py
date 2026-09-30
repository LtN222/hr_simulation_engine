"""Ploegendienst assignment shared by initial generation and later hires."""

DEFAULT_SHIFT_VALUES = ["Dag", "2-ploeg", "3-ploeg"]
DEFAULT_SHIFT_WEIGHTS = [0.3, 0.4, 0.3]


def shift_mix(config, department_name):
    """Return (values, weights) of the shift mix for a department.

    `ploegendienst_assignment` holds the default mix; `by_department` may
    override `weights` (and optionally `values`) for a department.
    """
    assignment = getattr(config, "ploegendienst_assignment", {})
    values = assignment.get("values", DEFAULT_SHIFT_VALUES)
    weights = assignment.get("weights", DEFAULT_SHIFT_WEIGHTS)
    override = assignment.get("by_department", {}).get(department_name, {})
    return override.get("values", values), override.get("weights", weights)


def assign_ploegendienst_key(role_row, state, config, rng):
    """Return a normalised shift key for the role's employment record."""
    shifts = state["dim_shift"]
    not_applicable = _key_for_name(shifts, "Niet van toepassing")
    if not bool(role_row.get("Ploegendienst_Flag", False)):
        return not_applicable

    values, weights = shift_mix(config, role_row.get("Afdeling_Naam"))
    selected = rng.choices(values, weights=weights, k=1)[0]
    return _key_for_name(shifts, selected)


def _key_for_name(shifts, name):
    matching = shifts.loc[
        shifts["Ploegendienst_Naam"] == name,
        "Shift_Key"
    ]
    if matching.empty:
        raise ValueError(f"Ploegendienst '{name}' is not configured.")
    return int(matching.iloc[0])
