# -*- test-case-name: pomodouroboros.model.test.test_observables -*-
from __future__ import annotations

import sys
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum, auto
from functools import total_ordering
from typing import (
    IO,
    Annotated,
    Callable,
    ContextManager,
    Generic,
    Iterable,
    Iterator,
    Mapping,
    MutableMapping,
    MutableSequence,
    Protocol,
    TypeVar,
    dataclass_transform,
    overload,
)
from weakref import proxy

K = TypeVar("K")
V = TypeVar("V")


Kcon = TypeVar("Kcon", contravariant=True)
Vcon = TypeVar("Vcon", contravariant=True)
Scon = TypeVar("Scon", contravariant=True)


class Changes(Protocol[Kcon, Vcon]):
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


@contextmanager
def noop() -> Iterator[None]:
    yield


@dataclass
class IgnoreChanges:
    @classmethod
    def added(cls, key: object, new: object) -> ContextManager[None]:
        return noop()

    @classmethod
    def removed(cls, key: object, old: object) -> ContextManager[None]:
        return noop()

    @classmethod
    def changed(
        cls, key: object, old: object, new: object
    ) -> ContextManager[None]:
        return noop()


_IgnoreChangesImplements: type[Changes[object, object]] = IgnoreChanges
_IgnoreChangesImplementsClass: Changes[object, object] = IgnoreChanges


@dataclass
class DebugChanges(Generic[Kcon, Vcon]):
    original: Changes[Kcon, Vcon] = IgnoreChanges
    stream: IO[str] = field(default_factory=lambda: sys.stderr)

    @contextmanager
    def added(self, key: Kcon, new: Vcon) -> Iterator[None]:
        self.stream.write(f"will add {key!r} {new!r}\n")
        with self.original.added(key, new):
            yield
        self.stream.write(f"did add {key!r} {new!r}\n")

    @contextmanager
    def removed(self, key: Kcon, old: Vcon) -> Iterator[None]:
        self.stream.write(f"will remove {key!r} {old!r}\n")
        with self.original.removed(key, old):
            yield
        self.stream.write(f"did remove {key!r} {old!r}\n")

    @contextmanager
    def changed(self, key: Kcon, old: Vcon, new: Vcon) -> Iterator[None]:
        self.stream.write(f"will change {key!r} from {old!r} to {new!r}\n")
        with self.original.added(key, new):
            yield
        self.stream.write(f"did change {key!r} from {old!r} to {new!r}\n")


_DebugChangesImplements: type[Changes[object, object]] = DebugChanges

_ObjectObserverBound = Changes[str, object]
_O = TypeVar("_O", bound=_ObjectObserverBound)


class _ObserverMarker(Enum):
    sentinel = auto()


_ItsTheObserver = _ObserverMarker.sentinel

CustomObserver = Annotated[_O, _ItsTheObserver]
_AnnotatedType = type(CustomObserver)
Observer = CustomObserver[_ObjectObserverBound]
SequenceObserver = Changes[int | slice, V | Iterable[V]]


@dataclass(eq=False, order=False)
class ObservableDict(MutableMapping[K, V]):
    observer: Changes[K, V]
    _storage: MutableMapping[K, V] = field(default_factory=dict)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, ObservableDict):
            return dict(self._storage) == dict(other._storage)
        elif isinstance(other, dict):
            return dict(self._storage) == dict(other)
        else:
            return NotImplemented

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
            self.observer.changed(key, self._storage[key], value)
            if key in self._storage
            else self.observer.added(key, value)
        ):
            return self._storage.__setitem__(key, value)

    def __delitem__(self, key: K) -> None:
        with self.observer.removed(key, self._storage[key]):
            return self._storage.__delitem__(key)


@total_ordering
@dataclass(repr=False, eq=False, order=False)
class ObservableList(MutableSequence[V]):
    observer: SequenceObserver[V]
    _storage: MutableSequence[V] = field(default_factory=list)

    def __lt__(self, other: object) -> bool:
        if isinstance(other, ObservableList):
            return list(self._storage) < list(other._storage)
        elif isinstance(other, list):
            return list(self._storage) < list(other)
        else:
            return NotImplemented

    def __eq__(self, other: object) -> bool:
        if isinstance(other, ObservableList):
            return list(self._storage) == list(other._storage)
        elif isinstance(other, list):
            return list(self._storage) == list(other)
        else:
            return NotImplemented

    def __repr__(self) -> str:
        return repr(self._storage) + "~(observable)"

    @overload
    def __setitem__(self, index: int, value: V) -> None:
        ...

    @overload
    def __setitem__(self, index: slice, value: Iterable[V]) -> None:
        ...

    def __setitem__(self, index: int | slice, value: V | Iterable[V]) -> None:
        with (
            self.observer.changed(index, self._storage[index], value)
            if (
                isinstance(index, int)
                and (0 <= index < len(self._storage))
                or isinstance(index, slice)
            )
            else self.observer.added(index, value)
        ):
            # the overloads above ensure the proper type dependence between
            # 'index' and 'slice' (slice index means Iterable[V], int index
            # means V), but we can't express the dependent relationship to
            # mypy, so we ignore the resulting errors as narrowly as possible.

            self._storage.__setitem__(
                index,  # type:ignore[index]
                value,  # type:ignore[assignment]
            )

    def __delitem__(self, index: int | slice) -> None:
        with self.observer.removed(index, self._storage[index]):
            self._storage.__delitem__(index)

    def insert(self, index: int, value: V) -> None:
        """
        a value was inserted
        """
        with self.observer.added(index, value):
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
        return self._storage.__iter__()

    def __len__(self) -> int:
        return self._storage.__len__()


@dataclass
class MirrorDict(Generic[K, V]):
    mirror: MutableMapping[K, V]

    @contextmanager
    def added(self, key: K, new: V) -> Iterator[None]:
        yield
        self.mirror[key] = new

    @contextmanager
    def removed(self, key: K, old: V) -> Iterator[None]:
        yield
        del self.mirror[key]

    @contextmanager
    def changed(self, key: K, old: V, new: V) -> Iterator[None]:
        yield
        self.mirror[key] = new


_MirrorDictImplements: type[Changes[str, float]] = MirrorDict[str, float]


@dataclass
class MirrorList(Generic[V]):
    mirror: MutableSequence[V]

    @contextmanager
    def added(self, key: int | slice, new: V | Iterable[V]) -> Iterator[None]:
        yield
        if isinstance(key, int):
            key = slice(key, key)
            new = [new]  # type:ignore
        self.mirror[key] = new  # type:ignore

    @contextmanager
    def removed(
        self, key: int | slice, old: V | Iterable[V]
    ) -> Iterator[None]:
        yield
        del self.mirror[key]

    @contextmanager
    def changed(
        self, key: int | slice, old: V | Iterable[V], new: V | Iterable[V]
    ) -> Iterator[None]:
        yield
        self.mirror[key] = new  # type:ignore


_MirrorListImplements: type[SequenceObserver[str]] = MirrorList[str]


@dataclass
class MirrorObject:
    mirror: object
    nameTranslation: Mapping[str, str]

    @contextmanager
    def added(self, key: str, new: object) -> Iterator[None]:
        yield
        setattr(self.mirror, self.nameTranslation.get(key, key), new)

    @contextmanager
    def removed(self, key: str, old: object) -> Iterator[None]:
        yield
        delattr(self.mirror, self.nameTranslation.get(key, key))

    @contextmanager
    def changed(self, key: str, old: object, new: object) -> Iterator[None]:
        yield
        setattr(self.mirror, self.nameTranslation.get(key, key), new)


@dataclass
class ObservableProperty:
    observer_name: str
    field_name: str

    def __get__(self, instance: object, owner: object) -> object:
        if self.field_name not in instance.__dict__:
            raise AttributeError(f"couldn't find {self.field_name!r}")
        return instance.__dict__[self.field_name]

    def __set__(self, instance: object, value: object) -> None:
        notify: Changes[str, object] = getattr(instance, self.observer_name)

        # I need to avoid invoking the observer if the instance isn't fully
        # initialized
        with notify.changed(
            self.field_name, instance.__dict__[self.field_name], value
        ) if self.field_name in instance.__dict__ else notify.added(
            self.field_name, value
        ):
            instance.__dict__[self.field_name] = value

    def __delete__(self, instance: object) -> None:
        if self.field_name not in instance.__dict__:
            raise AttributeError(f"couldn't find {self.field_name!r}")
        notify: Changes[str, object] = getattr(instance, self.observer_name)
        with notify.removed(
            self.field_name, instance.__dict__[self.field_name]
        ):
            del instance.__dict__[self.field_name]


def _unstringify(cls: type, annotation: object) -> object:
    if not isinstance(annotation, str):
        return annotation
    try:
        mod = sys.modules[cls.__module__]
        clslocals = dict(vars(cls))
        return eval(annotation, mod.__dict__, clslocals)
    except:
        return None


def _isObserver(annotation: object) -> bool:
    if isinstance(annotation, _AnnotatedType):
        # does the standard lib have no nicer way to ask 'is this `Annotated`'?
        for element in annotation.__metadata__:
            if element is _ItsTheObserver:
                return True
    return False


Ty = TypeVar("Ty", bound=type)


class MustSpecifyObserver(Exception):
    """
    You must annotate exactly one attribute with Observer when declaring a
    class to be L{observable}.
    """


@dataclass_transform(field_specifiers=(field,))
def observable(repr: bool = True) -> Callable[[Ty], Ty]:
    def make_observable(cls: Ty) -> Ty:
        observerName = None
        originalAnnotations = cls.__annotations__

        cls = dataclass(repr=repr)(cls)  # type:ignore[assignment]
        for i, (k, v) in enumerate(originalAnnotations.items()):
            if _isObserver(_unstringify(cls, v)):
                observerIndex = i
                observerName = k
                break

        if observerName is None:
            raise MustSpecifyObserver(
                "you must annotate one attribute with Observer"
            )

        for k, v in originalAnnotations.items():
            if k != observerName:
                setattr(cls, k, ObservableProperty(observerName, k))
        if observerIndex != 0:
            # If the observer is not specified as the first argument, then the
            # dataclass-generated __init__ is going to assign other attributes
            # first, and therefore we cannot observe them.  So here we provide
            # a class-level default that will allow the attribute to be
            # retrieved by ObservableProperty.__set__/.__delete__.
            setattr(cls, observerName, IgnoreChanges)
        return cls

    return make_observable


@dataclass(repr=False)
class PathObserver(Generic[Kcon, Vcon]):
    """
    A L{PathObserver} implements L{Changes} for any key / value type and
    translates the key type to a string that represents a path.  You can add
    elements to the path.

    For example, if you have two observables like so, one containing the other,
    and you want to keep track of which thing was changed::

        @observable()
        class B:
            bValue: str
            observer: Observer = IgnoreChanges


        @observable()
        class A:
            b: B
            aValue: str
            observer: Observer = IgnoreChanges

    You can then arrange observers like so::

        root = DebugChanges()
        path = PathObserver(root, "a")

        a = A(B("b"), "a")
        a.observer = path
        a.b.observer = path.child("b")
        a.aValue = "x"
        a.b.bValue = "y"

    and you will see that the changes are reflected with keys of 'a.aValue' and
    'a.b.bValue' respectively.
    """

    wrapped: Changes[str, Vcon]
    prefix: str
    convert: Callable[[Kcon], str] = str
    sep: str = "."

    def __repr__(self) -> str:
        return f"{self.wrapped}/({self.prefix})"

    def _keyPath(self, segment: str) -> str:
        return (
            self.sep.join([self.prefix, segment]) if self.prefix else segment
        )

    def child(self, segment: str) -> PathObserver[Kcon, Vcon]:
        """
        create child path observer
        """
        return PathObserver(
            self.wrapped,
            self._keyPath(segment),
            self.convert,
            self.sep,
        )

    @contextmanager
    def added(self, key: Kcon, new: Vcon) -> Iterator[None]:
        """
        C{value} was added for the given C{key}.
        """
        with self.wrapped.added(self._keyPath(self.convert(key)), new):
            yield

    @contextmanager
    def removed(self, key: Kcon, old: Vcon) -> Iterator[None]:
        """
        C{key} was removed for the given C{key}.
        """
        with self.wrapped.removed(self._keyPath(self.convert(key)), old):
            yield

    @contextmanager
    def changed(self, key: Kcon, old: Vcon, new: Vcon) -> Iterator[None]:
        """
        C{value} was changed from C{old} to C{new} for the given C{key}.
        """
        with self.wrapped.changed(self._keyPath(self.convert(key)), old, new):
            yield


@dataclass(repr=False)
class AfterInitObserver:
    """
    Interposer that handles attribute-added notifications during object
    initialization.
    """

    _original: Changes[str, object] | None = None

    def __repr__(self) -> str:
        return repr(self._original) + "*"

    def added(self, key: str, new: object) -> ContextManager[None]:
        """
        C{value} was added for the given C{key}.
        """
        original = self._original
        if original is not None:
            return original.added(key, new)
        else:
            return noop()

    def removed(self, key: str, old: object) -> ContextManager[None]:
        """
        C{key} was removed for the given C{key}.
        """
        original = self._original
        if original is not None:
            return original.removed(key, old)
        else:
            return noop()

    def changed(
        self, key: str, old: object, new: object
    ) -> ContextManager[None]:
        """
        C{value} was changed from C{old} to C{new} for the given C{key}.
        """
        original = self._original
        if original is not None:
            return original.changed(key, old, new)
        else:
            return noop()

    def finalize(self, ref: object) -> None:
        """
        The observed object has been garbage collected; let the observer go.
        """
        self._original = None


CN = TypeVar("CN", bound=Changes[str, object])


def build(
    observed: Callable[[Changes[str, object]], V],
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
    o = interpose._original = observer(
        observable if strong else proxy(observable, interpose.finalize)
    )
    return observable, o
