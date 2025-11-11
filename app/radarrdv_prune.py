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
import psutil
import time

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime, timedelta
from arrapi import RadarrAPI, exceptions
from chump import Application
from socket import gaierror


class RLP():
    def __init__(self):
        logging.basicConfig(
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            level=logging.INFO)

    # Directories: prefer env overrides, else use repo-relative
        repo_dir = os.path.dirname(os.path.abspath(__file__))
        config_dir = os.environ.get(
            'RADARR_PRUNE_CONFIG_DIR',
            os.path.join(repo_dir, '..', 'config')
        )
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
                f"Can't open file {self.config_filePath}, "
                "creating example INI file."
            )

            src = os.path.join(app_dir, self.exampleconfigfile)
            dst = os.path.join(config_dir, self.exampleconfigfile)
            try:
                shutil.copyfile(src, dst)
                logging.info(f"Wrote example config to {dst}")
            except Exception as e:
                logging.error(f"Failed to copy example INI file: {e}")
            sys.exit()

        # Load configuration
        try:
            self.config = configparser.ConfigParser()
            self.config.read(self.config_filePath)

            # RADARR
            # small helper: parse ON/OFF values consistently
            def _is_on(val: str) -> bool:
                return str(val).strip().upper() == 'ON'

            self.radarr_enabled = _is_on(
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
            self.remove_percentage = float(
                self.config['PRUNE']['REMOVE_MOVIES_DISK_PERCENTAGE'])
            self.warn_days_infront = int(
                self.config['PRUNE']['WARN_DAYS_INFRONT'])
            self.dry_run = _is_on(
                self.config.get('PRUNE', 'DRY_RUN', fallback='OFF')
            )
            self.enabled_run = _is_on(
                self.config.get('PRUNE', 'ENABLED', fallback='OFF')
            )
            self.delete_files = _is_on(
                self.config.get(
                    'PRUNE', 'PERMANENT_DELETE_MEDIA', fallback='OFF'
                )
            )
            self.only_show_remove_messages = _is_on(
                self.config.get(
                    'PRUNE', 'ONLY_SHOW_REMOVE_MESSAGES', fallback='OFF'
                )
            )
            self.verbose_logging = _is_on(
                self.config.get('PRUNE', 'VERBOSE_LOGGING', fallback='OFF')
            )
            self.video_extensions = list(
                self.config['PRUNE']
                ['VIDEO_EXTENSIONS_MONITORED'].split(","))
            self.mail_enabled = True if (
                self.config['PRUNE']
                ['MAIL_ENABLED'] == "ON") else False
            self.only_mail_when_removed = _is_on(
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
            self.pushover_enabled = True if (
                self.config['PUSHOVER']['ENABLED'] == "ON") else False
            self.pushover_user_key = self.config['PUSHOVER']['USER_KEY']
            self.pushover_token_api = self.config['PUSHOVER']['TOKEN_API']
            self.pushover_sound = self.config['PUSHOVER']['SOUND']

        except KeyError as e:
            logging.error(
                f"Seems a key(s) {e} is missing from INI file. "
                f"Please check for mistakes. Exiting."
            )

            sys.exit()

        except ValueError as e:
            logging.error(
                f"Seems a invalid value in INI file. "
                f"Please check for mistakes. Exiting. "
                f"MSG: {e}"
            )

            sys.exit()

    def isDiskFull(self):
        # Get the Rootfolders and disk usage. Be defensive: if Radarr isn't
        # enabled or an error occurs, return (False, 0) to avoid accidental
        # deletions.
        if not getattr(self, 'radarr_enabled', False):
            return (False, 0)

        try:
            folders = self.radarrNode.root_folder()
            root_Folder = folders[0]
            diskInfo = psutil.disk_usage(root_Folder.path)
            isFull = diskInfo.percent >= self.remove_percentage
            return (isFull, diskInfo.percent)
        except Exception:
            return (False, 0)

    def sortOnTitle(self, e):
        return e.sortTitle

    def getTagLabeltoID(self):
        # Put all tags in a dictonairy with pair label <=> ID

        TagLabeltoID = {}
        for tag in self.radarrNode.all_tags():
            # Add tag to lookup by it's name
            TagLabeltoID[tag.label] = tag.id

        return TagLabeltoID

    def getIDsforTagLabels(self, tagLabels):

        TagLabeltoID = self.getTagLabeltoID()

        # Get ID's for extending media
        tagsIDs = []
        for taglabel in tagLabels:
            tagID = TagLabeltoID.get(taglabel)
            if tagID:
                tagsIDs.append(tagID)

        return tagsIDs

    def writeLog(self, init, msg):
        mode = "w" if init else "a"
        try:
            with open(self.log_filePath, mode) as logfile:
                logfile.write(f"{datetime.now()} - {msg}\n")
        except IOError:
            logging.error(f"Can't write file {self.log_filePath}.")

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
                            "Prune - NEW - "
                            f"{movie.title} ({movie.year}) is new."
                        )
                        self.writeLog(False, txtFirstSeen)
                        logging.info(txtFirstSeen)

                modifieddate = os.stat(firstseen_path).st_mtime
                movieDownloadDate = datetime.fromtimestamp(modifieddate)
                break

        # Prepare inputs for decision function
        isFull, percentage = self.isDiskFull()

        movie_dict = {
            'tagsIds': list(movie.tagsIds),
            'genres': list(movie.genres),
            'download_date': movieDownloadDate,
        }

        config = {
            'tags_keep_ids': self.getIDsforTagLabels(
                self.tags_to_keep
            ),
            'unwanted_genres': self.unwanted_genres,
            'remove_after_days': self.remove_after_days,
            'warn_days_infront': self.warn_days_infront,
            'tags_no_exclusion_ids': self.getIDsforTagLabels(
                self.radarr_tags_no_exclusion
            ),
            'months_no_exclusion': self.radarr_months_no_exclusion,
            'is_full': isFull,
        }

        # Ensure the repository root is on sys.path when the script is
        # executed directly so `from app.prune_logic` resolves correctly.
        repo_dir = os.path.dirname(os.path.abspath(__file__))
        repo_root = os.path.dirname(repo_dir)
        if repo_root not in sys.path:
            sys.path.insert(0, repo_root)

        # Import here (local) to avoid module-level import-after-code issues
        # and to keep top-level imports tidy.
        from app.prune_logic import decide_prune_action

        isRemoved, isPlanned, reason = decide_prune_action(movie_dict, config)

        # Handle the different outcomes with side-effects (delete, notify, log)
        if reason == 'keep-tag':
            if not self.only_show_remove_messages:
                txtKeeping = (
                    "Prune - KEEPING - "
                    f"{movie.title} ({movie.year}). Skipping."
                )
                self.writeLog(False, txtKeeping)
                logging.info(txtKeeping)
            return False, False

        if reason == 'missing-files':
            if not self.only_show_remove_messages:
                txtMissing = (
                    "Prune - MISSING - "
                    f"{movie.title} ({movie.year}) is not downloaded yet. "
                    "Skipping."
                )
                self.writeLog(False, txtMissing)
                logging.info(txtMissing)
            return False, False

        if reason == 'unwanted-genre':
            if not self.dry_run and self.radarr_enabled:
                self.radarrNode.delete_movie(
                    movie_id=movie.id,
                    tmdb_id=None,
                    imdb_id=None,
                    addImportExclusion=True,
                    deleteFiles=self.delete_files,
                )

                if self.delete_files:
                    self.txtFilesDelete = ", files deleted."
                else:
                    self.txtFilesDelete = ", files preserved."
            if self.pushover_enabled:
                self.userPushover.send_message(
                    message=(
                        f"{movie.title} ({movie.year}) Prune - UNWANTED "
                        f"{self.txtFilesDelete} - {movieDownloadDate}"
                    ),
                    sound=self.pushover_sound,
                )

            txtUnwanted = (
                "Prune - UNWANTED - "
                f"{movie.title} ({movie.year}){self.txtFilesDelete} - "
                f"{movieDownloadDate}"
            )
            self.writeLog(False, txtUnwanted)
            logging.info(txtUnwanted)
            return True, False

        if reason == 'will-be-removed':
            # replicate original time-left calculation
            timeLeft = (
                movieDownloadDate + timedelta(days=self.remove_after_days)
            ) - datetime.now()
            txtTimeLeft = 'h'.join(str(timeLeft).split(':')[:2])
            txtTitle = f"{movie.title} ({movie.year})"
            if self.pushover_enabled:
                self.userPushover.send_message(
                    message=(
                        "Prune - "
                        f"{txtTitle} will be removed from server in "
                        f"{txtTimeLeft}"
                    ),
                    sound=self.pushover_sound,
                )

            txtWillBeRemoved = (
                "Prune - WILL BE REMOVED - "
                f"{txtTitle} in {txtTimeLeft} - {movieDownloadDate}"
            )
            self.writeLog(False, txtWillBeRemoved)
            logging.info(txtWillBeRemoved)
            pct_msg = "Percentage diskspace radarrdv: " + f"{percentage}%"
            self.writeLog(False, pct_msg)
            logging.info(pct_msg)
            return False, True

        if reason == 'removed':
            # determine exclusion flags as before
            tagLabels_for_no_exclusion = self.radarr_tags_no_exclusion
            tagsIDs_for_no_exclusion = (
                self.getIDsforTagLabels(tagLabels_for_no_exclusion)
            )
            exclusiontagsfound = bool(
                set(movie.tagsIds) & set(tagsIDs_for_no_exclusion)
            )
            monthfound = (
                movieDownloadDate.month in self.radarr_months_no_exclusion
                if movieDownloadDate
                else False
            )

            if not self.dry_run and self.radarr_enabled:
                self.radarrNode.delete_movie(
                    movie_id=movie.id,
                    tmdb_id=None,
                    imdb_id=None,
                    addImportExclusion=not (monthfound or exclusiontagsfound),
                    deleteFiles=self.delete_files,
                )

                if self.delete_files:
                    self.txtFilesDelete = ", files deleted."
                else:
                    self.txtFilesDelete = ", files preserved."
            if self.pushover_enabled:
                self.userPushover.send_message(
                    message=(
                        f"{movie.title} ({movie.year}) Prune - REMOVED "
                        f"{self.txtFilesDelete} - {movieDownloadDate}"
                    ),
                    sound=self.pushover_sound,
                )

            txtRemoved = (
                "Prune - REMOVED - "
                f"{movie.title} ({movie.year}){self.txtFilesDelete} - "
                f"{movieDownloadDate}"
            )
            self.writeLog(False, txtRemoved)
            logging.info(txtRemoved)
            pct_msg = "Percentage diskspace radarrdv: " + f"{percentage}%"
            self.writeLog(False, pct_msg)
            logging.info(pct_msg)
            return True, False

        # default: active
        if not self.only_show_remove_messages:
            txtActive = (
                "Prune - ACTIVE - "
                f"{movie.title} ({movie.year}) is active. Skipping. - "
                f"{movieDownloadDate}"
            )
            self.writeLog(False, txtActive)
            logging.info(txtActive)

        return False, False

    def run(self):
        if not self.enabled_run:
            logging.info(
                "Prune - Library purge disabled.")
            self.writeLog(False, "Prune - Library purge disabled.\n")
            sys.exit()

        # Connect to Radarr
        if self.radarr_enabled:
            try:
                self.radarrNode = RadarrAPI(
                    self.radarr_url, self.radarr_token)
            except exceptions.ArrException as e:
                logging.error(
                    f"Can't connect to Radarr source {e}"
                )
                sys.exit()
            except Exception as e:
                logging.error(
                    f"Unexpected error connecting Radarr source: {e}")
                sys.exit(1)
        else:
            logging.info(
                "Prune - Radarr disabled in INI, exting.")
            self.writeLog(False, "Radarr disabled in INI, exting.\n")
            sys.exit()

        if self.dry_run:
            logging.info(
                "*****************************************************")
            logging.info(
                "**** DRY RUN, NOTHING WILL BE DELETED OR REMOVED ****")
            logging.info(
                "*****************************************************")
            self.writeLog(False, "Dry Run.\n")

        # Setting for PushOver
        if self.pushover_enabled:
            self.appPushover = Application(self.pushover_token_api)
            self.userPushover = \
                self.appPushover.get_user(self.pushover_user_key)

        # Get all movies from the server.
        media = None
        if self.radarr_enabled:
            media = self.radarrNode.all_movies()

        if self.verbose_logging:
            logging.info("Prune - Radarr Prune started.")
        self.writeLog(True, "Prune - Radarr Prune started.\n")

        # Make sure the library is not empty.
        numDeleted = 0
        numNotifified = 0
        isRemoved, isPlanned = False, False

        isFull, percentage = self.isDiskFull()

        logging.info(f"Percentage diskspace radarrdv: {percentage}%")

        if media and isFull:
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

            attachment = open(self.log_filePath, 'rb')
            obj = MIMEBase('application', 'octet-stream')
            obj.set_payload((attachment).read())
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

            logfile = open(self.log_filePath, "r")

            body += ''.join(logfile.readlines())

            logfile.close()

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
                logging.info(f"Prune - Mail Sent to {message['To']}.")
                self.writeLog(
                    False, f"Prune - Mail Sent to {message['To']}.\n")

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


if __name__ == '__main__':

    rlp = RLP()
    rlp.run()
    rlp = None
