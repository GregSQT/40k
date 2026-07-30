"""Mode de verification par recalcul de la carte de cellules (`engine.mask_verification`).

Ce que ces tests verrouillent, dans l'ordre d'importance :

1. Le controle DETECTE une divergence que le tampon (ancre, phase) laisse passer. Sans cette
   preuve, un controle qui ne discrimine rien afficherait « tout va bien » — le pire des
   resultats, parce qu'il inspire confiance.
2. Le controle N'ALTERE PAS ce qu'il observe. Recalculer le masque reecrit la carte memoisee et
   peut tirer le jet d'Advance : recalculer sur l'etat vivant ecraserait la preuve cherchee et
   changerait ce que le decodage executerait ensuite.
3. Desarme (cas de production), il est strictement inerte.
"""

import copy
import os
import pathlib
from typing import Any, Dict, Tuple

import pytest

from engine import mask_verification
from engine.mask_verification import mask_verification_enabled, verify_memoised_move_cell_map

#: Racine du depot — les tests en sous-processus importent le paquet depuis la.
_REPO_ROOT = str(pathlib.Path(__file__).resolve().parents[3])

CellMap = Dict[int, Tuple[Tuple[int, int], float]]

_MEMOISED: CellMap = {10: ((6, 6), 3.0), 20: ((7, 7), 8.0)}


def _game_state(**extra: Any) -> Dict[str, Any]:
    state: Dict[str, Any] = {"config": {}, "phase": "move", "mask_verification": True}
    state.update(extra)
    return state


def _stub_recompute(monkeypatch: pytest.MonkeyPatch, fresh):
    """Remplace le recalcul reel : ces tests portent sur la COMPARAISON, pas sur le masque."""
    seen: list = []

    def _fake(game_state, squad_id):
        seen.append((game_state, squad_id))
        return fresh

    monkeypatch.setattr(mask_verification, "_recompute_move_cell_map", _fake)
    return seen


# ─── Armement ───────────────────────────────────────────────────────────────


def test_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("W40K_MASK_VERIFY", raising=False)
    assert mask_verification_enabled({}) is False
    assert mask_verification_enabled(None) is False


def test_enabled_by_env_or_game_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("W40K_MASK_VERIFY", "1")
    assert mask_verification_enabled({}) is True
    monkeypatch.delenv("W40K_MASK_VERIFY")
    assert mask_verification_enabled({"mask_verification": True}) is True


def test_disarmed_verification_does_not_recompute(monkeypatch: pytest.MonkeyPatch) -> None:
    """En production le controle doit etre STRICTEMENT inerte : aucun recalcul, aucun cout."""
    monkeypatch.delenv("W40K_MASK_VERIFY", raising=False)
    seen = _stub_recompute(monkeypatch, {})
    verify_memoised_move_cell_map({"config": {}}, "1", _MEMOISED)
    assert seen == [], "le recalcul a tourne alors que le mode est desarme"


# ─── Detection (le controle discrimine-t-il vraiment ?) ─────────────────────


def test_identical_map_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_recompute(monkeypatch, dict(_MEMOISED))
    verify_memoised_move_cell_map(_game_state(), "1", _MEMOISED)


def test_detects_a_destination_that_moved(monkeypatch: pytest.MonkeyPatch) -> None:
    """Meme cellule, autre destination : exactement ce qu'un pool perime produit."""
    _stub_recompute(monkeypatch, {10: ((6, 6), 3.0), 20: ((9, 9), 8.0)})
    with pytest.raises(RuntimeError, match=r"divergence masque/execution") as excinfo:
        verify_memoised_move_cell_map(_game_state(), "1", _MEMOISED)
    message = str(excinfo.value)
    assert "cellule 20" in message
    assert "(9, 9)" in message and "(7, 7)" in message


def test_detects_a_cell_that_disappeared(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_recompute(monkeypatch, {10: ((6, 6), 3.0)})
    with pytest.raises(RuntimeError, match=r"disparue"):
        verify_memoised_move_cell_map(_game_state(), "1", _MEMOISED)


def test_detects_a_cell_that_appeared(monkeypatch: pytest.MonkeyPatch) -> None:
    fresh = dict(_MEMOISED)
    fresh[30] = ((8, 8), 2.0)
    _stub_recompute(monkeypatch, fresh)
    with pytest.raises(RuntimeError, match=r"apparue"):
        verify_memoised_move_cell_map(_game_state(), "1", _MEMOISED)


def test_detects_a_pool_that_vanished(monkeypatch: pytest.MonkeyPatch) -> None:
    """Le masque ne produit plus AUCUNE carte : rejouer la memoisee serait le pire cas."""
    _stub_recompute(monkeypatch, None)
    with pytest.raises(RuntimeError, match=r"n'en produit plus aucune"):
        verify_memoised_move_cell_map(_game_state(), "1", _MEMOISED)


# ─── Le controle n'altere pas son objet ─────────────────────────────────────


def test_recompute_never_touches_the_live_state() -> None:
    """Le recalcul REEL doit travailler sur une copie : l'etat vivant sort inchange.

    C'est l'invariant central. Le masque reecrit la carte memoisee et peut tirer le jet
    d'Advance ; recalculer en place ecraserait la carte par la version fraiche, donc le
    controle ne pourrait plus jamais voir de divergence — il serait vert par construction.
    """
    recorded: Dict[str, Any] = {}

    class _Decoder:
        def __init__(self, config):
            _ = config

        def get_squad_action_mask_and_eligible_units(self, game_state):
            # Un masque reel MUTE l'etat qu'il recoit : on reproduit fidelement ces ecritures.
            game_state["_squad_advance_rolls"] = {"1": 6}
            game_state.setdefault("_squad_move_cell_maps", {})["1"] = {
                "anchor": (5, 5), "phase": "move", "map": {10: ((6, 6), 3.0)},
            }
            recorded["received"] = game_state
            return [], []

    import engine.action_decoder as action_decoder

    original = action_decoder.ActionDecoder
    action_decoder.ActionDecoder = _Decoder  # type: ignore[misc]
    try:
        live = _game_state(_squad_advance_rolls={"1": 2}, _squad_move_cell_maps={})
        before = copy.deepcopy(live)
        fresh = mask_verification._recompute_move_cell_map(live, "1")
    finally:
        action_decoder.ActionDecoder = original  # type: ignore[misc]

    assert fresh == {10: ((6, 6), 3.0)}, "le recalcul n'a pas rendu la carte fraiche"
    assert live == before, "le recalcul a modifie l'etat VIVANT au lieu d'une copie"
    assert recorded["received"] is not live, "le masque a recu l'etat vivant, pas une copie"


def test_reentrancy_guard_stops_recursion(monkeypatch: pytest.MonkeyPatch) -> None:
    """Le recalcul rejoue le masque ; s'il atteignait un point de verification, la premiere
    divergence partirait en recursion infinie au lieu d'etre signalee."""
    depth = {"max": 0, "current": 0}

    def _recursive(game_state, squad_id):
        depth["current"] += 1
        depth["max"] = max(depth["max"], depth["current"])
        verify_memoised_move_cell_map(game_state, squad_id, _MEMOISED)
        depth["current"] -= 1
        return dict(_MEMOISED)

    monkeypatch.setattr(mask_verification, "_recompute_move_cell_map", _recursive)
    verify_memoised_move_cell_map(_game_state(), "1", _MEMOISED)
    assert depth["max"] == 1, "le verrou d'anti-reentrance n'a pas tenu"


# ─── Cycle de vie du jet d'Advance (regle 09.06) ────────────────────────────


def test_advance_rolls_cycle_passes_when_none_survived() -> None:
    """Cas nominal : le dict est vide (ou absent) a l'ouverture de la phase move."""
    from engine.mask_verification import verify_advance_rolls_cycle

    verify_advance_rolls_cycle(_game_state())
    verify_advance_rolls_cycle(_game_state(_squad_advance_rolls={}))


def test_advance_rolls_cycle_detects_a_survivor() -> None:
    """Un jet survivant serait REJOUE par l'escouade au tour suivant : le masque ne re-tire
    que si la cle est absente. Aucune erreur ne le signalerait sans ce controle."""
    from engine.mask_verification import verify_advance_rolls_cycle

    state = _game_state(_squad_advance_rolls={"7": 5}, turn=3, current_player=2)
    with pytest.raises(RuntimeError, match=r"survivant\(s\) a l'ouverture d'une phase move") as excinfo:
        verify_advance_rolls_cycle(state)
    message = str(excinfo.value)
    assert "'7': 5" in message
    assert "09.06" in message


def test_advance_rolls_cycle_is_inert_when_disarmed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Desarme (production), un jet survivant ne doit PAS faire echouer la partie."""
    from engine.mask_verification import verify_advance_rolls_cycle

    monkeypatch.delenv("W40K_MASK_VERIFY", raising=False)
    verify_advance_rolls_cycle({"_squad_advance_rolls": {"7": 5}})


# ─── Deux niveaux d'armement ────────────────────────────────────────────────
#
# Les controles de masque TRANSMIS coutent une copie profonde et un recalcul complet par appel,
# et tournent ~315 fois par episode : mesure, ils font passer un run de 2,6 a 55 s par episode.
# Les fondre dans le niveau 1 supprimait en pratique le seul mode de diagnostic utilisable sur un
# run un peu long. Ces tests verrouillent la separation — sans eux, remettre les deux controles
# sur le meme drapeau resterait vert.


def _stub_supplied_recompute(monkeypatch: pytest.MonkeyPatch, mask, eligible):
    """Double du recalcul, avec compteur. Sans lui, un `game_state` minimal fait lever le decodeur
    AVANT la comparaison : le test passerait sur un crash accidentel au lieu du controle vise."""
    import numpy as np

    from engine import mask_verification

    calls = []

    def _fake(_game_state):
        calls.append(True)
        return np.asarray(mask, dtype=bool), eligible

    # Pas de `raising=False` : si ce joint disparait, le test doit ECHOUER, pas se taire.
    monkeypatch.setattr(mask_verification, "_recompute_supplied_mask", _fake)
    return calls


def test_level_one_does_not_run_the_supplied_mask_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """Niveau 1 : le controle du masque transmis ne tourne PAS — aucun recalcul, aucun cout."""
    from engine.mask_verification import verify_supplied_mask

    monkeypatch.setenv("W40K_MASK_VERIFY", "1")
    calls = _stub_supplied_recompute(monkeypatch, [True, True], [{"id": "z"}])
    # Masque volontairement divergent du recalcul : s'il etait compare, l'appel leverait.
    verify_supplied_mask({"config": {}}, [True, False], [{"id": "z"}], "test")
    assert calls == [], "le niveau 1 a declenche le recalcul du masque transmis"


def test_level_two_compares_the_supplied_mask(monkeypatch: pytest.MonkeyPatch) -> None:
    """Niveau 2 : le recalcul TOURNE et la comparaison leve sur un masque divergent.

    Verrou de la comparaison elle-meme, et pas seulement de la porte : le compteur prouve que le
    recalcul a eu lieu, l'exception prouve que son resultat a bien ete compare.
    """
    from engine.mask_verification import verify_supplied_mask

    monkeypatch.setenv("W40K_MASK_VERIFY", "2")
    calls = _stub_supplied_recompute(monkeypatch, [True, True], [{"id": "z"}])
    with pytest.raises(RuntimeError, match="masque transmis perime"):
        verify_supplied_mask({"config": {}}, [True, False], [{"id": "z"}], "test")
    assert calls == [True], "le recalcul n'a pas tourne au niveau 2"


def test_level_two_detects_a_diverging_eligible_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    """Le pool est verifie separement : un masque identique peut cacher un pool qui a change.

    C'est le pool qui designe l'unite activee et l'observateur — une comparaison qui ne
    regarderait que les bits du masque laisserait passer ce cas.
    """
    from engine.mask_verification import verify_supplied_mask

    monkeypatch.setenv("W40K_MASK_VERIFY", "2")
    _stub_supplied_recompute(monkeypatch, [True, False], [{"id": "apres"}])
    with pytest.raises(RuntimeError, match="pool eligible transmis perime"):
        verify_supplied_mask({"config": {}}, [True, False], [{"id": "avant"}], "test")


def test_level_two_accepts_a_matching_mask(monkeypatch: pytest.MonkeyPatch) -> None:
    """Le pendant : un masque et un pool concordants ne doivent PAS lever (sinon tout leverait)."""
    from engine.mask_verification import verify_supplied_mask

    monkeypatch.setenv("W40K_MASK_VERIFY", "2")
    calls = _stub_supplied_recompute(monkeypatch, [True, False], [{"id": "z"}])
    verify_supplied_mask({"config": {}}, [True, False], [{"id": "z"}], "test")
    # Sans cette assertion, le test resterait vert meme si la porte niveau 2 ne s'ouvrait plus
    # (constante remontee, comparaison inversee, retour anticipe) : « ne leve pas » est aussi ce
    # que fait un controle qui ne tourne pas.
    assert calls == [True], "le recalcul n'a pas tourne : le test ne prouve aucune acceptation"


def test_unknown_flag_value_raises_instead_of_disarming(monkeypatch: pytest.MonkeyPatch) -> None:
    """Une valeur mal tapee ne doit PAS desarmer en silence : un run entier serait vert pour rien."""
    from engine.mask_verification import mask_verification_level

    monkeypatch.setenv("W40K_MASK_VERIFY", "ues")
    with pytest.raises(ValueError, match="n'est pas une valeur reconnue"):
        mask_verification_level({})


def test_documented_disarming_values_stay_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Le pendant : les valeurs de desarmement documentees ne doivent pas lever."""
    from engine.mask_verification import mask_verification_level

    for value in ("0", "false", "no", ""):
        monkeypatch.setenv("W40K_MASK_VERIFY", value)
        assert mask_verification_level({}) == 0


def test_game_state_can_arm_level_two_without_an_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    """Le serveur API et les harnais embarques n'ont pas de variable d'environnement a poser.

    `mask_verification: True` valait niveau 1 et PLAFONNAIT la : le niveau 2 leur etait
    structurellement inaccessible, un masque transmis perime serait passe sans bruit alors que
    l'appelant croyait avoir arme la verification.
    """
    from engine.mask_verification import mask_verification_level, verify_supplied_mask

    monkeypatch.delenv("W40K_MASK_VERIFY", raising=False)
    assert mask_verification_level({"mask_verification": True}) == 1
    assert mask_verification_level({"mask_verification": 2}) == 2
    # Forme JSON : c'est par la qu'arrivent les valeurs du serveur API. Ignorer les chaines en
    # silence recreait, sur cette voie, le faux feu vert elimine cote variable d'environnement.
    assert mask_verification_level({"mask_verification": "2"}) == 2
    assert mask_verification_level({"mask_verification": "off"}) == 0
    assert mask_verification_level({"mask_verification": False}) == 0
    # Et une valeur inexploitable leve, au lieu de desarmer sans le dire.
    for bad in (2.0, ["2"], {"niveau": 2}):
        with pytest.raises(ValueError, match="inexploitable|n'est pas une valeur reconnue"):
            mask_verification_level({"mask_verification": bad})

    calls = _stub_supplied_recompute(monkeypatch, [True, True], [{"id": "z"}])
    with pytest.raises(RuntimeError, match="masque transmis perime"):
        verify_supplied_mask(
            {"config": {}, "mask_verification": 2}, [True, False], [{"id": "z"}], "test"
        )
    assert calls == [True]


def test_a_mistyped_flag_fails_at_import_not_mid_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """Une valeur mal tapee doit echouer AU LANCEMENT, pas a la premiere phase de mouvement.

    La valeur n'etait lue que depuis le chemin moteur, par pas de simulation : un run (ou une
    requete API) demarrait normalement puis mourait en cours de partie.

    Teste dans un SOUS-PROCESSUS et non par `importlib.reload` : un reload qui echoue laisse le
    module a moitie re-execute pour tout le reste de la session du worker, et fait echouer des
    fichiers sans rapport avec des erreurs trompeuses. Le sous-processus mesure en plus la vraie
    chose — un demarrage de processus avec ce drapeau — au lieu d'une re-execution en cours de vie.
    """
    import subprocess
    import sys

    # Valeur volontairement absente des DEUX tables (`on` a rejoint les valeurs valides dans le
    # meme lot : un test qui l'utiliserait mesurerait desormais l'inverse de ce qu'il annonce).
    env = dict(os.environ, W40K_MASK_VERIFY="ues")
    result = subprocess.run(
        [sys.executable, "-c", "import engine.mask_verification"],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0, "l'import a reussi malgre une valeur de drapeau invalide"
    assert "n'est pas une valeur reconnue" in result.stderr

    # Le pendant : une valeur de desarmement documentee doit importer SANS broncher. Sans lui, un
    # module qui leverait sur TOUTE valeur passerait le test ci-dessus (`off` a justement casse
    # tous les points d'entree avant d'etre ajoute aux valeurs de desarmement).
    ok = subprocess.run(
        [sys.executable, "-c", "import engine.mask_verification"],
        cwd=_REPO_ROOT,
        env=dict(os.environ, W40K_MASK_VERIFY="off"),
        capture_output=True,
        text=True,
    )
    assert ok.returncode == 0, f"`off` doit desarmer, pas casser le demarrage : {ok.stderr[-400:]}"
