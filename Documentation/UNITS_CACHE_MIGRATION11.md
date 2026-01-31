## Migration units_cache (version 11, mort = absent)

### Objectif
Faire de `game_state["units_cache"]` la **seule source de verite** pour :
- HP (etat vivant/mort)
- positions (col/row)
- eligibilite et fin de phase/tour/episode

`game_state["units"]` reste **statique** (unitType, armes, stats de base) et ne doit
jamais etre utilise pour HP/positions ou logique runtime.

---

## Decision ferme
**Mort = absent du cache.**
- Si une unite est absente de `units_cache`, elle est consideree morte.
- Une unite vivante est **toujours** presente dans `units_cache` avec `HP_CUR > 0`.
- Aucune logique runtime ne doit traiter une unite absente comme vivante.

Cette decision est obligatoire et doit etre appliquee partout (code + docs).

---

## Contrats d'API (helpers)

### HP
- `get_hp_from_cache(unit_id, game_state)` : retourne l'HP si present, **None** si absent.
- `require_hp_from_cache(unit_id, game_state)` : erreur explicite si absent.

### Position
- `get_unit_position(unit_id, game_state)` : retourne `(col, row)` si present, **None** si absent.
- `require_unit_position(unit_id, game_state)` : erreur explicite si absent.

### Vivant
- `is_unit_alive(unit_id, game_state)` : vrai si present dans `units_cache` **et** `HP_CUR > 0`.

---

## Invariants a maintenir
- `units_cache` existe toujours apres `reset()`.
- Toute logique runtime (eligibilite, LoS, adjacency, fin de phase) s'appuie sur `units_cache`.
- Fin de phase = pool vide (pas de scan sur `game_state["units"]`).
- Fin de tour/episode = derivee des pools et/ou du cache.
- Mort = **absent** du cache, sans exception.

---

## Regles d'execution (prompt-ready)

### A. Ordre strict
1) Remplacer les lectures HP/position/vivant par les helpers.
2) Rebatir tous les pools d'activation a partir de `units_cache`.
3) Corriger fin de phase / tour / episode pour ne lire que pools + cache.
4) Corriger adjacency / LoS / range pour ne lire que `require_unit_position`.
5) Corriger observation / reward pour enumerer via `units_cache`.
6) Nettoyer tout acces runtime a `unit["HP_CUR"]`, `unit["col"]`, `unit["row"]`.

### B. Stop conditions (obligatoires)
Arreter si :
- Une fonction runtime lit `unit["HP_CUR"]` ou `unit["col"]/["row"]`.
- Un pool est construit en scannant `game_state["units"]` pour l'eligibilite.
- Une fin de phase/episode depend de `game_state["units"]`.
- Une unite morte reste dans `units_cache`.

---

## Patterns de migration (remplacements attendus)

### Pattern A - Boucle principale
Avant :
- `for unit in game_state["units"]`

Apres :
- `for unit_id, entry in units_cache.items()`
- `unit = get_unit_by_id(unit_id, game_state)` uniquement si necessaire (statique).

### Pattern B - Positions
- Remplacer `unit["col"]`, `unit["row"]` par `require_unit_position(unit_id, game_state)`.

### Pattern C - HP
- Remplacer `unit["HP_CUR"]` par `get_hp_from_cache(unit_id, game_state)`.

### Pattern D - Vivant
- Remplacer toute logique ad hoc par `is_unit_alive(unit_id, game_state)`.

### Pattern E - Mort = absent
- Toute logique doit traiter "absent du cache" comme "mort".
- Ne jamais conserver une unite morte dans `units_cache`.

---

## Zones a migrer (priorite)

### Priorite 1 - Phase handlers
- `engine/phase_handlers/movement_handlers.py`
- `engine/phase_handlers/shooting_handlers.py`
- `engine/phase_handlers/charge_handlers.py`
- `engine/phase_handlers/fight_handlers.py`
- `engine/phase_handlers/generic_handlers.py`

### Priorite 2 - Engine core / fin d'episode
- `engine/w40k_core.py` (fin d'episode, metrics)

### Priorite 3 - Observation / Reward
- `engine/observation_builder.py`
- `engine/reward_calculator.py`

### Priorite 4 - Utils et selection d'armes
- `engine/combat_utils.py`
- `engine/ai/weapon_selector.py`
- `engine/action_decoder.py`
- `engine/game_utils.py`

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

---

## Harmonisation documentaire
`Documentation/AI_IMPLEMENTATION.md` doit affirmer "mort = absent".
Si un passage indique "mort = HP_CUR=0 dans le cache", il doit etre corrige.

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
- pools coherents
- pas de regressions sur LoS / adjacency

---

## References
- `Documentation/AI_TURN.md`
- `Documentation/AI_IMPLEMENTATION.md`
- `Documentation/unit_cache21.md`
