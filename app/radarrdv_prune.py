# Name: Radarr Prune
# Coder: Marco Janssen (mastodon @marc0janssen@mastodon.green)
# date: 2021-11-15 21:38:51
# update: 2024-12-24 11:45:00

import logging
import configparser
import sys
import shutil
import glob
import os
import smtplib

if (
    __name__ == '__main__'
    and len(sys.argv) > 1
    and sys.argv[1] in ('--version', '-V')
):
    _vpath = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        '__version__.py',
    )
    with open(_vpath, encoding='utf-8') as _vf:
        _vg: dict = {}
        exec(compile(_vf.read(), '__version__.py', 'exec'), _vg)
    print(_vg['__version__'])
    raise SystemExit(0)

import time

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime, timedelta
from chump import Application
from socket import gaierror

_repo_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.dirname(_repo_dir)
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)
if _repo_dir not in sys.path:
    sys.path.insert(0, _repo_dir)

try:
    # Repo layout: /repo/app/radarrdv_prune.py
    from app.__version__ import __version__  # noqa: E402
    from app.radarr_prune_logic import decide_prune_action, is_on  # noqa: E402
    from app.radarr_client import (  # noqa: E402
        MovieRecord,
        RadarrApiError,
        RadarrClient,
    )
except ModuleNotFoundError:
    # Flat/container layout: /app/radarr/radarrdv_prune.py
    from __version__ import __version__  # noqa: E402
    from radarr_prune_logic import decide_prune_action, is_on  # noqa: E402
    from radarr_client import (  # noqa: E402
        MovieRecord,
        RadarrApiError,
        RadarrClient,
    )


class RLP():
    def __init__(self):
        logging.basicConfig(
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            level=logging.INFO)

    # Directories: prefer env overrides, else use repo-relative
        repo_dir = os.path.dirname(os.path.abspath(__file__))
        default_config_dir = os.path.join(repo_dir, '..', 'config')
        # Container-friendly default: if a Docker mount uses `/config`,
        # prefer that automatically.
        env_config_dir = os.environ.get('RADARR_PRUNE_CONFIG_DIR')
        if env_config_dir:
            config_dir = env_config_dir
        else:
            config_dir = '/config' if os.path.isdir('/config') else default_config_dir
        app_dir = os.environ.get('RADARR_PRUNE_APP_DIR', repo_dir + os.sep)
        log_dir = os.environ.get(
            'RADARR_PRUNE_LOG_DIR',
            os.path.join(repo_dir, '..')
        )

        self.config_file = "radarrdv_prune.ini"
        # Fix: example file as present in repository
        self.exampleconfigfile = "radarrdv_prune.ini.example"
        self.log_file = "radarrdv_prune.log"
        self.firstseen = ".firstseen"

        # Ensure directories exist (create config dir if missing)
        try:
            os.makedirs(config_dir, exist_ok=True)
            os.makedirs(log_dir, exist_ok=True)
        except Exception:
            # If creation fails, fall back to current working directory
            config_dir = '.'
            log_dir = '.'

        self.config_filePath = os.path.join(config_dir, self.config_file)
        self.log_filePath = os.path.join(log_dir, self.log_file)

        try:
            # try to open config; if missing, copy example from app_dir
            with open(self.config_filePath, "r"):
                pass
        except (IOError, FileNotFoundError):
            logging.error(
                f"Configuration file not found at {self.config_filePath}. "
                "Attempting to write an example INI to the config directory "
                "and exiting so you can review and update it before rerunning."
            )

            src = os.path.join(app_dir, self.exampleconfigfile)
            dst = os.path.join(config_dir, self.exampleconfigfile)
            try:
                shutil.copyfile(src, dst)
                logging.info(
                    f"Wrote example configuration to {dst}. "
                    "Edit the file to set your Radarr URL and API token, "
                    "and configure prune options before running again."
                )
            except Exception as e:
                logging.error(
                    f"Failed to copy example INI from {src} to {dst}: {e}. "
                    "Create a configuration file manually and ensure the "
                    "target directory is writable."
                )
            sys.exit()

        # Load configuration
        try:
            self.config = configparser.ConfigParser()
            self.config.read(self.config_filePath)

            # RADARR
            self.radarr_enabled = is_on(
                self.config.get('RADARR', 'ENABLED', fallback='OFF')
            )
            self.radarr_url = self.config['RADARR']['URL']
            self.radarr_token = self.config['RADARR']['TOKEN']
            self.tags_to_keep = list(
                self.config['RADARR']
                ['TAGS_KEEP_MOVIES_ANYWAY'].split(",")
            )

            # PRUNE
            self.radarr_tags_no_exclusion = list(
                self.config['PRUNE']
                ['AUTO_NO_EXCLUSION_TAGS'].split(","))
            # list(map(int, "list")) converts a list of string to
            # a list of ints
            months_raw = self.config.get(
                'PRUNE', 'AUTO_NO_EXCLUSION_MONTHS', fallback=''
            )
            self.radarr_months_no_exclusion = list(
                map(int, [s for s in months_raw.split(',') if s.strip()])
            )
            self.remove_after_days = int(
                self.config['PRUNE']['REMOVE_MOVIES_AFTER_DAYS'])
            self.warn_days_infront = int(
                self.config['PRUNE']['WARN_DAYS_INFRONT'])
            self.dry_run = is_on(
                self.config.get('PRUNE', 'DRY_RUN', fallback='OFF')
            )
            self.enabled_run = is_on(
                self.config.get('PRUNE', 'ENABLED', fallback='OFF')
            )
            self.delete_files = is_on(
                self.config.get(
                    'PRUNE', 'PERMANENT_DELETE_MEDIA', fallback='OFF'
                )
            )
            self.only_show_remove_messages = is_on(
                self.config.get(
                    'PRUNE', 'ONLY_SHOW_REMOVE_MESSAGES', fallback='OFF'
                )
            )
            self.verbose_logging = is_on(
                self.config.get('PRUNE', 'VERBOSE_LOGGING', fallback='OFF')
            )
            self.video_extensions = list(
                self.config['PRUNE']
                ['VIDEO_EXTENSIONS_MONITORED'].split(","))
            self.mail_enabled = is_on(
                self.config.get('PRUNE', 'MAIL_ENABLED', fallback='OFF')
            )
            self.only_mail_when_removed = is_on(
                self.config.get(
                    'PRUNE', 'ONLY_MAIL_WHEN_REMOVED', fallback='OFF'
                )
            )
            self.mail_port = int(
                self.config['PRUNE']['MAIL_PORT'])
            self.mail_server = self.config['PRUNE']['MAIL_SERVER']
            self.mail_login = self.config['PRUNE']['MAIL_LOGIN']
            self.mail_password = self.config['PRUNE']['MAIL_PASSWORD']
            self.mail_sender = self.config['PRUNE']['MAIL_SENDER']
            self.mail_receiver = list(
                self.config['PRUNE']['MAIL_RECEIVER'].split(","))
            self.unwanted_genres = list(
                self.config['PRUNE']['UNWANTED_GENRES'].split(","))

            # PUSHOVER
            self.pushover_enabled = is_on(
                self.config.get('PUSHOVER', 'ENABLED', fallback='OFF')
            )
            self.pushover_user_key = self.config['PUSHOVER']['USER_KEY']
            self.pushover_token_api = self.config['PUSHOVER']['TOKEN_API']
            self.pushover_sound = self.config['PUSHOVER']['SOUND']

        except KeyError as e:
            logging.error(
                f"Missing configuration key {e} in {self.config_filePath}. "
                "Please add the missing key(s) and try again. Exiting."
            )

            sys.exit()

        except ValueError as e:
            logging.error(
                f"Invalid value in INI file {self.config_filePath}: {e}. "
                "Please correct the configuration and try again. Exiting."
            )

            sys.exit()

    def sortOnTitle(self, e):
        return e.sortTitle

    def getTagLabeltoID(self):
        # Put all tags in a dictionary with pair label <=> ID
        return {
            tag['label']: tag['id']
            for tag in self.radarr_client.get_tags()
            if tag.get('label') is not None and tag.get('id') is not None
        }

    def getIDsforTagLabels(self, tagLabels):
        TagLabeltoID = getattr(self, '_tag_label_to_id', None)
        if TagLabeltoID is None:
            TagLabeltoID = self.getTagLabeltoID()
            self._tag_label_to_id = TagLabeltoID
        # Get IDs for existing labels only
        return [
            tagID for taglabel in tagLabels
            if (tagID := TagLabeltoID.get(taglabel))
        ]

    def writeLog(self, init, msg):
        mode = "w" if init else "a"
        try:
            with open(self.log_filePath, mode) as logfile:
                logfile.write(f"{datetime.now()} - {msg}\n")
        except IOError:
            logging.error(
                f"Unable to write log file {self.log_filePath}. "
                "Check file permissions and available disk space."
            )

    def _delete_action_suffix(self) -> str:
        """Human-readable fragment for logs/Pushover after a delete attempt."""
        if self.dry_run or not self.radarr_enabled:
            return ", dry run (no changes to Radarr)."
        return ", files deleted." if self.delete_files else ", files preserved."

    def _log_detail(self, msg: str) -> None:
        if self.only_show_remove_messages:
            return
        self.writeLog(False, msg)
        logging.info(msg)

    def _log_line(self, msg: str) -> None:
        self.writeLog(False, msg)
        logging.info(msg)

    def _pushover(self, message: str) -> None:
        if self.pushover_enabled:
            self.userPushover.send_message(
                message=message,
                sound=self.pushover_sound,
            )

    def _try_delete_movie(
        self,
        movie_id: int,
        movie_title: str,
        add_import_exclusion: bool,
    ) -> bool:
        if self.dry_run or not self.radarr_enabled:
            return True
        try:
            self.radarr_client.delete_movie(
                movie_id,
                delete_files=self.delete_files,
                add_import_exclusion=add_import_exclusion,
            )
            return True
        except RadarrApiError as e:
            logging.error(
                "Radarr API error deleting movie %s (%s): %s",
                movie_id,
                movie_title,
                e,
            )
            return False

    def evalMovie(self, movie):
        # Determine download date (firstseen) and whether video files exist
        movieDownloadDate = None

        fileList = glob.glob(movie.path + "/*")
        for file in fileList:
            if file.lower().endswith(tuple(self.video_extensions)):
                firstseen_path = os.path.join(movie.path, self.firstseen)
                if not os.path.isfile(firstseen_path):
                    # create marker file
                    open(firstseen_path, 'w').close()
                    if not self.only_show_remove_messages:
                        txtFirstSeen = (
                            f"PRUNE: NEW - {movie.title} ({movie.year}) "
                            f"detected at {movie.path}; "
                            "marker file created to record first-seen time."
                        )
                        self.writeLog(False, txtFirstSeen)
                        logging.info(txtFirstSeen)

                modifieddate = os.stat(firstseen_path).st_mtime
                movieDownloadDate = datetime.fromtimestamp(modifieddate)
                break

        movie_dict = {
            'tagsIds': list(movie.tagsIds),
            'genres': list(movie.genres),
            'download_date': movieDownloadDate,
        }

        config = {
            'tags_keep_ids': self.tags_to_keep_ids,
            'unwanted_genres': self.unwanted_genres,
            'remove_after_days': self.remove_after_days,
            'warn_days_infront': self.warn_days_infront,
            'tags_no_exclusion_ids': self.tags_no_exclusion_ids,
            'months_no_exclusion': self.radarr_months_no_exclusion,
        }

        result = decide_prune_action(movie_dict, config)
        reason = result.reason
        sfx = self._delete_action_suffix()

        match reason:
            case 'keep-tag':
                self._log_detail(
                    f"PRUNE: KEEP - {movie.title} ({movie.year}) has a "
                    "keep tag; skipping removal."
                )
                return False, False

            case 'missing-files':
                self._log_detail(
                    f"PRUNE: MISSING FILES - {movie.title} ({movie.year}) "
                    "has no monitored video files in its folder; skipping."
                )
                return False, False

            case 'unwanted-genre':
                if not self._try_delete_movie(movie.id, movie.title, True):
                    return False, False
                self._pushover(
                    f"{movie.title} ({movie.year}) Prune - UNWANTED "
                    f"{sfx} - {movieDownloadDate}"
                )
                self._log_line(
                    f"PRUNE: UNWANTED GENRE - {movie.title} ({movie.year})"
                    f"{sfx}; "
                    f"original download date: {movieDownloadDate}"
                )
                return True, False

            case 'will-be-removed':
                timeLeft = (
                    movieDownloadDate + timedelta(days=self.remove_after_days)
                ) - datetime.now()
                txtTimeLeft = 'h'.join(str(timeLeft).split(':')[:2])
                txtTitle = f"{movie.title} ({movie.year})"
                self._pushover(
                    "Prune - "
                    f"{txtTitle} will be removed from server in "
                    f"{txtTimeLeft}"
                )
                self._log_line(
                    f"PRUNE: SCHEDULED REMOVAL - {txtTitle} will be removed in "
                    f"{txtTimeLeft} (download date: {movieDownloadDate})"
                )
                return False, True

            case 'removed':
                if not self._try_delete_movie(
                    movie.id, movie.title, result.add_import_exclusion
                ):
                    return False, False
                self._pushover(
                    f"{movie.title} ({movie.year}) Prune - REMOVED "
                    f"{sfx} - {movieDownloadDate}"
                )
                self._log_line(
                    f"PRUNE: REMOVED - {movie.title} ({movie.year})"
                    f"{sfx}; "
                    f"original download date: {movieDownloadDate}"
                )
                return True, False

            case _:
                self._log_detail(
                    f"PRUNE: ACTIVE - {movie.title} ({movie.year}) appears "
                    f"active or recent; skipping removal (download date: "
                    f"{movieDownloadDate})."
                )
                return False, False

    def run(self):
        logging.info("Radarr Prune %s", __version__)
        if not self.enabled_run:
            logging.info(
                "Prune - Library purge disabled.")
            self.writeLog(False, "Prune - Library purge disabled.\n")
            sys.exit()

        # Connect to Radarr (HTTP API v3, no arrapi)
        if self.radarr_enabled:
            try:
                self.radarr_client = RadarrClient(
                    self.radarr_url, self.radarr_token)
                self.radarr_client.ping()
            except RadarrApiError as e:
                logging.error(
                    f"Failed to reach Radarr at {self.radarr_url}: {e}"
                )
                sys.exit(1)
            except Exception as e:
                logging.error(
                    f"Unexpected error connecting to Radarr at "
                    f"{self.radarr_url}: {e}"
                )
                sys.exit(1)
        else:
            logging.info("Radarr integration disabled; exiting.")
            self.writeLog(False, "Radarr integration disabled.\n")
            sys.exit()

        if self.dry_run:
            logging.info("DRY RUN: no changes will be made.")
            self.writeLog(False, "Dry run mode - no deletions performed.\n")

        # Setting for PushOver
        if self.pushover_enabled:
            self.appPushover = Application(self.pushover_token_api)
            self.userPushover = \
                self.appPushover.get_user(self.pushover_user_key)

        # Get all movies from the server.
        media = None
        if self.radarr_enabled:
            try:
                # Cache tag label -> id mapping once per run to avoid
                # per-movie /tag API calls.
                self._tag_label_to_id = self.getTagLabeltoID()
                self.tags_to_keep_ids = self.getIDsforTagLabels(
                    self.tags_to_keep
                )
                self.tags_no_exclusion_ids = self.getIDsforTagLabels(
                    self.radarr_tags_no_exclusion
                )
                raw = self.radarr_client.get_movies()
                media = [MovieRecord.from_api(m) for m in raw]
            except RadarrApiError as e:
                logging.error("Failed to fetch movies from Radarr: %s", e)
                sys.exit(1)

        if self.verbose_logging:
            logging.info("PRUNE: Radarr prune run started.")
        self.writeLog(True, "PRUNE: Radarr prune run started.\n")

        # Make sure the library is not empty.
        numDeleted = 0
        numNotifified = 0
        isRemoved, isPlanned = False, False

        # Movies are always evaluated; prune decisions are age/tag/month based.
        if media:
            media.sort(key=self.sortOnTitle)  # Sort the list on Title
            for movie in media:
                isRemoved, isPlanned = self.evalMovie(movie)
                if isRemoved:
                    numDeleted += 1
                if isPlanned:
                    numNotifified += 1

                time.sleep(0.2)

        txtEnd = (
            f"Prune - There were {numDeleted} movies removed "
            f"and {numNotifified} movies planned to be removed "
            f"within {self.warn_days_infront} days."
        )

        if self.pushover_enabled:
            self.message = self.userPushover.send_message(
                message=txtEnd,
                sound=self.pushover_sound
            )

        if self.verbose_logging:
            logging.info(txtEnd)
        self.writeLog(False, f"{txtEnd}\n")

        if self.mail_enabled and \
            (not self.only_mail_when_removed or
                (self.only_mail_when_removed and (
                    numDeleted > 0 or numNotifified > 0))):

            sender_email = self.mail_sender
            receiver_email = self.mail_receiver

            message = MIMEMultipart()
            message["From"] = sender_email
            message['To'] = ", ".join(receiver_email)
            message['Subject'] = (
                f"Radarr - Pruned {numDeleted} movies "
                f"and {numNotifified} planned for removal"
            )

            with open(self.log_filePath, 'rb') as attachment:
                obj = MIMEBase('application', 'octet-stream')
                obj.set_payload(attachment.read())
            encoders.encode_base64(obj)
            obj.add_header(
                'Content-Disposition',
                "attachment; filename= "+self.log_file
            )
            message.attach(obj)

            body = (
                "Hi,\n\n Attached is the prunelog from Prxlovarr.\n\n"
                "Have a nice day.\n\n"
            )

            with open(self.log_filePath, "r", encoding='UTF-8') as logfile:
                body += logfile.read()

            plain_text = MIMEText(
                body, _subtype='plain', _charset='UTF-8')
            message.attach(plain_text)

            my_message = message.as_string()

            try:
                email_session = smtplib.SMTP(
                    self.mail_server, self.mail_port)
                email_session.starttls()
                email_session.login(
                    self.mail_login, self.mail_password)
                email_session.sendmail(
                    self.mail_sender, self.mail_receiver, my_message)
                email_session.quit()
                logging.info(
                    f"PRUNE: Email sent to {message['To']} "
                    "with prune log attached."
                )
                self.writeLog(
                    False,
                    f"PRUNE: Email sent to {message['To']}.\n"
                )

            except (gaierror, ConnectionRefusedError):
                logging.error(
                    "Failed to connect to the server. "
                    "Bad connection settings?")
            except smtplib.SMTPServerDisconnected:
                logging.error(
                    "Failed to connect to the server. "
                    "Wrong user/password?"
                )
            except smtplib.SMTPException as e:
                logging.error(
                    "SMTP error occurred: " + str(e))

        rc = getattr(self, 'radarr_client', None)
        if rc is not None:
            rc.close()


if __name__ == '__main__':
    rlp = RLP()
    rlp.run()
    rlp = None
