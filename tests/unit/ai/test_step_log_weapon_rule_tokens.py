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

import random

import pytest

from engine.phase_handlers import shooting_handlers
from engine.phase_handlers.shared_utils import build_manual_shoot_allocation
from tests._state_invariants import turn_state_invariants


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


def _uc(col, row, *, player, models=None):
    """Entrée units_cache. `occupied_hexes_by_model` est ce dont `_models_segment_for_unit`
    tire le segment `[MODELS: A1@(c,r,z0)]` — sans lui l'analyzer ne connaît pas le NOMBRE de
    figurines de l'escouade, donc pas le plafond de tirs, donc pas la fenêtre RAPID FIRE.

    `floor_height_by_model` est écrite AVEC elle, jamais seule : les deux cartes sont le contrat
    de la couche per-figurine (position + altitude, §03.04), et le moteur exige la seconde dès
    que la première est là. Plateau plat ici → 0.0 partout."""
    entry = {"BASE_SHAPE": "round", "BASE_SIZE": 6, "col": col, "row": row,
             "occupied_hexes": set(), "VALUE": 10.0, "player": player}
    if models:
        entry["occupied_hexes_by_model"] = dict(models)
        entry["floor_height_by_model"] = {mid: 0.0 for mid in models}
    return entry


def _game_state(weapon_rules, *, moved_inches=0.0, target=TARGET, n_attacks=1,
                unit_rules=(), cover=False, unit_type=UNIT_TYPE, weapon_name=WEAPON_NAME):
    """Tireur '1' vs cible '101', 1 attaque, en `gym_training_mode` (allocation auto)."""
    weapon = {"ATK": 3, "STR": 4, "AP": -1, "DMG": 1, "NB": 2, "RNG": WEAPON_RANGE,
              "WEAPON_RULES": list(weapon_rules), "display_name": weapon_name}
    attacker = {"id": "1#0", "squad_id": "1", "player": 0, "T": 4, "SHOOT_LEFT": 1,
                "col": SHOOTER[0], "row": SHOOTER[1], "RNG_WEAPONS": [weapon]}
    target_model = {"id": "101#0", "squad_id": "101", "player": 1, "T": 4, "HP_CUR": 9, "HP_MAX": 9,
                    "ARMOR_SAVE": 2, "INVUL_SAVE": 7, "role": None, "unitType": "AssaultIntercessor",
                    "points_per_hp": 5.0, "VALUE": 10.0, "col": target[0], "row": target[1]}
    return {**turn_state_invariants(),
        "gym_training_mode": True,
        "turn": 1, "phase": "shoot",
        "action_logs": [], "action_log_seq": 0,
        "models_cache": {"1#0": attacker, "101#0": target_model},
        "squad_models": {"1": ["1#0"], "101": ["101#0"]},
        "squad_cache": {"1": {"model_count_at_start": 1}, "101": {"model_count_at_start": 1}},
        "units_cache": {"1": _uc(*SHOOTER, player=0, models={"1#0": SHOOTER}),
                        "101": _uc(*target, player=1, models={"101#0": target})},
        "units": [{"id": "1", "player": 0, "unitType": unit_type},
                  {"id": "101", "player": 1, "unitType": "AssaultIntercessor"}],
        # `deployed_on_turn` : clause 2 de [HEAVY] 24.16 (« not set up this turn »), lue par
        # le moteur. 0 = posée avant la bataille.
        "unit_by_id": {"1": {"id": "1", "UNIT_RULES": list(unit_rules), "deployed_on_turn": 0},
                       "101": {"id": "101", "UNIT_RULES": [], "deployed_on_turn": 0}},
        "objectives": [], "units_moved": set(), "units_advanced": set(),
        "inches_to_subhex": 5,
        "moved_distance_by_model": {"1#0": float(moved_inches) * 5},
        "pending_squad_shoot_intents": {
            "1": [{"model_id": "1#0", "target_unit_id": "101", "weapon_index": 0,
                   "n_attacks_resolved": n_attacks}]
        },
    }


def _engine_shoot_log(monkeypatch, weapon_rules, rolls, *, moved_inches=0.0, target=TARGET,
                      n_attacks=1, unit_rules=(), cover=False, unit_type=UNIT_TYPE,
                      weapon_name=WEAPON_NAME):
    """Fait jouer UN tir par le vrai moteur et rend (game_state, action_log de type 'shoot')."""
    seq = list(rolls)

    def fake(a, b):
        assert seq, "sequence RNG epuisee"
        return seq.pop(0)

    monkeypatch.setattr(random, "randint", fake)
    monkeypatch.setattr(shooting_handlers, "compute_unit_los", lambda gs, s, t: {"cover": cover})
    monkeypatch.setattr(shooting_handlers, "_get_unit_by_id", lambda gs, sid: {"id": sid})

    monkeypatch.setattr(
        shooting_handlers, "_is_adjacent_to_enemy_within_cc_range", lambda gs, u: False
    )
    gs = _game_state(weapon_rules, moved_inches=moved_inches, target=target,
                     n_attacks=n_attacks, unit_rules=unit_rules, cover=cover,
                     unit_type=unit_type, weapon_name=weapon_name)
    build_manual_shoot_allocation(gs, "1")
    shoot_logs = [l for l in gs["action_logs"] if l.get("type") == "shoot"]
    assert shoot_logs, "le moteur n'a émis aucun log de tir"
    return gs, shoot_logs[0]


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

    out = tmp_path / "engine_line.log"
    logger = StepLogger(output_file=str(out), enabled=True, buffer_size=1)
    logger.episode_number = 1
    for shot in shots:
        logger.log_action(
            unit_id=raw_log["shooterId"], action_type="shoot", phase="shoot",
            player=1, success=True, step_increment=True,
            action_details=bridge._build_shot_details(raw_log, shot, 1, None),
        )
    logger._flush_buffer()
    lines = [l for l in out.read_text().splitlines() if " SHOOT : " in l]
    assert len(lines) == len(shots), (
        "le StepLogger n'a pas produit une ligne par jet — `log_action` avale ses exceptions, "
        f"un champ requis manque probablement dans le mapping ({len(lines)}/{len(shots)})"
    )
    return lines


def _step_log_line(tmp_path, gs, raw_log):
    """Première ligne, pour les tests qui ne regardent qu'un jet."""
    return _step_log_lines(tmp_path, gs, raw_log)[0]


def _analyzer_stats(tmp_path, engine_lines, *, unit_type=UNIT_TYPE):
    """Injecte la/les ligne(s) PRODUITE(S) PAR LE MOTEUR dans un step.log valide, et lance
    le vrai analyzer dessus."""
    import ai.analyzer as an

    if isinstance(engine_lines, str):
        engine_lines = [engine_lines]
    body = "\n".join(
        f"[10:00:0{2 + i}] E1 T1 P1 SHOOT : {l.split(' : ', 1)[1]}"
        for i, l in enumerate(engine_lines)
    )
    log = tmp_path / "step.log"
    log.write_text(
        "=== STEP-BY-STEP ACTION LOG ===\n"
        "================================================================================\n\n"
        "[10:00:00] === EPISODE 1 START ===\n"
        "[10:00:00] Scenario: scenario_bot-01\n"
        "[10:00:00] Opponent: SelfplayBot\n"
        "[10:00:00] Walls: \n"
        f"[10:00:00] Objectives: rect b NW:{OBJECTIVES}\n"
        "[10:00:00] Board: cols=220 rows=300 inches_to_subhex=5 hex_radius=2.78 margin=1\n"
        "[10:00:00] Run rules: engagement_zone_subhex=10 metric.engagement=hex metric.ranged=euclidean move.thru_ez=True move.thru_enemy=False move.thru_friendly=True cohesion.model_subhex=10 cohesion.global_subhex=45 cohesion.min_neighbors=1\n"
        f"[10:00:00] Unit 1 ({unit_type}) P1: Starting position (-1,-1), HP_MAX=2 base=round/6\n"
        "[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position (-1,-1), HP_MAX=2 base=round/6\n"
        "[10:00:00] === ACTIONS START ===\n"
        f"[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1({SHOOTER[0]},{SHOOTER[1]}) DEPLOYED from (-1,-1) to ({SHOOTER[0]},{SHOOTER[1]}) [R:+0.0] [SUCCESS]\n"
        f"[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101({TARGET[0]},{TARGET[1]}) DEPLOYED from (-1,-1) to ({TARGET[0]},{TARGET[1]}) [R:+0.0] [SUCCESS]\n"
        f"{body}\n"
    )
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
    assert "Save 2(3+)" in line, f"la sauvegarde ne doit pas porter le couvert : {line}"


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
