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
  - **19.04** : l'observation suit l'UNION en vigueur quand elle change en cours de partie —
    l'id d'une source DISPARAIT a la mort de sa derniere figurine. Les DEUX sources sont
    verrouillees en observation depuis que `deep_strike` a un `obs_id` : le BODYGUARD
    (`charge_impact`) s'eteint quand sa derniere figurine meurt, le LEADER (`deep_strike`)
    reste tant que le Chaplain vit. Avant cela, aucun character du registre ne portait de regle
    observable (balaye le 2026-08-10) et seule la moitie bodyguard du tableau 19.04 etait
    couverte ici ; le fold cote leader ne l'etait que par une assertion sur `UNIT_RULES`.
    Laquelle source s'eteint quand reste verrouille source par source par
    `test_attached_units_abilities_19_04.py` ;
  - les marqueurs de ROLE ne sont pas dupliques (le bloc TYPES les porte deja) ;
  - une regle sans effet n'a pas d'id (meme critere que [INDIRECT FIRE] cote armes) ;
  - les ids sont TRIES croissants et paddes a 0 (reproductibilite bit a bit des replays) ;
  - un DEBORDEMENT leve, il ne tronque jamais.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import types
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pytest

from ai.unit_registry import UnitRegistry
from engine.observation_builder import ObservationBuilder
from engine.observation_builder import unit_ability_obs_ids
from engine.observation_entities import (
    ONCE_PER_BATTLE_SPENT_STATE_KEYS,
    UNIT_ABILITY_SLOTS,
    UNIT_RULE_EFFECT_IDS,
    UNIT_STATUS_SLOTS,
    unit_bin_index,
)
from engine.w40k_core import W40KEngine
from tests.unit.engine._config_helpers import (
    ATTACHED_BODYGUARD,
    ATTACHED_BODYGUARD_RULE,
    ATTACHED_ENEMY,
    ATTACHED_LEADER,
    ATTACHED_LEADER_RULE,
    ATTACHED_LEADER_RULES,
    attached_scenario,
    load_engine_from_scenario,
)

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
#: ORK contre ORK, rosters FIXES : le seul scenario qui garantit la presence d'une datasheet
#: orke donnee des deux cotes. Les scenarios de training tirent leurs rosters au hasard
#: (`agent_roster_ref: training_random`), ce qui ne construit aucune situation observable.
ORK_VS_ORK = os.path.join(
    PROJECT_ROOT,
    "config/agents/ArmageddonAgent_x1/scenarios/holdout_regular/scenario_bot-04.json",
)

# Fixtures d'unites attachees PARTAGEES avec `test_attached_units_abilities_19_04` : elles y
# etaient recopiees, et la bascule du 2026-08-10 (purge du placeholder `reroll_charge`) a du
# etre appliquee deux fois a la main. Leur contrat — le couple discriminant dans les deux sens
# et les deux regles qui l'opposent — vit desormais dans `_config_helpers`.
_BODYGUARD = ATTACHED_BODYGUARD
_LEADER = ATTACHED_LEADER
_ENEMY = ATTACHED_ENEMY


def _load(units: List[Dict[str, Any]]) -> W40KEngine:
    # `training_n_envs=1` : UN environnement joue en serie (engine/episode_schedule.py). C'est la
    # seule difference avec les autres consommateurs du scenario d'unites attachees.
    return load_engine_from_scenario(attached_scenario(units), training_n_envs=1)


_BY_OBS_ID: Dict[int, str] = {}


def _rule_ids(obs, family: str, row: int) -> set:
    """Capacites en vigueur sur un slot d'entite, relues depuis les `obs_id` ecrits."""
    if not _BY_OBS_ID:
        _BY_OBS_ID.update({obs_id: rule_id for rule_id, obs_id in unit_ability_obs_ids().items()})
    row_vals = obs[f"{family}_ability_ids"][row]
    try:
        return {_BY_OBS_ID[k] for v in row_vals if (k := int(v)) != 0}
    except KeyError as exc:
        raise KeyError(
            f"obs_id {exc} absent de unit_ability_obs_ids (family={family!r}, row={row})"
        ) from exc


#: Regle propre du BODYGUARD, telle que l'observation l'expose. `charge_impact` est un effet
#: direct : contrairement a `targeted_intercession`, elle ne se resout pas en plusieurs effets.
_OBS_REGLE_DU_BODYGUARD = {ATTACHED_BODYGUARD_RULE}


def test_active_squad_rules_are_observed():
    """L'escouade observee expose ses propres regles (ligne 0 du bloc amis)."""
    eng = _load([_BODYGUARD, _ENEMY])
    obs = eng.obs_builder.build_squad_observation(eng.game_state, "101")
    assert _rule_ids(obs, "allies", 0) == _OBS_REGLE_DU_BODYGUARD


def test_enemy_squad_rules_are_observed():
    """Les regles de l'ENNEMI sont visibles : elles portent la menace autant que ses armes."""
    eng = _load([_BODYGUARD, _ENEMY])
    obs = eng.obs_builder.build_squad_observation(eng.game_state, "1")
    slot = next(
        i for i in range(ObservationBuilder.K_ENEMY_SLOTS)
        if obs["enemies_bin"][i][unit_bin_index("present")] == 1.0
    )
    assert _rule_ids(obs, "enemies", slot) == _OBS_REGLE_DU_BODYGUARD


def test_attached_squad_rule_is_observed_then_extinguished_with_its_source():
    """19.04 dans l'observation : le bit d'une source apparait, puis DISPARAIT a sa mort.

    Le cas qui rendait ce trou couteux : depuis 19.04 l'union en vigueur change en cours de
    partie, et l'agent n'en voyait rien.

    La source qui S'ETEINT est le BODYGUARD (`charge_impact`), et le leader attache SURVIT —
    c'est la moitie du tableau 19.04 « until the last model in that bodyguard unit is
    destroyed ». Depuis que `deep_strike` a un `obs_id`, l'autre moitie est observable elle
    aussi : la regle du Chaplain est verifiee PRESENTE avant comme apres, ce qui distingue « le
    bloc suit l'union » de « le bloc s'est vide ». Laquelle source s'eteint quand, c'est
    `test_attached_units_abilities_19_04.py` qui le verrouille, source par source.
    """
    from engine.phase_handlers.shared_utils import destroy_model

    eng = _load([_BODYGUARD, _LEADER, _ENEMY])

    # Le FOLD a bien eu lieu : la regle du Chaplain est dans l'union en vigueur de l'escouade.
    # C'est le chainon que l'observation consomme (`unit["UNIT_RULES"]`) : sans cette assertion,
    # casser `_fold_attached_characters` laisserait TOUT ce fichier vert, puisque la source
    # suivie ci-dessous appartient au bodyguard.
    union = {str(r["ruleId"]) for r in eng.game_state["unit_by_id"]["101"]["UNIT_RULES"]}
    assert ATTACHED_LEADER_RULE in union, (
        "la regle du Chaplain attache n'est pas dans l'union 19.04 : le fold n'a pas eu lieu, "
        "et l'observation lit cette union"
    )
    assert ATTACHED_BODYGUARD_RULE in union, "l'escouade a perdu sa propre regle au fold"

    before = _rule_ids(eng.obs_builder.build_squad_observation(eng.game_state, "101"), "allies", 0)
    assert before == {ATTACHED_BODYGUARD_RULE, *ATTACHED_LEADER_RULES}, (
        "l'observation doit porter les DEUX sources de l'union 19.04 — celle de l'escouade et "
        "celle du leader attache"
    )

    models_cache = eng.game_state["models_cache"]
    natives = [
        mid for mid in eng.game_state["squad_models"]["101"]
        if "attached_from" not in models_cache[mid]
    ]
    assert len(natives) == 3, "fixture : 3 bodyguards attendus"

    # ETAPE 1 — tuer tous les bodyguards SAUF UN. La source vit encore, donc son id doit tenir.
    # Cette assertion POSITIVE apres mutation est le garde anti-vert-vacant du test : sans elle,
    # un bug qui zerote le bloc de capacites de la ligne 0 satisferait l'etape 2 sans rien dire,
    # un ensemble vide passant toutes les assertions negatives. L'etape 2 en pose un second, sur
    # la regle du LEADER, qui elle doit SURVIVRE a la mort du bodyguard.
    for mid in natives[:-1]:
        destroy_model(eng.game_state, mid, "combat")
    mid_course = _rule_ids(
        eng.obs_builder.build_squad_observation(eng.game_state, "101"), "allies", 0
    )
    assert ATTACHED_BODYGUARD_RULE in mid_course, (
        "un bodyguard vit encore : sa regle doit rester observee (19.04, « until the LAST model "
        "in that bodyguard unit is destroyed »)"
    )

    # ETAPE 2 — la derniere figurine de la source meurt : le bit s'eteint.
    destroy_model(eng.game_state, natives[-1], "combat")
    # Le leader vit encore : l'unite existe, et c'est bien la SOURCE morte qui a disparu.
    assert eng.game_state["squad_models"]["101"], "le Chaplain attache doit survivre"
    after = _rule_ids(eng.obs_builder.build_squad_observation(eng.game_state, "101"), "allies", 0)
    assert after == set(ATTACHED_LEADER_RULES), (
        "la regle du bodyguard mort doit disparaitre, celle du Chaplain VIVANT doit rester — "
        "un bloc entierement vide prouverait un zerotage, pas 19.04"
    )


def test_role_markers_are_not_duplicated_as_rule_ids():
    """`leader`/`sergeant`/`support`/`special_weapon` restent au bloc TYPES, pas ici.

    Contre-epreuve sur le REGISTRE : ces marqueurs n'ont pas d'`obs_id`, donc rien ne pourrait
    les ecrire dans un slot de capacite meme par accident.
    """
    for marker in ("leader", "sergeant", "support", "special_weapon"):
        assert marker not in UNIT_RULE_EFFECT_IDS
        assert marker not in unit_ability_obs_ids()


def test_only_rules_with_a_real_effect_have_a_bit():
    """Aucune regle inerte exposee. ⚠️ [INDIRECT FIRE] n illustre plus ce critere : elle est vive
    depuis le 2026-08-16 et donc exposee. Le critere, lui, est inchange.

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
        # Ancre ORK. C'etait `Boyz: {reroll_charge}` avant le chantier 05 : cette capacite
        # etait un placeholder invente, absent de la datasheet, purge des rosters. Gretchin
        # porte la seule capacite ORKE reellement lue par l'observation aujourd'hui.
        "Gretchin": {"cp_gain_on_objective"},
        "AggressorFlamestorm": {"closest_target_penetration"},
        # Deep Strike (24.09) : les trois porteurs des rosters Armageddon. `ChaplainJumpPack`
        # porte aussi `leader`, marqueur de ROLE sans `obs_id` — il ne doit PAS remonter ici.
        # Les autres entrees de ce tableau font la contre-epreuve : aucune ne porte la capacite.
        # Primitive A (chantier 06, passe 1) : les trois porteurs des modificateurs de jet. Le
        # Chaplain en porte DEUX effets avec Deep Strike, ce qui est aussi la contre-epreuve que
        # le bloc suit bien une UNION et non un premier hit.
        #
        # Les seconds effets du Chaplain, du Warboss, du Bigboss et du Vanguard sont entres dans
        # le vocabulaire le 2026-09-08 (les 14 regles qui portaient un `obs_id` sans y figurer).
        # Ils SONT la contre-epreuve de cette livraison : ils etaient appliques par le moteur et
        # absents de `got` tant que le tuple ne les nommait pas.
        "ChaplainJumpPack": {
            "deep_strike", "wound_roll_bonus_fight", "mortal_wounds_on_fight_activation",
        },
        "Warboss": {"hit_roll_bonus_fight", "melee_attacks_bonus_while_waaagh"},
        "Bigboss": {"charge_roll_bonus", "grant_weapon_rule_melee"},
        "VanguardVeteranSquadJumpPack": {"deep_strike", "grant_weapon_rule_melee_after_charge"},
        "LandSpeederOnslaughtGatlingCannon": {"deep_strike", "move_after_shooting"},
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
    """Sur un VRAI scenario, une capacite de datasheet remonte bien dans l'observation.

    Le scenario est ORK contre ORK (`scenario_bot-04`), donc les deux rosters CONTIENNENT
    Gretchin : la situation observee est construite, pas esperee d'un tirage. L'ancien
    montage lisait `scenario_training_armageddon1`, dont les rosters sont tires au hasard
    (`training_random`) — il pariait sur 4 resets pour voir passer un roster orke.

    La capacite lue est `cp_gain_on_objective` (Thievin' Scavengers) : depuis le chantier 05
    c'est la seule capacite ORKE que les rosters Armageddon portent encore.

    PORTEE EXACTE : le verrou repose sur le bloc ENNEMI. Le chemin d'encodage des ALLIES n'est
    pas couvert ici (cf. le commentaire ci-dessous) — il l'est par les tests de ce fichier qui
    construisent leur propre scenario, ou l'escouade active est posee sur le plateau.
    """
    import random as _random
    eng = W40KEngine(
        rewards_config="ArmageddonAgent_x1", training_config_name="x1",
        controlled_agent="ArmageddonAgent_x1", scenario_file=ORK_VS_ORK,
        unit_registry=UnitRegistry(), quiet=True, gym_training_mode=True,
        training_n_envs=1,  # UN environnement joue en serie (engine/episode_schedule.py)
    )
    obs_ids = unit_ability_obs_ids()
    obs, _ = eng.reset()

    # Au reset, la phase est `deployment` : aucune unite n'est encore posee sur le plateau
    # (col=-1 = sentinelle "non deploye"), donc get_enemy_slot_mapping renvoie tout None et
    # `enemies_ability_ids` est nul. On joue jusqu'a la sortie de la phase de deploiement pour
    # que les ennemis soient visibles dans l'observation.
    rng = _random.Random(0)
    assert obs is not None
    for i in range(400):
        ennemis = obs["enemies_ability_ids"]
        # On attend l'id CHERCHÉ, pas « un id quelconque ». Depuis que le Warboss et le Bigboss
        # portent leurs modificateurs de jet (chantier 06), le premier id non nul du bloc ennemi
        # est le leur : sortir de la boucle là dessus faisait tomber l'assertion Gretchin sur une
        # observation où leur escouade n'était simplement pas encore dans les slots ennemis.
        if (eng.game_state.get("phase") != "deployment"
                and int((ennemis == obs_ids["cp_gain_on_objective"]).sum()) > 0):
            break
        valid = list(np.flatnonzero(eng.get_action_mask()))
        assert valid, (
            f"masque entierement vide a l'iteration {i} (phase={eng.game_state.get('phase')!r}) "
            "— invariant moteur viole : aucune action valide hors terminaison"
        )
        action = int(rng.choice(valid))
        obs, _, terminated, truncated, _ = eng.step(action)
        if terminated or truncated:
            obs, _ = eng.reset()
        assert obs is not None
    else:
        raise AssertionError(
            "budget 400 epuise sans trouver cp_gain_on_objective hors deploiement "
            "— augmenter la limite ou verifier que le roster ORK contient Gretchin"
        )

    # Le bloc ENNEMI, et lui seul. En phase de deploiement les unites amies ne sont
    # pas encore posees, donc `allies_ability_ids` est INTEGRALEMENT nul (mesure : 0 valeur non
    # nulle sur 12x8). Sommer les deux blocs laissait croire a une couverture des deux cotes
    # alors que le seul hit venait des ennemis — et rendait la contre-epreuve ci-dessous
    # trivialement vraie, puisqu'un bloc nul satisfait n'importe quelle inegalite.
    assert obs is not None
    ennemis = obs["enemies_ability_ids"]
    assert int((ennemis == obs_ids["cp_gain_on_objective"]).sum()) > 0, (
        "les Gretchin du roster ennemi n'ecrivent pas cp_gain_on_objective"
    )

    # VERT VACANT : la contre-epreuve qui suit ne prouve quelque chose que si ce bloc porte
    # REELLEMENT des identifiants. Un bloc nul les satisferait toutes.
    assert int((ennemis != 0).sum()) > 0, "bloc de capacites ennemi vide : rien n'est observe"

    # Contre-epreuve, DANS LE MEME BLOC : une regle qu'aucun roster de training ne porte n'est
    # jamais ecrite. `reactive_move` appartient aux Tyranides (Termagant, FenrisianWolf).
    assert np.all(ennemis != obs_ids["reactive_move"])


# ---------------------------------------------------------------------------
# 2026-09-08 — les 14 regles qui portaient un `obs_id` sans entrer dans le vocabulaire
# ---------------------------------------------------------------------------


def test_datasheets_of_the_last_uncovered_effects_write_their_ids():
    """Deux datasheets REELLES des rosters d'entrainement ecrivent leurs nouveaux ids.

    `deadly_demise` (WeirdBoy, §24.08) et `oc_bonus` (Ancient, Relic Banner) portaient un
    `obs_id` dans `config/unit_rules.json` et etaient appliquees par le moteur — le premier
    dans `destroy_model`, le second dans `unit_effective_oc`, source UNIQUE de l'OC du controle
    d'objectif — sans figurer dans `UNIT_RULE_EFFECT_IDS` : `unit_ability_obs_ids` ne construit
    sa table QUE sur ce tuple, donc aucun slot ne pouvait les porter.

    Le WeirdBoy est ORK et l'Ancient ADEPTUS ASTARTES : `army_faction` est declare par camp, la
    valeur par defaut du scenario partage ne vaudrait pas pour le camp orke (08.04 refuse de la
    deduire des unites).

    L'Ancient est un SUPPORT attache (19.01) : son `oc_bonus` n'est pas une regle de l'escouade
    Intercessor mais de l'union en vigueur — c'est le meme chemin 19.04 que les autres tests de
    ce fichier, applique a un effet qui n'etait pas observable jusqu'ici.
    """
    scenario = attached_scenario([
        {"id": 1, "unit_type": "WeirdBoy", "player": 1, "col": 5, "row": 5},
        {"id": 101, "unit_type": "Intercessor", "player": 2, "col": 12, "row": 10,
         "models": [{"col": 12, "row": 10}, {"col": 13, "row": 10}, {"col": 14, "row": 10}]},
        {"id": 102, "unit_type": "Ancient", "player": 2, "attached_squad": 101,
         "col": 15, "row": 10},
    ])
    scenario["army_faction"] = {"1": "ORKS", "2": "ADEPTUS ASTARTES"}
    eng = load_engine_from_scenario(scenario, training_n_envs=1)

    weirdboy = _rule_ids(eng.obs_builder.build_squad_observation(eng.game_state, "1"), "allies", 0)
    assert "deadly_demise" in weirdboy, (
        "le WeirdBoy applique Deadly Demise (destroy_model) sans l'ecrire dans ses ability_ids"
    )
    # Seconde capacite de la MEME datasheet, entree par la meme livraison : sa presence prouve
    # que le bloc suit une UNION et non un premier hit.
    assert "weapon_profile_scaling_by_model_count" in weirdboy

    intercessor = _rule_ids(
        eng.obs_builder.build_squad_observation(eng.game_state, "101"), "allies", 0
    )
    assert "oc_bonus" in intercessor, (
        "l'Ancient attache modifie l'OC de l'escouade (unit_effective_oc) sans l'ecrire"
    )
    assert {"feel_no_pain_near_objective", "secure_objective_on_control"} <= intercessor

    # Contre-epreuve : le WeirdBoy ne porte AUCUN des effets de l'escouade adverse, et
    # reciproquement — un bloc qui recopierait tout serait vert sur les assertions ci-dessus.
    assert not (weirdboy & intercessor)


def test_every_registered_obs_id_is_in_the_vocabulary():
    """CONTRAT : un `obs_id` declare est un id OBSERVE. Aucune exception aujourd'hui.

    C'est la moitie manquante du critere du tuple (« seules les regles a effet reel »). Le
    chargeur exige deja qu'une regle du vocabulaire ait un `obs_id` ; rien n'exigeait l'inverse,
    et 14 regles vives ont vecu avec un `obs_id` qu'aucun slot ne pouvait porter — l'agent les
    subissait sans les percevoir.

    Une regle INERTE reste hors vocabulaire : elle doit alors n'avoir AUCUN `obs_id`, pas un id
    declare et ignore. Le cout d'une entree de plus etant de zero scalaire
    (`test_adding_an_observed_capability_costs_zero_scalar`), il n'y a aucune raison de rouvrir
    un ecart ici : c'est pourquoi ce test n'a pas de liste d'exceptions.
    """
    from config_loader import get_config_loader

    registry = get_config_loader().load_unit_rules_config()
    with_obs_id = {rule_id for rule_id, entry in registry.items() if "obs_id" in entry}
    assert len(with_obs_id) >= len(UNIT_RULE_EFFECT_IDS)
    orphelins = sorted(with_obs_id - set(UNIT_RULE_EFFECT_IDS))
    # VERT VACANT : un registre sans aucun `obs_id` laisserait `orphelins` vide et cette
    # assertion passerait sans rien verifier — la garde `>=` ci-dessus l'empeche.
    assert not orphelins, (
        f"regles portant un obs_id sans etre observees : {orphelins} — soit elles entrent dans "
        f"UNIT_RULE_EFFECT_IDS (cout : zero scalaire), soit leur obs_id doit disparaitre du "
        f"registre config/unit_rules.json"
    )
    # Reciproque, deja garantie par `unit_ability_obs_ids` (KeyError au chargement) : ancree ici
    # pour que le contrat se lise dans les DEUX sens au meme endroit.
    assert set(unit_ability_obs_ids()) == set(UNIT_RULE_EFFECT_IDS)


def test_ability_slots_hold_on_every_datasheet():
    """MESURE (sans moteur) : aucun model_type individuel n'excede UNIT_ABILITY_SLOTS effets.

    Complement leger de `test_ability_slots_hold_on_the_real_training_rosters` : celui-ci couvre
    les compositions reelles apres fold 19.04 (attachements), celui-la couvre TOUS les model_types
    du depot — y compris ceux absents des rosters courants. Un nouveau datasheet avec trop de
    regles serait detecte ici AVANT d'apparaitre dans un roster.

    VERT VACANT : un type sans aucune capacite observable tiendrait trivialement dans 8 slots.
    """
    registry = UnitRegistry()
    pire = 0
    detail = ""
    for ut, data in registry.units.items():
        effets = [
            r["ruleId"] for r in data.get("UNIT_RULES", [])
            if r.get("ruleId") in UNIT_RULE_EFFECT_IDS
        ]
        if len(effets) > pire:
            pire = len(effets)
            detail = f"{ut}: {sorted(effets)}"

    assert pire >= 1, (
        f"mesure degeneree (max={pire}) : aucun datasheet ne porte de capacite observable"
    )
    assert pire <= UNIT_ABILITY_SLOTS, (
        f"UNIT_ABILITY_SLOTS={UNIT_ABILITY_SLOTS} deborde sur le datasheet {detail}"
    )


def _max_effets_in_engine(scen_path: Path, label: str, registry: Any) -> tuple[int, str]:
    """Lance le moteur sur `scen_path` et retourne (max_effets, detail) pour cette partie."""
    from engine.phase_handlers.shared_utils import unit_has_rule_effect

    eng = W40KEngine(
        rewards_config="ArmageddonAgent_x1", training_config_name="x1",
        controlled_agent="ArmageddonAgent_x1", scenario_file=str(scen_path),
        unit_registry=registry, quiet=True, gym_training_mode=True, training_n_envs=1,
    )
    eng.reset()
    pire = 0
    detail = ""
    for unit in eng.game_state["units"]:
        effets = [r for r in UNIT_RULE_EFFECT_IDS if unit_has_rule_effect(unit, r)]
        if len(effets) > pire:
            pire = len(effets)
            detail = f"{label} / unite {unit['id']} : {sorted(effets)}"
    return pire, detail


def test_ability_slots_hold_on_the_real_training_rosters():
    """MESURE (pas projection) : les unions 19.04 des rosters d'entrainement tiennent en 8 slots.

    Le debordement est un `raise` (`_fill_id_slots`), donc la marge doit se lire sur les rosters
    reellement joues, avec le vocabulaire du jour. Chaque roster est charge par le CHEMIN DU
    MOTEUR (`agent_roster_ref` -> `_expand_compact_roster_to_basic_units` -> fold 19.04) : rien
    n'est reconstitue ici, sinon la mesure porterait sur une copie du fold, pas sur le fold.

    L'union lue au reset est l'union MAXIMALE de la partie : 19.04 ne fait ensuite qu'en retirer
    des sources a mesure que les figurines meurent.
    """
    import json
    import tempfile

    rosters_dir = Path(PROJECT_ROOT) / "config/agents/ArmageddonAgent_x1/rosters/500pts/training"
    p2_dir = Path(PROJECT_ROOT) / "config/agents/_p2_rosters/500pts/training"
    agent_rosters = sorted(rosters_dir.glob("agent_*.json"))
    assert agent_rosters, f"aucun roster d'entrainement sous {rosters_dir}"

    base_scenario = json.loads(
        (Path(PROJECT_ROOT)
         / "config/agents/ArmageddonAgent_x1/scenarios/training/scenario_training_armageddon1.json"
         ).read_text(encoding="utf-8")
    )
    registry = UnitRegistry()
    pire = 0
    detail = ""
    with tempfile.TemporaryDirectory() as tmp:
        # Le moteur derive l'agent_key et le split du CHEMIN du scenario ; les rosters, eux, sont
        # lus dans le depot. Un scenario jetable a cette forme suffit donc a cibler un roster
        # PRECIS, la ou `scenario_training_armageddon1` en tire un au hasard a chaque episode.
        scen_dir = Path(tmp) / "agents" / "ArmageddonAgent_x1" / "scenarios" / "training"
        scen_dir.mkdir(parents=True)
        for agent_roster in agent_rosters:
            opponent = p2_dir / agent_roster.name.replace("agent_", "opponent_", 1)
            assert opponent.exists(), (
                f"pas de roster adverse jumeau pour {agent_roster.name} : {opponent}"
            )
            scenario = dict(base_scenario)
            scenario["agent_roster_ref"] = f"training/{agent_roster.name}"
            scenario["opponent_roster_ref"] = f"training/{opponent.name}"
            scen_path = scen_dir / f"{agent_roster.stem}.json"
            scen_path.write_text(json.dumps(scenario), encoding="utf-8")
            n, d = _max_effets_in_engine(scen_path, agent_roster.name, registry)
            if n > pire:
                pire, detail = n, d

    # Holdout scenarios : refs explicites, pas de tempdir necessaire.
    holdout_scen_dir = (
        Path(PROJECT_ROOT) / "config/agents/ArmageddonAgent_x1/scenarios/holdout_regular"
    )
    holdout_scens = sorted(holdout_scen_dir.glob("scenario_bot-*.json"))
    assert holdout_scens, f"aucun scenario holdout sous {holdout_scen_dir}"
    for holdout_scen in holdout_scens:
        n, d = _max_effets_in_engine(holdout_scen, holdout_scen.name, registry)
        if n > pire:
            pire, detail = n, d

    # VERT VACANT : une escouade sans aucune capacite tiendrait trivialement dans 8 slots.
    assert pire >= 2, f"mesure vide ou degeneree (max={pire}) : le fold 19.04 n'a rien produit"
    assert pire <= UNIT_ABILITY_SLOTS, (
        f"UNIT_ABILITY_SLOTS={UNIT_ABILITY_SLOTS} deborde sur les rosters training+holdout : {detail}"
    )


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
    """Les deux registres reels passent la validation, et TOUT effet observe a un id."""
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


# ─────────────────────────────────────────────────────────────────────────────
# Capacites 1x/PARTIE : effacees de l'observation une fois DEPENSEES
# ─────────────────────────────────────────────────────────────────────────────
#
# Trou ferme ici (constat verifie le 2026-09-09). `once_per_battle_melee_buff` etait efface par
# une lecture de `finest_hour_used` ecrite EN DUR dans le contexte d'observation ; le seul autre
# effet 1x/partie du vocabulaire, `return_destroyed_models` (Grot Orderly), ne l'etait par rien.
# Son `obs_id` restait donc ecrit dans les `ability_ids` d'une escouade qui avait deja restitue
# ses figurines, et l'agent percevait un avantage eteint pour le reste de la partie. Le filtre
# lit desormais `ONCE_PER_BATTLE_SPENT_STATE_KEYS` et ne nomme plus aucune regle.

#: Une escouade PORTEUSE par effet 1x/partie : la capacite arrive par le LEADER (19.04), seule
#: source de ces deux effets dans les rosters. La cle d'etat est indexee sur l'ID D'ESCOUADE —
#: c'est bien celui-la que le moteur y inscrit (`command_handlers` balaye `game_state["units"]`).
_ONCE_PER_BATTLE_FIXTURES: Dict[str, Any] = {
    "once_per_battle_melee_buff": (
        "ADEPTUS ASTARTES",
        [
            {"id": 101, "unit_type": "Intercessor", "player": 2, "col": 12, "row": 10,
             "models": [{"col": 12, "row": 10}, {"col": 13, "row": 10}]},
            {"id": 102, "unit_type": "CaptainRelicShield", "player": 2,
             "attached_squad": 101, "col": 15, "row": 10},
            {"id": 1, "unit_type": "Intercessor", "player": 1, "col": 3, "row": 3},
        ],
    ),
    "return_destroyed_models": (
        "ORKS",
        [
            {"id": 101, "unit_type": "Boyz", "player": 2, "col": 12, "row": 10,
             "models": [{"col": 12, "row": 10}, {"col": 13, "row": 10}]},
            {"id": 102, "unit_type": "PainBoy", "player": 2,
             "attached_squad": 101, "col": 15, "row": 10},
            {"id": 1, "unit_type": "Boyz", "player": 1, "col": 3, "row": 3},
        ],
    ),
}


def _once_per_battle_scenario(faction: str, units: List[Dict[str, Any]]) -> Dict[str, Any]:
    """`attached_scenario`, mais la Faction d'Armee est celle du roster teste.

    08.04 exige la faction DECLAREE et refuse de la deduire des unites : le couple PainBoy/Boyz
    ne peut donc pas passer par la fixture ADEPTUS ASTARTES partagee.
    """
    scenario = attached_scenario(units)
    scenario["army_faction"] = {"1": faction, "2": faction}
    return scenario


@pytest.mark.parametrize("rule_id", sorted(ONCE_PER_BATTLE_SPENT_STATE_KEYS))
def test_once_per_battle_capability_disappears_once_spent(rule_id: str):
    """Chaque effet 1x/partie du registre disparait des `ability_ids` quand il est depense.

    ROUGE avant le fix pour `return_destroyed_models` : le filtre testait le nom
    `once_per_battle_melee_buff` en dur, donc l'`obs_id` du Grot Orderly restait ecrit.
    """
    faction, units = _ONCE_PER_BATTLE_FIXTURES[rule_id]
    eng = load_engine_from_scenario(_once_per_battle_scenario(faction, units), training_n_envs=1)

    avant = _rule_ids(eng.obs_builder.build_squad_observation(eng.game_state, "101"), "allies", 0)
    assert rule_id in avant, (
        f"VERT VACANT : l'escouade porteuse n'expose meme pas {rule_id!r} avant depense "
        f"(vu : {sorted(avant)}) — la fixture ne met en scene aucune capacite a effacer"
    )

    # Ce que le moteur ecrit quand la capacite est CONSOMMEE, a la cle que le registre designe.
    eng.game_state[ONCE_PER_BATTLE_SPENT_STATE_KEYS[rule_id].spent_key] = {"101"}

    apres = _rule_ids(eng.obs_builder.build_squad_observation(eng.game_state, "101"), "allies", 0)
    assert rule_id not in apres, (
        f"{rule_id!r} est 1x/partie et deja depense, mais reste ecrit dans les ability_ids : "
        "l'agent percoit un avantage qu'il ne peut plus employer"
    )
    assert avant - {rule_id} == apres, (
        f"la depense de {rule_id!r} a change d'autres capacites : {sorted(avant ^ apres)}"
    )


#: Effets du registre qui restent EN VIGUEUR apres avoir ete depenses — le temps d'une phase.
_STILL_IN_EFFECT_RULES = sorted(
    rule_id for rule_id, spec in ONCE_PER_BATTLE_SPENT_STATE_KEYS.items()
    if spec.still_in_effect_key is not None
)


@pytest.mark.parametrize("rule_id", _STILL_IN_EFFECT_RULES)
def test_once_per_battle_capability_stays_visible_while_still_in_effect(rule_id: str):
    """Depense n'est pas eteinte : la capacite reste observee tant que le moteur l'applique.

    Finest Hour consomme son usage a la premiere activation (`finest_hour_used`) mais accorde
    [DEVASTATING WOUNDS] jusqu'a la fin de CETTE phase de combat
    (`finest_hour_active_this_phase`, lu par `shared_utils` et `attack_sequence`). L'effacer des
    l'usage disait a l'agent que l'avantage avait disparu alors que chaque attaque de melee de
    l'escouade en beneficiait encore.

    La garde de PHASE compte autant : `finest_hour_active_this_phase` n'est purge qu'a l'entree
    de la fight phase SUIVANTE, donc il reste peuple pendant les phases intermediaires — sans
    elle, la capacite reapparaitrait hors du combat ou elle agit.
    """
    spec = ONCE_PER_BATTLE_SPENT_STATE_KEYS[rule_id]
    assert spec.still_in_effect_key and spec.still_in_effect_phase
    faction, units = _ONCE_PER_BATTLE_FIXTURES[rule_id]
    eng = load_engine_from_scenario(_once_per_battle_scenario(faction, units), training_n_envs=1)

    eng.game_state[spec.spent_key] = {"101"}
    eng.game_state[spec.still_in_effect_key] = {"101"}

    eng.game_state["phase"] = spec.still_in_effect_phase
    pendant = _rule_ids(eng.obs_builder.build_squad_observation(eng.game_state, "101"), "allies", 0)
    assert rule_id in pendant, (
        f"{rule_id!r} est encore applique par le moteur dans la phase {spec.still_in_effect_phase!r} "
        f"(escouade dans {spec.still_in_effect_key!r}) mais l'observation l'a deja efface"
    )

    # Meme etat, phase suivante : l'ensemble n'a PAS ete purge, la capacite ne doit pas revenir.
    eng.game_state["phase"] = "move"
    hors_phase = _rule_ids(
        eng.obs_builder.build_squad_observation(eng.game_state, "101"), "allies", 0
    )
    assert rule_id not in hors_phase, (
        f"{rule_id!r} reapparait hors de la phase {spec.still_in_effect_phase!r} : "
        f"{spec.still_in_effect_key!r} n'est purge qu'a l'entree de la phase suivante, "
        "la garde de phase est donc obligatoire"
    )


#: Formulations « une seule fois par bataille » des descriptions de `config/unit_rules.json`, FR
#: comme EN. Le registre ne se relit pas dans la config (les cles d'etat sont un detail MOTEUR,
#: pas une donnee de regle 40K) : c'est ce verrou qui interdit la derive, celle-la meme qui avait
#: laisse `return_destroyed_models` observable apres usage. La tolerance de la regex n'est pas
#: cosmetique — un tuple de sous-chaines ratait « une SEULE fois par bataille ».
_ONCE_PER_BATTLE_WORDING_RE = re.compile(
    r"1\s*[x×]\s*/\s*(partie|bataille)"
    r"|une\s+(seule\s+)?fois\s+par\s+(bataille|partie)"
    r"|once\s+per\s+battle",
    re.IGNORECASE,
)


def test_once_per_battle_wording_detection_catches_the_canonical_phrasings():
    """VERT VACANT : la detection doit attraper les formulations qu'elle pretend couvrir."""
    for description in (
        "Primitive F : 1x/partie, en phase de commandement, retourne D3 figurines.",
        "Une seule fois par bataille, cette unite gagne +2 A.",
        "une fois par bataille en phase de corps a corps, les armes gagnent +A.",
        "Faction ability : once per battle, you can call a Waaagh!.",
    ):
        assert _ONCE_PER_BATTLE_WORDING_RE.search(description), description
    assert not _ONCE_PER_BATTLE_WORDING_RE.search(
        "Cette unite relance ses jets de charge a chaque tour."
    ), "la detection accepte une description qui ne parle pas d'usage unique"


def test_every_once_per_battle_rule_is_in_the_spent_registry():
    """Toute regle du vocabulaire annoncee 1x/partie doit avoir ses cles d'etat."""
    from config_loader import get_config_loader

    rules = get_config_loader().load_unit_rules_config()
    annoncees = {
        rule_id for rule_id in UNIT_RULE_EFFECT_IDS
        if _ONCE_PER_BATTLE_WORDING_RE.search(str(rules[rule_id].get("description", "")))
    }
    assert annoncees, (
        "VERT VACANT : aucune description ne porte la mention 1x/partie — le balayage lit le "
        "mauvais champ, il ne prouve plus rien"
    )
    manquantes = annoncees - set(ONCE_PER_BATTLE_SPENT_STATE_KEYS)
    assert not manquantes, (
        f"capacites 1x/partie sans cle d'etat depense, donc observees a vie : {sorted(manquantes)}"
    )
