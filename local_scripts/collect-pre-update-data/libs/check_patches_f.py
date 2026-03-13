# collect-pre-update-data PCUP check_patches_f related objects


import enum
import logging
import os
import threading

from libs.common import (get_script, maybe_die,
                         TempfileBufferedFileWriter,
                         ParanoidThreadPoolExecutor)
from libs.format import (multiline_list, indent_strs,
                         dump_object_multiline_pairs,
                         InstalledRPMReport)
from libs.objects import threadsafemethod, MetaSingleton
from libs.heartbeat import (PCModsParserRPMsResolvingHook,
                            PCModsParserOutputCollectionHook,
                            HeartbeatManager)
from libs.runtime import get_my_tid, Facts, Regex, ReturnCode
from libs.mods_generic import (UnexpectedInput, Resolution,
                               AtomicModification, ModifiedFile,
                               ComplexModification, ModsProvider)
from libs.servers import Servers


class ModifiedOSFilePC(ModifiedFile):
    """Modified OS file representation

    Represents a particular file detected by check_patches_f in OS
    directories such as /etc, /usr, or /var. Since these files aren't
    controlled by PI, there's no comprehensive historical data about
    them, and most should be reviewed by SE.
    """

class ModifiedRepoFilePC(ModifiedFile):
    """Modified repository file representation

    Represents a particular file detected by check_patches_f in package
    repositories like /home/porta-admin or /home/porta-configurator,
    i.e., directories with a Git repo initialized during RPM build and
    most likely controlled by Patches Inventory. However, some files
    may not be controlled, and this is expected.
    """

class TTLocalFilePC(ModifiedFile):
    """Created .tt.local file representation

    PortaConfigurator uses the Template Toolkit engine and stores
    templates as separate files with the .tt extension. We can override
    these files by creating a .tt.local version without modifying the
    original. Such files should be treated differently.
    """

class InstalledRPM(AtomicModification):
    """Installed RPM representation

    Represents an RPM detected by check_patches_f that is not expected
    to be installed on the server, according to Oracle and PortaOne
    default RPM groups.
    """

    def __init__(self, name, *args, **kwargs):
        """Initializer

        Parameters:
            :name (str): RPM name without version.
        """
        super().__init__(*args, **kwargs)
        self.name = name

    def __str__(self):
        """Representor for user"""
        return InstalledRPMReport(self)

    def __format__(self, spec):
        """Representor with format"""
        return InstalledRPMReport(self, spec=spec)

    def identify(self):
        """Abstract method implementation"""
        return ("name", self.name)

    def tokenize(self):
        """Abstract method implementation"""
        tokens = [part[0] for part in self.identify()[1].split("-")]
        return tuple(tokens)


class PCMod(ComplexModification):
    """check_patches_f modification complex representation

    Represents a modification from check_patches_f output. Used by the
    mods provider to provide unified access to different modification types.
    """


class PCModsProvider(ModsProvider):
    """Provides global access to parsed check_patches_f modifications"""

    #: list of IndexNode: Indexed storage. Creating a separate list here
    #: to avoid ancestor's list usage between inheritors.
    _cmods_index = []

    @staticmethod
    def gen_amod_lookup_attrs(amod, *args, **kwargs):
        """Abstract method implementation"""
        attr, value = amod.identify()
        return {f"amod.{attr}": [value]}

    @staticmethod
    def gen_cmod_object(amod, servers, *args, **kwargs):
        """Abstract method implementation"""
        return PCMod(amod, servers)

    @staticmethod
    def mutate_mod_for_insert(servers, amod, *args, **kwargs):
        """Abstract method implementation"""
        return PCModsProvider.gen_cmod_object(amod, servers)

    @staticmethod
    def mutate_mod_for_update(servers, pcm, *args, **kwargs):
        """Abstract method implementation"""
        if set(servers).intersection(set(pcm.servers)):
            return
        pcm.servers.extend(servers)
        return pcm

    @staticmethod
    def gen_dump_path():
        """Abstract method implementation"""
        return (
            f"{Facts.backup_dir}/raws/"
            f"check_patches_f.parsed.{Facts.start_epoch}.txt"
        )


class PCModsParserState(enum.IntEnum):
    """Currently parsed check_patches_f output position map"""

    #: int: Usually the first line of check_patches_f output.
    NO_DATA = enum.auto()
    #: int: New server header line.
    NEW_SERVER = enum.auto()
    #: int: Section switch or state transition.
    IN_TRANSIT = enum.auto()
    #: int: "Modified /etc files:" section, parsing /etc files.
    MODIFIED_ETC_FILES = enum.auto()
    #: int: "Modified files" section, parsing RPM file checks.
    MODIFIED_RPM_FILES = enum.auto()
    #: int: New RPM name header line in "Modified files" section.
    NEW_MODIFIED_RPM = enum.auto()
    #: int: Found unsatisfied dependencies for RPM name.
    UNSATISFIED_DEPS_FOR = enum.auto()
    #: int: Inside RPM-specific modified files list.
    CURRENT_MODIFIED_RPM_FILES = enum.auto()
    #: int: "Check installed rpms:" section, debug output.
    CHECK_INSTALLED_RPMS_FLOOD = enum.auto()
    #: int: RPMs listed in custom-delete group.
    CHECK_INSTALLED_RPMS_CUSTOM_DELETE = enum.auto()
    #: int: RPMs listed as "Shouldn't be installed:".
    CHECK_INSTALLED_RPMS_DONT_INSTALL = enum.auto()
    #: int: Entered "tt.local config files:" section.
    TT_LOCAL_FILES = enum.auto()
    #: int: Faced "Custom httpd conf file was found:" message.
    CUSTOM_HTTPD_CONFIGS = enum.auto()
    #: int: Diffs and backups generated by check_patches_f.
    ARCHIVES_PATHS = enum.auto()


class PCModsParser(metaclass=MetaSingleton):
    """Maintains check_patches_f output parsing

    The parser uses PCModsParserState to determine the context
    and required actions for each check_patches_f line. Parsed
    data is stored in PCModsProvider.

    If you plan to modify the parser, consider the following:
    - CHECK_PATCHES_F_REGEX_MAP from defaults is used for regex
      matching; keys correspond to _process_capture_{key} methods.
    - Each _process_capture_* method depends on the current state.
    - Line handling logic is implemented in _process_capture_* methods.
    """

    #: threading.RLock: Ensures no simultaneous executions.
    _lock = threading.RLock()

    def __init__(self):
        """Initializer

        Attributes:
            :_logger (logging.Logger): Child logger.
            :_prev_state (PCModsParserState): Previous processed block.
            :_last_state (PCModsParserState): Last processed block.
            :_line_raw (str): Current check_patches_f line.
            :_line_capture (re.Match): Regex capture result
                for the current line.
            :_capture_type (str): Key from CHECK_PATCHES_F_REGEX_MAP.
            :_current_server (str): Currently parsed server name.
            :_current_rpm (str): Currently parsed RPM name.
        """
        self._logger = logging.getLogger("check_patches_f")
        self._prev_state = PCModsParserState.NO_DATA
        self._last_state = PCModsParserState.NO_DATA
        self._line_raw = None
        self._line_capture = None
        self._capture_type = None
        self._current_server = None
        self._current_rpm = None

    def __repr__(self):
        """Representor"""
        return dump_object_multiline_pairs(self)

    @threadsafemethod
    def main(self, no_parse=False):
        """Start check_patches_f output collection and parsing

        Parameters:
            :no_parse (bool): Skip parsing (CPU-heavy); useful when
                running in threads where GIL blocks execution anyway.
        """
        if not Facts.pc_output_path:
            self._logger.info(
                "Path to check_patches_f output isn't set, "
                "going to collect fresh data"
            )
            if not self.collect_output():
                return
        if not no_parse:
            self.parse_output()

    @threadsafemethod
    def collect_output(self):
        """Collect check_patches_f output on remote servers

        Wraps protected method with thread lock and heartbeat hook.

        Returns:
            :bool: False if collection failed on any of remote servers.
        """
        pc_output = TempfileBufferedFileWriter(
            f"{Facts.backup_dir}/raws/"
            f"check_patches_f.collected.{Facts.start_epoch}.txt"
        )
        Facts.pc_output_path = pc_output.path

        desc_params = {
            "servers": multiline_list(Servers.get()),
            "target":  pc_output.path
        }
        with HeartbeatManager.track(
            PCModsParserOutputCollectionHook.id, {}, desc_params,
            goal=len(Servers.get())
        ) as hooked:
            return self._collect_output(pc_output, hooked, desc_params)

    def _collect_output(self, pc_output, hooked, desc_params):
        """Collect check_patches_f output on remote servers

        Parameters:
            :pc_output (TempfileBufferedFileWriter): Path for output.
            :hooked (str|None): Registered heartbeat event name if any.
            :desc_params (dict of str): Parameters
                for PCModsParserOutputCollectionHook.desc method.

        Returns:
            :bool: False if collection failed on any of remote servers.
        """
        from modes.check_patches_f import (
            CHECK_PATCHES_F_EMAIL_BODY_COLLECTION_FAILED
        )
        if not hooked:
            self._logger.info(
                f"Start of {PCModsParserOutputCollectionHook.desc(**desc_params)}"
            )
            self._logger.warning(
                "Note that this might take some time, PC check_patches_f is slow"
            )
        procs = Servers.run_cmd(
            get_script("check_patches_f", no_shared=True),
            to_fd=pc_output,
            timeout=3600,
            ignore_err=True,
            notify_id=PCModsParserOutputCollectionHook.id,
            parallel=True,
            max_workers=7
        )
        failed_servers = [
            server for server, proc in procs.items()
            if proc.returncode != 0
        ]
        if not failed_servers:
            if not hooked:
                self._logger.info("Collection is successfully finished")
            Facts.pc_output_collected = True
            return True
        self._logger.error(
            f"PC check_patches_f collection failed on some servers:\n"
            f"{indent_strs(CHECK_PATCHES_F_EMAIL_BODY_COLLECTION_FAILED)}"
        )
        Facts.pc_output_collected = False
        ReturnCode.set(1)
        return False

    @threadsafemethod
    def parse_output(self, pc_output=None):
        """Parse collected check_patches_f output

        Parameters:
            :pc_output (str|None): check_patches_f path override.
        """
        from modes.check_patches_f import (
            CHECK_PATCHES_F_EMAIL_BODY_PARSING_FAILED
        )
        pc_output = pc_output or Facts.pc_output_path
        pc_output_fd = open(pc_output, "r", encoding="utf-8")
        self._logger.info(
            f"Starting check_patches_f output parsing: {pc_output}"
        )

        try:
            for line in pc_output_fd:
                maybe_die(self._logger)

                self._line_raw = line.strip("\n")
                self._line_capture = None
                self._capture_type = None

                self._logger.debug(f"Got raw line:\n{self._line_raw}")
                self._get_capture()

                if self._capture_type:
                    self._exec_capture_processor()
        except UnexpectedInput:
            self._logger.error(
                f"PC check_patches_f parsing failed:\n"
                f"{indent_strs(CHECK_PATCHES_F_EMAIL_BODY_PARSING_FAILED)}\n\n",
                exc_info=True
            )
            Facts.pc_output_parsed = False
            pc_output_fd.close()
            return

        pc_output_fd.close()

        self._resolve_files_rpms()

        self._logger.info(
            f"Finished check_patches_f output parsing: {pc_output}"
        )
        Facts.pc_output_parsed = True

    def _get_capture(self):
        """Try to match the line to any of the default regexes

        Regular expressions from CHECK_PATCHES_F_REGEX_MAP will be
        compared to the currently parsed line and matches will be captured.

        Raises:
            :RuntimeError: If no currently retrieved line in parser.
        """
        if self._line_raw is None:
            raise RuntimeError(
                "No retrieved check_patches_f line found; cannot "
                "perform regex match and capture"
            )

        self._capture_type, self._line_capture = Regex.search(
            "CHECK_PATCHES_F_REGEX_MAP", self._line_raw
        )
        if self._line_capture is None:
            self._capture_type = "non_match"
        self._logger.debug(f"Got capture of {self._capture_type}")

    def _exec_capture_processor(self):
        """Switch parser execution according to the last capture type

        Capture types are keys of CHECK_PATCHES_F_REGEX_MAP. They are
        used to identify a corresponding method to process the last match
        according to the current parser state.

        Raises:
            :RuntimeError: If no current capture type in parser.
        """
        if self._capture_type is None:
            raise RuntimeError(
                "Capture type is undefined; cannot select "
                "last capture processing method"
            )
        getattr(self, f"_process_capture_{self._capture_type}")()

    def _process_capture_blank(self):
        """Process captured blank line

        Resets state depending on whether it's a transition between
        servers in check_patches_f or a transition between particular
        blocks of server output.
        """
        if self._last_state is PCModsParserState.ARCHIVES_PATHS:
            self._change_state(PCModsParserState.NO_DATA)
            self._current_server = None
        elif (
            self._last_state is not PCModsParserState.NO_DATA
            and self._last_state is not PCModsParserState.IN_TRANSIT
        ):
            self._change_state(PCModsParserState.IN_TRANSIT)

    def _process_capture_server_header(self):
        """Process captured server header line

        Usually means lines like:
            "----- sip1 192.168.0.107 -----"

        Raises:
            :UnexpectedInput: If it's not the parsing start or it's not
                a change between server blocks.
        """
        if self._last_state is not PCModsParserState.NO_DATA:
            raise UnexpectedInput(f"Got server header in:\n{self}")

        self._change_state(PCModsParserState.NEW_SERVER)
        self._process_server()

    def _process_capture_modified_etc_header(self):
        """Process captured modified /etc header line

        Usually means lines like:
            "Modified /etc config files:"

        Raises:
            :UnexpectedInput: If it's not a transition after the server
                header in the particular server block.
        """
        if (
            self._last_state is not PCModsParserState.IN_TRANSIT
            and self._prev_state is not PCModsParserState.NEW_SERVER
        ):
            raise UnexpectedInput(f"Got modified etc header in:\n{self}")
        self._change_state(PCModsParserState.MODIFIED_ETC_FILES)

    def _process_capture_modified_etc_file(self):
        """Process captured modified /etc file line

        Usually means lines like:
            "  /etc/.updated"

        Raises:
            :UnexpectedInput: If it's not an /etc file path after
                a previous such file or corresponding header.
            :RuntimeError: If no defined current server whose output
                block is being parsed.
        """
        if (
            self._last_state is not PCModsParserState.MODIFIED_ETC_FILES
            and self._prev_state is not PCModsParserState.IN_TRANSIT
        ):
            raise UnexpectedInput(f"Got modified etc file in:\n{self}")
        if self._current_server is None:
            raise RuntimeError(f"Got modified etc file when server is unknown")
        self._process_os_file(self._line_capture.group("path"))

    def _process_capture_modified_rpm_header(self):
        """Process captured modified RPM header line

        Usually means lines like:
            "Modified files:"

        Raises:
            :UnexpectedInput: If it's not a transition after /etc files.
        """
        if (
            self._last_state is not PCModsParserState.IN_TRANSIT
            and self._prev_state is not PCModsParserState.MODIFIED_ETC_FILES
        ):
            raise UnexpectedInput(f"Got modified rpm header in:\n{self}")
        self._change_state(PCModsParserState.MODIFIED_RPM_FILES)

    def _process_capture_modified_rpm_name(self):
        """Process captured modified RPM name line

        Usually means lines like:
            "  porta-configurator-data"

        Raises:
            :UnexpectedInput: If it's not after the modified RPM header
                or a previous RPM file or a unsatisfied dependencies.
        """
        is_not_after_modified_rpm_header = (
            self._last_state is not PCModsParserState.MODIFIED_RPM_FILES
            and self._prev_state is not PCModsParserState.IN_TRANSIT
        )
        is_not_after_prev_rpm_file = (
            self._last_state is not PCModsParserState.CURRENT_MODIFIED_RPM_FILES
            and self._prev_state is not PCModsParserState.NEW_MODIFIED_RPM
            and self._prev_state is not PCModsParserState.UNSATISFIED_DEPS_FOR
        )
        is_not_after_unsatisfied_deps = (
            self._last_state is not PCModsParserState.UNSATISFIED_DEPS_FOR
            and self._prev_state is not PCModsParserState.NEW_MODIFIED_RPM
        )
        if (
            is_not_after_modified_rpm_header
            and is_not_after_prev_rpm_file
            and is_not_after_unsatisfied_deps
        ):
            raise UnexpectedInput(f"Got modified rpm name in:\n{self}")

        self._change_state(PCModsParserState.NEW_MODIFIED_RPM)
        self._current_rpm = self._line_capture.group("name")

    def _process_capture_unsatisfied_deps_header(self):
        """Process captured unsatisfied dependencies header line

        Usually means lines like:
            "      Unsatisfied dependencies for porta-selfcare-115.4-1.20250124.1.el8.noarch:"

        Raises:
            :UnexpectedInput: If received when self._last_state and
                self._prev_state values don't imply that the line is
                after an affected RPM name.
            :RuntimeError: If the current RPM is unknown.
        """
        if (
            self._last_state is not PCModsParserState.NEW_MODIFIED_RPM
            and self._prev_state is not PCModsParserState.CURRENT_MODIFIED_RPM_FILES
            and self._prev_state is not PCModsParserState.MODIFIED_RPM_FILES
        ):
            raise UnexpectedInput(f"Got unsatisfied dependencies in:\n{self}")
        if self._current_rpm is None:
            raise RuntimeError(
                "Got unsatisfied dependencies when RPM is unknown"
            )
        self._change_state(PCModsParserState.UNSATISFIED_DEPS_FOR)

    def _process_capture_modified_rpm_file(self):
        """Process captured modified RPM file line

        Usually means lines like:
            "      SM5..UGT.    /home/porta-configurator/data/options/webcluster.def"
            "      S.5....T.    /usr/libexec/nagios/portaone/gearman.pl"

        Raises:
            :UnexpectedInput: If received when self._last_state and
                self._prev_state values don't imply that the line is
                after a modified RPM name or a previous file of the
                same RPM or unsatisfied dependencies of the current.
            :RuntimeError: If the current server or RPM is unknown.
        """
        is_not_after_new_rpm = (
            self._last_state is not PCModsParserState.NEW_MODIFIED_RPM
            and self._prev_state is not PCModsParserState.MODIFIED_RPM_FILES
            and self._prev_state is not PCModsParserState.CURRENT_MODIFIED_RPM_FILES
        )
        is_not_after_prev_file = (
            self._last_state is not PCModsParserState.CURRENT_MODIFIED_RPM_FILES
            and self._prev_state is not PCModsParserState.NEW_MODIFIED_RPM
            and self._prev_state is not PCModsParserState.UNSATISFIED_DEPS_FOR
        )
        is_not_after_unsatisfied_deps = (
            self._last_state is not PCModsParserState.UNSATISFIED_DEPS_FOR
            and self._prev_state is not PCModsParserState.NEW_MODIFIED_RPM
        )
        if (
            is_not_after_new_rpm
            and is_not_after_prev_file
            and is_not_after_unsatisfied_deps
        ):
            raise UnexpectedInput(f"Got modified rpm file in:\n{self}")

        if self._current_server is None:
            raise RuntimeError(f"Got modified rpm file when server is unknown")
        if self._current_rpm  is None:
            raise RuntimeError(f"Got modified rpm file when RPM is unknown")

        if self._last_state is PCModsParserState.NEW_MODIFIED_RPM:
            self._change_state(PCModsParserState.CURRENT_MODIFIED_RPM_FILES)

        path = self._line_capture.group("path")
        if Regex.is_it("PI_PKGDIRS", path):
            self._process_repo_file(path, self._current_rpm)
        else:
            self._process_os_file(path, self._current_rpm)

    def _process_capture_missing_rpms(self):
        """Process captured missing RPMs list

        Usually means lines like:
            "Missing rpms: ci-provision."

        Just skips such lines, no state transitions or other actions.

        Raises:
            :UnexpectedInput: If it's not a transition
                after modified RPM files.
        """
        if (
            self._last_state is not PCModsParserState.IN_TRANSIT
            and self._prev_state is not PCModsParserState.CURRENT_MODIFIED_RPM_FILES
        ):
            raise UnexpectedInput(f"Got missing RPMs in:\n{self}")

    def _process_capture_check_installed_rpms_header(self):
        """Process captured check installed RPMs header line

        Usually means lines like:
            "Check installed rpms:"

        Raises:
            :UnexpectedInput: If it's not a transition after particular
                RPM modified files.
        """
        if (
            self._last_state is not PCModsParserState.IN_TRANSIT
            and self._prev_state is not PCModsParserState.CURRENT_MODIFIED_RPM_FILES
        ):
            raise UnexpectedInput(
                f"Got check installed rpms header in:\n{self}"
            )
        self._change_state(PCModsParserState.CHECK_INSTALLED_RPMS_FLOOD)
        self._current_rpm = None

    def _process_capture_check_installed_rpms_flood(self):
        """Process captured check installed RPMs flood line

        Usually means lines that aren't like:
            "[debug] Shouldn't be installed: pcs-0.10.17-2.0.1.el8.x86_64"

        Just skips such lines, no state transitions or other actions.

        Raises:
            :UnexpectedInput: If it's not a flood line after a previous
                or header line.
        """
        if (
            self._last_state is not PCModsParserState.CHECK_INSTALLED_RPMS_FLOOD
            and self._prev_state is not PCModsParserState.IN_TRANSIT
        ):
            raise UnexpectedInput(
                f"Got check installed rpms flood in:\n{self}"
            )

    def _process_capture_check_installed_rpms_custom_delete(self):
        """Process capture check installed RPMs custom-delete line

        Usually means lines like:
            "[info] rpms in custom-delete group: ['audit-libs', 'avahi-libs',...]"

        Raises:
            :UnexpectedInput: If received when self._last_state and
                self._prev_state values don't imply that the line is
                after a flood RPM check line.
            :RuntimeError: If the current server is unknown.
        """
        if (
            self._last_state is not PCModsParserState.CHECK_INSTALLED_RPMS_FLOOD
            and self._prev_state is not PCModsParserState.IN_TRANSIT
        ):
            raise UnexpectedInput(f"Got custom-delete RPMs in:\n{self}")
        if self._current_server is None:
            raise RuntimeError(
                "Got custom-delete install RPMs when server is unknown"
            )
        self._change_state(PCModsParserState.CHECK_INSTALLED_RPMS_CUSTOM_DELETE)

        for raw_rpm in self._line_capture.group("rpms").split():
            self._process_installed_rpm(raw_rpm.lstrip("'").rstrip("',"))

    def _process_capture_check_installed_rpms_dont_install(self):
        """Process captured check installed RPMs don't install line

        Usually means lines like:
            "[debug] Shouldn't be installed: pcs-0.10.17-2.0.1.el8.x86_64"

        Raises:
            :UnexpectedInput: If received when self._last_state and
                self._prev_state values don't imply that the line is
                after a flood RPM check line or a previous don't install
                RPM line.
            :RuntimeError: If the current server is unknown.
        """
        is_not_after_flood = (
            self._last_state is not PCModsParserState.CHECK_INSTALLED_RPMS_FLOOD
            and self._prev_state is not PCModsParserState.IN_TRANSIT
        )
        is_not_after_prev_rpm = (
            self._last_state is not PCModsParserState.CHECK_INSTALLED_RPMS_DONT_INSTALL
            and self._prev_state is not PCModsParserState.CHECK_INSTALLED_RPMS_FLOOD
        )
        is_not_after_custom_delete_rpms = (
            self._last_state is not PCModsParserState.CHECK_INSTALLED_RPMS_CUSTOM_DELETE
            and self._prev_state is not PCModsParserState.CHECK_INSTALLED_RPMS_FLOOD
        )
        if (
            is_not_after_flood
            and is_not_after_prev_rpm
            and is_not_after_custom_delete_rpms
        ):
            raise UnexpectedInput(f"Got don't install RPM in:\n{self}")
        if self._current_server is None:
            raise RuntimeError(f"Got don't install RPM when server is unknown")

        if self._last_state is PCModsParserState.CHECK_INSTALLED_RPMS_FLOOD:
            self._change_state(PCModsParserState.CHECK_INSTALLED_RPMS_DONT_INSTALL)

        self._process_installed_rpm(self._line_capture.group("rpm"))

    def _process_capture_tt_local_header(self):
        """Process captured .tt local header line

        Usually means lines like:
            "tt.local config files:"

        Raises:
            :UnexpectedInput: If it's not a transition after installed
                RPM checks.
        """
        if (
            self._last_state is not PCModsParserState.IN_TRANSIT
            and self._prev_state is not PCModsParserState.CHECK_INSTALLED_RPMS_DONT_INSTALL
            and self._prev_state is not PCModsParserState.CHECK_INSTALLED_RPMS_FLOOD
        ):
            raise UnexpectedInput(f"Got .tt local header in:\n{self}")
        self._change_state(PCModsParserState.TT_LOCAL_FILES)

    def _process_capture_tt_local_file(self):
        """Process captured .tt local file line

        Usually means lines like:
            "    /home/porta-configurator/etc/tt/shared/exim.conf.tt.local"

        Raises:
            :UnexpectedInput: If it's not a .tt local file path after
                a previous file or header.
        """
        if (
            self._last_state is not PCModsParserState.TT_LOCAL_FILES
            and self._prev_state is not PCModsParserState.IN_TRANSIT
        ):
            raise UnexpectedInput(f"Got .tt local file in:\n{self}")
        if self._current_server is None:
            raise RuntimeError(f"Got .tt local file when server is unknown")

        self._process_tt_local(
            self._line_capture.group("path").rstrip(".local")
        )

    def _process_capture_custom_httpd_conf(self):
        """Process captured custom Apache config path line

        Usually means lines like:
            "Custom httpd conf file was found: /etc/httpd/conf.d/porta.httpd.777679.conf"

        Raise:
            :UnexpectedInput: If received when self._last_state and
                self._prev_state values don't imply that the line is
                after a .tt local file path or a previous custom Apache
                config path line.
            :RuntimeError: If the current server is unknown.
        """
        is_not_after_tt_local = (
            self._last_state is not PCModsParserState.IN_TRANSIT
            and self._prev_state is not PCModsParserState.TT_LOCAL_FILES
        )
        is_not_after_prev_conf = (
            self._last_state is not PCModsParserState.CUSTOM_HTTPD_CONFIGS
            and self._prev_state is not PCModsParserState.IN_TRANSIT
        )
        if is_not_after_tt_local and is_not_after_prev_conf:
            raise UnexpectedInput(f"Got custom Apache config path in:\n{self}")
        if self._current_server is None:
            raise RuntimeError(
                f"Got custom Apache config path when server is unknown"
            )

        if self._last_state is PCModsParserState.IN_TRANSIT:
            self._change_state(PCModsParserState.CUSTOM_HTTPD_CONFIGS)

        self._process_os_file(self._line_capture.group("path"))

    def _process_capture_archives(self):
        """Process captured archives line

        Usually means lines like:
            "All custom patched files are backed up to"

        Raises:
            :UnexpectedInput: If it's not a transition
                after .tt local files.
        """
        is_not_after_tt_local = (
            self._last_state is not PCModsParserState.IN_TRANSIT
            and self._prev_state is not PCModsParserState.TT_LOCAL_FILES
        )
        is_not_after_custom_httpd_conf = (
            self._last_state is not PCModsParserState.CUSTOM_HTTPD_CONFIGS
            and self._prev_state is not PCModsParserState.IN_TRANSIT
        )
        if is_not_after_tt_local and is_not_after_custom_httpd_conf:
            raise UnexpectedInput(f"Got archives in:\n{self}")
        self._logger.info(
            f"Generated archive path notification:\n{self._line_raw}"
        )
        self._change_state(PCModsParserState.ARCHIVES_PATHS)

    def _process_capture_non_match(self):
        """Process captured non-matching line

        Usually means a line that doesn't match any regex from
        CHECK_PATCHES_F_REGEX_MAP.

        This can be an expected line in the following cases:
        - Generated archive paths in the end of server block.
        - Unsatisfied dependency by expected RPM.

        Raises:
            :UnexpectedInput: If it's a truly unexpected line.
        """
        if (
            self._last_state is PCModsParserState.ARCHIVES_PATHS
            and (
                self._prev_state is PCModsParserState.IN_TRANSIT
                or self._prev_state is PCModsParserState.CUSTOM_HTTPD_CONFIGS
            )
        ):
            self._logger.info(
                f"Path to archive generated on {self._current_server.name}:\n"
                f"{self._line_raw}"
            )
            return
        if (
            self._last_state is PCModsParserState.UNSATISFIED_DEPS_FOR
            and self._prev_state is PCModsParserState.NEW_MODIFIED_RPM
        ):
            self._logger.user(
                f"Unsatisfied dependency of {self._current_rpm} package:\n"
                f"{self._line_raw}"
            )
            return
        raise UnexpectedInput(
            f"Got unexpected non-matching line in:\n{self}"
        )

    def _process_server(self):
        """Check detected server and get Server object

        Raises:
            :RuntimeError: If line capture is empty.
        """
        if not self._line_capture:
            raise RuntimeError(
                "Attempt to check known servers when no line capture"
            )
        self._current_server = Servers.get_or_add(
            name=self._line_capture.group("name"),
            ip=self._line_capture.group("ip")
        )

    def _process_os_file(self, path, package=None):
        """Add detected file as ModifiedOSFilePC to PCModsProvider

        Parameters:
            :path (str): Path to detected modified file.
            :package (str|None): Resolved file owner RPM.

        Raises:
            :RuntimeError: If called when current server is unknown.
        """
        if not self._current_server:
            raise RuntimeError(
                "Attempt to add ModifiedOSFilePC when server is unknown"
            )

        resolution = Resolution.MANUAL_ATTENTION_REQUIRED_UNKNOWN

        is_ignored = Regex.is_it("EXPECTED_OS_CHANGES_IGNORED", path)
        is_warning = Regex.is_it("EXPECTED_OS_CHANGES_WARNING", path)

        if is_ignored:
            resolution = Resolution.NO_ATTENTION_REQUIRED_UNKNOWN
        elif is_warning:
            resolution = Resolution.MANUAL_ATTENTION_REQUIRED_KNOWN

        PCModsProvider.upsert(
            [self._current_server],
            ModifiedOSFilePC(
                path, package, resolution, is_ignored, is_warning
            )
        )

    def _process_repo_file(self, path, package=None):
        """Add detected file as ModifiedRepoFilePC to PCModsProvider

        Parameters:
            :path (str): Path to detected modified file.
            :package (str|None): Resolved file owner RPM.

        Raises:
            :RuntimeError: If called when current server is unknown.
        """
        if not self._current_server:
            raise RuntimeError(
                "Attempt to add ModifiedRepoFilePC when server is unknown"
            )

        resolution = Resolution.MANUAL_ATTENTION_REQUIRED_UNKNOWN

        is_ignored = Regex.is_it("EXPECTED_REPO_CHANGES_IGNORED", path)
        is_warning = Regex.is_it("EXPECTED_REPO_CHANGES_WARNING", path)

        if is_ignored:
            resolution = Resolution.NO_ATTENTION_REQUIRED_UNKNOWN
        elif is_warning:
            resolution = Resolution.MANUAL_ATTENTION_REQUIRED_KNOWN

        PCModsProvider.upsert(
            [self._current_server],
            ModifiedRepoFilePC(
                path, package, resolution, is_ignored, is_warning
            )
        )

    def _process_installed_rpm(self, name):
        """Add detected RPM as an InstalledRPM into PCModsProvider

        Parameters:
            :name (str): Name of the installed RPM.

        Raises:
            :RuntimeError: If called when current server is unknown.
        """
        if not self._current_server:
            raise RuntimeError(
                "Attempt to add InstalledRPM when server is unknown"
            )

        name_match = Regex.search("RPM_NAME", name)[1]
        if not name_match:
            raise RuntimeError(f"Cannot strip RPM version in:\n{self}")
        name = name_match.group("name")

        resolution = Resolution.MANUAL_ATTENTION_REQUIRED_UNKNOWN

        is_ignored = Regex.is_it("EXPECTED_INSTALLED_RPMS_IGNORED", name)
        is_warning = Regex.is_it("EXPECTED_INSTALLED_RPMS_WARNING", name)

        if is_ignored:
            resolution = Resolution.NO_ATTENTION_REQUIRED_UNKNOWN
        elif is_warning:
            resolution = Resolution.MANUAL_ATTENTION_REQUIRED_KNOWN

        PCModsProvider.upsert(
            [self._current_server],
            InstalledRPM(name, resolution, is_ignored, is_warning)
        )

    def _process_tt_local(self, path, package=None):
        """Add detected file as TTLocalFilePC to PCModsProvider

        Parameters:
            :path (str): Path to detected modified file.
            :package (str|None): Resolved file owner RPM.

        Raises:
            :RuntimeError: If called when current server is unknown.
        """
        if not self._current_server:
            raise RuntimeError(
                "Attempt to add TTLocalFilePC when server is unknown"
            )

        resolution = Resolution.MANUAL_ATTENTION_REQUIRED_UNKNOWN
        PCModsProvider.upsert(
            [self._current_server],
            TTLocalFilePC(path, package, resolution, None, None)
        )

    def _change_state(self, state):
        """Change parser state

        Rotates states from last to previous.

        Parameters:
            :state (PCModsParserState): State to change to.

        Raises:
            :ValueError: If state isn't PCModsParserState.
        """
        if not isinstance(state, PCModsParserState):
            raise ValueError(
                f"Invalid {state!r} state passed; should be one of "
                f"{list(PCModsParserState)}"
            )

        self._prev_state = self._last_state
        self._last_state = state
        self._logger.info(
            f"Parser state changed from {self._prev_state.name} to "
            f"{self._last_state.name}"
        )

    def _resolve_files_rpms(self):
        """Retrieve files owner RPMs on remote hosts

        The method forms bulk RPM queries to each affected server.
        """
        affected_pcms = [
            pcm for pcm in
            PCModsProvider.lookup(attrs={"amod.package": None})
            if isinstance(pcm.amod, ModifiedFile)
        ]
        affected_servers = set([
            server for pcm in affected_pcms for server in pcm.servers
        ])
        desc_params = {"servers": multiline_list(affected_servers)}
        tid = get_my_tid()

        with HeartbeatManager.track(
            PCModsParserRPMsResolvingHook.id, {}, desc_params,
            goal=len(affected_servers)
        ) as hooked:
            if not hooked:
                self._logger.info(
                    f"Start of {PCModsParserRPMsResolvingHook.desc(**desc_params)}"
                )
            pcm_access_lock = threading.RLock()

            with ParanoidThreadPoolExecutor(
                max_workers=int(os.cpu_count() or 4)
            ) as pool:
                for server in affected_servers:
                    pool.submit(
                        self._resolve_files_rpms_on_server,
                        server,
                        affected_pcms,
                        pcm_access_lock,
                        altid=tid
                    )
                for future in pool.iter_completed():
                    future.result()

    def _resolve_files_rpms_on_server(
        self, server, affected_pcms, pcm_access_lock, altid=None
    ):
        """Retrieve files owner RPMs on remote host

        Parameters:
            :server (Server): Server to perform data lookup on.
            :affected_pcms (list of PCMod): Objects which
                AtomicModification is missing package.
            :pcm_access_lock (threading.RLock): Prevents simultaneous
                access to PCMod objects data.
            :altid (int): Originating thread ID.
        """
        def _notify():
            HeartbeatManager.notify(
                PCModsParserRPMsResolvingHook.id,
                {"server": server.name},
                altid=altid
            )

        if not server.is_known:
            self._logger.warning(
                f"Skipping packages identification for the following "
                f"server as it's unknown: {server!r}"
            )
            return

        with pcm_access_lock:
            current_pcms = [
                pcm for pcm in affected_pcms
                if pcm.amod.package is None and server in pcm.servers
            ]
        script = (
            "rpm -q --queryformat '%% %{NAME}\\n' -f \\\n\t" + " \\\n\t".join([
                pcm.amod.path for pcm in current_pcms
            ]) + " 2>&1"
        )
        result = server.run_cmd(script, ignore_err=True).communicate()[0]

        if not result:
            _notify()
            return
        with pcm_access_lock:
            for pcm, line in zip(current_pcms, result.splitlines()):
                if line.startswith("% "):
                    pcm.amod.package = line.lstrip("% ")
        _notify()

