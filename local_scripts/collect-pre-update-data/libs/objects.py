# collect-pre-update-data instances simple manipulations


import functools
import operator
import threading


#: str: Name for flag attribute that will be used by MetaInterfaceClass
#: and interfacemethod to check/mark method as contracted by interface.
INTERFACE_METHOD_FLAG_FROM_MCS_NAME = "__is_contracted__"


def is_matching_object(obj, criteria):
    """Match objects against provided criteria

    Parameters:
        :obj (Any): Instance to match.
        :criteria (dict of Any): Each key must match an attribute
            of the object. Built-in attrgetter specification
            is possible. Each value is either a list of acceptable
            values or single possible value.
            Caller must be aware of attribute types.

    Returns:
        :bool: True if the object matches provided criteria.
    """
    votes = []
    for criteria_attr, criteria_values in criteria.items():
        obj_attr = None
        try:
            obj_attr = operator.attrgetter(criteria_attr)(obj)
        except AttributeError:
            continue

        if isinstance(criteria_values, (tuple, list)):
            if (
                isinstance(obj_attr, list)
                and set(criteria_values).issubset(obj_attr)
            ):
                votes.append(True)
            elif obj_attr in criteria_values:
                votes.append(True)
            else:
                votes.append(False)
        else:
            if (
                isinstance(obj_attr, list)
                and criteria_values in obj_attr
            ):
                votes.append(True)
            elif obj_attr == criteria_values:
                votes.append(True)
            else:
                votes.append(False)
    return all(votes)


def interfacemethod(method):
    """Wrap method to mark it as contract part of some interface

    Use decorator in combination with MetaInterfaceClass.
    """
    setattr(method, INTERFACE_METHOD_FLAG_FROM_MCS_NAME, True)
    return method


def threadsafemethod(unsafe_method):
    """Wrap method with lock acquire

    Method should be bound to class/instance that has _lock attribute
    which, in turn, is threading.Lock|threading.RLock object!

    Use as decorator in combination with class/instance how has such.
    """
    @functools.wraps(unsafe_method)
    def locking_wrapper(obj, *args, **kwargs):
        with obj._lock:
            return unsafe_method(obj, *args, **kwargs)
    return locking_wrapper


class MetaStaticClass(type):
    """Provides a possibility of defining purely static classes

    Such classes can be used for keeping some template values within
    single structure maintaining clear semantics in the same time.
    """

    def __new__(cls, name, bases, attrs, allow_classmethods=False):
        """Constructor

        Ancestor override to make sure only @staticmethod static methods
        are attempting to tie to the class.

        Parameters:
            :allow_classmethods (bool): Allows @classmethod declaration
                along with @staticmethod, which may be required
                in very specific scenarios.
        """
        for attr_name, attr_value in attrs.items():
            if attr_name.startswith("_"):
                continue
            if not callable(attr_value):
                continue
            if isinstance(attr_value, staticmethod):
                continue
            if allow_classmethods and isinstance(attr_value, classmethod):
                continue
            raise TypeError(
                f"{name} is static class and non-static public method"
                f"tied to it"
            )
        return super().__new__(cls, name, bases, attrs)

    def __setattr__(self, name, value):
        """Ancestor method override

        Prohibit attribute change. Doesn't guarantee immutability
        for already mutable data types.
        """
        raise AttributeError(
            f"{self.__name__} is static class and {name} attribute "
            f"cannot be changed as any other"
        )

    def __delattr__(self, name):
        """Ancestor method override

        Prohibit attribute removal. Doesn't guarantee immutability
        for already mutable data types.
        """
        raise AttributeError(
            f"{self.__name__} is static class and {name} attribute "
            f"cannot be remove as any other"
        )

    def __call__(self, *args, **kwargs):
        """Ancestor method override

        Raises:
            :TypeError: If you're trying to create class instance.
        """
        raise TypeError(
            f"{self.__name__} is static class and cannot be instantiated"
        )


class MetaInterfaceClass(type):
    """Contract enforcer for strict interface compliance

    Use this metaclass and form contract via public class attirbutes
    in to define minimal requirement for interface compliance.

    The contract implies that public attirbutes defined by ancestor
    should be clearly redefined again by inheritor.

    For methods please use interfacemethod decorator.
    """

    def __new__(cls, name, bases, attrs):
        """Constructor

        Ancestor override to check inheritor-defined contract
        implementation compliance by the currently creating class.
        """
        def _is_contracted(attr, value):
            return (not attr.startswith("_") and (not callable(value) or (
                hasattr(value, INTERFACE_METHOD_FLAG_FROM_MCS_NAME)
            )))

        required = set([
            attr
            for base in bases
            for attr in dir(base)
            if _is_contracted(attr, getattr(base, attr))
        ])
        if not required:
            required = [
                attr
                for attr, value in attrs.items()
                if _is_contracted(attr, value)
            ]
            if required:
                return super().__new__(cls, name, bases, attrs)
            raise TypeError(
                f"{name} class and its ancestors don't have any contract "
                f"defined; should have public class attributes of any type "
                f"except callable to form contract"
            )
        if required:
            missing = [req for req in required if req not in attrs]
            if missing:
                raise TypeError(
                    f"{name} class doesn't implement static attributes "
                    f"required by contract: {missing}"
                )
        return super().__new__(cls, name, bases, attrs)


class MetaStaticInterface(MetaStaticClass, MetaInterfaceClass):
    """Handy combination of ancestors"""


class MetaSingleton(type):
    """Simple and unified approach for singletons creation

    Use this metaclass to convert some classes to singletons without
    overriding their constructors and initializers each time.

    NB: IT'S THREAD UNAWARE!
    You might like to use threadsafemethod decorator.
    """

    def __init__(self, *args, **kwargs):
        """Initializer

        Attributes:
            :_singleton_instance (object): Constructed and initialized
                single instance of the controlled class.
        """
        super().__init__(*args, **kwargs)
        self._meta_singleton_instance = None

    def __call__(self, *args, **kwargs):
        """Ancestor method override

        Provide already created instance if any.
        """
        if self._meta_singleton_instance is None:
            self._meta_singleton_instance = super().__call__(*args, **kwargs)
        return self._meta_singleton_instance


class MetaThreadSafeKeeper(type):
    """Thread-safe values keeper and provider

    Unlike ThreadSafeNamespace doesn't create separate namespaces
    for each thread. All thread access the same one namespace but
    acquiring lock beforehand to avoid corruptions.
    """

    def __init__(self, *args, **kwargs):
        """Initializer

        Attributes:
            :_lock (threading.RLock): Ensures thread-safe access.
        """
        super().__init__(*args, **kwargs)
        self._lock = threading.RLock()

    def __getattribute__(self, name):
        """Ancestor method override

        Protect public names lookup with thread lock.

        Parameters:
            :name (str): Name of property or instances's attribute.

        Returns:
            :Any: Resolved object.
        """
        if name.startswith("_"):
            return super().__getattribute__(name)
        with self._lock:
            return super().__getattribute__(name)

    def __setattr__(self, name, value):
        """Ancestor method override

        Protect public names lookup with thread lock.

        Parameters:
            :name (str): Name of property or instance's attribute.
            :value (Any): New value for it.
        """
        if name.startswith("_"):
            return super().__setattr__(name, value)
        with self._lock:
            return super().__setattr__(name, value)

    def __delattr__(self, name):
        """Ancestor method override

        Protect public names lookup with thread lock.

        Parameters:
            :name (str): Name of section's object or instance's.
        """
        if name.startswith("_"):
            return super().__delattr__(name)
        with self._lock:
            return super().__delattr__(name)

