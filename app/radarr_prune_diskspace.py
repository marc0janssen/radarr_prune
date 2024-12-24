# Name: Radarr Prune
# Coder: Marco Janssen (mastodon @marc0janssen@mastodon.online)
# date: 2024-12-24 11:45:00
# update: 2024-12-24 11:45:00

import logging
import configparser
import sys
import shutil
import glob
import os
import smtplib
import psutil

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime, timedelta
from arrapi import RadarrAPI
from chump import Application
from socket import gaierror


class RLP():

    def __init__(self):
        logging.basicConfig(
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            level=logging.INFO)

        config_dir = "/config/"
        app_dir = "/app/"
        log_dir = "/logging/prune/"

        self.config_file = "radarr_prune.ini"
        self.exampleconfigfile = "radarr_prune.ini.example"
        self.log_file = "radarr_prune.log"
        self.firstseen = ".firstseen"

        self.config_filePath = f"{config_dir}{self.config_file}"
        self.log_filePath = f"{log_dir}{self.log_file}"

        try:
            with open(self.config_filePath, "r") as f:
                f.close()
            try:
                self.config = configparser.ConfigParser()
                self.config.read(self.config_filePath)

                # RADARR
                self.radarr_enabled = True if (
                    self.config['RADARR']['ENABLED'] == "ON") else False
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
                self.radarr_months_no_exclusion = list(map(int, list(
                    self.config['PRUNE']
                    ['AUTO_NO_EXCLUSION_MONTHS'].split(","))))
                self.remove_after_days = int(
                    self.config['PRUNE']['REMOVE_MOVIES_AFTER_DAYS'])
                self.warn_days_infront = int(
                    self.config['PRUNE']['WARN_DAYS_INFRONT'])
                self.dry_run = True if (
                    self.config['PRUNE']['DRY_RUN'] == "ON") else False
                self.enabled_run = True if (
                    self.config['PRUNE']['ENABLED'] == "ON") else False
                self.delete_files = True if (
                    self.config['PRUNE']
                    ['PERMANENT_DELETE_MEDIA'] == "ON") else False
                self.only_show_remove_messages = True if (
                    self.config['PRUNE']
                    ['ONLY_SHOW_REMOVE_MESSAGES'] == "ON") else False
                self.verbose_logging = True if (
                    self.config['PRUNE']['VERBOSE_LOGGING'] == "ON") else False
                self.video_extensions = list(
                    self.config['PRUNE']
                    ['VIDEO_EXTENSIONS_MONITORED'].split(","))
                self.mail_enabled = True if (
                    self.config['PRUNE']
                    ['MAIL_ENABLED'] == "ON") else False
                self.only_mail_when_removed = True if (
                    self.config['PRUNE']
                    ['ONLY_MAIL_WHEN_REMOVED'] == "ON") else False
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

        except IOError or FileNotFoundError:
            logging.error(
                f"Can't open file {self.config_filePath}, "
                f"creating example INI file."
            )

            shutil.copyfile(f'{app_dir}{self.exampleconfigfile}',
                            f'{config_dir}{self.exampleconfigfile}')
            sys.exit()

    def sortOnTitle(self, e):
        return e.sortTitle

    def getTagLabeltoID(self, typeOfMedia):
        # Put all tags in a dictonairy with pair label <=> ID

        TagLabeltoID = {}
        if typeOfMedia == "serie":
            for tag in self.sonarrNode.all_tags():
                # Add tag to lookup by it's name
                TagLabeltoID[tag.label] = tag.id
        else:
            for tag in self.radarrNode.all_tags():
                # Add tag to lookup by it's name
                TagLabeltoID[tag.label] = tag.id

        return TagLabeltoID

    def getIDsforTagLabels(self, typeOfmedia, tagLabels):

        TagLabeltoID = self.getTagLabeltoID(typeOfmedia)

        # Get ID's for extending media
        tagsIDs = []
        for taglabel in tagLabels:
            tagID = TagLabeltoID.get(taglabel)
            if tagID:
                tagsIDs.append(tagID)

        return tagsIDs

    def writeLog(self, init, msg):

        try:
            if init:
                logfile = open(self.log_filePath, "w")
            else:
                logfile = open(self.log_filePath, "a")
            logfile.write(f"{datetime.now()} - {msg}")
            logfile.close()
        except IOError:
            logging.error(
                f"Can't write file {self.log_filePath}."
            )

    def evalMovie(self, movie):

        movieDownloadDate = None

        fileList = glob.glob(movie.path + "/*")
        for file in fileList:
            if file.lower().endswith(tuple(self.video_extensions)):
                # Get modfified date on .firstseen,
                # Which is the downloaddate
                # If not exist then create this file.

                if not os.path.isfile(f"{movie.path}/{self.firstseen}"):
                    with open(f"{movie.path}/{self.firstseen}", 'w') \
                            as firstseen_file:
                        firstseen_file.close()

                        if not self.only_show_remove_messages:
                            txtFirstSeen = (
                                f"Prune - NEW - "
                                f"{movie.title} ({movie.year})"
                                f" is new."
                            )

                            self.writeLog(False, f"{txtFirstSeen}\n")
                            logging.info(txtFirstSeen)

                modifieddate = os.stat(
                    f"{movie.path}/{self.firstseen}").st_mtime
                movieDownloadDate = \
                    datetime.fromtimestamp(modifieddate)

                break

        isRemoved, isPlanned = False, False

        # Get ID's for keeping movies anyway
        tagLabels_to_keep = self.tags_to_keep
        tagsIDs_to_keep = self.getIDsforTagLabels(
            "movie", tagLabels_to_keep)

        # check if ONE of the "KEEP" tags is
        # in the set of "MOVIE TAGS"
        if set(movie.tagsIds) & set(tagsIDs_to_keep):
            if not self.only_show_remove_messages:

                txtKeeping = (
                    f"Prune - KEEPING - {movie.title} ({movie.year})."
                    f" Skipping."
                )

                self.writeLog(False, f"{txtKeeping}\n")
                logging.info(txtKeeping)

        else:

            if not fileList or not movieDownloadDate:
                # If FIle is not found, the movie is missing
                # add will be skipped, These are probably
                # movies in the future

                if not self.only_show_remove_messages:
                    txtMissing = (
                        f"Prune - MISSING - "
                        f"{movie.title} ({movie.year})"
                        f" is not downloaded yet. Skipping."
                    )

                    self.writeLog(False, f"{txtMissing}\n")
                    logging.info(txtMissing)

            else:

                if (
                    set(movie.genres) &
                    set(self.unwanted_genres)
                ):
                    if not self.dry_run:
                        if self.radarr_enabled:

                            self.radarrNode.delete_movie(
                                movie_id=movie.id,
                                tmdb_id=None,
                                imdb_id=None,
                                addImportExclusion=True,
                                deleteFiles=self.delete_files
                            )

                    if self.delete_files:
                        self.txtFilesDelete = \
                            ", files deleted."
                    else:
                        self.txtFilesDelete = \
                            ", files preserved."

                    if self.pushover_enabled:
                        self.message = self.userPushover.send_message(
                            message=f"{movie.title} ({movie.year}) "
                            f"Prune - UNWANTED - {movie.title} "
                            f"({movie.year})"
                            f"{self.txtFilesDelete}"
                            f" - {movieDownloadDate}",
                            sound=self.pushover_sound
                        )

                    txtUnwanted = (
                        f"Prune - UNWANTED - {movie.title} ({movie.year})"
                        f"{self.txtFilesDelete}"
                        f" - {movieDownloadDate}"
                    )

                    self.writeLog(False, f"{txtUnwanted}\n")
                    logging.info(txtUnwanted)

                    isRemoved, isPlanned = True, False

                    return isRemoved, isPlanned

                now = datetime.now()

                # check if there needs to be warn "DAYS" infront of removal
                # 1. Are we still within the period before removel?
                # 2. Is "NOW" less than "warning days" before removal?
                # 3. is "NOW" more then "warning days - 1" before removal
                #               (warn only 1 day)
                if (
                    timedelta(
                        days=self.remove_after_days) >
                    now - movieDownloadDate and
                    movieDownloadDate +
                    timedelta(
                        days=self.remove_after_days) -
                    now <= timedelta(days=self.warn_days_infront) and
                    movieDownloadDate +
                    timedelta(
                        days=self.remove_after_days) -
                    now > timedelta(days=self.warn_days_infront) -
                    timedelta(days=1)
                ):

                    self.timeLeft = (
                        movieDownloadDate +
                        timedelta(
                            days=self.remove_after_days) - now)

                    txtTimeLeft = \
                        'h'.join(str(self.timeLeft).split(':')[:2])

                    txtTitle = f"{movie.title} ({movie.year})"

                    if self.pushover_enabled:

                        self.message = self.userPushover.send_message(
                            message=f"Prune - {txtTitle} "
                            f"will be removed from server in "
                            f"{txtTimeLeft}",
                            sound=self.pushover_sound
                        )

                    txtWillBeRemoved = (
                        f"Prune - WILL BE REMOVED - "
                        f"{txtTitle}"
                        f" in {txtTimeLeft}"
                        f" - {movieDownloadDate}"
                    )

                    self.writeLog(False, f"{txtWillBeRemoved}\n")
                    logging.info(txtWillBeRemoved)

                    isRemoved, isPlanned = False, True

                    return isRemoved, isPlanned

                # Check is movie is older than "days set in INI"
                if (
                    now - movieDownloadDate >=
                        timedelta(
                            days=self.remove_after_days)
                ):

                    if not self.dry_run:
                        if self.radarr_enabled:

                            # Get ID's for exclusion list movies
                            tagLabels_for_no_exclusion = \
                                self.radarr_tags_no_exclusion
                            tagsIDs_for_no_exclusion = \
                                self.getIDsforTagLabels(
                                    "movie", tagLabels_for_no_exclusion)

                            # Check if no_exclusion_tags are in movie tags
                            exclusiontagsfound = set(movie.tagsIds) & set(
                                tagsIDs_for_no_exclusion)

                            # Check is the current month is in the
                            # no_exclusion_months list
                            monthfound = \
                                movieDownloadDate.month in \
                                self.radarr_months_no_exclusion

                            self.radarrNode.delete_movie(
                                movie_id=movie.id,
                                tmdb_id=None,
                                imdb_id=None,
                                addImportExclusion=not
                                (monthfound or exclusiontagsfound),
                                deleteFiles=self.delete_files
                            )

                    if self.delete_files:
                        self.txtFilesDelete = \
                            ", files deleted."
                    else:
                        self.txtFilesDelete = \
                            ", files preserved."

                    if self.pushover_enabled:
                        self.message = self.userPushover.send_message(
                            message=f"{movie.title} ({movie.year}) "
                            f"Prune - REMOVED - {movie.title} "
                            f"({movie.year})"
                            f"{self.txtFilesDelete}"
                            f" - {movieDownloadDate}",
                            sound=self.pushover_sound
                        )

                    txtRemoved = (
                        f"Prune - REMOVED - {movie.title} ({movie.year})"
                        f"{self.txtFilesDelete}"
                        f" - {movieDownloadDate}"
                    )

                    self.writeLog(False, f"{txtRemoved}\n")
                    logging.info(txtRemoved)

                    isRemoved, isPlanned = True, False

                else:
                    if not self.only_show_remove_messages:
                        txtActive = (
                            f"Prune - ACTIVE - "
                            f"{movie.title} ({movie.year})"
                            f" is active. Skipping."
                            f" - {movieDownloadDate}"
                        )

                        self.writeLog(False, f"{txtActive}\n")
                        logging.info(txtActive)

                    isRemoved, isPlanned = False, False

        return isRemoved, isPlanned

    def run(self):
        if not self.enabled_run:
            logging.info(
                "Prune - Library purge disabled.")
            self.writeLog(False, "Prune - Library purge disabled.\n")
            sys.exit()

        # Connect to Radarr
        if self.radarr_enabled:
            self.radarrNode = RadarrAPI(
                self.radarr_url, self.radarr_token)
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

        # Get the Rootfolers
        if self.radarr_enabled:
            folders = self.radarrNode.root_folder()
            root_Folder = folders[0]
            tttr = root_Folder[0]
            print(tttr)

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
        if media:
            media.sort(key=self.sortOnTitle)  # Sort the list on Title
            for movie in media:
                isRemoved, isPlanned = self.evalMovie(movie)
                if isRemoved:
                    numDeleted += 1
                if isPlanned:
                    numNotifified += 1

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
