def choose_hire_source(config, dim_hire_source, rng):
    """Choose an original external source for a newly created employee.

    Internal mobility can fill a vacancy, but it can never be an employee's
    original source of hire. Older narrow test fixtures do not carry the flag,
    so they retain their previous behaviour.
    """
    sources = dim_hire_source
    if "Is_Internal" in sources.columns:
        external_sources = sources[~sources["Is_Internal"].fillna(False)]
        if not external_sources.empty:
            sources = external_sources

    return rng.choice(sources["HireSource_Key"].tolist())


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
