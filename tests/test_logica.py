"""Test di segmentazione, trigger, prompt e motore (senza audio vero né Claude vero)."""
import threading
import time
from pathlib import Path

import numpy as np

from copilota.assistente import Assistente
from copilota.config import carica
from copilota.motore import Eventi, Motore, modelli
from copilota.segmentatore import Segmentatore
from copilota.trascrittore import _segmento_valido, ricampiona
from copilota.trigger import sembra_richiesta

RADICE = Path(__file__).resolve().parent.parent
SR = 48000
_rng = np.random.default_rng(0)


def _rumore(s):
    return _rng.normal(0, 10 ** (-60 / 20), int(SR * s)).astype(np.float32)


def _voce(s):
    t = np.arange(int(SR * s)) / SR
    return (0.1 * np.sin(2 * np.pi * 220 * t) * (1 + 0.5 * np.sin(2 * np.pi * 3 * t))).astype(np.float32)


def test_segmentatore():
    # 2 s di voce, un colpo da 0,1 s (da scartare), 15 s di voce (spezzata a 12 s)
    segnale = np.concatenate([_rumore(1), _voce(2), _rumore(1.2), _voce(0.1), _rumore(1.2),
                              _voce(15), _rumore(1.5), np.zeros(SR, np.float32)])
    seg = Segmentatore(SR)
    frasi = []
    for i in range(0, len(segnale), 1440):
        frasi += seg.aggiungi(segnale[i:i + 1440])
    durate = [round(len(f) / SR, 2) for f in frasi]
    assert len(frasi) == 3, durate
    assert 2.0 <= durate[0] <= 2.6 and 11.9 <= durate[1] <= 12.1 and 2.5 <= durate[2] <= 3.6, durate


def test_silenzio_digitale():
    assert not Segmentatore(SR).aggiungi(np.zeros(SR * 3, np.float32))


def test_ricampionamento_e_filtri():
    assert len(ricampiona(_voce(1), 48000)) == 16000
    assert len(ricampiona(_voce(1)[:44100], 44100)) == 16000
    assert not _segmento_valido("Sottotitoli creati dalla comunità Amara.org", 0.1, -0.2, 1.2)
    assert _segmento_valido("Usiamo un outbox pattern", 0.1, -0.3, 1.2)


def test_trigger():
    si = [
        "Come possiamo fare a fare in modo che la cache si invalidi quando cambia l'ordine",
        "Che pattern ci conviene usare per implementare questa cosa",
        "secondo te ha senso spezzare il servizio in due",
        "Quindi facciamo con una coda o con un cron?",
        "how should we handle the retries here",
        "non so se sia meglio usare Redis o Postgres",
        "qual è il modo migliore per gestire le migrazioni",
    ]
    no = ["ok perfetto", "sì sì, l'ho visto ieri", "Ho fatto il deploy stamattina e funziona tutto.", "Va bene?"]
    for s in si:
        assert sembra_richiesta(s), s
    for s in no:
        assert not sembra_richiesta(s), s


def test_modelli():
    cfg = carica(RADICE / "config.toml")
    assert modelli(cfg["claude"]) == {"auto": "claude-haiku-5-5", "manuale": "claude-sonnet-5-5"}
    assert modelli({"modello": "x"}) == {"auto": "x", "manuale": "x"}  # vecchia chiave unica


class _StreamFinto:
    def __init__(self, testo):
        self.testo = testo

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    @property
    def text_stream(self):
        for w in self.testo.split(" "):
            time.sleep(0.01)
            yield w + " "


class _ClientFinto:
    def __init__(self):
        self.chiamate = []
        self.messages = self

    def stream(self, **kw):
        self.chiamate.append(kw)
        return _StreamFinto("**Usa l'outbox pattern.** - scrivi l'evento nella stessa transazione")


class _Registro(Eventi):
    def __init__(self):
        self.log = []

    def intervento(self, c, t):
        self.log.append(("int", c, t))

    def sugg_inizio(self, t):
        self.log.append(("inizio", t))

    def sugg_testo(self, p):
        self.log.append(("testo", p))

    def sugg_fine(self, v):
        self.log.append(("fine", v))

    def errore(self, t):
        self.log.append(("err", t))


def test_motore_con_api_finta():
    cfg = carica(RADICE / "config.toml")
    cfg["suggerimenti"]["attesa_s"] = 0.3
    client = _ClientFinto()
    ev = _Registro()
    m = Motore(cfg, ev, assistente=Assistente("claude-sonnet-5-5", 700, "Stack: NestJS", client=client),
               trascrittore=object())
    threading.Thread(target=m._ciclo_programmazione, daemon=True).start()
    m.nuova_frase("Interlocutore", "Abbiamo un servizio ordini che pubblica eventi su Kafka.")
    m.nuova_frase("Interlocutore", "Come possiamo fare a fare in modo che non perdiamo eventi")
    time.sleep(0.1)
    m.nuova_frase("Interlocutore", "se il database fa commit ma Kafka è giù?")  # la frase continua
    time.sleep(1.2)
    assert [e[0] for e in ev.log].count("inizio") == 1 and ("fine", False) in ev.log
    kw = client.chiamate[0]
    msg = kw["messages"][0]["content"]
    assert "Kafka è giù?" in msg and "Concentrati" in msg
    assert kw["system"][-1]["cache_control"] == {"type": "ephemeral"} and "NestJS" in kw["system"][-1]["text"]
    # pausa minima: una nuova domanda subito dopo non lancia un altro suggerimento automatico
    m.nuova_frase("Interlocutore", "E che pattern conviene per i retry?")
    time.sleep(0.6)
    assert [e[0] for e in ev.log].count("inizio") == 1
    # domanda scritta: il messaggio include i suggerimenti precedenti
    m.chiedi("come si chiama la libreria per l'outbox in NestJS?")
    time.sleep(0.8)
    msg2 = client.chiamate[1]["messages"][0]["content"]
    assert "Suggerimenti già mostrati" in msg2 and "L'utente ti chiede" in msg2
