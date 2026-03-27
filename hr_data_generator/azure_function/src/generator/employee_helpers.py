def choose_hire_source(dim_hire_source, rng):

    return rng.choice(
        dim_hire_source["HireSource_Key"].tolist()
    )


def choose_education(
    role_name,
    sector_config,
    dim_education_level,
    rng
):

    edu_cfg = sector_config.get(
        "education_distribution_by_role",
        {}
    ).get(
        role_name,
        {"MBO": 0.5, "HBO": 0.3, "WO": 0.2}
    )

    niveaus = list(edu_cfg.keys())
    gewichten = list(edu_cfg.values())

    gekozen = rng.choices(
        niveaus,
        weights=gewichten
    )[0]

    return dim_education_level.loc[
        dim_education_level["EducationLevel"] == gekozen,
        "EducationLevel_Key"
    ].values[0]


def choose_location(
    dim_location,
    sector_config,
    rng
):

    loc_cfg = sector_config.get("dim_location", {})

    names = list(loc_cfg.keys())
    weights = list(loc_cfg.values())

    gekozen = rng.choices(
        names,
        weights=weights
    )[0]

    return dim_location.loc[
        dim_location["Location_Name"] == gekozen,
        "Location_Key"
    ].values[0]