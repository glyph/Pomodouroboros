from __future__ import annotations
import sys

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

from twisted.trial.unittest import SynchronousTestCase as TC

from ..observables import (
    observable,
    AnyNotifier,
    ObservableList,
    ChangeNotifications,
    PathObserver,
    build,
    MustSpecifyNotifier,
)



class TestObservables(TC):
    """ """

    def test_notifierErrorMessage(self) -> None:
        """
        If we make an L{observable} class without providing a L{Notifier}
        annotation, we get a nice error message telling us that it's invalid.
        """
        with self.assertRaises(MustSpecifyNotifier) as msn:

            @observable()
            class Oops:
                name: str
                age: int

        self.assertIn("you must annotate one attribute with Notifier[T]", str(msn.exception))


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
