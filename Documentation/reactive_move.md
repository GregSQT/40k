# Reactive Move - Specification d implementation

## Objectif

Ajouter la regle `reactive_move` de facon robuste, deterministe, et compatible training:

- trigger uniquement apres la fin d un mouvement ennemi;
- aucun fallback silencieux;
- aucune boucle infinie;
- refresh complet des caches positionnels uniquement apres un `reactive_move`;
- comportement normal inchange en dehors de ce cas.

## Regle metier figee

Une unite avec `reactive_move` peut, si elle le veut, effectuer un deplacement reactif (jusqu a D6) quand une unite ennemie termine un mouvement `move|advance|flee|reposition_normal` dans un rayon de 9.

Contraintes metier:

- la distance est mesuree depuis la nouvelle position (`to_col`, `to_row`) de l unite ennemie qui vient de terminer son mouvement;
- une unite ne peut faire qu un `reactive_move` par tour adverse;
- un `reactive_move` ne peut jamais en declencher un autre.

## Decisions figees (scope courant)

Ces decisions sont verrouillees pour l implementation initiale:

1. Fenetre unique par evenement de move
   - un `move|advance|flee|reposition_normal` ennemi ouvre exactement une `reaction_window`;
   - la fenetre est fermee une fois le `reaction_pool` epuise.

2. Reaction pool construit une seule fois
   - le `reaction_pool` est calcule au debut de la `reaction_window`;
   - pas de recalcul incremental du pool apres chaque reactive move dans la meme fenetre.

3. Reactions sequencées sans retrigger
   - plusieurs unites peuvent reagir de facon sequentielle dans la meme fenetre;
   - un `reactive_move` applique ne cree jamais une nouvelle fenetre de reaction;
   - pas de mecanique `react_moved_units` en file pour relancer des vagues.

4. Refresh cache strictement cible
   - refresh complet des caches positionnels uniquement apres un `reactive_move` effectivement applique;
   - aucun refresh global additionnel hors ce cas.

## Invariants non negociables

1. Pas de fallback anti-erreur.
   - si un champ requis manque: `KeyError`/`ValueError` explicite.
2. Source de verite unique.
   - positions/HP via `units_cache` et helpers existants.
3. Pas de trigger en chaine.
   - un reactive move ne peut jamais en declencher un autre.
4. Etat de phase coherent.
   - le reactive move ne doit pas corrompre `active_*_unit` ni les pools d activation.
5. Refresh complet cible.
   - uniquement sur `move_cause == reactive_move`.

## Contrat d evenement

Point unique de trigger:

- `on_enemy_move_ended(moved_unit_id, from_col, from_row, to_col, to_row, move_kind, move_cause)`

Contraintes:

- `move_kind` in `{move, advance, flee, reposition_normal}`
- `move_cause` in `{normal, reactive_move}`
- si `move_cause == "reactive_move"` alors stop immediat (anti-chaine)
- `reposition_normal` est traite comme un deplacement normal pour le trigger `reactive_move`, meme hors phase move.

## Contrat game_state

Champs requis a ajouter:

- `units_reacted_this_enemy_turn: set[str]`
  - trace les unites ayant deja react pendant le tour adverse courant.
- `reaction_window_active: bool`
  - garde de re-entrance pour empecher les triggers imbriques.
- `last_move_event_id: int`
  - identifiant monotone pour debug/tracabilite.
- `last_move_cause: str`
  - `normal` ou `reactive_move`.

Initialisation:

- au reset episode: set vide, `reaction_window_active = False`, `last_move_event_id = 0`, `last_move_cause = "normal"`.

Reset tour:

- au changement de joueur actif: vider `units_reacted_this_enemy_turn`.
- ne pas vider a chaque phase.

## Detection d eligibilite

Une unite reactionnaire est eligible si:

1. vivante;
2. camp oppose a l unite qui vient de bouger;
3. possede `reactive_move` (direct ou via `grants_rule_ids`);
4. pas deja utilisee pendant ce tour adverse (`units_reacted_this_enemy_turn`);
5. distance hex <= 9 depuis `to_col`, `to_row` de l unite ennemie;
6. dispose d au moins une destination legale de mouvement reactif.

Si aucune unite eligible: fin immediate du flux reactif.

## Politique training (decision et destination)

En training/gym:

- l unite reactionnaire choisit explicitement:
  - soit `decline_reactive_move`,
  - soit `reactive_move(unit_id, destination)`.
- la destination doit appartenir au pool legal calcule pour ce reactive move;
- toute destination hors pool = `ValueError` explicite (pas de correction automatique, pas de fallback).

### Politique multi eligibles (figee)

Quand plusieurs unites sont eligibles:

- mode micro:
  - ordre de presentation/selection deterministe;
  - tri numerique sur la partie numerique de `unit_id` quand possible (ex: `u_2` avant `u_10`);
  - fallback explicite au tri lexicographique string si aucun ordre numerique n est derivable.
- mode macro:
  - l ordre est fourni par le macro agent;
  - si l ordre macro est absent, vide, ou contient un id non eligible: `ValueError` explicite.

### References techniques a respecter

- Trigger et orchestration:
  - `engine/phase_handlers/movement_handlers.py`
  - `on_enemy_move_ended(...)` puis `maybe_resolve_reactive_move(...)`.
- Resolution reactive et refresh centralise:
  - `engine/phase_handlers/shared_utils.py` (ou module dedie equivalent).
- Distance hex et normalisation coordonnees:
  - `engine/combat_utils.py`
  - utiliser `get_unit_coordinates(...)` et/ou `normalize_coordinates(...)` avant calcul distance;
  - utiliser `calculate_hex_distance(...)` (pas de reimplementation inline).
- Jet D6:
  - utiliser `resolve_dice_value("D6", "reactive_move_distance")` depuis `engine/combat_utils.py`;
  - interdit de dupliquer une logique ad hoc de D6 (ex: `random.randint(1, 6)` inline dans le handler reactive).

## Resolution du reactive move

Sequence stricte:

1. verifier gardes (`move_cause`, `reaction_window_active`, coherence state);
2. marquer `reaction_window_active = True`;
3. selectionner une unite eligible (selon politique explicite);
4. resoudre la decision (decline ou move);
5. si move: roll D6, calcul destinations legales, appliquer deplacement via primitives move existantes;
6. si move: `units_reacted_this_enemy_turn.add(unit_id_str)`;
7. marquer `last_move_cause = "reactive_move"` si move applique;
8. executer `refresh_all_positional_caches_after_reactive_move(game_state)` si move applique;
9. `reaction_window_active = False`;
10. retour au flux normal.

Garantie d implementation:

- le reset `reaction_window_active = False` doit etre garanti par un bloc `finally`, y compris en cas d exception.

## Strategie cache (contrat centralise)

Creer une fonction unique:

- `refresh_all_positional_caches_after_reactive_move(game_state)`

Responsabilites minimales:

1. invalider/reconstruire caches LoS globaux + unit-local impactes;
2. invalider/reconstruire `_target_pool_cache` / `valid_target_pool` stale;
3. invalider/reconstruire pools de destinations stale (move/charge/shoot selon design existant);
4. reconstruire structures d adjacency ennemie utilisees par restrictions move/charge/shoot.

Liste minimale des cles/pools a traiter explicitement:

- `units_cache` (source de verite positions/HP vivants): mise a jour incrementale des entrees impactees, pas rebuild global force;
- `game_state["los_cache"]`;
- `game_state["hex_los_cache"]`;
- `unit["los_cache"]` pour les unites actives impactees;
- `_target_pool_cache`;
- `unit["valid_target_pool"]` (toutes unites concernees);
- `game_state["valid_move_destinations_pool"]`;
- `game_state["valid_charge_destinations_pool"]`;
- `game_state[f"enemy_adjacent_hexes_player_{current_player}"]`;
- `game_state[f"enemy_adjacent_hexes_player_{enemy_player}"]`.

API/fonctions existantes a reutiliser dans le refresh:

- `build_enemy_adjacent_hexes(game_state, player)` dans `engine/phase_handlers/shared_utils.py`;
- `_invalidate_all_destination_pools_after_movement(game_state)` dans `engine/phase_handlers/movement_handlers.py`.

Regle d architecture:

- ne pas disperser le refresh entre plusieurs handlers;
- les invalidations normales deja necessaires hors reactive_move restent inchangees;
- le refresh global post-reactive est une securisation supplementaire, pas un remplacement de la logique normale.

Regle de validation:

- toute cle attendue mais absente dans un contexte ou elle est requise doit lever `KeyError` explicite;
- ne jamais remplacer une cle manquante par `{}` ou `[]` par defaut.

## Contrat d erreurs (comportement appelant)

Cas normaux (pas d erreur):

- aucune unite eligible;
- unite eligible mais decision `decline_reactive_move`.

Cas incoherents (fail hard, exception propagee):

- recursivite/re-entrance detectee;
- champs requis manquants;
- destination invalide hors pool;
- joueur/camp incoherent.

Types recommandes:

- `RuntimeError`: trigger recursif ou fenetre reaction incoherente;
- `KeyError`: champ requis manquant (`units_cache`, pools requis, etc);
- `ValueError`: action/destination invalide, etat metier incoherent.

Message d erreur minimal:

- `episode`, `turn`, `phase`, `current_player`;
- `moved_unit_id`, `reactive_unit_id` (si connu), `move_cause`;
- tailles des pools critiques.

Exemples de messages formates (uniformisation logs):

- `RuntimeError[reactive_move.reentrance]: episode={episode} turn={turn} phase={phase} current_player={current_player} moved_unit_id={moved_unit_id} move_cause={move_cause} reaction_window_active={reaction_window_active}`
- `KeyError[reactive_move.missing_key]: key={missing_key} episode={episode} turn={turn} phase={phase} current_player={current_player} moved_unit_id={moved_unit_id}`
- `ValueError[reactive_move.invalid_destination]: reactive_unit_id={reactive_unit_id} destination={destination} pool_size={pool_size} episode={episode} turn={turn} phase={phase} current_player={current_player}`

## Flux de controle recommande

1. `movement_handlers` termine un `move|advance|flee|reposition_normal` ennemi;
2. emission `on_enemy_move_ended(...)`;
3. appel `maybe_resolve_reactive_move(...)`;
4. `maybe_resolve_reactive_move`:
   - stop si `move_cause == reactive_move`;
   - stop si `reaction_window_active == True`;
   - detecte eligibles;
   - ouvre la decision reactive (decline ou move) pour une unite eligible;
   - si move applique: refresh global des caches positionnels;
5. retour au handler appelant.

## Fichiers cibles et responsabilites

1. `engine/phase_handlers/movement_handlers.py`
   - point d emission `on_enemy_move_ended`;
   - appel `maybe_resolve_reactive_move`.

2. `engine/phase_handlers/shared_utils.py` (ou module dedie)
   - detection eligibilite reactive;
   - validation decision/destination;
   - `refresh_all_positional_caches_after_reactive_move`.

3. `engine/phase_handlers/shooting_handlers.py` et `charge_handlers.py`
   - verifier consommation correcte de l etat recalcule.

4. `config/unit_rules.json`
   - declaration de la regle `reactive_move`.

## Matrice de tests minimale

1. Trigger sur `move`, `advance`, `flee`.
1.b Trigger sur `reposition_normal` (hors phase move).
2. Aucun trigger quand `move_cause == reactive_move`.
3. Portee: cas distance 8, 9, 10 depuis la nouvelle position ennemie.
4. Multi eligibles: decision explicite et resultat deterministe en training.
5. Une unite ne reagit qu une fois par tour adverse.
6. Cas `decline_reactive_move`: aucun deplacement, flux stable.
7. Destination hors pool: exception explicite.
8. Aucun eligible: pas de regression du flux normal.
9. Apres reactive move: shooting/charge lisent des caches a jour.
10. Non regression: sans unite `reactive_move`, comportement identique baseline.

## Matrice de tests automatisable (Given/When/Then)

1. Trigger move normal
   - Given: une unite ennemie termine `move` a distance 8 d une unite avec `reactive_move`.
   - When: `on_enemy_move_ended(..., move_kind="move", move_cause="normal")`.
   - Then: `reaction_window_active == True` pendant la resolution et une action reactive est demandee.

2. Trigger advance
   - Given: meme setup, `move_kind="advance"`.
   - When: fin de mouvement.
   - Then: meme comportement de trigger que `move`.

3. Trigger flee
   - Given: meme setup, `move_kind="flee"`.
   - When: fin de mouvement.
   - Then: meme comportement de trigger que `move`.

4. Anti chaine
   - Given: un evenement termine avec `move_cause="reactive_move"`.
   - When: `maybe_resolve_reactive_move(...)` est appele.
   - Then: retour immediat, `reaction_window_active` reste `False`, aucun nouveau trigger.

5. Portee limite
   - Given: cas distances 8, 9, 10 depuis `to_col,to_row`.
   - When: evaluation eligibilite.
   - Then: 8/9 eligibles, 10 non eligible.

6. Multi eligibles micro
   - Given: 3 unites eligibles ids `u_10`, `u_2`, `u_1`.
   - When: mode micro.
   - Then: ordre de selection `u_1`, `u_10`, `u_2` (tri string lexicographique).

7. Multi eligibles macro
   - Given: ordre macro fourni (`u_2`, `u_1`) et unites eligibles correspondantes.
   - When: mode macro.
   - Then: ordre impose par macro; si ordre invalide -> `ValueError[reactive_move.invalid_macro_order]`.

8. Once per enemy turn
   - Given: une unite a deja react dans `units_reacted_this_enemy_turn`.
   - When: nouveau trigger dans le meme tour adverse.
   - Then: cette unite n est plus eligible.

9. Decline explicite
   - Given: unite eligible.
   - When: action `decline_reactive_move`.
   - Then: aucun deplacement applique, `last_move_cause` reste `normal`, flux continue sans erreur.

10. Destination invalide
    - Given: destination proposee hors pool legal.
    - When: validation action reactive.
    - Then: `ValueError[reactive_move.invalid_destination]`.

11. Refresh post reactive
    - Given: un reactive move est applique.
    - When: fin de resolution.
   - Then: `refresh_all_positional_caches_after_reactive_move(game_state)` est execute une fois et:
     - `game_state["valid_move_destinations_pool"] == []`
     - `game_state["valid_charge_destinations_pool"] == []`
     - `_target_pool_cache` est vide
     - les caches `enemy_adjacent_hexes_player_*` des 2 joueurs sont reconstruits.

12. Non regression globale
    - Given: aucune unite ne possede `reactive_move`.
    - When: execution complete d un tour.
    - Then: memes transitions de phase/pools qu avant feature.

## Checklist implementation

- [ ] Trigger reactive uniquement sur fin de move ennemi.
- [ ] Garde anti-chaines (`move_cause == reactive_move` => no trigger).
- [ ] Portee mesuree depuis la nouvelle position de l unite ennemie.
- [ ] Limite once per enemy turn respectee.
- [ ] Aucun fallback silencieux.
- [ ] IDs normalises en string pour sets/pools.
- [ ] `units_reacted_this_enemy_turn` reset au changement de joueur actif.
- [ ] Refresh complet caches positionnels uniquement apres reactive move applique.
- [ ] Erreurs explicites avec contexte runtime complet.
- [ ] Pas de regression sur flux normal sans reactive_move.

## Critere de done

La feature est consideree propre si:

1. sans unite `reactive_move`: comportement strictement identique a avant;
2. avec `reactive_move`: mouvement reactif au bon moment, avec decision explicite;
3. aucun deadlock de phase/pool;
4. aucune chaine reactive;
5. pas d erreur cache stale apres reactive move;
6. matrice de tests minimale verte.

## Plan d implementation par iterations (1 fichier a la fois)

Objectif de ce plan:

- minimiser le risque de regression;
- garder des changements lisibles et auditables;
- valider les invariants apres chaque etape.

### Iteration 1 - `engine/phase_handlers/movement_handlers.py`

Scope:

- ajouter le point unique d emission `on_enemy_move_ended(...)`;
- ajouter l appel a `maybe_resolve_reactive_move(...)` en fin de `move|advance|flee|reposition_normal`;
- propager `move_cause` (`normal` pour le flux standard).

Critere de sortie:

- aucun changement de comportement observable sans regle `reactive_move`;
- anti-chaine active (`move_cause == reactive_move` bloque le trigger).

### Iteration 2 - `engine/phase_handlers/shared_utils.py` (ou module dedie)

Scope:

- implementer `maybe_resolve_reactive_move(...)`;
- implementer detection d eligibilite (distance depuis `to_col,to_row`, once per enemy turn);
- implementer validation stricte des actions (`decline` ou destination legale);
- implementer `refresh_all_positional_caches_after_reactive_move(game_state)`.

Critere de sortie:

- reactive move fonctionnel sur cas simple;
- erreurs explicites sur etats incoherents (pas de fallback).

### Iteration 3 - `engine/phase_handlers/shooting_handlers.py`

Scope:

- verifier/adapter la consommation des caches et pools apres reactive move;
- supprimer toute hypothese stale sur positions pre-reactive.

Critere de sortie:

- aucune incoherence de targets juste apres un reactive move.

### Iteration 4 - `engine/phase_handlers/charge_handlers.py`

Scope:

- verifier/adapter restrictions et pools apres reactive move;
- garantir coherence adjacency/destinations sur etat recalcule.

Critere de sortie:

- aucune incoherence de charge juste apres un reactive move.

### Iteration 5 - `config/unit_rules.json`

Scope:

- declarer la regle `reactive_move` pour les unites ciblees.

Critere de sortie:

- activation de la regle uniquement pour les unites configurees.

### Validation a faire apres chaque iteration

- verifier anti-chaine (`reactive_move` ne retrigger jamais);
- verifier `units_reacted_this_enemy_turn` (max 1 reaction par unite et par tour adverse);
- verifier absence de fallback silencieux;
- verifier qu un flux sans `reactive_move` reste identique au baseline.

