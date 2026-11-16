"""Finestra sempre in primo piano con suggerimenti e trascrizione."""
from __future__ import annotations

import sys

from PySide6.QtCore import QObject, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .motore import Eventi

STILE = """
QWidget { background: #17181c; color: #e8e8ea; font-size: 13px; }
QTextBrowser, QPlainTextEdit, QLineEdit {
    background: #202227; border: 1px solid #2e3037; border-radius: 8px; padding: 6px;
}
QPlainTextEdit { color: #9a9ca5; font-size: 12px; }
QPushButton {
    background: #d97757; color: #17181c; border: none; border-radius: 7px;
    padding: 6px 12px; font-weight: 600;
}
QPushButton:hover { background: #e58a6c; }
QPushButton#secondario { background: #2e3037; color: #e8e8ea; font-weight: 400; }
QPushButton#secondario:checked { background: #8a5a2b; color: #fff; }
QLabel#livello { color: #9a9ca5; font-size: 11px; }
QLabel#scorciatoie { color: #7d808a; font-size: 11px; }
QLabel#stato { color: #9a9ca5; font-size: 11px; }
QLabel#errore { color: #ff8a80; font-size: 11px; }
QLabel#miniatura { border: 1px solid #2e3037; border-radius: 4px; }
"""

MAX_STORICO = 5


class Segnali(QObject):
    intervento = Signal(str, str)
    stato = Signal(str)
    sugg_inizio = Signal(str)
    sugg_testo = Signal(str)
    sugg_fine = Signal(bool)
    errore = Signal(str)
    schermo = Signal(bytes)
    livelli = Signal(object)


class EventiQt(Eventi):
    """Passa gli eventi dai thread di lavoro alla finestra tramite segnali Qt."""

    def __init__(self, s: Segnali):
        self.s = s

    def intervento(self, chi, testo):
        self.s.intervento.emit(chi, testo)

    def stato(self, testo):
        self.s.stato.emit(testo)

    def sugg_inizio(self, titolo):
        self.s.sugg_inizio.emit(titolo)

    def sugg_testo(self, pezzo):
        self.s.sugg_testo.emit(pezzo)

    def sugg_fine(self, vuoto):
        self.s.sugg_fine.emit(vuoto)

    def errore(self, testo):
        self.s.errore.emit(testo)

    def schermo(self, dati):
        self.s.schermo.emit(dati)

    def livelli(self, valori):
        self.s.livelli.emit(valori)


class Livello(QWidget):
    """Barretta del livello audio di un canale, con una linea al livello minimo consigliato."""

    MIN_DB, MAX_DB, OBIETTIVO_DB = -70.0, 0.0, -45.0

    def __init__(self, nome: str):
        super().__init__()
        self.db = -100.0
        self.setFixedHeight(14)
        self.setMinimumWidth(70)
        self.setToolTip(
            f"Livello di «{nome}». Quando parla deve superare la linea (−45 dB), "
            "con picchi tra −35 e −15 dB."
        )

    def imposta(self, db: float):
        self.db = max(db, self.db - 3.0)  # sale subito, scende piano
        self.update()

    def _x(self, db: float) -> float:
        f = (min(max(db, self.MIN_DB), self.MAX_DB) - self.MIN_DB) / (self.MAX_DB - self.MIN_DB)
        return f * self.width()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        y, h = (self.height() - 6) / 2, 6
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#2e3037"))
        p.drawRoundedRect(QRectF(0, y, self.width(), h), 3, 3)
        if self.db > self.MIN_DB:
            p.setBrush(QColor("#5fb878" if self.db >= self.OBIETTIVO_DB else "#6b6e78"))
            p.drawRoundedRect(QRectF(0, y, self._x(self.db), h), 3, 3)
        p.setPen(QColor("#9a9ca5"))
        x = self._x(self.OBIETTIVO_DB)
        p.drawLine(int(x), 1, int(x), self.height() - 1)
        p.end()


def nascondi_da_condivisione(widget: QWidget) -> bool:
    """Prova a escludere la finestra dalla condivisione schermo (NSWindowSharingNone).

    Non tutte le app di videochiamata rispettano questa impostazione: va verificato.
    """
    try:
        import ctypes

        import objc

        vista = objc.objc_object(c_void_p=ctypes.c_void_p(int(widget.winId())))
        vista.window().setSharingType_(0)
        return True
    except Exception:
        return False


class Finestra(QWidget):
    def __init__(self, segnali: Segnali, motore):
        super().__init__()
        self.motore = motore
        self.storico: list[str] = []
        self.corrente: str | None = None
        self.titolo_corrente = ""
        self._catturando = False
        self.scorciatoie = None

        self.setWindowTitle("Copilota call")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setStyleSheet(STILE)
        self.resize(490, 680)

        self.lbl_stato = QLabel("Avvio…")
        self.lbl_stato.setObjectName("stato")
        self.lbl_stato.setWordWrap(True)
        self.lbl_errore = QLabel("")
        self.lbl_errore.setObjectName("errore")
        self.lbl_errore.setWordWrap(True)
        self.lbl_errore.hide()

        self.chk_auto = QCheckBox("Automatici")
        self.chk_auto.setToolTip("Suggerimenti automatici quando nella call emerge una domanda tecnica")
        self.chk_auto.setChecked(motore.auto)
        self.chk_auto.toggled.connect(lambda v: setattr(self.motore, "auto", v))
        self.btn_ora = btn_ora = QPushButton("Suggerisci ora")
        btn_ora.setToolTip("Suggerimento sul punto in discussione (⌘↩)")
        btn_ora.clicked.connect(self._suggerisci_ora)
        self.btn_pausa = QPushButton("⏸ Pausa")
        self.btn_pausa.setObjectName("secondario")
        self.btn_pausa.setCheckable(True)
        self.btn_pausa.setToolTip("Mette in pausa la trascrizione: niente arriva a Claude finché non riprendi")
        self.btn_pausa.toggled.connect(self._pausa)
        btn_pulisci = QPushButton("Pulisci")
        btn_pulisci.setObjectName("secondario")
        btn_pulisci.clicked.connect(self._pulisci)
        self.btn_schermo = btn_schermo = QPushButton("📸 Schermo")
        btn_schermo.setObjectName("secondario")
        btn_schermo.setToolTip(
            "Manda a Claude lo schermo principale insieme alla domanda scritta, se c'è (⌘⇧↩)"
        )
        btn_schermo.clicked.connect(self._screenshot)

        barra = QHBoxLayout()
        barra.addWidget(self.chk_auto)
        barra.addStretch(1)
        barra.addWidget(self.btn_pausa)
        barra.addWidget(btn_pulisci)
        barra.addWidget(btn_schermo)
        barra.addWidget(btn_ora)

        # Livelli audio dei canali (sempre visibili: un microfono troppo basso si vede subito)
        a = motore.cfg["audio"]
        canali = [a["etichetta_microfono"]] + ([a["etichetta_sistema"]] if a.get("sistema") else [])
        self.livelli: dict[str, tuple[Livello, QLabel]] = {}
        riga_livelli = QHBoxLayout()
        riga_livelli.setSpacing(6)
        for nome in canali:
            etichetta = QLabel(nome)
            etichetta.setObjectName("livello")
            barretta = Livello(nome)
            valore = QLabel("—")
            valore.setObjectName("livello")
            valore.setFixedWidth(46)
            riga_livelli.addWidget(etichetta)
            riga_livelli.addWidget(barretta, 1)
            riga_livelli.addWidget(valore)
            self.livelli[nome] = (barretta, valore)

        # Miniatura dell'ultimo screenshot mandato a Claude
        self.miniatura = QLabel()
        self.miniatura.setObjectName("miniatura")
        self.miniatura.setToolTip("Ultimo screenshot mandato a Claude")
        self.miniatura.hide()

        self.suggerimenti = QTextBrowser()
        self.suggerimenti.setOpenExternalLinks(True)
        self.suggerimenti.setMarkdown("_I suggerimenti compariranno qui quando nella call emerge una domanda tecnica._")

        self.trascrizione = QPlainTextEdit()
        self.trascrizione.setReadOnly(True)
        self.trascrizione.setMaximumBlockCount(300)
        self.trascrizione.setPlaceholderText("Trascrizione dal vivo…")

        divisore = QSplitter(Qt.Orientation.Vertical)
        divisore.addWidget(self.suggerimenti)
        divisore.addWidget(self.trascrizione)
        divisore.setSizes([480, 160])

        self.domanda = QLineEdit()
        self.domanda.setPlaceholderText("Chiedi qualcosa a Claude sulla call… (Invio · ⌘⇧↩ con lo schermo)")
        self.domanda.returnPressed.connect(self._chiedi)

        # Promemoria delle scorciatoie, sempre visibile sotto il campo domanda
        self.lbl_scorciatoie = QLabel()
        self.lbl_scorciatoie.setObjectName("scorciatoie")
        self.lbl_scorciatoie.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_scorciatoie.setWordWrap(True)
        self._mostra_scorciatoie([])

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.addLayout(barra)
        lay.addLayout(riga_livelli)
        lay.addWidget(self.miniatura, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(divisore, 1)
        lay.addWidget(self.domanda)
        lay.addWidget(self.lbl_scorciatoie)
        lay.addWidget(self.lbl_errore)
        lay.addWidget(self.lbl_stato)

        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self._suggerisci_ora)
        QShortcut(QKeySequence("Ctrl+Shift+Return"), self, activated=self._screenshot)  # ⌘⇧↩ su macOS

        segnali.intervento.connect(self._intervento)
        segnali.stato.connect(self.lbl_stato.setText)
        segnali.sugg_inizio.connect(self._sugg_inizio)
        segnali.sugg_testo.connect(self._sugg_testo)
        segnali.sugg_fine.connect(self._sugg_fine)
        segnali.errore.connect(self._errore)
        segnali.schermo.connect(self._mostra_miniatura)
        segnali.livelli.connect(self._aggiorna_livelli)

        self._registra_scorciatoie()

    # ---------- azioni ----------
    def _suggerisci_ora(self):
        self.lbl_errore.hide()
        self.motore.suggerisci_ora()

    def _chiedi(self):
        t = self.domanda.text().strip()
        if t:
            self.lbl_errore.hide()
            self.domanda.clear()
            self.motore.chiedi(t)

    def _screenshot(self):
        """Cattura lo schermo principale e lo manda a Claude con la domanda scritta, se c'è."""
        if self._catturando:
            return
        self._catturando = True
        self.lbl_errore.hide()
        domanda = self.domanda.text().strip() or None
        self.domanda.clear()
        # La finestra diventa trasparente per un attimo, così non compare nello screenshot.
        self.setWindowOpacity(0.0)
        QTimer.singleShot(150, lambda: self._scatta(domanda))

    def _scatta(self, domanda):
        from .schermo import cattura

        try:
            png = cattura(int(self.motore.cfg["schermo"]["numero"]))
        except Exception as e:  # noqa: BLE001
            self._errore(str(e))
            if domanda:
                self.domanda.setText(domanda)  # non perdere la domanda scritta
            return
        finally:
            self.setWindowOpacity(1.0)
            self._catturando = False
        self.motore.chiedi_su_schermo(png, domanda)

    def _pausa(self, attiva: bool):
        self.btn_pausa.setText("▶ Riprendi" if attiva else "⏸ Pausa")
        self.motore.imposta_pausa(attiva)

    def _registra_scorciatoie(self):
        """Scorciatoie globali di macOS (config.toml → [scorciatoie])."""
        if sys.platform != "darwin":
            return
        from .scorciatoie import ScorciatoieGlobali

        voci = [
            ("suggerisci", self._suggerisci_ora, self.btn_ora),
            ("schermo", self._screenshot, self.btn_schermo),
            ("pausa", self.btn_pausa.toggle, self.btn_pausa),
        ]
        self.scorciatoie = ScorciatoieGlobali()
        problemi, attive = [], []
        for chiave, azione, bottone in voci:
            testo = (self.motore.cfg.get("scorciatoie", {}).get(chiave) or "").strip()
            if not testo:
                continue
            try:
                etichetta = self.scorciatoie.registra(testo, azione)
            except Exception as e:  # noqa: BLE001
                problemi.append(f"'{testo}': {e}")
                continue
            bottone.setToolTip(bottone.toolTip() + f" · {etichetta} da qualsiasi app")
            attive.append((etichetta, chiave))
        self._mostra_scorciatoie(attive)
        if problemi:
            self._errore("Scorciatoie globali non attive: " + "; ".join(problemi)
                         + ". Cambiale in [scorciatoie] di config.toml.")

    NOMI_AZIONI = {"suggerisci": "suggerisci", "schermo": "📸 schermo", "pausa": "pausa"}

    def _mostra_scorciatoie(self, globali: list[tuple[str, str]]):
        """Riga con le scorciatoie attive: quelle globali se registrate, altrimenti quelle della finestra."""
        if globali:
            voci = [f"<b>{etichetta}</b> {self.NOMI_AZIONI.get(chiave, chiave)}" for etichetta, chiave in globali]
            testo = " &nbsp;·&nbsp; ".join(voci) + " &nbsp;<i>(da qualsiasi app)</i>"
        else:
            testo = "<b>⌘↩</b> suggerisci &nbsp;·&nbsp; <b>⌘⇧↩</b> 📸 schermo &nbsp;<i>(con la finestra in primo piano)</i>"
        self.lbl_scorciatoie.setText(testo)

    def _pulisci(self):
        self.storico.clear()
        self.corrente = None
        self.miniatura.hide()
        self._mostra()

    # ---------- eventi ----------
    def _intervento(self, chi, testo):
        self.trascrizione.appendPlainText(f"{chi}: {testo}")

    def _sugg_inizio(self, titolo):
        if self.corrente:  # un suggerimento interrotto finisce nello storico
            self._archivia(self.corrente + "\n\n_(interrotto)_")
        self.titolo_corrente = titolo
        self.corrente = ""
        self._mostra()

    def _sugg_testo(self, pezzo):
        if self.corrente is None:
            self.corrente = ""
        self.corrente += pezzo
        self._mostra()

    def _sugg_fine(self, vuoto):
        if self.corrente is not None and not vuoto:
            self._archivia(self.corrente)
        self.corrente = None
        self._mostra(nota="_Nessun suggerimento utile per questo passaggio._" if vuoto else None)

    def _errore(self, testo):
        self.lbl_errore.setText(testo)
        self.lbl_errore.show()

    def _aggiorna_livelli(self, valori: dict):
        for nome, db in valori.items():
            if nome in self.livelli:
                barretta, valore = self.livelli[nome]
                barretta.imposta(db)
                valore.setText("—" if barretta.db <= -69 else f"{barretta.db:.0f} dB")

    def _mostra_miniatura(self, dati):
        pix = QPixmap()
        if pix.loadFromData(dati):
            self.miniatura.setPixmap(pix.scaledToHeight(64, Qt.TransformationMode.SmoothTransformation))
            self.miniatura.show()

    # ---------- disegno ----------
    def _archivia(self, testo):
        intestazione = f"<sub>{self.titolo_corrente}</sub>\n\n" if self.titolo_corrente else ""
        self.storico.insert(0, intestazione + testo)
        del self.storico[MAX_STORICO:]

    def _mostra(self, nota=None):
        blocchi = []
        if self.corrente is not None:
            testa = f"<sub>{self.titolo_corrente} · in corso…</sub>\n\n"
            blocchi.append(testa + (self.corrente or "…"))
        elif nota:
            blocchi.append(nota)
        blocchi.extend(self.storico)
        self.suggerimenti.setMarkdown("\n\n---\n\n".join(blocchi) if blocchi else "")
        self.suggerimenti.verticalScrollBar().setValue(0)

    def chiudi_tutto(self):
        """Ferma audio, Claude e scorciatoie globali. Si può chiamare più volte."""
        if self.scorciatoie is not None:
            self.scorciatoie.chiudi()
        self.motore.ferma()

    def closeEvent(self, e):
        self.chiudi_tutto()
        super().closeEvent(e)
