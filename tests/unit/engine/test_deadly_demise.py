"""§24.08 DEADLY DEMISE — mécanisme générique dans destroy_model.

PDF 24.08 : « Each time a model in this unit is destroyed, after the units embarked within it
(if any) have made their emergency disembark moves, roll one D6. On a 6, that model suffers a
deadly demise; each unit within 6" of that model suffers a number of mortal wounds denoted by X ».

Ability CORE, propre à la figurine qui la porte (décision du 2026-09-13, couverture_regles.md
§ Attached Units) : la règle se lit sur `models_cache[mid]["UNIT_RULES"]` de la figurine
détruite, jamais sur l'union 19.04 de l'escouade — un Boy mené par un WeirdBoy n'explose pas.

Discrimination verrouillee :
- deadly_demise présente + D6=6 → action_log contient une entrée deadly_demise par unité dans 6"
- deadly_demise présente + D6=1 → action_log contient une entrée deadly_demise (d6Roll=1) mais
  deadlyDemiseWounds=0 et pas d'allocation
- deadly_demise absente → aucune entrée deadly_demise dans action_log
- WeirdBoy replié dans des Boyz : Boy détruit → 0 jet (WeirdBoy vivant ou mort), WeirdBoy → 1 jet
"""
import random
import pytest

from engine.constants import MORTAL_WOUND_QUEUE_KEY
from engine.hex_utils import compute_occupied_hexes
from engine.phase_handlers.shared_utils import destroy_model as _destroy_model_raw, drain_mortal_wound_queue


def destroy_model(gs, model_id, reason):
    """Détruit la figurine PUIS sert la file des blessures mortelles.

    25 DESTROYED : une Deadly Demise causée par une attaque n'est résolue qu'après les attaques
    de l'attaquant — `destroy_model` la met en file, `drain_mortal_wound_queue` la joue. Ces
    tests mesurent l'explosion elle-même : les deux gestes sont enchaînés ici, sans attente
    humaine possible (`player_types` programmatiques dans les fixtures)."""
    _destroy_model_raw(gs, model_id, reason=reason)
    wait = drain_mortal_wound_queue(gs)
    assert wait is None, f"attente humaine inattendue : {wait}"
from tests._state_invariants import unit_invariants
from tests.unit.engine._config_helpers import load_engine_from_scenario

_DD_RULE_1 = {"ruleId": "deadly_demise", "displayName": "Deadly Demise 1", "rule_args": {"value": 1}}


# ── game_state minimal pour destroy_model ────────────────────────────────────

def _gs(*, with_deadly_demise: bool = True, target_col: int = 2, target_row: int = 2,
        base_size: int = 1, src_shape: str = "round", src_base_size=None,
        src_orientation: int = 0):
    """Une figurine (mid='SRC#0') dans escouade 'SRC' à (0,0) + une escouade cible 'TGT' à
    (target_col, target_row).  inches_to_subhex=5 => 6" = 30 subhex.

    `base_size` (diamètre en subhex, socles ronds) : les deux escouades le partagent. 24.08 se
    mesure du BORD des socles (01.04), donc la taille change le verdict à écart de grille égal ;
    `occupied_hexes` en découle par `compute_occupied_hexes`, comme en production.

    `src_shape` / `src_base_size` / `src_orientation` décrivent le socle de la SEULE figurine qui
    explose — le profil véhicule/monstre que 24.08 vise, dont le contour n'est pas invariant par
    rotation.
    """
    ish = 5
    src_size = base_size if src_base_size is None else src_base_size
    # La règle est portée par LA FIGURINE (règles propres de sa datasheet), pas par l'escouade.
    src_model = {
        "col": 0, "row": 0, "level": 0, "player": 1, "squad_id": "SRC",
        "HP_CUR": 1, "BASE_SHAPE": src_shape, "BASE_SIZE": src_size,
        "orientation": src_orientation,
        "UNIT_RULES": [_DD_RULE_1] if with_deadly_demise else [],
    }
    src_uc: dict = {
        "col": 0, "row": 0, "player": 1, "HP_CUR": 1,
        "BASE_SHAPE": src_shape, "BASE_SIZE": src_size, "orientation": src_orientation,
        "occupied_hexes": compute_occupied_hexes(0, 0, src_shape, src_size, src_orientation),
        "occupied_hexes_by_model": {"SRC#0": (0, 0)},
        "floor_height_by_model": {"SRC#0": 0.0},
        "level_by_model": {"SRC#0": 0},
        "MODEL_HEIGHT": 2.0,
    }

    tgt_uc = {
        "col": target_col, "row": target_row, "player": 2, "HP_CUR": 2,
        "BASE_SHAPE": "round", "BASE_SIZE": base_size, "orientation": 0,
        "occupied_hexes": compute_occupied_hexes(target_col, target_row, "round", base_size),
        "occupied_hexes_by_model": {"TGT#0": (target_col, target_row)},
        "floor_height_by_model": {"TGT#0": 0.0},
        "level_by_model": {"TGT#0": 0},
        "MODEL_HEIGHT": 2.0,
    }

    # Couche `units` : elle porte `hideable`/`hidden`, que `destroy_model` rafraîchit (13.09,
    # état continu). Toute escouade de `units_cache` en a une en production. `hideable` dérive
    # de UNIT_KEYWORDS, donc hors socle : posé ici, False (aucun mot-clé hideable).
    units = [
        {**unit_invariants(), "id": "SRC", "player": 1, "hideable": False},
        {**unit_invariants(), "id": "TGT", "player": 2, "hideable": False},
    ]

    # La cible a une figurine VIVANTE : « each unit within 6" » ne vise que les escouades qui en
    # ont encore une (`select_eligible_models`), une escouade vide n'est plus une unité.
    tgt_model = {
        "col": target_col, "row": target_row, "level": 0, "player": 2, "squad_id": "TGT",
        "HP_CUR": 2, "HP_MAX": 2, "BASE_SHAPE": "round", "BASE_SIZE": base_size, "orientation": 0,
        "UNIT_RULES": [],
    }
    return {
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
        "models_cache": {"SRC#0": src_model, "TGT#0": tgt_model},
        "squad_models": {"SRC": ["SRC#0"], "TGT": ["TGT#0"]},
        "units_cache": {"SRC": src_uc, "TGT": tgt_uc},
        "action_logs": [],
        "action_log_seq": 0,
        "board_cols": 44, "board_rows": 44,
        "wall_hexes": set(),
        "_unit_move_version": 0,
        "terrain_areas": [],
        "inches_to_subhex": ish,
        "config": {
            "game_rules": {
                "engagement_zone": 2,
                "max_base_size_hex": 35,
                "unit_model_cohesion_range": 2,
                "unit_global_cohesion_range": 9,
                "squad_min_neighbors": 1,
                "cohesion_distance_mode": "euclidean",
                "plunging_fire_height": 3,
            },
            "move": {
                "can_move_through_enemy_engagement_zone": True,
                "can_move_through_enemy_model": False,
                "can_move_through_friendly_model": True,
            },
        },
        "phase": "fight",
        "turn": 1,
        # Proprietaires programmatiques : les blessures mortelles s attribuent sans question.
        "player_types": {"1": "ai", "2": "ai"},
    }


def _dd_logs(gs):
    return [e for e in gs["action_logs"] if e.get("type") == "deadly_demise"]


# ── tests ────────────────────────────────────────────────────────────────────

def test_dd_d6_6_emet_entree_dans_action_log(monkeypatch):
    """D6=6 et cible a <=6" -> une entree deadly_demise dans action_log, wounds > 0."""
    monkeypatch.setattr(random, "randint", lambda a, b: 6)
    import engine.phase_handlers.shared_utils as su
    monkeypatch.setattr(su, "allocate_mortal_wounds", lambda gs, uid, n, auto, sink, *, is_psychic=False: None)
    gs = _gs(with_deadly_demise=True, target_col=5, target_row=0)   # TGT a 5 subhex < 30
    destroy_model(gs, "SRC#0", reason="combat")
    logs = _dd_logs(gs)
    assert len(logs) >= 1, f"attendu >=1 entree deadly_demise, obtenu {logs}"
    hit = next(e for e in logs if e["unitId"] == "TGT")
    assert hit["d6Roll"] == 6
    assert hit["deadlyDemiseWounds"] == 1   # deadly_demise = 1 dans le gs


def test_dd_d6_1_emet_entree_sans_allocation(monkeypatch):
    """D6=1 -> entree deadly_demise emise MAIS wounds=0 et pas d'allocation."""
    monkeypatch.setattr(random, "randint", lambda a, b: 1)
    import engine.phase_handlers.shared_utils as su
    allocated_calls = []
    monkeypatch.setattr(su, "allocate_mortal_wounds",
                        lambda gs, uid, n, auto, sink, *, is_psychic=False: allocated_calls.append((uid, n)))
    gs = _gs(with_deadly_demise=True, target_col=5, target_row=0)
    destroy_model(gs, "SRC#0", reason="combat")
    logs = _dd_logs(gs)
    assert any(e["d6Roll"] == 1 for e in logs), "l'event doit etre emis meme sur echec"
    assert not any(e["deadlyDemiseWounds"] > 0 for e in logs)
    assert not allocated_calls, "aucune allocation sur d6 < 6"


def test_dd_player_est_le_proprietaire_de_la_source_sur_les_deux_formes(monkeypatch):
    """`player` = proprietaire de la SOURCE (P1 ici), jet reussi comme jet rate.

    Le jet rate portait `-1` : une fois le type journalise, la ligne step.log sortait `P-1`, hors
    de la grammaire `P(\\d+)` de toutes les lignes — erreur de parse a chaque explosion ratee.
    Le jet reussi portait le player de la VICTIME : c'est la source qui exerce 24.08."""
    import engine.phase_handlers.shared_utils as su
    monkeypatch.setattr(su, "allocate_mortal_wounds", lambda gs, uid, n, auto, sink, *, is_psychic=False: None)

    monkeypatch.setattr(random, "randint", lambda a, b: 6)
    gs = _gs(with_deadly_demise=True, target_col=5, target_row=0)
    destroy_model(gs, "SRC#0", reason="combat")
    hit = next(e for e in _dd_logs(gs) if e["unitId"] == "TGT")
    assert hit["player"] == 1, hit

    monkeypatch.setattr(random, "randint", lambda a, b: 1)
    gs = _gs(with_deadly_demise=True, target_col=5, target_row=0)
    destroy_model(gs, "SRC#0", reason="combat")
    (miss,) = _dd_logs(gs)
    assert miss["player"] == 1, miss


def test_dd_source_videe_n_est_pas_une_unite_dans_le_rayon(monkeypatch):
    """24.08 « each unit within 6" » : l'escouade source dont la figurine qui explose était la
    DERNIÈRE n'a plus de figurine — aucune entrée (donc aucune ligne `SUFFERS N MW`) pour elle.
    `destroy_model` ne la retire d'units_cache qu'après la Deadly Demise : sans ce filtre, le
    journal écrivait `Unit 4 DEADLY DEMISE … → Unit 4(27,30) SUFFERS 1 MW` sur une unité vide
    (mesuré, éval du 2026-09-13, E4 T3). Avec une figurine survivante, la source est bien visée."""
    monkeypatch.setattr(random, "randint", lambda a, b: 6)
    import engine.phase_handlers.shared_utils as su
    monkeypatch.setattr(su, "allocate_mortal_wounds", lambda gs, uid, n, auto, sink, *, is_psychic=False: None)

    gs = _gs(with_deadly_demise=True, target_col=5, target_row=0)
    destroy_model(gs, "SRC#0", reason="combat")
    assert [e["unitId"] for e in _dd_logs(gs)] == ["TGT"], _dd_logs(gs)

    gs = _gs(with_deadly_demise=True, target_col=5, target_row=0)
    gs["models_cache"]["SRC#1"] = {**gs["models_cache"]["SRC#0"], "col": 1, "HP_MAX": 1}
    gs["squad_models"]["SRC"].append("SRC#1")
    gs["units_cache"]["SRC"]["occupied_hexes_by_model"]["SRC#1"] = (1, 0)
    gs["units_cache"]["SRC"]["floor_height_by_model"]["SRC#1"] = 0.0
    gs["units_cache"]["SRC"]["level_by_model"]["SRC#1"] = 0
    destroy_model(gs, "SRC#0", reason="combat")
    assert sorted(e["unitId"] for e in _dd_logs(gs)) == ["SRC", "TGT"], _dd_logs(gs)


def _gs_multi(*, n_targets: int = 3):
    """game_state avec n_targets unités cibles à courte portée (5 subhex chacune)."""
    ish = 5
    src_model = {
        "col": 0, "row": 0, "level": 0, "player": 1, "squad_id": "SRC",
        "HP_CUR": 1, "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0,
        "UNIT_RULES": [_DD_RULE_1],
    }
    src_uc: dict = {
        "col": 0, "row": 0, "player": 1, "HP_CUR": 1,
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0,
        "occupied_hexes": {(0, 0)},
        "occupied_hexes_by_model": {"SRC#0": (0, 0)},
        "floor_height_by_model": {"SRC#0": 0.0},
        "level_by_model": {"SRC#0": 0},
        "MODEL_HEIGHT": 2.0,
    }
    units_cache: dict = {"SRC": src_uc}
    squad_models: dict = {"SRC": ["SRC#0"]}
    models_cache: dict = {"SRC#0": src_model}
    for i in range(n_targets):
        uid = f"TGT{i}"
        col = i + 1
        models_cache[f"{uid}#0"] = {
            "col": col, "row": 0, "level": 0, "player": 2, "squad_id": uid,
            "HP_CUR": 2, "HP_MAX": 2, "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0,
            "UNIT_RULES": [],
        }
        units_cache[uid] = {
            "col": col, "row": 0, "player": 2, "HP_CUR": 2,
            "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0,
            "occupied_hexes": {(col, 0)},
            "occupied_hexes_by_model": {f"{uid}#0": (col, 0)},
            "floor_height_by_model": {f"{uid}#0": 0.0},
            "level_by_model": {f"{uid}#0": 0},
            "MODEL_HEIGHT": 2.0,
        }
        squad_models[uid] = [f"{uid}#0"]
    # Couche `units` : cf. `_gs` — `destroy_model` y rafraîchit le statut 13.09.
    units = [
        {**unit_invariants(), "id": uid, "player": uc["player"], "hideable": False}
        for uid, uc in units_cache.items()
    ]
    return {
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
        "models_cache": models_cache,
        "squad_models": squad_models,
        "units_cache": units_cache,
        "action_logs": [],
        "action_log_seq": 0,
        "board_cols": 44, "board_rows": 44,
        "wall_hexes": set(),
        "_unit_move_version": 0,
        "terrain_areas": [],
        "inches_to_subhex": ish,
        "config": {
            "game_rules": {
                "engagement_zone": 2,
                "max_base_size_hex": 12,
                "unit_model_cohesion_range": 2,
                "unit_global_cohesion_range": 9,
                "squad_min_neighbors": 1,
                "cohesion_distance_mode": "euclidean",
                "plunging_fire_height": 3,
            },
            "move": {
                "can_move_through_enemy_engagement_zone": True,
                "can_move_through_enemy_model": False,
                "can_move_through_friendly_model": True,
            },
        },
        "phase": "fight",
        "turn": 1,
        "player_types": {"1": "ai", "2": "ai"},
    }


def test_dd_d6_1_un_seul_log_meme_avec_plusieurs_cibles(monkeypatch):
    """D6=1 avec 3 unites en portee -> exactement 1 log 'no effect', 0 jet de de par cible."""
    monkeypatch.setattr(random, "randint", lambda a, b: 1)
    import engine.phase_handlers.shared_utils as su
    monkeypatch.setattr(su, "allocate_mortal_wounds", lambda *a, **kw: None)
    gs = _gs_multi(n_targets=3)
    destroy_model(gs, "SRC#0", reason="combat")
    logs = _dd_logs(gs)
    assert len(logs) == 1, (
        f"d6<6 doit produire exactement 1 log 'no effect', obtenu {len(logs)}: {logs}"
    )
    assert logs[0]["d6Roll"] == 1
    assert logs[0]["deadlyDemiseWounds"] == 0


def test_dd_absent_aucune_entree(monkeypatch):
    """Sans la cle deadly_demise en units_cache, aucune entree deadly_demise emise."""
    monkeypatch.setattr(random, "randint", lambda a, b: 6)
    import engine.phase_handlers.shared_utils as su
    monkeypatch.setattr(su, "allocate_mortal_wounds", lambda gs, uid, n, auto, sink, *, is_psychic=False: None)
    gs = _gs(with_deadly_demise=False, target_col=5, target_row=0)
    destroy_model(gs, "SRC#0", reason="combat")
    assert not _dd_logs(gs), "aucune entree deadly_demise sans la cle"


def test_dd_cible_hors_portee_pas_d_entree(monkeypatch):
    """Cible a > 6" (> 30 subhex) -> aucune entree deadly_demise pour cette cible."""
    monkeypatch.setattr(random, "randint", lambda a, b: 6)
    import engine.phase_handlers.shared_utils as su
    monkeypatch.setattr(su, "allocate_mortal_wounds", lambda gs, uid, n, auto, sink, *, is_psychic=False: None)
    # TGT a (40, 0) = 40 subhex, donc 40/5 = 8" > 6"
    gs = _gs(with_deadly_demise=True, target_col=40, target_row=0)
    destroy_model(gs, "SRC#0", reason="combat")
    tgt_logs = [e for e in _dd_logs(gs) if e.get("unitId") == "TGT"]
    assert not tgt_logs, "la cible hors portee ne doit pas recevoir de MW"


def test_dd_le_6_pouces_n_est_pas_isotrope_sur_la_grille(monkeypatch):
    """Même écart de grille (30 cases), verdicts OPPOSÉS — la grille offset n'est pas isotrope.

    24.08 mesure « within 6" », donc une distance RÉELLE (01.04). Dans le repère `_hex_center`
    un pas de colonne vaut 1 subhex et un pas de RANGÉE √3/1,5 ≈ 1,155. À x5 (6" = 30 subhex) :
    30 rangées plein sud = 33,6 subhex, HORS des 6" ; 30 colonnes plein est = 29,0 subhex,
    DEDANS. La mesure sur les écarts de grille BRUTS (`sqrt(dc**2 + dr**2)`) rendait 30 dans les
    deux cas et faisait exploser la cible du sud, à 15 % au-delà de la portée réelle.
    """
    monkeypatch.setattr(random, "randint", lambda a, b: 6)
    import engine.phase_handlers.shared_utils as su
    monkeypatch.setattr(su, "allocate_mortal_wounds", lambda gs, uid, n, auto, sink, *, is_psychic=False: None)

    gs_sud = _gs(with_deadly_demise=True, target_col=0, target_row=30)
    destroy_model(gs_sud, "SRC#0", reason="combat")
    assert not [e for e in _dd_logs(gs_sud) if e["unitId"] == "TGT"], \
        "30 rangées plein sud = 33,6 subhex : hors des 6 pouces"

    gs_est = _gs(with_deadly_demise=True, target_col=30, target_row=0)
    destroy_model(gs_est, "SRC#0", reason="combat")
    assert [e for e in _dd_logs(gs_est) if e["unitId"] == "TGT"], \
        "30 colonnes plein est = 29,0 subhex : dans les 6 pouces"


def test_dd_le_6_pouces_se_mesure_du_bord_des_socles(monkeypatch):
    """01.04 : « measure to or from the closest part of that model's base » — pas centre à centre.

    Socles ronds de 5 subhex (le cas d'un véhicule à x5, celui qui porte Deadly Demise). Cible à
    34 colonnes : 34 subhex de centre à centre, donc HORS des 6" pour une mesure centre à centre,
    mais 29,0 subhex de bord à bord — l'unité explose. Contrôle à 36 colonnes : 31,0 subhex bord
    à bord, hors de portée, donc la borne existe toujours.
    """
    monkeypatch.setattr(random, "randint", lambda a, b: 6)
    import engine.phase_handlers.shared_utils as su
    monkeypatch.setattr(su, "allocate_mortal_wounds", lambda gs, uid, n, auto, sink, *, is_psychic=False: None)

    gs_dedans = _gs(with_deadly_demise=True, target_col=34, target_row=0, base_size=5)
    destroy_model(gs_dedans, "SRC#0", reason="combat")
    assert [e for e in _dd_logs(gs_dedans) if e["unitId"] == "TGT"], \
        "centres à 34 subhex mais bords à 29,0 : dans les 6 pouces"

    gs_dehors = _gs(with_deadly_demise=True, target_col=36, target_row=0, base_size=5)
    destroy_model(gs_dehors, "SRC#0", reason="combat")
    assert not [e for e in _dd_logs(gs_dehors) if e["unitId"] == "TGT"], \
        "bords à 31,0 subhex : hors des 6 pouces"


def test_dd_l_orientation_du_socle_detruit_decide_du_verdict(monkeypatch):
    """Socle OVAL : le contour tourne avec la figurine, donc le verdict des 6" aussi.

    La figurine qui explose porte un socle oval 21x9 subhex (profil véhicule à x5). Cible plein
    est à 40 colonnes : grand axe vers l'est (orientation 0) elle est à 29,0 subhex, DANS les
    6" ; pivotée d'un quart de tour (orientation 3), le petit axe la regarde et elle passe à
    35,0 subhex, HORS des 6". La figurine détruite ayant quitté `models_cache`, son orientation
    doit voyager dans la file avec sa forme : sans elle, le socle se remonte à l'orientation 0
    et l'unité de l'est explose dans les deux cas.
    """
    monkeypatch.setattr(random, "randint", lambda a, b: 6)
    import engine.phase_handlers.shared_utils as su
    monkeypatch.setattr(su, "allocate_mortal_wounds", lambda gs, uid, n, auto, sink, *, is_psychic=False: None)

    gs_grand_axe = _gs(with_deadly_demise=True, target_col=40, target_row=0,
                       src_shape="oval", src_base_size=[21, 9], src_orientation=0)
    destroy_model(gs_grand_axe, "SRC#0", reason="combat")
    assert [e for e in _dd_logs(gs_grand_axe) if e["unitId"] == "TGT"], \
        "grand axe vers la cible : 29,0 subhex, dans les 6 pouces"

    gs_petit_axe = _gs(with_deadly_demise=True, target_col=40, target_row=0,
                       src_shape="oval", src_base_size=[21, 9], src_orientation=3)
    destroy_model(gs_petit_axe, "SRC#0", reason="combat")
    assert not [e for e in _dd_logs(gs_petit_axe) if e["unitId"] == "TGT"], \
        "socle pivoté d'un quart de tour : 35,0 subhex, hors des 6 pouces"


def test_dd_la_file_en_attente_reste_copiable_et_picklable():
    """La file 24.08 traverse les frontières de requête : elle ne porte que des données plates.

    Une allocation humaine 06.02 suspend `drain_mortal_wound_queue` en laissant les explosions
    suivantes dans `game_state`, que `services/game_snapshots` `deepcopy` à chaque capture et que
    `services/game_saves` pickle puis relit sous liste blanche de classes. Une entrée portant un
    objet `Socle` (fabrique par `__new__`) casserait les deux — la capture lèverait
    `TypeError: Socle.__new__() missing 4 required positional arguments`.
    """
    import copy
    import pickle

    gs = _gs(with_deadly_demise=True, target_col=5, target_row=0)
    _destroy_model_raw(gs, "SRC#0", reason="combat")
    queue = gs[MORTAL_WOUND_QUEUE_KEY]
    assert [e["kind"] for e in queue] == ["deadly_demise"], queue

    copie = copy.deepcopy(queue)
    assert copie[0]["base"]["fp"] == queue[0]["base"]["fp"]
    assert pickle.loads(pickle.dumps(queue))[0]["base"]["shape"] == "round"


def test_dd_mutation_verrou(monkeypatch):
    """Verrou mutation : si la mise en file de destroy_model est retiree, aucun log deadly_demise.

    Prouve que le bloc `if _deadly_demise_val is not None: … append({"kind": "deadly_demise"…})`
    dans destroy_model est effectivement atteint quand la cle est presente.
    """
    monkeypatch.setattr(random, "randint", lambda a, b: 6)
    import engine.phase_handlers.shared_utils as su
    monkeypatch.setattr(su, "allocate_mortal_wounds", lambda gs, uid, n, auto, sink, *, is_psychic=False: None)

    # Cas controle : sans deadly_demise -> 0 log (baseline de la mutation)
    gs_no = _gs(with_deadly_demise=False, target_col=5, target_row=0)
    destroy_model(gs_no, "SRC#0", reason="combat")
    assert not _dd_logs(gs_no), "baseline : sans la regle, 0 log"

    # Cas actif : avec deadly_demise -> >= 1 log (echoue si le bloc est retire)
    gs_yes = _gs(with_deadly_demise=True, target_col=5, target_row=0)
    destroy_model(gs_yes, "SRC#0", reason="combat")
    assert _dd_logs(gs_yes), "avec la regle, le log doit apparaitre — echoue si le bloc est mute"


# ── portée FIGURINE : WeirdBoy (CORE Deadly Demise D3) replié dans des Boyz ──────────────
#
# Fold réel du moteur (`_build_enhanced_unit`, modèle inline avec rôle leader → source
# `_inline_…`, règles dans `_ATTACHED_RULE_GROUPS`) : l'union 19.04 de l'escouade PORTE
# deadly_demise tant que le WeirdBoy vit — c'est exactement ce que le moteur ne doit PAS lire.


def _boyz_weirdboy_scenario():
    return {
        "board_ref": "44x60x5",
        "primary_objectives": ["objectives_control"],
        "wall_ref": "walls-none.json",
        "army_faction": {"1": "TYRANIDS", "2": "ORKS"},
        "units": [
            {"id": 1, "unit_type": "Hormagaunt", "player": 1, "col": 3, "row": 3},
            {
                "id": 101, "unit_type": "Boyz", "player": 2, "col": 12, "row": 10,
                "models": [
                    {"col": 12, "row": 10},
                    {"col": 13, "row": 10},
                    {"unit_type": "WeirdBoy", "col": 14, "row": 10},
                ],
            },
        ],
    }


def _load_boyz_weirdboy():
    engine = load_engine_from_scenario(_boyz_weirdboy_scenario())
    gs = engine.game_state
    mc = gs["models_cache"]
    mids = gs["squad_models"]["101"]
    weirdboy = [m for m in mids if mc[m].get("unitType") == "WeirdBoy"]
    boyz = [m for m in mids if mc[m].get("unitType") != "WeirdBoy"]
    assert len(weirdboy) == 1 and len(boyz) == 2, "fold réel attendu : 2 Boyz + 1 WeirdBoy"
    # VERT VACANT : l'union d'escouade porte bien la règle (c'est la donnée piégeuse).
    assert any(r["ruleId"] == "deadly_demise" for r in gs["unit_by_id"]["101"]["UNIT_RULES"])
    return gs, weirdboy[0], boyz


def test_dd_boy_mene_par_weirdboy_vivant_n_explose_pas(monkeypatch):
    """Boy détruit, WeirdBoy vivant dans l'escouade → aucun jet 24.08 (règle propre au WeirdBoy)."""
    monkeypatch.setattr(random, "randint", lambda a, b: 6)
    gs, _wb, boyz = _load_boyz_weirdboy()
    destroy_model(gs, boyz[0], reason="combat")
    assert _dd_logs(gs) == [], "un Boy ne porte pas Deadly Demise : 0 jet, WeirdBoy vivant ou non"


def test_dd_boy_apres_mort_du_weirdboy_n_explose_pas(monkeypatch):
    """WeirdBoy détruit (jet raté) puis Boy détruit → le Boy ne déclenche rien (aucune clé d'escouade rémanente)."""
    monkeypatch.setattr(random, "randint", lambda a, b: 1)
    gs, wb, boyz = _load_boyz_weirdboy()
    destroy_model(gs, wb, reason="combat")
    assert len(_dd_logs(gs)) == 1 and _dd_logs(gs)[0]["d6Roll"] == 1
    monkeypatch.setattr(random, "randint", lambda a, b: 6)
    destroy_model(gs, boyz[0], reason="combat")
    assert len(_dd_logs(gs)) == 1, "le Boy détruit après le WeirdBoy ne doit produire aucun jet"


def test_dd_weirdboy_attache_detruit_explose(monkeypatch):
    """WeirdBoy détruit dans l'escouade → UN jet 24.08, source = l'escouade attachée (101)."""
    monkeypatch.setattr(random, "randint", lambda a, b: 6)
    gs, wb, _boyz = _load_boyz_weirdboy()
    import engine.phase_handlers.shared_utils as su
    monkeypatch.setattr(su, "allocate_mortal_wounds", lambda gs, uid, n, auto, sink, *, is_psychic=False: None)
    destroy_model(gs, wb, reason="combat")
    logs = _dd_logs(gs)
    assert logs and all(e["sourceUnitId"] == "101" and e["d6Roll"] == 6 for e in logs)
