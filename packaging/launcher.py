"""Entry point for the packaged app (PyInstaller starts this file).

PyInstaller needs a script to start from, and runs it as a plain file, not as
part of the package — so it imports the app by its full name instead of using
`python -m`.
"""

import sys

from remote_music_control.app.main import main

sys.exit(main())
