# Copilota call

Una finestrella sempre in primo piano che ascolta le tue videochiamate (Google Meet, Teams, Zoom, qualsiasi app). Quando nella discussione emerge una domanda tecnica, come «come possiamo fare in modo che…» o «che pattern ci conviene…», ti mostra un suggerimento di Claude in un paio di secondi.

- I suggerimenti usano il tuo **abbonamento Claude tramite Claude Code** (`claude -p`): non serve una chiave API.
- **Haiku** scrive i suggerimenti automatici (primo testo in meno di 1 secondo); **Sonnet** risponde quando chiedi tu (⌘↩ o domanda scritta), con circa 2 secondi in più ma risposte più ragionate.

**Cosa resta sul tuo Mac e cosa no**
- L'audio non lascia mai il computer e non viene salvato: lo trascrive Whisper in locale.
- A Claude arriva solo il **testo** degli ultimi minuti (8 di default), e solo quando serve un suggerimento.
- Lo **screenshot** dello schermo parte solo quando premi tu 📸 (o ⌘⇧↩): resta in memoria e non viene salvato.
- Ogni suggerimento consuma un po' dei limiti di utilizzo del tuo piano, come una normale richiesta a Claude Code.
- Non viene salvato niente su disco: chiusa la finestra, la trascrizione sparisce.

Come è fatto dentro, le scelte fatte e i tempi misurati: [docs/architettura.md](docs/architettura.md).

## Come funziona

```
Microfono (tu) ──┐
                 ├─► rilevamento frasi ─► Whisper locale ─► testo ─► domanda? ─► Claude ─► finestra
BlackHole (loro) ┘
```

Il programma ascolta due canali separati: il tuo microfono ("Io") e l'audio della call che arriva tramite BlackHole ("Interlocutore"). Così sa sempre chi sta parlando.

## Installazione (una volta sola)

Servono un Mac con Apple Silicon (sugli Intel funziona, ma la trascrizione è più lenta), [Homebrew](https://brew.sh) e Claude Code.

### 1. Python e BlackHole

```bash
brew install python@3.12 blackhole-2ch
```

Dopo l'installazione di BlackHole riavvia il Mac, o almeno esci e rientra nella sessione.

### 2. Un'uscita audio che va sia alle cuffie sia a BlackHole

1. Apri **Configurazione MIDI Audio** da Applicazioni → Utility.
2. In basso a sinistra premi **+** → **Crea dispositivo a uscita multipla**.
3. Spunta **le tue cuffie** e **BlackHole 2ch**. Metti le cuffie come *Dispositivo principale* e attiva *Correzione deriva* su BlackHole.
4. Rinominalo, ad esempio "Cuffie + Copilota".

### 3. Nella call, scegli quell'uscita

Basta cambiarla nell'app della call, non in tutto il Mac:
- **Google Meet** (browser): ⋮ → Impostazioni → Audio → Altoparlanti → "Cuffie + Copilota".
- **Teams**: Impostazioni → Dispositivi → Altoparlante → "Cuffie + Copilota".

> Usa le cuffie. Con gli altoparlanti il microfono sente anche la voce degli altri e la trascrizione si duplica.

### 4. Claude Code con il tuo abbonamento

Se non hai ancora Claude Code, installalo seguendo [code.claude.com](https://code.claude.com). Poi, una volta sola:

```bash
claude        # scegli l'accesso con il tuo abbonamento Claude, poi esci con /exit
```

Il programma lancia `claude -p` togliendo dall'ambiente un'eventuale `ANTHROPIC_API_KEY`, così usa sempre l'abbonamento.

### 5. Verifiche

Dalla cartella del progetto:

```bash
./avvia.sh --dispositivi      # al primo avvio installa le dipendenze, poi elenca i dispositivi audio
./avvia.sh --prova-claude     # due suggerimenti di prova: verifica l'accesso e misura i tempi
./avvia.sh --prova-audio      # parla e fai partire un video: devono muoversi entrambe le barre
./avvia.sh --solo-trascrizione  # trascrive nel Terminale, senza Claude né finestra
./avvia.sh --prova-schermo    # cattura lo schermo principale e chiede a Claude di descriverlo
```

- macOS chiederà il permesso del **microfono** per il Terminale: concedilo. Se non compare, vai in Impostazioni di Sistema → Privacy e sicurezza → Microfono.
- La prima trascrizione scarica il modello Whisper (circa 1,6 GB); da lì in poi funziona offline.
- `--prova-claude --modello claude-haiku-5-5` misura un modello diverso da quello predefinito.
- Per gli screenshot serve il permesso di **Registrazione schermo**: al primo `--prova-schermo` macOS lo chiede per il Terminale. Se non compare, vai in Impostazioni di Sistema → Privacy e sicurezza → Registrazione schermo e audio di sistema, abilita il Terminale e riaprilo. Senza permesso lo screenshot contiene solo lo sfondo: `--prova-schermo` ti dice dove aprire l'immagine per controllare.

### 6. Uso normale

```bash
./avvia.sh
```

- I suggerimenti partono da soli quando qualcuno fa una domanda tecnica (con Haiku).
- **⌘↩** o **Suggerisci ora**: un suggerimento sul punto in discussione in quel momento (con Sonnet).
- Nel campo in basso puoi scrivere una domanda («qual era la libreria che ha nominato?»): Claude risponde tenendo conto della call.
- **📸 Schermo** o **⌘⇧↩**: cattura lo schermo principale (quello con la barra dei menu) e lo manda a Claude (con Sonnet) insieme alla trascrizione. Se nel campo in basso hai scritto una domanda («perché fallisce questa query?»), parte insieme allo screenshot; altrimenti Claude ti dice cosa c'è di rilevante sullo schermo rispetto alla discussione. La finestra del copilota sparisce per un attimo, così non compare nell'immagine; in alto vedi la miniatura di cosa è stato mandato.
- Ogni suggerimento indica il motivo e il modello, per esempio "Domanda rilevata · Haiku".

## Provarlo con un video YouTube

- **Veloce, senza BlackHole:** metti `sistema = ""` in `config.toml`, lancia `./avvia.sh` e fai partire il video dalle casse. Lo sente il microfono e compare come "Io": i suggerimenti automatici partono comunque.
- **Come in una call vera:** imposta l'uscita del Mac su "Cuffie + Copilota" (Impostazioni di Sistema → Suono → Uscita), lancia `./avvia.sh` e il video comparirà come "Interlocutore". Finché è attiva l'uscita multipla, i tasti del volume del Mac non funzionano: regola il volume da YouTube, e alla fine rimetti le cuffie.

Scegli un video in cui qualcuno fa domande tecniche ad alta voce (un podcast tra sviluppatori, un talk con domande dal pubblico), oppure usa ⌘↩.

## Personalizzazione

- **`contesto.md`**: descrivi il tuo stack, le tue preferenze e i progetti in corso. È la cosa che migliora di più la qualità dei suggerimenti.
- **`config.toml`**, le impostazioni più utili:

| Impostazione | Predefinito | A cosa serve |
|---|---|---|
| `vocabolario` | termini di programmazione comuni | Nomi di tecnologie e progetti da far trascrivere giusti a Whisper |
| `modello_automatici` | `claude-haiku-5-5` | Modello per i suggerimenti automatici |
| `modello_su_richiesta` | `claude-sonnet-5-5` | Modello per ⌘↩ e le domande scritte |
| `sforzo` | `low` | Livello di ragionamento di Claude Code: `low` è il più veloce |
| `motore` (in `[claude]`) | `claude-code` | `api` per usare una chiave API (`ANTHROPIC_API_KEY`) invece dell'abbonamento |
| `attesa_s` / `attesa_max_s` | 0,6 / 2,5 s | Quanto aspettare dopo una domanda, nel caso continui. Se i suggerimenti partono su mezza domanda, porta `attesa_s` a 1,0 |
| `silenzio_fine_ms` | 550 | Quanto silenzio chiude una frase |
| `pausa_minima_s` | 10 | Secondi minimi tra due suggerimenti automatici |
| `solo_interlocutore` | `false` | `true`: gli automatici partono solo dalle domande degli altri |
| `automatici` | `true` | `false`: solo suggerimenti su richiesta. Si può cambiare anche dalla finestra |
| `margine_db` | 12 | Abbassalo se la trascrizione perde parole, alzalo se trascrive rumore |
| `microfono` / `sistema` | predefinito / `BlackHole` | Parte del nome dei dispositivi audio; `sistema = ""` usa solo il microfono |
| `numero` (in `[schermo]`) | 1 | Schermo catturato da 📸: 1 è il principale, 2, 3… gli altri. Il principale si sceglie in Impostazioni di Sistema → Monitor |
| `lato_max` / `qualita` | 1568 / 80 | Dimensione massima (pixel) e qualità JPEG dello screenshot mandato a Claude |

## Condivisione schermo

All'avvio la finestra prova a escludersi dalla condivisione schermo, ma non tutte le app rispettano questa impostazione. **Fai una prova prima di una call vera.** Nel dubbio, condividi una singola finestra o una scheda invece dell'intero schermo.

## Privacy

Prima di usarlo con i clienti, avvisali che usi un assistente con trascrizione automatica: è la cosa corretta da fare, e con il GDPR è in pratica necessario.

Prima di premere 📸, ricorda che a Claude arriva tutto quello che c'è sullo schermo principale: email, chat, dati dei clienti, notifiche, password visibili.

## Problemi comuni

| Sintomo | Causa probabile |
|---|---|
| "Nessun dispositivo di ingresso contiene 'BlackHole'" | BlackHole non è installato oppure serve un riavvio; per provare senza, metti `sistema = ""` |
| La barra "Interlocutore" non si muove in `--prova-audio` | L'app della call (o il Mac) non sta usando l'uscita "Cuffie + Copilota" |
| Le tue frasi compaiono due volte | Stai usando gli altoparlanti invece delle cuffie |
| Testo strano tipo "Sottotitoli creati da…" | Allucinazioni di Whisper sul rumore: alza `margine_db` |
| "Non trovo Claude Code" | Installalo, oppure scrivi il percorso in `percorso_claude` (lo trovi con `which claude`) |
| "Not logged in" o errore di autenticazione | Lancia `claude` nel Terminale e fai l'accesso con l'abbonamento |
| I suggerimenti arrivano lenti | Misura con `./avvia.sh --prova-claude --modello <nome>` e scegli i modelli in `config.toml` |
| I suggerimenti partono su mezza domanda | Alza `attesa_s` (es. 1,0) |
| "Non riesco a catturare lo schermo" o Claude vede solo lo sfondo | Manca il permesso di Registrazione schermo per il Terminale (vedi Verifiche) |
| Errore da Claude solo con 📸 | La versione di Claude Code potrebbe non accettare immagini: `claude update`, poi `./avvia.sh --prova-schermo` |
| 📸 cattura il monitor sbagliato | Cambia `numero` in `[schermo]`, o scegli il monitor principale in Impostazioni di Sistema → Monitor |

## Per sviluppatori

- Test (niente audio né Claude veri): `.venv/bin/python tests/esegui.py`
- Architettura, flusso dei thread, registro delle decisioni e tempi misurati: [docs/architettura.md](docs/architettura.md)

## File del progetto

```
avvia.sh              crea l'ambiente Python al primo avvio e lancia il programma
config.toml           impostazioni
contesto.md           il tuo contesto di lavoro, passato a Claude
requirements.txt      dipendenze Python
copilota/             codice (audio, segmentazione, trascrizione, trigger, Claude, finestra)
tests/                test automatici e finto 'claude'
docs/architettura.md  documentazione tecnica
```
