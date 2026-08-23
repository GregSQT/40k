"""V11 T6-f — Le commit de déploiement `deploy_unit` place TOUTES les figurines.

Rupture corrigée (2026-07-19) : `deployment_handlers.deploy_unit` (commit partagé par le gym,
l'auto-déploiement P2 du tutoriel PvP et le drag mono-socle) n'écrivait que l'ancre
(`set_unit_coordinates` + `update_units_cache_position`, qui ne touchent JAMAIS `models_cache`).
Les figurines restaient donc à (-1,-1) après un déploiement « réussi ».

Le bug ne se voyait PAS au déploiement : il explosait une phase plus tard, au premier move, quand
`build_rigid_plan` translatait toutes les figurines depuis (-1,-1) — elles atterrissaient sur un
hex unique et `validate_move_plan` rejetait, alors que le masque avait autorisé la cellule
(« incohérence masque/exécution »). En training vectorisé, les workers `SubprocVecEnv` mouraient.

Le fix fait passer `deploy_unit` par le MÊME écrivain que le flux PvP par escouade
(`build_validated_deployment_plan` → `_apply_deploy_plan` → `update_model_position` par figurine).

Verrous :
- **Placement** : après le déploiement, aucune figurine vivante ne reste à (-1,-1).
- **Cohérence ancre/figurines** : l'ancre `units_cache` est celle de la figurine vivante de plus
  petit index — l'invariant exact dont `build_rigid_plan` dépend.
- **Légalité du plan committé** : le plan écrit est validé par `deployment_preview_plan`.
- **Contrat du helper** : `build_validated_deployment_plan` est déterministe, sans écriture, et
  rend `None` (jamais un plan illégal) quand la formation ne tient pas.
"""
from __future__ import annotations

import sys

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
from tests.unit.engine._config_helpers import both_terrains

SCENARIO = (
    PROJECT_ROOT / "config" / "agents" / "ArmageddonAgent" / "scenarios" / "training"
    / "scenario_training_armageddon1.json"
)

# Ce fichier est REJOUÉ SUR LES DEUX TERRAINS : ce qu'il vérifie dépend des murs, des zones de
# déploiement ou des pièces d'objectif, et ces trois-là changent entièrement entre `terrain-mc1`
# et `terrain-mc2`. La fixture réécrit `SCENARIO` le temps de chaque test (cf. `both_terrains`).
_terrain = both_terrains(sys.modules[__name__])


UNDEPLOYED = (-1, -1)


@pytest.fixture(autouse=True)
def _pin_board(board_x5):
    pass


def _load(seed: int = 0):
    from ai.unit_registry import UnitRegistry
    from engine.w40k_core import W40KEngine

    eng = W40KEngine(
        rewards_config="ArmageddonAgent", training_config_name="x1_debug", controlled_agent="ArmageddonAgent",
        scenario_file=str(SCENARIO), unit_registry=UnitRegistry(), quiet=True,
        gym_training_mode=True,
    )
    # Le scheduler de déploiement actif est neutralisé ci-dessous : ce test cible le COMMIT d'un
    # déploiement ACTIF (deploy_unit) et force deployment_type='active' du scénario directement.
    assert eng.training_config is not None
    sched = eng.training_config.get("deployment_mode_schedule")
    if isinstance(sched, dict):
        sched["enabled"] = False
    eng.reset(seed=seed)
    return eng


def _drive_deployment(eng):
    """Déroule la phase de déploiement en prenant la 1re action de déploiement du masque."""
    gs = eng.game_state
    steps = 0
    while gs.get("phase") == "deployment" and steps < 1000:
        mask = eng.get_action_mask()
        deploy_actions = [a for a in range(4, 9) if mask[a]]
        assert deploy_actions, f"aucune action de déploiement dans le masque (step {steps})"
        eng.step(int(deploy_actions[0]))
        steps += 1
    assert gs.get("phase") != "deployment", "déploiement non terminé (deadlock)"


def _deployed_squad_ids(gs):
    return [str(u) for u in gs["deployment_state"]["deployed_units"]]


@pytest.mark.parametrize("seed", [0, 1])
def test_deploy_unit_writes_every_model_position(seed):
    """Aucune figurine vivante ne reste à (-1,-1) après le déploiement."""
    eng = _load(seed=seed)
    assert eng.game_state.get("phase") == "deployment", "le scénario doit démarrer en déploiement"
    _drive_deployment(eng)

    gs = eng.game_state
    models_cache = gs["models_cache"]
    squad_models = gs["squad_models"]
    deployed = _deployed_squad_ids(gs)
    assert deployed, "aucune escouade déployée — le test n'a rien exercé"

    for squad_id in deployed:
        alive = [mid for mid in squad_models.get(squad_id, []) if mid in models_cache]
        assert alive, f"escouade {squad_id} déployée mais sans figurine dans models_cache"
        for mid in alive:
            pos = (int(models_cache[mid]["col"]), int(models_cache[mid]["row"]))
            assert pos != UNDEPLOYED, (
                f"figurine {mid} de l'escouade {squad_id} laissée à (-1,-1) par le commit "
                f"de déploiement — `models_cache` non écrit (V11 T6-f)"
            )


@pytest.mark.parametrize("seed", [0, 1])
def test_anchor_matches_first_alive_model(seed):
    """L'ancre `units_cache` est celle de la figurine vivante de plus petit index.

    C'est l'invariant dont `build_rigid_plan` dépend : il calcule le vecteur de translation
    comme `destination - position de alive_mids[0]`. Une ancre désynchronisée décale tout le
    bloc et fait diverger le pool BFS (construit sur l'ancre) de l'exécution.
    """
    eng = _load(seed=seed)
    _drive_deployment(eng)

    gs = eng.game_state
    models_cache = gs["models_cache"]
    squad_models = gs["squad_models"]
    units_cache = gs["units_cache"]

    for squad_id in _deployed_squad_ids(gs):
        alive = [mid for mid in squad_models.get(squad_id, []) if mid in models_cache]
        anchor_model = models_cache[alive[0]]
        entry = units_cache[squad_id]
        assert (int(entry["col"]), int(entry["row"])) == (
            int(anchor_model["col"]), int(anchor_model["row"])
        ), (
            f"ancre units_cache de l'escouade {squad_id} désynchronisée de sa figurine "
            f"d'ancrage {alive[0]}"
        )


def test_committed_plan_is_legal():
    """Le placement committé passe le dry-run par-figurine du flux PvP."""
    from engine.phase_handlers.deployment_handlers import deployment_preview_plan

    eng = _load(seed=0)
    _drive_deployment(eng)

    gs = eng.game_state
    models_cache = gs["models_cache"]
    squad_models = gs["squad_models"]

    for squad_id in _deployed_squad_ids(gs):
        alive = [mid for mid in squad_models.get(squad_id, []) if mid in models_cache]
        plan = [
            (mid, int(models_cache[mid]["col"]), int(models_cache[mid]["row"]),
             int(models_cache[mid]["level"]))
            for mid in alive
        ]
        preview = deployment_preview_plan(gs, squad_id, plan)
        assert preview["can_validate"], (
            f"placement committé de l'escouade {squad_id} invalide : "
            f"per_model={preview['per_model']} coherency_ok={preview['coherency_ok']}"
        )


def test_build_validated_plan_is_read_only_and_deterministic():
    """Le helper ne mute rien et rend deux fois le même plan — c'est ce qui autorise le décodeur
    (choix de l'ancre) et le commit à l'appeler séparément sans mémoisation."""
    from engine.phase_handlers.deployment_handlers import build_validated_deployment_plan

    eng = _load(seed=0)
    gs = eng.game_state
    squad_id = str(gs["deployment_state"]["deployable_units"][1][0])
    anchor = gs["deployment_pools"][1][0]
    col, row = int(anchor[0]), int(anchor[1])

    before = {
        mid: (int(m["col"]), int(m["row"]))
        for mid, m in gs["models_cache"].items()
    }
    first = build_validated_deployment_plan(gs, squad_id, col, row)
    after = {
        mid: (int(m["col"]), int(m["row"]))
        for mid, m in gs["models_cache"].items()
    }
    assert after == before, "build_validated_deployment_plan a muté models_cache (lecture pure)"

    second = build_validated_deployment_plan(gs, squad_id, col, row)
    assert first == second, "build_validated_deployment_plan n'est pas déterministe"


def test_build_validated_plan_never_returns_an_illegal_plan():
    """Invariant du helper : tout plan rendu est validé par le dry-run par-figurine.

    `generate_compact_formation` est un helper UX dont l'overflow documenté peut poser des
    figurines HORS ZONE (« signalées rouge par le preview, à repositionner ») — un plan n'est
    donc PAS légal par construction. Le helper doit filtrer, sinon le commit écrirait un
    placement hors-règle.

    Balayage sur un échantillon d'ancres de la zone : chaque plan non-`None` passe
    `deployment_preview_plan`.
    """
    from engine.phase_handlers.deployment_handlers import (
        build_validated_deployment_plan, deployment_preview_plan,
    )

    eng = _load(seed=0)
    gs = eng.game_state
    squad_id = str(gs["deployment_state"]["deployable_units"][1][0])
    pool = [(int(c), int(r)) for c, r in gs["deployment_pools"][1]]
    assert pool, "fixture invalide : zone de déploiement vide"

    checked = 0
    for col, row in pool[:: max(1, len(pool) // 40)]:
        plan = build_validated_deployment_plan(gs, squad_id, col, row)
        if plan is None:
            continue
        assert deployment_preview_plan(gs, squad_id, plan)["can_validate"], (
            f"plan rendu pour l'ancre ({col},{row}) mais rejeté par le dry-run par-figurine"
        )
        checked += 1
    assert checked > 0, "aucune ancre n'a produit de plan — le test n'a rien vérifié"


def test_precomputed_footprint_matches_the_canonical_one():
    """L'empreinte par translation d'offsets == l'empreinte canonique, aux DEUX parités.

    `generate_compact_formation` ne reconstruit plus l'empreinte du socle à chaque case de sa
    spirale : elle translate des offsets pré-calculés (`precompute_footprint_offsets`), ce qui
    supprime ~67 % de son coût. L'optimisation n'est valide que si les deux formes coïncident
    exactement — y compris sur la parité de colonne, dont dépend la géométrie offset odd-q.

    Ce code est partagé avec le déploiement PvP par escouade : une divergence déplacerait des
    socles à l'écran, pas seulement en training.
    """
    from engine.hex_utils import precompute_footprint_offsets
    from engine.phase_handlers.shared_utils import (
        compute_candidate_footprint, get_engagement_zone,
    )

    eng = _load(seed=0)
    gs = eng.game_state
    assert get_engagement_zone(gs) > 1, "fixture invalide : board sans empreintes multi-hex"

    models_cache = gs["models_cache"]
    seen_shapes = set()
    checked = 0
    for model in models_cache.values():
        shape = model["BASE_SHAPE"]
        size = model["BASE_SIZE"]
        orient = int(model.get("orientation", 0))
        key = (shape, tuple(size) if isinstance(size, list) else size, orient)
        if key in seen_shapes:
            continue
        seen_shapes.add(key)
        if size == 1:
            continue
        offsets_even, offsets_odd = precompute_footprint_offsets(shape, size, orient)
        for col in (40, 41, 120, 121):  # deux colonnes paires, deux impaires
            for row in (60, 61):
                off = offsets_even if col % 2 == 0 else offsets_odd
                translated = {(col + dc, row + dr) for dc, dr in off}
                canonical = compute_candidate_footprint(
                    col, row,
                    {"BASE_SHAPE": shape, "BASE_SIZE": size, "orientation": orient},
                    gs,
                )
                assert translated == canonical, (
                    f"empreinte divergente pour {key} en ({col},{row}) : "
                    f"{sorted(translated ^ canonical)}"
                )
                checked += 1
    assert checked > 0, "aucune empreinte multi-hex vérifiée"


def test_memoized_plan_is_invalidated_by_a_stale_stamp():
    """La mémo décodeur→commit ne survit pas à un changement d'état.

    Elle n'existe que pour éviter un 2e `generate_compact_formation` (~77 ms sur board x5) dans
    le MÊME step. Un tampon périmé doit rendre `None` — le commit recalcule alors, plutôt que
    d'écrire un placement obsolète.
    """
    from engine.phase_handlers.deployment_handlers import (
        build_validated_deployment_plan, read_validated_deployment_plan,
        store_validated_deployment_plan,
    )

    eng = _load(seed=0)
    gs = eng.game_state
    squad_id = str(gs["deployment_state"]["deployable_units"][1][0])
    anchor = gs["deployment_pools"][1][0]
    col, row = int(anchor[0]), int(anchor[1])

    plan = build_validated_deployment_plan(gs, squad_id, col, row)
    assert plan is not None, "fixture invalide : aucune formation légale à cette ancre"
    store_validated_deployment_plan(gs, squad_id, col, row, plan)

    assert read_validated_deployment_plan(gs, squad_id, col, row) == plan, (
        "le plan mémoisé doit être relu tel quel quand le tampon correspond"
    )
    assert read_validated_deployment_plan(gs, squad_id, col + 1, row) is None, (
        "une AUTRE ancre ne doit pas relire le plan mémoisé"
    )

    # Avancement du déploiement → tampon périmé.
    gs["deployment_state"]["deployed_units"].add("999")
    assert read_validated_deployment_plan(gs, squad_id, col, row) is None, (
        "un plan mémoisé avant une autre pose ne doit plus être relu"
    )


def test_anchor_is_a_suggestion_not_a_constraint():
    """Comportement RÉEL de `generate_compact_formation`, non évident et volontairement verrouillé.

    Sa spirale BFS part de l'ancre et retient la 1re case LÉGALE : une ancre hors zone ne fait
    donc PAS échouer la génération, elle place l'escouade dans la zone la plus proche. Autrement
    dit l'ancre oriente le placement, elle ne le contraint pas.

    Conséquence pour `deploy_unit` : le refus d'une ancre hors zone vient de sa validation
    mono-ancre (`deploy_footprint_outside_zone`), PAS du helper — ne pas déplacer cette garde en
    croyant le helper suffisant.
    """
    from engine.phase_handlers.deployment_handlers import build_validated_deployment_plan

    eng = _load(seed=0)
    gs = eng.game_state
    squad_id = str(gs["deployment_state"]["deployable_units"][1][0])
    pool = {(int(c), int(r)) for c, r in gs["deployment_pools"][1]}

    outside = (0, 0)
    assert outside not in pool, "fixture invalide : (0,0) appartient à la zone de déploiement"

    plan = build_validated_deployment_plan(gs, squad_id, outside[0], outside[1])
    assert plan is not None, "la spirale doit rattraper la zone depuis une ancre hors zone"
    for _mid, col, row, _lv in plan:
        assert (col, row) in pool, (
            f"figurine placée hors zone ({col},{row}) — le preview aurait dû rejeter ce plan"
        )


# ---------------------------------------------------------------------------------------------
# Mémoïsation de `_deploy_pool_set` (perf) — le plan doit rester IDENTIQUE, et le cache doit
# s'invalider quand les zones sont re-publiées.
#
# `_deploy_pool_set` matérialisait le `set` de la zone (~16 000 hexes) à CHAQUE appel : 2,5 ms
# sur les 12,6 ms d'une formation. Il est désormais mémoïsé dans `game_state`. Le risque n'est
# pas la lenteur mais le SILENCE : un cache non purgé rend la zone du scénario précédent, sans
# rien lever. Ces tests verrouillent les deux faces (équivalence + invalidation).
# ---------------------------------------------------------------------------------------------

_POOL_CACHE_KEY = "_deploy_pool_set_cache"


def test_memoized_pool_yields_the_same_formation_plan():
    """Critère d'acceptation du refactor de perf : MÊME plan, sur un échantillon d'ancres.

    `generate_compact_formation` est déterministe. La zone mémoïsée est comparée à la zone
    reconstruite à la main — celle que l'ancien code rebâtissait à chaque appel.
    """
    from engine.phase_handlers.deployment_handlers import (
        _deploy_pool_set, generate_compact_formation,
    )

    eng = _load(seed=0)
    gs = eng.game_state
    squad_id = str(gs["deployment_state"]["deployable_units"][1][0])
    raw_pool = [(int(c), int(r)) for c, r in gs["deployment_pools"][1]]

    expected_zone = {(int(c), int(r)) for c, r in raw_pool}
    assert _deploy_pool_set(gs, 1, None) == expected_zone, (
        "la zone mémoïsée diffère de la zone reconstruite directement"
    )

    # Échantillon réparti sur toute la zone (pas seulement la première ancre).
    sample = [raw_pool[i] for i in range(0, len(raw_pool), max(1, len(raw_pool) // 8))][:8]
    assert len(sample) >= 4, "fixture invalide : échantillon d'ancres trop petit"

    for col, row in sample:
        first = generate_compact_formation(gs, squad_id, col, row)
        second = generate_compact_formation(gs, squad_id, col, row)
        assert first == second, (
            f"formation non déterministe à l'ancre ({col},{row}) : {first} != {second}"
        )
        assert all((c, r) in expected_zone for _m, c, r in first), (
            f"formation hors zone à l'ancre ({col},{row}) — cache incohérent avec deployment_pools"
        )


def _zone_of(gs, player: int):
    return {(int(c), int(r)) for c, r in gs["deployment_pools"][player]}


def _poison_cache(gs):
    """Empoisonne le cache du joueur 1 avec la zone du joueur 2, et rend cette zone fausse.

    Le poison joue le rôle de la zone héritée de l'épisode précédent : si un chemin de
    re-publication ne purge pas le cache, c'est ELLE qui ressortira. Empoisonner le cache plutôt
    qu'injecter des zones dans `config` est le seul montage fiable — `reset` recharge le scénario
    et réécrirait l'injection, alors que le poison n'appartient qu'au cache.

    Le poison est une VRAIE zone (celle d'en face) et non des cases arbitraires : la suite du
    reset consomme cette valeur pour bâtir le masque de déploiement, et une zone illégale y fait
    boucler la recherche de case au lieu de produire un échec lisible.
    """
    from engine.phase_handlers.deployment_handlers import _deploy_pool_set

    _deploy_pool_set(gs, 1, None)  # amorce le cache
    assert gs.get(_POOL_CACHE_KEY), "le cache doit être amorcé après un premier appel"

    wrong = frozenset(_zone_of(gs, 2))
    assert wrong and not (wrong & _zone_of(gs, 1)), (
        "fixture invalide : les zones des deux joueurs doivent être disjointes et non vides"
    )
    gs[_POOL_CACHE_KEY][1] = wrong
    return wrong


def _assert_zone_is_fresh(gs, wrong, context: str):
    from engine.phase_handlers.deployment_handlers import _deploy_pool_set

    refreshed = _deploy_pool_set(gs, 1, None)
    assert refreshed != wrong, f"zone empoisonnée ressortie {context}"
    assert refreshed == _zone_of(gs, 1), f"zone périmée rendue {context}"


def test_pool_cache_is_invalidated_by_reset_without_scenario_reload():
    """VERROU T1 — chemin gym nominal : `reset` SANS rechargement de scénario.

    `game_state` survit d'un épisode à l'autre (le reset le mute en place), donc un cache non
    purgé au site de publication rendrait la zone de l'épisode précédent, silencieusement.

    Le rechargement est explicitement désarmé : sinon `_reload_scenario` purge lui aussi et
    MASQUE l'absence de purge dans `reset` — le test resterait vert sans rien verrouiller.
    Cycle rouge : retirer le `pop("_deploy_pool_set_cache")` de `W40KEngine.reset`.
    """
    eng = _load(seed=0)
    # Les déclencheurs de `should_reload_scenario` (cf. `reset`) : roster d'agent tiré au sort,
    # rotation de scénario, changement de joueur contrôlé. Le scheduler est déjà désarmé par
    # `_load`.
    eng._scenario_has_random_agent_roster = False
    assert not (eng._random_scenario_mode and len(eng._scenario_files) > 1), (
        "fixture invalide : la rotation de scénario forcerait un rechargement"
    )

    wrong = _poison_cache(eng.game_state)

    eng.reset(seed=0)
    # La clé peut très bien être REPRÉSENTE : la suite du reset re-consulte les zones et ré-amorce
    # le cache légitimement. Ce qui est verrouillé n'est donc pas l'absence de la clé, mais
    # l'absence du POISON — que la valeur d'avant n'ait pas survécu.
    _assert_zone_is_fresh(eng.game_state, wrong, "après un reset sans rechargement de scénario")


def test_pool_cache_is_invalidated_by_a_direct_scenario_reload():
    """VERROU T1 — chemin de rotation : `_reload_scenario` appelé DIRECTEMENT, sans reset.

    Ce chemin existe vraiment (cf. `test_board_boundary_walls_survive_reload.py`, qui appelle
    `_reload_scenario` seul) : la purge du `reset` ne le couvre donc pas. Une rotation change de
    terrain, donc de zones — un cache survivant rendrait celles du scénario précédent.
    Cycle rouge : retirer le `pop("_deploy_pool_set_cache")` de `_reload_scenario`.
    """
    eng = _load(seed=0)
    wrong = _poison_cache(eng.game_state)

    eng._reload_scenario(str(SCENARIO))

    _assert_zone_is_fresh(eng.game_state, wrong, "après un appel direct à `_reload_scenario`")


def test_pool_cache_does_not_mask_a_scenario_without_zones():
    """VERROU T1 : sans zones déclarées, les lecteurs doivent LEVER, pas lire un cache périmé.

    Le reset RETIRE `deployment_pools` quand le scénario n'en déclare pas, plutôt que d'en laisser
    une périmée, précisément pour que `require_key` lève (cf. le commentaire du reset). Un cache
    consulté AVANT cette vérification annulerait la garantie — le trou le plus discret de la
    mémoïsation, puisqu'il change une erreur explicite en zone silencieusement fausse.

    Ce que ça verrouille dans le code : `require_key("deployment_pools")` est évalué AVANT la
    lecture du cache. Cycle rouge : déplacer le `return cached` au-dessus du `require_key`.
    """
    from engine.phase_handlers.deployment_handlers import _deploy_pool_set

    eng = _load(seed=0)
    gs = eng.game_state
    _deploy_pool_set(gs, 1, None)  # amorce le cache
    assert gs.get(_POOL_CACHE_KEY), "le cache doit être amorcé après un premier appel"

    # Scénario sans zones : l'état exact que produit la branche `is None` du reset.
    from shared.data_validation import ConfigurationError

    del gs["deployment_pools"]
    with pytest.raises(ConfigurationError):
        _deploy_pool_set(gs, 1, None)


def test_memoized_pool_is_immutable():
    """Le `set` est partagé entre tous les appelants, donc il doit être immuable.

    Sans ça, un appelant qui muterait le résultat corromprait la zone de tous les autres pour
    tout le reste de la partie.
    """
    from engine.phase_handlers.deployment_handlers import _deploy_pool_set

    eng = _load(seed=0)
    zone = _deploy_pool_set(eng.game_state, 1, None)
    assert isinstance(zone, frozenset), (
        f"la zone mémoïsée doit être un frozenset, pas {type(zone).__name__}"
    )
