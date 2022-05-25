from Foundation import NSObject
from typing import Type, Iterable, TypeVar

from textwrap import dedent

ACTION_SIGNATURE = b"v@:@"

def getOutlets(cls):
    for k, v in cls.__dict__.items():
        if getattr(v, "__isOutlet__", False):
            yield k


def getActions(cls):
    for k, v in cls.__dict__.items():
        if k.endswith("_") and k.count("_") == 1 and k != 'forwardInvocation_':
            signature = getattr(v, "signature", None)
            if signature is None:
                continue
            if signature == ACTION_SIGNATURE:
                yield k[:-1]


def fakeSwiftClass(cls: Type[NSObject]) -> str:
    someOutlets = list(getOutlets(cls))
    someActions = list(getActions(cls))
    if not (someOutlets or someActions):
        return ""
    indentation = "\n            "
    outlets = indentation.join(f"@IBOutlet var {each}: id;" for each in someOutlets)
    actions = indentation.join(
        [f"@IBAction func {each}(_ sender: NSObject) {{ }}" for each in someActions]
    )
    return dedent(
        f"""
        class {cls.__name__}: NSObject {{
            # Outlets
            {outlets}
            # Actions
            {actions}
        }}
        """
    )

T = TypeVar("T")

def uniq(stuff: Iterable[T]) -> Iterable[T]:
    seen = set()
    for each in stuff:
        if each in seen:
            continue
        seen.add(each)
        yield each

def swiftFileForInterfaceBuilder(everything: Iterable[object]) -> str:
    return "".join(
        [
            "import Foundation\n",
            *uniq(
                fakeSwiftClass(cls)
                for cls in everything
                if isinstance(cls, type)
                and issubclass(cls, NSObject)
                and cls is not NSObject
            ),
        ]
    )


if __name__ == '__main__':
    import sys
    from importlib import import_module
    everything: list[object] = []
    for module_name in sys.argv[1:]:
        everything.extend(import_module(module_name).__dict__.values())
    print(swiftFileForInterfaceBuilder(everything))
