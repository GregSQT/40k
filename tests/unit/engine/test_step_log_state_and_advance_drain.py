"""Deux trous de journalisation fermés ensemble, mesurés sur le run de 600 épisodes du 2026-08-08.

1. `advance_phase` (« pool_empty ») appelait `_process_squad_action` SANS drainer ses action_logs.
   Cette transition n'est pas neutre : elle déclenche `fight_phase_start` puis le PILE IN groupé
   (12.02). Résultat mesuré : **zéro** ligne `PILED IN` dans 22 Mo de journal, pour 203
   `CONSOLIDATED` — la consolidation, elle, naît pendant `squad_fight`, donc dans la fenêtre de
   drainage. Instrumentation du chemin de production : plan calculé 24 fois (jamais None), commité
   24 fois, action_log appendu 24 fois, **drainé 0 fois**. Côté lecteurs : 229 chargeurs sur 319
   changeaient de position entre leur ligne de charge et leur ligne de combat sans qu'aucune ligne
   ne l'explique, et le contrôle « Pile-in au-delà de 3" » affichait 0 en ne regardant rien.

2. Aucun lecteur du journal n'avait de point de RECALAGE : l'état est reconstruit par accumulation
   (PV initial moins chaque `Dmg:`, position initiale plus chaque déplacement). Une donnée
   manquante dérivait jusqu'à la fin de l'épisode — 546 lignes portent une sauvegarde ratée sans
   segment `Dmg:`, d'où 76 « action sur une unité morte » et 15 « Missing unit_hp on damage ».
   La ligne `T{tour} STATE:` borne la dérive à un tour et la rend mesurable.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

import pytest

from ai.step_logger import StepLogger
from engine.w40k_core import W40KEngine
from shared.data_validation import ConfigurationError


def _logger(tmp_path) -> StepLogger:
    return StepLogger(output_file=str(tmp_path / "step.log"), enabled=True, buffer_size=1)


def _engine(game_state: Dict[str, Any], logger: StepLogger) -> W40KEngine:
    """Instance nue : les deux méthodes testées ne touchent que `game_state` et `step_logger`."""
    eng = W40KEngine.__new__(W40KEngine)
    eng.game_state = game_state
    eng.step_logger = logger
    return eng


def _state(turn: int = 1) -> Dict[str, Any]:
    return {
        "turn": turn,
        "units_cache": {
            "1": {
                "occupied_hexes_by_model": {"1#0": (5, 48), "1#1": (7, 47)},
                "floor_height_by_model": {"1#0": 0.0, "1#1": 2.5},
            },
            "101": {
                "occupied_hexes_by_model": {"101#5": (4, 49)},
                "floor_height_by_model": {"101#5": 0.0},
            },
        },
        "models_cache": {
            "1#0": {"HP_CUR": 2}, "1#1": {"HP_CUR": 1}, "101#5": {"HP_CUR": 2},
        },
    }


# ── 1. Ligne d'état par tour ────────────────────────────────────────────────────────────────

def test_ligne_detat_porte_socles_positions_hauteurs_et_pv(tmp_path) -> None:
    logger = _logger(tmp_path)
    eng = _engine(_state(turn=3), logger)
    eng._log_state_snapshot_if_turn_changed()
    logger._flush_buffer()

    content = (tmp_path / "step.log").read_text(encoding="utf-8")
    assert "T3 STATE:" in content, content
    assert "1[1#0@(5,48,z0):2 1#1@(7,47,z2.5):1]" in content, content
    assert "101[101#5@(4,49,z0):2]" in content, content


def test_une_seule_ligne_par_tour_puis_une_nouvelle_au_tour_suivant(tmp_path) -> None:
    logger = _logger(tmp_path)
    gs = _state(turn=1)
    eng = _engine(gs, logger)
    eng._log_state_snapshot_if_turn_changed()
    eng._log_state_snapshot_if_turn_changed()  # même tour : ne doit rien réécrire
    gs["turn"] = 2
    eng._log_state_snapshot_if_turn_changed()
    logger._flush_buffer()

    lines = [l for l in (tmp_path / "step.log").read_text(encoding="utf-8").splitlines() if "STATE:" in l]
    assert len(lines) == 2, lines
    assert "T1 STATE:" in lines[0] and "T2 STATE:" in lines[1], lines


def test_figurine_absente_du_models_cache_est_absente_de_la_ligne(tmp_path) -> None:
    """L'absence EST la mort : aucun drapeau vivant/mort à accorder avec les positions.

    C'est le point du correctif — le journal ne disait jamais qu'une figurine était tombée quand
    sa blessure était écartée faute d'allocataire (546 lignes `Save X(None+)` sans `Dmg:`).
    """
    logger = _logger(tmp_path)
    gs = _state(turn=1)
    del gs["models_cache"]["1#1"]          # figurine détruite
    del gs["models_cache"]["101#5"]        # dernière figurine de l'unité 101 : l'unité disparaît
    eng = _engine(gs, logger)
    eng._log_state_snapshot_if_turn_changed()
    logger._flush_buffer()

    content = (tmp_path / "step.log").read_text(encoding="utf-8")
    assert "1[1#0@(5,48,z0):2]" in content, content
    assert "1#1@" not in content, content
    assert "101[" not in content, content


def test_hp_manquant_leve_au_lieu_de_journaliser_un_etat_faux(tmp_path) -> None:
    """Un instantané tronqué ferait passer une dérive pour un état constaté : il doit lever."""
    logger = _logger(tmp_path)
    gs = _state(turn=1)
    del gs["models_cache"]["1#0"]["HP_CUR"]
    eng = _engine(gs, logger)
    with pytest.raises(ConfigurationError):
        eng._log_state_snapshot_if_turn_changed()


# ── 2. Drainage des action_logs d'`advance_phase` ───────────────────────────────────────────

def test_advance_phase_draine_ses_action_logs(tmp_path) -> None:
    """VERROU DU DÉFAUT : c'est par là que passait le PILE IN, et il n'était drainé par personne.

    Remettre `self._process_squad_action(advance_action)` à la place de
    `self._advance_phase_and_drain(...)` rend ce test ROUGE (`drained` reste vide).
    """
    gs: Dict[str, Any] = {"turn": 4, "fight_subphase": "pile_in", "action_logs": [{"type": "move"}]}
    eng = W40KEngine.__new__(W40KEngine)
    eng.game_state = gs
    drained: List[Tuple[int, Any, Any]] = []

    def _process(action):
        # Ce que fait réellement la transition : elle entre en phase de combat et y produit le
        # pile-in groupé (12.02) — donc des action_logs, APRÈS le drainage de l'action de l'agent.
        gs["action_logs"].append({"type": "pile_in", "unitId": "1"})
        gs["action_logs"].append({"type": "pile_in", "unitId": "2"})
        return True, {"action": "advance_phase"}

    def _flush(pre_len, pre_turn, pre_fight=None):
        drained.append((pre_len, pre_turn, pre_fight))

    eng._process_squad_action = _process           # type: ignore[method-assign]
    eng._flush_squad_action_logs_to_step_logger = _flush  # type: ignore[method-assign]

    success, _ = eng._advance_phase_and_drain({"action": "advance_phase", "from": "charge"})

    assert success is True
    assert len(drained) == 1, drained
    pre_len, pre_turn, pre_fight = drained[0]
    # Le curseur est celui d'AVANT la transition : les deux entrées produites par elle tombent
    # dans la fenêtre. Le lire APRÈS les aurait laissées hors de portée de tout drainage.
    assert pre_len == 1, pre_len
    assert [e["type"] for e in gs["action_logs"][pre_len:]] == ["pile_in", "pile_in"]
    assert pre_turn == 4
    assert pre_fight == {"fight_subphase": "pile_in"}


def test_une_entree_nest_jamais_drainee_deux_fois(tmp_path) -> None:
    """Corollaire du drainage imbriqué : deux fenêtres peuvent se recouvrir.

    Celle d'`advance_phase` et celle, plus large, du step qui l'englobe. Sans curseur persistant,
    la même ligne partirait deux fois dans step.log — et compterait double partout (attaques,
    activations, distances) sans qu'aucune erreur ne le signale.
    """
    logger = _logger(tmp_path)
    eng = W40KEngine.__new__(W40KEngine)
    eng.step_logger = logger
    eng.game_state = {
        "turn": 2,
        "action_logs": [
            {"type": "pile_in", "unitId": "1", "player": 1, "phase": "fight", "turn": 2,
             "fromCol": 1, "fromRow": 1, "toCol": 2, "toRow": 2},
        ],
    }
    eng._flush_squad_action_logs_to_step_logger(0, 2, None)   # drainage imbriqué
    eng._flush_squad_action_logs_to_step_logger(0, 2, None)   # drainage englobant, même curseur
    logger._flush_buffer()

    lines = [l for l in (tmp_path / "step.log").read_text(encoding="utf-8").splitlines()
             if "PILED IN" in l]
    assert len(lines) == 1, lines


def test_aucun_site_advance_phase_ne_court_circuite_le_drainage() -> None:
    """Le test ci-dessus verrouille le HELPER ; celui-ci verrouille ses APPELANTS.

    Le défaut ne venait pas d'un drainage cassé — il venait de trois sites qui ne drainaient pas.
    Un quatrième site (ou un retour en arrière sur l'un des trois) rejouerait exactement le même
    journal muet, sans qu'aucun test de comportement ne bronche : les entrées perdues ne
    provoquent aucune erreur, elles manquent, simplement.
    """
    import inspect
    from engine import w40k_core

    source = inspect.getsource(w40k_core)
    direct = source.count("_process_squad_action(advance_action)")
    via_helper = source.count("_advance_phase_and_drain(advance_action)")
    # Une seule occurrence directe autorisée : celle qui vit DANS `_advance_phase_and_drain`.
    assert direct == 1, (
        f"{direct} appels directs à `_process_squad_action(advance_action)` (1 attendu, dans le "
        f"helper). Un site qui court-circuite `_advance_phase_and_drain` perd ses action_logs — "
        f"dont le PILE IN groupé (12.02) — sans provoquer la moindre erreur."
    )
    assert via_helper >= 3, via_helper


# ── 3. Datasheet par figurine dans l'entête d'épisode ───────────────────────────────────────

def test_model_types_nomme_la_datasheet_de_chaque_socle() -> None:
    """Une escouade n'est pas homogène : la règle 19 y replie un personnage COMME figurine.

    Sans ce segment, tout plafond calculé par figurine repose sur le type d'ESCOUADE. Mesuré :
    5 attaques d'un Ancient rattaché (arme NB=5) plafonnées au NB=3 de l'Intercessor porteur.
    Le nom d'affichage de l'arme ne peut pas trancher — cinq armes s'appellent « Close Combat
    Weapon », de NB 2 à 6.
    """
    eng = W40KEngine.__new__(W40KEngine)
    eng.game_state = {
        "squad_models": {"105": ["105#0", "105#4", "105#5", "105#6"]},
        "models_cache": {
            "105#0": {},                              # pas de type propre -> celui de l'escouade
            "105#4": {"unit_type": "IntercessorSergeant"},
            "105#5": {"unit_type": "CaptainRelicShield"},
            "105#6": {"unit_type": "Ancient"},
        },
    }
    seg = eng._model_types_segment_for_unit("105", "Intercessor")
    assert seg == (
        "[MODEL_TYPES: 105#0=Intercessor 105#4=IntercessorSergeant "
        "105#5=CaptainRelicShield 105#6=Ancient]"
    ), seg


def test_model_types_ignore_les_figurines_deja_retirees() -> None:
    eng = W40KEngine.__new__(W40KEngine)
    eng.game_state = {
        "squad_models": {"1": ["1#0", "1#1"]},
        "models_cache": {"1#0": {}},  # 1#1 détruite
    }
    assert eng._model_types_segment_for_unit("1", "Boyz") == "[MODEL_TYPES: 1#0=Boyz]"


# ── 4. Token [WAAAGH!] : émis ET relu ───────────────────────────────────────────────────────

def test_token_waaagh_est_emis_sur_la_ligne_de_melee(tmp_path) -> None:
    logger = _logger(tmp_path)
    msg = logger._format_replay_style_message("1", "combat", {
        "unit_with_coords": "1(5,5)", "target_id": "101", "target_coords": (6, 5),
        "weapon_name": "Choppa", "waaagh_melee": True,
        "hit_roll": 4, "hit_target": 3, "hit_result": "HIT",
        "wound_roll": 5, "wound_target": 3, "wound_result": "WOUND",
        "save_roll": 2, "save_target": 4, "save_result": "FAIL", "damage_dealt": 1,
        "fight_subphase": "fight",
    })
    assert "FOUGHT [WAAAGH!] Unit 101(6,5) with [Choppa]" in msg, msg


def test_la_ligne_avec_waaagh_reste_lue_par_lanalyzer() -> None:
    """JUMEAU : poser un token entre le verbe et la cible casse tout lecteur à grammaire rigide.

    C'est le motif de panne déjà payé sur le move (3 lignes non parsées suffisaient à fabriquer
    3 fausses adjacences). Ici, une ligne non reconnue échapperait à TOUS les contrôles de combat
    — plafond d'attaques, alternance, cible morte — sans lever la moindre erreur.
    """
    import inspect
    import re as _re

    from ai.analyzer_phases import fight_handler
    import ai.hidden_action_finder as haf

    line = "Unit 105(22,26) FOUGHT [WAAAGH!] Unit 1(23,26) with [Choppa] - Hit 5(3+)"
    full = "[10:00:00] E1 T3 P2 FIGHT : " + line

    # Les deux lecteurs portent leur motif en clair dans leur source : on l'EN EXTRAIT plutôt
    # que d'en réécrire une copie ici, qui ne prouverait rien de ce que le code fait vraiment.
    def _patterns(module, needle: str) -> list:
        src = inspect.getsource(module)
        return [m for m in _re.findall(r"r'([^']*" + needle + r"[^']*)'", src)]

    assert _patterns(fight_handler, r"ATTACKED\|FOUGHT"), (
        "motif de combat introuvable dans le handler analyzer"
    )
    m = _re.search(
        r'Unit (\d+)\((\d+),\s*(\d+)\) (?:ATTACKED|FOUGHT)(?:\s+\[[^\]]+\])*'
        r'\s+Unit (\d+)\((\d+),\s*(\d+)\)', line,
    )
    assert m is not None and (m.group(1), m.group(4)) == ("105", "1"), line
    # La tolérance doit être PRÉSENTE dans les deux sources, pas seulement dans ce test.
    assert r"(?:\s+\[[^\]]+\])*" in inspect.getsource(fight_handler), (
        "le motif de combat de l'analyzer n'accepte plus de token entre le verbe et la cible"
    )
    haf_src = inspect.getsource(haf)
    assert "_FIGHT_ABILITY" in haf_src and r"(?:\s+\[[^\]]+\])*" in haf_src, (
        "hidden_action_finder n'accepte plus de token de capacité sur les lignes de mêlée"
    )
    assert _re.search(
        r'\[([^\]]+)\] E(\d+) T(\d+) P(\d+) FIGHT : Unit (\d+)\((\d+),(\d+)\) FOUGHT'
        r'(?:\s+\[[^\]]+\])*\s+Unit (\d+)\((\d+),(\d+)\)', full
    ) is not None, full
