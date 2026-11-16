"""Avvio: python -m copilota [--dispositivi | --prova-audio | --solo-trascrizione | --prova-claude | --prova-schermo]"""
from __future__ import annotations

import argparse
import os
import queue
import sys
import time
from pathlib import Path

import numpy as np

from .config import carica
from .motore import Eventi, Motore

CARTELLA = Path(__file__).resolve().parent.parent


class EventiTerminale(Eventi):
    def intervento(self, chi, testo):
        print(f"{chi}: {testo}", flush=True)

    def stato(self, testo):
        print(f"· {testo}", flush=True)

    def errore(self, testo):
        print(f"! {testo}", file=sys.stderr, flush=True)


def elenca():
    from .audio import elenca_ingressi

    print("Dispositivi di ingresso:")
    for i, nome, ch, sr in elenca_ingressi():
        print(f"  [{i}] {nome}  ({ch} canali, {sr} Hz)")


def prova_audio(cfg, secondi=20):
    from .audio import Cattura

    a = cfg["audio"]
    coda: queue.Queue = queue.Queue()
    catture = [Cattura(a["microfono"] or None, a["etichetta_microfono"], coda)]
    if a.get("sistema"):
        catture.append(Cattura(a["sistema"], a["etichetta_sistema"], coda))
    for c in catture:
        print(f"{c.etichetta} ← {c.nome} ({c.sr} Hz)")
        c.avvia()
    print(f"Parla e fai partire un audio (es. un video su YouTube) per {secondi} secondi…\n")
    livelli = {c.etichetta: -100.0 for c in catture}
    fine = time.time() + secondi
    prossimo = time.time() + 0.5
    while time.time() < fine:
        try:
            chi, b = coda.get(timeout=0.1)
            db = 20 * np.log10(max(float(np.sqrt(np.mean(b**2))), 1e-5))
            livelli[chi] = max(livelli[chi], db)
        except queue.Empty:
            pass
        if time.time() >= prossimo:
            riga = "   ".join(
                f"{k}: {'█' * int(max(0, (v + 70) / 3)):<24}{v:6.1f} dB" for k, v in livelli.items()
            )
            print("\r" + riga, end="", flush=True)
            livelli = {k: -100.0 for k in livelli}
            prossimo = time.time() + 0.5
    print()
    for c in catture:
        c.ferma()


def prova_claude(cfg, modello=None):
    import threading

    from .assistente import Assistente, AssistenteClaudeCode, costruisci_messaggio

    c = cfg["claude"]
    from .motore import modelli

    modello = modello or modelli(c)["auto"]
    if c.get("motore", "claude-code") == "api":
        a = Assistente(modello, int(c["max_token"]))
        prove = [("API", "Come possiamo fare in modo che non perdiamo eventi se il database fa commit ma Kafka è giù?")]
    else:
        a = AssistenteClaudeCode(modello, "", c.get("percorso_claude", ""), c.get("sforzo", "low"), preriscalda=False)
        print(f"Uso Claude Code: {a.eseguibile} · modello {modello}\n")
        prove = [
            ("avvio a freddo", "Come possiamo fare in modo che non perdiamo eventi se il database fa commit ma Kafka è giù?"),
            ("processo già pronto", "Che pattern ci conviene usare per gestire i retry verso un servizio esterno lento?"),
        ]
    tempi = []
    for i, (nome, domanda) in enumerate(prove):
        if i == 1:
            a.preriscalda = True
            a.prepara()
            time.sleep(6)  # come in una call: il processo si avvia mentre si parla
        msg = costruisci_messaggio(f"[00:05] Interlocutore: {domanda}", focus=domanda)
        print(f"── {nome}: «{domanda}»\n")
        t0 = time.time()
        primo = []

        def stampa(p, t0=t0, primo=primo):
            if not primo:
                primo.append(time.time() - t0)
            print(p, end="", flush=True)

        a.suggerisci(msg, stampa, threading.Event())
        tempi.append((nome, primo[0] if primo else 0, time.time() - t0))
        print("\n")
    if hasattr(a, "chiudi"):
        a.chiudi()
    for nome, primo, totale in tempi:
        print(f"· {nome}: primo testo dopo {primo:.1f}s, completo dopo {totale:.1f}s")


def prova_schermo(cfg, modello=None):
    """Cattura lo schermo, lo manda a Claude e misura i tempi: verifica permesso e supporto immagini."""
    import tempfile
    import threading

    from .assistente import Assistente, AssistenteClaudeCode, costruisci_messaggio
    from .motore import modelli
    from .schermo import cattura, dimensioni_png, prepara

    s, c = cfg["schermo"], cfg["claude"]
    t0 = time.time()
    png = cattura(int(s["numero"]))
    t_cattura = time.time() - t0
    t0 = time.time()
    immagine = prepara(png, int(s["lato_max"]), int(s["qualita"]))
    t_prepara = time.time() - t0
    dim = dimensioni_png(png) or (0, 0)
    print(f"Schermo {s['numero']}: {dim[0]}×{dim[1]} px, catturato in {t_cattura:.2f}s")
    print(f"Da mandare a Claude: {immagine.tipo}, {len(immagine.dati) // 1024} KB, preparato in {t_prepara:.2f}s")
    estensione = ".jpg" if immagine.tipo == "image/jpeg" else ".png"
    file = Path(tempfile.gettempdir()) / f"copilota-prova-schermo{estensione}"
    file.write_bytes(immagine.dati)
    print(f"Per vedere cosa riceve Claude: open {file}")
    print("(se vedi solo lo sfondo senza finestre, manca il permesso di Registrazione schermo)\n")

    modello = modello or modelli(c)["manuale"]
    if c.get("motore", "claude-code") == "api":
        a = Assistente(modello, int(c["max_token"]))
    else:
        a = AssistenteClaudeCode(modello, "", c.get("percorso_claude", ""), c.get("sforzo", "low"), preriscalda=False)
    domanda = "Descrivi in due righe cosa vedi sullo schermo."
    msg = costruisci_messaggio("", domanda_utente=domanda, schermo=True)
    print(f"── {modello}: «{domanda}»\n")
    t0 = time.time()
    primo = []

    def stampa(p):
        if not primo:
            primo.append(time.time() - t0)
        print(p, end="", flush=True)

    a.suggerisci(msg, stampa, threading.Event(), immagine=immagine)
    totale = time.time() - t0
    if hasattr(a, "chiudi"):
        a.chiudi()
    print(f"\n\n· primo testo dopo {primo[0] if primo else 0:.1f}s, completo dopo {totale:.1f}s (avvio a freddo)")


def main(argv=None):
    p = argparse.ArgumentParser(prog="copilota", description="Suggerimenti di Claude in tempo reale durante le call.")
    p.add_argument("--config", default=str(CARTELLA / "config.toml"))
    p.add_argument("--dispositivi", action="store_true", help="elenca i dispositivi audio")
    p.add_argument("--prova-audio", action="store_true", help="mostra i livelli di microfono e BlackHole")
    p.add_argument("--solo-trascrizione", action="store_true", help="trascrive nel terminale, senza Claude né finestra")
    p.add_argument("--prova-claude", action="store_true", help="chiede due suggerimenti di prova a Claude e misura i tempi")
    p.add_argument("--prova-schermo", action="store_true",
                   help="cattura lo schermo principale e lo manda a Claude: verifica permesso e tempi")
    p.add_argument("--modello", help="con --prova-claude o --prova-schermo: prova un altro modello (es. claude-haiku-5-5)")
    args = p.parse_args(argv)
    cfg = carica(Path(args.config))

    if args.prova_claude:
        try:
            prova_claude(cfg, args.modello)
        except Exception as e:  # noqa: BLE001
            print(f"\n! {e}", file=sys.stderr)
            sys.exit(1)
        return
    if args.prova_schermo:
        try:
            prova_schermo(cfg, args.modello)
        except Exception as e:  # noqa: BLE001
            print(f"\n! {e}", file=sys.stderr)
            sys.exit(1)
        return
    if args.dispositivi:
        elenca()
        return
    if args.prova_audio:
        prova_audio(cfg)
        return
    if args.solo_trascrizione:
        m = Motore(cfg, EventiTerminale(), usa_claude=False)
        m.avvia()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            m.ferma()
        return

    from PySide6.QtWidgets import QApplication

    from .finestra import EventiQt, Finestra, Segnali, nascondi_da_condivisione

    app = QApplication(sys.argv)
    app.setApplicationName("Copilota call")
    segnali = Segnali()
    motore = Motore(cfg, EventiQt(segnali))
    finestra = Finestra(segnali, motore)
    finestra.show()
    nascondi_da_condivisione(finestra)
    motore.avvia()
    codice = app.exec()
    # Chiusura ordinata, poi uscita immediata. Lasciando a Python la chiusura normale, PySide6
    # distrugge i widget rimasti durante lo spegnimento dell'interprete e a volte va in crash
    # (segmentation fault in QObject::~QObject). Non c'è niente da salvare, quindi os._exit è sicuro.
    finestra.chiudi_tutto()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(codice)


if __name__ == "__main__":
    main()
