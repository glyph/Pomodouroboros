from __future__ import annotations

import sys
from contextlib import contextmanager
from dataclasses import dataclass, field
from io import StringIO
from typing import (
    Annotated,
    Any,
    Callable,
    ContextManager,
    Generic,
    Iterable,
    Iterator,
    MutableMapping,
    MutableSequence,
    Protocol,
    TypeVar,
    overload,
)
from weakref import proxy

from twisted.trial.unittest import SynchronousTestCase as TC
from typing_extensions import dataclass_transform

from ..observables import (
    Changes,
    MustSpecifyObserver,
    ObservableList,
    Observer,
    PathObserver,
    build,
    observable,
    DebugChanges,
    MirrorList,
    MirrorObject,
    ObservableDict,
    MirrorDict,
)


class TestObservables(TC):
    """
    tests for observables
    """

    def test_observerErrorMessage(self) -> None:
        """
        If we make an L{observable} class without providing a L{Observer}
        annotation, we get a nice error message telling us that it's invalid.
        """
        with self.assertRaises(MustSpecifyObserver) as msn:

            @observable()
            class Oops:
                name: str
                age: int

        self.assertIn(
            "you must annotate one attribute with Observer",
            str(msn.exception),
        )

    def test_buildAndObserve(self) -> None:
        """
        simple cases
        """
        example, cr = build(
            lambda observer: Example.new(
                observer=observer, name="John", age=30
            ),
            lambda mycls: ChangeRecorder(mycls),
            # strong=True,
        )
        self.assertEqual(cr.changes, [])
        example.value1 = "x"
        example.value2 = 3
        example.valueList.append("hello")
        example.valueList.append("goodbye")
        example.valueList[1] = "goodbye!"
        del example.valueList[1]
        self.assertEqual(
            [
                ("will change", "value1", "John", "John", "x"),
                ("did change", "value1", "x", "John", "x"),
                ("will change", "value2", 30, 30, 3),
                ("did change", "value2", 3, 30, 3),
                ("will add", "list.0", "not found"),
                ("did add", "list.0", "not found"),
                ("will add", "list.1", "not found"),
                ("did add", "list.1", "not found"),
                (
                    "will change",
                    "list.1",
                    "not found before",
                    "goodbye",
                    "goodbye!",
                ),
                (
                    "did change",
                    "list.1",
                    "not found after",
                    "goodbye",
                    "goodbye!",
                ),
                ("will remove", "list.1", None, "goodbye!"),
                ("did remove", "list.1", None, "goodbye!"),
            ],
            cr.changes,
        )

    def test_debug(self) -> None:
        """
        L{DebugChanges} will write some text to allow you to easily inspect
        changes being delivered.
        """
        io = StringIO()
        example, debug = build(
            lambda observer: Example.new(
                observer=observer, name="John", age=30
            ),
            lambda mycls: DebugChanges(ChangeRecorder(mycls), io),
            # strong=True,
        )

        # can't express a bound that DebugChanges[K, V].original is a TypeVar
        # with its own type but also bounded by Changes[K, V]
        # https://github.com/python/typing/issues/548
        cr: ChangeRecorder = debug.original  # type:ignore[assignment]

        example.value1 = "new value"
        del example.value1
        example.valueList.append("new list value")
        expectedDebugOutput = "\n".join(
            [
                "will change 'value1' from 'John' to 'new value'",
                "did change 'value1' from 'John' to 'new value'",
                "will remove 'value1' 'new value'",
                "did remove 'value1' 'new value'",
                "will add 'list.0' 'new list value'",
                "did add 'list.0' 'new list value'",
                "",
            ]
        )
        expectedChanges = [
            ("will add", "value1", "John"),
            ("did add", "value1", "new value"),
            ("will remove", "value1", "new value", "new value"),
            ("did remove", "value1", None, "new value"),
            ("will add", "list.0", "not found"),
            ("did add", "list.0", "not found"),
        ]
        self.assertEqual(cr.changes, expectedChanges)
        self.assertEqual(io.getvalue(), expectedDebugOutput)

    def test_mirrorList(self) -> None:
        """
        A L{MirrorList} can update from one list to another.
        """
        a: list[str] = []
        b: list[str] = []

        o = ObservableList(MirrorList(b), a)
        o.append("1")
        self.assertEqual(a, b)
        o.insert(0, "2")
        self.assertEqual(a, b)
        o.extend(str(each) for each in range(10))
        self.assertEqual(a, b)
        del o[3:7]
        self.assertEqual(a, b)

    def test_mirrorDict(self) -> None:
        """
        A L{MirrorDict} can update from one dictionary to another.
        """
        a: dict[str, float] = {}
        b: dict[str, float] = {}
        o = ObservableDict(MirrorDict(b), a)
        o["hello"] = 1
        self.assertEqual(a, b)
        o["goodbye"] = 2
        self.assertEqual(a, b)
        o["goodbye"] = 2
        self.assertEqual(a, b)
        o.pop("hello")
        self.assertEqual(a, b)

    def test_mirrorObject(self) -> None:
        nameMapping = {"r": "red", "g": "green", "b": "blue"}
        b = VerboseColor("fullred", 1, 0, 0)
        a = TerseColor(MirrorObject(b, nameMapping), "fullred", 1, 0, 0)

        def check() -> None:
            self.assertEqual(a.tuplify(), b.tuplify())

        check()
        a.name = "fullblue"
        check()
        a.r = 0
        check()
        # check __delete__ for completeness even though this leaves the object
        # invalid
        del a.b
        check()
        a.b = 1
        check()


@observable()
class TerseColor:
    observer: Observer
    name: str
    r: float
    g: float
    b: float

    def tuplify(self) -> tuple[str, float, float, float | None]:
        return (self.name, self.r, self.g, getattr(self, "b", None))


@dataclass
class VerboseColor:
    name: str
    red: float
    green: float
    blue: float

    def tuplify(self) -> tuple[str, float, float, float | None]:
        return (self.name, self.red, self.green, getattr(self, "blue", None))


@dataclass(repr=False)
class ChangeRecorder:
    example: Example
    changes: list[Any] = field(default_factory=list)

    def __repr__(self) -> str:
        return "~"

    @contextmanager
    def added(self, key: str, new: object) -> Iterator[None]:
        """
        C{value} was added for the given C{key}.
        """
        self.changes.append(
            ("will add", key, getattr(self.example, key, "not found"))
        )
        yield
        self.changes.append(
            ("did add", key, getattr(self.example, key, "not found"))
        )

    @contextmanager
    def removed(self, key: str, old: object) -> Iterator[None]:
        """
        C{key} was removed for the given C{key}.
        """
        self.changes.append(
            ("will remove", key, getattr(self.example, key, None), old)
        )
        yield
        self.changes.append(
            ("did remove", key, getattr(self.example, key, None), old)
        )

    @contextmanager
    def changed(self, key: str, old: object, new: object) -> Iterator[None]:
        """
        C{value} was changed from C{old} to C{new} for the given C{key}.
        """
        oldval = getattr(self.example, key, "not found before")
        self.changes.append(("will change", key, oldval, old, new))
        yield
        self.changes.append(
            (
                "did change",
                key,
                getattr(self.example, key, "not found after"),
                old,
                new,
            )
        )


@observable()
class Example:
    observer: Observer
    value1: str
    value2: int
    valueList: ObservableList[str]

    @classmethod
    def new(
        cls, observer: Changes[str, object], name: str, age: int
    ) -> Example:
        p: PathObserver[object, object] = PathObserver(observer, "")
        return cls(p, name, age, valueList=ObservableList(p.child("list"), []))
