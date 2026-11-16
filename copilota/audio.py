"""Cattura audio da microfono e da BlackHole (voce degli altri partecipanti)."""
from __future__ import annotations

import queue

import numpy as np


def _sd():
    import sounddevice as sd  # import ritardato: richiede PortAudio

    return sd


def elenca_ingressi() -> list[tuple[int, str, int, int]]:
    sd = _sd()
    out = []
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            out.append((i, d["name"], int(d["max_input_channels"]), int(d["default_samplerate"])))
    return out


def trova_ingresso(nome: str | None) -> int:
    sd = _sd()
    if not nome:
        idx = sd.default.device[0]
        if idx is None or idx < 0:
            raise RuntimeError("Nessun microfono predefinito trovato.")
        return int(idx)
    for i, n, _ch, _sr in elenca_ingressi():
        if nome.lower() in n.lower():
            return i
    raise RuntimeError(
        f"Nessun dispositivo di ingresso contiene '{nome}'. "
        "Lancia ./avvia.sh --dispositivi per vedere l'elenco."
    )


class Cattura:
    """Legge un dispositivo di ingresso e mette blocchi mono float32 in una coda."""

    def __init__(self, nome_dispositivo: str | None, etichetta: str, coda: queue.Queue, blocco_ms: int = 30):
        sd = _sd()
        self.indice = trova_ingresso(nome_dispositivo)
        info = sd.query_devices(self.indice, "input")
        self.nome = info["name"]
        self.sr = int(info["default_samplerate"])
        self.canali = max(1, min(2, int(info["max_input_channels"])))
        self.etichetta = etichetta
        self.coda = coda
        self.stream = sd.InputStream(
            device=self.indice,
            channels=self.canali,
            samplerate=self.sr,
            blocksize=int(self.sr * blocco_ms / 1000),
            dtype="float32",
            callback=self._callback,
        )

    def _callback(self, indata, frames, tempo, status):  # thread audio: deve essere veloce
        mono = indata.mean(axis=1) if indata.shape[1] > 1 else indata[:, 0]
        try:
            self.coda.put_nowait((self.etichetta, np.array(mono, dtype=np.float32)))
        except queue.Full:
            pass

    def avvia(self):
        self.stream.start()

    def ferma(self):
        try:
            self.stream.stop()
            self.stream.close()
        except Exception:
            pass
