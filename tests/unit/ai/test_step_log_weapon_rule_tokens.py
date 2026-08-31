"""Chaîne d'affichage des règles d'armes : moteur → step.log → analyzer.

⚠️ **Le maillon que personne ne testait** (constat V11 §0.38, 2026-07-29). L'information d'une
règle d'arme traverse QUATRE maillons avant d'être exploitable :

    record moteur  →  `w40k_core._SHOT_RECORD_FIELD_MAP`  →  ligne step.log  →  regex analyzer

Chaque maillon avait ses tests ; **aucun ne traversait la jonction**. Résultat : les tokens
`Save [DEVASTATING WOUNDS]`, `[HEAVY]` et `[RAPID FIRE:X]` ont cessé d'être émis sans que rien
ne le signale, et les contrôles de conformité de `ai/analyzer_phases/shoot_handler.py` qui les
lisent sont muets — donc `ai/analyzer.py`, que CLAUDE.md désigne comme la stratégie de
validation du training, rend un verdict faux en silence. Le replay (`replayParser.ts`) lit
exactement les mêmes tokens et est aveugle pour la même raison.

Ce fichier verrouille la chaîne ENTIÈRE, avec du code de production à chaque maillon :
  - le record vient du vrai moteur (`build_manual_shoot_allocation`, dés scriptés) ;
  - le mapping est la vraie `_build_shot_details` et la vraie `_SHOT_RECORD_FIELD_MAP` ;
  - la ligne est écrite par le vrai `StepLogger.log_action` ;
  - le verdict est rendu par le vrai `ai.analyzer.parse_step_log`.

Rien n'est simulé sauf le décor (en-tête d'épisode, positions), qui n'est pas le sujet.
"""
from __future__ import annotations

from typing import Any, Dict
import random

import pytest

from engine.phase_handlers import shooting_handlers
from engine.phase_handlers.fight_handlers import build_manual_fight_allocation
from engine.phase_handlers.shared_utils import build_manual_shoot_allocation
from ai.step_logger import LOG_GRAMMAR_VERSION
from tests._state_invariants import turn_state_invariants
from tests.unit.ai._fabriques import entete_step_log, units_cache_entry as _uc


# Unité et arme RÉELLES du roster Space Marines. `sternguard_bolt_rifle` est le seul profil
# qui porte LES TROIS règles en jeu ici — [HEAVY], [DEVASTATING WOUNDS] et [RAPID FIRE:1] —
# ce qui rend les recoupements de l'analyzer réellement exerçables : il ne se contente pas de
# voir un token, il vérifie que l'arme déclare bien la règle et, pour RAPID FIRE, que la
# VALEUR du marqueur correspond à celle de l'armurerie. Avec une arme inventée, le test
# sortirait silencieusement de ces contrôles et ne prouverait rien.
UNIT_TYPE = "SternguardVeteranBoltRifle"
WEAPON_NAME = "Sternguard Bolt Rifle"
WEAPON_RANGE = 120  # 24" en subhexes (inches_to_subhex=5), comme l'armurerie
SHOOTER = (50, 50)
TARGET = (80, 50)  # 30 subhex = 6" — dans la DEMI-portée (60), donc RAPID FIRE s'applique
TARGET_FAR = (160, 50)  # 110 subhex = 22" — dans la portée, HORS demi-portée
OBJECTIVES = ";".join(f"(150,{r})" for r in range(150, 156))

# [SUSTAINED HITS X] : l'analyzer recoupe le marqueur avec l'ARMURERIE (marqueur sur une arme
# qui ne déclare pas la règle = parse error). Il faut donc un profil qui la porte réellement.
SUSTAINED_UNIT = "EradicatorHeavyBolter"
SUSTAINED_WEAPON = "Heavy Bolter"

# [CLOSE-QUARTERS] 24.07 : l'analyzer résout l'arme par son nom dans l'ARMURERIE, pas dans le
# décor de test — une clé d'usage bâtie sur un nom qu'elle ne connaît pas ne serait jamais
# incrémentée, et le test rendrait zéro sans rien prouver. `Sternguard Bolt Pistol` est le
# second profil de tir du MÊME porteur que `WEAPON_NAME` et déclare réellement la règle.
CQ_WEAPON = "Sternguard Bolt Pistol"


def _game_state(weapon_rules, *, moved_inches=0.0, target=TARGET, n_attacks=1,
                unit_rules=(), cover=False, unit_type=UNIT_TYPE, weapon_name=WEAPON_NAME,
                target_models=1, melee=False, target_keywords=(), hp_cur=9):
    """Attaquant '1' vs cible '101', en `gym_training_mode` (allocation auto).

    `target_models` : effectif de la CIBLE. Il ne servait à rien tant qu'aucune règle ne
    dépendait de la taille de la cible ; [BLAST] 24.05 et [CLEAVE] 24.06 comptent leurs dés
    additionnels par tranche de 5 figurines, donc une cible d'UNE figurine sort silencieusement
    de la règle et ne prouve rien.

    `melee` : même décor, arme de CORPS À CORPS et intents de combat. La chaîne à vérifier est
    la même à un verbe près (`SHOT`/`FOUGHT`), et c'est justement le point : [CLEAVE] n'existe
    qu'en mêlée, [BLAST] qu'au tir, et deux harnais séparés laisseraient chacun croire l'autre
    couvert — le motif d'échec n°1 du dépôt.
    """
    weapon = {"ATK": 3, "STR": 4, "AP": -1, "DMG": 1, "NB": 2, "RNG": WEAPON_RANGE,
              "WEAPON_RULES": list(weapon_rules), "code": weapon_name, "display_name": weapon_name}
    attacker = {"id": "1#0", "squad_id": "1", "player": 0, "T": 4, "SHOOT_LEFT": 1,
                "ATTACK_LEFT": n_attacks,
                "col": SHOOTER[0], "row": SHOOTER[1],
                "RNG_WEAPONS": [] if melee else [weapon],
                "CC_WEAPONS": [weapon] if melee else []}
    target_cache = {}
    models_cache = {"1#0": attacker}
    for index in range(target_models):
        mid = f"101#{index}"
        pos = (target[0], target[1] + index)
        models_cache[mid] = {
            "id": mid, "squad_id": "101", "player": 1, "T": 4, "HP_CUR": hp_cur, "HP_MAX": hp_cur,
            "ARMOR_SAVE": 2, "INVUL_SAVE": 7, "role": None, "unitType": "AssaultIntercessor",
            "points_per_hp": 5.0, "VALUE": 10.0, "col": pos[0], "row": pos[1],
            "RNG_WEAPONS": [], "CC_WEAPONS": [],
        }
        target_cache[mid] = pos
    intent = {"model_id": "1#0", "target_unit_id": "101", "weapon_index": 0,
              "n_attacks_resolved": n_attacks,
              # Taille au Select Targets step — la donnée même de [BLAST]/[CLEAVE].
              "target_squad_size_at_declaration": target_models}
    intents_key = "pending_squad_fight_intents" if melee else "pending_squad_shoot_intents"
    return {**turn_state_invariants(),
        "gym_training_mode": True,
        "turn": 1, "phase": "fight" if melee else "shoot",
        "action_logs": [], "action_log_seq": 0,
        "models_cache": models_cache,
        "squad_models": {"1": ["1#0"], "101": list(target_cache)},
        "squad_cache": {"1": {"model_count_at_start": 1},
                        "101": {"model_count_at_start": target_models}},
        "units_cache": {"1": _uc(*SHOOTER, player=0, models={"1#0": SHOOTER}),
                        "101": _uc(*target, player=1, models=target_cache, hp_cur=hp_cur * target_models)},
        "units": [{"id": "1", "player": 0, "unitType": unit_type},
                  {"id": "101", "player": 1, "unitType": "AssaultIntercessor"}],
        # `deployed_on_turn` : clause 2 de [HEAVY] 24.16 (« not set up this turn »), lue par
        # le moteur. 0 = posée avant la bataille.
        # `player` sur l'attaquant : exigé par le décideur d'allocation du COMBAT
        # (`_is_ai_controlled_fight_unit`), qui lève sinon avant tout log.
        "unit_by_id": {"1": {"id": "1", "UNIT_RULES": list(unit_rules), "deployed_on_turn": 0,
                             "player": 0},
                       # `unit_keywords` de la CIBLE : c'est la donnée même de [ANTI-X Y+] 24.03
                       # (« against a target with the X keyword »). Sans elle, l'instance de la
                       # règle n'est retenue par AUCUNE cible et le profil sort sans `ANTI` —
                       # le test passerait au vert en n'ayant rien exercé.
                       "101": {"id": "101", "UNIT_RULES": [], "deployed_on_turn": 0,
                               "player": 1, "unit_keywords": list(target_keywords)}},
        "objectives": [], "units_moved": set(), "units_advanced": set(),
        "inches_to_subhex": 5,
        "moved_distance_by_model": {"1#0": float(moved_inches) * 5},
        # Requis par les caches spatiaux lorsqu'une figurine meurt (`destroy_model` →
        # `remove_from_units_cache` → `update_enemy_adjacent_caches_after_unit_removed`).
        "board_cols": 200,
        "board_rows": 100,
        # engagement_zone déjà en subhexes (1" × inches_to_subhex=5), lu par get_engagement_zone.
        "config": {"game_rules": {"engagement_zone": 5}},
        # Désactive la boucle de décision d'allocation RL : ce harnais teste les tokens du
        # step.log, pas la politique d'allocation. Sans ce flag, `_manual_allocation_step`
        # retourne `allocation_model_pending` avant d'émettre les logs dès que ≥2 modèles
        # cibles sont présents (cas [BLAST] / [CLEAVE] avec TARGET_SQUAD=10).
        "no_gym_allocation_model": True,
        intents_key: {"1": [intent]},
    }


def _engine_shoot_log(monkeypatch, weapon_rules, rolls, *, moved_inches=0.0, target=TARGET,
                      n_attacks=1, unit_rules=(), cover=False, unit_type=UNIT_TYPE,
                      weapon_name=WEAPON_NAME, target_models=1, melee=False,
                      target_keywords=(), units_advanced=False, engaged=False,
                      indirect=False, spotter=False, hp_cur=9):
    """Fait jouer UNE attaque par le vrai moteur et rend (game_state, son action_log).

    `melee=True` passe par `build_manual_fight_allocation` — le MÊME émetteur de log
    (`_emit_squad_shoot_log`) et le même `_build_shot_details`, ce qui est précisément ce qu'on
    veut exercer : un token écrit d'un seul côté du miroir tir/mêlée ne se verrait pas ici.

    `units_advanced=True` place le squad attaquant dans `units_advanced` (10.05 — ASSAULT).
    `engaged` pose l'engagement pour 10.05/10.06. Les DEUX primitives sont remplacées ensemble
    — `_squad_is_in_enemy_er` (que le portier `resolve_squad_shooting_type` interroge) et
    `_squads_are_engaged` (l'engagement AVEC LA CIBLE) : les laisser diverger ferait dire au
    décor qu'une escouade est engagée sans l'être de sa cible, un état que le plateau ne
    produit pas ici. Le patch est requis, pas commode : ce décor minimal ne porte pas la
    `config` que les vraies primitives exigent.

    `indirect=True` pose le type de tir INDIRECT sur l'escouade 1 (10.07). Par défaut la cible
    n'est visible d'aucune unité amie → plancher 6+. `spotter=True` (exige `indirect=True`) rend
    `can_see=True` pour que `_target_visible_to_a_friendly_unit` retourne True, déclenchant le
    plancher 4+ (l'escouade est stationnaire car `moved_inches=0.0`). La règle d'arme
    INDIRECT_FIRE doit figurer dans `weapon_rules` pour que la règle joue (deux moitiés).
    """
    seq = list(rolls)

    def fake(a, b):
        assert seq, "sequence RNG epuisee"
        return seq.pop(0)

    monkeypatch.setattr(random, "randint", fake)
    # `can_see` : False → plancher 6+ (pas de spotter) ; True → plancher 4+ (spotter présent).
    _can_see = bool(spotter)
    monkeypatch.setattr(
        shooting_handlers, "compute_unit_los",
        lambda gs, s, t: {"cover": cover, "can_see": _can_see},
    )
    monkeypatch.setattr(shooting_handlers, "_get_unit_by_id", lambda gs, sid: {"id": sid})

    monkeypatch.setattr(
        shooting_handlers, "_is_adjacent_to_enemy_within_cc_range", lambda gs, u: False
    )
    gs = _game_state(weapon_rules, moved_inches=moved_inches, target=target,
                     n_attacks=n_attacks, unit_rules=unit_rules, cover=cover,
                     unit_type=unit_type, weapon_name=weapon_name,
                     target_models=target_models, melee=melee,
                     target_keywords=target_keywords, hp_cur=hp_cur)
    if units_advanced:
        gs["units_advanced"] = {"1"}
    from engine.phase_handlers import shared_utils as _su
    monkeypatch.setattr(_su, "_squad_is_in_enemy_er", lambda _gs, sid: engaged and sid == "1")
    monkeypatch.setattr(_su, "_squads_are_engaged", lambda _gs, a, b: engaged and a == "1")
    if indirect:
        from engine.phase_handlers.shared_utils import SQUAD_SHOOTING_TYPE_CHOICE_KEY, SHOOTING_TYPE_INDIRECT
        gs[SQUAD_SHOOTING_TYPE_CHOICE_KEY] = {"1": SHOOTING_TYPE_INDIRECT}
    if melee:
        build_manual_fight_allocation(gs, "1")
    else:
        build_manual_shoot_allocation(gs, "1")
    log_type = "combat" if melee else "shoot"
    attack_logs = [l for l in gs["action_logs"] if l.get("type") == log_type]
    assert attack_logs, f"le moteur n'a émis aucun log de type {log_type!r}"
    return gs, attack_logs[0]


class _Bridge:
    """Emprunte à `W40KEngine` le VRAI mapping record → action_details, sans construire le
    moteur complet (qui exigerait un scénario et une partie entière). Les trois membres
    empruntés sont le code de production tel quel — c'est `_SHOT_RECORD_FIELD_MAP` qui est
    le maillon suspect, il doit être exercé, pas réécrit."""

    def __init__(self, game_state):
        from engine.w40k_core import W40KEngine

        self.game_state = game_state
        self._SHOT_RECORD_FIELD_MAP = W40KEngine._SHOT_RECORD_FIELD_MAP
        self._build_shot_details = W40KEngine._build_shot_details.__get__(self)
        self._models_segment_for_unit = W40KEngine._models_segment_for_unit.__get__(self)


def _step_log_lines(tmp_path, gs, raw_log):
    r"""Écrit UNE ligne step.log par jet avec le VRAI StepLogger, et les relit.

    Une ligne par jet : c'est la granularité que produit
    `_flush_squad_action_logs_to_step_logger` et qu'attend l'analyzer (`Dmg:(\d+)HP` par
    attaque, comptage d'index de tir pour le plafond)."""
    from ai.step_logger import StepLogger

    shots = raw_log["shootDetails"]
    assert shots, "le log de tir ne porte aucun jet"
    bridge = _Bridge(gs)

    melee = raw_log.get("type") == "combat"
    out = tmp_path / "engine_line.log"
    logger = StepLogger(output_file=str(out), enabled=True, buffer_size=1)
    logger.episode_number = 1
    for shot in shots:
        logger.log_action(
            unit_id=raw_log["shooterId"],
            action_type="combat" if melee else "shoot",
            phase="fight" if melee else "shoot",
            player=1, success=True, step_increment=True,
            # `fight_state` : le contrat de replay exige `fight_subphase` sur toute ligne de
            # combat (le formateur lève sans, et `log_action` avale l'exception).
            action_details=bridge._build_shot_details(
                raw_log, shot, 1, {"fight_subphase": "fight"} if melee else None
            ),
        )
    logger._flush_buffer()
    marker = " FIGHT : " if melee else " SHOOT : "
    lines = [l for l in out.read_text().splitlines() if marker in l]
    assert len(lines) == len(shots), (
        "le StepLogger n'a pas produit une ligne par jet — `log_action` avale ses exceptions, "
        f"un champ requis manque probablement dans le mapping ({len(lines)}/{len(shots)})"
    )
    return lines


def _step_log_line(tmp_path, gs, raw_log):
    """Première ligne, pour les tests qui ne regardent qu'un jet."""
    return _step_log_lines(tmp_path, gs, raw_log)[0]


def _analyzer_stats(tmp_path, engine_lines, *, unit_type=UNIT_TYPE, target_models=1,
                    melee=False, units_advanced=False, log_grammar=None):
    """Injecte la/les ligne(s) PRODUITE(S) PAR LE MOTEUR dans un step.log valide, et lance
    le vrai analyzer dessus.

    `target_models` peuple le segment `[MODELS:]` de la ligne de départ de la cible : c'est de
    là que l'analyzer tire son effectif, donc la tranche de 5 de [BLAST] / [CLEAVE]. Sans lui,
    la cible vaut UNE figurine et les deux règles n'ajoutent jamais rien — le test passerait
    au vert sans avoir rien exercé.

    `units_advanced=True` injecte une ligne MOVE ADVANCED pour Unit 1 avant les lignes de tir :
    cela peuple `state.units_advanced`, ce qui permet de valider le fallback grammaire < 4
    de la règle ASSAULT (shoot_handler.py : `shooter_id in state.units_advanced`).

    `log_grammar` déclare la version de grammaire de l'entête. `None` (défaut) l'OMET, donc le
    lecteur lève 1 et prend ses chemins de repli — le seul régime que ce fichier exerçait. La
    renseigner à `LOG_GRAMMAR_VERSION` reproduit ce qu'écrit le vrai StepLogger, c'est-à-dire le
    régime de PRODUCTION, où le token fait autorité (`_eligibility_rule_applied`).
    """
    import ai.analyzer as an

    if isinstance(engine_lines, str):
        engine_lines = [engine_lines]
    phase_label = "FIGHT" if melee else "SHOOT"
    body = "\n".join(
        f"[10:00:0{2 + i}] E1 T1 P1 {phase_label} : {l.split(' : ', 1)[1]}"
        for i, l in enumerate(engine_lines)
    )
    adv_dest = (SHOOTER[0] + 10, SHOOTER[1])
    advanced_line = (
        f"[10:00:01] E1 T1 P1 MOVE : Unit 1({adv_dest[0]},{adv_dest[1]})"
        f" ADVANCED from ({SHOOTER[0]},{SHOOTER[1]}) to ({adv_dest[0]},{adv_dest[1]})"
        f" [Roll: 2] [R:+0.0] [MODELS: 1#0@({adv_dest[0]},{adv_dest[1]},z0)] [SUCCESS]\n"
        if units_advanced else ""
    )
    target_models_segment = "[MODELS: " + " ".join(
        f"101#{i}@({TARGET[0]},{TARGET[1] + i},z0)" for i in range(target_models)
    ) + "]"
    log = tmp_path / "step.log"
    log.write_text(entete_step_log(
        f"[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1({SHOOTER[0]},{SHOOTER[1]}) DEPLOYED from (-1,-1) to ({SHOOTER[0]},{SHOOTER[1]}) [R:+0.0] [SUCCESS]\n"
        f"[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101({TARGET[0]},{TARGET[1]}) DEPLOYED from (-1,-1) to ({TARGET[0]},{TARGET[1]}) [R:+0.0] [SUCCESS]\n"
        f"{advanced_line}"
        f"{body}\n",
        units=(
            f"[10:00:00] Unit 1 ({unit_type}) P1: Starting position (-1,-1), HP_MAX=2 base=round/6\n"
            f"[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position (-1,-1), HP_MAX=2 base=round/6 {target_models_segment}\n"
        ),
        log_grammar=log_grammar,
    ))
    return an.parse_step_log(str(log))


# ─────────────────────────────────────────────────────────────────────────────
# [DEVASTATING WOUNDS] 24.10 — la chaîne complète
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def devastating_line(monkeypatch, tmp_path):
    """Un tir dont la blessure est CRITIQUE (6) sur une arme DEVASTATING : la sauvegarde ne
    doit pas être faite, et la ligne doit le dire."""
    gs, raw_log = _engine_shoot_log(monkeypatch, ["DEVASTATING_WOUNDS"], [4, 6])
    assert gs["models_cache"]["101#0"]["HP_CUR"] == 8, "prémisse : le dégât a bien été infligé"
    return _step_log_line(tmp_path, gs, raw_log)


def test_la_ligne_step_log_annonce_la_sauvegarde_sautee(devastating_line):
    """Maillon 1-3 : le token que l'analyzer ET le replay cherchent doit être présent."""
    assert "[DEVASTATING WOUNDS]" in devastating_line, devastating_line


def test_la_ligne_ne_montre_pas_de_jet_de_sauvegarde(devastating_line):
    """24.10 : « no saving throw can be made ». Afficher `Save 6(2+)` sur une blessure
    mortelle est ce que l'analyzer lui-même classe en `devastating_wounds_incorrect`."""
    import re

    assert re.search(r"Save\s+\d+\(", devastating_line) is None, devastating_line


def test_l_analyzer_compte_le_tir_comme_conforme(devastating_line, tmp_path):
    """Maillon 4 : le verdict de conformité de l'analyzer sur la ligne réelle du moteur."""
    stats = _analyzer_stats(tmp_path, devastating_line)

    assert stats["devastating_wounds_incorrect"][1] == 0, stats["devastating_wounds_incorrect"]
    assert stats["devastating_wounds_correct"][1] == 1, (
        "l'analyzer doit compter ce tir en DEVASTATING conforme ; 0 signifie que la chaîne "
        "moteur → step.log → analyzer est rompue"
    )


# ─────────────────────────────────────────────────────────────────────────────
# [HEAVY] 24.16 — même chaîne, autre token
# ─────────────────────────────────────────────────────────────────────────────

def test_le_token_heavy_atteint_step_log(monkeypatch, tmp_path):
    """Bonus HEAVY appliqué (unité immobile) → la ligne doit porter `[HEAVY]` ET le seuil
    d'origine, sans quoi le compteur d'usage de la règle reste à zéro pour toujours."""
    gs, raw_log = _engine_shoot_log(monkeypatch, ["HEAVY"], [3, 4, 2], moved_inches=0.0)
    line = _step_log_line(tmp_path, gs, raw_log)

    assert "[HEAVY]" in line, line
    assert "3+->2+" in line, ("le seuil d'origine et le seuil amélioré doivent tous deux "
                              f"apparaître : {line}")


def test_sans_bonus_heavy_pas_de_token(monkeypatch, tmp_path):
    """Contre-épreuve : l'unité a parcouru 6" (> 3", clause 3 de 24.16) → bonus non appliqué,
    donc aucun token. Un token émis sur la seule déclaration de l'arme serait un faux positif
    pour l'analyzer."""
    gs, raw_log = _engine_shoot_log(monkeypatch, ["HEAVY"], [3, 4, 2], moved_inches=6.0)
    line = _step_log_line(tmp_path, gs, raw_log)

    assert "[HEAVY]" not in line, line


def test_l_analyzer_compte_l_usage_de_heavy(monkeypatch, tmp_path):
    """Maillon 4 : l'usage de [HEAVY] est comptabilisé, et n'est PAS compté comme invalide."""
    gs, raw_log = _engine_shoot_log(monkeypatch, ["HEAVY"], [3, 4, 2], moved_inches=0.0)
    stats = _analyzer_stats(tmp_path, _step_log_line(tmp_path, gs, raw_log))

    usage = {k: v for k, v in stats["weapon_rule_usage"].items() if k[0] == "HEAVY"}
    assert usage, ("aucun usage de HEAVY compté : la chaîne moteur → step.log → analyzer "
                   "est rompue")
    assert all(sum(v.values()) > 0 for v in usage.values()), usage


# ─────────────────────────────────────────────────────────────────────────────
# [RAPID FIRE X] 24.30 — le marqueur porte la VALEUR, que l'analyzer recoupe
# ─────────────────────────────────────────────────────────────────────────────

def test_le_marqueur_rapid_fire_atteint_step_log(monkeypatch, tmp_path):
    """Cible dans la demi-portée → le pool grossit de X, et la ligne porte `[RAPID FIRE:X]`.

    L'analyzer ne se contente pas de voir le marqueur : il vérifie que sa VALEUR correspond à
    celle déclarée par l'arme (sinon `parse_errors`). Le token doit donc porter le bon X."""
    # RNG 120 subhex = 24" ; la cible est à 30 subhex = 6", donc bien dans la demi-portée.
    gs, raw_log = _engine_shoot_log(monkeypatch, ["RAPID_FIRE:1"], [3, 4, 2, 3, 4, 2])
    line = _step_log_line(tmp_path, gs, raw_log)

    assert "[RAPID FIRE:1]" in line, line


def test_hors_demi_portee_pas_de_marqueur(monkeypatch, tmp_path):
    """Contre-épreuve : arme de portée courte → cible hors demi-portée, bonus non appliqué,
    donc aucun marqueur. Un marqueur émis sur la seule déclaration de l'arme serait compté
    comme une erreur de parsing par l'analyzer."""
    gs, raw_log = _engine_shoot_log(monkeypatch, ["RAPID_FIRE:1"], [3, 4, 2], target=TARGET_FAR)
    line = _step_log_line(tmp_path, gs, raw_log)

    assert "RAPID FIRE" not in line, line


def test_le_marqueur_rapid_fire_leve_le_plafond_de_tirs(monkeypatch, tmp_path):
    """LE contrôle qui compte : le plafond de tirs de l'escouade (`shoot_over_rng_nb`).

    `sternguard_bolt_rifle` : NB=2, RAPID_FIRE:1 → 3 attaques dans la demi-portée. Sans le
    marqueur, l'analyzer plafonne à NB=2 et compte le 3ᵉ tir comme une violation ; c'est ce
    qu'il faisait pour TOUTE activation RAPID FIRE avant cette tranche. Le marqueur lui dit
    que le bonus s'applique, et le plafond monte à 3.

    L'analyzer recoupe aussi la VALEUR du marqueur avec l'armurerie : un X faux produirait
    une `parse_errors`. Émettre le token de travers serait donc pire que ne rien émettre."""
    gs, raw_log = _engine_shoot_log(monkeypatch, ["RAPID_FIRE:1"],
                                    [3, 4, 2, 3, 4, 2, 3, 4, 2], n_attacks=2)
    lines = _step_log_lines(tmp_path, gs, raw_log)
    assert len(lines) == 3, f"NB=2 + RAPID FIRE:1 = 3 attaques, {len(lines)} lignes"

    stats = _analyzer_stats(tmp_path, lines)

    assert not [e for e in stats["parse_errors"] if "RAPID FIRE" in e.get("error", "")]
    assert stats["shoot_over_rng_nb"][1] == 0, (
        "le 3ᵉ tir est légitime (NB 2 + bonus 1) ; le compter comme dépassement signifie que "
        "le marqueur n'atteint pas la ligne"
    )


def test_le_controle_per_shot_du_tir_bonus_est_supprime(monkeypatch, tmp_path):
    """Le contrôle « ce tir est-il LE tir bonus ? » a été supprimé, pas remis à zéro.

    24.30 augmente le NOMBRE d'attaques ; aucune attaque n'est « la » bonus. Exiger du log
    qu'il en désigne une, c'est exiger une information que le moteur ne produit plus depuis
    qu'il résout un pool. Le remettre à zéro aurait laissé la mécanique prête à réinventer le
    faux positif."""
    gs, raw_log = _engine_shoot_log(monkeypatch, ["RAPID_FIRE:1"],
                                    [3, 4, 2, 3, 4, 2, 3, 4, 2], n_attacks=2)
    stats = _analyzer_stats(tmp_path, _step_log_lines(tmp_path, gs, raw_log))

    assert "rapid_fire_correct" not in stats
    assert "rapid_fire_incorrect" not in stats


# ─────────────────────────────────────────────────────────────────────────────
# Abilité d'unité (relance de blessure) — le token est le nom de la RÈGLE SOURCE
# ─────────────────────────────────────────────────────────────────────────────

TARGETED_INTERCESSION = {
    "ruleId": "targeted_intercession",
    "displayName": "Targeted Intercession",
    "grants_rule_ids": ["reroll_1_towound"],
    "usage": "and",
}


def test_le_nom_de_l_abilite_apparait_quand_la_relance_a_lieu(monkeypatch, tmp_path):
    """Une blessure de 1 relancée par `reroll_1_towound` → le log nomme l'abilité SOURCE.

    C'est le nom que l'analyzer compte comme usage de la règle (`special_rule_usage`), et
    auquel le frontend accroche son tooltip."""
    gs, raw_log = _engine_shoot_log(monkeypatch, [], [3, 1, 5, 2],  # touche, blessure=1, relance=5, save
                                    unit_rules=[TARGETED_INTERCESSION])
    line = _step_log_line(tmp_path, gs, raw_log)

    assert "[TARGETED INTERCESSION]" in line, line


def test_pas_de_nom_quand_aucune_relance_n_a_lieu(monkeypatch, tmp_path):
    """Discrimination : l'abilité est PRÉSENTE mais la blessure passe du premier coup — rien
    n'a été relancé, donc rien à signaler. Un token posé sur la simple présence de la règle
    ferait compter un usage qui n'a pas eu lieu."""
    gs, raw_log = _engine_shoot_log(monkeypatch, [], [3, 5, 2],  # blessure=5, aucune relance
                                    unit_rules=[TARGETED_INTERCESSION])
    line = _step_log_line(tmp_path, gs, raw_log)

    assert "TARGETED INTERCESSION" not in line, line


def test_l_analyzer_compte_l_usage_de_l_abilite(monkeypatch, tmp_path):
    """Maillon 4 : l'usage de la règle de relance est enfin comptabilisé."""
    gs, raw_log = _engine_shoot_log(monkeypatch, [], [3, 1, 5, 2],
                                    unit_rules=[TARGETED_INTERCESSION])
    stats = _analyzer_stats(tmp_path, _step_log_line(tmp_path, gs, raw_log))

    usage = {k: v for k, v in stats["special_rule_usage"].items() if k[0] == "reroll_1_towound"}
    assert usage and any(sum(v.values()) > 0 for v in usage.values()), (
        "aucun usage compté : la chaîne moteur → step.log → analyzer est rompue"
    )


# ─────────────────────────────────────────────────────────────────────────────
# [COVER] 13.08 — dans CE moteur le couvert dégrade le SEUIL DE TOUCHE
# ─────────────────────────────────────────────────────────────────────────────

def test_le_token_cover_est_rendu_du_cote_de_la_touche(monkeypatch, tmp_path):
    """13.08 : `_cover_worsened_bs` dégrade le seuil de touche de 1. Le token doit donc
    accompagner la TOUCHE, comme [HEAVY] — et non la sauvegarde, modèle du code mort."""
    gs, raw_log = _engine_shoot_log(monkeypatch, [], [4, 4, 2], cover=True)
    line = _step_log_line(tmp_path, gs, raw_log)

    assert "[COVER]" in line, line
    assert "3+->4+" in line, f"seuil dégradé attendu du côté touche : {line}"
    assert "Save 2(2+ AP-1 → 3+)" in line, f"la sauvegarde ne doit pas porter le couvert : {line}"


def test_sans_couvert_aucun_token(monkeypatch, tmp_path):
    """Contre-épreuve fonctionnelle."""
    gs, raw_log = _engine_shoot_log(monkeypatch, [], [4, 4, 2], cover=False)
    line = _step_log_line(tmp_path, gs, raw_log)

    assert "COVER" not in line, line


# ─────────────────────────────────────────────────────────────────────────────
# [SUSTAINED HITS X] 24.36 — la touche additionnelle n'est PAS une attaque
# ─────────────────────────────────────────────────────────────────────────────

def test_la_touche_additionnelle_porte_son_marqueur(monkeypatch, tmp_path):
    """Maillon 1-3 : le moteur marque déjà le record (`sustainedHit`) ; sans le mapping ni le
    token, la ligne est un `Hit None(3+)` que rien ne distingue d'une ligne malformée."""
    gs, raw_log = _engine_shoot_log(monkeypatch, ["SUSTAINED_HITS:1"], [6, 4, 2, 4, 2],
                                    unit_type=SUSTAINED_UNIT, weapon_name=SUSTAINED_WEAPON)
    lines = _step_log_lines(tmp_path, gs, raw_log)

    sustained = [l for l in lines if "[SUSTAINED HITS]" in l]
    assert len(sustained) == 1, lines
    assert "Hit None(" in sustained[0], sustained[0]
    # La touche NORMALE du même jet critique ne porte pas le marqueur.
    assert sum("[SUSTAINED HITS]" in l for l in lines) < len(lines), lines


def test_l_analyzer_ne_compte_pas_la_touche_additionnelle_dans_le_plafond(monkeypatch, tmp_path):
    """Maillon 4, LE défaut : 2 attaques (plafond NB=2) toutes deux critiques produisent
    4 lignes. Compter les touches additionnelles comme des tirs faisait remonter
    `shots over RNG_NB` sur un tir parfaitement légal — signature vécue : 12 lignes de Heavy
    Bolter pour 9 attaques, 3 erreurs."""
    gs, raw_log = _engine_shoot_log(
        monkeypatch, ["SUSTAINED_HITS:1"], [6, 4, 2, 4, 2, 6, 4, 2, 4, 2], n_attacks=2,
        unit_type=SUSTAINED_UNIT, weapon_name=SUSTAINED_WEAPON,
    )
    lines = _step_log_lines(tmp_path, gs, raw_log)
    assert len(lines) == 4, f"prémisse : 2 attaques + 2 touches additionnelles = 4 lignes {lines}"

    stats = _analyzer_stats(tmp_path, lines, unit_type=SUSTAINED_UNIT)

    assert stats["shoot_over_rng_nb"][1] == 0, stats["shoot_over_rng_nb"]


def test_l_analyzer_atteste_l_usage_de_sustained_hits(monkeypatch, tmp_path):
    """1.8 annonçait « NOT USED » sur une règle qui venait de servir : sans marqueur, l'usage
    n'était attestable par rien."""
    gs, raw_log = _engine_shoot_log(monkeypatch, ["SUSTAINED_HITS:1"], [6, 4, 2, 4, 2],
                                    unit_type=SUSTAINED_UNIT, weapon_name=SUSTAINED_WEAPON)
    stats = _analyzer_stats(tmp_path, _step_log_lines(tmp_path, gs, raw_log),
                            unit_type=SUSTAINED_UNIT)

    usage = {k: v for k, v in stats["weapon_rule_usage"].items() if k[0] == "SUSTAINED_HITS"}
    assert usage and any(sum(v.values()) > 0 for v in usage.values()), stats["weapon_rule_usage"]


def test_l_ordre_ignores_cover_avant_sustained_hits_est_le_meme_en_melee_et_au_tir(
    monkeypatch, tmp_path
):
    """VERROU d'ordre : [IGNORES COVER] précède [SUSTAINED HITS] sur la touche additionnelle.

    La branche SHOOT produit les tokens `_HIT_SEGMENT_RULE_TOKENS` (dont [IGNORES COVER]) PUIS
    [SUSTAINED HITS]. La branche FOUGHT les a longtemps déclarés dans l'ordre inverse, sans
    qu'aucun test ne vérifie les POSITIONS — seule la PRÉSENCE était contrôlée. Un lecteur
    qui lirait le premier token d'une paire verrait un comportement différent selon la phase."""
    gs, raw_log = _engine_shoot_log(
        monkeypatch, ["IGNORES_COVER", "SUSTAINED_HITS:1"], [6, 4, 2, 4, 2],
        unit_type=CLEAVE_UNIT, weapon_name=CLEAVE_WEAPON, melee=True,
    )
    lines = _step_log_lines(tmp_path, gs, raw_log)

    # La touche additionnelle n'a pas de dé de touche — c'est sa signature dans le log.
    additional = [l for l in lines if "Hit None(" in l]
    assert len(additional) == 1, (
        f"prémisse : un seul coup additionnel attendu ; {len(additional)} trouvé(s) : {lines}"
    )
    line = additional[0]
    assert "[IGNORES COVER]" in line, f"token absent de la ligne additionnelle : {line}"
    assert "[SUSTAINED HITS]" in line, f"token absent de la ligne additionnelle : {line}"
    pos_ignores = line.index("[IGNORES COVER]")
    pos_sustained = line.index("[SUSTAINED HITS]")
    assert pos_ignores < pos_sustained, (
        f"[IGNORES COVER] doit précéder [SUSTAINED HITS] (miroir du SHOOT branch) : {line}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# [REROLLED:n] — le dé AVANT relance, jusqu'à step.log
# ─────────────────────────────────────────────────────────────────────────────

def test_le_de_d_origine_d_une_relance_atteint_step_log(monkeypatch, tmp_path):
    """Maillon complet `_SHOT_RECORD_FIELD_MAP` -> StepLogger.

    Le nom de la capacité dit que la relance était POSSIBLE ; seul le dé d'origine dit qu'elle a
    EU LIEU et ce qu'elle a changé. Sans l'entrée dans le field map, `Wound 6(4+)` est
    indiscernable d'un 6 direct — alors que le combat log PvP affiche déjà « (1->6) ».

    La forme `Wound N(T+)` reste intacte : l'analyzer et le parseur de replay la lisent par
    regex, d'où un token PARAMÉTRÉ accolé au segment (même forme que `[RAPID FIRE:2]`).
    """
    gs, raw_log = _engine_shoot_log(
        monkeypatch, [], [4, 1, 6, 2],  # touche 4, blessure 1 (echec) -> relance 6, sauvegarde 2
        unit_rules=({"ruleId": "reroll_1_towound", "displayName": "Targeted Intercession"},),
    )
    line = _step_log_line(tmp_path, gs, raw_log)

    assert "Wound 6(4+)" in line, f"la forme lue par l'analyzer ne doit pas bouger : {line}"
    assert "[REROLLED:1]" in line, f"le de d'origine doit etre lisible : {line}"
    assert "[TARGETED INTERCESSION]" in line, line


def test_sans_relance_aucun_token_rerolled(monkeypatch, tmp_path):
    """Contre-épreuve : un jet réussi du premier coup ne porte aucun dé d'origine."""
    gs, raw_log = _engine_shoot_log(monkeypatch, [], [4, 6, 2])
    line = _step_log_line(tmp_path, gs, raw_log)

    assert "REROLLED" not in line, line


# ─────────────────────────────────────────────────────────────────────────────
# Formateur FOUGHT — le jumeau mêlée, qu'AUCUN test n'exécutait
#
# Les tokens ci-dessus sont produits par la branche `action_type == "shoot"` du StepLogger. La
# branche `"combat"` en écrit sa propre copie, segment par segment, et rien ne la faisait tourner :
# seule une inspection du SOURCE (`count(...) == 2`) attestait qu'elle appelait les mêmes helpers.
# Un test qui lit du code ne voit pas ce que le code PRODUIT — il reste vert sur un helper cassé.
#
# PÉRIMÈTRE BORNÉ, à ne pas surinterpréter : ces tests exercent le record moteur, le vrai
# `_SHOT_RECORD_FIELD_MAP` et le vrai formateur FOUGHT. Le record vient d'un tir, pas d'un combat
# joué — c'est légitime ici parce que les deux phases partagent `roll_attack_pool` (donc la forme
# du record) et `_build_shot_details` (donc la traduction). Ce que ces tests NE couvrent pas :
# l'enchaînement propre à la phase de combat qui mène au `log_action`.
# ─────────────────────────────────────────────────────────────────────────────

def _step_log_fight_line(tmp_path, gs, raw_log):
    """Écrit UNE ligne `FOUGHT` avec le VRAI StepLogger, et la relit.

    Jumeau de `_step_log_lines`, à trois différences près : `action_type="combat"` (c'est ce qui
    choisit la branche du formateur), le `fight_state` que cette branche EXIGE (contrat replay :
    `[FIGHT_SUBPHASE:fight]`, posé en production par `_pre_action_fight_state`), et le filtre sur
    le verbe produit."""
    from ai.step_logger import StepLogger

    shots = raw_log["shootDetails"]
    assert shots, "le log ne porte aucun jet"
    bridge = _Bridge(gs)

    out = tmp_path / "fight_line.log"
    logger = StepLogger(output_file=str(out), enabled=True, buffer_size=1)
    logger.episode_number = 1
    logger.log_action(
        unit_id=raw_log["shooterId"], action_type="combat", phase="fight",
        player=1, success=True, step_increment=True,
        action_details=bridge._build_shot_details(
            raw_log, shots[0], 1, {"fight_subphase": "fight"}
        ),
    )
    logger._flush_buffer()
    lines = [l for l in out.read_text().splitlines() if " FOUGHT " in l]
    assert len(lines) == 1, (
        "le StepLogger n'a pas produit de ligne FOUGHT — `log_action` avale ses exceptions, un "
        f"champ requis manque probablement dans le mapping ({len(lines)} ligne(s))"
    )
    return lines[0]


def test_la_melee_nomme_la_relance_de_blessure_et_son_de_d_origine(monkeypatch, tmp_path):
    """Côté BLESSURE, la ligne de mêlée porte les mêmes deux tokens que celle de tir.

    C'est le motif d'échec n°1 du dépôt : le tir affichait la capacité et le dé d'origine, la
    mêlée pouvait cesser de le faire sans qu'aucun test ne rougisse."""
    gs, raw_log = _engine_shoot_log(
        monkeypatch, [], [4, 1, 6, 2],  # touche 4, blessure 1 (échec) -> relance 6, sauvegarde 2
        unit_rules=(TARGETED_INTERCESSION,),
    )
    line = _step_log_fight_line(tmp_path, gs, raw_log)

    assert "Wound 6(4+)" in line, f"la forme lue par l'analyzer ne doit pas bouger : {line}"
    assert "[REROLLED:1]" in line, f"le dé d'origine doit être lisible : {line}"
    assert "[TARGETED INTERCESSION]" in line, line


def test_la_melee_nomme_la_relance_de_touche(monkeypatch, tmp_path):
    """Côté TOUCHE, jumeau du précédent — c'est ce que l'inspection de source gardait.

    `hitAbility` est posé sur le record par les deux rollers (Oath of Moment relance en mêlée
    aussi, cf. `test_faction_abilities`) : on le pose ici sur le record du moteur pour que le
    VRAI field map le traduise et que le VRAI formateur le rende."""
    gs, raw_log = _engine_shoot_log(monkeypatch, [], [1, 4, 6, 2])
    raw_log["shootDetails"][0]["hitAbility"] = "Oath of Moment"
    raw_log["shootDetails"][0]["attackRollInitial"] = 1
    line = _step_log_fight_line(tmp_path, gs, raw_log)

    assert "[OATH OF MOMENT]" in line, line
    assert "[REROLLED:1]" in line, f"le dé d'origine de la touche doit être lisible : {line}"


def test_la_melee_ne_pose_aucun_token_sans_relance(monkeypatch, tmp_path):
    """Contre-épreuve : sans capacité ni relance, la ligne de mêlée ne porte aucun de ces tokens.

    Sans elle, un formateur qui écrirait les tokens INCONDITIONNELLEMENT passerait les deux
    tests ci-dessus."""
    gs, raw_log = _engine_shoot_log(monkeypatch, [], [4, 6, 2])
    line = _step_log_fight_line(tmp_path, gs, raw_log)

    assert "Wound 6(4+)" in line, f"la ligne doit bien décrire l'attaque : {line}"
    assert "REROLLED" not in line, line
    assert "OATH" not in line, line


# ─────────────────────────────────────────────────────────────────────────────
# [TWIN-LINKED] 24.38 — règle d'ARME relanceuse, jumeau des capacités d'unité ci-dessus
# ─────────────────────────────────────────────────────────────────────────────

def test_la_relance_twin_linked_est_nommee_dans_step_log(monkeypatch, tmp_path):
    """Blessure ratée relancée par [TWIN-LINKED] → step.log nomme la RÈGLE.

    `woundAbility` ne nomme que les capacités d'UNITÉ (`resolve_wound_reroll_ability` rend
    None sur la cause `twin_linked`, la règle venant de l'arme) : sans champ dédié, step.log
    montrait `Wound 5(4+) [REROLLED:1]` — un dé relancé sans cause, alors que la relance d'une
    capacité, elle, est nommée. C'est l'asymétrie exacte que le Game Log PvP a fermée, et cette
    chaîne-ci (moteur → field map → formateur) doit la fermer aussi."""
    gs, raw_log = _engine_shoot_log(monkeypatch, ["TWIN_LINKED"], [3, 1, 5, 2])
    line = _step_log_line(tmp_path, gs, raw_log)

    assert "[REROLLED:1]" in line, f"le dé d'origine doit être lisible : {line}"
    assert "[TWIN-LINKED]" in line, line


def test_sans_relance_twin_linked_ne_dit_rien(monkeypatch, tmp_path):
    """Discrimination : l'arme EST [TWIN-LINKED] mais la blessure passe du premier coup — rien
    n'a été relancé. Un token posé sur la présence de la règle annoncerait une relance qui n'a
    pas eu lieu."""
    gs, raw_log = _engine_shoot_log(monkeypatch, ["TWIN_LINKED"], [3, 5, 2])
    line = _step_log_line(tmp_path, gs, raw_log)

    assert "REROLLED" not in line, line
    assert "TWIN" not in line, line


def test_la_melee_nomme_aussi_la_relance_twin_linked(monkeypatch, tmp_path):
    """JUMEAU mêlée : `roll_attack_pool` est partagé, donc la cause `twin_linked` arrive
    identique — le formateur FOUGHT doit la rendre comme le formateur SHOT."""
    gs, raw_log = _engine_shoot_log(monkeypatch, ["TWIN_LINKED"], [3, 1, 5, 2])
    line = _step_log_fight_line(tmp_path, gs, raw_log)

    assert "[TWIN-LINKED]" in line, line


def test_l_analyzer_compte_l_usage_de_twin_linked(monkeypatch, tmp_path):
    """Maillon 4 : le token [TWIN-LINKED] doit alimenter le compteur d'usage de §1.8.

    Sans ce compteur, une arme TWIN_LINKED dont les relances ont joué ressort « NOT USED »
    dans le tableau — même écart que [MELTA] mesuré sur le run du 2026-08-11."""
    gs, raw_log = _engine_shoot_log(monkeypatch, ["TWIN_LINKED"], [3, 1, 5, 2])
    stats = _analyzer_stats(tmp_path, _step_log_line(tmp_path, gs, raw_log))

    usage = {k: v for k, v in stats["weapon_rule_usage"].items() if k[0] == "TWIN_LINKED"}
    assert usage, ("aucun usage de TWIN_LINKED compté : la chaîne moteur → step.log → analyzer "
                   "est rompue")
    assert all(sum(v.values()) > 0 for v in usage.values()), usage


# ─────────────────────────────────────────────────────────────────────────────
# [MELTA X] 24.25 — le token n'atteignait PAS step.log
#
# Le moteur applique bien le bonus de dégâts (`shared_utils` : `dmg_bonus`), et le token
# `[MELTA:X]` existait — mais seulement dans la ligne de synthèse du Game Log, dont un
# commentaire du moteur note lui-même qu'« aucun consommateur ne l'analyse ». Le journal que
# lisent l'analyzer et le replay, lui, ne portait rien : mesuré sur le run du 2026-08-11,
# 708 tirs de Multi-Melta et une paire (MELTA, Multi-Melta) rendue « NOT USED » par le rapport.
# ─────────────────────────────────────────────────────────────────────────────

MELTA_UNIT = "LandSpeederOnslaughtGatlingCannon"
MELTA_WEAPON = "Multi-Melta"   # armurerie : ["HEAVY", "MELTA:2"]


def test_le_token_melta_atteint_step_log(monkeypatch, tmp_path):
    """Cible dans la demi-portée → bonus appliqué → la ligne doit porter `[MELTA:2]`.

    Grammaire commune à [RAPID FIRE:X] : le X est celui que DÉCLARE l'arme, jamais le total
    de dégâts ajoutés."""
    gs, raw_log = _engine_shoot_log(monkeypatch, ["MELTA:2"], [3, 4, 2],
                                    unit_type=MELTA_UNIT, weapon_name=MELTA_WEAPON)
    line = _step_log_line(tmp_path, gs, raw_log)

    assert "[MELTA:2]" in line, line


def test_hors_demi_portee_pas_de_token_melta(monkeypatch, tmp_path):
    """Contre-épreuve 24.25 : « if the target was within half range ». Hors demi-portée le
    bonus n'est pas appliqué, donc rien ne doit être dit — un token posé sur la seule
    déclaration de l'arme ferait compter une règle qui n'a pas joué."""
    gs, raw_log = _engine_shoot_log(monkeypatch, ["MELTA:2"], [3, 4, 2], target=TARGET_FAR,
                                    unit_type=MELTA_UNIT, weapon_name=MELTA_WEAPON)
    line = _step_log_line(tmp_path, gs, raw_log)

    assert "MELTA" not in line, line


def test_l_analyzer_compte_l_usage_de_melta(monkeypatch, tmp_path):
    """Maillon 4 : sans ce compteur, §1.8 déclarait morte une règle vive."""
    gs, raw_log = _engine_shoot_log(monkeypatch, ["MELTA:2"], [3, 4, 2],
                                    unit_type=MELTA_UNIT, weapon_name=MELTA_WEAPON)
    stats = _analyzer_stats(tmp_path, _step_log_line(tmp_path, gs, raw_log),
                            unit_type=MELTA_UNIT)

    usage = {k: v for k, v in stats["weapon_rule_usage"].items() if k[0] == "MELTA"}
    assert usage, ("aucun usage de MELTA compté : la chaîne moteur → step.log → analyzer "
                   "est rompue")
    assert all(sum(v.values()) > 0 for v in usage.values()), usage


# ─────────────────────────────────────────────────────────────────────────────
# [RAPID FIRE X] et [DEVASTATING WOUNDS] : le token atteignait step.log, mais §1.8 ne le
# comptait pas. Une règle vive rendue « NOT USED » affirme que le moteur ne l'applique pas.
# ─────────────────────────────────────────────────────────────────────────────

def test_l_analyzer_compte_l_usage_de_rapid_fire(monkeypatch, tmp_path):
    """4 080 marqueurs `[RAPID FIRE:x]` dans le journal du 2026-08-11, 0 usage compté."""
    gs, raw_log = _engine_shoot_log(monkeypatch, ["RAPID_FIRE:1"], [3, 4, 2, 3, 4, 2])
    stats = _analyzer_stats(tmp_path, _step_log_lines(tmp_path, gs, raw_log))

    usage = {k: v for k, v in stats["weapon_rule_usage"].items() if k[0] == "RAPID_FIRE"}
    assert usage, "aucun usage de RAPID_FIRE compté"
    assert all(sum(v.values()) > 0 for v in usage.values()), usage


def test_l_analyzer_ventile_devastating_wounds_par_arme(devastating_line, tmp_path):
    """La règle avait une ligne GLOBALE mais aucune ventilation : le tableau des paires
    déclarait « NOT USED » ce que la même page comptait 336 fois."""
    stats = _analyzer_stats(tmp_path, devastating_line)

    usage = {k: v for k, v in stats["weapon_rule_usage"].items() if k[0] == "DEVASTATING_WOUNDS"}
    assert usage, "aucun usage de DEVASTATING_WOUNDS ventilé par arme"
    assert sum(sum(v.values()) for v in usage.values()) == stats["devastating_wounds_correct"][1], (
        "sur CE tir, dont l'arme est portée par le type d'escouade, la ventilation et la ligne "
        "globale comptent le même fait"
    )


# ─────────────────────────────────────────────────────────────────────────────
# [PRECISION] 24.28 — dernier token de la famille à ne pas atteindre step.log
#
# Même histoire que [MELTA] : appliqué par le moteur, rendu dans la ligne de synthèse du Game
# Log, absent du journal que lisent l'analyzer et le replay. Le drapeau vient du groupe
# (`precision_applied`, posé à l'Allocation Order step) : ce test part du log de groupe RÉEL et
# y pose le drapeau, puis exerce les maillons ajoutés — mapping `_build_shot_details`, formateur
# `StepLogger`, regex de l'analyzer. Construire une allocation sur un CHARACTER visible relève
# du test moteur, qui la couvre déjà (`tests/unit/engine/test_weapon_rule_log_tokens.py`).
# ─────────────────────────────────────────────────────────────────────────────

def test_le_token_precision_atteint_step_log(monkeypatch, tmp_path):
    """Le drapeau du groupe doit ressortir en `[PRECISION]` sur la ligne."""
    gs, raw_log = _engine_shoot_log(monkeypatch, ["PRECISION"], [3, 4, 2])
    assert "precisionApplied" in raw_log, (
        "le log de groupe doit PORTER le drapeau : sans lui, aucun maillon suivant ne peut le voir"
    )
    raw_log["precisionApplied"] = True
    line = _step_log_line(tmp_path, gs, raw_log)

    assert "[PRECISION]" in line, line


def test_sans_application_aucun_token_precision(monkeypatch, tmp_path):
    """Contre-épreuve 24.28 : contre une cible sans CHARACTER visible la règle n'impose aucun
    groupe d'allocation — elle n'a rien fait, elle ne dit rien."""
    gs, raw_log = _engine_shoot_log(monkeypatch, ["PRECISION"], [3, 4, 2])
    assert raw_log["precisionApplied"] is False, "prémisse : le moteur ne l'a pas appliquée"
    line = _step_log_line(tmp_path, gs, raw_log)

    assert "PRECISION" not in line, line


def test_l_analyzer_compte_l_usage_de_precision(monkeypatch, tmp_path):
    """Maillon 4 : sans ce compteur, §1.8 déclarait la règle morte."""
    gs, raw_log = _engine_shoot_log(monkeypatch, ["PRECISION"], [3, 4, 2])
    raw_log["precisionApplied"] = True
    stats = _analyzer_stats(tmp_path, _step_log_line(tmp_path, gs, raw_log))

    usage = {k: v for k, v in stats["weapon_rule_usage"].items() if k[0] == "PRECISION"}
    assert usage, "aucun usage de PRECISION compté"
    assert all(sum(v.values()) > 0 for v in usage.values()), usage


# ─────────────────────────────────────────────────────────────────────────────
# [BLAST] 24.05 (tir) et [CLEAVE X] 24.06 (mêlée) — les dés additionnels par
# tranche de 5 figurines de la CIBLE. Le token dit que la règle a joué ; le
# NOMBRE de dés, lui, est recalculé par l'analyzer.
# ─────────────────────────────────────────────────────────────────────────────

# Paires (unité, arme) RÉELLES des rosters : l'analyzer recoupe le marqueur avec l'armurerie
# (marqueur sur une arme qui ne déclare pas la règle = parse error, valeur différente = parse
# error). Avec une arme inventée, le test sortirait silencieusement de ces deux contrôles.
BLAST_UNIT = "DeathwingTerminatorPlasmaCannon"
BLAST_WEAPON = "Plasma Cannon (Standard)"   # [BLAST], forme nue → X = 1
CLEAVE_UNIT = "Bigboss"
CLEAVE_WEAPON = "Two-Handed Big Choppa"     # [CLEAVE:1], NB 5
TARGET_SQUAD = 10                           # 10 // 5 = 2 dés additionnels


def _blast_log(monkeypatch, rolls, *, target_models=TARGET_SQUAD, n_attacks=3):
    return _engine_shoot_log(
        monkeypatch, ["BLAST"], rolls, n_attacks=n_attacks, unit_type=BLAST_UNIT,
        weapon_name=BLAST_WEAPON, target_models=target_models,
    )


def _cleave_log(monkeypatch, rolls, *, target_models=TARGET_SQUAD, n_attacks=5):
    return _engine_shoot_log(
        monkeypatch, ["CLEAVE:1"], rolls, n_attacks=n_attacks, unit_type=CLEAVE_UNIT,
        weapon_name=CLEAVE_WEAPON, target_models=target_models, melee=True,
    )


def test_le_marqueur_blast_atteint_step_log(monkeypatch, tmp_path):
    """Cible de 10 figurines → 2 dés additionnels, et la ligne doit le dire."""
    gs, raw_log = _blast_log(monkeypatch, [4] * 40)
    line = _step_log_line(tmp_path, gs, raw_log)

    assert "[BLAST:1]" in line, line


def test_le_marqueur_cleave_atteint_step_log(monkeypatch, tmp_path):
    """JUMEAU mêlée : même règle, même token, même site d'écriture."""
    gs, raw_log = _cleave_log(monkeypatch, [4] * 40)
    line = _step_log_line(tmp_path, gs, raw_log)

    assert "[CLEAVE:1]" in line, line


def test_cible_de_moins_de_cinq_figurines_ne_dit_rien(monkeypatch, tmp_path):
    """Contre-épreuve : l'arme DÉCLARE la règle, mais 4 // 5 = 0 dé — elle n'a rien fait.
    Un token posé sur la déclaration serait compté comme une erreur par l'analyzer."""
    gs, raw_log = _blast_log(monkeypatch, [4] * 40, target_models=4)
    assert "BLAST" not in _step_log_line(tmp_path, gs, raw_log)

    gs, raw_log = _cleave_log(monkeypatch, [4] * 40, target_models=4)
    assert "CLEAVE" not in _step_log_line(tmp_path, gs, raw_log)


def test_le_marqueur_cleave_leve_le_plafond_d_attaques(monkeypatch, tmp_path):
    """LE contrôle qui compte, côté mêlée : `fight_over_cc_nb`.

    C'est la mesure du 2026-08-11 rejouée en petit. Le Bigboss (Two-Handed Big Choppa, NB 5)
    frappe une escouade de 10 : 2 dés additionnels, donc des lignes d'attaque au-delà du NB.
    Sans le marqueur, l'analyzer plafonne au NB seul et les compte en dépassement — c'est
    l'intégralité des 24 « Attacks over CC_NB » du run.
    """
    gs, raw_log = _cleave_log(monkeypatch, [4] * 40)
    lines = _step_log_lines(tmp_path, gs, raw_log)
    assert len(lines) == 7, (
        f"5 attaques (NB du Two-Handed Big Choppa) + 2 dés de CLEAVE = 7 lignes, "
        f"obtenu {len(lines)}"
    )

    stats = _analyzer_stats(tmp_path, lines, unit_type=CLEAVE_UNIT,
                            target_models=TARGET_SQUAD, melee=True)

    assert not [e for e in stats["parse_errors"] if "CLEAVE" in e.get("error", "")], (
        stats["parse_errors"]
    )
    assert stats["fight_over_cc_nb"][1] == 0, (
        "les 2 attaques de CLEAVE sont légitimes ; les compter en dépassement signifie que le "
        "marqueur n'atteint pas la ligne ou que le plafond l'ignore"
    )


def test_le_marqueur_blast_leve_le_plafond_de_tirs(monkeypatch, tmp_path):
    """JUMEAU exact au tir : `shoot_over_rng_nb`. Aucun roster joué le 2026-08-11 ne portait
    d'arme BLAST — ce contrôle est donc corrigé AVANT de s'être allumé, et c'est ce test qui
    l'atteste."""
    gs, raw_log = _blast_log(monkeypatch, [4] * 40)
    lines = _step_log_lines(tmp_path, gs, raw_log)
    assert len(lines) == 5, (
        f"3 attaques (NB max du Plasma Cannon, D3) + 2 dés de BLAST = 5 lignes, "
        f"obtenu {len(lines)}"
    )

    stats = _analyzer_stats(tmp_path, lines, unit_type=BLAST_UNIT, target_models=TARGET_SQUAD)

    assert not [e for e in stats["parse_errors"] if "BLAST" in e.get("error", "")], (
        stats["parse_errors"]
    )
    assert stats["shoot_over_rng_nb"][1] == 0, stats["shoot_over_rng_nb"]
    # §1.8 : une règle dont le token est dans le journal ne doit PAS ressortir « NOT USED ».
    # C'est le mode d'échec de [MELTA] (708 tirs déclarés morts), et il se rejouerait à
    # l'identique pour [BLAST] si le token atteignait step.log sans compteur en face.
    usage = {k: v for k, v in stats["weapon_rule_usage"].items() if k[0] == "BLAST"}
    assert usage and any(sum(v.values()) > 0 for v in usage.values()), (
        "aucun usage de BLAST compté alors que le token est présent sur les lignes"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Le segment `Save …` ne décrit QUE ce qui a eu lieu
# ─────────────────────────────────────────────────────────────────────────────

def test_la_melee_annonce_la_sauvegarde_sautee(monkeypatch, tmp_path):
    """24.10 en MÊLÉE : le miroir du tir, qui n'avait jamais été écrit.

    La branche `FOUGHT` imprimait `Save {roll}({target}+)` sans condition. Sur une blessure
    critique d'une arme [DEVASTATING WOUNDS], le moteur ne lance AUCUN dé de sauvegarde
    (« no saving throw can be made ») : la ligne affichait donc littéralement `Save None(3+)`,
    un jet inexistant sous un seuil réel.
    """
    gs, raw_log = _engine_shoot_log(
        monkeypatch, ["DEVASTATING_WOUNDS"], [4, 6] * 20, melee=True,
        unit_type=CLEAVE_UNIT, weapon_name=CLEAVE_WEAPON, target_models=1,
    )
    assert raw_log["shootDetails"][0]["saveSkipped"] is True, "prémisse : le moteur l'a sautée"
    line = _step_log_line(tmp_path, gs, raw_log)

    assert "Save [DEVASTATING WOUNDS]" in line, line
    assert "Save None" not in line, f"un jet inexistant ne doit plus être imprimé : {line}"


def test_l_analyzer_compte_devastating_en_melee(monkeypatch, tmp_path):
    """Maillon 4 : §1.8 comptait 0 usage en mêlée faute de token à lire."""
    gs, raw_log = _engine_shoot_log(
        monkeypatch, ["DEVASTATING_WOUNDS"], [4, 6] * 20, melee=True,
        unit_type=CLEAVE_UNIT, weapon_name=CLEAVE_WEAPON, target_models=1,
    )
    stats = _analyzer_stats(tmp_path, _step_log_lines(tmp_path, gs, raw_log),
                            unit_type=CLEAVE_UNIT, target_models=1, melee=True)

    usage = {k: v for k, v in stats["weapon_rule_usage"].items()
             if k[0] == "DEVASTATING_WOUNDS"}
    assert usage and any(sum(v.values()) > 0 for v in usage.values()), (
        "aucun usage de DEVASTATING_WOUNDS compté en mêlée : la chaîne est rompue"
    )


def test_une_attaque_non_allouee_ne_fabrique_pas_de_sauvegarde(tmp_path):
    """05 Attack sequence — « excess attacks lost ».

    Le seuil de sauvegarde n'est écrit qu'à l'ALLOCATION. Quand la cible est détruite avant que
    le pool ne soit résolu, le moteur cesse (à raison) d'allouer : le record reste sans seuil et
    sans résultat. Le formateur imprimait quand même `Save {roll}(None+)` — 1 429 lignes sur
    10 021 du run du 2026-08-11, soit 14 %, qu'aucun contrôle ne pouvait relire.

    Le record est construit à la main ici : provoquer un wipe en cours de pool par le vrai
    moteur demanderait un scénario entier, alors que l'invariant testé est celui du FORMATEUR —
    « pas de seuil ⇒ pas de segment chiffré ».
    """
    from ai.step_logger import _save_segments

    unallocated = {"save_target": None, "save_roll": 4, "save_skipped": False}
    assert _save_segments(unallocated, damage=2, save_result=None) == ["Save [NOT ALLOCATED]"]

    allocated = {"save_target": 3, "save_roll": 4, "save_skipped": False}
    assert _save_segments(allocated, damage=2, save_result="FAIL") == ["Save 4(3+)", "Dmg:2HP"]


@pytest.mark.parametrize("melee", [False, True], ids=["tir", "melee"])
def test_la_ligne_nomme_la_figurine_allouee(monkeypatch, tmp_path, melee):
    """La chaîne `[ALLOC_MODEL:]` : record moteur → mapping → ligne (2026-08-12).

    Le journal disait qu'une escouade perdait des PV, jamais QUI. L'analyzer le déduisait, et ses
    deux déductions étaient fausses : 2 342 fenêtres où l'escouade entière retombait sur son
    ancre — donc un point fantôme là où la figurine venait de tomber — et 200 PV par socle faux
    sur 173 129 comparés aux instantanés moteur, la cascade d'allocation réelle
    (`_select_allocation_model`) n'étant pas le tri de l'analyzer.

    Ce test tient le maillon d'ÉMISSION ; l'exploitation par l'analyzer est verrouillée par
    `tests/unit/ai/test_analyzer_alloc_model_named.py`. Les deux moitiés doivent exister
    séparément : couper l'émission ici ne fait PAS tomber les tests de lecture, qui travaillent
    sur des journaux écrits à la main (vérifié par mutation, 2026-08-12).

    PARAMÉTRÉ tir/mêlée : le token est écrit au point d'émission COMMUN (`log_action`), jamais
    dans les deux branches du formateur. C'est ce choix que ce paramètre vérifie — un token posé
    dans la seule branche SHOT laisserait sans donnée les 19 157 lignes de mêlée du run de
    référence, et le miroir tir/mêlée est le motif d'échec n°1 de ce dépôt.
    """
    gs, raw_log = _engine_shoot_log(monkeypatch, [], [6, 6, 1], melee=melee)
    line = _step_log_line(tmp_path, gs, raw_log)
    assert "[ALLOC_MODEL: 101#0]" in line, (
        "la ligne ne nomme pas la figurine allouée — la chaîne record → mapping → ligne est "
        f"rompue :\n{line}"
    )


def test_l_entete_declare_la_grammaire_du_journal(tmp_path):
    """`Log grammar:` — sans elle, un lecteur ne peut pas distinguer « donnée absente » de
    « producteur en panne », et n'a d'autre choix que de retomber en silence sur une
    reconstruction approximative. C'est cette ligne qui rend `[ALLOC_MODEL:]` EXIGIBLE.

    Ce qu'il prouve exactement : l'ALLER-RETOUR. Le producteur écrit la ligne, le lecteur la
    retrouve. Un désaccord de version entre les deux est hors de portée d'un test — et n'a pas
    à être testé : les deux lisent la MÊME constante, il n'y a rien à désynchroniser. Verrou
    prouvé en supprimant l'écriture de la ligne → ROUGE.
    """
    from ai.analyzer import parse_log_grammar_version
    from ai.step_logger import LOG_GRAMMAR_VERSION, StepLogger

    out = tmp_path / "entete.log"
    logger = StepLogger(output_file=str(out), enabled=True, buffer_size=1)
    logger.log_episode_start(
        units_data=[], scenario_info="scenario_bot-01", bot_name="tactical",
        board_config={"cols": 44, "rows": 60, "inches_to_subhex": 1, "hex_radius": 13.9,
                      "margin": 5},
        run_rules={"engagement_zone_subhex": 2},
    )
    logger._flush_buffer()
    assert parse_log_grammar_version(str(out)) == LOG_GRAMMAR_VERSION, (
        "le producteur et le lecteur ne s'accordent pas sur la version de grammaire"
    )


# ─────────────────────────────────────────────────────────────────────────────
# LOT A (2026-08-12) — les six règles d'armes que `step.log` ne portait PAS
#
# Elles étaient dans le cas décrit par `Documentation/Chantiers/analyzer_couverture.md`
# §1.3 : le moteur SAIT poser leur token (`shared_utils.weapon_rule_log_tokens`), mais
# seulement sur la ligne de synthèse du Game Log PvP, que rien ne relit automatiquement. Aucun
# contrôle analyzer ne pouvait donc exister pour elles, et §1.8 les rendait « NOT USED » —
# c'est-à-dire FAUSSEMENT MORTES : le rapport affirmait que le moteur ne les appliquait pas.
#
# Chaque règle est vérifiée SUR LES DEUX FACES du miroir (tir ET mêlée) par le même
# paramétrage, parce que l'émetteur (`_emit_squad_shoot_log`) et le formateur (`step_logger`)
# sont partagés : un token écrit d'un seul côté est le motif d'échec n°1 de ce dépôt.
# ─────────────────────────────────────────────────────────────────────────────

#: `(règle d'arme, token attendu, dés scriptés, kwargs, joue_en_melee)` — la table de vérité
#: du lot. Les dés sont choisis pour ATTEINDRE le segment qui porte le token : `[LETHAL HITS]`
#: exige une touche CRITIQUE (6), les autres une touche puis une blessure réussies.
#:
#: `joue_en_melee=False` pour [PSYCHIC] SEULEMENT, et ce n'est pas une exception de commodité :
#: 24.29 neutralise un modificateur, et le seul modificateur d'attaque de ce moteur est le
#: couvert 13.08, qui est ranged-only. En mêlée la règle n'a jamais rien à neutraliser, donc le
#: token n'y est jamais posé — la BRANCHE existe (même table partagée), c'est sa CONDITION qui
#: ne peut pas être vraie. Le test de contre-épreuve couvre les deux faces dans tous les cas.
LOT_A_TOKENS = [
    ("TORRENT", "[TORRENT]", [4, 2], {}, True),
    ("LETHAL_HITS", "[LETHAL HITS]", [6, 2], {}, True),
    ("IGNORES_COVER", "[IGNORES COVER]", [3, 4, 2], {}, True),
    ("EXTRA_ATTACKS", "[EXTRA ATTACKS]", [3, 4, 2], {}, True),
    ("PSYCHIC", "[PSYCHIC]", [3, 4, 2], {"cover": True}, False),
    ("ANTI_INFANTRY:4", "[ANTI-INFANTRY:4+]", [3, 4, 2],
     {"target_keywords": ("INFANTRY",)}, True),
    # [ASSAULT] 24.04 / [CLOSE-QUARTERS] 24.07 : règles d'ÉLIGIBILITÉ (10.05 / 10.06). Leur
    # condition a DEUX moitiés — l'arme la déclare ET l'unité est dans l'état voulu. Les kwargs
    # posent l'état ; la contre-épreuve les GARDE et retire seulement la règle d'arme, ce qui
    # prouve que le token vient bien de l'arme et pas du seul état. L'autre moitié (arme
    # déclarée, état neutre) est tenue par `test_regle_sans_l_etat_absente_du_pont`.
    ("ASSAULT", "[ASSAULT]", [3, 4, 2], {"units_advanced": True}, False),
    ("CLOSE_QUARTERS", "[CLOSE-QUARTERS]", [3, 4, 2], {"engaged": True}, False),
    # [INDIRECT FIRE] 10.07 (24.19) : plancher 6+ (sans spotter) accolé au segment Hit.
    # MEME schéma deux moitiés : arme INDIRECT_FIRE + type de tir INDIRECT. `indirect=True`
    # pose le choix de type ; la contre-épreuve le GARDE et retire seulement la règle d'arme.
    # ranged-only : melee_ok=False.
    ("INDIRECT_FIRE", "[INDIRECT FIRE:6+]", [3, 4, 2], {"indirect": True}, False),
    # Plancher 4+ avec spotter : même arme, même type de tir, mais `spotter=True` fait que
    # `_target_visible_to_a_friendly_unit` retourne True → `indirect_fire_fail_below` = 4.
    # Verrou sur la branche spotted de `indirect_fire_fail_below` (shared_utils.py).
    ("INDIRECT_FIRE", "[INDIRECT FIRE:4+]", [3, 4, 2], {"indirect": True, "spotter": True}, False),
]

_LOT_A_IDS = [rule.split(":")[0] for rule, *_ in LOT_A_TOKENS]

#: Paire (unité, arme) RÉELLE de MÊLÉE. Le décor de tir par défaut porte une arme de TIR : la
#: rejouer en mêlée fait remonter `missing CC_NB` à l'analyzer, donc des `parse_errors` qui
#: masqueraient ceux que le contrôle de masse cherche vraiment.
MELEE_KWARGS: dict[str, Any] = {"unit_type": CLEAVE_UNIT, "weapon_name": CLEAVE_WEAPON}


@pytest.mark.parametrize("melee", [False, True], ids=["tir", "melee"])
@pytest.mark.parametrize("rule,token,rolls,kwargs,melee_ok", LOT_A_TOKENS, ids=_LOT_A_IDS)
def test_le_token_du_lot_a_atteint_step_log(monkeypatch, tmp_path, melee, rule, token, rolls,
                                            kwargs, melee_ok):
    """Maillons 1-3, les DEUX faces du miroir : le token que l'analyzer et le replay
    cherchent doit être présent sur la ligne réellement écrite par le StepLogger."""
    if melee and not melee_ok:
        pytest.skip("règle ranged-only : pas de token en mêlée")
    extra = dict(MELEE_KWARGS) if melee else {}
    gs, raw_log = _engine_shoot_log(monkeypatch, [rule], rolls, melee=melee, **kwargs, **extra)
    line = _step_log_line(tmp_path, gs, raw_log)

    assert token in line, f"{rule} n'a pas franchi le pont vers step.log : {line}"


@pytest.mark.parametrize("melee", [False, True], ids=["tir", "melee"])
@pytest.mark.parametrize("rule,token,rolls,kwargs,melee_ok", LOT_A_TOKENS, ids=_LOT_A_IDS)
def test_sans_la_regle_le_token_du_lot_a_est_absent(monkeypatch, tmp_path, melee, rule, token,
                                                    rolls, kwargs, melee_ok):
    """Contre-épreuve OBLIGATOIRE : une arme SANS la règle ne doit rien dire.

    Sans elle, un token posé inconditionnellement passerait le test ci-dessus tout en étant un
    faux positif pour tout lecteur — le mode d'échec historique de ce chantier.

    Les `kwargs` du décor sont GARDÉS : pour les règles d'éligibilité (ASSAULT,
    CLOSE_QUARTERS) l'état d'unité reste posé et seule la règle d'arme disparaît, ce qui prouve
    que le token vient de l'arme et pas du seul état."""
    extra = dict(MELEE_KWARGS) if melee else {}
    gs, raw_log = _engine_shoot_log(monkeypatch, [], rolls, melee=melee, **kwargs, **extra)
    line = _step_log_line(tmp_path, gs, raw_log)

    assert token not in line, f"token posé sans que l'arme déclare {rule} : {line}"


def test_torrent_se_distingue_d_une_ligne_malformee(monkeypatch, tmp_path):
    """24.37 « does not make a Hit roll » : le moteur écrit `attackRoll=None` ET
    `hitTarget=None`, donc la ligne rend `Hit None(None+)` — exactement la forme d'une ligne
    cassée. Le token est la SEULE chose qui distingue « la règle a fait toucher d'office » de
    « le producteur est en panne » ; c'est le trou que [SUSTAINED HITS] a déjà coûté."""
    gs, raw_log = _engine_shoot_log(monkeypatch, ["TORRENT"], [4, 2])
    line = _step_log_line(tmp_path, gs, raw_log)

    assert "Hit None(None+) [TORRENT]" in line, line


def test_lethal_hits_ne_parle_que_sur_la_touche_critique(monkeypatch, tmp_path):
    """24.23 ne joue QUE sur une touche critique : le marqueur est par ATTAQUE, pas par groupe.

    Deux attaques, une seule critique. Un drapeau de groupe aurait annoncé la règle sur les
    deux — donc sur une attaque où elle n'a rien fait, et où le jet de blessure a bel et bien
    eu lieu (`Wound 4(4+)`, pas `Wound None(4+)`)."""
    gs, raw_log = _engine_shoot_log(
        monkeypatch, ["LETHAL_HITS"], [6, 2, 3, 4, 2], n_attacks=2,
    )
    lines = _step_log_lines(tmp_path, gs, raw_log)

    assert len(lines) == 2, lines
    porteuses = [l for l in lines if "[LETHAL HITS]" in l]
    assert len(porteuses) == 1, (
        "exactement une des deux attaques est critique ; le marqueur doit suivre l'ATTAQUE "
        f"et non le groupe : {lines}"
    )
    assert "Wound None(" in porteuses[0], porteuses[0]


def test_psychic_ne_dit_rien_sans_modificateur_a_neutraliser(monkeypatch, tmp_path):
    """24.29 : la règle ignore les modificateurs subis. Le seul modificateur d'attaque de ce
    moteur est la dégradation de seuil du couvert 13.08 ; sans couvert, la règle n'a rien
    neutralisé et l'annoncer ferait croire à un effet. MÊME prédicat que le Game Log PvP
    (`psychic_rule_applies`), et c'est justement pour qu'il n'y en ait qu'un."""
    gs, raw_log = _engine_shoot_log(monkeypatch, ["PSYCHIC"], [3, 4, 2], cover=False)
    line = _step_log_line(tmp_path, gs, raw_log)

    assert "[PSYCHIC]" not in line, line


def test_anti_ne_dit_rien_quand_la_cible_n_a_pas_le_keyword(monkeypatch, tmp_path):
    """24.03 : « against a target with the X keyword ». Une arme [ANTI-VEHICLE 4+] tirant sur
    de l'INFANTERIE n'a AUCUNE instance applicable — 24.02 n'en retient aucune — donc le seuil
    critique n'a pas bougé et la ligne ne doit rien dire."""
    gs, raw_log = _engine_shoot_log(
        monkeypatch, ["ANTI_VEHICLE:4"], [3, 4, 2], target_keywords=("INFANTRY",),
    )
    line = _step_log_line(tmp_path, gs, raw_log)

    assert "[ANTI-" not in line, line


def test_anti_ecrit_le_seuil_declare_par_l_arme(monkeypatch, tmp_path):
    """Le `Y+` du token est celui de la DATASHEET, jamais le `crit_wound_on` que le moteur en
    tire.

    C'est la différence entre un contrôle et un vert vacant : avec le chiffre du moteur,
    l'analyzer vérifierait le moteur avec sa propre réponse, et le seul recoupement qui vaille
    — le token contre l'armurerie — n'existerait plus.

    Les deux valeurs coïncident pour tout Y+ jouable (2..6), donc un test à 4+ ne DISCRIMINE
    rien : il passerait au vert avec l'une comme avec l'autre source. On déclare donc un `7+`,
    seule valeur où le clamp de 05.02 (« rien n'est plus critique qu'un 6 ») les sépare. C'est
    une armurerie fautive — et c'est le point : le journal doit l'exposer, pas la lisser.
    """
    from engine.phase_handlers.attack_sequence import build_weapon_attack_profile

    weapon = {"WEAPON_RULES": ["ANTI_INFANTRY:7"], "code": WEAPON_NAME, "display_name": WEAPON_NAME}
    profile = build_weapon_attack_profile(weapon, {"unit_keywords": ["INFANTRY"]})
    assert (profile.anti_threshold, profile.crit_wound_on) == (7, 6), (
        "prémisse : les deux seuils doivent DIVERGER, sinon le test ne discrimine rien"
    )

    gs, raw_log = _engine_shoot_log(
        monkeypatch, ["ANTI_INFANTRY:7"], [3, 4, 2], target_keywords=("INFANTRY",),
    )
    line = _step_log_line(tmp_path, gs, raw_log)

    assert "[ANTI-INFANTRY:7+]" in line, (
        f"le token doit porter le 7+ DÉCLARÉ, pas le 6 que le moteur en a tiré : {line}"
    )


def test_un_profil_anti_a_moitie_rempli_est_refuse():
    """Le keyword et le seuil sont UN SEUL fait. Un profil qui n'en porte qu'un écrirait
    `[ANTI-INFANTRY:None+]` — une valeur par défaut déguisée en donnée (T1). L'invariant vit
    sur le dataclass, donc aucun producteur ne peut le contourner."""
    from engine.phase_handlers.attack_sequence import WeaponAttackProfile

    with pytest.raises(ValueError, match="anti_keyword et anti_threshold"):
        WeaponAttackProfile(anti_keyword="INFANTRY")
    # Direction inverse : seuil sans keyword.
    with pytest.raises(ValueError, match="anti_keyword et anti_threshold"):
        WeaponAttackProfile(anti_threshold=4)


def test_un_seuil_anti_sous_2_leve_a_l_entree_du_moteur():
    """05.02 : un jet de blessure non modifié de 1 rate TOUJOURS, donc `ANTI_INFANTRY:1` n'est
    pas une armurerie « limite », c'est une donnée impossible.

    Le seuil est refusé à la RÉSOLUTION, pas au formateur de journal. `step_logger` refuse déjà
    le même domaine, mais il tourne dans le `except Exception` de `log_action` : une arme
    déclarant `ANTI_INFANTRY:1` voyait TOUTES ses lignes d'attaque disparaître de `step.log`,
    sans `parse_errors` côté analyzer puisque la ligne n'avait jamais existé — un sous-comptage
    silencieux, le mode d'échec le plus long à voir.

    Le HAUT reste non borné (cf. le `7+` du test ci-dessus) : là, le journal doit exposer
    l'armurerie fautive, il peut l'écrire. `1+` n'est pas écrivable du tout.
    """
    from engine.observation_weapon_profiles import anti_rule_of
    from engine.phase_handlers.attack_sequence import build_weapon_attack_profile

    weapon = {"WEAPON_RULES": ["ANTI_INFANTRY:1"], "code": WEAPON_NAME, "display_name": WEAPON_NAME}

    with pytest.raises(ValueError, match="minimum 2"):
        build_weapon_attack_profile(weapon, {"unit_keywords": ["INFANTRY"]})

    # JUMEAU : l'observation lit le MÊME paramètre par le MÊME site. Une seule des deux lectures
    # gardée, et la donnée impossible entrait quand même dans le vecteur d'observation.
    with pytest.raises(ValueError, match="minimum 2"):
        anti_rule_of(weapon)


#: `(règle d'arme, clé de détail, token, état d'unité qui déclenche)` — les règles d'ÉLIGIBILITÉ
#: 10.05 / 10.06, seules du lot dont la condition a une moitié HORS de l'arme. Une seule table
#: pour les deux faces du pont : la présence lit `engine_kwargs`, la contre-épreuve les retire.
ELIGIBILITY_RULES = [
    ("ASSAULT", "assault_applied", "[ASSAULT]", {"units_advanced": True}),
    ("CLOSE_QUARTERS", "close_quarters_applied", "[CLOSE-QUARTERS]", {"engaged": True}),
]
_ELIGIBILITY_IDS = ["assault", "close_quarters"]


@pytest.mark.parametrize("weapon_rule, detail_key, token, engine_kwargs", ELIGIBILITY_RULES,
                         ids=_ELIGIBILITY_IDS)
def test_regle_posee_dans_les_details_du_pont(monkeypatch, weapon_rule, detail_key, token,
                                              engine_kwargs):
    """Preuve par le VRAI pont (`_build_shot_details`) que les drapeaux de règle d'arme
    ([ASSAULT] 24.04, [CLOSE-QUARTERS] 24.07) sont bien posés dans les détails quand les
    conditions de déclenchement sont réunies.

    La clé DOIT être présente (câblage du producteur 2026-08-16) — c'est elle qui rend le
    token atteignable dans step.log. Que le token y arrive VRAIMENT est tenu par
    `test_le_token_du_lot_a_atteint_step_log`, qui porte ces deux règles.
    """
    gs, raw_log = _engine_shoot_log(monkeypatch, [weapon_rule], [3, 4, 2], **engine_kwargs)
    bridge = _Bridge(gs)
    details = bridge._build_shot_details(raw_log, raw_log["shootDetails"][0], 1, None)

    assert details.get(detail_key) is True, (
        f"`{detail_key}` doit être posé par le pont : {details}"
    )
    # VERT VACANT : attester que le pont a bien travaillé.
    assert details["hit_roll"] == 3 and details["hit_target"] == 3, details


@pytest.mark.parametrize("weapon_rule, detail_key, token, engine_kwargs", ELIGIBILITY_RULES,
                         ids=_ELIGIBILITY_IDS)
def test_regle_sans_l_etat_absente_du_pont(monkeypatch, tmp_path, weapon_rule, detail_key, token,
                                           engine_kwargs):
    """Contre-épreuve du pont, SECONDE moitié : l'arme déclare la règle mais l'unité n'est PAS
    dans l'état qui la déclenche (pas d'advance pour 10.05, pas d'engagement pour 10.06).

    La contre-épreuve LOT_A couvre « arme sans règle, état posé » ; celle-ci couvre « arme avec
    règle, état neutre ». Si le producteur régressait à tester l'arme seule, ce test échoue et
    l'autre reste vert — c'est pour ça que les deux existent. L'état neutre est le MÊME décor
    avec les mêmes clés mises à `False`, pas un décor absent : c'est ce qui rend la seule
    différence avec le test de présence lisible.
    """
    neutre: Dict[str, Any] = {k: False for k in engine_kwargs}
    gs, raw_log = _engine_shoot_log(monkeypatch, [weapon_rule], [3, 4, 2], **neutre)
    bridge = _Bridge(gs)
    details = bridge._build_shot_details(raw_log, raw_log["shootDetails"][0], 1, None)

    assert detail_key not in details, (
        f"`{detail_key}` ne doit PAS être posé quand l'unité n'est pas dans l'état "
        f"{set(engine_kwargs)} attendu, même si l'arme déclare {weapon_rule} : {details}"
    )
    line = _step_log_line(tmp_path, gs, raw_log)
    assert token not in line, line


@pytest.mark.parametrize("weapon_rule, detail_key, token, engine_kwargs", ELIGIBILITY_RULES,
                         ids=_ELIGIBILITY_IDS)
def test_avance_et_engage_aucune_des_deux_regles_ne_joue(monkeypatch, tmp_path, weapon_rule,
                                                         detail_key, token, engine_kwargs):
    """CLAUSE DU PORTIER, celle qu'aucune moitié de la condition ne dit : une escouade ENGAGÉE
    qui a AVANCÉ ce tour ne tire sous aucun des deux régimes.

    10.06 exige explicitement « did not make an advance move this turn » (PDF 10 Shooting
    phase), et 10.05 ne s'applique qu'hors engagement : `resolve_squad_shooting_type` rend donc
    `None`, et AUCUN des deux tokens ne doit apparaître — alors même que les deux moitiés
    naïves (« l'arme déclare la règle » + « l'unité a avancé / est engagée ») sont vraies.

    C'est le verrou du chantier : un producteur qui redérive ces conditions à côté de
    l'autorité, au lieu de lire son verdict, écrit ici un token que la règle interdit. Les deux
    contre-épreuves voisines restent vertes dans ce cas — seule celle-ci tombe.
    """
    gs, raw_log = _engine_shoot_log(monkeypatch, [weapon_rule], [3, 4, 2],
                                    units_advanced=True, engaged=True)
    bridge = _Bridge(gs)
    details = bridge._build_shot_details(raw_log, raw_log["shootDetails"][0], 1, None)

    assert detail_key not in details, (
        f"escouade engagée ET ayant avancé : le portier ne rend aucun type de tir, donc "
        f"`{detail_key}` ne doit pas être posé : {details}"
    )
    # VERT VACANT : le pont a bien construit CETTE attaque, l'absence n'est pas celle d'un
    # `details` vide ni d'une chaîne rompue.
    assert details["hit_roll"] == 3 and details["hit_target"] == 3, details
    line = _step_log_line(tmp_path, gs, raw_log)
    assert token not in line, line


def test_analyzer_compte_assault_fallback_grammar_lt4(monkeypatch, tmp_path):
    """Fallback grammaire < 4 : l'analyzer compte ASSAULT via `units_advanced` + `weapon_rules_list`.

    `entete_step_log` n'émet pas de ligne `Log grammar:` → le parseur lève grammar=1 (< 4) et
    prend le chemin état-based (`shooter_id in state.units_advanced and 'ASSAULT' in weapon_rules_list`).
    La ligne ADVANCED injectée peuple `state.units_advanced` ; le registre config confirme que
    `Sternguard Bolt Rifle` porte ASSAULT → le compteur doit être 1.

    Sans ce test, une régression sur le chemin fallback passerait inaperçue : les tests du pont
    ne prouvent que la grammaire >= 4 (token `[ASSAULT]` présent dans la ligne).
    """
    gs, raw_log = _engine_shoot_log(monkeypatch, ["ASSAULT"], [3, 4, 2],
                                    units_advanced=True)
    stats = _analyzer_stats(tmp_path, _step_log_line(tmp_path, gs, raw_log),
                            units_advanced=True)

    assert stats["parse_errors"] == [], stats["parse_errors"]
    weapon_key = f"{WEAPON_NAME} ({UNIT_TYPE})"
    usage = stats["weapon_rule_usage"].get(("ASSAULT", weapon_key), {})
    assert sum(usage.values()) == 1, (
        "le fallback grammaire < 4 doit compter ASSAULT quand l'unité a avancé — "
        f"weapon_rule_usage[('ASSAULT', '{weapon_key}')] = {usage}"
    )
    # VERT VACANT : prouver que l'analyzer a bien traité la ligne de tir.
    assert stats["shoot_hit_result_checked"][1] == 1, stats["shoot_hit_result_checked"]


def test_analyzer_assault_fallback_absent_sans_advance(monkeypatch, tmp_path):
    """Contre-épreuve : arme ASSAULT + unité NON avancée → le fallback < 4 ne compte rien.

    Si le compteur s'incrémente ici, le fallback testerait l'arme seule sans vérifier l'état
    d'unité — le mode d'échec exact que le chemin état-based doit éviter.
    """
    gs, raw_log = _engine_shoot_log(monkeypatch, ["ASSAULT"], [3, 4, 2],
                                    units_advanced=False)
    stats = _analyzer_stats(tmp_path, _step_log_line(tmp_path, gs, raw_log),
                            units_advanced=False)

    assert stats["parse_errors"] == [], stats["parse_errors"]
    weapon_key = f"{WEAPON_NAME} ({UNIT_TYPE})"
    usage = stats["weapon_rule_usage"].get(("ASSAULT", weapon_key), {})
    assert sum(usage.values()) == 0, (
        "le fallback grammaire < 4 ne doit PAS compter ASSAULT si l'unité n'a pas avancé — "
        f"weapon_rule_usage[('ASSAULT', '{weapon_key}')] = {usage}"
    )


def test_analyzer_assault_fallback_absent_sans_regle_d_arme(monkeypatch, tmp_path):
    """Contre-épreuve de l'AUTRE moitié du repli : unité AYANT avancé, arme SANS [ASSAULT].

    Le repli a deux moitiés (`shooter_id in state.units_advanced` ET `'ASSAULT' in
    weapon_rules_list`) et la paire de tests voisine n'en verrouillait qu'une : supprimer la
    moitié « arme » du produit laissait toute la suite au vert, donc l'analyzer aurait pu
    créditer ASSAULT à n'importe quelle arme d'une unité ayant avancé.

    `Heavy Bolter` (EradicatorHeavyBolter) est le porteur : profil RÉEL de l'armurerie qui ne
    déclare PAS ASSAULT. C'est le registre, pas le décor de test, qui alimente
    `weapon_rules_list` — une arme inventée ne prouverait rien ici.
    """
    gs, raw_log = _engine_shoot_log(monkeypatch, [], [3, 4, 2], units_advanced=True,
                                    unit_type=SUSTAINED_UNIT, weapon_name=SUSTAINED_WEAPON)
    stats = _analyzer_stats(tmp_path, _step_log_line(tmp_path, gs, raw_log),
                            unit_type=SUSTAINED_UNIT, units_advanced=True)

    assert stats["parse_errors"] == [], stats["parse_errors"]
    weapon_key = f"{SUSTAINED_WEAPON} ({SUSTAINED_UNIT})"
    usage = stats["weapon_rule_usage"].get(("ASSAULT", weapon_key), {})
    assert sum(usage.values()) == 0, (
        "le repli ne doit PAS compter ASSAULT pour une arme qui ne le déclare pas, même si "
        f"l'unité a avancé — weapon_rule_usage[('ASSAULT', '{weapon_key}')] = {usage}"
    )
    # VERT VACANT : l'unité a bien été vue comme ayant avancé, sinon la moitié « état » suffirait
    # à expliquer le zéro et le test ne prouverait rien de la moitié « arme ».
    assert stats["shots_after_advance"][1] == 1, stats["shots_after_advance"]


@pytest.mark.parametrize("weapon_rule, detail_key, token, engine_kwargs", ELIGIBILITY_RULES,
                         ids=_ELIGIBILITY_IDS)
def test_analyzer_grammaire_4_compte_depuis_le_token(monkeypatch, tmp_path, weapon_rule,
                                                     detail_key, token, engine_kwargs):
    """RÉGIME DE PRODUCTION — le vrai StepLogger écrit toujours `Log grammar:`, donc le chemin
    réellement emprunté par l'analyzer est la branche TOKEN, pas le repli.

    Cette branche n'était atteinte par aucun test du dépôt : `entete_step_log` omettait la ligne
    de grammaire, si bien que TOUTES les assertions analyzer de ce fichier tournaient en
    grammaire 1. Neutraliser la branche token laissait la suite entière au vert — c'est-à-dire
    qu'une panne du comptage sur les journaux d'entraînement réels ne se voyait nulle part.
    """
    weapon_name = CQ_WEAPON if weapon_rule == "CLOSE_QUARTERS" else WEAPON_NAME
    gs, raw_log = _engine_shoot_log(monkeypatch, [weapon_rule], [3, 4, 2],
                                    weapon_name=weapon_name, **engine_kwargs)
    line = _step_log_line(tmp_path, gs, raw_log)
    assert token in line, f"prémisse : le moteur doit poser {token} : {line}"

    # AUCUN décor d'état injecté dans le journal (pas de ligne ADVANCED) : le token est alors la
    # SEULE source possible du comptage. Un repli qui reprendrait la main ne trouverait rien.
    stats = _analyzer_stats(tmp_path, line, log_grammar=LOG_GRAMMAR_VERSION)

    assert stats["parse_errors"] == [], stats["parse_errors"]
    weapon_key = f"{weapon_name} ({UNIT_TYPE})"
    usage = stats["weapon_rule_usage"].get((weapon_rule, weapon_key), {})
    assert sum(usage.values()) == 1, (
        f"en grammaire {LOG_GRAMMAR_VERSION} le token fait autorité et doit compter un usage — "
        f"weapon_rule_usage[('{weapon_rule}', '{weapon_key}')] = {usage}"
    )


@pytest.mark.parametrize("weapon_rule, detail_key, token, engine_kwargs", ELIGIBILITY_RULES,
                         ids=_ELIGIBILITY_IDS)
def test_analyzer_grammaire_4_ne_compte_rien_sans_token(monkeypatch, tmp_path, weapon_rule,
                                                        detail_key, token, engine_kwargs):
    """Contre-épreuve du régime de production : même arme, état neutre → le moteur ne pose pas
    le token, donc l'analyzer ne compte rien.

    Sans elle, un comptage inconditionnel en grammaire >= 4 passerait le test de présence.
    """
    weapon_name = CQ_WEAPON if weapon_rule == "CLOSE_QUARTERS" else WEAPON_NAME
    neutre: Dict[str, Any] = {k: False for k in engine_kwargs}
    gs, raw_log = _engine_shoot_log(monkeypatch, [weapon_rule], [3, 4, 2],
                                    weapon_name=weapon_name, **neutre)
    line = _step_log_line(tmp_path, gs, raw_log)
    assert token not in line, f"prémisse : sans l'état, le moteur ne pose pas {token} : {line}"

    stats = _analyzer_stats(tmp_path, line, log_grammar=LOG_GRAMMAR_VERSION)

    assert stats["parse_errors"] == [], stats["parse_errors"]
    weapon_key = f"{weapon_name} ({UNIT_TYPE})"
    usage = stats["weapon_rule_usage"].get((weapon_rule, weapon_key), {})
    assert sum(usage.values()) == 0, (
        f"aucun token {token} sur la ligne : rien ne doit être compté — "
        f"weapon_rule_usage[('{weapon_rule}', '{weapon_key}')] = {usage}"
    )


@pytest.mark.parametrize("melee", [False, True], ids=["tir", "melee"])
def test_l_analyzer_accepte_les_lignes_porteuses_des_tokens_du_lot(monkeypatch, tmp_path, melee):
    """CONTRÔLE DE MASSE — un token que personne ne lit ne se livre pas.

    Ce lot ne produit AUCUN contrôle analyzer : il n'y a donc pas de compteur à vérifier. Ce
    qui doit l'être, c'est que le parseur ne se casse pas sur la grammaire nouvelle — une
    ligne qu'il rejette est une ligne perdue pour TOUS les contrôles existants, pas seulement
    pour les règles ajoutées. `parse_errors` est le seul témoin de ce mode d'échec, et il est
    muet par construction tant qu'on ne le regarde pas."""
    lignes = []
    attendus = []
    extra = dict(MELEE_KWARGS) if melee else {}
    for rule, token, rolls, kwargs, melee_ok in LOT_A_TOKENS:
        if melee and not melee_ok:
            continue
        gs, raw_log = _engine_shoot_log(
            monkeypatch, [rule], rolls, melee=melee, **kwargs, **extra
        )
        lignes.extend(_step_log_lines(tmp_path, gs, raw_log))
        attendus.append(token)

    # Le journal réellement soumis au parseur PORTE bien chaque token, une fois chacun : sans
    # ce comptage, un `parse_errors` vide n'attesterait que d'un journal vide de tokens.
    journal = "\n".join(lignes)
    for token in attendus:
        assert journal.count(token) == 1, f"{token} : {journal.count(token)} occurrence(s)"

    stats = _analyzer_stats(
        tmp_path, lignes, melee=melee,
        unit_type=CLEAVE_UNIT if melee else UNIT_TYPE,
    )

    assert stats["parse_errors"] == [], stats["parse_errors"]
    # VERT VACANT : un analyzer qui n'aurait reconnu AUCUNE de ces lignes rendrait lui aussi
    # `parse_errors == []`. Le compteur de lignes de touche réellement JUGÉES atteste qu'il a
    # bien lu les six — moins celle de [TORRENT], qui ne porte aucun jet de touche.
    checked = "fight_hit_result_checked" if melee else "shoot_hit_result_checked"
    assert stats[checked][1] == len(lignes) - 1, (
        "toutes les lignes sauf celle de [TORRENT] (`Hit None(None+)`) doivent être jugées "
        f"par l'analyzer : {stats[checked]} pour {len(lignes)} lignes"
    )


# ─────────────────────────────────────────────────────────────────────────────
# L1 — jet de battle-shock dans step.log (01.07 / 08.03)
# ─────────────────────────────────────────────────────────────────────────────

def _battle_shock_details(*, roll, ld, battle_shocked):
    """action_details minimaux pour le formateur battle_shock du StepLogger."""
    return {
        "current_turn": 1,
        "unit_with_coords": "3(10,12)",
        "roll": roll,
        "ld": ld,
        "battle_shocked": battle_shocked,
    }


def _battle_shock_line(tmp_path, *, roll, ld, battle_shocked):
    """Écrit une ligne battle_shock via le vrai StepLogger et la relit."""
    from ai.step_logger import StepLogger

    out = tmp_path / "bs.log"
    logger = StepLogger(output_file=str(out), enabled=True, buffer_size=1)
    logger.episode_number = 1
    logger.log_action(
        unit_id="3",
        action_type="battle_shock",
        phase="command",
        player=1,
        success=True,
        step_increment=False,
        action_details=_battle_shock_details(roll=roll, ld=ld, battle_shocked=battle_shocked),
    )
    logger._flush_buffer()
    lines = [l for l in out.read_text().splitlines() if "COMMAND" in l]
    assert lines, "le StepLogger n'a produit aucune ligne COMMAND"
    return lines[0]


def test_l1_battle_shock_ligne_shocked(tmp_path):
    """Jet raté (roll < Ld) → la ligne porte BATTLE-SHOCK, le jet, le seuil, et SHOCKED."""
    line = _battle_shock_line(tmp_path, roll=4, ld=7, battle_shocked=True)
    assert "BATTLE-SHOCK" in line, line
    assert "Roll:2D6=4" in line, line
    assert "Ld7+" in line, line
    assert "→ SHOCKED" in line, line
    assert "→ OK" not in line, line


def test_l1_battle_shock_ligne_ok(tmp_path):
    """Jet réussi (roll >= Ld) → la ligne porte OK et ne porte pas SHOCKED."""
    line = _battle_shock_line(tmp_path, roll=9, ld=7, battle_shocked=False)
    assert "BATTLE-SHOCK" in line, line
    assert "Roll:2D6=9" in line, line
    assert "Ld7+" in line, line
    assert "→ OK" in line, line
    assert "→ SHOCKED" not in line, line


def test_l1_roll_battle_shock_fournit_les_champs(monkeypatch):
    """roll_battle_shock écrit les champs l, roll, battle_shocked dans l'action_log (L1).

    Ces champs sont lus par _build_step_log_details pour construire l'action_details du
    formateur — leur absence rendrait la ligne illisible (require_key lève).
    """
    import random as _random
    from engine.phase_handlers.shared_utils import roll_battle_shock
    from tests._state_invariants import turn_state_invariants

    monkeypatch.setattr(_random, "randint", lambda a, b: 3)  # roll = 3+3 = 6
    gs = {
        **turn_state_invariants(),
        "action_logs": [], "action_log_seq": 0,
        "models_cache": {
            "7#0": {"id": "7#0", "squad_id": "7", "player": 1, "unitType": "AssaultIntercessor",
                    "col": 10, "row": 12, "HP_CUR": 5, "HP_MAX": 5, "LD": 7},
        },
        "squad_models": {"7": ["7#0"]},
        "units": [{"id": "7", "player": 1, "unitType": "AssaultIntercessor", "LD": 7,
                   "col": 10, "row": 12, "battle_shocked": False}],
        "units_cache": {},
        "unit_by_id": {"7": {"id": "7", "UNIT_RULES": []}},
        "phase": "command",
    }
    roll_battle_shock("7", gs)

    logs = [l for l in gs["action_logs"] if l.get("type") == "battle_shock"]
    assert logs, "roll_battle_shock doit écrire un entry de type 'battle_shock'"
    entry = logs[0]
    assert "ld" in entry, "champ 'ld' manquant — _build_step_log_details ne peut pas le lire"
    assert "roll" in entry, "champ 'roll' manquant"
    assert "battle_shocked" in entry, "champ 'battle_shocked' manquant"
    assert isinstance(entry["roll"], int), entry["roll"]
    assert isinstance(entry["ld"], int), entry["ld"]
    assert entry["roll"] == 6, entry["roll"]  # 3+3


# ─────────────────────────────────────────────────────────────────────────────
# L3 — → <mid> sur la partie Save/Dmg (figurine cible allouée)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def allocated_shoot_line(monkeypatch, tmp_path):
    """Tir alloué à une figurine précise : la ligne doit porter → <mid> avant Save."""
    # AP -1 pour que la save ne réussisse pas toujours (armor 2, AP -1 → seuil 3, roll 2 : fail)
    gs, raw_log = _engine_shoot_log(monkeypatch, [], [3, 4, 2])
    return _step_log_line(tmp_path, gs, raw_log)


def test_l3_alloc_mid_prefixe_save(allocated_shoot_line):
    """L3 : le mid alloué apparaît avant le segment Save — pattern '→ <mid>'."""
    import re
    # Le mid a la forme <squad_id>#<index>, ex: 101#0
    assert re.search(r"→ \d+#\d+", allocated_shoot_line), (
        f"L3 : '→ <mid>' attendu avant Save : {allocated_shoot_line}"
    )


def test_l3_alloc_mid_avant_save(allocated_shoot_line):
    """L3 : le '→ <mid>' apparaît dans la séquence avant 'Save'."""
    import re
    m = re.search(r"→ (\d+#\d+)", allocated_shoot_line)
    save_pos = allocated_shoot_line.find(" Save ")
    assert m is not None, f"'→ <mid>' absent : {allocated_shoot_line}"
    assert m.start() < save_pos, (
        f"L3 : '→ <mid>' ({m.start()}) doit précéder 'Save' ({save_pos}) : {allocated_shoot_line}"
    )


def test_l3_not_allocated_pas_de_mid(monkeypatch, tmp_path):
    """L3 : Save [NOT ALLOCATED] ne doit PAS porter de '→ <mid>'.

    Cible à 1 PV, 2 attaques, DMG=1 : la première attaque tue la fig, la deuxième
    n'a plus de cible valide → NOT ALLOCATED.
    Rolls hit/wound/save : [3, 4, 2] × 2 ; seuil save = 3 (Sv=2+ AP=-1).
    """
    import re
    gs, raw_log = _engine_shoot_log(monkeypatch, [], [3, 4, 2, 3, 4, 2], n_attacks=2, hp_cur=1)
    lines = _step_log_lines(tmp_path, gs, raw_log)
    not_alloc = [l for l in lines if "NOT ALLOCATED" in l]
    assert not_alloc, (
        "L3 : aucune attaque NOT ALLOCATED produite — vérifier hp_cur=1 et n_attacks=2"
    )
    for line in not_alloc:
        assert not re.search(r"→ \d+#\d+", line), (
            f"L3 : 'Save [NOT ALLOCATED]' ne doit pas porter de '→ <mid>' : {line}"
        )


@pytest.fixture
def devastating_alloc_line(monkeypatch, tmp_path):
    """Tir DEVASTATING WOUNDS alloué : la ligne doit porter → <mid> ET [DEVASTATING WOUNDS]."""
    gs, raw_log = _engine_shoot_log(monkeypatch, ["DEVASTATING_WOUNDS"], [4, 6])
    return _step_log_line(tmp_path, gs, raw_log)


def test_l3_devastating_wounds_porte_mid(devastating_alloc_line):
    """L3 : même sur [DEVASTATING WOUNDS], le mid alloué est présent."""
    import re
    assert "[DEVASTATING WOUNDS]" in devastating_alloc_line, devastating_alloc_line
    assert re.search(r"→ \d+#\d+", devastating_alloc_line), (
        f"L3 : '→ <mid>' attendu même sur [DEVASTATING WOUNDS] : {devastating_alloc_line}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# L4 — AP de l'arme et Sv de base de la figurine sur le segment Save
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def ap_save_line(monkeypatch, tmp_path):
    """Tir avec AP (AP=-1 dans le décor _game_state : weapon AP=-1, armor 2+).

    Rolls : touche 3 (>= BS 3+), blessure 4 (>= 4+), save 2 (< seuil 3 = 2 - (-1) = 3).
    Save échoue : la ligne montre le segment Save complet."""
    gs, raw_log = _engine_shoot_log(monkeypatch, [], [3, 4, 2])
    return _step_log_line(tmp_path, gs, raw_log)


def test_l4_save_affiche_base_ap_effectif(ap_save_line):
    """L4 : le segment Save montre '<base>+ AP<n> → <eff>+' au lieu de '<eff>+' seul."""
    import re
    # Format attendu : Save R(2+ AP-1 → 3+)  [base=2, ap=-1, eff=3]
    assert re.search(r"Save \d+\(\d+\+ AP-?\d+ → \d+\+\)", ap_save_line), (
        f"L4 : format 'Save R(<base>+ AP<n> → <eff>+)' attendu : {ap_save_line}"
    )


def test_l4_save_valeurs_coherentes(ap_save_line):
    """L4 : les valeurs base, AP, eff sont mutuellement cohérentes (max(base-AP, invul) == eff).

    La figurine cible a Sv=2, InSv=7 (pas d'invul, sentinel), et l'arme a AP=-1.
    Seuil effectif = min(2 - (-1), 7) = min(3, 7) = 3 (seuil le moins favorable au sauvegardeur).
    """
    import re
    m = re.search(r"Save \d+\((\d+)\+ AP(-?\d+) → (\d+)\+\)", ap_save_line)
    assert m, f"L4 : pattern non trouvé : {ap_save_line}"
    base_sv, ap_val, eff_sv = int(m.group(1)), int(m.group(2)), int(m.group(3))
    # La figurine a armor=2, invul=7 (sentinel = pas d invul) et AP=-1.
    assert base_sv == 2, f"base Sv attendu 2 (ARMOR_SAVE du décor) : {base_sv}"
    assert ap_val == -1, f"AP attendu -1 (arme du décor) : {ap_val}"
    # eff = base - AP = 2 - (-1) = 3  (AP est négatif, donc base - AP = base + |AP|)
    assert eff_sv == base_sv - ap_val, (
        f"seuil effectif incohérent : {base_sv} - ({ap_val}) ≠ {eff_sv}"
    )


def test_l4_save_ap0_affiche_base(monkeypatch, tmp_path):
    """L4 : même avec AP=0, le format étendu est présent (base présent, pas de modification)."""
    import re
    # AP=0 : on crée le game_state manuellement avec une arme AP=0.
    # On réutilise _engine_shoot_log avec une arme AP=0 en monkey-patchant
    # le weapon dict. Approche simple : RAPID FIRE pour AP=0.
    # En fait, _game_state construit l'arme avec AP=-1 hardcodé ; il faut passer par monkeypatch.
    # Plutôt : tester directement _save_segments avec les bons champs.
    from ai.step_logger import _save_segments

    details = {
        "save_roll": 3,
        "save_target": 3,   # eff = 3 (base 3, AP 0)
        "alloc_model_armor": 3,
        "weapon_ap": 0,
    }
    segs = _save_segments(details, damage=1, save_result="FAIL")
    save_seg = next((s for s in segs if s.startswith("Save")), None)
    assert save_seg is not None, segs
    assert re.search(r"Save \d+\(\d+\+ AP0 → \d+\+\)", save_seg), (
        f"L4 : AP=0 doit aussi afficher le format étendu : {save_seg}"
    )


def test_l4_melee_save_affiche_ap(monkeypatch, tmp_path):
    """L4 : même format sur une ligne FOUGHT (miroir tir/mêlée obligatoire)."""
    import re
    gs, raw_log = _engine_shoot_log(monkeypatch, [], [3, 4, 2], melee=True)
    line = _step_log_line(tmp_path, gs, raw_log)
    assert re.search(r"Save \d+\(\d+\+ AP-?\d+ → \d+\+\)", line), (
        f"L4 : format étendu attendu aussi en mêlée : {line}"
    )
