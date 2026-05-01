# Prompt: Radarr Prune opnieuw bouwen (zonder arrapi)

Kopieer onderstaande sectie naar een LLM of gebruik hem als functionele specificatie. **Gebruik geen `arrapi`**; praat rechtstreeks met de **Radarr HTTP API v3** (JSON). Optioneel: `requests` of `httpx` voor HTTP; `urllib` mag ook.

---

## Doel

Een CLI-/daemon-achtig Python-script **“Radarr Prune”** dat:

1. Configuratie uit een **INI-bestand** leest (zelfde bedoeling als `radarrdv_prune.ini` / `.ini.example` in deze repo).
2. Optioneel mappen aanmaakt en bij ontbrekende config een **example-INI** kopieert en afsluit (veilige first-run).
3. Verbindt met **Radarr** via **REST**, geen third-party Arr-clientbibliotheek.
4. Lokaal op de schijf (waar de Radarr-host het pad ziet, of via gedeelde mount) per filmmap een **`.firstseen`**-marker gebruikt om “eerste keer gezien” vast te leggen (mtime = referentie voor “downloaddatum” voor de prune-logica).
5. Een **pure beslislaag** toepast (zie hieronder): tags, genres, leeftijd, waarschuwingsvenster.
6. **Logging** naar console + bestand; optioneel **Pushover** en **SMTP-mail** met log als bijlage.
7. Tussen films een korte **sleep** (bijv. 0,2 s) om API/storage te sparen.

---

## Radarr API (v3) — zelf implementeren

- **Basis-URL**: uit config, bv. `http://host:7878` (geen afsluitende slash verplicht; normaliseer consistent).
- **Authenticatie**: header **`X-Api-Key: <TOKEN>`** (zelfde token als in Radarr Settings → General → API Key).
- **Content-Type**: `application/json` voor GET-responses; DELETE zonder body.

Minimaal nodige calls:

| Actie | Methode | Pad | Opmerking |
|--------|---------|-----|-----------|
| Lijst alle films | GET | `/api/v3/movie` | Response: array van filmobjecten. |
| Alle tags | GET | `/api/v3/tag` | Voor label → id mapping (tag heeft `id` en `label`). |
| Film verwijderen | DELETE | `/api/v3/movie/{id}` | Query parameters (zie Radarr-bron): `deleteFiles` (bool), `addImportExclusion` (bool). |

**Verwijderen** (equivalent met huidige script):

- `DELETE {base}/api/v3/movie/{movieId}?deleteFiles=<bool>&addImportExclusion=<bool>`
- Controleer bij jouw Radarr-versie in **Swagger** (`/swagger` op de Radarr-host) of parameternamen exact `deleteFiles` en `addImportExclusion` zijn; pas zo nodig aan.

**Filmvelden** uit GET `/api/v3/movie` die je nodig hebt (namen kunnen in JSON camelCase zijn, check response):

- Numeriek **id**
- **title**, **year**
- **path** (map op schijf voor glob + `.firstseen`)
- **tags** of equivalent: lijst van tag-**id**’s (integers)
- **genres**: lijst van genre-strings (voor ongewenste genres)

Start met een **connectietest**: bijv. GET `/api/v3/system/status` of de eerste succesvolle GET `/api/v3/movie` (als jouw Radarr dat ondersteunt). Faal netjes met log als URL/token ongeldig is.

---

## Lokale logica per film (pad op schijf)

- Zoek in `movie.path` naar bestanden met extensies uit config **`VIDEO_EXTENSIONS_MONITORED`** (comma-gescheiden, bv. `.mp4`, `.mkv`).
- Als er een videobestand is maar nog geen **`.firstseen`**: maak die file aan en log “NEW” (tenzij `ONLY_SHOW_REMOVE_MESSAGES`).
- **Downloaddatum voor beslislaag**: `mtime` van `.firstseen` als die bestaat na scan; anders geen datum → behandel als nog geen geldige download / geen video.

---

## Pure beslislaag (`decide_prune_action`)

Implementeer equivalent aan onderstaande logica (returns o.a. `reason` en voor `removed` een vlag **`add_import_exclusion`** voor de DELETE-call).

**Input movie (dict-achtig):**

- `tagsIds`: lijst int
- `genres`: lijst strings
- `download_date`: `datetime | None`

**Input config:**

- `tags_keep_ids`, `tags_no_exclusion_ids`: lijsten int
- `unwanted_genres`: lijst strings (vergelijk met filmgenres; overlap = match)
- `remove_after_days`, `warn_days_infront`: int
- `months_no_exclusion`: lijst int 1–12 (maand van `download_date` kan uitsluiten van “lege” verwijder-reden)

**Volgorde:**

1. Als doorsnede van film-tags met **keep-tags** niet leeg → **keep-tag** (geen actie).
2. Geen `download_date` → **missing-files** (geen actie).
3. Doorsnede genres met **unwanted_genres** niet leeg → **unwanted-genre** (verwijderen bedoeld; bij API: `addImportExclusion=True` in huidige code).
4. Bereken `removal_date = download_date + remove_after_days`. Als `0 < (removal_date - now) <= warn_days_infront` (als timedelta) → **will-be-removed** (alleen waarschuwen).
5. Als `now - download_date >= remove_after_days` **en** niet (maand in `months_no_exclusion` **of** tag in `tags_no_exclusion_ids`) → **removed** met `add_import_exclusion = not (monthfound or exclusiontagsfound)`.
6. Anders → **active**.

Return-type kan een `NamedTuple` zijn: `is_removed`, `is_planned`, `reason`, `add_import_exclusion`.

---

## Side-effects na beslissing

- **Dry-run / Radarr uit**: geen DELETE; log/Pushover-tekst moet **altijd** een duidelijke suffix hebben (bijv. “dry run (no changes to Radarr)” vs “files deleted” / “files preserved”) — geen ongeïnitialiseerde variabelen tussen films.
- **Unwanted-genre**: DELETE met `addImportExclusion=True` (zoals bestaand gedrag).
- **Removed**: DELETE met `addImportExclusion=result.add_import_exclusion`, `deleteFiles` uit config.
- **Pushover** (optioneel, `chump` of direct POST naar Pushover API): berichten zoals in het huidige script (titel, jaar, tijd tot verwijdering, eindsom).
- **Mail**: multipart, logbestand als attachment + body met logtekst; TLS + login zoals in config.

---

## Config (INI) — secties

Houd dezelfde **secties en sleutels** aan als in `app/radarrdv_prune.ini.example`: `[RADARR]` (URL, TOKEN, ENABLED, TAGS_KEEP_MOVIES_ANYWAY), `[PRUNE]` (ENABLED, DRY_RUN, drempels, genres, mail, video-extensies, …), `[PUSHOVER]`.

**Environment overrides** (zoals nu): `RADARR_PRUNE_CONFIG_DIR`, `RADARR_PRUNE_APP_DIR`, `RADARR_PRUNE_LOG_DIR`.

---

## Technische eisen voor de nieuwe implementatie

- **Python 3.10+** mag (`match`/`case`, `datetime | None`).
- **Geen `arrapi`**: alle Radarr-interactie via HTTP client + JSON parse.
- Behoud **unit tests** voor de pure functie (`decide_prune_action`); mock HTTP voor integratietests indien gewenst.
- Foutafhandeling: netwerk timeouts, 401/403, 404 op delete — loggen en niet crashen zonder bericht.

---

## Niet in scope tenzij gevraagd

- Web-UI, Docker packaging wijzigen, database.
- Gedrag wijzigen van de prune-regels tenzij expliciet gevraagd.

---

*Dit document beschrijft het gedrag van de bestaande codebase in deze repository; gebruik het om een equivalent te bouwen met directe Radarr REST-calls.*
