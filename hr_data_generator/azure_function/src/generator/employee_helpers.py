def choose_hire_source(config, dim_hire_source, rng):
    """Choose an original external source for a newly created employee.

    Weighted by `initial_population.hire_source_weights` (per `Bron_Naam`) when
    configured, uniform otherwise.

    Internal mobility can fill a vacancy, but it can never be an employee's
    original source of hire. Older narrow test fixtures do not carry the flag,
    so they retain their previous behaviour.
    """
    sources = dim_hire_source
    if "Is_Internal" in sources.columns:
        external_sources = sources[~sources["Is_Internal"].fillna(False)]
        if not external_sources.empty:
            sources = external_sources

    weights_by_name = getattr(config, "initial_population", {}).get("hire_source_weights")
    if not weights_by_name or "Bron_Naam" not in sources.columns:
        return rng.choice(sources["HireSource_Key"].tolist())

    # Configured mix (measured from the simulated history); a source missing
    # from the weights gets weight 0.
    weights = [float(weights_by_name.get(name, 0.0)) for name in sources["Bron_Naam"]]
    if sum(weights) <= 0:
        raise ValueError(
            "initial_population.hire_source_weights gives no external hire source a weight"
        )
    return rng.choices(sources["HireSource_Key"].tolist(), weights=weights, k=1)[0]


def choose_education(
    role_name,
    config,
    dim_education,
    rng
):

    edu_cfg = config.education_distribution_by_role[role_name]
    niveaus = list(edu_cfg.keys())
    gewichten = list(edu_cfg.values())

    gekozen = rng.choices(
        niveaus,
        weights=gewichten
    )[0]

    requirements = config.role_career_paths[role_name]["relevante_opleidingen"]
    candidates = dim_education[
        (dim_education["Opleidingsniveau"] == gekozen)
        & dim_education["Opleiding_Naam"].isin(requirements)
    ]
    if candidates.empty:
        candidates = dim_education[dim_education["Opleiding_Naam"].isin(requirements)]
    return rng.choice(candidates["Education_Key"].tolist())
