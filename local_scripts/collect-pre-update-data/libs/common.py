# collect-pre-update-data auxiliary objects shared between components


import concurrent.futures
import errno
import io
import logging
import os
import pathlib
import re
import signal
import subprocess
import sys
import tempfile
import threading

from libs.defaults import DATA_DIR, TMP_DIR, USER_LEVEL
from libs.heartbeat import PopenWrapperEveryHook, HeartbeatManager
from libs.objects import threadsafemethod
from libs.runtime import get_my_tid, maybe_die, Facts


def add_user_logging():
    """Tweak logging.Logger adding user log level functionality"""
    def user(self, msg, *args, **kwargs):
        if self.isEnabledFor(USER_LEVEL):
            self._log(USER_LEVEL, msg, args, **kwargs)

    setattr(logging, "USER", USER_LEVEL)
    setattr(logging.Logger, "user", user)
    logging.addLevelName(USER_LEVEL, "USER")


def is_there_any_human():
    """Check whether running being connected to a terminal

    Returns:
        :bool: True if so.
    """
    return sys.stdin.isatty() and sys.stdout.isatty()


def prompt(msg, criteria, timeout=None):
    """Retrieve and check user keyboard input

    Parameters:
        :msg (str): Prompt message to show to user.
        :criteria (str): Regex to validate user input.
        :timeout (int|None): Timeout for user input.

    Returns:
        :None: If user input is timed out.
        :str: Valid user input.
    """
    def _handler(signum, frame):
        raise TimeoutError("User input retrieval has timed out")

    signal.signal(signal.SIGALRM, _handler)
    answer = None

    try:
        while True:
            if timeout:
                signal.alarm(timeout)
            answer = input(msg)
            if re.search(criteria, answer):
                break
            print("Wrong input; try again")
    except TimeoutError:
        return None

    return answer

def prompt_bool(msg, timeout=None):
    """Retrieve and check user keyboard [y/n] input

    Parameters are the same as in prompt()

    Returns:
        :None: If user input is timed out.
        :bool: User's answer.
    """
    answer = prompt(msg, "^([Yy]([Ee][Ss])?|[Nn][Oo]?)$", timeout=timeout)
    if not answer: return None
    return True if re.search("^[Yy]([Ee][Ss])?$", answer) else False


def gen_backup_id():
    """Selects new unique backup ID scanning DATA_DIR

    Returns:
        :int: New unique backup ID.
    """
    data_dir = pathlib.Path(DATA_DIR)
    if not data_dir.is_dir(): return 1

    top_found = 0

    for item in data_dir.iterdir():
        if not re.search(r"^backup_[0-9]+$", item.name):
            continue

        found_id = int(item.name.split("_")[1])
        if found_id > top_found: top_found = found_id

    return top_found + 1


def lookup_script(name):
    """Lookup prepared Bash script

    Parameters:
        :name (str): Name of Bash script to lookup in the
            Facts.baseplace without .sh.

    Returns:
        :pathlib.Path: Path to found Bash script.
        :None: If no Bash script found.
    """
    path = pathlib.Path(Facts.baseplace) / f"scripts/{name}.sh"
    return path if path.is_file() else None

def get_script(name, libs_names=None, no_shared=False):
    """Cat prepared Bash script from disk to memory

    Parameters:
        :name (str): Name of Bash script to load from the
            Facts.baseplace without .sh.
        :libs_names (list of str|None): Names of Bash libs to load
            from the Facts.baseplace without .sh.
        :no_shared (bool): Prevents forceful _shared.sh lib load.

    Returns:
        :str: Retrieved compound Bash script to execute.

    Raises:
        :ValueError: If no parameters provided.
    """
    libs_names = libs_names or []
    names_list = libs_names + [name]
    files_list = []

    if not no_shared:
        names_list.insert(0, "_shared")

    for name in names_list:
        files_list.append(lookup_script(name))
        if not files_list[-1]:
            raise FileNotFoundError(
                errno.ENOENT, os.strerror(errno.ENOENT), name
            )

    return "\n".join([file.read_text() for file in files_list])


class PopenWrapper(subprocess.Popen):
    """Tweaked variation of subprocess.Popen

    Simplifies logging, file interaction and adds compatibility fixups.
    """

    #: logging.Logger: Child logger.
    _logger = logging.getLogger("process")

    def __init__(
        self,
        cmd,
        *args,
        wait=True,
        input=None,
        output=None,
        error=None,
        raise_exc=True,
        ignore_err=False,
        timeout=None,
        hook=None,
        **kwargs
    ):
        """Initializer

        All parameters except mentioned are same as subprocess.Popen.

        Parameters:
            :cmd (str|list of str): Command to execute.
            :wait (bool): If False the command is executed in async.
            :input (None|str): Text to pass to STDIN, e.g., Bash script.
            :output (None|str|TextIOWrapper): Opened file descriptor
                to write output or path to file. If None, PIPE is used.
            :error (None|str|TextIOWrapper): Opened file descriptor
                to write output or path to file. If None, PIPE is used.
            :raise_exc (bool): If True and process returned non-zero
                code then RuntimeError exception will be raised.
            :timeout (None|int): Allowed execution seconds, implies
                enabled wait.
            :hook (HeartbeatHook|None): Event hook to use or None.
                Provided hook should be compatible with
                PopenWrapperEveryHook placeholders.

        Attributes:
            :_output_path (str|None): Write destination description.
                Purely informative, don't use in logic.
            :_error_path (str|None): Write destination destination.
                Purely informative, don't use in logic.
            :_cached_stdout (str): See self.communicate().
            :_cached_stderr (str): See self.communicate().
        """
        self._output_path = None
        self._error_path = None
        self._cached_stdout = None
        self._cached_stderr = None
        event = 'failed'

        if isinstance(output, str):
            self._output_path = output
            output = open(output, "a", encoding="utf-8")
        elif isinstance(output, TempfileBufferedFileWriter):
            self._output_path = f"buffer {output.realpath} of {output.path}"

        if isinstance(error, str):
            self._error_path = error
            error = open(error, "a", encoding="utf-8")
        elif isinstance(error, TempfileBufferedFileWriter):
            self._error_path = f"buffer {error.realpath} of {error.path}"

        desc_params = {
            "stdout": self._output_path or "memory",
            "stderr": self._error_path or "memory",
            "cmd":    cmd
        }
        hook = hook or PopenWrapperEveryHook
        is_hookable = HeartbeatManager.is_hookable(hook.id)

        if not wait or not is_hookable:
            self._logger.debug(
                f"Going to execute "
                f"{PopenWrapperEveryHook.desc(**desc_params)}"
            )

        super().__init__(
            cmd,
            *args,
            stdin=subprocess.PIPE,
            stdout=(output or subprocess.PIPE),
            stderr=(error or subprocess.PIPE),
            universal_newlines=True,
            **kwargs
        )
        if input:
            self.stdin.write(input)
            self.stdin.flush()
        if wait:
            if is_hookable:
                HeartbeatManager.hook(hook.id, {"pid": self.pid}, desc_params)
            last_timeout = timeout
            while True:
                try:
                    self.communicate(timeout=1)
                    break
                except subprocess.TimeoutExpired:
                    maybe_die(self._logger)
                    if not timeout:
                        continue
                    if not last_timeout:
                        event = 'timed out'
                        self.kill()
                        break
                    last_timeout = last_timeout - 1
        try:
            if (
                not ignore_err
                and isinstance(self.returncode, int)
                and self.returncode != 0
            ):
                if raise_exc:
                    raise RuntimeError(f"Command {event}:\n{self.dump_result()}")
                self._logger.error(f"Command {event}:\n{self.dump_result()}")
        finally:
            if isinstance(self.returncode, int) and is_hookable:
                HeartbeatManager.unwind()

    def communicate(self, *args, **kwargs):
        """Override ancestor method to tweak it

        Starting from CPython 3.7+ consequent super().communicate() call
        doesn't create any issues and just returns streams. However, in
        older versions it leads to an attempt to interact with already
        closed descriptors.
        """
        if self._cached_stdout or self._cached_stderr:
            return (self._cached_stdout, self._cached_stderr)

        self._cached_stdout, self._cached_stderr = super().communicate(
            *args, **kwargs
        )
        self.stdout = None
        self.stderr = None
        return (self._cached_stdout, self._cached_stderr)

    def dump_result(self):
        """Handy shortcut to dump command execution result

        Returns:
            :str: If log_method is None then returns prepared script.
        """
        stdout, stderr = self.communicate()
        stdout = f"{stdout.strip()}\n" if stdout else ""
        stderr = f"{stderr.strip()}\n" if stderr else ""

        if self._output_path:
            stdout += f"- Actual STDOUT is collected to: {self._output_path}\n"
        if self._error_path:
            stderr += f"- Actual STDERR is collected to: {self._error_path}\n"

        return (
            f"Dumping execution result of: {self.args}:\n"
            f"Return code: {self.returncode}\n"
            f"--- STDOUT ---\n"
            f"{stdout}"
            f"--------------\n"
            f"--- STDERR ---\n"
            f"{stderr}"
            f"--------------"
        )


class TempfileBufferedFileWriter(io.TextIOBase):
    """Thread-safe variation of io.TextIOWrapper using tempfile objects"""

    def __init__(self, path, delete=True, dump_exc_to_path=False):
        """Initializer

        Parameters:
            :path (str): Path to target file.
            :delete (bool): Automatically unlinks all buffers if True.
            :dump_exc_to_path (bool): If True and caught an exception
                during self._write_direct() execution, then it will be
                supressed and dumped to target file instead of raising.

        Attributes:
            :_lock (threading.RLock): Ensures thread-safe flush.
            :_fd (io.TextIOWrapper): Target file descriptor.
            :_dir (tempfile.TemporaryDirectory): Directory for
                pre-thread buffers.
            :_buf_pool (dict of int and tempfile.NamedTemporaryFile):
                Per-thread buffers.
        """
        self._path = path
        self._delete = delete
        self._dump_exc_to_path = dump_exc_to_path
        self._fd = open(self._path, "a+", encoding="utf-8")
        self._lock = threading.RLock()
        self._dir = tempfile.TemporaryDirectory(
            prefix=f"{pathlib.Path(self._path).name}___",
            dir=TMP_DIR
        )
        if not delete:
            self._dir._finalizer.detach()
        self._buf_pool = {}

    @property
    def path(self):
        return self._path

    @property
    def realpath(self):
        return self._get_thread_buf().name

    @property
    def closed(self):
        return self._fd.closed

    @threadsafemethod
    def _get_thread_buf(self):
        """Get buffer of caller thread

        Returns:
            :tempfile.NamedTemporaryFile: Current thread buffer.
        """
        tid = get_my_tid()
        return self._buf_pool.setdefault(
            tid,
            tempfile.NamedTemporaryFile(
                mode="w+",
                encoding="utf-8",
                prefix=f"{tid}___",
                dir=self._dir.name,
                delete=self._delete
            )
        )

    def fileno(self):
        return self._get_thread_buf().file.fileno()

    def _assert_not_closed(self):
        """Check whether target file is closed

        Raises:
            :RuntimeError: If so.
        """
        if self.closed:
            raise RuntimeError("Attempt to write in closed file")

    @threadsafemethod
    def _write_direct(self, data):
        """NOT SAFE bypass to write to target file

        Parameters:
            :data (str|list of str): Data to write.

        Returns:
            :int: Number of written symbols.
        """
        self._assert_not_closed()
        self._fd.seek(0,2)
        res = 0
        try:
            if sys._getframe(1).f_code.co_name == "write_direct":
                res = self._fd.write(data)
            else:
                res = self._fd.writelines(data)
        except Exception as exc:
            if not self._dump_exc_to_path:
                raise
            res = self._fd.write(
                f"\n"
                f"The below exception occurred on attempt to write "
                f"to the file; likely data to write is binary "
                f"and cannot be handled properly; "
                f"please check data source and don't submit this;\n{exc}\n"
            )
        self._fd.flush()
        return res

    def write_direct(self, string):
        """NOT SAFE bypass to write line to target file"""
        return self._write_direct(string)

    def writelines_direct(self, strings):
        """NOT SAFE bypass to write lines to target file"""
        return self._write_direct(strings)

    def _write(self, data):
        """Write data to caller thread buffer

        Parameters:
            :data (str|list of str): Data to write.

        Returns:
            :int: Number of written symbols.
        """
        self._assert_not_closed()
        buf = self._get_thread_buf()
        buf.seek(0,2)
        if sys._getframe(1).f_code.co_name == "write":
            res = buf.write(data)
        else:
            res = buf.writelines(data)
        buf.flush()
        return res

    def write(self, string):
        """Safe ancestor method override"""
        return self._write(string)

    def writelines(self, strings):
        """Safe ancestor method override"""
        return self._write(strings)

    def _flush_to_file(self, buf):
        """Perform write from buffer to target file

        Parameters:
            :buf (tempfile.NamedTemporaryFile): Buffer to flush.
        """
        self._assert_not_closed()
        buf.seek(0)
        self.writelines_direct(buf.file)
        buf.seek(0)
        buf.truncate(0)

    @threadsafemethod
    def flush_to_file(self):
        """Perform write from buffer to target file

        Thread buffer will be discarded!
        """
        buf = self._buf_pool.pop(get_my_tid(), None)
        if buf:
            self._flush_to_file(buf)
            buf.close()

    @threadsafemethod
    def flush_to_file_all(self):
        """Write from all buffers to target file

        All thread buffers will be discarded!
        """
        while self._buf_pool:
            _, buf = self._buf_pool.popitem()
            self._flush_to_file(buf)
            buf.close()

    @threadsafemethod
    def close(self):
        """Flush buffers and close target file"""
        if self.closed: return
        self.flush_to_file_all()
        self._fd.close()


class ParanoidThreadPoolExecutor(concurrent.futures.ThreadPoolExecutor):
    """ThreadPoolExecutor that crashes on the first exception"""

    #: list of cls: All active instances, used to abort all threads.
    _pools = []
    #: threading.RLock: Halts other pools interactions.
    _lock = threading.RLock()

    def __init__(self, *args, **kwargs):
        """Initializer

        Attributes:
            :_all_futures (list of concurrent.futures.Future):
                Pool queued futures.
            :_first_exc (Exception): Will be raised immediately.
            :_lock (threading.RLock): Prevents first captured exceptionS
                overwrite by other failed threads.
        """
        super().__init__(*args, **kwargs)
        self._all_futures = []
        self._first_exc = None
        self._lock = threading.RLock()
        with self.__class__._lock:
            self._pools.append(self)

    def submit(self, task, *args, **kwargs):
        """Ancestor method override

        Parameters:
            :task (callable): Function to execute in a separate thread.
        """
        future = super().submit(task, *args, **kwargs)
        self._all_futures.append(future)
        future.add_done_callback(self._done_callback)
        return future

    def iter_completed(self):
        """Handy wrapper for as_completed futures method"""
        yield from concurrent.futures.as_completed(list(self._all_futures))

    @threadsafemethod
    def cancel_all(self, but=None):
        """Cancel all known futures of the current pool

        Parameters:
            :but (list of concurrent.futures.Future): Future objects to
                omit during canceling.
        """
        for future in self._all_futures:
            if future not in but:
                future.cancel()

    def _done_callback(self, future):
        """Check and preserve first thread exception halting other pools

        Parameters:
            :future (concurrent.futures.Future): Finished future.
        """
        if future.cancelled():
            return
        exc = future.exception()
        if not exc or isinstance(exc, concurrent.futures.CancelledError):
            return
        with self._lock, self.__class__._lock:
            if not self._first_exc:
                self._first_exc = exc
            for pool in self._pools:
                pool.cancel_all(but=[future])

    def __exit__(self, exc_type, exc_obj, exc_tb):
        """Ancestor method override

        Parameters:
            :exc_type (type): Exception class.
            :exc_obj (Exception): Exception instance.
            :exc_tb (traceback): Exception traceback object.
        """
        self.shutdown(wait=False)
        with self.__class__._lock:
            self._pools.remove(self)
        if not exc_type and self._first_exc:
            raise self._first_exc
        return False


class ThreadSafeNamespace:
    """Thread-safe storage for multiple objects

    Automatically creates a separate namespace for each thread who tries
    to set public attributes for this class instance.

    Important that this object does no any automatic cleanup. Each
    thread should be aware of this peculiarity and call self.cleanup()!
    """

    def __init__(self):
        """Initializer

        Attributes:
            :_namespaces (dict of int and dict): Per-thread storage
                for various objects owned by it.
        """
        self._namespaces = {}

    def _assert_name_exists(self, name):
        """Check whether thread has such name in its namespace

        Parameters:
            :name (str): Name of thread's object.

        Raises:
            :AttributeError: If no such.
        """
        tid = get_my_tid()
        if tid not in self._namespaces or name not in self._namespaces[tid]:
            raise AttributeError(f"No such {name} object in {tid}'s namespace")

    def _assert_name_reserved(self, name):
        """Check whether name is reserved by API

        Parameters:
            :name (str): Name of thread's object.

        Raises:
            :AttributeError: If so.
        """
        if name == "cleanup":
            raise AttributeError(
                f"{name} is reserved by {self.__class__.__name__}"
            )

    def __getattribute__(self, name):
        """Ancestor method override

        Reroute public names lookup to current thread namespace.

        Parameters:
            :name (str): Name of thread's object or instance's protected.

        Returns:
            :Any: Resolved object.
        """
        if name == "cleanup" or name.startswith("_"):
            return super().__getattribute__(name)
        self._assert_name_exists(name)
        return self._namespaces[get_my_tid()][name]

    def __setattr__(self, name, value):
        """Ancestor method override

        Reroute public names lookup to current thread namespace.

        Parameters:
            :name (str): Name of thread's object or instance's protected.
            :value (Any): New value for it.
        """
        self._assert_name_reserved(name)
        if name.startswith("_"):
            return super().__setattr__(name, value)
        self._namespaces.setdefault(get_my_tid(), {})[name] = value

    def __delattr__(self, name):
        """Ancestor method override

        Reroute public names lookup to current thread namespace.

        Parameters:
            :name (str): Name of keeper object or instance's protected.
        """
        self._assert_name_reserved(name)
        if name.startswith("_"):
            return super().__delattr__(name)
        self._assert_name_exists(name)
        del(self._namespaces[get_my_tid()][name])

    def cleanup(self):
        """Removes namespace of the current thread"""
        tid = get_my_tid()
        if tid not in self._namespaces:
            return
        self._namespaces.pop(tid)


class SectionedNamespace:
    """Convenient and clear API for objects grouping

    Interact with it like with any other object to access values.
    To switch section you're currently switch pointer attribute.

    NB IT'S THREAD-UNSAFE!
    """

    def __init__(self):
        """Initializer

        Attributes:
            :pointer (Any): Pointer to the current section.
            :_sections (dict of Any and dict): Per-section labeled
                storage for various objects.
        """
        self.pointer = None
        self._sections = {}

    @property
    def _section(self):
        return self._sections.setdefault(self.pointer, {})

    def _assert_name_exists(self, name):
        """Check whether section has such name

        Parameters:
            :name (str): Name to check.

        Raises:
            :AttributeError: If no such.
        """
        if name not in self._section:
            raise AttributeError(f"No such {name} object in section")

    def _assert_name_readonly(self, name):
        """Check whether name is readonly because of API

        Parameters:
            :name (str): Name of section's object.

        Raises:
            :AttributeError: If so.
        """
        if name == "clear":
            raise AttributeError(
                f"{name} is readonly in {self.__class__.__name__}"
            )

    def __getattribute__(self, name):
        """Ancestor method override

        Reroute public names lookup to current section.

        Parameters:
            :name (str): Name of section's object or instance's.

        Returns:
            :Any: Resolved object.
        """
        if name in ("pointer", "clear") or name.startswith("_"):
            return super().__getattribute__(name)
        self._assert_name_exists(name)
        return self._section[name]

    def __setattr__(self, name, value):
        """Ancestor method override

        Reroute public names lookup to current section.

        Parameters:
            :name (str): Name of section's object or instance's.
            :value (Any): New value for it.
        """
        self._assert_name_readonly(name)
        if name == "pointer" or name.startswith("_"):
            return super().__setattr__(name, value)
        self._section[name] = value

    def __delattr__(self, name):
        """Ancestor method override

        Reroute public names lookup to current section.

        Parameters:
            :name (str): Name of section's object or instance's.
        """
        self._assert_name_readonly(name)
        if name == "pointer" or name.startswith("_"):
            return super().__delattr__(name)
        self._assert_name_exists(name)
        del(self._section[name])

    def __bool__(self):
        """Check section emptiness

        Returns:
            :bool: False is so.
        """
        return not not self._section

    def clear(self, *pointers):
        """Removes sections

        Parameters:
            :*pointers (Any): Exact pointers to sections to remove.
                ALL WILL BE REMOVED IF NO ANY!!!
        """
        if not pointers:
            self._sections.clear()
            return
        for pointer in pointers:
            self._sections.pop(pointer)

