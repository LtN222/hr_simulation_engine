
# Marketing dashboard data generator

## Description
Dit project genereert marketinggegevens voor dashboards.
De gegevens kunnen in een keer worden gegenereerd, daarna kan de data dagelijks iteratief worden geupdate.
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
session config
↓
initial session generation (full)
↓
dataframe
↓
state update
```
Incremental generation:
```
current state
↓
daily simulation
↓
dataframe
↓
state update
```

## Projectstructuur

```
config/
├── session configs (bijv. parameters.json)

src/
├── generator.py
├── parameters.py
├── utils.py
```

## Generator Flow

1. generate_dataset.py <br>
&#x21b3; initiate Generator  
&#x21b3; generate_data() &larr; generator.py  
&#x21b3; save_data() &larr; generator.py  
2. generate_data() <br>
&#x21b3; 1. _add_new_campaigns() &rarr; campaign generation  
&#x21b3; 2. _sample_campaign_ids() &rarr; _generate_sessions() &rarr; session sampling  
&#x21b3; 3. _generate_interaction() &rarr; interactie generation  
&#x21b3; 4.  &rarr; conversie bepaling  
&#x21b3; 5. source generation  
3. save_data() <br>
&#x21b3; 1. save data to csv  
&#x21b3; 2. save state to json


## Bijdragen aan de code

Om het algoritme te verbeteren of uit te breiden is het goed om de structuur van de code te begrijpen.  
In de 