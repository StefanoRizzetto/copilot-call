"""Riconosce le frasi che meritano un suggerimento (domande e decisioni tecniche)."""
from __future__ import annotations

import re

_SCHEMI = [
    r"\?\s*$",
    r"\bcome\s+(possiamo|potremmo|posso|potrei|facciamo|faremmo|faccio|si\s+fa|gestiamo|gestiresti|"
    r"risolviamo|implementiamo|implementeresti|strutturiamo|organizziamo|evitiamo|testiamo)\b",
    r"\b(che|quale|quali)\s+(pattern|approcci?o?|librerie|libreria|framework|strategia|architettura|"
    r"soluzioni|soluzione|tecnologia|database|db|struttura|tool|strumento)\b",
    r"\bconv(iene|errebbe|engono)\b",
    r"\bsecondo\s+te\b",
    r"\bcosa\s+ne\s+pens\w*",
    r"\b(è|sarebbe)\s+meglio\b",
    r"\bin\s+che\s+modo\b",
    r"\bfare\s+in\s+modo\s+che\b",
    r"\bnon\s+(so|sappiamo|sapevo)\s+(come|se|quale|perch[eé])\b",
    r"\bqual\s*['’]?\s*è\s+(il|la)\s+(modo|differenza|soluzione)\b",
    r"\b(best\s+practice|trade[\s-]?off)\b",
    r"\bhow\s+(do|can|could|should|would)\s+(we|i|you)\b",
    r"\bshould\s+we\b",
    r"\bwhat['’]?s\s+the\s+best\b",
    r"\bwhich\s+(pattern|approach|library|framework)\b",
]
_RE = [re.compile(s, re.IGNORECASE) for s in _SCHEMI]


def sembra_richiesta(testo: str) -> bool:
    t = testo.strip()
    if len(t.split()) < 4:
        return False
    return any(r.search(t) for r in _RE)
