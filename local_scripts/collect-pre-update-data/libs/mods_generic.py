# collect-pre-update-data modifications generic objects


import abc
import enum
import threading

from libs.format import (dump_object_multiline_pairs,
                         dump_object_oneline_reference,
                         AtomicModificationReport,
                         ModifiedFileReport,
                         ComplexModificationReport)
from libs.objects import is_matching_object, threadsafemethod
from libs.servers import run_cmd_on_iter


class UnexpectedInput(RuntimeError):
    """Handy exception to indicate parser error

    Use when parser receives unexpected input, e.g., a line that doesn't
    match the current parser state.
    """


class Resolution(enum.IntEnum):
    """Modified object resolutions map"""

    #: int: Usually OS and other files not controlled by PI.
    MANUAL_ATTENTION_REQUIRED_UNKNOWN = enum.auto()
    #: int: Files controlled by PI but without Fixed-In.
    MANUAL_ATTENTION_REQUIRED_KNOWN = enum.auto()
    #: int: OS files expected but not managed by PI.
    NO_ATTENTION_REQUIRED_UNKNOWN = enum.auto()
    #: int: Files controlled by PI and Fixed-In is present.
    NO_ATTENTION_REQUIRED_KNOWN = enum.auto()

    def desc(self):
        """Return human readable description of resolution"""
        return {
            Resolution.MANUAL_ATTENTION_REQUIRED_UNKNOWN: (
                "Manual attention required, unknown to default filters"
            ),
            Resolution.MANUAL_ATTENTION_REQUIRED_KNOWN: (
                "Manual attention required, forced by default filters"
            ),
            Resolution.NO_ATTENTION_REQUIRED_UNKNOWN: (
                "No attention required, forced by default filters"
            ),
            Resolution.NO_ATTENTION_REQUIRED_KNOWN: (
                "No attention required at all"
            )
        }[self]


class AtomicModification(abc.ABC):
    """Atomic modification abstract representation for contract

    An atomic modification represents a single modified aspect of a
    server, such as a file, installed RPM, etc.
    """

    def __init__(self, resolution, is_ignored, is_warning):
        """Initializer

        Parameters:
            :resolution (Resolution): Resolution of the mod.
            :is_ignored (bool): Set to True if the mod should
                be ignored in the final report.
            :is_warning (bool): Set to True if the mod
                is expected but the user attention required.

        Raises:
            :ValueError: If wrong instance passed as resolution.
        """
        if not isinstance(resolution, Resolution):
            raise ValueError(
                f"Invalid resolution passed; should be one of "
                f"{list(Resolution)}; passed: {resolution!r}"
            )
        self.resolution = resolution
        self.is_ignored = is_ignored
        self.is_warning = is_warning

    def __repr__(self):
        """Representor for devel"""
        return dump_object_oneline_reference(self, mask_protected=True)

    def __str__(self):
        """Representor for user"""
        return AtomicModificationReport(self)

    def __format__(self, spec):
        """Representor with format"""
        return AtomicModificationReport(self, spec=spec)

    @abc.abstractmethod
    def identify(self):
        """Handy switcher for inheritors

        Returns:
            :tuple of str and Any: Name of attribute that acts as unique
                identifier and its value.
        """
        return (str(), None)

    @abc.abstractmethod
    def tokenize(self):
        """Handy switcher for inheritors

        Returns:
            :tuple of str: Identifier divided to index tokens.
        """
        return tuple()

class ModifiedFile(AtomicModification):
    """Modified file representation

    Generic class for more specific file types detected by
    check_patches_f PCUP script or PI summary module.
    """

    def __init__(self, path, package, *args, **kwargs):
        """Initializer

        Parameters:
            :path (str): Path to the observed modified file.
            :package (None|str): RPM or PI package owning the file.
        """
        super().__init__(*args, **kwargs)
        self.path = path
        self.package = package

    def __str__(self):
        """Representor for user"""
        return ModifiedFileReport(self)

    def __format__(self, spec):
        """Representor with format"""
        return ModifiedFileReport(self, spec=spec)

    def identify(self):
        """Abstract method implementation"""
        return ("path", self.path)

    def tokenize(self):
        """Abstract method implementation"""
        tokens = self.identify()[1].split("/")[1:][:-1]
        return tuple(tokens)


class ComplexModification(abc.ABC):
    """Complex modification abstract representation for contract

    Unlike atomic ones, a complex modification provides additional
    metadata for an atomic modification and exposes a unified public
    interface to interact with it.
    """

    def __init__(self, amod, servers):
        """Initializer

        Parameters:
            :amod (AtomicModification): Any subclass instance.
            :servers (list of Server): Where the modification exists.

        Raises:
            :ValueError: If wrong amod instance is passed.
                If invalid servers instance is passed.
        """
        if not isinstance(amod, AtomicModification):
            raise ValueError(
                f"Invalid amod passed; should be subclass of "
                f"AtomicModification; passed: {amod!r}"
            )
        if not isinstance(servers, list):
            raise ValueError(
                f"Invalid servers passed; should be list; passed: {servers!r}"
            )
        self.amod = amod
        self.servers = servers

    def __repr__(self):
        """Representor for devel"""
        return dump_object_multiline_pairs(self, mask_protected=True)

    def __str__(self):
        """Representor for user"""
        return ComplexModificationReport(self)

    def __format__(self, spec):
        """Representor with format"""
        return ComplexModificationReport(self, spec=spec)

    def run_cmd_on_affected(self, *args, **kwargs):
        """Run command on all affected servers

        Behavior is identical to run_cmd_on_iter().
        """
        return run_cmd_on_iter(self.servers, *args, **kwargs)


class IndexNode:
    """ComplexModifications index node representation"""

    def __init__(self, token, next=None, cmods=None):
        """Initializer

        Parameters:
            :token (str): Unique node identifier.
            :next (list of IndexNode|None): Next nodes after self.
            :cmods (list of ComplexModification|None): Mods of self.
        """
        if next and not isinstance(next, list):
            raise ValueError(
                f"Invalid next nodes passed; should be list of IndexNode; "
                f"passed: {next}"
            )
        if cmods and not isinstance(cmods, list):
            raise ValueError(
                f"Invalid cmods passed; should be list of "
                f"ComplexModifications; passed: {cmods!r}"
            )
        self.token = token
        self.next = next or []
        self.cmods = cmods or []

    def __repr__(self):
        """Representor"""
        return dump_object_multiline_pairs(self, mask_protected=True)


class ModsProvider(abc.ABC):
    """Abstract representation of a modifications provider contract

    Modifications are stored as ComplexModification inheritors
    in an index of IndexNodes that form depth via their next attribute.

    If an AtomicModification already exists, a reference is created
    and the corresponding ComplexModification is updated.
    """

    #: list of IndexNode: Indexed storage.
    _cmods_index = []
    #: threading.RLock: Ensures thread-safe access to records.
    _lock = threading.RLock()

    @classmethod
    @threadsafemethod
    def is_empty(cls):
        """Check whether index empty

        Returns:
            :bool: True if so.
        """
        return not cls._cmods_index

    @classmethod
    @threadsafemethod
    def walk(cls, *filters, nodes=None, strict=False):
        """Recursive stored nodes iterator

        Filters are layers of:
        - Possible node token options.
        - None to accept any node.

        I.e., filter can be:
            (
                None,
                (
                    Resolution.I_LOVE_PINK_PONIES,
                    Resolution.SMTH_ABOUT_OTHER_TYPE_OF_PONIES
                ),
                "var",
                "ponies",
                (
                    "white_ponies",
                    "some_other_type_of_ponies",
                    "random_unexpected_type_of_ponies"
                )

            )
        We have 5 layers in this example:
        0. Any node.
        1. Either that or that.
        2. Only "var".
        3. Only "ponies".
        4. Any options of specified

        According to the example we can have the following yields:
        - IndexNode("ServerAAA"),
            IndexNode(<resolution_about_PINK>),
                IndexNode("var"),
                    IndexNode("ponies"),
                        IndexNode(<about_white>).
        - IndexNode("ServerBBB"),
            IndexNode(<resolution_about_OTHER>),
                IndexNode("var"),
                    IndexNode("ponies"),
                        IndexNode(<about_some_other>).
        - IndexNode("ServerCCC"),
            IndexNode(<resolution_about_PINK_again>),
                IndexNode("var"),
                    IndexNode("ponies"),
                        IndexNode(<about_random_unexpected>).

        Parameters:
            :*filters (list of None or list of str): Tokens to filter
                nodes to walk.
            :nodes (list of IndexNode|None): Root nodes to start.
            :strict (bool): True to skip nodes after last filter.

        Yields:
            :IndexNode: Current level index node.
        """
        nodes = nodes or cls._cmods_index
        filters_len = len(filters)

        for node in nodes:

            # Either end of recursive walk sequence
            # or no filters there wasn't any filters from start.
            if filters_len == 0:
                yield node
                if node.next and not strict:
                    yield from cls.walk(nodes=node.next, strict=False)
                continue

            # Just get rid of unsuitable branch.
            if isinstance(filters[0], (tuple, list)):
                if filters[0] and node.token not in filters[0]:
                    continue
            else:
                if filters[0] and node.token != filters[0]:
                    continue

            # There's some last filter left and node is suitable.
            # This is either the end or almost it.
            if filters_len == 1:
                yield node
                if node.next and not strict:
                    yield from cls.walk(nodes=node.next, strict=False)
                continue

            # Most-likely just start of the recursive sequence
            # or middle of it; there's much of job to do deeper.
            if node.next:
                yield from cls.walk(
                    *filters[1:], nodes=node.next, strict=strict
                )

    @classmethod
    def iterate(cls, *filters, strict=False):
        """Recurive parsed modifications iterator

        May return duplicates.

        Parameters:
            :*filters (list of None or list of str): Tokens to filter
                nodes to walk. See cls.walk() docstring for details.
            :strict (bool): True to skip nodes after last filter.

        Yields:
            :ComplexModification: Modification object.
        """
        for node in cls.walk(*filters, strict=strict):
            if node.cmods:
                yield from node.cmods

    @classmethod
    def lookup(cls, *filters, attrs=None, limit=None):
        """Search modifications by given criteria

        Returns unique records only.

        Parameters:
            :*filters (list of None or list of str): Tokens to filter
                nodes to walk. See cls.walk() docstring for details.
            :attrs (dict of Any|None): Keys must match ComplexModification
                attributes; values are tested against them.
            :limit (int): Maximum retrieved records.

        Returns:
            :tuple of ComplexModification: Matching modifications.

        Raises:
            :ValueError: If no parameters are specified.
        """
        if not filters and not attrs:
            raise ValueError(
                "At least one lookup criteria should be specified"
            )
        found_cmods = []
        for cmod in cls.iterate(*filters):
            if (
                (not attrs or is_matching_object(cmod, attrs))
                and cmod not in found_cmods
            ):
                found_cmods.append(cmod)
            if limit and len(found_cmods) >= limit:
                return tuple(found_cmods)
        return tuple(found_cmods)

    @classmethod
    @threadsafemethod
    def upsert(cls, servers, amod, *args, **kwargs):
        """Upsert modification object

        If a similar modification is already present, the further change
        is determined by cls.mutate_mod_for_update().

        Parameters:
            :servers (list of Server): Where modification was found.
            :amod (AtomicModification): Instance to insert as a new
                ComplexModification or update an existing one.

        Raises:
            :RuntimeError: If wrong amod instance is passed.
                If duplicate insert attempted.
                If multiple matching modifications are found.
        """
        def _index(cmod):
            def _gen_node():
                new_nodes.append(IndexNode(token))
                if i == filters_len:
                    new_nodes[-1].cmods.append(cmod)
                return new_nodes[-1]

            last_nodes = None
            is_new_branch = False
            filters_len = len(filters)

            # So specific range is made to slice filters
            # starting from first one and extend them one by one.
            for i in range(1, filters_len + 1):
                filters_cut = filters[:i]
                new_nodes = []
                current_nodes = []

                # If so therefore no sense trying to retrieve some
                # known nodes as it cannot exist in fact.
                if not is_new_branch:
                    current_nodes = [
                        node for node in cls.walk(*filters_cut, strict=True)
                    ]

                # If it's completely new story then it's time to
                # only extend previously observed branch.
                # Remember filters are layers with suitable options.
                if not current_nodes:
                    is_new_branch = True
                    missing_tokens = filters_cut[-1]
                    if not isinstance(missing_tokens, (list, tuple)):
                        missing_tokens = [missing_tokens]


                # Extract index tokens, filter out tokens we've used
                # for check in previous iteration, find missing
                # tokens within requested but not checked before.
                # Remember filters are layers with suitable options.
                else:
                    found_tokens = [node.token for node in current_nodes]
                    last_tokens = filters_cut[-1]
                    if isinstance(last_tokens, (list, tuple)):
                        missing_tokens = [
                            token for token in last_tokens
                            if token not in found_tokens
                        ]
                    else:
                        missing_tokens = (
                            []
                            if last_tokens in found_tokens
                            else [last_tokens]
                        )

                # Means we've reached end filters but seems we're
                # not the first here and the branch already exist.
                # So just add ComplexModification to to its storage.
                if (
                    not missing_tokens
                    and current_nodes
                    and i == filters_len
                ):
                    for node in current_nodes:
                        node.cmods.append(cmod)
                    return

                # Process missing tokens found within known nodes
                # but not itersected with any token of last filters
                # cut layer; remember we're processing by steps.
                for token in missing_tokens:

                    # Means we've encountered this at very start
                    # of filter sequence and index itself.
                    if not last_nodes:
                        cls._cmods_index.append(_gen_node())
                        continue

                    # To make node appear on the current level we're
                    # creating them on the previous according to
                    # IndexNode node structure itself.
                    for node in last_nodes:
                        node.next.append(_gen_node())

                # New nodes are those that we know for sure
                # are correct and we don't need them to cache
                # except only one case: it's fresh new branch.
                last_nodes = current_nodes if current_nodes else new_nodes

        if not isinstance(servers, list):
            raise ValueError(
                f"Invalid servers passed; should be list; passed: {servers!r}"
            )
        if not isinstance(amod, AtomicModification):
            raise ValueError(
                f"Invalid amod passed; should be subclass of "
                f"AtomicModification; passed: {amod!r}"
            )
        # If you don't know what is this then check cls.walk() docstring.
        filters = [
            None,
            amod.resolution,
            *[token for token in amod.tokenize()],
        ]
        cmods = cls.lookup(
            *filters,
            attrs=cls.gen_amod_lookup_attrs(amod, *args, **kwargs),
            limit=2
        )
        filters[0] = servers

        for cmod in cmods:
            ucmod = cls.mutate_mod_for_update(servers, cmod, *args, **kwargs)
            if ucmod:
                _index(ucmod)
                return
        icmod = cls.mutate_mod_for_insert(servers, amod, *args, **kwargs)
        if icmod: _index(icmod)

    @staticmethod
    @abc.abstractmethod
    def gen_amod_lookup_attrs(amod, *args, **kwargs):
        """Handy switcher to inheritors

        Parameters:
            :amod (AtomicModification): Any subclass instance.

        Returns:
            :dict of Any: Lookup attributes to use on upsert.
        """
        return {}

    @staticmethod
    @abc.abstractmethod
    def gen_cmod_object(amod, servers, *args, **kwargs):
        """Handy switcher for inheritors

        Parameters:
            :amod (AtomicModification): Any subclass instance.
            :servers (list of Server): Where modification was found.

        Returns:
            :ComplexModification: Any subclass new instance.
        """
        return ComplexModification(amod, servers)

    @staticmethod
    @abc.abstractmethod
    def mutate_mod_for_insert(servers, amod, *args, **kwargs):
        """Handy switcher for inheritors

        Used in cls.upsert right before inserting new mod.

        Parameters:
            :servers (list of Server): Where modification was found.
            :amod (AtomicModification): Instance to insert as a new.

        Returns:
            :ComplexModification: Any subclass new instance.
        """
        return ComplexModification(amod, servers)

    @staticmethod
    @abc.abstractmethod
    def mutate_mod_for_update(servers, cmod, *args, **kwargs):
        """Handy switcher for inheritors

        Used in cls.upsert right before updating known mod.

        Parameters:
            :servers (list of Server): Where modification was found.
            :cmod (AtomicModification): Instance to update.

        Returns:
            :ComplexModification: Any subclass updated instance.
        """
        return ComplexModification(cmod.amod, servers)

    @classmethod
    @threadsafemethod
    def dump(cls, path=None):
        """Dump provider data to a file

        Parameters:
            :path (str|None): Dump path override.
        """
        path = path or cls.gen_dump_path()
        with open(path, "x", encoding="utf-8") as fd:
            fd.write(repr(cls._cmods_index))

    @staticmethod
    @abc.abstractmethod
    def gen_dump_path():
        """Handy switched for inheritors

        Returns:
            :str: Default path to index dump.
        """
        return str()

