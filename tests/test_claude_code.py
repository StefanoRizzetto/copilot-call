"""Test del motore 'claude-code' con un finto eseguibile claude (tests/claude_finto.py)."""
import os
import sys
import threading
import time
from pathlib import Path

from copilota.assistente import AssistenteClaudeCode
from copilota.config import carica
from copilota.motore import Eventi, Motore
from copilota.schermo import Immagine
from tests.test_logica import PNG_1X1

RADICE = Path(__file__).resolve().parent.parent
FINTO = str(Path(__file__).resolve().parent / "claude_finto.py")


def _prepara_finto():
    os.chmod(FINTO, 0o755)
    os.environ["ANTHROPIC_API_KEY"] = "sk-da-togliere"  # deve essere rimossa prima di lanciare claude
    # il finto usa '#!/usr/bin/env python3': mettiamo in testa al PATH l'interprete corrente
    os.environ["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", "")


def _nuovo(modo, **kw):
    _prepara_finto()
    os.environ["FAKE_MODO"] = modo
    return AssistenteClaudeCode("sonnet", "contesto", eseguibile=FINTO, **kw)


def test_streaming():
    a = _nuovo("ok")
    pezzi = []
    out = a.suggerisci("domanda", pezzi.append, threading.Event())
    a.chiudi()
    assert out.startswith("**Usa il transactional") and "".join(pezzi) == out and len(pezzi) == 3


def test_screenshot_nel_messaggio():
    a = _nuovo("ok")
    out = a.suggerisci("domanda", lambda p: None, threading.Event(), immagine=Immagine(PNG_1X1, "image/png"))
    a.chiudi()
    assert out.startswith("Vedo lo schermo.") and "outbox" in out


def test_opzione_sconosciuta_viene_tolta():
    a = _nuovo("opzione")
    out = a.suggerisci("d", lambda p: None, threading.Event())
    a.chiudi()
    assert out and ["--safe-mode"] not in a.opzionali


def test_errore_di_accesso():
    a = _nuovo("login")
    try:
        a.suggerisci("d", lambda p: None, threading.Event())
    except RuntimeError as e:
        assert "Not logged in" in str(e) and "accesso" in str(e)
    else:
        raise AssertionError("doveva fallire")
    finally:
        a.chiudi()


def test_annullamento():
    a = _nuovo("lento")
    annulla = threading.Event()
    pezzi = []
    threading.Timer(0.8, annulla.set).start()
    t0 = time.time()
    a.suggerisci("d", pezzi.append, annulla)
    a.chiudi()
    assert time.time() - t0 < 2.5 and len(pezzi) < 20


def test_processo_pronto_riusato():
    a = _nuovo("ok")
    time.sleep(0.5)
    riserva = a._riserva
    assert riserva is not None and riserva.poll() is None
    a.suggerisci("x", lambda p: None, threading.Event())
    time.sleep(0.5)
    assert a._riserva is not None and a._riserva is not riserva  # ne è già pronto un altro
    a.chiudi()
    time.sleep(0.3)
    assert a._riserva is None


def test_due_modelli():
    _prepara_finto()
    os.environ["FAKE_MODO"] = "ok"
    cfg = carica(RADICE / "config.toml")
    cfg["claude"]["percorso_claude"] = FINTO
    cfg["suggerimenti"]["attesa_s"] = 0.2
    titoli = []

    class E(Eventi):
        def sugg_inizio(self, t):
            titoli.append(t)

    m = Motore(cfg, E(), trascrittore=object())
    m._apri_audio = lambda: None  # niente microfono nei test
    m._avvio()
    time.sleep(0.5)
    auto, manuale = m.assistenti["auto"], m.assistenti["manuale"]
    assert auto.modello == "claude-haiku-5-5" and manuale.modello == "claude-sonnet-5-5"
    m.nuova_frase("Interlocutore", "Che pattern ci conviene usare per la cache?")
    time.sleep(1)
    m.suggerisci_ora()
    time.sleep(0.6)
    m.ferma()
    assert titoli[0].endswith("· Haiku") and titoli[1].endswith("· Sonnet"), titoli
