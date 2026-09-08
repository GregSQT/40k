"""Le BFS géodésique hex du move, exercé par le VRAI flux PvP (plateau x1).

Ce que ce fichier verrouille et qu'aucun autre test d'intégration n'atteignait : à
``inches_to_subhex = 1`` la géométrie du move est hex (``geometry_is_hex``), donc la validation
d'un plan mesure la distance de CHEMIN — ``geodesic_move_reach`` via ``geodesic_field_for_origin``
et ``model_reach_predicate``. Toute la suite ``tests/integration/pvp/`` joue le plateau x5, où la
métrique est euclidienne : mesure du 2026-09-08 sur le flux complet, ``geodesic_move_reach`` 0
appel, ``move_transit_blocked_forms`` 0, ``_euclidean_move_field_for_model`` 15. Le chemin hex
n'était couvert que par des tests pilotant le moteur hors HTTP.

TROIS CHOIX DE CONSTRUCTION, chacun imposé par une mesure et non par une préférence :

1. UNE UNITÉ MONO-FIGURINE. Sur une escouade, la cohésion 06.02 et les zones d'engagement
   ennemies refusent les cases bien avant le trajet : balayage de 2 641 cases de pool sur
   l'unité 204 (12 figurines) — 0 case dont le verdict dépende du BFS. Une figurine seule n'a
   ni cohésion à tenir ni sœur à contourner : le trajet devient le seul juge.

2. UNE ASSERTION UNIVERSELLE, pas existentielle. « Il existe une case refusée » resterait VERTE
   avec le BFS cassé : sur l'unité 201, 18 candidates sont refusées mais 4 seulement le sont
   pour cause de trajet, les autres tombant sur l'engagement ennemi. C'est en exigeant
   qu'AUCUNE ne passe qu'une seule case redevenue joignable fait tomber le test.

3. UNE CONTRE-ÉPREUVE SUR LE POOL ENTIER. Sans elle, un refus global — budget nul, unité non
   activée, plan malformé — satisferait l'assertion universelle sans que rien ne soit mesuré.
   Elle a d'abord porté sur une seule case (``min(pool)``) : mesure du 2026-09-09, cette forme
   ne détectait la perte du contournement que sur une unité sur trois, parce qu'elle dépendait
   de la case désignée. Elle balaie donc tout le pool — 340 cases sur les trois unités, toutes
   validables en code réel.

LES DEUX PORTES SONT COUVERTES, et il en fallait deux. ``geodesic_field_for_origin`` mémoïse son
champ dans ``_move_spatial_cache`` : un ``preview_move_plan`` le calcule, et le ``commit_move_plan``
qui suit le relit sans jamais appeler ``geodesic_move_reach``. Mesure du 2026-09-09, unité 1005,
case injoignable (15, 44) : commit APRÈS preview — refusé, 0 appel au BFS ; commit SANS preview —
refusé, 1 appel. Un test qui ne commit qu'après un preview ne dit donc rien du commit lui-même,
d'où ``test_le_commit_refuse_seul_une_case_injoignable_sans_preview``.

Le budget et les murs se dérivent du PAYLOAD, jamais du moteur : ``game_state['wall_hexes']`` est
filtré de la réponse HTTP (seul ``dense_wall_hexes`` en sort) et ``get_squad_move_budget`` exige
l'état interne. ``MOVE × inches_to_subhex`` a été vérifié égal au budget moteur sur les trois
unités de ``_MONO_MODEL_UNITS`` (8/8, 6/6, 6/6).

Preuve de mordant (2026-09-08) : ``geodesic_move_reach`` remplacé par un disque hex — toute
cellule non bloquée à ``hex_distance <= budget`` — fait passer 11, 11 et 4 candidates de refusées
à acceptées sur les trois unités, le témoin restant accepté dans les deux régimes.
"""

from __future__ import annotations

from typing import Set, Tuple

import pytest

from engine.hex_utils import hex_distance

pytestmark = pytest.mark.integration

# Unités MONO-FIGURINE du scénario figé présentes dans le pool de move du tour 1, dont la mesure
# a montré que le verdict du BFS y est discriminant (candidates refusées qui basculent sous
# mutation : 11/21, 11/42, 4/10). Nommées et non découvertes au vol : une unité tirée du pool
# pourrait être multi-figurines ou sans obstacle à portée, et le test ne mesurerait plus rien.
_MONO_MODEL_UNITS = ("1005", "1002", "3")


def _ground_cells(entries) -> Set[Tuple[int, int]]:
    """Cases de niveau SOL d'un pool ``[[col, row, level], ...]``."""
    return {(int(e[0]), int(e[1])) for e in entries if int(e[2]) == 0}


def _model_pool(game, model_id: str) -> Set[Tuple[int, int]]:
    body = game.act("move_model_destinations", model_id=model_id, provisional_plan={})
    return _ground_cells(body["result"]["destinations"])


def _model_origin(game, model_id: str) -> Tuple[int, int]:
    model = game.state["models_cache"][model_id]
    return int(model["col"]), int(model["row"])


def _move_budget(game, unit_id: str) -> int:
    """Budget de move en subhex, dérivé du PAYLOAD seul (cf. docstring du module)."""
    return int(game.unit(unit_id)["MOVE"]) * int(game.state["inches_to_subhex"])


def _occupied_ground(game) -> Set[Tuple[int, int]]:
    return {
        (int(m["col"]), int(m["row"]))
        for m in game.state["models_cache"].values()
        if int(m["level"]) == 0
    }


def _can_validate(game, unit_id: str, model_id: str, cell: Tuple[int, int]) -> bool:
    """Verdict de la VALIDATION pour cette figurine posée sur ``cell`` — le seul chemin qui
    exerce le trajet. ``explain_move_plan_rejection`` appelée directement ne le ferait pas :
    ``DEFAULT_MOVE_CONSTRAINTS`` porte ``budget_per_model = None``, donc aucun contrôle de
    distance, donc aucun appel au BFS et toute case acceptée."""
    accepted, body = game.try_act(
        "preview_move_plan", unitId=unit_id, plan=[[model_id, cell[0], cell[1], 0]]
    )
    if not accepted:
        return False
    result = body["result"]
    return bool(result["can_validate"]) and bool(result["per_model"][model_id])


def _detour_candidates(
    game, unit_id: str, model_id: str
) -> Tuple[Set[Tuple[int, int]], Set[Tuple[int, int]]]:
    """(pool, candidates) — candidates = cases que SEUL un détour sépare de l'origine.

    À portée hex du budget, absentes du pool, et libres de tout ce qui interdirait la case
    elle-même : mur, figurine. Ce qui reste ne peut être refusé que par la longueur du chemin.
    """
    pool = _model_pool(game, model_id)
    origin = _model_origin(game, model_id)
    budget = _move_budget(game, unit_id)
    walls = {(int(w[0]), int(w[1])) for w in game.state["dense_wall_hexes"]}
    blocked = walls | _occupied_ground(game)
    candidates = {
        (col, row)
        for col in range(int(game.state["board_cols"]))
        for row in range(int(game.state["board_rows"]))
        if (col, row) != origin
        and hex_distance(origin[0], origin[1], col, row) <= budget
        and (col, row) not in pool
        and (col, row) not in blocked
    }
    return pool, candidates


@pytest.mark.parametrize("unit_id", _MONO_MODEL_UNITS)
class TestGeodesicMoveReachIsWiredToPvp:
    def test_le_plateau_x1_mesure_le_move_en_hex(self, game_x1, unit_id):
        """Garde de la fixture : sans géométrie hex, tout le fichier mesurerait l'euclidien."""
        assert int(game_x1.state["inches_to_subhex"]) == 1
        assert (int(game_x1.state["board_cols"]), int(game_x1.state["board_rows"])) == (44, 60)
        assert unit_id in game_x1.pool("move_activation_pool")
        assert len(game_x1.models_of(unit_id)) == 1, "unité attendue mono-figurine (cf. docstring)"

    def test_aucune_case_derriere_un_detour_hors_budget_n_est_validable(self, game_x1, unit_id):
        """09.05 : la distance parcourue est celle du CHEMIN, pas celle du vol d'oiseau."""
        model_id = game_x1.models_of(unit_id)[0]
        game_x1.act("activate_unit", unitId=unit_id)
        _pool, candidates = _detour_candidates(game_x1, unit_id, model_id)

        assert candidates, (
            f"unité {unit_id} : aucune case à portée hex hors du pool — le test ne mesurerait "
            f"rien (VERT VACANT)"
        )
        validables = sorted(
            cell for cell in candidates if _can_validate(game_x1, unit_id, model_id, cell)
        )
        assert not validables, (
            f"unité {unit_id} : {len(validables)} case(s) validées alors qu'aucun chemin de "
            f"{_move_budget(game_x1, unit_id)} pas n'y mène — {validables[:5]}"
        )

    def test_tout_le_pool_par_figurine_est_validable(self, game_x1, unit_id):
        """« masque ⊆ exécutable » : chaque case offerte par le pool passe la validation.

        CONTRE-ÉPREUVE de l'assertion ci-dessus, et pas seulement : sans elle, un refus global
        — budget nul, unité non activée, plan malformé — laisserait « aucune case hors budget
        n'est validable » vraie sans que rien ne soit mesuré.

        POURQUOI TOUT LE POOL et non un témoin. Le pool par-figurine a son PROPRE BFS hex inline
        (``movement_build_model_destinations_pool``), distinct du géodésique qu'emploie la
        validation : deux implémentations du même atteignable, que rien ne tient en phase par
        construction. Mesure du 2026-09-09 — le BFS inline remplacé par un disque hex à filtres
        de destination identiques laisse VERTS les 116 tests des dix fichiers unitaires qui
        touchent ce pool ; seul un témoin unique tombait, et sur une seule des trois unités,
        parce qu'il dépendait de la case que ``min(pool)`` désigne. Balayer le pool entier rend
        la détection indépendante de ce hasard.

        Coût assumé : 340 previews pour les trois unités, mesurées toutes validables en code
        réel (177 + 70 + 93, zéro écart). Une seule case refusée ici est un défaut moteur —
        le masque proposerait au joueur une destination que le commit refuserait.
        """
        model_id = game_x1.models_of(unit_id)[0]
        game_x1.act("activate_unit", unitId=unit_id)
        pool = _model_pool(game_x1, model_id) - {_model_origin(game_x1, model_id)}

        assert pool, f"unité {unit_id} : pool de move vide, le test ne mesurerait rien"
        refusees = sorted(
            cell for cell in pool if not _can_validate(game_x1, unit_id, model_id, cell)
        )
        assert not refusees, (
            f"unité {unit_id} : {len(refusees)} case(s) offertes par son propre pool sont "
            f"refusées par la validation — masque ⊄ exécutable — {refusees[:5]}"
        )

    def test_le_commit_refuse_seul_une_case_injoignable_sans_preview(self, game_x1, unit_id):
        """``commit_move_plan`` mesure le trajet LUI-MÊME, sans dépendre d'un preview préalable.

        AUCUN ``preview_move_plan`` NE DOIT PRÉCÉDER LE COMMIT DANS CE TEST, et ce n'est pas une
        économie d'appel : c'est tout le sujet. ``geodesic_field_for_origin`` mémoïse son champ
        dans ``_move_spatial_cache``, donc un preview le calcule et le commit qui suit le relit
        sans jamais appeler ``geodesic_move_reach``. Mesure du 2026-09-09 sur l'unité 1005, case
        injoignable (15, 44) : commit APRÈS preview — refusé, 0 appel au BFS ; commit SANS
        preview — refusé, 1 appel. Seul le second prouve que le commit sait refuser seul. Y
        ajouter un preview « par symétrie » avec le test suivant rendrait celui-ci aveugle.

        ``move_model_destinations`` peut être appelé sans risque : le pool a son propre BFS
        inline et ne peuple pas le cache géodésique — vérifié par le compteur ci-dessus.

        Enjeu de règle : sans ce contrôle côté commit, un client qui saute le preview (script,
        rejeu, front modifié) téléporterait une figurine derrière un mur en violation de 09.05.
        """
        model_id = game_x1.models_of(unit_id)[0]
        game_x1.act("activate_unit", unitId=unit_id)
        origin = _model_origin(game_x1, model_id)
        _pool, candidates = _detour_candidates(game_x1, unit_id, model_id)
        assert candidates, f"unité {unit_id} : aucune case injoignable à portée (VERT VACANT)"

        target = min(candidates)
        accepted, _body = game_x1.try_act(
            "commit_move_plan", unitId=unit_id, plan=[[model_id, target[0], target[1], 0]]
        )
        assert not accepted, (
            f"unité {unit_id} : commit accepté vers {target}, injoignable en "
            f"{_move_budget(game_x1, unit_id)} pas — 09.05 violée sans passer par le preview"
        )
        assert _model_origin(game_x1, model_id) == origin, (
            f"unité {unit_id} : figurine déplacée en {_model_origin(game_x1, model_id)} alors que "
            f"le commit a été refusé"
        )

    def test_le_plan_d_un_pas_est_previewe_puis_committe_a_la_case_prevue(self, game_x1, unit_id):
        """Le flux nominal complet sur le même plateau : ce que le front joue."""
        model_id = game_x1.models_of(unit_id)[0]
        game_x1.act("activate_unit", unitId=unit_id)
        origin = _model_origin(game_x1, model_id)
        pool = _model_pool(game_x1, model_id)
        destination = min(
            pool - {origin},
            key=lambda cell: hex_distance(origin[0], origin[1], cell[0], cell[1]) or 99,
        )
        plan = [[model_id, destination[0], destination[1], 0]]

        preview = game_x1.act("preview_move_plan", unitId=unit_id, plan=plan)["result"]
        assert preview["can_validate"] is True
        assert preview["per_model"][model_id] is True

        game_x1.act("commit_move_plan", unitId=unit_id, plan=plan)
        assert _model_origin(game_x1, model_id) == destination
