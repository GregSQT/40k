"""10.02 étape 2 — le type de tir est CHOISI, et le choix est une action de l'agent.

    « Select Shooting Type: Select ONE shooting type that unit is eligible to make, and
      resolve it with that unit. »

Ce fichier verrouille la bascule la plus structurante du chantier : jusqu'au 2026-08-16 le type
de tir était DÉRIVÉ de l'état, et `resolve_squad_shooting_type` justifiait cette dérivation par un
invariant d'exclusivité que 10.07 casse. Le type devient une décision, ce qui touche l'espace
d'action — d'où le ré-entraînement, acté par l'utilisateur avant l'écriture.

Option retenue : **A**, une dimension d'action dédiée. L'option concurrente (déduire le type de la
cible retenue, puisque le tir normal domine sur cible visible) a été écartée pour deux raisons qui
tiennent au long terme : elle reposait sur un fait contingent — aucune datasheet actuelle ne porte
deux armes indirectes — et elle aurait REDÉRIVÉ le type, réintroduisant exactement l'invariant que
les pièces 1-2 démontent, avec en prime une divergence IA/PvP (choix côté humain, déduction côté
agent).
"""
from __future__ import annotations

import pytest

from engine import macro_intents as mi
from engine.phase_handlers import shared_utils as SU
from engine.phase_handlers.shared_utils import (
    SHOOTING_TYPE_INDIRECT,
    SHOOTING_TYPE_NORMAL,
    SQUAD_SHOOTING_TYPE_CHOICE_KEY,
    resolve_squad_shooting_type,
    squad_shooting_type_choose,
    squad_shooting_type_clear,
)


# ─────────────────────────────────────────────────────────────────────────────
# L'état de choix : posé, honoré, validé, effacé
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def eligibles(monkeypatch):
    def _pose(types, defaut=SHOOTING_TYPE_NORMAL):
        monkeypatch.setattr(SU, "eligible_squad_shooting_types", lambda gs, sid: types)
        monkeypatch.setattr(SU, "_derive_squad_shooting_type", lambda gs, sid: defaut)
        return {"units_shot": set()}
    return _pose


def test_le_choix_prime_sur_la_derivation(eligibles):
    """Le cœur de la bascule : une fois choisi, le type n'est plus recalculé.

    La dérivation rendrait `normal` (c'est le défaut) ; le choix dit `indirect`, et c'est lui qui
    doit ressortir partout où le moteur lit le type."""
    gs = eligibles((SHOOTING_TYPE_NORMAL, SHOOTING_TYPE_INDIRECT))

    assert resolve_squad_shooting_type(gs, "1") == SHOOTING_TYPE_NORMAL, "prémisse : le défaut"

    squad_shooting_type_choose(gs, "1", SHOOTING_TYPE_INDIRECT)

    assert resolve_squad_shooting_type(gs, "1") == SHOOTING_TYPE_INDIRECT


def test_un_type_non_eligible_est_refuse(eligibles):
    """10.02 dit « that unit IS ELIGIBLE to make ». Accepter un type non éligible ferait résoudre
    une activation sous des règles qu'elle n'a pas le droit d'appliquer — typiquement un tir
    indirect sans arme indirecte, donc sans ligne de vue et sans plancher. Erreur explicite,
    jamais un repli sur le défaut (T1)."""
    gs = eligibles((SHOOTING_TYPE_NORMAL,))

    with pytest.raises(ValueError, match="non eligible"):
        squad_shooting_type_choose(gs, "1", SHOOTING_TYPE_INDIRECT)


def test_le_choix_est_efface_a_la_fin_de_l_activation(eligibles):
    """Sans effacement, une activation ULTÉRIEURE de la même escouade hériterait d'un type
    qu'elle n'a pas choisi — un tir normal résolu en indirect, sans que rien ne le signale."""
    gs = eligibles((SHOOTING_TYPE_NORMAL, SHOOTING_TYPE_INDIRECT))
    squad_shooting_type_choose(gs, "1", SHOOTING_TYPE_INDIRECT)

    squad_shooting_type_clear(gs, "1")

    assert resolve_squad_shooting_type(gs, "1") == SHOOTING_TYPE_NORMAL


def test_une_activation_depensee_n_a_plus_de_type_meme_choisi(eligibles):
    """Le garde `units_shot` précède volontairement la lecture du choix : si l'effacement venait
    à manquer, rendre le choix périmé ressusciterait une activation déjà jouée. C'est le repli
    silencieux que T1 interdit, et il se teste."""
    gs = eligibles((SHOOTING_TYPE_NORMAL, SHOOTING_TYPE_INDIRECT))
    squad_shooting_type_choose(gs, "1", SHOOTING_TYPE_INDIRECT)
    gs["units_shot"] = {"1"}

    assert resolve_squad_shooting_type(gs, "1") is None


def test_l_ensemble_eligible_ne_depend_pas_du_choix_deja_pose(monkeypatch):
    """Circularité évitée : `eligible_squad_shooting_types` énumère ce que l'escouade PEUT jouer,
    pas ce qu'elle a déjà choisi.

    Sans la séparation dérivation/résolution, poser un choix aurait rétréci l'ensemble éligible
    au choix lui-même — et un joueur PvP changeant d'avis se serait vu refuser son second choix
    par la validation de `squad_shooting_type_choose`."""
    monkeypatch.setattr(SU, "_derive_squad_shooting_type", lambda gs, sid: SHOOTING_TYPE_NORMAL)
    monkeypatch.setattr(SU, "_squad_has_indirect_fire_weapon", lambda gs, sid: False)
    # Choix INDIRECT déjà posé dans l'état (injection directe — squad_shooting_type_choose
    # validerait l'éligibilité, ce qui court-circuiterait le test).
    gs: dict = {SU.SQUAD_SHOOTING_TYPE_CHOICE_KEY: {"1": SHOOTING_TYPE_INDIRECT}}
    result = SU.eligible_squad_shooting_types(gs, "1")
    # La dérivation physique vaut NORMAL ; si eligible_squad_shooting_types lisait le choix via
    # resolve_squad_shooting_type, elle retournerait INDIRECT — c'est la régression testée.
    assert result == (SHOOTING_TYPE_NORMAL,)


# ─────────────────────────────────────────────────────────────────────────────
# L'espace d'action
# ─────────────────────────────────────────────────────────────────────────────

def test_les_slots_indirects_pavent_le_bloc_micro_sans_collision():
    """⚠️ LE DÉFAUT QUE CE TEST A RÉELLEMENT PRIS. Posés « à la fin » de `SQUAD_ACTION_SIZE`, les
    20 slots tombaient sur `BASE_ZONE_INTENT`, qui commençait exactement là : deux familles
    d'actions au même indice, et le décodeur en aurait servi une pour l'autre.

    `SQUAD_ACTION_SIZE` borne les actions MICRO — ce n'est pas la fin de l'espace d'action."""
    assert mi.SHOOT_INDIRECT_SLOT_BASE == SU.SQUAD_ACTION_SHOOT_INDIRECT_SLOT_BASE
    assert mi.SHOOT_INDIRECT_SLOT_COUNT == mi.SHOOT_SLOT_COUNT, (
        "invariant D1 : un slot = une ligne du tenseur ennemi, le MÊME mapping que le tir"
    )
    assert mi.BASE_ZONE_INTENT >= (
        mi.SHOOT_INDIRECT_SLOT_BASE + mi.SHOOT_INDIRECT_SLOT_COUNT
    ), "les intentions de zone doivent commencer APRÈS les slots indirects"


def _decode(action_int):
    """Décodage par le VRAI décodeur, avec le décor minimal qu'il exige.

    `ActionDecoder` se construit sur une config nue (même helper que
    `test_action_decoder.py`) ; l'aiguillage de phase demande un `game_state` en phase de tir et
    un pool d'unités éligibles, qu'on fournit plutôt que de contourner : c'est la branche de
    décodage qu'on veut exercer, pas une réécriture de celle-ci.
    """
    from engine.action_decoder import ActionDecoder

    decoder = ActionDecoder(config={"observation_params": {"action_space_size": 31}})
    game_state = {
        "phase": "shoot",
        SQUAD_SHOOTING_TYPE_CHOICE_KEY: {"1": SHOOTING_TYPE_NORMAL},
    }
    return decoder.convert_squad_action(
        action_int, game_state, eligible_units=[{"id": "1"}],
    )


@pytest.mark.parametrize("offset", [0, 7, 19])
def test_le_decodeur_rend_la_meme_action_avec_le_type_indirect(offset):
    """Une SEULE voie d'exécution (`squad_shoot`), deux familles de slots : deux actions
    distinctes auraient dupliqué la déclaration, le verrou et l'allocation."""
    normal = _decode(mi.SHOOT_SLOT_BASE + offset)
    indirect = _decode(mi.SHOOT_INDIRECT_SLOT_BASE + offset)

    assert normal["action"] == indirect["action"] == "squad_shoot"
    assert normal["target_slot"] == indirect["target_slot"] == offset, (
        "les deux familles indexent le MÊME mapping de cibles"
    )
    assert normal["shooting_type"] == SHOOTING_TYPE_NORMAL
    assert indirect["shooting_type"] == SHOOTING_TYPE_INDIRECT


def test_le_tir_ordinaire_declare_son_type_explicitement():
    """`normal` est DIT, pas laissé à deviner : un `shooting_type` absent obligerait le moteur à
    retomber sur la dérivation, qui ne saurait pas distinguer « l'agent a choisi normal » de
    « l'agent n'a rien dit ». C'est la distinction que tout ce chantier introduit."""
    assert "shooting_type" in _decode(mi.SHOOT_SLOT_BASE)


# ─────────────────────────────────────────────────────────────────────────────
# Robustesse de l'effacement du type
# ─────────────────────────────────────────────────────────────────────────────

def test_shooting_type_cleared_if_squad_declare_shoot_raises(monkeypatch):
    """try/finally garantit squad_shooting_type_clear même si squad_declare_shoot lève.

    Sans le finally, le type posé par squad_shooting_type_choose survivrait dans game_state.
    Le bare-except de execute_ai_turn (3462) avalant l'exception silencieusement, le masque
    du tour suivant ouvrirait des slots normaux sans contrainte de LoS (resolve rend INDIRECT,
    indirect_shooting_applies retourne True, require_visibility=False)."""
    from unittest.mock import patch
    import engine.phase_handlers.shared_utils as SU_mod
    from engine.w40k_core import W40KEngine

    def _raise(*a, **kw):
        raise RuntimeError("mock — squad_declare_shoot injecté pour le test")

    monkeypatch.setattr(SU_mod, "eligible_squad_shooting_types",
                        lambda gs, sid: (SHOOTING_TYPE_NORMAL,))
    monkeypatch.setattr(SU_mod, "squad_shooting_unit_activation_start", lambda gs, sid: None)
    monkeypatch.setattr(SU_mod, "squad_declare_shoot", _raise)
    monkeypatch.setattr(SU_mod, "get_enemy_slot_mapping", lambda gs, player: ["2"])

    eng = object.__new__(W40KEngine)
    eng.game_state = {
        "phase": "shoot",
        "units_cache": {"1": {"player": 1}},
    }
    semantic = {
        "action": "squad_shoot",
        "squad_id": "1",
        "target_slot": 0,
        "shooting_type": SHOOTING_TYPE_NORMAL,
    }

    with patch.object(eng, "_initialize_rule_choice_runtime_state", lambda: None):
        try:
            eng._process_squad_action(semantic)
        except RuntimeError:
            pass

    choices = eng.game_state.get(SU_mod.SQUAD_SHOOTING_TYPE_CHOICE_KEY, {})
    assert "1" not in choices, (
        "squad_shooting_type_clear doit effacer le choix même si squad_declare_shoot lève"
    )
