#!/usr/bin/env python3
"""
Convenience script for users who don't now you can run a module with ``python
-m``. Users should use the installed jellyfin-migrator entrypoint or simply:


..code:: bash

    python -m jellyfin_migrator.id_scanner --help
"""


if __name__ == '__main__':
    from jellyfin_migrator import core
    core.main()
