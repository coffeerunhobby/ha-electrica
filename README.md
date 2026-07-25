# Electrica România — Integrare Home Assistant

[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.12%2B-41BDF5?logo=homeassistant&logoColor=white)](https://www.home-assistant.io/)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

Integrare neoficială Home Assistant pentru **Electrica România**
([myelectrica.ro](https://www.myelectrica.ro)). Aduce în Home Assistant facturile,
soldul, indexul contorului, istoricul citirilor și consumul — plus posibilitatea
de a **trimite autocitirea** direct din Home Assistant.

> ⚠️ Proiect dezvoltat de comunitate, neafiliat cu Electrica România.
> Funcționează prin API-ul folosit de portalul myelectrica.ro.

---

## Funcționalități

- Autentificare simplă cu e-mail și parolă (**fără 2FA**).
- Un **dispozitiv per loc de consum (NLC)**, denumit după adresă.
- Senzori pentru: sold de plată, ultima factură, scadență, restanțe, indexul
  contorului, fereastra de autocitire, consumul convenit și ultima plată.
- **Consumul apare nativ în Energy Dashboard** (statistici pe termen lung).
- **Trimitere autocitire** din Home Assistant, cu verificări de siguranță.
- Istoric complet (facturi, plăți, citiri) disponibil ca atribute.

---

## Instalare

### Prin HACS

1. **HACS** → meniul ⋮ → **Custom repositories**.
2. Adaugă `https://github.com/coffeerunhobby/ha-electrica`, categoria
   **Integration** → **Add**.
3. Caută **Electrica România** → **Download** → repornește Home Assistant.

### Manual

Copiază `custom_components/electrica` în `config/custom_components` și
repornește Home Assistant.

---

## Configurare

**Settings → Devices & Services → Add Integration → Electrica**, apoi introdu
e-mailul și parola contului myelectrica.ro. Toate locurile de consum sunt
descoperite automat.

---

## Entități

Fiecare **loc de consum (NLC)** este un dispozitiv separat.

| Entitate | Descriere |
| --- | --- |
| `Amount due` | Sold de plată (RON); atribute: factură curentă, PDF, istoric |
| `Last invoice` | Valoarea ultimei facturi (RON) |
| `Due date` | Scadența ultimei facturi |
| `Overdue` | `yes` / `no` — există facturi neachitate |
| `Meter index` | Indexul contorului (kWh); atribute: toate citirile reale |
| `Self-reading window` | `open` / `closed` + perioada de autocitire |
| `Agreed annual consumption` | Consumul convenit (kWh/an) + profilul lunar |
| `Last payment` | Ultima plată (RON) + istoric |
| `Reading to submit` *(number)* | Indexul pregătit pentru trimitere |
| `Submit reading` *(button)* | Trimite autocitirea către Electrica |

> ℹ️ `entity_id`-ul folosește **NLC-ul** (ex. `sensor.electrica_1234567890_amount_due`).
> Adresa rămâne doar ca nume de dispozitiv. Numele entităților sunt în engleză.

---

## Grafice de consum (Energy Dashboard)

Indexul contorului este publicat ca **statistică pe termen lung**
(`electrica:consumption_<nlc>`), deci consumul apare direct în **Energy
Dashboard** și în cardul **Statistics Graph**, fără carduri suplimentare.

> Electrica citește contorul o dată la 2–3 luni. Pentru ca graficul să nu arate
> un singur vârf uriaș în ziua citirii, consumul dintre două citiri reale este
> **distribuit proporțional pe zile**. Citirile reale rămân vizibile ca atribute
> ale senzorului *Meter index* — interpolarea este doar pentru grafic.

---

## Autocitire (trimitere index)

1. Setează valoarea pe entitatea **`Reading to submit`**.
2. Apasă **`Submit reading`**.

Butonul este **indisponibil în afara perioadei de autocitire** și refuză
trimiterea dacă:

- fereastra de autocitire este închisă,
- nu se cunoaște seria contorului,
- nu ai setat o valoare, sau
- indexul este **mai mic decât ultima citire** (contorul nu merge înapoi).

> ⚠️ Autocitirea ajunge la contul tău real de utilități. Verifică valoarea
> înainte de a apăsa butonul. Integrarea **nu trimite niciodată automat**.

---

## Confidențialitate

Credențialele sunt stocate local în Home Assistant. Datele personale (NLC, cod
client, nume, adresă, telefon, serie contor, numere de factură) sunt eliminate
automat din datele de diagnosticare.

---

## Licență

[MIT](LICENSE)
