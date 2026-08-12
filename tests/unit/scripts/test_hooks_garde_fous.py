"""Verrou des deux hooks de .claude/hooks/.

Ces hooks portent des règles qui vivaient auparavant dans CLAUDE.md sous forme de texte, donc
sans exécution : présence des sections du rapport de clôture, disposition du bloc RELIRE, refus
de la vérification large. Un hook muet est indistinguable d'un hook conforme — d'où ce fichier.

Les cas PASSANTS comptent autant que les cas bloquants : un hook qui bloque tout piège la session
aussi sûrement qu'un hook qui ne bloque rien laisse passer les défauts.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[3] / ".claude" / "hooks"
H_STOP = HOOKS / "rapport-cloture.sh"
H_DENY = HOOKS / "deny-verif-large.sh"

RAPPORT_CONFORME = """Fait.

LU : engine/x.py en entier, ses 3 appelants
JUMEAU : grep -rn "foo" engine/ -> 2 hits, 2 traites
RELIRE :
/code-review engine/x.py
/simplify engine/x.py
"""

WORKTREE_FILE = "/home/greg/40k/.claude/worktrees/sujet/engine/x.py"


# --------------------------------------------------------------------------- outils de transcript


def _user(text: str) -> dict:
    return {"type": "user", "message": {"role": "user", "content": text}}


def _tool_result() -> dict:
    """Un retour d'outil s'écrit `type: user` — il ne doit PAS compter comme un prompt."""
    return {
        "type": "user",
        "message": {"role": "user", "content": [{"type": "tool_result", "content": "ok"}]},
    }


def _edit(path: str, *, sidechain: bool = False) -> dict:
    entry = {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [{"type": "tool_use", "name": "Edit", "input": {"file_path": path}}],
        },
    }
    if sidechain:
        entry["isSidechain"] = True
    return entry


def _say(text: str) -> dict:
    return {
        "type": "assistant",
        "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
    }


def _appel(tmp_path: Path, entries: tuple[dict, ...], payload: dict) -> dict | None:
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")
    proc = subprocess.run(
        [str(H_STOP)],
        input=json.dumps({"transcript_path": str(transcript), **payload}),
        capture_output=True,
        text=True,
        check=True,
        # Le hook attend l'écriture asynchrone du message final ; ici les transcripts sont déjà
        # complets, donc l'attente n'aurait rien à attendre.
        env={**os.environ, "RAPPORT_CLOTURE_ATTENTE_MS": "0"},
    )
    return json.loads(proc.stdout) if proc.stdout.strip() else None


def _run_stop(tmp_path: Path, *entries: dict, active: bool = False) -> dict | None:
    """Verdict du hook Stop : le dict bloquant, ou None s'il laisse finir."""
    return _appel(tmp_path, entries, {"hook_event_name": "Stop", "stop_hook_active": active})


def _run_prompt(tmp_path: Path, *entries: dict) -> str | None:
    """Contexte injecté par le chemin de rattrapage UserPromptSubmit, ou None s'il se tait."""
    out = _appel(tmp_path, entries, {"hook_event_name": "UserPromptSubmit", "prompt": "suite"})
    return out["hookSpecificOutput"]["additionalContext"] if out else None


def _run_deny(command: str) -> dict | None:
    """Verdict du hook PreToolUse : le dict de refus, ou None si la commande passe."""
    proc = subprocess.run(
        [str(H_DENY)],
        input=json.dumps({"tool_input": {"command": command}}),
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(proc.stdout) if proc.stdout.strip() else None


# ------------------------------------------------------------------------------------- hook Stop


def test_tour_sans_modification_ne_reclame_rien(tmp_path: Path) -> None:
    assert _run_stop(tmp_path, _user("explique-moi ça"), _say("voilà.")) is None


def test_rapport_conforme_laisse_finir(tmp_path: Path) -> None:
    assert (
        _run_stop(tmp_path, _user("corrige"), _edit("engine/x.py"), _tool_result(),
                  _say(RAPPORT_CONFORME))
        is None
    )


def test_rapport_absent_bloque_en_nommant_chaque_section(tmp_path: Path) -> None:
    verdict = _run_stop(tmp_path, _user("corrige"), _edit("engine/x.py"), _tool_result(),
                        _say("c'est corrigé."))
    assert verdict is not None and verdict["decision"] == "block"
    for section in ("LU", "JUMEAU", "RELIRE"):
        assert section in verdict["reason"]


def test_stop_hook_active_ne_reboucle_jamais(tmp_path: Path) -> None:
    """Sans ce garde-fou, un rapport que l'agent refuse de compléter piège la session."""
    assert (
        _run_stop(tmp_path, _user("corrige"), _edit("engine/x.py"), _say("fait."), active=True)
        is None
    )


def test_etiquette_relire_doit_etre_seule_sur_sa_ligne(tmp_path: Path) -> None:
    colle = RAPPORT_CONFORME.replace("RELIRE :\n/code-review", "RELIRE : /code-review")
    verdict = _run_stop(tmp_path, _user("corrige"), _edit("engine/x.py"), _say(colle))
    assert verdict is not None and "SEULE sur sa ligne" in verdict["reason"]


@pytest.mark.parametrize("manquante", ["/code-review", "/simplify"])
def test_les_deux_commandes_de_relecture_sont_exigees(tmp_path: Path, manquante: str) -> None:
    ampute = "\n".join(
        ln for ln in RAPPORT_CONFORME.splitlines() if not ln.startswith(manquante)
    )
    verdict = _run_stop(tmp_path, _user("corrige"), _edit("engine/x.py"), _say(ampute))
    assert verdict is not None and manquante in verdict["reason"]


def test_worktree_exige_des_chemins_absolus(tmp_path: Path) -> None:
    """Défaut mesuré le 2026-08-08 : une review entière rendue sur le dépôt principal."""
    verdict = _run_stop(tmp_path, _user("corrige"), _edit(WORKTREE_FILE),
                        _say(RAPPORT_CONFORME))
    assert verdict is not None and "ABSOLUS" in verdict["reason"]


def test_worktree_avec_chemins_absolus_passe(tmp_path: Path) -> None:
    absolu = RAPPORT_CONFORME.replace("engine/x.py", WORKTREE_FILE)
    assert _run_stop(tmp_path, _user("corrige"), _edit(WORKTREE_FILE), _say(absolu)) is None


def test_modification_de_doc_seule_n_exige_pas_relire(tmp_path: Path) -> None:
    doc = "Fait.\n\nLU : CLAUDE.md en entier\nJUMEAU : grep -c foo -> 0 hit\n"
    assert _run_stop(tmp_path, _user("corrige la doc"), _edit("Documentation/x.md"),
                     _say(doc)) is None


def test_modification_de_doc_exige_quand_meme_lu_et_jumeau(tmp_path: Path) -> None:
    assert _run_stop(tmp_path, _user("corrige la doc"), _edit("Documentation/x.md"),
                     _say("fait.")) is not None


def test_edition_d_un_sous_agent_n_engage_pas_le_rapport(tmp_path: Path) -> None:
    assert _run_stop(tmp_path, _user("cherche"), _edit("engine/x.py", sidechain=True),
                     _say("rien trouvé.")) is None


def test_un_nouveau_prompt_remet_le_compteur_a_zero(tmp_path: Path) -> None:
    assert (
        _run_stop(tmp_path, _user("q1"), _edit("engine/x.py"), _say(RAPPORT_CONFORME),
                  _user("q2"), _say("juste une réponse"))
        is None
    )


def test_un_retour_d_outil_ne_passe_pas_pour_un_nouveau_tour(tmp_path: Path) -> None:
    assert (
        _run_stop(tmp_path, _user("corrige"), _edit("engine/x.py"), _tool_result(),
                  _edit("engine/y.py"), _tool_result(), _say("fait."))
        is not None
    )


def test_message_final_pas_encore_ecrit_ne_declenche_aucune_accusation(tmp_path: Path) -> None:
    """Le transcript est écrit de façon ASYNCHRONE — mesuré le 2026-08-12.

    À l'instant du Stop, le dernier message de l'assistant n'y figure pas encore. La première
    version de ce hook en concluait « aucun rapport » et bloquait TOUS les tours conformes : un
    contrôle qui regarde la mauvaise chose. Le tour est repris par le chemin UserPromptSubmit,
    quand le transcript est complet.
    """
    assert _run_stop(tmp_path, _user("corrige"), _edit("engine/x.py")) is None


# ------------------------------------------------------------- rattrapage UserPromptSubmit


def test_rattrapage_signale_le_tour_precedent_sans_rapport(tmp_path: Path) -> None:
    contexte = _run_prompt(tmp_path, _user("corrige"), _edit("engine/x.py"), _say("c'est fait."))
    assert contexte is not None and "PRÉCÉDENT" in contexte
    for section in ("LU", "JUMEAU", "RELIRE"):
        assert section in contexte


def test_rattrapage_muet_quand_le_tour_precedent_etait_conforme(tmp_path: Path) -> None:
    assert (
        _run_prompt(tmp_path, _user("corrige"), _edit("engine/x.py"), _say(RAPPORT_CONFORME))
        is None
    )


def test_rattrapage_muet_quand_le_tour_precedent_n_a_rien_modifie(tmp_path: Path) -> None:
    assert _run_prompt(tmp_path, _user("explique"), _say("voilà.")) is None


def test_rattrapage_ignore_le_tour_vide_du_prompt_qui_vient_d_arriver(tmp_path: Path) -> None:
    """Le prompt soumis peut déjà figurer au transcript : le tour à juger est le dernier NON vide."""
    contexte = _run_prompt(
        tmp_path, _user("corrige"), _edit("engine/x.py"), _say("c'est fait."), _user("et ensuite ?")
    )
    assert contexte is not None and "PRÉCÉDENT" in contexte


# -------------------------------------------------------------------------------- hook PreToolUse


@pytest.mark.parametrize(
    "command",
    [
        "python3 -m pytest tests/unit/ -q -n 8 --dist worksteal",
        "source .venv/bin/activate && python3 -m pytest tests/",
        "pytest",
        "pyright",
        "npx biome check frontend/src",
        "(cd frontend && npx tsc --noEmit -p tsconfig.app.json)",
        "p ai/hidden_action_finder.py",
        "python3 scripts/check_ai_rules.py",
    ],
)
def test_verification_large_refusee(command: str) -> None:
    verdict = _run_deny(command)
    assert verdict is not None
    decision = verdict["hookSpecificOutput"]["permissionDecision"]
    assert decision == "deny"


@pytest.mark.parametrize(
    "command",
    [
        "pytest tests/unit/engine/test_x.py",
        "source .venv/bin/activate && pytest tests/unit/ai/test_y.py -q",
        "pyright engine/x.py",
        "npx biome check frontend/src/utils/replayParser.ts",
        "python3 ai/train.py --agent CoreAgent --scenario bot --step",
        "grep -rn foo engine/",
        "git status --short",
        # Délégation ponctuelle : le marqueur ouvre la porte, et lui seul.
        "python3 -m pytest tests/unit/ -q -n 8  # VERIF-LARGE-AUTORISEE",
        "pyright  # VERIF-LARGE-AUTORISEE",
    ],
)
def test_verification_ciblee_et_delegation_passent(command: str) -> None:
    assert _run_deny(command) is None
