"""Ploegendienst assignment shared by initial generation and later hires."""

import pandas as pd

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


def carry_or_assign_shift_key(previous_row, target_role, state, config, rng):
    """Shift for an internal move (promotion, transfer, internal mobility).

    - target role is not ploegendienst: "Niet van toepassing";
    - the previous row was shift work, the target role is ploegendienst and the
      department is unchanged: the person keeps their shift (no rng draw);
    - otherwise a fresh draw from the target department's mix, as for a hire.
    """
    not_applicable = _key_for_name(state["dim_shift"], "Niet van toepassing")
    if not bool(target_role.get("Ploegendienst_Flag", False)):
        return not_applicable

    previous_key = pd.to_numeric(previous_row.get("Shift_Key"), errors="coerce")
    if (
        pd.notna(previous_key)
        and int(previous_key) != not_applicable
        and _same_department(previous_row, target_role, state)
    ):
        return int(previous_key)
    return assign_ploegendienst_key(target_role, state, config, rng)


def _same_department(previous_row, target_role, state):
    roles = state.get("dim_role")
    if roles is None or roles.empty:
        return False
    previous = roles.loc[roles["Role_Key"] == previous_row.get("Role_Key"), "Department_Key"]
    return not previous.empty and previous.iloc[0] == target_role.get("Department_Key")


def _key_for_name(shifts, name):
    matching = shifts.loc[
        shifts["Ploegendienst_Naam"] == name,
        "Shift_Key"
    ]
    if matching.empty:
        raise ValueError(f"Ploegendienst '{name}' is not configured.")
    return int(matching.iloc[0])
