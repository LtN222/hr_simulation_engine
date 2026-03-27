import pandas as pd


def choose_contract(startdatum, today, contract_rules, rng):

    contract_type = rng.choices(
        ["Vast", "Tijdelijk"],
        weights=[
            contract_rules["vast_kans"],
            contract_rules["tijdelijk_kans"]
        ]
    )[0]

    if contract_type == "Tijdelijk":

        tenure_years = (today - startdatum).days // 365
        contract_ronde = tenure_years + 1

        contract_einddatum = startdatum + pd.DateOffset(
            years=contract_ronde
        )

    else:

        contract_einddatum = None
        contract_ronde = None

    return contract_type, contract_einddatum, contract_ronde


def choose_contract_hours(role_name, sector_config, rng):

    hours_cfg = sector_config.get(
        "contract_hours_distribution",
        {}
    )

    role_dist = hours_cfg.get(
        role_name,
        hours_cfg.get("default")
    )

    hours = rng.choices(
        list(role_dist.keys()),
        weights=list(role_dist.values())
    )[0]

    return int(hours)