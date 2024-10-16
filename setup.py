"""
This is a setup.py script generated by py2applet

Usage:
    python setup.py py2app
"""
import os

from setuptools import setup

def check_mode() -> str:
    match os.environ:
        case {"CI_MODE": b}:
            if b:
                return "Ci"
        case {"TEST_MODE": b}:
            if b:
                return "Test"
        case _:
            return ""

MODE = check_mode()

APP = [f"mac/{MODE}Pomodouroboros.py"]
DATA_FILES = [
    "IBFiles/GoalListWindow.xib",
    "IBFiles/IntentionEditor.xib",
    "IBFiles/MainMenu.xib",
    "IBFiles/ProgressHUD.xib",
]
OPTIONS = {
    "plist": {
        "LSUIElement": True,
        "NSRequiresAquaSystemAppearance": False,
        "CFBundleIdentifier": f"im.glyph.and.this.is.{MODE}pomodouroboros",
    },
    "iconfile": f"{MODE}icon.icns",
}

setup(
    name=f"{MODE}Pomodouroboros",
    app=APP,
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
)
