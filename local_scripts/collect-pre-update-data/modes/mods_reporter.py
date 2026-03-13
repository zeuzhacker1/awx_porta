# collect-pre-update-data mods-reporter mode initial objects


import argparse

from libs.common import ParanoidThreadPoolExecutor
from libs.format import indent_strs
from libs.heartbeat import SubmodeGeneralHook, HeartbeatManager
from libs.mode_generic import ModeGeneric
from libs.mods_reporter import ModsReporter
from libs.runtime import get_my_tid, Facts
from libs.sender import Sender
from modes.check_patches_f import ModeCheckPatchesF
from modes.patches_inventory import ModePatchesInventory


DESC_MODS_REPORTER = """
Execute check-patches-f and patches-inventory submodes and analyze data
collected by them. I.e., compare modifications known to PC and PI.
"""
SHORT_DESC_MODS_REPORTER = "collect and analyze local modifications"
ARG_DESC_MODS_REPORTER_FILE_PC_SCRIPT_OUTPUT = (
    "file with pre-collected check_patches_f output to parse instead\n"
    "of collecting again when not needed"
)
ARG_DESC_MODS_REPORTER_FILE_PI_SUMMARY_OUTPUT = (
    "file with pre-collected PI summary CSV output to parse instead\n"
    "of collecting again when not needed"
)
ARG_DESC_MODS_REPORTER_NO_DIFFS = (
    "don't collect diffs even if it's an unknown modification;\n"
    "only compact output will be produced"
)
ARG_DESC_MODS_REPORTER_ALL = (
    "include all modifications in the report, even those that\n"
    "does not require manual attention or additional checks"
)
ARG_DESC_MODS_REPORTER_NO_ASYNC = (
    "process parsed modifications synchronously, needed for synthetic\n"
    "tests does have effect on parsers execution"
)
ARG_DESC_MODS_REPORTER_DUMP = "dump parsed objects stored in providers"


MODS_REPORTER_EMAIL_SUBJECT_COMPACT_CREATED = (
    "modifications compact report created"
)
MODS_REPORTER_EMAIL_BODY_COMPACT_CREATED = (
    "You are to analyze the attached report:\n"
    "- No modifications shown in it should be left without attention.\n"
    "- You should provide clear resolutions on each reported modification.\n"
    "- You might find full report version useful if you need more data.\n"
    "- If some modification should be ignored by default then submit it."
)
MODS_REPORTER_EMAIL_SUBJECT_COMPACT_FAILED = (
    "modifications compact report FAILED!"
)
MODS_REPORTER_EMAIL_BODY_COMPACT_FAILED = (
    "Please proceed with the following:\n"
    "1. Investigate attached output.\n"
    "2. Fix or submit issues found in it.\n"
    "3. DO NOT EXECUTE UPDATE UNLESS MODIFICATIONS ANALYZED!\n\n"
    "Hints:\n"
    "- Make sure check-patches-f mode was executed without issues.\n"
    "- Make sure patches-inventory mode was executed without issues.\n"
    "- Suite execution log might be helpful and usually sent to ticket too."
)
MODS_REPORTER_EMAIL_SUBJECT_FULL_CREATED = (
    "modifications full report created"
)
MODS_REPORTER_EMAIL_BODY_FULL_CREATED = (
    "Use it with compact report if you need details like diffs and others.\n"
    "Modifications IDs are always the same between compact and full report."
)
MODS_REPORTER_EMAIL_SUBJECT_FULL_FAILED = (
    "modifications full report FAILED!"
)
MODS_REPORTER_EMAIL_BODY_FULL_FAILED = (
    "Proceed with the same instructions as for the compact report."
)
MODS_REPORTER_EMAIL_SUBJECT_OLD_SCRIPTS_OUTPUT = (
    "OLD PATCHES SCRIPT OUTPUT ATTACHED"
)
MODS_REPORTER_EMAIL_BODY_OLD_SCRIPTS_OUTPUT = (
    "Likely there's no need falling back to old scripts.\n"
    "The suite collects same check_patches_f output."
)


class ModeModsReporter(ModeGeneric):
    """mods_reporter mode static representation"""

    @staticmethod
    def setup_subparser(subparsers):
        """Interface method implementation"""
        subparser = subparsers.add_parser(
            "mods-reporter",
            help=SHORT_DESC_MODS_REPORTER, description=DESC_MODS_REPORTER,
            formatter_class=argparse.RawTextHelpFormatter
        )
        subparser.add_argument(
            "-fc", "--file-pc-script-output",
            help=ARG_DESC_MODS_REPORTER_FILE_PC_SCRIPT_OUTPUT
        )
        subparser.add_argument(
            "-fp", "--file-pi-summary-output",
            help=ARG_DESC_MODS_REPORTER_FILE_PI_SUMMARY_OUTPUT
        )
        subparser.add_argument(
            "-nd", "--no-diffs", action="store_true",
            help=ARG_DESC_MODS_REPORTER_NO_DIFFS
        )
        subparser.add_argument(
            "-a", "--all", action="store_true",
            help=ARG_DESC_MODS_REPORTER_ALL
        )
        subparser.add_argument(
            "-na", "--no-async", action="store_true",
            help=ARG_DESC_MODS_REPORTER_NO_ASYNC
        )
        subparser.add_argument(
            "-d", "--dump", action="store_true",
            help=ARG_DESC_MODS_REPORTER_DUMP
        )

    @staticmethod
    def run_mode(args, logger, no_send=False):
        """Run mods_reporter mode

        Runs check_patches_f and patches_inventory in parallel threads.
        Then starts mods_reporter.
        """
        def _exec_submode(name, method):
            method(args, logger)
            HeartbeatManager.notify(
                SubmodeGeneralHook.id, {"name": name}, altid=tid
            )
        is_config_mode_my = args.mode == "mods-reporter"
        with HeartbeatManager.track(
            SubmodeGeneralHook.id,
            {"name": (
                "mods-reporter "
                if is_config_mode_my
                else "mods-reporter sub"
            )},
            {"desc": SHORT_DESC_MODS_REPORTER},
            goal=3
        ):
            param_no_diffs = False
            param_all = False
            param_no_async = False
            param_dump = False

            if is_config_mode_my:
                param_no_diffs = args.no_diffs
                param_all = args.all
                param_no_async = args.no_async
                param_dump = args.dump
                Facts.pc_output_path = args.file_pc_script_output
                Facts.pi_output_path = args.file_pi_summary_output

            Facts.no_pc_index_dump = not param_dump
            Facts.no_pi_index_dump = not param_dump

            tid = get_my_tid()
            submodes = {
                "check-patches-f":   ModeCheckPatchesF.run_mode,
                "patches-inventory": ModePatchesInventory.run_mode
            }
            if param_no_async:
                for name, method in submodes.items():
                    _exec_submode(name, method)
            else:
                with ParanoidThreadPoolExecutor(max_workers=2) as pool:
                    for name, method in submodes.items():
                        pool.submit(_exec_submode, name, method)
                    for future in pool.iter_completed():
                        future.result()

            try:
                ModsReporter().main(
                    no_diffs=param_no_diffs, all=param_all, no_async=param_no_async
                )
            except Exception:
                logger.error(
                    f"Modifications report creation failed:\n"
                    f"{indent_strs(MODS_REPORTER_EMAIL_BODY_COMPACT_FAILED)}\n\n",
                    exc_info=True
                )
                Facts.mods_compact_created = False
                Facts.mods_full_created = False

            if no_send or not Facts.csup_tt:
                return

            if (
                Facts.mods_compact_output
                and Facts.mods_compact_created is not None
            ):
                if Facts.mods_compact_created:
                    subject = MODS_REPORTER_EMAIL_SUBJECT_COMPACT_CREATED
                    body = MODS_REPORTER_EMAIL_BODY_COMPACT_CREATED
                    attach_type = ""
                else:
                    subject = MODS_REPORTER_EMAIL_SUBJECT_COMPACT_FAILED
                    body = MODS_REPORTER_EMAIL_BODY_COMPACT_FAILED
                    attach_type = "failed_"
                Sender.send(
                    subject,
                    body,
                    attach=Facts.mods_compact_output,
                    attach_as=(
                        f"cpud.{attach_type}mods_report_compact."
                        f"{Facts.start_epoch}.txt"
                    )
                )
            if (
                Facts.mods_full_output
                and Facts.mods_full_created is not None
            ):
                if Facts.mods_full_created:
                    subject = MODS_REPORTER_EMAIL_SUBJECT_FULL_CREATED
                    body = MODS_REPORTER_EMAIL_BODY_FULL_CREATED
                    attach_type = ""
                else:
                    subject = MODS_REPORTER_EMAIL_SUBJECT_FULL_FAILED
                    body = MODS_REPORTER_EMAIL_BODY_FULL_FAILED
                    attach_type = "failed_"
                Sender.send(
                    subject,
                    body,
                    attach=Facts.mods_full_output,
                    attach_as=(
                        f"cpud.{attach_type}mods_report_full."
                        f"{Facts.start_epoch}.txt"
                    )
                )
            if (
                Facts.pc_output_collected
                and (
                    not Facts.mods_compact_created
                    or not Facts.mods_full_created
                )
            ):
                Sender.send(
                    MODS_REPORTER_EMAIL_SUBJECT_OLD_SCRIPTS_OUTPUT,
                    MODS_REPORTER_EMAIL_BODY_OLD_SCRIPTS_OUTPUT,
                    attach=Facts.pc_output_path,
                    attach_as=(
                        f"cpud.old_scripts_output.{Facts.start_epoch}.txt"
                    )
                )

