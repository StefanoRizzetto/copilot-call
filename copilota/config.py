"""Caricamento della configurazione (config.toml) con valori predefiniti."""
from __future__ import annotations

import copy
import tomllib
from pathlib import Path

PREDEFINITI: dict = {
    "audio": {
        # Parte del nome del microfono; vuoto = microfono predefinito di macOS.
        "microfono": "",
        # Dispositivo da cui arriva la voce degli altri (BlackHole). Vuoto = disattivato.
        "sistema": "BlackHole",
        "etichetta_microfono": "Io",
        "etichetta_sistema": "Interlocutore",
    },
    "vad": {
        "silenzio_fine_ms": 550,
        "margine_db": 12.0,
        "soglia_min_db": -50.0,
        "durata_max_s": 12.0,
        "durata_min_ms": 300,
    },
    "trascrizione": {
        "motore": "auto",  # auto | mlx | faster-whisper
        "modello_mlx": "mlx-community/whisper-large-v3-turbo",
        "modello_faster": "small",
        "lingua": "it",
        "vocabolario": (
            "Discussione tecnica tra programmatori: API, endpoint, backend, frontend, "
            "refactoring, design pattern, repository, pull request, deploy, database, "
            "cache, microservizi, Docker, Kubernetes, TypeScript, Python, React."
        ),
    },
    "claude": {
        # "claude-code" = usa il tuo abbonamento tramite 'claude -p'; "api" = chiave API.
        "motore": "claude-code",
        "percorso_claude": "",
        "sforzo": "low",
        # modello_automatici / modello_su_richiesta: vedi motore.modelli()
        "max_token": 700,
        "minuti_contesto": 8,
        "file_contesto": "contesto.md",
    },
    "suggerimenti": {
        "automatici": True,
        # Attende un attimo dopo la domanda, nel caso la frase continui.
        "attesa_s": 0.6,
        "attesa_max_s": 2.5,
        # Intervallo minimo tra due suggerimenti automatici.
        "pausa_minima_s": 10.0,
        # Se true, i suggerimenti automatici partono solo dalle domande degli altri.
        "solo_interlocutore": False,
    },
}


def _unisci(base: dict, sopra: dict) -> dict:
    for k, v in sopra.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _unisci(base[k], v)
        else:
            base[k] = v
    return base


def carica(percorso: Path) -> dict:
    cfg = copy.deepcopy(PREDEFINITI)
    if percorso.exists():
        with open(percorso, "rb") as f:
            _unisci(cfg, tomllib.load(f))
    cfg["_cartella"] = str(percorso.parent.resolve())
    return cfg
