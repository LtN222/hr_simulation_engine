## ⚙️ Azure Portal – Snelle aanpassingen

Deze sectie beschrijft hoe je gedrag van de HR Data Generator aanpast **zonder code te wijzigen**.

Alle instellingen worden beheerd via **Environment Variables** in de Function App.

---

### 🔹 Waar vind je dit?

Ga in Azure Portal naar:

1. Function App (`fa-demo-hr-datagenerator`)
2. **Settings → Environment Variables**
3. Tab: **Application settings**

---

## 🔹 Planning aanpassen (timer)

Zo pas je het moment van de wekelijkse run aan.

### Variabele:

```text
HR_TIMER_SCHEDULE
```

### Voorbeeld:

```text
0 0 2 * * 1
```

👉 Betekent: elke maandag om 02:00 (UTC)

---

### 🔸 Veelgebruikte schema’s

| Beschrijving       | Waarde        |
| ------------------ | ------------- |
| Elke dag 02:00     | `0 0 2 * * *` |
| Elke maandag 02:00 | `0 0 2 * * 1` |
| Elke zondag 01:00  | `0 0 1 * * 0` |

⚠️ Let op: tijden zijn in **UTC**

---

## 🔹 Simulation mode aanpassen

### Variabele:

```text
HR_SIMULATION_MODE
```

### Mogelijke waarden:

| Waarde        | Gedrag                              |
| ------------- | ----------------------------------- |
| `full`        | Volledige dataset opnieuw genereren |
| `incremental` | Alleen nieuwe weken genereren       |

---

### ⚠️ Belangrijk

* De **timer gebruikt altijd incremental mode**
* Deze setting geldt alleen voor:

  * handmatige API calls
  * lokale runs

---

## 🔹 Sector aanpassen

### Variabele:

```text
HR_SECTOR
```

### Voorbeeld:

```text
maakindustrie
horeca
retail
```

👉 Bepaalt welke configuratie wordt gebruikt
Op dit moment is alleen 'maakindustrie' beschikbaar

---

## 🔹 Seed aanpassen (optioneel)

### Variabele:

```text
HR_SIMULATION_SEED
```

👉 Bepaalt random gedrag van simulatie
👉 Zelfde seed = reproduceerbare resultaten

---

## 🔹 Na aanpassen

1. Klik **Save**
2. Function App herstart automatisch
3. Nieuwe instellingen zijn direct actief

---

## 🔹 Veelgemaakte fouten

* ❌ Verkeerde cron syntax
* ❌ Vergeten dat tijd in UTC is
* ❌ Typfout in variabelenaam
* ❌ Verwachten dat timer “full” draait

---

## 🔹 TL;DR

Je kunt aanpassen zonder deploy:

* ⏰ wanneer de job draait → `HR_TIMER_SCHEDULE`
* 🔁 hoe hij draait → `HR_SIMULATION_MODE`
* 🏭 welke sector → `HR_SECTOR` (op dit moment is alleen 'maakindustrie' beschikbaar)

---
