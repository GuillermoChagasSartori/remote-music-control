"""The app's own words (tray menu, notices, errors), in English and Portuguese.

A plain dictionary per language rather than a translation framework such as
gettext: there are a handful of strings, and a Python file that anyone can read
and edit beats a toolchain for compiling translation files. This is the
simplest form of *internationalization* (i18n): code refers to text by a key,
and the key is looked up in the user's language.
"""

import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class Texts:
    window_title: str
    tray_show: str
    tray_pair: str
    tray_quit: str
    still_running_title: str
    still_running: str
    start_failed_title: str
    start_failed: str  # {error} and {log} are filled in


ENGLISH = Texts(
    window_title="Remote Music Control",
    tray_show="Show YouTube Music",
    tray_pair="Connect a phone or computer",
    tray_quit="Quit",
    still_running_title="Still playing",
    still_running="Remote Music Control keeps running here. Use this icon to open it again or to quit.",
    start_failed_title="Remote Music Control couldn't start",
    start_failed="Remote Music Control couldn't start:\n\n{error}\n\nDetails are in the log file:\n{log}",
)

PORTUGUESE = Texts(
    window_title="Remote Music Control",
    tray_show="Mostrar o YouTube Music",
    tray_pair="Conectar um celular ou computador",
    tray_quit="Sair",
    still_running_title="A música continua",
    still_running="O Remote Music Control continua aberto aqui. Use este ícone para abri-lo de novo ou para sair.",
    start_failed_title="O Remote Music Control não pôde iniciar",
    start_failed="O Remote Music Control não pôde iniciar:\n\n{error}\n\nOs detalhes estão no arquivo de log:\n{log}",
)

# Windows identifies languages by number (a LANGID). The low 10 bits are the
# "primary language", shared by every regional variant (pt-BR, pt-PT...).
PRIMARY_LANGUAGE_MASK = 0x3FF
LANG_PORTUGUESE = 0x16


def texts_for_language_id(language_id: int) -> Texts:
    """Portuguese for any Portuguese variant; English for everything else."""
    if language_id & PRIMARY_LANGUAGE_MASK == LANG_PORTUGUESE:
        return PORTUGUESE
    return ENGLISH


def system_texts() -> Texts:
    """The texts in the language of Windows' user interface (English elsewhere).

    The *display* language, not the regional format: someone in Brazil with an
    English Windows sees English, as in every other program they use.
    """
    if sys.platform != "win32":
        return ENGLISH
    import ctypes  # windll exists only on Windows

    return texts_for_language_id(ctypes.windll.kernel32.GetUserDefaultUILanguage())
