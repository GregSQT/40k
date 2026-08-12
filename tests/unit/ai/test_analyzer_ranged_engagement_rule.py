"""Table de vérité de 10.06 / 04.02 / 17.03, côté analyzer — un seul énoncé, deux lecteurs.

`handle_shoot` (qui compte les fautes) et `handle_wait` (qui écarte du pool de cibles ce qu'un tir
n'aurait pas eu le droit de viser) avaient chacun leur transcription de la même règle, à quelques
lignes d'écart. La version WAIT ignorait le volet CIBLES de 10.06 : un tireur engagé, pistolet au
poing, gardait dans son pool les unités avec lesquelles il n'était PAS engagé.

Cet écart-là ne produisait aucun verdict faux — une ligne WAIT n'inflige pas de dégâts, et l'unité
avec laquelle on est engagé reste de toute façon une cible valide, donc le compartiment
`wait_with_targets` ne bouge pas. C'est le motif du dépôt : « pas encore faux » n'est pas une
propriété qui se maintient toute seule, et la prochaine évolution de la règle serait partie d'un
seul côté. D'où la source unique — et cette table, qui la rend lisible sans ouvrir les handlers.
"""
from __future__ import annotations

import pytest

from ai.analyzer_phases.shoot_handler import ranged_engagement_verdict

_LIBRE = dict(
    shooter_engaged=False,
    shooter_is_monster_or_vehicle=False,
    shooter_engaged_with_target=False,
    target_engaged=False,
    target_is_monster_or_vehicle=False,
    weapon_is_close_quarters=False,
)


def _verdict(**overrides):
    return ranged_engagement_verdict(**{**_LIBRE, **overrides})


def test_tir_libre_aucun_interdit():
    """Prémisse : hors engagement, rien n'interdit rien. Sans elle, tout le reste passerait."""
    assert not _verdict().forbids_shot()


def test_tireur_engage_arme_non_close_quarters():
    """10.06, volet ARMES."""
    v = _verdict(shooter_engaged=True)
    assert v.engaged_with_non_close_quarters
    assert v.forbids_shot()


def test_tireur_engage_monster_vehicle_tire_avec_toutes_ses_armes():
    """10.06 « OR is a MONSTER/VEHICLE unit » — l'exemption porte sur le TIREUR."""
    v = _verdict(shooter_engaged=True, shooter_is_monster_or_vehicle=True)
    assert not v.forbids_shot()


def test_tireur_engage_pistolet_sur_une_unite_avec_laquelle_il_ne_l_est_pas():
    """10.06, volet CIBLES — c'est précisément ce que `handle_wait` n'appliquait pas."""
    v = _verdict(shooter_engaged=True, weapon_is_close_quarters=True)
    assert v.close_quarters_at_unengaged
    assert v.forbids_shot()


def test_tireur_engage_pistolet_sur_l_unite_avec_laquelle_il_l_est():
    """Le tir à bout portant légal : engagé, arme [CLOSE-QUARTERS], sur SA cible."""
    v = _verdict(
        shooter_engaged=True, weapon_is_close_quarters=True, shooter_engaged_with_target=True
    )
    assert not v.forbids_shot()


def test_cible_engagee_avec_un_allie_du_tireur():
    """04.02 : « you can only select enemy units that are not engaged with any of your units »."""
    v = _verdict(target_engaged=True)
    assert v.target_engaged_untargetable
    assert v.forbids_shot()


def test_cible_engagee_monster_vehicle_tireur_libre():
    """17.03 : la cible M/V engagée reste ciblable — mais l'exemption ne vise QUE la cible."""
    v = _verdict(target_engaged=True, target_is_monster_or_vehicle=True)
    assert not v.forbids_shot()


def test_cible_engagee_monster_vehicle_mais_tireur_engage():
    """Encadré de 17.03 : un tireur non-M/V engagé reste borné au close-quarters.

    Exempter sur la seule nature de la cible désarmait le contrôle dès qu'un véhicule ennemi était
    au contact — c'est un défaut vécu, pas une hypothèse.
    """
    v = _verdict(shooter_engaged=True, target_engaged=True, target_is_monster_or_vehicle=True)
    assert v.engaged_with_non_close_quarters
    assert v.target_engaged_untargetable


def test_les_deux_lecteurs_lisent_bien_cette_fonction():
    """VERROU d'usage : une transcription locale rendrait ce test ROUGE.

    Le défaut réparé ici n'est pas un mauvais calcul, c'est un DOUBLON — un test de valeurs ne
    l'aurait donc jamais attrapé. Ce qu'on verrouille, c'est le nombre de lecteurs.
    """
    import inspect

    from ai.analyzer_phases import shoot_handler

    source = inspect.getsource(shoot_handler)
    assert source.count("ranged_engagement_verdict(") >= 3, (
        "attendu : la définition + un appel dans handle_shoot + un appel dans handle_wait"
    )
    for handler in (shoot_handler.handle_shoot, shoot_handler.handle_wait):
        assert "ranged_engagement_verdict" in inspect.getsource(handler), (
            f"{handler.__name__} a repris une transcription locale de 10.06/17.03"
        )
