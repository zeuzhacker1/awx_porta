# collect-pre-update-data sender mode initial objects


import argparse

from libs.defaults import DATA_DIR
from libs.heartbeat import SubmodeGeneralHook, HeartbeatManager
from libs.mode_generic import ModeGeneric
from libs.runtime import Facts
from libs.sender import Sender


DESC_SENDER = f"""
Send already collected data to the specified ticket. May be useful if it
was omitted during previous execution of any mode.

Collected data is stored under the {DATA_DIR} directory. Each script run
creates a backup with a unique ID.

This ID is part of the backup directory name. Use it to send collected
data to the ticket.
"""
SHORT_DESC_SENDER = "send already collected data to the ticket"
ARG_DESC_SENDER_ID = "unique ID of collected data package"


class ModeSender(ModeGeneric):
    """sender mode static representation"""

    @staticmethod
    def setup_subparser(subparsers):
        """Interface method implementation"""
        subparser = subparsers.add_parser(
            "sender",
            help=SHORT_DESC_SENDER, description=DESC_SENDER,
            formatter_class=argparse.RawTextHelpFormatter
        )
        subparser.add_argument(
            "-i", "--id", required=True,
            help=ARG_DESC_SENDER_ID
        )

    @staticmethod
    def run_mode(args, logger, no_send=False):
        """Run sender mode"""
        is_config_mode_my = args.mode == "sender"
        with HeartbeatManager.track(
            SubmodeGeneralHook.id,
            {"name": (
                "sender "
                if is_config_mode_my
                else "sender sub"
            )},
            {"desc": SHORT_DESC_SENDER}
        ):
            if Facts.csup_tt:
                Sender().legacy_main()
                return
            logger.user("Ticket number isn't set, cannot send collected data")

