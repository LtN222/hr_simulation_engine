## Feedback Joshua (in progress)
Mail
    Weet je zeker dat je hier (alleen) je Heeyoo mail adres wilt gebruiken? Mijn zege heb je om er ook een persoonlijke te vermelden en/of een link naar de GitHub repo als je dat wilt.
    Andersom zou ik je werkmail verwijderen als je dit script in een persoonlijke repo zet. Als je werkmail door een scraper uit je repo wordt getrokken kan die belanden in een spam list en dat kan vervelend worden.
Prerequisites
    Horen de libraries hier niet bij?
Create and activate a virtual environment
    Heel netjes dat je dat beschrijft. Had wat mij betreft niet echt gehoeven, maar ik zie het graag!
Usage
    Ik zou hier dan wss ook nog vermelden hoe je de parameter file in moet vullen. Iemand die het algoritme voor het eerst gebruikt, zal dat bij de eerste poging (en wss ook de opvolgende) verpesten.
Aanvullende feedback volgt..

# Marketing dashboard data generator
Auteur: Christian Steennis (<christian.steennis@heeyoo.nl>)

## Description
Dit project genereert marketinggegevens voor dashboards.
De gegevens kunnen in een keer worden gegenereerd, daarna kan de data dagelijks worden geupdate. Eventueel langere perioden tussen updates kan ook, de data wordt dan iteratief per dag aangevuld tot de dag van updaten.
De gegenereerde data bestaat uit sessies met klik- en paginaweergave-trends.
De sessies zijn campagne gedreven, dat wil zeggen elke elke sessie is gegenereerd vanuit een marketingcampagne.

## Prerequisites
- Python 3.x
- Git

## Installation
Clone the repository
```bash
git clone https://Heeyoo-Services@dev.azure.com/Heeyoo-Services/Beheer/_git/Demo_Dashboards
cd Demo_Dashboards/marketing_data_generator
```

### Create and activate a virtual environment
Windows:
```bash
python -m venv .venv
.venv\Scripts\activate
```
MacOS/Linux:
```bash
python -m venv .venv
source .venv/bin/activate
```
### Install required packages
```bash
pip install -r requirements.txt
```
## Usage
For creating a custom dataset interactively:
```bash
python generate_dataset.py
```

For generating a quick dataset from preset parameters:
```bash
python generate_dataset.py test
```

For generating a dataset with parameters from a file:
```bash
python generate_dataset.py -p [PARAMETER_FILE.json]
```

For updating an existing dataset:
```bash
python generate_dataset.py update
```

## Overzicht van de pipelines

Initial generation:
```
config (parameter file or interactive configuration)
↓
initial session generation (full)
↓
save dataframe to csv
↓
state update
```
Incremental generation: (single day or multiple days iteratively)
```
current state
↓
daily simulation
↓
save dataframe to csv
↓
state update
```

## Projectstructuur

```
config/
├── generator configs (bijv. parameters.json)

src/
├── generator/
    ├── base_generator.py
    ├── historical_generator.py
    ├── incremental_generator.py
    ├── interaction_generator.py
    ├── session_generator.py
    ├── campaign_manager.py
├── parameters.py
├── utils.py
```

## Uitleg van de code

### Generators
De generator bestaat uit 2 verschillende flows. Beide flows hebben hun eigen class, `HistoricalGenerator` en `IncrementalGenerator`, beide erven van de base class `DataGenerator`. In `DataGenerator` is de hoofdflow voor het genereren van records gedefinieerd en wordt de state bijgehouden. De `generate_dataset()` functie is de kern van de class en wordt gebruikt voor zowel historische data generatie als de update functionaliteit. Nadat de data hiermee is gegenereerd moet het resulterende dataframe worden opgeslagen met de `save_data()` functie, ook onderdeel van de `DataGenerator` class, ook de huidige state met daarin alle configuratie informatie die nodig is om de trends door te trekken in een nieuwe generatie wordt weggeschreven naar een json bestand.

#### Historische generatie
Voor het genereren van historische data wordt de uitgelezen configuratie klaargezet voor gebruik in state. Ook worden op basis van de configuratie campagnes gegenereerd via de `campaign_manager`. De eigenschappen van de campagnes worden ook opgeslagen in de state. Vervolgens wordt de generieke `generate_dataset()` functie aangeroepen.


#### Incrementele generatie
Om bestaande data te genereren wordt een eerder weggeschreven state uitgelezen. De configuratie bevat de gegevens om de voorgaande campagne trends door te zetten. `IncrementalGenerator` definieert een loop waarin steeds records van één dag worden gegenereerd. Deze loop genereert records vanaf de laatste dag in de state tot de dag dat het programma wordt gestart. In deze loop wordt steeds met een kans van 10% (hardcoded op dit moment) een nieuwe campagne gestart. Bij het starten van een nieuwe campagne worden meteen de eigenschappen van deze campagne toegevoegd aan de state. 

Het aantal records voor een nieuwe dag wordt dynamisch bepaald op basis van het aantal records op de laatst gegenereerde dag. Er wordt met de eigenschappen van alle campagnes bepaald of het totaal aantal records zou moeten groeien of dalen. Hierbij wordt onafhankelijk een basetrend bijgehouden.

### Generator componenten

De daadwerkelijke generator `DataGenerator` definieert de hele flow van de data generatie. Met behulp van verschillende componenten worden sessies gegenereerd die ontstaan uit campagnes en een base trend. Elk van deze sessies krijgt interacties toegewezen op basis van campagne eigenschappen. De rest van de sessie data (device, city, traffic_source, country) is volledig willekeurig. De functie zorgt uiteindelijk dat de state up to date is en dat de data opgeslagen wordt in een dictionary, deze wordt later in de aparte generators omgezet naar een pandas dataframe.

De flow is opgedeeld in 3 componenten: campaign manager, session generator en interaction generator.

#### Campaign manager

De campaign manager heeft 2 functies: 
1. Het genereren van nieuwe campagnes en deze toevoegen aan de state
2. Het aantal records per campagne bepalen

Het genereren van de campagnes gebeurt willekeurig binnen een bepaalde range. De trend van een campagne is gebaseerd op een scheve normaal verdeling. Waarbij de scheefheid, standaardafwijking en piek willekeurig worden bepaald. In het geval van een update van bestaande data wordt de piek van de campagne zo verschoven dat het begin (waar de kans op een sessie minder dan 0.1% is) bij de huidige dag uitkomt. Vervolgens worden ook de eigenschappen van de verdelingen van de interacties willekeurig toegewezen aan de campagnes. 
NOTE: de randwaarden voor deze generatie zijn nu allemaal hardcoded op basis van eigen inzicht. 

Het aantal records dat er per campagne wordt gegenereerd wordt op basis van de theoretische activiteit en het bereik van de campagnes berekend. Er wordt een willekeurige reeks campagne ids gesampled waarbij de waarschijnlijkheid van elke campagne gelijk is aan de theoretische activiteit vermenigvuldigd met het toegewezen bereik van de campagne.

#### Session generator

De sessie generator is verantwoordelijk voor het genereren van de sessie dagen en tijden. De generator doet dit voor zowel het de sessies van de base trend als de sessies behorend bij de campagnes. 

Voor de sessies worden eerst de dagen gesampled. Voor de campagne sessies gebeurt dit volgens een scheve normaal verdeling waarvoor de parameters eerder in de state zijn opgeslagen. 
Om te zorgen dat de datums binnen de gegeven tijdsinterval vallen wordt rejection sampling toegepast. Dit houdt in dat datums die buiten de interval uitkomen opnieuw worden gesampled. Om tijd te besparen als veel datums buiten de interval vallen door bijvoorbeeld een uitgedoofde campagne worden deze datums statistisch gedwongen binnen de interval uit te komen. Dit is trager dan direct samplen uit de scheve verdeling en heeft niet de voorkeur maar garandeert wel een correcte werking.

Voor de basetrend worden de waarden uit een lineare verdeling gesampled.

Nadat de juiste datums bekend zijn wordt voor elke sessie een tijd gesampled. Dit gebeurt volgens een normaal verdeling zodat de tijden gecentreerd liggen rond de middag zodat er 'snachts minder sessies zijn als overdag.

#### interaction generator

De interactie generator simuleert de gedragingen van gebruikers tijdens een sessie. Hoe gebruikers zich gedragen is gebaseerd op de eigenschappen van de individuele campagnes. 

De interactie bestaat uit 4 onderdelen:
1. Het aantal bezochte pagina's (page views)
2. Het aantal site elementen waarop geklikt is (clicks)
3. Het aantal minuten dat de site bezocht is (visit duration)
4. Een berekening waaruit volgt of er een conversie plaatsvind naar aanleiding van de sessie

Het aantal bezochte pagina's vormt de basis voor de andere interacties. Dit wordt bepaald door een geometrische distributie. Deze distributie houd in dat met een kans `p` een volgende pagina wordt bezocht. Dit zorgt ervoor dat aantal bezochte pagina's altijd minstens 1 is en afhankelijk van `p` meer wordt, lees meer in de [scipy docs](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.geom.html#scipy.stats.geom). Bij het genereren van een campagne wordt deze kans willekeurig bepaald per campagne.  

Voor het aantal clicks zijn ook de parameters weer per campagne gegenereerd in de campaign manager tijdens de setup van de update of historische flow. In dit geval wordt de [poisson distributie](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.poisson.html#scipy.stats.poisson) gebruikt. Het minimum van de distributie wordt bepaald door het minimaal aantal clicks per pagina vermenigvuldigd met het aantal bekeken pagina's.

Hetzelfde geldt voor de bezoekduren. Alleen wordt hier een [gamma distributie](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.gamma.html#scipy.stats.gamma) gebruikt. De waarden die uit de gamma distributie komen zijn in minuten, ook weer rekening houdend met de minimale tijd per pagina en het aantal bezochte pagina's. De minuten worden omgezete naar `numpy.timedelta64['m']` objecten voor efficient optellen bij de sessie tijden.

## Ideeën voor toekomstige features

- min en max voor de verschillende campagne eigenschappen genereren op basis van verschillende soorten campagnes (bijv. social media, billboard, krant, televisie)
