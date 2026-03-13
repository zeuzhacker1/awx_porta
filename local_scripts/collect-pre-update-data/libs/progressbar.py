# collect-pre-update-data progressbar control and rendering


import contextlib
import enum
import logging
import re
import shutil
import sys
import threading
import time


from libs.defaults import (PROGRESSBAR_STYLE_MAIN,
                           PROGRESSBAR_STYLE_FALLBACK,
                           PROGRESSBAR_SWAP_INTERVAL,
                           PROGRESSBAR_MIN_SPACING,
                           PROGRESSBAR_MIN_CUT_CONTENT,
                           PROGRESSBAR_MAX_RENDER_ATTEMPTS,
                           PROGRESSBAR_WAITERS_THRESHOLD)
from libs.common import SectionedNamespace
from libs.heartbeat import HeartbeatEvent, HeartbeatManager
from libs.objects import (threadsafemethod, MetaStaticInterface, MetaSingleton)
from libs.runtime import die, ShutdownEvent


ANSI_PREFIX = "\033"
ANSI_RE = re.compile(r"(?P<code>\x1b\[[\d;]*m)")


class ProgressbarAwareLoggingStreamHandler(logging.StreamHandler):
    """Write STDOUT logs without progressbar corruption"""

    def emit(self, *args, **kwargs):
        """Ancestor override

        Acquires progressbar lock and arranges space before writing log.
        In this way no corruption will appear in output.
        """
        Progressbar.please_let_others_draw()
        with ProgressbarManager.wait(manage=True):
            super().emit(*args, **kwargs)


class ProgressbarColor(enum.Enum):
    """Pregefined ANSI color codes"""

    BLACK      = f"{ANSI_PREFIX}[30m"
    RED        = f"{ANSI_PREFIX}[31m"
    GREEN      = f"{ANSI_PREFIX}[32m"
    YELLOW     = f"{ANSI_PREFIX}[33m"
    BLUE       = f"{ANSI_PREFIX}[34m"
    MAGENTA    = f"{ANSI_PREFIX}[35m"
    CYAN       = f"{ANSI_PREFIX}[36m"
    GRAY       = f"{ANSI_PREFIX}[37m"

    BLACK_BG   = f"{ANSI_PREFIX}[40m"
    RED_BG     = f"{ANSI_PREFIX}[41m"
    GREEN_BG   = f"{ANSI_PREFIX}[42m"
    YELLOW_BG  = f"{ANSI_PREFIX}[43m"
    BLUE_BG    = f"{ANSI_PREFIX}[44m"
    MAGENTA_BG = f"{ANSI_PREFIX}[45m"
    CYAN_BG    = f"{ANSI_PREFIX}[46m"
    GRAY_BG    = f"{ANSI_PREFIX}[47m"

    BLACK_LT   = f"{ANSI_PREFIX}[90m"
    RED_LT     = f"{ANSI_PREFIX}[91m"
    GREEN_LT   = f"{ANSI_PREFIX}[92m"
    YELLOW_LT  = f"{ANSI_PREFIX}[93m"
    BLUE_LT    = f"{ANSI_PREFIX}[94m"
    MAGENTA_LT = f"{ANSI_PREFIX}[95m"
    CYAN_LT    = f"{ANSI_PREFIX}[96m"
    GRAY_LT    = f"{ANSI_PREFIX}[97m"

    BOLD       = f"{ANSI_PREFIX}[1m"
    RESET      = f"{ANSI_PREFIX}[0m"

    def __str__(self):
        return self.value

    @staticmethod
    def count(string, length=False):
        """Count number of colors codes in string

        Parameters:
            :string (str): Obviously -_-
            :length (bool): Count not just number of codes
                but their total length.

        Returns:
            :int: Either number of codes or their total length.
        """
        found = ANSI_RE.findall(string)
        return sum(map(len, found)) if length else len(found)

    @staticmethod
    def strip(string):
        """Strip color codes from string

        Parameters:
            :string (str): Obviously -_-

        Returns:
            :str: Same string without ANSI codes.
        """
        return ANSI_RE.sub("", string)


class ProgressbarElement(enum.IntEnum):
    """Elements placeholders used as hints during progressbar rendering

    Should be used with ProgressbarStyle.format as placeholders
    to unify mappings across components.

    Each member represent elemnt to be placed and actual progressbar
    and elements have different handling approaches depending on purpose.
    """

    #: int: Hint to draw to HeartbeatEvent().desc.
    LONG_DESC = enum.auto()
    #: int: Hint to draw to HeartbeatEvent().name.
    SHORT_DESC = enum.auto()
    #: int: Hint to draw progressbar itself depending on event progress.
    #: In case if goal is available then draws indeed progressbar.
    #: Otherwise draws slider bouncing around.
    #: Should be always rendered considering terminal width
    #: and other parts of progressbar within line.
    PROGRESS = enum.auto()
    #: int: Hint to draw animation when progressbar is stalled.
    ANIMATION = enum.auto()
    #: int: Hint to draw current goal achievement status.
    STATUS = enum.auto()
    #: int: Hint to draw target goal.
    GOAL = enum.auto()

    def is_fixed(self):
        """Check whether member should be rendered as fixed

        Fixed elements are those that should be placed disregarding
        other elements placement and terminal size limitations.

        Returns:
            :bool: True if so.
        """
        return self in (
            ProgressbarElement.SHORT_DESC,
            ProgressbarElement.ANIMATION,
            ProgressbarElement.STATUS,
            ProgressbarElement.GOAL
        )
    def is_adaptive(self):
        """Check whether member should be rendered as adaptive

        Adaptive elements are those that allow cutting their content
        in case of terminal size limitations.

        Returns:
            :bool: True if so.
        """
        return self in (
            ProgressbarElement.LONG_DESC,
        )
    def is_dependent(self):
        """Check whether member should be rendered as dependent

        Dependent elements are those that should be placed only when
        all other elements are rendered and their sizes are known.

        Returns:
            :bool: True if so.
        """
        return self in (
            ProgressbarElement.PROGRESS,
        )


class ProgressbarStyle(metaclass=MetaStaticInterface, allow_classmethods=True):
    """Elements themselves for rendering with redefined format

    Should be used in conjuction with ProgressbarStyleElements.
    """

    #: tuple of tuple of str: Frames of element, as separate parts.
    #: Symbol used for progressbar progress tail.
    #: Used only if goal is available in associated event.
    progress_tail = (("=",),)
    #: tuple of tuple of str: Frames of element, as separate parts.
    #: Symbol used for progressbar progress head.
    #: Used only if goal is available in associated event.
    progress_head = ((">",),)
    #: tuple of tuple of str: Frames of element, as separate parts.
    #: Symbol used for progressbar snake slider.
    #: Used only if goal IS NOT available in associated event.
    progress_bouncer = (("<=>",),)
    #: tuple of tuple of str: Frames of element, as separate parts.
    #: Animation drawn when progressbar is stalled.
    animation = (("/",), ("-",), ("\\",), ("|",),)
    #: tuple of str or ProgressbarElement: Sequence of progressbar parts
    #: such as predefined characters or elements placeholders.
    #: In all cases spaces should be added manually.
    format = (
        ProgressbarElement.SHORT_DESC,"... ",ProgressbarElement.ANIMATION
    )
    #: float: Seconds interval to redraw same progressbar in terminal.
    redraw_interval = 0.1
    #: int: Number of times to redraw same progressbar in terminal.
    redraw_times = 10


class ProgressbarStyleLarge7s5h4d3(ProgressbarStyle):
    """Definitely (not) original flavour"""

    #: tuple of tuple of str: Contract requirement implementation.
    progress_tail = ((
        ProgressbarColor.GREEN_LT, "⣿", ProgressbarColor.RESET
    ),)
    #: tuple of tuple of str: Contract requirement implementation.
    progress_head = (
        (
            ProgressbarColor.GREEN,     "⠶",
            ProgressbarColor.YELLOW_LT, "⠦",
            ProgressbarColor.YELLOW,    "⠤",
            ProgressbarColor.BOLD,
            ProgressbarColor.RED,       "/",
            ProgressbarColor.RESET
        ),
        (
            ProgressbarColor.GREEN,     "⠶",
            ProgressbarColor.YELLOW_LT, "⠦",
            ProgressbarColor.YELLOW,    "⠤",
            ProgressbarColor.BOLD,
            ProgressbarColor.RED,       "-",
            ProgressbarColor.RESET
        ),
        (
            ProgressbarColor.GREEN,     "⠶",
            ProgressbarColor.YELLOW_LT, "⠦",
            ProgressbarColor.YELLOW,    "⠤",
            ProgressbarColor.BOLD,
            ProgressbarColor.RED,       "\\",
            ProgressbarColor.RESET
        ),
        (
            ProgressbarColor.GREEN,     "⠶",
            ProgressbarColor.YELLOW_LT, "⠦",
            ProgressbarColor.YELLOW,    "⠤",
            ProgressbarColor.BOLD,
            ProgressbarColor.RED,       "|",
            ProgressbarColor.RESET
        )
    )
    #: tuple of tuple of str: Contract requirement implementation.
    progress_bouncer = ((
        ProgressbarColor.YELLOW,    "⠤",
        ProgressbarColor.YELLOW_LT, "⠴",
        ProgressbarColor.GREEN_LT,  "⠶",
        ProgressbarColor.GREEN_LT,  "⣿",
        ProgressbarColor.GREEN_LT,  "⠶",
        ProgressbarColor.YELLOW_LT, "⠦",
        ProgressbarColor.YELLOW,    "⠤",
        ProgressbarColor.RESET
    ),)
    #: tuple of tuple of str: Contract requirement implementation.
    animation = (
        (ProgressbarColor.MAGENTA,   "⠠", ProgressbarColor.RESET),
        (ProgressbarColor.RED,       "⠰", ProgressbarColor.RESET),
        (ProgressbarColor.RED_LT,    "⠸", ProgressbarColor.RESET),
        (ProgressbarColor.YELLOW,    "⠼", ProgressbarColor.RESET),
        (ProgressbarColor.YELLOW_LT, "⠾", ProgressbarColor.RESET),
        (ProgressbarColor.GREEN,     "⠿", ProgressbarColor.RESET),
        (ProgressbarColor.GREEN_LT,  "⣿", ProgressbarColor.RESET)
    )
    #: tuple of str or ProgressbarElement:
    #: Contract requirement implementation.
    format = (
        ProgressbarElement.ANIMATION,
        " ",
        ProgressbarElement.SHORT_DESC,
        " is running...",
        " ",
        ProgressbarColor.BOLD,
        ProgressbarColor.BLUE,
        "[",
        ProgressbarColor.RESET,
        ProgressbarElement.PROGRESS,
        ProgressbarColor.BOLD,
        ProgressbarColor.BLUE,
        "]",
        ProgressbarColor.RESET,
        " ",
        ProgressbarElement.STATUS,
        ProgressbarColor.BOLD,
        ProgressbarColor.BLUE,
        "/",
        ProgressbarColor.RESET,
        ProgressbarElement.GOAL
    )
    #: float: Contract requirement implementation.
    redraw_interval = 0.2
    #: int: Contract requirement implementation.
    redraw_times = 5

class ProgressbarStyleCompact7s5h4d3(ProgressbarStyle):
    """Definitely (not) original flavour"""

    #: tuple of tuple of str: Contract requirement implementation.
    progress_tail = None
    #: tuple of tuple of str: Contract requirement implementation.
    progress_head = None
    #: tuple of tuple of str: Contract requirement implementation.
    progress_bouncer = None
    #: tuple of tuple of str: Contract requirement implementation.
    animation = (
        (ProgressbarColor.MAGENTA,   "⠠", ProgressbarColor.RESET),
        (ProgressbarColor.RED,       "⠰", ProgressbarColor.RESET),
        (ProgressbarColor.RED_LT,    "⠸", ProgressbarColor.RESET),
        (ProgressbarColor.YELLOW,    "⠼", ProgressbarColor.RESET),
        (ProgressbarColor.YELLOW_LT, "⠾", ProgressbarColor.RESET),
        (ProgressbarColor.GREEN,     "⠿", ProgressbarColor.RESET),
        (ProgressbarColor.GREEN_LT,  "⣿", ProgressbarColor.RESET)
    )
    #: tuple of str or ProgressbarElement:
    #: Contract requirement implementation.
    format = (ProgressbarElement.ANIMATION,)
    #: float: Contract requirement implementation.
    redraw_interval = 0.2
    #: int: Contract requirement implementation.
    redraw_times = 5


class ProgressbarRendererError(RuntimeError):
    """Handy exception to indicate renderer error

    Use when renderer cannot create normal output but the application
    likely should continue working even without it.
    """


class Progressbar:
    """Particular drawing instance tied to an event and style

    These instances are used for drawing events progressbars.
    They highly rely on information from HeartbeatManager.

    NOTA BENE PROGRESSBARS AREN'T AWARE OF EACH OTHER!
    MOREOVER THEY'RE THREAD-UNSAFE!
    So don't use them directly for drawing, use ProgressbarManager!
    """

    #: int: Number of components that currently waiting for possibility
    #: to draw something to terminal and want Progressbar to finish.
    _waiters_counter = 0

    def __init__(self, event, style_main=None, style_fallback=None):
        """Initializer

        Parameters:
            :event (HeartbeatEvent): Tracked instance.
            :style_main (ProgressbarStyle|None): Any inheritor.
            :style_fallback (ProgressbarStyle|None): Any inheritor.

        Attributes:
            :_elems_i_frames (dict of Any and int): Current frame index
                of animated progressbar element.
            :_elems_poses (dict of Any and int): Current position index
                of dependent progressbar element.
            :_height (int): Calculated at init from number of lines in
                _style.format which in turn is figured out by \\n elems.
            :_width (int): Last known terminal width.
            :_prev_width (int): Previous known self._width.
            :_prev_event_status (int): Previous self._event.status.
            :_cache_ns (SectionedNamespace): Namespace for things cached
                by renderer, sectionized by line number.
                Please use only self._cache property for access.

        Raises:
            :TypeError: If any of parameters is wrong.
            :NotImplementedError: If height in style is more than line.
        """
        if not isinstance(event, HeartbeatEvent):
            raise TypeError(
                f"Got event not as a HeartbeatEvent: {event!r}"
            )
        if style_main and not issubclass(style_main, ProgressbarStyle):
            raise TypeError(
                f"Got main style not as ProgressbarStyle: {style_main!r}"
            )
        if style_fallback and not issubclass(style_fallback, ProgressbarStyle):
            raise TypeError(
                f"Got fallback style not as ProgressbarStyle: {style_fallback!r}"
            )

        self._event = event

        self._style_main = (
            style_main or globals()[PROGRESSBAR_STYLE_MAIN]
        )
        self._style_fallback = (
            style_fallback or globals()[PROGRESSBAR_STYLE_FALLBACK]
        )
        self._style = self._style_main
        self._heights = {}
        self._validate_styles_format()

        self._elems_i_frames = {}
        self._elems_poses = {}
        self._width = 0
        self._prev_width = 0
        self._prev_event_status = 0
        self._cache_ns = SectionedNamespace()
        self._cache_ns.pointer = 0

    @property
    def _height(self):
        """Height of currently active style"""
        return self._heights[self._style]

    @property
    def _cache(self):
        """Initializes section in cache namespace if it's new

        Attributes:
            :line (str): Cached previously rendered line.
            :re_render_forcers (list of callable): Functions
                that return bool to tell renderer whether line re-render
                is required if there some animated/changed element.

        Returns:
            :Any: Currently active cache section.
        """
        if not self._cache_ns:
            self._cache_ns.line = ""
            self._cache_ns.re_render_forcers = [lambda self: True]
        return self._cache_ns

    @classmethod
    def please_let_others_draw(cls):
        """Tell all instances that you want to draw in terminal

        DOESN'T GUARANTEE SUCH!
        """
        cls._waiters_counter += 1

    def _should_i_let_others_draw(self):
        """Check whether waiters counter exceeded threshold

        Returns:
            :bool: True if so.
        """
        yes = self.__class__._waiters_counter >= PROGRESSBAR_WAITERS_THRESHOLD
        if not yes:
            return False
        self.__class__._waiters_counter = 0
        return True

    def _validate_styles_format(self):
        """Make sure provided styles are valid

        Currently renderer have limitation that restrict duplicating
        elements as its caches as well as frames and position shifting
        mechanisms are strictly orieted to single ProgressbarElement
        mention per member.

        Another limitation is that you can use only one line. The class
        itself already supports multiline rendering and even scanouts.
        However there too much uncontrollable corruptions appear during
        such, so it's partial, not yet polished it is left in case if we
        decide to move the suite to curses.

        Raises:
            :NotImplementedError: If there's any ProgressbarElement
                member mention duplicate in style format.
                If style format is multiline.
        """
        def _validate_no_multiline(style):
            if style in self._heights:
                return
            self._heights[style] = len("".join(map(str, style.format)).splitlines())
            if self._heights[style] > 1:
                raise NotImplementedError(
                    "Unfortunately, but, progressbar cannot be higher "
                    "than one line; migrate to curses or change format"
                )
        def _validate_no_duplicates(style):
            if style in self._heights:
                return
            mention_index = {}
            for part in style.format:
                if not isinstance(part, ProgressbarElement):
                    continue
                if part not in mention_index:
                    mention_index[part] = None
                    continue
                raise NotImplementedError(
                    "Unfortunately, but, progressbar elements shouldn't "
                    "duplicate; extend renderer caching or change format"
                )
        for style in (self._style_main, self._style_fallback):
            _validate_no_multiline(style)
            _validate_no_duplicates(style)

    def arrange(self):
        """Arrange space for progressbar in terminal according to height"""
        for i in range(self._height):
            if i:
                self._println()

    def draw(self):
        """Renderer and scanout this progressbar several times in needed

        Number of times and interval depends on style.
        """
        redraw = self._style.redraw_times + 1
        self.arrange()

        while (
            redraw
            and not ShutdownEvent.is_set()
            and not self._should_i_let_others_draw()
        ):
            self._draw()
            redraw -= 1
            time.sleep(self._style.redraw_interval)

    def _draw(self):
        """Render and scanout this progressbar

        In case if renderer faces error associated with terminal size
        limitations then it switches style to fallback one.

        If even fallback style fail then renderer instead of progressbar
        puts just a simple message that he gives up trying.

        Renderer switches back to main style if terminal size changed.
        """
        self._width = shutil.get_terminal_size().columns

        if not self._prev_width:
            self._prev_width = self._width
        elif self._prev_width != self._width:
            if self._style is self._style_fallback:
                self.switch_style(self._style_main)

        render = ""
        while True:
            try:
                render = self._render()
                break
            except ProgressbarRendererError:
                # This is not a typo; this check for cases when styles
                # are the same and there's no point chaging them.
                if (
                    self._style is self._style_main
                    and self._style is not self._style_fallback
                ):
                    self.switch_style(self._style_fallback)
                    continue
                render = "too small terminal to show progress :("
                break

        self.clearall()
        self._print(render)
        self._prev_width = self._width
        self._prev_event_status = self._event.status

    def _render(self):
        """Get progressbar lines with all elements placed

        Renderer tries to use cached lines if data that they rely wasn't
        changed at all. This data is defined on very first rendering
        iteration by subsequent methods, they create callables in cache
        that used by renderer to retrieve boolean flag indicating whether
        line re-render is required.

        Re-render is forced if terminal size is changed.
        Re-render conditional functions are reset on each re-render.

        Returns:
            :str: Probably multiline string.
        """
        lines_split = []
        line_split = []

        for part in self._style.format:
            if part != "\n":
                line_split.append(part)
                continue
            lines_split.append(line_split)
            line_split = []
        lines_split.append(line_split)

        lines_composed = ""

        for i in range(len(lines_split)):
            re_render_needed = False
            self._cache.pointer = i

            if self._width != self._prev_width:
                re_render_needed = True
            else:
                for is_re_render_needed in self._cache.re_render_forcers:
                    if is_re_render_needed(self):
                        re_render_needed = True
            if re_render_needed:
                self._cache.re_render_forcers.clear()
                line = self._render_line(lines_split[i])
                self._cache.line = line
                lines_composed += line
            else:
                lines_composed += self._cache.line

        return lines_composed[:-1]

    def _render_line(self, line_split, cut_factor=0, try_number=1):
        """Get progressbar particular line with its elements placed

        Renderer tries to fit in terminal size limitations reducing
        space consumed by dynamic elements and cutting adaptive ones.
        ProgressbarColor are carefully excluded from calculations.

        Animated frames data such as i_frames and movement positions
        are restored to the initial state between render attempts
        until line is successfully rendered.

        Parameters:
            :line_split (list of str): ProgressbarStyle.format parts.
            :cut_factor (int): Used by recursive calls when attempting
                to cut adaptive elements more to fit in terminal size.
            :try_number (int): Used by the method itself as internal
                counter to prevent too deep recursion.

        Returns:
            :str: Progressbar line terminated by \\n.

        Raises:
            :TypeError: If got unexpected line part.
            :ProgressbarRendererError: If fails to render line due to
                current terminal size limitations.
        """
        def _retry(exceeding_len):
            self._elems_i_frames = early_copy_elems_i_frames
            self._elems_poses = early_copy_elems_poses
            return self._render_line(
                line_split,
                try_number=(try_number + 1),
                cut_factor=int(
                    ((exceeding_len - self._width) / (adaptives_num or 1)
                    ) + required_space_total
                )
            )

        if try_number > PROGRESSBAR_MAX_RENDER_ATTEMPTS:
            raise ProgressbarRendererError("Please fallback to compact style")

        early_copy_elems_i_frames = dict(self._elems_i_frames)
        early_copy_elems_poses = dict(self._elems_poses)

        line_split_interpreted = []
        line_split_translated = []
        adaptives_num = 0
        dependents_queue = []
        dependents_raws = []

        for part in line_split:
            if isinstance(part, (str, ProgressbarColor)):
                line_split_interpreted.append(part)
            elif isinstance(part, ProgressbarElement):
                if part.is_fixed():
                    line_split_interpreted.extend(
                        self._render_line_elem_fixed(part)
                    )
                elif part.is_adaptive():
                    adaptives_num += 1
                    line_split_interpreted.extend(
                        self._render_line_elem_adaptive(
                            part, cut_factor=cut_factor
                        )
                    )
                elif part.is_dependent():
                    line_split_interpreted.append(None)
                    dependents_queue.append(part)

                    interim_copy_elems_i_frames = dict(self._elems_i_frames)
                    interim_copy_elems_poses = dict(self._elems_poses)
                    dependents_raws.extend(
                        self._render_line_elem_dependent(part)
                    )
                    self._elems_i_frames = interim_copy_elems_i_frames
                    self._elems_poses = interim_copy_elems_poses
                else:
                    raise TypeError(
                        f"Unexpected ProgressbarElement member type "
                        f"of {part.name} which isn't resolveable by its "
                        f"own methods; looks like maintainer's mistake"
                    )
            else:
                raise TypeError(
                    f"Unexpected progressbar part type; should be either "
                    f"str or ProgressbarColor or ProgressbarElement but "
                    f"got: {part!r}"
                )

        required_spaces = len(dependents_queue)
        required_space_total = PROGRESSBAR_MIN_SPACING * required_spaces

        non_dependent_total_len = 0
        for part in line_split_interpreted:
            if isinstance(part, ProgressbarColor):
                line_split_translated.append(str(part))
            else:
                line_split_translated.append(part)
                if part is not None:
                    non_dependent_total_len += len(part)

        preliminary_total_len = non_dependent_total_len + len("".join([
            part for part in dependents_raws
            if not isinstance(part, ProgressbarColor)
        ])) + required_space_total

        if preliminary_total_len > self._width:
            return _retry(preliminary_total_len)

        if dependents_queue:
            available_width_per_dependent = int(
                (self._width - non_dependent_total_len) / required_spaces
            )
        else:
            available_width_per_dependent = 0

        total_len_wo_ansis = 0
        try:
            line = "".join([
                part
                if part is not None
                else "".join(map(str, self._render_line_elem_dependent(
                    dependents_queue.pop(),
                    width=available_width_per_dependent
                )))
                for part in line_split_translated
            ])
            total_len_wo_ansis = len(ProgressbarColor.strip(line))
            if total_len_wo_ansis > self._width:
                return _retry(total_len_wo_ansis)
        except ProgressbarRendererError:
            return _retry(total_len_wo_ansis)

        return line + "\n"

    def _render_line_elem_fixed(self, elem):
        """Translate progressbar element placeholder to value

        Should be used for elements fixed in terms
        of ProgressbarElement.is_fixed()

        Parameters:
            :elem (ProgressbarElement): Any member.

        Returns:
            :tuple of str: Corresponding frame parts.

        Raises:
            :TypeError: If got unexpected line element.
        """
        value = None
        if elem is ProgressbarElement.SHORT_DESC:
            value = self._event.name
        elif elem is ProgressbarElement.ANIMATION:
            value = self._style.animation
            self._cache_add_re_render_forcer(lambda self: True)
        elif elem is ProgressbarElement.STATUS:
            if self._event.status is None:
                value = "0"
            else:
                value = str(self._event.status)
                self._cache_add_re_render_forcer(
                    lambda self: self._event.status != self._prev_event_status
                )
        elif elem is ProgressbarElement.GOAL:
            value = (
                "1"
                if self._event.goal is None
                else str(self._event.goal)
            )
        else:
            raise TypeError(
                f"Unexpected ProgressbarElement fixed member type "
                f"of {elem.name} which cannot be handled by renderer"
            )
        return self._get_elem_animation_frame(elem, value)

    def _render_line_elem_adaptive(self, elem, cut_factor=0):
        """Translate progressbar element placeholder to value

        Should be used for elements adaptive in terms
        of ProgressbarElement.is_adaptive()

        Parameters:
            :elem (ProgressbarElement): Any member.
            :cut_factor (int): Number of times to shorten value to adapt
                it to size limitations if any. Factor of 1 implies:
                - Removing 1 last character.
                - Replacing 3 last characters with "...".
                Factor of 2 and so on will only change number of removed
                characters during adaptation.

        Returns:
            :tuple of str: Corresponding frame parts.

        Raises:
            :ValueError: If got negative cut factor.
            :TypeError: If got unexpected line element.
            :ProgressbarRendererError: If resulting content after cut
                is too short per PROGRESSBAR_MIN_CUT_CONTENT.
        """
        if cut_factor < 0:
            raise ValueError(
                f"Cut factor for element value adaptation cannot be negative; "
                f"got: {cut_factor}"
            )
        value = None
        if elem is ProgressbarElement.LONG_DESC:
            value = self._event.desc
        else:
            raise TypeError(
                f"Unexpected ProgressbarElement adaptive member type "
                f"of {elem.name} which cannot be handled by renderer"
            )
        if cut_factor:
            value = value[:-(cut_factor+3)]
            if len(value) < PROGRESSBAR_MIN_CUT_CONTENT:
                raise ProgressbarRendererError(
                    "Too short cut of adaptive content"
                )
            value = f"{value[:-(cut_factor+3)]}..."
        return self._get_elem_animation_frame(elem, value)

    def _render_line_elem_dependent(self, elem, width=0):
        """Translate progressbar element placeholder to value

        Should be used for elements dependent in terms
        of ProgressbarElement.is_dependent()

        Parameters:
            :elem (ProgressbarElement): Any member.
            :width (int): Available width for element.
                Not required space will be filled with... spaces.
                If 0 specified then returns frame without extension.

        Returns:
            :tuple of str: Corresponding frame parts.

        Raises:
            :ValueError: If got negative width.
            :TypeError: If got unexpected line element.
        """
        if width < 0:
            raise ValueError(
                f"Width for dependent element placement cannot be negative; "
                f"got: {width}"
            )
        parts = None
        if elem is ProgressbarElement.PROGRESS:
            if self._event.goal:
                parts = self._render_line_elem_progress_trail(width=width)
            else:
                parts = self._render_line_elem_progress_bouncer(width=width)
        else:
            raise TypeError(
                f"Unexpected ProgressbarElement dependent member type "
                f"of {elem.name} which cannot be handled by renderer"
            )
        return parts

    def _render_line_elem_progress_trail(self, width=0):
        """Generate event's progresss trail

        Parameters:
            :width (int): Available width for element.
                Not required space will be filled with... spaces.
                If 0 specified then returns trail without long tail.

        Returns:
            :tuple of str: Trail as some position.

        Raises:
            :ProgressbarRendererError: If space for trail is too small
                per PROGRESSBAR_MIN_SPACING.
        """
        tail_name = f"{ProgressbarElement.PROGRESS}_tail"
        tail_parts = self._get_elem_animation_frame(
            tail_name, self._style.progress_tail
        )
        head_name = f"{ProgressbarElement.PROGRESS}_head"
        head_parts = self._get_elem_animation_frame(
            head_name, self._style.progress_head
        )
        if not width:
            return tail_parts + head_parts

        head_len = len("".join([
            part for part in head_parts
            if not isinstance(part, ProgressbarColor)
        ]))


        left_space = int(
            (width * (self._event.status / self._event.goal)) - head_len
        )
        if left_space < 0:
            left_space += head_len
            if left_space < 0:
                left_space = 0
            right_space = width - head_len
        else:
            right_space = width - left_space - head_len

        if (left_space + right_space) < PROGRESSBAR_MIN_SPACING:
            raise ProgressbarRendererError(
                "No enough space for progress trail"
            )

        self._cache_add_re_render_forcer(
            lambda self: self._event.status != self._prev_event_status
        )
        return (*tail_parts*left_space, *head_parts, " "*right_space)

    def _render_line_elem_progress_bouncer(self, width=0):
        """Generate slider bouncing around

        Parameters:
            :width (int): Available width for element.
                Not required space will be filled with... spaces.
                If 0 specified then returns frame without spacing.

        Returns:
            :tuple of str: Bouncer as some position.

        Raises:
            :ProgressbarRendererError: If space for slider is too small
                per PROGRESSBAR_MIN_SPACING.
        """
        bouncer_name = f"{ProgressbarElement.PROGRESS}_bouncer"
        bouncer_parts = self._get_elem_animation_frame(
            bouncer_name, self._style.progress_bouncer
        )
        if not width:
            return bouncer_parts

        left_space = self._get_elem_movement_pos(
            bouncer_name, bouncer_parts, width
        )
        right_space = width - left_space - len("".join([
            part for part in bouncer_parts
            if not isinstance(part, ProgressbarColor)
        ]))
        if (left_space + right_space) < PROGRESSBAR_MIN_SPACING:
            raise ProgressbarRendererError(
                "No enough space for slider bouncing around"
            )

        self._cache_add_re_render_forcer(lambda self: True)
        return (" "*left_space, *bouncer_parts, " "*right_space)

    def _cache_add_re_render_forcer(self, forcer):
        """Register re-render force function

        Parameters:
            :forcer (callable): Function that returns only bool value
                that helps renderer to decide whether line re-render
                is required or not. Function should expect at least
                self of progressbar instance.

        Raises:
            :TypeError: If got not callable.
        """
        if not callable(forcer):
            raise TypeError(
                f"Got wrong re-render forcer for render cache; "
                f"should be callable when got: {forcer!r}"
            )
        self._cache.re_render_forcers.append(forcer)

    def _get_elem_animation_frame(self, name, frames):
        """Retrieve proper frame of probably animated element

        Parameters:
            :name (Any): Name of animated element to cache frame
                number to increment it in further calls.
            :frames (tuple of str|str): Frames of animated element
                to select a proper one. In case of single frame
                returns just if. The former part of logic left
                for convenience as method is often used.

        Returns:
            :tuple of str: Next frame parts of animated element if
                it's such otherwise just provided value itself wrapped.
        """
        if not isinstance(frames, (tuple, list)):
            return (str(frames),)
        if name in self._elems_i_frames:
            i_frame = (self._elems_i_frames[name] + 1) % len(frames)
        else:
            i_frame =0
        self._elems_i_frames[name] = i_frame
        return frames[i_frame]

    def _get_elem_movement_pos(self, name, part, limit):
        """Retrieve proper position of moving element

        In case if specified limit is exceeded then method starts
        counting position backwards.

        Parameters:
            :name (Any): Name of moving element to cache position
                number to increment it in further calls.
            :part (str): Moving frame part itself to properly estimate
                sizes required by it.
            :limit (int): Maximum position. Likely width of element.

        Returns:
            :int: Position of element starting from 0.
        """
        if name in self._elems_poses:
            true_limit = limit - len(part)
            pos = int(self._elems_poses[name] + (true_limit * 0.05))
            pos = (
                -int(self._elems_poses[name] - (true_limit * 0.05))
                if pos > true_limit
                else pos
            )
        else:
            pos = 0
        self._elems_poses[name] = pos
        return abs(pos)

    def switch_style(self, select):
        """Change style and reset render caches

        Parameters:
            :select (ProgressbarStyle): Any inheritor.

        Raises:
            :TypeError: If wrong object passed.
        """
        if not issubclass(select, ProgressbarStyle):
            raise TypeError(
                f"Got wrong style to switch to; should be "
                f"ProgressbarStyle; got: {select!r}"
            )
        self._style = select
        self._cache_ns.clear()
        self._elems_poses.clear()
        self._elems_i_frames.clear()

    def _print(self, *args, **kwargs):
        """Handy shortcut for scanouts"""
        print(*args, **kwargs, sep="", end="", file=sys.stderr, flush=True)

    def _println(self, *args, **kwargs):
        """Handy shortcut for scanouts with \\n"""
        print(*args, **kwargs, sep="", file=sys.stderr, flush=True)

    def _moveup(self, lines=1):
        """Move terminal cursor up

        Parameters:
            :lines (int): Number of lines to move up.
        """
        if lines < 1:
            raise ValueError(f"Got {lines} when should be positive")
        self._print(f"{ANSI_PREFIX}[%sA" % lines)

    def _clear(self):
        """Clear current line in terminal"""
        self._print("\r" + " " * self._width + "\r")

    def clearall(self):
        """Clear several lines in terminal according to height in style"""
        for i in range(self._height):
            if i:
                self._moveup()
            self._clear()


class ProgressbarManager:
    """Shared endpoint for progressbars and rendering management

    Loggers and other terminal output generating components should
    communicate with manager via cls.wait() method to prevent
    output corruption in terminal.

    Should be used by ProgressbarController for adding new progressbars
    and moving drawing queue.
    """

    #: dict of HeartbeatEvent and Progressbar: Registered progressbars.
    _progressbars = {}
    #: Progressbar: Currently displayed progressbar.
    _progressbar = None
    #: generator of tuple of HeartbeatEvent and Progressbar):
    #: Cached cls._next().
    _next_cached = None
    #: threading.RLock: Ensures thread-safe access to terminal output.
    _lock = threading.RLock()

    @classmethod
    @threadsafemethod
    def track(cls, event):
        """Adds progressbar for provided event

        Parameters:
            :event (HeartbeatEvent): Event to track.
        """
        if event in cls._progressbars:
            raise RuntimeError(
                f"Attempt to track event already being tracked: {event!r}"
            )
        cls._progressbars[event] = Progressbar(event)

    @classmethod
    @threadsafemethod
    def _next(cls):
        """Internal endless progressbars iterator

        Yields:
            :tuple of HeartbeatEvent and Progressbar: Yet another pair.
        """
        while True:
            yield from dict(cls._progressbars).items()

    @classmethod
    @threadsafemethod
    def next(cls):
        """Swaps progressbars on screen and remove those that finished"""
        if not cls._next_cached:
            cls._next_cached = cls._next()
        for event, progressbar in cls._next_cached:
            if cls._progressbar:
                cls._progressbar.clearall()
            cls._progressbar = progressbar
            progressbar.draw()
            if event.finished:
                cls._progressbars.pop(event)
            return

    @classmethod
    @threadsafemethod
    @contextlib.contextmanager
    def wait(cls, manage=True):
        """Temporary stops progressbar drawing

        Parameters:
            :manage (bool): Clear and later carefully redraw current
                progressbar back if True.
        """
        try:
            if manage and cls._progressbar:
                cls._progressbar.clearall()
            yield
        finally:
            if manage and cls._progressbar:
                cls._progressbar.draw()

    @classmethod
    @threadsafemethod
    def tracked(cls):
        """Retrieve copy of events tracked in progressbars

        Returns:
            :tuple of HeartbeatEvent: Tracked events.
        """
        return tuple(cls._progressbars.keys())

    @classmethod
    @threadsafemethod
    def reset(cls):
        """Resets manager and clears progressbar from terminal"""
        if cls._progressbar:
            cls._progressbar.clearall()
            cls._progressbar.arrange()
            cls._progressbar = None
        if cls._next_cached:
            cls._next_cached = None
        if cls._progressbars:
            cls._progressbars.clear()


class ProgressbarController(threading.Thread, metaclass=MetaSingleton):
    """Single instance responsible for progressbars drawing

    Relies on events registered via HeartbeatManager.
    """

    #: threading.RLock: Ensures no simultaneous executions.
    _lock = threading.RLock()

    def __init__(self, swap_interval=PROGRESSBAR_SWAP_INTERVAL):
        """Initializer

        Parameters:
            :swap_interval (int): Interval in seconds for refresh.
        """
        super().__init__(name=self.__class__.__name__)
        self._logger = logging.getLogger("progressbars")
        self._swap_interval = swap_interval

    @threadsafemethod
    def run(self):
        """Used by threading.Thread.start() call

        Here's a simple workaround to crash the service on an unhandled
        thread exception.
        """
        try:
            self.main()
        except Exception:
            die("Unhandled exception occurred:", self._logger, is_exc=True)
        finally:
            ProgressbarManager.reset()

    @threadsafemethod
    def main(self):
        """Main instance method in the thread

        Register new HeartbeatEvent found in HeartbeatManager
        as progressbars using ProgressbarManager.
        """
        while not ShutdownEvent.wait(self._swap_interval):
            with ProgressbarManager.wait(manage=False):
                tracked_events = set(ProgressbarManager.tracked())
                outgoing_events = set([
                    event
                    for _, events in HeartbeatManager.stacks().items()
                    for event in events
                ])
                for event in outgoing_events.difference(tracked_events):
                    ProgressbarManager.track(event)
            ProgressbarManager.next()

