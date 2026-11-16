#!/usr/bin/env python3
"""Finto 'claude' per i test: risponde come 'claude -p --input-format/--output-format stream-json'.

Il comportamento si sceglie con la variabile FAKE_MODO: ok | opzione | login | lento.
"""
import base64
import json
import os
import sys
import time

args = sys.argv[1:]
modo = os.environ.get("FAKE_MODO", "ok")
if modo == "opzione" and "--safe-mode" in args:
    print("error: unknown option '--safe-mode'", file=sys.stderr)
    sys.exit(1)

contenuto = json.loads(sys.stdin.readline())["message"]["content"]
immagine = isinstance(contenuto, list)
if immagine:  # screenshot: blocco image in base64 seguito dal testo
    img = [b for b in contenuto if b.get("type") == "image"]
    testo = [b for b in contenuto if b.get("type") == "text"]
    assert img and testo and img[0]["source"]["type"] == "base64", contenuto
    base64.b64decode(img[0]["source"]["data"], validate=True)
assert "--input-format" in args
assert "--system-prompt-file" in args and args[args.index("--tools") + 1] == ""
assert "ANTHROPIC_API_KEY" not in os.environ, "la chiave API deve essere tolta dall'ambiente"

print(json.dumps({"type": "system", "subtype": "init", "model": "finto"}), flush=True)
if modo == "login":
    print(json.dumps({"type": "result", "subtype": "success", "is_error": True,
                      "result": "Not logged in · Please run /login"}))
    sys.exit(1)

pezzi = ["**Usa il transactional ", "outbox pattern.**\n", "- scrivi l'evento in una tabella outbox\n"]
if immagine:
    pezzi = ["Vedo lo schermo. "] + pezzi
if modo == "lento":
    pezzi *= 20
for p in pezzi:
    evento = {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": p}}
    print(json.dumps({"type": "stream_event", "event": evento}), flush=True)
    time.sleep(0.2 if modo == "lento" else 0.05)
print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "".join(pezzi)}))
