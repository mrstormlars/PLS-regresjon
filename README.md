# PLS-regresjon

En enkel webapp for PLS-regresjon (Partial Least Squares) som kjører lokalt på din egen PC.
Du laster opp et datasett i Excel (`.xlsx`) eller CSV, velger hvilken kolonne som er respons (Y)
og hvilke som er prediktorer (X), og får en ferdig tilpasset PLS-modell med diagnostikk:
RMSEP/RMSEC per komponent, R², kryssvalidering, score- og koeffisientplott, uteliggerforslag,
automatisk variabelutvalg, hva-hvis-simulering og en eksporterbar HTML-rapport.

Alt skjer på din maskin. Dataene sendes aldri ut på nettet.

## Innhold

- [Hva trenger du?](#hva-trenger-du)
- [Installasjon på Windows, steg for steg](#installasjon-på-windows-steg-for-steg)
- [Starte og stoppe appen](#starte-og-stoppe-appen)
- [Feilsøking ved installasjon](#feilsøking-ved-installasjon)
- [Slik bruker du appen](#slik-bruker-du-appen)
- [Krav til datasettet](#krav-til-datasettet)
- [Hvor blir dataene mine av?](#hvor-blir-dataene-mine-av)
- [Feil, spørsmål og forbedringsforslag](#feil-spørsmål-og-forbedringsforslag)
- [For utviklere](#for-utviklere)

## Hva trenger du?

- En Windows-PC (Windows 10 eller 11). Appen fungerer også på Mac/Linux, se [For utviklere](#for-utviklere).
- Internett-tilgang **under installasjonen** (for å laste ned Python og noen Python-pakker). Etterpå trenger appen ikke nett.
- Ca. 500 MB ledig diskplass.
- Du trenger **ikke** administratorrettigheter, og du trenger **ikke** å kunne programmere.

## Installasjon på Windows, steg for steg

### Steg 1: Installer Python

1. Gå til <https://www.python.org/downloads/windows/> og last ned nyeste **Python 3** for Windows
   ("Windows installer (64-bit)"). Appen trenger Python 3.11 eller nyere.
2. Kjør installasjonsfila.
3. **Viktig:** Huk av for **"Add python.exe to PATH"** nederst i det første vinduet før du klikker
   *Install Now*.
4. Vent til installasjonen er ferdig og lukk vinduet.

Har du allerede Python installert? Da kan du hoppe over dette steget.

### Steg 2: Last ned appen

Enkleste måte (ingen Git nødvendig):

1. Gå til <https://github.com/mrstormlars/PLS-regresjon>.
2. Klikk den grønne knappen **Code** og velg **Download ZIP**.
3. Pakk ut ZIP-fila til et sted du finner igjen, for eksempel `C:\PLS-regresjon`.
   Høyreklikk på fila og velg *Pakk ut alle* (eller *Extract All*).

   Unngå mapper som synkroniseres til skyen (OneDrive og lignende), da kan installasjonen bli
   treg.

Bruker du Git fra før, kan du i stedet kjøre:

```bash
git clone https://github.com/mrstormlars/PLS-regresjon.git
```

### Steg 3: Start appen første gang

1. Åpne mappa du pakket ut, og gå inn i undermappa `scripts`.
2. Dobbeltklikk på **`start.bat`**.
3. Et svart kommandovindu åpner seg. **Første gang** lager skriptet et lokalt Python-miljø
   (mappa `.venv`) og laster ned pakkene appen trenger. Dette tar typisk 1–5 minutter, avhengig
   av nettet. La vinduet stå.
4. Når alt er klart, åpner nettleseren din seg automatisk på <http://127.0.0.1:8000>.
   Skjer ikke det, kan du åpne adressen selv.

Får du en advarsel fra Windows ("Windows beskyttet PC-en din" / SmartScreen) når du starter
`start.bat`? Klikk *Mer info* og deretter *Kjør likevel*. Skriptet er et vanlig batch-skript du
kan åpne i Notisblokk og lese selv.

## Starte og stoppe appen

- **Starte:** dobbeltklikk `scripts\start.bat`. Fra andre gang går det på noen sekunder.
- **Stoppe:** trykk `Ctrl+C` i det svarte kommandovinduet, eller bare lukk vinduet.
- Det svarte vinduet **må stå åpent** så lenge du bruker appen. Det er serveren som kjører der.
- Appen er kun tilgjengelig fra din egen PC (adressen `127.0.0.1` betyr "denne maskinen").
  Andre på nettverket kan ikke nå den.

## Feilsøking ved installasjon

| Problem | Løsning |
| --- | --- |
| `"py" is not recognized` eller `"python" is not recognized` | Python er ikke installert, eller ble installert uten "Add python.exe to PATH". Installer på nytt etter steg 1. |
| Vinduet lukker seg med en gang | Åpne en kommandolinje (søk etter "cmd" i startmenyen), skriv `cd` etterfulgt av stien til `scripts`-mappa, og kjør `start.bat` derfra. Da blir feilmeldingen stående. |
| Nettleseren åpner seg ikke | Åpne <http://127.0.0.1:8000> manuelt. Se i det svarte vinduet om det står `Application startup complete`. |
| `Address already in use` / port 8000 opptatt | Et annet program bruker port 8000. Åpne `scripts\start.bat` i Notisblokk og endre `set "PORT=8000"` til for eksempel `8010`. |
| Installasjonen feiler med nettverksfeil | Sjekk at du har nett, eventuelt at proxy/brannmur tillater `pip` å laste ned fra pypi.org. Prøv igjen. |
| Noe er helt i ukurs | Slett mappa `.venv` i appmappa og dobbeltklikk `start.bat` på nytt. Da bygges miljøet opp fra bunnen av. |

## Slik bruker du appen

Siden er delt i fem nummererte steg, ovenfra og ned.

### 1. Last opp datasett

Velg en `.xlsx`- eller `.csv`-fil og klikk **Last opp**. Maks filstørrelse er 20 MB.

### 2. Velg ark og rader

- **Ark:** hvilket regneark i Excel-fila som skal brukes (CSV har bare ett).
- **Header-rad:** Excel-radnummeret der kolonneoverskriftene står. Standard er rad 1. Har fila
  noen linjer med tittel eller kommentar først, setter du dette til raden med overskriftene.
- **Startrad / Sluttrad / Startkolonne / Sluttkolonne:** valgfritt. Bruk disse hvis bare en del
  av arket skal brukes. Kolonner kan oppgis som bokstav (`A`, `D`) eller tall (`1`, `4`). Alle
  numre er som i Excel (1-basert).

Klikk **Forhåndsvis** for å se de første radene slik appen tolker dem.

### 3. Forhåndsvisning

En tabell med de første 20 radene. Ser noe galt ut (feil overskriftsrad, tall som vises som
tekst), gå tilbake til steg 2 og juster.

### 4. Velg variabler og innstillinger

- **Y-variabel (respons):** kolonnen du vil predikere.
- **X-variabler (prediktorer):** huk av kolonnene som skal brukes som forklaringsvariabler.
  For hver kolonne kan du velge lineært ledd, **log10**-ledd, eller begge. Log10 er nyttig for
  variabler som spenner over flere størrelsesordener.
- **Grenseverdier per kolonne:** valgfritt `min`/`maks` per kolonne. Rader med verdier utenfor
  grensene fjernes før analysen. Praktisk for å luke ut nedetid, målefeil og lignende.
- **Bruk log10 av Y-variabelen:** transformerer responsen før modellen tilpasses.
- **Maks antall komponenter:** øvre grense for hvor mange PLS-komponenter som prøves ut
  (standard 10). Appen velger selv det antallet som gir lavest RMSEP.
- **Antall CV-folder:** antall deler i kryssvalideringen (standard 10).
- **Ekskluderte rader:** Excel-radnumre som skal holdes utenfor, kommaseparert.

Klikk **Kjør analyse**. Rader med tomme eller ikke-numeriske verdier i de valgte kolonnene
fjernes automatisk, og du får beskjed om hvor mange.

### 5. Resultater

**Nøkkeltall** øverst: optimalt antall komponenter, RMSEP og RMSEC ved dette antallet, samt R²
for kalibrering og kryssvalidering. Lav RMSEP og høy R² kryssvalidering er det du ønsker. Stort
sprik mellom R² kalibrering og R² kryssvalidering tyder på overtilpasning.

**Plott** (alle er interaktive, du kan zoome og holde musa over punkter):

- *RMSEP/RMSEC vs. antall komponenter*: viser hvordan feilen utvikler seg med flere komponenter.
- *Predikert vs. faktisk Y*: hvert punkt er en rad. Punkter nær diagonalen er godt predikert.
- *Scores (PC1 vs. PC2)*: viser hvordan radene fordeler seg i modellrommet. Punkter som ligger
  langt fra resten er kandidater til uteliggere.
- *Koeffisienter*: hvor mye hver X-variabel bidrar. Velg **Normaliserte** for å sammenligne
  variabler mot hverandre, eller **Rå** for koeffisienter i opprinnelige enheter.

**Markering.** Klikk på punkter i radplottene (eller søyler i koeffisientplottet) for å markere
rader eller kolonner. `Ctrl+klikk` legger til og fjerner, og du kan dra for å markere flere.
Deretter:

- **Kjør på nytt uten markerte:** fjerner de markerte radene/variablene og kjører analysen igjen.
- **Kjør kun med markerte:** beholder bare de markerte.
- **Fjern markering:** nullstiller.

**Forslag.** Appen kan foreslå uteliggere basert på Y-avstand, X-avstand eller T², og foreslå
variabler med lav påvirkning. Forslagene blir bare *markert* i plottene, du bestemmer selv om du
vil kjøre på nytt uten dem. *Uteliggerkartet* viser X-avstand mot Y-avstand per rad, farget
etter T², og hjelper deg å se hvor en terskel bør ligge.

**Automatisk variabeloptimalisering.** Fjerner én og én variabel så lenge RMSEP ikke blir
dårligere enn toleransen du oppgir (0 betyr "aldri dårligere"). Trinn 1 viser forslaget og en
graf over RMSEP per iterasjon. Trinn 2, **Bruk optimalisert utvalg**, tar forslaget i bruk og
oppdaterer resultatene.

**Hva-hvis-simulering.** Tabellen viser hver X-variabel med basisverdi i rå enheter. Skriv inn en
endring (absolutt eller prosent) og se hvordan predikert Y endrer seg. **Nullstill** setter
alt tilbake.

**Eksporter rapport (HTML).** Lager én selvstendig HTML-fil med nøkkeltall, plott,
innstillinger, forbehandling og siste simulering. Fila kan åpnes i hvilken som helst nettleser
og deles med andre uten at de trenger appen.

## Krav til datasettet

- Format: `.xlsx` (Excel) eller `.csv`, maks 20 MB.
- Én rad med kolonneoverskrifter, deretter én rad per observasjon.
- Kolonnene som skal brukes som X og Y må inneholde tall. Tekst, tomme celler og feilverdier
  gjør at raden fjernes.
- Minst 10 komplette rader må være igjen etter filtrering.
- CSV: skilletegn (`;`, `,` eller tabulator) og desimaltegn (`,` eller `.`) oppdages automatisk.
  Norsk Excel-eksport med semikolon og desimalkomma fungerer rett ut av boksen.
- Log10 kan bare brukes på positive verdier. Rader med 0 eller negative tall i en log10-kolonne
  fjernes.

## Hvor blir dataene mine av?

- Fila du laster opp holdes **i minnet** på din egen PC så lenge serveren kjører, og slettes
  automatisk etter én time eller når du stopper appen. Ingenting lagres på disk.
- Appen gjør **ingen** kall til internett. Alt av kode og biblioteker (inkludert plottbiblioteket)
  ligger lokalt.
- Serveren lytter kun på `127.0.0.1`, altså bare på din egen maskin.
- Unntaket er HTML-rapporten du eventuelt eksporterer. Den inneholder tallene fra analysen og
  lagres der du velger å lagre den.

## Feil, spørsmål og forbedringsforslag

Fant du en feil, eller har du et ønske om ny funksjonalitet? Ta gjerne kontakt:

- **GitHub:** opprett en sak på
  <https://github.com/mrstormlars/PLS-regresjon/issues> (krever GitHub-konto).
- **E-post:** <martin.storm.larsen@gmail.com>

Ved feil er det til stor hjelp om du tar med:

1. Hva du gjorde (hvilket steg, hvilke innstillinger).
2. Hva du forventet, og hva som faktisk skjedde. Feilmeldingen fra appen eller fra det svarte
   kommandovinduet, gjerne som skjermbilde.
3. Om mulig, et lite testdatasett som utløser feilen. **Ikke send data du ikke kan dele.**

## For utviklere

- **Backend:** Python, FastAPI, pandas/openpyxl for innlesing, scikit-learn `PLSRegression`.
- **Frontend:** ren HTML/CSS/JavaScript uten byggesteg, servert av backend. Plotly ligger
  lokalt i `frontend/vendor/`.
- Regler for bidrag, arkitektur og arbeidsflyt står i [CLAUDE.md](CLAUDE.md). Kort versjon:
  aldri push direkte til `main`, alltid branch + pull request, og alle kodeendringer har tester.

Manuell installasjon og kjøring (Windows):

```bash
python -m venv .venv
```

```bash
.venv\Scripts\python -m pip install -r requirements.txt
```

```bash
.venv\Scripts\python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

På macOS/Linux: `source .venv/bin/activate`, så `pip install -r requirements.txt` og
`python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000`.

Tester og lint:

```bash
pytest tests/
```

```bash
ruff check && ruff format --check
```

Innstillinger som maks antall komponenter, CV-folder, filstørrelse og lignende er samlet i
`backend/config.py`.
