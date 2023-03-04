
# Static imports to convince py2app to work properly

import OpenSSL.SSL as _
import service_identity as _
import six.moves as _
import _cffi_backend as _

from pomodouroboros.macos.mac_gui import main

main.runMain()
