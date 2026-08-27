"""VERROU : le preview de move regarde l'EMPREINTE d'un socle oval, pas seulement son ancre.

`movement_preview_move_plan` classait le socle en mono-hex avec `not isinstance(base_size, int)`.
Un socle NON ROND porte une PAIRE `[grand axe, petit axe]`, donc le predicat repondait « oui » —
`footprints` tombait a `{ancre}` et les quatre controles qui en dependent (`fp_wall`, `fp_other`,
`fp_intra`, EZ) ne regardaient plus qu'UNE case sur les 23 que couvre le socle. Le commit ne
regarde que `preview["can_validate"]`, donc rien en aval ne rattrapait la maille.

Le jumeau du MEME fichier (`movement_build_model_destinations_pool`) avait deja ete corrige et
nommait le defaut dans son commentaire : les deux predicats vivent maintenant dans
`hex_utils.socle_is_single_hex`, pour que la divergence ne puisse pas revenir une 3e fois.

Pourquoi une escouade AMIE et pas un mur : `can_move_through_friendly_model` vaut `true`
(config/game_config.json), donc une figurine amie n'est PAS un obstacle de trajet. Le champ
any-angle, lui, dilate deja ses obstacles par l'empreinte orientee et masquait le defaut sur un
mur — `fp_other` est le SEUL rempart contre un socle pose sur une escouade amie, et c'est
exactement celui que le predicat desactivait.
"""

from typing import Any, Dict, List, Tuple

import pytest

from engine.hex_utils import precompute_footprint_offsets, socle_is_single_hex
from engine.phase_handlers.movement_handlers import (
    _move_preview_footprint_span,
    movement_preview_move_plan,
)
from tests._state_invariants import turn_state_invariants, unit_invariants

BASE_SIZE = [8, 4]  # socle oval DEJA scale (`_scale_socle`), cf. WarTrakk / LandSpeeder
START = (10, 30)
DEST = (14, 30)
MOVE = 30
ORIENTATION = 0


def _footprint_at_dest() -> set:
    off_even, off_odd = precompute_footprint_offsets("oval", BASE_SIZE, ORIENTATION)
    offs = off_even if (DEST[0] & 1) == 0 else off_odd
    return {(DEST[0] + dc, DEST[1] + dr) for dc, dr in offs}


def _covered_cell() -> Tuple[int, int]:
    """Une case SOUS le socle a destination, et jamais l'ancre : c'est tout l'ecart mesure."""
    fp = _footprint_at_dest()
    assert len(fp) > 1, "socle mono-hex : ce test n'observerait rien"
    cell = sorted(fp - {DEST})[len(fp) // 2]
    assert cell != DEST
    return cell


def _gs_with_ally_under_the_base() -> Dict[str, Any]:
    victim = _covered_cell()
    mover = {**unit_invariants(),
        "id": 1, "player": 1, "col": START[0], "row": START[1], "MOVE": MOVE,
        "HP_CUR": 1, "BASE_SIZE": BASE_SIZE, "BASE_SHAPE": "oval", "UNIT_KEYWORDS": [],
    }
    # Escouade AMIE (meme joueur, autre id) posee sous l'empreinte, PAS sur l'ancre.
    ally = {**unit_invariants(),
        "id": 2, "player": 1, "col": victim[0], "row": victim[1], "MOVE": 6,
        "HP_CUR": 1, "BASE_SIZE": 1, "BASE_SHAPE": "round", "UNIT_KEYWORDS": [],
    }
    return {**turn_state_invariants(),
        "models_cache": {
            "1#0": {"col": START[0], "row": START[1], "level": 0, "player": 1, "squad_id": "1",
                    "HP_CUR": 1, "BASE_SHAPE": "oval", "BASE_SIZE": BASE_SIZE,
                    "orientation": ORIENTATION},
            "2#0": {"col": victim[0], "row": victim[1], "level": 0, "player": 1, "squad_id": "2",
                    "HP_CUR": 1, "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0},
        },
        "squad_models": {"1": ["1#0"], "2": ["2#0"]},
        "units_cache": {
            "1": {"col": START[0], "row": START[1], "player": 1, "occupied_hexes": set(),
                  "BASE_SHAPE": "oval", "BASE_SIZE": BASE_SIZE},
            "2": {"col": victim[0], "row": victim[1], "player": 1, "occupied_hexes": {victim},
                  "BASE_SHAPE": "round", "BASE_SIZE": 1},
        },
        "units": [mover, ally],
        "unit_by_id": {"1": mover, "2": ally},
        "board_cols": 44, "board_rows": 60,
        "wall_hexes": set(),
        "enemy_adjacent_hexes_player_1": set(),
        "config": {
            "game_rules": {"engagement_zone": 2},
            "move": {"can_move_through_enemy_engagement_zone": True,
                     "can_move_through_enemy_model": False,
                     # `true` comme en config reelle : l'amie ne bloque PAS le trajet, donc
                     # seul le controle d'empreinte peut refuser ce placement.
                     "can_move_through_friendly_model": True},
        },
        "phase": "move",
        "gym_training_mode": False,
        "inches_to_subhex": 5,  # a x1 le moteur normalise tout socle en round/1
        "units_took_to_skies": set(),
        "terrain_areas": [],
    }


def test_un_socle_oval_n_est_pas_mono_hex() -> None:
    """VERT VACANT : si le predicat rendait `True`, le test suivant validerait une ancre nue."""
    assert socle_is_single_hex("oval", BASE_SIZE) is False
    assert socle_is_single_hex("square", 4) is False
    assert socle_is_single_hex("round", 1) is True
    assert socle_is_single_hex("round", 6) is False


def test_un_socle_rond_de_taille_non_scalaire_n_est_pas_mono_hex() -> None:
    """RESIDU DU PREDICAT NAIF, corrige le 2026-08-12 — la 3e occurrence de la meme divergence.

    Un `round` porte un diametre SCALAIRE (`require_scalar_base_size` refuse tout le reste). La
    branche `not isinstance(base_size, int)` qui survivait ici rendait donc `True` pour un etat
    FAUX, et le declarait mono-hex : l'appelant sautait l'expansion d'empreinte et lisait une ancre
    nue la ou `compute_occupied_hexes` LEVE. C'est le meme motif que l'oval du test precedent,
    par l'autre bout de l'union etiquetee.
    """
    for taille in ([1, 1], [2, 2], (1, 1)):
        assert socle_is_single_hex("round", taille) is False, (
            f"round/{taille!r} est un etat corrompu, pas un socle mono-hex"
        )
    with pytest.raises(ValueError):
        precompute_footprint_offsets("round", [1, 1], 0)


def test_un_socle_oval_pose_sur_une_escouade_amie_est_refuse() -> None:
    """LE VERROU. Avant le fix : `can_validate` True, socle de 23 hexes par-dessus l'amie."""
    gs = _gs_with_ally_under_the_base()
    plan: List[Tuple[str, int, int, int, int]] = [("1#0", DEST[0], DEST[1], 0, ORIENTATION)]
    res = movement_preview_move_plan(gs, "1", plan)
    assert res["can_validate"] is False, (
        f"socle oval valide alors qu'il recouvre l'escouade 2 en {_covered_cell()}"
    )
    assert res["per_model"]["1#0"] is False


def test_la_meme_destination_reste_valide_sans_personne_dessous() -> None:
    """Controle NEGATIF : sans l'amie, la destination doit passer — sinon le verrou ci-dessus
    serait satisfait par n'importe quel refus (budget, coherency, EZ) et ne prouverait rien."""
    gs = _gs_with_ally_under_the_base()
    for key in ("models_cache", "squad_models", "units_cache"):
        gs[key].pop("2#0" if key == "models_cache" else "2", None)
    gs["units"] = [u for u in gs["units"] if u["id"] != 2]
    gs["unit_by_id"].pop("2", None)
    res = movement_preview_move_plan(gs, "1", [("1#0", DEST[0], DEST[1], 0, ORIENTATION)])
    assert res["can_validate"] is True, "la destination doit etre legale sans l'escouade amie"


def test_move_preview_footprint_span_invalid_base_size_raises() -> None:
    """T1 : BASE_SIZE invalide doit lever, jamais retourner 1 silencieusement."""
    with pytest.raises(ValueError):
        _move_preview_footprint_span({"id": "u1", "BASE_SIZE": []})

    with pytest.raises(ValueError):
        _move_preview_footprint_span({"id": "u1", "BASE_SIZE": [None, "foo"]})

    with pytest.raises(ValueError):
        _move_preview_footprint_span({"id": "u1", "BASE_SIZE": "invalid"})

    assert _move_preview_footprint_span({"id": "u1", "BASE_SIZE": [60, 35]}) == 60
    assert _move_preview_footprint_span({"id": "u1", "BASE_SIZE": 32}) == 32
