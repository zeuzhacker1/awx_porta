# collect-pre-update-data patches_inventory mode initial objects


import argparse
import pathlib
import shutil

from libs.defaults import (TMP_DIR,
                           EXPECTED_REPO_CHANGES_IGNORED,
                           EXPECTED_REPO_CHANGES_WARNING,
                           PI_SUMMARY_FIELDS_ORDER)
from libs.format import multiline_list
from libs.heartbeat import SubmodeGeneralHook, HeartbeatManager
from libs.mode_generic import (GENERIC_EMAIL_SUBJECT, GENERIC_EMAIL_BODY,
                               ModeGeneric)
from libs.patches_inventory import PIModsParser, PIModsProvider
from libs.runtime import Facts
from libs.sender import Sender


DESC_PATCHES_INVENTORY = f"""
Execute Patches Inventory summary collection and parsing separately.
This mode collects the summary CSV output from PI and parses it,
producing an intermediate dump of parsed objects. Useful for manual
collection or parser testing.

PI summary fields required for parser and their order:
{multiline_list(PI_SUMMARY_FIELDS_ORDER)}
"""
SHORT_DESC_PATCHES_INVENTORY = "collect and parse PI summary output"
ARG_DESC_PATCHES_INVENTORY_FILE_PI_SUMMARY_OUTPUT = (
    "file with pre-collected PI summary CSV output to parse instead\n"
    "of collecting again when not needed"
)
ARG_DESC_PATCHES_INVENTORY_NO_STATUS_UPDATE = (
    "don't update status before running; not recommended, as\n"
    "outdated data may be collected"
)


PATCHES_INVENTORY_EMAIL_SUBJECT_PROCESSED = (
    "PI summary output collected and parsed"
)
PATCHES_INVENTORY_EMAIL_BODY_PROCESSED = (
    "Nota bene: you shouldn't use raw PI output in most cases.\n"
    "Better feed it to the suite in mods-reporter mode, this will be easier."
)
PATCHES_INVENTORY_EMAIL_SUBJECT_COLLECTION_FAILED = (
    "PI summary output collection FAILED!"
)
PATCHES_INVENTORY_EMAIL_BODY_COLLECTION_FAILED = (
    "Please proceed with the following:\n"
    "1. Investigate attached output.\n"
    "2. Fix or submit issues found in it.\n"
    "3. DO NOT EXECUTE UPDATE UNLESS MODIFICATIONS COLLECTED!\n\n"
    "Hints:\n"
    "- Make sure PI itself is installed and initialized.\n"
    "- There shouldn't be any unknown modifications.\n"
    "- Suite execution log might be helpful and usually sent to ticket too."
)
PATCHES_INVENTORY_EMAIL_SUBJECT_PARSING_FAILED = (
    "PI summary output parsing FAILED!"
)
#TODO: once PI-240 resolved:
# - Remove this thing.
PATCHES_INVENTORY_EMAIL_SUBJECT_PARSING_FAILED__PI_240 = (
    PATCHES_INVENTORY_EMAIL_SUBJECT_PARSING_FAILED
)
PATCHES_INVENTORY_EMAIL_BODY_PARSING_FAILED = (
    "Please proceed with the following:\n"
    "1. Investigate attached output.\n"
    "2. Fix or submit issues found in it.\n"
    "3. DO NOT EXECUTE UPDATE UNLESS MODIFICATIONS PARSED!\n\n"
    "Hints:\n"
    "- Likely this is the issue in the suite itself.\n"
    "- Suite execution log might be helpful and usually sent to ticket too."
)
#TODO: once PI-240 resolved:
# - Remove this thing.
PATCHES_INVENTORY_EMAIL_BODY_PARSING_FAILED__PI_240 = (
    "Please proceed with the following:\n"
    "1. Escalate the issue to PI-240 providing attached data.\n"
    "2. DO NOT EXECUTE UPDATE UNLESS MODIFICATIONS PARSED!\n\n"
)


#: dict of list or dict of str: Pattern sets loaded into Regex at startup.
PATCHES_INVENTORY_REQUIRED_REGEXES = {
    "EXPECTED_REPO_CHANGES_IGNORED": EXPECTED_REPO_CHANGES_IGNORED,
    "EXPECTED_REPO_CHANGES_WARNING": EXPECTED_REPO_CHANGES_WARNING
}


class ModePatchesInventory(ModeGeneric):
    """patches_inventory mode static representation"""

    @staticmethod
    def setup_subparser(subparsers):
        """Interface method implementation"""
        subparser = subparsers.add_parser(
            "patches-inventory",
            help=SHORT_DESC_PATCHES_INVENTORY,
            description=DESC_PATCHES_INVENTORY,
            formatter_class=argparse.RawTextHelpFormatter
        )
        subparser.add_argument(
            "-fp", "--file-pi-summary-output",
            help=ARG_DESC_PATCHES_INVENTORY_FILE_PI_SUMMARY_OUTPUT
        )
        subparser.add_argument(
            "-n", "--no-status-update", action="store_true",
            help=ARG_DESC_PATCHES_INVENTORY_NO_STATUS_UPDATE
        )

    @staticmethod
    def run_mode(args, logger, no_send=False):
        """Run patches_inventory mode

        Collects new data or uses pre-collected file to run the parser.
        ModsReporter is not started in this mode. Useful for testing.

        #TODO: once PI-240 resolved:
        # - Restore normal flow.
        """
        ModePatchesInventory.run_mode__pi_240(args, logger, no_send=no_send)

    @staticmethod
    def run_mode__normal(args, logger, no_send=False):
        """Run patches_inventory mode

        Collects new data or uses pre-collected file to run the parser.
        ModsReporter is not started in this mode. Useful for testing.

        #TODO: once PI-240 resolved:
        # - Move back to ModePatchesInventory.run_mode.
        """
        is_config_mode_my = args.mode == "patches-inventory"
        with HeartbeatManager.track(
            SubmodeGeneralHook.id,
            {"name": (
                "patches-inventory "
                if is_config_mode_my
                else "patches-inventory sub"
            )},
            {"desc": SHORT_DESC_PATCHES_INVENTORY}
        ):
            param_no_update = False

            if is_config_mode_my:
                Facts.pi_output_path = args.file_pi_summary_output
                param_no_update = args.no_status_update

            ModeGeneric.setup_regex(PATCHES_INVENTORY_REQUIRED_REGEXES, logger)
            PIModsParser().main(no_update=param_no_update)

            if not Facts.no_pi_index_dump:
                logger.info("Dumping parsed PI objects")
                PIModsProvider().dump()

            if no_send or not Facts.csup_tt or not Facts.pi_output_path:
                return

            send_required = False
            is_config_mode_my_required = True
            subject = GENERIC_EMAIL_SUBJECT
            body = GENERIC_EMAIL_BODY
            attach_type = "generic_"

            if Facts.pi_output_parsed is False and Facts.pi_has_mods is True:
                send_required = True
                is_config_mode_my_required = False
                subject = PATCHES_INVENTORY_EMAIL_SUBJECT_PARSING_FAILED
                body = PATCHES_INVENTORY_EMAIL_BODY_PARSING_FAILED
                attach_type = "failed_"

            elif Facts.pi_output_collected is True:
                send_required = True
                subject = PATCHES_INVENTORY_EMAIL_SUBJECT_PROCESSED
                body = PATCHES_INVENTORY_EMAIL_BODY_PROCESSED
                attach_type = ""

            elif Facts.pi_output_collected is False and Facts.pi_has_mods is True:
                send_required = True
                is_config_mode_my_required = False
                subject = PATCHES_INVENTORY_EMAIL_SUBJECT_COLLECTION_FAILED
                body = PATCHES_INVENTORY_EMAIL_BODY_COLLECTION_FAILED
                attach_type = "failed_"

            if not send_required:
                return
            if is_config_mode_my_required and not is_config_mode_my:
                return

            Sender.send(
                subject,
                body,
                attach=Facts.pi_output_path,
                attach_as=(
                    f"cpud.{attach_type}pi_output."
                    f"{Facts.start_epoch}.txt"
                )
            )

    @staticmethod
    def run_mode__pi_240(args, logger, no_send=False):
        """Run patches_inventory mode

        Collects new data or uses pre-collected file to run the parser.
        ModsReporter is not started in this mode. Useful for testing.

        #TODO: once PI-240 resolved:
        # - Remove this alternative.
        """
        is_config_mode_my = args.mode == "patches-inventory"
        with HeartbeatManager.track(
            SubmodeGeneralHook.id,
            {"name": (
                "patches-inventory "
                if is_config_mode_my
                else "patches-inventory sub"
            )},
            {"desc": SHORT_DESC_PATCHES_INVENTORY}
        ):
            param_no_update = False

            if is_config_mode_my:
                Facts.pi_output_path = args.file_pi_summary_output
                param_no_update = args.no_status_update

            ModeGeneric.setup_regex(PATCHES_INVENTORY_REQUIRED_REGEXES, logger)
            PIModsParser().main(no_update=param_no_update)

            if not Facts.no_pi_index_dump:
                logger.info("Dumping parsed PI objects")
                PIModsProvider().dump()

            if no_send or not Facts.csup_tt or not Facts.pi_output_path:
                return

            send_required = False
            is_config_mode_my_required = True
            subject = GENERIC_EMAIL_SUBJECT
            body = GENERIC_EMAIL_BODY
            attach_type = "generic_"

            pack_target = None
            attach = None
            attach_as = None

            if Facts.pi_output_parsed is False and Facts.pi_has_mods is True:
                send_required = True
                is_config_mode_my_required = False
                subject = PATCHES_INVENTORY_EMAIL_SUBJECT_PARSING_FAILED__PI_240
                body = PATCHES_INVENTORY_EMAIL_BODY_PARSING_FAILED__PI_240
                attach_type = "failed_"

                pack_target = pathlib.Path(
                    f"{TMP_DIR}/backup_{Facts.backup_id}."
                    f"{Facts.start_epoch}."
                    f"patches_inventory.affecteds"
                )
                pack_target.mkdir(parents=True, exist_ok=True)

                shutil.copytree(
                    Facts.pi_tmpdir_path, f"{pack_target}/pi_tmpdir"
                )
                shutil.copy2(
                    Facts.pi_xtrace_n_output_path,
                    f"{pack_target}/pi_xtrace_n_output.txt"
                )
                shutil.copy2(
                    Facts.pi_output_path,
                    f"{pack_target}/pi_output.txt"
                )
                attach = str(pack_target)
                attach_as = (
                    f"cpud.{attach_type}pi_tmps_n_xtrace_n_ouput."
                    f"{Facts.start_epoch}.zip"
                )

            elif Facts.pi_output_collected is True:
                send_required = True
                subject = PATCHES_INVENTORY_EMAIL_SUBJECT_PROCESSED
                body = PATCHES_INVENTORY_EMAIL_BODY_PROCESSED
                attach_type = ""

            elif Facts.pi_output_collected is False and Facts.pi_has_mods is True:
                send_required = True
                is_config_mode_my_required = False
                subject = PATCHES_INVENTORY_EMAIL_SUBJECT_COLLECTION_FAILED
                body = PATCHES_INVENTORY_EMAIL_BODY_COLLECTION_FAILED
                attach_type = "failed_"

            if not send_required:
                return
            if is_config_mode_my_required and not is_config_mode_my:
                return

            attach = attach or Facts.pi_xtrace_n_output_path
            attach_as = attach_as or (
                f"cpud.{attach_type}pi_xtrace_n_output."
                f"{Facts.start_epoch}.txt"
            )
            Sender.send(
                subject,
                body,
                attach=attach,
                attach_as=attach_as
            )
            if pack_target:
                shutil.rmtree(str(pack_target))

