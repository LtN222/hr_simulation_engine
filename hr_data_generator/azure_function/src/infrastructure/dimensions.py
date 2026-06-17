import pandas as pd


# =====================================================
# Dim_Department
# =====================================================

def build_dim_department(structure: dict):

    departments = list(structure.keys())

    return pd.DataFrame({
        "Department_Key": range(1, len(departments) + 1),
        "Department_Name": departments
    })


# =====================================================
# Dim_Role
# =====================================================

def build_dim_role(structure: dict, dim_department: pd.DataFrame):

    dept_lookup = dict(
        zip(
            dim_department["Department_Name"],
            dim_department["Department_Key"]
        )
    )

    rows = []
    role_key = 1

    for dept, roles in structure.items():

        for role_name, details in roles.items():

            rows.append({
                "Role_Key": role_key,
                "Role_Name": role_name,
                "Department_Key": dept_lookup[dept],
                "Leidinggevend": details["leidinggevend"],
                "Salaris_min": details["salaris_range"][0],
                "Salaris_max": details["salaris_range"][1],
                "Ploegendienst_Flag": details.get("ploegendienst", False)
            })

            role_key += 1

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
# Dim_RedenVertrek
# =====================================================

def build_dim_reden_vertrek(vertrekredenen: dict):

    rows = []
    key = 1

    for categorie, redenen in vertrekredenen.items():

        for reden in redenen:

            rows.append({
                "RedenVertrek_Key": key,
                "RedenVertrek": reden,
                "Categorie": categorie
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

def build_dim_education_level(education_levels: list):

    rows = []

    for i, level in enumerate(education_levels, start=1):

        rows.append({
            "EducationLevel_Key": i,
            "EducationLevel": level
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