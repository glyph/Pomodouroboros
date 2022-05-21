
# Static imports to convince py2app to work properly

import OpenSSL.SSL as _
import pkg_resources.extern.pyparsing as _
import pkg_resources._vendor.jaraco.text as _
import service_identity as _
import six.moves as _
import _cffi_backend as _

from pomodouroboros.mac_gui import main

main.runMain()
