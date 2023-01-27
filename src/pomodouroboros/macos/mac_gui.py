from twisted.internet.interfaces import IReactorTime

from ..storage import TEST_MODE
from .old_mac_gui import main as oldMain
from .quickapp import mainpoint


@mainpoint()
def main(reactor: IReactorTime):
    if not TEST_MODE:
        return oldMain(reactor)

