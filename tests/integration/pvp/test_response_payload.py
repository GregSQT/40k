"""Contrat d'ENCODAGE des réponses PvP : voie rapide ``orjson``, rien d'interne dans le payload.

Ces invariants ne se voient dans AUCUN test fonctionnel : le repli ``make_json_serializable``
produit exactement le même JSON que ``orjson`` — seulement ~50 fois plus lentement — et une clé
moteur en trop dans la réponse ne casse rien côté client, elle la charge. Les deux se dégradent
donc en silence, et c'est ce qui s'est produit (mesure du 2026-07-30 : 61 réponses sur 61 d'une
partie ``pvp_test`` partaient dans le repli, 555 Ko sur 1,07 Mo de payload étaient des caches
moteur à préfixe ``_`` que le front ne lit pas).

Le déclencheur était minuscule et invisible : ``game_state["victory_points"] == {1: 0, 2: 0}``.
``orjson`` refuse une clé non-``str``, et ce refus n'est pas local — il fait retomber la réponse
ENTIÈRE sur le pré-parcours récursif Python.

UNE SEULE PARTIE pour les trois contrats : ils s'observent tous sur les mêmes réponses, et rejouer
la partie trois fois coûtait 40 s de suite pour une couverture identique.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

import services.api_server as api_server

pytestmark = pytest.mark.integration

# Verbe d'activation propre à chaque phase : le dispatch de tir REFUSE ``activate_unit`` (chemin
# squad attendu). Les phases absentes de cette table sont jouées en nominal.
_ACTIVATION_VERB = {
    "move": "activate_unit",
    "shoot": "squad_shoot_activate",
    "charge": "activate_unit",
}

# Charge : jet 2D6 forcé au maximum. Sans override, la charge rate le plus souvent et
# ``valid_charge_dest_distances`` (dict à clés tuple) reste vide — le contrôle passerait au vert
# sans jamais avoir vu la structure qu'il est là pour surveiller.
_ACTIVATION_EXTRA = {"charge": {"charge_roll_override": 12}}

# Plafond par phase. Une activation de tir déclenche la LoS par-figurine de tout le squad, une
# activation de charge un BFS de 12" par figurine : ~0,5 s pièce sur le plateau 44x60. Une seule
# suffit à faire naître les structures surveillées ici ; en activer toute la phase coûtait 27 s.
_MAX_ACTIVATIONS_PER_PHASE = {"shoot": 1, "charge": 1}


@pytest.fixture
def payload_probe(monkeypatch) -> List[Dict[str, Any]]:
    """Capture les charges envoyées à l'encodeur ET fait échouer tout recours au repli.

    Le repli n'est pas supprimé (il reste le filet des types exotiques), il est rendu BRUYANT le
    temps du test : sur une partie PvP normale, il n'a pas à être atteint.
    """
    seen: List[Dict[str, Any]] = []
    original = api_server.api_json_response_with_size

    def _spy(payload: Dict[str, Any]):
        seen.append(payload)
        return original(payload)

    def _forbidden(_obj: Any, *_args: Any, **_kwargs: Any):
        raise AssertionError(
            "réponse encodée via le repli make_json_serializable : orjson a refusé le payload "
            "(clé non-str ou type exotique). C'est ~50x plus lent, sur CHAQUE réponse."
        )

    monkeypatch.setattr(api_server, "api_json_response_with_size", _spy)
    monkeypatch.setattr(api_server, "make_json_serializable", _forbidden)
    return seen


def _play_including_activations(game) -> None:
    """Un tour joué en ACTIVANT une unité dans chaque phase qui le permet.

    Enchaîner des ``skip`` ne suffit pas : les structures les plus exotiques du payload
    (``valid_move_destinations_pool_by_level``, indexé par étage) ne naissent qu'à l'activation
    d'une unité. Un échantillon de phases skippées est un échantillon qui ne regarde pas — la
    première version de ce test passait au vert en ratant ce dict-là.
    """
    by_phase: Dict[str, int] = {}
    for _ in range(400):
        if game.state.get("game_over") or int(game.state["turn"]) >= 2:
            break
        phase = game.phase
        verb = _ACTIVATION_VERB.get(phase)
        pool_key = game.POOL_BY_PHASE.get(phase)
        budget = _MAX_ACTIVATIONS_PER_PHASE.get(phase)
        budget_left = budget is None or by_phase.get(phase, 0) < budget
        if verb is not None and pool_key is not None and budget_left and game.pool(pool_key):
            game.act(verb, unitId=game.pool(pool_key)[0], **_ACTIVATION_EXTRA.get(phase, {}))
            by_phase[phase] = by_phase.get(phase, 0) + 1
        action, payload = game.nominal_action()
        game.act(action, **payload)
    missing = sorted(set(_ACTIVATION_VERB) - set(by_phase))
    assert not missing, f"aucune activation en phase {missing} : ces phases ne sont pas regardées"


def test_pvp_responses_stay_on_the_fast_encoder_and_carry_no_engine_internals(
    payload_probe, game
) -> None:
    """Trois contrats sur une même partie : voie rapide, rien d'interne, clés entières en ``str``.

    Le pire cas est en cours de partie, pas au ``/start`` : les caches (LoS par tireur, cartes de
    cellules, champs géodésiques) naissent à la première activation. On joue donc avant d'observer.
    """
    _play_including_activations(game)

    # 1. Voie rapide — assuré par ``payload_probe`` : le repli lève. Rien à asserter ici.
    states = [p["game_state"] for p in payload_probe if isinstance(p.get("game_state"), dict)]
    assert len(states) >= 10, f"échantillon vide ou trop maigre : {len(states)} réponses"

    # 2. Aucune donnée moteur interne dans le game_state renvoyé.
    internal = sorted({k for s in states for k in s if k.startswith("_")})
    assert not internal, f"caches moteur envoyés au client : {internal}"
    for forbidden in ("terrain_areas", "unit_by_id", "wall_hexes", "config",
                      "valid_charge_dest_distances"):
        carriers = [k for s in states for k in s if k == forbidden]
        assert not carriers, f"{forbidden!r} envoyé au client dans {len(carriers)} réponse(s)"

    # 3. Aucun dict de premier niveau à clés non-``str``. Vérifié sur la charge AVANT encodage —
    #    après, JSON aurait de toute façon converti, et le contrôle ne regarderait plus rien.
    for state in states:
        for key, value in state.items():
            if not isinstance(value, dict):
                continue
            bad = [k for k in value if not isinstance(k, str)]
            assert not bad, f"game_state[{key!r}] a des clés non-str : {bad[:8]}"

    # Garde anti-vert-vacant : les structures exotiques doivent AVOIR été traversées. Sans elles,
    # les deux contrôles ci-dessus passent sur un état trop pauvre pour rien prouver.
    witnesses = ("victory_points", "valid_move_destinations_pool_by_level")
    for witness in witnesses:
        assert any(isinstance(s.get(witness), dict) and s[witness] for s in states), (
            f"{witness!r} jamais observé non vide : l'échantillon ne contient pas la structure "
            f"dont ce test surveille la normalisation"
        )
