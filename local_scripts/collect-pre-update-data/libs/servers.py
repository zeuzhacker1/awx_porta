# collect-pre-update-data PortaSwitch installation servers access objects


import logging
import os
import threading

from libs.common import (get_script, PopenWrapper,
                         TempfileBufferedFileWriter,
                         ParanoidThreadPoolExecutor)
from libs.defaults import TMP_DIR, RSH_WRAPPER, PI_APPBIN
from libs.format import ServerReport, dump_object_oneline_reference
from libs.heartbeat import ServerRunCmdEveryHook, HeartbeatManager
from libs.objects import threadsafemethod
from libs.runtime import get_my_tid


def run_cmd_on_iter(
    servers,
    script,
    args=None,
    to_fd=None,
    raise_exc=True,
    ignore_err=False,
    timeout=None,
    hook=None,
    notify_id=None,
    parallel=False,
    max_workers=None
):
    """Run script on specified servers

    Parameters:
        :servers (list of Servers): Where to execute command.
        :script (str): Bash script to execute.
        :args (None|list of str): Extra args for the script.
        :to_fd (None|str|TextIOBase): Save output to file or buffer.
        :raise_exc (bool): Raise if any script returns non-zero.
        :ignore_err (bool): If False, log output on failure.
        :hook (HeartbeatHook|None): Event hook to use or None.
            Provided hook should be compatible with
            ServerRunCmdEveryHook placeholders.
        :notify_id (str): Event hook ID to use for
            HeartbeatManager.notify() call. Updated event should
            expect %(server)s name placeholder.
        :parallel (bool): Perform operation in async using threads.
        :max_workers (int|None): Maximum number of concurrent workers
            or half of available CPUs.

    Returns:
        :dict of Server and PopenWrapper: Process objects.
    """
    def _notify(server):
        if not notify_id:
            return
        HeartbeatManager.notify(
            notify_id, {"server": server.name}, altid=tid
        )
    def _push_cmd_to_server(server):
        if fd:
            fd.write(f"\n--- {server.name} {server.ip} ---\n\n")
            fd.flush()
        procs[server] = server.run_cmd(
            script,
            args=args,
            to_fd=to_fd,
            raise_exc=raise_exc,
            ignore_err=ignore_err,
            timeout=timeout,
            hook=hook
        )
    def _push_cmd_to_server_with_flush(server):
        try:
            _push_cmd_to_server(server)
        finally:
            if isinstance(fd, TempfileBufferedFileWriter):
                fd.flush_to_file()
            _notify(server)

    tid = None
    procs = {}
    fd = None
    if to_fd:
        fd = (
            open(to_fd, "a", encoding="utf-8")
            if isinstance(to_fd, str) else to_fd
        )
    if parallel:
        tid = get_my_tid()
        with ParanoidThreadPoolExecutor(
            max_workers=(max_workers or int((os.cpu_count() or 8) / 2))
        ) as pool:
            for server in servers:
                pool.submit(_push_cmd_to_server_with_flush, server)
            for future in pool.iter_completed():
                future.result()
    else:
        for server in servers:
            _push_cmd_to_server(server)
            _notify(server)

    if fd and isinstance(to_fd, str):
        fd.close()
    return procs


class Server:
    """Unique server record representation"""

    #: logging.Logger: Child logger.
    _logger = logging.getLogger("server")

    def __init__(self, name, ip, is_known=False):
        """Initializer

        Parameters:
            :name (str): Server name.
            :ip (str): Server IP.
            :is_known (bool): If True then connection allowed.
        """
        self.name = name
        self.ip = ip
        self._is_known = is_known

    def __repr__(self):
        """Representor for devel"""
        return dump_object_oneline_reference(self)

    def __str__(self):
        """Representor for user"""
        return ServerReport(self)

    def __format__(self, spec):
        """Representor with format"""
        return ServerReport(self, spec=spec)

    @property
    def is_known(self):
        return self._is_known

    def run_cmd(
        self,
        script,
        args=None,
        to_fd=None,
        raise_exc=True,
        ignore_err=False,
        timeout=None,
        hook=None
    ):
        """Run command on a remote server

        _shared.sh and _shared_watchdog.sh will be loaded forcefully.
        So if you using get_script() it makes sense to use no_shared.

        Aborts connection if server is unknown.

        Parameters:
            :script (str): Bash script to execute remotely.
            :args (None|list of str): Extra args for the script.
            :to_fd (None|str|TextIOBase): Save output to file or buffer.
            :raise_exc (bool): Raise if exit code is non-zero.
            :ignore_err (bool): If False, log output on failure.
            :hook (HeartbeatHook|None): Event hook to use or None.
                Provided hook should be compatible with
                ServerRunCmdEveryHook placeholders.

        Returns:
            :PopenWrapper: Process object.
        """
        if not self._is_known:
            self._logger.error(
                f"Attempt to connect to unknown server {self.name} {self.ip}"
            )
            return

        name_params = {
            "name":   self.name,
            "ip":     self.ip,
        }
        desc_params = {
            "name":   self.name,
            "ip":     self.ip,
            "target": to_fd.path if to_fd else "memory",
            "script": (
                script
                if self._logger.getEffectiveLevel() <= logging.DEBUG
                else "<shown only on debug>"
            )
        }
        hook = hook or ServerRunCmdEveryHook

        script = f"{get_script('_shared_watchdog')}\n{script}"
        cmd = [
            RSH_WRAPPER,
            "-o", "ControlMaster=auto",
            "-o", "ControlPersist=no",
            "-o", f"ControlPath={TMP_DIR}/ssh___%C",
            self.ip
        ]
        rcmd = ["bash", "-eo", "pipefail"]

        if args:
            rcmd.append("-s")
            rcmd.extend(args)
        rcmd.append("-")
        cmd.append(" ".join(rcmd))

        with HeartbeatManager.track(
            hook.id, name_params, desc_params
        ) as hooked:
            if not hooked:
                self._logger.debug(
                    f"Going to execute "
                    f"{ServerRunCmdEveryHook.desc(**desc_params)}"
                )
            return PopenWrapper(
                cmd,
                input=script,
                output=to_fd,
                error=to_fd,
                raise_exc=raise_exc,
                ignore_err=ignore_err,
                timeout=timeout
            )


class Servers:
    """Provides global access to installation servers

    Stores known installation server info and allows SSH access.
    """

    #: list of Server: Installation servers.
    _servers = []
    #: threading.RLock: Ensures thread-safe access to servers.
    _lock = threading.RLock()
    #: logging.Logger: Child logger.
    _logger = logging.getLogger("servers")

    @classmethod
    @threadsafemethod
    def add(cls, *args, **kwargs):
        """Safe servers register

        Parameters are the same as for Server object creation.

        Returns:
            :Server: Created server object.
        """
        cls._servers.append(Server(*args, **kwargs))
        return cls._servers[-1]

    @classmethod
    @threadsafemethod
    def get(cls, names=None, ips=None):
        """Safe server list getter

        Parameters:
            :names (list of str|None): Server names to look for.
            :ips (list of str|None): Server IPs to look for.

        Returns:
            :list of Server: Value of _servers.
        """
        if not names and not ips:
            return cls._servers
        return [
            server for server in cls._servers
            if (
                (names and server.name in names)
                or (ips and server.ip in ips)
            )
        ]

    @classmethod
    def get_or_add(cls, name=None, ip=None):
        """Handy shortcut for cls.get or cls.add

        Tries to retrieve a known server. If not found, adds a new one
        as unknown to prohibit connections.

        Parameters:
            :name (str): Optional server name.
            :ip (str): Optional server IP.

        Raises:
            :ValueError: If neither name nor IP is provided.
        """
        if not name and not ip:
            raise ValueError("At least one parameter should be specified")

        known = cls.get(
            names=[name] if name else None,
            ips=[ip] if ip else None
        )

        if not known:
            return cls.add(name, ip, is_known=False)
        if len(known) > 1:
            raise RuntimeError(f"Multiple servers found: {known!r}")
        return known[0]

    @classmethod
    @threadsafemethod
    def update(cls):
        """Fetch and update server list using PI data

        Uses Patches Inventory instead of CFG DB. PI data will be
        compared with check_patches_f output in default mode.
        """
        raw_list = PopenWrapper([PI_APPBIN, "server", "show"]).communicate()[0]
        cls._servers = []
        for line in raw_list.splitlines():
            columns = line.split()
            cls._servers.append(Server(
                columns[0], columns[2], is_known=True
            ))

    @classmethod
    def run_cmd(cls, *args, **kwargs):
        """Run script on all known servers

        Behavior is identical to run_cmd_on_iter().
        """
        servers = cls.get()
        return run_cmd_on_iter(servers, *args, **kwargs)

