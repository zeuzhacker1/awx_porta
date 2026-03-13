# collect-pre-update-data backup data sender related objects


import datetime
import email
import hashlib
import logging
import mimetypes
import pathlib
import smtplib
import time
import zipfile

from libs.runtime import Facts, ReturnCode
from libs.common import ThreadSafeNamespace
from libs.defaults import (TMP_DIR, SENDER_MAIL_PARAMS,
                           SENDER_SUPPLY_COOKIE, SENDER_MAX_ATTACHEMENT_SIZE)


class Sender:
    """Simple email sender"""

    #: ThreadSafeNamespace: Traverse per-thread parameters in callstack.
    _tns = ThreadSafeNamespace()
    #: logging.Logger: Child logger.
    _logger = logging.getLogger("sender")

    @classmethod
    def send(
        cls,
        subject,
        body,
        attach=None,
        attach_as=None,
        zip_attach=False,
    ):
        """Sender refreshed main sequence

        Parameters:
            :subject (str): Email subject.
            :body (str): Email body.
            :attach (str|None): Path to file or directory to attach.
                In case of directory zip will be created.
            :attach_as (str|None): Name to use for attachement.
                Name of attach itself will be used if no any.
            :zip_attach (bool): Zip attachement, may be useful for file.
                Forced if attachement is directory.
        """
        try:
            cls._setup_tns(subject, body, attach, attach_as, zip_attach)
            cls._send_email()
        finally:
            if cls._tns.zip_arch:
                cls._tns.zip_arch.unlink()
            cls._tns.cleanup()

    @classmethod
    def legacy_main(cls):
        """Old sender sequence"""
        cls.assert_backup_is_not_empty()
        backup_dir = Facts.backup_dir
        cls.send(
            (f"whole backup directory"),
            (
                f"Archive is attached; original is on "
                f"Configuration server in: {backup_dir}"
            ),
            attach=backup_dir,
            attach_as=f"cpud.backup_dir.{Facts.start_epoch}.zip",
            zip_attach=True
        )

    @classmethod
    def _setup_tns(cls, subject, body, attach, attach_as, zip_attach):
        """Setup thread namespace for further work

        Parameters:
            :subject (str): Email subject.
            :body (str): Email body.
            :attach (str|None): Path to file or directory to attach.
                In case of directory zip will be created.
            :attach_as (str|None): Name to use for attachement.
                Name of attach itself will be used if no any.
            :zip_attach (bool): Zip attachement, may be useful for file.
                Forced if attachement is directory.
        """
        cls._tns.subject = subject
        cls._tns.body = body
        cls._tns.attach_src = attach
        cls._tns.attach_as = attach_as
        cls._tns.zip_attach = zip_attach
        cls._tns.zip_arch = None

    @staticmethod
    def assert_backup_is_not_empty():
        """Check if backup is empty

        Raises:
            :FileNotFoundError: If backup is empty.
        """
        backup_dir = Facts.backup_dir

        raws_path = pathlib.Path(backup_dir) / "raws"
        reports_path = pathlib.Path(backup_dir) / "reports"

        raws = [ item for item in raws_path.iterdir() ]
        reports = [ item for item in reports_path.iterdir() ]

        if raws or reports: return
        raise FileNotFoundError("Current backup is empty; nothing to send")

    @classmethod
    def _send_email(cls):
        """Send zipped backup via email

        Expects cls._tns in state as after cls._setup_tns().
        Email will be composed automatically.
        """
        msg = cls._compose_email()
        host = SENDER_MAIL_PARAMS["smtp_host"]
        port = SENDER_MAIL_PARAMS["smtp_port"]

        cls._logger.info(
            f"Sending email to {Facts.csup_tt}: {cls._tns.subject}"
        )
        with smtplib.SMTP(host, port) as smtp:
            if cls._logger.getEffectiveLevel() <= logging.DEBUG:
                smtp.set_debuglevel(1)
            smtp.ehlo_or_helo_if_needed()
            res = smtp.send_message(msg)

        cls._logger.info(f"Email sent; result: {res or 'OK'}")

    @classmethod
    def _compose_email(cls):
        """Prepare email to send backup to ticket

        Returns:
            :email.message.EmailMessage: Composed message.
        """
        em = email.message.EmailMessage()

        em["From"] = SENDER_MAIL_PARAMS["mail_from"]
        em["To"]   = SENDER_MAIL_PARAMS["mail_to"]
        em["Date"] = email.utils.format_datetime(
            datetime.datetime.now(datetime.timezone.utc)
        )
        em["Message-Id"] = email.utils.make_msgid()

        em["Subject"] = (
            f"[{Facts.csup_tt}] "
            f"/collect-pre-update-data #{Facts.backup_id}/ {cls._tns.subject}"
        )
        em.set_content(f"{cls._tns.body} @comment")

        if cls._tns.attach_src:
            cls._attach_file(
                em, cls._tns.attach_src, file_name=cls._tns.attach_as
            )
        return em

    @classmethod
    def _attach_file(cls, em, file_path, file_name=None, compressed=False):
        """Supply attachement to email message

        Expects cls._tns in state as after cls._setup_tns().

        Validates file size and tries to compress it
        if exceeds SENDER_MAX_ATTACHEMENT_SIZE.

        Supplies cookie in the end of file if SENDER_SUPPLY_COOKIE.
        It's required to bypass YT's duplicate attachement limitation.

        Parameters:
            :em (email.message.EmailMessage): Message to attach to.
            :file_path (str): Path to file to attach.
            :file_name (str|None): Name for file to attach.
            :compressed (bool): Internal switcher indicating that there
                is no point in attempting to compress file.
        """
        def _zip_file(file_path):
            cls._tns.zip_arch = cls.zip_file(file_path, file_name=file_name)
            return cls._attach_file(
                em, cls._tns.zip_arch, file_name=file_name, compressed=True
            )

        file_path = pathlib.Path(file_path)

        if not compressed and (file_path.is_dir() or cls._tns.zip_attach):
            return _zip_file(file_path)

        if file_path.stat().st_size > SENDER_MAX_ATTACHEMENT_SIZE*1024*1024:
            if not compressed:
                return _zip_file(file_path)
            cls._logger.error(
                f"Cannot send the following email with attachement "
                f"due to size limit in {SENDER_MAX_ATTACHEMENT_SIZE}M: "
                f"{em['Subject']}"
            )
            ReturnCode.set(1)
            return

        ctype, _ = mimetypes.guess_type(str(file_path))
        maintype, subtype = (
            ctype.split("/")
            if ctype
            else ("application", "octet-stream")
        )

        content = file_path.read_bytes()
        if SENDER_SUPPLY_COOKIE:
            content += (
                f"\n"
                f"CPUD_COOKIE;"
                f"backup_id:{Facts.backup_id};"
                f"start_epoch:{Facts.start_epoch};"
                f"attach_src:{cls._tns.attach_src};"
                f"attach_md5:{hashlib.md5(content).hexdigest()};"
                f"attach_time:{round(time.time(), 3)};"
                .encode(encoding="utf-8")
            )
        em.add_attachment(
            content,
            maintype=maintype,
            subtype=subtype,
            filename=(file_name or file_path.name)
        )

    @classmethod
    def zip_file(cls, zip_target, file_name=None):
        """Zip files/directory before sending

        Parameters:
            :zip_target (str): Path to file or directory to zip.
            :zip_name (str|None): Name part for resulting file.
                Name of target will be used if None.

        Returns:
            :str: Path to zipped backup.
        """
        zip_target = pathlib.Path(zip_target)
        zip_arch = pathlib.Path(
            f"{TMP_DIR}/backup_{Facts.backup_id}."
            f"{Facts.start_epoch}."
            f"{file_name or zip_target.name}.zip"
        )
        cls._logger.info(f"Going to zip {zip_target} to {zip_arch}")

        with zipfile.ZipFile(zip_arch, "w", zipfile.ZIP_DEFLATED) as zfd:
            for item in zip_target.rglob("*"):
                cls._logger.debug(f"Zipping {item}")
                zfd.write(item, arcname=item.relative_to(zip_target.parent))

        cls._logger.info("Backup zipped")
        return zip_arch

