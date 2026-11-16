"""Test di segmentazione, trigger, prompt e motore (senza audio vero né Claude vero)."""
import base64
import threading
import time
from pathlib import Path

import numpy as np

from copilota.assistente import Assistente, contenuto, costruisci_messaggio
from copilota.config import carica
from copilota.motore import Eventi, Motore, modelli
from copilota.schermo import Immagine, dimensioni_png, prepara
from copilota.segmentatore import Segmentatore
from copilota.trascrittore import _segmento_valido, ricampiona
from copilota.trigger import sembra_richiesta

RADICE = Path(__file__).resolve().parent.parent
SR = 48000
_rng = np.random.default_rng(0)
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


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

    def schermo(self, d):
        self.log.append(("schermo", len(d)))


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


def test_messaggio_con_screenshot():
    msg = costruisci_messaggio("[00:01] Interlocutore: guarda qui", schermo=True)
    assert "screenshot" in msg and "ti mostra il suo schermo" in msg
    msg2 = costruisci_messaggio("", domanda_utente="perché fallisce?", schermo=True)
    assert "screenshot" in msg2 and "perché fallisce?" in msg2 and "ti mostra" not in msg2
    assert "screenshot" not in costruisci_messaggio("x")
    c = contenuto("ciao", Immagine(b"abc", "image/jpeg"))
    assert c[0] == {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "YWJj"}}
    assert c[1] == {"type": "text", "text": "ciao"} and contenuto("ciao") == "ciao"


def test_prepara_screenshot():
    assert dimensioni_png(PNG_1X1) == (1, 1) and dimensioni_png(b"non un png") is None
    img = prepara(PNG_1X1)  # su macOS diventa JPEG con sips, altrove resta PNG
    assert img.dati and img.tipo in ("image/jpeg", "image/png")


def test_motore_con_screenshot():
    cfg = carica(RADICE / "config.toml")
    client = _ClientFinto()
    ev = _Registro()
    m = Motore(cfg, ev, assistente=Assistente("claude-sonnet-5-5", 700, client=client), trascrittore=object())
    m.nuova_frase("Interlocutore", "Vedi questo errore nella console?")
    m.chiedi_su_schermo(PNG_1X1, "cos'è questo errore?")
    time.sleep(0.8)
    content = client.chiamate[-1]["messages"][0]["content"]
    assert isinstance(content, list) and content[0]["type"] == "image"
    assert "cos'è questo errore?" in content[1]["text"] and "screenshot" in content[1]["text"]
    assert "errore nella console" in content[1]["text"]  # la trascrizione c'è sempre
    assert any(e[0] == "schermo" for e in ev.log)
    assert any(e[0] == "inizio" and e[1].startswith("📸 Domanda") for e in ev.log), ev.log
    assert m._pendente is None  # la richiesta con lo schermo annulla l'automatico in attesa
