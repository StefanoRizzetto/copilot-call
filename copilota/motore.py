"""Collega cattura audio → frasi → trascrizione → trigger → Claude."""
from __future__ import annotations

import os
import queue
import threading
import time
from collections import deque
from pathlib import Path

from .assistente import NESSUN_SUGGERIMENTO, Assistente, AssistenteClaudeCode, costruisci_messaggio
from .segmentatore import Segmentatore
from .trigger import sembra_richiesta


def modelli(c: dict) -> dict:
    """Modello per i suggerimenti automatici e per quelli chiesti a mano."""
    # Predefiniti: Haiku per gli automatici (veloce), Sonnet quando chiedi tu (più ragionato).
    # La vecchia chiave 'modello', se presente, vale per entrambi.
    return {
        "auto": c.get("modello_automatici") or c.get("modello") or "claude-haiku-5-5",
        "manuale": c.get("modello_su_richiesta") or c.get("modello") or "claude-sonnet-5-5",
    }


class Eventi:
    """Ricevitore degli eventi del motore (la finestra o il terminale)."""

    def intervento(self, chi: str, testo: str): ...
    def stato(self, testo: str): ...
    def sugg_inizio(self, titolo: str): ...
    def sugg_testo(self, pezzo: str): ...
    def sugg_fine(self, vuoto: bool): ...
    def errore(self, testo: str): ...
    def schermo(self, dati: bytes): ...  # screenshot appena mandato a Claude (per la miniatura)


class Conversazione:
    def __init__(self):
        self._righe: deque = deque(maxlen=2000)
        self._lock = threading.Lock()
        self.inizio = time.time()

    def aggiungi(self, chi: str, testo: str):
        with self._lock:
            self._righe.append((time.time(), chi, testo))

    def recente(self, minuti: float) -> str:
        limite = time.time() - minuti * 60
        with self._lock:
            righe = [r for r in self._righe if r[0] >= limite]
        out = []
        for t, chi, testo in righe:
            s = int(t - self.inizio)
            out.append(f"[{s // 60:02d}:{s % 60:02d}] {chi}: {testo}")
        return "\n".join(out)


class Motore:
    def __init__(self, cfg: dict, eventi: Eventi, usa_claude: bool = True, assistente=None, trascrittore=None):
        self.cfg = cfg
        self.ev = eventi
        self.usa_claude = usa_claude
        self.auto = bool(cfg["suggerimenti"]["automatici"])
        self.conversazione = Conversazione()
        self.coda_audio: queue.Queue = queue.Queue(maxsize=4000)
        self.coda_frasi: queue.Queue = queue.Queue()
        self.catture = []
        self.segmentatori: dict[str, Segmentatore] = {}
        self.sr: dict[str, int] = {}
        self.trascrittore = trascrittore
        # Un assistente per i suggerimenti automatici e uno per quelli chiesti a mano.
        self.assistenti: dict = {"auto": assistente, "manuale": assistente} if assistente else {}
        self.nomi_modelli: dict = {}
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._pendente = None  # dict(scadenza, primo, focus)
        self._ultimo_auto = 0.0
        self._generazione = 0
        self._annulla = threading.Event()
        self._precedenti: deque = deque(maxlen=3)

    # ---------- avvio / arresto ----------
    def avvia(self):
        threading.Thread(target=self._avvio, daemon=True).start()

    def _avvio(self):
        try:
            if self.usa_claude and not self.assistenti:
                c = self.cfg["claude"]
                contesto = ""
                p = Path(self.cfg.get("_cartella", ".")) / c["file_contesto"]
                if p.exists():
                    contesto = p.read_text(encoding="utf-8")
                api = c.get("motore", "claude-code") == "api"
                if api and not os.environ.get("ANTHROPIC_API_KEY"):
                    raise RuntimeError(
                        "Manca ANTHROPIC_API_KEY. Aggiungi 'export ANTHROPIC_API_KEY=…' a ~/.zshrc "
                        "e riapri il Terminale, oppure usa motore = \"claude-code\"."
                    )
                creati: dict = {}
                for tipo, modello in modelli(c).items():
                    if modello not in creati:  # stesso modello = stesso assistente
                        if api:
                            creati[modello] = Assistente(modello, int(c["max_token"]), contesto)
                        else:
                            creati[modello] = AssistenteClaudeCode(
                                modello, contesto, c.get("percorso_claude", ""), c.get("sforzo", "low")
                            )
                    self.assistenti[tipo] = creati[modello]
                    self.nomi_modelli[tipo] = modello

            if self.trascrittore is None:
                self.ev.stato("Carico il modello di trascrizione (la prima volta lo scarica)…")
                from .trascrittore import Trascrittore

                self.trascrittore = Trascrittore(self.cfg["trascrizione"])
                self.trascrittore.riscalda()

            self._apri_audio()
            for f in (self._ciclo_segmenti, self._ciclo_trascrizione, self._ciclo_programmazione):
                threading.Thread(target=f, daemon=True).start()
            for c in self.catture:
                c.avvia()
            nomi = ", ".join(f"{c.etichetta} ← {c.nome}" for c in self.catture)
            self.ev.stato(f"In ascolto · {nomi}")
        except Exception as e:  # noqa: BLE001
            self.ev.errore(str(e))

    def _apri_audio(self):
        from .audio import Cattura

        a = self.cfg["audio"]
        self.catture.append(Cattura(a["microfono"] or None, a["etichetta_microfono"], self.coda_audio))
        if a.get("sistema"):
            self.catture.append(Cattura(a["sistema"], a["etichetta_sistema"], self.coda_audio))
        v = self.cfg["vad"]
        for c in self.catture:
            self.sr[c.etichetta] = c.sr
            self.segmentatori[c.etichetta] = Segmentatore(
                c.sr,
                silenzio_fine_ms=int(v["silenzio_fine_ms"]),
                margine_db=float(v["margine_db"]),
                soglia_min_db=float(v["soglia_min_db"]),
                durata_max_s=float(v["durata_max_s"]),
                durata_min_ms=int(v["durata_min_ms"]),
            )

    def ferma(self):
        self._stop.set()
        self._annulla.set()
        for c in self.catture:
            c.ferma()
        for a in set(self.assistenti.values()):
            if hasattr(a, "chiudi"):
                a.chiudi()

    # ---------- pipeline ----------
    def _ciclo_segmenti(self):
        while not self._stop.is_set():
            try:
                chi, blocco = self.coda_audio.get(timeout=0.2)
            except queue.Empty:
                continue
            for frase in self.segmentatori[chi].aggiungi(blocco):
                self.coda_frasi.put((chi, frase, self.sr[chi]))

    def _ciclo_trascrizione(self):
        from .trascrittore import ricampiona

        while not self._stop.is_set():
            try:
                chi, frase, sr = self.coda_frasi.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                testo = self.trascrittore.trascrivi(ricampiona(frase, sr))
            except Exception as e:  # noqa: BLE001
                self.ev.errore(f"Errore di trascrizione: {e}")
                continue
            if testo:
                self.nuova_frase(chi, testo)

    def nuova_frase(self, chi: str, testo: str):
        self.conversazione.aggiungi(chi, testo)
        self.ev.intervento(chi, testo)
        if not self.usa_claude:
            return
        s = self.cfg["suggerimenti"]
        ora = time.time()
        with self._lock:
            if self._pendente is not None:
                # la frase continua: allunga l'attesa e aggiunge il testo al focus
                p = self._pendente
                p["focus"] += " " + testo
                p["scadenza"] = min(ora + float(s["attesa_s"]), p["primo"] + float(s["attesa_max_s"]))
                return
            if not self.auto or not sembra_richiesta(testo):
                return
            if s.get("solo_interlocutore") and chi != self.cfg["audio"]["etichetta_sistema"]:
                return
            if ora - self._ultimo_auto < float(s["pausa_minima_s"]):
                return
            self._pendente = {"scadenza": ora + float(s["attesa_s"]), "primo": ora, "focus": testo}

    def _ciclo_programmazione(self):
        while not self._stop.is_set():
            time.sleep(0.1)
            with self._lock:
                p = self._pendente
                if p is None or time.time() < p["scadenza"]:
                    continue
                self._pendente = None
                self._ultimo_auto = time.time()
            self._lancia("auto", focus=p["focus"], titolo="Domanda rilevata")

    # ---------- richieste ----------
    def suggerisci_ora(self):
        with self._lock:
            self._pendente = None
        self._lancia("manuale", titolo="Su richiesta")

    def chiedi(self, domanda: str):
        self._lancia("manuale", domanda_utente=domanda, titolo=f"Domanda: {domanda}")

    def chiedi_su_schermo(self, png: bytes, domanda: str | None = None):
        """Suggerimento su richiesta con lo screenshot dello schermo (PNG già catturato).

        L'immagine viene ridotta e convertita in un thread a parte, poi parte come una
        richiesta manuale (modello su richiesta). Non viene salvata da nessuna parte.
        """
        with self._lock:
            self._pendente = None

        def lavora():
            from .schermo import prepara

            s = self.cfg["schermo"]
            try:
                immagine = prepara(png, int(s["lato_max"]), int(s["qualita"]))
            except Exception as e:  # noqa: BLE001
                self.ev.errore(f"Errore nella preparazione dello screenshot: {e}")
                return
            self.ev.schermo(immagine.dati)
            titolo = f"📸 Domanda: {domanda}" if domanda else "📸 Schermo"
            self._lancia("manuale", domanda_utente=domanda, titolo=titolo, immagine=immagine)

        threading.Thread(target=lavora, daemon=True).start()

    def _lancia(self, tipo, focus=None, domanda_utente=None, titolo="", immagine=None):
        assistente = self.assistenti.get(tipo)
        if not self.usa_claude or assistente is None:
            self.ev.errore("Claude non è ancora pronto.")
            return
        self._annulla.set()  # interrompe un suggerimento ancora in corso
        annulla = threading.Event()
        with self._lock:
            self._generazione += 1
            gen = self._generazione
            self._annulla = annulla
        minuti = float(self.cfg["claude"]["minuti_contesto"])
        msg = costruisci_messaggio(
            self.conversazione.recente(minuti), focus, domanda_utente, list(self._precedenti),
            schermo=immagine is not None,
        )
        nome = self.nomi_modelli.get(tipo, "")
        if nome:
            titolo += " · " + nome.replace("claude-", "").split("-")[0].capitalize()
        threading.Thread(
            target=self._esegui, args=(assistente, gen, msg, titolo, annulla, immagine), daemon=True
        ).start()

    def _esegui(self, assistente, gen, msg, titolo, annulla, immagine=None):
        attuale = lambda: gen == self._generazione and not annulla.is_set()  # noqa: E731
        if not attuale():
            return
        self.ev.sugg_inizio(titolo)
        self.ev.stato("Claude sta pensando…")
        try:
            extra = {"immagine": immagine} if immagine is not None else {}
            testo = assistente.suggerisci(
                msg, lambda pezzo: attuale() and self.ev.sugg_testo(pezzo), annulla, **extra
            )
        except Exception as e:  # noqa: BLE001
            if attuale():
                self.ev.errore(f"Errore da Claude: {e}")
            return
        if attuale():
            vuoto = testo.strip() in ("", NESSUN_SUGGERIMENTO, "-")
            if not vuoto:
                self._precedenti.append(testo.strip())
            self.ev.sugg_fine(vuoto)
            self.ev.stato("In ascolto")
