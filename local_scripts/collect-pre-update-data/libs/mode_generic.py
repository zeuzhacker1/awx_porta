# collect-pre-update-data mode generic initial objects


from libs.runtime import Regex
from libs.objects import interfacemethod, MetaStaticInterface


GENERIC_EMAIL_SUBJECT = "if you see this then some nasty error happened"
GENERIC_EMAIL_BODY = "there should be some appropriate message"


class ModeGeneric(metaclass=MetaStaticInterface):
    """Mode abstract representation for contract"""

    @staticmethod
    @interfacemethod
    def setup_subparser(subparsers):
        """Setup suite subparser for particular mode

        Parameters:
            :subparsers (argparse._SubParsersAction): Special action
                object to create and manage new subparsers.
        """
        pass

    @staticmethod
    @interfacemethod
    def run_mode(args, logger, no_send=True):
        """Execute particular mode

        Parameters:
            :args (argparse.Namespace): Parsed args.
            :logger (logging.Logger): Logger from the calling context.
            :no_send (bool): If True then data won't be sent to ticket.
        """
        pass

    @staticmethod
    def setup_regex(patterns_set, logger, no_err=True):
        """Precompile patterns in regex provider

        Patterns:
            :patterns_set (dict of list or dict of str): Lists of
                patterns to load and their names.
            :logger (logging.Logger): Logger from the calling context.
            :no_err (bool): If True then no RuntimeError will be raised
                in case of duplicate name.
        """
        logger.info("Loading regular expression set")
        for name, patterns in patterns_set.items():
            if not patterns: continue
            logger.debug(f"Precompiling {name} patterns")
            Regex.load(name, patterns, no_err)

