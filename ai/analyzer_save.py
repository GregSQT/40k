"""Effets DÉFENSIFS des capacités Armageddon — seuil de sauvegarde et Feel No Pain (05.04, 24.12).

Le journal écrit ce que le moteur a appliqué et rien ne le vérifiait :
  - ``Save R(<base>+ AP<n> → <eff>+)`` — le seuil de sauvegarde EFFECTIF de la figurine allouée ;
  - ``Dmg:XHP [FNP:<sauvés>/<seuil>+ ×<tentatives>]`` — les jets Feel No Pain d'une attaque ;
  - ``SUFFERS n Mortal Wounds [<tag>] … [FNP_ROLLS: <mid>=<sauvés>/<seuil>+ ×<blessures> …]`` —
    leur miroir sur les blessures mortelles, PAR FIGURINE.

Deux compteurs, un par entrée du corpus (bucket §2.3 « dégâts ») :

1. ``save_threshold_mismatch`` (PROJ.2.3.save_threshold). Seuil attendu = ce que calcule
   `save_threshold` du MOTEUR : min(Sv − AP, InSv effective), InSv effective = la meilleure entre
   la datasheet de la figurine allouée, les `invul_save_override` portés par une source PRÉSENTE
   de l'escouade (19.04 : Waaagh! Banner 5+, Mental Fortress 4+) et le 5+ du Waaagh! quand
   `T{tour} EFFECTS:` le dit actif pour le camp défenseur et que l'escouade porte la capacité
   (`waaagh_invul`, LU dans EFFECTS et jamais redeviné). 05.04 : « Invulnerable Save … the
   result is equal to or greater than that characteristic ; Save and AP … » — le meilleur des
   deux, jamais les deux. Pas de plafond à 6 : un Sv 5+ sous AP−2 vaut 7+, c'est-à-dire
   insauvable, et c'est ce que le moteur imprime.
2. ``fnp_threshold_mismatch`` (PROJ.2.3.fnp, 24.12). Seuil attendu = le MEILLEUR des seuils portés
   par des sources présentes (24.02 : instances dupliquées non cumulatives, « the controlling
   player must select which instance will apply » — le meilleur seuil est le seul choix
   rationnel, et le moteur le prend) : Dok's Toolz si un porteur de `feel_no_pain` est présent ;
   Psychic Hood si un porteur de `feel_no_pain_vs_psychic` est présent ET que l'arme est
   `[PSYCHIC]` (ou la source de la blessure mortelle : Da Jump) ; Unbreakable Resolve seulement
   si la FIGURINE ALLOUÉE porte `feel_no_pain_near_objective` ET est à portée d'un objectif
   (14.02 : « within range of a terrain objective while it is within that terrain area » — son
   socle recouvre l'aire) ou à 6" du centre, mesurés du BORD de son socle (01.04) avec la
   métrique de portée du run. Aucun FNP attendu → tout `[FNP:]` est une faute ;
   FNP attendu, dégâts appliqués (`Dmg:X>0`) sans `[FNP:]` → faute ; seuil ≠ attendu → faute ;
   `X ≠ tentatives − sauvés` → faute. Sur une ligne de blessures mortelles, le même jugement est
   rendu PAR FIGURINE sur les entrées de `[FNP_ROLLS:]` (cf. `check_fnp_mortal`).

« PRÉSENTE » = figurine de l'escouade cible au Select Targets step de l'activation
(`SelectTargetsFreeze.models`) : c'est l'échéance de 19.04 avec sa dernière clause — « if that
last model was destroyed as the result of an attack, the ability applies until the attacking
unit has resolved all of its attacks » —, et le journal émet les lignes DEAD AVANT les lignes
d'attaque de l'activation, donc les socles VIVANTS à la ligne sous-estimeraient les sources.

24.12 est cité mot pour mot : « Each time a model with this ability would lose a wound, roll
one D6: on an X+, that wound is not lost. » Le jet est donc attaché à LA FIGURINE, et 06.02 en
sélectionne une par blessure mortelle (« Select Model … The selected model loses 1 wound ») :
c'est pourquoi le contrôle des blessures mortelles se rend par figurine et non sur un total.
24.02 justifie le seuil unique : les instances d'une même capacité ne se cumulent pas, une seule
s'applique, et le moteur prend la meilleure.

CE QUI EST DÉLIBÉRÉMENT ÉCARTÉ (abstention, jamais une faute inventée) : segment `Save` sans
base/AP (journal antérieur, `[DEVASTATING WOUNDS]`, `[NOT ALLOCATED]`) ; figurine allouée ou
datasheet inconnue ; caractéristique symbolique au registre ; Waaagh! actif sans clé
`waaagh_invul` dans EFFECTS (journal antérieur) ; figurine dont le journal ne donne pas la
position (la clause positionnelle d'Unbreakable Resolve est alors indécidable — la présence
comme l'absence du 4+ y sont acceptées).
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, Optional, Set, Tuple

from ai.analyzer_core import parse_fnp_rolls
from ai.analyzer_rules import note_rule_usage
from shared.data_validation import require_key

#: `Save R(<base>+ AP<n> → <eff>+)` — jet, Sv de base de la figurine allouée, AP, seuil effectif.
SAVE_SEGMENT_RE = re.compile(r"Save\s+(\d+)\((\d+)\+\s+AP(-?\d+)\s*→\s*(\d+)\+\)")
#: `[FNP:<sauvés>/<seuil>+ ×<tentatives>]` (attaque, `_save_segments`).
FNP_ATTACK_RE = re.compile(r"\[FNP:(\d+)/(\d+)\+ ×(\d+)\]")
#: `SUFFERS <n> Mortal Wounds` — total DÉCLARÉ, borne haute de ce que `[FNP_ROLLS:]` attribue
#: (06.02 : « until either all of them have been inflicted or that unit is destroyed »).
MORTAL_DECLARED_RE = re.compile(r"SUFFERS\s+(\d+)\s+Mortal\s+Wounds")
DMG_RE = re.compile(r"Dmg:(\d+)HP")
_ALLOC_MODEL_RE = re.compile(r"\[ALLOC_MODEL:\s*(\d+#[^\s\]]+)\s*\]")
#: Sentinelle « pas d'InSv » du moteur (`save_threshold`).
NO_INVUL = 7
#: Blessures mortelles de source PSYCHIC (tags `HAZARD_CONTEXT_TAGS`) : Da Jump seulement.
PSYCHIC_MORTAL_TAGS = ("[DA JUMP]",)
#: Tags dont les blessures mortelles NE peuvent PAS tomber dans le sursis 19.04 : aucune
#: allocation de tir ni de combat n'est ouverte quand elles sont infligées (24.15 est un test de
#: hasard, 09.07 un jet de fuite, Da Jump un effet de mouvement). Sur eux seulement, les socles
#: vivants à la ligne donnent exactement les sources que le moteur a lues, et le verdict de
#: SOURCE est rendu. Hold Still and Say Aaargh tombe en pleine allocation de combat, et
#: Exhortation of Rage n'est pas prouvée hors sursis : les deux s'abstiennent.
#:
#: Une EXPRESSION et non une liste de sous-chaînes : le producteur écrit `[HAZARDOUS:<n>]` dès
#: que le compte d'armes 24.15 est connu, et `"[HAZARDOUS]" in ligne` est alors FAUX — le piège
#: exact déjà payé une fois (`_HAZARDOUS_TAG_RE`, `ai/analyzer_core.py`).
SOURCE_DECIDABLE_MORTAL_RE = re.compile(r"\[(?:HAZARDOUS(?::\d+)?|DESPERATE ESCAPE|DA JUMP)\]")

SAVE_COUNTER = "save_threshold_mismatch"
FNP_COUNTER = "fnp_threshold_mismatch"


def _error(state: Any, stats: Dict[str, Any], counter: str, player: int, line: str, detail: str) -> None:
    stats[counter][player] += 1
    first = stats["first_error_lines"][counter]
    if first[player] is None:
        first[player] = {"episode": state.current_episode_num, "line": line.strip(), "detail": detail}


def alloc_model_id(action_desc: str) -> Optional[str]:
    m = _ALLOC_MODEL_RE.search(action_desc)
    return m.group(1) if m else None


def _present_types(state: Any, present_models: Optional[Iterable[str]], target_id: str) -> Optional[Set[str]]:
    """Datasheets des figurines PRÉSENTES (Select Targets step) — None si l'une est inconnue."""
    mids = list(present_models) if present_models is not None else list(
        state.positions_by_model.get(target_id, {})  # get allowed : jamais vue par socle
    )
    if not mids:
        return None
    out: Set[str] = set()
    for mid in mids:
        mtype = state.model_types.get(mid)  # get allowed : socle sans datasheet = abstention
        if mtype is None:
            return None
        out.add(mtype)
    return out


def weapon_is_psychic(config: Any, action_desc: str, weapon_display_name: str) -> bool:
    """`[PSYCHIC]` posé par le moteur (grammaire 3), sinon le profil au registre."""
    if "[PSYCHIC]" in action_desc:
        return True
    carriers = config.weapon_rule_to_weapons.get("PSYCHIC", set())  # get allowed : aucune arme PSYCHIC
    prefix = f"{weapon_display_name} ("
    return any(key.startswith(prefix) for key in carriers)


# ─────────────────────────────────────────────────────────────────────────────
# Seuil de sauvegarde
# ─────────────────────────────────────────────────────────────────────────────


def expected_invul_save(
    state: Any, config: Any, target_id: str, alloc_type: str, present_types: Set[str],
) -> Optional[int]:
    """InSv effective de la figurine allouée (`effective_invul_save` du moteur), ou None si le
    journal ne permet pas de trancher (Waaagh! actif sans `waaagh_invul` dans EFFECTS)."""
    invul = config.unit_invul_save_by_type.get(alloc_type)  # get allowed : caractéristique symbolique
    if invul is None:
        return None
    invul = int(invul)
    for ds in present_types:
        override = config.invul_override_by_type.get(ds)  # get allowed : datasheet sans override
        if override is not None:
            invul = min(invul, int(override))
    target_player = state.unit_player.get(target_id)  # get allowed
    unit_type = state.unit_types.get(target_id)  # get allowed
    if target_player is not None and unit_type in config.rule_to_units.get("waaagh", set()):  # get allowed
        effects = state.active_effects.get(int(target_player), {})  # get allowed : aucun effet
        if effects.get("waaagh") == "on":  # get allowed
            raw = effects.get("waaagh_invul")  # get allowed : journal antérieur à la clé
            if raw is None:
                return None
            invul = min(invul, int(str(raw).rstrip("+")))
    return invul


def check_save_threshold(
    state: Any, config: Any, stats: Dict[str, Any], line: str, action_desc: str,
    target_id: str, attacker_player: int, present_models: Optional[Iterable[str]],
) -> None:
    """Compare le seuil de sauvegarde imprimé au seuil attendu (05.04)."""
    m = SAVE_SEGMENT_RE.search(action_desc)
    if m is None:
        return
    base_logged, ap, eff_logged = int(m.group(2)), int(m.group(3)), int(m.group(4))
    mid = alloc_model_id(action_desc)
    if mid is None:
        return
    alloc_type = state.model_types.get(mid)  # get allowed : socle sans datasheet
    if alloc_type is None:
        return
    armor = config.unit_armor_save_by_type.get(alloc_type)  # get allowed : caractéristique symbolique
    if armor is None:
        return
    present = _present_types(state, present_models, target_id)
    if present is None:
        return
    invul = expected_invul_save(state, config, target_id, alloc_type, present)
    if invul is None:
        return
    note_rule_usage(stats, "PROJ.2.3.save_threshold", attacker_player)
    # Le camp fautif est celui du DÉFENSEUR : c'est SA sauvegarde que le moteur a calculée.
    defender = int(state.unit_player.get(target_id, attacker_player))  # get allowed
    if base_logged != int(armor):
        _error(state, stats, SAVE_COUNTER, defender, line,
               f"Sv de base imprimée {base_logged}+ vs datasheet {alloc_type} {armor}+")
        return
    effective_armor = int(armor) - ap
    expected = invul if invul < NO_INVUL and invul < effective_armor else effective_armor
    if expected != eff_logged:
        _error(state, stats, SAVE_COUNTER, defender, line,
               f"seuil imprimé {eff_logged}+ vs attendu {expected}+ (Sv {armor}+ AP{ap}, InSv {invul}+)")


# ─────────────────────────────────────────────────────────────────────────────
# Feel No Pain
# ─────────────────────────────────────────────────────────────────────────────


def model_near_objective_or_center(state: Any, config: Any, mid: str, target_id: str) -> Optional[bool]:
    """Unbreakable Resolve : le socle recouvre l'aire d'un objectif (14.02) ou est à 6" du
    centre. None = indéterminable (position de la figurine absente du journal).

    Les deux clauses sont mesurées sur l'EMPREINTE du socle, donc exactes à toute résolution.
    Le 6" du centre passe par la primitive du MOTEUR
    (`ranged_edge_distance_to_battlefield_center`, qui porte aussi la définition du centre) avec
    la métrique de portée du RUN (`metric.ranged` de l'entête) : 01.04 mesure « from the closest
    part of that model's base », et c'est le même bord-à-bord que le moteur applique. L'ancre
    seule ne le donnait pas, d'où une abstention à x5 — le socle y déborde de son ancre — qui
    laissait la clause positionnelle injugée à la résolution où tourne le jeu."""
    from ai.analyzer import _get_inches_to_subhex_for_analyzer
    from ai.analyzer_config import get_run_board_dims
    from ai.analyzer_perfig import _model_footprint, model_base
    from ai.analyzer_phases.shoot_handler import _analyzer_ranged_metric
    from engine.combat_utils import ranged_edge_distance_to_battlefield_center
    from engine.hex_utils import Socle

    pos = state.positions_by_model.get(target_id, {}).get(mid)  # get allowed
    if pos is None:
        return None
    col, row = int(pos[0]), int(pos[1])
    # « within that terrain area » : l'EMPREINTE du socle (datasheet de la figurine, à la
    # résolution du run) recouvre l'aire — exact à toute résolution.
    shape, size = model_base(state, config, target_id, mid)
    footprint = _model_footprint(col, row, (shape, size))
    if not footprint.isdisjoint(state.objective_cells):
        return True
    cols, rows = get_run_board_dims()
    distance = ranged_edge_distance_to_battlefield_center(
        Socle(shape, size, col, row, set(footprint)),
        col, row, cols, rows, _analyzer_ranged_metric(config),
    )
    return distance <= 6 * int(_get_inches_to_subhex_for_analyzer())


def expected_fnp_thresholds(
    state: Any, config: Any, target_id: str, present_types: Set[str], mid: Optional[str],
    is_psychic: bool,
) -> Tuple[Set[Optional[int]], bool]:
    """Seuils acceptables → ``(ensemble des seuils attendus possibles, clause positionnelle
    indéterminée)``. `None` dans l'ensemble = « aucun FNP » est une réponse acceptable."""
    thresholds = []
    for ds in present_types:
        th = config.fnp_threshold_by_type.get(ds)  # get allowed : datasheet sans FNP
        if th is not None:
            thresholds.append(int(th))
        th_psy = config.fnp_vs_psychic_by_type.get(ds)  # get allowed
        if th_psy is not None and is_psychic:
            thresholds.append(int(th_psy))
    base: Optional[int] = min(thresholds) if thresholds else None
    accepted: Set[Optional[int]] = {base}
    if mid is not None:
        alloc_type = state.model_types.get(mid)  # get allowed
        th_obj = config.fnp_near_objective_by_type.get(alloc_type) if alloc_type else None  # get allowed
        if th_obj is not None:
            near = model_near_objective_or_center(state, config, mid, target_id)
            with_obj = int(th_obj) if base is None else min(base, int(th_obj))
            if near is True:
                accepted = {with_obj}
            elif near is None:
                accepted = {base, with_obj}
                return accepted, True
    return accepted, False


def check_fnp(
    state: Any, config: Any, stats: Dict[str, Any], line: str, action_desc: str,
    target_id: str, attacker_player: int, weapon_display_name: str,
    present_models: Optional[Iterable[str]],
) -> None:
    """Attaque (tir ou mêlée) : `[FNP:s/t+ ×n]` contre les sources présentes (24.12)."""
    dmg_m = DMG_RE.search(action_desc)
    fnp_m = FNP_ATTACK_RE.search(action_desc)
    if dmg_m is None and fnp_m is None:
        return
    mid = alloc_model_id(action_desc)
    present = _present_types(state, present_models, target_id)
    if present is None:
        return
    is_psychic = weapon_is_psychic(config, action_desc, weapon_display_name)
    accepted, ambiguous = expected_fnp_thresholds(state, config, target_id, present, mid, is_psychic)
    note_rule_usage(stats, "PROJ.2.3.fnp", attacker_player)
    defender = int(state.unit_player.get(target_id, attacker_player))  # get allowed
    dmg = int(dmg_m.group(1)) if dmg_m else 0
    if fnp_m is None:
        # FNP attendu (et sans ambiguïté), dégâts appliqués → le moteur devait jeter. Jugé sans
        # garde de version : la compatibilité avec les journaux antérieurs à la garantie a été
        # abandonnée (décision du 2026-09-19), et une garde qu'aucun journal ne peut plus
        # atteindre est du code mort qui dit le contraire de ce que fait le lecteur.
        if dmg > 0 and None not in accepted and not ambiguous:
            _error(state, stats, FNP_COUNTER, defender, line,
                   f"Dmg:{dmg}HP sans [FNP:] alors qu'un Feel No Pain {min(t for t in accepted if t is not None)}+ "
                   "est porté par une source présente")
        return
    saves, threshold, attempts = int(fnp_m.group(1)), int(fnp_m.group(2)), int(fnp_m.group(3))
    real = {t for t in accepted if t is not None}
    if not real:
        _error(state, stats, FNP_COUNTER, defender, line,
               f"[FNP:{saves}/{threshold}+ ×{attempts}] sans aucun Feel No Pain porté par une source présente")
        return
    if threshold not in real:
        _error(state, stats, FNP_COUNTER, defender, line,
               f"seuil FNP {threshold}+ vs attendu {sorted(real)}")
        return
    if dmg != attempts - saves:
        _error(state, stats, FNP_COUNTER, defender, line,
               f"Dmg:{dmg}HP ≠ tentatives {attempts} − sauvés {saves}")


def check_fnp_mortal(
    state: Any, config: Any, stats: Dict[str, Any], line: str, action_desc: str,
    victim_id: str, victim_player: int,
) -> None:
    """Blessures mortelles : chaque entrée de `[FNP_ROLLS:]` est jugée POUR SA FIGURINE (24.12,
    06.02) — jet manquant alors qu'une source s'applique, jet revendiqué sans aucune source,
    seuil faux, sauvés supérieurs aux blessures, et total attribué différent du total déclaré
    dans les deux sens : au-dessus c'est une blessure inventée, en dessous c'est une séquence
    06.02 interrompue, qui n'est légitime que si l'escouade y est tombée.

    La source PSYCHIC est lue sur le tag (`PSYCHIC_MORTAL_TAGS`), comme pour Da Jump.

    CE QUI EST ÉCARTÉ, et pourquoi. 19.04 dernière clause : « if that last model was destroyed
    as the result of an attack, the ability it was conferring upon the attached unit applies
    until the attacking unit has resolved all of its attacks ». Le moteur l'implémente, et
    n'ouvre ce sursis que pendant une allocation de TIR ou de COMBAT
    (`_attack_allocation_in_progress`, `engine/phase_handlers/shared_utils.py`) : une source
    morte y confère encore son Feel No Pain, ce que les socles vivants à la ligne ne disent pas.
    Les verdicts de SOURCE ne sont donc rendus que sur les tags qui ne peuvent PAS tomber dans
    ce sursis (`SOURCE_DECIDABLE_MORTAL_RE`) ; sur les autres, seuls les comptes sont jugés.
    Abstention explicite, jamais une faute inventée.
    """
    rolls = parse_fnp_rolls(action_desc)
    if rolls is None:
        return  # `SUFFERS 0` : aucune blessure attribuée. L'absence sur une ligne qui en
        # déclare est levée par `net_mortal_wounds`, pas comptée comme une faute de règle.
    note_rule_usage(stats, "PROJ.2.3.fnp", int(victim_player))
    declared = MORTAL_DECLARED_RE.search(action_desc)
    allocated = sum(w for _mid, _s, _t, w in rolls)
    if declared is not None and allocated > int(declared.group(1)):
        _error(state, stats, FNP_COUNTER, int(victim_player), line,
               f"[FNP_ROLLS:] attribue {allocated} blessure(s) pour {declared.group(1)} déclarée(s)")
    elif declared is not None and allocated < int(declared.group(1)):
        # 06.02 : « until either all of them have been inflicted OR THAT UNIT IS DESTROYED ».
        # Attribuer moins que le declare n a donc qu une explication legitime, et elle se lit
        # sur la ligne elle-meme : son `[MODELS:]` est ecrit au FLUSH, donc APRES les morts de
        # la sequence (`models_segment_for_unit`, `engine/action_log_utils.py` — le payload des
        # blessures mortelles ne le pre-capture pas, contrairement aux lignes d attaque). Un
        # survivant qui y figure prouve que l escouade n etait pas detruite, et donc que rien
        # n autorisait l arret. Aucun calcul de PV : les points de vie deja retires ne sont plus
        # comparables a ceux qui restent, et le suivi de l analyzer n a pas a entrer dans le
        # verdict. Ligne sans segment (journal fabrique a la main) : abstention.
        from ai.analyzer_perfig import parse_models_segment

        _by_unit = parse_models_segment(action_desc)
        _survivors = (_by_unit or {}).get(str(victim_id))  # get allowed : segment absent
        if _survivors:
            _error(state, stats, FNP_COUNTER, int(victim_player), line,
                   f"[FNP_ROLLS:] attribue {allocated} blessure(s) pour {declared.group(1)} "
                   f"declaree(s) alors que {len(_survivors)} socle(s) survivent : 06.02 ne "
                   "s arrete avant la fin que sur la destruction de l escouade")
    source_decidable = SOURCE_DECIDABLE_MORTAL_RE.search(action_desc) is not None
    present = _present_types(state, None, victim_id)
    is_psychic = any(tag in action_desc for tag in PSYCHIC_MORTAL_TAGS)
    for mid, saves, threshold, wounds in rolls:
        if saves > wounds:
            _error(state, stats, FNP_COUNTER, int(victim_player), line,
                   f"{mid} : {saves} sauvée(s) pour {wounds} blessure(s) attribuée(s)")
            continue
        if not source_decidable or present is None:
            continue
        accepted, ambiguous = expected_fnp_thresholds(
            state, config, victim_id, present, mid, is_psychic,
        )
        if ambiguous:
            continue
        real = {t for t in accepted if t is not None}
        if threshold is None:
            if real and None not in accepted:
                _error(state, stats, FNP_COUNTER, int(victim_player), line,
                       f"{mid} encaisse {wounds} blessure(s) mortelle(s) sans jet Feel No Pain "
                       f"alors qu'un {min(real)}+ est porté par une source présente")
        elif not real:
            _error(state, stats, FNP_COUNTER, int(victim_player), line,
                   f"{mid} : Feel No Pain {threshold}+ jeté sans aucune source présente qui le porte")
        elif threshold not in real:
            _error(state, stats, FNP_COUNTER, int(victim_player), line,
                   f"{mid} : seuil FNP {threshold}+ vs attendu {sorted(real)}")
