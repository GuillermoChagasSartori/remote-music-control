# PyInstaller build recipe for the Windows app. Run through packaging\build.ps1.
#
# A .spec file is Python that PyInstaller executes. It describes what goes into
# the bundle: the start script, data files the code reads at run time, and how
# the executable is built. The result is a folder (dist\RemoteMusicControl)
# holding RemoteMusicControl.exe, a private copy of Python and every package —
# the customer's PC needs no Python.
#
# "onedir" (a folder) rather than "onefile" (one big .exe): a onefile app
# unpacks itself to a temporary folder on every start, which is slower and is
# exactly what antivirus heuristics find suspicious in unsigned programs.

from importlib.metadata import version

from PyInstaller.utils.hooks import collect_data_files, copy_metadata
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

APP_VERSION = version("remote-music-control")
numbers = tuple(int(part) for part in APP_VERSION.split(".")[:3]) + (0,)

# Details shown in the .exe's Properties > Details tab in Windows. A program
# that says who made it looks less suspicious to users and antivirus alike.
version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=numbers, prodvers=numbers),
    kids=[
        StringFileInfo([
            StringTable("040904B0", [  # US English, Unicode
                StringStruct("CompanyName", "Guillermo Chagas Sartori"),
                StringStruct("FileDescription", "Remote Music Control"),
                StringStruct("FileVersion", APP_VERSION),
                StringStruct("InternalName", "RemoteMusicControl"),
                StringStruct("LegalCopyright", "MIT License"),
                StringStruct("OriginalFilename", "RemoteMusicControl.exe"),
                StringStruct("ProductName", "Remote Music Control"),
                StringStruct("ProductVersion", APP_VERSION),
            ])
        ]),
        VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
    ],
)

analysis = Analysis(
    ["launcher.py"],
    pathex=[],
    # Files the code opens by path: the web page, the page functions and the
    # tray icon (collected from inside the package), and the installed
    # package's metadata, which importlib.metadata reads for the version.
    datas=collect_data_files("remote_music_control") + copy_metadata("remote-music-control"),
    # PyInstaller finds imports by reading the code, including imports inside
    # functions. These are listed anyway because the app can't work without
    # them and a missing one would only show up on the customer's PC.
    hiddenimports=[
        "winrt.windows.media.control",
        "winrt.windows.foundation",
        "winrt.windows.foundation.collections",
        "remote_music_control.adapters.windows",
        "remote_music_control.adapters.page_library",
    ],
    excludes=["tkinter"],  # the standard GUI toolkit: unused, and a few MB
)

pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,  # onedir: libraries stay next to the .exe
    name="RemoteMusicControl",
    icon="../src/remote_music_control/app/icon.ico",
    version=version_info,
    console=False,  # a windowed app: no console window
    # UPX compression makes the files smaller but is another antivirus red flag.
    upx=False,
)

COLLECT(exe, analysis.binaries, analysis.datas, name="RemoteMusicControl", upx=False)
