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

Le correctif n'évalue PAS le contour case par case : mesuré, l'exact naïf coûte 0,98 s par masque
contre ~140 s pour un run de 12 épisodes entier. Il exploite le fait que la clairance ne dépend
que de l'ÉCART entre les deux centres — donc, à couple de géométries fixé, l'ensemble des ancres
interdites est un motif translaté (somme de Minkowski) calculé UNE fois et estampé autour de
chaque figurine ennemie. Cette invariance est ce que ce fichier vérifie en premier : sans elle,
tout le reste repose sur une supposition.
"""

from __future__ import annotations

import numpy as np
import pytest

from engine.hex_utils import (
    ENGAGEMENT_NORM_HEX_WIDTH, Socle, _hex_center, compute_occupied_hexes,
    engagement_minimum_clearance_norm, euclidean_edge_distance,
)
from engine.phase_handlers.movement_handlers import (
    EZ_KERNEL_TIE_EPS_NORM, _compute_mover_ez_forbidden_mask, _ez_offset_kernels,
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
    if a.fp is None or b.fp is None:
        raise ValueError("_cell_distance mesure des EMPREINTES : un socle sans `fp` n'en a pas")
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
# L'INVARIANCE PAR TRANSLATION : tout le correctif repose dessus
# ─────────────────────────────────────────────────────────────────────────────

def _forbidden_offsets(mover_shape, mover_size, orient, enemy_col, enemy_row, span=9):
    """Offsets strictement interdits autour d'un ennemi PLACÉ, mesurés à ses coordonnées réelles.

    Les offsets dont la distance tombe dans la bande EZ_KERNEL_TIE_EPS_NORM autour de THR sont
    EXCLUS : le moteur les re-mesure à la position réelle (``_resolve_ez_ties_exactly``) et ils
    ne font pas partie du domaine où l'invariance par translation est censée tenir.
    """
    enemy = Socle(shape=ENEMY[0], base_size=ENEMY[1], col=enemy_col, row=enemy_row,
                  fp=None, orientation=0)
    out = set()
    for dc in range(-span, span + 1):
        for dr in range(-span, span + 1):
            mover = Socle(shape=mover_shape, base_size=mover_size, col=enemy_col + dc,
                          row=enemy_row + dr, fp=None, orientation=orient)
            d = euclidean_edge_distance(mover, enemy, max_distance=THR + EZ_KERNEL_TIE_EPS_NORM)
            if d <= THR - EZ_KERNEL_TIE_EPS_NORM:
                out.add((dc, dr))
    return out


@pytest.mark.parametrize("mover_shape,mover_size", [
    ("oval", [20, 14]), ("oval", [16, 8]), ("square", 10), ("round", 6),
])
@pytest.mark.parametrize("orient", [0, 1, 3])
def test_the_forbidden_pattern_only_depends_on_the_column_parity(mover_shape, mover_size, orient):
    """Le motif interdit est le MÊME partout sur le plateau, à parité de colonne égale.

    C'est la prémisse du noyau : s'il dépendait de la position absolue, l'estamper autour de
    chaque figurine ennemie donnerait un masque faux ailleurs qu'à l'endroit où il a été calculé.
    Le décalage d'une demi-ligne une colonne sur deux est la SEULE dépendance admise — d'où deux
    noyaux et non un.
    """
    key_size = tuple(mover_size) if isinstance(mover_size, list) else mover_size
    key_enemy = tuple(ENEMY[1]) if isinstance(ENEMY[1], list) else ENEMY[1]
    _, _, dcol_max, _ = _ez_offset_kernels(
        mover_shape, key_size, orient, ENEMY[0], key_enemy, 0, THR, True,
    )
    for parity in (0, 1):
        ancres = [(100, 100), (100, 137), (156, 203), (12, 9)]
        ref = None
        for col, row in ancres:
            col = col - (col & 1) + parity
            got = _forbidden_offsets(mover_shape, mover_size, orient, col, row, span=dcol_max)
            if ref is None:
                ref = got
            else:
                assert got == ref, (
                    f"motif interdit différent en ({col},{row}) pour {mover_shape}/{mover_size} "
                    f"orient={orient} parité={parity} : {sorted(got ^ ref)[:5]} — le noyau de "
                    "Minkowski n'est pas légitime, le masque sera faux loin de son origine"
                )
        assert ref, "prémisse : aucun offset interdit, le balayage ne mesure rien"


@pytest.mark.parametrize("mover_shape,mover_size,enemy_shape,enemy_size", [
    ("oval", [20, 14], "round", 6), ("square", 10, "round", 6),
    ("round", 6, "oval", [20, 14]), ("oval", [16, 8], "square", 10),
    ("round", 6, "round", 6),
])
def test_the_kernel_window_holds_every_forbidden_offset(
    mover_shape, mover_size, enemy_shape, enemy_size
):
    """Rien d'interdit ne vit HORS de la fenêtre du noyau.

    La fenêtre est dérivée des disques circonscrits (``seuil + r_mover + r_ennemi``). Si elle
    était trop étroite d'une seule colonne, le masque cesserait d'interdire les ancres du bord —
    et aucun balayage centré sur le témoin ne le verrait, faute d'ancre interdite si loin. Le
    contrôle se fait donc sur le noyau lui-même, en débordant délibérément sa fenêtre.
    """
    key_size = tuple(mover_size) if isinstance(mover_size, list) else mover_size
    key_enemy = tuple(enemy_size) if isinstance(enemy_size, list) else enemy_size
    col, row = 100, 100
    enemy = Socle(shape=enemy_shape, base_size=enemy_size, col=col, row=row, fp=None,
                  orientation=0)
    sure, tie, dcol_max, drow_max = _ez_offset_kernels(
        mover_shape, key_size, 0, enemy_shape, key_enemy, 0, THR, True,
    )
    marge = 3
    interdits = 0
    for dc in range(-dcol_max - marge, dcol_max + marge + 1):
        for dr in range(-drow_max - marge, drow_max + marge + 1):
            mover = Socle(shape=mover_shape, base_size=mover_size, col=col + dc, row=row + dr,
                          fp=None, orientation=0)
            if euclidean_edge_distance(mover, enemy, max_distance=THR) > THR:
                continue
            interdits += 1
            assert abs(dc) <= dcol_max and abs(dr) <= drow_max, (
                f"offset interdit ({dc},{dr}) HORS de la fenêtre du noyau "
                f"({dcol_max}×{drow_max}) : le masque laissera passer cette ancre"
            )
            i, j = dc + dcol_max, dr + drow_max
            assert sure[i, j] or tie[i, j], (
                f"offset interdit ({dc},{dr}) classé « autorisé » par le noyau"
            )
    assert interdits > 100, "prémisse : le balayage ne trouve presque aucun offset interdit"


@pytest.mark.parametrize("mover_shape,mover_size", [
    ("oval", [20, 14]), ("oval", [16, 8]), ("square", 10), ("round", 6),
])
@pytest.mark.parametrize("orient", [0, 2, 5])
def test_the_tie_band_bounds_the_kernel_error(mover_shape, mover_size, orient):
    """``EZ_KERNEL_TIE_EPS_NORM`` majore l'écart noyau ↔ mesure aux coordonnées réelles.

    Les deux calculs sont algébriquement identiques mais pas bit-à-bit : le noyau mesure à une
    origine canonique, l'exécution à la position réelle. Toute case dont la clairance tombe à
    moins de EPS du seuil est re-mesurée ; si l'écart réel dépassait EPS, une case serait
    tranchée depuis le noyau ALORS QUE l'exécution la classera dans l'autre sens — exactement la
    divergence masque/exécution que ce fichier existe pour interdire.
    """
    def _gap(col, row, dc, dr):
        enemy = Socle(shape=ENEMY[0], base_size=ENEMY[1], col=col, row=row, fp=None,
                      orientation=0)
        mover = Socle(shape=mover_shape, base_size=mover_size, col=col + dc, row=row + dr,
                      fp=None, orientation=orient)
        return euclidean_edge_distance(mover, enemy, max_distance=THR + 1.0)

    worst = 0.0
    mesures = 0
    for parity in (0, 1):
        origine = (100 + parity, 100)
        for col, row in ((156 + parity, 203), (12 + parity, 9), (200 + parity, 311)):
            for dc in range(-9, 10):
                for dr in range(-9, 10):
                    a = _gap(*origine, dc, dr)
                    b = _gap(col, row, dc, dr)
                    if a > THR + 1.0 or b > THR + 1.0:
                        continue          # hors du domaine où la mesure est garantie exacte
                    mesures += 1
                    worst = max(worst, abs(a - b))
    assert mesures > 100, "prémisse : le balayage ne compare presque rien"
    assert worst < EZ_KERNEL_TIE_EPS_NORM, (
        f"écart noyau ↔ position réelle {worst:.3e} >= EPS {EZ_KERNEL_TIE_EPS_NORM} pour "
        f"{mover_shape}/{mover_size} orient={orient} : une case peut être tranchée depuis le "
        "noyau alors que l'exécution la classera de l'autre côté du seuil"
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
    for col in range(170, 200):
        for row in range(195, 240):
            mover = _socle(*MOVER, col, row)
            engaged = any(
                euclidean_edge_distance(mover, e, max_distance=THR) <= THR for e in enemy_socles
            )
            if bool(mask[col, row]) != engaged:
                desaccords.append((col, row, bool(mask[col, row]), engaged))
    assert not desaccords, f"masque et règle divergent sur {len(desaccords)} ancres : {desaccords[:5]}"


def test_the_mask_agrees_with_the_rule_on_flat_edged_bases(euclidean):
    """MÊME balayage, mais sur deux socles CARRÉS — le seul cas où l'ambiguïté existe.

    Deux arêtes parallèles alignées sur la grille produisent des clairances RIGOUREUSEMENT
    égales au seuil : le noyau, mesuré à une origine canonique, et l'exécution, mesurée à la
    position réelle, tombent alors des deux côtés d'une égalité flottante. C'est
    `_resolve_ez_ties_exactly` qui les réconcilie ; sans elle ce balayage compte 41 désaccords.
    Le témoin oval↔rond du test précédent, lui, ne produit AUCUNE ambiguïté : il resterait vert.
    """
    mover_geom, enemy_geom = ("square", 10), ("square", 6)
    models = WITNESS_ENEMY_MODELS
    gs = _state(models)
    entry = {"id": "5", "player": 1, "BASE_SHAPE": enemy_geom[0], "BASE_SIZE": enemy_geom[1],
             "orientation": 0, "occupied_hexes_by_model": dict(models)}
    mask = _compute_mover_ez_forbidden_mask(
        gs, {"id": "105", "BASE_SHAPE": mover_geom[0], "BASE_SIZE": mover_geom[1],
             "orientation": 0},
        [("5", entry)], EZ, BOARD[0], BOARD[1],
    )
    enemy_socles = [_socle(*enemy_geom, c, r) for c, r in models.values()]
    desaccords = []
    for col in range(165, 205):
        for row in range(200, 245):
            mover = _socle(*mover_geom, col, row)
            engaged = any(
                euclidean_edge_distance(mover, e, max_distance=THR) <= THR for e in enemy_socles
            )
            if bool(mask[col, row]) != engaged:
                desaccords.append((col, row, bool(mask[col, row]), engaged))
    assert not desaccords, (
        f"masque et règle divergent sur {len(desaccords)} ancres à socles carrés : "
        f"{desaccords[:5]} — les égalités flottantes ne sont plus re-mesurées"
    )


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
