import os
import sys
import pipes
import site
from Foundation import NSBundle, NSObject
from AppKit import NSApp, NSMenu, NSMenuItem, NSStatusBar, NSVariableStatusItemLength


class Actionable(NSObject):
    def initWithFunction_(self, thunk):
        self.thunk = thunk
        return self

    def doIt_(self, sender):
        self.thunk()


def menu(title, items):
    result = NSMenu.alloc().initWithTitle_(title)
    for (subtitle, thunk) in items:
        # print("Adding item: {} {}".format(subtitle, thunk))
        item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            subtitle, "doIt:", subtitle[0].lower()
        )
        item.setTarget_(Actionable.alloc().initWithFunction_(thunk).retain())
        result.addItem_(item)
    result.update()
    return result


class Status(object):
    def __init__(self, text):
        self.item = NSStatusBar.systemStatusBar().statusItemWithLength_(
            NSVariableStatusItemLength
        )
        self.item.setTitle_(text)
        self.item.setEnabled_(True)
        self.item.setHighlightMode_(True)

    def menu(self, items):
        m = menu(self.item.title(), items)
        self.item.setMenu_(m)


def mainpoint():
    def wrapup(appmain):
        def doIt():
            from twisted.internet import cfreactor
            import PyObjCTools.AppHelper
            from AppKit import NSApplication

            app = NSApplication.sharedApplication()
            reactor = cfreactor.install(runner=PyObjCTools.AppHelper.runEventLoop)
            reactor.callWhenRunning(appmain, reactor)
            reactor.run()
            os._exit(0)

        appmain.runMain = doIt
        return appmain
    return wrapup


def quit():
    """
    Quit.
    """
    NSApp().terminate_(NSApp())
