# HR Data Generator

Een config-gedreven HR-datasimulator voor demo- en analyseomgevingen. De
generator bouwt een historische workforce op, simuleert vervolgens wekelijkse
HR-gebeurtenissen en schrijft het resultaat naar Azure SQL. Een Azure Function
biedt zowel een handmatige HTTP-trigger als een wekelijkse incremental run.

De primaire consument van deze data is een webapp (met AI/LLM-functionaliteit
als reden om niet voor Power BI als primair kanaal te kiezen). Het datamodel
moet daarnaast bruikbaar blijven als Power BI-semantisch model, voor het geval
een Power BI-dashboard alsnog gewenst is. Beide consumenten lezen dezelfde
Azure SQL-tabellen; het datamodel mag dus geen aannames bevatten die alleen in
een van de twee kloppen.

De startbezetting en de volwassen organisatiemix zijn afzonderlijk
configureerbaar. `workforce_planning.department_target_weights` stuurt de
langetermijnverdeling per afdeling; `target_weight` (per rol in `structure`; de
oude naam `fte_ratio` wordt nog als terugval gelezen) bepaalt de verdeling van
rollen binnen die afdeling. `active_from_headcount` (met `active_from_scope`:
`company`, `department` of `department_group`, en bij een groep
`active_from_departments`) houdt een rol leeg totdat de organisatie of
afdeling groot genoeg is: de rol komt dan niet in de initiële allocatie en niet
in groei-vacatures, promoties of transfers voor. De rolsleutel
`initially_staffed` staat nog in de configuratie maar wordt door de simulatie
niet gelezen (alleen een test verwijst ernaar); de sleutel `qualification_events`
staat er ook nog en is gereserveerd voor het openstaande onderdeel
"kwalificatie-events tijdens het dienstverband" (zie `BACKLOG.md`), maar wordt
eveneens niet door de simulatie gelezen. Nu worden kwalificaties alleen bij de
aanname vastgelegd en is `Verkregen_Tijdens_Dienstverband` altijd `false`.

De huidige sectorconfiguratie is `maakindustrie`.

## Wat wordt gesimuleerd

- Organisatiestructuur, rollen, locaties, contracten en managers.
- Groei, vacatures, sollicitaties, hires en non-hires.
- Uitstroom, inclusief leeftijdsafhankelijk pensioen.
- Promoties, transfers, performance en salarisreviews.
- Contractwijzigingen volgens de Nederlandse ketenregeling: een tijdelijk
  contract wordt verlengd, omgezet naar vast, of niet verlengd zodra het
  afloopt - uiterlijk bij het derde contract of na drie jaar moet het vast
  worden. Goed presterende medewerkers (top 10% van de actuele
  prestatiescores) krijgen vaker een vroegtijdige omzetting naar vast.
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
- Veiligheidsincidenten, met een risico dat per afdeling, ploegendienst en
  diensttijd verschilt; een deel daarvan levert ook verzuim op (`Bedrijfsongeval`).
- Locatietransfers: laterale verhuizingen tussen productielocaties voor
  medewerkers in een `multi_site`-rol, zonder rol- of afdelingswijziging.
- Man/vrouw-verhouding per afdeling en, waar relevant, per rol
  (`gender_ratio` in de sectorconfiguratie), zodat de samenstelling
  aansluit bij een echt productiebedrijf (bijv. Productie/Techniek
  overwegend mannelijk, Kwaliteit/HR overwegend vrouwelijk) in plaats van
  een vlakke 50/50-verdeling voor elke rol.
- Namen: elke weergavenaam ("Voornaam Achternaam", inclusief spatie) is
  maximaal `person_names.max_display_length` tekens (20) voor alle
  medewerkers, omdat iedere medewerker later manager kan worden en
  `dim_manager` uit `dim_employee` wordt opgebouwd. Een te lange naam wordt
  helemaal opnieuw getrokken (max. 100 pogingen, daarna een foutmelding; er
  wordt nooit afgekapt). Expats krijgen een naam die klopt bij hun geslacht en
  land: `special_arrangements.Expat.name_locales` koppelt een land aan een
  Faker-locale (nu Polen `pl_PL`, Roemenie `ro_RO`, Bulgarije `bg_BG`; een land
  zonder koppeling valt terug op `en_US`, nog steeds geslachtsafhankelijk).
  Poolse achternamen krijgen de vrouwelijke vorm (-ski wordt -ska), Bulgaarse
  namen worden volgens het officiele Streamlined System naar Latijns schrift
  getranslitereerd, en tekens die CP1252 niet kent (o.a. l, s, a, e met
  diakriet, Roemeense s/t met komma) worden naar gewone letters teruggebracht:
  de SQL-naamkolommen zijn `VARCHAR` met collation `SQL_Latin1_General_CP1_CI_AS`
  (CP1252). Nederlandse namen blijven ongewijzigd. Alle namen zijn
  reproduceerbaar vanuit `simulation_seed`.
- Ploegendienst: naast Productie werken ook Monteur, Teamleider Technische
  Dienst (Techniek), Magazijnmedewerker en Teamleider Logistiek (Logistiek) in
  ploegendienst (`structure.<rol>.ploegendienst`). De verdeling over Dag,
  2-ploeg en 3-ploeg staat in `ploegendienst_assignment`: `values`/`weights`
  is de standaardmix en `by_department` overschrijft de gewichten per
  afdeling (nu Techniek 40/30/30 en Logistiek 50/50/0 voor Dag/2-ploeg/
  3-ploeg). Niet-ploegrollen blijven "Niet van toepassing". De ploegendienst
  werkt door in de verzuimkans (`absence.ploegendienst_multipliers`), de
  incidentkans (`safety.ploegendienst_multipliers`) en in het verlof "Tijd
  voor tijd" (alleen 2-/3-ploeg).
- Een bewuste, functie-gecorrigeerde beloningskloof tussen mannen en
  vrouwen (`salary_benchmark.compa_ratio.gender_pay_gap`), kleiner dan het
  Nederlandse bedrijfsleven-gemiddelde maar niet nul - zie de toelichting
  bij `Streef_Compa_Ratio` verderop.

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
       Azure SQL
        /      \
       v        v
   web app   Power BI semantic model
  (LLM feature)  (optional)
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
`dim_absence_type`, `dim_shift`, `dim_salary_band`,
`dim_salary_scale`, `dim_satisfaction_band`, `dim_engagement_band`,
`dim_satisfaction_driver`, `dim_performance_driver`,
`dim_engagement_driver` en `dim_incident_type`.

`dim_education` vervangt de eerdere niveau-dimensie. Elke rij combineert een
opleidingsnaam, niveau en richting. `dim_role` is de enige bron van rolidentiteit
en geschiktheid. Naast de leesbare lijsten `Relevante_Opleidingen`,
`Logische_Doorgroei` en `Laterale_Transfers` bevat hij de geschiktheidsvoorwaarden
`Min_Relevante_Ervaring_Jr`, `Formele_Kwalificatie_Vereist`,
`Min_Opleidingsniveau`, `Leidinggevend` en `Min_Leidinggevende_Ervaring_Jr`;
de gestructureerde bron daarvoor is `role_career_paths` in de
sectorconfiguratie (een regel per rol, nu 57).

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
- `fact_employee_qualification`: kwalificatiegeschiedenis, een regel per
  behaalde opleiding van een medewerker (verwijst naar `dim_education`). Nu
  wordt precies één regel per medewerker vastgelegd, bij de aanname (initiële
  populatie en elke nieuwe hire); `Behaald_Datum` is daarbij de aannamedatum, geen
  echte diplomadatum, en `Verkregen_Tijdens_Dienstverband` is altijd `false`.
  Kwalificaties die tijdens het dienstverband worden behaald zijn niet
  gemodelleerd (open onderdeel in `BACKLOG.md`). De tabel is append-only.
- `fact_workforce_snapshot`: maandelijkse workforce-stand per actieve
  medewerker; dit is de centrale analysetabel voor medewerkerstrends.
- `fact_manager_assignment`: technische, effectieve-datumhistorie van de
  managerrelatie. Wordt bij de initiële populatie, elke gesimuleerde week en
  aan het eind van zowel een volledige als een incrementele run bijgewerkt.
  Toewijzingen zijn stabiel: een medewerker houdt zijn manager zolang die
  manager nog leidinggeeft in dezelfde afdeling en ruimte heeft. Alleen
  medewerkers zonder geldige manager, nieuwe instroom, afdelingswisselaars en
  de overloop van een te groot team worden opnieuw toegewezen. Uit dienst
  getreden medewerkers houden hun laatste manager in `dim_employee` en tellen
  niet mee voor de teamgrootte.
- `fact_salary_benchmark`: maandelijkse marktbenchmark per rol, schaal en
  salaristrede.
- `fact_performance_review`: jaarlijkse beoordeling per medewerker (zie
  hieronder voor de scoresemantiek).
- `fact_safety_incident`: één regel per veiligheidsincident, inclusief het
  incidenttype, de rol/afdeling/locatie/ploegendienst op het moment van het
  incident en de verloren werkdagen. Een incident met werkelijk verzuim
  (`Incidenttype_Naam = "Verzuimongeval"`) krijgt een bijbehorende
  `fact_absence`-episode van het type `Bedrijfsongeval`, zodat
  bedrijfsongevallen in dezelfde verzuimrapportage meelopen als gewone
  ziekmeldingen in plaats van in een geïsoleerde tabel te blijven staan. Er is
  geen sleutel tussen de twee facts; de koppeling loopt op querytijd via
  `Employee_Key` en datum (zie verderop).
  `Bedrijfsongeval` wordt uitsluitend door de veiligheidssimulator aangemaakt
  (begin op de `Incident_Date`): `absence.excluded_from_random_draw` houdt het
  type buiten de gewone verzuimtrekking, zodat elke episode een incident heeft
  en het totale aantal ziekmeldingen alleen over kort/middellang/lang
  verzuim wordt verdeeld.

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
overgedragen. Ook contractverlengingen en -omzettingen, locatietransfers,
afdelingsverhuizingen en de uitdienst-regel rollen de opgebouwde ervaring door
naar de nieuwe regel (`carried_experience`, zelfde domein), zodat
`Relevante_Ervaring_Jaren` maand op maand niet terugvalt.

Anciënniteit ("nieuw in dienst", tenure) komt in alle simulatoren uit de
aaneengesloten diensttijd (`dim_employee.Aaneengesloten_Indienst_Datum`, via
`src/infrastructure/tenure.py`), nooit uit de `Startdatum` van de actuele
`fact_employment`-regel: die wordt bij elke salarisreview, verlenging,
promotie of verhuizing opnieuw gezet. Dit geldt voor uitstroom (tenure-
multiplier, salaris-, categorie- en redenlogica), verzuim
(`minimum_tenure_days` en de `min_tenure_days` van verlofsoorten),
veiligheidsincidenten (`new_hire_multiplier`), performance reviews en de
salarisreview.

Promoties volgen uitsluitend de geconfigureerde `Logische_Doorgroei` van de
huidige rol. Een hogere salarisschaal is dus geen promotiecriterium. Interne
transfers blijven een afzonderlijke, laterale mobiliteitsroute en worden als
`Transfer` vastgelegd.

Interne kandidaten voor een promotie, transfer of de bron `Interne mobiliteit`
worden op dezelfde kwalificatie- en ervaringsregels beoordeeld als externe
kandidaten (`qualification_and_experience_reason` in
`src/infrastructure/role_eligibility.py`): het minimale opleidingsniveau van
een relevante opleiding, de WO-uitzondering voor Senior-rollen en de minimale
relevante ervaring. Hun ervaring is dezelfde waarde als in snapshots, promoties
en instroom (`carried_experience`): de startervaring van de geldende
employment-regel plus opgebouwde tijd, volledig binnen een afdeling en met
`career_events.relevant_experience_transfer_ratio` over een afdelingsgrens.
Alleen de interne regels blijven: het type beweging (`Promotie` of
`Transfer`), de minimale performance
(`career_events.internal_min_performance`, 2,7), dezelfde salarisschaal bij
een transfer en de leiderschapsdrempels
(`career_events.internal_first_leadership_min_experience_years`, 3, en
`internal_leadership_experience_discount`). Bij een promotie of transfer
binnen dezelfde afdeling houdt een medewerker in ploegendienst zijn
ploegendienst; alleen bij een andere afdeling of een niet-ploegenrol wordt de
ploegendienst opnieuw bepaald.

`fact_recruitment` heeft één regel per sollicitatie. De fact bevat zowel de
compacte tekstkolom `Status` als `RecruitmentStatus_Key`; gebruik voor nieuwe
Power BI-relaties en legendes de laatste key naar `dim_recruitment_status`.
Die dimensie bevat de korte status voor visuals, de uitleg (`Status_Omschrijving`),
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

`Kandidaat_Kwaliteit` is een gesimuleerde, latente selectiescore op een schaal
van 1-5. Het is geen werkelijk assessmentresultaat. Voor externe hires werkt
de score beperkt door in de initiële performance; voor interne kandidaten is
hij deels gebaseerd op de al bekende performance. Gebruik hem daarom alleen
als demo-indicator naast hire rate, time-to-fill, retentie en performance na
instroom.

`dim_salary_scale` is de arbeidsvoorwaardelijke salarisschaal: de schaalrange
en het aantal treden. `dim_salary_band` is juist een rapportage-indeling van
het feitelijke salaris in brede bins. `fact_workforce_snapshot` bevat beide
keys, naast `Salaris_Trede`, `Benchmark_Salaris`, `Benchmark_Verschil` en
`Benchmark_Status`. Daarmee kunnen medewerkers direct worden vergeleken met
hun marktbenchmark zonder een relatie tussen twee facts te maken.

Elke rol in `structure` heeft een expliciete `salary_scale_code`. De
rolspecifieke salarisrange en marktmediaan worden naast die functiewaardering
geconfigureerd en moeten daarmee inhoudelijk consistent blijven. Daardoor is
een schaalgrens geen impliciet toewijzingsmechanisme voor `dim_role`.

Gebruik `fact_workforce_snapshot` voor headcount, dienstjaren en slicers op
afdeling, functie, instroombron, opleidingsniveau, locatie, performance en
tevredenheid. De fact heeft een medewerker-per-maandultimo-grain en bewaart
dus de organisatiecontext die op dat moment gold. Wie precies op een
maandultimo uit dienst gaat, telt in die maand niet meer mee: een medewerker
valt uit de snapshot vanaf zijn uitdienstdatum, en de nul-dagen "Uit dienst"-
regel is nooit de regel waar een snapshot naar verwijst. Zo geldt
headcount(begin) + instroom - uitstroom = headcount(einde). Vóór de eerste
performance review toont de snapshot de startscore
(`dim_employee.Aanvangs_Prestatie_Score`) en dus niet de huidige
`Prestatie_Score`; `SalaryScale_Key` is de schaal van de geldende
employment-regel, terwijl de benchmarkbedragen van de huidige rolschaal
blijven uitgaan. Verzuim in de
uitdienstmaand en volledige `Beschikbare_*`-capaciteit voor in- en uitstromers
zijn bewust nog niet aangepast.

De snapshot bevat daarnaast `Betrokkenheid_Score`, `EngagementBand_Key`,
`EngagementDriver_Key` en de actuele `PerformanceDriver_Key`.
Betrokkenheid is bewust geen kopie van tevredenheid: loopbaanmomentum,
managercontext, performance en relatieve beloning geven elk een eigen,
begrensde bijdrage. De score heeft een kleine, gemaximeerde invloed op de
volgende performance-review en op vrijwillige uitstroom; hij beinvloedt niet
rechtstreeks de afwezigheidsduur.

**Verdeling van tevredenheid en betrokkenheid.** De scores zijn opgebouwd uit
waarneembare factoren (beloning ten opzichte van de benchmark, loopbaan/
performance/diensttijd/loopbaanmomentum en afdeling) plus wat HR niet kan
zien. Die laatste delen zijn **normaal verdeeld**: de instellingen
`individual_spread`, `manager_effect_spread`, `team_effect_spread` en
`culture_effect_spread` (tevredenheid) en `individual_spread` en
`manager_effect_spread` (betrokkenheid) zijn echte standaarddeviaties in
scorepunten (via de inverse normale verdeling van een deterministische hash; het
oude uniforme bereik gaf een standaarddeviatie van slechts 0,58 x de instelling en
harde grenzen). Daarnaast heeft elke score een **tijdsvariërend deel**
(`satisfaction.time_varying` en `engagement.time_varying`): per medewerker en
maand een gewogen som van de laatste `window_months` maandelijkse normale trekkingen
(lineair afnemend, genormaliseerd tot variantie 1, de correlatie tussen opeenvolgende
maanden is dus 0,77 bij 6 maanden) maal `sd`. Het deel hangt alleen van de
medewerker en de maand van de scoredatum af, zonder opgeslagen state: attrition,
verzuim, snapshot en vertrek geven dezelfde waarde voor dezelfde medewerker in
dezelfde maand, en een full run en een hervatte incremental run blijven identiek.
`shared_fraction` is het deel van de variantie dat uit een gedeelde "levensomstandigheden"-
trekking komt (dezelfde voor tevredenheid en betrokkenheid), de rest is
scorespecifiek. Betrokkenheid erft bovendien via `satisfaction_effect` een deel van
tevredenheid; ze blijven aparte concepten. De trekkingen voor de
constructieve-bijdragesignalen (en dus de betrokkenheidsdriver) en de
performance-eigenschappen blijven uniform.

Doelen (eerste-passkalibratie met een smalle harnas zonder weeklus, op de echte
afdelingsmix, 24 maandultimo's): tevredenheid gemiddelde 6,75 en standaarddeviatie
ca. 1,2 met banden van ca. 3% / 24% / 47% / 19% / 7% (Zeer laag ... Zeer hoog);
betrokkenheid gemiddelde 6,4 en standaarddeviatie ca. 1,2 met ca. 6% / 31% / 45% /
14% / 4%; correlatie tussen beide ca. 0,6; en voor tevredenheid verklaren de
waarneembare factoren 25-35% van de variantie. Daarvoor zijn de factoreffecten van
tevredenheid (`compa_ratio_adjustments`, `performance_effect`, `tenure_adjustments`,
loopbaanmomentum, `department_adjustments`) x1,35 opgeschaald, met behoud van tekens en
volgorde. Voor betrokkenheid geldt iets anders: **beloning is begrensde context, de
vrijwillige constructieve bijdragen sturen de score.** De bijdragesignalen
(`constructive_contribution_effect` 4,0) zijn de grootste waarneembare bron van
betrokkenheidsvariantie; prestatie en loopbaan wegen matig en de directe beloningseffecten
blijven op hun oorspronkelijke waarden (-0,45 / -0,2 / 0 / +0,08 / +0,12). Regel, afgedwongen
door een unittest: het TOTALE beloningseffect op betrokkenheid (direct plus
`satisfaction_effect` x het beloningseffect op tevredenheid) is voor elke compa-band
hoogstens 55% van het beloningseffect op tevredenheid. Een medewerker ver onder de markt
verliest zo ca. 0,68 betrokkenheidspunt (en 1,55 tevredenheidspunt). Om de correlatie met
tevredenheid ondanks de lage `satisfaction_effect` (0,15) rond 0,6 te houden, deelt
betrokkenheid 70% van de variantie van haar persoonlijke deel
(`individual_shared_fraction`) en haar hele tijdsvariërende deel (`shared_fraction` 1,0)
met tevredenheid. In plaats van "25-35% verklaard" geldt voor betrokkenheid: de
bijdragesignalen zijn de grootste waarneembare bron en beloning (direct en indirect) weegt
hoogstens ongeveer de helft van zijn aandeel in tevredenheid (nu 5,6% tegen 27,0% van de
variantie). Een hoge tevredenheid of
betrokkenheid hangt dus zichtbaar samen met beloning en loopbaan, maar de rest is
individueel en verandert door de tijd, waardoor medewerkers tijdelijk door de buitenste
banden gaan. Deze waarden zijn gekalibreerd op het harnas en niet op een full run;
herkalibreer ze als een echte run er duidelijk van afwijkt.

**Attrition en verzuim volgen de banden.** De grenzen waarmee uitstroom
(`satisfaction_attrition_multipliers`, `engagement_attrition_multipliers`, de
vrijwillig/werkgever-verdeling en de redengroepen) en verzuim
(`satisfaction_incident_multipliers`) tevredenheid en betrokkenheid indelen, zijn niet
meer vastgelegd als 4,5/6,0/7,5/8,5 maar komen uit de `Minimum_Score` van
`dim_satisfaction_band` en `dim_engagement_band`, op positie benoemd (zeer_laag, laag,
neutraal, hoog, zeer_hoog). Zo kloppen banden en gedrag altijd met elkaar, en gelden de
multipliers voor "Zeer laag" (1,8) en "Zeer hoog" (0,7) ook echt. De
`driver_selection`-drempels (`low_score`, `high_score`) zijn driverdrempels en geen
banden en blijven staan. `validate_role_configuration` eist dat elke banddimensie uit
precies vijf geordende, aaneensluitende banden bestaat en controleert de
`time_varying`-instellingen.

Elke `fact_performance_review` bevat één dominante `PerformanceDriver_Key`.
De driver verklaart het zwaartepunt van de score vanuit resultaat en
werkuitvoering, vakmanschap en relevante ervaring, samenwerking, initiatief
of coachen en kennisdeling. Verzuim, structureel overwerk en bereikbaarheid
buiten werktijd zijn geen performancefactoren. De driver
`Relevante startkwalificatie` blijft inactief totdat een opleidingsrichting en
een aantoonbare relatie met rol of domein zijn gemodelleerd; alleen
`Education_Key` is daarvoor onvoldoende.

`Prestatie_Score` is een continue score op een schaal van 1-5. Hij bestaat uit
een stabiel persoonlijk niveau (vaste gedragskenmerken, een klein
leidinggevende-effect en relevante ervaring, die na een aantal jaren afvlakt)
plus een jaarlijkse afwijking. Alleen die afwijking werkt gedeeltelijk door
naar het volgende jaar, zodat bonussen zich niet jaar na jaar opstapelen. De
parameters in de `performance`-sectie van de sectorconfiguratie zijn
gekalibreerd op een realistische Nederlandse verdeling: gemiddeld circa 3,35,
ongeveer 7% op 4,0 of hoger, minder dan 1% op 4,5 of hoger en een 5,0 vrijwel
nooit. De teruggevulde historie van de initiële populatie beslaat de meest
recente (maximaal vijf) jubilea vóór de startdatum. Na een wijziging in dit
model is een volledige run nodig.

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

`Shift_Key`, `SalaryScale_Key` en de technische
`Streef_Compa_Ratio` horen bij `fact_employment`. Een promotie, transfer of
salarisreview maakt een nieuwe employment-regel met die historische context.
`fact_absence` kopieert de ploegendienst, schaal en salarisband bij aanvang
van de afwezigheid, zodat het rapport geen facts aan elkaar hoeft te koppelen.

De salarisgenerator gebruikt dezelfde marktbenchmark als de rapportage.
Werkelijke salarissen worden gegenereerd rond een stabiele beloningspositie
ten opzichte van die benchmark; de vijf benchmarkstatussen blijven daarom
zichtbaar in de data zonder dat ze in Power BI worden geforceerd.

`Salaris` is altijd een voltijdbedrag (1,0 FTE); de pro-ratering voor deeltijd
gebeurt in de consumer. Voor dat voltijdbedrag geldt een wettelijke
ondergrens, geindexeerd via `salary_benchmark.legal_minimum_salary`:
`reference_year` (2026), `annual_full_time_salary` (EUR 31.179 excl.
toeslagen) en een map `allowances` (nu `vakantiegeld: 0.08`; extra toeslagen
zoals `eindejaarsuitkering` tellen gewoon op). De ondergrens in het
referentiejaar is `ceil(annual_full_time_salary * (1 + som(allowances)))` =
EUR 33.674 op 1 januari van dat jaar. De ondergrens is **stapsgewijs**, zoals
het Nederlandse minimumloon: hij verandert alleen op de indexatiedata
(`legal_minimum_salary.indexation_months`, standaard `[1, 7]`: 1 januari en
1 juli) en geldt op een datum met de waarde van de laatste indexatiedatum op of
voor die datum. Die waarde schaalt met `annual_market_growth_rate` (zelfde
groeifactor als de benchmark, naar boven afgerond) vanaf 1 januari van het
referentiejaar: 1 januari 2020 EUR 29.036, 1 juli 2020 EUR 29.396, 1 januari
2026 EUR 33.674, 1 juli 2026 EUR 34.089, 1 januari 2027 EUR 34.516. Na het
referentiejaar groeit hij door en voor `salary_benchmark.base_date` (burn-in)
is hij vlak (elke datum eerder dan 1 januari 2020 krijgt de waarde van
1 januari 2020). Alle salarispaden -
initieel/instroom, salarisreview, promotie/transfer en interne mobiliteit -
lopen via `SalaryPolicy.apply_floor(salaris, datum)`. Nieuw wettelijk minimum
(nieuw jaar)? Werk `reference_year`, `annual_full_time_salary` en zo nodig de
toeslagen bij **voor** een full run; `validate_role_configuration` bewaakt dat
de laagste schaal niet onder de ondergrens van het eerste jaar begint.

Een salaris verandert alleen bij aanname, promotie/transfer, interne mobiliteit
en de jaarlijkse review. Daarom brengt de wekelijkse runner na elke
indexatiedatum iedereen onder de nieuwe ondergrens op de ondergrens met de
gebeurtenis **`Minimumloonaanpassing`** (`simulate_minimum_wage_adjustments` in
`simulation_career_events.py`). Dit is de eerste salarisstap van de week, vóór
contractverlengingen, uitstroom en reviews, zodat elke regel die later die week
ontstaat al op of boven de ondergrens begint. Valt een indexatiedatum in de
zeven dagen die eindigen op de gesimuleerde maandag, dan krijgt elke actieve
medewerker met `Salaris` onder `legal_minimum(maandag)` de gewone
close-and-open-employment-beweging: de actieve regel sluit op die maandag, de
nieuwe regel start die dag met `Salaris` = de ondergrens, en al het andere wordt
overgenomen (rol, locatie, ploegendienst, schaal, `Streef_Compa_Ratio`, contract
en de doorgerolde `Relevante_Ervaring_Jaren_Bij_Start`). Er is geen opgeslagen
state: in een full run en in een hervatte incremental run gebeurt precies
hetzelfde. Wie die week zijn jaarlijkse review krijgt (zeker: eerder dan dit
kalenderjaar in dienst en `salary_increase_rate` 1) wordt overgeslagen, want die
review past de ondergrens zelf toe. De gebeurtenis telt niet als salarisreview
(een medewerker die in januari is aangepast krijgt zijn jaarreview nog gewoon),
en niet als promotie of transfer (loopbaanmomentum in tevredenheid en
betrokkenheid kijkt alleen naar `Promotie` en `Transfer`). `dim_event_type`
heeft deze gebeurtenis als laatste, negende lid, zodat bestaande sleutels niet
verschuiven.

**Ploegentoeslag.** `Salaris` is het voltijd-*basis*salaris. Daarbovenop komt
voor ploegendienst een aparte toeslag, de kolom `Ploegentoeslag` (hele euro's
per jaar, op dezelfde voltijdbasis als `Salaris`) op `fact_employment` en
`fact_workforce_snapshot`. De toeslag is een percentage van `Salaris` per type
ploegendienst, `shift_allowance.percentages` in `maakindustrie.json` (sleutels
zijn `dim_shift.Ploegendienst_Naam`): Niet van toepassing 0%, Dag 0%, 2-ploeg
12% en 3-ploeg 20%. Dit zijn **eerste-passwaarden** (een gangbare orde van
grootte in de maakindustrie, niet gekalibreerd); `validate_role_configuration`
eist een percentage voor elke ploegendienst tussen 0 en 0,5. Het totale loon is
`Salaris + Ploegentoeslag` (beide voltijd; de webapp past de FTE-pro-rata op beide
toe). De vloer (wettelijk minimum), de marktbenchmark en `Benchmark_Status`,
`Streef_Compa_Ratio`, salarisreviews, de beloningskloof-kalibratie en de
beloningsinvoer van tevredenheid en betrokkenheid gebruiken **alleen `Salaris`**
en zien de toeslag niet. De toeslag wordt op één plek berekend
(`src/infrastructure/shift_allowance.py`: `round(Salaris * percentage)`, 0 bij een
ontbrekende ploegendienst of een ontbrekend salaris) en in `post_process` voor elke
`fact_employment`-regel afgeleid uit de eigen `Salaris` en `Shift_Key` van die
regel; de snapshot kopieert hem van de geldende employment-regel zoals `Salaris`.
Daardoor geven een full run en een hervatte incremental run dezelfde waarden en
telt een herberekende waarde bij de vergelijking van gewijzigde rijen niet als
wijziging. Een beloningskloof op *totaal* loon valt groter uit dan op `Salaris`,
omdat ploegendienst mannelijk gedomineerd is. Wijzig je een percentage, dan
veranderen de toeslagen van bestaande employment-regels; een snapshotmaand die niet
meer wordt herbouwd (alleen de open maand wordt herschreven) houdt de oude waarde,
dus draai een full run na zo'n wijziging.

De laagste marktmedianen (o.a. Productie-/Magazijnmedewerker 41.000) en de
schaalranges zijn zo gekozen dat de ondergrens zelden wordt geraakt. Gemeten
met een smalle harness (alleen `SalaryPolicy`, geen weeksimulatie) is het
aandeel salarissen dat exact op de ondergrens uitkomt voor 2020/2022/2024/2026
ca. 2-4% voor Productie-/Magazijnmedewerker (instroom en initiele populatie) en
minder dan 1% voor Financieel Medewerker en HR Medewerker, en dus ongeveer
constant over de jaren (met de eerdere vlakke EUR 33.674 was dat in 2020 nog
21-41%; de stapsgewijze ondergrens verandert dat nauwelijks: 0,4-3,1%). De jaarlijkse salarisreview wordt alleen overgeslagen voor wie dat
kalenderjaar aaneengesloten in dienst kwam (niet meer voor wie eerder dat jaar
een verlenging, verhuizing of promotie kreeg).

`dim_salary_scale` heeft een open einde voor de directieschaal **Boven-CAO**
(`SalaryScale_Key` 7, code `BC`, minimum 105.000, `Maximum_Salaris` = NULL):
Managing Director, CFO, Operations Director en Commercial Director vallen
daarin (Plant Manager blijft in Schaal F). Voor die rollen is
`fact_salary_benchmark.Schaal_Max_Salaris` dus NULL; de webapp en Power BI
moeten een ontbrekend schaalmaximum aankunnen. Schaal A loopt van ca. 29.100
(afgerond boven de geindexeerde 2020-ondergrens) tot 46.000.
`validate_role_configuration` controleert dat elke rol een marktmediaan heeft,
dat de markt-P25-P75 van elke rol binnen de eigen schaal valt (bij een schaal
zonder maximum alleen het minimum) en dat de laagste schaal niet onder de
geindexeerde ondergrens van 2020 begint.

`salary_benchmark.compa_ratio.gender_pay_gap` (`female_starting_offset`,
`female_review_offset`) trekt de `Streef_Compa_Ratio` van vrouwen bewust een
klein stukje omlaag, zowel bij instroom als bij elke salarisreview. Dit is
een bewuste, functie-gecorrigeerde kloof - de generator kijkt verder nergens
naar geslacht bij beloning, dus zonder deze correctie zou het functie-
gecorrigeerde verschil in de praktijk richting 0% convergeren, wat voor een
Nederlands productiebedrijf onrealistisch positief zou zijn. Beide
offsets zijn zo gekalibreerd (op een kleine, snelle in-memory testrun, niet
een volledige full run) dat het resulterende, per-rol gecorrigeerde verschil
uitkomt op ongeveer 4-5% (gemeten 4,45% met `female_starting_offset` -0,043 en
`female_review_offset` -0,0018, na de vloer en meerdere jaren reviews) - beter dan het Nederlandse bedrijfsleven-gemiddelde
(CBS 2024: 6,1% gecorrigeerd in het bedrijfsleven, 1,7% bij de overheid) maar
niet nul. Herkalibreer deze twee waarden als een langere/grotere run een
ander resultaat oplevert.

`fact_absence` bevat zowel ziekteverzuim als niet-ziekte-afwezigheid, zoals
vakantie en ouderschapsverlof. Filter
`dim_absence_type[Telt_als_verzuim] = TRUE()` voor uitsluitend
ziekteverzuim. `Duur_dagen` is de kalenderduur van een episode; gebruik voor
verzuimpercentages de werkdag- of uurkolommen. De velden
`Tevredenheid_Score_Bij_Aanvang` en `SatisfactionBand_Key` beschrijven de
tevredenheid bij de start van de episode. Een episode die nog loopt wanneer een
medewerker uit dienst gaat (uitstroom, pensioen of een niet verlengd contract)
wordt afgekapt op de uitdienstdatum: `Einddatum`, `Duur_dagen` en de
werkdag- en uurkolommen worden herberekend, zodat er geen verzuim meer wordt
geteld nadat iemand is vertrokken. Eindigde de episode al eerder, dan blijft
hij ongewijzigd.

Maak geen directe relatie tussen facts, ongeacht of de data wordt gelezen
door de webapp of door Power BI. Facts worden via gedeelde dimensies
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
dim_incident_type       -> fact_safety_incident
```

**Geaccepteerde uitzonderingen op "facts relateren via gedeelde dimensies".**
Twee SQL-foreign keys tussen facts blijven bewust bestaan:
`fact_workforce_snapshot.Employment_Key` naar `fact_employment` (de
employment-regel waaruit de snapshotregel van die maand is afgeleid) en
`fact_recruitment.Vacancy_Key` naar `fact_vacancy` (de vacature waarop is
gesolliciteerd). Het zijn herkomstverwijzingen (lineage) die de integriteit in
SQL bewaken, geen rapportagerelaties: leg in de webapp of in Power BI geen
relatie op deze kolommen, maar join op querytijd (in Power BI met een
DAX-measure). `fact_employment.Previous_Employment_Key` is een aparte zaak: een
zelfverwijzing binnen dezelfde fact voor de keten van employment-regels. Een
nieuwe sleutel tussen facts is niet toegestaan zonder hem hier en in
`CLAUDE.md` als uitzondering vast te leggen; een schematest bewaakt de lijst.

Een `fact_safety_incident`-rij met werkelijk verzuim
(`Incidenttype_Naam = "Verzuimongeval"`) heeft geen aparte sleutel naar zijn
`fact_absence`-episode: er is bewust geen `Absence_Key`-kolom op
`fact_safety_incident`. De koppeling is op querytijd te reconstrueren via
`Employee_Key` en datum, omdat `SafetyIncidentSimulator` de episode altijd
laat starten op `Incident_Date` en een medewerker nooit twee overlappende
afwezigheidsepisodes geeft:

```sql
SELECT si.*, fa.*
FROM fact_safety_incident si
JOIN fact_absence fa
  ON fa.Employee_Key = si.Employee_Key
 AND fa.Startdatum   = si.Incident_Date
```

In Power BI is de gelijkwaardige aanpak dezelfde als bij
`fact_vacancy`/`fact_recruitment` hieronder: een DAX-measure die de koppeling
op basis van die twee velden legt, in plaats van een opgeslagen
fact-to-fact-relatie in het model.

`fact_vacancy` bevat geen `HireSource_Key`: de bron is die van de uiteindelijk
aangenomen sollicitatie in `fact_recruitment`. Gebruik voor time-to-fill per
bron daarom een join op `Vacancy_Key` op querytijd (in de webapp een gewone
SQL-join, in Power BI een DAX-measure met die key als filtercontext), niet een
fact-to-fact-relatie.

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
| `HR_SIMULATION_DRY_RUN` | Optioneel, standaard `false`. Bij `true` (alleen voor `incremental`) draait de hele pipeline en de volledige schrijftransactie, waarna alles wordt teruggedraaid; de log en het antwoord tonen per tabel hoeveel rijen er zouden zijn toegevoegd, bijgewerkt en verwijderd. Een dry run past het schema niet aan (schema-evolutie wordt overgeslagen); is het schema verouderd, dan mislukt het schrijven binnen de transactie, wordt teruggedraaid en volgt een foutmelding. De **timer negeert deze instelling** (zie onder). |
| `HR_SIMULATION_AS_OF` | Optioneel, `YYYY-MM-DD`, standaard de echte datum van vandaag. Vervangt "vandaag" in beide modi; een datum in de toekomst wordt geweigerd. De HTTP-trigger respecteert beide validatie-instellingen; **`weekly_hr_run` (de timer) negeert `HR_SIMULATION_AS_OF` en `HR_SIMULATION_DRY_RUN` altijd**: de timer draait met de echte datum en commit altijd, en logt een WARNING wanneer een van beide is gezet. Verwijder ze uit de app settings na het valideren. |
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

### Valideren tegen de demo-database (dry run en as-of)

Met twee instellingen kun je het SQL-pad valideren zonder te wachten tot er
een week voorbij is en zonder de database te wijzigen:

1. **Full run met `HR_SIMULATION_AS_OF`** twee weken terug (bijvoorbeeld
   `2026-09-16`). Dit schrijft de database en het eerste checkpoint, tot en met
   die datum.
2. **Dry-run incremental** zonder `HR_SIMULATION_AS_OF`
   (`HR_SIMULATION_DRY_RUN=true`, mode `incremental`). Er worden echt twee
   weken gesimuleerd en de volledige schrijftransactie (inclusief checkpoint)
   wordt uitgevoerd en daarna teruggedraaid. Controleer in de log de aantallen
   per tabel (toegevoegd/bijgewerkt/ongewijzigd/verwijderd) en dat er niets is
   veranderd in de database.
3. **Echte incremental** (`HR_SIMULATION_DRY_RUN` weer `false`): dezelfde twee
   weken worden nu echt geschreven.
4. **Dezelfde incremental nogmaals** als nulmeting: er is geen week meer due,
   dus er worden 0 weken gesimuleerd en 0 rijen toegevoegd of bijgewerkt. Dat
   bewijst dat de vergelijking van gewijzigde rijen klopt.

Een dry run is niet toegestaan voor een full run (die reset de database; valideer
een full run met een echte run). `HR_SIMULATION_AS_OF` werkt voor beide modi en
mag niet in de toekomst liggen; zet hem weer leeg voor normale runs.

### Full run

Zet tijdelijk `HR_SIMULATION_MODE` op `full` en roep de HTTP-endpoint aan.
Een full run bouwt de initiele populatie opnieuw op, simuleert de geschiedenis
tot vandaag en reset de beheerde SQL-tabellen. Gebruik dit voor wijzigingen in
de historische simulatielogica of het datamodel. Verouderde beheerde tabellen
(waaronder `fact_salary_snapshot`) en verouderde kolommen (`deprecated_columns`
in het schema) worden bij elke schrijfactie verwijderd, dus ook bij een
incremental run; een full run is daarvoor niet nodig.

**Draai een full run altijd lokaal** (`func start`), niet op de gedeployde
Function App. Een full run duurt met de huidige sectorconfiguratie meer dan twee
uur, en op het Consumption-plan is de maximale looptijd van een functie 10
minuten, dus een full run op de gedeployde app wordt afgebroken. Lokaal speelt
die grens niet: `host.json` zet `functionTimeout` bewust op `-1` (onbeperkt) en
een lokale `func start` houdt zich daaraan. De 10 minuten gelden voor de
gedeployde app, waar alleen de wekelijkse incremental run hoort te draaien. De
HTTP-aanroep blijft tijdens een lokale full run open totdat die klaar is.

De run houdt gedurende de hele looptijd een SQL-lock (`sp_getapplock`) vast op
een verbinding die niets anders doet. Verliest die verbinding de lock (Azure SQL
of het netwerk verbreekt een inactieve verbinding), dan kan een timer-run op de
gedeployde app tegelijk met jouw schrijfactie draaien. Daarom controleert de
writer vóór de eerste schrijfactie, en nogmaals vlak vóór de datatransactie,
dat de lock nog wordt vastgehouden (`SimulationLock.verify`,
`APPLOCK_MODE`). Een lock die tijdens de inactiviteit is verloren, hoeft niet
fataal te zijn: er is alleen overlap als een andere run ertussen echt heeft
geschreven. Daarom legt de run direct na het nemen van de lock een vingerafdruk
van `simulation_state` vast (volgende te simuleren week en `last_run`, of "geen
rij"). Is de lock weg, dan probeert `verify` het eenmalig opnieuw op een verse
verbinding (`sp_getapplock`, zelfde resource, timeout 0). Lukt dat en is de
vingerafdruk ongewijzigd, dan logt de run een WARNING ("simulation lock was lost
while idle and re-acquired; no other run wrote in between"), houdt de nieuwe
verbinding de lock vast (en geeft die aan het eind vrij) en gaat de run door. Kan
de lock niet worden teruggenomen (een andere run houdt hem) of is de
vingerafdruk veranderd, dan stopt de run met `SimulationLockLostError` voordat er
iets is geschreven; de oude data en het oude checkpoint blijven staan en je
start de run opnieuw. Dit geldt ook voor een full run. De controle is een
momentopname: de tijd die het schrijven zelf kost, valt daarbuiten.

Een full run is ook vereist na wijzigingen aan recruitmentbronprofielen,
recruitmentstatussen, de interne-mobiliteitslogica of snapshotkolommen zoals
de driverkeys en `Relevante_Ervaring_Jaren`. Een incremental run kan
nieuwe dimensiekolommen en statuskeys aanvullen, maar kan historische
snapshotwaarden en sollicitatie-uitkomsten niet realistisch hersimuleren.

Zet de instelling na afloop terug op `incremental`. Een full run schrijft ook
het eerste checkpoint waarmee incremental runs daarna verdergaan.

### Incremental run

Een incremental run is een full run die vanaf een checkpoint wordt
hervat: beide modi lopen door dezelfde pipeline
(`src/application/pipeline.py`: `prepare_state` - `run_weeks` -
`post_process` - `store.write`). De incremental run leest de beheerde tabellen
en het checkpoint uit `simulation_state`, simuleert alle weken vanaf de
volgende nog te simuleren week tot en met de week van vandaag en werkt de
tabellen bij. Actuele dimensies en facts met nabewerkte gebeurteniscontext,
zoals `fact_employment` en `fact_absence`, worden bijgewerkt.

Het checkpoint bevat: de `simulation_seed`, `next_year`/`next_week` (de
**volgende** week die nog gesimuleerd moet worden, dus een week wordt nooit
twee keer gesimuleerd; `current_year`/`current_week` blijven de laatst
gesimuleerde week ter leesbaarheid), een vingerafdruk van de sectorconfiguratie
en de simulatiestate die geen tabel is (`checkpoint_json`: geopende locaties en
hun capaciteitsstreak, verhuisde afdelingen, de kandidaatprofielen van de
lopende recruitmentpipeline en openstaande vacatureverzoeken). Welke
statesleutels bewaard worden en welke tijdelijk zijn staat in
`STATE_KEY_REGISTER` (`src/infrastructure/state/checkpoint.py`); een nieuwe
sleutel die daar niet in staat, laat de run falen.

Elke gesimuleerde week gebruikt een eigen willekeurige stroom,
`Random(f"{seed}:{jaar}:{week}")`, en zet de naamgenerator opnieuw op
`f"{seed}:{jaar}:{week}:names"`; de initiële populatie heeft een eigen stroom
(`{seed}:population`). Een week geeft daardoor dezelfde uitkomst, ongeacht
hoeveel weken er eerder in hetzelfde proces zijn gesimuleerd. De jaarlijkse
groeivoet wordt eenmalig uit `Random(f"{seed}:growth-rate")` afgeleid en is dus
in elke run gelijk. Acceptatie-eis: een full run tot week N geeft dezelfde
tabellen als een full run tot week N-1 gevolgd door een incremental week
(`src/tests/test_pipeline_equivalence.py`).

Na het deployen van deze versie heeft de bestaande database geen checkpoint en
een andere sleutelindeling voor `fact_salary_benchmark`: **draai eerst een full
run**; een incremental run stopt anders met de melding dat er geen checkpoint
is. Ook een andere `HR_SIMULATION_SEED` dan die van het checkpoint stopt de
run; een gewijzigde sectorconfiguratie geeft alleen een waarschuwing in de log.
Alleen `full` en `incremental` zijn geldige waarden voor `HR_SIMULATION_MODE`.
Afrondingsverschillen van SQL-`DECIMAL`-kolommen tussen een in-memory run en
een run via SQL worden geaccepteerd.

#### Schrijven naar SQL

**Schrijfmodus per tabel.** Elke tabel in `hr_maakindustrie_schema.json` heeft
`write_mode`: `upsert` (nieuwe sleutels invoegen en gewijzigde rijen bijwerken)
voor alle `dim_*`-tabellen (ook de statische, zodat wijzigingen in de
configuratie de beschrijvende kolommen bereiken; sleutels blijven behouden),
`fact_employment`, `fact_absence`, `fact_recruitment`, `fact_vacancy`,
`fact_manager_assignment` en `fact_workforce_snapshot`; of `append` (alleen
nieuwe sleutels, een bestaande rij wordt nooit gewijzigd) voor
`fact_performance_review`, `fact_safety_incident`,
`fact_employee_qualification` en `fact_salary_benchmark`. Een nieuwe tabel moet
een `write_mode` declareren (een schematest dwingt dat af). De
equivalentietests op `InMemoryStore`, die dezelfde schrijfmodi toepast, zijn het
bewijs dat de indeling klopt: een `append`-tabel waarvan bestaande rijen in het
geheugen veranderen laat die tests falen.

**Alleen gewijzigde rijen.** De incremental load bewaart per tabel een
genormaliseerde baseline (een digest per primaire sleutel). Bij het schrijven
worden alleen rijen weggeschreven die nieuw zijn of waarvan de waarden
afwijken, zodat een incrementele week ruim binnen de 10 minuten van het
Consumption-plan blijft. Beide kanten worden op dezelfde manier genormaliseerd:
waarden volgen het schematype, `DECIMAL(p,s)` wordt op zijn schaal afgerond
(een opnieuw berekende 6,8123 is gelijk aan de opgeslagen 6,81, anders zou
vrijwel elke herberekende rij als gewijzigd tellen), NaN/None/NaT zijn gelijk,
datums worden als datum vergeleken en gehele getallen en kommagetallen met
dezelfde waarde zijn gelijk. De log toont per tabel toegevoegd/bijgewerkt/
ongewijzigd/verwijderd. Een full run leegt de beheerde tabellen en voegt alles
in bulk in. Rijen worden bij het laden in volgorde van de primaire sleutel
gelezen (`ORDER BY`), omdat de simulatoren tabellen in rijvolgorde doorlopen en
daarbij willekeurige getallen trekken; beide modi starten de weeklus vanuit
dezelfde volgorde (`canonicalize_row_order`).

**Atomair schrijven.** Eerst volgt schema-evolutie buiten de datatransactie
(ontbrekende tabellen en kolommen, verouderde tabellen en kolommen, constraints
en de kolommen van `simulation_state`). Daarna volgt **een transactie op een
verbinding**: bij een full run het leegmaken plus alle inserts, bij een
incremental run alle inserts, updates en deletes (bij een full run worden de
tabellen in omgekeerde schrijfvolgorde leeggemaakt, kinderen eerst, zonder
foreign keys uit te zetten), en als **laatste statement**
het checkpoint in `simulation_state`. Mislukt er iets (bijvoorbeeld een vol
transactielog op een kleine tier tijdens een full run), dan wordt alles
teruggedraaid en blijven de oude data en het oude checkpoint staan; de log zegt
dat expliciet. Het lezen van de state (`load_current_state`) faalt luid bij
elke fout behalve "tabel bestaat niet".

**Wat de webapp ziet tijdens het schrijven.** Azure SQL gebruikt standaard
`READ_COMMITTED_SNAPSHOT`: lezers (webapp, Power BI) blijven bij zowel een
incremental als een full run de oude, consistente data zien tot de commit en
zien dus nooit een half geschreven of leeg gemaakte tabel. De transactie bevat
bewust geen `ALTER TABLE` (ook geen tijdelijk uitzetten van foreign keys): dat
neemt een schema-modificatielock die ook snapshot-lezers tot de commit blokkeert.
Een mislukte delete of insert draait alles terug en laat de oude data staan.
(Alleen schema-evolutie, zoals een nieuwe kolom, gebeurt vooraf buiten die
transactie en wordt bij een dry run overgeslagen.) `DECIMAL`-waarden worden als
`Decimal` verstuurd, afgerond op precies dezelfde manier als de vergelijking van
gewijzigde rijen (halve waarden omhoog): een `float` zou SQL Server anders
afronden (6,805 wordt 6,80) en elke run als wijziging laten tellen.

**Verwijderde rijen.** Geen enkele tabel verliest rijen tijdens een run, met een
uitzondering: `fact_workforce_snapshot` (`"delete_missing": true`). De open maand
wordt bij elke run herbouwd; een medewerker die na de vorige run op of vóór de
maandultimo uit dienst gaat, valt uit die maand (zie de snapshotregel bij
`fact_workforce_snapshot`) en zijn rij wordt binnen de transactie verwijderd. Een
ingeladen rij die in een andere tabel ontbreekt, geeft een duidelijke fout en er
wordt niets geschreven.

**Snapshots en benchmarks: alleen de open maand.** Een incremental run bouwt
`fact_workforce_snapshot` en `fact_salary_benchmark` alleen voor de maandultimo's
vanaf de eerste dag van de maand waarin de eerste gesimuleerde week valt en voegt
ze samen met de ingeladen rijen (eerdere maanden blijven ongemoeid; de open maand
wordt bij elke run herschreven). Een full run bouwt alles. De sleutels zijn
deterministisch: `WorkforceSnapshot_Key` = `yyyymm * 10000 + Employee_Key` en
`SalaryBenchmark_Key` = `yyyymm * 10000 + Role_Key * 100 + Salaris_Trede` (past
in een `INT`; configuratievalidatie eist `Role_Key` en het aantal treden onder
100), zodat het toevoegen van een rol of trede geen bestaande sleutels verschuift.
De kosten van de simulatie zelf groeien nog met de geschiedenis (AR-18, open).

## Configuratie

`maakindustrie.json` bevat onder andere:

- `initial_population`: omvang, burn-in en dienstjarenverdeling, plus
  `hire_source_weights`: de mix van externe instroombronnen van de initiële
  populatie (Vacaturebank 52,5, Campus 14,8, Interne recruiter 14,7, Referral
  11,4, Recruitmentbureau 6,7 - gemeten aan `fact_recruitment` met status
  Aangenomen). Een bron zonder gewicht krijgt 0; zonder gewichten is de keuze
  uniform. `validate_role_configuration` controleert dat elke bron bestaat en
  extern is.
- `growth`: groeipad, capaciteit en economische gebeurtenissen.
- `structure`: afdelingen, rollen, salarisbanden en managementrollen.
- `gender_ratio`: man/vrouw-verhouding per afdeling, met `role_overrides`
  voor rollen die van hun afdelingsgemiddelde afwijken (bijv.
  Productontwikkelaar binnen R&D); `default` geldt voor niet-genoemde
  afdelingen. `salary_benchmark.compa_ratio.gender_pay_gap` bevat de aparte
  offsets voor de bewuste beloningskloof.
- `person_names`: maximale lengte van de weergavenaam
  (`max_display_length`). `special_arrangements.Expat.name_locales` bepaalt per
  land de naamlocale.
- `recruitment`: volume en uitkomstlogica van sollicitaties.
- `absence`: type-specifieke kansen, duur en eligibility-regels.
- `career_events`: performance, salarisgroei, promoties en transfers.
  `career_events.chain_rule` bevat de ketenregeling-parameters
  (`max_contract_rounds`, `max_temporary_years`, `renewal_duration_years`,
  `top_performer_percentile`, `top_performer_conversion_kans`);
  `contract_rules.<afdeling>.keten_conversion_kans` stuurt de kans op omzetting
  naar vast zodra de wettelijke grens is bereikt.
- `satisfaction`: de scoreverdeling en effecten van relatieve beloning,
  manager, performance, diensttijd en afdeling. De `*_spread`-waarden zijn
  standaarddeviaties van normaal verdeelde delen; `time_varying` (`sd`,
  `window_months`, `shared_fraction`) is het maand-op-maand variërende deel.
- `engagement`: de scoreverdeling en effecten van tevredenheid, relatieve
  beloning, manager, performance, loopbaanmomentum en afdeling, met dezelfde
  betekenis van `*_spread` en `time_varying`.
- `attrition`: uitstroompercentages per afdeling, plus de invloed van
  tevredenheid en betrokkenheid op vertrek- en vertrekredenlogica.
  `no_show_max_tenure_days` (30): de vertrekreden `No-show` is alleen mogelijk
  binnen zoveel dagen aaneengesloten diensttijd. De reden `Seizoenswerker` staat
  in `dim_departure_reason` maar wordt nu nooit gebruikt, omdat er geen
  seizoenscontracten worden gemodelleerd (`contract_rules.*.zomer_kans` is
  ongebruikte configuratie); hij blijft staan omdat verwijderen de positionele
  sleutels van latere redenen zou verschuiven. `Contract niet verlengd` hoort bij
  de categorie `tijdelijk` en wordt alleen door de contractsimulator gebruikt.
- `salary_benchmark`: marktmedianen per rol, marktgroei, treden en de
  classificatie onder/rond/boven benchmark.
- `retirement`: pensioen vanaf 50, met de grootste uitstroom rond 65 en een
  harde bovengrens op 67.
- `avatar`: publieke Blob Storage-basis-URL, vaste toewijzingsseed en het
  aandeel neutrale avatars voor mannen en vrouwen.
- `safety`: jaarlijkse incidentkans per afdeling, de vermenigvuldigers voor
  ploegendienst en nieuwe medewerkers, de gewichten per incidenttype en de
  bandbreedte voor verloren werkdagen bij een `Verzuimongeval`.
  `safety.annual_incident_rate_by_department` is een *basis*kans; de
  gerealiseerde kans per medewerker-jaar is basis x verwachte ploegfactor x
  verwachte nieuwe-medewerkerfactor. `safety.target_incident_rate_by_department`
  (Productie 0,35, Techniek 0,30, Logistiek 0,25) legt de gewenste
  gerealiseerde kans vast en `safety.calibration.new_hire_share_by_department`
  (gemeten aandeel medewerkers binnen 180 dagen diensttijd: 19,7% / 16,9% /
  15,7%) is de invoer voor de nieuwe-medewerkerfactor. De helper
  `src/infrastructure/safety_calibration.py` rekent de verwachte kans uit
  configuratie uit (aandeel ploegrollen uit `allocate_headcount` op de
  groeigrens, ploegmix, multipliers) en geeft met `calibrated_base_rate` de
  basiskans die het doel haalt; een test bewaakt dat de gerealiseerde kans
  binnen 10% van het doel blijft. Huidige basiskansen: Productie 0,26,
  Techniek 0,25, Logistiek 0,21.
- `absence.excluded_from_random_draw`: verzuimtypen die een andere simulator
  beheert (nu `Bedrijfsongeval`). `validate_role_configuration` controleert
  dat `Bedrijfsongeval` bestaat en hierin staat, en dat elke sleutel van
  `attrition.voluntary_reason_satisfaction_multipliers` een bestaande
  vertrekreden is.

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
`simulation_parameters` in `pipeline.py`) — er is dus geen organische groei tijdens de burn-in en
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

De meerweekse pipeline-equivalentietests zijn gemarkeerd als `slow` en worden
standaard overgeslagen (`addopts = -m "not slow"` in `pytest.ini`). Draai ze met
`python -m pytest -q -m slow`; dat moet ook slagen voordat je wijzigingen aan de
pipeline, de state of de SQL-writer commit.

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
| `pyodbc.OperationalError: Login timeout expired (HYT00)` | Voorbijgaande Azure SQL-verbindingsstoring. `acquire_simulation_lock` doet hiervoor automatisch een paar nieuwe pogingen (`CONNECT_ATTEMPTS`/`CONNECT_RETRY_DELAY_SECONDS` in `simulation_lock.py`); houdt de storing langer aan, controleer de DTU/verbindingsbelasting van de database (vooral bij een kleine tier zoals S0) en of de firewallregels nog kloppen. |
| `SimulationLockLostError` ("The simulation lock is no longer held" of "could not be verified") | De inactieve lock-verbinding is tijdens de run verbroken en de lock kon niet veilig worden teruggenomen: een andere run houdt hem, of `simulation_state` is veranderd terwijl de lock weg was. De writer schrijft dan niets en er is niets gewijzigd. Controleer dat er geen andere run is gestart en draai de run opnieuw. Was er geen andere run, dan staat er in de log een WARNING "re-acquired" en gaat de run gewoon door. |
| De HTTP-endpoint geeft een algemene 500 met een "reference" | Zo gedraagt de gedeployde app zich: de volledige fout staat in de Function App-logs onder diezelfde reference. Lokaal (`func start` zet `AZURE_FUNCTIONS_ENVIRONMENT=Development`) bevat het antwoord de volledige foutmelding. |
| De wekelijkse timer-run toont "Succeeded" maar er is geen nieuwe data | Controleer de logs op "Weekly HR job failed": `weekly_hr_run` gooit de fout sinds kort opnieuw op na loggen, dus een mislukte run staat voortaan ook als Failed in Azure. |

## Deployen

Publiceer de inhoud van `azure_function/` naar de Azure Function App via de
CI/CD-pipeline of Azure Functions Core Tools. Voeg de runtime-instellingen als
Application Settings toe in Azure; kopieer `local.settings.json` niet naar de
repository of de deployment.

Bij een gedeployde Function App vereist de HTTP-endpoint een function key.

Voor een release met simulatielogica- of schemawijzigingen:

1. Voer `python -m pytest -q` uit vanuit `azure_function/`.
2. Deploy de Function App en controleer de Application Settings.
3. Voer eenmaal een handmatige full run uit, **lokaal** (zie "Full run"): op de
   gedeployde app stopt een full run na 10 minuten (Consumption-plan).
4. Controleer dat de webapp de gewijzigde tabellen correct oppikt; vernieuw
   indien er ook een Power BI-dashboard actief is de gewijzigde tabellen daar
   en controleer nieuwe relaties.
