"""Effets d'OBJECTIF et de RESTITUTION — 14.02 / 14.03 / Relic Banner / Grot Orderly (REVIVED).

Trois compteurs, un par entrée du corpus (bucket §2.3 « dégâts / état de partie ») :

1. ``objective_control_mismatch`` (PROJ.2.3.objective_control, 14.02 + Relic Banner + 08.03). À
   chaque instantané `T{tour} OBJECTIVE CONTROL: … ZONES=<zone>:Ctrl=<c>:Mthd=<m>:OC1=<n>:OC2=<n>[:Sec=<s>]|…`,
   l'OC de chaque camp est RESOMMÉ par zone depuis les socles vivants (`unit_model_hp`,
   `positions_by_model`, empreinte réelle du socle — 14.02 : « A model is within range of a
   terrain objective while it is within that terrain area ») : OC de datasheet par figurine
   (02.02) + `oc_bonus` par figurine si un porteur vivant de l'escouade le confère (19.04,
   « This unit has +1 OC »), 0 pour toute l'escouade battle-shocked (01.07 / 08.03). Écart avec
   `OC1=/OC2=` → faute. Contrôleur attendu (miroir de `_resolve_objective_controller`) : plus haut
   niveau ; égalité → personne, sauf sécurisé (`Mthd=secured`, ou `Sec=` = contrôleur précédent)
   où le contrôleur précédent reste ; un objectif sécurisé n'est perdu que sur STRICTEMENT plus.
2. ``objective_secured_invalid`` (PROJ.2.3.objective_secured, 14.03 — grammaire 15). `Sec=<p>`
   ne peut APPARAÎTRE qu'après une ligne « Unit N(c,r) SECURES <zone> [<capacité>] » de <p>
   depuis l'instantané précédent ; cette ligne est en phase COMMAND de <p>, sur une escouade
   vivante et PRÉSENTE dans l'aire, porteuse de `secure_objective_on_control` (19.04, relevé
   `note_special_rule_usage`), et l'instantané qui suit donne le contrôle à <p>. Une perte de
   `Sec=` sans niveau adverse strictement supérieur, ou `Sec=<p>` maintenu avec un contrôleur
   ≠ <p> sans niveau strictement supérieur, est une faute. Journal < 15 : abstention (pas de Sec=).
3. ``returned_models_invalid`` (PROJ.2.3.returned_models, REVIVED + Grot Orderly). Sur chaque
   ligne `RETURNED k models [GROT ORDERLY] (D3=n) [MODEL_TYPES: mid=type …]` : k ≤ n ; k ≤ figurines
   détruites de l'escouade non encore rendues ; un usage par escouade et par partie ; phase
   COMMAND du propriétaire ; chaque type rendu est celui d'une figurine RÉELLEMENT morte (non
   encore rendue) ; aucun leader/support rendu (« bodyguard models »).

CE QUI EST ÉCARTÉ (abstention) : zone dont une escouade vivante n'a pas de socles connus ou dont
une figurine a une datasheet/OC symbolique ; instantané sans `OC1=/OC2=` (journal antérieur à L18) ;
`Sec=` absent (journal < 15).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple

from ai.analyzer_rules import note_rule_usage, note_special_rule_usage
from shared.data_validation import require_key

#: Une entrée de `ZONES=` : `<nom>:Ctrl=<1|2|none>[:Mthd=<m>][:OC1=<n>:OC2=<n>][:Sec=<1|2|none>]`.
#: Les entrées sont séparées par `|` — le nom d'une zone porte des espaces (« rect b NW »).
ZONE_ENTRY_RE = re.compile(
    r"^\s*(?P<name>.+?):Ctrl=(?P<ctrl>1|2|none)(?::Mthd=(?P<mthd>\w+))?"
    r"(?::OC1=(?P<oc1>-?\d+):OC2=(?P<oc2>-?\d+))?(?::Sec=(?P<sec>1|2|none))?\s*$"
)
#: « Unit N(c,r) SECURES <zone> [<CAPACITÉ>] » (grammaire 15).
SECURES_LINE_RE = re.compile(r"SECURES (.+?) \[([^\]]+)\]")
#: « RETURNED k models [<CAPACITÉ>] (D3=n) » (grammaire 10).
RETURNED_RE = re.compile(r"RETURNED\s+(\d+)\s+models\s+\[([^\]]+)\]\s+\(D3=(\d+)\)")

CONTROL_COUNTER = "objective_control_mismatch"
SECURED_COUNTER = "objective_secured_invalid"
RETURNED_COUNTER = "returned_models_invalid"
SECURED_GRAMMAR = 15


def _error(state: Any, stats: Dict[str, Any], counter: str, player: int, line: str, detail: str) -> None:
    stats[counter][player] += 1
    first = stats["first_error_lines"][counter]
    if first[player] is None:
        first[player] = {"episode": state.current_episode_num, "line": line.strip(), "detail": detail}


def _ctrl(value: str) -> Optional[int]:
    return None if value == "none" else int(value)


def parse_zones(payload: str) -> List[Dict[str, Any]]:
    """Les entrées de `ZONES=`, dans l'ordre. Une entrée illisible LÈVE : le producteur est unique."""
    zones: List[Dict[str, Any]] = []
    for raw in payload.split("|"):
        if not raw.strip():
            continue
        m = ZONE_ENTRY_RE.match(raw)
        if m is None:
            raise ValueError(f"ZONES= : entrée illisible {raw!r}")
        zones.append({
            "name": m.group("name").strip(),
            "ctrl": _ctrl(m.group("ctrl")),
            "mthd": m.group("mthd"),
            "oc": (int(m.group("oc1")), int(m.group("oc2"))) if m.group("oc1") is not None else None,
            "sec": _ctrl(m.group("sec")) if m.group("sec") is not None else "absent",
        })
    return zones


def parse_objective_zones(payload: str) -> Dict[str, Set[Tuple[int, int]]]:
    """Entête `Objectives: <nom>:(c,r);(c,r)|<nom2>:…` → aires par nom (même clé que `ZONES=`)."""
    zones: Dict[str, Set[Tuple[int, int]]] = {}
    for raw in payload.split("|"):
        if not raw.strip():
            continue
        name, sep, cells = raw.partition(":")
        if not sep:
            raise ValueError(f"Objectives: entrée illisible {raw!r}")
        zones[name.strip()] = {
            (int(c), int(r)) for c, r in re.findall(r"\((\d+),(\d+)\)", cells)
        }
    return zones


# ─────────────────────────────────────────────────────────────────────────────
# 14.02 — OC par zone depuis les socles
# ─────────────────────────────────────────────────────────────────────────────


def expected_oc_sums(
    state: Any, config: Any, zone_cells: Set[Tuple[int, int]]
) -> Optional[Tuple[int, int]]:
    """`(OC joueur 1, OC joueur 2)` resommés depuis les socles vivants — miroir de
    `objective_control_contributions` (moteur). None = une escouade vivante n'est pas jugeable."""
    from ai.analyzer_perfig import _model_footprint, model_base, unit_effect_in_force

    sums = [0, 0]
    for uid, hp in state.unit_hp.items():
        if int(hp) <= 0:
            continue
        player = state.unit_player.get(uid)  # get allowed
        if player not in (1, 2):
            continue
        living = state.unit_model_hp.get(uid)  # get allowed : socles jamais vus
        positions = state.positions_by_model.get(uid)  # get allowed
        if not living or not positions:
            # Escouade vivante sans socles connus : hors table (réserves, sentinelle) → 0 OC ;
            # sinon la composition ne tranche pas.
            anchor = state.unit_positions.get(uid)  # get allowed
            if anchor is None or int(anchor[0]) < 0:
                continue
            return None
        if state.battle_shocked_by_unit.get(uid, False):  # get allowed : jamais testée = saine
            continue
        # `unit_oc_bonus` (moteur) SOMME les entrées `oc_bonus` de l'union 19.04 — une par type
        # de porteur présent ; miroir : somme sur les types VIVANTS distincts.
        living_types: Set[str] = set()
        for mid in living:
            mtype = state.model_types.get(mid)  # get allowed
            if mtype is None:
                return None
            living_types.add(mtype)
        bonus = sum(int(config.oc_bonus_by_type.get(t, 0)) for t in living_types)  # get allowed
        if bonus and unit_effect_in_force(state, config, uid, "oc_bonus") is False:
            bonus = 0
        for mid in living:
            pos = positions.get(mid)  # get allowed : socle vivant sans position = hors table
            if pos is None or int(pos[0]) < 0:
                continue
            mtype = state.model_types.get(mid)  # get allowed
            oc = config.unit_oc_by_type.get(mtype)  # get allowed : OC symbolique
            if oc is None:
                return None
            model_oc = int(oc) + bonus
            if model_oc <= 0:
                continue
            # Socle de LA figurine (un personnage attaché déborde de celui de ses Boyz).
            base = model_base(state, config, uid, mid)
            if not _model_footprint(int(pos[0]), int(pos[1]), base).isdisjoint(zone_cells):
                sums[0 if int(player) == 1 else 1] += model_oc
    return sums[0], sums[1]


def expected_controller(
    oc: Tuple[int, int], prev_ctrl: Optional[int], prev_sec: Optional[int], mthd: Optional[str]
) -> Tuple[Optional[int], bool]:
    """Miroir de `_resolve_objective_controller` : (contrôleur attendu, la sécurisation tombe)."""
    use_secured = mthd == "secured" or (prev_sec is not None and prev_sec == prev_ctrl)
    higher: Optional[int] = 1 if oc[0] > oc[1] else 2 if oc[1] > oc[0] else None
    new = (prev_ctrl if higher is None else higher) if use_secured else higher
    clears = prev_sec is not None and new is not None and new != prev_sec
    return new, clears


def handle_objective_control_snapshot(
    state: Any, config: Any, stats: Dict[str, Any], line: str, payload: str
) -> None:
    """Un instantané : chaque zone est jugée (OC resommés, contrôleur, sécurisation), puis
    mémorisée comme état « précédent » pour le suivant."""
    zones = parse_zones(payload)
    for zone in zones:
        name = str(zone["name"])
        cells = state.objective_zones.get(name)  # get allowed : entête sans cette zone
        prev_ctrl = state.objective_last_ctrl.get(name)  # get allowed : premier instantané = None
        prev_sec = state.objective_last_sec.get(name)  # get allowed
        secured_line = state.objective_secures_pending.pop(name, None)
        printed_oc = zone["oc"]
        sec = zone["sec"]
        ctrl = zone["ctrl"]
        if cells and printed_oc is not None:
            expected = expected_oc_sums(state, config, cells)
            if expected is not None:
                note_rule_usage(stats, "PROJ.2.3.objective_control", 1)
                if expected != printed_oc:
                    _error(state, stats, CONTROL_COUNTER, 1, line,
                           f"zone {name} : OC imprimés P1={printed_oc[0]} P2={printed_oc[1]} vs "
                           f"resommés P1={expected[0]} P2={expected[1]}")
                elif ctrl != prev_ctrl:
                    # Le contrôleur n'est déterminé qu'aux FRONTIÈRES de phase (14.02) alors que
                    # l'OC de l'instantané est vivant : entre deux frontières un instantané
                    # (VP, CP) porte un contrôleur d'AVANT le dernier mouvement — mesuré sur le
                    # journal réel du 2026-09-18 (T1 : OC2=8, Ctrl=none, puis Ctrl=2 à la
                    # frontière suivante, même OC). Seul un CHANGEMENT de contrôleur atteste
                    # d'une détermination faite avec ces OC-là ; le maintien sous sécurisation
                    # est jugé par `_judge_secured`.
                    prev_sec_for_ctrl = prev_sec if isinstance(prev_sec, int) else None
                    exp_ctrl, _ = expected_controller(printed_oc, prev_ctrl, prev_sec_for_ctrl, zone["mthd"])
                    if exp_ctrl != ctrl:
                        _error(state, stats, CONTROL_COUNTER, 1, line,
                               f"zone {name} : contrôleur imprimé {ctrl} vs attendu {exp_ctrl} "
                               f"(OC {printed_oc}, précédent {prev_ctrl}, sécurisé {prev_sec_for_ctrl})")
        if sec != "absent" and state.log_grammar >= SECURED_GRAMMAR:
            _judge_secured(state, stats, line, name, ctrl, printed_oc, sec, prev_sec, secured_line)
        state.objective_last_ctrl[name] = ctrl
        state.objective_last_sec[name] = sec if sec != "absent" else None
    # Une ligne SECURES sans instantané qui la reflète : la zone n'existe pas dans ZONES=.
    for name, player in list(state.objective_secures_pending.items()):
        _error(state, stats, SECURED_COUNTER, int(player), line,
               f"SECURES {name} du joueur {player} sans zone {name!r} dans l'instantané suivant")
    state.objective_secures_pending.clear()


def _judge_secured(
    state: Any, stats: Dict[str, Any], line: str, name: str, ctrl: Optional[int],
    oc: Optional[Tuple[int, int]], sec: Optional[int], prev_sec: Optional[int],
    secured_line: Optional[int],
) -> None:
    """14.03 sur une zone : apparition, maintien et perte de `Sec=`."""
    prev = prev_sec if isinstance(prev_sec, int) else None
    if prev is not None:
        note_rule_usage(stats, "PROJ.2.3.objective_secured", prev)
    if sec is not None and sec != prev:
        # APPARITION : une ligne SECURES de ce joueur, et le contrôle lui revient.
        if secured_line != sec:
            _error(state, stats, SECURED_COUNTER, int(sec), line,
                   f"zone {name} sécurisée par {sec} sans ligne SECURES de ce joueur depuis l'instantané précédent")
        elif ctrl != sec:
            _error(state, stats, SECURED_COUNTER, int(sec), line,
                   f"zone {name} sécurisée par {sec} mais contrôlée par {ctrl}")
        return
    if prev is not None and sec is None:
        # PERTE : seulement sur un niveau adverse STRICTEMENT supérieur.
        opp = 2 if prev == 1 else 1
        strictly_higher = oc is not None and oc[opp - 1] > oc[prev - 1]
        if not strictly_higher or ctrl != opp:
            _error(state, stats, SECURED_COUNTER, int(prev), line,
                   f"zone {name} : sécurisation de {prev} perdue sans niveau adverse strictement "
                   f"supérieur (OC {oc}, contrôleur {ctrl})")
        return
    if prev is not None and sec == prev and ctrl != prev:
        _error(state, stats, SECURED_COUNTER, int(prev), line,
               f"zone {name} sécurisée par {prev} mais contrôlée par {ctrl} — un objectif sécurisé "
               "reste contrôlé jusqu'à un niveau adverse strictement supérieur")


def handle_secures_line(
    state: Any, config: Any, stats: Dict[str, Any], line: str, action_desc: str,
    unit_id: str, player: int, phase: str,
) -> bool:
    """Branche de la ligne SECURES (grammaire 15). Rend False si la ligne n'en est pas une."""
    from ai.analyzer_perfig import _model_footprint, model_base, positions_by_model_for

    m = SECURES_LINE_RE.search(action_desc)
    if m is None:
        return False
    name = m.group(1).strip()
    player = int(player)
    note_rule_usage(stats, "PROJ.2.3.objective_secured", player)
    if phase != "COMMAND":
        _error(state, stats, SECURED_COUNTER, player, line,
               f"SECURES {name} en phase {phase} — « at the end of your Command phase »")
    owner = state.unit_player.get(unit_id)  # get allowed
    if owner is not None and int(owner) != player:
        _error(state, stats, SECURED_COUNTER, player, line,
               f"SECURES {name} par Unit {unit_id} du joueur {owner} pendant le tour de {player}")
    cells = state.objective_zones.get(name)  # get allowed
    living = state.unit_model_hp.get(unit_id, {})  # get allowed
    positions = positions_by_model_for(state, unit_id)
    if not living:
        _error(state, stats, SECURED_COUNTER, player, line, f"SECURES {name} par une escouade sans socle vivant")
    elif cells is not None and positions:
        inside = any(
            not _model_footprint(int(p[0]), int(p[1]), model_base(state, config, unit_id, mid)).isdisjoint(cells)
            for mid, p in positions.items() if mid in living and int(p[0]) >= 0
        )
        if not inside:
            _error(state, stats, SECURED_COUNTER, player, line,
                   f"SECURES {name} par Unit {unit_id} sans aucun socle dans l'aire")
    unit_type = state.unit_types.get(unit_id)  # get allowed
    if unit_type:
        note_special_rule_usage(stats, state, config, "secure_objective_on_control", unit_id, unit_type, player)
    state.objective_secures_pending[name] = player
    return True


# ─────────────────────────────────────────────────────────────────────────────
# Grot Orderly — REVIVED
# ─────────────────────────────────────────────────────────────────────────────


def check_returned_models(
    state: Any, config: Any, stats: Dict[str, Any], line: str, action_desc: str,
    unit_id: str, player: int, phase: str, declared_types: Dict[str, str],
    dead_mids_before: Set[str],
) -> None:
    """Une ligne RETURNED : k ≤ D3, k ≤ mortes rendables, un usage par escouade et par partie,
    phase COMMAND du propriétaire, types ⊆ mortes non rendues, aucun leader/support."""
    from ai.analyzer_core import _model_is_character

    m = RETURNED_RE.search(action_desc)
    if m is None:
        return
    k, d3 = int(m.group(1)), int(m.group(3))
    player = int(player)
    note_rule_usage(stats, "PROJ.2.3.returned_models", player)
    if k > d3:
        _error(state, stats, RETURNED_COUNTER, player, line, f"{k} figurines rendues pour un D3 de {d3}")
    if phase != "COMMAND":
        _error(state, stats, RETURNED_COUNTER, player, line, f"RETURNED en phase {phase} — « In your Command phase »")
    owner = state.unit_player.get(unit_id)  # get allowed
    if owner is not None and int(owner) != player:
        _error(state, stats, RETURNED_COUNTER, player, line,
               f"RETURNED de Unit {unit_id} (joueur {owner}) pendant le tour de {player}")
    if unit_id in state.returned_models_used:
        _error(state, stats, RETURNED_COUNTER, player, line,
               f"second Grot Orderly de Unit {unit_id} dans la partie — « Once per battle »")
    state.returned_models_used.add(unit_id)
    already = state.returned_models_by_unit.setdefault(unit_id, [])
    # Types des figurines RÉELLEMENT mortes et non encore rendues (multi-ensemble).
    dead_types: List[str] = []
    for mid in sorted(dead_mids_before):
        mtype = state.model_types.get(mid)  # get allowed
        if mtype is not None:
            dead_types.append(mtype)
    for mtype in already:
        if mtype in dead_types:
            dead_types.remove(mtype)
    if k > len(dead_types):
        _error(state, stats, RETURNED_COUNTER, player, line,
               f"{k} figurines rendues pour {len(dead_types)} détruite(s) rendable(s)")
    for mid, mtype in declared_types.items():
        if _model_is_character(config, mtype):
            _error(state, stats, RETURNED_COUNTER, player, line,
                   f"{mid}={mtype} rendu : un leader/support n'est pas un bodyguard model")
        elif mtype in dead_types:
            dead_types.remove(mtype)
        else:
            _error(state, stats, RETURNED_COUNTER, player, line,
                   f"{mid}={mtype} rendu alors qu'aucune figurine de ce type n'est morte (non rendue)")
        already.append(mtype)
