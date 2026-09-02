"""
analyzer_core.py — boucle principale de parse_step_log, extraite de analyzer.py.
Utilise AnalyzerState (state) et AnalyzerConfig (config) pour tout état mutable/config.
"""

import re
from functools import lru_cache
from typing import Dict, Optional, cast

from engine.constants import DRAW_WINNER
from shared.data_validation import require_key, require_present
from ai.analyzer_rules import note_rule_usage

from ai.analyzer_perfig import MODEL_TOKEN_PATTERN, position_is_on_battlefield
from ai.analyzer_state import AnalyzerState
from ai.analyzer_config import AnalyzerConfig
from ai.analyzer_phases.episode_handler import handle_episode_start
from ai.analyzer_phases.shoot_handler import handle_shoot, handle_wait, handle_advance
from ai.analyzer_phases.charge_handler import handle_charge
from ai.analyzer_phases.move_handler import handle_move_or_fled
from ai.analyzer_phases.fight_handler import handle_fight, handle_fight_move


PLAYER_ONE_ID = 1
PLAYER_TWO_ID = 2

# 07.02 — ordre canonique des phases d'un tour de joueur.
_PHASE_ORDER = ['COMMAND', 'MOVE', 'SHOOT', 'CHARGE', 'FIGHT']
_PHASE_RANK: Dict[str, int] = {p: i for i, p in enumerate(_PHASE_ORDER)}


def _check_phase_seq(
    state: AnalyzerState, turn: int, stats: Dict
) -> None:
    """Valide la séquence de phases du tour `turn` par joueur et enregistre les violations 07.02.

    P1 et P2 jouent chacun leur propre séquence dans le même round de bataille : il est
    légal que P1 fasse FIGHT avant que P2 ne fasse CHARGE dans son demi-tour. Chaque
    séquence joueur est validée indépendamment.
    """
    for player_id, seq in state.phase_seq_current_turn.items():
        last_rank = -1
        for p in seq:
            rank = _PHASE_RANK.get(p, -1)
            if rank < 0:
                continue  # Phase inconnue (ex. DEPLOYMENT) — hors contrôle 07.02
            if rank <= last_rank:
                stats['phase_order_violations'] += 1
                if stats['first_error_lines']['phase_order_violation'] is None:
                    stats['first_error_lines']['phase_order_violation'] = {
                        'episode': state.current_episode_num,
                        'turn': turn,
                        'player': player_id,
                        'sequence': list(seq),
                    }
                break
            last_rank = rank


# Seuil (en lignes de log) entre deux appels à `_resync_living_models` avec `removed != {}`
# pour la même unité, en-dessous duquel on considère qu'ils appartiennent à la même activation
# (DEAD-before-SHOOT artifact) et on ACCUMULE les positions. Au-delà, on REMPLACE (nouvelle
# activation cross-turn). Les DEAD-lines d'une même attaque sont espacées de 1 à ~10 lignes
# (interleaving possible entre cibles d'un BLAST) ; deux activations FIGHT séparées ont
# toujours au moins une phase complète entre elles (50+ lignes en pratique).
_DEAD_POS_SAME_ACTIVATION_THRESHOLD = 20



#: Token(s) de capacité OPTIONNELS entre un verbe et son complément (`[WAAAGH!]`, `[FLY]`, …).
#: MÊME fragment pour les verbes de mouvement (`move_line_re`) et d'attaque : c'est la grammaire
#: du journal, pas celle d'un site.
ACTION_ABILITY_TOKENS = r'(?:\s+\[[^\]]+\])*'


# Grammaire d'une ligne de mouvement : `Unit N(c,r) VERBE [TOKEN] from (c,r) to (c,r)`.
# UN SEUL constructeur pour les trois verbes et les cinq sites qui la lisaient. Ces copies
# avaient déjà divergé : deux d'entre elles ignoraient le token optionnel entre le verbe et
# `from`, si bien qu'une ligne portant `[FLY]` n'était aiguillée vers aucun handler — position
# figée, adjacences suivantes mesurées contre un fantôme. Le prochain token n'aura qu'un
# endroit à toucher.
@lru_cache(maxsize=None)
def move_line_re(verb: str, *, with_positions: bool = True) -> "re.Pattern[str]":
    # `ACTION_ABILITY_TOKENS` et non une copie : ce site écrivait `?` (UN token au plus) là où la
    # grammaire d'attaque écrit `*`. Une ligne de move portant deux tokens (`[FLY] [WAAAGH!]` —
    # le second vient d'être ajouté) n'était donc aiguillée nulle part, en silence. Mémoïsé :
    # `analyzer_core.run` appelle ces constructeurs par LIGNE, sur ~90 000 lignes.
    head = r'Unit (\d+)\((\d+),\s*(\d+)\)\s+' + verb + ACTION_ABILITY_TOKENS + r'\s+from'
    if not with_positions:
        return re.compile(head)
    return re.compile(head + r'\s+\((\d+),\s*(\d+)\)\s+to\s+\((\d+),\s*(\d+)\)')


@lru_cache(maxsize=None)
def attack_line_re(verbs: str = r"ATTACKED|FOUGHT", *, with_positions: bool = True) -> "re.Pattern[str]":
    """Grammaire d'une ligne d'attaque : `Unit N(c,r) VERBE [TOKEN…] Unit M(c,r)`.

    ⚠️ UN SEUL constructeur, et il existe pour une raison mesurée. Le token `[WAAAGH!]` a été
    ajouté entre le verbe et la cible ; QUATRE lecteurs portaient cette grammaire à la main, et
    deux seulement ont été corrigés du premier coup. Les deux oubliés étaient les plus coûteux :
    l'aiguillage (`"FOUGHT Unit" in action_desc`) — donc AUCUN contrôle de combat n'était appelé
    sur une ligne Waaagh — et l'application des dégâts (`'fought unit' in …lower()`) — donc la
    cible gardait des PV fantômes et sa mort n'était jamais enregistrée, rouvrant exactement la
    dérive que l'instantané `STATE:` venait de fermer.

    Le mode d'échec est muet dans les deux cas : la ligne n'est pas rejetée, elle est ignorée.
    Le prochain token n'aura qu'un endroit à toucher — comme pour `move_line_re`.
    """
    head = r'Unit (\d+)\((\d+),\s*(\d+)\)\s+(?:' + verbs + r')' + ACTION_ABILITY_TOKENS
    if not with_positions:
        return re.compile(head + r'\s+Unit (\d+)')
    return re.compile(head + r'\s+Unit (\d+)\((\d+),\s*(\d+)\)')


def attack_verb_present(action_desc: str, verbs: str = r"ATTACKED|FOUGHT") -> bool:
    """Cette ligne porte-t-elle un verbe d'attaque suivi d'une cible ? (aiguillage)

    Remplace les tests par SOUS-CHAÎNE (`"FOUGHT Unit" in action_desc`), qui cessaient de matcher
    dès qu'un token s'intercalait — sans que rien ne le signale.
    """
    # Dérivé du MÊME constructeur : une troisième écriture de la grammaire dans le lot qui vient
    # d'en unifier quatre serait le défaut rejoué. Le garde par sous-chaîne évite le scan complet
    # sur les ~80 % de lignes qui ne sont pas des attaques.
    if "FOUGHT" not in action_desc and "ATTACKED" not in action_desc:
        return False
    return attack_line_re(verbs, with_positions=False).search(action_desc) is not None


def move_verb_present(verb: str, action_desc: str) -> bool:
    """Le verbe de mouvement `verb` introduit-il un `from` sur cette ligne ?
    Aiguillage : même grammaire que `move_line_re`, sans les positions."""
    return re.search(r'\b' + verb + r'(?:\s+\[[^\]]+\])?\s+from', action_desc) is not None


_STATE_UNIT_RE = re.compile(r'(\d+)\[([^\]]*)\]')
# Le token per-figurine de la ligne d'état = celui des segments `[MODELS:]`, suffixé des PV.
# Dérivé de `MODEL_TOKEN_PATTERN` et non réécrit : les deux copies avaient déjà divergé, et un
# motif d'état qui ne matche plus fait sortir l'unité de l'instantané — donc la fait passer pour
# morte, en silence.
_STATE_MODEL_RE = re.compile(MODEL_TOKEN_PATTERN + r':(-?\d+)')



#: `[ALLOC_MODEL: 101#3]` — la figurine CIBLE à qui le moteur a alloué cette attaque (05).
#: Le motif de socle est celui des segments `[MODELS:]`, pour la même raison qu'au-dessus : deux
#: écritures d'un même token finissent par diverger, et celle qui ne matche plus est silencieuse.
_ALLOC_MODEL_RE = re.compile(r'\[ALLOC_MODEL:\s*(\d+#[^\s\]]+)\s*\]')


def _alloc_model_from_line(state: AnalyzerState, action_desc: str, line: str) -> Optional[str]:
    """Figurine allouée nommée par la ligne, ou None sur un journal de grammaire 1.

    EXIGIBLE à partir de la grammaire 2 : le producteur promet alors de nommer la figurine sur
    toute attaque parvenue à l'allocation, donc sur toute ligne qui applique des dégâts. Son
    absence n'est plus une donnée manquante, c'est une panne du producteur — et la taire ferait
    retomber l'analyzer sur les deux déductions fausses que ce token vient précisément retirer.

    HORS PROMESSE, et c'est pourquoi ce garde n'est appelé qu'aux deux sites d'attaque : la
    ligne `IMPACTED` de la charge applique ses blessures mortelles au niveau de l'ESCOUADE
    (`_apply_charge_impact` → `update_units_cache_hp`), sans jamais toucher une figurine. Aucune
    figurine allouée n'y existe, côté moteur comme côté journal.
    """
    m = _ALLOC_MODEL_RE.search(action_desc)
    if m:
        return m.group(1)
    if state.log_grammar >= 2:
        raise ValueError(
            f"ligne {state.line_number}: journal `Log grammar: {state.log_grammar}` — une "
            "attaque applique des dégâts sans segment `[ALLOC_MODEL:]`. Le producteur "
            "(`ai/step_logger`, via `_resolve_one_manual_wound`) garantit ce segment sur toute "
            "attaque parvenue à l'allocation ; son absence est une panne de la chaîne "
            f"moteur→journal, pas un vieux format.\n  {line.strip()}"
        )
    return None


_EFFECTS_PLAYER_RE = re.compile(r'P(\d+)\s+([^|]*)')
_RT_UNIT_ID_RE = re.compile(r'Unit\s+(\d+)')
_HAZARDOUS_TAG_RE = re.compile(r'\[HAZARDOUS(?::\d+)?\]')
_HAZARDOUS_SUFFERS_RE = re.compile(r'SUFFERS\s+(\d+)\s+Mortal\s+Wounds\s+\[HAZARDOUS(?::\d+)?\]')


def _parse_effects_snapshot(payload: str) -> "Dict[int, Dict[str, str]]":
    """`P1 waaagh=on waaagh_melee_atk=+1 | P2 none` → `{1: {...}, 2: {}}`.

    `none` est écrit par le producteur quand un joueur n'a aucun effet : l'absence est DITE, elle
    ne se confond pas avec une ligne tronquée — et le dict vide qui en résulte remplace bien
    l'état précédent, au lieu de le laisser traîner.
    """
    out: "Dict[int, Dict[str, str]]" = {}
    for m in _EFFECTS_PLAYER_RE.finditer(payload):
        entries: "Dict[str, str]" = {}
        for token in m.group(2).split():
            key, sep, value = token.partition("=")
            if sep:
                entries[key] = value
        out[int(m.group(1))] = entries
    return out



#: Capacités de FACTION repérables dans la ligne d'effets : clé présente ⇒ capacité active.
#: Elles ne figurent dans aucun `UNIT_RULES` de datasheet (c'est le mot-clé de faction qui les
#: donne), donc la table `rule_to_units` de la section 1.7 ne pouvait pas les compter.
_FACTION_ABILITY_KEYS = {"waaagh": "waaagh", "oath_target": "oath_of_moment"}


def _count_faction_activations(state: AnalyzerState, new_effects: "Dict[int, Dict[str, str]]") -> None:
    """Compte une ACTIVATION par passage de l'inactif à l'actif, jamais une ligne.

    L'instantané d'effets se répète à chaque changement d'état du plateau : compter les lignes
    donnerait un nombre qui dépend du nombre de changements, pas du nombre d'usages.
    """
    stats = state.stats
    for player, entries in new_effects.items():
        was = state.active_effects.get(player, {})  # get allowed : premier instantané
        for key, rule_id in _FACTION_ABILITY_KEYS.items():
            if key in entries and key not in was:
                stats['faction_ability_activations'][rule_id][player] += 1


#: 03.03 s'applique à la MISE EN PLACE et à la FIN DE TOUT DÉPLACEMENT (« must be set up and end
#: any kind of move in coherency »). Ces sept verbes sont exactement les lignes qui portent une
#: position d'arrivée par-figurine : les six déplacements de la matrice plus le déploiement. Une
#: ligne de tir ou d'attaque porte aussi `[MODELS:]`, mais elle ne termine aucun déplacement —
#: la contrôler ferait remonter la MÊME formation à chaque salve.
_COHERENCY_LINE_VERBS = (
    " MOVED ", " ADVANCED ", " FLED ", " CHARGED ", " PILED IN ", " CONSOLIDATED ", " DEPLOYED ",
)


def _check_line_coherency(state: AnalyzerState, line: str) -> None:
    """03.03 Coherency — verdict sur les socles d'ARRIVÉE de cette ligne, si elle en porte.

    Trou identifié de longue date (V11 T6-i) : la donnée était là — `[MODELS:]` porte toutes les
    positions — et rien ne la lisait. Le moteur purge les figurines incohérentes en fin de tour
    (`end_of_turn_regain_coherency_all_squads`) ; personne ne vérifiait que les formations
    journalisées respectaient la règle À CHAQUE FIN DE DÉPLACEMENT, qui est ce que 03.03 exige.

    Une ligne = au plus UNE faute par unité, même si trois de ses figurines sont hors cohérence :
    c'est la FORMATION qui est fautive, et compter par figurine ferait dépendre la gravité de la
    taille de l'escouade.
    """
    from ai.analyzer_perfig import _unit_base, squad_coherency_offenders
    from ai.analyzer_config import get_run_rule_optional

    if not state.current_line_models:
        return
    upper = line.upper()
    if not any(verb in upper for verb in _COHERENCY_LINE_VERBS):
        return
    # Clés absentes = journal antérieur au tracking de cohérence (check sauté, pas d'erreur).
    _coh = get_run_rule_optional("cohesion.model_subhex")
    _coh_max = get_run_rule_optional("cohesion.global_subhex")
    _min_nb = get_run_rule_optional("cohesion.min_neighbors")
    if _coh is None or _coh_max is None or _min_nb is None:
        return
    coh = int(_coh)
    coh_max = int(_coh_max)
    min_neighbors = int(_min_nb)
    stats = state.stats
    for unit_id, models in state.current_line_models.items():
        if unit_id not in state.unit_player:
            continue
        offenders = squad_coherency_offenders(
            models, _unit_base(state.unit_base, unit_id), coh, coh_max, min_neighbors
        )
        player = int(require_key(state.unit_player, unit_id))
        # 03.03 JUGÉE — mais seulement si la règle GOUVERNE cette escouade : « a unit that
        # contains more than one model ». Compter une escouade à un socle gonflerait le nombre
        # d'exercices d'occasions où il n'y avait rien à juger, et masquerait le seul cas qui
        # mérite l'alerte : un roster sans aucune escouade multi-figurines, où la cohérence n'est
        # jamais mise à l'épreuve. Posé avant le `continue`, sinon seules les formations FAUTIVES
        # compteraient et une section sans faute afficherait « jamais exercée ».
        if len(models) > 1:
            note_rule_usage(stats, "03.03", player)
        if not offenders:
            continue
        stats['squad_coherency_violations'][player] += 1
        first = stats['first_error_lines']['squad_coherency_violations']
        if first[player] is None:
            first[player] = {
                'episode': state.current_episode_num,
                'line': line.strip(),
                'detail': f"socles hors cohérence : {' '.join(offenders)}",
            }


def _model_full_hp(state: AnalyzerState, config: AnalyzerConfig, mid: str, squad_hp_max: int) -> int:
    """PV pleins de LA figurine ``mid`` — sa datasheet, pas celle de l'escouade.

    ``[MODEL_TYPES:]`` absent pour ce socle (journal antérieur à cette clé d'entête) → PV de
    l'escouade. C'est l'ancien comportement, conservé pour rester capable d'analyser les vieux
    journaux : donnée absente, jamais une composition supposée. La datasheet inconnue du
    registry, elle, LÈVE — c'est une incohérence log/registry, pas une donnée manquante.
    """
    mtype = state.model_types.get(mid)  # get allowed : cf. docstring
    if mtype is None:
        return int(squad_hp_max)
    return int(require_key(require_key(config.unit_registry.units, mtype), "HP_MAX"))


def _model_is_character(config: AnalyzerConfig, mtype: Optional[str]) -> bool:
    """CHARACTER au sens ALLOCATION (06.02) : rôle ``support`` ou ``leader``.

    Même dérivation que le moteur (``_derive_model_role`` / ``_is_character_role`` sur les
    ``UNIT_RULES``), importée plutôt que recopiée : l'ordre d'allocation est une règle, et une
    copie locale la figerait au jour de l'écriture.
    """
    if mtype is None:
        return False
    from engine.phase_handlers.shared_utils import _derive_model_role, _is_character_role

    unit_data = require_key(config.unit_registry.units, mtype)
    return _is_character_role(_derive_model_role(require_key(unit_data, "UNIT_RULES")))


def _ordered_living_mids(
    state: AnalyzerState, config: AnalyzerConfig, unit_id: str
) -> "list[str]":
    """Socles vivants de l'escouade, dans l'ordre où ils encaisseront les pertes (06.02).

    Non-CHARACTER d'abord, CHARACTER en dernier — ce que fait ``select_eligible_models`` côté
    moteur, et ce que montre le témoin (l'Ancient et le Captain de l'escouade 105 survivent à
    leurs Intercessors). Tri STABLE : à rôle égal, l'ordre du segment ``[MODELS:]`` est conservé.

    Le PREMIER est la figurine « front », celle qui encaisse — elle n'est donc pas stockée mais
    DÉDUITE, ce qui rend impossible la désynchronisation front/relève de la version précédente.
    """
    return sorted(
        state.unit_model_hp.get(unit_id, {}),  # get allowed : escouade jamais vue
        key=lambda mid: _model_is_character(config, state.model_types.get(mid)),  # get allowed
    )


def _sync_front_hp(state: AnalyzerState, config: AnalyzerConfig, unit_id: str) -> None:
    """Réaligne ``unit_hp[unit_id]`` (miroir scalaire) sur les PV de la figurine front.

    ``unit_hp`` reste l'invariant d'aliveness que lit tout le reste de l'analyzer : présent et
    ``> 0`` ⟺ escouade vivante. Plus aucun socle vivant → l'entrée DISPARAÎT, exactement comme
    quand la dernière figurine tombe sous les dégâts.
    """
    ordered = _ordered_living_mids(state, config, unit_id)
    if not ordered:
        state.unit_hp.pop(unit_id, None)
        state.unit_models_alive[unit_id] = 0
        return
    state.unit_hp[unit_id] = int(state.unit_model_hp[unit_id][ordered[0]])
    state.unit_models_alive[unit_id] = len(ordered)


def _resync_living_models(
    state: AnalyzerState,
    config: AnalyzerConfig,
    unit_id: str,
    mids: "list[str]",
    hp_by_mid: "Optional[Dict[str, int]]" = None,
) -> None:
    """Recale l'EFFECTIF sur les socles réellement vivants, sans réinventer leurs PV.

    ⚠️ DÉFAUT CORRIGÉ ICI. Le segment ``[MODELS:]`` de chaque ligne d'action donne les socles
    vivants mais PAS leurs PV. La version précédente reconstruisait alors la relève à PV pleins :
    une figurine entamée y était SOIGNÉE (mesuré : ``[…, 1, 2, 4]`` → ``[…, 2, 5, 4]``).
    L'escouade 102 survivait ainsi à 4 PV de dégâts pour 4 PV restants, et continuait d'engager
    sa cible — c'est ce qui faisait sonner « tir sur cible engagée » sur un tir parfaitement légal.

    Indexés par socle, les PV connus se conservent : recaler consiste à ne GARDER que les socles
    listés. Un socle listé mais inconnu (première apparition) entre à PV pleins — c'est la seule
    valeur que la donnée autorise, et elle n'écrase rien.

    ``hp_by_mid`` fourni (instantané ``T{n} STATE:``, qui porte les PV par socle) → les PV sont
    ceux du moteur, sans interprétation.
    """
    squad_hp_max = state.unit_hp_squad_max.get(unit_id, 1)  # get allowed : unité jamais vue
    known = state.unit_model_hp.get(unit_id, {})  # get allowed
    if hp_by_mid is not None:
        state.unit_model_hp[unit_id] = {str(m): int(hp) for m, hp in hp_by_mid.items()}
    else:
        state.unit_model_hp[unit_id] = {
            m: int(known[m]) if m in known
            else _model_full_hp(state, config, m, squad_hp_max)
            for m in mids
        }
    # Socles qui étaient connus et ne figurent plus dans le nouveau dict → retirés par ce
    # resync (artifact d'ordonnancement : DEAD line avant la ligne d'attaque correspondante,
    # ou [MODELS:] post-mort). On les mémorise pour que _apply_damage_to_named_model ne les
    # compte pas en alloc_model_unknown : le moteur les avait bien ciblés quand ils étaient
    # vivants, c'est l'ordre de flush qui les a fait disparaître avant le traitement.
    removed = known.keys() - state.unit_model_hp[unit_id].keys()
    if removed:
        state.dead_model_ids_episode.setdefault(unit_id, set()).update(removed)
        # § 1.2 / 1.4 — mémoriser les positions des socles retirés pour corriger le gel du
        # Select Targets step (cf. `freeze_select_targets`). `positions_by_model[unit_id]`
        # contient les positions d'avant la fusion `current_line_models` de la ligne courante :
        # c'est l'état de la ligne N-1, qui est bien celui qu'avait la cible quand le moteur
        # a décidé. Les socles absents de cette carte sont ignorés (position inconnue).
        _cur_pos = state.positions_by_model.get(unit_id, {})  # get allowed
        # Intra-activation (DEAD-before-SHOOT) : plusieurs DEAD-lines consécutives pour la même
        # attaque doivent s'ACCUMULER (chaque ligne ne retire qu'un socle). Cross-activation
        # (deux FIGHT séparés sans MOVE/freeze entre-deux) : la deuxième série doit REMPLACER
        # la première pour ne pas réinjecter des positions périmées dans freeze_select_targets.
        # Heuristique : si la dernière écriture pour cette unité date de plus de
        # _DEAD_POS_SAME_ACTIVATION_THRESHOLD lignes, c'est une nouvelle activation.
        _last_line = state.dead_model_positions_episode_line.get(unit_id, -_DEAD_POS_SAME_ACTIVATION_THRESHOLD - 1)
        if state.line_number - _last_line > _DEAD_POS_SAME_ACTIVATION_THRESHOLD:
            state.dead_model_positions_episode[unit_id] = {}
        _dead_pos = state.dead_model_positions_episode.setdefault(unit_id, {})
        for _mid in removed:
            _p = _cur_pos.get(_mid)  # get allowed
            if _p is not None:
                _dead_pos[_mid] = _p
        state.dead_model_positions_episode_line[unit_id] = state.line_number
    else:
        # Aucune mort nouvelle : l'unité vient de bouger / attendre avec tous ses socles intacts.
        # Les positions accumulées dans dead_model_positions_episode proviennent d'activations
        # précédentes et sont périmées — elles provoqueraient des faux engagements dans
        # freeze_select_targets si elles n'étaient pas purgées ici.
        state.dead_model_positions_episode.pop(unit_id, None)
        state.dead_model_positions_episode_line.pop(unit_id, None)
    _sync_front_hp(state, config, unit_id)


def _apply_state_snapshot(state: AnalyzerState, config: AnalyzerConfig, payload: str) -> None:
    """Recale l'état reconstruit sur l'instantané du moteur, APRÈS avoir compté les écarts.

    Trois écarts sont comptés séparément, parce qu'ils n'ont pas la même cause :
      - `dead_missed`   : l'analyzer croyait l'unité vivante, le moteur ne la voit plus. C'est
                          le fantôme — une mort dont aucune ligne ne parlait.
      - `alive_missed`  : l'inverse — l'analyzer a tué une unité que le moteur garde. C'est une
                          sur-attribution de dégâts (ou une résurrection ratée).
      - `pos_mismatch`  : une figurine n'est pas là où l'analyzer la croyait — un déplacement
                          non journalisé (c'est ainsi que le pile-in muet se manifestait).

    Le recalage lui-même est délibérément TOTAL : positions, altitudes, PV, effectif. Corriger à
    moitié laisserait deux sources en désaccord dans le même état, ce qui est pire que l'une ou
    l'autre. Ce qui n'est PAS recalé : `unit_positions` (l'ancre d'escouade), que l'instantané ne
    porte pas — les lignes d'action la resynchronisent déjà, et l'inventer depuis une figurine
    fabriquerait un troisième point de vue.
    """
    stats = state.stats
    seen_units = set()
    for unit_match in _STATE_UNIT_RE.finditer(payload):
        uid = unit_match.group(1)
        models = {}
        heights = {}
        hps = []
        hp_by_mid: Dict[str, int] = {}
        for m in _STATE_MODEL_RE.finditer(unit_match.group(2)):
            mid = m.group(1)
            models[mid] = (int(m.group(2)), int(m.group(3)))
            hp_by_mid[mid] = int(m.group(5))
            # `z` optionnel dans la grammaire partagée (journaux antérieurs au 3D) : 0.0 = sol,
            # même convention que `parse_models_and_heights`.
            heights[mid] = float(m.group(4)) if m.group(4) is not None else 0.0
            hps.append(int(m.group(5)))
        if not models:
            continue
        seen_units.add(uid)

        if state.unit_hp.get(uid, 0) <= 0:  # get allowed : absente == inconnue == pas vivante
            stats['state_resync']['alive_missed'] += 1
        known = state.positions_by_model.get(uid)  # get allowed : unité jamais vue par socle
        if known:
            for mid, pos in models.items():
                if mid in known and known[mid] != pos:
                    stats['state_resync']['pos_mismatch'] += 1

        state.positions_by_model[uid] = models
        state.heights_by_model[uid] = heights
        # PV PAR SOCLE, pris TELS QUELS dans l'instantané : c'est la seule source qui les donne
        # nommément. `unit_hp` (miroir scalaire) et l'effectif en découlent — plus de `max(hps)`
        # choisi à part, donc plus de front et de relève qui décrivent des états différents.
        _resync_living_models(state, config, uid, list(models), hp_by_mid)
        state.dead_units_current_episode.discard(uid)
        state.models_invalidated.discard(uid)

    # Unités que l'analyzer croit vivantes et que le moteur ne voit plus : c'est le fantôme.
    # HORS TABLE ≠ MORTE. Deux cas légitimes d'absence dans l'instantané moteur :
    #   - aucun segment [MODELS:] encore reçu (réserves jamais déployées, positions_by_model vide)
    #   - tous les socles connus portent la sentinelle (-1,-1) (réserves stratégiques 20.01)
    # Dans les deux cas, l'unité est HORS TABLE — pas morte. La tuer ici la ferait « ressusciter »
    # à son ingress move, et un compteur qui sonne sur les réserves finit par être ignoré.
    for uid in [u for u, hp in state.unit_hp.items() if hp > 0 and u not in seen_units]:
        known_models = state.positions_by_model.get(uid)  # get allowed
        if not known_models or not any(position_is_on_battlefield(pos) for pos in known_models.values()):
            continue
        stats['state_resync']['dead_missed'] += 1
        state.unit_hp[uid] = 0
        state.unit_models_alive[uid] = 0
        state.positions_by_model.pop(uid, None)
        state.dead_units_current_episode.add(uid)
        if state.last_phase in {'MOVE', 'SHOOT', 'CHARGE', 'FIGHT'}:
            state.unit_deaths.append((state.episode_turn, state.last_phase, uid, state.line_number))


def run(state: AnalyzerState, config: AnalyzerConfig, filepath: str) -> None:
    """Execute the main parsing loop. Modifies state.stats in-place."""
    from ai.analyzer import (
        _apply_damage_and_handle_death,
        _track_unit_reappearance,
        _position_cache_set,
        _position_cache_remove,
        _get_unit_hp_value,
        _track_action_phase_accuracy,
        _debug_log,
        is_within_engine_engagement_zone,
        _get_engagement_zone_for_analyzer,
        is_adjacent,
        _build_move_bfs_blockers,
        _build_enemy_adjacent_hexes,
        _per_model_move_violation,
        _get_inches_to_subhex_for_analyzer,
        has_line_of_sight,
        parse_timestamp_to_seconds,
    )

    stats = state.stats
    unit_id: Optional[str] = None  # may be set from unit_start or deploy lines

    from ai.analyzer_perfig import (
        parse_models_and_heights,
        parse_target_models_segment,
        surviving_start_models,
    )

    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            state.line_number += 1
            # Segment per-figurine [MODELS:] : socles vivants de l'unité qui agit sur
            # CETTE ligne. On le stocke dans current_line_models (positions_by_model garde
            # l'état précédent pour les contrôles de move per-socle) puis on fusionne en fin
            # de traitement de la ligne. Aliveness pilotée par ce segment (résurrection des
            # unités faussement tuées par le modèle d'ancre 1-HP : cf. Class C engagement).
            # Fusionner d'abord les socles de la LIGNE PRÉCÉDENTE dans l'état persistant :
            # positions_by_model reflète alors tout jusqu'à la ligne N-1 (= positions
            # d'ORIGINE per-socle pour le contrôle de move de la ligne N), tandis que
            # current_line_models portera les positions de DESTINATION de la ligne N.
            for _muid, _mmodels in state.current_line_models.items():
                state.positions_by_model[_muid] = _mmodels
                state.models_invalidated.discard(_muid)
            # Socles de la CIBLE, même rythme et même autorité que ceux de l'unité qui agit.
            # Sans eux, toute unité ayant perdu une figurine était réduite à SON ANCRE pour tous
            # les contrôles géométriques (`_apply_damage_and_handle_death` purge ses socles :
            # le journal ne dit pas laquelle tombe). Or `[TARGET_MODELS:]` dit qui RESTE, et il
            # est écrit sur la dernière ligne visant cette cible, donc après résolution.
            # Effet mesuré sur le run du 2026-08-11 (E123 T4) : le fall-back de l'unité 105
            # partait à 1 hex du socle survivant `1#5`, dans une zone d'engagement de 2 — donc
            # d'un engagement bien réel — et l'analyzer, qui ne voyait que l'ancre ennemie à
            # 3 hex, le comptait « fall-back sans engagement ».
            for _tuid, _tmodels in state.current_line_target_models.items():
                state.positions_by_model[_tuid] = _tmodels
                state.models_invalidated.discard(_tuid)
            # Altitudes : MÊME décalage d'une ligne que les positions. `heights_by_model` porte
            # l'état d'ORIGINE (jusqu'à la ligne N-1), qu'exigent les contrôles mesurés à la
            # position de DÉPART ; `current_line_heights` porte l'arrivée de la ligne N.
            for _muid, _mheights in state.current_line_heights.items():
                state.heights_by_model[_muid] = _mheights
            _line_models, _line_heights = parse_models_and_heights(line)
            state.current_line_models = _line_models or {}
            state.current_line_heights = _line_heights or {}
            # Socles TUÉS et pas encore retirés — appliqués à la FIN DE L'ACTIVATION, c'est-à-dire
            # dès qu'une AUTRE unité agit. Ni plus tôt, ni plus tard, et les deux bornes ont été
            # payées :
            #
            #  - plus tôt (à la ligne suivante) : les jets SUIVANTS de la même salve se retrouvent
            #    jugés sur les survivants des précédents. Mesuré le 2026-08-12 (E44) — un Onslaught
            #    Gatling Cannon vise une escouade à 22 hex, tue les six figurines les plus proches,
            #    et ses derniers jets ressortent « hors portée », les survivantes étant à 25-27
            #    pour une arme de 24. La portée se juge au Select Targets, une fois par activation.
            #  - plus tard (jamais, en laissant `[TARGET_MODELS:]` seul trancher) : une mort qui
            #    n'émet AUCUN segment de survivants — blessures mortelles, retrait de cohérence —
            #    laisserait la figurine debout jusqu'à la prochaine action de son escouade.
            #
            # Le moteur applique la même règle à son propre journal : il diffère `[TARGET_MODELS:]`
            # au dernier jet parce que « les pertes se retirent APRÈS résolution de toutes les
            # attaques » (`w40k_core`). Ce bloc en est le miroir côté lecteur.
            if state.pending_model_removals and state.current_line_models:
                if state.pending_removals_actor not in state.current_line_models:
                    for _duid, _dmids in state.pending_model_removals.items():
                        _known_models = state.positions_by_model.get(_duid)  # get allowed
                        if _known_models is None:
                            continue
                        for _dmid in _dmids:
                            _known_models.pop(_dmid, None)
                        if not _known_models:
                            state.positions_by_model.pop(_duid, None)
                    state.pending_model_removals = {}
                    state.pending_removals_actor = None
            # `[TARGET_MODELS:]` ne nomme qu'une cible, mais ses socles sont groupés par
            # préfixe `<unit_id>#` comme partout ailleurs : aucune hypothèse sur l'unité.
            state.current_line_target_models = {}
            _target_models = parse_target_models_segment(line)
            if _target_models:
                for _tmid, _tpos in _target_models.items():
                    _tuid = _tmid.split("#", 1)[0]
                    state.current_line_target_models.setdefault(_tuid, {})[_tmid] = _tpos
            _check_line_coherency(state, line)
            if state.current_line_models:
                for _uid, _models in state.current_line_models.items():
                    if not _models:
                        continue
                    # L'unité a des socles vivants sur le plateau -> elle est vivante.
                    # Réparer l'incohérence unit_positions/unit_hp créée par une "mort"
                    # d'ancre (HP_MAX squad = 1) alors que l'escouade a encore des figurines.
                    if _uid in state.unit_player:
                        # [MODELS:] = source de vérité des socles VIVANTS de _uid : effectif,
                        # PV par socle et miroir scalaire sont recalés d'un seul geste, sur la
                        # même source. Les PV déjà connus sont CONSERVÉS — c'est la correction
                        # centrale (cf. `_resync_living_models`).
                        _resync_living_models(state, config, _uid, list(_models))
                        if _uid in state.unit_hp:
                            # L'escouade a des socles vivants : elle n'est pas détruite, même si
                            # l'analyzer l'avait retirée à tort (incohérence connue, réparée par
                            # le recalage ci-dessus).
                            state.dead_units_current_episode.discard(_uid)
                        # Restaurer l'ancre si elle a été purgée par la fausse mort d'ancre :
                        # les handlers la resynchronisent ensuite depuis l'ancre loguée.
                        if _uid not in state.unit_positions:
                            _first_pos = next(iter(_models.values()))
                            _position_cache_set(state.unit_positions, _uid, _first_pos[0], _first_pos[1])

            # Episode start
            if '=== EPISODE' in line and 'START ===' in line:
                handle_episode_start(state, config, line)
                continue

            # Skip header lines
            if line.startswith('===') or line.startswith('AI_TURN') or line.startswith('STEP') or \
               line.startswith('NO STEP') or line.startswith('FAILED') or not line.strip():
                continue

            # Parse scenario
            scenario_match = re.search(r'Scenario: (.+)$', line)
            if scenario_match:
                state.current_scenario = scenario_match.group(1).strip()
                continue

            # Siège de l'agent pour CET épisode. Aucun défaut : un journal sans `AGENT_PLAYER=`
            # est antérieur au format, et deviner « 1 » est exactement l'erreur qu'on ferme
            # (cf. `AnalyzerState.current_agent_player`). L'absence est traitée à l'usage, au
            # moment d'attribuer une victoire — là où elle peut être signalée avec l'épisode.
            # Garde par sous-chaîne : ce motif n'existe qu'UNE fois par épisode, mais le scan
            # tournait sur les ~90 000 lignes d'action d'un journal (mesuré : 4,3 µs le scan
            # contre 0,085 µs le test d'appartenance).
            agent_player_match = (
                re.search(r'\bAGENT_PLAYER=(\d+)\b', line) if 'AGENT_PLAYER=' in line else None
            )
            if agent_player_match:
                state.current_agent_player = int(agent_player_match.group(1))
                continue

            # Instantané 14.02 écrit par le MOTEUR (cf. Documentation/Chantiers/Replay.md
            # §2.3) : SOURCE DE VÉRITÉ des points de victoire et du contrôle d'objectif.
            #   [hh:mm:ss] T{tour} OBJECTIVE CONTROL: VP1=… VP2=… CP1=… CP2=… ZONES=…
            # Ne matche PAS le récapitulatif de fin d'épisode ([ts] OBJECTIVE CONTROL:
            # Obj{id}:P1_OC=…), qui n'a ni T{tour} ni VP1= — cf. la même distinction dans
            # replayParser.ts. Les VP écrasent (et non accumulent) : le moteur journalise un
            # TOTAL courant, pas un delta.
            # ⚠️ `CP1=/CP2=` (08.02) est un groupe OPTIONNEL, exactement comme dans
            # `replayParser.ts` : ce champ est apparu le 2026-08-04 entre les VP et `ZONES=`.
            # Sans l'optionalité, ce motif cesserait de matcher les journaux ANTÉRIEURS et
            # l'analyzer les déclarerait sans instantané — et sans l'ancrage `ZONES=`, il
            # cesserait de matcher les journaux POSTÉRIEURS. Les deux parseurs de cette ligne
            # (celui-ci et celui du replay) doivent bouger ensemble : c'est le même format.
            objective_control_match = re.search(
                r'\bT(\d+) OBJECTIVE CONTROL: VP1=(-?\d+) VP2=(-?\d+)'
                r'(?: CP1=(-?\d+) CP2=(-?\d+))? ZONES=(.*)$',
                line,
            )
            if objective_control_match:
                state.episode_victory_points[PLAYER_ONE_ID] = int(objective_control_match.group(2))
                state.episode_victory_points[PLAYER_TWO_ID] = int(objective_control_match.group(3))
                state.objective_control_seen = True
                # L18 — champs optionnels Mthd/OC1/OC2 dans chaque entrée de zone.
                # Format : "{nom}:Ctrl={c}[:Mthd={m}][:OC1={n}][:OC2={n}]" séparés par espaces.
                _zones_str = objective_control_match.group(6).strip()
                for _zone_token in _zones_str.split():
                    _mthd_m = re.search(r':Mthd=(\w+)', _zone_token)
                    _oc1_m = re.search(r':OC1=(-?\d+)', _zone_token)
                    _oc2_m = re.search(r':OC2=(-?\d+)', _zone_token)
                    if _mthd_m and state.objective_control_method is None:
                        state.objective_control_method = _mthd_m.group(1)
                    if _oc1_m and _oc2_m:
                        _zone_name = _zone_token.split(':')[0]
                        state.objective_oc_per_zone[_zone_name] = (
                            int(_oc1_m.group(1)), int(_oc2_m.group(1))
                        )
                continue

            # ── Instantané d'ÉTAT du moteur (une ligne par tour) : POINT DE RECALAGE ──────────
            #   [hh:mm:ss] T{tour} STATE: <uid>[<mid>@(col,row,z<h>):<pv> ...] ...
            # L'analyzer reconstruit l'état par ACCUMULATION (PV initial moins chaque `Dmg:`,
            # position initiale plus chaque déplacement) et n'avait AUCUN moyen de se corriger.
            # Mesuré sur le run du 2026-08-08 : 546 lignes portent une sauvegarde ratée SANS
            # segment `Dmg:` (blessure écartée faute d'allocataire, la cible étant morte en cours
            # de lot) — la mort n'était donc jamais vue, et 76 « action sur une unité morte »
            # suivaient, mesurées contre des fantômes.
            # L'écart entre l'état reconstruit et celui-ci est COMPTÉ avant d'être corrigé : une
            # correction muette ferait disparaître le symptôme sans jamais signaler sa cause, et
            # le prochain effet non journalisé passerait inaperçu.
            # Même garde, même raison : 60 lignes d'état pour 90 000 lignes scannées. Le tour
            # n'est pas capturé — `_apply_state_snapshot` ne le lit pas.
            state_snapshot_match = (
                re.search(r'\bT\d+ STATE: (.*)$', line) if ' STATE: ' in line else None
            )
            if state_snapshot_match:
                _apply_state_snapshot(state, config, state_snapshot_match.group(1))
                continue

            # ── Effets de règle EN VIGUEUR (`T{tour} EFFECTS: P1 … | P2 …`) ─────────────────
            # Une capacité d'ARMÉE (Waaagh! 24, Oath of Moment 08.04) vaut pour un joueur pendant
            # un tour. Elle était re-dérivée par expression régulière sur CHAQUE ligne d'attaque,
            # et son effet ré-encodé ici en dur — deux définitions d'une même règle. La ligne
            # porte désormais la contribution appliquée par le moteur ; on la lit, on ne la
            # redevine pas. Garde par sous-chaîne, même raison que les deux motifs ci-dessus.
            effects_match = (
                re.search(r'\bT\d+ EFFECTS: (.*)$', line) if ' EFFECTS: ' in line else None
            )
            if effects_match:
                _new_effects = _parse_effects_snapshot(effects_match.group(1))
                _count_faction_activations(state, _new_effects)
                state.active_effects = _new_effects
                continue

            # Parse walls
            wall_match = re.search(r'Walls: (.+)$', line)
            if wall_match:
                wall_str = wall_match.group(1).strip()
                if wall_str != 'none':
                    for coord_match in re.finditer(r'\((\d+),(\d+)\)', wall_str):
                        col, row = int(coord_match.group(1)), int(coord_match.group(2))
                        state.wall_hexes.add((col, row))
                continue

            # Ligne `Objectives:` : elle ne sert plus qu'à savoir si la partie DÉCLARE des
            # objectifs. Le bloc qui vivait ici reconstruisait `state.objective_hexes` (zone →
            # hexes) pour resommer l'OC à chaque action ; ce calcul est supprimé — il sommait par
            # ANCRE d'escouade là où le moteur somme par empreinte de socle (14.02), ignorait le
            # battle-shock (01.07) et évaluait à un moment qui n'est pas une frontière de phase.
            # Le contrôle et les points de victoire sont désormais LUS de la ligne
            # `T{tour} OBJECTIVE CONTROL:` que le moteur journalise (Replay.md §2.3).
            # Il emportait avec lui l'appariement nom → id positionnel
            # (`_get_objective_name_to_id_map`, supprimé) : plus rien n'a besoin d'un id d'objectif
            # côté analyzer, seul l'état moteur compte.
            objectives_match = re.search(r'Objectives:\s*(.+)$', line)
            if objectives_match:
                objectives_payload = objectives_match.group(1).strip()
                if not objectives_payload:
                    raise ValueError(
                        f"Objectives line missing payload in episode {state.current_episode_num}: {line.strip()[:200]}"
                    )
                state.objectives_declared = objectives_payload != 'none'
                continue

            # Ligne `Attached: lid→bid` de l'entête d'épisode (règle 19.01 : personnage attaché).
            # Arrive AVANT les lignes Starting position : unit_types n'est pas encore peuplé.
            # On stocke la paire dans state.leader_bodyguard_pairs, consommée dans unit_start_match.
            if 'Attached:' in line:
                attached_match = re.search(r'Attached:\s*(\d+)→(\d+)', line)
                if attached_match:
                    state.leader_bodyguard_pairs[attached_match.group(1)] = attached_match.group(2)
                continue

            # Parse unit starting positions
            unit_start_match = re.match(r'.*Unit (\d+) \((\w+)\) P(\d+): Starting position \((-?\d+),\s*(-?\d+)\)', line)
            if unit_start_match:
                unit_id = str(unit_start_match.group(1))
                unit_type = unit_start_match.group(2)
                player = int(unit_start_match.group(3))
                col = int(unit_start_match.group(4))
                row = int(unit_start_match.group(5))
                
                # CRITICAL: Get HP_MAX from registry (REAL HP, not guessed)
                unit_data = require_key(config.unit_registry.units, unit_type)
                hp_max = require_key(unit_data, "HP_MAX")
                _debug_log(f"[ANALYZER] Unit {unit_id} ({unit_type}) HP_MAX={hp_max} from registry")
                unit_move_value = require_key(unit_data, "MOVE")
                # MODEL_HEIGHT : borne haute de l'intervalle vertical (§03.04). Lue au MÊME
                # endroit que HP_MAX/MOVE — le registry, pas le log : c'est une stat d'unité
                # constante, la journaliser par action la dupliquerait sans rien apporter.
                state.unit_model_height[unit_id] = float(require_key(unit_data, "MODEL_HEIGHT"))
                
                # Modèle HP par-figurine : unit_hp = PV de la figurine front (= HP_MAX à plein),
                # nb de figurines vivantes compté sur le segment [MODELS:] de la ligne de départ
                # (source de vérité moteur), PV_MAX/figurine mémorisé pour reset à chaque perte.
                deploy_models = state.current_line_models.get(unit_id)
                n_models = len(deploy_models) if deploy_models else 1
                state.unit_hp[unit_id] = hp_max
                state.unit_models_alive[unit_id] = n_models
                state.unit_hp_squad_max[unit_id] = hp_max

                state.unit_player[unit_id] = player
                _position_cache_set(state.unit_positions, unit_id, col, row)
                state.unit_types[unit_id] = unit_type
                stats['unit_types'][unit_id] = unit_type
                require_key(stats, 'unit_types_seen').add(unit_type)

                # 19.01 leader/support : compter l'exercice à la mise en place, là où les paires
                # Attached: ont été stockées. unit_types est maintenant peuplé pour cette unité.
                _unit_rules = config.unit_rules_by_type.get(unit_type, set())
                if unit_id in state.leader_bodyguard_pairs and "leader" in _unit_rules:
                    note_rule_usage(stats, "PROJ.1.9.leader", player)
                if unit_id in state.leader_bodyguard_pairs.values() and "support" in _unit_rules:
                    note_rule_usage(stats, "PROJ.1.9.support", player)
                state.unit_move[unit_id] = unit_move_value * config.inches_to_subhex
                state.positions_at_turn_start[unit_id] = (col, row)
                state.unit_movement_history[unit_id] = [{"position": (col, row)}]
                base_token_match = re.search(r'base=\w+/(?:\d+|\[[^\]]*\])', line)
                if base_token_match:
                    from ai.analyzer_perfig import parse_base_token
                    state.unit_base[unit_id] = parse_base_token(base_token_match.group(0))
                # Datasheet par figurine : écrite UNE fois, dans l'entête (la composition ne
                # change pas en cours de partie — une figurine meurt, elle ne change pas de
                # datasheet). Cf. `AnalyzerState.model_types`.
                model_types_match = re.search(r'\[MODEL_TYPES: ([^\]]+)\]', line)
                if model_types_match:
                    for _pair in model_types_match.group(1).split():
                        _mid, _sep, _mtype = _pair.partition("=")
                        if _sep:
                            state.model_types[_mid] = _mtype
                            # Les datasheets PORTEUSES entrent dans les types vus, au même titre
                            # que celle de l'escouade : c'est `unit_types_seen` qui décide des
                            # paires (règle, arme) que le tableau §1.8 ATTEND. Sans elles, l'arme
                            # d'un sergent ou d'un personnage rattaché (règle 19) n'était ni
                            # attendue ni comptée — donc invisible des deux côtés à la fois.
                            require_key(stats, 'unit_types_seen').add(_mtype)
                # PV PAR SOCLE (cf. `unit_model_hp`). Posés ICI et pas plus haut : ils ont besoin
                # de `[MODEL_TYPES:]`, que la même ligne d'entête vient seulement de fournir.
                # À l'entête, aucune figurine n'est entamée : PV pleins par datasheet.
                #
                # ENTÊTE SANS `[MODELS:]` → une figurine SYNTHÉTIQUE, jamais zéro. C'est le
                # repli mono-figurine déjà appliqué à l'effectif (`n_models … else 1`) : une
                # liste vide voudrait dire « aucun socle vivant », donc escouade détruite, et
                # l'unité naîtrait morte. Les journaux antérieurs au segment `[MODELS:]` en
                # dépendent, et deux tests d'engagement close-quarters l'ont attrapé.
                _seed = list(deploy_models) if deploy_models else [f"{unit_id}#0"]
                _resync_living_models(state, config, unit_id, _seed)
                continue

            # Parse unit deployment positions (authoritative start positions)
            #
            # La PHASE n'est pas contrainte : une mise en place n'a pas lieu qu'au déploiement.
            # L'ingress move des réserves stratégiques (20.04) EST une mise en place, journalisée
            # par le même formateur (`deploy_unit` → « DEPLOYED from (-1,-1) to (c,r) ») mais dans
            # la phase de MOUVEMENT. Épinglée sur `DEPLOYMENT`, cette regex laissait l'escouade
            # arrivée à la sentinelle `(-1,-1)` pour tout le reste de l'épisode — et la ligne ne
            # correspondait à aucune branche d'action ensuite (elles testent `MOVED from`,
            # `ADVANCED`, `CHARGED`, `FLED`) : l'arrivée était donc simplement perdue.
            deploy_match = re.match(
                r'.*E\d+\s+T(\d+)\s+P(\d+)\s+(\w+)\s+:\s+Unit\s+(\d+)\((\d+),\s*(\d+)\)\s+DEPLOYED\s+from\s+\((-?\d+),\s*(-?\d+)\)\s+to\s+\((\d+),\s*(\d+)\)',
                line
            )
            if deploy_match:
                deploy_turn = int(deploy_match.group(1))
                player = int(deploy_match.group(2))
                deploy_phase = deploy_match.group(3)
                unit_id = str(deploy_match.group(4))
                unit_type = state.unit_types.get(unit_id)
                if unit_type is None:
                    raise KeyError(f"Unit {unit_id} missing unit type before deployment parse")
                dest_col = int(deploy_match.group(9))
                dest_row = int(deploy_match.group(10))

                state.unit_player[unit_id] = player
                _position_cache_set(state.unit_positions, unit_id, dest_col, dest_row)
                state.positions_at_turn_start[unit_id] = (dest_col, dest_row)
                if unit_id not in state.unit_movement_history:
                    state.unit_movement_history[unit_id] = []
                # `turn` et `episode` sont PORTÉS, comme sur toute autre entrée d'historique
                # (move, fled, charge, advance, reactive) : les trois détecteurs de collision
                # (`move_handler`, `charge_handler`, `shoot_handler`) exigent ces deux clés pour
                # retenir une unité posée sur l'hexe convoité. Sans elles, une escouade arrivée
                # des réserves ne pouvait figurer dans AUCUNE collision — un chevauchement réel
                # disparaissait du rapport au lieu d'y entrer.
                _deploy_ts = re.search(r'\[(\d+:\d+:\d+)\]', line)
                state.unit_movement_history[unit_id].append({
                    'position': (dest_col, dest_row),
                    'timestamp': _deploy_ts.group(1) if _deploy_ts else None,
                    'action': 'deploy' if deploy_phase == 'DEPLOYMENT' else 'ingress',
                    'turn': deploy_turn,
                    'episode': state.current_episode_num,
                })
                # Seule la phase de DÉPLOIEMENT s'arrête ici. Un ingress (20.04) est une action de
                # la phase de MOUVEMENT — un step gym à part entière (`deploy_unit` n'est pas dans
                # `_STEP_LOG_NON_INCREMENTING_TYPES`) : il doit continuer vers le parseur d'action,
                # qui le compte ET porte les remises à zéro de tour et de phase. L'absorber ici
                # perdait son comptage et pouvait laisser `charged_units_current_fight` de la
                # phase de charge précédente en place quand l'ingress ouvre la phase de move.
                if deploy_phase == 'DEPLOYMENT':
                    continue
                # 20.03 — les réserves stratégiques ne peuvent arriver qu'à partir du round 2.
                if deploy_turn == 1:
                    stats['reserves_too_early'][player] += 1
                    if stats['first_error_lines']['reserves_too_early'][player] is None:
                        stats['first_error_lines']['reserves_too_early'][player] = {'episode': state.current_episode_num, 'line': line.strip()}

            # Episode end
            if 'EPISODE END' in line:
                # 07.02 — valider la séquence du DERNIER tour (pas couverte par le bloc
                # turn-change, qui ne s'exécute que quand un NOUVEAU tour commence).
                if state.last_turn > 0:
                    _check_phase_seq(state, state.last_turn, stats)

                if stats['current_episode_deaths']:
                    stats['death_orders'].append(tuple(stats['current_episode_deaths']))

                # Save turn distribution for this episode
                if state.episode_turn > 0:
                    stats['turns_distribution'][state.episode_turn] += 1
                stats['episode_lengths'].append((state.current_episode_num, state.episode_actions))
                
                # Calculate episode duration from Duration= field (wall-clock from step_logger)
                duration_match = re.search(r'Duration=(\d+(?:\.\d+)?)\s*s?\b', line)
                if not duration_match:
                    raise ValueError(
                        f"Missing Duration= in EPISODE END line for episode {state.current_episode_num}: "
                        f"{line.strip()[:200]}"
                    )
                duration_seconds = float(duration_match.group(1))
                stats['episode_durations'].append((state.current_episode_num, duration_seconds))

                winner_match = re.search(r'Winner=(-?\d+)', line)
                method_match = re.search(r'Method=(\w+)', line)

                if winner_match:
                    winner = int(winner_match.group(1))
                    win_method = method_match.group(1) if method_match else None

                    # SIÈGE de l'agent, jamais déduit. Un journal sans `AGENT_PLAYER=` est
                    # antérieur au format : on demande sa régénération plutôt que de supposer
                    # « agent == P1 », qui est précisément l'erreur fermée ici (même parti que
                    # l'instantané `OBJECTIVE CONTROL` plus bas).
                    if state.current_agent_player is None:
                        raise ValueError(
                            f"Episode {state.current_episode_num} sans 'AGENT_PLAYER=' dans son "
                            f"entête 'Rosters:'. Regenerate step.log: le siège de l'agent est lu "
                            f"dans le journal, il n'est plus supposé être P1 "
                            f"(controlled_player_mode accepte p2 et random)."
                        )
                    agent_seat = state.current_agent_player
                    stats['agent_seat_counts'][agent_seat] += 1

                    if winner == PLAYER_ONE_ID:
                        stats['wins_by_scenario'][state.current_scenario]['p1'] += 1
                    elif winner == PLAYER_TWO_ID:
                        stats['wins_by_scenario'][state.current_scenario]['p2'] += 1
                    elif winner == DRAW_WINNER:
                        stats['wins_by_scenario'][state.current_scenario]['draws'] += 1

                    if winner in (PLAYER_ONE_ID, PLAYER_TWO_ID):
                        seat_key = 'agent' if winner == agent_seat else 'bot'
                        stats['wins_by_scenario'][state.current_scenario][seat_key] += 1
                        if win_method and win_method in stats['win_methods_by_seat'][seat_key]:
                            stats['win_methods_by_seat'][seat_key][win_method] += 1

                    if win_method:
                        if winner in stats['win_methods'] and win_method in stats['win_methods'][winner]:
                            stats['win_methods'][winner][win_method] += 1
                        elif winner == DRAW_WINNER:
                            stats['win_methods'][DRAW_WINNER]['draw'] += 1
                    else:
                        stats['episodes_without_method'].append({
                            'winner': winner,
                            'line': line.strip()[:100]
                        })

                # Points de victoire = ceux du MOTEUR, lus dans le dernier instantané
                # `OBJECTIVE CONTROL` de l'épisode. Le barème (fenêtre de score, cas T5/joueur 2,
                # plafond par tour, conditions) vivait ici en double de
                # `StateManager.apply_primary_objective_scoring` : il est supprimé, le moteur
                # étant seul à décider ce qui est marqué.
                if state.objective_control_seen:
                    stats['victory_points_by_episode'][state.current_episode_num] = {
                        PLAYER_ONE_ID: state.episode_victory_points[PLAYER_ONE_ID],
                        PLAYER_TWO_ID: state.episode_victory_points[PLAYER_TWO_ID],
                    }
                    stats['victory_points_values'][PLAYER_ONE_ID].append(
                        state.episode_victory_points[PLAYER_ONE_ID]
                    )
                    stats['victory_points_values'][PLAYER_TWO_ID].append(
                        state.episode_victory_points[PLAYER_TWO_ID]
                    )
                    # Jumeau au SIÈGE : sans lui, la ligne « P1 » du tableau des points de
                    # victoire mélange les épisodes où l'agent tient P1 et ceux où il tient P2.
                    if state.current_agent_player is not None:
                        _bot_seat = PLAYER_TWO_ID if state.current_agent_player == PLAYER_ONE_ID else PLAYER_ONE_ID
                        stats['victory_points_values_by_seat']['agent'].append(
                            state.episode_victory_points[state.current_agent_player]
                        )
                        stats['victory_points_values_by_seat']['bot'].append(
                            state.episode_victory_points[_bot_seat]
                        )
                elif state.objectives_declared:
                    # Journal antérieur au format : mêmes règles que le replay
                    # (`replayParser.ts`) — on ne devine pas des VP, on demande la régénération.
                    raise ValueError(
                        f"Episode {state.current_episode_num} declares objectives but carries no "
                        f"'T<turn> OBJECTIVE CONTROL:' snapshot. Regenerate step.log: victory "
                        f"points are read from the engine, no longer recomputed by the analyzer."
                    )

                # P2 — tour maximum dépassé.
                if state.episode_turn > 0 and config.max_turns > 0:
                    if state.episode_turn > config.max_turns:
                        stats['game_turn_exceeded_count'] += 1
                        if stats['first_error_lines']['game_turn_exceeded'] is None:
                            stats['first_error_lines']['game_turn_exceeded'] = {
                                'episode': state.current_episode_num,
                                'turn': state.episode_turn,
                                'max_turns': config.max_turns,
                            }

                # P2 — méthode de victoire incohérente avec l'état final reconstruit.
                # Contrôle : si win_method=elimination, le perdant doit avoir 0 unité vivante.
                _winner_for_check: Optional[int] = winner_match and int(winner_match.group(1))
                _method_for_check = (method_match.group(1) if method_match else None) if winner_match else None
                if (
                    _winner_for_check in (PLAYER_ONE_ID, PLAYER_TWO_ID)
                    and _method_for_check == 'elimination'
                ):
                    _loser = PLAYER_TWO_ID if _winner_for_check == PLAYER_ONE_ID else PLAYER_ONE_ID
                    _loser_still_alive = [
                        uid for uid, pl in state.unit_player.items()
                        if int(pl) == _loser
                        and uid not in state.dead_units_current_episode
                        and state.unit_hp.get(uid, 0) > 0  # get allowed : absente == inconnue == pas vivante
                    ]
                    if _loser_still_alive:
                        stats['win_method_mismatch_count'] += 1
                        if stats['first_error_lines']['win_method_mismatch'] is None:
                            stats['first_error_lines']['win_method_mismatch'] = {
                                'episode': state.current_episode_num,
                                'winner': _winner_for_check,
                                'method': _method_for_check,
                                'loser_alive_units': _loser_still_alive[:5],
                            }

                stats['current_episode_deaths'] = []
                stats['wounded_enemies'] = {1: set(), 2: set()}
                state.current_episode = []
                continue

            # Parse action line
            # Support both old format (T\d+) and new format (E\d+ T\d+)
            # STEP marker is optional (removed from logs)
            match = re.match(r'\[.*?\] (?:E\d+ )?T(\d+) P(\d+) (\w+) : (.*?) \[(SUCCESS|FAILED)\](?: \[STEP: (YES|NO)\])?', line)
            if match:
                turn = int(match.group(1))
                player = int(match.group(2))
                phase = match.group(3)
                action_desc = match.group(4)
                is_reactive_move = False
                success = match.group(5) == 'SUCCESS'
                step_marker_present = match.group(6) is not None
                step_inc = match.group(6) == 'YES' if step_marker_present else True
                rule_choice_line_match = re.match(
                    r'Unit (\d+)\((\d+),\s*(\d+)\) chose \[([^\]]+)\]',
                    action_desc,
                    re.IGNORECASE,
                )
                # Attaquant de la ligne (préfixe "Unit N(...)") : sert à attribuer la
                # destruction d'une cible pour distinguer les attaques restantes de la MÊME
                # activation (excess lost) d'un vrai cadavre attaqué par une unité tierce.
                _dmg_actor_match = re.match(r'Unit (\d+)\(', action_desc)
                _dmg_actor_id: str | None = cast(str, _dmg_actor_match.group(1)) if _dmg_actor_match else None

                # Effectifs AVANT les dégâts de cette ligne. [BLAST] 24.05 et [CLEAVE] 24.06
                # comptent les figurines de la cible « in the Select Targets step », donc AVANT
                # que l'activation n'en tue : les dégâts sont appliqués juste en dessous, avant
                # que le handler de tir/combat ne voie la ligne, et la première ligne d'une
                # séquence peut déjà avoir retiré un socle.
                state.models_alive_pre_line = dict(state.unit_models_alive)
                # Jumeaux géométriques du gel ci-dessus, pris au MÊME instant : les contrôles
                # d'engagement (10.06, 04.02, alternance 12.04) se jugent au Select Targets step,
                # et les dégâts appliqués juste en dessous retirent socles, PV et ancre de la
                # cible. Sans ces instantanés, un handler n'a plus AUCUN moyen de savoir où était
                # la cible quand le moteur a décidé (cf. `AnalyzerState.freeze_select_targets`).
                state.unit_hp_pre_line = dict(state.unit_hp)
                state.unit_positions_pre_line = dict(state.unit_positions)
                state.positions_by_model_pre_line = dict(state.positions_by_model)
                # MÊME instant, pour la même raison : `_apply_damage_and_handle_death` ajoute la
                # cible aux blessés (ou l'en retire quand elle meurt) AVANT que le handler ne
                # juge la priorité de ciblage — qui est, elle aussi, une décision du Select
                # Targets step. Cf. `AnalyzerState.freeze_select_targets`.
                state.wounded_enemies_pre_line = {
                    _pl: set(_wounded) for _pl, _wounded in require_key(stats, 'wounded_enemies').items()
                }

                # CRITICAL: Apply damage regardless of STEP marker
                # Non-step lines still contain real attacks/shots and can kill units.
                # If we ignore STEP: NO damage, later rule checks (e.g., adjacency) can produce false positives
                # by treating dead units as alive.
                target_match = re.search(
                    r'\bSHOT(?:\s+\([A-Za-z0-9_ ]+\)|\s+\[[^\]]+\])*'
                    r'(?:\s+\[RAPID(?: |_)?FIRE:(\d+)\])?\s+(?:at\s+)?Unit\s+(\d+)',
                    action_desc,
                    re.IGNORECASE
                )
                if target_match:
                        target_id = target_match.group(2)
                        damage_match = re.search(r'Dmg:(\d+)HP', action_desc)
                        if damage_match:
                            damage = int(damage_match.group(1))
                            # RULE: Shoot at dead unit (target already dead when shot).
                            # Exception 05 Attack sequence : les tirs restants de la MÊME
                            # activation qui a détruit la cible sont des « excess attacks lost »
                            # (même attaquant, même turn/phase) → pas une violation.
                            if damage > 0:
                                target_already_dead = target_id not in state.unit_hp or require_key(state.unit_hp, target_id) <= 0
                                same_activation_kill = state.unit_kill_context.get(target_id) == (_dmg_actor_id, turn, phase)
                                if target_already_dead and not same_activation_kill:
                                    stats['shoot_at_dead_unit'][player] += 1
                                    if stats['first_error_lines']['shoot_at_dead_unit'][player] is None:
                                        stats['first_error_lines']['shoot_at_dead_unit'][player] = {'episode': state.current_episode_num, 'line': line.strip()}
                            _apply_damage_and_handle_death(
                                target_id, _dmg_actor_id, damage, player, turn, phase, state.line_number, state.current_episode_num,
                                line, state.dead_units_current_episode, state.unit_hp, state.unit_models_alive, state.unit_model_hp, lambda _u: _ordered_living_mids(state, config, _u), state.unit_hp_squad_max, state.unit_types, state.unit_positions, state.unit_deaths, state.unit_kill_context, stats,
                                positions_by_model=state.positions_by_model,
                                models_invalidated=state.models_invalidated,
                                alloc_model_id=_alloc_model_from_line(state, action_desc, line),
                                pending_model_removals=state.pending_model_removals,
                                dead_model_ids_episode=state.dead_model_ids_episode,
                            )
                            state.pending_removals_actor = _dmg_actor_id
                # Sauvegarde avant que target_match soit écrasé par la grammaire FOUGHT ci-dessous.
                # 10.02 — marqueur d'activation SHOOT : seuls les SHOT désignent un tir réel ;
                # les FOUGHT qui suivent (arme de mêlée, sur la même ligne d'action) ne comptent pas.
                _is_shot_action = target_match is not None

                # Grammaire PARTAGÉE (`attack_line_re`) : le test par sous-chaîne qui vivait ici
                # cessait de matcher dès qu'un token de capacité s'intercalait — la cible gardait
                # alors des PV fantômes et sa mort n'était jamais enregistrée.
                target_match = (
                    attack_line_re(with_positions=False).search(action_desc)
                    if ("FOUGHT" in action_desc or "ATTACKED" in action_desc) else None
                )
                if target_match:
                    # Groupes de `attack_line_re` : 1=attaquant, 2/3=ses coordonnées, 4=cible.
                    target_id = target_match.group(4)
                    damage_match = re.search(r'Dmg:(\d+)HP', action_desc)
                    if damage_match:
                        damage = int(damage_match.group(1))
                        _apply_damage_and_handle_death(
                            target_id, _dmg_actor_id, damage, player, turn, phase, state.line_number, state.current_episode_num,
                            line, state.dead_units_current_episode, state.unit_hp, state.unit_models_alive, state.unit_model_hp, lambda _u: _ordered_living_mids(state, config, _u), state.unit_hp_squad_max, state.unit_types, state.unit_positions, state.unit_deaths, state.unit_kill_context, stats,
                            positions_by_model=state.positions_by_model,
                            models_invalidated=state.models_invalidated,
                            alloc_model_id=_alloc_model_from_line(state, action_desc, line),
                            pending_model_removals=state.pending_model_removals,
                            dead_model_ids_episode=state.dead_model_ids_episode,
                        )
                        state.pending_removals_actor = _dmg_actor_id

                # CHARGE IMPACT mortal wounds (11.01):
                # "Unit CHARGER(c,r) IMPACTED [ABILITY] Unit TARGET(c,r) - Hit:T+:N(HIT|FAIL) Wound:AUTO Save:NONE[MW] Dmg:ZHP"
                impact_damage_match = re.search(
                    r'Unit\s+(\d+)\(\d+,\d+\)\s+IMPACTED\s+\[[^\]]+\]\s+Unit\s+(\d+)\(\d+,\d+\)\s+-\s+Hit:(\d+)\+:\d+\((?:HIT|FAIL)\)(?:\s+Wound:AUTO\s+Save:NONE\[MW\]\s+Dmg:(\d+)HP)?',
                    action_desc,
                    re.IGNORECASE
                )
                if impact_damage_match:
                    _impact_charger_id = impact_damage_match.group(1)
                    target_id = impact_damage_match.group(2)
                    _impact_threshold = int(impact_damage_match.group(3))
                    damage_group = impact_damage_match.group(4)
                    damage = int(damage_group) if damage_group is not None else 0
                    _impact_player = state.unit_player.get(_impact_charger_id, player)  # get allowed: charger peut être inconnu
                    _impact_charger_type = state.unit_types.get(_impact_charger_id)  # get allowed
                    _impact_rules = config.unit_rules_by_type.get(_impact_charger_type or "", set())
                    if "charge_impact" in _impact_rules:
                        note_rule_usage(stats, "PROJ.1.3.charge_impact", _impact_player)
                        # obs_id=3 → seuil always 4+, dégâts always 1 MW
                        _IMPACT_THRESHOLD_EXPECTED = 4
                        _IMPACT_DAMAGE_EXPECTED = 1
                        if _impact_threshold != _IMPACT_THRESHOLD_EXPECTED:
                            stats['charge_impact_wrong_threshold'][_impact_player] += 1
                        if damage > 0 and damage != _IMPACT_DAMAGE_EXPECTED:
                            stats['charge_impact_wrong_damage'][_impact_player] += 1
                    if damage > 0:
                        _apply_damage_and_handle_death(
                            target_id, _dmg_actor_id, damage, player, turn, phase, state.line_number, state.current_episode_num,
                            line, state.dead_units_current_episode, state.unit_hp, state.unit_models_alive, state.unit_model_hp, lambda _u: _ordered_living_mids(state, config, _u), state.unit_hp_squad_max, state.unit_types, state.unit_positions, state.unit_deaths, state.unit_kill_context, stats,
                                positions_by_model=state.positions_by_model,
                                models_invalidated=state.models_invalidated,
                                dead_model_ids_episode=state.dead_model_ids_episode,
                        )

                if _dmg_actor_match:
                    assert _dmg_actor_id is not None
                    actor_id = _dmg_actor_id
                    _track_unit_reappearance(
                        actor_id,
                        state.unit_hp,
                        state.unit_player,
                        state.dead_units_current_episode,
                        state.revived_units_current_episode,
                        stats,
                        state.current_episode_num,
                        line
                    )
                    if rule_choice_line_match:
                        chosen_unit_id = rule_choice_line_match.group(1)
                        chosen_player = (
                            int(state.unit_player[chosen_unit_id])
                            if chosen_unit_id in state.unit_player
                            else int(player)
                        )
                        chosen_rule_label = rule_choice_line_match.group(4).strip().upper()
                        display_rule_ids = config.display_rule_name_to_ids.get(chosen_rule_label, set())
                        if len(display_rule_ids) != 1:
                            stats['rule_choice_selection_invalid'][chosen_player] += 1
                            if stats['first_error_lines']['rule_choice_selection_invalid'][chosen_player] is None:
                                stats['first_error_lines']['rule_choice_selection_invalid'][chosen_player] = {
                                    'episode': state.current_episode_num,
                                    'line': line.strip()
                                }
                            stats['parse_errors'].append({
                                'episode': state.current_episode_num,
                                'turn': turn,
                                'phase': phase,
                                'line': line.strip(),
                                'error': (
                                    f"Rule choice label '{chosen_rule_label}' is "
                                    f"{'unknown' if len(display_rule_ids) == 0 else 'ambiguous'}"
                                )
                            })
                        else:
                            selected_display_rule_id = next(iter(display_rule_ids))
                            selected_technical_rule_id = config.resolve_rule_id(
                                selected_display_rule_id
                            )
                            chosen_unit_type = require_key(state.unit_types, chosen_unit_id)
                            effect_to_sources_for_unit = config.unit_choice_effect_to_source_rules.get(
                                chosen_unit_type, {}
                            )
                            source_rule_ids = effect_to_sources_for_unit.get(
                                selected_technical_rule_id, set()
                            )
                            if not source_rule_ids:
                                stats['rule_choice_selection_invalid'][chosen_player] += 1
                                if stats['first_error_lines']['rule_choice_selection_invalid'][chosen_player] is None:
                                    stats['first_error_lines']['rule_choice_selection_invalid'][chosen_player] = {
                                        'episode': state.current_episode_num,
                                        'line': line.strip()
                                    }
                                stats['parse_errors'].append({
                                    'episode': state.current_episode_num,
                                    'turn': turn,
                                    'phase': phase,
                                    'line': line.strip(),
                                    'error': (
                                        f"Rule choice '{selected_technical_rule_id}' does not belong to "
                                        f"any choice source for unit type {chosen_unit_type}"
                                    )
                                })
                            else:
                                if chosen_unit_id not in state.selected_choice_by_unit_source:
                                    state.selected_choice_by_unit_source[chosen_unit_id] = {}
                                for source_rule_id in source_rule_ids:
                                    state.selected_choice_by_unit_source[chosen_unit_id][source_rule_id] = (
                                        selected_technical_rule_id
                                    )
                                key = (selected_technical_rule_id, chosen_unit_type)
                                stats['rule_choice_selection_usage'][key][chosen_player] += 1
                    action_desc_upper = action_desc.upper()
                    if not rule_choice_line_match:
                        actor_unit_type = require_key(state.unit_types, actor_id)
                        actor_player = (
                            int(state.unit_player[actor_id]) if actor_id in state.unit_player else int(player)
                        )
                        effect_to_sources_for_unit = config.unit_choice_effect_to_source_rules.get(
                            actor_unit_type, {}
                        )
                        if effect_to_sources_for_unit:
                            bracket_labels = re.findall(r'\[([^\]]+)\]', action_desc)
                            for raw_bracket_label in bracket_labels:
                                normalized_label = raw_bracket_label.strip().upper()
                                candidate_display_rule_ids = config.display_rule_name_to_ids.get(
                                    normalized_label, set()
                                )
                                for candidate_display_rule_id in candidate_display_rule_ids:
                                    candidate_technical_rule_id = config.resolve_rule_id(
                                        candidate_display_rule_id
                                    )
                                    if candidate_technical_rule_id not in effect_to_sources_for_unit:
                                        continue
                                    source_rule_ids = effect_to_sources_for_unit[candidate_technical_rule_id]
                                    selected_sources = state.selected_choice_by_unit_source.get(actor_id, {})  # fallback allowed — acteur sans selection enregistree
                                    has_matching_source = any(
                                        selected_sources.get(source_rule_id) == candidate_technical_rule_id
                                        for source_rule_id in source_rule_ids
                                    )
                                    has_any_selection_for_sources = any(
                                        source_rule_id in selected_sources for source_rule_id in source_rule_ids
                                    )
                                    usage_key = (candidate_technical_rule_id, actor_unit_type)
                                    if has_matching_source:
                                        stats['rule_choice_usage'][usage_key]['correct'][actor_player] += 1
                                    elif has_any_selection_for_sources:
                                        stats['rule_choice_usage'][usage_key]['mismatch'][actor_player] += 1
                                        if stats['first_error_lines']['rule_choice_usage_mismatch'][actor_player] is None:
                                            stats['first_error_lines']['rule_choice_usage_mismatch'][actor_player] = {
                                                'episode': state.current_episode_num,
                                                'line': line.strip()
                                            }
                                    else:
                                        stats['rule_choice_usage'][usage_key]['missing'][actor_player] += 1
                                        if stats['first_error_lines']['rule_choice_usage_missing'][actor_player] is None:
                                            stats['first_error_lines']['rule_choice_usage_missing'][actor_player] = {
                                                'episode': state.current_episode_num,
                                                'line': line.strip()
                                            }
                    is_reactive_move = (
                        "REACTIVE MOVED" in action_desc_upper
                        or ("MOVED [" in action_desc_upper and " - TRIGGER: UNIT " in action_desc_upper)
                    )
                    is_move_after_shooting_marker = (
                        "MOVED AFTER SHOOTING" in action_desc_upper
                        or re.search(
                            r"MOVED\s+\[MOVE_AFTER_SHOOTING(?::\d+)?\]\s+FROM",
                            action_desc_upper,
                            re.IGNORECASE,
                        ) is not None
                    )
                    is_move_marker = (
                        ") MOVED" in action_desc_upper
                        and not is_reactive_move
                        and not is_move_after_shooting_marker
                    )
                    # 20.04 : l'ingress EST le mouvement du tour (« until the start of the next
                    # Charge phase, your unit is not eligible to make any other type of move »),
                    # et le moteur termine bien l'activation (`_handle_ingress_move_action` →
                    # `end_activation`). Sans ce marqueur, une escouade qui arrive PUIS bouge dans
                    # la même phase ne comptait aucune double activation. Les lignes de la phase
                    # de DÉPLOIEMENT n'atteignent pas ce point (elles sont consommées plus haut).
                    is_ingress_marker = ") DEPLOYED" in action_desc_upper
                    # 12.07 : « Each unit can make one consolidation move during this step ». La
                    # ligne `CONSOLIDATED` marque donc la FIN d'une activation de combat, une par
                    # unité et par phase — c'est le seul marqueur d'activation que la phase FIGHT
                    # possède (les lignes `FOUGHT` sont par ATTAQUE, il y en a des dizaines).
                    is_consolidation_marker = ") CONSOLIDATED " in action_desc_upper
                    # 10.02 — « Each unit can only shoot once per Shooting phase ».
                    # SHOT est par ATTAQUE (des dizaines par activation), donc ce n'est pas la
                    # ligne SHOT elle-même qui marque la frontière, mais la PREMIÈRE ligne SHOT
                    # d'une nouvelle activation. La frontière est détectée via shoot_last_activator :
                    #   • première activation (phase fraîche) : shoot_last_activator est None → ≠ actor_id ;
                    #   • reprise par un AUTRE acteur : shoot_last_activator porte l'ID de l'acteur
                    #     précédent → ≠ actor_id ;
                    #   • tirs consécutifs de la MÊME unité (salve) : shoot_last_activator == actor_id
                    #     depuis le premier tir → False, pas un nouveau marqueur.
                    # shoot_last_activator est mis à jour pour TOUTE action de la phase SHOOT
                    # (SHOT ou non), donc une WAIT intercalée ne rompt pas la continuité de l'acteur.
                    is_shoot_activation_start = (
                        _is_shot_action
                        and state.shoot_last_activator != actor_id
                    )
                    is_activation_marker = (
                        is_move_marker
                        or is_ingress_marker
                        or is_consolidation_marker
                        or is_shoot_activation_start
                        or " ADVANCED " in action_desc_upper
                        or " CHARGED " in action_desc_upper
                        or " FAILED CHARGE " in action_desc_upper
                        or " FLED " in action_desc_upper
                    )
                    # Double-activation should only count unit activations, not per-shot/per-attack logs.
                    # FIGHT : marqueur = ligne CONSOLIDATED (12.07 — une seule consolidation par unité
                    # et par phase). SHOOT : marqueur = première ligne SHOT d'un nouvel acteur
                    # (is_shoot_activation_start, 10.02 — livré le 2026-08-17).
                    if phase in ('MOVE', 'SHOOT', 'CHARGE', 'FIGHT') and is_activation_marker:
                        if player is None:
                            raise ValueError("player is required for double-activation check")
                        # CLÉ DE PHASE. Pour FIGHT, `(tour, phase, joueur)` ne DÉSIGNE PAS une
                        # phase : un tour en contient DEUX (celle du tour de P1, celle du tour de
                        # P2), et les unités des deux camps combattent dans chacune — c'est la
                        # règle (12.04 : les joueurs alternent leurs sélections dans la MÊME
                        # phase). Le `player` de la ligne est celui de l'unité qui agit, pas celui
                        # de la phase : les deux activations légitimes d'une unité, une par phase,
                        # tombaient donc sur la même clé et étaient comptées comme un doublon.
                        # Mesuré : 55 unités « dupliquées » sur un run de 12 épisodes, dont zéro
                        # vraie — `fight_phase_start` n'a JAMAIS été appelé deux fois pour une même
                        # phase (1427 phases instrumentées, 0 doublon).
                        # `fight_phase_seq_id` compte les ENTRÉES en phase de combat : c'est la
                        # seule grandeur qui identifie une phase.
                        if phase == 'FIGHT':
                            # ⚠️ `fight_phase_seq_id` n'est incrémenté qu'APRÈS ce bloc (avec les
                            # autres remises à zéro de frontière de phase). La PREMIÈRE ligne
                            # d'une phase de combat verrait donc encore l'identifiant de la
                            # précédente, et la seconde le nouveau : deux clés différentes pour
                            # la même phase, et le vrai doublon passait inaperçu. On applique donc
                            # ici la même détection de frontière que le bloc ci-dessous.
                            _fight_phase_id = state.fight_phase_seq_id + (
                                1 if phase != state.last_phase else 0
                            )
                            phase_key = (phase, _fight_phase_id, int(player))
                        else:
                            phase_key = (turn, phase, int(player))
                        seen_units = state.phase_activation_seen.setdefault(phase_key, set())
                        if actor_id in seen_units:
                            double_activation_by_phase = require_key(stats, "double_activation_by_phase")
                            double_activation_by_phase[phase] += 1
                            first_errors = require_key(stats, "first_error_lines")
                            double_activation_first = require_key(first_errors, "double_activation_by_phase")
                            if double_activation_first[phase] is None:
                                double_activation_first[phase] = {'episode': state.current_episode_num, 'line': line.strip()}
                        else:
                            seen_units.add(actor_id)

                    # 12.02, volet « Each unit cannot make more than one pile-in move during this
                    # step ». Il lui faut sa PROPRE clé : `PILED IN` ne peut pas rejoindre
                    # `is_activation_marker` ci-dessus, sans quoi le pile-in et la consolidation
                    # d'une même unité — deux étapes DISTINCTES et toutes deux légales dans la
                    # même phase (12.02 puis 12.07) — tomberaient sur le même ensemble et
                    # compteraient un faux doublon. Même identité de phase que la double
                    # activation (`fight_phase_seq_id`) : un tour porte DEUX phases de combat.
                    if phase == 'FIGHT' and ") PILED IN " in action_desc_upper:
                        if player is None:
                            raise ValueError("player is required for the pile-in check")
                        _pile_in_phase_id = state.fight_phase_seq_id + (
                            1 if phase != state.last_phase else 0
                        )
                        _pile_in_seen = state.pile_in_seen.setdefault(
                            (_pile_in_phase_id, int(player)), set()
                        )
                        if actor_id in _pile_in_seen:
                            stats['fight_double_pile_in'][int(player)] += 1
                            _pile_in_first = require_key(
                                require_key(stats, "first_error_lines"), "fight_double_pile_in"
                            )
                            if _pile_in_first[int(player)] is None:
                                _pile_in_first[int(player)] = {
                                    'episode': state.current_episode_num, 'line': line.strip()
                                }
                        else:
                            _pile_in_seen.add(actor_id)


                # Reset markers when turn changes
                if turn != state.last_turn:
                    # 07.02 — valider la séquence de phases du tour SORTANT avant de la purger.
                    if state.last_turn > 0:
                        _check_phase_seq(state, state.last_turn, stats)
                    state.phase_seq_current_turn = {}
                    state.units_moved = set()
                    state.units_shot = set()
                    # CRITICAL: Reset state.units_fled at the start of each turn
                    # According to tour_de_jeu.md and command_phase_start(), state.units_fled is reset at the start of each turn
                    # A unit that fled in T1 SHOULD be able to shoot/charge in T2
                    state.units_fled = set()
                    state.units_advanced = set()
                    state.units_fought = set()
                    state.charged_units_current_fight = set()
                    state.charged_units_fought = set()
                    state.units_moved_after_shooting_in_turn = set()
                    state.positions_at_turn_start = state.unit_positions.copy()
                    state.positions_at_move_phase_start = {}
                    state.last_player = None  # Reset last player on turn change
                    state.last_phase = None
                    state.last_phase_by_player = {}
                    state.last_shoot_shooter_id = None
                    state.last_shoot_weapon = None
                    state.last_shoot_target_id = None
                    state.shoot_last_activator = None
                    state.last_fight_fighter_id = None
                    state.last_fight_weapon = None
                    state.last_fight_shooters = ()
                    state.last_turn = turn

                # Track positions at start of MOVE phase for fled detection
                # CRITICAL: Must track positions at the start of EACH player's MOVE phase, not just the first MOVE of the turn
                # When player changes OR when we see the first MOVE action of a turn, capture positions
                # BUT: Don't fill it yet - we'll fill it with positions "from" of MOVE actions below
                if phase == 'MOVE' and (state.last_player != player or not state.positions_at_move_phase_start):
                    # Don't fill state.positions_at_move_phase_start here - it will be filled below using "from" positions from log
                    state.positions_at_move_phase_start = {}
                
                # Update state.last_player after processing the action
                state.last_player = player

                # 07.02 — enregistrer la séquence de phases par joueur, en partant de son COMMAND.
                # Les actions d'un joueur AVANT son COMMAND dans un round (défenseur au FIGHT de
                # l'adversaire, mort loggée en P2 SHOOT pendant le tir P1) ne font pas partie de
                # sa séquence active et ne sont pas validées — sinon FIGHT/SHOOT avant COMMAND = FP.
                #
                # §2.9 : les lignes DEAD (unité tuée par l'adversaire) portent le player du
                # PROPRIÉTAIRE de l'unité et la phase COURANTE (phase de l'adversaire). Elles ne
                # représentent pas une action volontaire du joueur victime → exclues du suivi.
                # Regex `\S*` absorbe les coordonnées optionnelles `(col,row)` — présentes quand
                # `unit_with_coords` est fourni au step_logger, absentes sur les journaux antérieurs.
                _dead_event_m = re.match(r'Unit (\d+)\S* DEAD model=(\S+)', action_desc)
                _is_dead_event = _dead_event_m is not None
                if _dead_event_m:
                    _dead_uid = _dead_event_m.group(1)
                    _dead_mid = _dead_event_m.group(2)
                    # Appliquer immédiatement la suppression : si c'est le DERNIER socle, il
                    # n'y aura plus de [MODELS:] pour déclencher la purge `pending_model_removals`,
                    # et le modèle resterait « fantôme » dans `positions_by_model`.
                    _pbm = state.positions_by_model.get(_dead_uid)
                    if _pbm is not None:
                        _pbm.pop(_dead_mid, None)
                        if not _pbm:
                            state.positions_by_model.pop(_dead_uid, None)
                            # Dernier socle retiré : unit_hp doit refléter la mort pour que
                            # _build_move_bfs_blockers ne traite pas l'ancre comme bloqueur fantôme.
                            state.unit_hp[_dead_uid] = 0
                    elif _dead_uid in state.unit_hp and state.unit_hp[_dead_uid] > 0:
                        # positions_by_model absent (purgé par charge_handler, move_handler, etc.)
                        # avant ce DEAD : le if-branch ne peut pas compter les socles restants.
                        # Décrémenter le compteur local ; quand il atteint 0 (tous les socles
                        # déclarés morts via DEAD), zéroer unit_hp pour que _build_move_bfs_blockers
                        # n'inclue plus l'ancre fantôme dans occupied_positions.
                        _models_left = state.unit_models_alive.get(_dead_uid, 1) - 1
                        state.unit_models_alive[_dead_uid] = max(0, _models_left)
                        if _models_left <= 0:
                            state.unit_hp[_dead_uid] = 0
                    _prm = state.pending_model_removals.get(_dead_uid)
                    if _prm is not None:
                        _prm.discard(_dead_mid)
                        if not _prm:
                            state.pending_model_removals.pop(_dead_uid, None)
                if phase != state.last_phase_by_player.get(int(player)):
                    _player_seq = state.phase_seq_current_turn.get(int(player))
                    if _player_seq is not None or phase == 'COMMAND':
                        if _player_seq is None:
                            _player_seq = []
                            state.phase_seq_current_turn[int(player)] = _player_seq
                        if not _is_dead_event and phase not in _player_seq:
                            _player_seq.append(phase)
                    state.last_phase_by_player[int(player)] = phase

                if phase != state.last_phase and not _is_dead_event:
                    if phase == 'COMMAND':
                        state.selected_choice_by_unit_source = {}
                    if phase == 'MOVE':
                        # Reset snapshot at the start of each MOVE phase
                        state.positions_at_move_phase_start = {}
                        state.charged_units_current_fight = set()
                        state.charged_units_fought = set()
                    if phase == 'SHOOT':
                        # Reset shot sequence counts at the start of each SHOOT phase
                        state.shot_sequence_counts = {}
                        state.last_shoot_shooter_id = None
                        state.last_shoot_weapon = None
                        state.last_shoot_target_id = None
                        state.units_moved_after_shooting_in_turn = set()
                        state.combi_profile_usage = {}
                        state.combi_conflicts_seen = set()
                        state.shoot_last_activator = None
                    if phase == 'FIGHT':
                        state.fight_phase_seq_id += 1
                        state.last_fight_fighter_id = None
                        state.last_fight_weapon = None
                        state.last_fight_shooters = ()
                    state.last_phase = phase

                # 10.02 — frontière d'activation SHOOT. Mis à jour ICI, APRÈS les blocs de
                # reset de tour et de phase, pour éviter que le reset de tour (turn != last_turn)
                # n'écrase la valeur qu'on vient de fixer pour la première ligne de chaque tour.
                # Mis à jour UNIQUEMENT sur les lignes SHOT (is_shot_action) : une action non-tir
                # de l'unité B (reactive move) ne doit pas interrompre la salve en cours de A.
                # `_dmg_actor_id` est disponible ici (défini avant `if _dmg_actor_match:`).
                if _is_shot_action and phase == 'SHOOT':
                    state.shoot_last_activator = _dmg_actor_id

                # 01.07 / L1 — drapeau battle-shocked par unité. Ligne :
                # «Unit N(c,r) BATTLE-SHOCK Roll:2D6=X vs LdY+ → SHOCKED|OK»
                _bs_match = re.search(
                    r'Unit (\d+)\(\d+,\d+\) BATTLE-SHOCK Roll:.* → (SHOCKED|OK)',
                    action_desc,
                )
                if _bs_match:
                    _bs_uid = _bs_match.group(1)
                    state.battle_shocked_by_unit[_bs_uid] = (_bs_match.group(2) == 'SHOCKED')

                state.episode_turn = max(state.episode_turn, turn)

                if step_inc:
                    stats['total_actions'] += 1
                    state.episode_actions += 1
                    stats['actions_by_phase'][phase] += 1

                # REACTIVE MOVE metrics (normal + abnormal occurrences)
                # Supported log examples:
                # - "Unit X(...) REACTIVE MOVED from (...) to (...) [Roll: N]"
                # - "Unit X(...) MOVED [PREDATOR INSTINCT] from (...) to (...) [Roll: N] - trigger: Unit Y->(a,b)"
                # - "Unit X(...) DECLINED REACTIVE MOVE"
                reactive_decline_match = re.search(
                    r'Unit\s+(\d+).*DECLINED\s+REACTIVE\s+MOVE',
                    action_desc,
                    re.IGNORECASE
                )
                reactive_move_match = re.search(
                    r'Unit\s+(\d+)\((\d+),\s*(\d+)\)\s+'
                    r'(?:REACTIVE\s+MOVED(?:\s+\[[^\]]+\])?|MOVED\s+\[[^\]]+\])\s+'
                    r'from\s+\((\d+),\s*(\d+)\)\s+to\s+\((\d+),\s*(\d+)\)'
                    r'(?:\s+\[Roll:\s*(\d+)\])?',
                    action_desc,
                    re.IGNORECASE
                )
                # Guard against false reactive classification for normal keyword moves (e.g. MOVED [FLY]).
                # A move is reactive only when explicit reactive markers are present.
                if reactive_move_match and not is_reactive_move:
                    reactive_move_match = None

                if reactive_decline_match:
                    reactive_unit_id = reactive_decline_match.group(1)
                    reactive_player = state.unit_player.get(reactive_unit_id) if reactive_unit_id in state.unit_player else player
                    reactive_player = int(reactive_player) if reactive_player is not None else player
                    reactive_stats = require_key(stats, 'reactive_move_stats')
                    reactive_stats[reactive_player]['declined'] += 1

                if reactive_move_match:
                    reactive_unit_id = reactive_move_match.group(1)
                    reactive_player = state.unit_player.get(reactive_unit_id) if reactive_unit_id in state.unit_player else player
                    reactive_player = int(reactive_player) if reactive_player is not None else player
                    reactive_stats = require_key(stats, 'reactive_move_stats')
                    reactive_stats[reactive_player]['applied'] += 1
                    reactive_unit_type = require_key(state.unit_types, reactive_unit_id)
                    key = ("reactive_move", reactive_unit_type)
                    stats['special_rule_usage'][key][reactive_player] += 1
                    reactive_key = (state.current_episode_num, turn, reactive_player)
                    if reactive_key in state.reactive_activation_counts:
                        reactive_counts = state.reactive_activation_counts[reactive_key]
                    else:
                        reactive_counts = {}
                        state.reactive_activation_counts[reactive_key] = reactive_counts
                    if reactive_unit_id in reactive_counts:
                        reactive_counts[reactive_unit_id] += 1
                    else:
                        reactive_counts[reactive_unit_id] = 1
                    if reactive_counts[reactive_unit_id] == 2:
                        stats['double_activation_reactive_move'] += 1
                        first_errors = require_key(stats, "first_error_lines")
                        if first_errors['double_activation_reactive_move'] is None:
                            first_errors['double_activation_reactive_move'] = {
                                'episode': state.current_episode_num,
                                'line': line.strip()
                            }

                    from_col = int(reactive_move_match.group(4))
                    from_row = int(reactive_move_match.group(5))
                    to_col = int(reactive_move_match.group(6))
                    to_row = int(reactive_move_match.group(7))
                    roll_group = reactive_move_match.group(8)
                    roll_value = int(roll_group) if roll_group is not None else None
                    if reactive_unit_id not in state.unit_movement_history:
                        state.unit_movement_history[reactive_unit_id] = []
                    timestamp_match = re.search(r'\[(\d+:\d+:\d+)\]', line)
                    timestamp = timestamp_match.group(1) if timestamp_match else None
                    state.unit_movement_history[reactive_unit_id].append({
                        'position': (to_col, to_row),
                        'timestamp': timestamp,
                        'action': 'reactive_move',
                        'turn': turn,
                        'episode': state.current_episode_num
                    })

                    # Ce compteur ne pose plus qu'UNE question : le move réactif a-t-il eu lieu
                    # dans une phase où il n'a rien à faire ?
                    #
                    # Il en posait une seconde — « la distance dépasse-t-elle le D6 ? » — mesurée
                    # d'ANCRE à ANCRE, à vol d'oiseau, sans murs ni figurines. Or son jumeau
                    # immédiat (`distance_over_roll`, 40 lignes plus bas) pose exactement la même
                    # question par le contrôle mutualisé `_per_model_move_violation` : par
                    # figurine, chemin réel, budget converti. Deux mesures contradictoires de la
                    # même grandeur sur la même ligne, et toutes deux dans le total §1.1 : une
                    # reformation d'ancre suffisait à n'en déclencher qu'une, un vrai dépassement
                    # en déclenchait DEUX — le rapport comptait alors 2 fautes pour 1. La mesure
                    # d'ancre disparaît, la mesure par socle reste : c'est la même correction que
                    # le plafond de tir (V14), et par le même moyen — mutualiser, pas recopier.
                    reactive_abnormal = phase not in ("MOVE", "SHOOT")

                    if reactive_abnormal:
                        reactive_stats[reactive_player]['abnormal'] += 1
                        first_errors = require_key(stats, 'first_error_lines')
                        reactive_first = require_key(first_errors, 'reactive_move_abnormal')
                        if reactive_first[reactive_player] is None:
                            reactive_first[reactive_player] = {
                                'episode': state.current_episode_num,
                                'line': line.strip()
                            }

                    # Apply MOVE-like legality checks to reactive moves.
                    reactive_checks = require_key(stats, 'reactive_move_checks')
                    first_errors = require_key(stats, 'first_error_lines')

                    # Keep position cache aligned with log start position before validation.
                    if reactive_unit_id not in state.unit_positions or state.unit_positions[reactive_unit_id] != (from_col, from_row):
                        _position_cache_set(state.unit_positions, reactive_unit_id, from_col, from_row)

                    if reactive_unit_id not in state.unit_hp:
                        stats['parse_errors'].append({
                            'episode': state.current_episode_num,
                            'turn': turn,
                            'phase': phase,
                            'line': line.strip(),
                            'error': f"Reactive move for unknown unit_id (missing in state.unit_hp): {reactive_unit_id}"
                        })
                    else:
                        unit_hp_at_reactive = dict(state.unit_hp)
                        positions_at_reactive = dict(state.unit_positions)
                        if (from_col, from_row) != (to_col, to_row):
                            # Capacité de projet `reactive_move` JUGÉE — et seulement ICI, DERRIÈRE
                            # ses gardes. Posée plus haut, elle comptait un exercice pour une unité
                            # inconnue de `unit_hp` ou pour un déplacement nul, cas où trois de ses
                            # quatre contrôles ne s'exécutent pas : le rapport rendait « OK » là où
                            # il n'avait presque rien jugé.
                            note_rule_usage(stats, "PROJET.reactive_move", reactive_player)
                            if roll_value is not None:
                                # Le D6 loggué est en POUCES : le moteur le convertit
                                # (`_build_reactive_move_destinations_pool`), l'analyzer doit
                                # suivre. Comparer un jet en pouces à un nombre de cases
                                # plafonnait le contrôle à 6 cases quelle que soit la résolution.
                                _reactive_budget = int(roll_value) * _get_inches_to_subhex_for_analyzer()
                                occupied_positions, enemy_adjacent_hexes = _build_move_bfs_blockers(
                                    state.positions_by_model, positions_at_reactive,
                                    state.unit_base, state.unit_player, unit_hp_at_reactive,
                                    reactive_unit_id
                                )
                                # 5e site du controle per-socle : meme helper que move,
                                # advance, charge et pile-in. La ligne reactive porte un
                                # segment `[MODELS:]` depuis qu'elle est journalisee.
                                if _per_model_move_violation(
                                    surviving_start_models(
                                        state.positions_by_model.get(reactive_unit_id),  # get allowed
                                        state.current_line_models.get(reactive_unit_id),  # get allowed
                                    ),
                                    state.current_line_models.get(reactive_unit_id),  # get allowed
                                    (from_col, from_row), (to_col, to_row),
                                    _reactive_budget, False,
                                    state.wall_hexes, occupied_positions, enemy_adjacent_hexes,
                                ):
                                    reactive_checks['distance_over_roll'][reactive_player] += 1
                                    if first_errors['reactive_move_distance_over_roll'][reactive_player] is None:
                                        first_errors['reactive_move_distance_over_roll'][reactive_player] = {
                                            'episode': state.current_episode_num,
                                            'line': line.strip()
                                        }
                            else:
                                reactive_checks['distance_over_roll'][reactive_player] += 1
                                if first_errors['reactive_move_distance_over_roll'][reactive_player] is None:
                                    first_errors['reactive_move_distance_over_roll'][reactive_player] = {
                                        'episode': state.current_episode_num,
                                        'line': line.strip()
                                    }

                            positions_for_adjacency_check = dict(positions_at_reactive)
                            positions_for_adjacency_check[reactive_unit_id] = (to_col, to_row)
                            positions_for_adjacency_check_filtered = {}
                            for uid, hp_value in unit_hp_at_reactive.items():
                                if hp_value <= 0:
                                    continue
                                pos = positions_for_adjacency_check.get(uid)
                                if pos is None:
                                    continue
                                positions_for_adjacency_check_filtered[uid] = pos

                            reactive_dest_adjacent = is_within_engine_engagement_zone(
                                reactive_unit_id,
                                state.unit_player,
                                positions_for_adjacency_check_filtered,
                                unit_hp_at_reactive,
                                engagement_zone=_get_engagement_zone_for_analyzer(),
                                # Le move réactif ne loggue pas de `[MODELS:]` d'arrivée : le
                                # sujet reste mesuré à l'ancre, les ennemis à leurs socles.
                                # Donc pas de gate vertical non plus (§03.04) — sans socle
                                # d'arrivée, le sujet n'a pas d'altitude, et le contrôle
                                # « tout ou rien » de la primitive le laisse en 2D. Une altitude
                                # supposée rendrait un verdict faux, pas un verdict absent.
                                position_override=(to_col, to_row),
                                    unit_base=state.unit_base,
                            )
                            if reactive_dest_adjacent:
                                reactive_checks['to_adjacent_enemy'][reactive_player] += 1
                                if first_errors['reactive_move_to_adjacent_enemy'][reactive_player] is None:
                                    first_errors['reactive_move_to_adjacent_enemy'][reactive_player] = {
                                        'episode': state.current_episode_num,
                                        'line': line.strip()
                                    }

                            if (to_col, to_row) in state.wall_hexes:
                                reactive_checks['into_wall'][reactive_player] += 1
                                if first_errors['reactive_move_into_wall'][reactive_player] is None:
                                    first_errors['reactive_move_into_wall'][reactive_player] = {
                                        'episode': state.current_episode_num,
                                        'line': line.strip()
                                    }

                            if require_key(state.unit_hp, reactive_unit_id) > 0:
                                _position_cache_set(state.unit_positions, reactive_unit_id, to_col, to_row)

                # Determine action type and validate rules
                action_unit_id = require_present(unit_id, "unit_id")
                is_shoot_action = re.search(
                    r'\bSHOT(?:\s+\([A-Za-z0-9_ ]+\)|\s+\[[^\]]+\])*'
                    r'(?:\s+\[RAPID(?: |_)?FIRE:(\d+)\])?\s+(?:at\s+)?Unit\s+\d+',
                    action_desc,
                    re.IGNORECASE
                ) is not None
                if not is_shoot_action:
                    state.last_shoot_shooter_id = None
                    state.last_shoot_weapon = None
                    state.last_shoot_target_id = None
                if re.search(
                    r'\bSHOT(?:\s+\([A-Za-z0-9_ ]+\)|\s+\[[^\]]+\])*'
                    r'(?:\s+\[RAPID(?: |_)?FIRE:(\d+)\])?\s+(?:at\s+)?Unit\s+\d+',
                    action_desc,
                    re.IGNORECASE
                ):
                        action_type = 'shoot'
                        handle_shoot(state, config, line, action_desc, action_unit_id, player, turn, phase, step_marker_present, step_inc)
                elif " WAIT" in action_desc:
                        action_type = 'wait'
                        if handle_wait(state, config, line, action_desc, action_unit_id, player, turn, phase):
                            continue
                elif " SKIP" in action_desc:
                        # Le moteur ne journalise AUCUN `SKIP` : `_STEP_LOG_TYPE_MAP`
                        # (`w40k_core.py`) est une liste blanche et n'y porte pas `skip` — « type
                        # sans formateur -> volontairement non journalisé ». Tout ce qui pendait
                        # à cette branche était donc inatteignable, `dead_unit_skipping` compris,
                        # et son 0 perpétuel comptait pour un ✅ (vert vacant V3, 2026-08-10).
                        #
                        # La branche SURVIT, mais pour DIRE que le contrat a changé au lieu de
                        # laisser la ligne tomber en silence dans `other` : le jour où le moteur
                        # journalisera les skips, cette ligne apparaîtra en §2.7 et il faudra
                        # ré-écrire les contrôles, pas les deviner.
                        action_type = 'other'
                        stats['parse_errors'].append({
                            'episode': state.current_episode_num,
                            'turn': turn,
                            'phase': phase,
                            'line': line.strip(),
                            'error': "ligne SKIP inattendue : le moteur ne journalise pas ce "
                                     "type d'action (_STEP_LOG_TYPE_MAP). Les contrôles de skip "
                                     "ont été supprimés le 2026-08-10 comme inatteignables."
                        })
                # Le token optionnel `[FLY]` (21.03) s'insère entre le verbe et `from` sur les
                # trois types de move. Un aiguillage sur la chaîne littérale `"<VERBE> from"`
                # laissait ces lignes SANS branche : l'action n'était pas traitée, la position
                # de l'unité restait figée, et toutes les adjacences calculées ensuite l'étaient
                # contre un fantôme.
                elif move_verb_present("ADVANCED", action_desc):
                        action_type = 'advance'
                        if handle_advance(state, config, line, action_desc, action_unit_id, player, turn, phase):
                            continue
                # `[^\]]+` : cf. `analyzer_phases/charge_handler.py` — un nom de capacité peut
                # porter un `!` (`[WAAAGH!]`), et une classe énumérée faisait tomber la ligne
                # dans le `else` (action non classée) au lieu de la brancher sur la charge.
                elif re.search(r"CHARGED(?:\s+(?:\([^)]+\)|\[[^\]]+\]))*\s+Unit", action_desc) or "FAILED CHARGE" in action_desc:
                        action_type = 'charge'
                        handle_charge(state, config, line, action_desc, action_unit_id, player, turn, phase)
                elif (
                    "MOVED from" in action_desc
                    or "MOVED AFTER SHOOTING" in action_desc
                    or ("MOVED [" in action_desc and " - trigger: Unit " not in action_desc)
                    or move_verb_present("FLED", action_desc)
                ):
                        action_type = 'move'
                        fled_match_check = move_line_re("FLED", with_positions=False).search(action_desc)
                        if fled_match_check:
                            action_type = 'fled'
                        if handle_move_or_fled(state, config, line, action_desc, action_unit_id, player, turn, phase):
                            continue
                elif "CONSOLIDATED from" in action_desc or "PILED IN from" in action_desc:
                        # 12.03 pile-in / 12.08 consolidation : déplacements de la phase de
                        # combat, contrôlés comme les autres (budget 3", per-socle, chemin).
                        action_type = 'move'
                        handle_fight_move(state, config, line, action_desc, player, turn, phase)
                elif " COHERENCY REMOVED " in action_desc:
                        # 03.03 End of Turn — retrait de figurines hors cohérence. Ce n'est PAS
                        # une faute : c'est la règle qui s'applique, et c'est la seule mort qui ne
                        # descend d'aucune attaque. Le travail utile est fait en amont par le
                        # segment `[MODELS:]` de cette ligne (survivants de l'escouade), qui purge
                        # les socles retirés de `positions_by_model` — sans elle ils restaient
                        # « vivants » jusqu'à la prochaine action de l'escouade et fabriquaient
                        # des engagements et des blocages de chemin qui n'existaient pas.
                        # La branche existe pour COMPTER l'exercice de la règle et pour que la
                        # ligne ne tombe pas dans `other`, où plus personne ne la lit.
                        action_type = 'coherency_removal'
                        _removed = re.search(
                            r'COHERENCY REMOVED\s+(.+?)\s+\(03\.03\)', action_desc
                        )
                        if not _removed:
                            stats['parse_errors'].append({
                                'episode': state.current_episode_num,
                                'turn': turn,
                                'phase': phase,
                                'line': line.strip(),
                                'error': "ligne COHERENCY REMOVED sans liste de figurines",
                            })
                        else:
                            stats['coherency_removals'][player] += len(_removed.group(1).split())
                            note_rule_usage(stats, "03.03", player)
                elif " RESERVES TIMEOUT " in action_desc:
                        # 20.04 — destruction en fin de 3e round des unités restées en réserves
                        # stratégiques. L'escouade est entièrement détruite : contrairement à
                        # coherency_removal, aucun survivant ne resynchronise la position.
                        # On marque l'escouade comme morte pour que les compteurs d'attrition
                        # soient cohérents, et on l'exclut du tracking de positions.
                        action_type = 'reserves_timeout'
                        _rt_match = _RT_UNIT_ID_RE.match(action_desc)
                        if _rt_match:
                            _rt_uid = _rt_match.group(1)
                            if _rt_uid in state.unit_hp and state.unit_hp[_rt_uid] > 0:
                                # Pas de current_episode_deaths.append : le timeout n'est pas un
                                # kill attribuable à un joueur (même convention que coherency_removal).
                                # Pas de wounded_enemies.discard : une unité en réserves n'a jamais
                                # été sur le plateau et ne peut donc figurer dans aucun des deux sets.
                                _position_cache_remove(state.unit_positions, _rt_uid)
                                state.positions_by_model.pop(_rt_uid, None)
                                state.unit_deaths.append((turn, phase, _rt_uid, state.line_number))
                                state.dead_units_current_episode.add(_rt_uid)
                                state.unit_models_alive[_rt_uid] = 0
                                del state.unit_hp[_rt_uid]
                        stats['reserves_timeout_destroyed'][player] += 1
                        note_rule_usage(stats, "20.04", player)
                elif " SUFFERS " in action_desc and _HAZARDOUS_TAG_RE.search(action_desc):
                        # 24.15 [HAZARDOUS] : après résolution de ses attaques (tir ou mêlée),
                        # l'unité subit X blessures mortelles auto-infligées.
                        # Grammaire : `Unit N(c,r) SUFFERS X Mortal Wounds [HAZARDOUS]`.
                        # Grammar ≥ 6 : le moteur nomme le socle cible dans [ALLOC_MODEL:],
                        # exactement comme pour les attaques régulières (cf. step_logger.py §569).
                        action_type = 'hazardous'
                        _hz_match = _HAZARDOUS_SUFFERS_RE.search(action_desc)
                        if _hz_match:
                            _hz_mw = int(_hz_match.group(1))
                            if "[ALL FNP SAVED]" in action_desc:
                                _hz_mw = 0
                            # Cible = acteur : le préfixe "Unit N(" d'action_desc est la seule
                            # source fiable de l'ID de l'unité sur une ligne SUFFERS (action_unit_id
                            # retient le dernier ID de header, pas celui de la ligne courante).
                            _hz_unit_id = _dmg_actor_id or action_unit_id
                            # Vérifier que l'unité porte effectivement une arme HAZARDOUS.
                            # `state.unit_model_hp` ne contient que les socles VIVANTS : si la MW
                            # tue le porteur de l'arme HAZARDOUS (ex. VanguardVeteranSquadJumpPackPlasma)
                            # avant ce contrôle, la boucle ne le voit plus → faux positif.
                            # `state.model_types` conserve TOUS les types (vivants ET morts) pour
                            # toute la durée de l'épisode — source correcte ici.
                            # Toutes les datasheets de l'escouade (hétérogène : 19.01) sont
                            # consultées ; une seule suffit pour que la ligne soit légitime.
                            _squad_type = state.unit_types.get(_hz_unit_id)
                            _all_unit_types: "set[str]" = set()
                            if _squad_type:
                                _all_unit_types.add(_squad_type)
                            _unit_prefix = _hz_unit_id + "#"
                            for _mid, _mtype in state.model_types.items():
                                if _mid.startswith(_unit_prefix) and _mtype:
                                    _all_unit_types.add(_mtype)
                            _has_hazardous = any(
                                any(
                                    "HAZARDOUS" in (w.get("rules") or [])
                                    for w in (config.unit_weapons_cache.get(t) or [])
                                )
                                for t in _all_unit_types
                            )
                            # `_all_unit_types` vide = données absentes du log ; pas de
                            # faux positif dans ce cas, le contrôle ne peut pas aboutir.
                            if _all_unit_types and not _has_hazardous:
                                _hz_key = (
                                    'hazardous_no_hazardous_weapon_fight'
                                    if phase.upper() == 'FIGHT'
                                    else 'hazardous_no_hazardous_weapon'
                                )
                                stats[_hz_key][player] += 1
                                _first_hz = stats['first_error_lines'][_hz_key]
                                if _first_hz[player] is None:
                                    _first_hz[player] = {
                                        'episode': state.current_episode_num,
                                        'line': line.strip(),
                                    }
                            # Appliquer les dégâts à l'unité ELLE-MÊME (auto-infligés).
                            # `_dmg_actor_id` est le préfixe "Unit N(" de la ligne SUFFERS :
                            # c'est la seule source fiable de l'unité touchée (action_unit_id
                            # retient le dernier ID de header, pas celui de la ligne courante).
                            # grammar ≥ 6 : [ALLOC_MODEL:] présent si mw>0, lu comme pour tir/mêlée.
                            # grammar < 6 : None → chemin hérité (ordered_living_mids[0]).
                            # mw==0 : aucun dé raté (step.log émet [NO ALLOC]) ou [ALL FNP SAVED]
                            # → aucune blessure effective → aucune allocation possible ; on saute
                            # le bloc de dégâts entièrement.
                            # `pending_model_removals=None` : les removals d'une attaque précédente
                            # de la MÊME activation ne doivent pas être fusionnés ici — cette mort
                            # est distincte, et le flush se produit au changement d'acteur.
                            if _hz_mw > 0:
                                stats['hazardous_mortal_wounds'][player] += _hz_mw
                                _apply_damage_and_handle_death(
                                    _hz_unit_id, _hz_unit_id, _hz_mw,
                                    player, turn, phase, state.line_number, state.current_episode_num,
                                    line, state.dead_units_current_episode, state.unit_hp,
                                    state.unit_models_alive, state.unit_model_hp,
                                    lambda _u: _ordered_living_mids(state, config, _u),
                                    state.unit_hp_squad_max, state.unit_types, state.unit_positions,
                                    state.unit_deaths, state.unit_kill_context, stats,
                                    positions_by_model=state.positions_by_model,
                                    models_invalidated=state.models_invalidated,
                                    alloc_model_id=_alloc_model_from_line(state, action_desc, line) if state.log_grammar >= 6 else None,
                                    pending_model_removals=None,
                                    dead_model_ids_episode=state.dead_model_ids_episode,
                                )
                        else:
                            stats['parse_errors'].append({
                                'episode': state.current_episode_num,
                                'turn': turn,
                                'phase': phase,
                                'line': line.strip(),
                                'error': "ligne HAZARDOUS : format inattendu (attendu : "
                                         "'SUFFERS N Mortal Wounds [HAZARDOUS]' ou '[HAZARDOUS:K]')",
                            })
                elif " SUFFERS " in action_desc and "[DESPERATE ESCAPE]" in action_desc:
                        # 09.07 [DESPERATE ESCAPE] : blessures mortelles auto-infligées lors d'un
                        # Fall Back d'une unité engagée et battle-shocked. Tag différent de
                        # [HAZARDOUS] (24.15) : ne doit pas incrémenter hazardous_mortal_wounds
                        # ni déclencher le contrôle d'armurerie.
                        action_type = 'desperate_escape'
                        _de_match = re.search(
                            r'SUFFERS\s+(\d+)\s+Mortal\s+Wounds\s+\[DESPERATE ESCAPE\]',
                            action_desc,
                        )
                        if _de_match:
                            _de_mw = int(_de_match.group(1))
                            if "[ALL FNP SAVED]" in action_desc:
                                _de_mw = 0
                            _de_unit_id = _dmg_actor_id
                            if _de_unit_id is None:
                                stats['parse_errors'].append({
                                    'episode': state.current_episode_num,
                                    'turn': turn,
                                    'phase': phase,
                                    'line': line.strip(),
                                    'error': "ligne DESPERATE ESCAPE : ID unité introuvable "
                                             "(attendu : 'Unit N(' en tête d'action)",
                                })
                            elif _de_mw > 0:
                                _apply_damage_and_handle_death(
                                    _de_unit_id, _de_unit_id, _de_mw,
                                    player, turn, phase, state.line_number, state.current_episode_num,
                                    line, state.dead_units_current_episode, state.unit_hp,
                                    state.unit_models_alive, state.unit_model_hp,
                                    lambda _u: _ordered_living_mids(state, config, _u),
                                    state.unit_hp_squad_max, state.unit_types, state.unit_positions,
                                    state.unit_deaths, state.unit_kill_context, stats,
                                    positions_by_model=state.positions_by_model,
                                    models_invalidated=state.models_invalidated,
                                    alloc_model_id=_alloc_model_from_line(state, action_desc, line) if state.log_grammar >= 6 else None,
                                    pending_model_removals=None,
                                    dead_model_ids_episode=state.dead_model_ids_episode,
                                )
                        else:
                            stats['parse_errors'].append({
                                'episode': state.current_episode_num,
                                'turn': turn,
                                'phase': phase,
                                'line': line.strip(),
                                'error': "ligne DESPERATE ESCAPE : format inattendu (attendu : "
                                         "'SUFFERS N Mortal Wounds [DESPERATE ESCAPE]')",
                            })
                elif "[DEADLY DEMISE]" in action_desc:
                        # §24.08 DEADLY DEMISE — blessures mortelles après destruction d'une figurine.
                        # Une entrée par unité dans le rayon (d6 partagé) ; la ligne dit si c'est effectif
                        # (`SUFFERS X MW`) ou nul (`no effect`). Compteur d'EXERCICE seul.
                        action_type = 'deadly_demise'
                        stats['deadly_demise_triggers'][player] += 1
                        note_rule_usage(stats, "24.08", player)
                elif attack_verb_present(action_desc):
                        action_type = 'fight'
                        handle_fight(state, config, line, action_desc, action_unit_id, player, turn, phase, step_marker_present, step_inc)
                else:
                    action_type = 'other'

                # Ici vivait un recalcul du contrôle d'objectif à CHAQUE action `step_inc`,
                # suivi d'une seconde implémentation du barème primaire. Les deux sont supprimés :
                # ils sommaient l'OC par ANCRE d'escouade (le moteur somme par empreinte de socle,
                # 14.02), ignoraient le battle-shock (01.07 : OC de toutes les figurines à '-'),
                # et évaluaient à chaque action alors que le contrôle est figé en fin de phase.
                # Les VP viennent maintenant de la ligne `T{tour} OBJECTIVE CONTROL:` du moteur
                # (lue plus haut) ; l'historique `objective_control_history` qu'ils alimentaient
                # n'avait AUCUN lecteur dans tout le dépôt.

                stats['actions_by_type'][action_type] += 1
                stats['actions_by_player'][player][action_type] += 1

                state.current_episode.append(line.strip())
    
    # Check if last episode ended without EPISODE END
    if state.current_episode:
        stats['episodes_without_end'].append({
            'episode_num': state.current_episode_num,
            'actions': state.episode_actions,
            'turn': state.episode_turn,
            'last_line': state.current_episode[-1][:100] if state.current_episode else 'N/A'
        })
        
        stats['episode_lengths'].append((state.current_episode_num, state.episode_actions))
        # Save turn distribution for last episode
        if state.episode_turn > 0:
            stats['turns_distribution'][state.episode_turn] += 1

