# collect-pre-update-data hardware mode initial objects


import argparse

from libs.hardware_processor import HardwareProcessor
from libs.heartbeat import SubmodeGeneralHook, HeartbeatManager
from libs.mode_generic import ModeGeneric
from libs.runtime import Facts
from libs.sender import Sender


DESC_HARDWARE = """
Execute hardware info/configuration collection and backup.
Mostly needed in case if you have RAID configured.
"""
SHORT_DESC_HARDWARE = "collect hardware information backup"


HARDWARE_EMAIL_SUBJECT_BACKUP_COLLECTED = "hardware configuration backup collected"
HARDWARE_EMAIL_BODY_BACKUP_COLLECTED = "Use during update in case of any issues."

HARDWARE_EMAIL_SUBJECT_BACKUP_FAILED = "hardware configuration backup FAILED!"
HARDWARE_EMAIL_BODY_BACKUP_FAILED = (
    "Please proceed with the following:\n"
    "1. Investigate attached output.\n"
    "2. Fix or submit issues found in it.\n"
    "3. DO NOT EXECUTE UPDATE UNLESS BACKUP IS COLLECTED!\n\n"
    "Hints:\n"
    "- Suite execution log might be helpful and usually sent to ticket too."
)


class ModeHardware(ModeGeneric):
    """hardware mode static representation"""

    @staticmethod
    def setup_subparser(subparsers):
        """Interface method implementation"""
        subparsers.add_parser(
            "hardware",
            help=SHORT_DESC_HARDWARE, description=DESC_HARDWARE,
            formatter_class=argparse.RawTextHelpFormatter
        )

    @staticmethod
    def run_mode(args, logger, no_send=False):
        """Run hardware mode

        Runs scripts/hardware_backup.sh on all servers.
        """
        is_config_mode_my = args.mode == "hardware"
        with HeartbeatManager.track(
            SubmodeGeneralHook.id,
            {"name": (
                "hardware "
                if is_config_mode_my
                else "hardware sub"
            )},
            {"desc": SHORT_DESC_HARDWARE}
        ):
            HardwareProcessor().main()
            if (
                no_send
                or not Facts.csup_tt
                or not Facts.hw_backup_output
                or Facts.hw_backup_collected is None
            ):
                return

            if Facts.hw_backup_collected:
                subject = HARDWARE_EMAIL_SUBJECT_BACKUP_COLLECTED
                body = HARDWARE_EMAIL_BODY_BACKUP_COLLECTED
                attach_type = ""
            else:
                subject = HARDWARE_EMAIL_SUBJECT_BACKUP_FAILED
                body = HARDWARE_EMAIL_BODY_BACKUP_FAILED
                attach_type = "failed_"
            Sender.send(
                subject,
                body,
                attach=Facts.hw_backup_output,
                attach_as=(
                    f"cpud.{attach_type}hardware_backup."
                    f"{Facts.start_epoch}.txt"
                )
            )

