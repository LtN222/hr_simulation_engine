import pandas as pd


# =====================================================
# Dim_Department
# =====================================================

def build_dim_department(structure: dict):

    departments = list(structure.keys())

    return pd.DataFrame({
        "Department_Key": [
            next(iter(structure[name].values())).get("department_key", i)
            for i, name in enumerate(departments, 1)
        ],
        "Department_Name": departments
    })


# =====================================================
# Dim_Role
# =====================================================

def build_dim_role(
    structure: dict,
    dim_department: pd.DataFrame,
    dim_salary_scale=None,
    market_median_by_role=None,
    role_career_paths=None,
):

    dept_lookup = dict(
        zip(
            dim_department["Department_Name"],
            dim_department["Department_Key"]
        )
    )

    rows = []
    market_median_by_role = market_median_by_role or {}
    role_career_paths = role_career_paths or {}

    for dept, roles in structure.items():

        for role_name, details in roles.items():
            career_path = role_career_paths.get(role_name)
            if career_path is None:
                career_path = {
                    "relevante_opleidingen": [],
                    "logische_doorgroei": [],
                }
            scale_key = _salary_scale_for_role(
                details,
                role_name,
                dim_salary_scale,
                market_median_by_role
            )

            rows.append({
                "Role_Key": details.get("role_key", len(rows) + 1),
                "Role_Name": role_name,
                "Department_Key": dept_lookup[dept],
                "Department_Name": dept,
                "Leidinggevend": details["leidinggevend"],
                "Salaris_min": details["salaris_range"][0],
                "Salaris_max": details["salaris_range"][1],
                "SalaryScale_Key": scale_key,
                "Ploegendienst_Flag": details.get("ploegendienst", False),
                "Relevante_Opleidingen": "; ".join(career_path["relevante_opleidingen"]),
                "Logische_Doorgroei": "; ".join(career_path["logische_doorgroei"]),
                "Laterale_Transfers": "; ".join(career_path.get("laterale_transfers", [])),
                "Min_Relevante_Ervaring_Jr": career_path.get("min_relevante_ervaring_jr", 0),
                "Formele_Kwalificatie_Vereist": career_path.get("formele_kwalificatie_verplicht", False),
                "Min_Opleidingsniveau": career_path.get("min_opleidingsniveau", "Geen"),
                "Min_Leidinggevende_Ervaring_Jr": career_path.get("min_leidinggevende_ervaring_jr", 0),
            })

    return pd.DataFrame(rows)


# =====================================================
# Dim_EventType
# =====================================================

def build_dim_event_type(event_types: list):

    rows = []

    for i, event in enumerate(event_types, start=1):

        rows.append({
            "EventType_Key": i,
            "EventType": event
        })

    return pd.DataFrame(rows)


# =====================================================
# Dim_DepartureReason
# =====================================================

def build_dim_departure_reason(departure_reasons: dict):

    rows = []
    key = 1

    for category, reasons in departure_reasons.items():

        for reason in reasons:

            rows.append({
                "DepartureReason_Key": key,
                "DepartureReason": reason,
                "Category": category
            })

            key += 1

    return pd.DataFrame(rows)


# =====================================================
# Dim_HireSource
# =====================================================

def build_dim_hire_source(hire_sources: list):

    rows = []

    for i, source in enumerate(hire_sources, start=1):

        rows.append({
            "HireSource_Key": i,
            "HireSource_Name": source
        })

    return pd.DataFrame(rows)


# =====================================================
# Dim_EducationLevel
# =====================================================

def build_dim_education(educations: list):

    rows = []

    for i, education in enumerate(educations, start=1):

        rows.append({
            "Education_Key": education.get("Education_Key", i),
            "Education_Name": education["Education_Name"],
            "Education_Level": education["Education_Level"],
            "Education_Direction": education["Education_Direction"],
        })

    return pd.DataFrame(rows)


# =====================================================
# Dim_Location
# =====================================================

def build_dim_location(locations: dict):

    rows = []

    for i, loc in enumerate(locations.keys(), start=1):

        rows.append({
            "Location_Key": i,
            "Location_Name": loc
        })

    return pd.DataFrame(rows)


# =====================================================
# Dim_Absence_Type
# =====================================================

def build_dim_absence_type(absence_types: dict):

    rows = []

    for i, (absence_type, telt_als_verzuim) in enumerate(
        absence_types.items(),
        start=1
    ):

        rows.append({
            "AbsenceType_Key": i,
            "AbsenceType_Name": absence_type,
            "Telt_als_verzuim": telt_als_verzuim
        })

    return pd.DataFrame(rows)


def _salary_scale_for_role(
    details,
    role_name,
    dim_salary_scale,
    market_median_by_role
):
    """Assign each role one grade using its configured market median."""
    if dim_salary_scale is None or dim_salary_scale.empty:
        return None

    if "salary_scale_code" in details:
        matching = dim_salary_scale.loc[
            dim_salary_scale["SalaryScale_Code"] == details["salary_scale_code"],
            "SalaryScale_Key"
        ]
        if not matching.empty:
            return int(matching.iloc[0])

    median = float(market_median_by_role.get(
        role_name,
        (float(details["salaris_range"][0]) + float(details["salaris_range"][1])) / 2
    ))
    scales = dim_salary_scale.copy()
    inside = scales[
        (scales["Minimum_Salaris"] <= median)
        & (scales["Maximum_Salaris"].isna()
           | (scales["Maximum_Salaris"] >= median))
    ]
    if not inside.empty:
        return int(inside.sort_values("SalaryScale_Key").iloc[0]["SalaryScale_Key"])

    midpoints = (
        scales["Minimum_Salaris"] + scales["Maximum_Salaris"].fillna(median)
    ) / 2
    return int(scales.loc[(midpoints - median).abs().idxmin(), "SalaryScale_Key"])
