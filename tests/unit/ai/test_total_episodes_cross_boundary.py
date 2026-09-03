"""Verrou : total_episodes d'une etape curriculum doit traverser la frontiere forkserver.

Un override de total_episodes est pose dans le processus PARENT (via _apply_stage_hp_overrides
qui mute training_config["total_episodes"]). Mais un worker vectorise demarre en forkserver/spawn,
reimporte tout et relit le profil via config_loader NON decore — il voit donc la valeur du JSON,
pas celle de l'etape. Seul un argument passe a make_training_env -> W40KEngine franchit cette
frontiere.

Ce que ces tests separent :
  - Le diagnostic : le worker lit bien le JSON sans intervention (le probleme existe).
  - Le verrou moteur (W40KEngine(training_total_episodes=X)) vit dans
    tests/unit/engine/test_deployment_mode_schedule.py, qui possede deja les fixtures
    necessaires et le contrat total_episodes.
"""

import multiprocessing as mp

import pytest

AGENT = "ArmageddonAgent_x1"
# Valeur attendue du profil x1_long dans le JSON (verifiee par test_deployment_mode_schedule.py).
X1_LONG_JSON_TOTAL_EPISODES = 100_000


# ── Fonction cible forkserver (niveau module pour etre picklable) ────────────

def _read_total_episodes_in_child(queue) -> None:
    """Relit le profil dans le processus enfant, sans aucun patch parent."""
    from config_loader import get_config_loader

    cfg = get_config_loader().load_agent_training_config(AGENT, "x1_long")
    queue.put(cfg.get("total_episodes"))


# ── Tests ────────────────────────────────────────────────────────────────────

def test_forkserver_child_reads_json_total_episodes() -> None:
    """Constat : le worker voit la valeur JSON, pas un override in-process.

    Ce test DOIT rester vert. Si le child voyait un override in-process, cela voudrait dire
    qu'une mutation de dict se propage aux workers — ce qui est impossible avec forkserver/spawn
    et invaliderait la raison d'etre du passage en argument.
    """
    if "forkserver" not in mp.get_all_start_methods():
        pytest.skip("forkserver indisponible sur cette plateforme")

    ctx = mp.get_context("forkserver")
    queue = ctx.Queue()
    proc = ctx.Process(target=_read_total_episodes_in_child, args=(queue,))
    proc.start()
    proc.join(timeout=120)
    if proc.exitcode is None:
        proc.kill()
        proc.join()
        pytest.fail("le worker n'a pas termine dans le delai imparti (120s)")
    assert proc.exitcode == 0, "le worker n'a pas pu lire la config"
    assert queue.get(timeout=10) == X1_LONG_JSON_TOTAL_EPISODES, (
        "le worker ne lit pas la valeur JSON attendue : le profil x1_long a change, "
        f"mettre a jour X1_LONG_JSON_TOTAL_EPISODES (attendu {X1_LONG_JSON_TOTAL_EPISODES})."
    )
