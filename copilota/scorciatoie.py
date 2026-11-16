"""Scorciatoie globali di macOS: funzionano anche quando la finestra del copilota non è in primo piano.

Usa RegisterEventHotKey (Carbon) tramite ctypes: nessuna dipendenza in più e nessun permesso di
Accessibilità, perché il programma non legge la tastiera, riceve solo le combinazioni registrate.
Il sistema chiama il gestore sul thread principale, dentro il ciclo di eventi di Qt.
"""
from __future__ import annotations

import ctypes
import sys
from collections.abc import Callable

# Codici dei tasti (kVK_*) della tastiera ANSI di macOS
TASTI = {
    "a": 0x00, "s": 0x01, "d": 0x02, "f": 0x03, "h": 0x04, "g": 0x05, "z": 0x06, "x": 0x07,
    "c": 0x08, "v": 0x09, "b": 0x0B, "q": 0x0C, "w": 0x0D, "e": 0x0E, "r": 0x0F, "y": 0x10,
    "t": 0x11, "1": 0x12, "2": 0x13, "3": 0x14, "4": 0x15, "6": 0x16, "5": 0x17, "9": 0x19,
    "7": 0x1A, "8": 0x1C, "0": 0x1D, "o": 0x1F, "u": 0x20, "i": 0x22, "p": 0x23, "l": 0x25,
    "j": 0x26, "k": 0x28, "n": 0x2D, "m": 0x2E,
    "return": 0x24, "invio": 0x24, "enter": 0x24, "tab": 0x30, "space": 0x31, "spazio": 0x31,
}
NOMI_TASTI = {"return": "↩", "invio": "↩", "enter": "↩", "tab": "⇥", "space": "Spazio", "spazio": "Spazio"}

# Modificatori di Carbon e simbolo da mostrare (ordine standard di macOS: ⌃⌥⇧⌘)
MODIFICATORI = {
    "ctrl": (0x1000, "⌃"), "control": (0x1000, "⌃"),
    "alt": (0x0800, "⌥"), "option": (0x0800, "⌥"), "opt": (0x0800, "⌥"),
    "shift": (0x0200, "⇧"),
    "cmd": (0x0100, "⌘"), "command": (0x0100, "⌘"),
}
_ORDINE = "⌃⌥⇧⌘"


def analizza(testo: str) -> tuple[int, int, str]:
    """'ctrl+cmd+return' → (codice tasto, modificatori Carbon, etichetta '⌃⌘↩')."""
    parti = [p.strip().lower() for p in testo.split("+") if p.strip()]
    if not parti:
        raise ValueError("scorciatoia vuota")
    *mods, tasto = parti
    if tasto not in TASTI:
        raise ValueError(f"tasto sconosciuto '{tasto}' in '{testo}'")
    maschera, simboli = 0, set()
    for m in mods:
        if m not in MODIFICATORI:
            raise ValueError(f"modificatore sconosciuto '{m}' in '{testo}' (usa ctrl, alt, shift, cmd)")
        maschera |= MODIFICATORI[m][0]
        simboli.add(MODIFICATORI[m][1])
    if not maschera & (0x1000 | 0x0100):
        # da macOS 15 le scorciatoie globali con solo ⌥ o ⇧ non sono più permesse
        raise ValueError(f"'{testo}' deve contenere ctrl o cmd")
    etichetta = "".join(s for s in _ORDINE if s in simboli) + NOMI_TASTI.get(tasto, tasto.upper())
    return TASTI[tasto], maschera, etichetta


def _fourcc(s: str) -> int:
    return int.from_bytes(s.encode("ascii"), "big")


class _TipoEvento(ctypes.Structure):
    _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]


class _IdScorciatoia(ctypes.Structure):
    _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]


_GESTORE = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
_FIRMA = _fourcc("CPLT")
_NON_GESTITO = -9874  # eventNotHandledErr


class ScorciatoieGlobali:
    def __init__(self):
        self._carbon = None
        self._gestore = None  # va tenuto in vita finché il gestore è installato
        self._azioni: dict[int, Callable[[], None]] = {}
        self._registrate: list[ctypes.c_void_p] = []

    def _carica(self):
        if sys.platform != "darwin":
            raise RuntimeError("le scorciatoie globali funzionano solo su macOS")
        c = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/Carbon.framework/Carbon")
        c.GetApplicationEventTarget.restype = ctypes.c_void_p
        c.GetApplicationEventTarget.argtypes = []
        c.InstallEventHandler.restype = ctypes.c_int32
        c.InstallEventHandler.argtypes = [ctypes.c_void_p, _GESTORE, ctypes.c_ulong,
                                          ctypes.POINTER(_TipoEvento), ctypes.c_void_p, ctypes.c_void_p]
        c.RegisterEventHotKey.restype = ctypes.c_int32
        c.RegisterEventHotKey.argtypes = [ctypes.c_uint32, ctypes.c_uint32, _IdScorciatoia, ctypes.c_void_p,
                                          ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
        c.UnregisterEventHotKey.restype = ctypes.c_int32
        c.UnregisterEventHotKey.argtypes = [ctypes.c_void_p]
        c.GetEventParameter.restype = ctypes.c_int32
        c.GetEventParameter.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
                                        ctypes.c_ulong, ctypes.c_void_p, ctypes.c_void_p]
        gestore = _GESTORE(self._evento)
        tipo = _TipoEvento(_fourcc("keyb"), 5)  # kEventClassKeyboard, kEventHotKeyPressed
        err = c.InstallEventHandler(c.GetApplicationEventTarget(), gestore, 1, ctypes.byref(tipo), None, None)
        if err:
            raise RuntimeError(f"impossibile installare il gestore delle scorciatoie (errore {err})")
        self._carbon, self._gestore = c, gestore

    def _evento(self, _chiamata, evento, _dati):
        try:
            hk = _IdScorciatoia()
            err = self._carbon.GetEventParameter(
                evento, _fourcc("----"), _fourcc("hkid"), None, ctypes.sizeof(hk), None, ctypes.byref(hk)
            )
            if err or hk.signature != _FIRMA or hk.id not in self._azioni:
                return _NON_GESTITO
            self._azioni[hk.id]()
        except Exception as e:  # noqa: BLE001 — un errore qui non deve far cadere il programma
            print(f"! scorciatoia globale: {e}", file=sys.stderr)
        return 0

    def registra(self, testo: str, azione: Callable[[], None]) -> str:
        """Registra la scorciatoia; restituisce l'etichetta (es. '⌃⌘↩'). Solleva un errore se non riesce."""
        codice, maschera, etichetta = analizza(testo)
        if self._carbon is None:
            self._carica()
        n = len(self._azioni) + 1
        rif = ctypes.c_void_p()
        err = self._carbon.RegisterEventHotKey(
            codice, maschera, _IdScorciatoia(_FIRMA, n), self._carbon.GetApplicationEventTarget(), 0,
            ctypes.byref(rif),
        )
        if err:
            raise RuntimeError(f"{etichetta} è già usata da un'altra app (errore {err})")
        self._azioni[n] = azione
        self._registrate.append(rif)
        return etichetta

    def chiudi(self):
        if self._carbon is not None:
            for rif in self._registrate:
                self._carbon.UnregisterEventHotKey(rif)
        self._registrate.clear()
        self._azioni.clear()
