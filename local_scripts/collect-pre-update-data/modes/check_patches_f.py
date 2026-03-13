# collect-pre-update-data check-patches-f mode initial objects


import argparse

from libs.check_patches_f import PCModsParser, PCModsProvider
from libs.defaults import (EXPECTED_OS_CHANGES_IGNORED,
                           EXPECTED_OS_CHANGES_WARNING,
                           EXPECTED_REPO_CHANGES_IGNORED,
                           EXPECTED_REPO_CHANGES_WARNING,
                           EXPECTED_INSTALLED_RPMS_IGNORED,
                           EXPECTED_INSTALLED_RPMS_WARNING,
                           CHECK_PATCHES_F_REGEX_MAP, RPM_NAME)
from libs.heartbeat import SubmodeGeneralHook, HeartbeatManager
from libs.mode_generic import (GENERIC_EMAIL_SUBJECT, GENERIC_EMAIL_BODY,
                               ModeGeneric)
from libs.patches_inventory import get_pi_pkgdir_regexes
from libs.runtime import Facts
from libs.sender import Sender


DESC_CHECK_PATCHES_F = """
Execute check_patches_f collection and parsing separately. This mode
will collect check_patches_f similarly to the legacy pre-update script
and parse it, producing an intermediate dump of parsed objects. Useful
for manual collection or parser testing.
"""
SHORT_DESC_CHECK_PATCHES_F = "collect and parse check_patches_f output"
ARG_DESC_CHECK_PATCHES_F_FILE_PC_SCRIPT_OUTPUT = (
    "file with pre-collected check_patches_f output to parse instead\n"
    "of collecting again when not needed"
)


CHECK_PATCHES_F_EMAIL_SUBJECT_PROCESSED = (
    "PC check_patches_f output collected and parsed"
)
CHECK_PATCHES_F_EMAIL_BODY_PROCESSED = (
    "Nota bene: you shouldn't use raw PC output in most cases.\n"
    "Better feed it to the suite in mods-reporter mode, this will be easier."
)
CHECK_PATCHES_F_EMAIL_SUBJECT_COLLECTION_FAILED = (
    "PC check_patches_f output collection FAILED!"
)
CHECK_PATCHES_F_EMAIL_BODY_COLLECTION_FAILED = (
    "Please proceed with the following:\n"
    "1. Investigate attached output.\n"
    "2. Fix or submit issues found in it.\n"
    "3. DO NOT EXECUTE UPDATE UNLESS MODIFICATIONS COLLECTED!\n\n"
    "Hints:\n"
    "- Make sure PC's check_patches_f script itself is working normally.\n"
    "- Suite execution log might be helpful and usually sent to ticket too."
)
CHECK_PATCHES_F_EMAIL_SUBJECT_PARSING_FAILED = (
    "PC check_patches_f output parsing FAILED!"
)
CHECK_PATCHES_F_EMAIL_BODY_PARSING_FAILED = (
    "Please proceed with the following:\n"
    "1. Investigate attached output.\n"
    "2. Fix or submit issues found in it.\n"
    "3. DO NOT EXECUTE UPDATE UNLESS MODIFICATIONS PARSED!\n\n"
    "Hints:\n"
    "- Likely this is the issue in the suite itself.\n"
    "- Suite execution log might be helpful and usually sent to ticket too.\n"
)


#: dict of list or dict of str: Pattern sets loaded into Regex at startup.
CHECK_PATCHES_F_REQUIRED_REGEXES = {
    "EXPECTED_OS_CHANGES_IGNORED":     EXPECTED_OS_CHANGES_IGNORED,
    "EXPECTED_OS_CHANGES_WARNING":     EXPECTED_OS_CHANGES_WARNING,
    "EXPECTED_REPO_CHANGES_IGNORED":   EXPECTED_REPO_CHANGES_IGNORED,
    "EXPECTED_REPO_CHANGES_WARNING":   EXPECTED_REPO_CHANGES_WARNING,
    "EXPECTED_INSTALLED_RPMS_IGNORED": EXPECTED_INSTALLED_RPMS_IGNORED,
    "EXPECTED_INSTALLED_RPMS_WARNING": EXPECTED_INSTALLED_RPMS_WARNING,
    "CHECK_PATCHES_F_REGEX_MAP":       CHECK_PATCHES_F_REGEX_MAP,
    "RPM_NAME":                        [RPM_NAME]
}


class ModeCheckPatchesF(ModeGeneric):
    """check_patches_f mode static representation"""

    @staticmethod
    def setup_subparser(subparsers):
        """Interface method implementation"""
        subparser = subparsers.add_parser(
            "check-patches-f",
            help=SHORT_DESC_CHECK_PATCHES_F, description=DESC_CHECK_PATCHES_F,
            formatter_class=argparse.RawTextHelpFormatter
        )
        subparser.add_argument(
            "-fc", "--file-pc-script-output",
            help=ARG_DESC_CHECK_PATCHES_F_FILE_PC_SCRIPT_OUTPUT
        )

    @staticmethod
    def run_mode(args, logger, no_send=False):
        """Run check_patches_f mode

        Collects new data or uses pre-collected file to run parser.
        ModsReporter is not used in this mode. Useful for testing.
        """
        is_config_mode_my = args.mode == "check-patches-f"
        with HeartbeatManager.track(
            SubmodeGeneralHook.id,
            {"name": (
                "check-patches-f "
                if is_config_mode_my
                else "check-patches-f sub"
            )},
            {"desc": SHORT_DESC_CHECK_PATCHES_F}
        ):
            if is_config_mode_my:
                Facts.pc_output_path = args.file_pc_script_output

            CHECK_PATCHES_F_REQUIRED_REGEXES["PI_PKGDIRS"] = get_pi_pkgdir_regexes()
            ModeGeneric.setup_regex(CHECK_PATCHES_F_REQUIRED_REGEXES, logger)
            PCModsParser().main()

            if not Facts.no_pc_index_dump:
                logger.info("Dumping parsed PC objects")
                PCModsProvider().dump()

            if no_send or not Facts.csup_tt or not Facts.pc_output_path:
                return

            send_required = False
            is_config_mode_my_required = True
            subject = GENERIC_EMAIL_SUBJECT
            body = GENERIC_EMAIL_BODY
            attach_type = "generic_"

            if Facts.pc_output_parsed is False:
                send_required = True
                is_config_mode_my_required = False
                subject = CHECK_PATCHES_F_EMAIL_SUBJECT_PARSING_FAILED
                body = CHECK_PATCHES_F_EMAIL_BODY_PARSING_FAILED
                attach_type = "failed_"

            elif Facts.pc_output_collected is True:
                send_required = True
                subject = CHECK_PATCHES_F_EMAIL_SUBJECT_PROCESSED
                body = CHECK_PATCHES_F_EMAIL_BODY_PROCESSED
                attach_type = ""

            elif Facts.pc_output_collected is False:
                send_required = True
                is_config_mode_my_required = False
                subject = CHECK_PATCHES_F_EMAIL_SUBJECT_COLLECTION_FAILED
                body = CHECK_PATCHES_F_EMAIL_BODY_COLLECTION_FAILED
                attach_type = "failed_"

            if not send_required:
                return
            if is_config_mode_my_required and not is_config_mode_my:
                return

            Sender.send(
                subject,
                body,
                attach=Facts.pc_output_path,
                attach_as=(
                    f"cpud.{attach_type}pc_output."
                    f"{Facts.start_epoch}.txt"
                )
            )

