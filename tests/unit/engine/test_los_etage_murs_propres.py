"""13.11 — une figurine à l'étage ignore les murs de SA ruine ; sa camarade au sol, non.

Règle lue (13 Terrain.pdf, 13.11 Solid) : la LoS ne se trace pas à travers les ouvertures ≤ 3" du
sol ; au-dessus (étage à 3"), elle se trace normalement. Trou de couverture fermé ici : aucun test
ne référençait `_walls_around_occupied_floor` ni son cache `_elevated_ignored_walls_cache`.

Fixture : ruine R (colonnes 28..34, floor level 1 à 3", mur dense colonne 34) ; escouade tireuse
de deux figurines — E (31,20) SUR le floor de R au niveau 1, G (27,20) au sol HORS de R, derrière
le mur (colonne 34 entre G et la cible) ; cible T (50,20) au sol.
"""

from __future__ import annotations

from tests.unit.engine.test_los_symetrie_etage_sol import can_see, make_engine

_E = (31, 20)  # sur le floor de R, niveau 1
_G = (27, 20)  # au sol, hors de R, derrière le mur colonne 34


def test_l_escouade_voit_par_sa_figurine_elevee_seule():
    eng = make_engine(s_level=0, s_positions=[_E, _G], s_levels=[1, 0])
    gs = eng.game_state
    assert can_see(eng, "1", "2") is True, "la figurine à l'étage doit voir par-dessus son mur"
    # Mécanisme : les murs ignorés sont mémoïsés PAR FIGURINE (clé « m:<mid> »), non vides pour E
    # (niveau 1 sur le floor), vides pour G (au sol → jamais calculés, ou ∅).
    cache = gs["_elevated_ignored_walls_cache"]
    e_mid, g_mid = gs["squad_models"]["1"]
    assert cache[f"m:{e_mid}"][1], "E à l'étage : ses murs de ruine doivent être retirés"
    assert not cache.get(f"m:{g_mid}", (None, set()))[1], "G au sol : aucun mur retiré"


def test_la_figurine_au_sol_seule_reste_bloquee():
    eng = make_engine(s_level=0, s_positions=[_G])
    assert can_see(eng, "1", "2") is False


def test_les_deux_au_sol_l_escouade_ne_voit_rien():
    """Contre-épreuve : sans étage, le même mur bloque les deux figurines."""
    eng = make_engine(s_level=0, s_positions=[_E, _G], s_levels=[0, 0])
    assert can_see(eng, "1", "2") is False
