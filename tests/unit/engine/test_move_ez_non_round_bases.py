"""EZ du move pour les socles NON RONDS : le masque doit dire la même chose que la règle.

DÉFAUT VERROUILLÉ (mesuré le 2026-08-10). Le correctif « EZ par figurine » du 2026-08-09 avait
aligné le prédicat du move sur `_compute_mover_ez_forbidden_mask`. Mais ce masque ne traitait
exactement que la paire RONDE↔RONDE : toute paire impliquant un socle non rond retombait sur la
distance entre CENTRES DE CELLULES, alors que `entries_in_engagement_zone` — le prédicat que la
phase de combat applique — mesure les CONTOURS continus.

Témoin (E8 T5 du journal du 2026-08-09) : l'unité 105 est un WarTrakk, socle `oval/[20, 14]`,
187 cases d'empreinte. Après son move normal vers (183,207) :

    entries_in_engagement_zone(euclidean) -> True    (écart bord-à-bord 13,85 <= seuil 15)
    masque du move interdit (183,207) ?   -> False   (il n'interdisait que (183,208))

Une case d'écart, et 09.05 violé pour tout véhicule à socle oval.

Le correctif n'évalue PAS le contour partout : mesuré, l'exact naïf coûte 0,98 s par masque
contre ~140 s pour un run de 12 épisodes entier. Il encadre — `exact <= cellules <=
exact + MARGE` — et ne paie le contour que dans la frange. La borne haute est ce que ce fichier
vérifie en premier : sans elle, tout le reste repose sur une supposition.
"""

from __future__ import annotations

import numpy as np
import pytest

from engine.hex_utils import (
    ENGAGEMENT_NORM_HEX_WIDTH, Socle, _hex_center, compute_occupied_hexes,
    engagement_minimum_clearance_norm, euclidean_edge_distance,
)
from engine.phase_handlers.movement_handlers import (
    NON_ROUND_EZ_BAND_NORM, _compute_mover_ez_forbidden_mask,
)

EZ = 10                      # engagement_zone 2" × inches_to_subhex 5
THR = engagement_minimum_clearance_norm(EZ)
BOARD = (240, 320)
MOVER = ("oval", [20, 14])   # WarTrakk du témoin
ENEMY = ("round", 6)         # Intercessor
WITNESS_ANCHOR = (183, 207)
# Socles de l'unité 5 au moment du move (T5 STATE du journal).
WITNESS_ENEMY_MODELS = {
    "5#0": (198, 236), "5#1": (198, 230), "5#2": (192, 234), "5#3": (192, 228),
    "5#4": (198, 224), "5#5": (185, 231), "5#6": (186, 224),
}


def _socle(shape, size, col, row, orient=0):
    fp = set(compute_occupied_hexes(col, row, shape, size, orient))
    return Socle(shape=shape, base_size=size, col=col, row=row, fp=fp, orientation=orient)


def _cell_distance(a: Socle, b: Socle) -> float:
    """Distance MINIMALE entre centres de cellules — l'approximation que le masque filtre avec."""
    a_centers = [_hex_center(c, r) for c, r in a.fp]
    b_centers = [_hex_center(c, r) for c, r in b.fp]
    return min(
        ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5
        for ax, ay in a_centers for bx, by in b_centers
    )


@pytest.fixture
def euclidean(monkeypatch):
    monkeypatch.setattr(
        "engine.spatial_relations.engagement_distance_metric",
        lambda *args, **kwargs: "euclidean",
    )


def _enemy_entry(models):
    return {
        "id": "5", "player": 1, "BASE_SHAPE": ENEMY[0], "BASE_SIZE": ENEMY[1], "orientation": 0,
        "occupied_hexes_by_model": dict(models),
    }


def _mover(shape=MOVER[0], size=MOVER[1]):
    return {"id": "105", "BASE_SHAPE": shape, "BASE_SIZE": size, "orientation": 0}


def _mask(models=None, mover=None):
    """État COMPLET : le masque est mémoïsé par le fingerprint d'état partagé
    (`_move_spatial_cache`), qui lit `models_cache`, la phase et les zones d'engagement. Une
    fixture qui les omet ne décrit pas un état que le moteur peut produire — et le cache lève
    plutôt que d'inventer une clé, ce qui est le comportement voulu."""
    models = models or WITNESS_ENEMY_MODELS
    gs = {
        "config": {"game_rules": {"engagement_zone": EZ, "max_base_size_hex": 24}},
        "inches_to_subhex": 5,
        "phase": "move",
        "units": [],
        "models_cache": {
            mid: {"col": c, "row": r, "level": 0} for mid, (c, r) in models.items()
        },
        "enemy_adjacent_hexes_player_1": set(),
        "enemy_adjacent_hexes_player_2": set(),
    }
    return _compute_mover_ez_forbidden_mask(
        gs, mover or _mover(), [("5", _enemy_entry(models))], EZ, BOARD[0], BOARD[1],
    )


# ─────────────────────────────────────────────────────────────────────────────
# La borne : tout le correctif repose dessus
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("mover_shape,mover_size", [
    ("oval", [20, 14]), ("oval", [16, 8]), ("square", 10), ("round", 6),
])
@pytest.mark.parametrize("orient", [0, 1, 3])
def test_the_band_bounds_the_gap(mover_shape, mover_size, orient):
    """``exact <= cellules <= exact + MARGE`` sur les géométries réellement jouées.

    La borne BASSE est structurelle (le contour enferme ses centres de cellules) ; la borne
    HAUTE est ce qui autorise à ne PAS évaluer le contour hors de la frange. Si ce test tombe,
    le masque laisse passer des placements engagés — élargir `NON_ROUND_EZ_BAND_NORM`.
    """
    enemy = _socle(*ENEMY, 100, 100)
    worst = 0.0
    for dc in range(-26, 27, 3):
        for dr in range(-26, 27, 3):
            mover = _socle(mover_shape, mover_size, 100 + dc, 100 + dr, orient)
            exact = euclidean_edge_distance(mover, enemy, max_distance=None)
            cells = _cell_distance(mover, enemy)
            assert exact <= cells + 1e-9, (
                f"contour PLUS LOIN que les centres de cellules ({exact} > {cells}) : "
                "l'encadrement est faux, la moitié « interdit à coup sûr » du masque ne tient plus"
            )
            worst = max(worst, cells - exact)
    assert worst <= NON_ROUND_EZ_BAND_NORM + 1e-9, (
        f"écart mesuré {worst:.3f} > marge {NON_ROUND_EZ_BAND_NORM} pour "
        f"{mover_shape}/{mover_size} orient={orient} : la frange est trop étroite et le masque "
        "déclare « autorisé » des ancres que le contour interdit"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Le témoin
# ─────────────────────────────────────────────────────────────────────────────

def test_premise_the_witness_is_engaged_for_the_rule(euclidean):
    """Sans ça, le test suivant verrouillerait une non-violation."""
    from engine.spatial_relations import entries_in_engagement_zone

    def entry(models, shape, size):
        occ = set()
        for c, r in models.values():
            occ |= set(compute_occupied_hexes(c, r, shape, size, 0))
        first = next(iter(models.values()))
        return {"col": first[0], "row": first[1], "BASE_SHAPE": shape, "BASE_SIZE": size,
                "orientation": 0, "occupied_hexes": occ,
                "occupied_hexes_by_model": dict(models),
                "floor_height_by_model": {m: 0.0 for m in models}, "MODEL_HEIGHT": 3.0}

    assert entries_in_engagement_zone(
        entry({"105#0": WITNESS_ANCHOR}, *MOVER), entry(WITNESS_ENEMY_MODELS, *ENEMY),
        EZ, "euclidean", 5.0,
    ), "le témoin n'est plus engagé au sens de la règle : les positions ont bougé"


def test_the_witness_anchor_is_forbidden(euclidean):
    """Le masque doit refuser l'ancre que la phase de combat juge engagée."""
    mask = _mask()
    assert bool(mask[WITNESS_ANCHOR[0], WITNESS_ANCHOR[1]]), (
        "le masque autorise encore l'ancre du WarTrakk : un socle non rond peut finir son move "
        "engagé, 09.05 violé (témoin E8 T5 du 2026-08-09)"
    )


def test_the_mask_agrees_with_the_rule_cell_by_cell(euclidean):
    """Aucun désaccord masque ↔ `euclidean_edge_distance` autour du témoin.

    Le témoin ne prouve qu'UNE case. Ce balayage prouve l'absence de frontière décalée : c'est
    exactement ce qu'un test sur la seule case du témoin laisserait repasser.
    """
    mask = _mask()
    enemy_socles = [_socle(*ENEMY, c, r) for c, r in WITNESS_ENEMY_MODELS.values()]
    desaccords = []
    for col in range(170, 200, 2):
        for row in range(195, 240, 2):
            mover = _socle(*MOVER, col, row)
            engaged = any(
                euclidean_edge_distance(mover, e, max_distance=THR) <= THR for e in enemy_socles
            )
            if bool(mask[col, row]) != engaged:
                desaccords.append((col, row, bool(mask[col, row]), engaged))
    assert not desaccords, f"masque et règle divergent sur {len(desaccords)} ancres : {desaccords[:5]}"


def test_round_movers_are_untouched(euclidean):
    """La paire ronde↔ronde était déjà exacte : elle ne doit pas changer de chemin."""
    mask = _mask(mover=_mover("round", 6))
    enemy_socles = [_socle(*ENEMY, c, r) for c, r in WITNESS_ENEMY_MODELS.values()]
    for col, row in ((190, 230), (183, 207), (150, 200)):
        mover = _socle("round", 6, col, row)
        engaged = any(
            euclidean_edge_distance(mover, e, max_distance=THR) <= THR for e in enemy_socles
        )
        assert bool(mask[col, row]) == engaged, f"ancre ronde ({col},{row}) mal classée"


# ─────────────────────────────────────────────────────────────────────────────
# Mémoïsation : un cache qui sert un masque périmé est pire que le coût qu'il évite
# ─────────────────────────────────────────────────────────────────────────────

def _state(models):
    return {
        "config": {"game_rules": {"engagement_zone": EZ, "max_base_size_hex": 24}},
        "inches_to_subhex": 5, "phase": "move", "units": [],
        "models_cache": {m: {"col": c, "row": r, "level": 0} for m, (c, r) in models.items()},
        "enemy_adjacent_hexes_player_1": set(), "enemy_adjacent_hexes_player_2": set(),
    }


def test_mask_is_memoised_per_state(euclidean):
    """Deux demandes identiques dans le MÊME état rendent le même objet, sans recalcul."""
    models = dict(WITNESS_ENEMY_MODELS)
    gs = _state(models)
    a = _compute_mover_ez_forbidden_mask(
        gs, _mover(), [("5", _enemy_entry(models))], EZ, BOARD[0], BOARD[1])
    b = _compute_mover_ez_forbidden_mask(
        gs, _mover(), [("5", _enemy_entry(models))], EZ, BOARD[0], BOARD[1])
    assert a is b, "masque recalculé à état inchangé : la mémoïsation ne prend pas"


def test_mask_is_recomputed_when_a_model_moves(euclidean):
    """LE risque du cache : servir un masque d'AVANT le déplacement.

    Le fingerprint d'état couvre les positions par figurine ; bouger un socle doit suffire à le
    périmer. Sans ça, le moteur autoriserait des placements dans une EZ qui a bougé.
    """
    models = dict(WITNESS_ENEMY_MODELS)
    gs = _state(models)
    avant = _compute_mover_ez_forbidden_mask(
        gs, _mover(), [("5", _enemy_entry(models))], EZ, BOARD[0], BOARD[1])
    n_avant = int(avant.sum())
    gs["models_cache"]["5#0"]["col"] -= 40      # l'ennemi s'éloigne franchement
    models["5#0"] = (WITNESS_ENEMY_MODELS["5#0"][0] - 40, WITNESS_ENEMY_MODELS["5#0"][1])
    apres = _compute_mover_ez_forbidden_mask(
        gs, _mover(), [("5", _enemy_entry(models))], EZ, BOARD[0], BOARD[1])
    assert apres is not avant and int(apres.sum()) != n_avant, (
        "masque inchangé après déplacement d'une figurine ennemie : le cache sert une carte "
        "périmée"
    )


def test_cached_mask_cannot_be_mutated(euclidean):
    """Rendu par référence : une mutation corromprait tous les autres lecteurs."""
    models = dict(WITNESS_ENEMY_MODELS)
    mask = _compute_mover_ez_forbidden_mask(
        _state(models), _mover(), [("5", _enemy_entry(models))], EZ, BOARD[0], BOARD[1])
    with pytest.raises(ValueError):
        mask[0, 0] = True


def test_two_base_geometries_do_not_share_a_mask(euclidean):
    """La clé porte la géométrie : un socle rond ne doit pas hériter du masque de l'oval."""
    models = dict(WITNESS_ENEMY_MODELS)
    gs = _state(models)
    oval = _compute_mover_ez_forbidden_mask(
        gs, _mover(), [("5", _enemy_entry(models))], EZ, BOARD[0], BOARD[1])
    rond = _compute_mover_ez_forbidden_mask(
        gs, _mover("round", 6), [("5", _enemy_entry(models))], EZ, BOARD[0], BOARD[1])
    assert int(oval.sum()) > int(rond.sum()), (
        "le socle oval, bien plus large, doit interdire plus de cases que le rond — masques "
        "confondus par le cache"
    )


# ─────────────────────────────────────────────────────────────────────────────
# L'ORIENTATION : elle change l'empreinte sans changer l'ancre
# ─────────────────────────────────────────────────────────────────────────────

def test_the_mask_depends_on_the_mover_orientation(euclidean):
    """Un socle oval pivoté n'interdit pas les mêmes ancres — sinon le pivot serait gratuit.

    Prémisse du test suivant : si le masque ignorait l'orientation, l'écart pool/validation
    serait invisible.
    """
    models = dict(WITNESS_ENEMY_MODELS)
    gs = _state(models)
    a = _compute_mover_ez_forbidden_mask(
        gs, _mover(), [("5", _enemy_entry(models))], EZ, BOARD[0], BOARD[1])
    pivote = {**_mover(), "orientation": 1}
    b = _compute_mover_ez_forbidden_mask(
        gs, pivote, [("5", _enemy_entry(models))], EZ, BOARD[0], BOARD[1])
    assert int(a.sum()) != int(b.sum()), (
        "le masque ne dépend pas de l'orientation du mover : le pivot d'un socle oval ne "
        "changerait rien, et l'écart pool/validation ne serait pas mesurable"
    )


def test_state_fingerprint_covers_a_pivot_in_place(euclidean):
    """Pivoter une figurine ENNEMIE sans la déplacer doit périmer le masque mémoïsé.

    `update_model_position(..., orientation=)` autorise ce commit, et
    `update_enemy_adjacent_caches_after_unit_move` sort tôt quand col/row sont inchangés : sans
    l'orientation dans le fingerprint, le cache servait l'empreinte D'AVANT le pivot.
    """
    models = dict(WITNESS_ENEMY_MODELS)
    gs = _state(models)
    for mid in gs["models_cache"]:
        gs["models_cache"][mid]["orientation"] = 0
    gs["units_cache"] = {}
    avant = _compute_mover_ez_forbidden_mask(
        gs, _mover(), [("5", _enemy_entry(models))], EZ, BOARD[0], BOARD[1])
    # Pivot SUR PLACE d'un socle ennemi : col/row inchangés, orientation changée.
    for mid in gs["models_cache"]:
        gs["models_cache"][mid]["orientation"] = 2
    apres = _compute_mover_ez_forbidden_mask(
        gs, _mover(), [("5", _enemy_entry(models))], EZ, BOARD[0], BOARD[1])
    assert apres is not avant, (
        "masque servi depuis le cache après un pivot sur place : le fingerprint d'état ignore "
        "l'orientation, donc l'empreinte ennemie utilisée est périmée"
    )


# ─────────────────────────────────────────────────────────────────────────────
# La PRUNE des ennemis doit voir le même socle que le masque
# ─────────────────────────────────────────────────────────────────────────────

def test_enemy_prune_horizon_follows_the_mover_socle():
    """L'horizon d'élagage se borne au rayon du MOVER : mesuré sur la figurine, pas l'escouade.

    Le pool par-figurine calcule l'EZ avec le socle de la FIGURINE. Si la prune, elle, se borne
    au socle d'ESCOUADE, un personnage attaché à socle plus grand (Boyz 13 → rayon 7, Warboss
    20 → rayon 10) fait élaguer des ennemis encore pertinents : le masque n'interdit pas leurs
    ancres et `explain_move_plan_rejection`, qui voit TOUS les ennemis, refuse la case —
    l'incohérence masque/exécution que le socle par-figurine vient de fermer.
    """
    from engine.phase_handlers.movement_handlers import (
        _enemy_items_within_move_engagement_horizon,
    )

    escouade = {"id": "1", "BASE_SHAPE": "round", "BASE_SIZE": 6}
    perso = {"id": "1", "BASE_SHAPE": "round", "BASE_SIZE": 20}
    # Ennemi placé juste au-delà de l'horizon du petit socle, en deçà de celui du grand.
    units_cache = {
        "9": {
            "id": "9", "player": 2, "col": 50, "row": 20, "HP_CUR": 1,
            "BASE_SHAPE": "round", "BASE_SIZE": 6, "orientation": 0,
            "occupied_hexes": {(50, 20)},
        }
    }
    gs = {
        "config": {"game_rules": {"engagement_zone": EZ, "max_base_size_hex": 24}},
        "inches_to_subhex": 5,
    }
    petit = _enemy_items_within_move_engagement_horizon(
        gs, escouade, "1", 1, 20, 20, 10, units_cache)
    grand = _enemy_items_within_move_engagement_horizon(
        gs, perso, "1", 1, 20, 20, 10, units_cache)
    assert len(grand) > len(petit), (
        "prémisse : l'ennemi choisi doit tomber ENTRE les deux horizons, sinon rien n'est mesuré"
    )


def test_the_pool_prunes_enemies_with_the_socle_it_measures_with(monkeypatch):
    """VERROU DE CÂBLAGE : le pool doit passer le MÊME socle à la prune et au masque.

    Le test précédent ne vérifie que le CONTRAT de la prune ; il reste vert si le site d'appel
    lui repasse le socle d'escouade — c'est exactement ce qui s'est produit. Ici on observe
    l'appel réel : les deux fonctions doivent recevoir la même géométrie, sinon la prune élague
    des ennemis que le masque aurait interdits et l'invariant masque ⊆ exécutable retombe.
    """
    import engine.phase_handlers.movement_handlers as mh

    vus: dict = {}

    _prune_orig = mh._enemy_items_within_move_engagement_horizon
    _mask_orig = mh._compute_mover_ez_forbidden_mask

    def _prune_spy(game_state, unit, *a, **k):
        vus["prune"] = (unit.get("BASE_SHAPE"), str(unit.get("BASE_SIZE")),
                        unit.get("orientation"))
        return _prune_orig(game_state, unit, *a, **k)

    def _mask_spy(game_state, unit, *a, **k):
        vus["masque"] = (unit.get("BASE_SHAPE"), str(unit.get("BASE_SIZE")),
                         unit.get("orientation"))
        return _mask_orig(game_state, unit, *a, **k)

    monkeypatch.setattr(mh, "_enemy_items_within_move_engagement_horizon", _prune_spy)
    monkeypatch.setattr(mh, "_compute_mover_ez_forbidden_mask", _mask_spy)

    from tests.unit.engine._config_helpers import build_armageddon_engine

    eng = build_armageddon_engine(seed=1)
    gs = eng.game_state
    mc = gs["models_cache"]
    mid = next(m for m in mc if "#" in m)
    model = mc[mid]
    # Socle de la figurine RENDU DIFFÉRENT de celui de son escouade : c'est la situation du
    # personnage attaché, et la seule où l'écart prune/masque est observable.
    model["BASE_SHAPE"], model["BASE_SIZE"] = "round", 20
    sid = str(model["squad_id"])
    gs["units_cache"][sid]["BASE_SHAPE"] = "round"
    gs["units_cache"][sid]["BASE_SIZE"] = 6

    mh.movement_build_model_destinations_pool(gs, mid)

    assert "prune" in vus and "masque" in vus, "le chemin ez > 1 n'a pas été emprunté"
    assert vus["prune"] == vus["masque"], (
        f"prune {vus['prune']} et masque {vus['masque']} ne voient pas le même socle : la prune "
        "élaguera des ennemis que le masque aurait interdits"
    )
