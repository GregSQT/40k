"""Contrat de `geodesic_move_reach` : le champ rendu doit être STRICTEMENT celui du BFS d'origine.

`geodesic_move_reach` a été réécrit pour la performance (2026-09-08) : marche sur les index de
`hex_index_table` au lieu de paires de coordonnées, expansion par couches au lieu d'une file de
`(cellule, distance)`, puis obstacles reçus en CARTE D'OCTETS mémoïsée (`BlockedBitmap`) au lieu
d'être réindexés à chaque appel. Ces trois changements sont invisibles du dehors — c'est
précisément ce que ce fichier vérifie, faute de quoi une optimisation aurait déplacé la frontière
du jouable sans qu'aucun test ne s'en aperçoive.

Les obstacles arrivent désormais convertis : la conversion elle-même (paire fractionnaire inerte,
paire de valeur entière bloquante quel qu'en soit le type, case hors plateau ignorée) est le
`bitmap_in_bounds` de `HexIndexTable`, et les trois derniers tests de ce fichier la verrouillent
à travers le champ — c'est-à-dire là où une régression se verrait vraiment.

`_reference_geodesic_move_reach` est l'implémentation d'AVANT, recopiée verbatim. La comparaison
porte sur DEUX égalités :

  - `dict ==` — mêmes cellules, mêmes distances ;
  - `list(items()) ==` — même ORDRE D'INSERTION. Le champ est consommé tel quel par le pool
    d'ancre et la carte de cellules du masque ; deux champs de même contenu mais d'ordre différent
    produiraient des masques différemment ordonnés, donc des actions différemment numérotées.

Trois angles, parce qu'aucun ne suffit seul :

  1. `test_field_matches_reference_over_real_steps` — vraie partie, actions masquées aléatoires :
     couvre les origines, budgets et jeux d'obstacles que le moteur produit RÉELLEMENT, mais ne
     va pas au bord du plateau (les unités se déploient loin des lisières) ;
  2. `test_field_matches_reference_at_board_edges` — origines aux coins et sur les bords : c'est
     LÀ que vit le filtre de bornes. Sans ce test, une table de voisins construite sans filtre
     resterait verte, alors qu'un index hors plateau (`col * board_rows + row` pour `(0, -1)`)
     désigne une autre case du plateau et bloque ou ouvre un chemin qui n'existe pas ;
  3. les cas dégénérés — budget nul ou négatif, origine enclavée par ses six voisins, et les
     obstacles dont les coordonnées ne sont pas des `int` : le champ d'origine les jugeait sur
     leur VALEUR (`(5, 3) == (5.0, 3.0)`), pas sur leur type.
"""

from __future__ import annotations

import os
import random
from collections import deque
from typing import Dict, List, Set, Tuple, cast

import pytest

import engine.phase_handlers.shared_utils as su
from engine.combat_utils import BlockedBitmap, get_hex_neighbors, hex_index_table

SCENARIO = "config/board/44x60x5/scenario/scenario_pvp_test.json"
PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
STEPS = 50
BOARD_COLS, BOARD_ROWS = 220, 300


def _blocked(cells) -> BlockedBitmap:
    """Obstacles sous la forme attendue par le moteur, via le SEUL constructeur de production.

    Jamais construite à la main ici : c'est `bitmap_in_bounds` qui porte le filtre (bornes,
    coordonnée de valeur entière, coordonnée fractionnaire), donc le tester en le contournant
    ne prouverait rien.
    """
    return hex_index_table(BOARD_COLS, BOARD_ROWS).bitmap_in_bounds(cells)


def _blocked_pairs(blocked: BlockedBitmap) -> Set[Tuple[int, int]]:
    """Carte d'octets -> paires, pour alimenter la référence, qui n'accepte qu'un `set`.

    `bytes.find` saute d'un octet marqué au suivant en C : le coût suit le nombre d'obstacles
    (~2 000), pas la taille du plateau (66 000 cases) — 0,23 ms par appel.
    """
    cells = blocked.table.cells
    out: Set[Tuple[int, int]] = set()
    pos = blocked.data.find(1)
    while pos != -1:
        out.add(cells[pos])
        pos = blocked.data.find(1, pos + 1)
    return out


def _reference_geodesic_move_reach(
    start_col: int,
    start_row: int,
    budget: int,
    transit_blocked: Set[Tuple[int, int]],
    board_cols: int,
    board_rows: int,
) -> Dict[Tuple[int, int], int]:
    """Implémentation d'origine, RECOPIÉE VERBATIM (commit 92b4c922). Ne pas « améliorer » :
    sa seule raison d'être est de rester l'ancienne, y compris dans ses détails de forme."""
    start = (int(start_col), int(start_row))
    field: Dict[Tuple[int, int], int] = {start: 0}
    if budget <= 0:
        return field
    queue: "deque[Tuple[Tuple[int, int], int]]" = deque([(start, 0)])
    while queue:
        (cc, cr), cd = queue.popleft()
        if cd >= budget:
            continue
        nd = cd + 1
        for nc, nr in get_hex_neighbors(cc, cr):
            if nc < 0 or nr < 0 or nc >= board_cols or nr >= board_rows:
                continue
            nb = (nc, nr)
            if nb in field:
                continue
            if nb in transit_blocked:
                continue
            field[nb] = nd
            queue.append((nb, nd))
    return field


def _assert_same_field(call, produced, expected) -> None:
    origin, budget, blocked_size, dims = call
    assert produced == expected, (
        f"champ DIFFÉRENT pour origine={origin} budget={budget} "
        f"obstacles={blocked_size} plateau={dims} : "
        f"{len(produced)} cellules contre {len(expected)} attendues"
    )
    assert list(produced.items()) == list(expected.items()), (
        f"même contenu mais ORDRE D'INSERTION différent pour origine={origin} "
        f"budget={budget} plateau={dims}"
    )


def _build_env():
    """Vrai moteur, même construction que `test_los_pair_cache_invariant.py`."""
    from ai.training_utils import setup_imports
    from ai.unit_registry import UnitRegistry
    from services.api_server import get_agents_from_scenario

    W40KEngine, _ = setup_imports()
    ur = UnitRegistry()
    sf = os.path.join(PROJECT_ROOT, SCENARIO)
    if not os.path.exists(sf):
        raise FileNotFoundError(sf)
    env = W40KEngine(
        rewards_config="default",
        training_config_name="x1",
        controlled_agent=sorted(get_agents_from_scenario(sf, ur))[0],
        scenario_file=sf,
        unit_registry=ur,
        quiet=True,
        gym_training_mode=True,
        training_n_envs=1,
    )
    env.reset(seed=42)
    return env


def test_field_matches_reference_over_real_steps(monkeypatch):
    """Sur une vraie partie, chaque appel du moteur rend le champ de l'implémentation d'origine."""
    live = su.geodesic_move_reach
    calls: List[Tuple[Tuple[int, int], int, int, Tuple[int, int]]] = []
    cells_compared = 0

    def shadowed(start_col, start_row, budget, blocked: BlockedBitmap):
        nonlocal cells_compared
        # La carte passée par le moteur est mémoïsée et partagée entre appels ; la référence,
        # recopiée verbatim, n'accepte qu'un `set`. On DÉCODE donc la carte réellement reçue au
        # lieu de reconstruire les obstacles autrement : c'est la seule façon de comparer les
        # deux implémentations sur EXACTEMENT les mêmes obstacles, conversion comprise.
        pairs = _blocked_pairs(blocked)
        board_cols, board_rows = blocked.table.board_cols, blocked.table.board_rows
        call = (
            (int(start_col), int(start_row)),
            int(budget),
            len(pairs),
            (int(board_cols), int(board_rows)),
        )
        produced = live(start_col, start_row, budget, blocked)
        expected = _reference_geodesic_move_reach(
            start_col, start_row, budget, set(pairs), board_cols, board_rows
        )
        _assert_same_field(call, produced, expected)
        calls.append(call)
        cells_compared += len(produced)
        return produced

    monkeypatch.setattr(su, "geodesic_move_reach", shadowed)

    env = _build_env()
    rng = random.Random(42)
    for _ in range(STEPS):
        mask = env.get_action_mask()
        valid = [i for i in range(len(mask)) if mask[i]]
        if not valid:
            break
        _, _, terminated, truncated, _ = env.step(rng.choice(valid))
        if terminated or truncated:
            env.reset(seed=42)

    # VERT VACANT : sans ces bornes, un moteur qui n'appellerait plus la fonction (ou qui ne
    # produirait que des champs d'une seule cellule) rendrait ce test vert sans rien prouver.
    assert len(calls) >= 20, f"seulement {len(calls)} appels observés — le test n'a rien exercé"
    assert cells_compared >= 10_000, (
        f"seulement {cells_compared} cellules comparées — champs dégénérés, rien n'est verrouillé"
    )
    assert max(budget for _o, budget, _b, _d in calls) > 0, "aucun budget positif exercé"
    assert max(blocked for _o, _bu, blocked, _d in calls) > 0, "aucun obstacle exercé"


def test_memoized_bitmap_never_outlives_its_source_set(monkeypatch):
    """La carte d'obstacles mémoïsée doit TOUJOURS valoir celle du transit courant.

    POURQUOI CE TEST EXISTE À CÔTÉ DU PRÉCÉDENT. `test_field_matches_reference_over_real_steps`
    ne peut PAS attraper une carte périmée : il décode la carte qu'on lui passe et la donne à la
    référence, donc les deux implémentations voient les mêmes obstacles — fussent-ils faux.
    Vérifié le 2026-09-08 en sortant la mémoïsation de `move_transit_blocked_forms` du holder
    `_move_spatial_cache` : ce test-là restait VERT. Il verrouille l'ALGORITHME, pas l'ENTRÉE.

    Le risque propre à la mémoïsation est ailleurs : la carte vit dans le même holder que
    l'ensemble dont elle sort, donc le fingerprint qui jette l'un doit jeter l'autre. Ici on
    compare, à chaque appel d'une vraie partie, la carte SERVIE à celle qu'on obtient en
    re-dérivant depuis `build_move_transit_blocked` — la source unique. Une invalidation
    décorrélée ferait diverger les deux et fermerait des cases que les figurines ont libérées.
    """
    live = su.move_transit_blocked_forms
    checks = 0
    distinct_maps = set()

    def shadowed(game_state, squad_id, player, level):
        nonlocal checks
        pairs, blocked = live(game_state, squad_id, player, level)
        # Source unique, relue MAINTENANT. `build_move_transit_blocked` est mémoïsé dans le même
        # holder : s'il est frais et que la carte ne l'est pas, c'est l'invalidation de la carte
        # qui a décroché.
        source = su.build_move_transit_blocked(game_state, str(squad_id), int(player), int(level))
        assert set(pairs) == set(source), (
            f"les paires servies pour ({squad_id}, {player}, {level}) ne sont plus celles du "
            f"transit courant : {len(set(pairs) ^ set(source))} cases d'écart"
        )
        expected = blocked.table.bitmap_in_bounds(source)
        assert blocked.data == expected.data, (
            f"la carte mémoïsée pour ({squad_id}, {player}, {level}) n'est plus celle du transit "
            f"courant : {sum(a != b for a, b in zip(blocked.data, expected.data))} cases d'écart"
        )
        checks += 1
        distinct_maps.add(blocked.data)
        return pairs, blocked

    monkeypatch.setattr(su, "move_transit_blocked_forms", shadowed)

    env = _build_env()
    rng = random.Random(42)
    for _ in range(STEPS):
        mask = env.get_action_mask()
        valid = [i for i in range(len(mask)) if mask[i]]
        if not valid:
            break
        _, _, terminated, truncated, _ = env.step(rng.choice(valid))
        if terminated or truncated:
            env.reset(seed=42)

    # VERT VACANT : une partie qui n'appellerait jamais l'accesseur, ou qui ne verrait qu'une
    # seule carte, rendrait ce test vert sans avoir exercé la moindre invalidation.
    assert checks >= 20, f"seulement {checks} appels observés — le test n'a rien exercé"
    assert len(distinct_maps) >= 2, (
        f"une seule carte d'obstacles vue sur {checks} appels — aucune invalidation exercée"
    )


@pytest.mark.parametrize(
    "origin",
    [
        (0, 0),
        (0, BOARD_ROWS - 1),
        (BOARD_COLS - 1, 0),
        (BOARD_COLS - 1, BOARD_ROWS - 1),
        (0, 150),
        (110, 0),
        (BOARD_COLS - 1, 150),
        (110, BOARD_ROWS - 1),
        (1, 1),  # colonne impaire : l'autre parité de voisinage, au contact du bord
    ],
    ids=lambda o: f"{o[0]}x{o[1]}",
)
def test_field_matches_reference_at_board_edges(origin):
    """Aux bords, un voisin hors plateau doit être ignoré — jamais replié sur une autre case."""
    col, row = origin
    blocked = {(col + 3, row), (col, row + 3), (col - 3, row), (col, row - 3)}
    produced = su.geodesic_move_reach(col, row, 12, _blocked(blocked))
    expected = _reference_geodesic_move_reach(
        col, row, 12, blocked, BOARD_COLS, BOARD_ROWS
    )
    _assert_same_field((origin, 12, len(blocked), (BOARD_COLS, BOARD_ROWS)), produced, expected)
    assert all(
        0 <= c < BOARD_COLS and 0 <= r < BOARD_ROWS for (c, r) in produced
    ), f"le champ depuis {origin} sort du plateau"


@pytest.mark.parametrize("budget", [0, -1, -7])
def test_null_or_negative_budget_yields_only_the_origin(budget):
    """Budget épuisé : le champ se réduit à l'origine, à distance 0 — et surtout pas à un vide."""
    produced = su.geodesic_move_reach(60, 80, budget, _blocked(set()))
    expected = _reference_geodesic_move_reach(
        60, 80, budget, set(), BOARD_COLS, BOARD_ROWS
    )
    _assert_same_field(((60, 80), budget, 0, (BOARD_COLS, BOARD_ROWS)), produced, expected)
    assert produced == {(60, 80): 0}


def test_enclosed_origin_yields_only_the_origin():
    """Origine murée par ses six voisins : elle figure au champ, seule, malgré un gros budget."""
    origin = (60, 80)
    blocked = set(get_hex_neighbors(*origin))
    produced = su.geodesic_move_reach(*origin, 30, _blocked(blocked))
    expected = _reference_geodesic_move_reach(*origin, 30, blocked, BOARD_COLS, BOARD_ROWS)
    _assert_same_field((origin, 30, len(blocked), (BOARD_COLS, BOARD_ROWS)), produced, expected)
    assert produced == {origin: 0}


def test_fractional_blocked_coordinate_closes_no_cell_anywhere():
    """Un obstacle fractionnaire est inerte — y compris sur la case dont il porte l'INDEX.

    `62.7 * 300 + 80` vaut exactement `18890.0`, qui hache comme `18890`, l'index de
    `(62, 290)` sur un plateau 220x300. Une indexation naïve fermerait donc `(62, 290)` à cause
    d'un obstacle situé 210 lignes plus haut. Le BFS d'origine, lui, comparait des paires :
    `(62, 290) != (62.7, 80)`, donc rien n'était bloqué. C'est CETTE case-là que le champ doit
    contenir — la vérifier ailleurs ne prouverait rien, l'obstacle y étant hors de portée.
    """
    # `cast` assumé : ce test exerce précisément ce que l'annotation interdit. Rien n'empêche
    # un appelant de produire une coordonnée fractionnaire à l'exécution, et c'est le
    # comportement dans ce cas-là qui est verrouillé ici.
    colliding = cast(Set[Tuple[int, int]], {(62.7, 80)})
    origin = (62, 285)
    with_fractional = su.geodesic_move_reach(*origin, 20, _blocked(colliding))
    reference = _reference_geodesic_move_reach(
        *origin, 20, colliding, BOARD_COLS, BOARD_ROWS
    )
    _assert_same_field((origin, 20, 1, (BOARD_COLS, BOARD_ROWS)), with_fractional, reference)
    assert (62, 290) in with_fractional, (
        "la case dont l'obstacle fractionnaire porte l'index a été fermée"
    )

    # Contrôle de dents : la MÊME case écrite en entiers ferme bien le passage, sinon le test
    # ci-dessus serait vert pour un moteur qui ignorerait tous les obstacles.
    with_integral = su.geodesic_move_reach(*origin, 20, _blocked({(62, 290)}))
    assert (62, 290) not in with_integral


def test_integer_valued_blocked_coordinates_block_whatever_their_type():
    """`(62.0, 80.0)` et son équivalent numpy bloquent, exactement comme `(62, 80)`.

    Le BFS d'origine testait `(62, 80) in obstacles` : une paire de VALEUR entière y est égale
    quel qu'en soit le type. Filtrer les obstacles sur `type(...) is int` rendrait ces deux
    écritures inertes, donc rouvrirait un passage que l'appelant a fermé.
    """
    import numpy as np

    origin = (60, 80)
    forms = [
        cast(Set[Tuple[int, int]], {(62, 80)}),
        cast(Set[Tuple[int, int]], {(62.0, 80.0)}),
        cast(Set[Tuple[int, int]], {(np.int64(62), np.int64(80))}),
    ]
    fields = [
        su.geodesic_move_reach(*origin, 8, _blocked(blocked))
        for blocked in forms
    ]
    for blocked, field in zip(forms, fields):
        assert (62, 80) not in field, f"{blocked} n'a pas bloqué (62, 80)"
    assert fields[0] == fields[1] == fields[2]
    assert list(fields[0].items()) == list(fields[1].items()) == list(fields[2].items())


def test_blocked_cell_outside_the_board_changes_nothing():
    """Un obstacle hors plateau est inerte — il ne doit pas se replier sur une case joignable.

    `(5, -1)` porte l'index de `(4, 299)` à 220x300 : si les obstacles étaient indexés sans
    filtre de bornes, cet obstacle-là fermerait une case située à l'autre bout du plateau.
    """
    inert = {(5, -1), (-1, 5), (BOARD_COLS, 5), (5, BOARD_ROWS)}
    with_inert = su.geodesic_move_reach(4, 298, 20, _blocked(inert))
    without = su.geodesic_move_reach(4, 298, 20, _blocked(set()))
    assert with_inert == without
    assert list(with_inert.items()) == list(without.items())
