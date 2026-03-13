# collect-pre-update-data network configuration-related objects


import logging
import threading

from libs.common import get_script, TempfileBufferedFileWriter
from libs.format import indent_strs
from libs.objects import threadsafemethod, MetaSingleton
from libs.runtime import Facts, ReturnCode
from libs.servers import Servers


class NetworkProcessor(metaclass=MetaSingleton):
    """Network configuration check and backup processor

    Uses network_check.sh and network_backup.sh scripts from the
    corresponding directory and follows the same logic for launching.
    """

    #: threading.RLock: Ensures no simultaneous executions.
    _lock = threading.RLock()

    def __init__(self):
        """Initializer

        Attributes:
            :_logger (logging.Logger): Child logger.
        """
        self._logger = logging.getLogger("network")

    @threadsafemethod
    def main(self, no_backup=False):
        """Initiates network configuration check and backup

        Parameters:
            :no_backup (bool): If True then configuration backup
                won't be performed even if check is successful.
        """
        if self.check_config() and not no_backup:
            self._logger.info(
                "Configs check passed; going to perform full backup"
            )
            self.backup_config()

    @threadsafemethod
    def check_config(self):
        """Execute network configuration check on remote servers

        Returns:
            :bool: False if network configuration check failed on any of
                remote servers.
        """
        from modes.network import NETWORK_EMAIL_BODY_CHECK_FAILED

        check_output = TempfileBufferedFileWriter(
            f"{Facts.backup_dir}/reports/"
            f"network_check.{Facts.start_epoch}.txt"
        )
        Facts.net_check_output = check_output.path
        self._logger.info(
            f"Going to perform network configuration check; "
            f"output: {check_output.path}"
        )

        procs = Servers.run_cmd(
            get_script(
                "network_check",
                libs_names=["_shared_network"],
                no_shared=True
            ),
            to_fd=check_output,
            ignore_err=True,
            parallel=True
        )
        failed_servers = [
            server for server, proc in procs.items()
            if proc.returncode != 0
        ]
        if not failed_servers:
            self._logger.info("Check is successfully finished on all servers")
            Facts.net_check_passed = True
            return True
        self._logger.user(
            f"Network configuration check failed on some servers:\n"
            f"{indent_strs(NETWORK_EMAIL_BODY_CHECK_FAILED)}"
        )
        Facts.net_check_passed = False
        # We don't want to trigger suite execution logs sending.
        #ReturnCode.set(1)
        return False

    @threadsafemethod
    def backup_config(self):
        """Execute network configuration backup on remote servers"""
        from modes.network import NETWORK_EMAIL_BODY_BACKUP_FAILED

        backup_output = TempfileBufferedFileWriter(
            f"{Facts.backup_dir}/raws/"
            f"network_backup.{Facts.start_epoch}.txt"
        )
        Facts.net_backup_output = backup_output.path
        self._logger.info(
            f"Going to perform network configuration backup; "
            f"output: {backup_output.path}"
        )
        procs = Servers.run_cmd(
            get_script(
                "network_backup",
                libs_names=["_shared_network"],
                no_shared=True
            ),
            to_fd=backup_output,
            ignore_err=True,
            parallel=True
        )
        failed_servers = [
            server for server, proc in procs.items()
            if proc.returncode != 0
        ]
        if not failed_servers:
            self._logger.info("Backup is successfully finished")
            Facts.net_backup_collected = True
            return
        self._logger.error(
            f"Network configuration backup failed on some servers:\n"
            f"{indent_strs(NETWORK_EMAIL_BODY_BACKUP_FAILED)}"
        )
        Facts.net_backup_collected = False
        ReturnCode.set(1)

