#!/usr/bin/env python3
"""
ai/step_logger.py - Step-by-step action logging

Contains:
- StepLogger: Logs all actions that increment steps

Extracted from ai/train.py during refactoring (2025-01-21)
"""

import time
import builtins
import json
from typing import Any, Dict, Optional

from shared.data_validation import require_key

from ai.bot_registry import bot_display_name

__all__ = ['StepLogger', 'LOG_GRAMMAR_VERSION']


#: Version de la GRAMMAIRE du journal, ecrite a l entete de chaque episode (`Log grammar:`).
#: Elle dit ce que le journal GARANTIT porter — ce qui permet a un lecteur de traiter une donnee
#: manquante comme une PANNE et non comme un vieux format, sans jamais retomber en silence sur
#: une reconstruction approximative.
#:
#:   1 — grammaire d avant le 2026-08-12 : aucune ligne ne nomme la figurine cible allouee.
#:   2 — `[ALLOC_MODEL: <mid>]` sur toute attaque parvenue a l allocation (tir ET melee).
#:   3 — TOUTE regle d arme de `config/weapon_rules.json` qui a joue est NOMMEE sur la ligne.
#:       Six y sont entrees d un bloc le 2026-08-12 ([TORRENT], [LETHAL HITS], [IGNORES COVER],
#:       [EXTRA ATTACKS], [ANTI-X:Y+], [PSYCHIC] et, en melee comme au tir, leurs jumeaux) ;
#:       INDIRECT_FIRE reste hors du journal parce qu elle n est pas implementee dans le moteur
#:       — un token pour elle annoncerait un effet qui n a pas lieu. C est ce qui rend un
#:       compteur d usage a zero LISIBLE : sous cette version, il dit que la regle n a pas joue,
#:       plus jamais que le journal ne sait pas le dire.
#:
#: N incrementer que pour une garantie NOUVELLE, jamais pour un changement cosmetique : un
#: lecteur qui refuse une version qu il ne connait pas doit avoir une raison de le faire.
LOG_GRAMMAR_VERSION = 3


#: Regles qui AJOUTENT des des au pool d attaques et dont l effet depend de la CIBLE :
#: `(libelle de token, cle de `details`)`. [RAPID FIRE] 24.30 n y est pas — son X s applique par
#: figurine tirante, il a donc son propre site, deja en place. Les deux ci-dessous sont jumelles
#: a la virgule pres (« add X additional attack dice for every five models that were in the
#: target unit in the Select Targets step »), [CLEAVE] ajoutant la clause « une seule cible ».
_ADDITIVE_RULE_TOKENS: tuple = (("BLAST", "blast_rule_value"), ("CLEAVE", "cleave_rule_value"))


def _additive_rule_tokens(details) -> list:
    """Tokens `[BLAST:X]` / `[CLEAVE:X]` d une ligne d attaque — TIR ET MELEE, un seul site.

    MEME grammaire que `[RAPID FIRE:X]` : X est le parametre DECLARE par l arme, jamais le
    nombre de des ajoutes. Ce nombre depend de la taille de la cible au Select Targets step, et
    l ecrire ici dispenserait le lecteur de le recalculer — donc rendrait le controle VACANT :
    l analyzer verifierait le moteur avec le chiffre du moteur.

    Le token n est pose que si la regle a REELLEMENT ajoute des des (cle absente sinon) : une
    arme [BLAST] tirant sur une escouade de 4 figurines n ajoute rien, elle ne dit rien.

    Les deux branches du formateur (SHOT et FOUGHT) l appellent. Ecrire le token dans une seule
    des deux est le motif d echec n°1 de ce depot : [CLEAVE] n existe qu en melee, [BLAST] qu au
    tir, et deux sites separes auraient laisse chacun croire l autre couvert.
    """
    tokens = []
    for rule_label, detail_key in _ADDITIVE_RULE_TOKENS:
        rule_value = details.get(detail_key)
        if rule_value is None:
            continue
        if not isinstance(rule_value, int) or rule_value <= 0:
            raise ValueError(
                f"{detail_key} must be a positive int when present, got: {rule_value}"
            )
        tokens.append(f"[{rule_label}:{rule_value}]")
    return tokens


#: Regles d arme SANS parametre dont le journal ne portait aucune trace, rangees par SEGMENT de
#: la ligne : `(cle de `details`, libelle de token)`.
#:
#: Le segment n est pas cosmetique — c est lui qui donne son sens au token pour les deux seuls
#: lecteurs automatiques du journal. L analyzer et `replayParser.ts` rattachent un token au jet
#: qu il SUIT ; ecrire `[LETHAL HITS]` du cote de la touche le ferait lire comme une propriete
#: du jet de touche, alors qu il decrit la blessure qui n a pas ete jetee.
_HIT_SEGMENT_RULE_TOKENS: tuple = (
    # 24.37 « does not make a Hit roll » : la ligne rend `Hit None(None+)`, forme indiscernable
    # d une ligne malformee tant que ce token n est pas la.
    ("auto_hit", "TORRENT"),
    # 24.18 : le couvert n est meme pas calcule (court-circuit moteur), donc le token dit ce qui
    # est vrai et verifiable — cette attaque ignore le couvert — et non « la cible l aurait eu ».
    ("ignores_cover_applied", "IGNORES COVER"),
    # 24.29 : pose UNIQUEMENT quand un modificateur a ete neutralise (cf. `psychic_rule_applies`).
    ("psychic_applied", "PSYCHIC"),
)
#: JUMEAU du precedent, cote BLESSURE.
_WOUND_SEGMENT_RULE_TOKENS: tuple = (
    # 24.23 : blessure automatique -> `Wound None(4+)`. Sans le token, rien ne distingue cette
    # absence de jet d une panne du producteur.
    ("lethal_hit", "LETHAL HITS"),
)
#: JUMEAU des deux precedents, sur les TAGS de ligne (avant la cible, comme [RAPID FIRE:X]).
_LINE_TAG_RULE_TOKENS: tuple = (
    # 24.11 : l arme est resolue EN PLUS des autres — son effet est l existence meme du groupe,
    # donc le token est pose sur la declaration, comme [IGNORES COVER]. C est ce qui permet a un
    # lecteur de ne pas compter ce groupe dans le plafond d attaques de la figurine.
    ("extra_attacks_applied", "EXTRA ATTACKS"),
)


def _flag_rule_tokens(details, table) -> list:
    """Tokens `[REGLE]` d une des trois tables ci-dessus, dans leur ordre de declaration.

    Un drapeau n est jamais pose a `False` par le moteur : la cle EXISTE ou la regle n a pas
    joue. Une cle presente avec autre chose que `True` est donc une chaine rompue, pas un
    « non » — l accepter en silence rendrait le token muet sans que rien ne le signale, ce que
    ce fichier a deja paye trois fois.
    """
    tokens = []
    for detail_key, rule_label in table:
        flag = details.get(detail_key)
        if flag is None:
            continue
        if flag is not True:
            raise ValueError(
                f"{detail_key} must be True when present, got: {flag!r}"
            )
        tokens.append(f"[{rule_label}]")
    return tokens


def _anti_rule_token(details) -> str:
    """`[ANTI-INFANTRY:4+]` 24.03, suffixe du segment `Wound` — ou chaine vide.

    Le seuil ecrit est celui que l ARME DECLARE, jamais le `crit_wound_on` que le moteur en a
    tire : c est la seule forme sous laquelle l analyzer peut recouper la ligne avec
    l armurerie. Ecrire le chiffre du moteur reviendrait a lui faire verifier le moteur avec sa
    propre reponse — un vert vacant, exactement ce que la grammaire `[REGLE:X]` existe pour
    empecher (cf. `_additive_rule_tokens`).

    Le DOMAINE du seuil (Y+ >= 2, 05.02) appartient a `attack_sequence.anti_threshold_of`, qui
    le refuse a l entree du moteur. Le controle ci-dessous n est donc plus le premier a voir une
    armurerie fautive — il ne l aurait pas SIGNALEE : `log_action` avale toute exception du
    formateur, et la ligne d attaque disparaissait au lieu de lever. Il reste ici parce qu il
    verrouille le CONTRAT du token (ce fichier ne doit jamais ecrire `[ANTI-X:1+]`), pas la
    donnee.
    """
    anti_keyword = details.get("anti_keyword")
    if anti_keyword is None:
        return ""
    anti_threshold = require_key(details, "anti_threshold")
    if not isinstance(anti_threshold, int) or anti_threshold < 2:
        raise ValueError(
            f"anti_threshold must be an int >= 2 when anti_keyword is present, "
            f"got: {anti_threshold!r}"
        )
    return f" [ANTI-{anti_keyword}:{anti_threshold}+]"


def _save_segments(details, *, damage, save_result, ap_ability_token: str = "") -> list:
    """Segments `Save …` (+ `Dmg:` le cas echeant) d une attaque — TIR ET MELEE, un seul site.

    Trois etats, et un seul d entre eux comporte des chiffres :

    1. `Save [DEVASTATING WOUNDS]` — 24.10, « no saving throw can be made » : le moteur a SAUTE
       la sauvegarde, il le dit (`save_skipped` + motif). Ecrire un jet ici serait decrire un de
       qui n a jamais ete lance. La branche existait au TIR seulement : la melee imprimait
       `Save None(<seuil>+)`, c est-a-dire un jet inexistant sous un seuil reel.

    2. `Save [NOT ALLOCATED]` — l attaque n a jamais ete ALLOUEE a une figurine. Le seuil de
       sauvegarde n est ecrit qu a l allocation (`_resolve_one_manual_wound`) : sans elle, ni
       seuil ni resultat n existent. C est un etat de jeu LEGITIME (05 Attack sequence, « excess
       attacks lost » : la cible est detruite avant que le reste du pool ne soit resolu), et le
       moteur a raison de s arreter. Mesure du 2026-08-11 : **1 429 lignes sur 10 021 (14 %)**
       imprimaient `Save <jet>(None+)` ou `Save None(None+)` — un segment de sauvegarde
       entierement fabrique par le formateur, que les controles de conformite ne peuvent pas
       lire (ils cherchent des nombres) et qu ils sautaient donc EN SILENCE.

    3. Le cas normal : jet, seuil, relance et capacite d AP, puis les degats si la save echoue.
    """
    save_skipped = bool(details.get("save_skipped", False))
    if save_skipped and details.get("save_skip_reason") == "DEVASTATING_WOUNDS":
        return ["Save [DEVASTATING WOUNDS]", f"Dmg:{damage}HP"]
    if details.get("save_target") is None:
        return ["Save [NOT ALLOCATED]"]
    save_part = f"Save {details['save_roll']}({details['save_target']}+)"
    save_part += _rerolled_token(details, "save_roll_initial")
    save_part += ap_ability_token
    segments = [save_part]
    if save_result == "FAIL":
        segments.append(f"Dmg:{damage}HP")
    return segments


def _rerolled_token(details, field_name: str) -> str:
    """`` [REROLLED:1]`` quand le jet a ete RELANCE, chaine vide sinon.

    POURQUOI un token et pas `Hit 1->3(3+)` : l analyzer (`ai/analyzer_phases/shoot_handler.py`)
    et le parseur de replay (`frontend/src/utils/replayParser.ts`) lisent tous deux la forme
    `Hit N(T+)` par expression reguliere. Un token PARAMETRE accole au segment — meme forme que
    `[RAPID FIRE:2]` — porte le de d origine sans toucher a ce que ces deux consommateurs lisent.

    Sans lui, le nom de la capacite dit que la relance etait POSSIBLE ; seul le de d origine dit
    qu elle a EU LIEU, et ce qu elle a change.
    """
    initial = details.get(field_name)
    if not isinstance(initial, int):
        return ""
    return f" [REROLLED:{initial}]"


def _ability_token(display_name: Any) -> str:
    """`` [NOM DE CAPACITE]`` quand le nom d affichage est renseigne, chaine vide sinon.

    Meme forme que `_rerolled_token`, et extrait pour la meme raison : le triplet
    `isinstance / strip / upper` etait ecrit a l identique sur les DEUX formateurs (SHOT et
    FOUGHT), c est-a-dire sur la paire ou ce depot diverge. Le frontend (`GameLog.tsx`) accroche
    le tooltip de la regle sur cette forme, l analyzer y compte l usage.

    Ne couvre PAS les sites ou le nom est OBLIGATOIRE (reactive_move, move_after_shooting,
    charge_impact) : ceux-la levent avant de formater, l absence y est une erreur, pas un vide.
    """
    if not isinstance(display_name, str) or not display_name.strip():
        return ""
    return f" [{display_name.strip().upper()}]"


def _build_hit_suffix(details: Dict[str, Any], hit_ability_display_name: Any) -> str:
    """Suffixe commun du segment `Hit` — SHOOT et FOUGHT, meme ordre.

    Extrait pour que les deux formateurs ne divergent plus silencieusement : l ordre
    ``_HIT_SEGMENT_RULE_TOKENS`` / ``[REROLLED]`` / ``[SUSTAINED HITS]`` / ``_ability_token``
    etait encode deux fois et avait deja diverge une fois. SHOOT prefixe en plus
    ``[HEAVY]``/``[COVER]`` avant d appeler ce helper.
    """
    suffix = "".join(
        f" {tok}" for tok in _flag_rule_tokens(details, _HIT_SEGMENT_RULE_TOKENS)
    )
    suffix += _rerolled_token(details, "hit_roll_initial")
    if details.get("sustained_hit"):
        suffix += " [SUSTAINED HITS]"
    suffix += _ability_token(hit_ability_display_name)
    return suffix


def _charge_distance_segment(details: Dict[str, Any]) -> str:
    """`` [Dist: 5.0" | Nearest: 3.0"]`` — les deux distances 11.04 de cette charge.

    JUMEAU EXACT des lignes CHARGED et FAILED CHARGE : c'est en les comparant que la mesure
    parle (mediane des ratees a 9", des reussies a 5", sur le step.log du 2026-08-11), donc un
    segment pose d'un seul cote ne repondrait a rien.

    `Dist` = distance a la cible AU MOMENT DU CHOIX, `Nearest` = distance a l'ennemi le plus
    proche a la DECLARATION : leur ecart dit si l'agent charge autre chose que ce qu'il a sous
    la main. En POUCES, comme le `[Roll: N]` qui les precede sur la meme ligne.

    Chaque terme est omis s'il est absent, et l'absence est une information : une charge
    declaree qui n'atteint aucune cible (11.02.3) n'a pas de distance a la cible, et ecrire 0
    la ferait passer pour une charge au contact.
    """
    parts = []
    target_inches = details.get("charge_target_distance_inches")  # get allowed : cf. docstring
    nearest_inches = details.get("charge_nearest_enemy_inches")  # get allowed : cf. docstring
    if target_inches is not None:
        parts.append(f'Dist: {float(target_inches):.1f}"')
    if nearest_inches is not None:
        parts.append(f'Nearest: {float(nearest_inches):.1f}"')
    return f" [{' | '.join(parts)}]" if parts else ""


class StepLogger:
    """
    Step-by-step action logger for training debugging.
    Captures ALL actions that generate step increments per AI_TURN.md.
    """
    
    def __init__(self, output_file: str = "step.log", enabled: bool = False, buffer_size: Optional[int] = None, debug_mode: bool = False):
        self.output_file = output_file
        self.enabled = enabled
        self.debug_mode = debug_mode  # LOG TEMPORAIRE: timings/logs to debug.log only when --debug
        self.step_count = 0
        self.action_count = 0
        # Per-episode counters
        self.episode_step_count = 0
        self.episode_action_count = 0
        self.episode_number = 0  # Track episode number for logging
        self.current_bot_name: Optional[str] = None  # Set externally for bot-evaluation logging
        self._last_step_wall = None  # Wall-clock of last step end (for STEP_TIMING → analyzer "Step Durations")
        # PERFORMANCE: Buffer logs to reduce I/O (buffer_size from training_config step_log_buffer_size)
        # Obligatoire si enabled ; si disabled, buffer_size peut être None (non utilisé).
        if enabled and buffer_size is None:
            raise ValueError("buffer_size is required when step logging is enabled (from training_config step_log_buffer_size)")
        self.log_buffer = []
        self.buffer_size = buffer_size if buffer_size is not None else 0
        
        if self.enabled:
            # Clear existing log file
            with open(self.output_file, 'w') as f:
                f.write("=== STEP-BY-STEP ACTION LOG ===\n")
                f.write("AI_TURN.md COMPLIANCE: Actions that increment episode_steps are logged\n")
                f.write("INCREMENTED ACTIONS: move, shoot, charge, combat, wait (SUCCESS OR FAILURE)\n")
                f.write("NON-INCREMENTED: auto-skip ineligible units, phase transitions\n")
                f.write("FAILED ACTIONS: Still increment steps - unit consumed time/effort\n")
                f.write("=" * 80 + "\n\n")
            print(f"📝 Step logging enabled: {self.output_file}")
    
    @staticmethod
    def _objective_display_name(objective) -> str:
        """Cle d'une zone d'objectif dans le step.log.

        MEME cle pour la ligne `Objectives:` (geometrie, ecrite au demarrage d'episode) et pour
        les instantanes `OBJECTIVE CONTROL` (controle, ecrits en cours de partie) : le replay
        apparie les deux par ce nom (`replayParser.ts`). Deux calculs de cle divergents
        casseraient l'appariement en silence — d'ou l'unique implementation.
        """
        if "name" in objective:  # `in` allowed — le nom est optionnel dans les scenarios
            return objective["name"]
        return f"Obj{require_key(objective, 'id')}"

    def log_objective_control_snapshot(
        self, turn, objectives, objective_controllers, victory_points, command_points
    ):
        """Instantane FAISANT FOI du controle d'objectif, des VP et des CP (regles 14.02, 08.02).

        Ecrit l'etat que le MOTEUR a calcule (`objective_controllers`, `victory_points` et
        `command_points` du game_state), jamais un recalcul. Le replay le relit tel quel au lieu de resommer les OC
        cote navigateur : ni l'empreinte de socle par figurine (14.02) ni le drapeau
        `battle_shocked` (01.07 / 02.02, qui annule l'OC de toute l'escouade) ne sont
        reconstituables depuis le step.log, donc tout calcul cote client diverge par nature.

        Passe par `log_buffer` comme `log_action` : une ecriture directe dans le fichier
        s'intercalerait AVANT des actions encore bufferisees, et le replay lit ce journal dans
        l'ordre — l'instantane se retrouverait attache au mauvais point de la partie.

        Pas de `try/except` ici, contrairement au reste du module : cette ligne est la source de
        verite du replay. Une exception avalee produirait un flux d'instantanes tronque, donc un
        controle affiche perime — exactement le defaut que cette ligne corrige.
        """
        if not self.enabled:
            return

        timestamp = time.strftime("%H:%M:%S", time.localtime())
        zone_entries = []
        for objective in objectives:
            obj_id = str(require_key(objective, "id"))
            # get allowed : une cle absente = objectif jamais evalue (aucune frontiere de phase
            # franchie, 14.02) — c'est l'etat « personne ne controle », que le moteur lui-meme
            # initialise a None dans `calculate_objective_control`.
            controller = objective_controllers.get(obj_id)
            if controller is None:
                ctrl = "none"
            elif int(controller) in (1, 2):
                ctrl = str(int(controller))
            else:
                raise ValueError(f"Unexpected objective controller for {obj_id}: {controller!r}")
            zone_entries.append(f"{self._objective_display_name(objective)}:Ctrl={ctrl}")

        vp1 = require_key(victory_points, 1)
        vp2 = require_key(victory_points, 2)
        # Les CP sont ecrits APRES les VP et AVANT `ZONES=` : le parseur du replay les lit en
        # groupe OPTIONNEL, donc un step.log enregistre avant le 2026-08-04 reste lisible et
        # affiche simplement l'absence de CP — jamais un 0 fabrique, qui serait un mensonge sur
        # une partie ou le stock etait autre.
        cp1 = require_key(command_points, 1)
        cp2 = require_key(command_points, 2)
        line = (
            f"[{timestamp}] T{turn} OBJECTIVE CONTROL: "
            f"VP1={vp1} VP2={vp2} CP1={cp1} CP2={cp2} ZONES={'|'.join(zone_entries)}\n"
        )
        self.log_buffer.append(line)
        if len(self.log_buffer) >= self.buffer_size:
            self._flush_buffer()

    def log_effects_snapshot(self, turn, effects_by_player):
        """Effets de règle EN VIGUEUR, par joueur — avec leur CONTRIBUTION CHIFFRÉE.

        Format : ``T{tour} EFFECTS: P1 <clé>=<valeur> … | P2 <clé>=<valeur> …``

        POURQUOI CETTE LIGNE. Une capacité comme Waaagh! (24) est vraie pour une ARMÉE pendant un
        tour — pas pour une attaque. Elle était pourtant recopiée en token sur chaque ligne de
        mêlée, puis re-dérivée par expression régulière chez trois lecteurs. Coût déjà payé :
        poser ce token entre le verbe et la cible a cassé QUATRE grammaires de lecteurs, dont deux
        rattrapées par un code-review. Oath of Moment posait déjà la même question et se
        retrouvait dérivé une seconde fois, indépendamment, sur les lignes de charge.

        Et surtout : le nom seul obligeait le lecteur à RÉ-ENCODER la règle (« waaagh ⇒ +1 Force
        et +1 Attaques »). Deux définitions d'une même règle, dont l'une diverge en silence le
        jour où l'autre bouge. La ligne porte donc la valeur appliquée, exactement comme
        ``Run rules:`` porte la zone d'engagement réellement utilisée par le run : c'est une
        DÉCLARATION D'ÉTAT, jamais un verdict — le lecteur recalcule et compare.

        Conséquence directe : le volet **+1 Force** du Waaagh, jusqu'ici représenté nulle part,
        devient attribuable. Un seuil de blessure amélioré cesse d'être inexplicable.

        ÉMISE AU CHANGEMENT, pas à la frontière de tour. Le Waaagh se déclare en phase de
        COMMANDEMENT, donc pendant le tour : une ligne écrite à la frontière dirait « inactif »
        alors que la capacité s'allume ensuite. Même déclencheur, et pour la même raison, que
        ``log_objective_control_snapshot`` (dont les VP bougent aussi dans les handlers).

        ``effects_by_player`` : ``[(player, [(clé, valeur), …]), …]``. Un joueur sans aucun effet
        est écrit ``P{n} none`` — l'absence est alors DITE, et ne se confond pas avec une ligne
        tronquée.
        """
        if not self.enabled:
            return

        timestamp = time.strftime("%H:%M:%S", time.localtime())
        parts = []
        for player, entries in effects_by_player:
            body = " ".join(f"{key}={value}" for key, value in entries) if entries else "none"
            parts.append(f"P{player} {body}")
        line = f"[{timestamp}] T{turn} EFFECTS: {' | '.join(parts)}\n"
        self.log_buffer.append(line)
        if len(self.log_buffer) >= self.buffer_size:
            self._flush_buffer()

    def log_state_snapshot(self, turn, units_state):
        """Instantané d'ÉTAT du plateau à la fin d'un tour : socles vivants, positions, PV.

        POURQUOI CETTE LIGNE EXISTE. Tout lecteur du journal (analyzer, replay) reconstruit
        l'état par ACCUMULATION d'événements : PV initial, puis soustraction de chaque
        `Dmg:XHP` lu ; position initiale, puis application de chaque ligne de déplacement.
        Il n'existait AUCUN point de correction — une seule donnée manquante dérivait jusqu'à
        la fin de l'épisode.

        Ce n'est pas une hypothèse. Mesuré sur le run de 600 épisodes du 2026-08-08 :
          - 546 lignes portent une sauvegarde ratée SANS segment `Dmg:` (la blessure est
            écartée faute de figurine à qui l'allouer, la cible étant morte en cours de lot) :
            l'analyzer ne voyait jamais la mort et mesurait ensuite contre un fantôme, d'où
            76 « combat/charge/tir sur une unité morte » et 15 « Missing unit_hp on damage » ;
          - 229 chargeurs sur 319 changent de position entre leur ligne de charge et leur ligne
            de combat, sans aucune ligne de déplacement entre les deux.

        Ce que cette ligne change : la dérive devient BORNÉE (un tour) et MESURABLE — l'écart
        entre l'état reconstruit et celui-ci est lui-même un compteur d'erreur, qui se déclenche
        le jour où un nouvel effet cesse d'être journalisé. C'est le seul correctif du lot qui
        empêche le défaut de revenir au lieu de le réparer une fois.

        Format : ``T{tour} STATE: <uid>[<mid>@(col,row,z<hauteur>):<pv> ...] ...``
        Une unité SANS figurine vivante est absente de la ligne — l'absence EST la mort, et il
        n'y a donc rien à accorder entre deux informations concurrentes.

        Passe par ``log_buffer`` comme les autres lignes : une écriture directe s'intercalerait
        avant des actions encore bufferisées, et l'instantané se retrouverait attaché au mauvais
        point de la partie. Pas de `try/except`, pour la même raison que
        ``log_objective_control_snapshot`` : un instantané tronqué serait pire que pas
        d'instantané du tout, puisqu'il ferait passer une dérive pour un état constaté.
        """
        if not self.enabled:
            return

        timestamp = time.strftime("%H:%M:%S", time.localtime())
        # L'appelant (`_log_state_snapshot_if_turn_changed`) n'ajoute une unité que si elle a des
        # figurines, et a déjà normalisé les types : ni garde ni recast ici — deux contrats
        # possibles là où il n'y en a qu'un donneraient à croire que ce site peut être appelé
        # autrement.
        unit_entries = []
        for unit_id, models in units_state:
            model_parts = " ".join(
                f"{mid}@({col},{row},z{height:g}):{hp}"
                for mid, col, row, height, hp in models
            )
            unit_entries.append(f"{unit_id}[{model_parts}]")
        line = f"[{timestamp}] T{turn} STATE: {' '.join(unit_entries)}\n"
        self.log_buffer.append(line)
        if len(self.log_buffer) >= self.buffer_size:
            self._flush_buffer()

    def log_action(self, unit_id, action_type, phase, player, success, step_increment, action_details=None):
        """Log action with step increment information using clear format.

        Un parametre `step_calls_since_last` ajoutait un suffixe `step_calls=` a la ligne
        STEP_TIMING de debug.log. Son unique producteur etait le compteur
        `_step_calls_since_increment` du bloc step_logger de `W40KEngine._process_semantic_action`,
        supprime le 2026-07-29 parce qu'inatteignable : plus aucun appelant ne pouvait renseigner
        l'argument, donc le suffixe ne pouvait plus s'afficher. Pour retrouver ce diagnostic, le
        point d'accroche est `step()` (ou `_episode_step_calls` compte deja les appels), pas la
        journalisation.
        """
        # LOG TEMPORAIRE: Log when log_action is called for move actions (only if --debug)
        import time
        call_id = f"{time.time():.6f}_{id(self)}_{self.action_count}"
        if self.debug_mode and action_type == "move" and action_details:
            try:
                with open("debug.log", "a") as f:
                    f.write(f"[STEP_LOGGER log_action CALLED] ID={call_id} Unit {unit_id}: enabled={self.enabled} unit_with_coords={action_details.get('unit_with_coords')} end_pos={action_details.get('end_pos')} col={action_details.get('col')} row={action_details.get('row')}\n")
            except Exception:
                pass
        
        if not self.enabled:
            return
            
        self.action_count += 1
        self.episode_action_count += 1
        if step_increment:
            self.step_count += 1
            self.episode_step_count += 1
            # LOG TEMPORAIRE: STEP_TIMING → debug.log for analyzer "Step Durations" (only if --debug).
            # step_index = episode_step_count so it matches WRAPPER_STEP_TIMING (wrapper reads episode_steps after return).
            now = time.time()
            duration_s = (now - self._last_step_wall) if self._last_step_wall is not None else 0.0
            step_index = self.episode_step_count
            if self.debug_mode:
                try:
                    with open("debug.log", "a") as f_db:
                        f_db.write(f"STEP_TIMING episode={self.episode_number} step_index={step_index} duration_s={duration_s:.6f}\n")
                except Exception:
                    pass
            self._last_step_wall = now

        try:
            timestamp = time.strftime("%H:%M:%S", time.localtime())

            # Format message using gameLogUtils.ts style
            message = self._format_replay_style_message(unit_id, action_type, action_details)
            # Segment per-figurine [MODELS: <mid>@(c,r) ...] : positions par socle courantes,
            # source de verite pour l'analyzer (raisonnement par socle, pas par ancre). Ajoute
            # ICI, en un seul point, pour couvrir tous les types d'action. Absent/vide -> rien.
            if action_details is not None:
                _models_seg = action_details.get("models_segment")  # get allowed
                if _models_seg:
                    message = f"{message} {_models_seg}"
                # Segment cible [TARGET_MODELS:] (survivants per-figurine de la cible post-pertes,
                # tir/combat) : consomme UNIQUEMENT par le replay. Distinct de [MODELS:] pour ne
                # pas perturber l'analyzer (son regex \[MODELS: ne matche pas [TARGET_MODELS:).
                _target_models_seg = action_details.get("target_models_segment")  # get allowed
                if _target_models_seg:
                    message = f"{message} {_target_models_seg}"
                # Segment [SHOOTER_MODELS:] : figs de l'unite qui agit ayant EFFECTIVEMENT tire/frappe
                # dans cette action (sous-ensemble de [MODELS:]). Consomme UNIQUEMENT par le replay
                # (cercle vert + cone LoS restreints aux figs tireuses). Distinct de [MODELS:] pour ne
                # pas perturber l'analyzer (son regex \[MODELS: ne matche pas [SHOOTER_MODELS:).
                _shooter_models_seg = action_details.get("shooter_models_segment")  # get allowed
                if _shooter_models_seg:
                    message = f"{message} {_shooter_models_seg}"
                # Segment [ALLOC_MODEL: <mid>] : la figurine CIBLE a qui cette attaque a ete
                # allouee (05, « Allocate Attack »). Une ligne = un jet — verifie sur 144 022
                # lignes, aucune n'en porte deux — donc un seul socle par ligne, jamais une liste.
                #
                # Emis ICI, au meme point que les trois segments ci-dessus, et pour la meme
                # raison : les deux branches du formateur (SHOT et FOUGHT) sont la paire ou ce
                # depot diverge. Un token ecrit dans l'une et oublie dans l'autre laisserait la
                # melee (19 157 lignes du run de reference) sans la donnee que le tir aurait.
                #
                # NOM : ni `[TARGET_MODEL:` (prefixe de `[TARGET_MODELS:`, segment qui a deja
                # fausse deux verdicts de distance en s'y substituant), ni `[ALLOC:` (que l'oeil
                # confond avec le `Save [NOT ALLOCATED]` du meme journal).
                _alloc_model = action_details.get("target_model_id")  # get allowed
                if _alloc_model:
                    message = f"{message} [ALLOC_MODEL: {_alloc_model}]"


            # Standard format: [timestamp] TX PX PHASE : Message [SUCCESS/FAILED]
            success_status = "SUCCESS" if success else "FAILED"
            phase_upper = phase.upper()
            
            # Get turn and episode from SINGLE SOURCE OF TRUTH
            if action_details is None:
                raise ValueError("action_details is required to log current_turn")
            turn_number = require_key(action_details, 'current_turn')
            # Use self.episode_number which is updated in log_episode_start()
            episode_number = self.episode_number
            # Include episode in log line: [timestamp] E{episode} T{turn} P{player} PHASE : Message
            log_line = f"[{timestamp}] E{episode_number} T{turn_number} P{player} {phase_upper} : {message} [{success_status}]\n"
            # PERFORMANCE: Buffer logs and flush periodically to reduce I/O overhead
            self.log_buffer.append(log_line)
            if len(self.log_buffer) >= self.buffer_size:
                self._flush_buffer()
            
            # LOG TEMPORAIRE: Log what was actually written to step.log (only if --debug)
            if self.debug_mode and action_type == "move":
                try:
                    with open("debug.log", "a") as f_debug:
                        f_debug.write(f"[STEP_LOGGER AFTER WRITE] ID={call_id} Unit {unit_id}: log_line written={log_line.strip()}\n")
                except Exception:
                    pass
                
        except Exception as e:
            print(f"⚠️ Step logging error: {e}")
    
    def _flush_buffer(self):
        """Flush buffered logs to file"""
        if not self.enabled or not self.log_buffer:
            return
        try:
            # CRITICAL: Use builtins.open to ensure availability even if open is shadowed
            with builtins.open(self.output_file, 'a') as f:
                f.writelines(self.log_buffer)
            self.log_buffer = []
        except Exception as e:
            print(f"⚠️ Step logging flush error: {e}")
    
    def log_episode_start(self, units_data, scenario_info=None, bot_name=None, walls=None, objectives=None, primary_objective_config=None, roster_info=None, board_config=None, scenario_path=None, run_rules=None):
        """Log episode start with all unit starting positions, walls, and objectives

        ``scenario_path`` : chemin du scénario RÉELLEMENT tiré pour cet épisode, relatif à la
        racine du dépôt. C'est par lui que le replay retrouve le décor joué — ``scenario_info``
        vaut « Random from N scenarios » en entraînement et ne désigne aucun fichier
        (cf. Documentation/Implémentation/Replay.md §2.4).

        ``run_rules`` : les valeurs de règle que le moteur a RÉELLEMENT appliquées. Elles vivent
        dans `config/game_config.json`, que l'on édite entre deux runs : sans elles, l'analyzer
        relit un vieux journal avec les valeurs du jour et rend des verdicts faux EN SILENCE —
        basculer `distance_metric.engagement` de `hex` à `euclidean` change tous les verdicts
        d'engagement d'hier. Même raison que la ligne `Board:`, même remède.
        """
        if not self.enabled:
            return

        # PERFORMANCE: Flush any remaining buffered logs before episode start
        self._flush_buffer()

        self._episode_start_wall = time.perf_counter()
        self._last_step_wall = time.time()  # First step duration = time since episode start

        # Increment episode number
        self.episode_number += 1
        
        # Reset per-episode counters
        self.episode_step_count = 0
        self.episode_action_count = 0

        # Use bot_name parameter or fall back to current_bot_name attribute
        effective_bot_name = bot_name or getattr(self, 'current_bot_name', None)
        # Nom LISIBLE resolu ICI, AVANT le `try` : ce bloc avale ses exceptions (il degrade en
        # avertissement plutot que de casser un episode pour une ligne de journal), donc une cle
        # hors registre y disparaitrait en silence — l'en-tete perdrait sa ligne `Opponent:` sans
        # que rien ne le signale, exactement le mode d'echec que ce fichier a deja paye.
        opponent_display = bot_display_name(effective_bot_name) if effective_bot_name else None

        try:
            timestamp = time.strftime("%H:%M:%S", time.localtime())
            episode_marker = f"\n[{timestamp}] === EPISODE {self.episode_number} START ===\n"
            
            # Write to step.log: validate first (inside with open), then write so we never emit a partial header
            with open(self.output_file, 'a') as f:
                units_list = list(units_data)
                for unit in units_list:
                    if "id" not in unit:
                        raise KeyError("Unit missing required 'id' field")
                    if "col" not in unit:
                        raise KeyError(f"Unit {unit['id']} missing required 'col' field")
                    if "row" not in unit:
                        raise KeyError(f"Unit {unit['id']} missing required 'row' field")
                    if "player" not in unit:
                        raise KeyError(f"Unit {unit['id']} missing required 'player' field")
                    if "HP_MAX" not in unit:
                        raise KeyError(f"Unit {unit['id']} missing required 'HP_MAX' field")

                f.write(episode_marker)

                if scenario_info:
                    f.write(f"[{timestamp}] Scenario: {scenario_info}\n")
                if scenario_path:
                    f.write(f"[{timestamp}] Scenario file: {scenario_path}\n")
                if roster_info:
                    if not isinstance(roster_info, dict):
                        raise ValueError(f"roster_info must be dict when provided, got {type(roster_info).__name__}")
                    agent_roster_id = require_key(roster_info, "agent_roster_id")
                    opponent_roster_id = require_key(roster_info, "opponent_roster_id")
                    agent_roster_ref = require_key(roster_info, "agent_roster_ref")
                    opponent_roster_ref = require_key(roster_info, "opponent_roster_ref")
                    scale = require_key(roster_info, "scale")
                    # SIÈGE de l'agent (`controlled_player`). Sans lui, tout consommateur du
                    # journal suppose « agent == P1 » — ce que fait `ai/analyzer.py`, qui écrit
                    # « Agent (P1) » / « Bot (P2) » en dur. Or `controlled_player_mode` accepte
                    # `p2` et `random` (ai/train.py) : mesuré sur un run de 600 épisodes, l'agent
                    # occupait le siège P2 dans 180 d'entre eux, et l'analyzer y comptait ses
                    # victoires dans la colonne du bot — 33,3 % affichés pour 45,3 % réels.
                    # `bot_evaluation` (donc le gating) attribuait déjà juste, en lisant
                    # `controlled_player` ; c'est le seul consommateur qui n'avait pas la donnée.
                    agent_player = require_key(roster_info, "agent_player")
                    f.write(
                        f"[{timestamp}] Rosters: scale={scale} AGENT_PLAYER={agent_player} "
                        f"AGENT={agent_roster_id} ({agent_roster_ref}) "
                        f"OPPONENT={opponent_roster_id} ({opponent_roster_ref})\n"
                    )

                if opponent_display:
                    # Nom lu dans le registre, jamais fabrique ici : `capitalize() + "Bot"` ne
                    # tombait juste que sur les cles d'un seul mot et inventait `Value_tradeBot`
                    # ou `AlphaBot` pour les autres (cf. `bot_display_name`).
                    f.write(f"[{timestamp}] Opponent: {opponent_display}\n")

                # Log walls/obstacles for replay
                if walls:
                    wall_coords = ";".join([f"({w['col']},{w['row']})" for w in walls])
                    f.write(f"[{timestamp}] Walls: {wall_coords}\n")
                else:
                    f.write(f"[{timestamp}] Walls: none\n")

                # Log objectives for replay - format: name:(col,row);(col,row)|name2:(col,row);...
                if objectives:
                    obj_strs = []
                    for obj in objectives:
                        name = self._objective_display_name(obj)
                        hexes = require_key(obj, "hexes")
                        hex_coords = ";".join([f"({h[0]},{h[1]})" for h in hexes])
                        obj_strs.append(f"{name}:{hex_coords}")
                    f.write(f"[{timestamp}] Objectives: {'|'.join(obj_strs)}\n")
                else:
                    f.write(f"[{timestamp}] Objectives: none\n")

                rules_payload = {
                    "primary_objective": primary_objective_config
                }
                f.write(f"[{timestamp}] Rules: {json.dumps(rules_payload, separators=(',', ':'))}\n")

                if board_config is None:
                    raise ValueError("board_config is required for episode start logging")
                cols = require_key(board_config, "cols")
                rows = require_key(board_config, "rows")
                inches_to_subhex = require_key(board_config, "inches_to_subhex")
                hex_radius = require_key(board_config, "hex_radius")
                margin = require_key(board_config, "margin")
                f.write(f"[{timestamp}] Board: cols={cols} rows={rows} inches_to_subhex={inches_to_subhex} hex_radius={hex_radius} margin={margin}\n")
                # Pas de `if ... is not None` : l'analyzer REFUSE tout journal sans cette ligne.
                # La sauter en silence ferait tomber l'erreur des heures plus tard, chez le
                # consommateur, au lieu d'ici où le producteur est identifiable. Même exigence
                # que `board_config` juste au-dessus.
                if not isinstance(run_rules, dict) or not run_rules:
                    raise ValueError(
                        "log_episode_start: `run_rules` requis et non vide — l'analyzer refuse "
                        f"un journal sans entête `Run rules:` (reçu {run_rules!r})"
                    )
                _rules_txt = " ".join(f"{k}={v}" for k, v in sorted(run_rules.items()))
                f.write(f"[{timestamp}] Run rules: {_rules_txt}\n")
                # VERSION DE GRAMMAIRE — ce que le journal GARANTIT porter, pas ce qu'il porte
                # peut-être. Sans elle, l'absence de `[ALLOC_MODEL:]` sur une ligne de dégâts
                # serait indécidable : vieux journal, ou ligne que le moteur a oublié d'annoter ?
                # Le lecteur devrait alors retomber en silence sur son ancienne devinette — le
                # repli qui masque une panne, exactement ce que ce dépôt s'interdit.
                # Déclarée ici, elle rend le token EXIGIBLE : sur un journal `log_grammar=2`,
                # une ligne qui applique des dégâts sans nommer sa figurine est une ERREUR.
                #   1 = grammaire d'avant le 2026-08-12 (aucune figurine allouée nommée)
                #   2 = `[ALLOC_MODEL: <mid>]` sur toute attaque parvenue à l'allocation
                f.write(f"[{timestamp}] Log grammar: {LOG_GRAMMAR_VERSION}\n")

                # Log all unit starting positions (already validated above)
                for unit in units_list:
                    unit_type = require_key(unit, "unitType")
                    display_name = unit.get("DISPLAY_NAME")
                    display_suffix = f" [{display_name}]" if isinstance(display_name, str) and display_name.strip() else ""
                    player_name = f"P{unit['player']}"
                    hp_max = require_key(unit, "HP_MAX")
                    base_shape = require_key(unit, "BASE_SHAPE")
                    base_size = require_key(unit, "BASE_SIZE")
                    base_info = f" base={base_shape}/{base_size}" if base_size != 1 else ""
                    # Segment per-figurine initial [MODELS:] (positions de deploiement par socle) :
                    # meme source de verite que les lignes d'action -> le replay affiche tous les
                    # socles des le debut. Absent/vide -> rien (mono-fig sans cache exploitable).
                    models_seg = unit.get("models_segment")  # get allowed
                    models_suffix = f" {models_seg}" if models_seg else ""
                    # DATASHEET PAR FIGURINE. Une escouade n'est pas homogène : la règle 19
                    # (Attached units) y replie un personnage COMME figurine, et le roster y met
                    # sergents et armes spéciales. Le type d'ESCOUADE ne décrit donc pas chaque
                    # socle, et tout ce qui se calcule par figurine à partir de lui est faux.
                    # Mesuré sur le run de 600 épisodes : « Attacks over CC_NB » remontait 20
                    # lignes, dont 5 attaques d'un Ancient rattaché (arme NB=5, ATK=2 — le journal
                    # affiche bien `Hit x(2+)`) plafonnées au NB=3 de l'Intercessor porteur, et
                    # 20 attaques de 10 Gretchin plafonnées à 10. Le nom d'affichage de l'arme ne
                    # suffit pas à trancher : cinq armes distinctes s'appellent « Close Combat
                    # Weapon », de NB 2 à 6. Seul le type de la FIGURINE le fait.
                    types_seg = unit.get("model_types_segment")  # get allowed
                    types_suffix = f" {types_seg}" if types_seg else ""
                    f.write(
                        f"[{timestamp}] Unit {unit['id']} ({unit_type}){display_suffix} {player_name}: "
                        f"Starting position ({unit['col']},{unit['row']}), HP_MAX={hp_max}{base_info}"
                        f"{models_suffix}{types_suffix}\n"
                    )

                f.write(f"[{timestamp}] === ACTIONS START ===\n")
            
                
        except Exception as e:
            print(f"⚠️ Episode start logging error: {e}")

    def _format_display_name_suffix(self, details, field_name):
        """Format optional display name suffix for step log readability."""
        if not isinstance(details, dict):
            return ""
        display_name = details.get(field_name)
        if isinstance(display_name, str) and display_name.strip():
            return f" [{display_name}]"
        return ""
    
    def _format_replay_style_message(self, unit_id, action_type, details):
        """Format messages with detailed combat info - enhanced replay format"""
        # CRITICAL: Handle None details gracefully
        if details is None:
            details = {}
        
        # Extract unit coordinates from action_details for consistent format
        unit_coords = ""
        if details and "unit_with_coords" in details:
            # Extract coordinates from format "3(12, 7)" -> "(12, 7)"
            coords_part = details["unit_with_coords"]
            if "(" in coords_part:
                coord_start = coords_part.find("(")
                unit_coords = coords_part[coord_start:]
        unit_label = f"Unit {unit_id}{unit_coords}"
        
        if action_type == "move" and details:
            # Extract position info for move message
            if "start_pos" in details and details["start_pos"] is not None and "end_pos" in details and details["end_pos"] is not None:
                start_col, start_row = details["start_pos"]
                end_col, end_row = details["end_pos"]
                # LOG TEMPORAIRE: Log exact values in _format_replay_style_message to debug.log (only if --debug)
                if self.debug_mode:
                    try:
                        with open("debug.log", "a") as f:
                            f.write(f"[STEP_LOGGER DEBUG] Unit {unit_id}: unit_coords={unit_coords} start_pos=({start_col},{start_row}) end_pos=({end_col},{end_row}) unit_with_coords={details.get('unit_with_coords')} col={details.get('col')} row={details.get('row')}\n")
                    except Exception:
                        pass  # Don't fail if logging fails
                is_fly_move = details.get("is_fly_move") is True
                if is_fly_move:
                    base_msg = f"{unit_label} MOVED [FLY] from ({start_col},{start_row}) to ({end_col},{end_row})"
                else:
                    base_msg = f"{unit_label} MOVED from ({start_col},{start_row}) to ({end_col},{end_row})"
            elif "col" in details and "row" in details:
                # Use destination coordinates from mirror_action
                base_msg = f"{unit_label} MOVED to ({details['col']},{details['row']})"
            else:
                raise KeyError("Move action missing required position data")

            # Add position reward if available (like shooting reward)
            reward = details.get("reward")
            if reward is not None:
                base_msg += f"[R:{reward:+.1f}]"

            return base_msg

        elif action_type == "reactive_move" and details:
            if (
                "start_pos" in details
                and details["start_pos"] is not None
                and "end_pos" in details
                and details["end_pos"] is not None
            ):
                start_col, start_row = details["start_pos"]
                end_col, end_row = details["end_pos"]
                trigger_unit_id = require_key(details, "triggered_by_unit_id")
                trigger_to = require_key(details, "trigger_to_pos")
                if not isinstance(trigger_to, tuple) or len(trigger_to) != 2:
                    raise ValueError(
                        f"reactive_move trigger_to_pos must be tuple(col,row), got {trigger_to}"
                    )
                trigger_to_col, trigger_to_row = trigger_to
                range_roll = require_key(details, "range_roll")
                if not isinstance(range_roll, int) or isinstance(range_roll, bool):
                    raise ValueError(
                        f"reactive_move range_roll must be int, got {type(range_roll).__name__}: {range_roll!r}"
                    )
                ability_display_name = require_key(details, "ability_display_name")
                if not isinstance(ability_display_name, str) or not ability_display_name.strip():
                    raise ValueError(
                        f"reactive_move ability_display_name must be non-empty for unit {unit_id}, got {ability_display_name!r}"
                    )
                base_msg = (
                    f"{unit_label} REACTIVE MOVED [{ability_display_name.strip().upper()}] from ({start_col},{start_row}) "
                    f"to ({end_col},{end_row}) [Roll: {range_roll}] - trigger: Unit {trigger_unit_id}"
                    f"->({trigger_to_col},{trigger_to_row})"
                )
            else:
                raise KeyError("Reactive_move action missing required position data")

            reward = details.get("reward")
            if reward is not None:
                base_msg += f" [R:{reward:+.1f}]"

            return base_msg

        elif action_type == "flee" and details:
            # FLEE: Unit flees from enemy (same format as move but indicates flee)
            if "start_pos" in details and details["start_pos"] is not None and "end_pos" in details and details["end_pos"] is not None:
                start_col, start_row = details["start_pos"]
                end_col, end_row = details["end_pos"]
                _fly_seg = " [FLY]" if details.get("is_fly_move") is True else ""
                base_msg = f"{unit_label} FLED{_fly_seg} from ({start_col},{start_row}) to ({end_col},{end_row})"
            elif "col" in details and "row" in details:
                # Use destination coordinates
                base_msg = f"{unit_label} FLED to ({details['col']},{details['row']})"
            else:
                raise KeyError("Flee action missing required position data")

            # Add position reward if available
            reward = details.get("reward")
            if reward is not None:
                base_msg += f" [R:{reward:+.1f}]"

            return base_msg

        elif action_type == "advance" and details:
            # ADVANCE_IMPLEMENTATION: Format advance action message
            if "start_pos" in details and details["start_pos"] is not None and "end_pos" in details and details["end_pos"] is not None:
                start_col, start_row = details["start_pos"]
                end_col, end_row = details["end_pos"]
                advance_range = details.get("advance_range")
                # `[Strategy: <label>]` SUPPRIMÉ le 2026-08-11 : le segment annonçait un choix
                # tactique (aggressive/tactical/defensive/objective) que RIEN ne calculait.
                # `details["advance_strategy"]` n'avait aucun producteur dans tout le dépôt —
                # ni moteur, ni gym, ni frontend — et deux valeurs par défaut, ici et dans
                # l'analyzer, écrivaient « aggressive » à chaque advance. Le rapport en tirait
                # « Advance : 100 % aggressive », une donnée inventée sur 12 163 advances.
                _fly_seg = " [FLY]" if details.get("is_fly_move") is True else ""
                if advance_range is not None and advance_range > 0:
                    base_msg = f"{unit_label} ADVANCED{_fly_seg} from ({start_col},{start_row}) to ({end_col},{end_row}) [Roll: {advance_range}]"
                else:
                    base_msg = f"{unit_label} ADVANCED{_fly_seg} from ({start_col},{start_row}) to ({end_col},{end_row})"
            else:
                raise KeyError("Advance action missing required position data")

            # Add reward if available
            reward = details.get("reward")
            if reward is not None:
                base_msg += f" [R:{reward:+.1f}]"

            return base_msg

        elif action_type == "move_after_shooting" and details:
            if "start_pos" not in details or details["start_pos"] is None:
                raise KeyError("Move_after_shooting action missing required start_pos")
            if "end_pos" not in details or details["end_pos"] is None:
                raise KeyError("Move_after_shooting action missing required end_pos")
            start_col, start_row = details["start_pos"]
            end_col, end_row = details["end_pos"]
            ability_display_name = details.get("ability_display_name")
            if not isinstance(ability_display_name, str) or not ability_display_name.strip():
                raise KeyError("Move_after_shooting action missing required ability_display_name")
            source_rule_id = details.get("source_rule_id")
            if not isinstance(source_rule_id, str) or not source_rule_id.strip():
                raise KeyError("Move_after_shooting action missing required source_rule_id")
            base_msg = (
                f"{unit_label} MOVED AFTER SHOOTING [{ability_display_name.strip().upper()}] "
                f"from ({start_col},{start_row}) to ({end_col},{end_row})"
            )
            return base_msg

        elif action_type == "deploy_unit" and details:
            if (
                "start_pos" in details
                and details["start_pos"] is not None
                and "end_pos" in details
                and details["end_pos"] is not None
            ):
                start_col, start_row = details["start_pos"]
                end_col, end_row = details["end_pos"]
                base_msg = f"{unit_label} DEPLOYED from ({start_col},{start_row}) to ({end_col},{end_row})"
            else:
                raise KeyError("Deploy action missing required position data")

            reward = details.get("reward")
            if reward is not None:
                base_msg += f" [R:{reward:+.1f}]"

            return base_msg
                
        elif action_type == "coherency_removal" and details:
            # 03.03 End of Turn. Le VERBE est `COHERENCY REMOVED` et non `REMOVED` seul : les
            # aiguillages de l'analyzer testent des verbes entoures d'espaces (` MOVED `,
            # ` FLED `...), et un verbe trop generique risquerait de capter une autre ligne.
            removed = details.get("removed_models")  # get allowed
            if not isinstance(removed, list) or not removed:
                raise KeyError("Coherency_removal action missing required removed_models")
            return f"{unit_label} COHERENCY REMOVED {' '.join(str(m) for m in removed)} (03.03)"

        elif action_type == "strategic_reserves_timeout":
            # 20.04 — destruction fin de 3e round. L'escouade est ENTIEREMENT detruite : le
            # segment [MODELS:] sera vide (units_cache n'a plus d'entree pour elle), ce qui est
            # semantiquement correct — le lecteur voit la disparition totale de l'escouade.
            # Le verbe `RESERVES TIMEOUT` est distinct et unique : aucun autre type de mort
            # ne le porte, l'analyzer peut l'aiguiller sans risque de collision.
            return f"{unit_label} RESERVES TIMEOUT (20.04)"

        elif action_type == "shoot":
            if "target_id" not in details:
                raise KeyError("Shoot action missing required target_id")
            if "hit_roll" not in details:
                raise KeyError("Shoot action missing required hit_roll")
            if "wound_roll" not in details:
                raise KeyError("Shoot action missing required wound_roll")
            if "save_roll" not in details:
                raise KeyError("Shoot action missing required save_roll")
            if "damage_dealt" not in details:
                raise KeyError("Shoot action missing required damage_dealt")
            if "hit_result" not in details:
                raise KeyError("Shoot action missing required hit_result")
            if "wound_result" not in details:
                raise KeyError("Shoot action missing required wound_result")
            if "save_result" not in details:
                raise KeyError("Shoot action missing required save_result")
            if "hit_target" not in details:
                raise KeyError("Shoot action missing required hit_target")
            if "wound_target" not in details:
                raise KeyError("Shoot action missing required wound_target")
            if "save_target" not in details:
                raise KeyError("Shoot action missing required save_target")
            
            target_id = details["target_id"]
            hit_roll = details["hit_roll"]
            wound_roll = details["wound_roll"]
            save_roll = details["save_roll"]
            damage = details["damage_dealt"]
            hit_result = details["hit_result"]
            wound_result = details["wound_result"]
            save_result = details["save_result"]
            
            hit_target = details["hit_target"]
            hit_target_base = details.get("hit_target_base")
            hit_rule_modifier = details.get("hit_rule_modifier")
            wound_target = details["wound_target"]
            save_target = details["save_target"]
            save_skipped = bool(details.get("save_skipped", False))
            save_skip_reason = details.get("save_skip_reason")
            rapid_fire_bonus_shot = bool(details.get("rapid_fire_bonus_shot", False))
            assault_applied = bool(details.get("assault_applied", False))
            close_quarters_applied = bool(details.get("close_quarters_applied", False))
            hazardous_test_required = bool(details.get("hazardous_test_required", False))
            hazardous_test_roll = details.get("hazardous_test_roll")
            
            # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Include weapon name
            weapon_name = details.get("weapon_name")
            target_coords = details.get("target_coords")
            target_coords_str = f"({target_coords[0]},{target_coords[1]})" if target_coords else ""
            target_label = f"Unit {target_id}{target_coords_str}"
            wound_ability_display_name = details.get("wound_ability_display_name")
            # JUMEAU du precedent, cote TOUCHE (chantier 03) : nom de la capacite qui a ouvert
            # la relance du jet de touche, quand elle a EFFECTIVEMENT eu lieu.
            hit_ability_display_name = details.get("hit_ability_display_name")
            ap_modifier_ability_display_name = details.get("ap_modifier_ability_display_name")
            
            shot_tags = []
            if assault_applied:
                shot_tags.append("[ASSAULT]")
            if close_quarters_applied:
                shot_tags.append("[CLOSE-QUARTERS]")
            if rapid_fire_bonus_shot:
                rapid_fire_rule_value = require_key(details, "rapid_fire_rule_value")
                if not isinstance(rapid_fire_rule_value, int) or rapid_fire_rule_value <= 0:
                    raise ValueError(
                        "rapid_fire_bonus_shot=True requires rapid_fire_rule_value as a positive int, "
                        f"got: {rapid_fire_rule_value}"
                    )
                shot_tags.append(f"[RAPID FIRE:{rapid_fire_rule_value}]")
            # [MELTA:X] 24.25 : meme grammaire que [RAPID FIRE:X] — X est le parametre DECLARE
            # par l arme, jamais le total. Le token n est pose que si le moteur a applique le
            # bonus (cible a demi-portee) : `melta_rule_value` n existe pas sinon.
            melta_rule_value = details.get("melta_rule_value")
            if melta_rule_value is not None:
                if not isinstance(melta_rule_value, int) or melta_rule_value <= 0:
                    raise ValueError(
                        "melta_rule_value must be a positive int when present, "
                        f"got: {melta_rule_value}"
                    )
                shot_tags.append(f"[MELTA:{melta_rule_value}]")
            shot_tags.extend(_additive_rule_tokens(details))
            # [EXTRA ATTACKS] 24.11 : MEME site et MEME table qu en melee, ou la regle vit
            # surtout. Le token se range avec les tags de ligne (et non sur un jet) parce qu il
            # decrit le GROUPE d attaques, comme [RAPID FIRE:X] et [BLAST:X].
            shot_tags.extend(_flag_rule_tokens(details, _LINE_TAG_RULE_TOKENS))
            # [PRECISION] 24.28 : drapeau sans parametre — meme regime que les precedents, le
            # token n est pose que si le moteur a applique la regle.
            if details.get("precision_applied") is True:
                shot_tags.append("[PRECISION]")
            shot_tags_suffix = f" {' '.join(shot_tags)}" if shot_tags else ""
            if weapon_name:
                base_msg = f"{unit_label} SHOT{shot_tags_suffix} {target_label} with [{weapon_name}]"
            else:
                base_msg = f"{unit_label} SHOT{shot_tags_suffix} {target_label}"
            # Tokens du cote TOUCHE : [HEAVY] 24.16 (+1 au jet) et [COVER] 13.08 (-1 au jet —
            # dans ce moteur le couvert degrade le SEUIL DE TOUCHE, pas la sauvegarde, cf.
            # `_cover_worsened_bs`). Meme mecanique pour les deux : token + affichage
            # `base+->effectif+`. Le frontend y accroche le tooltip de la regle (GameLog.tsx),
            # l analyzer y compte l usage.
            hit_rule_suffix = (
                f" [{hit_rule_modifier}]" if hit_rule_modifier in ("HEAVY", "COVER") else ""
            )
            hit_rule_suffix += _build_hit_suffix(details, hit_ability_display_name)
            if hit_rule_modifier in ("HEAVY", "COVER") and isinstance(hit_target_base, int):
                hit_target_display = f"{hit_target_base}+->{hit_target}+"
            else:
                hit_target_display = f"{hit_target}+"
            detail_parts = [f"Hit {hit_roll}({hit_target_display}){hit_rule_suffix}"]
            if hit_result == "HIT":
                # [LETHAL HITS] 24.23 puis [ANTI-X Y+] 24.03 : MEME table et MEME helper qu en
                # melee. En tete du suffixe, avant les capacites d unite, comme du cote touche.
                wound_suffix = "".join(
                    f" {tok}" for tok in _flag_rule_tokens(details, _WOUND_SEGMENT_RULE_TOKENS)
                )
                wound_suffix += _anti_rule_token(details)
                wound_suffix += _ability_token(wound_ability_display_name)
                # Regle d ARME ayant ouvert la relance ([TWIN-LINKED] 24.38) : `wound_ability`
                # ne nomme que les capacites d UNITE, si bien qu une relance d arme laissait
                # `Wound 5(4+) [REROLLED:1]` sans aucune cause — l asymetrie exacte que le
                # Game Log PvP vient de fermer, et qui vaut ici aussi.
                wound_suffix += _ability_token(details.get("wound_reroll_rule_name"))
                # MODIFICATEUR de blessure (+1 d Oath) : le seuil affiche est deja net, donc sans
                # ce token step.log montrait un `Wound x(3+)` ameliore sans cause visible — alors
                # que la relance de TOUCHE, elle, etait nommee. Champ distinct de la relance : les
                # deux peuvent apparaitre sur la meme attaque.
                wound_suffix += _ability_token(details.get("wound_bonus_ability_display_name"))
                wound_suffix += _rerolled_token(details, "wound_roll_initial")
                detail_parts.append(
                    f"Wound {wound_roll}({wound_target}+){wound_suffix}"
                )
                if wound_result in ("WOUND", "SUCCESS"):
                    # Le couvert ne touche PAS la sauvegarde dans ce moteur : 13.08 y degrade le
                    # SEUIL DE TOUCHE (`_cover_worsened_bs`), et le token [COVER] est rendu de ce
                    # cote-la (plus haut). L ancienne branche `save_cover_applied` /
                    # `save_target_base` portait le modele du code mort de tir et n avait plus
                    # aucun producteur (V11 §0hist.38).
                    detail_parts.extend(_save_segments(
                        details, damage=damage, save_result=save_result,
                        ap_ability_token=_ability_token(ap_modifier_ability_display_name),
                    ))
            detail_msg = f" - {' - '.join(detail_parts)}"
            if hazardous_test_required:
                if not isinstance(hazardous_test_roll, int) or hazardous_test_roll < 1 or hazardous_test_roll > 6:
                    raise ValueError(
                        f"hazardous_test_required=True but hazardous_test_roll is invalid: {hazardous_test_roll}"
                    )
                detail_msg += f" [HAZARDOUS] Roll:{hazardous_test_roll}"
            
            # Add reward if available
            reward = details.get("reward")
            if reward is not None:
                detail_msg += f" [R:{reward:+.1f}]"
            
            return base_msg + detail_msg

        elif action_type == "hazardous":
            unit_with_coords = details.get("unit_with_coords")
            if not isinstance(unit_with_coords, str) or not unit_with_coords:
                raise KeyError("Hazardous action missing required unit_with_coords")
            hazardous_mortal_wounds = require_key(details, "hazardous_mortal_wounds")
            return f"Unit {unit_with_coords} SUFFERS {hazardous_mortal_wounds} Mortal Wounds [HAZARDOUS]"
            
        elif action_type == "shoot_summary":
            # Summary of multi-shot sequence
            if "target_id" not in details:
                raise KeyError("Shoot summary missing required target_id")
            if "total_shots" not in details or "total_damage" not in details:
                raise KeyError("Shoot summary missing required total_shots or total_damage")
                
            target_id = details["target_id"]
            total_shots = details["total_shots"]
            total_damage = details["total_damage"]
            hits = details.get("hits")
            wounds = details.get("wounds")
            failed_saves = details.get("failed_saves")
            
            target_coords = details.get("target_coords")
            target_coords_str = f"({target_coords[0]},{target_coords[1]})" if target_coords else ""
            return f"Unit {unit_id}{unit_coords} SHOOTING COMPLETE at Unit {target_id}{target_coords_str} - {total_shots} shots, {hits} hits, {wounds} wounds, {failed_saves} failed saves, {total_damage} total damage"
            
        elif action_type == "charge" and details:
            if "target_id" in details:
                target_id = details["target_id"]
                if "start_pos" in details and details["start_pos"] is not None and "end_pos" in details and details["end_pos"] is not None:
                    start_col, start_row = details["start_pos"]
                    end_col, end_row = details["end_pos"]
                    # Include target coordinates if available
                    target_coords = details.get("target_coords")
                    target_coords_str = f"({target_coords[0]},{target_coords[1]})" if target_coords else ""
                    target_label = f"Unit {target_id}{target_coords_str}"
                    # Include charge roll (2d6) if available
                    charge_roll = details.get("charge_roll")
                    ability_suffix = _ability_token(details.get("ability_display_name"))
                    # 21.03 : vol DÉCLARÉ pour cette charge. Le moteur en retranche 2" au budget
                    # (`_charge_budget_subhex`) et autorise la traversée — sans le marqueur ici,
                    # l'analyzer juge la charge avec un budget faux et des murs qui ne
                    # s'appliquent pas. Ce formateur réécrit intégralement la ligne : le marqueur
                    # posé sur le `message` de l'action_log moteur ne sert QUE au replay/PvP et
                    # n'atteint jamais step.log.
                    _fly_seg = " [FLY]" if details.get("is_fly_move") is True else ""
                    if charge_roll is not None:
                        base_msg = (
                            f"{unit_label} CHARGED{ability_suffix}{_fly_seg} {target_label} "
                            f"from ({start_col},{start_row}) to ({end_col},{end_row}) [Roll: {charge_roll}]"
                        )
                    else:
                        base_msg = (
                            f"{unit_label} CHARGED{ability_suffix}{_fly_seg} {target_label} "
                            f"from ({start_col},{start_row}) to ({end_col},{end_row})"
                        )
                else:
                    base_msg = f"{unit_label} CHARGED Unit {target_id}"
            else:
                base_msg = f"{unit_label} CHARGED"

            base_msg += _charge_distance_segment(details)

            # Add reward if available
            reward = details.get("reward")
            if reward is not None:
                base_msg += f" [R:{reward:+.1f}]"

            return base_msg

        elif action_type == "charge_fail" and details:
            # Charge failed because roll was too low
            charge_roll = details.get("charge_roll")
            require_key(details, "charge_failed_reason")
            if charge_roll is None:
                raise KeyError("Charge_fail action missing required charge_roll")
            if not isinstance(charge_roll, int) or isinstance(charge_roll, bool):
                raise ValueError(
                    f"charge_roll must be int for charge_fail, got {type(charge_roll).__name__}: {charge_roll!r}"
                )
            # DEUX ECHECS DE CHARGE, ET UN SEUL PORTE UNE CIBLE. 11.02 les distingue : le jet peut
            # etre insuffisant pour la cible CHOISIE (`no valid charge plan for roll`), ou
            # n'amener AUCUNE cible a portee — l'escouade a declare (11.02.1) puis n'a rien pu
            # viser, il n'y a donc pas de cible a nommer. `target_id` et `target_coords` etaient
            # exiges par `require_key` : le second cas levait, et `log_action` avale ses
            # exceptions, si bien que la ligne n'atteignait JAMAIS step.log. Ni le chemin gym
            # (`_process_squad_action`, squad_wait) ni le chemin PvP (`charge_handlers`, branche
            # « too short to reach any target ») n'etaient donc journalises — d'ou un
            # `n_charge_success_rate` bloque a 1.000 sur tout un run de 50 000 episodes.
            target_id = details.get("target_id")
            target_coords = details.get("target_coords")
            if target_id is None:
                base_msg = f"{unit_label} FAILED CHARGE - no target within reach [Roll: {charge_roll}]"
            else:
                if target_coords is None:
                    raise KeyError("Charge_fail action missing required target_coords")
                if not isinstance(target_coords, tuple) or len(target_coords) != 2:
                    raise ValueError(
                        f"Charge_fail target_coords must be tuple(col,row), got {target_coords!r}"
                    )
                target_col, target_row = target_coords
                base_msg = (
                    f"{unit_label} FAILED CHARGE to unit {target_id}({target_col},{target_row}) "
                    f"[Roll: {charge_roll}]"
                )
            base_msg += _charge_distance_segment(details)

            return base_msg

        elif action_type == "charge_impact" and details:
            target_id = require_key(details, "target_id")
            roll_value = require_key(details, "impact_roll")
            threshold = require_key(details, "impact_threshold")
            hit_result = require_key(details, "impact_hit_result")
            mortal_wounds = require_key(details, "mortal_wounds")
            ability_display_name = require_key(details, "ability_display_name")
            target_coords = require_key(details, "target_coords")
            if not isinstance(target_coords, tuple) or len(target_coords) != 2:
                raise ValueError(
                    f"charge_impact target_coords must be tuple(col,row), got {target_coords!r}"
                )
            target_col, target_row = target_coords
            if not isinstance(hit_result, str) or hit_result not in ("HIT", "FAIL"):
                raise ValueError(
                    f"charge_impact impact_hit_result must be 'HIT' or 'FAIL', got {hit_result!r}"
                )
            if not isinstance(ability_display_name, str) or not ability_display_name.strip():
                raise ValueError(
                    f"charge_impact ability_display_name must be non-empty for unit {unit_id}"
                )
            base_msg = (
                f"{unit_label} IMPACTED [{ability_display_name.strip().upper()}] "
                f"Unit {target_id}({target_col},{target_row}) - "
                f"Hit:{threshold}+:{roll_value}({hit_result})"
            )
            if hit_result == "HIT":
                base_msg += f" Wound:AUTO Save:NONE[MW] Dmg:{mortal_wounds}HP"
            reward = details.get("reward")
            if reward is not None:
                base_msg += f" [R:{reward:+.1f}]"
            return base_msg

        elif action_type == "combat":
            if "target_id" not in details:
                return f"Unit {unit_id}{unit_coords} FOUGHT (no target data)"
            
            target_id = details["target_id"]
            
            # Check if all required dice data is present - if not, return simple message
            required_fields = ["hit_roll", "wound_roll", "save_roll", "damage_dealt", "hit_result", "wound_result", "save_result", "hit_target", "wound_target", "save_target"]
            if not all(field in details for field in required_fields):
                return f"Unit {unit_id}{unit_coords} FOUGHT Unit {target_id} (dice data incomplete)"
            
            # All dice data present - format detailed message
            hit_roll = details["hit_roll"]
            wound_roll = details["wound_roll"]
            save_roll = details["save_roll"]
            damage = details["damage_dealt"]
            hit_result = details["hit_result"]
            wound_result = details["wound_result"]
            save_result = details["save_result"]
            hit_target = details["hit_target"]
            wound_target = details["wound_target"]
            save_target = details["save_target"]
            # Pas de couvert en melee : 13.08 (« Benefit of Cover ») est ranged-only. Les
            # variables `save_cover_applied` / `save_target_base` de cette branche etaient
            # mortes deux fois — regle inapplicable ET plus aucun producteur (V11 §0hist.38).
            wound_ability_display_name = details.get("wound_ability_display_name")
            # JUMEAU du tir, cote TOUCHE (chantier 03) : Oath of Moment relance en melee aussi.
            hit_ability_display_name = details.get("hit_ability_display_name")
            
            # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Include weapon name
            weapon_name = details.get("weapon_name")
            target_coords = details.get("target_coords")
            target_coords_str = f"({target_coords[0]},{target_coords[1]})" if target_coords else ""
            target_label = f"Unit {target_id}{target_coords_str}"
            
            # WAAAGH! : « add 1 to the Strength and Attacks characteristics of melee weapons ».
            # Les deux moitiés sont appliquées par le moteur, mais RIEN ne le disait ici. Mesuré
            # sur le run de 600 épisodes : un WarTrakk (Choppa NB=5) portait 6 attaques — le
            # plafond recalculé par l'analyzer était inférieur d'un cran et remontait « Attacks
            # over CC_NB », pendant que « 1.7 Special rules usage » affichait 0 utilisation de
            # `waaagh`. Le token est posé sur la LIGNE d'attaque, comme [SUSTAINED HITS] : c'est
            # à cette granularité que le plafond se compte.
            _waaagh_seg = " [WAAAGH!]" if details.get("waaagh_melee") else ""
            # [CLEAVE:X] 24.06 — MEME site et MEME helper que [BLAST:X] au tir. Comme [WAAAGH!],
            # le token vit sur la LIGNE d'attaque : c'est la granularite a laquelle le plafond
            # d'attaques se compte, et sans lui les des additionnels de la regle etaient comptes
            # comme des attaques en trop (24 faux positifs mesures le 2026-08-11).
            _waaagh_seg += "".join(f" {tok}" for tok in _additive_rule_tokens(details))
            # [EXTRA ATTACKS] 24.11 — JUMEAU du tir, et c est ici que la regle vit reellement :
            # elle designe une arme de melee resolue EN PLUS des autres. Sans le token, ses
            # attaques se comptent dans le plafond de la figurine et ressortent en « Attacks
            # over CC_NB » — le faux positif deja paye par [CLEAVE] et [WAAAGH!].
            _waaagh_seg += "".join(
                f" {tok}" for tok in _flag_rule_tokens(details, _LINE_TAG_RULE_TOKENS)
            )
            if weapon_name:
                base_msg = f"{unit_label} FOUGHT{_waaagh_seg} {target_label} with [{weapon_name}]"
            else:
                base_msg = f"{unit_label} FOUGHT{_waaagh_seg} {target_label}"
            
            # Apply truncation logic like shooting phase - stop after first failure.
            # JUMEAU du tir : meme helper, meme ordre garanti. SHOOT prefixe [HEAVY]/[COVER]
            # avant l appel ; FOUGHT ne les a pas, donc `_build_hit_suffix` suffit seul.
            _sustained_seg = _build_hit_suffix(details, hit_ability_display_name)
            detail_parts = [f"Hit {hit_roll}({hit_target}+){_sustained_seg}"]
            
            # Only show wound if hit succeeded
            if hit_result == "HIT":
                # [LETHAL HITS] 24.23 et [ANTI-X Y+] 24.03 — JUMEAUX du tir, MEME table et MEME
                # helper. [ANTI] est la regle de melee par excellence (les armes anti-vehicule
                # frappent au contact) : c est ici qu elle manquait le plus.
                wound_suffix = "".join(
                    f" {tok}" for tok in _flag_rule_tokens(details, _WOUND_SEGMENT_RULE_TOKENS)
                )
                wound_suffix += _anti_rule_token(details)
                wound_suffix += _ability_token(wound_ability_display_name)
                # JUMEAU du tir : regle d ARME relanceuse ([TWIN-LINKED]), puis modificateur +1
                # d Oath, tous deux distincts de la relance de capacite (cf. la-bas).
                wound_suffix += _ability_token(details.get("wound_reroll_rule_name"))
                wound_suffix += _ability_token(details.get("wound_bonus_ability_display_name"))
                wound_suffix += _rerolled_token(details, "wound_roll_initial")
                detail_parts.append(f"Wound {wound_roll}({wound_target}+){wound_suffix}")

                # Only show save if wound succeeded
                if wound_result in ("WOUND", "SUCCESS"):
                    # MEME helper que le tir. Cette branche imprimait `Save {roll}({target}+)`
                    # sans condition : sur une blessure DEVASTATING elle affichait `Save None`
                    # — 24.10 dit qu aucune sauvegarde n est faite — et sur une attaque non
                    # allouee, un seuil `None`. Le tir avait la premiere moitie du remede depuis
                    # V11 §0hist.38, la melee ne l a jamais eue : miroir a moitie ecrit, motif
                    # d echec n°1 du depot. Pas de capacite d AP en melee (aucun producteur).
                    detail_parts.extend(_save_segments(
                        details, damage=damage, save_result=save_result,
                    ))
            
            detail_msg = f" - {' - '.join(detail_parts)}"

            # Add reward if available
            reward = details.get("reward")
            if reward is not None:
                detail_msg += f" [R:{reward:+.1f}]"
            fight_subphase = details.get("fight_subphase")
            if not isinstance(fight_subphase, str) or not fight_subphase.strip():
                raise KeyError("Combat action missing required fight_subphase for replay contract")
            # Pas de pool loggue : le cercle vert du replay (unite active) est derive de l'attaquant
            # de la ligne FOUGHT cote parser, pas d'un pool d'eligibilite (cf. Documentation Replay.md).
            replay_meta = f" [FIGHT_SUBPHASE:{fight_subphase}]"
            return base_msg + detail_msg + replay_meta

        elif action_type == "wait":
            return f"{unit_label} WAIT"

        elif action_type == "skip":
            reason = (details.get("skip_reason") or "").strip()
            if reason:
                return f"{unit_label} SKIP ({reason})"
            return f"{unit_label} SKIP"

        elif action_type == "rule_choice":
            selected_rule_name = details.get("selected_rule_name")
            if not isinstance(selected_rule_name, str) or not selected_rule_name.strip():
                raise KeyError("Rule_choice action missing required selected_rule_name")
            return f"{unit_label} chose [{selected_rule_name.strip().upper()}]"
            
        elif action_type == "combat_summary":
            # Summary of multi-attack sequence
            if "target_id" not in details:
                raise KeyError("Combat summary missing required target_id")
            if "total_attacks" not in details or "total_damage" not in details:
                raise KeyError("Combat summary missing required total_attacks or total_damage")
                
            target_id = details["target_id"]
            total_attacks = details["total_attacks"]
            total_damage = details["total_damage"]
            hits = details.get("hits")
            wounds = details.get("wounds")
            failed_saves = details.get("failed_saves")
            
            return f"Unit {unit_id}{unit_coords} COMBAT COMPLETE at Unit {target_id} - {total_attacks} attacks, {hits} hits, {wounds} wounds, {failed_saves} failed saves, {total_damage} total damage"
            
        elif action_type in ("pile_in", "consolidation") and details:
            # Déplacements de la phase fight (12.02 pile-in / 12.07 consolidation), format miroir
            # du move : « Unit X(c,r) PILED IN/CONSOLIDATED from (a,b) to (c,d) ». Le segment
            # [MODELS:] (positions par-figurine d'arrivée) est ajouté génériquement par log_action.
            verb = "PILED IN" if action_type == "pile_in" else "CONSOLIDATED"
            if (
                "start_pos" in details
                and details["start_pos"] is not None
                and "end_pos" in details
                and details["end_pos"] is not None
            ):
                start_col, start_row = details["start_pos"]
                end_col, end_row = details["end_pos"]
                base_msg = f"{unit_label} {verb} from ({start_col},{start_row}) to ({end_col},{end_row})"
            else:
                raise KeyError(f"{action_type} action missing required position data")
            reward = details.get("reward")
            if reward is not None:
                base_msg += f" [R:{reward:+.1f}]"
            return base_msg

        else:
            raise ValueError(f"Unknown action_type '{action_type}'")
    
    def log_phase_transition(self, from_phase, to_phase, player, turn_number=1):
        """Log phase transitions (no step increment) using simplified format"""
        if not self.enabled:
            return
            
        try:
            with open(self.output_file, 'a') as f:
                timestamp = time.strftime("%H:%M:%S", time.localtime())
                # Clearer format: [timestamp] TX PX PHASE phase Start
                phase_upper = to_phase.upper()
                f.write(f"[{timestamp}] T{turn_number} P{player} {phase_upper} phase Start\n")
        except Exception as e:
            print(f"⚠️ Step logging error: {e}")
    
    def log_episode_end(self, total_episodes_steps, winner, win_method, objective_control):
        """Log episode completion summary using replay-style format

        Args:
            total_episodes_steps: Total steps across all episodes
            winner: 0, 1, or -1 (draw)
            win_method: "elimination", "objectives", "value_tiebreaker", or "draw"
            objective_control: Dict of objective_id -> control data (OC totals + controller)
        """
        if not self.enabled:
            return

        # PERFORMANCE: Flush any remaining buffered logs before episode end
        self._flush_buffer()

        try:
            duration_s = time.perf_counter() - getattr(self, '_episode_start_wall', time.perf_counter())
            with open(self.output_file, 'a') as f:
                timestamp = time.strftime("%H:%M:%S", time.localtime())
                method_str = f", Method={win_method}" if win_method else ""
                f.write(f"[{timestamp}] EPISODE END: Winner={winner}{method_str}, Actions={self.episode_action_count}, Steps={self.episode_step_count}, Total={total_episodes_steps}, Duration={duration_s:.3f}s\n")
                if objective_control:
                    objective_entries = []
                    for obj_id, data in objective_control.items():
                        player_1_oc = require_key(data, "player_1_oc")
                        player_2_oc = require_key(data, "player_2_oc")
                        controller = require_key(data, "controller")
                        objective_entries.append(
                            f"Obj{obj_id}:P1_OC={player_1_oc},P2_OC={player_2_oc},Ctrl={controller}"
                        )
                    f.write(f"[{timestamp}] OBJECTIVE CONTROL: {' | '.join(objective_entries)}\n")
                f.write("=" * 80 + "\n")
        except Exception as e:
            print(f"⚠️ Step logging error: {e}")
    
    def __del__(self):
        """Ensure buffer is flushed when logger is destroyed"""
        try:
            if hasattr(self, 'log_buffer') and self.log_buffer:
                self._flush_buffer()
        except (NameError, AttributeError):
            # Ignore errors during interpreter shutdown (open may not be available)
            pass


