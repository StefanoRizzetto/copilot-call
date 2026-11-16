#!/usr/bin/env python3
"""Finto 'claude' per i test: risponde come 'claude -p --input-format/--output-format stream-json'.

Il comportamento si sceglie con la variabile FAKE_MODO: ok | opzione | login | lento.
"""
import json
import os
import sys
import time

args = sys.argv[1:]
modo = os.environ.get("FAKE_MODO", "ok")
if modo == "opzione" and "--safe-mode" in args:
    print("error: unknown option '--safe-mode'", file=sys.stderr)
    sys.exit(1)

messaggio = json.loads(sys.stdin.readline())["message"]["content"]
assert "--input-format" in args
assert "--system-prompt-file" in args and args[args.index("--tools") + 1] == ""
assert "ANTHROPIC_API_KEY" not in os.environ, "la chiave API deve essere tolta dall'ambiente"

print(json.dumps({"type": "system", "subtype": "init", "model": "finto"}), flush=True)
if modo == "login":
    print(json.dumps({"type": "result", "subtype": "success", "is_error": True,
                      "result": "Not logged in · Please run /login"}))
    sys.exit(1)

pezzi = ["**Usa il transactional ", "outbox pattern.**\n", "- scrivi l'evento in una tabella outbox\n"]
if modo == "lento":
    pezzi *= 20
for p in pezzi:
    evento = {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": p}}
    print(json.dumps({"type": "stream_event", "event": evento}), flush=True)
    time.sleep(0.2 if modo == "lento" else 0.05)
print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "".join(pezzi)}))
