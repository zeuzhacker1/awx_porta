# collect-pre-update-data default mode initial objects


import argparse

from libs.common import ParanoidThreadPoolExecutor
from libs.heartbeat import SubmodeGeneralHook, HeartbeatManager
from libs.mode_generic import ModeGeneric
from libs.runtime import get_my_tid
from modes.hardware import ModeHardware
from modes.mods_reporter import ModeModsReporter
from modes.network import ModeNetwork


DESC_DEFAULT = """
Default execution mode. Runs mods_reporter, network check and backup,
and hardware configuration backup in parallel. For details, see each
mode's description.
"""
SHORT_DESC_DEFAULT = "recommended pre-update data collection sequence"


class ModeDefault(ModeGeneric):
    """default mode static representation"""

    @staticmethod
    def setup_subparser(subparsers):
        """Interface method implementation"""
        subparsers.add_parser(
            "default",
            help=SHORT_DESC_DEFAULT, description=DESC_DEFAULT,
            formatter_class=argparse.RawTextHelpFormatter
        )

    @staticmethod
    def run_mode(args, logger, no_send=False):
        """Run default mode

        Runs mods_reporter, network, and hardware modes in parallel.
        """
        def _exec_submode(name, method):
            method(args, logger)
            HeartbeatManager.notify(
                SubmodeGeneralHook.id, {"name": name}, altid=tid
            )
        with HeartbeatManager.track(
            SubmodeGeneralHook.id,
            {"name": "default "},
            {"desc": SHORT_DESC_DEFAULT},
            goal=4
        ):
            tid = get_my_tid()
            submodes = {
                "mods-reporter": ModeModsReporter.run_mode,
                "network":       ModeNetwork.run_mode,
                "hardware":      ModeHardware.run_mode
            }
            with ParanoidThreadPoolExecutor(max_workers=3) as pool:
                for name, method in submodes.items():
                    pool.submit(_exec_submode, name, method)
                for future in pool.iter_completed():
                    future.result()

