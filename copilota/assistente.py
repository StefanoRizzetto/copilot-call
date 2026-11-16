"""Suggerimenti da Claude in streaming, a partire dalla trascrizione recente."""
from __future__ import annotations

import threading
from collections.abc import Callable

NESSUN_SUGGERIMENTO = "—"

PROMPT_SISTEMA = f"""Sei un copilota silenzioso che aiuta un programmatore durante una videochiamata tecnica con altri programmatori.
Ricevi la trascrizione automatica degli ultimi minuti: "Io" è la persona che stai aiutando, "Interlocutore" sono gli altri partecipanti.
La trascrizione è automatica: termini tecnici, nomi di librerie e frammenti di codice possono essere storpiati. Interpretali nel modo più plausibile per il contesto.

Quando emerge una domanda o una decisione tecnica (per esempio «come facciamo a fare in modo che…», «che pattern conviene usare per…»), dai un suggerimento che si legga in 10-15 secondi e si possa usare subito nella discussione.

Formato:
- Prima riga in **grassetto**: la risposta o la raccomandazione, in una frase.
- Poi 2-4 punti brevi: come si fa, alternative, trade-off o rischi da citare.
- Solo se aiuta davvero, uno snippet di codice di massimo 8 righe.
- Se la domanda è ambigua, chiudi con una domanda da fare all'interlocutore per chiarire.

Niente premesse, saluti o ripetizioni della domanda. Scrivi in italiano; i termini tecnici restano in inglese.
Se non c'è niente su cui valga la pena intervenire, rispondi soltanto con: {NESSUN_SUGGERIMENTO}"""


def costruisci_messaggio(
    trascrizione: str,
    focus: str | None = None,
    domanda_utente: str | None = None,
    precedenti: list[str] | None = None,
    schermo: bool = False,
) -> str:
    parti = [f"Trascrizione degli ultimi minuti:\n<trascrizione>\n{trascrizione or '(ancora vuota)'}\n</trascrizione>"]
    if precedenti:
        elenco = "\n".join(f"- {p.splitlines()[0][:200]}" for p in precedenti if p.strip())
        if elenco:
            parti.append(f"Suggerimenti già mostrati di recente (non ripeterli; al massimo approfondisci):\n{elenco}")
    if schermo:
        parti.append(
            "In allegato c'è uno screenshot dello schermo principale dell'utente, catturato adesso. "
            "Usalo per capire a cosa si riferiscono la domanda e la discussione (codice, errori, diagrammi, documenti)."
        )
    if domanda_utente:
        parti.append(f"L'utente ti chiede direttamente: «{domanda_utente}». Rispondi tenendo conto della chiamata.")
    elif schermo:
        parti.append(
            "L'utente ti mostra il suo schermo: indica cosa c'è di rilevante rispetto al punto in discussione "
            "e suggerisci cosa dire o fare. Se lo schermo non c'entra con la call, dillo in una riga."
        )
    elif focus:
        parti.append(f"Concentrati su questo intervento: «{focus}»")
    else:
        parti.append("L'utente ha chiesto un suggerimento adesso: aiutalo sul punto in discussione in questo momento.")
    return "\n\n".join(parti)


def contenuto(messaggio: str, immagine=None):
    """Contenuto del messaggio utente: solo testo, oppure immagine + testo."""
    if immagine is None:
        return messaggio
    return [immagine.blocco(), {"type": "text", "text": messaggio}]


class Assistente:
    def __init__(self, modello: str, max_token: int, contesto_utente: str = "", client=None):
        if client is None:
            import anthropic

            client = anthropic.Anthropic()  # legge ANTHROPIC_API_KEY
        self.client = client
        self.modello = modello
        self.max_token = max_token
        self.sistema = [{"type": "text", "text": PROMPT_SISTEMA}]
        if contesto_utente.strip():
            self.sistema.append(
                {
                    "type": "text",
                    "text": f"Contesto di lavoro dell'utente (scritto da lui):\n{contesto_utente.strip()}",
                }
            )
        self.sistema[-1]["cache_control"] = {"type": "ephemeral"}

    def suggerisci(
        self,
        messaggio: str,
        su_testo: Callable[[str], None],
        annulla: threading.Event,
        immagine=None,
    ) -> str:
        """Chiama Claude in streaming. Restituisce il testo completo."""
        completo = []
        with self.client.messages.stream(
            model=self.modello,
            max_tokens=self.max_token,
            system=self.sistema,
            messages=[{"role": "user", "content": contenuto(messaggio, immagine)}],
        ) as stream:
            for pezzo in stream.text_stream:
                if annulla.is_set():
                    break
                completo.append(pezzo)
                su_testo(pezzo)
        return "".join(completo)


def trova_claude(percorso: str = "") -> str:
    """Trova l'eseguibile di Claude Code."""
    import shutil
    from pathlib import Path

    candidati = [percorso] if percorso else []
    candidati += [
        shutil.which("claude") or "",
        str(Path.home() / ".local/bin/claude"),
        str(Path.home() / ".claude/local/claude"),
        "/opt/homebrew/bin/claude",
        "/usr/local/bin/claude",
    ]
    for c in candidati:
        if c and Path(c).expanduser().exists():
            return str(Path(c).expanduser())
    raise RuntimeError(
        "Non trovo Claude Code. Installalo (https://code.claude.com), poi lancia 'claude' una volta "
        "nel Terminale e fai l'accesso con il tuo abbonamento."
    )


class AssistenteClaudeCode:
    """Usa 'claude -p' (Claude Code) con l'accesso del tuo abbonamento, senza chiave API."""

    # Opzioni che rendono l'avvio più leggero; se la tua versione non ne conosce una, viene tolta.
    OPZIONALI = [
        ["--safe-mode"],
        ["--strict-mcp-config"],
        ["--disable-slash-commands"],
        ["--no-session-persistence"],
    ]

    def __init__(self, modello: str, contesto_utente: str = "", eseguibile: str = "", sforzo: str = "low",
                 preriscalda: bool = True):
        import tempfile
        from pathlib import Path

        self.eseguibile = trova_claude(eseguibile)
        self.modello = modello
        self.sforzo = sforzo
        self.cartella = tempfile.mkdtemp(prefix="copilota-")  # cartella vuota: niente CLAUDE.md di progetto
        sistema = PROMPT_SISTEMA
        if contesto_utente.strip():
            sistema += f"\n\nContesto di lavoro dell'utente (scritto da lui):\n{contesto_utente.strip()}"
        self.file_sistema = str(Path(self.cartella) / "sistema.txt")
        Path(self.file_sistema).write_text(sistema, encoding="utf-8")
        self.opzionali = [o for o in self.OPZIONALI]
        if sforzo:
            self.opzionali.append(["--effort", sforzo])
        # Processo 'claude' già avviato e in attesa: elimina il tempo di avvio a ogni suggerimento.
        self.preriscalda = preriscalda
        self._riserva = None
        self._lock = threading.Lock()
        self._chiuso = False
        if preriscalda:
            self.prepara()

    def _comando(self) -> list[str]:
        cmd = [
            self.eseguibile, "-p",
            "--input-format", "stream-json",
            "--output-format", "stream-json", "--verbose", "--include-partial-messages",
            "--system-prompt-file", self.file_sistema,
            "--tools", "",
            "--disallowedTools", "mcp__*",
        ]
        if self.modello:
            cmd += ["--model", self.modello]
        for o in self.opzionali:
            cmd += o
        return cmd

    def _ambiente(self) -> dict:
        import os

        env = dict(os.environ)
        # Senza chiave API nell'ambiente, Claude Code usa l'accesso dell'abbonamento.
        env.pop("ANTHROPIC_API_KEY", None)
        env.pop("ANTHROPIC_AUTH_TOKEN", None)
        return env

    def _nuovo_processo(self):
        import subprocess

        return subprocess.Popen(
            self._comando(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            cwd=self.cartella,
            env=self._ambiente(),
        )

    def prepara(self):
        """Avvia in background il processo per il prossimo suggerimento."""

        def avvia():
            try:
                p = self._nuovo_processo()
            except Exception:
                return
            with self._lock:
                if self._chiuso:
                    p.terminate()
                    return
                vecchio, self._riserva = self._riserva, p
            if vecchio is not None and vecchio.poll() is None:
                vecchio.terminate()

        threading.Thread(target=avvia, daemon=True).start()

    def _prendi(self):
        with self._lock:
            p, self._riserva = self._riserva, None
        if p is not None and (p.poll() is not None or p.args != self._comando()):
            if p.poll() is None:
                p.terminate()
            p = None
        p = p or self._nuovo_processo()
        if self.preriscalda:
            self.prepara()
        return p

    def chiudi(self):
        with self._lock:
            self._chiuso = True
            p, self._riserva = self._riserva, None
        if p is not None and p.poll() is None:
            p.terminate()

    def suggerisci(self, messaggio: str, su_testo: Callable[[str], None], annulla: threading.Event,
                   immagine=None) -> str:
        for _ in range(len(self.opzionali) + 1):
            esito = self._esegui(messaggio, su_testo, annulla, immagine)
            if esito[0] == "ok":
                return esito[1]
            if esito[0] == "opzione":  # opzione sconosciuta: la tolgo e riprovo
                self.opzionali = [o for o in self.opzionali if o[0] != esito[1]]
                continue
            if immagine is not None:
                raise RuntimeError(
                    esito[1] + " — Se succede solo con lo screenshot, la tua versione di Claude Code potrebbe "
                    "non accettare immagini: aggiornala con 'claude update' e riprova con './avvia.sh --prova-schermo'."
                )
            raise RuntimeError(esito[1])
        raise RuntimeError("Claude Code non accetta le opzioni richieste.")

    def _esegui(self, messaggio, su_testo, annulla, immagine=None):
        import json
        import subprocess

        proc = self._prendi()

        def sorveglia():  # se arriva un suggerimento più nuovo, interrompe questo
            while proc.poll() is None:
                if annulla.wait(0.1):
                    proc.terminate()
                    return

        threading.Thread(target=sorveglia, daemon=True).start()
        try:
            riga = {"type": "user", "message": {"role": "user", "content": contenuto(messaggio, immagine)}}
            proc.stdin.write(json.dumps(riga, ensure_ascii=False) + "\n")
            proc.stdin.flush()
        except (BrokenPipeError, OSError):
            pass

        testo, risultato, errore = [], None, False
        for riga in proc.stdout:
            riga = riga.strip()
            if not riga:
                continue
            try:
                ev = json.loads(riga)
            except ValueError:
                continue
            if ev.get("type") == "stream_event":
                d = (ev.get("event") or {}).get("delta") or {}
                if d.get("type") == "text_delta" and d.get("text"):
                    testo.append(d["text"])
                    if not annulla.is_set():
                        su_testo(d["text"])
            elif ev.get("type") == "result":
                risultato = ev.get("result")
                errore = bool(ev.get("is_error")) or ev.get("subtype", "success") != "success"
                break
        try:
            proc.stdin.close()  # fine della conversazione: il processo può uscire
        except (BrokenPipeError, OSError):
            pass
        try:
            codice = proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.terminate()
            codice = proc.wait()
        stderr = proc.stderr.read()

        if annulla.is_set() and risultato is None:
            return ("ok", "".join(testo))
        if errore or (risultato is None and codice != 0):
            for o in self.opzionali:
                if o[0] in stderr and ("unknown option" in stderr.lower() or "unrecognized" in stderr.lower()):
                    return ("opzione", o[0])
            dettaglio = (risultato or stderr or f"codice di uscita {codice}").strip()
            if "login" in dettaglio.lower() or "auth" in dettaglio.lower():
                dettaglio += " — lancia 'claude' nel Terminale e fai l'accesso con il tuo abbonamento."
            return ("errore", f"Claude Code: {dettaglio[:400]}")
        completo = "".join(testo)
        if not completo and risultato:
            completo = risultato
            su_testo(risultato)
        return ("ok", completo)
