
# installation instructions:
# sudo apt install libgirepository1.0-dev gcc libcairo2-dev pkg-config python3-dev gir1.2-gtk-4.0

# deps:
# ewmh==0.1.6
# pycairo==1.26.0
# PyGObject==3.48.2
# python-xlib==0.33
# six==1.16.0

# Load Gtk
import gi                       # type:ignore

gi.require_version("GLib", "2.0")
from gi.repository import GLib  # type:ignore

gi.require_version("Gdk", "4.0")
from gi.repository import Gdk

Gdk.set_allowed_backends("x11")
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

css = Gtk.CssProvider()

# css.load_from_data("""
# button {background-image: image(cyan);}
# button:hover {background-image: image(green);}
# button:active {background-image: image(brown);}
# """)

css.load_from_data("""
progressbar text {
  color: yellow;
  font-weight: bold;
}
progressbar trough, progress {
  min-height: 100px;
}
progressbar progress {
  background-image: none;
  background-color: #f00;
}
progressbar trough {
 background-image: none;
 background-color: #0f0;
}
""")

from Xlib.display import Display as XOpenDisplay  # type:ignore
from ewmh import EWMH                             # type:ignore

from cairo import Region        # type:ignore


# When the application is launched…
def on_activate(app):
    # … create a new window…
    win = Gtk.ApplicationWindow(application=app, title="Should Never Focus")
    win.set_opacity(0.25)
    win.set_decorated(False)
    win.set_default_size(2000, 100)
    # … with a button in it…
    # btn = Gtk.Button(label="Hello, World!")
    prog = Gtk.ProgressBar()
    frac = 0.7

    def refraction() -> bool:
        nonlocal frac
        frac += 0.01
        frac %= 1.0
        prog.set_fraction(frac)
        return True

    to = GLib.timeout_add((1000//10), refraction)

    prog.set_fraction(0.7)

    win.set_child(prog)
    gdisplay = prog.get_display()

    Gtk.StyleContext.add_provider_for_display(gdisplay, css, Gtk.STYLE_PROVIDER_PRIORITY_USER)

    # we can't actually avoid getting focus, but in case the compositors ever
    # fix themselves, let's give it our best try
    win.set_can_focus(False)
    win.set_focusable(False)
    win.set_focus_on_click(False)
    win.set_can_target(False)
    win.set_auto_startup_notification(False)
    win.set_receives_default(False)

    win.present()

    win.get_surface().set_input_region(Region())
    gdk_x11_win = win.get_native().get_surface()
    xid = gdk_x11_win.get_xid()
    display = XOpenDisplay()
    xlibwin = display.create_resource_object("window", xid)
    screen = display.screen()
    ewmh = EWMH(display, screen.root)
    # Always on top
    ewmh.setMoveResizeWindow(xlibwin, x=300, y=800, w=2000, h=150)
    ewmh.setWmState(xlibwin, 1, "_NET_WM_STATE_ABOVE")

    # Draw even over the task bar (this breaks stuff)
    # ewmh.setWmState(xlibwin, 1, '_NET_WM_STATE_FULLSCREEN')

    # Don't show the icon in the task bar
    ewmh.setWmState(xlibwin, 1, "_NET_WM_STATE_SKIP_TASKBAR")
    ewmh.setWmState(xlibwin, 1, "_NET_WM_STATE_SKIP_PAGER")
    display.flush()


if __name__ == "__main__":
    # Create a new application
    app = Gtk.Application(application_id="com.example.GtkApplication")
    app.connect("activate", on_activate)

    # Run the application
    app.run(None)
