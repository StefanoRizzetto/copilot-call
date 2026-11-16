"""Finestra sempre in primo piano con suggerimenti e trascrizione."""
from __future__ import annotations

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QPixmap, QShortcut
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

        self.setWindowTitle("Copilota call")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setStyleSheet(STILE)
        self.resize(470, 680)

        self.lbl_stato = QLabel("Avvio…")
        self.lbl_stato.setObjectName("stato")
        self.lbl_stato.setWordWrap(True)
        self.lbl_errore = QLabel("")
        self.lbl_errore.setObjectName("errore")
        self.lbl_errore.setWordWrap(True)
        self.lbl_errore.hide()

        self.chk_auto = QCheckBox("Suggerimenti automatici")
        self.chk_auto.setChecked(motore.auto)
        self.chk_auto.toggled.connect(lambda v: setattr(self.motore, "auto", v))
        btn_ora = QPushButton("Suggerisci ora  ⌘↩")
        btn_ora.clicked.connect(self._suggerisci_ora)
        btn_pulisci = QPushButton("Pulisci")
        btn_pulisci.setObjectName("secondario")
        btn_pulisci.clicked.connect(self._pulisci)
        btn_schermo = QPushButton("📸 Schermo")
        btn_schermo.setObjectName("secondario")
        btn_schermo.setToolTip(
            "Manda a Claude lo schermo principale insieme alla domanda scritta, se c'è (⌘⇧↩)"
        )
        btn_schermo.clicked.connect(self._screenshot)

        barra = QHBoxLayout()
        barra.addWidget(self.chk_auto)
        barra.addStretch(1)
        barra.addWidget(btn_pulisci)
        barra.addWidget(btn_schermo)
        barra.addWidget(btn_ora)

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

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.addLayout(barra)
        lay.addWidget(self.miniatura, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(divisore, 1)
        lay.addWidget(self.domanda)
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

    def closeEvent(self, e):
        self.motore.ferma()
        super().closeEvent(e)
