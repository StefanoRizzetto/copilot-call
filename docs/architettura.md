# Copilota call: documentazione tecnica

Come è fatto il programma, perché è fatto così e dove intervenire per cambiarlo. La guida d'uso e l'installazione sono nel [README](../README.md).

## In breve

Un'app Python per macOS che:
1. cattura due canali audio: il microfono (tu) e BlackHole (gli altri partecipanti alla call);
2. divide l'audio in frasi con un rilevatore di voce basato sull'energia;
3. trascrive ogni frase in locale con Whisper (mlx-whisper su Apple Silicon);
4. riconosce le domande tecniche con espressioni regolari;
5. chiede un suggerimento a Claude tramite `claude -p` (Claude Code, abbonamento) e lo mostra in streaming in una finestra PySide6 sempre in primo piano.

L'audio non lascia il Mac e non viene salvato. A Claude arriva solo il testo degli ultimi `minuti_contesto` minuti, e solo quando serve un suggerimento.

## Flusso dei dati e thread

```
 thread audio (PortAudio)        thread segmenti          thread trascrizione           thread programmazione     thread suggerimento
 ───────────────────────         ───────────────          ───────────────────           ─────────────────────     ───────────────────
 Cattura("Io") ──┐                                                                       
                 ├─► coda_audio ─► Segmentatore ─► coda_frasi ─► ricampiona 16 kHz          
 Cattura("Int.") ┘   (etichetta,   (uno per         (etichetta,   ─► Whisper ─► testo      
                      blocco)       canale)          frase, sr)        │                    
                                                                       ▼                    
                                                         Conversazione + evento "intervento"
                                                                       │ sembra_richiesta?
                                                                       ▼                    
                                                               _pendente (attesa) ──► _lancia("auto") ──► Assistente.suggerisci
                                                                                                          │ (streaming)
 Finestra (thread Qt) ◄──────────────────── segnali Qt (EventiQt) ◄────────────────────────────────────────┘
   ⌘↩ / domanda scritta ──► _lancia("manuale")
```

Tutti i thread di lavoro comunicano con la finestra solo tramite segnali Qt (`finestra.EventiQt`), quindi l'interfaccia viene aggiornata sempre dal thread principale.

## Moduli

| File | Ruolo |
|---|---|
| `copilota/__main__.py` | Avvio e comandi di diagnosi: `--dispositivi`, `--prova-audio`, `--solo-trascrizione`, `--prova-claude [--modello]` |
| `copilota/config.py` | Valori predefiniti e lettura di `config.toml` (unione profonda) |
| `copilota/audio.py` | `Cattura`: legge un dispositivo di ingresso con `sounddevice`, converte in mono float32, mette i blocchi in coda |
| `copilota/segmentatore.py` | Rilevatore di voce a energia, adattivo sul rumore di fondo; restituisce frasi complete |
| `copilota/trascrittore.py` | Whisper locale (mlx-whisper o faster-whisper), ricampionamento a 16 kHz, filtro delle allucinazioni |
| `copilota/trigger.py` | Espressioni regolari che riconoscono domande e decisioni tecniche (italiano e inglese) |
| `copilota/assistente.py` | Prompt di sistema e costruzione del messaggio; `Assistente` (API) e `AssistenteClaudeCode` (`claude -p`) |
| `copilota/motore.py` | Orchestrazione: thread, conversazione, attesa e pausa minima, due modelli, annullamento |
| `copilota/finestra.py` | Finestra PySide6: suggerimenti (Markdown, ultimi 5), trascrizione, campo domanda, ⌘↩ |
| `tests/` | Test senza audio né Claude veri: `.venv/bin/python tests/esegui.py` |

## Componenti nel dettaglio

### Cattura audio

- Il microfono è il dispositivo di ingresso predefinito, oppure quello il cui nome contiene `audio.microfono`.
- La voce degli altri arriva da BlackHole: nell'app della call l'uscita è un "dispositivo a uscita multipla" che manda l'audio sia alle cuffie sia a BlackHole.
- Ogni canale ha un'etichetta (`Io` / `Interlocutore`), quindi non serve riconoscere chi parla dalla voce.
- Lo stream gira alla frequenza nativa del dispositivo (di solito 48 kHz); il ricampionamento a 16 kHz si fa una volta per frase, con `scipy.signal.resample_poly`.

### Segmentazione (rilevamento delle frasi)

Rilevatore a energia, scelto perché non richiede modelli né dipendenze in più e basta per due canali puliti:
- frame da 30 ms; i primi 300 ms servono a stimare il rumore di fondo (mediana);
- il rumore si aggiorna di continuo: scende in fretta, sale piano (circa 0,3 dB/s); è limitato tra −70 e −20 dB;
- un frame è voce se supera `max(rumore + margine_db, soglia_min_db)`;
- una frase inizia dopo 3 frame di voce consecutivi (si tengono 300 ms prima, per non tagliare l'attacco) e finisce dopo `silenzio_fine_ms` di silenzio, oppure a `durata_max_s`;
- le frasi con meno di `durata_min_ms` di voce vengono scartate.

### Trascrizione

- `motore = "auto"` usa mlx-whisper (`whisper-large-v3-turbo`) su Apple Silicon, faster-whisper (`small`, int8 su CPU) altrove.
- `lingua = "it"` è fissa: il riconoscimento automatico della lingua su frasi brevi sbaglia spesso.
- `vocabolario` è passato come `initial_prompt` per aiutare Whisper con i termini tecnici.
- `condition_on_previous_text=False` e `temperature=0` evitano ripetizioni e tentativi multipli.
- Un segmento viene scartato se: `no_speech_prob > 0,6` e `avg_logprob < −0,8`; oppure `avg_logprob < −1,5`; oppure `compression_ratio > 2,4`; oppure contiene frasi tipiche delle allucinazioni ("Sottotitoli creati dalla comunità Amara.org" e simili).
- Un solo thread di trascrizione serve entrambi i canali, in ordine di arrivo.

### Quando parte un suggerimento

- **Automatico:** `trigger.sembra_richiesta()` vede almeno 4 parole e uno schema: punto di domanda finale, «come possiamo/facciamo…», «che pattern/approccio/libreria…», «conviene», «secondo te», «è meglio», «fare in modo che», «how should we…» e simili.
- **Attesa:** dopo la domanda si aspettano `attesa_s` secondi, perché spesso la domanda continua nella frase successiva. Ogni nuova frase in quel periodo si aggiunge alla domanda e allunga l'attesa, fino a `attesa_max_s` dalla prima.
- **Pausa minima:** tra due suggerimenti automatici passano almeno `pausa_minima_s` secondi.
- **`solo_interlocutore = true`:** gli automatici partono solo dalle domande degli altri.
- **Su richiesta:** ⌘↩ o "Suggerisci ora" (sul punto in discussione) e la domanda scritta. Annullano un eventuale suggerimento automatico in attesa.
- **Annullamento:** un nuovo suggerimento interrompe quello in corso. Un contatore di generazione impedisce che pezzi di testo del vecchio arrivino nella finestra; quello interrotto finisce nello storico con "(interrotto)".

### Prompt

- Il **prompt di sistema** (`assistente.PROMPT_SISTEMA`) descrive il ruolo (copilota silenzioso in una call tra programmatori), avverte che la trascrizione può storpiare i termini tecnici e fissa il formato: una frase in grassetto, 2-4 punti, snippet di massimo 8 righe se serve, eventuale domanda da fare all'interlocutore, niente preamboli. Se non c'è niente da dire, il modello risponde «—» e la finestra mostra "Nessun suggerimento utile".
- Al prompt di sistema si aggiunge `contesto.md` (stack, preferenze, progetti dell'utente).
- Il **messaggio** contiene la trascrizione recente con orari ed etichette, gli ultimi 3 suggerimenti mostrati (per non ripeterli) e il punto su cui concentrarsi, oppure la domanda scritta dall'utente.

### Claude Code (`AssistenteClaudeCode`)

Comando lanciato:

```
claude -p --input-format stream-json --output-format stream-json --verbose --include-partial-messages
       --system-prompt-file <tmp>/sistema.txt --tools "" --disallowedTools "mcp__*" --model <modello>
       [--safe-mode] [--strict-mcp-config] [--disable-slash-commands] [--no-session-persistence] [--effort low]
```

- **Abbonamento:** `ANTHROPIC_API_KEY` e `ANTHROPIC_AUTH_TOKEN` vengono tolte dall'ambiente del processo figlio, così Claude Code usa l'accesso del piano. Non si usa `--bare`, perché in quella modalità Claude Code non legge l'accesso dell'abbonamento.
- **Avvio leggero:** nessuno strumento, nessun server MCP, nessun comando; con `--safe-mode` niente plugin, hook, CLAUDE.md o memoria. Il processo gira in una cartella temporanea vuota.
- **Opzioni facoltative:** quelle tra parentesi quadre vengono tolte automaticamente se la versione installata di Claude Code non le riconosce ("unknown option"), e la richiesta viene ripetuta.
- **Processo sempre pronto:** si avvia un processo `claude` in anticipo e lo si tiene in attesa su stdin. Quando serve un suggerimento gli si scrive una riga JSON (`{"type":"user","message":{"role":"user","content":…}}`), si leggono gli eventi `stream_event` / `text_delta` fino al `result`, poi si chiude stdin. Intanto si avvia già il processo per il suggerimento successivo. Ogni suggerimento è quindi una conversazione nuova, senza contesto che si accumula.
- **Due modelli:** un assistente (con il suo processo pronto) per gli automatici e uno per le richieste manuali. Se il modello è lo stesso, l'assistente è condiviso.
- **Errori:** se manca l'accesso o Claude Code non viene trovato, la finestra mostra un messaggio con cosa fare.

Con `motore = "api"` si usa invece l'SDK `anthropic` (streaming, prompt di sistema in cache) con la chiave `ANTHROPIC_API_KEY`.

### Finestra

- PySide6, `WindowStaysOnTopHint`. Non è una finestra di tipo "Tool", perché su macOS quelle si nascondono quando l'app perde il focus.
- Tenta di escludersi dalla condivisione schermo con `NSWindow.sharingType = none` (via PyObjC). Non tutte le app di videoconferenza lo rispettano: va verificato.
- Mostra il suggerimento in corso più gli ultimi 5, il più recente in alto; l'intestazione indica il motivo e il modello ("Domanda rilevata · Haiku").

## Tempi misurati

Misure fatte il 16/11/2026 sul MacBook Pro (Apple Silicon) con `./avvia.sh --prova-claude`, motore `claude-code`, sforzo `low`:

| Modello | Avvio a freddo: primo testo / completo | Processo già pronto: primo testo / completo |
|---|---|---|
| Sonnet 5.5 | 4,0 s / 7,6 s | 2,6 s / 6,3 s |
| Haiku 5.5 | 1,1 s / 4,2 s | 0,8 s / 3,6 s |

Prima che il messaggio parta verso Claude si aggiungono `silenzio_fine_ms` (0,55 s), la trascrizione Whisper (non ancora misurata a parte; su Apple Silicon dovrebbe essere sotto il secondo per una frase) e `attesa_s` (0,6 s). Con Haiku, quindi, il suggerimento automatico dovrebbe comparire in circa 2-3 secondi dalla fine della domanda. È una stima, da misurare in una call vera.

Con Sonnet 5.5 e Haiku 5.5 il ragionamento interno non si può disattivare: per ridurre i tempi si agisce su `--effort` (sforzo) e sulla scelta del modello.

## Registro delle decisioni

| Decisione | Motivo | Alternative considerate |
|---|---|---|
| Cattura locale (microfono + BlackHole) | Funziona con qualunque app di call, nessun bot nella riunione, l'audio resta sul Mac | Bot che entra nella call (Recall.ai); Google Meet Media API (in anteprima, richiede che tutti i partecipanti siano iscritti al programma) |
| BlackHole invece di ScreenCaptureKit o Core Audio taps | Funziona subito da Python con `sounddevice`, senza codice Swift né permessi di registrazione schermo | Un helper Swift con ScreenCaptureKit o i process tap di macOS 14.2+: evita il driver e il dispositivo a uscita multipla, possibile miglioramento futuro |
| Whisper locale | Privacy (l'audio non esce) e nessun costo | Servizi cloud in streaming (Deepgram, AssemblyAI): più veloci sulle frasi lunghe, ma l'audio esce dal Mac |
| Rilevatore di voce a energia | Zero dipendenze, sufficiente con due canali separati | Silero VAD (più robusto al rumore, richiede onnxruntime o torch) |
| Domande riconosciute con espressioni regolari | Immediato e gratuito: Claude viene chiamato solo quando serve | Far decidere a un modello su ogni frase: più preciso, ma più costoso e rumoroso |
| `claude -p` con l'abbonamento | Richiesta dell'utente: niente chiave API né costi a parte | API (rimane disponibile con `motore = "api"`); modello locale con Ollama (tutto offline, qualità inferiore) |
| Processo `claude` sempre pronto | Toglie circa 1,4 s di avvio a ogni suggerimento | Una sessione unica per tutta la call: contesto che cresce e risposte influenzate dalle precedenti |
| Haiku per gli automatici, Sonnet su richiesta | Haiku: 0,8 s al primo testo; Sonnet ragiona meglio quando è l'utente a chiedere | Un solo modello per tutto |
| Tempi di attesa 550 ms / 0,6 s / 2,5 s | Reattività; prima erano 700 ms / 1,5 s / 4 s | Se le domande vengono spezzate, alzare `attesa_s` a 1,0 |

## Limiti noti

- La condivisione dell'intero schermo potrebbe mostrare la finestra: verificare con la propria app di call.
- Con gli altoparlanti invece delle cuffie, il microfono sente anche gli altri e la trascrizione si duplica.
- Il dispositivo a uscita multipla disattiva i tasti del volume del Mac finché è selezionato come uscita di sistema.
- Le espressioni regolari possono perdere domande formulate in modo insolito (rimedio: ⌘↩) o scattare su frasi retoriche (mitigato dalla pausa minima e dalla risposta «—»).
- Whisper può storpiare i nomi di librerie poco comuni: aggiungerli a `vocabolario`.
- Ogni suggerimento consuma un po' dei limiti di utilizzo del piano Claude.

## Possibili sviluppi

- Helper Swift con ScreenCaptureKit o i process tap per catturare l'audio della call senza BlackHole.
- Silero VAD al posto del rilevatore a energia, per ambienti rumorosi.
- Scorciatoia globale (fuori dalla finestra) per "Suggerisci ora".
- Riassunto della call a fine riunione, con le decisioni prese e le cose da fare (opzionale, con consenso).
- Profili di contesto diversi per cliente o progetto (`contesto-<cliente>.md`).

## Test

```bash
.venv/bin/python tests/esegui.py
```

I test non usano né audio vero né Claude vero:
- `test_logica.py`: segmentazione su audio sintetico, ricampionamento, filtro delle allucinazioni, trigger, scelta dei modelli, motore con un client API finto (attesa, pausa minima, contenuto dei messaggi);
- `test_claude_code.py`: `AssistenteClaudeCode` con `tests/claude_finto.py` (streaming, opzione sconosciuta, errore di accesso, annullamento, processo pronto riusato, due modelli).

Per una prova end-to-end: `./avvia.sh --prova-claude`, poi `./avvia.sh` con un video YouTube in riproduzione.
