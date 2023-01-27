from os import popen, system
from os.path import join
from tempfile import TemporaryDirectory
from sys import stdout
from twisted.internet.fdesc import setBlocking

from objc import IBAction, IBOutlet
from Foundation import NSData, NSURL, NSObject
from AppKit import NSNib, NSArrayController
from pomodouroboros.macos.quickapp import mainpoint

from shlex import quote
nibs = []

def livenib(owner: NSObject, path: str) -> tuple[NSNib, list[object]]:
    with TemporaryDirectory() as d:
        p = join(d, "out.nib")
        try:
            system(f"ibtool --compile '{quote(p)}' '{quote(path)}'")
        finally:
            setBlocking(1)
        with open(p, 'rb') as f:
            data = f.read()
    nsdata = NSData.dataWithBytes_length_(data, len(data))
    print("data:", repr(nsdata))
    nib = NSNib.alloc().initWithNibData_bundle_(nsdata, None)
    print("nib?", nib)
    worked, tlo = nib.instantiateWithOwner_topLevelObjects_(owner, None)
    if not worked:
        raise RuntimeError("didnt work")
    return tlo, nib

class ItsAnObject(NSObject):
    def initWithValue1_andValue2_(self, value1, value2):
        super().init()
        self.field1 = value1
        self.field2 = value2
        return self

    def setValue_forKey_(self, value, key: str) -> None:
        print("set value", value, key)
        super().setValue_forKey_(value, key)

    def clickedRowButton_(self, aButton) -> None:
        """
        This is hooked up via a target I{binding} (chain link icon) not a
        sent-action I{connection}.  By binding it to the clickedRowButton:
        selector on table cell view's objectValue, we get the click directly
        here, and don't need to go through NSTableView.rowForView_ to figure
        out what to click on; we just need to maintain whatever state we need
        locally in this view.
        """
        print("row clicked", self.field1)


class CustomDataSource(NSObject):

    table = IBOutlet()

    @IBAction
    def rowButtonTest_(self, target) -> None:
        # print("click", target, self.table)
        print("custom button click")

    def numberOfRowsInTableView_(self, view) -> int:
        print("NORITV", view)
        return 3

    def tableView_objectValueForTableColumn_row_(self, view, column, row: int) -> NSObject:
        print("TVOVFTCR", view, "---", column, "---", row)
        return ItsAnObject.alloc().initWithValue1_andValue2_(row * 2, (row * 2) + 1)

    def tableView_isGroupRow_(self, view, row) -> bool:
        print("group row check", view, row)
        return False

src = []
@mainpoint()
def go(argv: list[str]) -> None:
    dataSource = CustomDataSource.alloc().init()
    src.append(dataSource)
    tlo, nib = livenib(dataSource, "./IBFiles/IntentionListWindow.xib")
    # [arc] = [each for each in tlo if isinstance(each, NSArrayController)]
    nibs.append(nib)

if __name__ == '__main__':
    go.runMain()
