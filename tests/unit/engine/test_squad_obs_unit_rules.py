"""Verrou : l'observation squad expose les CAPACITES D'UNITE, amies comme ennemies.

Trou ferme ici (constat verifie le 2026-07-27). Les regles d'armes etaient devenues visibles
(V11 §9.2.5), pas celles d'unite : `UNIT_CONT_FIELDS`/`UNIT_BIN_FIELDS` n'avaient aucun champ
de regle, et `unit_has_rule_effect` n'apparaissait qu'a UN endroit de tout l'encodage —
`_encode_rule_features`, appelee uniquement par `build_observation`, le pipeline mono-figurine
LEGACY. Le routage envoie le pipeline squad sur `build_squad_observation`, qui n'y passe jamais.
L'agent subissait donc `reroll_charge`, `closest_target_penetration`, `move_after_shooting`…
sans les percevoir, exactement le constat qui avait motive la tranche des regles d'armes.

Depuis le chantier 01, ces capacites ne sont plus des BITS `rule_<id>` mais des ENSEMBLES
D'IDENTIFIANTS entiers (`allies_ability_ids` / `enemies_ability_ids`, 8 slots, `obs_id` du
registre `config/unit_rules.json`) lus par une table d'embedding. Le CANAL change, le contenu
non :
ces tests decrivent le meme jeu qu'avant.

Ce que ces tests verrouillent :
  - les ids decrivent les EFFETS, donc captent aussi les capacites composites des datasheets
    (`cunning_hunters`, `targeted_intercession`, `target_priority`…) ;
  - ils valent pour les entites ENNEMIES (choix de cible et evaluation de menace) ;
  - **19.04** : une escouade menee par un character porte les regles de son leader, et l'id
    DISPARAIT a sa mort — c'est le point qui rendait ce trou couteux depuis la tranche 19.04 ;
  - les marqueurs de ROLE ne sont pas dupliques (le bloc TYPES les porte deja) ;
  - une regle sans effet n'a pas d'id (meme critere que [INDIRECT FIRE] cote armes) ;
  - les ids sont TRIES croissants et paddes a 0 (reproductibilite bit a bit des replays) ;
  - un DEBORDEMENT leve, il ne tronque jamais.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import types
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

from ai.unit_registry import UnitRegistry
from engine.observation_builder import ObservationBuilder
from engine.observation_builder import unit_ability_obs_ids
from engine.observation_entities import (
    UNIT_ABILITY_SLOTS,
    UNIT_RULE_EFFECT_IDS,
    UNIT_STATUS_SLOTS,
    unit_bin_index,
)
from engine.w40k_core import W40KEngine

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
TEMPLATE = os.path.join(
    PROJECT_ROOT,
    "config/agents/ArmageddonAgent/scenarios/training/scenario_training_armageddon.json",
)

# Memes fixtures que test_attached_units_abilities_19_04 : `AssaultIntercessor` porte
# `targeted_intercession` et PAS `reroll_charge` ; `CaptainPowerWeaponBolter` l'inverse.
_BODYGUARD = {
    "id": 101, "unit_type": "AssaultIntercessor", "player": 2, "col": 12, "row": 10,
    "models": [{"col": 12, "row": 10}, {"col": 13, "row": 10}, {"col": 14, "row": 10}],
}
_LEADER = {
    "id": 102, "unit_type": "CaptainPowerWeaponBolter", "player": 2,
    "attached_squad": 101, "col": 15, "row": 10,
}
_ENEMY = {"id": 1, "unit_type": "Intercessor", "player": 1, "col": 3, "row": 3}


def _load(units: List[Dict[str, Any]]) -> W40KEngine:
    scenario = {
        "board_ref": "44x60x5",
        "primary_objectives": ["objectives_control"],
        "wall_ref": "walls-none.json",
        # Faction d'Armée DÉCLARÉE des deux camps : 08.04 la demande à chaque phase de commandement
        # et refuse de la déduire des unités. ADEPTUS ASTARTES est la faction RÉELLE des datasheets
        # de ce fichier (Intercessor, AssaultIntercessor, Captain*).
        "army_faction": {"1": "ADEPTUS ASTARTES", "2": "ADEPTUS ASTARTES"},
        # Corollaire OBLIGATOIRE d'une armée ADEPTUS ASTARTES : la clause du +1 Wound d'Oath
        # en dépend, et la construction de l'observation la lit désormais (bits
        # `*_oath_wound_bonus_active`). Un scénario de production le déclare toujours.
        "uses_codex_detachment": {"1": True, "2": True},
        "units": units,
    }
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "rules_obs.json"
        path.write_text(json.dumps(scenario))
        eng = W40KEngine(
            rewards_config="ArmageddonAgent", training_config_name="x1_debug",
            controlled_agent="ArmageddonAgent", scenario_file=str(path),
            unit_registry=UnitRegistry(), quiet=True, gym_training_mode=True,
            training_n_envs=1,  # UN environnement joue en serie (engine/episode_schedule.py)
        )
        eng.reset(seed=0)
        return eng


def _rule_ids(obs, family: str, row: int) -> set:
    """Capacites en vigueur sur un slot d'entite, relues depuis les `obs_id` ecrits."""
    by_obs_id = {obs_id: rule_id for rule_id, obs_id in unit_ability_obs_ids().items()}
    return {by_obs_id[int(v)] for v in obs[f"{family}_ability_ids"][row] if int(v) != 0}


def test_active_squad_rules_are_observed():
    """L'escouade observee expose ses propres regles (ligne 0 du bloc amis)."""
    eng = _load([_BODYGUARD, _ENEMY])
    obs = eng.obs_builder.build_squad_observation(eng.game_state, "101")
    # `targeted_intercession` se resout en DEUX effets — ce sont les effets qui sont exposes.
    assert _rule_ids(obs, "allies", 0) == {
        "reroll_1_towound", "reroll_towound_target_on_objective"
    }


def test_enemy_squad_rules_are_observed():
    """Les regles de l'ENNEMI sont visibles : elles portent la menace autant que ses armes."""
    eng = _load([_BODYGUARD, _ENEMY])
    obs = eng.obs_builder.build_squad_observation(eng.game_state, "1")
    slot = next(
        i for i in range(ObservationBuilder.K_ENEMY_SLOTS)
        if obs["enemies_bin"][i][unit_bin_index("present")] == 1.0
    )
    assert _rule_ids(obs, "enemies", slot) == {
        "reroll_1_towound", "reroll_towound_target_on_objective"
    }


def test_attached_leader_rule_is_observed_then_extinguished_on_his_death():
    """19.04 dans l'observation : le bit du leader apparait, puis DISPARAIT a sa mort.

    Le cas qui rendait ce trou couteux : depuis 19.04 l'union en vigueur change en cours de
    partie, et l'agent n'en voyait rien.
    """
    from engine.phase_handlers.shared_utils import destroy_model

    eng = _load([_BODYGUARD, _LEADER, _ENEMY])
    before = _rule_ids(eng.obs_builder.build_squad_observation(eng.game_state, "101"), "allies", 0)
    assert "reroll_charge" in before, "regle du Captain attache invisible"

    leader_mid = next(
        mid for mid in eng.game_state["squad_models"]["101"]
        if "attached_from" in eng.game_state["models_cache"][mid]
    )
    destroy_model(eng.game_state, leader_mid, "combat")

    after = _rule_ids(eng.obs_builder.build_squad_observation(eng.game_state, "101"), "allies", 0)
    assert "reroll_charge" not in after, "regle du leader mort toujours observee"
    assert "reroll_1_towound" in after, "l'escouade a perdu ses propres regles au passage"


def test_role_markers_are_not_duplicated_as_rule_ids():
    """`leader`/`sergeant`/`support`/`special_weapon` restent au bloc TYPES, pas ici.

    Contre-epreuve sur le REGISTRE : ces marqueurs n'ont pas d'`obs_id`, donc rien ne pourrait
    les ecrire dans un slot de capacite meme par accident.
    """
    for marker in ("leader", "sergeant", "support", "special_weapon"):
        assert marker not in UNIT_RULE_EFFECT_IDS
        assert marker not in unit_ability_obs_ids()


def test_only_rules_with_a_real_effect_have_a_bit():
    """Aucune regle inerte exposee — meme critere que [INDIRECT FIRE] cote armes.

    `adrenalised_onslaught` est un CHOIX de joueur (Aggression OU Preservation Imperative) que
    le moteur ne resout pas : sans le mecanisme generique de decision agent (P2) elle ne produit
    aucun effet, donc aucun bit. Contre-epreuve : ses deux effets possibles, eux, SONT exposes.
    """
    assert "adrenalised_onslaught" not in UNIT_RULE_EFFECT_IDS
    assert "target_priority" not in UNIT_RULE_EFFECT_IDS  # capacite source, exposee par ses effets
    assert "reroll_1_tohit_fight" in UNIT_RULE_EFFECT_IDS
    assert "reroll_1_save_fight" in UNIT_RULE_EFFECT_IDS


def test_composite_datasheet_abilities_are_captured_through_their_effects():
    """Les capacites nommees des datasheets remontent bien en bits d'EFFET.

    Ancre DONNEE (pas une reimplementation) : ces unites existent dans le registry et portent
    ces capacites. Sans la resolution source -> effet, tous ces bits seraient a zero.
    """
    from engine.phase_handlers.shared_utils import unit_has_rule_effect

    registry = UnitRegistry()
    expected = {
        "GreyHunterPlasmaGun": {"shoot_after_advance", "shoot_after_flee"},   # cunning_hunters
        "AssaultIntercessor": {"reroll_1_towound", "reroll_towound_target_on_objective"},
        "TyranidWarriorRanged": {"charge_after_flee", "shoot_after_flee"},    # adaptable_predators
        "LieutenantStormShield": {"charge_after_flee", "shoot_after_flee"},   # target_priority
        "Boyz": {"reroll_charge"},
        "AggressorFlamestorm": {"closest_target_penetration"},
        "Gargoyle": {"move_after_shooting"},
        "Termagant": {"reactive_move"},
        "Neurogaunt": {"charge_after_advance"},
    }
    for unit_type, wanted in expected.items():
        unit = dict(registry.get_unit_data(unit_type))
        unit.setdefault("id", unit_type)
        got = {r for r in UNIT_RULE_EFFECT_IDS if unit_has_rule_effect(unit, r)}
        assert got == wanted, f"{unit_type}: {got} != {wanted}"


def test_real_training_roster_writes_the_expected_id():
    """Sur le VRAI scenario de training, les Orks ecrivent `reroll_charge` et les SM non.

    Discrimination reelle, pas un montage : c'est la seule des 13 regles portee par les rosters
    SM/Orks actuels — les autres attendent des rosters qui les declarent (Tyranides, Loups…).
    """
    eng = W40KEngine(
        rewards_config="ArmageddonAgent", training_config_name="x5_new",
        controlled_agent="ArmageddonAgent", scenario_file=TEMPLATE,
        unit_registry=UnitRegistry(), quiet=True, gym_training_mode=True,
        training_n_envs=1,  # UN environnement joue en serie (engine/episode_schedule.py)
    )
    obs_ids = unit_ability_obs_ids()
    lit = 0
    for _ in range(4):
        obs, _ = eng.reset()
        for family in ("allies", "enemies"):
            lit += int((obs[f"{family}_ability_ids"] == obs_ids["reroll_charge"]).sum())
    assert lit > 0, "aucune escouade Ork n'ecrit reroll_charge sur 4 resets"

    # Contre-epreuve : une regle qu'aucun roster de training ne porte n'est jamais ecrite.
    obs, _ = eng.reset()
    assert np.all(obs["allies_ability_ids"] != obs_ids["reactive_move"])


# ---------------------------------------------------------------------------
# Chantier 01 — verrous propres au canal « ensembles d'identifiants »
# ---------------------------------------------------------------------------


def _grant_effects(unit: Dict[str, Any], effect_ids: List[str]) -> None:
    """Fait porter a `unit` exactement `effect_ids`, dans l'ORDRE donne.

    Ecrit directement `UNIT_RULES`, la structure que `unit_has_rule_effect` lit — c'est la
    source des capacites en vigueur (19.04), donc le montage est celui du moteur, pas une
    reimplementation.
    """
    unit["UNIT_RULES"] = [{"ruleId": rid, "displayName": rid} for rid in effect_ids]


def test_ability_ids_are_sorted_regardless_of_declaration_order():
    """Verrou de TRI : deux unites de memes capacites, declarees dans deux ORDRES differents,
    produisent des `ability_ids` IDENTIQUES.

    Le pooling somme de l'`EmbeddingBag` rend l'ordre indifferent au reseau, mais pas au debug :
    sans tri, l'observation cesserait d'etre reproductible bit a bit d'un run a l'autre et les
    diffs de replay deviendraient illisibles.
    """
    eng = _load([_BODYGUARD, _ENEMY])
    effects = ["reroll_charge", "shoot_after_advance", "charge_after_flee"]
    unit = next(u for u in eng.game_state["units"] if str(u["id"]) == "101")

    _grant_effects(unit, effects)
    first = eng.obs_builder.build_squad_observation(eng.game_state, "101")["allies_ability_ids"][0]
    _grant_effects(unit, list(reversed(effects)))
    second = eng.obs_builder.build_squad_observation(eng.game_state, "101")["allies_ability_ids"][0]

    assert list(first) == list(second)
    written = [int(v) for v in first if int(v) != 0]
    assert written == sorted(written), "ids non tries"
    assert len(first) == UNIT_ABILITY_SLOTS
    assert all(int(v) == 0 for v in first[len(written):]), "padding non nul"


def test_ability_overflow_raises_and_never_truncates():
    """Verrou de DEBORDEMENT : 9 capacites pour 8 slots -> `ValueError` nommant l'unite.

    Tronquer ferait subir a l'agent des regles qu'il ne percoit pas — exactement le trou que
    V11 §0.30 avait ferme. Le message nomme l'escouade ET les capacites en exces.
    """
    import pytest

    eng = _load([_BODYGUARD, _ENEMY])
    unit = next(u for u in eng.game_state["units"] if str(u["id"]) == "101")
    _grant_effects(unit, list(UNIT_RULE_EFFECT_IDS[: UNIT_ABILITY_SLOTS + 1]))

    with pytest.raises(ValueError, match="101"):
        eng.obs_builder.build_squad_observation(eng.game_state, "101")


def test_duplicate_obs_id_in_the_registry_is_refused_at_load():
    """Verrou d'UNICITE : un `obs_id` duplique leve au chargement du registre.

    Un `obs_id` designe UNE ligne de table d'embedding. Deux regles sur la meme ligne, c'est un
    reseau qui ne peut plus les distinguer — et rien, en entrainement, ne le signalerait.
    """
    import pytest

    from config_loader import _validate_obs_ids

    registry = {
        "a": {"id": "a", "obs_id": 4},
        "b": {"id": "b", "obs_id": 4},
    }
    with pytest.raises(ValueError, match="Duplicate obs_id 4"):
        _validate_obs_ids(registry, "test")

    # … et le domaine est borne : 0 est reserve au padding, 128 sort de la table.
    with pytest.raises(ValueError, match="out of range"):
        _validate_obs_ids({"a": {"id": "a", "obs_id": 0}}, "test")
    with pytest.raises(ValueError, match="out of range"):
        _validate_obs_ids({"a": {"id": "a", "obs_id": 128}}, "test")


def test_out_of_vocabulary_id_raises_at_the_write_site():
    """Verrou de DOMAINE : un `obs_id` hors table leve A L'ECRITURE, pas en aval.

    RIEN ne valide une observation contre son espace sur le chemin d'entrainement (ni
    `check_env`, ni `observation_space.contains`) : les bornes du `Box` DECLARENT le domaine,
    elles ne le font pas respecter. Un id hors vocabulaire atteindrait donc `EmbeddingBag`, ou il
    devient — sur GPU — un `device-side assert` asynchrone a la pile trompeuse. Ici, l'erreur
    nomme l'escouade.
    """
    import pytest

    from engine.observation_entities import OBS_ID_MAX
    from engine.observation_builder import _fill_id_slots

    registry = {"a": 1}
    for bad in (OBS_ID_MAX + 1, 0, -1):
        with pytest.raises(ValueError, match="hors domaine"):
            _fill_id_slots(
                [bad], UNIT_ABILITY_SLOTS, registry=registry, kind="capacites",
                slots_constant="UNIT_ABILITY_SLOTS", squad_id="101",
            )


def test_the_declared_observation_space_bounds_the_id_keys():
    """Les bornes annoncees par l'espace d'observation sont celles du registre.

    Elles ne remplacent pas le garde ci-dessus, mais un `Box` non borne dirait a SB3 (et a qui lit
    la config) qu'un id peut valoir n'importe quoi.
    """
    from gymnasium import spaces as gym_spaces

    from engine.observation_entities import OBS_ID_MAX

    eng = _load([_BODYGUARD, _ENEMY])
    obs_space = eng.observation_space
    assert isinstance(obs_space, gym_spaces.Dict), "obs Dict attendue (une Box n'a pas de cles)"
    id_keys = [k for k in obs_space.spaces if k.endswith("_ids")]
    assert sorted(id_keys) == [
        "allies_ability_ids", "allies_status_ids", "allies_wpn_rule_ids",
        "enemies_ability_ids", "enemies_status_ids", "enemies_wpn_rule_ids",
    ]
    for key in id_keys:
        space = obs_space.spaces[key]
        assert isinstance(space, gym_spaces.Box), f"{key} : Box attendue (bornes lisibles)"
        assert float(space.low.min()) == 0.0, f"{key} : borne basse != 0 (padding)"
        assert float(space.high.max()) == float(OBS_ID_MAX), f"{key} : borne haute != OBS_ID_MAX"


def test_the_ability_slots_are_sorted_by_the_writer():
    """Verrou de TRI cote CAPACITES, jumeau frere du verrou statuts ci-dessous.

    Le test de bout en bout ci-dessus ne l'EXERCE pas : le builder parcourt
    `UNIT_RULE_EFFECT_IDS`, dont les `obs_id` sont deja croissants, donc l'ordre de declaration
    est perdu avant l'ecrivain. Le tri ne se verrouille que la ou une entree DECROISSANTE peut
    l'atteindre — l'ecrivain lui-meme.
    """
    from engine.observation_builder import _fill_id_slots

    abilities = unit_ability_obs_ids()
    ascending = sorted(abilities.values())[:3]
    written = _fill_id_slots(
        list(reversed(ascending)), UNIT_ABILITY_SLOTS, registry=abilities, kind="capacites",
        slots_constant="UNIT_ABILITY_SLOTS", squad_id="101",
    )
    assert list(written) == ascending + [0.0] * (UNIT_ABILITY_SLOTS - len(ascending)), (
        "tri croissant ou padding non appliques aux capacites"
    )


def test_the_status_slots_go_through_the_same_writer():
    """Les statuts empruntent le MEME ecrivain que les capacites (tri, padding, gardes).

    C'est ce qui fait heriter les chantiers 02/03/06 des gardes sans les reecrire — deux
    ecrivains jumeaux auraient diverge sur le premier des deux.
    """
    import pytest

    from engine.observation_builder import _fill_id_slots, unit_status_obs_ids

    statuses = unit_status_obs_ids()
    written = _fill_id_slots(
        [statuses["suppressed"], statuses["battle_shock"]],
        UNIT_STATUS_SLOTS, registry=statuses, kind="statuts",
        slots_constant="UNIT_STATUS_SLOTS", squad_id="101",
    )
    assert list(written) == [
        statuses["battle_shock"], statuses["suppressed"], 0.0, 0.0
    ], "tri croissant ou padding non appliques aux statuts"

    with pytest.raises(ValueError, match="statuts en vigueur"):
        _fill_id_slots(
            [1, 2, 3, 4, 5], UNIT_STATUS_SLOTS, registry=statuses, kind="statuts",
            slots_constant="UNIT_STATUS_SLOTS", squad_id="101",
        )


def test_the_real_registries_load_clean():
    """Les deux registres reels passent la validation, et les 13 effets observes ont un id."""
    from config_loader import get_config_loader

    loader = get_config_loader()
    loader.load_unit_rules_config()
    statuses = loader.load_unit_statuses_config()

    assert set(unit_ability_obs_ids()) == set(UNIT_RULE_EFFECT_IDS)
    # Les trois statuts sont DECLARES des maintenant : c'est ce qui garantit que les chantiers
    # 02, 03 et 06 ne toucheront pas `obs_size`.
    assert set(statuses) == {"battle_shock", "oath_target", "suppressed"}


#: Capacite qui n'existe nulle part : elle simule l'ajout d'une entree au vocabulaire OBSERVE.
_FICTIVE_CAPABILITY = "zz_capacite_fictive"
_VOCABULARY_MARKER = "UNIT_RULE_EFFECT_IDS: Tuple[str, ...] = (\n"


def _entities_source_with_one_more_capability() -> str:
    """Source d'`observation_entities` avec UNE capacite fictive de plus au vocabulaire.

    Patcher le tuple APRES import ne prouverait rien : les `*_SIZE` sont figes au moment de leur
    definition. C'est la source qu'il faut modifier, puis re-executer.
    """
    import engine.observation_entities as oe

    assert oe.__file__, "schema d'entites sans fichier : la source est illisible"
    source = Path(oe.__file__).read_text(encoding="utf-8")
    assert _VOCABULARY_MARKER in source, "declaration du vocabulaire introuvable : adapter ce verrou"
    return source.replace(
        _VOCABULARY_MARKER, _VOCABULARY_MARKER + f'    "{_FICTIVE_CAPABILITY}",\n', 1
    )


def _entities_module_with_one_more_capability() -> Any:
    """Le schema patche, execute dans un module JETABLE — aucun effet sur la session.

    Sert au diagnostic (quel registre a grossi), pas au verdict : le module est une FEUILLE, donc
    il ne voit pas ce qu'un module INTERMEDIAIRE ferait du vocabulaire.
    """
    module = types.ModuleType("engine.observation_entities")
    exec(compile(_entities_source_with_one_more_capability(), "<entities+1>", "exec"),
         module.__dict__)
    # VERT VACANT : sans cette garde, une substitution ratee comparerait le schema a lui-meme.
    assert _FICTIVE_CAPABILITY in module.UNIT_RULE_EFFECT_IDS
    assert len(module.UNIT_RULE_EFFECT_IDS) == len(UNIT_RULE_EFFECT_IDS) + 1
    return module


#: Mesure d'`obs_size` sur le schema patche, dans un PROCESSUS NEUF. Le sous-processus est le
#: motif deja retenu ailleurs pour ce besoin (`test_mask_verification.py`) : re-importer `engine.*`
#: en cours de session laisserait, au moindre incident, un worker `-n 8` travailler sur un schema
#: fictif pour tous les tests suivants. Ici le processus meurt avec la mesure.
#: La source patchee arrive par l'ENTREE STANDARD, elle n'est pas relue depuis un chemin : le
#: parent la tire de `oe.__file__`, donc l'enfant mesure l'arbre que la SESSION a importe. Un
#: chemin re-derive du repertoire courant ferait diverger les deux cotes des que le fichier de
#: test d'un worktree est lance depuis un autre arbre — ce depot travaille en worktrees paralleles.
_MEASURE_SCRIPT = f"""
import sys, types

# Injecte AVANT tout import du paquet : `engine/__init__` tire `w40k_core`, donc le schema reel.
module = types.ModuleType("engine.observation_entities")
exec(compile(sys.stdin.read(), "<entities+1>", "exec"), module.__dict__)
sys.modules["engine.observation_entities"] = module

import engine.observation_builder as ob

# VERT VACANT : si le builder avait importe le schema REEL, la mesure comparerait obs_size a
# lui-meme et le verrou serait vert a vie, quel que soit le couplage.
assert "{_FICTIVE_CAPABILITY}" in ob.UNIT_RULE_EFFECT_IDS, "builder bati sur le vocabulaire NON patche"
print(int(ob.ObservationBuilder.SQUAD_OBS_SIZE_TARGET))
print(ob.__file__)
"""


def _obs_size_with_one_more_capability() -> int:
    """Mesure le NOMBRE, seul verdict qui couvre chaque terme de la formule ou qu'il vive.

    Lire le TEXTE de la formule ne suffit pas : un terme peut venir d'un autre module
    (`PROFILE_BIN_SIZE`) ou d'une indirection (`K_X = _calcule()`), et le couplage y passerait.
    """
    import engine.observation_builder as ob

    result = subprocess.run(
        [sys.executable, "-c", _MEASURE_SCRIPT],
        input=_entities_source_with_one_more_capability(),
        cwd=str(Path(str(ob.__file__)).parents[1]), capture_output=True, text=True,
    )
    assert result.returncode == 0, f"mesure d'obs_size impossible :\n{result.stderr}"
    # Decoupage par LIGNES : un chemin de worktree peut contenir une espace, et un module qui
    # ecrirait sur la sortie standard a l'import ajouterait des jetons — les deux feraient lever
    # un `ValueError` opaque au lieu de l'assertion d'arbre ci-dessous.
    lines = result.stdout.splitlines()
    assert len(lines) >= 2, f"mesure illisible :\n{result.stdout}"
    measured, builder_file = lines[-2], lines[-1]
    # Les deux cotes doivent mesurer le MEME arbre : `frozen` vient du builder de la session,
    # `measured` de celui que l'enfant a importe.
    assert builder_file == str(ob.__file__), (
        f"l'enfant a mesure un autre arbre : {builder_file} au lieu de {ob.__file__}"
    )
    return int(measured)


def test_adding_an_observed_capability_costs_zero_scalar():
    """VERROU DE LA PROMESSE du chantier 01 : allonger le vocabulaire OBSERVE ne bouge pas `obs_size`.

    C'est le verrou qui manquait. Sans lui, le couplage repare le 2026-08-04 pouvait revenir sans
    que rien ne leve : `DECISION_OPTION_BIN_FIELDS` etait bati sur `UNIT_RULE_EFFECT_IDS`, donc
    chaque capacite ajoutee a l'observation coutait 6 scalaires (1 par slot de candidat) et un
    retrain `--new` — l'exact contraire de ce que le chantier 01 existe pour garantir.

    Methode : recalculer `obs_size` dans un processus neuf bati sur un schema d'entites augmente
    d'une capacite fictive, et comparer le NOMBRE (cf. `_obs_size_with_one_more_capability`).

    Le balayage des constantes du schema vient EN PLUS, pour nommer le champ fautif : le nombre
    dit qu'`obs_size` a bouge, le balayage dit lequel des registres a grossi.
    """
    import engine.observation_builder as ob
    import engine.observation_entities as oe

    patched = _entities_module_with_one_more_capability()

    real_ints = {
        name: value
        for name, value in vars(oe).items()
        if name.isupper() and isinstance(value, int)
    }
    assert real_ints, "aucune constante entiere lue : le balayage regarde le mauvais module"
    drifted = {
        name: (value, getattr(patched, name))
        for name, value in real_ints.items()
        if getattr(patched, name) != value
    }
    assert not drifted, (
        f"une capacite OBSERVEE de plus a fait grossir des registres du schema : {drifted}."
    )

    frozen = int(ob.ObservationBuilder.SQUAD_OBS_SIZE_TARGET)
    measured = _obs_size_with_one_more_capability()
    assert measured == frozen, (
        f"une capacite OBSERVEE de plus fait passer obs_size de {frozen} a {measured} "
        f"({measured - frozen:+d} scalaires), donc impose un retrain `--new`. Le vocabulaire "
        "observe ne doit dimensionner AUCUN bloc : le registre positionnel des candidats de "
        "decision est `DECISION_GRANTABLE_EFFECT_IDS`."
    )
