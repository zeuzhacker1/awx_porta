# collect-pre-update-data shared runtime objects


import re
import sys
import threading

from libs.format import dump_object_multiline_pairs
from libs.objects import threadsafemethod, MetaThreadSafeKeeper


def get_my_tid():
    """Shortcut to get current thread ID

    Returns:
        :int: ID of current thread.
    """
    return threading.current_thread().ident


def die(msg, logger, code=1, is_exc=False):
    """Thread-shared on-error termination shortcut

    Logs the message, sets global shutdown event.

    Parameters:
        :msg (str): Log message to record on error.
        :logger (logging.Logger): Caller's logger.
        :is_error (bool): In some scenarios, this is more of a warning
            than an error.
        :is_exc (bool): If the issue occurred during exception handling,
            this flag should be set.
    """
    ReturnCode.set(code)
    log_method = logger.error if code > 0 else logger.user
    log_method(msg, exc_info=is_exc)

    ShutdownEvent.set()
    logger.user(
        "Set shutdown event; trying to stop other threads gracefully"
    )

def maybe_die(logger):
    """Handy shortcut for threads to die if main thread did the same

    Parameters:
        :logger (logging.Logger): Child logger from the calling context.
    """
    if ShutdownEvent.is_set():
        logger.warning("Other threads die, it's my turn too")
        sys.exit(ReturnCode.get())


#: threading.Event: Global event shared across threads.
ShutdownEvent = threading.Event()


class Facts(metaclass=MetaThreadSafeKeeper):
    """Runtime suite state facts provider

    Thread-safe storage for values shared across classes and call stacks.
    """

    #: int: Script start Unix timestamp.
    start_epoch = None
    #: str: Path to script baseplace.
    baseplace   = None

    #: str: CSUP ticket number in format "^PortaOne-[0-9]{3,5}$".
    #: Used to send collected data.
    csup_tt = None
    #: str: User-selected execution mode.
    mode    = None

    #: int: Backup ID, either existing or to be created.
    backup_id  = None
    #: str: Backup dir, either existing or to be created.
    backup_dir = None

    #: str: Path to log file.
    log       = None
    #: int: Events reminder interval in seconds.
    heartbeat = None

    #: str: Path to collected/provided check_patches_f output.
    pc_output_path      = None
    #: bool: True if output was successfully collected, otherwise False.
    pc_output_collected = None
    #: bool: True if output was successfully parsed, otherwise False.
    pc_output_parsed    = None

    #TODO: once PI-240 resolved:
    # - Remove these facts and restore normal flow.
    #: str: PI-240 related fact, PI_TMPDIR is overriden.
    pi_tmpdir_path          = None
    #: str: PI-240 related fact, summary is collected with xtrace first.
    pi_xtrace_n_output_path = None

    #: str: Path to collected/provided existing PI summary output.
    pi_output_path      = None
    #: bool: True if output was successfully collected, otherwise False.
    pi_output_collected = None
    #: bool: True if output was successfully parsed, otherwise False.
    pi_output_parsed    = None
    #: bool: True if there are modifications in PI, otherwise False.
    pi_has_mods         = None

    #: str: Path to collected network configuration check output.
    net_check_output = None
    #: bool: True if output was successfully parsed, otherwise False.
    net_check_passed = None

    #: str: Path to collected network configuration backup output.
    net_backup_output    = None
    #: bool: True if output was successfully parsed, otherwise False.
    net_backup_collected = None

    #: str: Path to collected hardware configuration backup output.
    hw_backup_output    = None
    #: bool: True if output was successfully parsed, otherwise False.
    hw_backup_collected = None

    #: str: Path to created compact modifications report.
    mods_compact_output  = None
    #: bool: True if output was successfully parsed, otherwise False.
    mods_compact_created = None

    #: str: Path to created full modifications report.
    mods_full_output  = None
    #: bool: True if output was successfully parsed, otherwise False.
    mods_full_created = None

    #: bool: If True, parsed check_patches_f dump won't be created.
    no_pc_index_dump = None
    #: bool: If True, parsed PI summary dump won't be created.
    no_pi_index_dump = None

    @threadsafemethod
    def __repr__(self):
        """Representor"""
        return dump_object_multiline_pairs(self.__class__)


class ReturnCode:
    """Thread-safe return code accessor"""

    #: int: Exit code to return on exit.
    _code = 0
    #: threading.RLock: Ensures thread-safe access to code.
    _lock = threading.RLock()

    @classmethod
    @threadsafemethod
    def set(cls, code):
        """Safe exit code setter

        Parameters:
            :code (int): New value for the _code attribute.
        """
        if code > 0 and cls._code == 0:
            cls._code = code

    @classmethod
    @threadsafemethod
    def get(cls):
        """Safe exit code getter

        Returns:
            :int: Current _code attribute value.
        """
        return cls._code


class Regex:
    """Runtime compiled regular expressions provider

    To improve performance, regexes are compiled once and shared
    thread-safely across components.
    """

    #: dict of list of str: Compiled regex patterns.
    _regexes = {}
    #: threading.RLock: Ensures thread-safe modifcation.
    _lock = threading.RLock()

    @classmethod
    @threadsafemethod
    def load(cls, name, patterns, no_err=False):
        """Compile and store patterns in memory

        Parameters:
            :name (str): Identifier for accessing compiled patterns.
            :patterns (list or dict of str): Regex patterns to compile.
            :no_err (bool): If True, don't raise if name already exists.

        Raises:
            :RuntimeError: If name already exists.
        """
        if name in cls._regexes:
            if no_err:
                return
            raise ValueError(
                f"Attempt to load already loaded regexes {name}: "
                f"{patterns}"
            )
        if isinstance(patterns, list):
            cls._regexes[name] = [
                re.compile(pattern) for pattern in patterns
            ]
        elif isinstance(patterns, dict):
            cls._regexes[name] = {
                key: re.compile(pattern)
                for key, pattern in patterns.items()
            }
        else:
            raise ValueError(
                f"Unsupported patterns {name} passed: {patterns}"
            )

    @classmethod
    @threadsafemethod
    def unload(cls, name):
        """Remove previously compiled patterns

        Parameters:
            :name (str): Identifier of patterns to remove.

        Raises:
            :RuntimeError: If name does not exist.
        """
        if name not in cls._regexes:
            raise ValueError(
                f"Attempt to unload not loaded regexes {name}"
            )
        cls._regexes.pop(name)

    @classmethod
    def search(cls, name, line, no_err=False):
        """Search using compiled patterns

        Parameters:
            :name (str): Identifier of pattern list to use.
            :line (str): Line to test.
            :no_err (bool): If True, don't raise if name doesn't exists.

        Returns:
            :tuple of str and re.Match: For matched dict-based patterns.
            :tuple of None and re.Match: For matched list-based patterns.
            :tuple of None and None: If no match.

        Raises:
            :RuntimeError: If name does not exist.
        """
        if name not in cls._regexes:
            if no_err:
                return
            raise ValueError(
                f"Attempt to access not loaded regexes {name}"
            )

        if isinstance(cls._regexes[name], list):
            for pattern in cls._regexes[name]:
                capture = pattern.search(line)
                if capture:
                    return (None, capture)
        elif isinstance(cls._regexes[name], dict):
            for key, pattern in cls._regexes[name].items():
                capture = pattern.search(line)
                if capture:
                    return (key, capture)

        return (None, None)

    @classmethod
    def is_it(cls, *args, **kwargs):
        """Check whether matches using compiled patterns

        Parameters are the same as for cls.search().

        Returns:
            :bool: True if matches.
        """
        result = cls.search(*args, **kwargs, no_err=True)
        return True if result and result[1] else False

