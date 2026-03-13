# collect-pre-update-data output data formatting tools


import abc


def multiline_list(arr):
    """Useful to avoid fstrings limitations and to call repr inside

    Parameters:
        :arr (list): List to print.

    Returns:
        :str: Multiline string list representation.
    """
    return "\n".join(f"{item!r}" for item in arr)


def indent_strs(strings):
    """Useful to avoid fstrings limitations and to indent strings inside

    Parameters:
        :strings (str): Oneline or multiline strings.

    Returns:
        :str: Indented string.
    """
    return "\n".join([f"  {string}" for string in strings.splitlines()])


def justify_strs_parts(data, separator, separator_limit=1, splitter=None):
    """Re-aling strings by max length of parts divided by separator

    Turns something like:
        KEY_AAA: VALUE_AAA
        KEY_BBBBBB: VALUE_BBBBBB
    Into:
        KEY_AAA:    VALUE_AAA
        KEY_BBBBBB: VALUE_BBBBBB

    Parameters:
        :data (str): String(s) to re-aling.
        :separator (str): Symbol used to divide string into parts.
        :separator_limit (int): Maximum divisions by separator.
        :splitter (str|None): Multiline divider into strings.

    Returns:
        :str: Re-alingned string(s).
    """
    splitter = splitter or "\n"
    elems_formatted = []
    elems_separated = []
    parts_widths = []

    for elem in data.split(splitter):
        elems_separated.append(elem.split(separator, separator_limit))
        columns_widths_len = len(parts_widths)

        for i in range(len(elems_separated[-1])):
            elem_part_len = len(f"{elems_separated[-1][i]}{separator}")

            if i >= columns_widths_len:
                parts_widths.append(elem_part_len)
            elif parts_widths[i] < elem_part_len:
                parts_widths[i] = elem_part_len

    for elem_parts in elems_separated:
        elem_parts_len = len(elem_parts)
        elems_formatted.append("".join(
            f"{elem_parts[i]}{separator}".ljust(parts_widths[i])
            if i+1 < elem_parts_len
            else elem_parts[i].ljust(parts_widths[i]).rstrip(" ")
            for i in range(elem_parts_len)
        ))

    return splitter.join(elems_formatted).rstrip(" ")


def dump_object(
    obj,
    names_to_mask=None,
    mask_protected=False,
    mask_private=True,
    mask_callable=True
):
    """Dump object instance/class attributes

    Parameters:
        :obj (Any): Class itself or its instance.
        :names_to_mask (None|list of str): Optional list of names to
            omit in dump.
        :mask_protected (bool): If True protected attributes will be
            omitted.
        :mask_private (bool): If True private attributes will be
            omitted.
        :mask_callable (bool): If True callable attributes will be
            omitted.

    Returns:
        :dict of str: Raw string representation of object.
    """
    def _check_not_requested_mask(attr):
        return not names_to_mask or attr not in names_to_mask
    def _check_not_protected(attr):
        return (
            not mask_protected
            or attr.startswith("__") or not attr.startswith("_")
        )
    def _check_not_private(attr):
        return not mask_private or not attr.startswith("__")
    def _check_not_callable(value):
        return (
            not mask_callable
            or (not callable(value) and not isinstance(value, classmethod))
        )

    return {
        f"{attr}": f"{value!r}"
        for attr, value in sorted(obj.__dict__.items())
        if (
            _check_not_requested_mask(attr)
            and _check_not_protected(attr)
            and _check_not_private(attr)
            and _check_not_callable(value)
        )
    }

def dump_object_multiline_pairs(*args, **kwargs):
    """Dump object instance/class attributes

    Generates multiline string in the following format:
        ATTR = VALUE

    Parameters are the same as for dump_object().

    Returns:
        :str: Multiline string representation of object.
    """
    try:
        class_name = args[0].__name__
    except AttributeError:
        class_name = args[0].__class__.__name__
    object_attrs = "\n".join([
        f"{attr} = {value}"
        if "\n" not in value
        else f"{attr} = (\n{indent_strs(value)}\n)"
        for attr, value in dump_object(*args, **kwargs).items()
    ])
    return f"{class_name}(\n{indent_strs(object_attrs)}\n)"

def dump_object_oneline_reference(*args, **kwargs):
    """Dump object instance/class attributes

    Generates oneline string in the following format:
        ObjectClassName(attr=value)

    Parameters are the same as for dump_object().

    Returns:
        :str: Oneline string representation of object.
    """
    try:
        class_name = args[0].__name__
    except AttributeError:
        class_name = args[0].__class__.__name__
    object_attrs = ", ".join([
        f"{attr}={value}"
        if "\n" not in value
        else f"{attr}=(\n{indent_strs(value)}\n)"
        for attr, value in dump_object(*args, **kwargs).items()
    ])
    return f"{class_name}({object_attrs})"


class HumanFriendlyRepresentor(str, abc.ABC):
    """Generic pretty formatter for object representations

    Subclass and instantiate with the target object. The instance
    evaluates to a formatted multi-line string. Output is built by
    translating attribute names and transforming their values.

    Customize via class attributes:
    - _represent_order - Sequence of attribute names to include and in
      what order. Must be overridden.
    - _name_translation - Map attribute names to human-friendly labels.
      Every name in from the above must have a label here; otherwise an
      exception is raised.
    - _value_transformation - Map attribute names to callables that
      produce human-friendly values. If a name is missing, standard
      string representation is used. Note all callables should have only
      **kwargs as parameter and expect at least "value" key. If you want
      to use some foreign fuction, just wrap it with lambda.
    """

    #: list of str: Manually defined order of formatted attributes.
    _represent_order = []
    #: dict of str and str: Presets to translate attribute names.
    _name_translation = {}
    #: dict of str and callable: Presets to transform attribute values.
    #: All callables should have **kwargs parameter. You should access
    #: the original value via "value" key.
    _value_transformation = {}

    def __new__(
        cls,
        obj,
        indent=0,
        prefix=None,
        separator=None,
        multiline=True,
        justify=False,
        inherit=None,
    ):
        """Constructor

        Parameters:
            :obj (Any): Class to format itself or its instance.
            :indent (int): Number of indent spaces for output.
            :prefix (str|None): String to add as leading to all lines.
            :separator (str|None): Symbol to separate ATTR and VALUE.
            :multiline (bool): Use ; instead of \\n if False.
            :justify (bool): Works only if multiline.
                See justify_strs_parts() for more details.
            :inherit (dict|None): Additional parameters to pass to value
                transformation callable.

        Raises:
            :AttributeError: If order or names presets aren't set.
            :ValueError: If attr from order is absent in names preset.
        """
        if not (cls._represent_order and cls._name_translation):
            raise AttributeError(
                f"Improper definition of HumanFriendlyFormatter inheritor "
                f"{cls.__name__!r}: both cls._represent_order and "
                f"cls._name_translation should be defined"
            )
        indent = " " * indent
        prefix = prefix or ""
        separator = separator or ": "
        newline = "\n" if multiline else "; "
        inherit = inherit or {}
        formatted = ""
        is_first_attr = True

        for attr in cls._represent_order:
            if attr not in cls._name_translation:
                raise ValueError(
                    f"{attr!r} attribute is present in order set but name "
                    f"translation is missing for it"
                )
            name = cls._name_translation[attr]
            raw_value = getattr(obj, attr)
            value = (
                cls._value_transformation[attr](value=raw_value, **inherit)
                if attr in cls._value_transformation
                else str(raw_value)
            )
            if value[0] == "\n":
                formatted += f"{indent}{prefix}{name}{separator.rstrip(' ')}{value}{newline}"
            else:
                formatted += f"{indent}{prefix}{name}{separator}{value}{newline}"
            if not multiline and is_first_attr:
                is_first_attr = False
                indent = ""
        if multiline and justify:
            return justify_strs_parts(formatted, separator)
        return formatted


class ReportEntryFormatter(HumanFriendlyRepresentor, abc.ABC):
    """Handy shortcut for reports formatting

    Alternative formatting specification for fstrings is possible:
    - align.(bool) - Switches the corresponding parameter.
    - indent.(int) - $_
    - oneline.(bool) - $_
    - (str) - Returns transformed value of the corresponding name.

    You can access those specification values in _value_transformation
    presets via corresponding kwargs keys.
    """

    def __new__(cls, obj, spec=None, indent=0, oneline=False, align=False):
        """Constructor

        Parameters:
            :obj (Any): Class to format itself or its instance.
            :spec (str|None): Formatting specification.
            :indent (int): Number of indent spaces for output.
            :oneline (bool): Put every attribute on the same line if True.

        Raises:
            :ValueError: If unexpected value specified for any of
                parameters including fstrings.
        """
        def _str_to_bool():
            if not value:
                raise ValueError(
                    f"No value specified for {key} fstring parameter; "
                    f"bool is expected"
                )
            elif value == "True" or value == "true":
                return True
            elif value == "False" or value == "false":
                return False
            else:
                raise ValueError(
                    f"Unexpected value for {key} fstring parameter "
                    f"instead of bool: {value!r}"
                )

        if not spec:
            return super().__new__(
                cls,
                obj,
                indent=indent,
                multiline=(not oneline),
                justify=align,
                inherit={"indent": indent, "oneline": oneline}
            )
        for param in spec.split(":"):
            param = param.split(".")
            key = param[0]
            value = param[1] if len(param) > 1 else None
            if key.startswith("align"):
                align = _str_to_bool()
            elif key.startswith("oneline"):
                oneline = _str_to_bool()
            elif key.startswith("indent"):
                try:
                    indent = int(value)
                except ValueError:
                    raise ValueError(
                        f"Unexpected value for indent fstring parameter "
                        f"instead of int: {value!r}"
                    )
            elif key in cls._value_transformation:
                if value:
                    raise ValueError(
                        "Unexpected value for {key} attribute; "
                        "expected nothing"
                    )
                return cls._value_transformation[key](
                    value=getattr(obj, key)
                ).strip()
            else:
                raise ValueError(
                    f"Unexpected fstring parameter passed: {key}.{value}"
                )
        return super().__new__(
            cls,
            obj,
            indent=indent,
            multiline=(not oneline),
            justify=align,
            inherit={"indent": indent, "oneline": oneline}
        )


class AtomicModificationReport(ReportEntryFormatter):
    """AtomicModification human readable representation"""

    #: list of str: Ancestor attribute override.
    _represent_order = [
        "resolution",
        #"is_ignored",
        #"is_warning",
    ]
    #: dict of str and str: Ancestor attribute override.
    _name_translation = {
        "resolution":  "Resolution",
        #"is_ignored": "Should you ignore it",
        #"is_warning": "Is forced to be reviewed"
    }
    #: dict of str and callable: Ancestor attribute override.
    _value_transformation = {
        "resolution":  lambda **kwargs: kwargs["value"].desc(),
        #"is_ignored": lambda **kwargs: (
        #    "Yes, according to default filters"
        #    if kwargs["value"]
        #    else "No, not mentioned in default filters"
        #),
        #"is_warning": lambda **kwargs: (
        #    "Yes, according to default filters"
        #    if kwargs["value"]
        #    else "No, not mentioned in default filters"
        #)
    }


class ModifiedFileReport(AtomicModificationReport):
    """ModifiedFile human readable representation"""

    #: list of str: Ancestor attribute extension.
    _represent_order = (
        ["path", "package"] + AtomicModificationReport._represent_order
    )
    #: dict of str and str: Ancestor attribute copy.
    _name_translation = dict(AtomicModificationReport._name_translation)
    #: str: Ancestor attribute extension.
    _name_translation["path"] = "Path to modified file"
    #: str: Ancestor attribute extension.
    _name_translation["package"] = "RPM owner of modified file"
    #: dict of str and callable: Ancestor attribute copy.
    _value_transformation = dict(AtomicModificationReport._value_transformation)
    #: callable: Ancestor attribute extension.
    _value_transformation["package"] = lambda **kwargs: (
        kwargs["value"] if kwargs["value"] else "unknown, not important"
    )


class ModifiedRepoFilePIReport(ModifiedFileReport):
    """ModifiedRepoFilePI human readable representation"""

    #: list of str: Ancestor attribute extension.
    _represent_order = (
        ModifiedFileReport._represent_order[:2]
        + ["change_type"]
        + ModifiedFileReport._represent_order[2:]
    )
    #: dict of str and str: Ancestor attribute copy.
    _name_translation = dict(ModifiedFileReport._name_translation)
    #: str: Ancestor attribute extension.
    _name_translation["change_type"] = "File git status"
    #: dict of str and callable: Ancestor attribute copy.
    _value_transformation = dict(ModifiedFileReport._value_transformation)
    #: callable: Ancestor attribute extension.
    _value_transformation["change_type"] = lambda **kwargs: (
        kwargs["value"] if kwargs["value"] else "UNKNOWN, critical"
    )


class InstalledRPMReport(AtomicModificationReport):
    """InstalledRPM human readable representation"""

    #: list of str: Ancestor attribute extension.
    _represent_order = ["name"] + AtomicModificationReport._represent_order
    #: dict of str and str: Ancestor attribute copy.
    _name_translation = dict(AtomicModificationReport._name_translation)
    #: str: Ancestor attribute extension.
    _name_translation["name"] = "RPM name"


class ComplexModificationReport(ReportEntryFormatter):
    """ComplexModification human readable representation"""

    #: list of str: Ancestor attribute override.
    _represent_order = [
        "amod",
        "servers"
    ]
    #: dict of str and str: Ancestor attribute override.
    _name_translation = {
        "amod":    "Modified object",
        "servers": "Affected servers"
    }
    #: dict of str and callable: Ancestor attribute override.
    _value_transformation = {
        "amod": lambda **kwargs: (
            "\n"
            + f"{kwargs['value']:indent.{kwargs['indent'] + 2}:align.true}"
                .rstrip()
        ),
        "servers": lambda **kwargs: (
            "\n" + justify_strs_parts(
                "\n".join(
                    f"{s:oneline.true:indent.{kwargs['indent'] + 2}}"
                        .rstrip()
                    for s in kwargs["value"]
                ),
                "; ",
                separator_limit=-1
            )
        )
    }


class PIModReport(ComplexModificationReport):
    """PIMod human readable representation"""

    #: list of str: Ancestor attribute extension.
    _represent_order = (
        ComplexModificationReport._represent_order[:1]
        + ["bundle", "patch"]
        + ComplexModificationReport._represent_order[1:]
    )
    #: dict of str and str: Ancestor attribute copy.
    _name_translation = dict(ComplexModificationReport._name_translation)
    #: str: Ancestor attribute extension.
    _name_translation["bundle"] = "Affected PI bundle"
    _name_translation["patch"] =  "Affected PI patch"
    #: dict of str and callable: Ancestor attribute copy.
    _value_transformation = dict(ComplexModificationReport._value_transformation)
    #: callable: Ancestor attribute extension.
    _value_transformation["bundle"] = lambda **kwargs: (
        "\n"
        + f"{kwargs['value']:indent.{kwargs['indent'] + 2}:align.true}"
            .rstrip()
    )
    _value_transformation["patch"] = lambda **kwargs: (
        "\n"
        + f"{kwargs['value']:indent.{kwargs['indent'] + 2}:align.true}"
            .rstrip()
    )

class PIPatchReport(ReportEntryFormatter):
    """PIPatch record human readable representation"""

    #: list of str: Ancestor attribute override.
    _represent_order = [
        "subject",
        "sha",
        "number",
        "fixed_in",
        "csup_tt",
        "dev_tt",
    ]
    #: dict of str and str: Ancestor attribute override.
    _name_translation = {
        "subject":  "Patch subject",
        "sha":      "Patch SHA sum",
        "number":   "Patch number in PI bundle",
        "fixed_in": "Fixed-In release where patch is present",
        "csup_tt":  "Support-Ticket where patch was applied",
        "dev_tt":   "Devel-Issue where patch was created"
    }
    #: dict of str and callable: Ancestor attribute override.
    _value_transformation = {
        "fixed_in": lambda **kwargs: (
            kwargs["value"] if kwargs["value"] else "UNKNOWN, critical"
        ),
        "csup_tt": lambda **kwargs: (
            kwargs["value"] if kwargs["value"] else "UNKNOWN, critical"
        ),
        "dev_tt": lambda **kwargs: (
            kwargs["value"] if kwargs["value"] else "unknown, not important"
        ),
    }


class PIBundleReport(ReportEntryFormatter):
    """PIBundle record human readable representation"""

    #: list of str: Ancestor attribute override.
    _represent_order = [
        "name",
        "sha",
        "is_dirty"
    ]
    #: dict of str and str: Ancestor attribute override.
    _name_translation = {
        "name":     "Bundle name",
        "sha":      "Bundle SHA sum",
        "is_dirty": "Contains unaccounted modifications"
    }
    #: dict of str and callable: Ancestor attribute override.
    _value_transformation = {
        "is_dirty": lambda **kwargs: (
            "Yes, should be investigated"
            if kwargs["value"]
            else "No, everything is clean"
        )
    }


class ServerReport(ReportEntryFormatter):
    """Server record human readable representation"""

    #: list of str: Ancestor attribute override.
    _represent_order = [
        "name",
        "ip",
        #"_is_known"
    ]
    #: dict of str and str: Ancestor attribute override.
    _name_translation = {
        "name":       "Server name",
        "ip":         "Server IP",
        #"_is_known": "Is part of installation"
    }
    #: dict of str and callable: Ancestor attribute override.
    _value_transformation = {
        "name": (
            lambda **kwargs: kwargs["value"] if kwargs["value"] else "ERROR"
        ),
        "ip": (
            lambda **kwargs: kwargs["value"] if kwargs["value"] else "ERROR"
        ),
        #"_is_known": lambda **kwargs: (
        #    "Yes, found in PI" if kwargs["value"] else "No, absent in PI"
        #)
    }

