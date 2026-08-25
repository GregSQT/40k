#!/usr/bin/env python3
"""T3 clôture: repli residuel dans la fenetre 4 lignes apres get_unit_by_id."""
import re, sys
from pathlib import Path

FILES = [
    "engine/phase_handlers/shared_utils.py",
    "engine/phase_handlers/fight_handlers.py",
    "engine/phase_handlers/shooting_handlers.py",
    "engine/observation_builder.py",
    "engine/w40k_core.py",
    "engine/phase_handlers/charge_handlers.py",
    "engine/action_decoder.py",
]

CALL_RE = re.compile(r"(?<!require_)(?<!_)get_unit_by_id\s*\(")
GUARD_RE = re.compile(
    r"\b(if\s+not\s+[a-z_]+\b|if\s+[a-z_]+\s+is\s+None\b|if\s+[a-z_]+\s+is\s+not\s+None\b)"
)

hits = []
for fname in FILES:
    p = Path(fname)
    if not p.exists():
        continue
    lines = p.read_text().splitlines()
    for i, line in enumerate(lines):
        if CALL_RE.search(line):
            window = lines[i+1 : i+5]
            for j, wline in enumerate(window):
                if GUARD_RE.search(wline):
                    hits.append((fname, i+1, line.strip(), i+2+j, wline.strip()))

print(f"{len(hits)} hits (4-line window after get_unit_by_id)")
for fname, cln, cline, gln, gline in hits:
    print(f"  {fname}:{cln}  call: {cline[:60]}")
    print(f"  {fname}:{gln}  guard: {gline[:70]}")
    print()
