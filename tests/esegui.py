"""Esegue tutti i test senza dipendenze extra: .venv/bin/python tests/esegui.py"""
import importlib
import sys
import traceback
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RADICE))


def main():
    falliti = 0
    totali = 0
    for file in sorted((RADICE / "tests").glob("test_*.py")):
        modulo = importlib.import_module(f"tests.{file.stem}")
        for nome in sorted(n for n in dir(modulo) if n.startswith("test_")):
            totali += 1
            try:
                getattr(modulo, nome)()
                print(f"ok      {file.stem}.{nome}")
            except Exception:  # noqa: BLE001
                falliti += 1
                print(f"FALLITO {file.stem}.{nome}")
                traceback.print_exc()
    print(f"\n{totali - falliti}/{totali} test superati")
    sys.exit(1 if falliti else 0)


if __name__ == "__main__":
    main()
