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
    eng.step_logger = _LoggerStub()
    drained: List[Tuple[Any, Any]] = []

    def _process(action):
        # Ce que fait réellement la transition : elle entre en phase de combat et y produit le
        # pile-in groupé (12.02) — donc des action_logs, APRÈS le drainage de l'action de l'agent.
        gs["action_logs"].append({"type": "pile_in", "unitId": "1"})
        gs["action_logs"].append({"type": "pile_in", "unitId": "2"})
        return True, {"action": "advance_phase"}

    def _flush(pre_turn, pre_fight=None):
        drained.append((pre_turn, pre_fight))

    eng._process_squad_action = _process           # type: ignore[method-assign]
    eng._flush_squad_action_logs_to_step_logger = _flush  # type: ignore[method-assign]

    success, _ = eng._advance_phase_and_drain({"action": "advance_phase", "from": "charge"})

    assert success is True
    assert len(drained) == 1, drained
    pre_turn, pre_fight = drained[0]
    # La BORNE n'est plus un paramètre : c'est le curseur persistant, à l'intérieur du flush.
    # Ce que le helper transporte, c'est le contexte de FORMATAGE, capturé AVANT la transition
    # (la sous-phase change pendant).
    assert pre_turn == 4
    assert pre_fight == {"fight_subphase": "pile_in"}


class _LoggerStub:
    """StepLogger minimal : le helper ne construit son contexte que si quelqu'un journalise."""

    enabled = True


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
    eng._flush_squad_action_logs_to_step_logger(2, None)   # drainage imbriqué
    eng._flush_squad_action_logs_to_step_logger(2, None)   # drainage englobant
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

    ⚠️ Les entrées portent la clé `unitType` (camelCase), celle que le PRODUCTEUR écrit
    (`shared_utils._build_models_cache_entry`). Ce test la construisait en `unit_type` — une
    forme que `models_cache` ne contient jamais : il restait vert pendant que la production
    repliait chaque figurine sur le type d'escouade. Un test qui fabrique une situation que le
    code réel ne produit pas ne verrouille rien ; il certifie l'inverse de ce qu'il annonce.
    """
    eng = W40KEngine.__new__(W40KEngine)
    eng.game_state = {
        "squad_models": {"105": ["105#0", "105#4", "105#5", "105#6"]},
        "models_cache": {
            "105#0": {},                             # pas de type propre -> celui de l'escouade
            "105#4": {"unitType": "IntercessorSergeant"},
            "105#5": {"unitType": "CaptainRelicShield"},
            "105#6": {"unitType": "Ancient"},
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


def test_la_ligne_avec_waaagh_reste_lue_par_les_quatre_consommateurs() -> None:
    """JUMEAU — le defaut a ete commis ICI, et un code-review l'a rattrape.

    Poser un token entre le verbe et la cible casse tout lecteur a grammaire rigide. QUATRE
    lecteurs portaient cette grammaire ; deux seulement avaient ete corriges. Les deux oublies
    etaient les plus couteux, et tous deux echouaient EN SILENCE :
      - l'aiguillage (`"FOUGHT Unit" in action_desc`) : aucun controle de combat n'etait appele
        sur une ligne Waaagh — plafond d'attaques, alternance et recalage de position sautaient ;
      - l'application des degats (`'fought unit' in ...lower()`) : la cible gardait des PV
        fantomes et sa mort n'etait jamais enregistree, rouvrant la derive que l'instantane
        `STATE:` venait de fermer.
    Les trois lecteurs Python partagent desormais `attack_line_re` ; le quatrieme est le parseur
    du replay (TypeScript), verrouille par son propre motif ci-dessous.
    """
    from ai.analyzer_core import attack_line_re, attack_verb_present
    from ai.replay_converter import _ACTION_GRAMMAR  # noqa: F401  (import = grammaire construite)
    import ai.hidden_action_finder as haf
    import inspect
    import pathlib as _pathlib
    import re as _re

    line = "Unit 105(22,26) FOUGHT [WAAAGH!] Unit 1(23,26) with [Choppa] - Hit 5(3+) - Dmg:1HP"

    # 1. aiguillage
    assert attack_verb_present(line), line
    # 2. grammaire complete (handler de combat)
    m = attack_line_re().search(line)
    assert m is not None and (m.group(1), m.group(4)) == ("105", "1"), line
    # 3. application des degats : meme grammaire, cible en groupe 4
    m2 = attack_line_re(with_positions=False).search(line)
    assert m2 is not None and m2.group(4) == "1", line
    # 4. hidden_action_finder
    haf_src = inspect.getsource(haf)
    assert "_FIGHT_ABILITY" in haf_src and r"(?:\s+\[[^\]]+\])*" in haf_src, (
        "hidden_action_finder n'accepte plus de token de capacite sur les lignes de melee"
    )
    # 5. parseur du replay (TypeScript) : la ligne DISPARAIT du replay sans cette tolerance.
    ts = _pathlib.Path(__file__).resolve().parents[3] / "frontend/src/utils/replayParser.ts"
    ts_src = ts.read_text(encoding="utf-8")
    fight_re = [l for l in ts_src.splitlines()
                if "FIGHT : Unit" in l and "FOUGHT" in l and not l.strip().startswith("//")]
    assert fight_re and all(r"(?:\s+\[[^\]]+\])*" in l for l in fight_re), fight_re

    # Et le SITE lui-meme n'utilise plus de test par sous-chaine.
    from ai import analyzer_core
    core_src = inspect.getsource(analyzer_core)
    # On regarde les lignes EXECUTABLES (`if`/`elif`), pas les docstrings qui citent l'ancien
    # motif pour expliquer le defaut.
    branches = [l.strip() for l in core_src.splitlines()
                if l.strip().startswith(("if ", "elif "))]
    assert not [l for l in branches if '"FOUGHT Unit" in action_desc' in l], (
        "l'aiguillage est revenu a un test par sous-chaine : une ligne a token est ignoree"
    )
    assert not [l for l in branches if "'fought unit' in" in l.lower()], (
        "l'application des degats est revenue a un test par sous-chaine"
    )
    assert _re.search(r"attack_line_re", core_src) is not None
