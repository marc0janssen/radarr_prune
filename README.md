# radarr_prune

Radarr Prune verwijdert (of markeert) oude of ongewenste films uit je Radarr-database
volgens regels die je in de INI-config instelt. Dit repo bevat een eenvoudige, testbare
beslissingslaag (`app/prune_logic.py`) en de integratie met Radarr in
`app/radarrdv_prune.py`.

## Hoofdpunten
- Veilig standaardgedrag: gebruik `DRY_RUN=ON` om eerst te controleren wat er zou
  gebeuren zonder daadwerkelijk te verwijderen.
- Beslissingslogica is gescheiden (pure functies) en getest met pytest.
- Compatibel met PushOver en e-mailmeldingen.

## Vereisten
- Python 3.8+ (3.12 getest in dev-omgeving)
- De gebruikte (optionele) pakketten staan in `requirements.txt`.

## Quickstart (fish shell)
1. Clone de repo en ga naar de directory.
2. Maak en activeer een virtualenv (fish):

```fish
python3 -m venv .venv
source .venv/bin/activate.fish
pip install -r requirements.txt
```

3. Plaats je configuratie in een map (of gebruik de voorbeeld-INI):

```fish
# set een config dir (optioneel, anders maakt het script een example INI in ./config)
set -x RADARR_PRUNE_CONFIG_DIR "/pad/naar/config"

# kopieer voorbeeld INI naar config map als je nog geen config hebt
cp app/radarrdv_prune.ini.example $RADARR_PRUNE_CONFIG_DIR/
```

4. Controleer of `PRUNE.DRY_RUN` in de INI op `ON` staat (veilige default).

5. Draai het script (dry-run):

```fish
.venv/bin/python app/radarrdv_prune.py
```

Zodra je tevreden bent met de output en logs, zet `PRUNE.DRY_RUN=OFF` in je INI
om verwijderingen toe te staan.

## Configuratie (belangrijkste opties)
Het script leest een INI-bestand. Het voorbeeldbestand `app/radarrdv_prune.ini.example`
geeft alle beschikbare opties; hieronder staan de meest belangrijke:

- [RADARR]
  - ENABLED = ON|OFF  # Gebruik ON om Radarr-integratie te activeren
  - URL = http://radarr:7878
  - TOKEN = <api-token>

- [PRUNE]
  - ENABLED = ON|OFF             # globale enable voor de prune-run
  - DRY_RUN = ON|OFF             # ON = niets verwijderen, alleen loggen
  - REMOVE_MOVIES_AFTER_DAYS = 30
  - REMOVE_MOVIES_DISK_PERCENTAGE = 90.0
  - WARN_DAYS_INFRONT = 3
  - VIDEO_EXTENSIONS_MONITORED = mkv,mp4,avi
  - PERMANENT_DELETE_MEDIA = ON|OFF
  - MAIL_ENABLED = ON|OFF
  - MAIL_* settings voor SMTP (server, port, login, etc.)
  - AUTO_NO_EXCLUSION_TAGS = tag1,tag2
  - AUTO_NO_EXCLUSION_MONTHS = 1,2,12
  - TAGS_KEEP_MOVIES_ANYWAY = important-tag

- [PUSHOVER]
  - ENABLED = ON|OFF
  - USER_KEY, TOKEN_API, SOUND

Lees `app/radarrdv_prune.ini.example` voor een compleet voorbeeld en toelichting.

## Tests
De beslissingslogica is getest met pytest. Om tests lokaal te draaien (venv
geactiveerd):

```fish
.venv/bin/python -m pytest -q
```

De tests bevinden zich in `tests/` en de belangrijkste pure functie is
`app.prune_logic.decide_prune_action`.

## Development notes
- De kernregel (of een toekomstige uitbreiding daarvan) staat in
  `app/prune_logic.py` — dit maakt het eenvoudig om extra regels toe te voegen
  en unit-tests te schrijven.
- `app/radarrdv_prune.py` doet de integratie: het leest config, roept Radarr
  aan, verstuurt meldingen en schrijft logbestanden.
- Standaard schrijft het script logs naar de `log_dir` zoals ingesteld in de
  code of via environment overrides.

## Contributie
- Voeg kleine, gerichte PRs toe. Nieuwe logica gaat idealiter eerst in
  `app/prune_logic.py` met bijbehorende tests.

## License
Zie `LICENSE` in de repo.

---
Als je wilt kan ik ook:
- het `app/radarrdv_prune.ini.example` verduidelijken en veiliger maken
- een GitHub Actions workflow toevoegen die pytest en lint draait
- integratietests schrijven die Radarr-API-calls mocken

Zeg welke van de bovenstaande je wil en ik voer het uit.
