"""10.07 — ciblage sans ligne de vue, et les bornes de ce contournement.

    « [INDIRECT FIRE] weapons in your unit can target units that are not visible to the
      attacking model. »

Une seule exigence tombe : la VISIBILITÉ. La portée reste. Ce fichier vérifie les deux moitiés,
parce qu'une implémentation qui rendrait `True` trop tôt ouvrirait la carte entière — et parce
que la même fonction sert au chemin PvP, au masque de l'agent et au pool de cibles.

Les deux gates qui tombent sont TOUTES DEUX des gates de visibilité : le tracé de ligne de vue
(06.01 / 13.10) et la détection d'une unité `hidden` (13.09, « it can only be VISIBLE to enemy
models that are within its detection range »). Celle qui NE tombe pas est [PRECISION] 24.28, qui
exige un CHARACTER « visible to one or more of the attacking models » : c'est une exigence propre
à cette règle, pas la ligne de vue du tir.
"""
from __future__ import annotations

import pytest

from engine.phase_handlers import shared_utils as SU
from engine.phase_handlers.shared_utils import (
    SHOOTING_TYPE_INDIRECT,
    SHOOTING_TYPE_NORMAL,
    indirect_shooting_applies,
)

INDIRECT = {"display_name": "Impaler Cannon", "RNG": 180, "NB": 4, "ATK": 4, "STR": 5,
            "AP": -1, "DMG": 1, "WEAPON_RULES": ["HEAVY", "INDIRECT_FIRE"], "code": "test_indirect_weapon"}
DIRECT = {"display_name": "Bolt Rifle", "RNG": 120, "NB": 2, "ATK": 3, "STR": 4,
          "AP": -1, "DMG": 1, "WEAPON_RULES": [], "code": "test_direct_weapon"}


# ─────────────────────────────────────────────────────────────────────────────
# Le prédicat partagé : ciblage et résolution doivent lire le MÊME fait
# ─────────────────────────────────────────────────────────────────────────────

def _gs(shooting_type):
    """`resolve_squad_shooting_type` est le seul point que le prédicat interroge : on le
    contrôle directement plutôt que de reconstruire un plateau, dont rien ici ne dépend."""
    return {"__type": shooting_type}


@pytest.fixture
def type_fige(monkeypatch):
    def _fige(valeur):
        monkeypatch.setattr(
            SU, "resolve_squad_shooting_type", lambda gs, sid: gs["__type"],
        )
        return _gs(valeur)
    return _fige


def test_la_regle_ne_porte_que_sur_les_armes_indirectes(type_fige):
    """Encadré du PDF : sous tir indirect, « its other weapons can still target other visible
    targets ». Une arme ordinaire de la même unité garde donc son exigence de ligne de vue."""
    gs = type_fige(SHOOTING_TYPE_INDIRECT)

    assert indirect_shooting_applies(gs, "1", INDIRECT) is True
    assert indirect_shooting_applies(gs, "1", DIRECT) is False


def test_hors_tir_indirect_l_arme_indirecte_est_une_arme_ordinaire(type_fige):
    """La contre-épreuve qui compte : porter la règle ne suffit pas, il faut que l'unité ait
    CHOISI le tir indirect (10.02). Sans elle, une Impaler Cannon tirerait sans ligne de vue en
    permanence — c'est-à-dire que le choix du type de tir ne servirait à rien."""
    gs = type_fige(SHOOTING_TYPE_NORMAL)

    assert indirect_shooting_applies(gs, "1", INDIRECT) is False


def test_le_predicat_sort_avant_de_resoudre_le_type_de_tir(monkeypatch):
    """La paresse est CONTRACTUELLE, pas une optimisation opportuniste : `resolve_squad_shooting_type`
    balaie les figurines vivantes et leurs armes, et exige `config.game_rules.engagement_zone`.
    Le prédicat est appelé sur CHAQUE test de ciblage du jeu ; s'il résolvait le type avant de
    regarder l'arme, il ferait payer ce balayage aux 229 profils qui ne portent pas la règle.

    Mesuré par le nombre d'appels, pas supposé."""
    appels = []
    monkeypatch.setattr(
        SU, "resolve_squad_shooting_type",
        lambda gs, sid: appels.append(sid) or SHOOTING_TYPE_INDIRECT,
    )

    assert indirect_shooting_applies({}, "1", DIRECT) is False
    assert appels == [], "une arme sans la règle ne doit déclencher aucune résolution de type"

    indirect_shooting_applies({}, "1", INDIRECT)
    assert appels == ["1"], "une arme qui la porte doit, elle, résoudre le type"


# ─────────────────────────────────────────────────────────────────────────────
# Le contournement lui-même : ce qui tombe, ce qui reste
# ─────────────────────────────────────────────────────────────────────────────

def _board(distance_subhex):
    """Plateau minimal pour `_attacker_model_can_reach_squad` : un tireur en (0,0), une cible
    a `distance_subhex` colonnes. Meme forme que la fixture de `test_detection_range_strict`.

    La VISIBILITE est controlee par monkeypatch plutot que par un mur : c'est la branche qu'on
    veut isoler, et un terrain reel ferait dependre le test d'une geometrie sans rapport avec
    10.07.
    """
    attacker = {"id": "1#0", "squad_id": "1", "col": 0, "row": 0,
                "BASE_SHAPE": "round", "BASE_SIZE": 1, "alive": True}
    target = {"id": "101#0", "squad_id": "101", "col": distance_subhex, "row": 0,
              "BASE_SHAPE": "round", "BASE_SIZE": 1, "alive": True}
    gs = {
        "config": {"game_rules": {"detection_range": 15}},
        "inches_to_subhex": 5,
        "models_cache": {"1#0": attacker, "101#0": target},
        "squad_models": {"1": ["1#0"], "101": ["101#0"]},
        "units_cache": {"1": {"player": 1, "alive": True},
                        "101": {"player": 2, "alive": True}},
        "units": [{"id": "1", "player": 1}, {"id": "101", "player": 2}],
    }
    return gs, attacker


@pytest.fixture
def cible_invisible(monkeypatch):
    """La cible n'est JAMAIS visible : `visible = 0` sur toute paire."""
    from engine.phase_handlers import shooting_handlers

    appels = []

    def _aucune_visibilite(*a, **k):
        appels.append(1)
        return (0, 7, None)

    monkeypatch.setattr(
        shooting_handlers, "_compute_visibility_with_obscuring", _aucune_visibilite,
    )
    return appels


def test_la_portee_reste_exigee_sans_ligne_de_vue(cible_invisible):
    """LA BORNE du contournement. 10.07 retire la visibilite, RIEN d'autre : une cible hors
    portee reste hors portee. Une implementation qui rendrait `True` des l'entree de la boucle
    ouvrirait la carte entiere — c'est le seul defaut vraiment couteux de cette piece."""
    gs, tireur = _board(distance_subhex=1000)

    assert SU._attacker_model_can_reach_squad(
        gs, tireur, 0, 0, "101", range_subhex=180, require_visibility=False,
    ) is False


def test_une_cible_a_portee_mais_invisible_devient_atteignable(cible_invisible):
    """Le coeur de la piece : meme geometrie, meme portee, seule l'exigence de visibilite change.

    Les DEUX assertions sont necessaires — sans la premiere, rien ne prouverait que la cible
    etait bien refusee avant, donc que c'est la visibilite qu'on a levee et non la portee qu'on
    a elargie."""
    gs, tireur = _board(distance_subhex=60)

    assert SU._attacker_model_can_reach_squad(
        gs, tireur, 0, 0, "101", range_subhex=180, require_visibility=True,
    ) is False, "premisse : sans le contournement, une cible invisible est refusee"

    assert SU._attacker_model_can_reach_squad(
        gs, tireur, 0, 0, "101", range_subhex=180, require_visibility=False,
    ) is True


def test_le_contournement_ne_calcule_meme_pas_la_ligne_de_vue(cible_invisible):
    """Ne pas calculer un trace pour en jeter le resultat : c'est ce qui rend la piece gratuite
    sur le chemin de ciblage, qui est un chemin chaud (masque de l'agent, pool de cibles).

    Mesure par le nombre d'appels, pas supposee."""
    gs, tireur = _board(distance_subhex=60)

    SU._attacker_model_can_reach_squad(
        gs, tireur, 0, 0, "101", range_subhex=180, require_visibility=False,
    )
    assert cible_invisible == [], "aucun trace de ligne de vue ne doit avoir ete demande"

    SU._attacker_model_can_reach_squad(
        gs, tireur, 0, 0, "101", range_subhex=180, require_visibility=True,
    )
    assert cible_invisible != [], "et le chemin ordinaire, lui, doit bien le demander"


def test_une_unite_hidden_reste_ciblable_sans_visibilite(cible_invisible):
    """13.09 est une gate de VISIBILITE (« it can only be VISIBLE to enemy models within its
    detection range »), pas de portee. Une regle qui n'exige plus la visibilite ne peut donc pas
    buter dessus.

    Sans ce test, la detection resterait active sous tir indirect et une unite cachee au-dela de
    15\" serait intirable — un blocage silencieux, puisque la ligne de vue, elle, aurait bien
    ete contournee."""
    gs, tireur = _board(distance_subhex=150)  # 30" : bien au-dela des 15" de detection
    gs["units"][1]["hidden"] = True

    assert SU._attacker_model_can_reach_squad(
        gs, tireur, 0, 0, "101", range_subhex=180, require_visibility=True,
    ) is False, "premisse : hors detection, le tir ordinaire refuse la cible cachee"

    assert SU._attacker_model_can_reach_squad(
        gs, tireur, 0, 0, "101", range_subhex=180, require_visibility=False,
    ) is True
