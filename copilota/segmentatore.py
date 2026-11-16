"""Divide il flusso audio in frasi usando l'energia del segnale (VAD semplice e adattivo)."""
from __future__ import annotations

from collections import deque

import numpy as np


class Segmentatore:
    def __init__(
        self,
        sr: int,
        *,
        frame_ms: int = 30,
        silenzio_fine_ms: int = 700,
        margine_db: float = 12.0,
        soglia_min_db: float = -50.0,
        durata_max_s: float = 12.0,
        durata_min_ms: int = 300,
        preroll_ms: int = 300,
        frame_avvio: int = 3,
    ):
        self.sr = sr
        self.frame_ms = frame_ms
        self.fl = int(sr * frame_ms / 1000)
        self.silenzio_fine = max(1, silenzio_fine_ms // frame_ms)
        self.coda_silenzio = max(0, 200 // frame_ms)  # silenzio finale da tenere
        self.margine = margine_db
        self.soglia_min = soglia_min_db
        self.durata_max = durata_max_s
        self.voce_min = max(1, durata_min_ms // frame_ms)
        self.frame_avvio = frame_avvio

        self.residuo = np.zeros(0, dtype=np.float32)
        self.rumore: float | None = None
        self.calibrazione: list[float] = []
        self.preroll: deque = deque(maxlen=max(1, preroll_ms // frame_ms))
        self._azzera()

    def ricomincia(self):
        """Scarta la frase in corso e l'audio non ancora elaborato; tiene la stima del rumore."""
        self.residuo = np.zeros(0, dtype=np.float32)
        self.preroll.clear()
        self._azzera()

    def _azzera(self):
        self.in_voce = False
        self.frames: list[np.ndarray] = []
        self.silenzio = 0
        self.voce_consecutiva = 0
        self.frame_voce = 0

    @staticmethod
    def _db(frame: np.ndarray) -> float:
        rms = float(np.sqrt(np.mean(frame.astype(np.float64) ** 2)))
        return 20.0 * np.log10(max(rms, 1e-5))

    def aggiungi(self, blocco: np.ndarray) -> list[np.ndarray]:
        """Aggiunge audio; restituisce le frasi complete trovate."""
        self.residuo = np.concatenate([self.residuo, blocco.astype(np.float32)])
        n = len(self.residuo) // self.fl
        out = []
        for k in range(n):
            seg = self._frame(self.residuo[k * self.fl : (k + 1) * self.fl])
            if seg is not None:
                out.append(seg)
        self.residuo = self.residuo[n * self.fl :]
        return out

    def _aggiorna_rumore(self, db: float):
        if db < self.rumore:
            self.rumore = 0.7 * self.rumore + 0.3 * db  # scende in fretta
        else:
            self.rumore += 0.01  # sale piano (~0,3 dB/s)
        self.rumore = min(max(self.rumore, -70.0), -20.0)

    def _frame(self, f: np.ndarray):
        db = self._db(f)
        if self.rumore is None:  # primi 300 ms: stima il rumore di fondo
            self.calibrazione.append(db)
            self.preroll.append(f)
            if len(self.calibrazione) >= 10:
                self.rumore = min(max(float(np.median(self.calibrazione)), -70.0), -20.0)
            return None

        voce = db > max(self.rumore + self.margine, self.soglia_min)
        self._aggiorna_rumore(db)

        if not self.in_voce:
            self.preroll.append(f)
            self.voce_consecutiva = self.voce_consecutiva + 1 if voce else 0
            if self.voce_consecutiva >= self.frame_avvio:
                self.in_voce = True
                self.frames = list(self.preroll)
                self.preroll.clear()
                self.silenzio = 0
                self.frame_voce = self.voce_consecutiva
            return None

        self.frames.append(f)
        if voce:
            self.silenzio = 0
            self.frame_voce += 1
        else:
            self.silenzio += 1
        durata = len(self.frames) * self.frame_ms / 1000
        if self.silenzio >= self.silenzio_fine or durata >= self.durata_max:
            return self._chiudi()
        return None

    def _chiudi(self):
        da_togliere = max(0, self.silenzio - self.coda_silenzio)
        frames = self.frames[: len(self.frames) - da_togliere] if da_togliere else self.frames
        valido = self.frame_voce >= self.voce_min and frames
        seg = np.concatenate(frames) if valido else None
        self._azzera()
        return seg
