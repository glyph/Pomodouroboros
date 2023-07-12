
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import (
    Generic,
    Annotated,
    Callable,
    ContextManager,
    Iterable,
    Iterator,
    MutableMapping,
    MutableSequence,
    Protocol,
    TypeVar,
    overload,
)
from weakref import proxy

from typing_extensions import dataclass_transform

K = TypeVar("K")
V = TypeVar("V")


Kcon = TypeVar("Kcon", contravariant=True)
Vcon = TypeVar("Vcon", contravariant=True)
Scon = TypeVar("Scon", contravariant=True)


class ChangeNotifications(Protocol[Kcon, Vcon]):
    """
    Methods to observe changes.

    Each method is a context manager; the change will be performed in the body
    of the context manager.

    This is used for mutable mappings, sequences, and objects.

        1. When observing a mapping, C{Kcon} and C{Vcon} are defined by the
           mapping's key and value types.

        2. When observing an object, C{Kcon} is L{str} and C{Vcon} is
           C{object}; you must know the type of the attribute being changed.

        3. When observing a sequence, C{Kcon} is C{int | slice} and C{Vcon} is
           the type of the sequence contents.
    """

    def added(self, key: Kcon, new: Vcon) -> ContextManager[None]:
        """
        C{value} was added for the given C{key}.
        """

    def removed(self, key: Kcon, old: Vcon) -> ContextManager[None]:
        """
        C{key} was removed for the given C{key}.
        """

    def changed(self, key: Kcon, old: Vcon, new: Vcon) -> ContextManager[None]:
        """
        C{value} was changed from C{old} to C{new} for the given C{key}.
        """


ObjectNotifierBound = ChangeNotifications[str, object]
NotifierMustBe = TypeVar("NotifierMustBe", bound=ObjectNotifierBound)
ItsTheNotifier = object()
Notifier = Annotated[NotifierMustBe, ItsTheNotifier]
AnyNotifier = Notifier[ObjectNotifierBound]


@dataclass
class ObservableDictionary(MutableMapping[K, V]):
    _notifier: ChangeNotifications[K, V]
    _storage: MutableMapping[K, V]

    # unchanged proxied read operations
    def __getitem__(self, key: K) -> V:
        return self._storage.__getitem__(key)

    def __iter__(self) -> Iterator[K]:
        return self._storage.__iter__()

    def __len__(self) -> int:
        return self._storage.__len__()

    # notifying write operations
    def __setitem__(self, key: K, value: V) -> None:
        with (
            self._notifier.changed(key, self._storage[key], value)
            if key in self._storage
            else self._notifier.added(key, value)
        ):
            return self._storage.__setitem__(key, value)

    def __delitem__(self, key: K) -> None:
        with self._notifier.removed(key, self._storage[key]):
            return self._storage.__delitem__(key)


@dataclass(repr=False)
class ObservableList(MutableSequence[V]):
    """ """

    _notifier: ChangeNotifications[int | slice, V | Iterable[V]]
    _storage: MutableSequence[V]

    def __repr__(self) -> str:
        return repr(self._storage) + "~(observable)"

    @overload
    def __setitem__(self, index: int, value: V) -> None:
        """ """

    @overload
    def __setitem__(self, index: slice, value: Iterable[V]) -> None:
        """ """

    def __setitem__(self, index: int | slice, value: V | Iterable[V]) -> None:
        with (
            self._notifier.changed(index, self._storage[index], value)
            if (
                isinstance(index, int)
                and (0 <= index < len(self._storage))
                or isinstance(index, slice)
            )
            else self._notifier.added(index, value)
        ):
            # overload above ensure type dependence between 'index' and 'slice',
            # but we can't express to mypy the dependent relationship, so we
            # type\:ignore

            self._storage.__setitem__(index, value)  # type:ignore[index,assignment]

    def __delitem__(self, index: int | slice) -> None:
        """ """
        with self._notifier.removed(index, self._storage[index]):
            self._storage.__delitem__(index)

    def insert(self, index: int, value: V) -> None:
        """
        a value was inserted
        """
        with self._notifier.added(index, value):
            self._storage.insert(index, value)

    # proxied read operations
    @overload
    def __getitem__(self, index: int) -> V:
        ...

    @overload
    def __getitem__(self, index: slice) -> MutableSequence[V]:
        ...

    def __getitem__(self, index: slice | int) -> V | MutableSequence[V]:
        return self._storage.__getitem__(index)

    def __iter__(self) -> Iterator[V]:
        """ """
        return self._storage.__iter__()

    def __len__(self) -> int:
        """ """
        return self._storage.__len__()


@dataclass
class ObservableProperty:
    notifier_name: str
    field_name: str

    def __get__(self, instance: object, owner: object) -> object:
        if self.field_name not in instance.__dict__:
            raise AttributeError(f"couldn't find {self.field_name!r}")
        return instance.__dict__[self.field_name]

    def __set__(self, instance: object, value: object) -> None:
        notify: ChangeNotifications[str, object] = getattr(instance, self.notifier_name)
        # I need to avoid invoking the observer if the instance isn't fully
        # initialized
        with notify.changed(
            self.field_name, instance.__dict__[self.field_name], value
        ) if self.field_name in instance.__dict__ else notify.added(
            self.field_name, value
        ):
            instance.__dict__[self.field_name] = value


import sys


def unstringize_one(cls: type, annotation: object) -> object:
    if not isinstance(annotation, str):
        return annotation
    try:
        return eval(
            annotation,
            sys.modules[cls.__module__].__dict__,
            dict(vars(cls)),
        )
    except:
        return None


def is_notifier(annotation: object) -> bool:
    if isinstance(annotation, type(Notifier)):
        # does the standard lib have no nicer way to ask 'is this `Annotated`'?
        for element in annotation.__metadata__:
            if element is ItsTheNotifier:
                return True
    return False


Ty = TypeVar("Ty", bound=type)


@dataclass_transform(field_specifiers=(field,))
def observable(repr: bool = True) -> Callable[[Ty], Ty]:
    def make_observable(cls: Ty) -> Ty:
        notifierName = None

        for k, v in cls.__annotations__.items():
            if is_notifier(unstringize_one(cls, v)):
                notifierName = k

        if notifierName is None:
            raise RuntimeError("you must annotate one attribute with Notifier[T]")

        for k, v in cls.__annotations__.items():
            if k != notifierName:
                setattr(cls, k, ObservableProperty(notifierName, k))
        return dataclass(repr=repr)(cls)  # type:ignore[return-value]

    return make_observable


@contextmanager
def empty() -> Iterator[None]:
    yield


@dataclass(repr=False)
class PathObserver(Generic[Kcon, Vcon]):
    """
    Path Observer!
    """

    wrapped: ChangeNotifications[str, Vcon]
    prefix: str
    convert: Callable[[Kcon], str] = str
    sep: str = "."

    def __repr__(self) -> str:
        return f"{self.wrapped}/({self.prefix})"

    def child(self, segment: str) -> PathObserver[Kcon, Vcon]:
        """
        create child path observer
        """
        return PathObserver(
            self.wrapped,
            self.sep.join([self.prefix, segment]),
            self.convert,
            self.sep,
        )

    @contextmanager
    def added(self, key: Kcon, new: Vcon) -> Iterator[None]:
        """
        C{value} was added for the given C{key}.
        """
        with self.wrapped.added(self.sep.join([self.prefix, self.convert(key)]), new):
            yield

    @contextmanager
    def removed(self, key: Kcon, old: Vcon) -> Iterator[None]:
        """
        C{key} was removed for the given C{key}.
        """
        with self.wrapped.removed(self.sep.join([self.prefix, self.convert(key)]), old):
            yield

    @contextmanager
    def changed(self, key: Kcon, old: Vcon, new: Vcon) -> Iterator[None]:
        """
        C{value} was changed from C{old} to C{new} for the given C{key}.
        """
        with self.wrapped.changed(
            self.sep.join([self.prefix, self.convert(key)]), old, new
        ):
            yield


@dataclass(repr=False)
class AfterInitObserver:
    """
    Interposer that handles attribute-added notifications during object
    initialization.
    """

    _actual: ChangeNotifications[str, object] | None = None

    def __repr__(self) -> str:
        return repr(self._actual) + "*"

    def added(self, key: str, new: object) -> ContextManager[None]:
        """
        C{value} was added for the given C{key}.
        """
        actual = self._actual
        if actual is not None:
            return actual.added(key, new)
        else:
            return empty()

    def removed(self, key: str, old: object) -> ContextManager[None]:
        """
        C{key} was removed for the given C{key}.
        """
        actual = self._actual
        if actual is not None:
            return actual.removed(key, old)
        else:
            return empty()

    def changed(self, key: str, old: object, new: object) -> ContextManager[None]:
        """
        C{value} was changed from C{old} to C{new} for the given C{key}.
        """
        actual = self._actual
        if actual is not None:
            return actual.changed(key, old, new)
        else:
            return empty()

    def finalize(self, ref: object) -> None:
        """
        The observed object has been garbage collected; let the observer go.
        """
        self._actual = None


CN = TypeVar("CN", bound=ChangeNotifications[str, object])


def build(
    observed: Callable[[ChangeNotifications[str, object]], V],
    observer: Callable[[V], CN],
    *,
    strong: bool = False,
) -> tuple[V, CN]:
    """
    Build an observer that requires being told about the object it's observing.

    @param strong: By default, to avoid circular references and the attendant
        load on the cyclic GC, we will give C{observer} a weakref proxy object
        to the result of C{builder} rather than a direct reference.  For
        esoteric use-cases, however, a strong reference may be required, so
        passing C{strong=True} will omit the proxy.
    """
    interpose = AfterInitObserver()
    observable: V = observed(interpose)
    o = interpose._actual = observer(
        observable if strong else proxy(observable, interpose.finalize)
    )
    return observable, o


# --- 8< --- cut here --- 8< ---

print("expecting an error when I forget to add a Notifier[...] to an @observable():")
try:

    @observable()
    class Oops:
        name: str
        age: int

except Exception as e:
    print("got it:", e)
else:
    raise RuntimeError("didn't get it")


@dataclass(repr=False)
class MyChanger:
    """ """

    mc: MyClass

    def __repr__(self) -> str:
        """ """
        return "~"

    @contextmanager
    def added(self, key: str, new: object) -> Iterator[None]:
        """
        C{value} was added for the given C{key}.
        """
        print(f"{self.mc} will add {key!r} {new!r}")
        yield
        print(f"{self.mc} did add {key!r} {new!r}")

    @contextmanager
    def removed(self, key: str, old: object) -> Iterator[None]:
        """
        C{key} was removed for the given C{key}.
        """
        print(f"{self.mc} will remove {key!r} (was {old!r})")
        yield
        print(f"{self.mc} did remove {key!r} (was {old!r})")

    @contextmanager
    def changed(self, key: str, old: object, new: object) -> Iterator[None]:
        """
        C{value} was changed from C{old} to C{new} for the given C{key}.
        """
        print(f"{self.mc} will change {key!r} from {old!r} to {new!r}")
        yield
        print(f"{self.mc} did change {key!r} from {old!r} to {new!r}")


@observable()
class MyClass:
    notifier: AnyNotifier
    name: str
    age: int
    emails: ObservableList

    @classmethod
    def new(
        cls, notifier: ChangeNotifications[str, object], name: str, age: int
    ) -> MyClass:
        """ """
        p: PathObserver[object, object] = PathObserver(notifier, "self")
        return cls(p, name, age, emails=ObservableList(p.child("emails"), []))


print("# create")
person, _ = build(
    lambda notifier: MyClass.new(notifier=notifier, name="John", age=30),
    lambda mycls: MyChanger(mycls),
    # strong=True,
)
print("(nothing, hopefully)")
print("# attributes")
person.name = "Bob"
person.age = 35
print("# sequence")
person.emails.append("one@one.com")
person.emails.append("two@two.com")
print("# clear")
person.emails.clear()
