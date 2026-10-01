"""MaAS reproduction package.

The application is commonly run with ``applications/maas_reproduction`` on
``PYTHONPATH`` while tests may import the fully-qualified applications path.
Registering both names here keeps schema class identity stable during that
transition; source files should still use one canonical import style.
"""

import sys as _sys

_module = _sys.modules[__name__]
_sys.modules.setdefault("maas_reproduction", _module)
_sys.modules.setdefault("applications.maas_reproduction.maas_reproduction", _module)

del _module, _sys
