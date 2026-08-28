# Tour de jeu — séquence, phases, activation (contrat moteur)

> **Objet** : LE contrat de toute logique de jeu du moteur — séquence du tour, arbres de décision
> par phase, matrices de conformité V11, suivi d'état transverse. Les ~174 commentaires
> « tour_de_jeu.md COMPLIANCE » du code (ex-« AI_TURN.md COMPLIANCE ») renvoient à ce contrat.
> **Source absorbée** : `AI_TURN.md` (même dossier), déplacée dans `Documentation/Archives/docs/`
> avec un bandeau retour.
> **L'état des chantiers fait foi dans `Documentation/Roadmap/`, jamais ici.**

---

## Contrat de codage (AI CODING CONTRACT, opérationnel)

Ce contrat contraint toute modification de ce code par un assistant ou un outil.

- **Ne jamais supposer une valeur** — si une valeur de configuration, un paramètre ou une entrée
  n'est pas clairement spécifié dans les configs ou la documentation, s'arrêter et demander la
  spécification au lieu d'inventer.
- **Toujours lever quand une donnée obligatoire manque** — toute variable critique, clé de
  configuration ou champ structurel absent déclenche une erreur explicite, jamais une
  substitution silencieuse ni un saut.
- **Aucune nouvelle constante dans la logique** — tout seuil, facteur d'échelle, poids de
  récompense ou quantité similaire va dans le fichier de configuration approprié (et est
  documenté), jamais en dur dans le code.
- **Toujours choisir le design conforme le plus simple** — préférer l'implémentation la plus
  petite et la plus claire qui suit ce document et `architecture_moteur.md` ; pas de couche ni de
  pattern supplémentaire non exigé par eux.
- **Refuser les changements qui violent ces règles** — si une demande contredit les règles de
  tour ou l'architecture, le signaler explicitement et demander clarification au lieu
  d'implémenter.

---

## 📅 Séquence du tour (SÉQUENCE DE TOUR)

**Phases d'un épisode** : `deployment` (une fois, au début), puis pour chaque joueur et chaque
tour : `command` → `move` → `shoot` → `charge` → `fight`. Le routage vit dans
`W40KEngine._process_semantic_action` et sa boucle de cascade (un handler `*_phase_start` par
phase) ; les joueurs sont `current_player` ∈ {1, 2}.

**Progression :**
```
Round N :
  J1 : Command → Move → Shoot → Charge → Fight
  J2 : Command → Move → Shoot → Charge → Fight
       └── fin du Fight de J2 : turn += 1, retour à la phase de commandement de J1
```

- **Incrément du compteur de tour** : à la FIN de la phase de fight du joueur 2, juste avant la
  transition `next_phase: "command"` vers le joueur 1 (`engine/phase_handlers/fight_handlers.py`).
- **Fin d'épisode** : un joueur n'a plus d'unités vivantes OU la limite de tours est atteinte
  (`get_effective_turn_limit`, `engine/game_utils.py`) — au dépassement, scoring final
  `apply_primary_objective_scoring` puis `game_over`.
- **Fin de phase** : aucune unité du joueur actif ne remplit les critères d'éligibilité de la
  phase (pool d'activation vide).
- **Pipeline d'exécution gym** : `_process_squad_action` (`engine/w40k_core.py`).
  Tailles d'espaces — ne jamais les recopier : lire `TOTAL_ACTION_SIZE` dans
  `engine/macro_intents.py`, et `observation_params.obs_size` dans la training config de l'agent
  (`config/agents/<agent>/<agent>_training_config.json`, exigée sans défaut par `W40KEngine`).

### Conventions de nommage des champs (Field Naming Logic)

**Convention MAJUSCULES** : toutes les statistiques d'unité utilisent des noms de champs en
MAJUSCULES, de façon cohérente dans tous les composants.

**Catégories :**
- **Mouvement** : MOVE, col, row
- **Tir** : RNG_WEAPONS[], selectedRngWeaponIndex, SHOOT_LEFT
  - `RNG_WEAPON_CODES` est **obligatoire** dans les définitions d'unités (même `[]` si aucune arme).
  - `RNG_WEAPONS` est **toujours présent** en runtime (liste vide autorisée).
- **Mêlée** : CC_WEAPONS[], selectedCcWeaponIndex, ATTACK_LEFT
  - `CC_WEAPON_CODES` est **obligatoire** dans les définitions d'unités (même `[]` si aucune arme).
  - `CC_WEAPONS` est **toujours présent** en runtime (liste vide autorisée).
- **Défense** : HP_CUR, HP_MAX, T, ARMOR_SAVE, INVUL_SAVE

**Accès aux armes** : utiliser les fonctions de `engine.utils.weapon_helpers` pour lire
`RNG_WEAPONS` / `CC_WEAPONS`.

---

## Primitives d'activation (GENERIC FUNCTIONS)

### end_activation — procédure de fin d'activation

Implémentation : `def end_activation` (`engine/phase_handlers/generic_handlers.py`) ; côté tir,
le nettoyage passe par `_handle_shooting_end_activation` (`engine/phase_handlers/shooting_handlers.py`).

```javascript
END OF ACTIVATION PROCEDURE
end_activation (Arg1, Arg2, Arg3, Arg4, Arg5, Arg6)
├── Arg1 = ?
│   ├── CASE Arg1 = ACTION → log the action
│   ├── CASE Arg1 = WAIT → log the wait action
│   └── CASE Arg1 = NO → do not log the action
├── Arg2 = 1 ?
│   ├── YES → +1 step
│   └── NO → No step increase
├── Arg3 =
│   ├── CASE Arg3 = 0 → Do not mark the unit
│   ├── CASE Arg3 = MOVE → Mark as units_moved
│   ├── CASE Arg3 = FLED → Mark as units_moved AND Mark as units_fled
│   ├── CASE Arg3 = SHOOTING → Mark as units_shot
│   ├── CASE Arg3 = ADVANCE → Mark as units_advanced
│   ├── CASE Arg3 = CHARGE → Mark as units_charged
│   └── CASE Arg3 = FIGHT → Mark as units_fought
├── Arg4 = ?
│   ├── CASE Arg4 = NOT_REMOVED → Do not remove the unit from an activation pool
│   ├── CASE Arg4 = MOVE → Unit removed from move_activation_pool
│   ├── CASE Arg4 = FLED → Unit removed from move_activation_pool
│   ├── CASE Arg4 = SHOOTING → Unit removed from shoot_activation_pool
│   ├── CASE Arg4 = CHARGE → Unit removed from charge_activation_pool
│   └── CASE Arg4 = FIGHT → Unit removed from fight_activation_pool
├── Arg5 = 1 ?
│   ├── YES → log the error
│   └── NO → No action
└── Arg6 = 1 ?
    ├── YES → Remove the green circle around the unit's icon
    └── NO → Do NOT remove the green circle around the unit's icon
```

**Référence des paramètres (End Activation Parameters Reference) :**
```javascript
end_activation(result_type, step_count, action_type, phase, remove_from_pool, increment_step)
```
- `result_type` : ACTION | WAIT | ERROR | NO | NOT_REMOVED
- `step_count` : 0 ou 1 (incrémenter episode_steps ?)
- `action_type` : SHOOTING | ADVANCE | MOVE | CHARGE | etc.
- `phase` : phase courante
- `remove_from_pool` : 0 ou 1 (retirer l'unité du pool d'activation ?)
- `increment_step` : 0 ou 1 (suivi interne)

### attack_sequence — séquence d'attaque (tir et mêlée)

```javascript
ATTACK ACTION
attack_sequence(Arg)
├── Arg = RNG ?
│   └── Use selected ranged weapon from attacker.RNG_WEAPONS[selectedRngWeaponIndex]
├── Arg = CC ?
│   └── Use selected melee weapon from attacker.CC_WEAPONS[selectedCcWeaponIndex]
├── Hit roll → hit_roll >= selected_weapon.ATK
│   ├── MISS
│   │   ├── Arg = RNG ? → ATTACK_LOG = "Unit <activeUnit ID>(col,row) SHOT Unit <selectedTarget ID>(col,row) with [<weapon_name>] - Hit <hit roll>(<target hit roll>+)"
│   │   └── Arg = CC ?  → ATTACK_LOG = "Unit <activeUnit ID>(col,row) FOUGHT Unit <selectedTarget ID>(col,row) with [<weapon_name>] - Hit <hit roll>(<target hit roll>+)"
│   └── HIT → hits++ → Continue to wound roll
│       └── Wound roll → wound_roll >= calculate_wound_target()
│           ├── FAIL
│           │   ├── Arg = RNG ? → ATTACK_LOG = "... - Hit <hit roll>(<target hit roll>+) - Wound <wound roll>(<target wound roll>+)"
│           │   └── Arg = CC ?  → ATTACK_LOG = idem (verbe FOUGHT)
│           └── WOUND → wounds++ → Continue to save roll
│               ├── Save roll → save_roll >= calculate_save_target()
│               │   ├── SAVE
│               │   │   ├── Arg = RNG ? → ATTACK_LOG = "... - Hit ... - Wound ... - Save <save roll>(<target save roll>+)"
│               │   │   └── Arg = CC ?  → idem (verbe FOUGHT)
│               │   └── FAIL → failed_saves++ → Continue to damage
│               └── Damage application:
│                   ├── damage_dealt = selected_weapon.DMG
│                   ├── total_damage += damage_dealt
│                   ├── ⚡ IMMEDIATE UPDATE: selected_target.HP_CUR -= damage_dealt
│                   ├── ATTACK_LOG = "... - Hit ... - Wound ... - Save ... - Dmg:<DMG>HP" (verbe SHOT ou FOUGHT selon Arg)
│                   └── selected_target.HP_CUR <= 0 ?
│                       ├── NO → (attack log only)
│                       └── YES → current_target.alive = False; separate death log entry: "Unit <selectedTarget ID> was DESTROYED"
└── Return: TOTAL_ATTACK_LOG
```

---

## Déploiement et mise en place (03.02)

La phase `deployment` ouvre l'épisode : `deployment_phase_start` /
`execute_deployment_action` (`engine/phase_handlers/deployment_handlers.py`). La chaîne de
placement — `generate_compact_formation` → `deployment_preview_plan` → `_apply_deploy_plan`,
alimentée par le pool `placement_pool_for_squad` — est la SEULE réponse à « où cette escouade
a-t-elle le droit d'être posée ? » ; l'arrivée des réserves (ingress 20.04, section Mouvement)
lui substitue simplement son aire légale via `pool_override` de `_deploy_pool_set`.

Pendant le déploiement, l'agent ou le joueur peut déposer une escouade en réserves stratégiques
(20.01 — `deployment_place_in_strategic_reserves`, plafond 50 % des points, voir la matrice
Mouvement). En mode `deployment_type: "active"`, TOUTES les unités commencent hors table et sont
posées une à une : voir « Unités hors table » dans la section Mouvement pour l'invariant
géométrique que cela impose.

---

## Phase de commandement (COMMAND PHASE)

Déroulé moteur (`engine/phase_handlers/command_handlers.py`) :
1. `command_step_start_of_phase` — remises à zéro « ce tour » : les six sets de suivi
   (`units_moved`, `units_fled`, `units_shot`, `units_charged`, `units_fought`,
   `units_advanced`) sont vidés ICI, et `units_shot_previous_turn` photographie le `units_shot`
   du tour précédent (pour la règle hidden 13.09). Point d'accrochage des capacités « at the
   start of your Command phase ».
2. `command_step_gain_core_cp` — gain de CP des deux joueurs.
3. `command_step_battle_shock` — tests de battle-shock du joueur actif.
4. `command_step_command_abilities` — décisions de faction (peut ARRÊTER la phase, voir matrice).
5. `command_phase_end` — point d'accrochage « at the end of your Command phase ».

Hors décision en attente, la phase n'accepte que `zone_intent` et `skip`
(`W40KEngine.COMMAND_PHASE_ACTIONS`).

### V11 COMPLIANCE MATRIX — COMMAND PHASE

> Source de vérité : `Documentation/40k_rules/08 Command phase.pdf`, `01 Core concepts.pdf`
> (01.06/01.07), `25 Rules appendix.pdf` (effectifs). Statut établi par lecture du code
> (`engine/phase_handlers/command_handlers.py`, `engine/game_state.py`).

| Règle | Contenu | Statut moteur | Mapping / notes |
|---|---|---|---|
| 08.01 | Start of Command phase | ✅ (2026-08-04) | `command_step_start_of_phase` — remises à zéro « ce tour » ; point d'accrochage des capacités « at the start of your Command phase » (chantiers 03/06) |
| 08.02 | Gain Core CP (« **both players** gain 1 CP ») | ✅ (2026-08-04) | `command_step_gain_core_cp` → `gain_command_points` (écrivain unique de `game_state["command_points"]`). Montant = constante du PDF (`CORE_CP_GAIN_PER_COMMAND_PHASE`), pas un réglage. Dotation de départ = `game_rules.starting_command_points`, **sans valeur par défaut** |
| 08.03 | Battle-shock (joueur **actif** ; unités déjà choquées **ou** à/sous demi-effectif) | ✅ (2026-08-04) | `command_step_battle_shock` : filtre `current_player`, union `battle_shocked` ∪ `is_unit_at_or_below_half_strength`. Clause de sortie (« succeeds → no longer battle-shocked ») portée par l'écriture inconditionnelle de `roll_battle_shock` |
| 08.04 | Command abilities | ✅ (2026-08-05) | `command_step_command_abilities` — pose la décision, puis **ARRÊTE la phase** : `command_phase_resume` ne bascule vers le move que si `faction_decision_is_pending` est faux, et l'arrêt est OPPOSABLE (toute autre action refusée, `faction_decision_pending`, aux deux points d'entrée). La décision jouée, la reprise **démarre** la phase de mouvement au lieu de se contenter de rendre `next_phase` : les deux routes de décision sortent du moteur avant la boucle de cascade, seul endroit où une transition s'exécute. Vivantes : **Waaagh!** (ORKS, `pending_agent_decision` type `waaagh_call`, `CHOICE_0/1`) et **Oath of Moment** (ADEPTUS ASTARTES, `pending_oath_selection` + `OATH_SLOTS`, NON optionnelle) — chantier 03, cf. [`regles_unites.md`](../jeu/regles_unites.md) §2 bis. Le décideur : masque en gym, `_select_ai_*` pour un siège IA hors gym, UI PvP pour un humain. Reste 🟡 Grot Orderly (chantier 06). Hors décision en attente, la phase n'accepte que `zone_intent` et `skip` (`W40KEngine.COMMAND_PHASE_ACTIONS`) |
| 08.05 | End of Command phase | ✅ | `command_phase_end` — point d'accrochage des capacités « at the end of your Command phase » |
| 01.06 | Leadership roll (**2D6** ≥ **une ou plusieurs** des caractéristiques Ld de l'unité) | ✅ (2026-08-04) | `unit_effective_leadership` = **min** des Ld des figurines VIVANTES (`models_cache["LD"]`). Warboss `LD 6+` replié dans des Boyz `LD 7+` → l'unité teste à 6+ ; le character mort, elle repasse à 7+ (extinction 19.04) |
| 01.07 | Battle-shock roll et ses trois effets | 🟡 Partiel, par absence de déclencheur | **OC → '-'** : ✅ `sum_objective_control_oc_multi` écarte l'unité entière (14.02). **Pas ciblable par un stratagème** et **inéligible aux actions** : ⛔ **sans objet** — ni stratagèmes (15) ni système d'actions (16) n'existent dans le moteur. Les coder produirait du code jamais atteint ; à rouvrir avec le chantier stratagèmes |
| 25 | Force de départ, sous l'effectif, à / sous le demi-effectif | ✅ (2026-08-04) | `is_unit_below_starting_strength`, `is_unit_at_half_strength`, `is_unit_below_half_strength` sur `_strength_measure` (figurines si force de départ ≥ 2, PV si = 1). **Clause de parité** : une force de départ impaire ne peut JAMAIS être *à* demi-effectif |
| — | `cp_gain_on_objective` (Thievin' Scavengers, Gretchin) | ✅ (2026-08-04) | `movement_step_cp_gain_on_objective`, au **début de la phase de mouvement** (pas de commandement) : 1 D6 par objectif contrôlé tenu par ≥ 1 unité amie **non battle-shocked** porteuse ; ≥ 1 résultat de 4+ → **+1 CP au total** |
| — | Dépense de CP | ⛔ Sans objet | aucun consommateur tant qu'il n'y a pas de stratagèmes ; `gain_command_points` refuse un montant ≤ 0 |
| — | Rites of Battle (réduction de coût de stratagème) | ⛔ Non implémentable | « when a stratagem targets this unit » n'a aucun déclencheur ; hors périmètre tant que 15 n'existe pas |

**Règle 14.02 — le checkpoint de contrôle d'objectif était éteint en entraînement.**
Trouvé en corrigeant `cp_gain_on_objective`, qui lit « for each objective you control » et ne
jouait JAMAIS au tour 1 (mesuré : `objective_controllers == {}` aux deux phases de mouvement).
Cause : `run_objective_control_checkpoint` sortait sur `if not check_cfg`, et la section
`objective_control_check` de `game_config.json` n'était posée que par les deux constructeurs de
`services/api_server` — la branche d'entraînement de `W40KEngine.__init__` l'avait omise. Le
contrôle n'était donc rafraîchi en gym que par effet de bord des chemins de scoring VP, à des
moments qui ne sont pas ceux de la règle. Corrigé le 2026-08-04 : **le contrôle est désormais
réévalué à chaque frontière de phase**.

**Le MÉCANISME, corrigé le même jour.** Le vrai défaut n'était pas la clé manquante mais le
régime d'erreur : le contrat « sections de `game_config.json` exigées par le moteur » était
recopié à la main sur QUATRE sites de construction (branche d'entraînement, les deux
constructeurs de `services/api_server`, `main.load_config` — ce dernier omettant aussi `move` et
`charge`), et il était lu en `.get()`. Deux sections du MÊME fichier avaient donc des régimes
opposés : un oubli de `move` plante à la première action (`_get_move_traversal_rules`,
`require_key`), un oubli de `objective_control_check` éteignait une règle du jeu en silence.
Le contrat vit désormais en UN endroit — `config_loader.GAME_CONFIG_SECTIONS_REQUIRED_BY_ENGINE`
et `require_engine_game_config_sections`, `require_key` sur chaque section — que les quatre sites
appellent, et le point de lecture du checkpoint est passé à `require_key`. Côté tests,
`tests/unit/engine/_config_helpers.build_engine_config` part de ce même contrat : une config de
test ne peut plus éteindre une règle en ne la déclarant pas. Même durcissement sur la mise à
l'échelle pouces → sub-hex de `W40KEngine.__init__`, qui sautait en silence sur un `.get` de
`game_rules` / `charge` et laissait les distances en pouces sur un plateau x5/x10.

**Le même défaut au niveau de la CLÉ, corrigé le même jour.** `shared_utils.get_max_base_size_hex`
lisait `game_rules["max_base_size_hex"]` par trois replis en cascade terminés par un défaut
littéral `35`, alors que son jumeau strict à dix lignes de là dans le MÊME fichier
(`get_engagement_zone` → `spatial_relations.get_engagement_zone`) exige les trois niveaux par
`require_key` : deux lecteurs de la même section, régimes opposés. Mesuré sur une partie réelle
(791 appels, deux graines) : **zéro repli**, la valeur venait toujours de la config — le défaut ne
pouvait que masquer un état malformé ou une clé retirée du JSON. Passé à `require_key` en cascade,
la valeur ne vit plus que dans `config/game_config.json`. Ce seuil est un DIAMÈTRE HEX **non
scalé** par `inches_to_subhex` (absent de la liste de conversion de `w40k_core`), donc un littéral
en dur n'avait même pas le même sens d'un plateau à l'autre. Verrou :
`tests/unit/engine/test_max_base_size_hex_regime.py`.

**Trois généralisations évaluées et ÉCARTÉES** (2026-08-04) — écrites ici pour qu'on ne les
re-propose pas comme dette. (a) Factoriser en un `require_game_rule(game_state, name)` le prélude
`config` → `game_rules` écrit 23 fois dans `engine/` : découpage sur du code correct, aucun défaut
évité. (b) Un test de contrat AST vérifiant que les 13 clés lues existent dans
`game_config.json` : depuis que tous les lecteurs sont en `require_key`, une clé absente fait
lever le moteur au premier step — le test n'attraperait rien de plus. (c) Migrer vers
`_config_helpers.build_game_rules` les 97 fixtures qui écrivent un `"game_rules"` littéral :
**activement nocif**, car la migration INJECTE les vraies valeurs des clés que la fixture n'avait
pas (un test écrit sans `max_turns` se mettrait à tourner sur `max_turns: 5` et passerait en
mesurant autre chose) — du vert vacant à 97 exemplaires. La douleur qu'elle prétend prévenir a
été mesurée à zéro : sur les 21 fixtures dépourvues de `max_base_size_hex`, aucune n'a cassé au
durcissement. La bonne granularité est le cas par cas : quand une fixture casse, on la migre en
vérifiant qu'elle mesure encore la même chose.

Ce que ça change, MESURÉ (5 graines, même flux d'actions, `cp_gain_on_objective` neutralisée des
deux côtés pour ne pas décaler le flux `random` — sans cette précaution les épisodes divergent et
la comparaison ne mesure plus rien) :

| | effet |
|---|---|
| **Points de victoire** | **AUCUN**, sur les 5 graines. `_calculate_primary_objective_control_counts` recalcule le contrôleur depuis les sommes d'OC et **ignore l'état persisté** en `control_method: "default"` — le seul mode livré. Le scoring ne pouvait donc pas dépendre du moment du checkpoint. |
| **Récompenses** | −10 / −10 / −15 / −5 / −20 selon la graine. Elles, lisent `objective_controllers` en LECTURE PURE (`_compute_objective_hold_reward`, shaping d'intention de zone) : elles voyaient un contrôle périmé, crédité jusqu'au scoring suivant même une fois perdu. |
| **Observation, `cp_gain_on_objective`, step.log** | idem : tous lisent l'état persisté. |

Le sens constant du delta (l'agent perd de la récompense) mesure ce sur-crédit.
Verrou : `test_objective_control_checkpoint_1402.py`, qui contrôle la présence de la section,
que le checkpoint écrit réellement, que l'assembleur refuse chaque section manquante, que le
checkpoint LÈVE au lieu de se taire, et que `main.load_config` porte tout le contrat.

**Observation.** Les CP des deux joueurs sont dans `global_cont`
(`my_command_points` / `enemy_command_points`, grandeur globale : un CP appartient au joueur, pas
à une unité). Le battle-shock est un **statut** d'unité (`status_ids`, registre
`config/unit_statuses.json`), écrit pour les entités alliées **comme** ennemies — l'OC à '-' est
une information publique. Tests : `test_command_points_and_battle_shock.py`.

---

## 🏃 Phase de mouvement (MOVEMENT PHASE)

### MOVEMENT PHASE Decision Tree

Les marques `units_moved` / `units_fled` / `units_shot` / `units_charged` / `units_fought` sont
remises à zéro AVANT cette phase, dans `command_step_start_of_phase` (phase de commandement).

```javascript
START OF THE PHASE
For each unit
├── ELIGIBILITY CHECK (move_activation_pool Building Phase)
│   ├── unit.HP_CUR > 0?
│   │   └── NO → ❌ Dead unit (Skip, no log)
│   ├── unit.player === current_player?
│   │   └── NO → ❌ Wrong player (Skip, no log)
│   ├── Has at least one valid adjacent hex (not occupied, not adjacent to enemy, not a wall)?
│   │   └── NO → ❌ Unit cannot move (Skip, no log)
│   └── ALL conditions met → ✅ Add to move_activation_pool
│
├── STEP : UNIT_ACTIVABLE_CHECK → is move_activation_pool NOT empty ?
│   ├── YES → Current player is an AI player ?
│   │   ├── YES → pick one unit in move_activation_pool
│   │   │   └── Valid destination exists (reacheable hexes using BFS pathfinding within MOVE attribute distance, NOT through/into wall hexes, may traverse hexes occupied by allies but NOT end overlapping any model, NOT through/into adjacent-to-enemy engagement hexes) ?
│   │   │       ├── YES → MOVEMENT PHASE ACTIONS AVAILABLE
│   │   │       │   ├── 🎯 VALID ACTIONS: [move, wait]
│   │   │       │   ├── ❌ INVALID ACTIONS: [shoot, charge, attack] → end_activation (ERROR, 0, PASS, MOVE, 1, 1)
│   │   │       │   └── AGENT ACTION SELECTION → Choose move ?
│   │   │       │       ├── YES → ✅ VALID → Execute move action
│   │   │       │       │   ├── The active_unit was adjacent to an enemy unit at the start of its move action ?
│   │   │       │       │   │   ├── YES → end_activation (ACTION, 1, FLED, MOVE, 1, 1)
│   │   │       │       │   │   └── NO → end_activation (ACTION, 1, MOVE, MOVE, 1, 1)
│   │   │       │       └── NO → Agent chooses: wait?
│   │   │       │           ├── YES → ✅ VALID → Execute wait action
│   │   │       │           │   └── end_activation (WAIT, 1, PASS, MOVE, 1, 1)
│   │   │       │           └── NO → Agent chooses invalid action (shoot/charge/attack)?
│   │   │       │               └── ❌ INVALID ACTION ERROR → end_activation (ERROR, 0, PASS, MOVE, 1, 1)
│   │   │       └── NO → end_activation (NO, 0, PASS, MOVE, 1, 1)
│   │   │
│   │   └── NO → Human player → STEP : UNIT_ACTIVATION
│   │       ├── If any, cancel the Highlight of the hexes in valid_move_destinations_pool
│   │       ├── Player activate one unit by left clicking on it
│   │       └── Build valid_move_destinations_pool (NOT wall hexes, NOT ending on occupied hexes, may pass through allied-occupied hexes, NOT adjacent to enemy engagement hexes, reacheable using BFS pathfinding within MOVE attribute distance)
│   │           └── valid_move_destinations_pool not empty ?
│   │               ├── YES → STEP : PLAYER_ACTION_SELECTION
│   │               │   ├── Highlight the valid_move_destinations_pool hexes by making them green
│   │               │   └── Player select the action to execute
│   │               │       ├── Left click on a hex in valid_move_destinations_pool → Move the unit's icon to the selected hex
│   │               │       │   ├── The active_unit was adjacent to an enemy unit at the start of its move action ?
│   │               │       │   │   ├── YES → end_activation (ACTION, 1, FLED, MOVE, 1, 1)
│   │               │       │   │   └── NO → end_activation (ACTION, 1, MOVE, MOVE, 1, 1)
│   │               │       │   └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │               │       ├── Left click on the active_unit → Move postponed
│   │               │       │   └── GO TO STEP : UNIT_ACTIVATION
│   │               │       ├── Right click on the active_unit → Move cancelled
│   │               │       │   ├── end_activation (NO, 0, PASS, MOVE, 1, 1)
│   │               │       │   └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │               │       ├── Left click on another unit in activation pool → Move postponed
│   │               │       │   └── GO TO STEP : UNIT_ACTIVATION
│   │               │       └── Left OR Right click anywhere else on the board → Cancel Move hex selection
│   │               │           └── GO TO STEP : UNIT_ACTIVATION
│   │               └── NO → end_activation (NO, 0, PASS, MOVE, 1, 1)
│   ├── NO → If any, cancel the Highlight of the hexes in valid_move_destinations_pool
│   └── No more activable units → pass
└── End of MOVEMENT PHASE → Advance to shooting phase
```

### Restrictions de mouvement (Movement Restrictions Logic)

**Mouvement au sol (non-Fly) — pathfinding / preview :**
- **Murs** : ni traversée ni arrêt dessus.
- **Cases de figurines ennemies** : bloquent la traversée.
- **Cases occupées par des alliés** : traversables ; interdiction de **finir** le mouvement avec
  une figurine chevauchant une case occupée (alliée ou ennemie).
- **Zone d'engagement ennemie** : **non traversable** (pas seulement interdite en destination —
  le BFS ne l'utilise jamais comme étape). Sans **Fly**, impossible de franchir cette bande pour
  atteindre les cases derrière.
- **Adjacence / engagement** : anneaux d'adjacence ennemis en cache et `get_engagement_zone`
  (empreintes multi-hex comprises).

**Fly — pathfinding / preview :**
- L'exploration BFS ne traite ni murs ni occupation comme bloquants le long du chemin ; la
  validation de **destination** applique toujours murs, occupation et engagement sur l'empreinte.

### Fuite (Flee Mechanics Logic)

- **Déclencheur** : action de move démarrée depuis une case adjacente à un ennemi.
- **Implémentation** : détection à l'entrée de l'action (`_squad_is_in_enemy_er`), marquage par
  `finalize_flee_marking` (`engine/phase_handlers/movement_handlers.py`).
- **Note** : les restrictions de mouvement interdisent les destinations adjacentes à l'ennemi,
  donc contrôler la seule position de départ suffit à détecter la fuite.

**Conséquences de la fuite :**
- **Phase de tir** : ne peut pas tirer.
- **Phase de charge** : ne peut pas charger.
- **Phase de fight** : combat normalement.
- **Durée** : jusqu'à la fin du tour en cours uniquement.

### V11 COMPLIANCE MATRIX — MOVEMENT PHASE

> Source de vérité : `Documentation/40k_rules`. Statut établi par lecture du code (`engine/phase_handlers/movement_handlers.py`, `config/game_config.json`). Distances exprimées en **pouces** ; conversion hex = pouces × `inches_to_subhex` (board-dépendant : 44x60x1→1, 44x60x5→5, 44x60x10→10). **Ne jamais coder une équivalence pouce↔hex en dur.**

| Règle | Contenu | Statut moteur | Mapping / notes |
|---|---|---|---|
| 09.01 | Start of Movement phase | ✅ | `movement_phase_start()` |
| 09.02 | Move Units : sélection unité + type de move ; *toutes* les unités (y c. réserves) | ✅ (2026-08-04) | sélection via `execute_action` ; les unités en réserves sont ajoutées au `move_activation_pool` par `ingress_eligible_units` — leur « type de move » est l'ingress (20.04) |
| 09.03 | End of Movement phase | ✅ | transition → shoot |
| 09.04 | Remain stationary (aucun trigger start/end move) | ✅ | action `wait` |
| 09.05 | Normal move (max = M ; unengaged avant/après) | ✅ | budget = M (`get_squad_move_budget`) |
| 09.06 | Advance (max = M + D6 ; après : pas de charge ni action) | ✅ | `roll_advance_for_squad`, `units_advanced` ; tir après advance → voir section Tir (ASSAULT / `shoot_after_advance`) |
| 09.07 | Fall-back (engaged ; Ordered Retreat / Desperate Escape ; hazard ; battle-shock ; après : pas tir/charge/action) | ✅ | `desperate_escape = battle_shocked`, `roll_hazard_for_unit`, `roll_battle_shock`, `units_fled`, traversée ennemis en Desperate Escape |
| 18.04 | Disembark move | ⛔ Non implémenté | pas de transports |
| 19.01 | Forming attached units (éligibilité bodyguard + unicité leader/support) | ✅ | `_fold_attached_characters` : rôle leader/support exigé ; keyword de nom d'unité de la cible ∈ `CAN_LEAD` (insensible casse) ; cible du même joueur (« friendly ») ; au plus 1 leader ET 1 support par bodyguard → erreur explicite dans les 4 cas. « one friendly bodyguard unit » par leader : structurel (`attached_squad` est scalaire). Attachement facultatif (« you **can** select ») : un character sans `attached_squad` reste une unité autonome. « single unit for all rules purposes » : le fold produit un squad unique, pas deux entités liées. Test `test_attached_units_legality_19_01.py` |
| 19.02 | Attacking attached units (T = plus haute T bodyguard) | ✅ | `_target_highest_bodyguard_toughness` (tir + fight), + repli PDF « unité ne contenant que des leader/support → plus haute T de ceux-ci ». Bodyguard = figurine de rôle non leader/support (`_is_character_role`) ; aujourd'hui rôle ⟺ keyword `CHARACTER` dans les 9 datasheets qui le portent, mais le couplage n'est pas verrouillé par un test. Trigger « unité détruite » = dernière figurine du squad (l'unité attachée est un squad unique). Clause « the last model that **started the battle** » : sans objet, aucune mécanique de revive/ajout de figurine dans le moteur (grep zéro). Test `test_attached_units_toughness_19_02.py` |
| 19.03 | Keywords in attached units (union des keywords) | ✅ | `_build_enhanced_unit` : l'unité porte l'UNION des keywords de ses composants ; les keywords **propres** restent sur `models[i]["UNIT_KEYWORDS"]` pour les règles « each model » (06.03) — exactement la clause PDF « models do not gain the keywords of other models ». Identique à l'appendix 25 « Mixed keywords in units ». Test `test_attached_units_keywords_19_03.py` |
| 19.04 | Abilities in attached units (règle d'unité → toutes les figurines de l'unité attachée) | ✅ (2026-07-27) | `unit["UNIT_RULES"]` est l'union **en vigueur**, dérivée de deux sources immuables posées au build : `_UNIT_RULES_OWN` (bloc bodyguard = datasheet de l'escouade + règles propres de ses figurines natives) et `_ATTACHED_RULE_GROUPS` (un groupe par character replié, clé = id de l'unité d'origine). `recompute_unit_rules_in_effect` la réévalue à chaque `destroy_model` : mort du dernier bodyguard → le datasheet s'éteint et le leader garde ses propres règles (note explicite du PDF) ; mort de la dernière figurine d'un leader/support → sa règle quitte l'unité. Sursis « until the attacking unit has resolved all of its attacks » porté par l'allocation en cours et refermé par `_finalize_manual_allocation` (même point que HAZARDOUS 24.15) ; exclu pour HAZARDOUS et le retrait de cohérence, qui ne sont pas des attaques. Les marqueurs de rôle ne remontent jamais à l'escouade (`strip_role_rules`) : ils qualifient la figurine (05.04, T bodyguard 19.02). Corrige gym ET PvP. Test `test_attached_units_abilities_19_04.py` (e2e via le vrai chargement de scénario) |
| 20.01 | Placing units in strategic reserves (plafond 50 % des points) | ✅ (2026-08-04) | Deux entrées, un seul état : champ de roster `strategic_reserves` (validé AU CHARGEMENT par `validate_strategic_reserves_cap` — dépassement = erreur nommant les unités et le total, jamais une troncature) et DÉCISION de l'agent en phase de déploiement (`deployment_place_in_strategic_reserves`, action `SQUAD_ACTION_WAIT`, slot fermé par le masque dès que le plafond serait dépassé). `FORTIFICATIONS` exclues. Taille de bataille lue dans le `scale` du scénario (`points_limit`) ; sans elle le plafond vaut 0 et AUCUN dépôt n'est possible — les scénarios PvP ne la déclaraient pas, donc le conteneur était inerte quoi que fasse le joueur (verrouillé par `test_every_pvp_scenario_declares_a_battle_size`, dans `tests/unit/services/test_api_server_helpers.py`). **Siège PvP, deux gestes séparés** : (1) le DÉPÔT est un bouton `Strategic Reserve` porté par la ligne de l'escouade SÉLECTIONNÉE dans la liste à déployer — vert si `placeable_unit_ids` la contient, gris sinon, et un bouton gris n'appelle rien : la couleur est l'unique réponse rendue au joueur sur le plafond, jamais une arithmétique refaite en TS ; (2) le CONTENEUR (`StrategicReservesContainer`, contour orange, ratio « 120/250 » LU de l'API) est rendu SOUS la table de statut de chaque joueur, et ne sert qu'à voir les escouades hors table et à déclencher leur arrivée 20.04. Il s'efface quand il n'a rien à dire (aucune réserve hors phase de déploiement) : pendant le déploiement il reste, même vide, car son ratio est la seule lecture du plafond restant au moment de la décision. Les deux listes partagent UNE ligne (`UnitRosterRow` : figurines, nom, [action], points, nb de figurines, id) — même escouade, même tête, qu'elle attende son déploiement ou son arrivée. Le dépôt n'est proposé que pour les ids de `placeable_unit_ids`, calculés par `unit_can_be_placed_in_strategic_reserves` : le client ne rejoue ni le plafond ni le test FORTIFICATION |
| 20.02 | Repositioned units (3 clauses) | ✅ (2026-08-04) | `reposition_unit_to_strategic_reserves` : aucune garde sur `units_moved` (clause 1) ; `units_advanced`/`units_fled`/`units_moved` **laissés intacts** (clause 2 — les effacer rendrait le tir et la charge après un Advance) ; `battle_shocked` conservé, les effets de CIRCONSTANCE (auras) cessant d'eux-mêmes hors table puisqu'ils sont réévalués par distance (clause 3, exemple littéral du PDF). Exempte de la destruction de fin de 3e round (`reserves_repositioned`) |
| 20.03 | Arriving from strategic reserves (pas avant le 2e round) | ✅ (2026-08-04) | `ingress_eligible_units` rend `[]` avant le round d'arrivée → masque fermé. **Les trois grandeurs de 20.03/20.04 sont des PARAMÈTRES PAR UNITÉ**, pas des constantes : `reserves_arrival_round` (2), `reserves_edge_distance_inches` (6, `None` = « anywhere on the battlefield »), `reserves_enemy_clearance_inches` (8). Chaque clause commence par « unless otherwise stated » ou est remplacée par une capacité — Logan Grimnar fait arriver une unité au 1er round, Da Jump pose « more than 9" away » — et une capacité d'une AUTRE unité doit pouvoir les écrire (`set_reserves_arrival_round`, `set_reserves_setup_distances`). Le « une fois par partie » appartient à l'unité qui accorde, pas à celle qui reçoit |
| 20.04 | Ingress move | ✅ (2026-08-04) | **L'ingress est une MISE EN PLACE (03.02), pas un déplacement** : il ne passe pas par le pool BFS du move (il n'a ni origine ni budget) mais par la chaîne de placement du déploiement, à laquelle on substitue l'aire légale (`pool_override` de `_deploy_pool_set` → `generate_compact_formation` → `deployment_preview_plan` → `_apply_deploy_plan`). Aire = bande de 6" d'un bord ∩ **plus de 8"** horizontalement de toute unité ennemie ∩ (hors zone adverse avant le 3e round). Le seuil des 8" est le jumeau de la zone d'engagement à une autre distance : `<= 8"` INTERDIT (`_ingress_enemy_clearance_forbidden`, miroir vectorisé de `entries_in_engagement_zone`, verrouillé par test d'équivalence). APRÈS : `units_ingressed_no_move` interdit tout autre mouvement (move ET `move_after_shooting`) jusqu'au DÉBUT de la phase de charge (`clear_ingress_move_lock`, appelé par `charge_phase_start`). Fin du 3e round : `destroy_unarrived_strategic_reserves` (règle de jeu, journalisée comme telle) ; exception « embarquées dans un transport » sans sujet (pas de transports). **Le pool ne dépend pas de l'unité** au-delà de son triplet de paramètres (`ingress_pool_signature`) : la case candidate y est traitée comme un point, le socle réel n'intervenant qu'à la pose. Toutes les réserves de même signature partagent donc UN calcul — mémoïsé par `(joueur, signature, positions ENNEMIES)`, les positions ennemies étant la seule chose qui peut bouger pendant la phase (`reactive_move`). Côté PvP, `precompute_ingress_pools` réchauffe pool ET contours à chaque action de la phase de mouvement (mesuré board x5 : 2,3 s la 1re fois pour 2 signatures, puis 9 ms par sélection) ; en entraînement le calcul reste paresseux. L'aperçu est rendu EN CONTOUR (57 538 cases → 1 contour de 2 286 points), dans la RÉPONSE de l'action `ingress_preview` et non dans `move_preview_footprint_mask_loops` : cette action est en lecture pure, donc rien n'effacerait ensuite une bande laissée dans le canal d'aperçu partagé et elle repartirait dans toutes les réponses suivantes. Le calcul passe par `ingress_preview_loops` (pur, mémoïsé) ; `set_ingress_preview_loops`, qui publie dans l'état, n'a plus d'appelant de production. **Siège PvP** : sélection de l'escouade dans le conteneur → `ingress_preview` (aire affichée en polygone comme l'aperçu de mouvement) → clic pour OUVRIR un plan éditable (`deploy_generate_formation`), puis MÊME édition par-figurine qu'au déploiement — glisser chaque figurine, suivre le bloc, voile rouge — bornée par l'aire d'arrivée et non par la zone de déploiement, parce que `placement_pool_for_squad` est le SEUL endroit qui répond à « où cette escouade a-t-elle le droit d'être posée ? » et qu'il rend l'aire 20.04 dès que l'escouade est en réserves. Validation par `ingress_commit`, qui revalide le plan du client contre l'aire du tour : `deploy_commit` poserait les figurines sans le verrou 20.04 ni la fin d'activation. L'agent, lui, garde `ingress_move` (une ancre, formation construite par le moteur) — son masque n'a qu'une case à proposer. Édition possible AVANT validation seulement : après, 20.04 verrouille l'unité. Un bouton `Reset` gris occupe, sur la ligne de l'escouade, l'emplacement du bouton `Strategic Reserve` dès qu'elle est posée en provisoire — il annule la mise en place sans rien écrire côté moteur, donc l'escouade reste à poser et peut être reprise après en avoir placé une autre. Même bouton, même emplacement, au déploiement comme à l'arrivée. Le clic n'est pris qu'au relâchement et immobile (un pointerdown gauche démarre le pan du plateau, et la pose est irréversible), et seulement dans la surface réellement peinte — trous compris, les bulles d'exclusion de 8" étant des boucles imbriquées (`pointInMaskLoopsEvenOdd`). Deux popups : « aucune arrivée légale » quand le pool est vide (raison rendue par le moteur), et avertissement de dernier round au début du tour du joueur concerné, accroché à `strategic_reserves.last_round`. Action agent = slots 4-8 (`ingress_slot_candidates`, mêmes 5 intentions que le déploiement mais triées SANS exposition de ligne de vue — mesuré : 2,98 s pour la seule LoS sur les 57 538 cases d'un pool Deep Strike, contre 0,16 s pour tout le reste ; ces colonnes ne servaient qu'au départage et l'agent ne les voit pas hors phase de déploiement) + WAIT pour renoncer. Tests `test_strategic_reserves_20.py` |
| 24.09 | Deep Strike | ✅ (2026-08-04) | Variante du pool 20.04 : contrainte de bord LEVÉE, 8" CONSERVÉS, zone adverse autorisée. Condition « if EVERY MODEL in this unit has this ability » testée PAR FIGURINE VIVANTE sur ses règles propres (`models_cache[mid]["UNIT_RULES"]`, jumeau du test par-figurine de 06.03) et NON sur l'union 19.04 — une escouade Deep Strike menée par un character qui ne l'a pas PERD la capacité. Portée par Chaplain with Jump Pack, Vanguard Veteran Squad with Jump Packs (3 types de figurines) et Land Speeder (datasheets Armageddon relues) |
| 03.01 | Moving (traverse alliés, pas ennemis, pas hors plateau) | ✅ | config `move.can_move_through_friendly_model` / `can_move_through_enemy_model` ; bord = bounds plateau |
| 03.02 | Set up (déploiement) | ✅ | `deployment_handlers` |
| 03.03 | Coherency (2″H/5″V d'≥1 modèle ; 9″H/5″V de chaque modèle ; regain en End of Turn) | 🟡 Adapté (2026-07-29) | **SOURCE UNIQUE** `coherency_violation_flags` (`shared_utils`) : move, déploiement, charge, pile-in ET consolidation la lisent. Avant le 2026-07-29 il y avait **trois** implémentations — la partagée (mode config) plus deux copies inline (charge, fight) qui ignoraient `cohesion_distance_mode` **et** la connexité ; une formation validée par un pile-in pouvait être refusée ensuite par le move (« formation actuelle DEJA incoherente », crash du training). **1re puce** = CONNEXITÉ : l'escouade doit former une seule chaîne (précision d'arbitre / FAQ), plus stricte que le « ≥ 1 voisin » littéral ; `squad_min_neighbors` reste appliqué comme degré minimal. **2e puce** = critère PAR PAIRES (« de CHAQUE autre modèle ») ; c'était un cercle d'étalement centré sur la paire la plus éloignée, mal posé (plusieurs paires à distance maximale exactement égale → verdict dépendant de la position absolue de l'escouade, invariance par translation cassée, cf. `test_coherency_translation_invariance.py`). **Métrique** = résolution (`spatial_relations.geometry_is_hex`) : hex centre-à-centre à x1 (1 fig = 1 hex), bord d'empreinte à x5+. **Placement initial** : la réduction de roster x5→x1 (`_downscale_fixed_unit`) pose désormais une formation connexe PAR CONSTRUCTION et vérifie l'écart max en sortie — c'était le seul chemin de placement sans contrôle, et il livrait des escouades déjà incohérentes (`test_roster_downscale_coherency.py`). `unit_model_cohesion_range`=2, `unit_global_cohesion_range`=9 ; composante verticale 5″ **non mesurée** (2D, à câbler avec le chantier étages) |
| 03.04 | Engagement range = 2″H/5″V | 🟡 Adapté + ⚠️ | `engagement_zone` (hex). ⚠️ `engagement_zone=2` ne vaut 2″ que si 1 hex=1″ (board 44x60x1) ; sur boards fins (5/10 hex par ″) → **vérifier override par board**. Vertical 5″ sans objet (2D) |
| 21.02 | Surge move | ⛔ Non implémenté | aucune unité avec capacité de surge |
| 21.03 | Flying (take to skies : −2″, ignore vertical, traverse tous modèles/terrains) | ✅ CONFORME (2026-08-07) | **Mot-clé** : `_unit_has_keyword` compare `keywordId` insensiblement à la casse, comme tous les autres lecteurs du moteur — le corpus de rosters écrit `"fly"` (16 fichiers) ET `"FLY"` (6), et l'égalité stricte perdait ces 6 en silence, dont **cinq types des rosters d'entraînement d'ArmageddonAgent** (cette ligne était donc FAUSSE avant le 2026-07-29 : la règle ne s'appliquait à aucune unité volante de l'agent). **Déclaration** : `took_to_the_skies` est la SOURCE UNIQUE ; le malus −2″ (`get_squad_move_budget`, `_charge_budget_subhex` — 2 POUCES convertis par `inches_to_subhex`) et la traversée (`_fly_traversal_active`) en dérivent tous deux, la dissociation n'est plus représentable. **Couverture** : les 4 mouvements que le PDF énumère — normal / advance / fall-back (`units_took_to_skies`) ET **charge** (`units_took_to_skies_charge`), via `_charge_fly_active` et `charge_build_valid_plan`. **Exclusion** : pile-in / consolidation (12) ne figurent pas dans 21.03 (ni le PDF 12 ni le PDF 03 ne mentionnent FLY) → pas de traversée, table `_TAKE_TO_THE_SKIES_BY_PHASE`. **« Ignore vertical » n'est PLUS trivial** : le moteur est multi-niveaux (planchers, `level`, coût de descente 13.06) — le vol annule `squad_descent_penalty_subhex`, effet réel et testé. **DÉCISION DU JOUEUR ACTIF, pour les DEUX sièges** (V11 §0.48 `L6`, 2026-08-07) : 21.03 confie la déclaration au joueur actif à chaque mouvement. Le joueur humain l'exerce par le toggle (`movement_set_fly_mode_handler` / `charge_set_fly_mode_handler`) ; le siège piloté par le modèle par un POINT DE CHOIX d'agent (`fly_declaration`, `CHOICE_0` = déclarer / `CHOICE_1` = renoncer), posé par `arm_fly_declaration_decision` **avant** la construction du pool — puisque la déclaration en change le budget et la traversée — et appliqué par `apply_fly_declaration_decision`. La politique moteur « déclare toujours » de §0.49 point 5 est SUPPRIMÉE : plus aucune part de la performance de l'agent ne tient à un choix qu'il ne fait pas. `obs_size` et `TOTAL_ACTION_SIZE` inchangés (le type consomme une réserve d'`AGENT_DECISION_TYPE_SLOTS`). Tests `test_fly_2103_conformity.py` + `test_fly_declaration_decision.py` (dont le routage `CHOICE_i` sur un vrai `W40KEngine`) |

**Limites techniques (moteur 2D / hex) :**
- **2D pour l'ENGAGEMENT et la COHERENCY** → leurs clauses « X″ vertical » (03.03, 03.04) restent sans objet. ⚠️ **Ne vaut plus pour le MOUVEMENT** : le moteur est multi-niveaux (planchers de terrain, `level` par figurine) et facture la descente 13.06 (`squad_descent_penalty_subhex` ; appelants vérifiés le 2026-07-29 : budget de move, frontière normal/advance, érosion du pool, et `charge_build_valid_plan`). L'« ignore vertical » de Fly (21.03) a donc un effet réel — il annule ce coût — et n'est plus une clause triviale.
- **Hex** → distances stockées en hex = pouces × `inches_to_subhex`. La règle reste exprimée en pouces ; le hex en dérive par board.
- **Pas de transports** → 18.04 sans objet, et avec lui la 1re exception de destruction de 20.04
  (« unités embarquées dans un transport ayant fait un ingress ») : elle est codée mais n'a aucun
  sujet tant que les transports n'existent pas. Les **réserves**, elles, sont implémentées
  (20.01→20.04, 24.09) depuis le 2026-08-04.

### Unités hors table — invariant géométrique

**Une unité hors table est VIVANTE mais absente du champ de bataille.** Source unique du
« où » : `deployed_on_turn` (`None` = hors table), dont `entry_is_on_battlefield` (sentinelle
`(-1,-1)` dans `units_cache`) est le jumeau côté cache ; `in_strategic_reserves` porte le
« pourquoi » (20.01), que la position ne peut pas exprimer. Une telle unité n'occupe AUCUNE
case (`occupied_hexes` vide), donc elle ne bloque rien, ne contrôle aucun objectif (14.02) et
n'est ni ciblable au tir, ni chargeable, ni engageable — mais elle compte toujours dans le
départage aux points.

**Comment cet invariant est TENU (structure, 2026-08-05).** Il ne l'était pas : `deployment_type:
"active"` laisse TOUTES les unités hors table au reset (mesuré 12/12), et une centaine de sites
de mesure les énuméraient quand même — le motif recopié `entry.get("occupied_hexes", {ancre})`
ne protégeait rien, la clé étant PRÉSENTE et VIDE hors table. Deux symptômes : l'empreinte vide
faisait lever `min_distance_between_sets` (bruyant), et surtout `occupied_hexes_by_model` est
lui PEUPLÉ de `(-1,-1)`, donc l'engagement partait sur le chemin 3D et rendait un verdict FAUX
sans crasher (mesuré x1/hex, EZ=2 : fantôme vs unité en `(0,0)` → « engagées »).

La tenue de l'invariant est désormais **structurelle**, dans la couche basse
`engine/spatial_relations.py` (`shared_utils` ré-exporte, les imports historiques sont intacts).
Règle : **une MESURE lève, un PRÉDICAT répond par la règle, une ÉNUMÉRATION filtre.**

| Primitive | Rôle | Hors table |
|---|---|---|
| `require_entry_on_battlefield(entry, what)` | garde nommée | **lève** |
| `entry_footprint(entry)` | empreinte d'escouade, SOURCE UNIQUE (remplace les 96 `.get` recopiés) | **lève** |
| `entries_in_engagement_zone(a, b, …)` | mesure EZ par paire | **lève** |
| `unit_within_engagement_zone_footprints(gs, u, …)` | prédicat « engagée ? » sur tout le plateau | **`False`** (20.01) |
| `entries_on_battlefield(cache, exclude_id=…)` | énumération, toutes unités | **écarte** |
| `enemy_entries_on_battlefield(cache, player, exclude_id=…)` | énumération, ennemis | **écarte** |

Le `False` du prédicat n'est pas un repli anti-erreur : la question « cette unité est-elle
engagée ? » a une réponse de RÈGLE (non, 20.01) et elle est posée sur TOUTES les unités vivantes
(snapshot 12.04, observation). La MESURE par paire, elle, n'a aucune réponse juste pour une
entrée sans position : elle lève, pour qu'un filtre oublié soit un crash localisable au lieu
d'un verdict inventé. C'est ce choix qui a permis de trouver les sites restants.

**Ce qui n'est PAS couvert par ces primitives, et reste une garde explicite** : les
`*_phase_start` / `*_build_activation_pool` de `shooting`, `charge` et `movement` portent la
règle « une unité hors table ne choisit pas d'arme, ne tire pas, ne charge pas, ne bouge pas »,
côté ACTEUR. Ce ne sont pas des filtres d'énumération d'ennemis, et les retirer serait un bug.
`ingress_eligible_units` (20.04) énumère au contraire les unités hors table : c'est sa raison
d'être, elle ne doit jamais passer par `entries_on_battlefield`.

⚠️ **Piège de test** : la sentinelle `(-1,-1)` est à ~274 subhex des zones de déploiement, donc
hors de toute portée d'arme. Un test qui met une unité en réserves sans CONSTRUIRE la géométrie
(unité réelle amenée près de l'origine) reste vert avec le défaut. Verrou :
`tests/unit/engine/test_off_table_geometry.py`.

### Règle 19 — clauses connexes auditées (2026-07-26, PDF relus : 19, 24 p5-p8, 25 p1-p3, 05 p5, 08)

- **24.22 LEADER / 24.34 SUPPORT** → renvoient à 19, aucun contenu propre : rien à implémenter au-delà de 19.01.
- **24.24 LONE OPERATIVE** (« unless part of an attached unit ») → **sans objet** : aucune donnée du projet ne déclare cette capacité (grep zéro dans `config/unit_rules.json` et les rosters). À rouvrir si une datasheet la déclare.
- **Appendix 25 — Starting strength** (« la starting strength d'une unité attachée = les figurines qu'elle contient au début ») → ✅ (2026-08-04, chantier 02) : le character replié est une figurine du squad, donc compté dans `model_count_at_start` (squad_cache, photographié APRÈS le fold 19.04). ⚠️ **La ligne précédente était FAUSSE sur un point** : elle affirmait que le `<=` du code couvrait « a unit that cannot be evenly divided in half cannot be at half-strength ». Il ne la couvrait pas — une escouade de 5 réduite à 2 était classée « à demi-effectif », état que la règle rend impossible. Les trois prédicats de l'appendice sont désormais SÉPARÉS (`is_unit_below_starting_strength`, `is_unit_at_half_strength` avec clause de parité, `is_unit_below_half_strength`), et le déclencheur de 08.03 est leur union explicite (`is_unit_at_or_below_half_strength`). Test `test_command_points_and_battle_shock.py`.
- **Appendix 25 — Revived** (un leader revivé reste dans son unité attachée) → **sans objet**, aucune mécanique de revive.
- **24.28 PRECISION** → implémenté et cohérent avec le fold : le character est une figurine du squad, donc un groupe d'allocation ciblable. Le critère « CHARACTER model » est aujourd'hui le **rôle** leader/support, pas le keyword `CHARACTER` — équivalent sur les données actuelles, non verrouillé par un test.

---

## 🎯 Phase de tir (SHOOTING PHASE)

> ⚠️ **MAJ 2026-07-26 (V11 T-B)** — les arbres de cette section décrivent le chemin PvP/mono. Le
> chemin SQUAD/GYM résout un **type de tir** (10.04 normal / 10.05 assault / 10.06
> close-quarters) via `resolve_squad_shooting_type`, qui commande les armes sélectionnables. Le
> volet MONSTER/VEHICLE de 10.06 (−1 au jet, [BLAST] interdit sur unité engagée) n'existe que
> côté squad — divergence connue, cf.
> [`observation_et_actions.md`](../training/observation_et_actions.md) §1.9.

### SECTION 1 : variables globales et tables de référence

**Variables globales :**
```javascript
weapon_rule = (weapon rules activated) ? 1 : 0

// Units cache - source de vérité des positions/HP des unités vivantes
units_cache = {
    unit_id: {id: unit_id, col: col, row: row, HP_CUR: hp, player: player},
    ...
}
// Mise à jour: Quand une cible meurt, update_units_cache_hp(..., 0) la retire
```

**Cache par unité active :**
```javascript
// Cache LoS par unité active (stocké sur l'unité) — obscuring-aware (compute_unit_los)
unit["los_cache"] = {
    target_id: can_see,  // booléen (murs + obscuring, rule 13.10)
    ...
}
unit["los_cover_cache"] = {
    target_id: cover,    // booléen (rule 13.08 → −1 BS au tir)
    ...
}
// Calculé à:
// - Activation de l'unité
// - Fin d'advance de l'unité
// Mis à jour à:
// - Mort de la cible: retirer unit["los_cache"][dead_target_id] (pas de recalcul)
// Nettoyé à:
// - Fin de l'activation (comme valid_target_pool)
```

**Table des arguments (Function Argument Reference Table) :**

| Function | arg1 | arg2 | arg3 |
|----------|------|------|------|
| `valid_target_pool_build(arg1, arg2, arg3)` | weapon_rule (use weapon rules?) | advance_status: 0=no advance, 1=advanced | adjacent_status: 0=not adjacent, 1=adjacent to enemy |
| `weapon_availability_check(arg1, arg2, arg3)` | weapon_rule | advance_status: 0=no advance, 1=advanced | adjacent_status: 0=not adjacent, 1=adjacent to enemy |

**Note critique sur arg3 après advance :** quand l'unité a avancé (arg2=1), arg3 vaut TOUJOURS 0
— les restrictions d'advance interdisent les destinations adjacentes à l'ennemi.

**Drapeaux d'état (State Flags CAN_SHOOT, CAN_ADVANCE) :**

Déterminés à l'ELIGIBILITY CHECK :
- `CAN_ADVANCE = true` si l'unité n'est PAS adjacente à un ennemi (sinon `false`).
- `CAN_SHOOT = true` si `weapon_availability_check()` rend un pool non vide (sinon `false`).

Mis à jour après une action advance (si l'unité a réellement bougé) :
- `CAN_ADVANCE = false` (déjà avancé, ne peut plus avancer) ;
- `CAN_SHOOT = (weapon_availability_check(weapon_rule, 1, 0) rend un pool non vide)` — seules les
  armes ASSAULT restent disponibles si weapon_rule=1.

**Constante d'affichage (UI Display Constants) :** l'aperçu de tir affiche en BLEU, pour les
deux sièges (IA et humain), toutes les cases en ligne de vue et dans `selected_weapon.RNG`.

### Ligne de vue et couvert — source unique (rules 13.07–13.10)

Toute visibilité unité→unité passe par une primitive unique consciente de l'obscuring,
`compute_unit_los(game_state, shooter, target) → {can_see, fully_visible, cover, visible, total}`
(`engine/phase_handlers/shooting_handlers.py`). Construction de pool, éligibilité, validation de
cible, résolution de tir, aperçu ET observation IA la traversent tous : le moteur applique UNE
visibilité cohérente partout. `_has_line_of_sight()` est une enveloppe fine au-dessus. Le chemin
squad-shoot utilise la même primitive via `_attacker_model_can_reach_squad`.

**Ce qui bloque une ligne (hex, à la demande)** : un **mur dense** (toujours) OU une **zone de
terrain obscurante** que NI le tireur NI la cible n'occupe (rule 13.10 — obscuring intermédiaire,
zones occupées exclues). Les figurines ne bloquent jamais la LoS, seul le terrain. Les zones
obscurantes sont des polygones rastérisés en hex au chargement (`terrain_areas` sur le
game_state, chacune `{id, obscuring, polygon_vertices, hexes}`).

**Échantillonnage (rule 1.x « any part → any part »)** : la **cible** est échantillonnée sur son
**empreinte complète** (visible ssi une partie est atteignable) ; le **tireur** sur son **hex
d'ancre + deux extrêmes perpendiculaires de l'empreinte** (« peek » latéral, évalué en 2e chance
seulement si la ligne d'ancre est bloquée). `visible/total` = fraction des hex d'empreinte de la
cible atteignables.

- `can_see` ⇔ `ratio > 0` (au moins un hex du socle cible atteignable — règle 06.01 ; **aucun
  seuil minimum de ratio**).
- `fully_visible` ⇔ tous les hex d'empreinte de la cible sont atteignables.

**Benefit of Cover (rule 13.08) — appliqué en −1 BS, pas en bonus de save.** Une cible a un
couvert quand elle est visible ET remplit ≥ 1 condition (niveau unité) : (1) elle est
**hideable** (INFANTRY/BEASTS/SWARM) ET **dans une zone de terrain**, OU (2) elle n'est **pas
fully visible**. Cible à couvert + arme sans `IGNORES_COVER` → le **seuil de hit est aggravé de
+1** (BS −1) — la save n'est plus modifiée par le couvert. Le seuil legacy `cover_ratio` n'est
**plus utilisé** pour la décision de couvert (il ne subsiste que dans des diagnostics d'overlay
d'aperçu et peut être retiré).

**Hidden (rule 13.09)** : une unité est `hidden` quand elle est hideable, **dans une zone
obscurante**, et n'a fait **aucune attaque à distance ce tour ni le précédent** (`units_shot` /
`units_shot_previous_turn`, photographié à chaque début de tour). Un ennemi hidden n'est ciblable
que par un tireur à **portée de détection** (`detection_range` dans `game_rules`,
`config/game_config.json`, en pouces, scalé par `inches_to_subhex`) ; au-delà, l'unité hidden est
exclue du pool de cibles valides.

**Perf** : `compute_unit_los` est mémoïsé par `(shooter_id, target_id)` et invalidé dès qu'une
unité bouge (`_unit_move_version`) ; les hex obscurants sont pré-mappés (`hex → area id`) donc
l'exclusion est O(1) par cellule tracée. Une observation complète coûte quelques ms.

### Restrictions de ciblage (Target Restrictions Logic)

**Conditions d'une cible valide (TOUTES vraies) :**
1. **Portée** : ennemi dans `selected_weapon.RNG` hexes (par arme).
2. **Ligne de vue (obscuring-aware, `compute_unit_los`)** :
   - `can_see` ⇔ `ratio > 0` (au moins un hex du socle cible visible — règle 06.01 ; aucun seuil
     minimum). Blocage : mur dense OU terrain obscurant non occupé (règle 13.10).
   - **Cover** (rule 13.08) : conditionnel, pas un ratio — `can_see AND ((hideable AND in a
     terrain area) OR not fully_visible)` → **−1 BS** à la résolution (pas de bonus de save, pas
     de `cover_ratio`).
3. **Exclusion mêlée** : ennemi NON adjacent au tireur (adjacent = combat au corps à corps).
4. **Anti-friendly-fire** : ennemi NON adjacent à une unité amie.
5. **Hidden (rule 13.09)** : un ennemi `hidden` n'est valide que si une figurine tireuse est à
   `detection_range`.

**Une cible devient invalide quand :** elle meurt pendant l'action de tir ; elle sort de portée ;
la ligne de vue se bloque (rares pendant la phase de tir).

### SECTION 2 : fonctions cœur (CORE FUNCTIONS)

#### player_advance()
**Rôle** : exécuter le mouvement d'advance pour le joueur humain.
**Retour** : booléen (true si l'unité a réellement bougé vers un hex différent).

```javascript
player_advance():
├── Roll 1D6 → advance_range (from config: advance_distance_range)
├── Display advance_range on unit icon (bottom right)
├── Build valid_advance_destinations (BFS, advance_range, no walls, no enemy-adjacent)
├── Highlight destinations in ORANGE
├── Left click on valid advance hex → Move unit
│   └── Return: true (unit actually moved to different hex)
├── Left or Right click on the unit's icon
│   └── Return: false (unit didn't advance)
└── Remove advance icon from the unit
```

#### weapon_availability_check(arg1, arg2, arg3)
**Rôle** : filtrer les armes selon règles et contexte.
**Retour** : weapon_available_pool (armes sélectionnables). Boucle sur CHAQUE arme ranged.

```javascript
weapon_availability_check(arg1, arg2, arg3):
For each weapon:
├── Check arg1 (weapon_rule):
│   ├── arg1 = 0 → No weapon rules checked/applied (continue to next check)
│   └── arg1 = 1 → Weapon rules apply (continue to next check)
├── Check arg2 (advance_status):
│   ├── arg2 = 0 → No restriction (continue to next check)
│   └── arg2 = 1 → Unit DID advance:
│       ├── arg1 = 0 → ❌ Weapon CANNOT be selectable (skip weapon)
│       └── arg1 = 1 → ✅ Weapon MUST have ASSAULT rule (continue to next check)
├── Check arg3 (adjacent_status):
│   ├── arg3 = 0 → No restriction (continue to next check)
│   └── arg3 = 1 → Unit IS adjacent to enemy:
│       ├── arg1 = 0 → ❌ Weapon CANNOT be selectable (skip weapon)
│       └── arg1 = 1 → ✅ Weapon MUST have CLOSE_QUARTERS rule (continue to next check)
├── Check weapon.shot flag:
│   ├── weapon.shot = 0 → No restriction (continue to next check)
│   └── weapon.shot = 1 → ❌ Weapon CANNOT be selectable (skip weapon)
└── Check weapon.RNG and target availability:
    ├── weapon.RNG > 0? → NO → ❌ Weapon CANNOT be selectable (skip weapon)
    └── YES → Check if at least ONE enemy unit meets ALL conditions:
        │   Conditions (ALL must be true for at least one enemy):
        │   ├── Within weapon.RNG range (distance <= weapon.RNG)
        │   ├── In Line of Sight (no dense wall AND no intervening obscuring terrain blocking — compute_unit_los)
        │   ├── HP_CUR > 0 (alive)
        │   └── NOT adjacent to friendly unit (excluding active unit)
        │       └── EXCEPTION: If enemy is adjacent to shooter AND weapon has CLOSE_QUARTERS rule:
        │           └── ✅ Can shoot at adjacent enemy (even if engaged with other friendly units)
        │       └── If enemy is NOT adjacent to shooter:
        │           └── ❌ Cannot shoot if enemy is adjacent to any friendly unit
        └── If NO enemy meets ALL conditions → ❌ Weapon CANNOT be selectable (skip weapon)
        └── If at least ONE enemy meets ALL conditions → ✅ Add weapon to weapon_available_pool
```

#### build_units_cache()
**Rôle** : construire le cache des unités vivantes (positions + HP).
Implémentation : `def build_units_cache` (`engine/phase_handlers/shared_utils.py`).

```javascript
build_units_cache():
├── units_cache = {}
├── For each unit in game_state["units"]:
│   ├── unit.HP_CUR > 0? → NO → ❌ Skip (dead unit)
│   └── YES → ✅ Add to units_cache
│       └── units_cache[unit.id] = {id, col, row, HP_CUR, player}
└── Store in game_state["units_cache"]
```

**Appelé à :** reset du jeu (une seule fois).

**Note d'implémentation** : `units_cache` est la source de vérité pour position, `HP_CUR` et
aliveness des unités vivantes. Les unités mortes sont retirées via `update_units_cache_hp(..., 0)`
(tir/fight). **`HP_CUR`** a une source unique : seul `update_units_cache_hp` écrit `HP_CUR` en
jeu ; pour « vivant », utiliser `is_unit_alive(unit_id, game_state)`. Voir `architecture_moteur.md`
(section Units cache & HP_CUR).

#### build_unit_los_cache(unit_id)
**Rôle** : calculer le cache LoS d'une unité (voir la section LoS ci-dessus pour la définition).
Implémentation : `def build_unit_los_cache` (`engine/phase_handlers/shooting_handlers.py`).

```javascript
build_unit_los_cache(unit_id):
├── unit = get_unit_by_id(unit_id)
├── For each alive enemy target in units_cache:
│   ├── los = compute_unit_los(game_state, unit, target_unit)   // walls + obscuring (rule 13.10)
│   ├── unit["los_cache"][target_id]       = los["can_see"]
│   └── unit["los_cover_cache"][target_id] = los["cover"]        // rule 13.08 (→ −1 BS at resolution)
└── Caches stored on the unit; per-pair results memoized in _unit_los_pair_cache
```

**Optimisation** : utilise `has_line_of_sight_coords()` (cache `hex_los_cache` entre mêmes
coordonnées) au lieu de recherches linéaires dans `game_state["units"]` — complexité O(m), m =
cibles ennemies dans `units_cache`.

**Appelé à :** activation de l'unité (STEP 2) ; fin d'advance effectif. **PAS** après mort de
cible (on retire juste l'entrée du cache).

**Cas limites :** aucun ennemi vivant → `unit["los_cache"] = {}` (vide mais existant) ; unité qui
a fui → `los_cache` **non construit** (elle ne peut pas tirer).

#### update_los_cache_after_target_death(dead_target_id)
Implémentation : `def update_los_cache_after_target_death` (`engine/phase_handlers/shooting_handlers.py`).

```javascript
update_los_cache_after_target_death(dead_target_id):
├── units_cache est mis à jour par update_units_cache_hp(..., 0) (cible retirée)
├── active_unit_id = game_state["active_shooting_unit"]  // Seule l'unité active a un los_cache
├── If active_unit_id AND active_unit["los_cache"] exists AND dead_target_id in cache:
│   └── del active_unit["los_cache"][dead_target_id]
└── Caches mis à jour (pas de recalcul)
```

**Note** : seule l'unité active a un `los_cache` (les autres unités du pool ne sont pas encore
activées). Appelé après la mort d'une cible dans le contrôleur d'attaque de tir.

#### valid_target_pool_build(arg1, arg2, arg3)
**Rôle** : construire le pool de cibles valides de l'unité active.
Implémentation : `engine/phase_handlers/shared_utils.py`.

**Fonctionnement :**
1. `build_unit_los_cache` a stocké `unit["los_cache"] = {target_id: has_los}`.
2. On filtre `los_cache` pour ne garder que les cibles avec `has_los == true`.
3. Pour chaque cible avec LoS : distance (portée d'**au moins une arme** du
   `weapon_available_pool` — l'unité peut changer d'arme), règle CLOSE_QUARTERS (si adjacent),
   règle « engaged enemy » (si pas adjacent).
4. Les cibles qui passent tous les checks entrent dans le pool.

```javascript
valid_target_pool_build(arg1, arg2, arg3):
├── valid_target_pool = []
├── ASSERT: unit["los_cache"] exists (doit être créé par build_unit_los_cache à l'activation)
├── weapon_available_pool = weapon_availability_check(arg1, arg2, arg3)
├── usable_weapons = [w for w in weapon_available_pool if w["can_use"]]
├── Filter los_cache: targets_with_los = {target_id for (target_id, has_los) if has_los == true}
├── For each target_id in targets_with_los:
│   ├── distance = calculate_distance(unit, enemy_unit)
│   ├── Range check: distance <= RNG of AT LEAST ONE weapon in usable_weapons? → NO → Skip
│   ├── Adjacent check: enemy adjacent to shooter?
│   │   ├── YES → Check CLOSE_QUARTERS weapon rule
│   │   └── NO → Check engaged enemy rule
│   └── ALL conditions met → ✅ Add target_id to valid_target_pool
└── Return valid_target_pool
```

**Cas limites :**
- `los_cache` absent ET `unit.id NOT in units_fled` : **ERREUR** (doit être créé à l'activation).
- `los_cache` absent ET `unit.id in units_fled` : NORMAL — l'unité ne peut pas tirer, mais peut
  avancer ; `valid_target_pool_build` n'est pas appelé.
- `los_cache` vide `{}` : aucun ennemi dans `units_cache` → pool vide.
- Pool vide ET unité n'a pas encore tiré : → STEP 6 EMPTY_TARGET_HANDLING (advance possible si
  `CAN_ADVANCE`).
- Pool vide ET unité a déjà tiré : → fin d'activation (**pas d'advance après avoir tiré**).

#### weapon_selection() (humain uniquement)

```javascript
weapon_selection():
├── Opens weapon selection menu
├── Weapons in weapon_available_pool: displayed normally, selectable
├── Weapons NOT in weapon_available_pool: displayed greyed, NOT selectable
├── Click on weapon in weapon_available_pool:
│   ├── selected_weapon = clicked weapon
│   ├── SHOOT_LEFT = selected_weapon.NB
│   ├── Determine context: arg1 = weapon_rule ; arg2 = (unit in units_advanced) ? 1 : 0 ;
│   │   arg3 = (unit adjacent to enemy) ? 1 : 0
│   ├── valid_target_pool_build(arg1, arg2, arg3)
│   ├── Close weapon selection menu
│   └── Return: weapon selected (continue to shooting action selection)
├── Click weapon selection icon OR click outside menu:
│   ├── Close weapon selection menu
│   └── Return: no weapon selected (continue with current weapon)
```

#### shoot_action(target)

```javascript
shoot_action(target):
├── Execute attack_sequence(RNG)
├── Concatenate Return to TOTAL_ACTION log
├── SHOOT_LEFT -= 1
├── Target died?
│   ├── YES →
│   │   ├── update_los_cache_after_target_death(target_id)
│   │   ├── Remove from valid_target_pool
│   │   └── valid_target_pool empty? → YES → End activation
│   └── NO → Target survives
└── SHOOT_LEFT == 0 ?
    ├── YES → Current weapon exhausted:
    │   ├── Mark selected_weapon as used
    │   └── weapon_available_pool NOT empty?
    │       ├── YES → Select next available weapon:
    │       │   ├── selected_weapon = next weapon ; SHOOT_LEFT = selected_weapon.NB
    │       │   ├── Determine context (arg1/arg2/arg3 comme weapon_selection)
    │       │   ├── valid_target_pool_build(weapon_rule, arg2, arg3)  // Utilise unit["los_cache"]
    │       │   └── Continue to shooting action selection
    │       └── NO → All weapons exhausted → End activation
    └── NO → Continue normally (SHOOT_LEFT > 0):
        └── Continue to shooting action selection step
```

**« Continue normally »** (contrôle de flux) : après un tir avec SHOOT_LEFT > 0 restant —
1. traiter l'issue de la cible (morte/survivante) ; 2. mettre à jour valid_target_pool ;
3. contrôle de sécurité final (slaughter handling si plus de cible) ; 4. reboucler sur la
sélection d'action de tir. Maintient la séquence multi-tirs jusqu'à SHOOT_LEFT = 0 ou plus de
cible.

#### POSTPONE_ACTIVATION() (humain uniquement)
**Déclencheur** : le joueur clique ailleurs sans tirer ET l'unité n'a tiré avec AUCUNE arme.

```javascript
POSTPONE_ACTIVATION():
├── Unit is NOT removed from shoot_activation_pool (can be re-activated later)
├── Remove weapon selection icon from UI
└── Return to UNIT_ACTIVABLE_CHECK step
```

### SECTION 3 : flux de la phase (PHASE FLOW, STEP 0 → 7)

#### STEP 0: PHASE INITIALIZATION

**Appelé à :** début de la phase de tir (automatiquement dans `execute_action` si
`_shooting_phase_initialized` est False) ; une seule fois par phase.

```javascript
shooting_phase_start():
├── Set phase = "shoot"
├── Initialize weapon_rule = 1
├── Clear target_pool_cache (cache global obsolète)
├── Initialize weapon.shot = 0 for all units
├── Pre-select a valid weapon and set SHOOT_LEFT for current player units
├── shooting_build_activation_pool()  // Build shoot_activation_pool (appelle STEP 1)
└── Continue to STEP 2: UNIT_ACTIVABLE_CHECK
```

**Cache kill probability :** `game_state["kill_probability_cache"]` n'est plus construit en
début de phase — rempli à la demande (lazy) au premier appel de `select_best_ranged_weapon()` /
`select_best_melee_weapon()` pour une paire (unité, cible). Voir `engine/ai/weapon_selector.py`.

#### STEP 1: ELIGIBILITY CHECK (Pool Building Phase)

**Sortie** : shoot_activation_pool (unités éligibles).

```javascript
shooting_build_activation_pool():
├── shoot_activation_pool = []
├── For each unit in game_state["units"]:
│   ├── unit.player === current_player? → NO → Skip
│   ├── unit.HP_CUR > 0? → NO → Skip
│   ├── unit.id in units_fled? → YES → Check CAN_ADVANCE only (cannot shoot)
│   │   ├── Determine adjacency: Unit adjacent to enemy? → YES → CAN_ADVANCE = false, NO → CAN_ADVANCE = true
│   │   ├── CAN_ADVANCE == true? → YES → Add unit.id to pool (can advance but not shoot)
│   │   └── CAN_ADVANCE == false? → Skip (no valid actions)
│   ├── unit.id NOT in units_fled? → Check CAN_SHOOT OR CAN_ADVANCE
│   │   └── Determine adjacency: Unit adjacent to enemy?
│   │       ├── YES →
│   │       │   ├── CAN_ADVANCE = false (cannot advance when adjacent)
│   │       │   ├── weapon_availability_check(weapon_rule, 0, 1) → Build weapon_available_pool
│   │       │   ├── CAN_SHOOT = (weapon_available_pool NOT empty)
│   │       │   └── CAN_SHOOT == false? → Skip ; sinon → Add unit.id to pool
│   │       └── NO →
│   │           ├── CAN_ADVANCE = true
│   │           ├── weapon_availability_check(weapon_rule, 0, 0) → Build weapon_available_pool
│   │           ├── CAN_SHOOT = (weapon_available_pool NOT empty)
│   │           └── (CAN_SHOOT OR CAN_ADVANCE)? → NO → Skip ; YES → Add unit.id to pool
│   └── Continue
└── Store in game_state["shoot_activation_pool"]
```

**IMPORTANT :** une unité qui a fui (`units_fled`) peut avancer mais **ne peut pas tirer** ; elle
entre dans le pool si `CAN_ADVANCE == true` (pas adjacente à un ennemi).

#### STEP 2: UNIT_ACTIVABLE_CHECK

```javascript
STEP : UNIT_ACTIVABLE_CHECK
├── shoot_activation_pool NOT empty?
│   ├── YES → Pick one unit from shoot_activation_pool:
│   │   ├── Clear valid_target_pool
│   │   ├── Clear TOTAL_ATTACK log
│   │   ├── build_unit_los_cache(unit_id)  // Calculer cache LoS
│   │   ├── Determine adjacency → unit_is_adjacent = true/false
│   │   ├── weapon_availability_check(weapon_rule, 0, unit_is_adjacent ? 1 : 0)
│   │   ├── valid_target_pool_build(weapon_rule, arg2=0, arg3=unit_is_adjacent ? 1 : 0)
│   │   └── valid_target_pool NOT empty?
│   │       ├── YES → SHOOTING ACTIONS AVAILABLE → Go to STEP 3: ACTION_SELECTION
│   │       └── NO → valid_target_pool is empty → Go to STEP 6: EMPTY_TARGET_HANDLING
│   └── NO → End of shooting phase → Advance to charge phase
```

**IMPORTANT :** pour une unité qui a fui, on ne construit ni `los_cache` ni `valid_target_pool`.

#### STEP 3: ACTION_SELECTION (état initial, valid_target_pool NOT empty)

```javascript
STEP : ACTION_SELECTION (Initial State)
├── Pre-select first available weapon
├── SHOOT_LEFT = selected_weapon.NB
├── Display shooting preview: Blue hexes (LoS and selected_weapon.RNG)
├── Display HP bar blinking animation for units in valid_target_pool
├── Build VALID_ACTIONS list:
│   ├── If unit.CAN_SHOOT = true AND valid_target_pool NOT empty → Add "shoot"
│   ├── If unit.CAN_ADVANCE = true → Add "advance"
│   └── Always add "wait"
├── ❌ INVALID ACTIONS: [move, charge, attack] → end_activation(ERROR, 0, 0, SHOOTING, 1, 1) → UNIT_ACTIVABLE_CHECK
└── Execute chosen action:
    ├── "advance" → Go to STEP 4: ADVANCE_ACTION
    ├── "shoot" → Go to STEP 5: SHOOTING_ACTION_SELECTION (normal)
    └── "wait" → Go to STEP 7: WAIT_ACTION
```

**IA vs humain :** l'IA choisit programmatiquement dans VALID_ACTIONS ; l'humain clique les
éléments d'UI (icône advance, cible, icône de sélection d'arme, ou icône de l'unité).

#### STEP 4: ADVANCE ACTION

```javascript
ADVANCE ACTION:
├── Execute advance movement
├── Unit actually moved to different hex?
│   ├── YES → Unit advanced:
│   │   ├── Mark units_advanced — journalisé end_activation(ACTION, 1, ADVANCE, NOT_REMOVED, 1, 0) :
│   │   │   l'unité RESTE dans le pool (elle peut encore tirer en ASSAULT), cercle vert conservé
│   │   ├── build_unit_los_cache(unit_id)  // Recalculer cache LoS avec nouvelle position
│   │   ├── Invalidate valid_target_pool (vide le pool)
│   │   ├── weapon_availability_check(weapon_rule, 1, 0) → seules armes ASSAULT ; CAN_SHOOT mis à jour ;
│   │   │   CAN_ADVANCE = false
│   │   ├── valid_target_pool_build(weapon_rule, arg2=1, arg3=0)  // Reconstruire pool avec nouveau cache
│   │   └── valid_target_pool NOT empty AND CAN_SHOOT → Continue to STEP 5B ;
│   │       sinon → end_activation(ACTION, 1, ADVANCE, SHOOTING, 1, 1) → UNIT_ACTIVABLE_CHECK
│   └── NO → Unit didn't move → Continue normally (reste au choix d'action, non marquée units_advanced)
```

Le cache LoS est recalculé après l'advance, puis le pool est reconstruit.

#### STEP 5: SHOOTING_ACTION_SELECTION

Deux variantes : normale (pas d'advance) et post-advance.

##### STEP 5A: SHOOTING_ACTION_SELECTION (Normal - unit has NOT advanced)

```javascript
STEP : SHOOTING_ACTION_SELECTION (Normal)
├── Display shooting preview
├── Display HP bar blinking animation
├── Human only: Display weapon selection icon (if CAN_SHOOT)
└── Action handling:
    ├── Weapon selection (Human only):
    │   ├── Left click on weapon selection icon → weapon_selection() → Return to this step
    │   └── Continue with current weapon
    ├── Shoot action:
    │   ├── AI: Select best target from valid_target_pool
    │   ├── Human: Left click on target in valid_target_pool
    │   ├── Execute shoot_action(target) → See shoot_action() function above
    │   └── After shoot_action():
    │       ├── If activation ended → Go to UNIT_ACTIVABLE_CHECK
    │       └── Else → Return to this step
    ├── Wait action (Human only):
    │   ├── Left/Right click on active_unit
    │   └── Check if unit has shot with ANY weapon (any weapon.shot = 1)?
    │       ├── YES → end_activation(ACTION, 1, SHOOTING, SHOOTING, 1, 1) → UNIT_ACTIVABLE_CHECK
    │       └── NO → end_activation(WAIT, 1, 0, SHOOTING, 1, 1) → UNIT_ACTIVABLE_CHECK
    └── Postpone/Click elsewhere (Human only):
        ├── Left click on another unit in shoot_activation_pool
        ├── Left/Right click anywhere else (treated as potential misclick)
        └── Check if unit has shot with ANY weapon?
            ├── NO → POSTPONE_ACTIVATION() → UNIT_ACTIVABLE_CHECK
            └── YES → Do not end activation automatically (allow user to click active unit to confirm) → Return to this step
```

##### STEP 5B: ADVANCED_SHOOTING_ACTION_SELECTION (Post-advance state)

```javascript
STEP : ADVANCED_SHOOTING_ACTION_SELECTION (Post-advance)
├── Display shooting preview
├── Display HP bar blinking animation
├── Human only: Display weapon selection icon (if CAN_SHOOT)
├── 🎯 VALID ACTIONS: [shoot (if CAN_SHOOT), wait]
├── ❌ INVALID ACTIONS: [advance, move, charge, attack] → end_activation(ERROR, 0, 0, SHOOTING, 1, 1) → UNIT_ACTIVABLE_CHECK
└── Action handling:
    ├── Weapon selection (Human only): comme STEP 5A
    ├── Shoot action: comme STEP 5A (note: still in ADVANCED state, arg2=1)
    ├── Wait action:
    │   ├── AI: Agent chooses wait ; Human: Left/Right click on active_unit
    │   └── Check if unit has shot with ANY weapon?
    │       ├── YES → end_activation(ACTION, 1, SHOOTING, SHOOTING, 1, 1) → UNIT_ACTIVABLE_CHECK
    │       └── NO → Unit has not shot yet (only advanced) → end_activation(ACTION, 1, ADVANCE, SHOOTING, 1, 1) → UNIT_ACTIVABLE_CHECK
    └── Postpone/Click elsewhere (Human only): comme STEP 5A
```

#### STEP 6: EMPTY_TARGET_HANDLING (valid_target_pool is empty)

```javascript
STEP : EMPTY_TARGET_HANDLING
└── unit.CAN_ADVANCE = true?
    ├── YES → Only action available is advance:
    │   ├── Display ADVANCE icon (waiting for user click)
    │   ├── Human: Click ADVANCE logo → ⚠️ POINT OF NO RETURN
    │   │   └── Execute player_advance() → Roll 1D6 → advance_range → Build destinations → unit_advanced (boolean)
    │   ├── Human: Left or Right click on the active_unit → No effect →
    │   │   end_activation(WAIT, 1, 0, SHOOTING, 1, 1) → UNIT_ACTIVABLE_CHECK
    │   │   (décliner l'advance SANS franchir le point de non-retour)
    │   └── unit_advanced = true?
    │       ├── YES → end_activation(ACTION, 1, ADVANCE, SHOOTING, 1, 1) → UNIT_ACTIVABLE_CHECK
    │       └── NO → end_activation(WAIT, 1, 0, SHOOTING, 1, 1) → UNIT_ACTIVABLE_CHECK
    └── NO → unit.CAN_ADVANCE = false → No valid actions available:
        └── end_activation(WAIT, 1, 0, SHOOTING, 1, 1) → UNIT_ACTIVABLE_CHECK
```

#### STEP 7: WAIT_ACTION

```javascript
STEP : WAIT_ACTION
├── AI: Agent chooses wait          ← seulement si le masque ouvrait AUTRE CHOSE que `wait`
├── AI: sinon, le MOTEUR joue le wait lui-même (attente FORCÉE, cf. ci-dessous)
├── Human: Player chooses wait
└── end_activation(WAIT, 1, 0, SHOOTING, 1, 1) → UNIT_ACTIVABLE_CHECK
```

**ATTENTE FORCÉE — chemin gym uniquement** (`W40KEngine.step_with_mask`)

Quand le masque n'ouvre QUE `wait`, l'agent n'a rien à décider : le moteur joue l'attente
lui-même et enchaîne, au lieu de rendre la main pour une question à une seule réponse.

- **Récompense = 0** pour la part `base_actions.wait` (`RewardCalculator._wait_reward`, source
  unique des branches `wait` et `squad_wait`). La pénalité de −0,1 sanctionne la passivité
  CHOISIE ; l'appliquer à une non-décision ajoute au signal un terme que l'agent ne peut pas
  éviter. La récompense d'objectif éventuelle, elle, est conservée et cumulée.
- **Le step reste un step du moteur** : `episode_steps`, `action_family_counts`, le StepLogger et
  le garde anti-runaway (`_episode_step_calls`) le comptent comme les autres, parce que le rejeu
  passe par `step_with_mask` lui-même et non par un chemin d'exécution parallèle.
- **Borne** : `FORCED_WAIT_CHAIN_LIMIT` (`engine/w40k_core.py`) n'est pas un réglage de jeu mais
  un détecteur de boucle — la chaîne se draine seule, chaque attente retirant une escouade de son
  pool.
- **`info` reste celui de l'action de l'APPELANT**, sauf les clés de FIN D'ÉPISODE
  (`TERMINAL_INFO_KEYS` : `winner`, `win_method`, `episode`, `tactical_data`, `deployment_mode`,
  `turn_limit_exceeded`, `truncation_reason`, `truncation_debug`), reprises du dernier step de la
  chaîne. Les deux sens comptent : écraser `info` en bloc ferait disparaître la dernière action
  réelle de chaque phase (`ai/env_wrappers.AGENT_STEP_INFO_KEYS` est prélevé APRÈS le retour du
  moteur), et NE rien reprendre fait perdre son bilan à tout épisode qui se termine pendant une
  chaîne — `ai/training_callbacks._handle_episode_end` exige `tactical_data` et `deployment_mode`
  par `require_key`, et le run meurt dessus. Cette énumération n'est pas déclarative : le bloc de
  terminaison pose ses clés dans un dict dédié et `step_with_mask` LÈVE si l'une n'y figure pas.
- **PvP et bots ne sont pas concernés** : le drapeau `_wait_was_forced` n'existe que sur le chemin
  gym, et son absence conserve exactement le comportement antérieur.

Mesure ayant motivé le changement (scénario d'entraînement Armageddon, politique neuve) : 31,8
attentes forcées par épisode, soit −3,18 de pénalité inévitable et ~16 % des steps. 28 des 31,8
sont en phase de tir — le pool de tir retient toute unité ARMÉE sans exiger qu'elle ait une CIBLE
(`shoot_pool_require_los_target` à `False` par défaut, le pool exact coûtant ~1,5 s par
transition). **Ce changement déplace les récompenses : il exige un ré-entraînement.**

Ce qui devient incomparable d'avant à après, et ce qui ne l'est PAS — le message du commit
`de19a6bb` se trompe sur ce point, cette ligne fait foi :

- **Incomparables** : les courbes de récompense (`ep_rew_mean`, les cinq `reward/*_total`,
  `reward/objective_share`). À jeu identique, un épisode gagne désormais jusqu'à +3,18.
- **Comparables, aucun recalibrage à faire** : le gate et le score robuste. Les quatre seuils
  (`model_gating_min_combined`, `min_worst_bot`, `min_worst_scenario_combined`, `min_vs_control`)
  comparent des TAUX DE VICTOIRE dans [0,1] (`ai/training_callbacks.py`, `_evaluate_model_gate`),
  et `robust_base` dérive de `combined_win_rate`, pas de la récompense. Un taux de victoire compte
  des parties gagnées : il ne bouge pas parce qu'une attente forcée cesse de coûter −0,1.
  `best_robust_score` repart de `-inf` à chaque run, il n'y a donc aucun état à effacer.

Verrou : `tests/unit/engine/test_forced_wait_not_penalised.py`.

#### END_ACTIVATION (nettoyage — historiquement aussi numéroté STEP 7)

Implémentation : `end_activation` (`engine/phase_handlers/generic_handlers.py`) /
`_handle_shooting_end_activation` (`engine/phase_handlers/shooting_handlers.py`).

```javascript
end_activation(...) / _handle_shooting_end_activation(...):
├── Remove unit from shoot_activation_pool
├── If "valid_target_pool" in unit: del unit["valid_target_pool"]
├── If "los_cache" in unit: del unit["los_cache"]
├── If "active_shooting_unit" in game_state: del game_state["active_shooting_unit"]
├── Clear TOTAL_ATTACK_LOG
├── Clear selected_target_id
└── SHOOT_LEFT = 0
```

Le cache LoS est nettoyé à la fin de l'activation, comme valid_target_pool ;
`active_shooting_unit` est nettoyé pour permettre l'activation de la prochaine unité.

### SECTION 4 : transitions d'étapes (FLOW SUMMARY & STEP TRANSITIONS)

```
UNIT_ACTIVABLE_CHECK
  → ACTION_SELECTION (if valid_target_pool NOT empty)
  → [ADVANCE_ACTION | SHOOTING_ACTION_SELECTION | WAIT_ACTION]
  → [ADVANCED_SHOOTING_ACTION_SELECTION] (if advanced)
  → [EMPTY_TARGET_HANDLING] (if valid_target_pool empty)
  → UNIT_ACTIVABLE_CHECK
  → (repeat until pool empty) → End of shooting phase
```

- **UNIT_ACTIVABLE_CHECK → ACTION_SELECTION**: valid_target_pool NOT empty
- **UNIT_ACTIVABLE_CHECK → EMPTY_TARGET_HANDLING**: valid_target_pool is empty
- **ACTION_SELECTION → ADVANCE_ACTION**: Player/AI chooses advance
- **ACTION_SELECTION → SHOOTING_ACTION_SELECTION**: Player/AI chooses shoot
- **ACTION_SELECTION → WAIT_ACTION**: Player/AI chooses wait
- **ADVANCE_ACTION → ADVANCED_SHOOTING_ACTION_SELECTION**: Unit advanced AND valid_target_pool NOT empty AND CAN_SHOOT = true
- **ADVANCE_ACTION → UNIT_ACTIVABLE_CHECK**: Unit advanced but no valid targets
- **SHOOTING_ACTION_SELECTION → SHOOTING_ACTION_SELECTION**: Multi-shot sequence continues
- **SHOOTING_ACTION_SELECTION → UNIT_ACTIVABLE_CHECK**: All shots fired or no targets remain
- **ADVANCED_SHOOTING_ACTION_SELECTION → ADVANCED_SHOOTING_ACTION_SELECTION**: Multi-shot sequence continues (post-advance)
- **ADVANCED_SHOOTING_ACTION_SELECTION → UNIT_ACTIVABLE_CHECK**: All shots fired or no targets remain
- **EMPTY_TARGET_HANDLING → UNIT_ACTIVABLE_CHECK**: Advance executed or wait chosen
- **WAIT_ACTION → UNIT_ACTIVABLE_CHECK**: Always (end activation)

### Tirs multiples (Multiple Shots Logic)

- **Tous les tirs en une action** : les NB tirs de l'arme sélectionnée forment une seule activation.
- **Ciblage dynamique** : chaque tir peut viser une cible valide différente.
- **Résolution séquentielle** : chaque tir est résolu complètement avant le suivant.
- **Mort de cible** : les tirs restants peuvent recibler.
- **Slaughter handling** : plus aucune « Valid target » → l'activation se termine immédiatement,
  les tirs restants sont annulés (évite qu'une unité reste bloquée avec des tirs inutilisables).

**Exemple 1 :** Marine (NB = 2) face à deux Orks blessés (HP_CUR 1) — tir 1 tue Ork A, tir 2
recible et tue Ork B : deux menaces éliminées en une action.
**Exemple 2 (slaughter)** : Marine (NB = 2), un seul Ork blessé comme unique cible valide — tir 1
le tue, tir 2 annulé, fin d'activation.

### Advance (Advance Distance Logic)

- **Jet 1D6** : au moment où l'action advance est choisie (à l'activation). Le jet donne la
  distance maximale (1 à `advance_distance_range`, config).
- **Pathfinding** : même BFS que la phase de mouvement ; ni murs, ni cases adjacentes à l'ennemi
  (en chemin comme en destination).
- **Marquage** : l'unité n'est marquée `units_advanced` que si elle a réellement changé d'hex.
- **Irréversibilité** : cliquer le logo advance est un POINT OF NO RETURN — l'engagement précède
  la connaissance de la distance ; seul un tir ASSAULT reste ensuite possible.

**Restrictions post-advance :**
- **Tir** : ❌ interdit sauf arme avec règle ASSAULT.
- **Charge** : ❌ interdite (`units_advanced`) — ✅ exception : les unités avec la rule id
  `charge_after_advance` dans `UNIT_RULES` peuvent charger après advance.
- **Fight** : ✅ normal.

### Différences IA / humain (phase de tir)

1. **Sélection de cible** : l'IA choisit la meilleure cible ; l'humain clique la cible.
2. **Affichage** : les deux sièges voient l'aperçu bleu (cf. UI Display Constants).
3. **Sélection d'arme** : l'humain change d'arme via l'UI ; l'IA pré-sélectionne la meilleure.
4. **Sélection d'action** : IA programmatique ; humain par clics.
5. **Report d'activation (postpone)** : humain uniquement — possible tant que l'unité n'a tiré
   avec AUCUNE arme ; dès le premier tir, l'activation doit se conclure (clic sur l'unité active
   pour confirmer la fin).

### Flux d'exécution complet (récapitulatif)

```
1. shooting_phase_start()
   └── units_cache déjà construit au reset (pas de build ici)

2. UNIT_ACTIVABLE_CHECK
   └── build_unit_los_cache(unit_id)  // Calculer cache LoS pour cette unité
   └── valid_target_pool_build()  // Utilise unit["los_cache"]

3. ACTION_SELECTION
   └── Agent choisit action (ADVANCE ou SHOOT)
   ├── Si ADVANCE choisi:
   │   └── Unit avance → build_unit_los_cache(unit_id) → valid_target_pool_build()
   │   └── Retour à ACTION_SELECTION (peut maintenant tirer, armes ASSAULT)
   └── Si SHOOT choisi:
       └── Agent sélectionne target → vérifie target_id in valid_target_pool → shoot_action(target)

4. SHOOT ACTION
   └── shooting_attack_controller()
   └── Target meurt? → update_los_cache_after_target_death() + retirer de valid_target_pool
   └── SHOOT_LEFT > 0? → Retour à ACTION_SELECTION

5. END_ACTIVATION
   └── del unit["valid_target_pool"] ; del unit["los_cache"]
```

**⚠️ Points critiques :**
1. **units_cache** doit être mis à jour via `update_units_cache_hp(..., 0)` après chaque mort de cible.
2. **unit["los_cache"]** doit être recalculé après chaque advance (pas juste invalidé).
3. **unit["los_cache"]** doit être nettoyé à la fin de l'activation.
4. Le pool est la source de vérité, et utilise le cache LoS pour la performance.
5. Pas de recalcul après mort de cible, juste retirer l'entrée du cache.

### Cas limites : pools et caches vides

**Cas 1 — `los_cache` vide ou inexistant :**
1. Clé absente : ERREUR si `unit.id NOT in units_fled` (doit être créé à l'activation, STEP 2 ;
   `valid_target_pool_build` doit ASSERT) ; NORMAL si l'unité a fui (le cache n'est
   intentionnellement pas construit, `valid_target_pool_build` n'est pas appelé).
2. Cache `{}` vide : `units_cache` sans ennemi vivant → pool vide, comportement attendu.

**Cas 2 — `valid_target_pool` vide :**
1. Vide après construction (unité n'a pas tiré) : aucune cible en LoS / à portée / toutes
   engagées sans CLOSE_QUARTERS — NORMAL. `CAN_ADVANCE == true` → STEP 3 (peut avancer) ; sinon
   STEP 6 (fin d'activation).
2. Vide après mort de toutes les cibles (unité a tiré) : fin d'activation — **pas d'advance
   après avoir tiré**.
3. Vide après advance : NORMAL (nouvelle position) ; fin d'activation si plus rien à faire.

**Cas 3 — `units_cache` sans ennemis vivants :** rare mais possible — `los_cache` vide, pool
vide, toutes les unités peuvent avancer mais pas tirer.

**Assertions à maintenir :**
```
// Dans valid_target_pool_build()
ASSERT: unit["los_cache"] exists (doit être créé par build_unit_los_cache)
// Dans build_unit_los_cache()
ASSERT: game_state["units_cache"] exists (doit être construit au reset)
```

### V11 COMPLIANCE MATRIX — SHOOTING PHASE

> Source de vérité : `Documentation/40k_rules`. Statut établi par lecture du code (`engine/phase_handlers/shooting_handlers.py`, `engine/phase_handlers/shared_utils.py`, `engine/combat_utils.py`, `config/weapon_rules.json`).

**Phase & séquence d'attaque**

| Règle | Contenu | Statut moteur | Mapping / notes |
|---|---|---|---|
| 10.01 | Start of Shooting phase | ✅ | |
| 10.02 | Shoot : sélection unité + type de tir ; éligible si sur plateau et pas déjà sélectionnée | ✅ | |
| 10.03 | End of Shooting phase | ✅ | transition → charge |
| 10.04 | Normal shooting (unengaged, pas d'advance ce tour ; après : pas d'action) | ✅ | éligibilité `shooting_handlers` |
| 10.05 | Assault shooting (unengaged + advance + arme [ASSAULT] ; seules armes [ASSAULT]) | ✅ | `_can_unit_shoot_after_advance_with_weapon`, `weapon_helpers.weapon_has_rule(weapon, "ASSAULT")` |
| 10.06 | Close-quarters shooting (engaged, pas d'advance ; arme [CLOSE-QUARTERS]/[CLOSE_QUARTERS] ou MONSTER/VEHICLE ; cible unités engagées) | 🟡 | `weapon_has_rule(weapon, "CLOSE_QUARTERS")` + `_unit_shoots_as_monster_or_vehicle` (chemin squad) ; [CLOSE_QUARTERS] ≡ [CLOSE-QUARTERS] (24.27) ; malus −1 to hit MONSTER/VEHICLE → chemin squad uniquement (cf. bandeau V11 T-B), ⚠️ à vérifier côté mono |
| 10.07 | Indirect shooting (unengaged, pas d'advance, arme [INDIRECT FIRE] ; cible non-visible, cover forcé, échec 1-5 sauf stationnaire visible → 1-3, pas de re-roll) | ⛔ + ⚠️ | `INDIRECT_FIRE` reconnu au registry mais effets (cible non-visible, cover forcé, seuils 1-5/1-3) **non appliqués** en résolution |
| 04.01 | Select weapons (≥1 arme ranged par modèle) | ✅ | `weapon_selection` |
| 04.02 | Select targets (visible 06.01, à portée, unengaged) | ✅ | LOS/portée/`valid_target_pool` ; cible unengaged sauf close-quarters |
| 04.03 | Resolve attacks (gather A dés, identical attacks, par unité) | ✅ | `_roll_squad_shot_sequence` |
| 05.01 | Hit rolls (≥ BS ; 6 = critical hit ; 1 = échec) | 🟡 | seuil BS appliqué ; **critical hit non géré** (base de Lethal/Sustained) |
| 05.02 | Wound rolls (table S vs T ; 6 = critical wound) | 🟡 | `wound_threshold` (valeurs conformes) ; **critical wound non géré** (base d'Anti/Devastating) |
| 05.03 | Save rolls (Sv modifiée par AP, ou InSv ; groupes d'allocation, CHARACTER en dernier, blessés en premier) | 🟡 | `save_threshold` (AP + invuln OK) ; ordre d'allocation par groupes/CHARACTER → ⚠️ à vérifier |
| 05.04 | Inflict damage (perte = D ; Feel No Pain) | 🟡 | dégâts = D OK ; **Feel No Pain (24.12) non appliqué** |

**Weapon abilities (24.03-24.38) — reconnu au registry vs appliqué en résolution**

> ⚠️ Être reconnu au registry n'implique PAS être appliqué dans la séquence de résolution : `engine/weapons/` **charge et valide** le catalogue `config/weapon_rules.json`, il ne l'applique pas. L'application vit dans `engine/utils/weapon_helpers` + les handlers de phase (`attack_sequence`, tir, mêlée). La colonne « Appliqué » ci-dessous est donc la seule qui fasse foi.
>
> (2026-07-29 — cet avertissement citait auparavant un stub pass-through `_apply_single_rule` ; la classe `WeaponRulesApplier` qui le portait a été SUPPRIMÉE, cf. la pierre tombale dans `engine/weapons/rules.py`. L'avertissement reste valable, sa cause était juste ailleurs.)

> ⚠️ **FRAÎCHEUR (2026-08-10).** Seules les lignes RAPID FIRE et CLEAVE ont été re-mesurées à
> cette date, en travaillant sur les règles additives. Elles portaient toutes deux ⛔ « non
> appliqué » alors que le moteur les applique depuis longtemps. Les autres ⛔ ci-dessous n'ont
> PAS été revérifiées et sont probablement périmées de la même façon : la mémoire projet note
> « V11 P1 : toutes les règles d'armes du PDF 24 vives (tir+mêlée) », et `weapon_rule_log_tokens`
> émet bien des tokens pour [MELTA], [SUSTAINED HITS], [LETHAL HITS], [DEVASTATING WOUNDS] et
> [TWIN-LINKED] — ce qu'il ne ferait pas si les règles ne jouaient pas. Ne pas se fier à un ⛔ de
> ce tableau sans lire le code : c'est un audit à refaire, pas un état vérifié.

| Ability | Registry | Appliqué | Note |
|---|---|---|---|
| BLAST 24.05 | ✅ | ✅ | +1 dé / 5 figs (`weapon_has_rule(weapon, "BLAST")`, `_blast_extra_dice_per_five`) |
| ANTI 24.03 | ✅ | 🟡 | crit wound conditionnel — partiel, à vérifier |
| AP / InSv (05.03) | — | ✅ | `save_threshold` |
| ASSAULT 24.04 | ✅ | ✅ | éligibilité tir post-advance |
| CLOSE_QUARTERS / CLOSE-QUARTERS 24.27 / 24.07 | ✅ | ✅ | tir en état engaged |
| RAPID FIRE 24.30 | ✅ | ✅ | +X dés à demi-portée : `n_attacks += _rf_x` (`shared_utils.py`), test `test_rapid_fire_shoot.py`. Le X APPLIQUÉ entre dans la clé de groupe 04.03 (« same *applicable* rules ») ; le token `[RAPID FIRE:X]` porte le X DÉCLARÉ (2026-08-10) |
| CLEAVE 24.06 | ✅ | ✅ | +X dés / 5 figs si mono-cible : `n_attacks += _cleave_extra_dice` (`fight_handlers.py`), test `test_blast_cleave.py`. Jumeau mêlée de [BLAST] ; son X appliqué est dans la clé de groupe depuis le 2026-08-10 |
| MELTA 24.25 | ✅ | ⛔ | +X D à demi-portée non appliqué |
| SUSTAINED HITS 24.36 | ✅ | ⛔ | dépend du critical hit (non géré) |
| LETHAL HITS 24.23 | ✅ | ⛔ | dépend du critical hit (non géré) |
| DEVASTATING WOUNDS 24.10 | ✅ | ⛔ | dépend du critical wound (non géré) |
| TWIN-LINKED 24.38 | ✅ | ⛔ | re-roll wound non appliqué |
| TORRENT 24.37 | ✅ | ⛔ | auto-hit non appliqué |
| HEAVY 24.16 | ✅ | ⛔ | +1 hit si quasi-stationnaire non appliqué |
| IGNORES COVER 24.18 | ✅ | ⛔ | non appliqué |
| HAZARDOUS 24.15 | ✅ | 🟡 | `roll_hazard_for_unit` existe ; application post-tir à vérifier |
| EXTRA ATTACKS 24.11 | ✅ | ⚠️ | melee → voir section Fight |
| LANCE 24.21 | ⛔ | ⛔ | absent du registry |
| ONE SHOT 24.26 | ⛔ | ⛔ | absent du registry |
| PRECISION 24.28 | ⛔ | ⛔ | absent du registry |
| PSYCHIC 24.29 | ⛔ | ⛔ | absent du registry |

**Limites techniques (moteur 2D / hex) :**
- **LOS / cover** en 2D via `compute_unit_los` (ratio de visibilité) ; pas de blocage par hauteur verticale.
- Portées et demi-portées (Rapid Fire, Melta) en hex = pouces × `inches_to_subhex`.

---

## ⚡ Phase de charge (CHARGE PHASE)

### CHARGE PHASE Decision Tree

> Ordre normatif depuis l'alignement du 2026-08-11 (gym compris) : le jet 2D6 tombe à
> l'ACTIVATION, AVANT la sélection de cible — voir « Timing de la charge » ci-dessous. L'arbre
> historique plaçait le jet après le choix de la cible ; c'est l'ordre ci-dessous qui fait foi,
> et c'est celui du code (`charge_build_valid_plan`, oracle unique du masque, de l'observation et
> de l'exécution).

```javascript
For each unit
├── ELIGIBILITY CHECK (Pool Building Phase)
│   ├── unit.HP_CUR > 0?
│   │   └── NO → ❌ Dead unit (Skip, no log)
│   ├── unit.player === current_player?
│   │   └── NO → ❌ Wrong player (Skip, no log)
│   ├── units_fled.includes(unit.id)?
│   │   └── YES → ❌ Fled unit (Skip, no log)
│   ├── units_advanced.includes(unit.id)?
│   │   └── YES → ❌ Advanced unit cannot charge (Skip, no log)   // sauf rule charge_after_advance
│   ├── Adjacent to enemy unit within CC_RNG?
│   │   └── YES → ❌ Already in fight (Skip, no log)
│   ├── Enemies exist within charge_max_distance (12", × inches_to_subhex) with free adjacent hex(es)?
│   │   └── NO → ❌ No charge targets (Skip, no log)
│   └── ALL conditions met → ✅ Add to charge_activation_pool
│
├── STEP : UNIT_ACTIVABLE_CHECK → Is charge_activation_pool NOT empty ?
│   ├── YES → Activate one unit (AI: pick ; Human: left click)
│   │   ├── Roll 2d6 → charge_range (mémorisé dans charge_roll_values, détruit en fin d'activation)
│   │   ├── Build valid_targets_pool : Enemy units that are:
│   │   │   ├── within charge_max_distance (12")
│   │   │   ├── within charge_range (borne 11.04 BEFORE MOVING — charge_target_within_max_distance)
│   │   │   └── having non occupied adjacent hex(es) reachable within charge_range (BFS pathfinding)
│   │   ├── valid_targets_pool NOT empty ?
│   │   │   ├── YES → TARGET SELECTION (AI : l'agent choisit ; Human : left click sur la cible)
│   │   │   │   ├── Build valid_charge_destinations_pool for selected target : All hexes that are:
│   │   │   │   │   ├── adjacent to the selected target
│   │   │   │   │   ├── at distance <= charge_range (using BFS pathfinding)
│   │   │   │   │   └── unoccupied
│   │   │   │   └── valid_charge_destinations_pool NOT empty ?
│   │   │   │       ├── YES → CHARGE PHASE ACTIONS AVAILABLE
│   │   │   │       │   ├── 🎯 VALID ACTIONS: [charge, wait]
│   │   │   │       │   ├── ❌ INVALID ACTIONS: [move, shoot, attack] → end_activation (ERROR, 0, PASS, CHARGE, 1, 1)
│   │   │   │       │   ├── AI → Choose charge?
│   │   │   │       │   │   ├── YES → Select destination hex → Move unit → end_activation (ACTION, 1, CHARGE, CHARGE, 1, 1)
│   │   │   │       │   │   ├── NO → wait? → end_activation (WAIT, 1, PASS, CHARGE, 1, 1)
│   │   │   │       │   │   └── invalid action → ❌ ERROR → end_activation (ERROR, 0, PASS, CHARGE, 1, 1)
│   │   │   │       │   └── Human → STEP : PLAYER_ACTION_SELECTION
│   │   │   │       │       ├── Highlight the valid_charge_destinations_pool hexes (orange)
│   │   │   │       │       └── Player select the action to execute
│   │   │   │       │           ├── Left click on a hex in valid_charge_destinations_pool → Move unit
│   │   │   │       │           │   ├── end_activation (ACTION, 1, CHARGE, CHARGE, 1, 1)
│   │   │   │       │           │   └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │   │   │       │           ├── Left click on the active_unit → Charge postponed
│   │   │   │       │           │   └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │   │   │       │           ├── Right click on the active_unit → Charge cancelled
│   │   │   │       │           │   ├── end_activation (NO, 0, PASS, CHARGE, 1, 1)
│   │   │   │       │           │   └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │   │   │       │           ├── Left click on another unit in activation pool → Charge postponed
│   │   │   │       │           │   └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │   │   │       │           └── Left OR Right click anywhere else → Cancel charge hex selection
│   │   │   │       │               └── GO TO STEP : UNIT_ACTIVABLE_CHECK
│   │   │   │       └── NO → end_activation (NO, 0, PASS, CHARGE, 1, 1)
│   │   │   └── NO → end_activation (NO, 0, PASS, CHARGE, 1, 1)
│   │   └── Discard charge_range roll (whether used or not)
│   └── NO → If any, cancel highlights
│       └── No more activable units → pass
└── End of charge phase → Advance to Fight Phase
```

### Timing de la charge (Charge Timing Logic)

**Quand le 2d6 est jeté** : à l'ACTIVATION de l'escouade, avant toute sélection de cible —
séquence 11.02 (« 1. Declare Charge → 2. Make Charge Roll → 3. Attempt Charge »). Activer une
escouade en phase de charge VAUT déclaration au sens 11.02.1, et c'est déjà une décision
explicite de l'agent.
**Durée du jet** : jeté une fois et mémorisé (`charge_roll_values`), puis détruit à la fin de
l'activation de l'escouade — il appartient à CETTE activation.

⚠️ **Aligné le 2026-08-11, gym compris.** Jusque-là, seul le chemin PvP/PvE suivait cette
séquence : en entraînement, le jet tombait APRÈS le choix de la cible et le masque ouvrait tout
ennemi à `charge_max_distance` (12"). L'agent déclarait donc à l'aveugle, puis les dés
tranchaient. Mesure sur le step.log du 2026-08-11 (494 charges de l'agent) : 41 % des
déclarations visaient une cible à 9" ou plus, quand un 2D6 n'atteint 9 que 27,8 % du temps ;
médiane des charges ratées à 9", des réussies à 5". Les deux chemins partagent désormais la même
séquence, et une charge déclarée en gym ne peut plus échouer.

### Distance de charge (Charge Distance Logic)

**Système 2D6 :**
- **Quand** : à l'activation, AVANT la sélection de cible (11.02.2).
- **Distance** : le jet est la distance MAXIMALE du charge move (11.04).
- **Variabilité** : le risque porte sur ce que le jet permet d'atteindre, pas sur un pari déjà
  engagé — après le jet, l'agent choisit parmi les cibles réellement atteignables, ou renonce
  (11.02.3 « if you still want to », `WAIT` reste toujours ouvert).

**Mécanique :**
- **Éligibilité à déclarer** (11.02.1) : au moins un ennemi à `charge_max_distance` (12"), mesuré
  figurine la plus proche.
- **Cibles sélectionnables** (11.04 BEFORE MOVING) : celles à 12" ET **dans le jet**. L'oracle est
  `charge_build_valid_plan`, la fonction qu'exécute le commit — le masque, l'observation et
  l'exécution lisent donc la même source, ce qui rend la parité structurelle.
- **Réussite** : le jet doit permettre d'atteindre une position d'engagement avec la cible
  (*via pathfinding*, par figurine).
- **Pourquoi la différence** : on charge VERS un hex adjacent à l'ennemi, pas vers l'ennemi
  lui-même.

**Exemple :**
```
Marine à 7 hexes de la case d'engagement la plus proche d'un Ork.
Le jet tombe D'ABORD :
  Jet de 6 ou moins → cet Ork n'est pas proposé ; s'il n'y a aucune autre cible dans le
                      jet, seul WAIT reste et l'escouade ne charge pas (11.02.3).
  Jet de 7 ou plus  → l'Ork est proposé ; le déclarer conclut la charge et donne Fights First.
Décision : elle ne porte plus sur un pari à 58 %, mais sur l'opportunité de charger CE
           qui est atteignable — ou de garder l'escouade où elle est.
```

### Priorité de la charge (Charge Priority Logic)

- **Fights First** : une charge accorde l'ability Fights First (24.13) — les unités qui ont
  chargé sont résolues dans l'étape Fights First de la phase de combat.
- **Avantage tactique** : frapper avant la riposte ; la position de charge expose l'unité au feu
  ennemi pendant le tour adverse, le premier coup compense ce risque.

### V11 COMPLIANCE MATRIX — CHARGE PHASE

> Source de vérité : `Documentation/40k_rules`. Statut établi par lecture du code (`engine/phase_handlers/charge_handlers.py`, `engine/phase_handlers/shared_utils.py`, `config/game_config.json`).

| Règle | Contenu | Statut moteur | Mapping / notes |
|---|---|---|---|
| 11.01 | Start of Charge phase | ✅ | init pools, `charge_roll_values` / `charge_target_selections` |
| 11.02 | Charge : declare + charge roll 2D6 + attempt | ✅ | jet 2D6 stocké par unité ; budget = 2D6 × `inches_to_subhex` |
| 11.02 | Éligible si sur plateau, à 12″ d'un ennemi, PAS engaged, PAS d'advance/fall-back ce tour | ✅ | exclut `units_advanced` (sauf rule `charge_after_advance`) et `units_fled` (sauf rule) ; portée via `charge_max_distance`=12 |
| 11.03 | End of Charge phase | ✅ | transition → fight |
| 11.04 | Charge move (max = charge roll ; cibles à 12″ et ≤ max ; fin engaged avec TOUTES les cibles, PAS engaged avec des non-cibles ; Fights First jusqu'à fin du tour 24.13) | 🟡 | budget/cibles OK **depuis le 2026-08-08** : la borne « cible ≤ distance maximale » (BEFORE MOVING) n'existait dans AUCUN des deux chemins — seul le TRAJET était borné, donc toute cible à `jet + engagement range` était chargeable (portée doublée ; un jet de 2 réussissait, contre l'encart FAILED CHARGES). Borne unique `charge_target_within_max_distance` (`shared_utils`), lue par les QUATRE points de décision : `charge_build_valid_plan` (gym), `charge_build_valid_targets` (offre PvP), `charge_target_selection_handler` (déclaration) et `charge_preview_move_plan` (Check + commit + toggle vol — sans elle, une cible déclarée avant un Take to the skies restait committable hors de portée). Mesure bord-à-bord par `ranged_in_range`, la primitive de PORTÉE : la primitive d'ER y aurait ajouté le gate vertical 03.04 (5″), qui n'a rien à faire dans une portée de déclaration. C'est ce qui rend exact le « 2 n'est jamais suffisant » du livre. Le -2″ de 21.03 borne aussi la déclaration (« subtract 2" from the maximum distance »). Fights First → `units_charged` (lu par l'ordre Fight) ; contrainte « pas engaged avec une non-cible » → ⚠️ à vérifier |

**Limites techniques :** distances en hex = pouces × `inches_to_subhex` ; engagement range = `engagement_zone` (cf. matrice Movement).

---

## ⚔️ Phase de combat (FIGHT PHASE)

### Structure de la phase (V11 12.04) — normatif

**Deux étapes de résolution :**
1. **Resolve Fights First Combats** : les unités avec l'ability Fights First (24.13) — ce qui
   inclut toute unité ayant fait un charge move ce tour — sont résolues d'abord. Les deux joueurs
   alternent la sélection, **en commençant par le joueur actif** (celui dont c'est le tour).
2. **Resolve Remaining Combats** : toutes les autres unités éligibles alternent (joueur actif
   d'abord). Si, après un Remaining combat, une unité devient éligible Fights First, retour à
   l'étape 1 (re-sélecteur = joueur actif).

**Principes :**
- **Récompense de charge** : une charge réussie donne Fights First jusqu'à la fin du tour (24.13).
- **Combat mutuel** : les unités des DEUX joueurs agissent (unique à la phase de fight).
- **Résolution séquentielle** : une unité termine toutes ses attaques avant la suivante.
- **Validation de cible** : vérifier les ennemis adjacents avant chaque attaque.

**Machine moteur** (`engine/phase_handlers/fight_handlers.py`) — la phase enchaîne trois
sous-étapes via `fight_subphase` :
1. `pile_in` — PILE IN groupé (12.02/12.03), les deux joueurs, unités éligibles ;
2. `fight` — la machine de sélection 12.04 : `fight_v11_enter_fight_step` prend le snapshot
   `engaged_at_fight_step_start` (APRÈS le pile-in) et initialise `fight_step = "fights_first"`,
   `fight_selector` = **joueur actif** ; `fight_v11_advance_selection` rend l'unité que le
   sélecteur courant doit activer, avec handoff au joueur d'en face quand le sélecteur n'a plus
   d'unité éligible (`fight_v11_eligible_unit_ids`, `is_fights_first`), bascule
   `fights_first` → `remaining` quand plus aucune FF des deux côtés, et retour à `fights_first`
   (sélecteur = joueur actif) si une unité FF redevient éligible pendant Remaining ;
3. `consolidate` — CONSOLIDATE (12.07/12.08), cascade de modes (voir matrice).

**Éligibilité au fight (par unité)** — critères normatifs, portés par
`fight_v11_eligible_unit_ids` :
- `unit.HP_CUR > 0` (vivante) ;
- pas encore sélectionnée pour combattre ce tour (`units_selected_to_fight` / `units_fought`) ;
- engagée (adjacente à un ennemi dans CC_RNG, sur le snapshot `engaged_at_fight_step_start`) OU
  ayant chargé ce tour ;
- pour l'étape Fights First : `units_charged` OU ability Fights First
  (`is_fights_first` — 24.13).

### Résolution d'une activation de fight (arbre par unité)

Le même bloc s'applique à chaque activation, quels que soient l'étape (FF ou Remaining) et le
siège (IA ou humain) :

```javascript
FIGHT UNIT ACTIVATION
├── Clear any unit remaining in valid_target_pool
├── Clear TOTAL_ATTACK_LOG
├── ATTACK_LEFT = CC_NB
├── While ATTACK_LEFT > 0
│   ├── Build valid_target_pool : All enemies adjacent to active_unit AND having HP_CUR > 0
│   ├── (Human) Display the fight preview
│   └── valid_target_pool NOT empty ?
│       ├── YES → FIGHT PHASE ACTIONS AVAILABLE
│       │   ├── 🎯 VALID ACTIONS: [fight]
│       │   ├── ❌ INVALID ACTIONS: [move, shoot, charge, wait] → end_activation (ERROR, 0, PASS, FIGHT, 1, 1)
│       │   ├── AI → Choose fight?
│       │   │   ├── YES → ✅ Execute attack_sequence(CC)
│       │   │   │   ├── ATTACK_LEFT -= 1
│       │   │   │   ├── Concatenate Return to TOTAL_ACTION log
│       │   │   │   ├── selected_target dies → Remove from valid_target_pool, continue
│       │   │   │   └── selected_target survives → Continue
│       │   │   └── NO → invalid action → ❌ ERROR → end_activation (ERROR, 0, PASS, FIGHT, 1, 1)
│       │   └── Human → STEP : PLAYER_ACTION_SELECTION
│       │       ├── Left click on a target in valid_target_pool → Display selected_target confirmation
│       │       │   (HP bar blinking + attack preview)
│       │       │   ├── Left click SAME selected_target again → Confirm attack
│       │       │   │   ├── Execute attack_sequence(CC) ; ATTACK_LEFT -= 1 ; log ;
│       │       │   │   │   target dies → remove from pool ; survives → continue
│       │       │   │   └── GO TO STEP : PLAYER_ACTION_SELECTION
│       │       │   ├── Left click DIFFERENT target in valid_target_pool → Switch confirmation
│       │       │   └── Left OR Right click anywhere else on the board → Cancel target selection
│       │       │       └── GO TO STEP : PLAYER_ACTION_SELECTION
│       │       ├── Left click on another unit in activation pool ?
│       │       │   └── ATTACK_LEFT = CC_NB ?
│       │       │       ├── YES → Postpone the Fight Phase for this unit → UNIT_ACTIVABLE_CHECK
│       │       │       └── NO → The unit must end its activation when started
│       │       │           └── GO TO STEP : PLAYER_ACTION_SELECTION
│       │       ├── Left click on the active_unit → No effect
│       │       └── Right click on the active_unit
│       │           └── ATTACK_LEFT = CC_NB ?
│       │               ├── YES → Postpone the fight phase for this unit → UNIT_ACTIVABLE_CHECK
│       │               └── NO → The unit must end its activation when started
│       │                   └── GO TO STEP : PLAYER_ACTION_SELECTION (the unit must attack as
│       │                       long as it can and it has available targets)
│       └── NO → ATTACK_LEFT = CC_NB ?
│           ├── NO → Fought the last target available → end_activation (ACTION, 1, FIGHT, FIGHT, 1, 1)
│           └── YES → no target available at activation → no attack → end_activation (NO, 1, PASS, FIGHT, 1, 1)
├── Return: TOTAL_ACTION log
└── end_activation (ACTION, 1, FIGHT, FIGHT, 1, 1)
```

**Règles d'interaction humaine (normatif) :**
- **Postpone** possible SEULEMENT tant qu'aucune attaque n'a été portée (`ATTACK_LEFT = CC_NB`) ;
  dès la première attaque, l'activation démarrée doit se conclure.
- **Confirmation en deux clics** : premier clic = aperçu (HP bar blinking + attack preview),
  second clic sur la MÊME cible = attaque.
- **Slaughter handling** : toutes les cibles adjacentes éliminées → fin d'attaque naturelle,
  attaques restantes annulées.

### Considérations tactiques de l'alternance (Alternating Fight Tactical Considerations)

**Condition de délai sûr (Safe Delay)** : si TOUS les ennemis adjacents sont marqués
`units_fought` → l'unité peut retarder son attaque sans risque de riposte cette phase.

**Ordre de priorité d'activation et de ciblage :**
1. **Priorité 1** : unités à forte sortie de dégâts mêlée ET susceptibles de mourir cette phase.
2. **Priorité 2** : unités susceptibles de mourir (quel que soit leur output).
3. **Priorité 3** : unités à forte sortie de dégâts mêlée ET peu susceptibles d'être détruites
   cette phase.

**Critères :** « likely to die » = HP_CUR ennemi ≤ dégâts attendus de cette unité ; « high melee
damage » = CC_STR / CC_NB menaçants ; « safe targets » = ennemis déjà `units_fought` (pas de
riposte possible).

### V11 COMPLIANCE MATRIX — FIGHT PHASE

> Source de vérité : `Documentation/40k_rules`. Statut établi par lecture du code (`engine/phase_handlers/fight_handlers.py`, `engine/phase_handlers/shared_utils.py`) ; lignes 12.03/12.04/12.06/12.08 re-vérifiées le 2026-08-27. La séquence d'attaque mêlée réutilise Making Attacks (04) / Attack Sequence (05) — **mêmes lacunes que la matrice Shooting** (critical hit/wound, Feel No Pain, Lethal/Sustained/Devastating/Twin-Linked/Anti non appliqués).

| Règle | Contenu | Statut moteur | Mapping / notes |
|---|---|---|---|
| 12.01 | Start of Fight phase | ✅ | `fight_phase_start` — pose `fight_subphase = "pile_in"`, réinitialise `units_selected_to_fight`, `pile_in_done`, `consolidation_done` |
| 12.02 | Pile in (les deux joueurs, unités éligibles) | ✅ | étape groupée `pile_in` (`_fight_v11_grouped_step_eligible`) |
| 12.03 | Pile-in move (3″ ; éligible si engaged / a chargé / overrun ; fin engaged ; modèles en base-contact non déplaçables) | 🟡 | 3″ via `3 * scale` ; base-contact = adjacence hex ; branche overrun ✅ depuis la refonte 12.04 (`fight_v11_is_overrun_eligible`, `_fight_overrun_pile_in_plan` — re-vérifié 2026-08-27) |
| 12.04 | Fight : alterné, **Fights First** puis **Remaining** ; éligible si engaged ou a chargé | ✅ (re-vérifié 2026-08-27) | machine `fight_step` ∈ {fights_first, remaining} + `fight_selector`, initialisée par `fight_v11_enter_fight_step` avec **sélecteur = joueur actif** (conforme « the player whose turn it is ») ; alternance et handoff par `fight_v11_advance_selection` ; FF = `units_charged` OU ability (`is_fights_first`) ; retour FF pendant Remaining implémenté (inatteignable tant que FF = charge seule) |
| 12.05 | Normal fight (engaged) | ✅ | |
| 12.06 | Overrun fight (unengaged devenu engaged → pile-in additionnel) | ✅ (re-vérifié 2026-08-27) | `fight_v11_is_overrun_eligible` (« was unengaged at the start of the Fight step » = négation du snapshot) → pile-in additionnel `_fight_overrun_pile_in_plan` |
| 12.07 | Consolidate (les deux joueurs) | ✅ | étape groupée `consolidate` (`fight_v11_enter_consolidate`) |
| 12.08 | Consolidation move (3″ ; 3 modes : Ongoing / Engaging / Objective ; Engaging peut tirer de nouvelles unités au combat) | ✅ (re-vérifié 2026-08-27) | cascade `fight_v11_consolidation_mode` : `ongoing` (engagée) → `engaging` (ennemi dans `consolidation_trigger_range`, 3″) → `objective` (objectif dans 3″) ; « engaging → nouvelles unités éligibles » via `fight_v11_engaging_triggered_unit_ids` |
| 12.09 | End of Fight phase | ✅ | fin de phase → transition `next_phase: "command"` du joueur suivant (et `turn += 1` après le joueur 2) |

**Abilities mêlée (24) :** EXTRA ATTACKS 24.11 (registry ✅, application ⚠️ à vérifier) ;
FIGHTS FIRST 24.13 (✅ via `is_fights_first` / flag `fights_first` du cache) ; LANCE 24.21
(⛔ absent du registry) ; CLEAVE 24.06 (✅ appliqué — `_cleave_extra_dice`,
`test_blast_cleave.py`, cf. table Weapon abilities de la matrice Shooting).

**Limites techniques (moteur 2D / hex) :**
- Distances pile-in / consolidation 3″ = 3 × `inches_to_subhex` ; base-contact ≈ adjacence hex.
- Séquence d'attaque mêlée = mêmes limites que la séquence de tir (cf. matrice Shooting).

---

## 📊 Suivi d'état transverse (TRACKING SYSTEM LOGIC)

**Raisons d'être du tracking** : empêcher les actions en double (une unité agit une fois par
phase) ; porter les pénalités inter-phases (fuite) ; alimenter les priorités (charge → Fights
First) ; détecter la fin de phase (plus d'unité éligible). Design en sets : appartenance rapide,
sémantique add/remove claire, même motif dans toutes les phases.

**Remise à zéro** : les six sets ci-dessous sont vidés au **début de la phase de commandement**
du joueur (`command_step_start_of_phase`, `engine/phase_handlers/command_handlers.py`), qui
photographie aussi `units_shot_previous_turn` (13.09) juste avant.

| Set | Posé en | Usage |
|---|---|---|
| `units_moved` | phase de mouvement | unités ayant bougé (move ou flee) ce tour |
| `units_fled` | phase de mouvement | fuite : interdit tir et charge ce tour (fight normal) |
| `units_shot` | phase de tir | unités ayant tiré ce tour (+ snapshot tour précédent pour hidden 13.09) |
| `units_advanced` | phase de tir (action advance) | interdit la charge (sauf rule `charge_after_advance`) ; marqué SEULEMENT si l'unité a réellement bougé |
| `units_charged` | phase de charge | Fights First à la phase de combat (12.04/24.13) |
| `units_fought` | phase de combat | unités ayant attaqué ce tour ; « safe delay » de l'alternance |

**Persistance de `units_fled` (chaîne de pénalité)** : posé au move, lu au tir et à la charge,
sans effet au fight ; effet de niveau TOUR, effacé au début du tour suivant (pas à chaque phase).

**`charge_roll_values` (phase de charge)** : jets 2D6 par unité qui tente une charge — jeté dès
l'activation de l'unité, stocké `unit.id → valeur`, lu pour borner cibles et pathfinding, détruit
à la fin de l'activation (que la charge ait eu lieu ou non).

**Slaughter handling (rappel transverse)** : quand toutes les cibles valides meurent pendant une
action multi-attaques (tir ou mêlée), les attaques restantes sont annulées et l'activation se
termine immédiatement — pas d'unité bloquée, pas de boucle infinie.

---

## Historique et sources

- **Origine** : ce contrat est la consolidation (2026-08-28) de `AI_TURN.md`, lui-même issu d'un
  guide pédagogique réécrit par strates de 2025 à 2026. Le squelette pédagogique (objectifs
  d'apprentissage, rationales « Why ... ») et les doublons internes ont été purgés à la
  consolidation ; tout le contenu normatif est conservé.
- **Jalons datés portés par ce document** : 2026-07-26 (V11 T-B, type de tir squad ; audit
  règle 19) ; 2026-07-27 (19.04 UNIT_RULES en vigueur) ; 2026-07-29 (coherency source unique ;
  suppression des wrappers d'armes laxistes ; pierre tombale `WeaponRulesApplier`) ; 2026-08-04
  (phase de commandement, checkpoint 14.02, régime de config, réserves stratégiques
  20.01→20.04, Deep Strike 24.09) ; 2026-08-05 (invariant hors-table structurel ; arrêt de phase
  08.04) ; 2026-08-07 (Fly 21.03 conforme, décision du joueur actif) ; 2026-08-08 (borne 11.04
  BEFORE MOVING) ; 2026-08-10 (règles additives RAPID FIRE / CLEAVE re-mesurées) ; 2026-08-11
  (jet de charge à l'activation, gym compris) ; 2026-08-27/28 (consolidation : statuts fight
  12.03/12.04/12.06/12.08 re-vérifiés contre `fight_handlers`, séquence de tour et resets
  re-vérifiés contre `w40k_core` / `command_handlers` / `fight_handlers`).
- **Anciens noms retirés du code** (rencontrés dans de vieux commentaires ou commits) :
  `_weapon_has_assault_rule` / `_weapon_has_close_quarters_rule` →
  `weapon_helpers.weapon_has_rule` ; pools de fight `charging_activation_pool` /
  `active_alternating_activation_pool` / `non_active_alternating_activation_pool` → machine
  `fight_subphase` / `fight_step` / `fight_selector`.

---

## Correspondance des sources

Les commentaires du code citent « tour_de_jeu.md » (ex-« AI_TURN.md » ; parfois avec un numéro de STEP ou de ligne d'une
version antérieure). Table de correspondance : section de la source → section actuelle.

| Source | Ancien § | Section actuelle |
|---|---|---|
| AI_TURN.md | AI CODING CONTRACT (OPERATIONAL) | Contrat de codage (AI CODING CONTRACT, opérationnel) |
| AI_TURN.md | 📅 SÉQUENCE DE TOUR | 📅 Séquence du tour (SÉQUENCE DE TOUR) |
| AI_TURN.md | Field Naming Logic | Conventions de nommage des champs (Field Naming Logic) |
| AI_TURN.md | GENERIC FUNCTIONS (end_activation, attack_sequence) | Primitives d'activation (GENERIC FUNCTIONS) |
| AI_TURN.md | 🏃 MOVEMENT PHASE Decision Tree | Phase de mouvement → MOVEMENT PHASE Decision Tree |
| AI_TURN.md | Movement Restrictions Logic / Flee Mechanics Logic | Phase de mouvement → Restrictions de mouvement / Fuite |
| AI_TURN.md | 🆕 V11 COMPLIANCE MATRIX — COMMAND PHASE | Phase de commandement → V11 COMPLIANCE MATRIX — COMMAND PHASE |
| AI_TURN.md | 🆕 V11 COMPLIANCE MATRIX — MOVEMENT PHASE (+ hors-table, règle 19) | Phase de mouvement → V11 COMPLIANCE MATRIX — MOVEMENT PHASE ; Unités hors table ; Règle 19 |
| AI_TURN.md | 🎯 SHOOTING PHASE — SECTION 1 (variables, caches, LoS & Cover) | Phase de tir → SECTION 1 ; Ligne de vue et couvert |
| AI_TURN.md | SECTION 2: CORE FUNCTIONS | Phase de tir → SECTION 2 : fonctions cœur |
| AI_TURN.md | SECTION 3: PHASE FLOW (STEP 0 → STEP 7, attente forcée, END_ACTIVATION) | Phase de tir → SECTION 3 : flux de la phase (mêmes noms de STEP) |
| AI_TURN.md | SECTION 4: FLOW SUMMARY & STEP TRANSITIONS | Phase de tir → SECTION 4 : transitions d'étapes |
| AI_TURN.md | SECTION 5: CONCEPTUAL EXPLANATIONS (Target Restrictions Logic, Multiple Shots, Advance Distance, AI vs Human) | Phase de tir → Restrictions de ciblage ; Tirs multiples ; Advance ; Différences IA/humain |
| AI_TURN.md | 🔄 FLUX D'EXÉCUTION COMPLET / ⚠️ POINTS CRITIQUES / 🔍 CAS LIMITES | Phase de tir → Flux d'exécution complet ; Points critiques ; Cas limites |
| AI_TURN.md | 🆕 V11 COMPLIANCE MATRIX — SHOOTING PHASE (+ Weapon abilities) | Phase de tir → V11 COMPLIANCE MATRIX — SHOOTING PHASE |
| AI_TURN.md | « MOVEMENT PHASE — avance et tir post-avance » (bloc historiquement titré « CHARGE PHASE » par erreur ; arbre géant IA+humain de la phase de tir) | Phase de tir → SECTION 3 (STEP 3/4/5A/5B/6) — replié ; les éléments propres (journalisation `end_activation(ACTION, 1, ADVANCE, NOT_REMOVED, 1, 0)`, fin ADVANCE sans cible) sont dans STEP 4 |
| AI_TURN.md | ⚡ CHARGE PHASE (arbre + Timing + Distance + Priority) | Phase de charge |
| AI_TURN.md | 🆕 V11 COMPLIANCE MATRIX — CHARGE PHASE | Phase de charge → V11 COMPLIANCE MATRIX — CHARGE PHASE |
| AI_TURN.md | ⚔️ FIGHT PHASE LOGIC (overview, FIGHT Decision Tree, sub-phases) | Phase de combat (structure 12.04, arbre par unité) |
| AI_TURN.md | Alternating Fight Tactical Considerations | Phase de combat → Considérations tactiques de l'alternance |
| AI_TURN.md | 🆕 V11 COMPLIANCE MATRIX — FIGHT PHASE | Phase de combat → V11 COMPLIANCE MATRIX — FIGHT PHASE |
| AI_TURN.md | 📊 TRACKING SYSTEM LOGIC / 🔄 RULE INTERACTIONS | Suivi d'état transverse |

