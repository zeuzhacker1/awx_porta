# collect-pre-update-data Patches Inventory related objects


import logging
import os
import pathlib
import re
import shutil
import threading

from libs.common import get_script, maybe_die, PopenWrapper
from libs.defaults import (PI_APPBIN, PI_SUMMARY_FIELDS_ORDER,
                           PI_SUMMARY_NOT_MANDATORY_FIELDS)
from libs.format import (indent_strs,
                         dump_object_multiline_pairs,
                         dump_object_oneline_reference,
                         ModifiedRepoFilePIReport,
                         PIPatchReport, PIBundleReport, PIModReport)
from libs.heartbeat import (PIModsParserOutputCollectionHook,
                            HeartbeatManager)
from libs.mods_generic import (UnexpectedInput, Resolution, ModifiedFile,
                               ComplexModification, ModsProvider)
from libs.objects import threadsafemethod, MetaSingleton
from libs.runtime import Facts, Regex, ReturnCode
from libs.servers import Servers


def get_pi_pkgdir_regexes():
    """Retrieve PI package directories as regexes

    Returns:
        :list of str: ^/pkgdir
    """
    try:
        return [
            f"^{pkgdir}" for pkgdir in PopenWrapper(
                [shutil.which("bash"), "-"], input=get_script("get_pi_pkgdirs")
            ).communicate()[0].splitlines()
        ]
    except Exception:
        raise RuntimeError(
            "Cannot retrieve list of known package directories from PI; "
            "check whether it's installed and initialized"
        )


class ModifiedRepoFilePI(ModifiedFile):
    """Modified repository file representation

    Represents a file controlled by Patches Inventory, detected in the
    summary module output. Such files are usually expected changes and
    often do not require user attention.
    """

    def __init__(self, change_type, *args, **kwargs):
        """Initializer

        Parameters:
            :change_type (str): Change type from Git's --name-status.
        """
        super().__init__(*args, **kwargs)
        self.change_type = change_type

    def __str__(self):
        """Representor for user"""
        return ModifiedRepoFilePIReport(self)

    def __format__(self, spec):
        """Representor with format"""
        return ModifiedRepoFilePIReport(self, spec=spec)

class PIPatch:
    """Patches Inventory bundle patch representation

    Represents a patch from a PI bundle detected in the summary module
    output. Used by modifications comparator to decide whether manual
    attention is needed.
    """

    def __init__(self, sha, number, subject, csup_tt, dev_tt, fixed_in, files):
        """Initializer

        Parameters:
            :sha (str): Unique patch SHA.
            :number (str): Commit order number in bundle.
            :subject (str): Official subject or SE comment.
            :csup_tt (str): Support-Ticket header from commit.
            :dev_tt (str): Devel-Issue header from commit.
            :fixed_in (str): Fixed-In header from commit.
            :files (list of ModifiedRepoFilePI): Affected files.
        """
        if not isinstance(files, list):
            raise ValueError(
                f"Invalid files passed; should be list; passed: {files!r}"
            )

        self.sha = sha
        self.number = number
        self.subject = subject
        self.csup_tt = csup_tt
        self.dev_tt = dev_tt
        self.fixed_in = fixed_in
        self.files = files

    def __repr__(self):
        """Representor for devel"""
        return dump_object_oneline_reference(
            self, names_to_mask=["files"], mask_protected=True
        )

    def __str__(self):
        """Representor for user"""
        return PIPatchReport(self)

    def __format__(self, spec):
        """Representor with format"""
        return PIPatchReport(self, spec=spec)

class PIBundle:
    """Patches Inventory bundle representation

    Represents a PI bundle from the summary module output. Used to group
    patches and files logically.
    """

    def __init__(self, sha, name, is_dirty, patches):
        """Initializer

        Parameters:
            :sha (str): Unique PI bundle SHA hash.
            :name (str): PI bundle name in staged format.
            :is_dirty (bool): True if unknown modifications were found.
            :patches (list of PIPatch): Bundle patches.
        """
        if not isinstance(patches, list):
            raise ValueError(
                f"Invalid patches passed; should be list; passed: {patches!r}"
            )

        self.sha = sha
        self.name = name
        self.is_dirty = is_dirty
        self.patches = patches

    def __repr__(self):
        """Representor for devel"""
        return dump_object_oneline_reference(
            self, names_to_mask=["patches"], mask_protected=True
        )

    def __str__(self):
        """Representor for user"""
        return PIBundleReport(self)

    def __format__(self, spec):
        """Representor with format"""
        return PIBundleReport(self, spec=spec)


class PIMod(ComplexModification):
    """Patches Inventory modification complex representation

    Represents a modification from PI summary output. Used by the mods
    provider to provide unified access to different modification types.
    """

    def __init__(self, bundle, patch, *args, **kwargs):
        """Initializer

        Parameters:
            :bundle (PIBundle): Bundle owner of AtomicModification.
            :patch (PIPatch): Patch owner of AtomicModification.
        """
        super().__init__(*args, **kwargs)
        self.bundle = bundle
        self.patch = patch

    def __str__(self):
        """Representor for user"""
        return PIModReport(self)

    def __format__(self, spec):
        """Representor with format"""
        return PIModReport(self, spec=spec)


class PIModsProvider(ModsProvider):
    """Provides global access to parsed PI summary output"""

    #: list of IndexNode: Indexed storage. Creating a separate list here
    #: to avoid ancestor's list usage between inheritors.
    _cmods_index = []

    @classmethod
    def upsert(cls, servers, amod, bundle, patch):
        """Ancestor method parameters extension

        Parameters:
            :bundle (PIBundle): Bundle owner of AtomicModification.
            :patch (PIPatch): Patch owner of AtomicModification.
        """
        super().upsert(servers, amod, bundle, patch)

    @staticmethod
    def gen_amod_lookup_attrs(amod, *args, **kwargs):
        """Abstract method implementation

        Parameters:
            :bundle (PIBundle): Bundle owner of AtomicModification.
            :patch (PIPatch): Patch owner of AtomicModification.
        """
        attr, value = amod.identify()
        lookup_attrs = {f"amod.{attr}": value}
        if isinstance(amod, ModifiedRepoFilePI):
            lookup_attrs["amod.change_type"] = amod.change_type
        return lookup_attrs

    @staticmethod
    def gen_cmod_object(amod, servers, bundle, patch):
        """Abstract method implementation

        Parameters:
            :bundle (PIBundle): Bundle owner of AtomicModification.
            :patch (PIPatch): Patch owner of AtomicModification.
        """
        return PIMod(bundle, patch, amod, servers)

    @staticmethod
    def mutate_mod_for_insert(servers, amod, bundle, patch):
        """Abstract method implementation

        Parameters:
            :bundle (PIBundle): Bundle owner of AtomicModification.
            :patch (PIPatch): Patch owner of AtomicModification.
        """
        patch.files.append(amod)
        return PIModsProvider.gen_cmod_object(amod, servers, bundle, patch)

    @staticmethod
    def mutate_mod_for_update(servers, pim, bundle, patch):
        """Abstract method implementation

        Parameters:
            :bundle (PIBundle): Bundle owner of AtomicModification.
            :patch (PIPatch): Patch owner of AtomicModification.
        """
        if pim.bundle.sha == bundle.sha and pim.patch.sha == patch.sha:
            return
        patch.files.append(pim.amod)
        return PIModsProvider.gen_cmod_object(pim.amod, servers, bundle, patch)

    @staticmethod
    def gen_dump_path():
        """Abstract method implementation"""
        return (
            f"{Facts.backup_dir}/raws/"
            f"patches_inventory.parsed.{Facts.start_epoch}.txt"
        )


class PIModsParser(metaclass=MetaSingleton):
    """Maintains PI summary output parsing

    The parser has no complex state cycles, instead it just waits for
    the CSV header appearance and starts reading CSV values. All parsed
    data is available in PIModsProvider.

    The only important moment here is that parser inserts bundle records
    only once it finishes the bundle record compile.
    """

    #: threading.RLock: Ensures consistent parsing/indexation.
    _lock = threading.RLock()

    #TODO: on available resources:
    # 1. Currently, self._line_fields access is hardcoded. I.e.,
    #    if you change PI_SUMMARY_FIELDS_ORDER in defaults, you also
    #    have to change some calls in this class to make it works.
    #    We need to find a way to avoid this. E.g., some map constant
    #    and abstracted getters that rely on it.

    def __init__(self):
        """Initializer

        Attributes:
            :_logger (logging.Logger): Child logger.
            :_data_regex (re.Pattern): Generated regex for CSV/TSV data.
            :_header_reached (bool): True if CSV header is already seen.
            :_line_raw (str): Currently processed PI summary line.
            :_line_fields (dict of str): Fields of the current line.
            :_current_patch (PIPatch): Patch object to upsert into provider.
            :_current_bundle (PIBundle): Bundle object to upsert into
                provider.
            :_current_servers (list of Server): Cached servers where
                current bundle is checkedout.
        """
        self._logger = logging.getLogger("patches_inventory")
        self._data_regex = None
        self._header_reached = False
        self._line_raw = None
        self._line_fields = {}
        self._current_patch = None
        self._current_bundle = None
        self._current_servers = None

    def __repr__(self):
        """Representor"""
        return dump_object_multiline_pairs(self)

    @threadsafemethod
    def main(self, no_parse=False, no_update=False):
        """Start PI summary output collection and parsing

        Parameters:
            :no_parse (bool): Skip parsing (CPU-heavy); useful when
                running in threads where GIL blocks execution anyway.
            :no_update (bool): Skip PI status update before collection.
        """
        if not Facts.pi_output_path:
            self._logger.info(
                "Path to PI summary output isn't set, "
                "going to collect fresh data"
            )
            #TODO: once PI-240 resolved:
            # - Restore normal flow.
            if not self.collect_output__pi_240(no_update):
                return
        if not no_parse:
            self.parse_output()

    @threadsafemethod
    def collect_output(self, no_update=False):
        """Collect PI summary output

        Returns:
            :bool: False if collection failed.
        """
        from modes.patches_inventory import (
            PATCHES_INVENTORY_EMAIL_BODY_COLLECTION_FAILED
        )

        proc = PopenWrapper(
            (PI_APPBIN, "update"),
            raise_exc=False
        )
        if proc.returncode != 0:
            self._logger.error(
                "Failed to update PI. Please check."
            )
            ReturnCode.set(1)
            return False
        proc = PopenWrapper(
            self.get_pi_summary_status_cmd("unlisted"),
            ignore_err=True
        )
        if proc.returncode == 0:
            self._logger.error(
                "Unaccounted changes in bundles without patches were detected. "
                "Please perform 'pi slurp' to save them"
            )
            ReturnCode.set(1)
            return False
        proc = PopenWrapper(
            self.get_pi_summary_status_cmd("listed"),
            raise_exc=False
        )
        if proc.returncode != 0:
            self._logger.info(
                "No modifications found at all (make sure this is expected)"
            )
            Facts.pi_has_mods = False
            ReturnCode.set(1)
            return False
        Facts.pi_has_mods = True

        pi_output = (
            f"{Facts.backup_dir}/raws/"
            f"patches_inventory.collected.{Facts.start_epoch}.txt"
        )
        Facts.pi_output_path = pi_output

        is_hookable = HeartbeatManager.is_hookable(
            PIModsParserOutputCollectionHook.id
        )
        if not is_hookable:
            self._logger.info(
                f"Going to collect PI summary to: {pi_output}"
            )
            self._logger.warning(
                "Note that this might take some time, PI summary is slow"
            )
        proc = PopenWrapper(
            self.get_pi_summary_cmd(no_update),
            output=pi_output,
            error=pi_output,
            ignore_err=True,
            hook=PIModsParserOutputCollectionHook
        )
        if proc.returncode == 0:
            if not is_hookable:
                self._logger.info("Collection is successfully finished")
            Facts.pi_output_collected = True
            return True
        self._logger.error(
            f"PI summary collection failed:\n"
            f"{indent_strs(PATCHES_INVENTORY_EMAIL_BODY_COLLECTION_FAILED)}"
        )
        Facts.pi_output_collected = False
        ReturnCode.set(1)
        return False

    @threadsafemethod
    def collect_output__pi_240(self, no_update=False):
        """Temporary alternative related to PI-240

        Collects PI summary with Bash xtrace.
        Staus update is peformed separately.

        #TODO: once PI-240 resolved:
        # - Remove this alternative and restore normal flow.

        Returns:
            :bool: False if collection failed.
        """
        from modes.patches_inventory import (
            PATCHES_INVENTORY_EMAIL_BODY_COLLECTION_FAILED
        )
        self._logger.warning(
            "PI-240 temporary measure is active; "
            "PI summary will be collected with Bash xtrace; "
            "all temporary files will be preserved too"
        )
        self._logger.warning(
            "If you see this message but PI-240 resolved: "
            "ask maintainer to restore normal flow!"
        )

        proc = PopenWrapper(
            (PI_APPBIN, "update"),
            raise_exc=False
        )
        if proc.returncode != 0:
            self._logger.error(
                "Failed to update PI. Please check."
            )
            ReturnCode.set(1)
            return False
        proc = PopenWrapper(
            self.get_pi_summary_status_cmd("unlisted"),
            ignore_err=True
        )
        if proc.returncode == 0:
            self._logger.error(
                "Unaccounted changes in bundles without patches were detected. "
                "Please perform 'pi slurp' to save them"
            )
            ReturnCode.set(1)
            return False
        proc = PopenWrapper(
            self.get_pi_summary_status_cmd("listed"),
            raise_exc=False
        )
        if proc.returncode != 0:
            self._logger.info(
                "No modifications found at all (make sure this is expected)"
            )
            Facts.pi_has_mods = False
            ReturnCode.set(1)
            return False
        Facts.pi_has_mods = True

        if not no_update:
            proc = PopenWrapper(
                (PI_APPBIN, "status", "-u"),
                ignore_err=True
            )
            if proc.returncode != 0:
                self._logger.error(
                    f"PI status update failed:\n"
                    f"{indent_strs(PATCHES_INVENTORY_EMAIL_BODY_COLLECTION_FAILED)}"
                )
                Facts.pi_output_collected = False
                ReturnCode.set(1)
                return False

        pi_tmpdir = (
            f"{Facts.backup_dir}/raws/"
            f"patches_inventory.tmps.{Facts.start_epoch}"
        )
        Facts.pi_tmpdir_path = pi_tmpdir
        pathlib.Path(pi_tmpdir).mkdir(parents=True, exist_ok=True)

        trace_env = os.environ.copy()
        trace_env["PI_TMPDIR"] = pi_tmpdir
        trace_env["PI_FORCE_XTRACE"] = ""
        trace_env["PI_NO_TMP_CLEANUP"] = ""

        pi_xtrace_n_output = (
            f"{Facts.backup_dir}/raws/"
            f"patches_inventory.collected_traced.{Facts.start_epoch}.txt"
        )
        pi_output = (
            f"{Facts.backup_dir}/raws/"
            f"patches_inventory.collected_stripped.{Facts.start_epoch}.txt"
        )
        Facts.pi_xtrace_n_output_path = pi_xtrace_n_output
        Facts.pi_output_path = pi_output

        is_hookable = HeartbeatManager.is_hookable(
            PIModsParserOutputCollectionHook.id
        )
        if not is_hookable:
            self._logger.info(
                f"Going to collect PI summary with xtrace to: {pi_xtrace_n_output}"
            )
            self._logger.warning(
                "Note that this might take some time, PI summary is slow"
            )
        proc = PopenWrapper(
            self.get_pi_summary_cmd__pi_240(),
            output=pi_xtrace_n_output,
            error=pi_xtrace_n_output,
            ignore_err=True,
            hook=PIModsParserOutputCollectionHook,
            env=trace_env
        )
        if proc.returncode != 0:
            self._logger.error(
                f"PI summary collection failed:\n"
                f"{indent_strs(PATCHES_INVENTORY_EMAIL_BODY_COLLECTION_FAILED)}"
            )
            Facts.pi_output_collected = False
            ReturnCode.set(1)
            return False
        if not is_hookable:
            self._logger.info("Collection is successfully finished")
        self._logger.info(
            f"Stripping xtrace from summary saving it to: {pi_output}"
        )
        summary_header = r"\t".join((
            "Bundle SHA",
            "Bundle",
            "Is package dirty?",
            "Is bundle staged?",
            "Patch SHA",
            "Patch subject",
            "Patch#",
            "Change",
            "File",
            "CSUP-TT",
            "Dev-TT",
            "Fixed-In",
            "Servers"
        ))
        PopenWrapper(
            ("bash", "-"),
            input=rf"""
                sed -n '/^{summary_header}/,/^\+/p' {pi_xtrace_n_output} \
                | sed '$d' > {pi_output}
            """
        )
        Facts.pi_output_collected = True
        return True

    @staticmethod
    def get_pi_summary_status_cmd(status_type):
        """Retrieve command to check modifications status

        PI summary module provides possibility to check beforehand:
        - If there are changes that cannot be listed (unlisted).
        - If there are any changes to show at all (listed).

        Parameters:
            :status_type (str): Either "unlisted" or "listed"

        Returns:
            :list of str: Command to execute on the current host.
        """
        return [PI_APPBIN, "summary", "has", status_type, "changes"]

    @staticmethod
    def get_pi_summary_cmd(no_update=False):
        """Retrieve command to collect known modifications

        Parameters:
            :no_update (bool): If True, skip status update.

        Returns:
            :list of str: Command to execute on the current host.
        """
        script = [PI_APPBIN, "summary", "-t", "-f"]

        format_opt = "".join([
            f"{{{field}}}" for field in PI_SUMMARY_FIELDS_ORDER
        ])
        script.append(format_opt)

        update_opt = "-u" if not no_update else ""
        script.append(update_opt)

        return script

    @staticmethod
    def get_pi_summary_cmd__pi_240():
        """Temporary wrapper related to PI-240

        Forces no_update=True flag
        to avoid executing PI status update without tracing.

        #TODO: once PI-240 resolved:
        # - Remove this wrapper and restore normal flow.
        """
        return PIModsParser.get_pi_summary_cmd(no_update=True)

    @threadsafemethod
    def parse_output(self, pi_output=None):
        """Parse collected PI summary output"""
        from modes.patches_inventory import (
            PATCHES_INVENTORY_EMAIL_BODY_PARSING_FAILED
        )
        pi_output = pi_output or Facts.pi_output_path
        pi_output_fd = open(pi_output, "r", encoding="utf-8")
        self._logger.info(f"Starting PI summary output parsing: {pi_output}")

        if not self._data_regex:
            #self._data_regex = self.get_regex_csv()
            self._data_regex = self.get_regex_tsv()
        self._logger.debug(f"Using regex: {self._data_regex.pattern}")

        try:
            for line in pi_output_fd:
                maybe_die(self._logger)

                self._line_raw = line.strip("\n")
                self._line_fields.clear()

                self._logger.debug(f"Got raw line:\n{self._line_raw}")
                self._get_capture()

                if self._line_fields:
                    self._exec_capture_processor()
        except UnexpectedInput:
            self._logger.error(
                f"PI summary parsing failed:\n"
                f"{indent_strs(PATCHES_INVENTORY_EMAIL_BODY_PARSING_FAILED)}\n\n",
                exc_info=True
            )
            Facts.pi_output_parsed = False
            pi_output_fd.close()
            return

        pi_output_fd.close()
        self._logger.info(f"Finished PI summary output parsing: {pi_output}")
        Facts.pi_output_parsed = True

    @staticmethod
    def get_regex_csv():
        """Generate and compile regex for CSV data capture

        Returns:
            :re.Pattern: Regular expression for CSV parsing.
        """
        return re.compile(",".join([
            rf"([^,]*)" for _ in PI_SUMMARY_FIELDS_ORDER
        ]))

    @staticmethod
    def get_regex_tsv():
        """Generate and compile regex for TSV data capture

        Returns:
            :re.Pattern: Regular expression for TSV parsing.
        """
        return re.compile("\t".join([
            f"([^\t]*)" for _ in PI_SUMMARY_FIELDS_ORDER
        ]))

    def _get_capture(self):
        """Try to match line using CSV or TSV regex

        Runtime-generated regex (based on field count in
        PI_SUMMARY_FIELDS_ORDER) is applied to match the current line.

        Raises:
            :RuntimeError: If _line_raw or regex is not set.
        """
        if self._line_raw is None:
            raise RuntimeError(
                "No retrieved PI summary line found; "
                "cannot perform regex match and capture"
            )
        if self._data_regex is None:
            raise RuntimeError(
                "No prepared regex for CSV or TSV found; "
                "cannot perform regex match and capture"
            )

        line_capture = self._data_regex.search(self._line_raw)

        if line_capture:
            if self._header_reached:
                self._get_fields(line_capture)
            else:
                self._logger.info(
                    "Found first data line; considering it's header"
                )
                self._header_reached = True
        else:
            if self._header_reached:
                raise UnexpectedInput(f"Got non-data line in:\n{self}")
            else:
                self._logger.warning(
                    f"Skipping non-data line before header:\n{self._line_raw}"
                )

    def _get_fields(self, capture):
        """Map captured regex groups to summary fields

        Parameters:
            :capture (re.Match): Captured groups.

        Raises:
            :UnexpectedInput: If a mandatory field is missing.
        """
        for i, field in enumerate(PI_SUMMARY_FIELDS_ORDER):
            raw_value = capture.group(i+1)
            value = None if raw_value in ("N/A", "") else raw_value

            if not value and field not in PI_SUMMARY_NOT_MANDATORY_FIELDS:
                raise UnexpectedInput(
                    f"Mandatory field {field} is absent in:\n{self}"
                )
            self._line_fields[field] = value

    def _exec_capture_processor(self):
        """Process captured CSV data

        Raises:
            :RuntimeError: If no fields were captured.
        """
        if self._line_fields is None:
            raise RuntimeError(
                "Fields values aren't captured; nothing to process"
            )
        self._process_bundle()
        self._process_patch()
        self._process_file()

    def _process_bundle(self):
        """Drop current bundle and create a new bundle

        Skips procedure if current bundle is the same.
        """
        if self._is_same_bundle():
            return
        if self._current_bundle:
            self._logger.info(f"Rotating bundle: {self._current_bundle!r}")
        self._current_bundle = self._gen_current_bundle()
        self._current_servers = self._process_servers()

    def _process_servers(self):
        """Generate Server objects from current line

        Returns:
            :list of Server: Generate server objects.
        """
        return [
            Servers.get_or_add(name=name)
            for name in self._line_fields["servers_full"].split(" ")
        ]

    def _process_patch(self):
        """Push current patch to bundle and create a new patch

        Skips procedure if current patch is the same.

        Raises:
            :RuntimeError: If current bundle is not set.
        """
        if self._is_same_patch():
            return
        if self._current_patch:
            self._logger.info(f"Rotating patch: {self._current_patch!r}")
        self._current_patch = self._gen_current_patch()

        if not self._current_bundle:
            raise RuntimeError(
                f"Attempt to push patch to undefined bundle in:\n{self}"
            )
        self._current_bundle.patches.append(self._current_patch)

    def _process_file(self):
        """Push generated file to current patch and upsert to provider

        File is added to self._current_patch.files only on mutation
        during upsert to PIModsProvider to avoid duplication.

        Raises:
            :RuntimeError: If current patch is not set.
        """
        if (
            not self._current_patch
            or not self._current_bundle
            or not self._current_servers
        ):
            raise RuntimeError(
                f"Attempt to push file undefined entities in:\n{self}"
            )
        PIModsProvider.upsert(
            self._current_servers,
            self._gen_file(),
            self._current_bundle,
            self._current_patch
        )

    def _is_same_patch(self):
        """Check if patch matches last generated one

        Returns:
            :bool: True if it's the same patch.
        """
        return (
            self._current_patch and
            self._line_fields["patch_sha_short"] == self._current_patch.sha
        )

    def _is_same_bundle(self):
        """Check if bundle matches last generated one

        Returns:
            :bool: True if it's the same bundle.
        """
        return (
            self._current_bundle and
            self._line_fields["bundle_sha_short"] == self._current_bundle.sha
        )

    def _gen_current_patch(self):
        """Generate raw PIPatch from current line

        Returns:
            :PIPatch: Generated patch object.
        """
        return PIPatch(
            self._line_fields["patch_sha_short"],
            self._line_fields["patch_number"],
            self._line_fields["patch_subj"],
            self._line_fields["csup_tt"],
            self._line_fields["dev_tt"],
            self._line_fields["fixed_in"],
            []
        )

    def _gen_current_bundle(self):
        """Generate raw PIBundle from current line

        Returns:
            :PIBundle: Generated bundle object.
        """
        return PIBundle(
            self._line_fields["bundle_sha_short"],
            self._line_fields["bundle_shortname"],
            self._is_dirty(),
            []
        )

    def _gen_file(self):
        """Generate ModifiedRepoFilePI from current line

        Returns:
            :ModifiedRepoFilePI: Generated file object.
        """
        path = self._line_fields["file_w_pkgdir"]
        resolution = Resolution.MANUAL_ATTENTION_REQUIRED_UNKNOWN

        is_dirty = self._is_dirty()
        is_csup_tt = self._is_csup_tt()
        is_fixed_in = self._is_fixed_in()

        is_ignored = Regex.is_it("EXPECTED_REPO_CHANGES_IGNORED", path)
        is_warning = Regex.is_it("EXPECTED_REPO_CHANGES_WARNING", path)

        if is_ignored and is_fixed_in:
            resolution = Resolution.NO_ATTENTION_REQUIRED_UNKNOWN
        elif is_warning:
            resolution = Resolution.MANUAL_ATTENTION_REQUIRED_KNOWN
        elif is_csup_tt:
            if is_dirty or not is_fixed_in:
                resolution = Resolution.MANUAL_ATTENTION_REQUIRED_KNOWN
            else:
                resolution = Resolution.NO_ATTENTION_REQUIRED_KNOWN

        return ModifiedRepoFilePI(
            self._line_fields["change"],
            self._line_fields["file_w_pkgdir"],
            self._line_fields["bundle_shortname"].split(":")[0],
            resolution,
            is_ignored,
            is_warning
        )

    def _is_dirty(self):
        """Check if bundle has untracked remote changes

        Returns:
            :bool: True if bundle is dirty.
        """
        return self._line_fields["is_dirty"] == "Y"

    def _is_staged(self):
        """Check if bundle is staged

        Non-staged bundles (likely auto-generated) may require review.

        Returns:
            :bool: True if bundle is staged.
        """
        return self._line_fields["is_staged"] == "Y"

    def _is_fixed_in(self):
        """Check if Fixed-In is present in patch

        Patches without Fixed-In may require manual verification.

        Returns:
            :bool: True if patch contains Fixed-In.
        """
        return self._line_fields["fixed_in"] is not None

    def _is_csup_tt(self):
        """Check if Support-Ticket is present in patch

        Patches without it may require manual verification.

        Returns:
            :bool: True if patch contains Support-Ticket.
        """
        return self._line_fields["csup_tt"] is not None

