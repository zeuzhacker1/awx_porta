# collect-pre-update-data hardware configuration related objects


import logging
import threading

from libs.common import get_script, TempfileBufferedFileWriter
from libs.format import indent_strs
from libs.objects import threadsafemethod, MetaSingleton
from libs.runtime import Facts, ReturnCode
from libs.servers import Servers


class HardwareProcessor(metaclass=MetaSingleton):
    """Backup hardware configuration information"""

    #: threading.RLock: Ensures no simultaneous executions.
    _lock = threading.RLock()

    def __init__(self):
        """Initializer

        Attributes:
            :_logger (logging.Logger): Child logger.
        """
        self._logger = logging.getLogger("hardware")

    @threadsafemethod
    def main(self):
        """Initiates hardware configuration backup on remote servers"""
        from modes.hardware import HARDWARE_EMAIL_BODY_BACKUP_FAILED

        backup_output = TempfileBufferedFileWriter(
            f"{Facts.backup_dir}/raws/"
            f"hardware_backup.{Facts.start_epoch}.txt"
        )
        Facts.hw_backup_output = backup_output.path
        self._logger.info(
            f"Going to collect hardware configuration info to: "
            f"{backup_output.path}"
        )
        procs = Servers.run_cmd(
            get_script("hardware_backup", no_shared=True),
            to_fd=backup_output,
            ignore_err=True,
            parallel=True
        )
        failed_servers = [
            server for server, proc in procs.items()
            if proc.returncode != 0
        ]
        if not failed_servers:
            self._logger.info("Collection is successfully finished")
            Facts.hw_backup_collected = True
            return
        self._logger.error(
            f"Hardware backup failed on some servers:\n"
            f"{indent_strs(HARDWARE_EMAIL_BODY_BACKUP_FAILED)}"
        )
        Facts.hw_backup_collected = False
        ReturnCode.set(1)

