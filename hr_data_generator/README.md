# HR Data Generator

Een config-gedreven HR-datasimulator voor demo- en analyseomgevingen. De
generator bouwt een historische workforce op, simuleert vervolgens wekelijkse
HR-gebeurtenissen en schrijft het resultaat naar Azure SQL. Een Azure Function
biedt zowel een handmatige HTTP-trigger als een wekelijkse incremental run.

De startbezetting en de volwassen organisatiemix zijn afzonderlijk
configureerbaar. `workforce_planning.department_target_weights` stuurt de
langetermijnverdeling per afdeling; `fte_ratio` (of `target_weight`) bepaalt de
verdeling van rollen binnen die afdeling. Met `initially_staffed: false` kan een
rol wel in `dim_role` bestaan maar bij de start nog leeg blijven, en
`active_from` voorkomt dat groei-vacatures vóór het gekozen organisatiemoment
voor die rol worden aangemaakt.

De huidige sectorconfiguratie is `maakindustrie`.

## Wat wordt gesimuleerd

- Organisatiestructuur, rollen, locaties, contracten en managers.
- Groei, vacatures, sollicitaties, hires en non-hires.
- Uitstroom, inclusief leeftijdsafhankelijk pensioen.
- Promoties, transfers, contractwijzigingen, performance en salarisreviews.
- Ziekteverzuim en verlof, waaronder kort, middellang en lang verzuim,
  zwangerschap, ouderschapsverlof, vakantie, tijd-voor-tijd en
  calamiteitenverzuim.
- Maandelijkse workforce snapshots voor betrouwbare trends in salaris,
  performance, tevredenheid, capaciteit en afwezigheid.
- Tevredenheid, met effecten van marktconforme beloning, manager,
  performance en diensttijd. Tevredenheid beinvloedt bescheiden de kans op
  ziekmelding en vrijwillige uitstroom.
- Betrokkenheid, als afzonderlijke score voor energie en verbondenheid met het
  werk. Deze beweegt mee met tevredenheid, performance, manager,
  loopbaanmomentum en relatieve beloning.

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
`dim_manager`, `dim_hire_source`, `dim_recruitment_status`, `dim_education`,
`dim_absence_type`, `dim_ploegendienst`, `dim_salary_band`,
`dim_salary_scale`, `dim_satisfaction_band`, `dim_engagement_band`,
`dim_satisfaction_driver`, `dim_performance_driver` en
`dim_engagement_driver`.

`dim_education` vervangt de eerdere niveau-dimensie. Elke rij combineert een
opleidingsnaam, niveau en richting. `dim_role` bewaart daarnaast de leesbare
lijsten `Relevante_Opleidingen` en `Logische_Doorgroei`; de gestructureerde
bron daarvoor is `role_career_paths` in de sectorconfiguratie.

`dim_employee` bevat daarnaast `Avatar_FileName` en `Avatar_URL`. De generator
kiest de avatar stabiel op basis van `Employee_Key` en de avatar-seed. Mannen en
vrouwen krijgen hun eigen set afbeeldingen, met voor ieder ongeveer 5% een
neutrale avatar; `Anders` en `Onbekend` gebruiken altijd de neutrale set.
`Avatar_URL` kan in Power BI als gegevenscategorie **Image URL** worden gezet.

De `avatar`-sectie in `maakindustrie.json` bevat standaard de drie expliciete
afbeeldingslijsten. Voeg je een bestand toe, dan kun je het aan de juiste lijst
toevoegen. Als `auto_discover_from_blob` op `true` staat, leest de generator bij
het begin van iedere full of incremental run alle PNG-bestanden in `blob_prefix`
uit Blob Storage. Nieuwe bestanden moeten beginnen met `male`, `female` of
`neutral`, bijvoorbeeld `female5.png`; andere namen worden bewust genegeerd.
Voor een private container is hiervoor de Function App-setting
`HR_AVATAR_BLOB_CONNECTION_STRING` nodig. Gebruik
`reassign_existing_avatars: true` alleen tijdens ontwikkeling: daarmee kunnen
bestaande medewerkers na een incremental run opnieuw over de uitgebreidere set
worden verdeeld. Bij `false` behouden bestaande medewerkers hun huidige URL en
gebruiken alleen nieuwe medewerkers de nieuwe set.

Belangrijke facts zijn:

- `fact_employment`: historische arbeidsrelaties en interne events, inclusief
  relevante ervaring bij de start van elke employment-periode.
- `fact_absence`: afwezigheids- en verlofepisodes, inclusief de dimensies die
  gelden bij de start van de episode, zoals rol, afdeling, salarisband en
  tevredenheidsband.
- `fact_vacancy` en `fact_recruitment`: vacatures en alle sollicitaties.
- `fact_workforce_snapshot`: maandelijkse workforce-stand per actieve
  medewerker; dit is de centrale analysetabel voor medewerkerstrends.
- `fact_manager_assignment`: technische, effectieve-datumhistorie van de
  managerrelatie.
- `fact_salary_benchmark`: maandelijkse marktbenchmark per rol, schaal en
  salaristrede.
- `fact_performance_review`.

`fact_employment` is event-gebaseerd: promoties, transfers en salarisreviews
kunnen meerdere regels voor een medewerker opleveren. Gebruik voor trends in
salaris, performance, tevredenheid, dienstjaren of headcount daarom
`fact_workforce_snapshot`, en niet de startdatum van `fact_employment`. De
snapshot bewaart ook `Relevante_Ervaring_Jaren`: de actuele relevante ervaring
op de maandultimo, berekend vanuit de startwaarde van de effectieve
employment-regel plus opgebouwde relevante tijd.

`Relevante_Ervaring_Jaren_Bij_Start` is externe of eerder opgebouwde ervaring
die functioneel relevant is voor de rol op de startdatum. Leeftijd begrenst
alleen wat bij externe instroom plausibel is; het is geen ervaringsmaat. Bij
salariswijzigingen en promoties binnen hetzelfde domein loopt alle ervaring
door. Bij een transfer naar een ander functioneel domein wordt het
configureerbare deel `career_events.relevant_experience_transfer_ratio`
overgedragen.

Promoties volgen uitsluitend de geconfigureerde `Logische_Doorgroei` van de
huidige rol. Een hogere salarisschaal is dus geen promotiecriterium. Interne
transfers blijven een afzonderlijke, laterale mobiliteitsroute en worden als
`Transfer` vastgelegd.

`fact_recruitment` heeft één regel per sollicitatie. De fact bevat zowel de
compacte tekstkolom `Status` als `RecruitmentStatus_Key`; gebruik voor nieuwe
Power BI-relaties en legendes de laatste key naar `dim_recruitment_status`.
Die dimensie bevat de korte status voor visuals, de uitleg (`Status_Verbose`),
een statusgroep en technische flags zoals `Counts_As_Hire`.

Recruitmentbronnen hebben elk een eigen profiel in de
`recruitment.source_profiles`-sectie van de sectorconfiguratie. Dit profiel
stuurt sollicitatievolume, bron-specifieke conversie, kandidaatkwaliteit,
kans dat een kandidaat een aanbod weigert en afdelingsvoorkeuren. De standaard
onderscheidt `Interne recruiter` (actief gesourcet door het eigen team) en
`Recruitmentbureau` (externe aanbieder).

De recruitmentfunnel volgt daarbij een vaste volgorde: een sollicitant krijgt
eerst een kandidaatkwaliteit, reguliere niet-geselecteerde kandidaten worden
`Afgewezen`, en alleen een kandidaat die aan de bron-specifieke
selectiedrempel voldoet ontvangt een aanbod. Zo'n kandidaat wordt vervolgens
`Aangenomen` of `Geweigerd`; de laatste status betekent dus altijd dat een
aanbod door de kandidaat is afgewezen. Interne mobiliteit heeft bewust weinig
sollicitatievolume en een relatief hoge conversie, zodat de bron zichtbaar
blijft zonder de externe instroom te domineren.

`Interne mobiliteit` staat bewust ook in `fact_recruitment`, zodat die op
dezelfde recruitmentpagina als externe bronnen kan worden geanalyseerd. Bij
een aangenomen interne kandidaat koppelt de fact aan een bestaande
`Employee_Key`; de simulator maakt vervolgens een transfer of promotie in
`fact_employment`, geen nieuwe `dim_employee`-regel. De vrijgekomen oude rol
wordt in de volgende simulatieweek als backfill-vacature aangemaakt.

`Candidate_Quality` is een gesimuleerde, latente selectiescore op een schaal
van 1-5. Het is geen werkelijk assessmentresultaat. Voor externe hires werkt
de score beperkt door in de initiële performance; voor interne kandidaten is
hij deels gebaseerd op de al bekende performance. Gebruik hem daarom alleen
als demo-indicator naast hire rate, time-to-fill, retentie en performance na
instroom.

`dim_salary_scale` is de arbeidsvoorwaardelijke salarisschaal: de schaalrange
en het aantal treden. `dim_salary_band` is juist een rapportage-indeling van
het feitelijke salaris in brede bins. `fact_workforce_snapshot` bevat beide
keys, naast `SalaryStep`, `Benchmark_Salaris`, `Benchmark_Verschil` en
`Benchmark_Status`. Daarmee kunnen medewerkers direct worden vergeleken met
hun marktbenchmark zonder een relatie tussen twee facts te maken.

Elke rol in `structure` heeft een expliciete `salary_scale_code`. De
rolspecifieke salarisrange en marktmediaan worden naast die functiewaardering
geconfigureerd en moeten daarmee inhoudelijk consistent blijven. Daardoor is
een schaalgrens geen impliciet toewijzingsmechanisme voor `dim_role`.

Gebruik `fact_workforce_snapshot` voor headcount, dienstjaren en slicers op
afdeling, functie, instroombron, opleidingsniveau, locatie, performance en
tevredenheid. De fact heeft een medewerker-per-maandultimo-grain en bewaart
dus de organisatiecontext die op dat moment gold.

De snapshot bevat daarnaast `Betrokkenheid_Score`, `EngagementBand_Key`,
`EngagementDriver_Key` en de actuele `PerformanceDriver_Key`.
Betrokkenheid is bewust geen kopie van tevredenheid: loopbaanmomentum,
managercontext, performance en relatieve beloning geven elk een eigen,
begrensde bijdrage. De score heeft een kleine, gemaximeerde invloed op de
volgende performance-review en op vrijwillige uitstroom; hij beinvloedt niet
rechtstreeks de afwezigheidsduur.

Elke `fact_performance_review` bevat één dominante `PerformanceDriver_Key`.
De driver verklaart het zwaartepunt van de score vanuit resultaat en
werkuitvoering, vakmanschap en relevante ervaring, samenwerking, initiatief
of coachen en kennisdeling. Verzuim, structureel overwerk en bereikbaarheid
buiten werktijd zijn geen performancefactoren. De driver
`Relevante startkwalificatie` blijft inactief totdat een opleidingsrichting en
een aantoonbare relatie met rol of domein zijn gemodelleerd; alleen
`EducationLevel_Key` is daarvoor onvoldoende.

`EngagementDriver_Key` legt één dominante vorm van vrijwillige, constructieve
extra rol- of organisatiebijdrage vast, zoals initiatief, kennisdeling,
samenwerking buiten de rol, participatie, organisatieverbondenheid of
eigenaarschap. Dezelfde begrensde signalen dragen bij aan de score; pas vanaf
de configureerbare drempel `engagement.driver_dominance_threshold` krijgt één
driver de overhand, anders wordt `Geen dominant aandachtspunt` opgeslagen.
Informele borrels, social-media-activiteit en beschikbaarheid buiten werktijd
worden niet gebruikt.

De workforce snapshot bevat ook FTE, salarisbenchmarkvelden en maandelijkse
afwezigheidsmetrics (`Afwezige_Dagen`, `Verzuim_Dagen`, werkdagen, uren en
aantallen episodes). Elke actieve medewerker heeft iedere maand een
snapshotregel, dus ook medewerkers zonder afwezigheid. `fact_manager_assignment`
ondersteunt alleen de historische managercontext van de snapshot en kan in
Power BI verborgen blijven.

`Ploegendienst_Key`, `SalaryScale_Key` en de technische
`Target_Compa_Ratio` horen bij `fact_employment`. Een promotie, transfer of
salarisreview maakt een nieuwe employment-regel met die historische context.
`fact_absence` kopieert de ploegendienst, schaal en salarisband bij aanvang
van de afwezigheid, zodat het rapport geen facts aan elkaar hoeft te koppelen.

De salarisgenerator gebruikt dezelfde marktbenchmark als de rapportage.
Werkelijke salarissen worden gegenereerd rond een stabiele beloningspositie
ten opzichte van die benchmark; de vijf benchmarkstatussen blijven daarom
zichtbaar in de data zonder dat ze in Power BI worden geforceerd.

`fact_absence` bevat zowel ziekteverzuim als niet-ziekte-afwezigheid, zoals
vakantie en ouderschapsverlof. Filter
`dim_absence_type[Telt_als_verzuim] = TRUE()` voor uitsluitend
ziekteverzuim. `Duur_dagen` is de kalenderduur van een episode; gebruik voor
verzuimpercentages de werkdag- of uurkolommen. De velden
`Tevredenheid_Score_Bij_Aanvang` en `SatisfactionBand_Key` beschrijven de
tevredenheid bij de start van de episode.

Maak geen directe relatie tussen facts. Facts worden via gedeelde dimensies
gefilterd. In Power BI horen onder andere deze actieve, enkelrichtingsrelaties
in het model te staan:

```text
dim_satisfaction_band -> fact_workforce_snapshot
dim_satisfaction_band -> fact_absence
dim_satisfaction_band -> fact_employment (uitdienstcontext)
dim_engagement_band   -> fact_workforce_snapshot
dim_engagement_band   -> fact_employment (uitdienstcontext)
dim_performance_driver -> fact_performance_review
dim_performance_driver -> fact_workforce_snapshot
dim_engagement_driver  -> fact_workforce_snapshot
dim_candidate_quality_driver -> fact_recruitment
dim_hire_source        -> fact_recruitment
dim_recruitment_status -> fact_recruitment
```

`fact_vacancy` bevat geen `HireSource_Key`: de bron is die van de uiteindelijk
aangenomen sollicitatie in `fact_recruitment`. Gebruik voor time-to-fill per
bron daarom een DAX-measure met de aangenomen `Vacancy_Key` als filtercontext,
niet een fact-to-fact-relatie.

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
de historische simulatielogica of het datamodel. Een full run verwijdert ook
verouderde beheerde tabellen, waaronder `fact_salary_snapshot`.

Een full run is ook vereist na wijzigingen aan recruitmentbronprofielen,
recruitmentstatussen, de interne-mobiliteitslogica of snapshotkolommen zoals
de driverkeys en `Relevante_Ervaring_Jaren`. Een incremental run kan
nieuwe dimensiekolommen en statuskeys aanvullen, maar kan historische
snapshotwaarden en sollicitatie-uitkomsten niet realistisch hersimuleren.

Zet de instelling na afloop terug op `incremental`.

### Incremental run

Een incremental run leest de huidige SQL-state, simuleert alle ontbrekende
weken tot vandaag en voegt nieuwe facts toe. Actuele dimensies en facts met
nabewerkte gebeurteniscontext, zoals `fact_employment` en `fact_absence`,
worden bijgewerkt. De voortgang staat in `simulation_state`.

## Configuratie

`maakindustrie.json` bevat onder andere:

- `initial_population`: omvang, burn-in en dienstjarenverdeling.
- `growth`: groeipad, capaciteit en economische gebeurtenissen.
- `structure`: afdelingen, rollen, salarisbanden en managementrollen.
- `recruitment`: volume en uitkomstlogica van sollicitaties.
- `absence`: type-specifieke kansen, duur en eligibility-regels.
- `career_events`: performance, salarisgroei, promoties en transfers.
- `satisfaction`: de scoreverdeling en effecten van relatieve beloning,
  manager, performance, diensttijd en afdeling.
- `engagement`: de scoreverdeling en effecten van tevredenheid, relatieve
  beloning, manager, performance, loopbaanmomentum en afdeling.
- `attrition`: uitstroompercentages per afdeling, plus de invloed van
  tevredenheid en betrokkenheid op vertrek- en vertrekredenlogica.
- `salary_benchmark`: marktmedianen per rol, marktgroei, treden en de
  classificatie onder/rond/boven benchmark.
- `retirement`: pensioen vanaf 50, met de grootste uitstroom rond 65 en een
  harde bovengrens op 67.
- `avatar`: publieke Blob Storage-basis-URL, vaste toewijzingsseed en het
  aandeel neutrale avatars voor mannen en vrouwen.

### `baseline_headcount` versus `initial_population.headcount`

Deze twee waarden lijken op elkaar maar sturen iets anders aan. De burn-in
periode begint op `start_year_simulation - burn_in_years` en loopt tot
`start_year_simulation`; `initial_population.headcount` is de daadwerkelijke
personeelsomvang waarmee die burn-in start. `baseline_headcount` is het
ankerpunt van de groeicurve (`growth`) op `start_year_simulation` zelf: vóór
die datum staat het groeidoel plat op `baseline_headcount`, waardoor de
burn-in effectief richting die waarde groeit (begrensd door
`growth.max_weekly_hires`/`max_weekly_growth_rate`), en pas ná die datum volgt
het doel de exponentiële `annual_growth_rate`-curve.

Laat je `initial_population.headcount` weg, dan valt deze automatisch terug
op `baseline_headcount` (zie `WorkforceGenerator` in `population.py` en
`run_simulation.py`) — er is dus geen organische groei tijdens de burn-in en
de periode dient alleen om geschiedenis (promoties, vervangingswerving,
verzuim, salarisreviews) op een populatie van constante omvang op te bouwen
voordat het zichtbare venster begint. Zet `initial_population.headcount`
alleen bewust lager dan `baseline_headcount` als je wilt dat het personeels-
bestand tijdens de burn-in zelf ook nog organisch groeit (bijvoorbeeld een
"startup die uitgroeit" scenario) — voor de huidige sectorconfiguratie is dat
niet het geval.

Voor een nieuwe sector zijn minimaal een nieuwe sectorconfiguratie en passend
schema nodig. Gebruik `maakindustrie.json` en
`config/schemas/hr_maakindustrie_schema.json` als uitgangspunt.

## Testen

Voer vanuit `azure_function/` uit:

```powershell
python -m pytest -q
```

De tests dekken onder meer managerhierarchieen, employment-eventketens,
workforce snapshots, salarisbenchmarking, recruitment, verzuim,
tevredenheidscontext, groeilogica en pensioenuitstroom.

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

Voor een release met simulatielogica- of schemawijzigingen:

1. Voer `python -m pytest -q` uit vanuit `azure_function/`.
2. Deploy de Function App en controleer de Application Settings.
3. Voer eenmaal een handmatige full run uit.
4. Vernieuw de gewijzigde tabellen in Power BI en controleer nieuwe relaties.
