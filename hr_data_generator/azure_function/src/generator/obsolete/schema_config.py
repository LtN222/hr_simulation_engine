SCHEMA_CONFIG = {
  "dim_department": {
    "df": "dim_department",
    "primary_key": "Department_Key",
    "types": {
      "Department_Key": "INT",
      "Afdeling_Naam": "NVARCHAR(100)"
    }
  },

  "dim_role": {
    "df": "dim_role",
    "primary_key": "Role_Key",
    "types": {
      "Role_Key": "INT",
      "Department_Key": "INT",
      "Functie_Naam": "NVARCHAR(100)",
      "Leidinggevend_Flag": "BIT",
      "Salaris_min": "INT",
      "Salaris_max": "INT",
      "Ploegendienst_Flag": "BIT"
    },
    "foreign_keys": [
      ["Department_Key", "dim_department", "Department_Key"]
    ]
  },

  "dim_employee": {
    "df": "dim_employee",
    "primary_key": "Employee_Key",
    "types": {
      "Employee_Key": "INT",
      "Leeftijd": "INT",
      "Prestatie_Score": "DECIMAL(3,2)"
    }
  },

  "dim_reden_vertrek": {
    "df": "dim_reden_vertrek",
    "primary_key": "RedenVertrek_Key",
    "types": {
      "RedenVertrek_Key": "INT",
      "RedenVertrek": "NVARCHAR(100)",
      "Categorie": "NVARCHAR(50)"
    }
  },
    "dim_event_type": {
    "df": "dim_event_type",
    "primary_key": "EventType_Key",
    "types": {
      "EventType_Key": "INT",
      "Gebeurtenis": "NVARCHAR(50)"
    }
  },

  "fact_employment": {
    "df": "fact_employment",
    "primary_key": "Employment_Key",
    "types": {
      "Employment_Key": "INT",
      "Previous_Employment_Key": "INT",
      "Employee_Key": "INT",
      "Role_Key": "INT",
      "Startdatum": "DATE",
      "Einddatum": "DATE",
      "Dienstverband_status": "NVARCHAR(50)",
      "Salaris": "INT",
      "Contracttype": "NVARCHAR(50)",
      "Contract_einddatum": "DATE",
      "Contract_ronde": "INT",
      "EventType_Key": "INT",
      "RedenVertrek_Key": "INT"
    },
    "foreign_keys": [
      ["Employee_Key", "dim_employee", "Employee_Key"],
      ["Role_Key", "dim_role", "Role_Key"],
      ["Previous_Employment_Key", "fact_employment", "Employment_Key"],
      ["EventType_Key", "dim_event_type", "EventType_Key"],
      ["RedenVertrek_Key", "dim_reden_vertrek", "RedenVertrek_Key"]
    ],
    "indexes": [
      "Employee_Key",
      "Role_Key",
      "Startdatum",
      "Einddatum"
    ]
  },

  "fact_employment_attribute": {
    "df": "fact_employment_attribute",
    "types": {
      "Employment_Key": "INT",
      "Attribute_Name": "NVARCHAR(100)",
      "Attribute_Value": "NVARCHAR(100)"
    },
    "indexes": [
      "Employment_Key"
    ]
  }
}