# collect-pre-update-data components pulse monitoring and logging


import contextlib
import datetime
import logging
import sys
import threading
import time
import traceback


from libs.defaults import EVENTS_HOOKS_MAP, HEARTBEAT_INTERVAL
from libs.format import dump_object_multiline_pairs
from libs.objects import threadsafemethod, MetaStaticInterface, MetaSingleton
from libs.runtime import get_my_tid, die, Facts, ShutdownEvent


class HeartbeatHook(metaclass=MetaStaticInterface, allow_classmethods=True):
    """Base for static container for event hooks templates and data

    Hooks are used as unified templates for known events registration
    by HeartbeatManager. You should inherit this class, define
    attributes mentioned in contract and later use either
    HeartbeatManager.hook() or even better HeartbeatManager.track().
    """

    #: str: Name used in EVENTS_HOOKS_MAP to check refer to event.
    id = "example_hook_token"
    #: str: Old-style format strings for event name.
    name_template = "some long-running process of %(component)s"
    #: str: Old-style format strings for event description.
    desc_template = "that long-running process does something"
    #: str: Old-style format strings for event notifications.
    #: Optional, but should be clearly specified if so.
    notif_template = "process of %(component) did %(thing) something"

    @classmethod
    def name(cls, **params):
        return cls.name_template % params

    @classmethod
    def desc(cls, **params):
        return cls.desc_template % params

    @classmethod
    def notif(cls, **params):
        return (
            ""
            if not cls.notif_template
            else cls.notif_template % params
        )


class PopenWrapperEveryHook(HeartbeatHook):
    """PopenWrapper-related heartbeat event hook

    Should be used in PopenWrapper.__init__().
    """

    #: str: Contract requirement implementation.
    id = "every_child"
    #: str: Contract requirement implementation.
    name_template = "Child PID %(pid)s"
    #: str: Contract requirement implementation.
    desc_template = (
        "command writing STDOUT to %(stdout)s "
        "and STDERR to %(stderr)s: %(cmd)s"
    )
    #: str: Contract requirement implementation.
    notif_template = None

class ServerRunCmdEveryHook(HeartbeatHook):
    """Servers-related heartbeat event hook

    Should be used in Server.run_cmd().
    """

    #: str: Contract requirement implementation.
    id = "every_server_cmd"
    #: str: Contract requirement implementation.
    name_template = "Script on %(name)s %(ip)s host"
    #: str: Contract requirement implementation.
    desc_template = (
        "script on remote %(name)s %(ip)s host "
        "collecting data to local %(target)s:\n%(script)s"
    )
    #: str: Contract requirement implementation.
    notif_template = None

class SubmodeGeneralHook(HeartbeatHook):
    """PopenWrapper-related heartbeat event hook

    Should be used in PopenWrapper.__init__().
    """

    #: str: Contract requirement implementation.
    id = "submode_general"
    #: str: Contract requirement implementation.
    name_template = "%(name)smode"
    #: str: Contract requirement implementation.
    desc_template = "%(desc)s"
    #: str: Contract requirement implementation.
    notif_template = "%(name)s submode is finished"

class ModsReporterDetailsCollectionHook(HeartbeatHook):
    """ModsReporter-related heartbeat event hook

    Should be used in ModsReporter._run_cmd_on_pcm_affected_for_report().
    """

    #: str: Contract requirement implementation.
    id = "report_details_collection"
    #: str: Contract requirement implementation.
    name_template = "Mod ID #%(id)s details remote collection"
    #: str: Contract requirement implementation.
    desc_template = (
        "modification detailed infomation is being collected from the below "
        "mentioned remote hosts to %(target)s using script:\n"
        "- hosts:\n%(servers)s\n- script:\n%(script)s"
    )
    #: str: Contract requirement implementation.
    notif_template = "modification info collection finished on %(server)s"

class PCModsParserRPMsResolvingHook(HeartbeatHook):
    """PCModsParser-related heartbeat event hook

    Should be used in PCModsParser._resolve_files_rpms().
    """

    #: str: Contract requirement implementation.
    id = "pc_owner_rpms_resolution"
    #: str: Contract requirement implementation.
    name_template = "PC parsed files owner RPMs resolving"
    #: str: Contract requirement implementation.
    desc_template = (
        "RPM owners of parsed files are being resolved on the below mentioned "
        "remote hosts saving data to memory\n%(servers)s"
    )
    #: str: Contract requirement implementation.
    notif_template = "unknown RPMs resolving finished on %(server)s"

class ModsReporterPCModsProcessingHook(HeartbeatHook):
    """ModsReporter-related heartbeat event hook

    Should be used in ModsReporter.analyze_pc_mods().
    """

    #: str: Contract requirement implementation.
    id = "report_pcms_processing"
    #: str: Contract requirement implementation.
    name_template = "PC mods report creation"
    #: str: Contract requirement implementation.
    desc_template = (
        "%(amount)s affected mods found in PC check_patches_f are being "
        "compared to modifications found in PI summary"
    )
    #: str: Contract requirement implementation.
    notif_template = "PCMod ID #{%(id)s} processed"

class PIModsParserOutputCollectionHook(HeartbeatHook):
    """PIModsParser-related heartbeat event hook

    Should be used in PIModsParser.collect_output().
    """

    #: str: Contract requirement implementation.
    id = "pi_output_collection"
    #: str: Contract requirement implementation.
    name_template = "PI output collection PID %(pid)s"
    #: str: Contract requirement implementation.
    desc_template = (
        "PI summary is being collected locally to %(stdout)s file"
    )
    #: str: Contract requirement implementation.
    notif_template = None

class PCModsParserOutputCollectionHook(HeartbeatHook):
    """PCModsParser-related heartbeat event hook

    Should be used in PCModsParser.collect_output().
    """

    #: str: Contract requirement implementation.
    id = "pc_output_collection"
    #: str: Contract requirement implementation.
    name_template = "PC output remote collection"
    #: str: Contract requirement implementation.
    desc_template = (
        "check_patches_f is being collected from the below mentioned "
        "remote hosts to local %(target)s\n%(servers)s"
    )
    #: str: Contract requirement implementation.
    notif_template = "check_patches_f collection finished on %(server)s"


class HeartbeatEvent:
    """Monitored long-running event representation

    This class is used by HeartbeatManager to store information about
    long-running events such as PC check_patches_f collection.
    While those events are present in manager, HeartbeatWatchdog
    sees them and notify user from time to time.
    """

    def __init__(
        self,
        id,
        name,
        desc,
        hook=None,
        quiet=False,
        notif_template=None,
        goal=None
    ):
        """Initializer

        Parameters:
            :id (str): Event hook id.
            :name (str): Name of the long-running event.
            :desc (str): Human readable description.
            :hook (HeartbeatHook|None): Inheritor associated with event.
            :quiet (bool): Enables to avoid reporting the event.
            :notif_template (str|bool): Event nofication template.
                Tries to refer to hook if None.
            :goal (int|float|None): Number of something that should be
                achieved within the event to finish it.

        Attributes:
            :_origin (int): TID where event is occuring.
            :_started (float): Epoch when event was registered.
            :_finished (float|None): Epoch when event was finished.
            :_status (int): Goal achievement progress.
        """
        self._id = id
        self._name = name
        self._desc = desc
        self._origin = get_my_tid()

        self._hook = hook
        self._quiet = quiet
        self._started = time.time()
        self._finished = None

        self._notif_template = notif_template

        self._goal = goal
        self._status = None if goal is None else 0

    def __repr__(self):
        """Representor for devel"""
        return dump_object_multiline_pairs(self)

    @property
    def id(self):
        return self._id

    @property
    def name(self):
        return self._name

    @property
    def desc(self):
        return self._desc

    @property
    def hook(self):
        return self._hook

    @property
    def origin(self):
        return self._origin

    @property
    def quiet(self):
        return self._quiet

    @property
    def started(self):
        return self._started

    @property
    def finished(self):
        return (
            self._finished
            if self._finished is not None
            else self._goal is not None and self._status == self._goal
        )

    @property
    def goal(self):
        return self._goal

    @property
    def status(self):
        return self._status

    def finish(self):
        if self._finished is None:
            self._finished = time.time()

    def progress(self):
        if self._goal is not None:
            self._status += 1

    def notif(self, **params):
        if self._notif_template:
            return self._notif_template % params
        if self._hook:
            return self._hook.notif(**params)


class HeartbeatManager:
    """Shared endpoint for components long-running events management

    Provides thread-safe storage for registered events in form of
    stacks per each thread. Use predefined event hook subclassed
    from HeartbeatHook with cls.track() method in most cases.
    """

    #: dict of int and list of HeartbeatEvent: Registered events
    #: that are currently occuring in different threads.
    _events_stacks = {}
    #: threading.RLock: Ensures thread-safe access to monitors.
    _lock = threading.RLock()
    #: logging.Logger: Child logger.
    _logger = logging.getLogger("events")

    @classmethod
    def push(
        cls,
        id,
        name,
        desc,
        hook=None,
        quiet=False,
        notif_template=None,
        goal=None
    ):
        """Adds HeartbeatEvent to thread events stack

        Parameters:
            :id (str): Event hook id.
            :name (str): Name of the long-running event.
            :desc (str): Human readable description.
            :hook (HeartbeatHook|None): Inheritor associated with event.
            :quiet (bool): Enables to avoid reporting the event.
            :notif_template (str|bool): Event nofication template.
                Tries to refer to hook if None.
            :goal (int|float|None): Number of something that should be
                achieved within the event to finish it.

        Raises:
            :RuntimeError: If event is already registered.
        """
        def _push():
            if not quiet:
                cls._logger.info(
                    f"{name} event started: {desc}"
                )
            return HeartbeatEvent(
                id, name, desc,
                hook=hook, quiet=quiet,
                notif_template=notif_template, goal=goal
            )

        tid = get_my_tid()

        if tid not in cls._events_stacks:
            cls._events_stacks[tid] = [_push()]
            return
        for event in cls._events_stacks[tid]:
            if event.name == name:
                raise RuntimeError(
                    f"Attempt to register already registered event {name} "
                    f"within the same {tid} thread"
                )
        cls._events_stacks[tid].append(_push())

    @classmethod
    def is_hookable(cls, name):
        """Check whether event hook is enabled

        Parameters
            :name (str): Name of the event hook.

        Returns:
            :bool: True if enabled.
        """
        return not not EVENTS_HOOKS_MAP.get(name, None)

    @classmethod
    def hook(cls, id, name_params, desc_params, goal=None):
        """Shortcut to stack event only if hook is active

        Parameters:
            :id (str): Means HeartbeatHook.id of inheritor.
            :name_params (dict of str): Parameters for template.
            :desc_params (dict of str): Parameters for template.
            :goal (int|float|None): Number of something that should be
                achieved within the event to finish it.

        Returns:
            :str: Name of the registered event.
            :None: If no events registered.
        """
        if cls.is_hookable(id):
            hook = None
            try:
                hook = globals()[EVENTS_HOOKS_MAP[id]]
                if not issubclass(hook, HeartbeatHook):
                    raise TypeError()
            except Exception:
                raise RuntimeError(f"Cannot properly resolve {id} hook")
            event_name = hook.name(**name_params)
            cls.push(
                hook.id,
                event_name,
                hook.desc(**desc_params),
                hook=hook,
                goal=goal
            )
            return event_name

    @classmethod
    @contextlib.contextmanager
    def track(cls, id, name_params, desc_params, goal=None, unwind_params=None):
        """Combination of context manager and cls.hook()

        Parameters are the same as for the mentioned method except
        the below mentioned implemented by this method.

        If unwind_params are specified then method forcefully unwinds
        events stack on context manager exit using those parameters
        and ignoring usual workflow.

        Parameters:
            :unwind_params (dict|None): Alternative parameters to pass
                to cls.unwind(), e.g., forcefully remove upper events.

        Yields:
            :str: Name of the registered event.
        """
        hooked_event_name = None
        try:
            hooked_event_name = cls.hook(id, name_params, desc_params, goal=goal)
            yield hooked_event_name
        finally:
            if hooked_event_name:
                cls.unwind(**unwind_params or {})

    @classmethod
    def event(cls, altid=None):
        """Get current event of thread from stack

        Parameters:
            :altid (int): Alternative thread ID.

        Returns:
            :None: If no currently running event.
            :HeartbeatEvent: Found currently running top event.
        """
        tid = altid or get_my_tid()
        return (
            None
            if (
                tid not in cls._events_stacks
                or not cls._events_stacks[tid]
            )
            else cls._events_stacks[tid][-1]
        )

    @classmethod
    @threadsafemethod
    def stacks(cls):
        """Retrieve copy of registered thread events stacks

        Returns:
            :dict of int and tuple of tuples of HeartbeatEvent and []:
                Component long-running events per TID.
            :dict of int and tuple of tuples of HeartbeatEvent:
                Component long-running events per TID.
        """
        return {
            tid: tuple(events)
            for tid, events in cls._events_stacks.items()
        }

    @classmethod
    def notify(cls, id, notif_params, altid=None, no_progress=False):
        """Notify about ongoing event progress

        Parameters:
            :id (str): Event hook id to notify progress about.
            :notif_params (dict of str): Parameters for template.
            :altid (int|None): Alternative thread ID.
            :no_progress (bool): Don't increase event progressbar.
        """
        tid = altid or get_my_tid()
        if not cls.event(altid=tid):
            return
        for event in reversed(cls._events_stacks[tid]):
            if event.id != id:
                continue
            notif = event.notif(**notif_params)
            if notif:
                cls._logger.info(f"{event.name} event updated: {notif}")
                if not no_progress:
                    event.progress()

    @classmethod
    def pop(cls, quiet=False, no_err=False):
        """Pops event from thread stack

        Parameters:
            :quiet (bool): Performs removal quietly.
            :no_err (bool): If True don't raise if thread has no events.

        Raises:
            :RuntimeError: If the thread even doesn't have any events.
        """
        tid = get_my_tid()
        if not cls.event():
            if no_err:
                return
            raise RuntimeError(
                f"Attempt to register event finish for {tid} thread "
                f"who has no any registered events"
            )
        event = cls._events_stacks[tid].pop()
        event.finish()
        if not quiet and not event.quiet:
            cls._logger.info(f"{event.name} event finished")

    @classmethod
    def unwind(cls, depth=1, quiet=False, no_err=False):
        """Pops several events from thread stack

        Parameters:
            :depth (int): Forces stack unwind if positive value.
                Unwinds the whole stack in case of negative value.
            :quiet (bool): Performs removal quietly.
            :no_err (bool): If True don't raise if thread has no events.
        """
        tid = get_my_tid()
        if not depth:
            raise ValueError(
                f"Unwind depth should be either positive or negative integer"
            )
        if not cls.event():
            if no_err:
                return
            raise RuntimeError(
                f"Attempt to register event finish for {tid} thread "
                f"who has no any registered events"
            )
        while depth and cls._events_stacks[tid]:
            cls.pop(quiet=quiet, no_err=no_err)
            depth -= 1


class HeartbeatWatchdog(threading.Thread, metaclass=MetaSingleton):
    """Standalone long-running events monitor and threads exposer

    Periodically reminds user in log about ongoing activities registered
    via HeartbeatManager utility class.
    """

    #: threading.RLock: Ensures no simultaneous executions.
    _lock = threading.RLock()

    def __init__(self):
        """Initializer"""
        super().__init__(daemon=True, name=self.__class__.__name__)
        self._logger = logging.getLogger("heartbeat")

    @threadsafemethod
    def run(self):
        """Used by threading.Thread.start() call

        Here's a simple workaround to crash the service on an unhandled
        thread exception. Also triggers other threads monitoring in case
        if stop event was triggered.
        """
        try:
            self.main()
        except Exception:
            die("Unhandled exception occurred:", self._logger, is_exc=True)
        finally:
            self._expose_everyone()

    @threadsafemethod
    def main(self):
        """Main instance method in the thread

        Enter the main loop until the stop event is triggered.
        Does so even if heartbeat is disabled to trigger introspection
        loop in an appropriate time when other threads are stopping.
        """
        if Facts.heartbeat < 1:
            ShutdownEvent.wait()
            return
        while not ShutdownEvent.wait(Facts.heartbeat):
            events_stacks = HeartbeatManager.stacks()
            if not events_stacks:
                self._logger.debug("No stale events to report")
                continue
            self._remind_events(events_stacks)

    def _remind_events(self, events_stacks):
        """Iterates over provided heartbeat events

        Parameters:
            :event_stacks (dict of int and tuple of HeartbeatEvent):
                Copy from the HeartbeatManager.
        """
        for tid, events in events_stacks.items():
            self._logger.debug(f"Checking stale events of {tid} thread")
            for event in events:
                if event.quiet:
                    continue
                event_started_iso = datetime.datetime.fromtimestamp(
                    event.started
                ).time().isoformat()
                if event.finished:
                    self._logger.warning(
                        f"The {event.name} event of {tid} thread is finished "
                        f"but for some reason remain registered; why?"
                    )
                    continue
                self._logger.info(
                    f"The {event.name} event of {tid} thread is running since "
                    f"{event_started_iso[:-3]}: {event.desc}"
                )

    def _expose_everyone(self):
        """Expose in log every alive thread who holds suite termination

        Might be a bit too verbosive since dumps stack trace of each
        observed thread except self.
        """
        def _refresh_frames():
            current_frames.clear()
            current_frames.update(sys._current_frames())
        def _is_there_any_frames_except_self():
            return len(current_frames.keys()) > 1

        self_tid = get_my_tid()
        current_frames = {}
        _refresh_frames()

        while _is_there_any_frames_except_self():
            time_before_heartbeat = Facts.heartbeat or HEARTBEAT_INTERVAL
            while time_before_heartbeat:
                time_before_heartbeat -= 1
                time.sleep(1)
            _refresh_frames()
            if not _is_there_any_frames_except_self():
                break
            for tid, frame in current_frames.items():
                if tid != self_tid:
                    self._logger.user(
                        f"The {tid} thread holds us from dying:\n"
                        f"{''.join(traceback.format_stack(frame))}"
                    )

