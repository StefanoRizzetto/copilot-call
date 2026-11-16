"""Cattura dello schermo principale (macOS), da mandare a Claude insieme alla domanda.

Lo screenshot resta in memoria: il file temporaneo creato da 'screencapture' viene
cancellato subito dopo la lettura.
"""
from __future__ import annotations

import base64
import shutil
import struct
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

PERMESSO = (
    "Non riesco a catturare lo schermo. In Impostazioni di Sistema → Privacy e sicurezza → "
    "Registrazione schermo e audio di sistema, abilita il Terminale (o l'app da cui lanci il "
    "programma), poi chiudilo e riaprilo."
)


@dataclass
class Immagine:
    dati: bytes
    tipo: str  # media type, es. "image/jpeg"

    def base64(self) -> str:
        return base64.b64encode(self.dati).decode("ascii")

    def blocco(self) -> dict:
        """Blocco 'image' nel formato dei messaggi di Claude."""
        return {"type": "image", "source": {"type": "base64", "media_type": self.tipo, "data": self.base64()}}


def dimensioni_png(png: bytes) -> tuple[int, int] | None:
    if len(png) >= 24 and png[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", png[16:24])
    return None


def cattura(schermo: int = 1) -> bytes:
    """Screenshot PNG dello schermo indicato (1 = principale, quello con la barra dei menu)."""
    if sys.platform != "darwin":
        raise RuntimeError("La cattura dello schermo funziona solo su macOS.")
    with tempfile.TemporaryDirectory(prefix="copilota-schermo-") as cartella:
        file = Path(cartella) / "schermo.png"
        cmd = ["screencapture", "-x", "-t", "png"]  # -x: senza suono
        if schermo > 0:
            cmd += ["-D", str(schermo)]
        r = subprocess.run(cmd + [str(file)], capture_output=True, text=True, timeout=10)
        if r.returncode != 0 or not file.exists() or file.stat().st_size == 0:
            dettaglio = (r.stderr or "").strip()
            if schermo > 1 and "display" in dettaglio.lower():
                raise RuntimeError(
                    f"Lo schermo {schermo} non esiste: controlla 'numero' nella sezione [schermo] di config.toml."
                )
            raise RuntimeError(PERMESSO + (f" ({dettaglio})" if dettaglio else ""))
        return file.read_bytes()


def prepara(png: bytes, lato_max: int = 1568, qualita: int = 80) -> Immagine:
    """Riduce lo screenshot (lato lungo ≤ lato_max) e lo converte in JPEG con 'sips' di macOS.

    Uno screenshot Retina a piena risoluzione pesa diversi MB; Claude lo ridimensionerebbe
    comunque. Se 'sips' non c'è o fallisce, si manda il PNG originale.
    """
    sips = shutil.which("sips")
    if sips:
        with tempfile.TemporaryDirectory(prefix="copilota-schermo-") as cartella:
            ingresso, uscita = Path(cartella) / "in.png", Path(cartella) / "out.jpg"
            ingresso.write_bytes(png)
            cmd = [sips, "-s", "format", "jpeg", "-s", "formatOptions", str(qualita)]
            dim = dimensioni_png(png)
            if lato_max > 0 and (dim is None or max(dim) > lato_max):  # mai ingrandire
                cmd += ["-Z", str(lato_max)]
            try:
                r = subprocess.run(cmd + [str(ingresso), "--out", str(uscita)], capture_output=True, timeout=15)
                if r.returncode == 0 and uscita.exists() and uscita.stat().st_size > 0:
                    return Immagine(uscita.read_bytes(), "image/jpeg")
            except (OSError, subprocess.SubprocessError):
                pass
    return Immagine(png, "image/png")
