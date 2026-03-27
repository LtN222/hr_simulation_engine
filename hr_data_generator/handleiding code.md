# HR Data Generator

## Gebruikershandleiding – Nieuwe sector toevoegen & pipeline draaien

Deze handleiding beschrijft hoe je met de HR Data Generator een nieuwe dataset genereert, onderhoudt en automatiseert (full + incremental runs).

De generator is **config-gedreven**: nieuwe sectoren voeg je toe via configuratiebestanden — zonder Python-code aan te passen.

---

## 🔹 Overzicht van de pipeline

```
sector config
↓
initial workforce generation (full)
↓
weekly simulation
↓
dataframes
↓
write to Azure SQL
↓
simulation_state update
```

---

## 🔹 Projectstructuur

```
config/
├── sector configs (bijv. maakindustrie.json)
├── schema configs (bijv. hr_maakindustrie_schema.json)

src/
├── generator/
├── database/
├── simulation/

azure_function/
├── function_app.py
├── requirements.txt
├── host.json
```

---

## 🔹 Stap 1 — Sectorconfig maken

Maak een nieuw bestand in:

```
config/
```

Bijvoorbeeld:

```
config/horeca.json
```

Deze bevat o.a.:

* organisatiestructuur
* rollen & salarissen
* attrition gedrag
* contractregels
* locaties
* education distribution
* absence gedrag

👉 Gebruik `maakindustrie.json` als template.

### 🔹 Realisme van de dataset

De kwaliteit en het realisme van de gegenereerde dataset hangt sterk af van het gekozen startpunt van de simulatie.

Je krijgt de meest realistische resultaten wanneer je:

* start met een relatief klein aantal medewerkers
* op een tijdstip in het verleden
* en vervolgens de weken tot vandaag simuleert

De generator maakt dan een initiële workforce op het startmoment en simuleert daarna week voor week gebeurtenissen zoals groei, uitstroom, promoties en interne transfers.

Dit zorgt voor een natuurlijke opbouw van de organisatie en realistische historische data.

---

Je kunt er ook voor kiezen om direct een grote workforce te genereren op het huidige tijdstip en alleen vanaf dat moment incremental te simuleren.

In dat geval:

* is de dataset sneller beschikbaar
* maar bevat de historische data minder dynamiek
* en oogt de data minder realistisch (minder carrièrepaden, events en verloop over tijd)

---

👉 Aanbeveling:
Gebruik een historische start met groei voor productie- of analysedoeleinden, en een directe grote workforce alleen voor snelle tests of demo’s.


---

## 🔹 Stap 2 — Schema configuratie maken

Maak een schema bestand:

```
config/hr_horeca_schema.json
```

Bevat:

* dimension tables
* fact tables
* primary keys
* foreign keys
* datatype mapping

👉 Meestal kun je een bestaand schema kopiëren.

---

## 🔹 Stap 3 — Database instellen

In je sectorconfig:

```json
"database": "hr_horeca"
```

De connectie komt uit environment variables:

```json
"SQL_CONNECTION_TEMPLATE": "Driver={...};Database={database};..."
```

👉 `{database}` wordt automatisch vervangen.

⚠️ De database moet al bestaan in Azure SQL.

---

## 🔹 Stap 4 — Runtime configuratie

De pipeline gebruikt environment variables via `runtime_config.py`.

### Lokaal (`local.settings.json`)

```json
"HR_SECTOR": "maakindustrie",
"HR_SIMULATION_MODE": "full",
"HR_SIMULATION_SEED": "42"
```

### In Azure

Ga naar:
Function App → **Environment Variables**

---

### 🔸 Simulation modes

| Mode          | Gedrag                                  |
| ------------- | --------------------------------------- |
| `full`        | Genereert volledige dataset vanaf start |
| `incremental` | Genereert alleen nieuwe weken           |

---

## 🔹 Stap 5 — Function lokaal starten

```bash
func start
```

Endpoint:

```
http://localhost:7071/api/generate_hr_data
```

---

## 🔹 Stap 6 — Dataset genereren

```http
GET /api/generate_hr_data
```

---

### 🔸 Output

**Full run:**

```
Full HR dataset generated (1098 employees).
```

**Incremental run:**

```
Incremental update complete: +1 employees, +1 employments.
```

---

## 🔹 Stap 7 — Incremental updates

De tabel:

```
simulation_state
```

bevat:

* current_year
* current_week

---

### 🔸 Werking

```
load state
↓
start bij laatste week
↓
simuleer tot vandaag
↓
schrijf alleen nieuwe records
```

👉 Geen dubbele data
👉 Snelle updates

---

## 🔹 Stap 8 — Automatische runs (Timer)

De pipeline draait automatisch via een timer trigger.

### In code:

```python
@app.timer_trigger(
    schedule="%HR_TIMER_SCHEDULE%",
    arg_name="timer"
)
```

---

### 🔸 Configuratie

In `local.settings.json` of Azure:

```json
"HR_TIMER_SCHEDULE": "0 0 2 * * 1"
```

👉 Betekent:

```
Elke maandag om 02:00 (UTC)
```

---

### 🔸 Aanpassen zonder redeploy

Je kunt het schema wijzigen via:

* `local.settings.json`
* Azure Environment Variables

👉 Geen code wijziging nodig

---

## 🔹 Stap 9 — Deployment

```bash
func azure functionapp publish fa-demo-hr-datagenerator
```

👉 Dit deployt code en dependencies
👉 Environment variables blijven behouden

---

## 🔹 Stap 10 — Lokale storage (Azurite)

Voor timers is lokale storage nodig.

Start Azurite:

```bash
azurite
```

Of via VS Code.

---

## 🔹 Database output

### Dimension tables

* dim_employee
* dim_role
* dim_department
* dim_location
* dim_hire_source
* dim_education_level
* dim_absence_type
* dim_event_type
* dim_reden_vertrek
* dim_manager

---

### Fact tables

* fact_employment
* fact_employment_attribute
* fact_absence
* fact_performance_review

---

## 🔹 Veelgemaakte fouten

* Timer werkt niet → Azurite draait niet
* Imports falen → verkeerde working directory
* Geen data bij incremental → simulation_state niet correct
* Environment variables ontbreken
* Datatype fouten (datetime vs date)

---

## 🔹 Simulatiegedrag aanpassen

Via sectorconfig:

* attrition
* contract_rules
* growth
* locations
* education
* absence

---

## 🔹 Best practices

* Gebruik **incremental voor productie**
* Gebruik **full alleen voor reset**
* Zet secrets alleen in Azure
* Gebruik timer i.p.v. handmatige runs
* Houd config en code gescheiden

---

## 🔹 Samenvatting

Voor een nieuwe sector:

1. Sectorconfig maken
2. Schema configuratie maken
3. Database instellen
4. Environment variables zetten
5. Function draaien

---

## 🚀 Resultaat

* Volledige HR dataset
* Automatische wekelijkse updates
* Schaalbare pipeline
* Geen code-aanpassingen nodig voor nieuwe sectoren
