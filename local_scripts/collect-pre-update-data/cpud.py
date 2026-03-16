#!/usr/bin/env -S LC_ALL=C.UTF-8 PYTHONIOENCODING=utf-8 python3

# collect-pre-update-data suite main executable


import argparse
import importlib
import logging
import os
import pathlib
import re
import shutil
import signal
import sys
import time

from libs.common import (add_user_logging, is_there_any_human,
                         prompt_bool, gen_backup_id, PopenWrapper)
from libs.runtime import die, Facts, ReturnCode, ShutdownEvent
from libs.defaults import (MODES_INTERNAL_MAP, MODES_USER_MAP,
                           DATA_DIR, TMP_DIR, CSUP_TT_REGEX,
                           HEARTBEAT_INTERVAL, EVENTS_HOOKS_MAP,
                           DATE_FORMAT, LOG_FORMAT, LOG_FORMAT_DEBUG)
from libs.format import multiline_list
from libs.heartbeat import HeartbeatWatchdog
from libs.progressbar import (ProgressbarAwareLoggingStreamHandler,
                              ProgressbarController)
from libs.sender import Sender
from libs.servers import Servers


DESC_SUITE = """
The suite collects various pre-update data from servers including:
- Comprehensive modifications report (based on below mentioned sources);
- PC check_patches_f script output (system modifications mentions);
- PI summary module output (Git-controlled modifications mentions);
- network configuration check and backup (if check passed);
- hardware configuration backup (mostly RAID);

Running suite without MODE argument starts it in defult mode.
Also, help is available for each mode separately.

The suite requires PI to be installed and setup.
"""
TITLE_MODES = "suite mode to execute; default is recommended"
ARG_DESC_SUITE_DEBUG = "set suite log level to debug"
ARG_DESC_SUITE_TICKET = (
    "ticket to send collected data to. If not specified, the data\n"
    "won't be sent anywhere, only collected and preserved on the\n"
    "installation."
)
ARG_DESC_SUITE_HEARTBEAT = (
    "override default heartbeat interval in seconds. If you specify\n"
    "value 0 or less then disables the whole feature at all"
)
ARG_DESC_SUITE_NO_PROGRESSBAR = (
    "disable progressbar displaying; logs will be shown as in older\n"
    "versions"
)

SUITE_EMAIL_SUBJECT_FAILURE = "suite failed execution log"
SUITE_EMAIL_BODY_FAILURE = (
    "The CPUD suite encountered some unexpected failure.\n"
    "The attached log might be useful for you or maintainer."
)


class CollectPreUpdateData:
    """Main class for suite initialization

    Performs initial setup and selects mode based on CLI arguments.
    Modes are located in the corresponding directory and are lazy-loaded.
    """

    def __init__(self):
        """Initializer

        Attributes:
            :_logger (logging.Logger): Basic logger instance.
            :_args (argparse.Namespace): Parsed CLI arguments.
            :_watchdog (HeartbeatWatchdog): Standalone monitor.
            :_display (ProgressbarController): Draws them.
        """
        self._logger = logging.getLogger("main")
        self._args = None
        self._watchdog = HeartbeatWatchdog()
        self._display = ProgressbarController()

    def main(self):
        """Main entrypoint for suite execution"""
        self._manage_jail("disable")
        self._parse_args()
        self._setup_trap()
        self._setup_config()
        self._make_tree()
        self._setup_logger()

        self._logger.info(f"Dumping args: {self._args}")
        self._logger.info(f"Dumping pre-mode Facts:\n{Facts()}")

        self._setup_heartbeat()
        self._setup_progressbar()
        self._exec_mode()
        self.shutdown()

    def _manage_jail(self, command):
        """Enable or disable jailctl based on the supplied value.

        Parameters:
            :command (str): enable or disable
        """
        jailctl = shutil.which("jailctl")
        if is_there_any_human() and jailctl:
            PopenWrapper([jailctl, command, "--force"])

    def _parse_args(self):
        """Parse CLI arguments

        Available options may depend on AVAILABLE_MODES_MAP
        defined in the defaults library.
        """
        def _check_tt_num(value):
            if re.search(CSUP_TT_REGEX, value):
                return value
            raise argparse.ArgumentTypeError(
                f"Incorrect ticket number; should be: {CSUP_TT_REGEX}"
            )

        parser = argparse.ArgumentParser(
            description=DESC_SUITE,
            formatter_class=argparse.RawTextHelpFormatter
        )
        parser.add_argument(
            "-d", "--debug", action="store_true",
            help=ARG_DESC_SUITE_DEBUG
        )
        parser.add_argument(
            "-t", "--ticket", type=_check_tt_num,
            help=ARG_DESC_SUITE_TICKET
        )
        parser.add_argument(
            "-hb", "--heartbeat", type=int,
            help=ARG_DESC_SUITE_HEARTBEAT
        )
        parser.add_argument(
            "-np", "--no-progressbar", action="store_true",
            help=ARG_DESC_SUITE_NO_PROGRESSBAR
        )

        subparsers = parser.add_subparsers(
            dest="mode", title=TITLE_MODES, metavar="MODE"
        )

        for mode_module_name, mode_class_name in MODES_INTERNAL_MAP.items():
            mode_module = importlib.import_module(f"modes.{mode_module_name}")
            mode_class = getattr(mode_module, mode_class_name)
            mode_class.setup_subparser(subparsers)

        self._args = parser.parse_args()
        if not self._args.mode:
            self._args.mode = "default"

    def _setup_trap(self):
        """Traps OS signals"""
        signal.signal(signal.SIGINT, self._handle_sigterm)
        signal.signal(signal.SIGTERM, self._handle_sigterm)

    def _setup_config(self) -> None:
        """Apply CLI args to Facts and perform initial setup"""
        start_epoch = int(time.time())
        Facts.start_epoch = start_epoch

        baseplace = os.path.dirname(os.path.abspath(__file__))
        Facts.baseplace = baseplace

        if self._args.ticket:
            Facts.csup_tt = self._args.ticket
        elif self._args.mode == "sender":
            self.main_die("Please specify ticket number for sending backup")
        elif self._args.mode == "default":
            if not is_there_any_human():
                self.die(
                    "Ticket number is not set. "
                    "Not connected to terminal to ask user's confirmation"
                )
            answer = prompt_bool(
                "Ticket number is not set. Data will only be collected and not sent. "
                "Are you sure? [y/n]: "
            )
            if not answer:
                self.main_die("Script termination requested by user", code=0)

        backup_id = (
            self._args.id
            if self._args.mode == "sender"
            else gen_backup_id()
        )
        Facts.backup_id = backup_id

        backup_dir = f"{DATA_DIR}/backup_{backup_id}"
        Facts.backup_dir = backup_dir

        Facts.log = f"{backup_dir}/execution.{start_epoch}.log"

        if isinstance(self._args.heartbeat, int):
            Facts.heartbeat = self._args.heartbeat
        else:
            Facts.heartbeat = HEARTBEAT_INTERVAL

        Facts.mode = self._args.mode
        Servers.update()

    def _make_tree(self):
        """Create backup directory structure

        RuntimeError is not raised if Facts.backup_dir is missing,
        as it may be intentional in sender mode.

        Structure after DATA_DIR:
            - DATA_DIR/
              - backup_<backup_id>/
                - execution.<timestamp>.log
                - raws/
                    - check_patches_f.collected.<timestamp>.txt
                    - patches_inventory.collected.<timestamp>.txt
                    - check_patches_f.parsed.<timestamp>.txt
                    - patches_inventory.parsed.<timestamp>.txt
                    - network_backup.<timestamp>.txt
                    - hardware_backup.<timestamp>.txt
                - reports/
                    - mods_reporter.compact.<timestamp>.txt
                    - mods_reporter.full.<timestamp>.txt
                    - network_check.<timestamp>.txt
        """
        backup_dir = Facts.backup_dir
        if not backup_dir: return

        backup_dir = pathlib.Path(backup_dir)
        if backup_dir.is_dir(): return

        PopenWrapper([
            shutil.which("sudo"), shutil.which("install"), "-d",
            "-o", str(os.getuid()), "-g", str(os.getgid()), str(backup_dir)
        ])

        tree = [
            backup_dir / "raws",
            backup_dir / "reports",
            pathlib.Path(TMP_DIR)
        ]
        for item in tree:
            item.mkdir(parents=True, exist_ok=True)

    def _setup_logger(self):
        """Root logger configuration

        If progressbar enabled then replaces standard stream handler
        with ProgressbarAwareLoggingStreamHandler for compatibility.
        """
        format = LOG_FORMAT_DEBUG if self._args.debug else LOG_FORMAT
        level = logging.DEBUG if self._args.debug else logging.INFO
        logging.basicConfig(format=format, datefmt=DATE_FORMAT, level=level, stream=sys.stdout)

        formatter = logging.Formatter(
            fmt=format, datefmt=DATE_FORMAT
        )
        log_path = Facts.log

        if not self._args.no_progressbar and is_there_any_human():
            for handler in logging.root.handlers:
                logging.root.removeHandler(handler)
            stream_handler = ProgressbarAwareLoggingStreamHandler(
                stream=sys.stderr
            )
            stream_handler.setLevel("USER")
            stream_handler.setFormatter(formatter)
            logging.root.addHandler(stream_handler)

        file_handler = logging.FileHandler(log_path)
        file_handler.setFormatter(formatter)
        logging.root.addHandler(file_handler)

        if self._args.ticket:
            self._logger.user(
                f"All data that you need will be sent to {self._args.ticket}"
            )
        self._logger.user(f"You may found the full log in {log_path}")

    def _setup_heartbeat(self):
        """Suite additional heartbeat configuration"""
        is_heartbeat_enabled = True

        interval = Facts.heartbeat
        if interval < 1:
            self._logger.warning(
                "Heartbeat is generaly disabled in configuration; "
                "long-running events won't be tracked"
            )
            is_heartbeat_enabled = False

        effective_hooks = [
            hook_name for hook_name, hook_class in EVENTS_HOOKS_MAP.items()
            if hook_class
        ]
        if not effective_hooks:
            self._logger.warning(
                "No heartbeat events hooks enabled in default configuration; "
                "long-running events likely won't be tracked"
            )
            is_heartbeat_enabled = False

        if is_heartbeat_enabled:
            self._logger.warning(
                f"Heartbeat is enabled; you'll be reminded about "
                f"long-running events within {interval} seconds interval"
            )
            self._logger.debug(
                f"The following heartbeat events hooks will be effective:\n"
                f"{multiline_list(effective_hooks)}"
            )
        if not self._watchdog.is_alive():
            self._watchdog.start()

    def _setup_progressbar(self):
        """User-friendly progressbar initialization"""
        if not self._args.no_progressbar and is_there_any_human():
            if not self._display.is_alive():
                self._display.start()

    def _exec_mode(self):
        """Execute selected suite mode based on CLI args

        Raises:
            :RuntimeError: If unable to select a valid mode.
        """
        mode_module = importlib.import_module(
            f"modes.{MODES_USER_MAP[self._args.mode]}"
        )
        mode_class = getattr(
            mode_module, MODES_INTERNAL_MAP[MODES_USER_MAP[self._args.mode]]
        )

        self._logger.info(f"Switching to {self._args.mode} mode")
        mode_class.run_mode(self._args, self._logger)

    def _handle_sigterm(self, signum, frame):
        """Handle SIGINT/SIGTERM to gracefully stop the script"""
        self.main_die("Script termination initiated by SIGTERM/SIGINT", code=0)

    def main_die(self, msg, code=1, is_exc=False):
        """On-error termination shortcut wrappped"""
        die(msg, self._logger, code=code, is_exc=is_exc)
        self.shutdown()

    def shutdown(self):
        """Shutdown the suite

        Send its own log in case of on-error shutdown.
        """
        ShutdownEvent.set()
        self._logger.warning("Main thread dying, it's others' turn too")

        retcode = ReturnCode.get()
        if retcode > 0 and Facts.csup_tt:
            self._logger.user("Sending my own log to the ticket")
            Sender.send(
                SUITE_EMAIL_SUBJECT_FAILURE,
                SUITE_EMAIL_BODY_FAILURE,
                attach=Facts.log,
                attach_as=(
                    f"cpud.failed_execution."
                    f"{Facts.start_epoch}.log"
                )
            )
        self._manage_jail("enable")
        sys.exit(retcode)


def main():
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    add_user_logging()

    cpud = CollectPreUpdateData()
    try:
        cpud.main()
    except Exception:
        cpud.main_die("Unhandled exception occurred:", is_exc=True)


if __name__ == "__main__":
    main()

