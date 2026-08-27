"""Pure lateral moves between open production sites: same role, same
department, different location - distinct from a `Transfer` (which changes
role). Only `multi_site` roles participate. A small baseline flux runs
between every open production site; for a limited window after a new site
opens, an extra pull specifically toward that new site models people opting
in for a change of scenery.
"""
import pandas as pd

from src.infrastructure.record_builder import build_record


def simulate_location_transfers(state, config, schema, today, rng, event_type_map):
    event_key = event_type_map.get("Locatietransfer")
    if event_key is None:
        return state

    if state.get("dim_location") is None or state["dim_location"].empty:
        return state

    open_flags = state.get("_location_open", {})
    open_sites = [
        name
        for name, cfg in getattr(config, "dim_location", {}).items()
        if cfg.get("is_production_site") and open_flags.get(name)
    ]
    if len(open_sites) < 2:
        return state

    fact_employment = state["fact_employment"]
    dim_role = state["dim_role"]
    active = fact_employment[fact_employment["Dienstverband_status"] == "Actief"]
    if active.empty:
        return state

    multi_site_roles = {
        role_name
        for roles in getattr(config, "structure", {}).values()
        for role_name, role_config in roles.items()
        if role_config.get("multi_site")
    }
    role_lookup = dim_role.set_index("Role_Key")

    base_rate = float(config.career_events.get("location_transfer_rate", 0.0)) / 52
    pull_rate = float(config.career_events.get("new_site_pull_rate", 0.0)) / 52
    pull_weeks = int(config.career_events.get("new_site_pull_weeks", 0))
    newest_site, newest_open_weeks_ago = _newest_open_site_age(state, today, open_sites)

    next_key = int(fact_employment["Employment_Key"].max()) + 1
    new_records = []

    for idx, row in active.iterrows():
        role = role_lookup.loc[row["Role_Key"]]
        if role["Functie_Naam"] not in multi_site_roles:
            continue

        current_site = _location_name(state, row["Location_Key"])
        destinations = [site for site in open_sites if site != current_site]
        if not destinations:
            continue

        rate = base_rate
        pulled_destination = None
        if (
            newest_site is not None
            and newest_site != current_site
            and newest_open_weeks_ago is not None
            and newest_open_weeks_ago <= pull_weeks
        ):
            rate += pull_rate
            pulled_destination = newest_site

        if rng.random() >= rate:
            continue

        destination = pulled_destination or rng.choice(destinations)
        fact_employment.loc[idx, "Einddatum"] = today
        fact_employment.loc[idx, "Dienstverband_status"] = "Inactief"
        new_records.append(build_record(
            schema,
            "fact_employment",
            {
                **row.to_dict(),
                "Employment_Key": next_key,
                "Previous_Employment_Key": row["Employment_Key"],
                "Location_Key": _location_key(state, destination),
                "Startdatum": today,
                "Einddatum": None,
                "Dienstverband_status": "Actief",
                "EventType_Key": event_key,
                "DepartureReason_Key": None,
                "Tevredenheid_Score_Bij_Uitdienst": None,
                "SatisfactionBand_Key_Bij_Uitdienst": None,
                "Betrokkenheid_Score_Bij_Uitdienst": None,
                "EngagementBand_Key_Bij_Uitdienst": None,
            }
        ))
        next_key += 1

    if new_records:
        state["fact_employment"] = pd.concat(
            [fact_employment, pd.DataFrame(new_records)], ignore_index=True
        )
    return state


def _newest_open_site_age(state, today, open_sites):
    opened_on = state.get("_location_opened_on", {})
    dated = [(name, opened_on[name]) for name in open_sites if name in opened_on]
    if not dated:
        return None, None
    newest_name, newest_date = max(dated, key=lambda item: item[1])
    weeks_ago = (pd.Timestamp(today) - pd.Timestamp(newest_date)).days / 7
    return newest_name, weeks_ago


def _location_key(state, location_name):
    dim_location = state.get("dim_location")
    if dim_location is None or location_name is None:
        return None
    matches = dim_location.loc[dim_location["Vestiging_Naam"] == location_name, "Location_Key"]
    return matches.iloc[0] if not matches.empty else None


def _location_name(state, location_key):
    if location_key is None or pd.isna(location_key):
        return None
    dim_location = state.get("dim_location")
    if dim_location is None:
        return None
    matches = dim_location.loc[dim_location["Location_Key"] == location_key, "Vestiging_Naam"]
    return matches.iloc[0] if not matches.empty else None
