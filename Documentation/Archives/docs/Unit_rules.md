> **Document absorbé.** Consolidation P4 du 2026-08-28 : ce fichier a été fusionné dans [`Documentation/Reference/jeu/regles_unites.md`](../../Reference/jeu/regles_unites.md).

# Unit Rules - Guide d'implementation

Ce document explique la structure des regles d'unite, comment les declarer, et comment activer les choix contextuels (`choice_timing`) dans le moteur.

## 1) Vue d'ensemble

Le systeme se base sur 2 niveaux:

- `config/unit_rules.json` : registre global des regles (techniques et d'affichage).
- `static UNIT_RULES` dans chaque unite TS : declaration des regles portees par l'unite.

Le moteur resolt ensuite les effets via:

- `ruleId` (regle source portee par l'unite),
- `grants_rule_ids` (sous-regles eventuelles),
- `alias` dans `unit_rules.json` (mapping regle d'affichage -> regle technique).

## 2) Structure de `config/unit_rules.json`

Le fichier est un objet `rule_id -> rule_config`.

Format minimal d'une regle technique:

```json
{
  "reroll_1_tohit_fight": {
    "id": "reroll_1_tohit_fight",
    "obs_id": 8,
    "description": "During the fight phase, ..."
  }
}
```

Format d'une regle d'affichage (avec alias):

```json
{
  "aggression_imperative": {
    "id": "aggression_imperative",
    "name": "Aggression Imperative",
    "alias": "reroll_1_tohit_fight",
    "description": "During the fight phase, ..."
  }
}
```

Contraintes importantes:

- `id` requis et doit etre identique a la cle JSON.
- `description` requise et non vide.
- `alias` optionnel, mais s'il existe:
  - doit pointer vers une regle existante,
  - ne peut pas pointer vers elle-meme.
- `name` est requis en pratique pour toute regle utilisee comme option de choix (label UI).

### `obs_id` — identifiant d'observation

`obs_id` est l'entier que l'observation de l'agent ecrit dans les slots de capacite
(`allies_ability_ids` / `enemies_ability_ids`, cf. [`observation_et_actions.md`](../training/observation_et_actions.md)). Il
remplace les 13 bits `rule_<effet>` : une capacite n'est plus une DIMENSION du vecteur mais une
LIGNE d'une table d'embedding, ce qui rend son ajout gratuit — ni `obs_size`, ni le nombre de
parametres du reseau ne changent, donc aucun retrain.

Regles:

- **Requis** pour toute regle du vocabulaire observe (`UNIT_RULE_EFFECT_IDS`,
  `engine/observation_entities.py`) : les effets techniques, sans exception. Absent -> erreur
  explicite a la premiere observation. Le nombre n'est ecrit nulle part a dessein : la liste
  s'allonge pour zero scalaire, donc tout compte en prose serait faux des l'entree suivante.
- **Absent** pour tout le reste : capacites SOURCES composites (`cunning_hunters`,
  `targeted_intercession`…), regles d'affichage a `alias`, et marqueurs de ROLE (`leader`,
  `support`, `sergeant`, `special_weapon`) — le bloc TYPES porte deja ces derniers.

Depuis le 2026-08-04, allonger `UNIT_RULE_EFFECT_IDS` coute **exactement zero scalaire**. Ce
n'etait pas vrai avant : le bloc `decision_options_bin` (candidats de `rule_choice`) etait bati
sur ce meme tuple, donc chaque entree y ajoutait 6 bits positionnels — souvent morts a vie. Les
deux registres sont separes (`DECISION_GRANTABLE_EFFECT_IDS` = les seuls effets qu'un candidat
peut accorder), et un test de contrat recalcule le second depuis les `grantsRuleIds` des rosters.
Consequence pratique : une capacite nouvelle entre dans le vocabulaire observe **sans arbitrage
de cout** ; seul un effet ACCORDABLE nouveau fait bouger `obs_size`. Ce sont les
  EFFETS qui sont observes, jamais les capacites nommees : `unit_has_rule_effect` resout les
  sources vers eux.
- Domaine `[1, 127]`. `0` est reserve au padding des slots vides.
- **UNIQUE**, et **STABLE A VIE**. Un `obs_id` libere par la suppression d'une regle est **brule**,
  jamais reattribue : le reattribuer ferait pointer un modele deja entraine sur une ligne
  d'embedding qui ne veut plus dire la meme chose — corruption silencieuse, invisible en
  entrainement comme en eval.

Absent, hors domaine ou duplique -> le chargeur leve (`config_loader._validate_obs_ids`).

Le registre jumeau [`config/unit_statuses.json`](../../../config/unit_statuses.json) suit exactement la
meme convention pour les STATUTS (`battle_shock`, `oath_target`, `suppressed`), qui alimentent une
seconde table d'embedding. Les deux domaines sont independants : un `obs_id` de capacite et un
`obs_id` de statut peuvent porter la meme valeur.

## 2 bis) Capacites de FACTION — Waaagh! et Oath of Moment

Elles ne s'ACCORDENT NI par `config/unit_rules.json`, NI par `static UNIT_RULES`, et c'est
deliberе : une capacite de faction s'applique uniformement a toutes les unites de l'armee qui
la portent. L'inscrire par unite reviendrait a repeter les memes ids sur 28 entites, a faire
deborder `UNIT_ABILITY_SLOTS`, et a n'apporter aucune information — le reseau reconstitue
l'effet a partir de « cette unite est orke » et de « Waaagh! actif », deux faits GLOBAUX.

**Ou vit quoi**

| | Fichier |
|---|---|
| Le mot-cle porteur | `static FACTION_KEYWORDS` de la datasheet (`ORKS`, `ADEPTUS ASTARTES`) |
| La Faction d'Armee | DECLAREE : `army_faction` (scenario/roster/fichier d'armee), lue par `game_state.army_faction` |
| L'etat de partie | `game_state["waaagh_called" / "waaagh_active" / "oath_target"]` (`engine/game_state.py`) |
| La decision | 08.04, `command_handlers.command_step_command_abilities` |
| Les predicats d'application | `engine/game_state.py` (`waaagh_applies_to_unit`, `effective_invul_save`, `oath_hit_reroll_applies`, `oath_wound_roll_bonus`, `unit_can_charge_after_advance`) |
| L'observation | 6 drapeaux de `GLOBAL_BIN_FIELDS` + le statut `oath_target` (`config/unit_statuses.json`) |
| Le nom affiche | `OATH_ABILITY_DISPLAY_NAME` / `WAAAGH_ABILITY_DISPLAY_NAME` (`engine/game_state.py`) |
| La DESCRIPTION du log | entrees `oath_of_moment` / `waaagh` de `config/unit_rules.json` |

**Les deux entrees de `config/unit_rules.json` n'accordent RIEN.** Elles ne portent qu'un `name`
et une `description` : c'est le registre que le Game Log interroge pour accrocher une bulle
d'aide a un token `[...]` (`GameLog.tsx`, lookup par nom NORMALISE — majuscules, `!` compris).
Aucune datasheet ne les reference, et le moteur ne les lit jamais.

**Les tokens du log** — chaque effet qui modifie une valeur AFFICHEE nomme sa capacite, sinon la
ligne montre un ecart sans en donner la cause (les valeurs sont nettes) :

| Token | Ou | Ce qu'il annonce |
|---|---|---|
| `[OATH OF MOMENT]` | `Hit:X+RR` / `Wound:X+` | relance de touche, +1 au jet de blessure |
| `[WAAAGH!]` | `Shots:N` / `Wound:X+` | +1 Attaque, +1 Force (melee seulement) |
| `[WAAAGH!]` | `Save:X+` | invulnerable 5+ octroyee a la CIBLE, et seulement si elle AMELIORE le seuil affiche |
| `[WAAAGH!]` | `CHARGED [...]` | charge apres Advance autorisee par le Waaagh! (a defaut d'une capacite de datasheet) |

**`FACTION_KEYWORDS`** suit exactement la convention de `UNIT_KEYWORDS` : une liste d'objets
`{ keywordId: "..." }`, exigee par `_build_enhanced_unit`, et unie sur l'escouade par la regle
19.03 (un character attache fait entrer sa sous-faction dans l'armee).

**FACTION D'ARMEE — declaree, jamais deduite.** « If your Army Faction is ORKS / ADEPTUS
ASTARTES » porte sur la faction DECLAREE de la liste, pas sur la presence du mot-cle quelque
part dans l'armee. Les deux tests different des qu'une figurine invitee est presente : le camp
tyranide de `scenario_pvp_test.json` contient deux `WolfGuardTerminator` (ADEPTUS ASTARTES), et
tant que la faction etait calculee comme l'UNION des `FACTION_KEYWORDS` du camp, ce joueur se
voyait reclamer une designation d'Oath of Moment a chaque tour. La declaration vit donc dans la
donnee, sous trois formes selon le fichier qui decrit l'armee :

| Fichier | Forme | Exemple |
|---|---|---|
| Scenario a `units` | dict par joueur | `"army_faction": {"1": "ADEPTUS ASTARTES", "2": "TYRANIDS"}` |
| Roster compact (`config/agents/**`) | scalaire | `"army_faction": "ORKS"` |
| Fichier d'armee (`config/armies/*.json`) | scalaire | `"army_faction": "TYRANIDS"` |

Un scenario a `agent_roster_ref` n'en declare PAS : sa faction vient du roster effectivement
tire (`training_random` en change a chaque episode), et une declaration de scenario decrirait
l'armee d'un autre episode. `change_roster` propage de meme la faction du fichier d'armee au
joueur qui la charge, comme il propage deja `uses_codex_detachment`.

Champ ABSENT = erreur explicite (`game_state.army_faction` leve), jamais une deduction de
secours : deviner ferait apparaitre ou disparaitre une capacite d'armee entiere. Une faction
declaree que PERSONNE ne porte leve aussi — c'est la faute de frappe qui eteindrait l'Oath en
silence. Verrous : `tests/unit/engine/test_faction_abilities.py` (moteur) et
`tests/unit/engine/test_army_faction_declaration.py` (donnee).

**Waaagh! (ORKS)** — decision binaire, UNE fois par partie, au debut de MA phase de commandement.
Elle passe par le mecanisme generique de decision agent (`pending_agent_decision`, type
`waaagh_call`, actions `CHOICE_0` = appeler / `CHOICE_1` = passer). L'ordre des candidats est
CONTRACTUEL : c'est lui qui porte le sens, les deux candidats ayant un `effect_ids` vide (aucun
roster n'accorde les effets du Waaagh!, ils viennent de la faction). Effets, sur les seules
unites PORTANT le mot-cle : charge apres Advance, +1 Force et +1 Attaques aux armes de melee,
sauvegarde invulnerable 5+ (un OCTROI : une 4+ existante est conservee).

**Oath of Moment (ADEPTUS ASTARTES)** — designation d'une escouade ennemie, CHAQUE tour, et
NON OPTIONNELLE. Ses candidats sont des entites deja observees : elle se parametre donc en
DIMENSION D'ACTION + pointeur (`OATH_SLOTS`, `macro_intents`) et non en `CHOICE_k`. Le slot *i*
indexe le MEME `get_enemy_slot_mapping` que le tir, la charge et la melee — donc la MEME ligne
du tenseur ennemi (invariant D1). Effets contre la cible designee, pour les seules unites
portant le mot-cle : relance de TOUT jet de touche rate (`hit_any_fail`), et +1 au jet de
blessure si la clause de detachement est remplie.

**La clause de detachement** a deux moities. « votre armee ne contient pas d'unite BLOOD ANGELS
/ DARK ANGELS / DEATHWATCH / SPACE WOLVES » est un balayage REEL de l'armee (mots-cles de
faction, unites mortes comprises : la regle parle de la LISTE d'armee). « vous utilisez un
Detachement Codex: Space Marines » n'a aucun equivalent dans le moteur : c'est un champ
OBLIGATOIRE de la config de scenario / d'armee, `uses_codex_detachment` (bool, ou dict par
joueur). Absent alors qu'une armee ADEPTUS ASTARTES est en jeu -> ERREUR EXPLICITE, jamais de
valeur par defaut : la deviner ferait apparaitre ou disparaitre un +1 au jet de blessure sans
que personne ne l'ait decide.

**Duree** — les deux capacites durent « until the start of your next Command phase ». Le
nettoyage a donc lieu a l'ouverture de la phase de commandement suivante DU MEME JOUEUR
(`expire_faction_abilities_for_player`), et surtout PAS en fin de tour : les deux effets
doivent enjamber le tour adverse.

**Sieges** — la decision est posee pour les deux camps, quel que soit le pilote. En gym, le
siege repond par le MASQUE (agent comme bot). Hors gym, un siege IA est tranche par
`W40KEngine._select_ai_waaagh_call` / `_select_ai_oath_target`. Un siege HUMAIN recoit la
decision dans `game_state` (`pending_agent_decision` / `pending_oath_selection`) et la resout
par les actions `agent_decision` (option 0/1) ou `select_oath_target` (`unitId`) — l'API les
route deja ; il ne reste que les widgets React a brancher dessus.

**L'arret de phase est OPPOSABLE.** Tant que la decision du joueur ACTIF n'est pas jouee, toute
autre action est refusee (`error: "faction_decision_pending"`), aux DEUX points d'entree :
`execute_semantic_action` (UI PvP) et `_process_squad_action` (gym). Sans ce refus, l'arret
n'etait que conventionnel : `advance_phase` est intercepte AVANT le dispatch de phase et
terminait la phase de commandement avec la designation encore posee — purgee sans avoir servi a
l'ouverture de la phase suivante (`expire_faction_abilities_for_player`), donc plus aucune
relance de touche du tour, et pas un message. Hors decision en attente, la phase de commandement
n'accepte que `zone_intent` et `skip` (`W40KEngine.COMMAND_PHASE_ACTIONS`) : tout autre verbe y
etait traite comme une sortie volontaire et la terminait en rendant `success: True`.

**La reprise DEMARRE la phase suivante**, elle ne se contente pas de l'annoncer
(`_resume_command_phase_after_faction_decision` : `phase_complete` -> `movement_phase_start`, le
meme `if` que les six autres appelants de `start_command_phase`). Les deux routes de decision
sortent du moteur AVANT la boucle de cascade, seul endroit ou une transition s'execute : le
`next_phase: move` rendu au client decrivait une bascule qui n'avait pas eu lieu. Le gym s'en
sortait par accident (son masque garde un WAIT, qui termine la phase au step suivant) ; le PvP,
lui, n'a AUCUN verbe de sortie de cette phase — il n'en avait pas besoin tant que rien ne l'y
arretait, et la partie restait bloquee en commandement une fois l'Oath designe.

## 3) Structure de `UNIT_RULES` dans une unite

Exemple:

```ts
static UNIT_RULES = [
  {
    ruleId: "adrenalised_onslaught",
    displayName: "Adrenalised Onslaught",
    grants_rule_ids: ["aggression_imperative", "preservation_imperative"],
    usage: "or",
    choice_timing: {
      trigger: "phase_start",
      phase: "fight",
      active_player_scope: "both",
    },
  },
];
```

Champs:

- `ruleId` (requis): id de regle present dans `config/unit_rules.json`.
- `displayName` (requis): nom affiche cote unite.
- `grants_rule_ids` (optionnel): liste d'ids de sous-regles (doivent exister dans `unit_rules.json`).
- `usage` (optionnel): mode d'application des sous-regles.
- `choice_timing` (optionnel): quand demander un choix joueur.

## 4) `usage`: modes possibles

- `and`:
  - toutes les `grants_rule_ids` sont actives en meme temps.
  - pas de popup de choix.
- `or`:
  - une seule sous-regle active a la fois.
  - popup de choix.
  - le choix est remis a zero au debut de chaque phase `command`.
- `unique`:
  - une seule sous-regle choisie une fois.
  - le choix reste verrouille pour la suite de la partie.
- `always`:
  - comportement toujours actif (pas de popup), equivalent "toujours applique".

Note:

- Si `grants_rule_ids` contient moins de 2 elements, aucun popup n'est emis.

## 5) `choice_timing`: declencheurs et parametres

`choice_timing.trigger` autorise:

- `on_deploy`
- `turn_start`
- `player_turn_start`
- `phase_start`
- `activation_start`

`choice_timing.phase` autorise:

- `command`, `move`, `shoot`, `charge`, `fight`

`choice_timing.active_player_scope` autorise:

- `owner`: seulement quand le joueur actif est le proprietaire de l'unite.
- `opponent`: seulement pendant le tour/phases de l'adversaire.
- `both`: pour les deux joueurs actifs.

Regles de validation:

- `phase` est requis pour `phase_start` et `activation_start`.
- `active_player_scope` est requis pour `phase_start`.

## 6) Cycle runtime (moteur)

Le moteur:

1. Construit un index `choice_timing_index` a partir des unites vivantes/deployees.
2. Enqueue les prompts au bon moment (`on_deploy`, debut de tour, debut de phase, debut d'activation).
3. Emet `waiting_for_rule_choice` pour un joueur humain.
4. Recoit `select_rule_choice` et stocke `_selected_granted_rule_id` sur la regle source.

Comportement IA:

- cote IA, la premiere option est selectionnee automatiquement.

## 7) Procedure "ajouter une nouvelle regle"

1. Ajouter/mettre a jour la regle technique dans `config/unit_rules.json`.
   Si l'agent doit la PERCEVOIR : l'ajouter aussi a `UNIT_RULE_EFFECT_IDS`
   (`engine/observation_entities.py`) et lui donner un `obs_id` libre — le prochain entier
   JAMAIS utilise, y compris par une regle supprimee depuis (cf. §2). C'est tout : `obs_size`
   ne bouge pas, aucun retrain n'est necessaire. Ce « c'est tout » est VERROUILLE par
   `tests/unit/engine/test_squad_obs_unit_rules.py::test_adding_an_observed_capability_costs_zero_scalar`
   (il re-execute le schema d'entites avec une capacite fictive de plus et exige que toutes les
   tailles restent identiques) : il etait faux jusqu'au 2026-08-04, ou le registre des candidats
   de decision etait bati sur le vocabulaire observe, a 6 scalaires par capacite ajoutee.
   Si la regle peut etre ACCORDEE par un candidat de `rule_choice` (`grantsRuleIds`), l'ajouter
   EN PLUS a `DECISION_GRANTABLE_EFFECT_IDS` — la, ce n'est pas gratuit (1 bit x 6 slots), et
   l'omettre fait lever `set_pending_agent_decision`.
2. Si besoin de choix joueur, ajouter une (ou plusieurs) regles d'affichage avec:
   - `name`
   - `alias` vers la regle technique
   - `description`
3. Dans l'unite TS (`UNIT_RULES`):
   - declarer la regle source (`ruleId`, `displayName`)
   - renseigner `grants_rule_ids`
   - choisir `usage`
   - ajouter `choice_timing` si un prompt est attendu.
4. Verifier que tous les ids references existent dans `unit_rules.json`.

## 8) Erreurs frequentes

- "Unknown granted unit rule id ...":
  - un id dans `grants_rule_ids` n'existe pas dans `unit_rules.json`.
- Pas de popup:
  - `usage` vaut `and`/`always`, ou `grants_rule_ids` < 2.
- Prompt au mauvais moment:
  - `trigger`/`phase`/`active_player_scope` mal configures.
- Label vide dans popup:
  - la regle de sous-choix n'a pas `name`.

## 9) Exemple complet: Adrenalised Onslaught

`unit_rules.json`:

- `adrenalised_onslaught` (source)
- `aggression_imperative` -> alias `reroll_1_tohit_fight`
- `preservation_imperative` -> alias `reroll_1_save_fight`

`UNIT_RULES` unite melee:

- `usage: "or"`
- `trigger: "phase_start"`
- `phase: "fight"`
- `active_player_scope: "both"`

Effet:

- Au debut de chaque phase fight (joueur actif owner ou opponent), le popup propose 1 choix entre les 2 imperatives.

---

## 10) Specification : reactive_move (unite rule)

La regle `reactive_move` est une regle d'unite qui permet un deplacement reactif (jusqu'a D6) apres qu'une unite ennemie ait termine un mouvement. Elle se declare dans `config/unit_rules.json` et est portee par les unites via `UNIT_RULES` / `grants_rule_ids`. La specification d'implementation complete (game_state, caches, flux, erreurs, tests, plan) est ci-dessous.

### Objectif

Ajouter la regle `reactive_move` de facon robuste, deterministe, et compatible training:

- trigger uniquement apres la fin d un mouvement ennemi;
- aucun fallback silencieux;
- aucune boucle infinie;
- refresh complet des caches positionnels uniquement apres un `reactive_move`;
- comportement normal inchange en dehors de ce cas.

### Regle metier figee

Une unite avec `reactive_move` peut, si elle le veut, effectuer un deplacement reactif (jusqu a D6) quand une unite ennemie termine un mouvement `move|advance|flee|reposition_normal` dans un rayon de 9.

Contraintes metier:

- la distance est mesuree depuis la nouvelle position (`to_col`, `to_row`) de l unite ennemie qui vient de terminer son mouvement;
- une unite ne peut faire qu un `reactive_move` par tour adverse;
- un `reactive_move` ne peut jamais en declencher un autre.

### Decisions figees (scope courant)

1. Fenetre unique par evenement de move: un `move|advance|flee|reposition_normal` ennemi ouvre exactement une `reaction_window`; la fenetre est fermee une fois le `reaction_pool` epuise.
2. Reaction pool construit une seule fois au debut de la `reaction_window`; pas de recalcul incremental apres chaque reactive move dans la meme fenetre.
3. Reactions sequencées sans retrigger: un `reactive_move` applique ne cree jamais une nouvelle fenetre de reaction.
4. Refresh cache strictement cible: uniquement apres un `reactive_move` effectivement applique.

### Invariants non negociables

1. Pas de fallback anti-erreur (KeyError/ValueError explicite si champ requis manque).
2. Source de verite unique: positions/HP via `units_cache` et helpers existants.
3. Pas de trigger en chaine: un reactive move ne peut jamais en declencher un autre.
4. Etat de phase coherent: ne pas corrompre `active_*_unit` ni les pools d activation.
5. Refresh complet cible uniquement sur `move_cause == reactive_move`.

### Contrat d evenement

- Point unique de trigger: `on_enemy_move_ended(moved_unit_id, from_col, from_row, to_col, to_row, move_kind, move_cause)`.
- `move_kind` in `{move, advance, flee, reposition_normal}`; `move_cause` in `{normal, reactive_move}`.
- Si `move_cause == "reactive_move"` alors stop immediat (anti-chaine).
- `reposition_normal` est traite comme un deplacement normal pour le trigger.

### Contrat game_state

Champs requis: `units_reacted_this_enemy_turn: set[str]`, `reaction_window_active: bool`, `last_move_event_id: int`, `last_move_cause: str` (`normal` ou `reactive_move`). Initialisation au reset episode: set vide, `reaction_window_active = False`, `last_move_event_id = 0`, `last_move_cause = "normal"`. Reset tour: au changement de joueur actif, vider `units_reacted_this_enemy_turn` (pas a chaque phase).

### Detection d eligibilite

Une unite reactionnaire est eligible si: vivante; camp oppose a l unite qui vient de bouger; possede `reactive_move` (direct ou via `grants_rule_ids`); pas deja dans `units_reacted_this_enemy_turn`; distance hex <= 9 depuis `to_col`, `to_row` de l unite ennemie; au moins une destination legale de mouvement reactif. Si aucune unite eligible: fin immediate du flux reactif.

### Politique training

En training/gym: choix explicite `decline_reactive_move` ou `reactive_move(unit_id, destination)`; destination doit appartenir au pool legal; destination hors pool = `ValueError` explicite. Multi eligibles: mode micro = ordre deterministe (tri numerique/lexicographique sur unit_id); mode macro = ordre fourni par le macro agent, sinon `ValueError`. References: `engine/phase_handlers/movement_handlers.py` (on_enemy_move_ended, maybe_resolve_reactive_move), `shared_utils.py` (eligibilite, refresh); `engine/combat_utils.py` (get_unit_coordinates, normalize_coordinates, calculate_hex_distance, resolve_dice_value("D6", "reactive_move_distance")).

### Resolution du reactive move

Sequence: 1) gardes (move_cause, reaction_window_active); 2) reaction_window_active = True; 3) selection unite eligible; 4) decision (decline ou move); 5) si move: roll D6, destinations legales, appliquer deplacement; 6) si move: units_reacted_this_enemy_turn.add(unit_id_str); 7) last_move_cause = "reactive_move" si move applique; 8) refresh_all_positional_caches_after_reactive_move(game_state) si move applique; 9) reaction_window_active = False (garanti par `finally`); 10) retour flux normal.

### Strategie cache

Fonction unique `refresh_all_positional_caches_after_reactive_move(game_state)`. Responsabilites: invalider/reconstruire caches LoS globaux + unit-local; _target_pool_cache / valid_target_pool; pools de destinations (move/charge/shoot); structures enemy_adjacent_hexes. Cles/pools a traiter: units_cache (mise a jour incrementale); game_state["los_cache"], ["hex_los_cache"]; unit["los_cache"] unites impactees; _target_pool_cache; unit["valid_target_pool"]; game_state["valid_move_destinations_pool"], ["valid_charge_destinations_pool"]; game_state["enemy_adjacent_hexes_player_{current_player}"], ["enemy_adjacent_hexes_player_{enemy_player}"]. Reutiliser `build_enemy_adjacent_hexes(game_state, player)` (shared_utils), `_invalidate_all_destination_pools_after_movement(game_state)` (movement_handlers). Regle: ne pas disperser le refresh; invalidations normales hors reactive_move inchangees; refresh post-reactive = securisation supplementaire. Validation: cle attendue absente => KeyError explicite (jamais {} ou [] par defaut).

### Contrat d erreurs

Cas normaux (pas d erreur): aucune unite eligible; unite eligible mais decision `decline_reactive_move`. Cas incoherents (fail hard): recursivite/re-entrance; champs requis manquants; destination invalide hors pool; joueur/camp incoherent. Types: `RuntimeError` (trigger recursif ou fenetre incoherente), `KeyError` (champ requis manquant), `ValueError` (action/destination invalide). Message minimal: episode, turn, phase, current_player, moved_unit_id, reactive_unit_id (si connu), move_cause, tailles des pools. Exemples de messages formates:

- `RuntimeError[reactive_move.reentrance]: episode={episode} turn={turn} phase={phase} current_player={current_player} moved_unit_id={moved_unit_id} move_cause={move_cause} reaction_window_active={reaction_window_active}`
- `KeyError[reactive_move.missing_key]: key={missing_key} episode={episode} turn={turn} phase={phase} current_player={current_player} moved_unit_id={moved_unit_id}`
- `ValueError[reactive_move.invalid_destination]: reactive_unit_id={reactive_unit_id} destination={destination} pool_size={pool_size} episode={episode} turn={turn} phase={phase} current_player={current_player}`

### Flux de controle

1) movement_handlers termine move|advance|flee|reposition_normal ennemi; 2) on_enemy_move_ended(...); 3) maybe_resolve_reactive_move(...); 4) stop si move_cause == reactive_move ou reaction_window_active; detecte eligibles; decision reactive; si move applique: refresh caches; 5) retour handler appelant.

### Fichiers cibles

- `engine/phase_handlers/movement_handlers.py`: emission on_enemy_move_ended, appel maybe_resolve_reactive_move.
- `engine/phase_handlers/shared_utils.py`: eligibilite, validation, refresh_all_positional_caches_after_reactive_move.
- `engine/phase_handlers/shooting_handlers.py`, `charge_handlers.py`: consommation etat recalcule.
- `config/unit_rules.json`: declaration regle `reactive_move`.

### Matrice de tests minimale

Trigger sur move/advance/flee/reposition_normal; aucun trigger si move_cause == reactive_move; portee 8/9/10; multi eligibles deterministe; une reaction par unite par tour adverse; decline; destination hors pool => exception; aucun eligible => pas de regression; caches a jour apres reactive move; sans unite reactive_move => comportement identique baseline.

### Matrice de tests automatisable (Given/When/Then)

1. Trigger move normal: Given unite ennemie termine move a distance 8 d une unite avec reactive_move. When on_enemy_move_ended(..., move_kind="move", move_cause="normal"). Then reaction_window_active == True pendant la resolution et une action reactive est demandee.
2. Trigger advance/flee: meme setup, move_kind advance ou flee; meme comportement de trigger que move.
3. Anti chaine: Given evenement avec move_cause="reactive_move". When maybe_resolve_reactive_move. Then retour immediat, reaction_window_active reste False, aucun nouveau trigger.
4. Portee limite: distances 8, 9, 10 depuis to_col,to_row => 8/9 eligibles, 10 non eligible.
5. Multi eligibles micro: 3 unites u_10, u_2, u_1 => ordre u_1, u_10, u_2 (tri lexicographique).
6. Multi eligibles macro: ordre macro fourni => ordre impose; ordre invalide => ValueError[reactive_move.invalid_macro_order].
7. Once per enemy turn: unite deja dans units_reacted_this_enemy_turn => plus eligible.
8. Decline explicite: action decline_reactive_move => aucun deplacement, last_move_cause reste normal.
9. Destination invalide: destination hors pool => ValueError[reactive_move.invalid_destination].
10. Refresh post reactive: reactive move applique => refresh_all_positional_caches_after_reactive_move execute une fois; valid_move_destinations_pool == [], valid_charge_destinations_pool == [], _target_pool_cache vide, enemy_adjacent_hexes_player_* reconstruits.
11. Non regression globale: aucune unite reactive_move => memes transitions de phase/pools qu avant feature.

### Checklist implementation

Trigger uniquement fin move ennemi; garde anti-chaines; portee depuis nouvelle position ennemie; once per enemy turn; aucun fallback; IDs string; units_reacted_this_enemy_turn reset au changement joueur actif; refresh caches uniquement apres reactive move applique; erreurs explicites; pas de regression flux normal.

### Critere de done

Sans reactive_move: comportement identique; avec reactive_move: mouvement au bon moment, decision explicite; aucun deadlock; aucune chaine reactive; pas d erreur cache stale; matrice de tests verte.

### Plan d implementation par iterations

1. movement_handlers: on_enemy_move_ended, maybe_resolve_reactive_move, move_cause normal. 2. shared_utils: maybe_resolve_reactive_move, eligibilite, validation, refresh_all_positional_caches_after_reactive_move. 3. shooting_handlers: consommation caches apres reactive move. 4. charge_handlers: coherence adjacency/destinations. 5. unit_rules.json: declarer reactive_move. Validation apres chaque iteration: anti-chaine, units_reacted_this_enemy_turn, pas de fallback, flux sans reactive_move identique.

---

# Rules Implementation Audit Checklist

Objectif: déterminer si une regle declaree (`config/unit_rules.json`) peut etre marquee `2 (IMPLEMENTED)` de maniere fiable.

## Statuts

- `0` = `NOT_IMPLEMENTED`
- `1` = `NOT_IMPLEMENTABLE_YET`
- `2` = `IMPLEMENTED`

## Methode de validation (obligatoire)

Une regle passe en `2` seulement si les 3 couches sont validees:

1. **Statique (code)**: la regle est consommee dans les handlers moteur et modifie le gameplay (pas seulement UI/log).
2. **Completeness**: les cas attendus (positifs + negatifs + limites) sont couverts.
3. **Runtime**: scenario(s) de validation reproductibles passes.

---

## Audit statique actuel (preliminaire)

Ce tableau est un **pre-audit statique** base sur le code moteur actuel.
Il donne une proposition, a confirmer par tests runtime.

| ruleId | Preuve statique (handlers) | Statut propose (statique) | Notes |
|---|---|---:|---|
| `charge_after_advance` | `engine/phase_handlers/charge_handlers.py` | 2 | Verifie eligibility/applique exception apres advance |
| `charge_after_flee` | `engine/phase_handlers/charge_handlers.py` | 2 | Verifie eligibility/applique exception apres flee |
| `charge_impact` | `engine/phase_handlers/charge_handlers.py`, `engine/w40k_core.py` | 2 | Effet post-charge + logs action |
| `closest_target_penetration` | `engine/phase_handlers/shooting_handlers.py` | 2 | AP modifiee sur cible eligibile la plus proche |
| `reactive_move` | `engine/phase_handlers/shared_utils.py`, `movement_handlers.py`, `shooting_handlers.py`, `w40k_core.py` | 2 | Fenetre reactive complete + invalidation caches |
| `reroll_1_save_fight` | `engine/phase_handlers/fight_handlers.py` | 2 | Reroll save de 1 en fight |
| `reroll_1_tohit_fight` | `engine/phase_handlers/fight_handlers.py` | 2 | Reroll hit de 1 en fight |
| `reroll_1_towound` | `engine/phase_handlers/fight_handlers.py`, `shooting_handlers.py` | 2 | Reroll wound de 1 en tir + fight |
| `reroll_towound_target_on_objective` | `engine/phase_handlers/fight_handlers.py`, `shooting_handlers.py` | 2 | Full reroll wound si condition objectif |
| `shoot_after_advance` | `engine/phase_handlers/shooting_handlers.py` | 2 | Exception explicite dans check tir apres advance |
| `shoot_after_flee` | `engine/phase_handlers/shooting_handlers.py` | 2 | Exception explicite dans check tir apres flee |
| `move_after_shooting` | `engine/phase_handlers/shooting_handlers.py`, `engine/phase_handlers/charge_handlers.py` | 2 | Mouvement post-tir + blocage charge jusqu'a la fin du tour |
| `adaptable_predators` | grants -> `shoot_after_flee`, `charge_after_flee` | 2 | Regle composee; depend du systeme grants |
| `adaptable_predators_shoot_after_flee` | alias -> `shoot_after_flee` | 2 | Alias d'affichage |
| `adaptable_predators_charge_after_flee` | alias -> `charge_after_flee` | 2 | Alias d'affichage |
| `adrenalised_onslaught` | grants `or` + `choice_timing` via `w40k_core.py` | 2 | Selection runtime d'une option en phase fight |
| `aggression_imperative` | alias -> `reroll_1_tohit_fight` | 2 | Alias d'affichage |
| `preservation_imperative` | alias -> `reroll_1_save_fight` | 2 | Alias d'affichage |
| `cunning_hunters` | grants -> `shoot_after_advance`, `shoot_after_flee` | 2 | Regle composee |
| `cunning_hunters_shoot_after_advance` | alias -> `shoot_after_advance` | 2 | Alias d'affichage |
| `cunning_hunters_shoot_after_flee` | alias -> `shoot_after_flee` | 2 | Alias d'affichage |
| `targeted_intercession` | grants -> reroll wound rules | 2 | Regle composee |
| `targeted_intercession_reroll_1_towound` | alias -> `reroll_1_towound` | 2 | Alias d'affichage |
| `targeted_intercession_reroll_towound_target_on_objective` | alias -> `reroll_towound_target_on_objective` | 2 | Alias d'affichage |

---

## Checklist runtime par famille de regles

### A. Permissions d'action

Regles: `shoot_after_advance`, `shoot_after_flee`, `charge_after_advance`, `charge_after_flee`

- [ ] Cas positif: action autorisee quand la regle est presente
- [ ] Cas negatif: action refusee sans la regle
- [ ] Cas limite: interaction avec autres restrictions de phase
- [ ] Log explicite present (source display rule)

### B. Modificateurs de combat

Regles: `closest_target_penetration`, `reroll_1_towound`, `reroll_towound_target_on_objective`, `reroll_1_tohit_fight`, `reroll_1_save_fight`

- [ ] Cas positif: modificateur applique
- [ ] Cas negatif: modificateur non applique hors condition
- [ ] Cas limite: cible sur/ hors objectif, combat vs tir, cible la plus proche vs autre
- [ ] Verification des logs de source de regle

### C. Reactions / effets post-action

Regles: `reactive_move`, `charge_impact`

- [ ] Cas positif: effet declenche dans la fenetre attendue
- [ ] Cas negatif: pas de declenchement hors fenetre
- [ ] Cas limite: refus joueur/IA, destination invalide, cache refresh
- [ ] Verification action logs + coherence des positions

### D. Regles composees (grants/alias/choice)

Regles: `adaptable_predators*`, `cunning_hunters*`, `targeted_intercession*`, `adrenalised_onslaught`, `aggression_imperative`, `preservation_imperative`

- [ ] `alias` resolu vers regle technique correcte
- [ ] `grants_rule_ids` actifs selon `usage` (`and` / `or` / `unique`)
- [ ] `choice_timing` declenche au bon moment
- [ ] Option selectionnee effectivement appliquee

---

## Regles en alerte

Aucune alerte ouverte dans l'etat actuel du pre-audit statique.
