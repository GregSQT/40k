"""Enumeration ennemie de la phase de COMBAT : une unite hors table n'en fait jamais partie.

Pourquoi un fichier a part, et pourquoi une situation CONSTRUITE. Les consommateurs de la phase
de combat portaient chacun leur copie de la meme boucle « ennemi, pas moi, sur la table », dont
une CLOSURE (`_start_engagements`, dans `pile_in_autoplace_plan`) qu'aucun test ne peut appeler
isolement. Aucune trajectoire de `test_reserves_full_episode.py` ne les atteignait : recopier le
filtre dans chacune aurait donc produit du code non verifie — un test qui passe avec le defaut
remis vaut test absent.

Toutes passent desormais par la source unique `enemy_entries_on_battlefield`
(`engine/spatial_relations.py`), qui est ce que ce fichier verrouille. C'est elle qui rend la
closure couverte : celle-ci n'a plus d'enumeration propre, il n'est plus necessaire de l'appeler
pour prouver son filtre.

L'etat est bati a la main plutot que joue : la regle 03.04 se verifie sur des positions precises,
pas sur ce qu'une graine veut bien produire.
"""
from __future__ import annotations

from typing import Any, Dict

import pytest

ACTING = 1
FOE = 2


def _entry(col: int, row: int, player: int, *, off_table: bool = False) -> Dict[str, Any]:
    """Entree-cache minimale. HORS TABLE = sentinelle (-1,-1) + empreinte VIDE, ce que le moteur
    produit reellement pour une unite en reserves (20.01) ou pas encore posee — et non une entree
    absente, qui serait le cas « morte »."""
    return {
        "col": -1 if off_table else col,
        "row": -1 if off_table else row,
        "player": player,
        "BASE_SHAPE": "round",
        "BASE_SIZE": 1,
        "orientation": 0,
        "occupied_hexes": set() if off_table else {(col, row)},
    }


@pytest.fixture
def gs() -> Dict[str, Any]:
    """Un mover, un ennemi POSE au contact, un ennemi HORS TABLE, un allie (jamais enumere)."""
    return {
        "inches_to_subhex": 1,
        "units_cache": {
            "mover": _entry(5, 5, ACTING),
            "ennemi_pose": _entry(6, 5, FOE),
            "ennemi_reserve": _entry(0, 0, FOE, off_table=True),
            "allie": _entry(4, 5, ACTING),
        },
        "config": {
            "game_rules": {
                "engagement_zone": 1,
                "engagement_zone_vertical": 5,
                "max_base_size_hex": 35,
                # Portee du pile-in (12.03) : lue par `pile_in_targets_within_range`.
                "pile_in_target_range": 3,
            },
            "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
        },
    }


def test_the_shared_enumeration_drops_off_table_and_keeps_the_rest(gs: Dict[str, Any]) -> None:
    """Source unique (`enemy_entries_on_battlefield`) : elle ecarte le hors-table, soi-meme et
    les allies — et RIEN d'autre.

    Le temoin `ennemi_pose` est la borne anti-vert-vacant : une enumeration qui rendrait le vide
    satisfairait « le hors-table est ecarte » sans rien prouver.
    """
    from engine.spatial_relations import enemy_entries_on_battlefield

    got = {
        str(eid)
        for eid, _ce in enemy_entries_on_battlefield(
            gs["units_cache"], ACTING, exclude_id="mover"
        )
    }
    assert got == {"ennemi_pose"}, (
        f"enumeration = {sorted(got)} ; attendu le seul ennemi POSE. Vide -> elle ne mesure plus "
        "rien ; avec 'ennemi_reserve' -> le filtre hors-table est tombe ; avec 'allie' ou "
        "'mover' -> le test de camp ou l'exclusion de soi est tombe."
    )


def test_engagement_probe_ignores_an_off_table_enemy(gs: Dict[str, Any]) -> None:
    """`_fight_entry_in_engagement_with_any_enemy` : le hors-table ne cree pas d'engagement.

    Deux appels, pas un : avec l'ennemi pose on prouve que la sonde DETECTE (sinon un False
    constant passerait), sans lui on prouve que la reserve seule n'en cree aucun.
    """
    from engine.phase_handlers.fight_handlers import (
        _fight_entry_in_engagement_with_any_enemy,
    )

    unit = {"id": "mover", "player": ACTING}
    synth = gs["units_cache"]["mover"]

    assert _fight_entry_in_engagement_with_any_enemy(gs, unit, synth), (
        "l'ennemi POSE en (6,5) est adjacent au mover en (5,5) : la sonde doit le voir, sinon "
        "l'assertion suivante serait vraie sans rien prouver"
    )

    del gs["units_cache"]["ennemi_pose"]
    assert not _fight_entry_in_engagement_with_any_enemy(gs, unit, synth), (
        "seule reste une unite HORS TABLE : elle n'est engagee avec personne (03.04 mesure entre "
        "socles poses), et la mesurer ferait lever `_require_measurable_entry`"
    )


def test_engaged_with_lists_only_on_table_enemies(gs: Dict[str, Any]) -> None:
    """`_fight_units_engaged_with` : la liste ne contient que des ennemis POSES."""
    from engine.phase_handlers.fight_handlers import _fight_units_engaged_with

    engaged = _fight_units_engaged_with(gs, {"id": "mover", "player": ACTING})
    assert engaged == ["ennemi_pose"], (
        f"engages = {engaged} ; attendu ['ennemi_pose'] seul. Une liste vide signifierait que la "
        "fonction ne detecte plus rien ; 'ennemi_reserve' qu'une unite hors table est engagee."
    )


# ---------------------------------------------------------------------------
# Les consommateurs directement appelables, un par un.
#
# La source unique ci-dessus est verrouillee, mais un consommateur peut toujours REPARTIR sur une
# boucle brute : ces tests appellent chaque fonction sur l'etat construit et exigent qu'elle
# reponde sans lever ET qu'elle ne compte que l'ennemi POSE. Chacun porte son temoin — un
# resultat vide satisferait « la reserve est ecartee » sans rien mesurer.
# ---------------------------------------------------------------------------

def _unit(uid: str, player: int, col: int, row: int) -> Dict[str, Any]:
    return {
        "id": uid, "player": player, "col": col, "row": row,
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0,
        "RNG_WEAPONS": [{"NB": 1, "DMG": 1, "RNG": 12}], "CC_WEAPONS": [],
    }


def test_hex_contact_probe_ignores_an_off_table_enemy(gs: Dict[str, Any]) -> None:
    """`_fight_footprint_has_enemy_hex_contact` — contact A strict (empreintes <= 1)."""
    from engine.phase_handlers.fight_handlers import (
        _fight_footprint_has_enemy_hex_contact,
    )

    unit = _unit("mover", ACTING, 5, 5)
    assert _fight_footprint_has_enemy_hex_contact(gs, unit, {(5, 5)}), (
        "l'ennemi POSE en (6,5) est au contact de (5,5) : sans ce constat, l'assertion suivante "
        "serait vraie sans rien prouver"
    )
    del gs["units_cache"]["ennemi_pose"]
    assert not _fight_footprint_has_enemy_hex_contact(gs, unit, {(5, 5)}), (
        "seule reste une unite HORS TABLE : elle n'est au contact de rien"
    )


def test_pile_in_range_query_ignores_an_off_table_enemy(gs: Dict[str, Any]) -> None:
    """`pile_in_targets_within_range` et `_fight_v11_enemies_within_range` — requetes de portee."""
    from engine.phase_handlers.fight_handlers import (
        _fight_v11_enemies_within_range,
        pile_in_targets_within_range,
    )

    unit = _unit("mover", ACTING, 5, 5)
    assert pile_in_targets_within_range(gs, unit) == ["ennemi_pose"], (
        "seul l'ennemi POSE est a portee de pile-in ; une liste vide signifierait que la requete "
        "ne mesure plus rien, 'ennemi_reserve' que le filtre est tombe"
    )
    assert _fight_v11_enemies_within_range(gs, unit, 12) == ["ennemi_pose"], (
        "idem pour la requete de portee 12.08"
    )


def test_closest_enemy_snapshot_ignores_an_off_table_enemy(gs: Dict[str, Any]) -> None:
    """`_fight_pile_in_closest_enemy_snapshot` — les DEUX boucles (pre-filtre d_cap + mesure).

    Le pre-filtre `d_cap` mesurait `|col-(-1)| + |row-(-1)|` sur la sentinelle : il pouvait donc
    borner la recherche sur un ennemi qui n'existe pas, avant meme la mesure d'empreinte.
    """
    from engine.phase_handlers.fight_handlers import (
        _fight_pile_in_closest_enemy_snapshot,
    )

    d_min, ids = _fight_pile_in_closest_enemy_snapshot(gs, _unit("mover", ACTING, 5, 5))
    assert ids == ["ennemi_pose"], (
        f"plus proches = {ids} ; attendu le seul ennemi POSE (a distance {d_min})"
    )


def test_opposing_enemies_exist_ignores_an_off_table_enemy(gs: Dict[str, Any]) -> None:
    """`_fight_opposing_enemies_exist` — « y a-t-il un adversaire ? ».

    Pas de geometrie ici, donc PAS de crash : c'est un verdict FAUX. Une armee entierement en
    reserves rendait « des adversaires existent », alors qu'il n'y a personne a combattre (12.04
    porte sur les figurines sur le champ de bataille).
    """
    from engine.phase_handlers.fight_handlers import _fight_opposing_enemies_exist

    unit = _unit("mover", ACTING, 5, 5)
    assert _fight_opposing_enemies_exist(gs, unit), "l'ennemi POSE existe : constat prealable"
    del gs["units_cache"]["ennemi_pose"]
    assert not _fight_opposing_enemies_exist(gs, unit), (
        "toutes les unites adverses sont hors table : aucun adversaire n'est present sur la table"
    )


def test_a_friendly_off_table_blocks_no_ranged_shot(gs: Dict[str, Any]) -> None:
    """Volet TIR du meme motif : `_friendly_engagement_blocks_ranged_shot` (10.05).

    POURQUOI CETTE FONCTION ET PAS `_has_los_to_enemies_within_range`. La 1re version de ce test
    prenait cette derniere comme « jumeau tir/melee » : les deux modules en portaient une copie
    mot pour mot. Elles n'avaient AUCUN appelant, ni en Python, ni dans le frontend — du code mort,
    corrige et teste, ce qui donne une couverture de facade. Les deux copies ont ete supprimees.
    `_friendly_engagement_blocks_ranged_shot` est, elle, appelee depuis 4 sites de production.

    La regle : un tir sur une cible non adjacente est BLOQUE si un allie du tireur est au contact
    de cette cible. Une alliee pas encore posee (deploiement) ou en reserves (20.01) n'est au
    contact de rien : elle ne bloque aucun tir, et la mesurer ferait lever.
    """
    from engine.phase_handlers.shooting_handlers import (
        _friendly_engagement_blocks_ranged_shot,
    )

    # Le tireur est `mover` (joueur ACTING) ; `allie` est en (4,5), la cible en (5,5).
    cible = _entry(5, 5, FOE)
    gs["units_cache"]["cible"] = cible

    assert _friendly_engagement_blocks_ranged_shot(
        gs, "mover", ACTING, cible, "cible", False, gs["units_cache"]
    ), (
        "l'allie POSE en (4,5) est au contact de la cible en (5,5) : le tir DOIT etre bloque, "
        "sinon l'assertion suivante serait vraie sans rien prouver"
    )

    # Le seul allie restant est HORS TABLE : plus rien ne bloque.
    gs["units_cache"]["allie"] = _entry(4, 5, ACTING, off_table=True)
    assert not _friendly_engagement_blocks_ranged_shot(
        gs, "mover", ACTING, cible, "cible", False, gs["units_cache"]
    ), (
        "la seule alliee est HORS TABLE : elle n'est bord-a-bord avec personne et ne peut bloquer "
        "aucun tir (10.05)"
    )


def test_a_unit_without_a_camp_raises_instead_of_enumerating_its_allies(
    gs: Dict[str, Any],
) -> None:
    """Une unite sans `player` doit LEVER, pas produire un verdict.

    Le test de camp de `_opposing_on_table_entries` est `int(ce["player"]) == mover_player`.
    Quatre appelants calculaient leur camp `int(unit["player"]) if ... is not None else None` :
    a None, l'egalite n'est jamais vraie, donc RIEN n'etait saute et les ALLIEES etaient rendues
    comme ennemies. Un repli qui convertit une donnee invalide en verdict faux — l'inverse de la
    regle du depot, qui exige l'erreur explicite.

    Le cas est inatteignable en production (le chargeur exige la cle, aucune config ne porte
    `"player": null`). Ce verrou porte donc sur le CONTRAT, pas sur un bug vivant : il devient
    rouge si quelqu'un rehabilite le repli, puisque l'ancien code rendait `True` ici — l'alliee en
    (4,5) est au contact de (5,5) et etait comptee comme ennemie.
    """
    from engine.phase_handlers.fight_handlers import (
        _fight_footprint_has_enemy_hex_contact,
    )

    sans_camp = _unit("mover", ACTING, 5, 5)
    del sans_camp["player"]

    with pytest.raises(Exception) as exc:
        _fight_footprint_has_enemy_hex_contact(gs, sans_camp, {(5, 5)})
    assert "player" in str(exc.value), (
        f"l'erreur doit nommer la cle manquante, obtenu : {exc.value!r}"
    )
