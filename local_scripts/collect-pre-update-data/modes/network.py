# collect-pre-update-data network modes initial objects


import argparse

from libs.heartbeat import SubmodeGeneralHook, HeartbeatManager
from libs.mode_generic import ModeGeneric
from libs.network_processor import NetworkProcessor
from libs.runtime import Facts
from libs.sender import Sender


DESC_NETWORK_AUTO = """
Performs network configuration check and backup if check passed.
Both check and backup are necessary for normal update execution.

If configuration check failed you should fix faced issues.
Once fixed run network-backup mode separately.
"""
SHORT_DESC_NETWORK_AUTO = "check and maybe backup network configuration"
DESC_NETWORK_CHECK = """
Better use network-auto since in implies both check and backup.

Execute either NetworkManager or legacy RHEL/OL network configs checks.
Target configs are always selected automatically.

These checks ensure no major issues in your network configuration.
Once check passed you should backup configuration.
"""
SHORT_DESC_NETWORK_CHECK = "check network configuration"
DESC_NETWORK_BACKUP = """
Better use network-auto since in implies both check and backup.

Execute either NetworkManager or legacy RHEL/OL network configs backup.
Target configs are always selected automatically.

These backups are crucial for normal update workflows.
You should executy backup only if configs check passed.
"""
SHORT_DESC_NETWORK_BACKUP = "backup network configuration"


NETWORK_EMAIL_SUBJECT_CHECK_PASSED = "network configuration check passed"
NETWORK_EMAIL_BODY_CHECK_PASSED = (
    "Please make sure network configuration backup "
    "is collected too. No other actions required."
)
NETWORK_EMAIL_SUBJECT_CHECK_FAILED = "network configuration check FAILED!"
NETWORK_EMAIL_BODY_CHECK_FAILED = (
    "This is usual part of workflow and a bit expected; don't submit this.\n"
    "Please proceed with the following:\n"
    "1. Investigate attached output.\n"
    "2. Fix issues highlighted in it.\n"
    "3. Re-run the suite in network-auto mode.\n"
    "4. Make sure the check passed and network backup collected!"
)
NETWORK_EMAIL_SUBJECT_BACKUP_COLLECTED = "network configuration backup collected"
NETWORK_EMAIL_BODY_BACKUP_COLLECTED = "Use during update in case of any issues."

NETWORK_EMAIL_SUBJECT_BACKUP_FAILED = "network configuration backup FAILED!"
NETWORK_EMAIL_BODY_BACKUP_FAILED = (
    "Please proceed with the following:\n"
    "1. Investigate attached output.\n"
    "2. Fix or submit issues found in it.\n"
    "3. DO NOT EXECUTE UPDATE UNLESS BACKUP IS COLLECTED!\n\n"
    "Hints:\n"
    "- Suite execution log might be helpful and usually sent to ticket too."
)


#: dict of dict of str or callable: Handy mapping for network modes.
NETWORK_ACTION_MODE_TO_PARTS_MAP = {
    "network-auto": {
        "desc":     DESC_NETWORK_AUTO,
        "short":    SHORT_DESC_NETWORK_AUTO,
        "executor": NetworkProcessor().main
    },
    "network-check": {
      "desc":       DESC_NETWORK_CHECK,
        "short":    SHORT_DESC_NETWORK_CHECK,
        "executor": NetworkProcessor().check_config
    },
    "network-backup": {
        "desc":     DESC_NETWORK_BACKUP,
        "short":    SHORT_DESC_NETWORK_BACKUP,
        "executor": NetworkProcessor().backup_config
    }
}


class ModeNetwork(ModeGeneric):
    """network mode static representation"""

    @staticmethod
    def setup_subparser(subparsers):
        """Interface method implementation"""
        for mode, parts in NETWORK_ACTION_MODE_TO_PARTS_MAP.items():
            subparsers.add_parser(
                mode,
                help=parts["short"], description=parts["desc"],
                formatter_class=argparse.RawTextHelpFormatter
            )

    @staticmethod
    def run_mode(args, logger, no_send=False):
        """Run network mode

        Runs either network_check.sh or network_backup.sh on all servers
        depending on the selecte action.
        """
        is_config_mode_my = args.mode in NETWORK_ACTION_MODE_TO_PARTS_MAP
        if is_config_mode_my:
            name = f"{args.mode} "
            desc = NETWORK_ACTION_MODE_TO_PARTS_MAP[args.mode]["short"]
        else:
            name = f"network-auto sub"
            desc = (
                NETWORK_ACTION_MODE_TO_PARTS_MAP["network-auto"]["short"]
            )
        with HeartbeatManager.track(
            SubmodeGeneralHook.id,
            {"name": name},
            {"desc": desc}
        ):
            if is_config_mode_my:
                NETWORK_ACTION_MODE_TO_PARTS_MAP[args.mode]["executor"]()
            else:
                NETWORK_ACTION_MODE_TO_PARTS_MAP["network-auto"]["executor"]()
            if no_send or not Facts.csup_tt:
                return

            if Facts.net_check_output and Facts.net_check_passed is not None:
                if Facts.net_check_passed:
                    subject = NETWORK_EMAIL_SUBJECT_CHECK_PASSED
                    body = NETWORK_EMAIL_BODY_CHECK_PASSED
                    attach_type = ""
                else:
                    subject = NETWORK_EMAIL_SUBJECT_CHECK_FAILED
                    body = NETWORK_EMAIL_BODY_CHECK_FAILED
                    attach_type = "failed_"
                Sender.send(
                    subject,
                    body,
                    attach=Facts.net_check_output,
                    attach_as=(
                        f"cpud.{attach_type}network_check."
                        f"{Facts.start_epoch}.txt"
                    )
                )
            if Facts.net_backup_output and Facts.net_check_passed is not None:
                if Facts.net_backup_collected:
                    subject = NETWORK_EMAIL_SUBJECT_BACKUP_COLLECTED
                    body = NETWORK_EMAIL_BODY_BACKUP_COLLECTED
                    attach_type = ""
                else:
                    subject = NETWORK_EMAIL_SUBJECT_BACKUP_FAILED
                    body = NETWORK_EMAIL_BODY_BACKUP_FAILED
                    attach_type = "failed_"
                Sender.send(
                    subject,
                    body,
                    attach=Facts.net_backup_output,
                    attach_as=(
                        f"cpud.{attach_type}network_backup."
                        f"{Facts.start_epoch}.txt"
                    )
                )

