# radarr_prune

Radarr Prune verwijdert (of markeert) oude of ongewenste films uit je Radarr-database
volgens regels die je in de INI-config instelt. Dit repo bevat een eenvoudige, testbare
beslissingslaag (`app/radarr_prune_logic.py`) en de integratie met Radarr in
`app/radarrdv_prune.py`.

## Architectuur

De prune-**beslissing** (tags, leeftijd, waarschuwingsvenster, uitzonderingen)
staat bewust **los** van het script dat de API aanroept, logging doet en notificaties verstuurt.

- **Testen** — `radarr_prune_logic` bevat geen netwerk of bestands-I/O: alleen invoer →
  beslissing. Daardoor zijn de regels als pure functies met pytest te testen zonder Radarr
  te mocken voor elke scenario.
- **Onderhoud** — Wijzigingen aan regels gaan op één plek; tokens, URL’s en endpoints
  blijven in het integratiescript.
- **Hergebruik** — Hetzelfde patroon (beslislaag + aparte “driver”) kun je toepassen op
  andere *arr*-tools, bijvoorbeeld Sonarr: de API en velden verschillen, maar vergelijkbare
  prune-regels kun je delen of spiegelen zonder de hele hoofdfile te dupliceren.

## Hoofdpunten
- Veilig standaardgedrag: gebruik `DRY_RUN=ON` om eerst te controleren wat er zou
  gebeuren zonder daadwerkelijk te verwijderen.
- Beslissingslogica is gescheiden (pure functies) en getest met pytest.
- Compatibel met PushOver en e-mailmeldingen.

## Versie

Het applicatieversienummer staat op één plek in `app/__version__.py` (`__version__`).
Hoger bij releases (aanbevolen: [Semantic Versioning](https://semver.org/) — `MAJOR.MINOR.PATCH`).

- Commando: `python app/radarrdv_prune.py --version` of `-V` (drukt het nummer af en stopt;
  werkt met alleen de standaardlibrary, nog vóór optionele packages worden geladen).
- Elke run logt een regel: `Radarr Prune <versie>` aan het begin van `run()`.
- In code: `from app import __version__` of `from app.__version__ import __version__`.

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
# set een config dir (optioneel)
# standaard probeert het script ook `/config` (als die map bestaat)
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

### Prune-beslissing (huidig gedrag)
- Verwijderen gebeurt zodra een film ouder is dan `REMOVE_MOVIES_AFTER_DAYS`.
- Disk usage is niet langer een vereiste voor verwijderen.
- Keep-tags, no-exclusion-tags/-maanden en warning window blijven actief.

## Tests
De beslissingslogica is getest met pytest. Om tests lokaal te draaien (venv
geactiveerd):

```fish
.venv/bin/python -m pytest -q
```

De tests bevinden zich in `tests/` en de belangrijkste pure functie is
`app.radarr_prune_logic.decide_prune_action`.

## Development notes
- Nieuwe of gewijzigde prune-regels horen in `app/radarr_prune_logic.py`, met tests in
  `tests/`. Het integratiescript mapt Radarr-responses naar het invoermodel van
  `decide_prune_action` en voert de uitkomst uit.
- `app/radarrdv_prune.py` leest config, roept Radarr aan, verstuurt meldingen en schrijft
  logbestanden. Standaard gaan logs naar `log_dir` zoals in de code of via environment
  overrides ingesteld.

## Contributie
- Voeg kleine, gerichte PRs toe. Nieuwe logica gaat idealiter eerst in
  `app/radarr_prune_logic.py` met bijbehorende tests.

## License
Zie `LICENSE` in de repo.
