# collect-pre-update-data local modifications comparison logic


import logging
import os
import re
import threading

from libs.check_patches_f import (ModifiedOSFilePC, ModifiedRepoFilePC,
                                  TTLocalFilePC, InstalledRPM,
                                  PCMod, PCModsProvider)
from libs.common import (PopenWrapper, TempfileBufferedFileWriter,
                         ParanoidThreadPoolExecutor, ThreadSafeNamespace)
from libs.format import multiline_list
from libs.runtime import get_my_tid, Facts, ReturnCode
from libs.objects import threadsafemethod, MetaSingleton
from libs.heartbeat import (ModsReporterPCModsProcessingHook,
                            ModsReporterDetailsCollectionHook,
                            HeartbeatManager)
from libs.defaults import (PI_APPBIN,
                           PI_SLURP_SUBJECT_PREFIX_CSP,
                           REPORT_SEPARATOR_SYMBOL,
                           REPORT_SEPARATOR_WIDTH)
from libs.mods_generic import Resolution
from libs.patches_inventory import PIModsProvider


REPORT_HEADER = """
# This is local modifications analysis and comparison report.
# Below is only mandatory data for your manual attention.
#
# If you believe a modification should be ignored by default,
# add it to one of the EXPECTED_* regex lists in defaults.py
# and commit it to support-repo to save other SEs time.
#
# All expected modifications are skipped; such as:
# - /etc files that usually appear in check_patches_f output and there's
#   no need to check them as shown by practice.
# - Modifications detected by check_patches_f but accounted in Patches
#   Inventory bundle that has no issues. See information below about
#   affected PI bundles.
# - Removed or modified functional or autotests that always appear both
#   in check_patches_f output and PI bundles.
# - Recompiled files such as in result of PortaAdmin frontend patching
#   with TypeScript code recompilation.
# - Unknown installed RPMs that often appear in check_patches_f output
#   and usually ignored by user.
#
# There are two versions of report:
# - Compact version where only detected modification metadata.
# - Full version where diffs are supplied too.
#
# Typical reasons why PI bundle is considered affected:
# - The Support-Ticket header isn't set in affected patch in PI bundle.
#   This means that the patch was created during old slurp operation and
#   it's most likely unknown.
# - The affected bundle is dirty, i.e., there might be unaccounted
#   modifications that you should investigate.
# - The affected patch has no Fixed-In header. This means it will be
#   reapplied continuously after each update by the redo command.
"""


#: list of Resolution: Resolutions that require manual attention.
AFFECTED_RESOLUTIONS = [
    Resolution.MANUAL_ATTENTION_REQUIRED_UNKNOWN,
    Resolution.MANUAL_ATTENTION_REQUIRED_KNOWN
]

#: list of Resolution: Resolutions that can be safely ignored.
SKIPPED_RESOLUTIONS = [
    Resolution.NO_ATTENTION_REQUIRED_UNKNOWN,
    Resolution.NO_ATTENTION_REQUIRED_KNOWN
]


class ModsReporter(metaclass=MetaSingleton):
    """Compare and analyze check_patches_f and PI local modifications

    The class depends on data in PCModsProvider and PIModsProvider.
    Its public methods must be used after PCModsParser and
    PIModsParser were executed. Mostly relies on Resolutions assigned
    during parsing.
    """

    #: threading.RLock: Ensures no simultaneous executions.
    _lock = threading.RLock()

    def __init__(self):
        """Initializer

        Attributes:
            :_logger (logging.Logger): Child logger.
            :_prohibit_async (bool): Restricts any multi-threading.
            :_compact_output (TempfileBufferedFileWriter): Path
                to compact report.
            :_full_output (TempfileBufferedFileWriter): Path
                to full report.
            :_current_top_i_mod (int): Incremental index of last
                modification pushed in processing.
            :_tns (ThreadSafeNamespace): Used as storage for the
                below described properties for cross-thread access.
            :_tns.i_mod (int): Incremental ID of current modification.
            :_tns.pcm (PCMod): Modification object from PCModsProvider.
            :_control_tid (int): Main reporter thread. Used in notify
                calls to HeartbeatManager to specify altid.
        """
        self._logger = logging.getLogger("mods_reporter")
        self._prohibit_async = None
        self._compact_output = None
        self._full_output = None
        self._current_top_i_mod = 0
        self._tns = ThreadSafeNamespace()
        self._control_tid = None

    @threadsafemethod
    def main(self, no_diffs=False, all=False, no_async=False):
        """Initiates local modifications analysis

        Parameters:
            :no_diffs (bool): If True then full report won't be collected.
            :all (bool): If True, includes even unaffected modifications.
            :no_async (bool): If True then only on thread is used.
        """
        self.analyze_pc_mods(no_full=no_diffs, no_skip=all, no_threads=no_async)
        self.analyze_pi_mods(no_full=no_diffs, no_skip=all)

    def _set_report_outputs(self, no_full=False):
        """Set paths to compact and full report

        Parameters:
            :no_full (bool): If True then full report won't be collected.
        """
        reports_dir = f"{Facts.backup_dir}/reports"
        start_epoch = Facts.start_epoch

        if not self._compact_output:
            self._compact_output = TempfileBufferedFileWriter(
                f"{reports_dir}/mods_reporter.compact.{start_epoch}.txt",
                dump_exc_to_path=True
            )
            self._compact_output.write_direct(REPORT_HEADER)
            self._logger.info(
                f"Mods analysis compact report path set: "
                f"{self._compact_output.path}"
            )
            Facts.mods_compact_output = self._compact_output.path
        if no_full:
            return
        if not self._full_output:
            self._full_output = TempfileBufferedFileWriter(
                f"{reports_dir}/mods_reporter.full.{start_epoch}.txt",
                dump_exc_to_path=True
            )
            self._full_output.write_direct(REPORT_HEADER)
            self._logger.info(
                f"Mods analysis full report path set: "
                f"{self._full_output.path}"
            )
            Facts.mods_full_output = self._full_output.path

    def _check_modp_empty(self, msg, is_empty):
        """Check whether ModsProvider inheritor is empty

        Writes corresponding message in log and report outputs if so
        and switches suite return code and facts too.

        Parameters:
            :msg (str): Message to log and write to reports.
            :is_empty (callable): Function to check if so.
        """
        if not is_empty():
            return False
        self._logger.error(msg)

        self._write_both(line=msg)
        self._flush_both()

        self._switch_facts(False)
        ReturnCode.set(1)
        return True

    def _check_pcmp_empty(self):
        """Check whether PCModsProvider is empty

        Returns:
            :bool: True if so.
        """
        return self._check_modp_empty(
            "PC modifications index is empty; nothing to compare; "
            "was PC check_patches_f collection/parsing successful?",
            lambda: not Facts.pc_output_parsed or PCModsProvider.is_empty()
        )

    def _check_pimp_empty(self):
        """Check whether PIModsProvider is empty

        Returns:
            :bool: True if so.
        """
        return self._check_modp_empty(
            "PI modifications index is empty; nothing to compare; "
            "was PI summary collection/parsing successful?",
            lambda: not Facts.pi_output_parsed or PIModsProvider.is_empty()
        )

    @threadsafemethod
    def analyze_pc_mods(self, no_full=False, no_skip=False, no_threads=False):
        """Iterate over check_patches_f modifications

        Wraps protected method with thread lock and heartbeat hook.

        Parameters:
            :no_full (bool): If True then full report won't be collected.
            :no_skip (bool): If True, includes even unaffected mods.
            :no_threads (bool): If True then only on thread is used.
        """
        self._control_tid = get_my_tid()

        found_pcms = PCModsProvider.lookup(None, AFFECTED_RESOLUTIONS)
        goal = len(found_pcms)

        with HeartbeatManager.track(
            ModsReporterPCModsProcessingHook.id, {}, {"amount": goal},
            goal=goal
        ) as hooked:
            self._analyze_pc_mods(
                no_full, no_skip, no_threads, found_pcms, hooked
            )

    def _analyze_pc_mods(
        self, no_full, no_skip, no_threads, found_pcms, hooked
    ):
        """Iterate over check_patches_f modifications

        Parameters:
            :no_full (bool): If True then full report won't be collected.
            :no_skip (bool): If True, includes even unaffected mods.
            :no_threads (bool): If True then only on thread is used.
            :found_pcms (list of PCMod): Objects which resolution
                is in AFFECTED_RESOLUTIONS.
            :hooked (str|None): Registered heartbeat event name if any.
        """
        if not hooked:
            self._logger.info("Starting PC to PI modifications comparison")

        self._set_report_outputs(no_full=no_full)
        self._write_both(
            line="\n\n# check_patches_f analysis and details\n\n"
        )
        self._flush_both()

        if self._check_pcmp_empty():
            return
        if Facts.pi_has_mods is False:
            self._logger.warning(
                "No PI modifications was found. "
                "Please verify that it is expected"
            )
            self._write_both(
                "WARNING: No PI modifications was found. "
                "Please verify that it is expected"
            )
            self._flush_both()
        elif self._check_pimp_empty():
            return

        self._prohibit_async = no_threads
        if self._prohibit_async:
            self._logger.warning("Async operations restriction applied")
            for pcm in found_pcms:
                self._current_top_i_mod += 1
                self._analyze_affected_pcm(self._current_top_i_mod, pcm)
        else:
            with ParanoidThreadPoolExecutor(
                max_workers=int(os.cpu_count() or 4)
            ) as pool:
                for pcm in found_pcms:
                    self._current_top_i_mod += 1
                    pool.submit(
                        self._analyze_affected_pcm,
                        self._current_top_i_mod,
                        pcm
                    )
                for future in pool.iter_completed():
                    future.result()

        if no_skip:
            self._logger.warning("Dumping skipped PC mods as requested")
            self._report_mod(
                "Skipped PC mods",
                [
                    "  Reason: User request\n", "  List start\n"
                ] + [
                    f"\n{pcm:indent.4}"
                    for pcm in PCModsProvider.lookup(
                        None, SKIPPED_RESOLUTIONS
                    )
                ] + [ "\n  List end\n" ]
            )
        if not hooked:
            self._logger.info("Finished PC to PI modifications comparison")
        self._switch_facts(True)

    def _analyze_affected_pcm(self, i_mod, pcm):
        """Decide whether it's needed to report modification and how

        Parameters:
            :i_mod (int): Incremental ID of current modification.
                If async is allowed then preserves it in self._tns.
            :pcm (PCMod): Modification object from PCModsProvider.
                If async is allowed then preserves it in self._tns.

        Raises:
            :RuntimeError: If ComplexModification isn't PCMod.
                If AtomicModification is unknown.
        """
        self._tns.i_mod = i_mod
        self._tns.pcm = pcm
        try:
            if not isinstance(pcm, PCMod):
                raise RuntimeError(
                    f"Attempt to process not PCMod as it:\n{pcm!r}"
                )
            self._logger.warning(
                f"Processing #{i_mod} check_patches_f modification:\n{pcm!r}"
            )

            if isinstance(pcm.amod, ModifiedOSFilePC):
                if not self._is_mosfpc_in_skipped_irpm():
                    self._report_pcm_mosfpc()
            elif isinstance(pcm.amod, ModifiedRepoFilePC):
                if not self._is_mrfpc_in_pim():
                    self._report_pcm_mrfpc()
            elif isinstance(pcm.amod, InstalledRPM):
                self._report_pcm_irpm()
            elif isinstance(pcm.amod, TTLocalFilePC):
                self._report_pcm_ttlfpc()
            else:
                raise RuntimeError(
                    f"Unexpected AtomicModification in PCMod:\n{pcm!r}"
                )
        finally:
            if not self._prohibit_async:
                self._tns.cleanup()
            HeartbeatManager.notify(
                ModsReporterPCModsProcessingHook.id, {"id": i_mod},
                altid=self._control_tid
            )

    def _is_mrfpc_in_pim(self):
        """Search matching to check_patches_f mod in PI summary

        Returns:
            :bool: True if found similar modifications.
        """
        found_pims = PIModsProvider.lookup(
            self._tns.pcm.servers,
            None,
            *[token for token in self._tns.pcm.amod.tokenize()],
            attrs={"amod.path": self._tns.pcm.amod.path}
        )
        if not found_pims: return False
        self._logger.debug(
            f"Got PI summary modifications matching to check_patches_f's "
            f"current:\n{found_pims!r}"
        )
        return True

    def _is_mosfpc_in_skipped_irpm(self):
        """Search matching skipped InstalledRPM for ModifiedOSFilePC

        Returns:
            :bool: True if found such an RPM.
        """
        if not self._tns.pcm.amod.path.startswith("/etc"):
            return False
        found_irpms = [
            pcm for pcm in PCModsProvider.lookup(
                self._tns.pcm.servers,
                SKIPPED_RESOLUTIONS,
                *[token for token in self._tns.pcm.amod.tokenize()],
                attrs={"amod.name": self._tns.pcm.amod.package}
            )
            if isinstance(pcm.amod, InstalledRPM)
        ]
        if not found_irpms: return False
        self._logger.debug(
            f"Got skipped InstalledRPM matching to /etc file "
            f"current:\n{found_irpms!r}"
        )
        return True

    def _report_pcm_mosfpc(self):
        """Report ModifiedOSFilePC to draw attention

        Should be called only if ModifiedOSFilePC.resolution indicates
        manual attention is required.
        """
        reason = (
            "Known OS file modification but attention required"
            if self._is_known_amod(self._tns.pcm)
            else "Unknown OS file modification"
        )
        etc_file_cmd = rf"""
            head_after_base=$(
                sudo git -C /etc rev-list --no-merges HEAD \
                | tail -2 | head -1
            )
            sudo git -C /etc diff ${{head_after_base}} {self._tns.pcm.amod.path}
        """
        os_file_cmd = rf"""
            # Checks whether file is binary
            grep -qI '' -- {self._tns.pcm.amod.path} \
            && head -1000 {self._tns.pcm.amod.path} \
            || file {self._tns.pcm.amod.path}
        """
        self._report_mod(
            self._tns.i_mod,
            [ f"  Reason: {reason}\n", f"{self._tns.pcm:indent.2}" ],
            details_function=lambda: self._run_cmd_on_pcm_affected_for_report(
                etc_file_cmd
                if self._tns.pcm.amod.path.startswith("/etc")
                else os_file_cmd
            )
        )

    def _report_pcm_mrfpc(self):
        """Report ModifiedRepoFilePC to draw attention

        Should be called only if ModifiedRepoFilePC.resolution indicates
        manual attention is required, but no suitable PI mods were found
        in PIModsProvider.
        """
        self._report_mod(
            self._tns.i_mod,
            [
                "  Reason: Unknown even for PI and unexpected\n",
                f"{self._tns.pcm:indent.2}",
            ],
            details_function=lambda: self._run_cmd_on_pcm_affected_for_report(
                f"sudo git -C $(basename {self._tns.pcm.amod.path}) "
                    f"diff {self._tns.pcm.amod.path}"
            )
        )

    def _report_pcm_irpm(self):
        """Report InstalledRPM to draw attention

        Should be called only if InstalledRPM.resolution indicates
        manual attention is required.
        """
        reason = (
            "Known installed RPM but attention required"
            if self._is_known_amod(self._tns.pcm)
            else "Unknown installed RPM"
        )
        self._report_mod(
            self._tns.i_mod,
            [ f"  Reason: {reason}\n", f"{self._tns.pcm:indent.2}" ],
            details_function=lambda: self._run_cmd_on_pcm_affected_for_report(
                f"rpm -qi {self._tns.pcm.amod.name}"
            )
        )

    def _report_pcm_ttlfpc(self):
        """Report TTLocalFilePC to draw attention

        Should be called only if TTLocalFilePC.resolution indicates
        manual attention is required.
        """
        self._report_mod(
            self._tns.i_mod,
            [
                "  Reason: .tt.local files always should be checked\n",
                f"{self._tns.pcm:indent.2}"
            ],
            details_function=lambda: self._run_cmd_on_pcm_affected_for_report(
                f"sudo diff -u "
                    f"{self._tns.pcm.amod.path} {self._tns.pcm.amod.path}.local"
            )
        )

    def _is_known_amod(self, cmod):
        """Check if AtomicModification is known

        Parameters:
            :cmod (ComplexModification): Modification object
                from some ModsProvider.

        Returns:
            :bool: True if AtomicModification is known.
        """
        return (
            cmod.amod.resolution is Resolution.MANUAL_ATTENTION_REQUIRED_KNOWN
            or cmod.amod.resolution is Resolution.NO_ATTENTION_REQUIRED_KNOWN
        )

    def _run_cmd_on_pcm_affected_for_report(self, cmd):
        """Handy wrapper around PCMod.run_cmd_on_affected()

        Parameters:
            :cmd (str): Command or Bash script to execute.
        """
        fd = TempfileBufferedFileWriter(
            self._full_output.realpath, dump_exc_to_path=True
        )
        name_params = {
            "id":      self._tns.i_mod,
        }
        desc_params = {
            "servers": multiline_list(self._tns.pcm.servers),
            "target":  fd.path,
            "script":  cmd
        }
        with HeartbeatManager.track(
            ModsReporterDetailsCollectionHook.id,
            name_params,
            desc_params,
            goal=len(self._tns.pcm.servers)
        ):
            self._tns.pcm.run_cmd_on_affected(
                cmd,
                to_fd=fd,
                ignore_err=True,
                notify_id=ModsReporterDetailsCollectionHook.id,
                parallel=(not self._prohibit_async)
            )
            fd.flush_to_file_all()

    @threadsafemethod
    def analyze_pi_mods(self, no_full=False, no_skip=False):
        """Retrieve and process problematic PI bundles and patches

        For defition of problematic see REPORT_HEADER.

        Also reports patches created in PI via pi_slurp_custom()
        or it's more recent variation as part of new default workflow.

        Parameters:
            :no_full (bool): If True then full report won't be collected.
            :no_skip (bool): If True, includes even unaffected mods.
        """
        self._logger.info("Starting PI issues check")

        self._set_report_outputs(no_full=no_full)
        self._write_both(line="\n\n# PI summary analysis and details\n\n")
        self._flush_both()

        if Facts.pi_has_mods is False:
            self._logger.warning(
                "No PI modifications was found. "
                "Please verify that it is expected"
            )
            self._write_both(
                "WARNING: No PI modifications was found. "
                "Please verify that it is expected"
            )
            self._flush_both()
            return
        elif self._check_pimp_empty():
            return

        slurp_custom = re.compile(PI_SLURP_SUBJECT_PREFIX_CSP)

        customer_patches = {}
        dirty_bundles = []
        no_csup_tt_patches = {}
        no_fixed_in_patches = {}

        for pim in PIModsProvider.lookup(None, AFFECTED_RESOLUTIONS):
            if (
                slurp_custom.search(pim.patch.subject)
                and (
                    pim.bundle not in customer_patches
                    or pim.patch not in customer_patches[pim.bundle]
                )
            ):
                customer_patches.setdefault(pim.bundle, []).append(pim.patch)
            if (
                pim.bundle.is_dirty
                and pim.bundle not in dirty_bundles
            ):
                dirty_bundles.append(pim.bundle)
            if (
                pim.patch.csup_tt is None
                and (
                    pim.bundle not in no_csup_tt_patches
                    or pim.patch not in no_csup_tt_patches[pim.bundle]
                )
            ):
                no_csup_tt_patches.setdefault(pim.bundle, []).append(pim.patch)
            if (
                pim.patch.fixed_in is None
                and (
                    pim.bundle not in no_fixed_in_patches
                    or pim.patch not in no_fixed_in_patches[pim.bundle]
                )
            ):
                no_fixed_in_patches.setdefault(pim.bundle, []).append(pim.patch)

        if customer_patches:
            self._logger.warning(
                f"Found PI patches that contain customer modifications\n"
                f"{customer_patches!r}"
            )
            self._report_pim_customer(customer_patches)
        if dirty_bundles:
            self._logger.warning(f"Found dirty PI bundles:\n{dirty_bundles!r}")
            self._report_pim_dirty(dirty_bundles)
        if no_csup_tt_patches:
            self._logger.warning(
                f"Found PI patches without Support-Ticket:\n"
                f"{no_csup_tt_patches!r}"
            )
            self._report_pim_no_csup_tt(no_csup_tt_patches)
        if no_fixed_in_patches:
            self._logger.warning(
                f"Found PI patches without Fixed-In:\n{no_fixed_in_patches!r}"
            )
            self._report_pim_no_fixed_in(no_fixed_in_patches)

        if no_skip:
            self._logger.warning("Dumping skipped PI mods as requested")
            self._report_mod(
                "Skipped PI mods",
                [
                    "  Reason: User request\n", "  List start\n"
                ] + [
                    f"\n{pim:indent.4}"
                    for pim in PIModsProvider.lookup(None, SKIPPED_RESOLUTIONS)
                ] + [ "\n  List end\n" ]
            )

        self._logger.info("Finished PI issues check")
        self._switch_facts(True)

    def _report_pim_customer(self, bundles_n_patches):
        """Report PIPatches with CUSTOMER CHANGES tag in subject

        Parameters:
            :bundles_n_patches (dict of PIBundle and list of PIPatche):
                Affected PI patches with owner bundles.
        """
        self._report_mod(
            "Customer patches",
            [
                "  Reason: Customer should reapply his patches if needed\n",
                "  List start\n"
            ] + [
                f"\n{bundle:indent.4:align.true}" + "".join(
                    f"\n{patch:indent.6:align.true}" for patch in patches
                )
                for bundle, patches in bundles_n_patches.items()
            ] + [ "\n  List end\n" ]
        )

    def _report_pim_dirty(self, bundles):
        """Report dirty PIBundles to draw attention

        Parameters:
            :bundles (list of PIBundle): Affected PI bundles.
        """
        self._report_mod(
            "Dirty bundles",
            [
                "  Reason: Bundles contain unaccounted modifications\n",
                "  List start\n"
            ] + [
                f"    {bundle:indent.0:oneline.true:align.true}"
                    .rstrip(" ")+"\n"
                for bundle in bundles
            ] + [ "  List end\n" ],
            details_function=lambda: PopenWrapper(
                [PI_APPBIN, "status", "diff"] + bundles,
                output=self._full_output,
                error=self._full_output,
                raise_exc=False
            )
        )

    def _report_pim_no_csup_tt(self, bundles_n_patches):
        """Report PIPatches without Support-Ticket to draw attention

        Parameters:
            :bundles_n_patches (dict of PIBundle and list of PIPatch):
                Affected PI patches with owner bundles.
        """
        self._report_mod(
            "Patches without Support-Ticket",
            [
                "  Reason: Unknown patch origin\n",
                "  List start\n"
            ] + [
                f"\n{bundle:indent.4:align.true}" + "".join(
                    f"\n{patch:indent.6:align.true}" for patch in patches
                )
                for bundle, patches in bundles_n_patches.items()
            ] + [ "\n  List end\n" ]
        )

    def _report_pim_no_fixed_in(self, bundles_n_patches):
        """Report PIPatches without Fixed-In to draw attention

        Parameters:
            :bundles_n_patches (dict of PIBundle and list of PIPatch):
                Affected PI patches with owner bundles.
        """
        self._report_mod(
            "Patches without Fixed-In",
            [

                "  Reason: Patch will be reapplied every update\n",
                "  List start\n"
            ] + [
                f"\n{bundle:indent.4:align.true}" + "".join(
                    f"\n{patch:indent.6:align.true}" for patch in patches
                )
                for bundle, patches in bundles_n_patches.items()
            ] + [ "\n  List end\n" ]
        )

    def _switch_facts(self, to):
        """Switches facts related to report outputs properly

        Switch is performed per each output only if:
        - Output is active (set by self._set_report_outputs()).
        - Output isn't marked as failed before.

        Parameters:
            :to (bool): State to set.
        """
        if self._compact_output and not (
            to is True and Facts.mods_compact_created is False
        ):
            Facts.mods_compact_created = to
        if self._full_output and not (
            to is True and Facts.mods_full_created is False
        ):
            Facts.mods_full_created = to

    def _write_both(self, line=None, lines=None):
        """Write to both output files simultaneously

        Parameters:
            :line (str|None): String to write using write().
            :lines (list of str|None): Strings to write using writelines().

        Raises:
            :ValueError: If no parameters provided.
        """
        if (not line and not lines) or (line and lines):
            raise ValueError(
                f"Either single line or list of lines should be provided; "
                f"failed in:\n{self}"
            )
        for fd in (self._compact_output, self._full_output):
            if not fd:
                continue
            if line:
                fd.write(line)
            if lines:
                fd.writelines(lines)

    @staticmethod
    def gen_separator(label):
        """Generate separator for report output

        Parameters:
            :label (str): Meta to put in separator center.

        Returns:
            :str: Generated separator.
        """
        return f" {label} ".center(
            REPORT_SEPARATOR_WIDTH, REPORT_SEPARATOR_SYMBOL
        )

    def _report_mod(self, i_mod, meta_extension, details_function=None):
        """Report AtomicModification requiring attention

        Parameters:
            :i_mod (int|str): Incremental ID of current modification or label.
            :meta_extension (list of str): Extra metadata to include.
            :report_details (callable): Function to report details.
        """
        metadata = [
            f"\n{self.gen_separator(f'ID #{{{i_mod}}} metadata')}\n",
        ]
        metadata.extend(meta_extension)

        self._write_both(lines=metadata)

        if self._full_output and details_function:
            self._full_output.write(
                f"{self.gen_separator(f'ID #{{{i_mod}}} details start')}"
            )
            details_function()
            self._full_output.write(
                f"{self.gen_separator(f'ID #{{{i_mod}}} details end')}\n"
            )

        self._flush_both()

    def _flush_both(self):
        """Flush both output buffers simultaneously"""
        for buf in (self._compact_output, self._full_output):
            if buf:
                buf.flush_to_file()

