## Migration vers units_cache comme source unique

### Objectif
Faire de `game_state["units_cache"]` la **seule source de verite** pour :
- HP (etat vivant/mort)
- positions (col/row)
- eligibilite et fin de phase/tour/episode

Le tableau `game_state["units"]` reste une source **statique** (unitType, armes, stats de base), jamais utilisee pour HP/positions.

### Contexte et regles
- Lire HP via `get_hp_from_cache()` / `require_hp_from_cache()`.
- Lire positions via `get_unit_position()` / `require_unit_position()`.
- Determiner vivant via `is_unit_alive()`.
- Ne jamais lire `unit["HP_CUR"]`, `unit["col"]`, `unit["row"]` pour la logique runtime.

### Decision critique a clarifier
Deux sources documentent des comportements differents :
- `Documentation/AI_IMPLEMENTATION.md` indique que les unites mortes restent dans `units_cache` (HP_CUR=0).
- `engine/phase_handlers/shared_utils.py` retire l'unite du cache quand HP <= 0.

Cette migration doit **choisir un seul comportement** et l'appliquer partout, sinon les caches/pools deviennent incoherents.

### Invariants a maintenir
- `units_cache` existe toujours apres `reset()`.
- Tout calcul d'eligibilite s'appuie sur `units_cache`, jamais sur `game_state["units"]`.
- Fin de phase = pool vide (pas de scan sur `game_state["units"]`).
- Fin de tour/episode = derivee des pools et/ou du cache (pas d'HP/positions depuis `units`).

---

## Plan de migration (etapes)

### Etape 1 - Infrastructure de lecture (cache first)
Remplacer les lectures directes par les helpers :
- HP : `get_hp_from_cache()` / `require_hp_from_cache()`
- Position : `get_unit_position()` / `require_unit_position()`
- Vivant : `is_unit_alive()`

Objectif : aucune lecture runtime d'HP/position ne passe par `game_state["units"]`.

### Etape 2 - Pools d'activation (priorite haute)
Pour chaque phase :
- construire les pools **a partir de `units_cache`** (ids + col/row/HP/player).
- faire un lookup vers `game_state["units"]` uniquement pour les champs statiques.
- bannir toute condition d'eligibilite basee sur `unit["HP_CUR"]` ou `unit["col"]`.

Phases concernees :
- move
- shoot
- charge
- fight

### Etape 3 - Fin de phase / fin de tour / fin d'episode
Tous les calculs de fin doivent etre bases sur :
- pools d'activation (vides = fin de phase)
- `units_cache` (comptage par player et HP_CUR)

Exemples de regles a appliquer :
- phase complete = pool vide
- fin d'episode = un seul player vivant OU limite de tours

### Etape 4 - Combat, LoS, adjacency
Toutes les boucles qui calculent :
- adjacency (melee range)
- LoS ou range
- cibles valides
doivent lire les positions via `require_unit_position()` (cache), jamais via `unit["col"]/unit["row"]`.

### Etape 5 - Observation / Reward
Refactoriser les encodages et scores tactiques pour :
- enumerer les unites depuis `units_cache`
- faire un lookup vers `game_state["units"]` pour le contenu statique

### Etape 6 - Nettoyage final
- supprimer tout acces runtime a `unit["HP_CUR"]`, `unit["col"]`, `unit["row"]`
- interdire toute fin de phase/episode basee sur `game_state["units"]`

---

## Inventaire des zones a migrer (priorite)

### Priorite 1 - Phase handlers
- `engine/phase_handlers/movement_handlers.py`
- `engine/phase_handlers/shooting_handlers.py`
- `engine/phase_handlers/charge_handlers.py`
- `engine/phase_handlers/fight_handlers.py`

### Priorite 2 - Engine core / fin d'episode
- `engine/w40k_core.py` (fin d'episode, metrics)

### Priorite 3 - Observation / Reward
- `engine/observation_builder.py`
- `engine/reward_calculator.py`

### Priorite 4 - Utils et selection d'armes
- `engine/combat_utils.py`
- `engine/ai/weapon_selector.py`

---

## Regles de migration detaillees

### Pattern A - Boucle principale
Avant :
- `for unit in game_state["units"]`

Apres :
- `for unit_id, entry in units_cache.items()`
- `unit = get_unit_by_id(unit_id, game_state)` uniquement si necessaire

### Pattern B - Positions
- remplacer `unit["col"]`, `unit["row"]` par `require_unit_position(unit, game_state)`

### Pattern C - HP
- remplacer `unit["HP_CUR"]` par `get_hp_from_cache(unit_id, game_state)`

### Pattern D - Vivant
- remplacer toute logique ad hoc par `is_unit_alive(unit_id, game_state)`

---

## Checklist par module

### Phase handlers
- [ ] Pools construits depuis `units_cache`
- [ ] Adjacency / LoS via `require_unit_position`
- [ ] Eligibilite basee sur cache
- [ ] Fin de phase = pool vide

### Engine core
- [ ] Fin d'episode calculee depuis `units_cache`
- [ ] Pas de scan HP/positions dans `game_state["units"]`

### Observation / Reward
- [ ] Enumeration via `units_cache`
- [ ] Lookup `game_state["units"]` uniquement pour armes/stats statiques

---

## Tests recommandes

1) Run court (debug off) :
- 50 episodes

2) Run moyen :
- 200 a 500 episodes

3) Run long :
- 1000 episodes si besoin de validation robustesse

Verifier :
- pas de boucle de phase sans actions
- pools cohérents
- pas de regressions sur LoS / adjacency

---

## Notes de decision

### Source unique = cache
Si une unite est absente du cache, elle est **consideree morte**.
Toute logique runtime doit respecter cette regle.

### References
- `Documentation/AI_TURN.md`
- `Documentation/AI_IMPLEMENTATION.md`
- `Documentation/unit_cache21.md`

---

## Audit initial (zones qui utilisent encore game_state["units"])

### Engine core
- `engine/w40k_core.py` : fin d'episode / comptage d'unites (survivants, totaux)

### Phase handlers
- `engine/phase_handlers/movement_handlers.py` : eligibility, adjacency, pool build
- `engine/phase_handlers/shooting_handlers.py` : adjacency/LoS, pool build, cibles valides
- `engine/phase_handlers/charge_handlers.py` : adjacency, destinations, pools
- `engine/phase_handlers/fight_handlers.py` : eligibility / target loops
- `engine/phase_handlers/generic_handlers.py` : boucles d'unites

### Observation / Reward
- `engine/observation_builder.py` : encoding positions/targets/ally/enemy
- `engine/reward_calculator.py` : menaces, targets, proximite

### Utils / AI
- `engine/combat_utils.py` : helpers qui iterent sur units
- `engine/game_utils.py` : lookup par id
- `engine/action_decoder.py` : selection d'ennemis/eligibles
- `engine/ai/weapon_selector.py` : selection d'unites actives/ennemies

### Game state / scenario
- `engine/game_state.py` : initialisation / validation (OK pour statique)

#### Rappel d'audit
Tout usage de `game_state["units"]` est autorise **uniquement** pour des champs statiques
(unitType, armes, stats de base). Toute lecture HP/position/etat vivant ou fin de phase
doit basculer sur `units_cache` via les helpers.

---

## Audit granulaire (fonction par fonction)

### engine/action_decoder.py
- `get_all_valid_targets`
- `can_melee_units_charge_target`

### engine/ai/weapon_selector.py
- `precompute_kill_probability_cache`
- `recompute_cache_for_new_units_in_range`

### engine/combat_utils.py
- `get_unit_by_id`
- `has_valid_shooting_targets`

### engine/game_state.py
- `initialize_units`
- `get_unit_by_id`
- `calculate_objective_control`
- `check_game_over`
- `determine_winner`
- `determine_winner_with_method`

### engine/game_utils.py
- `get_unit_by_id`

### engine/observation_builder.py
- `_build_los_cache_for_observation`
- `_calculate_army_weighted_threat`
- `_can_melee_units_charge_target`
- `_encode_objective_control`
- `_get_active_unit_for_observation`
- `_encode_allied_units`
- `_encode_enemy_units`
- `_enemy_priority`
- `_get_valid_targets`
- `_get_six_reference_enemies`
- `_find_nearest_in_direction`
- `build_observation`

### engine/phase_handlers/charge_handlers.py
- `get_eligible_units`
- `charge_build_valid_targets`
- `charge_build_valid_destinations_pool`
- `_attempt_charge_to_destination`
- `_is_valid_charge_destination`
- `_select_strategic_destination`
- `_has_valid_charge_target`
- `_is_adjacent_to_enemy`
- `_is_hex_adjacent_to_enemy`
- `_find_adjacent_enemy_at_destination`
- `_hp_display`
- `_is_adjacent_to_enemy_simple`
- `charge_phase_end`

### engine/phase_handlers/fight_handlers.py
- `fight_build_activation_pools`
- `_is_adjacent_to_enemy_within_cc_range`
- `_fight_build_valid_target_pool`
- `_has_los_to_enemies_within_range`

### engine/phase_handlers/generic_handlers.py
- `_rebuild_alternating_pools_for_fight`
- `_is_adjacent_to_enemy_for_fight`

### engine/phase_handlers/movement_handlers.py
- `get_eligible_units`
- `movement_build_valid_destinations_pool`
- `_is_valid_destination`
- `_attempt_movement_to_destination`
- `_is_adjacent_to_enemy`
- `_select_strategic_destination`
- `movement_phase_end`

### engine/phase_handlers/shared_utils.py
- `build_units_cache` (OK pour init, pas runtime)
- `check_if_melee_can_charge`

### engine/phase_handlers/shooting_handlers.py
- `shooting_phase_start`
- `_get_available_weapons_for_selection`
- `weapon_availability_check`
- `_build_shooting_los_cache`
- `_rebuild_los_cache_for_unit`
- `shooting_build_activation_pool`
- `_is_valid_shooting_target`
- `valid_target_pool_build`
- `_is_adjacent_to_enemy_within_cc_range`
- `_has_los_to_enemies_within_range`
- `_get_unit_by_id`
- `_handle_advance_action`

### engine/pve_controller.py
- `load_ai_model_for_pve`
- `_ai_select_movement_destination`

### engine/reward_calculator.py
- `_get_situational_reward`
- `_calculate_objective_reward_turn5`
- `_calculate_army_weighted_threat`
- `_determine_winner`

### engine/w40k_core.py
- `reset`
- `step` (fin d'episode / metrics)
- `_check_game_over`
- `validate_compliance`
- `_reload_scenario` (init, OK statique)
