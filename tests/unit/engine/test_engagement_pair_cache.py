"""Verrou du cache d'engagement par paire (`engine.spatial_relations`).

Ce cache a UN SEUL mode d'échec, et il est silencieux : si son empreinte oublie un champ que la
mesure lit, deux états de jeu différents partagent une entrée et le moteur rend un verdict
d'engagement faux — sans erreur, sans trace. C'est exactement la forme de la régression §0.18
(cache de la carte de cellules clé sur `_unit_move_version`, qu'un chemin d'écriture ne bumpait
pas : carte périmée servie, divergence masque/exécution).

D'où deux familles de tests, et pas une :
- `test_empreinte_couvre_*` — ÉNUMÈRE les champs. Un scénario, si bien choisi soit-il, ne prouve
  rien sur le champ qu'il n'a pas fait varier.
- `test_cache_ne_sert_pas_de_verdict_perime` — vérifie le comportement de bout en bout, sur la
  mutation EN PLACE que le moteur pratique réellement (`_recompute_squad_occupied_hexes` réécrit
  les clés de l'entrée, il ne la remplace pas).
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from engine import spatial_relations as sr


def _entry(**overrides: Any) -> Dict[str, Any]:
    """Entrée-cache minimale mais COMPLÈTE : les trois clés verticales sont présentes, donc la
    mesure passe par le chemin 3D — celui qui lit le plus de champs."""
    entry: Dict[str, Any] = {
        "id": "1",
        "col": 10, "row": 10,
        "occupied_hexes": {(10, 10)},
        "occupied_hexes_by_model": {"m1": (10, 10)},
        "floor_height_by_model": {"m1": 0.0},
        "MODEL_HEIGHT": 2.5,
        "BASE_SHAPE": "round",
        "BASE_SIZE": 1,
        "orientation": 0,
    }
    entry.update(overrides)
    return entry


#: Chaque champ de l'empreinte, avec une valeur DIFFÉRENTE de celle de `_entry`. La liste est le
#: test : elle doit rester alignée sur `_engagement_entry_fingerprint`, dans les DEUX sens —
#: `test_liste_des_champs_alignee_sur_l_empreinte` ferme le sens retour.
_CHAMPS_LUS = {
    "col": 11,
    "row": 11,
    "occupied_hexes": {(12, 12)},
    "occupied_hexes_by_model": {"m1": (12, 12)},
    "floor_height_by_model": {"m1": 9.0},
    "MODEL_HEIGHT": 4.0,
    "BASE_SHAPE": "rectangle",
    "BASE_SIZE": 3,
    "orientation": 2,
}


@pytest.mark.parametrize("champ,nouvelle_valeur", sorted(_CHAMPS_LUS.items()))
def test_empreinte_couvre_chaque_champ_lu(champ: str, nouvelle_valeur: Any) -> None:
    """Faire varier N'IMPORTE LEQUEL des champs lus doit changer l'empreinte.

    Un champ absent de l'empreinte ne se voit pas au comportement : il faut deux positions qui
    tombent du même côté du seuil pour que le bug se manifeste, ce qu'un test de scénario ne
    garantit pas. On teste donc la propriété directement, champ par champ.
    """
    base = sr._engagement_entry_fingerprint(_entry())
    modifiee = sr._engagement_entry_fingerprint(_entry(**{champ: nouvelle_valeur}))
    assert base != modifiee, f"le champ {champ!r} n'entre pas dans l'empreinte du cache"


def test_liste_des_champs_alignee_sur_l_empreinte() -> None:
    """Ferme le sens RETOUR du verrou ci-dessus.

    `test_empreinte_couvre_chaque_champ_lu` prouve que chaque champ de `_CHAMPS_LUS` compte. Il ne
    dit rien du contraire : ajouter un composant à l'empreinte sans l'ajouter à `_CHAMPS_LUS`
    laisserait tout vert, et le champ ne serait jamais éprouvé — le lecteur croirait pourtant à un
    filet complet, puisque la liste se présente comme l'énumération des champs lus.

    L'empreinte est un tuple positionnel : comparer les LONGUEURS suffit et ne suppose rien de
    l'ordre. Si ce test casse, c'est qu'un composant a été ajouté ou retiré — il faut mettre
    `_CHAMPS_LUS` à jour, pas relâcher l'égalité.
    """
    assert len(sr._engagement_entry_fingerprint(_entry())) == len(_CHAMPS_LUS)


def test_poids_du_cache_est_borne_en_octets() -> None:
    """Le cache est borné en POIDS, pas en nombre d'entrées — une clé pèse de 2,5 kB à 43 kB selon
    la résolution et la taille d'escouade. Un plafond en nombre laissait passer 2,2 GB à x5, ×48
    processus d'entraînement. On vérifie ici que le compteur suit bien les insertions et que la
    purge le remet à zéro : sans ça, la borne dérive et ne borne plus rien.
    """
    sr._EZ_PAIR_CACHE.clear()
    sr._EZ_WEIGHT["items"] = 0
    a = _entry(id="1", col=10, row=10)
    b = _entry(id="2", col=11, row=10,
               occupied_hexes={(11, 10)}, occupied_hexes_by_model={"m2": (11, 10)},
               floor_height_by_model={"m2": 0.0})
    sr.entries_in_engagement_zone(a, b, engagement_zone=2, metric="hex")
    apres_une_insertion = sr._EZ_WEIGHT["items"]
    assert apres_une_insertion > 0, "le poids inséré n'est pas comptabilisé"

    # Une TOUCHE ne doit rien ajouter : compter deux fois la même entrée ferait purger un cache
    # qui tient largement dans son budget.
    sr.entries_in_engagement_zone(a, b, engagement_zone=2, metric="hex")
    assert sr._EZ_WEIGHT["items"] == apres_une_insertion

    # Budget ramené à presque rien : l'insertion suivante doit purger ET remettre le compteur à
    # la seule entrée conservée.
    budget = sr._EZ_PAIR_CACHE_MAX_BYTES
    try:
        sr._EZ_PAIR_CACHE_MAX_BYTES = 1
        sr.entries_in_engagement_zone(a, b, engagement_zone=7, metric="hex")
    finally:
        sr._EZ_PAIR_CACHE_MAX_BYTES = budget
    assert len(sr._EZ_PAIR_CACHE) == 1
    assert sr._EZ_WEIGHT["items"] == apres_une_insertion


def test_garde_fou_en_nombre_purge_aussi() -> None:
    """Second verrou de la borne : le compteur de poids est incrémenté HORS VERROU, et le serveur
    Flask tourne en `threaded=True` — deux aperçus PvP concurrents peuvent perdre un incrément et
    retarder la purge indéfiniment. Le plafond en NOMBRE d'entrées ne dépend d'aucun compteur
    partagé : il relit `len()`, donc il tient même si le poids a dérivé."""
    sr._EZ_PAIR_CACHE.clear()
    sr._EZ_WEIGHT["items"] = 0
    a = _entry(id="1", col=10, row=10)
    b = _entry(id="2", col=11, row=10,
               occupied_hexes={(11, 10)}, occupied_hexes_by_model={"m2": (11, 10)},
               floor_height_by_model={"m2": 0.0})
    sr.entries_in_engagement_zone(a, b, engagement_zone=2, metric="hex")
    # Poids SABOTÉ à zéro : c'est exactement ce que produit une suite d'incréments perdus. Seul
    # le garde-fou en nombre peut encore déclencher la purge.
    sr._EZ_WEIGHT["items"] = 0
    maxi = sr._EZ_MAX_ENTRIES
    try:
        sr._EZ_MAX_ENTRIES = 1
        sr.entries_in_engagement_zone(a, b, engagement_zone=7, metric="hex")
    finally:
        sr._EZ_MAX_ENTRIES = maxi
    assert len(sr._EZ_PAIR_CACHE) == 1


def test_empreinte_distingue_cle_absente_et_cle_vide() -> None:
    """ABSENTE ≠ PRÉSENTE-ET-VIDE : l'une est l'entrée synthétique légitime (mesurée à plat),
    l'autre une escouade morte restée en cache (état corrompu, `_require_measurable_entry` lève).
    Les confondre ferait partager une entrée de cache à deux états qui ne se mesurent pas pareil."""
    sans_cle = _entry()
    del sans_cle["occupied_hexes_by_model"]
    vide = _entry(occupied_hexes_by_model={})
    assert (
        sr._engagement_entry_fingerprint(sans_cle)
        != sr._engagement_entry_fingerprint(vide)
    )


def test_empreinte_supporte_un_socle_rectangulaire() -> None:
    """`BASE_SIZE` est un scalaire pour un socle rond mais une LISTE pour un rectangulaire — donc
    non hashable telle quelle. Ce défaut est INVISIBLE à x1 (roster tout rond) : il est sorti en
    `TypeError: unhashable type: 'list'` au premier run à x5."""
    fp = sr._engagement_entry_fingerprint(_entry(BASE_SHAPE="rectangle", BASE_SIZE=[2, 3]))
    hash(fp)  # lève si un composant est non hashable
    assert fp != sr._engagement_entry_fingerprint(
        _entry(BASE_SHAPE="rectangle", BASE_SIZE=[3, 2])
    )


def test_cache_ne_sert_pas_de_verdict_perime() -> None:
    """Bout en bout, sur la mutation EN PLACE que le moteur pratique réellement.

    Une entrée `units_cache` n'est pas remplacée quand une figurine bouge : ses clés sont
    réécrites (`_recompute_squad_occupied_hexes`). En production, `_touch_unit_los` est appelé
    après chaque écriture et vide `entry["_ez_fp"]` (item 1.8). Le test mute en direct mais
    efface aussi `_ez_fp` pour simuler le comportement moteur fidèlement.
    """
    sr._EZ_PAIR_CACHE.clear()
    a = _entry(id="1", col=10, row=10)
    b = _entry(id="2", col=11, row=10,
               occupied_hexes={(11, 10)}, occupied_hexes_by_model={"m2": (11, 10)},
               floor_height_by_model={"m2": 0.0})

    adjacent = sr.entries_in_engagement_zone(a, b, engagement_zone=2, metric="hex")
    assert adjacent is True

    # Même OBJET `b`, muté en place et emmené très loin — exactement ce que fait le moteur.
    # `_touch_unit_los` efface `_ez_fp` après chaque écriture de position (item 1.8) ; on
    # reproduit ce nettoyage ici pour que le test reste un témoin fidèle du chemin de prod.
    b["col"] = 40
    b["occupied_hexes"] = {(40, 10)}
    b["occupied_hexes_by_model"] = {"m2": (40, 10)}
    b.pop("_ez_fp", None)
    apres = sr.entries_in_engagement_zone(a, b, engagement_zone=2, metric="hex")
    assert apres is False, "verdict périmé servi depuis le cache après mutation en place"

    # Et le retour en arrière redonne le premier verdict : la clé identifie l'état, pas l'ordre
    # des appels.
    b["col"] = 11
    b["occupied_hexes"] = {(11, 10)}
    b["occupied_hexes_by_model"] = {"m2": (11, 10)}
    b.pop("_ez_fp", None)
    assert sr.entries_in_engagement_zone(a, b, engagement_zone=2, metric="hex") is True


def test_cache_separe_les_zones_et_les_metriques() -> None:
    """La zone d'engagement et la métrique ne sont pas des propriétés des entrées : deux appels
    sur la MÊME paire avec une zone différente doivent donner deux verdicts, pas un cache partagé."""
    sr._EZ_PAIR_CACHE.clear()
    a = _entry(id="1", col=10, row=10)
    b = _entry(id="2", col=14, row=10,
               occupied_hexes={(14, 10)}, occupied_hexes_by_model={"m2": (14, 10)},
               floor_height_by_model={"m2": 0.0})
    assert sr.entries_in_engagement_zone(a, b, engagement_zone=1, metric="hex") is False
    assert sr.entries_in_engagement_zone(a, b, engagement_zone=10, metric="hex") is True


def test_cache_separe_le_seuil_vertical() -> None:
    """Le seuil vertical est résolu depuis le config quand l'appelant ne l'épingle pas. Deux
    seuils différents sur la même paire = deux verdicts ; les confondre ferait lire à l'analyzer
    le seuil du jour au lieu de celui de son journal."""
    sr._EZ_PAIR_CACHE.clear()
    a = _entry(id="1", col=10, row=10, floor_height_by_model={"m1": 0.0})
    b = _entry(id="2", col=11, row=10,
               occupied_hexes={(11, 10)}, occupied_hexes_by_model={"m2": (11, 10)},
               floor_height_by_model={"m2": 30.0})
    serre = sr.entries_in_engagement_zone(
        a, b, engagement_zone=2, metric="hex", vertical_zone_inches=1.0
    )
    large = sr.entries_in_engagement_zone(
        a, b, engagement_zone=2, metric="hex", vertical_zone_inches=100.0
    )
    assert serre is False and large is True


def test_purge_ne_change_aucun_verdict() -> None:
    """Le cache est borné par purge totale. Une purge doit être invisible du dehors : elle enlève
    des entrées devenues inutiles, jamais de l'information."""
    sr._EZ_PAIR_CACHE.clear()
    a = _entry(id="1", col=10, row=10)
    b = _entry(id="2", col=11, row=10,
               occupied_hexes={(11, 10)}, occupied_hexes_by_model={"m2": (11, 10)},
               floor_height_by_model={"m2": 0.0})
    avant = sr.entries_in_engagement_zone(a, b, engagement_zone=2, metric="hex")
    sr._EZ_PAIR_CACHE.clear()
    assert sr.entries_in_engagement_zone(a, b, engagement_zone=2, metric="hex") == avant
