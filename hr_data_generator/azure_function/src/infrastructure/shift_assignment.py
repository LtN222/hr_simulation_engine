"""Ploegendienst assignment shared by initial generation and later hires."""


def assign_ploegendienst_key(role_row, state, config, rng):
    """Return a normalised shift key for the role's employment record."""
    shifts = state["dim_shift"]
    not_applicable = _key_for_name(shifts, "Niet van toepassing")
    if not bool(role_row.get("Ploegendienst_Flag", False)):
        return not_applicable

    assignment = getattr(config, "ploegendienst_assignment", {})
    values = assignment.get("values", ["Dag", "2-ploeg", "3-ploeg"])
    weights = assignment.get("weights", [0.3, 0.4, 0.3])
    selected = rng.choices(values, weights=weights, k=1)[0]
    return _key_for_name(shifts, selected)


def _key_for_name(shifts, name):
    matching = shifts.loc[
        shifts["Shift_Name"] == name,
        "Shift_Key"
    ]
    if matching.empty:
        raise ValueError(f"Ploegendienst '{name}' is not configured.")
    return int(matching.iloc[0])
