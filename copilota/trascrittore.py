"""Trascrizione locale con Whisper: mlx-whisper su Apple Silicon, faster-whisper altrove."""
from __future__ import annotations

import platform
from math import gcd

import numpy as np

SR_WHISPER = 16000

# Frasi che Whisper "inventa" sul silenzio o sul rumore.
ALLUCINAZIONI = (
    "amara.org",
    "sottotitoli creati",
    "sottotitoli a cura",
    "sottotitoli e revisione",
    "grazie per la visione",
    "grazie a tutti per la visione",
    "iscriviti al canale",
    "thank you for watching",
    "thanks for watching",
    "sous-titrage",
)


def ricampiona(audio: np.ndarray, sr: int) -> np.ndarray:
    if sr == SR_WHISPER:
        return audio.astype(np.float32)
    from scipy.signal import resample_poly

    g = gcd(sr, SR_WHISPER)
    return resample_poly(audio, SR_WHISPER // g, sr // g).astype(np.float32)


def _mlx_disponibile() -> bool:
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        return False
    try:
        import mlx_whisper  # noqa: F401

        return True
    except Exception:
        return False


def _segmento_valido(testo: str, no_speech: float, logprob: float, compressione: float) -> bool:
    if not testo.strip():
        return False
    if no_speech > 0.6 and logprob < -0.8:
        return False
    if logprob < -1.5 or compressione > 2.4:
        return False
    t = testo.lower()
    return not any(a in t for a in ALLUCINAZIONI)


class Trascrittore:
    def __init__(self, cfg: dict):
        self.lingua = cfg.get("lingua") or None
        self.prompt = cfg.get("vocabolario") or None
        motore = cfg.get("motore", "auto")
        if motore == "auto":
            motore = "mlx" if _mlx_disponibile() else "faster-whisper"
        self.motore = motore
        if motore == "mlx":
            import mlx_whisper

            self._mlx = mlx_whisper
            self.modello = cfg["modello_mlx"]
        elif motore == "faster-whisper":
            from faster_whisper import WhisperModel

            self.modello = cfg["modello_faster"]
            self._fw = WhisperModel(self.modello, device="cpu", compute_type="int8")
        else:
            raise ValueError(f"Motore di trascrizione sconosciuto: {motore}")

    def riscalda(self):
        """Carica il modello in memoria (al primo avvio lo scarica)."""
        self.trascrivi(np.zeros(SR_WHISPER, dtype=np.float32))

    def trascrivi(self, audio16k: np.ndarray) -> str:
        if self.motore == "mlx":
            r = self._mlx.transcribe(
                audio16k,
                path_or_hf_repo=self.modello,
                language=self.lingua,
                initial_prompt=self.prompt,
                condition_on_previous_text=False,
                temperature=0.0,
                verbose=None,
            )
            parti = [
                s["text"]
                for s in r.get("segments", [])
                if _segmento_valido(
                    s.get("text", ""),
                    s.get("no_speech_prob", 0.0),
                    s.get("avg_logprob", 0.0),
                    s.get("compression_ratio", 1.0),
                )
            ]
        else:
            segmenti, _info = self._fw.transcribe(
                audio16k,
                language=self.lingua,
                initial_prompt=self.prompt,
                beam_size=1,
                temperature=0.0,
                condition_on_previous_text=False,
                vad_filter=False,
            )
            parti = [
                s.text
                for s in segmenti
                if _segmento_valido(s.text, s.no_speech_prob, s.avg_logprob, s.compression_ratio)
            ]
        return " ".join(p.strip() for p in parti).strip()
