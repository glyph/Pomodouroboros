from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar
from weakref import ref

T = TypeVar("T")
U = TypeVar("U")


@dataclass
class IDHasher(Generic[T]):
    """
    Hash and compare by the identity of another object.
    """

    value: ref[T]
    id: int

    def __hash__(self) -> int:
        """
        Return the C{id()} of the object when it was live at the creation of
        this hasher.
        """
        return self.id

    def __eq__(self, other: object) -> bool:
        """
        Is this equal to another object?  Note that this compares equal only to
        another L{IDHasher}, not the underlying value object.
        """
        if not isinstance(other, IDHasher):
            return NotImplemented
        imLive = self.value.__callback__ is not None
        theyreLive = other.value.__callback__ is not None
        return (self.id == other.id) and (imLive == theyreLive)

    @classmethod
    def forDict(cls, aDict: dict[IDHasher[T], U], value: T) -> IDHasher[T]:
        """
        Create an IDHasher
        """

        def finalize(r: ref[T]) -> None:
            del aDict[self]

        self = IDHasher(ref(value, finalize), id(value))
        return self
