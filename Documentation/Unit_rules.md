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
