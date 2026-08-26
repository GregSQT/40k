#!/usr/bin/env python3
"""ai/bot_registry.py — SOURCE UNIQUE du « quel objet derriere quelle cle de bot ».

POURQUOI CE MODULE EXISTE
    La table cle -> classe existait en DEUX copies : `ai/bot_evaluation.py._make_eval_env` et
    `scripts/bot_ranking.py._play_match`. Mesure du 2026-08-11 : brancher les six nouveaux styles
    dans la premiere a suffi pour l'evaluation, et `bot_ranking.py --bots racer` levait toujours
    « Unknown bot type: 'racer' ». Deux tables qui repondent a la meme question divergent au
    premier ajout — c'est le mode d'echec n°1 de ce depot, et il s'est produit ici en direct.

CE QUE LA TABLE CONTIENT, ET POUR COMBIEN DE TEMPS
    - `random` : la baseline, sans doctrine ni randomness parametrable.
    - Les CINQ bots d'origine, GELES et condamnes : ils ne valent plus que par la campagne de
      correspondance (etape 7 de `Documentation/Implementation/A_faire/bots_refonte_panel.md`),
      apres quoi leurs entrees et leur module partent.
    - Les SIX styles refondus (`ai/bot_doctrines.py`), qui les remplacent.
    - `tactical`, le holdout, et il le reste : la refonte « joue pour gagner » a ete ECRITE puis
      SUPPRIMEE le 2026-08-12 (cf. §10.1 du chantier). Mesuree, elle coutait 9,5x un bot normal
      par episode et rendait 0,431 sur 160 parties contre deux styles ordinaires — donc pas plus
      forte qu'eux, alors que tout son interet reposait sur l'inverse. Elle n'avait par ailleurs
      jamais affronte l'agent : aucun profil ne la portait dans `bot_eval_weights`.
"""

from typing import Any, Dict

# ── NOMS ── declares SANS importer les classes : `ai/training_callbacks.py` en derive ses
# constantes de module (`ALL_BOT_NAMES`, `BOT_DISPLAY_NAMES`), et importer le moteur pour
# construire une constante creerait un cycle. `bot_classes()` ci-dessous rend les MEMES cles ;
# le verrou `tests/unit/ai/test_bot_registry_names.py` interdit aux deux de diverger.
# (Ce fichier a ete cite ici AVANT d'exister — ecrit le 2026-08-11 apres que la review l'ait
# releve : une reference a un verrou absent est pire qu'aucune reference, elle rassure a tort.)
#
# ⚠️ C'est la TROISIEME table de bots qu'on unifie ici. Les deux premieres (`BOT_CLASSES` dans
# `ai/bot_evaluation.py` et dans `scripts/bot_ranking.py`) laissaient `--bots racer` lever
# « Unknown bot type ». Celle de `training_callbacks` etait pire : une liste BLANCHE, donc les
# six styles refondus jouaient 600 episodes sans qu'aucune ligne `vs <bot>` ne soit imprimee —
# la mesure tournait, ses resultats etaient invisibles (constate le 2026-08-11).

#: Panel d'origine, GELE et condamne apres la campagne de correspondance.
LEGACY_BOT_KEYS = ("greedy", "defensive", "control", "adaptive", "value_trade")

#: Panel refondu : six styles orthogonaux (`ai/bot_doctrines.py`).
DOCTRINE_BOT_KEYS = ("racer", "endgame", "alpha", "attrition", "decapitation", "scorer")

#: Trois benchmarks de holdout a mecanisme de decision DIFFERENT (§4.C Bot_refactor.md).
#: Exclus de SELECTION (ne pilotent ni combined ni worst_bot). Mesures uniquement.
#: Aucun de leurs parametres ne vient de config/bot_movement_weights.json.
BENCHMARK_BOT_KEYS = ("reference_balanced", "reference_denial", "reference_reactive")

#: Holdout SCELLE : mesure et affiche, exclu de TOUT signal de selection, ne gate JAMAIS.
#: « tactical » : son profil de witness value est gele depuis le 2026-08-04 (V11 §10.5).
SEALED_HOLDOUT_KEYS = ("tactical",)

#: Compat-alias : HOLDOUT_BOT_KEYS designe desormais les SEALED seulement.
#: Les consommateurs doivent migrer vers SEALED_HOLDOUT_KEYS ou BENCHMARK_BOT_KEYS.
HOLDOUT_BOT_KEYS = SEALED_HOLDOUT_KEYS

#: Nom de classe reel, pour les tags TensorBoard et les resumes. Table EXPLICITE : un
#: `''.join(part.capitalize()) + 'Bot'` rendrait le bon nom aujourd'hui et divergerait en
#: silence a la premiere classe qui ne suit pas la convention.
BOT_DISPLAY_NAMES: Dict[str, str] = {
    "random": "RandomBot",
    "greedy": "GreedyBot",
    "defensive": "DefensiveBot",
    "control": "ControlBot",
    "adaptive": "AdaptiveBot",
    "value_trade": "ValueTradeBot",
    "tactical": "TacticalBot",
    "racer": "RacerBot",
    "endgame": "EndgameBot",
    "alpha": "AlphaStrikeBot",
    "attrition": "AttritionBot",
    "decapitation": "DecapitationBot",
    "scorer": "ScorerBot",
    # Benchmarks §4.C
    "reference_balanced": "ReferenceBalancedBot",
    "reference_denial": "ReferenceDenialBot",
    "reference_reactive": "ReferenceReactiveBot",
}

#: Tous les adversaires mesurables, `random` compris (il n'est pas dans `bot_classes()`, cf. sa
#: docstring, mais il produit bien une ligne de resultat).
ALL_BOT_KEYS = frozenset(
    ("random",) + LEGACY_BOT_KEYS + DOCTRINE_BOT_KEYS + BENCHMARK_BOT_KEYS + SEALED_HOLDOUT_KEYS
)

#: Adversaires qui PILOTENT la selection de modele : tous sauf les holdouts (V11 §10.5). La
#: partition vit ICI et non chez ses consommateurs : `ai/training_callbacks.py` (gating, score
#: robuste) et `ai/metrics_tracker.py` (worst_bot_score de TensorBoard) la refaisaient chacun de
#: leur cote, et le second le faisait avec une liste ECRITE A LA MAIN restee sur le panel d'origine.
#: Pilotent combined + worst_bot : tout sauf BENCHMARK + SEALED.
#: Les benchmarks sont mesures mais ne pilotent PAS combined.
SELECTION_BOT_KEYS = ALL_BOT_KEYS - frozenset(BENCHMARK_BOT_KEYS) - frozenset(SEALED_HOLDOUT_KEYS)

#: Famille des adversaires-étalons figés (R0b). Clés DYNAMIQUES : découvertes à l'exécution
#: depuis les archives `*_robust_*.zip` de l'agent (discover_checkpoint_archives), pas définies
#: ici en dur. Jamais dans ALL_BOT_KEYS ni SELECTION_BOT_KEYS : indicateur de
#: force relative uniquement. Tag TensorBoard : `bot_eval/vs_ckpt_<score>`.
CHECKPOINT_OPPONENT_FAMILY = "ckpt"


def bot_display_name(bot_key: str) -> str:
    """Nom LISIBLE d'un adversaire, pour tout ce qui s'affiche a un humain.

    SOURCE UNIQUE de la traduction cle -> nom. `ai/step_logger.py` la fabriquait de son cote par
    `bot_key.capitalize() + "Bot"`, ce qui rendait `Value_tradeBot`, `Tactical_lookaheadBot` et
    `AlphaBot` pour un bot qui s'appelle `AlphaStrikeBot` — l'en-tete de `step.log` nommait donc
    des adversaires qui n'existent pas. La recette ne tombait juste que sur les cles d'un seul mot.

    Une cle inconnue LEVE : cette table et `bot_classes()` couvrent le meme panel (verrou
    `tests/unit/ai/test_bot_registry_names.py`), donc un nom absent signale un bot ajoute a moitie,
    pas un cas a habiller d'une etiquette approximative.
    """
    display = BOT_DISPLAY_NAMES.get(bot_key)
    if display is None:
        raise KeyError(
            f"Bot inconnu du registre : {bot_key!r}. BOT_DISPLAY_NAMES couvre "
            f"{sorted(BOT_DISPLAY_NAMES)} — un adversaire qui s'affiche doit y figurer."
        )
    return display


def bot_classes() -> Dict[str, Any]:
    """Table cle -> classe de bot. Import differe : `evaluation_bots` tire tout le moteur.

    `random` n'y figure pas : `RandomBot` ne prend pas de `randomness` (il EST le hasard), donc
    il ne se construit pas comme les autres. `build_bot` le traite a part plutot que d'ouvrir
    ici une exception que chaque appelant devrait redecouvrir.
    """
    from ai.evaluation_bots import (
        AdaptiveBot, ControlBot, DefensiveBot, GreedyBot, TacticalBot, ValueTradeBot,
    )
    from ai.bot_doctrines import DOCTRINE_BOTS
    from ai.benchmark_bots import (
        ReferenceBalancedBot, ReferenceDenialBot, ReferenceReactiveBot,
    )

    return {
        # ─ Panel GELE, condamne apres la campagne de correspondance ─
        "greedy": GreedyBot,
        "defensive": DefensiveBot,
        "control": ControlBot,
        "adaptive": AdaptiveBot,
        "value_trade": ValueTradeBot,
        # V11 §10.5 : holdout SCELLE — JAMAIS dans bot_training.ratios, ne gate JAMAIS.
        "tactical": TacticalBot,
        # ─ Panel refondu : six styles orthogonaux sur un plancher de competence commun ─
        **DOCTRINE_BOTS,
        # ─ Benchmarks §4.C : holdout a mecanisme DIFFERENT, mesures uniquement ─
        "reference_balanced": ReferenceBalancedBot,
        "reference_denial": ReferenceDenialBot,
        "reference_reactive": ReferenceReactiveBot,
    }


def build_bot(bot_type: str, randomness_config: Dict[str, float]):
    """Instancie le bot `bot_type`. Aucun defaut de randomness : une entree manquante leve.

    (V11 §10.5 : le defaut silencieux a 0.15 a ete supprime — il donnait a un bot une part de
    hasard que personne n'avait demandee, et que personne ne voyait dans la config.)
    """
    from ai.evaluation_bots import RandomBot

    if bot_type == "random":
        return RandomBot()
    classes = bot_classes()
    if bot_type not in classes:
        raise ValueError(
            f"Unknown bot_type: {bot_type!r}. Valid: random, {', '.join(sorted(classes))}"
        )
    if bot_type not in randomness_config:
        raise KeyError(
            f"randomness_config n'a pas d'entree pour le bot '{bot_type}' — renseigner "
            "callback_params.bot_eval_randomness (V11 §10.5 : plus de defaut 0.15 silencieux)."
        )
    return classes[bot_type](randomness=randomness_config[bot_type])
