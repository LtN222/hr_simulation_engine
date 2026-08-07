# HR Data Generator

Een config-gedreven HR-datasimulator voor demo- en analyseomgevingen. De
generator bouwt een historische workforce op, simuleert vervolgens wekelijkse
HR-gebeurtenissen en schrijft het resultaat naar Azure SQL. Een Azure Function
biedt zowel een handmatige HTTP-trigger als een wekelijkse incremental run.

De huidige sectorconfiguratie is `maakindustrie`.

## Wat wordt gesimuleerd

- Organisatiestructuur, rollen, locaties, contracten en managers.
- Groei, vacatures, sollicitaties, hires en non-hires.
- Uitstroom, inclusief leeftijdsafhankelijk pensioen.
- Promoties, transfers, contractwijzigingen, performance en salarisreviews.
- Verzuim en verlof, waaronder ziekte, zwangerschap, ouderschapsverlof,
  vakantie en tijd-voor-tijd.
- Salarissnapshots voor een betrouwbare salarisontwikkeling door de tijd.

De gedragsregels en verdelingen staan centraal in
`azure_function/config/maakindustrie.json`.

## Architectuur

```text
HTTP trigger or weekly timer
          |
          v
full or incremental simulation
          |
          v
state dictionary with pandas DataFrames
          |
          v
schema-driven Azure SQL writer
          |
          v
Azure SQL and Power BI semantic model
```

De hoofdcode staat in `azure_function/`:

```text
azure_function/
|- function_app.py                 Azure Functions entry point
|- config/
|  |- maakindustrie.json           Sector and simulation settings
|  `- schemas/                     SQL table definitions and constraints
`- src/
   |- application/                 Orchestration and workforce allocation
   |- domain/                      Employee, person, job and contract objects
   |- generator/                   Initial employee generation
   |- simulation/                  Weekly HR event simulators
   `- infrastructure/              SQL, state and reporting helpers
```

## Datamodel

Belangrijke dimensies zijn `dim_employee`, `dim_department`, `dim_role`,
`dim_manager`, `dim_absence_type` en `dim_salary_band`.

Belangrijke facts zijn:

- `fact_employment`: historische arbeidsrelaties en interne events.
- `fact_absence`: afwezigheids- en verlofepisodes, inclusief de dimensies die
  gelden bij de start van de episode.
- `fact_vacancy` en `fact_recruitment`: vacatures en alle sollicitaties.
- `fact_salary_snapshot`: maandelijkse salarisstand per medewerker.
- `fact_performance_review` en `fact_employment_attribute`.

`fact_employment` is event-gebaseerd: promoties, transfers en salarisreviews
kunnen meerdere regels voor een medewerker opleveren. Gebruik voor een
salaristrend daarom `fact_salary_snapshot`, en niet de startdatum van
`fact_employment`.

`fact_absence` bevat ook niet-verzuim, zoals vakantie en ouderschapsverlof.
Filter `dim_absence_type[Telt_als_verzuim] = TRUE()` voor uitsluitend verzuim.
Maak geen directe relatie tussen `fact_absence` en `fact_employment`; beide
facts worden via gedeelde dimensies gefilterd.

## Vereisten

- Windows met Python 3.11.
- Azure Functions Core Tools v4.
- Node.js en Azurite voor lokale timer- en storage-emulatie.
- Microsoft ODBC Driver 18 for SQL Server.
- Toegang tot de doel-Azure SQL-database.

## Lokale installatie

Open PowerShell in `hr_data_generator/azure_function`.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install pytest
```

Installeer Azurite eenmalig wanneer dat nog niet op de machine staat:

```powershell
npm install -g azurite
```

Maak vervolgens `local.settings.json` op basis van de benodigde namen. Dit
bestand is bewust niet versiebeheerbaar.

| Instelling | Doel |
| --- | --- |
| `FUNCTIONS_WORKER_RUNTIME` | Moet `python` zijn. |
| `AzureWebJobsStorage` | Lokaal doorgaans `UseDevelopmentStorage=true`. |
| `SQL_CONNECTION_TEMPLATE` | ODBC-connectiestring met de placeholder `{database}`. |
| `HR_SECTOR` | Sectorconfiguratie, standaard `maakindustrie`. |
| `HR_SIMULATION_MODE` | `full` of `incremental`. |
| `HR_SIMULATION_SEED` | Seed voor reproduceerbare willekeur. |
| `HR_TIMER_SCHEDULE` | NCRONTAB-schema voor de timertrigger. |

`SQL_CONNECTION_TEMPLATE` wordt door de code ingevuld met de database uit de
sectorconfiguratie. Bewaar daarin nooit secrets in Git.

## Lokaal draaien

Start Azurite in een aparte PowerShell vanuit `azure_function/`:

```powershell
azurite --location .azurite --debug .azurite\debug.log
```

Start daarna de Function App in een tweede PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
func start
```

Roep voor een handmatige run de endpoint aan:

```text
http://localhost:7071/api/generate_hr_data
```

De timertrigger voert altijd een incremental run uit. De lokale listener
verwacht daarom ook dat Azurite beschikbaar is op poort 10000.

### Full run

Zet tijdelijk `HR_SIMULATION_MODE` op `full` en roep de HTTP-endpoint aan.
Een full run bouwt de initiele populatie opnieuw op, simuleert de geschiedenis
tot vandaag en reset de beheerde SQL-tabellen. Gebruik dit voor wijzigingen in
de historische simulatielogica of het datamodel.

Zet de instelling na afloop terug op `incremental`.

### Incremental run

Een incremental run leest de huidige SQL-state, simuleert alle ontbrekende
weken tot vandaag en voegt nieuwe facts toe. `dim_employee` wordt als actuele
Type-1 dimensie bijgewerkt. De voortgang staat in `simulation_state`.

## Configuratie

`maakindustrie.json` bevat onder andere:

- `initial_population`: omvang, burn-in en dienstjarenverdeling.
- `growth`: groeipad, capaciteit en economische gebeurtenissen.
- `structure`: afdelingen, rollen, salarisbanden en managementrollen.
- `recruitment`: volume en uitkomstlogica van sollicitaties.
- `absence`: type-specifieke kansen, duur en eligibility-regels.
- `career_events`: performance, salarisgroei, promoties en transfers.
- `retirement`: pensioen vanaf 50, met de grootste uitstroom rond 65 en een
  harde bovengrens op 67.

Voor een nieuwe sector zijn minimaal een nieuwe sectorconfiguratie en passend
schema nodig. Gebruik `maakindustrie.json` en
`config/schemas/hr_maakindustrie_schema.json` als uitgangspunt.

## Testen

Voer vanuit `azure_function/` uit:

```powershell
python -m pytest -q
```

De tests dekken onder meer managerhiarchieen, employment-eventketens,
salary snapshots, recruitment, verzuim, groeilogica en pensioenuitstroom.

## Troubleshooting

| Symptoom | Waarschijnlijke oorzaak en oplossing |
| --- | --- |
| Verbinding geweigerd op `127.0.0.1:10000` | Start Azurite voordat `func start` wordt uitgevoerd. |
| `DRIVER keyword syntax error` | Controleer `SQL_CONNECTION_TEMPLATE` en de geinstalleerde ODBC Driver 18. |
| Endpoint op poort 7071 niet bereikbaar | Controleer of `func start` volledig is opgestart en niet door een eerdere fout is gestopt. |
| Nieuwe schemawijziging ontbreekt in SQL | Draai een full run, of controleer de incremental schema-initialisatie. |

## Deployen

Publiceer de inhoud van `azure_function/` naar de Azure Function App via de
CI/CD-pipeline of Azure Functions Core Tools. Voeg de runtime-instellingen als
Application Settings toe in Azure; kopieer `local.settings.json` niet naar de
repository of de deployment.

Bij een gedeployde Function App vereist de HTTP-endpoint een function key.
