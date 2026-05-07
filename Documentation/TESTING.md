# Testing

## Lancer les tests

```bash
# Python — tous les tests (depuis la racine)
source .venv/bin/activate
pytest tests/unit/ -q

# Python — engine uniquement
pytest tests/unit/engine/ -q

# Frontend (depuis frontend/)
npx vitest run
```

---

## État actuel

### Python — `tests/unit/engine/` + `tests/unit/services/`

**853 tests, ~1.8s** (2 skipped)

| Fichier | Tests | Ce qui est couvert |
|---|---|---|
| `test_hex_utils.py` | 89 | LoS (`compute_los_visibility`, `compute_los_state`), voisins hex, distances, pathfinding |
| `test_movement_pool_build.py` | 7 | `movement_build_valid_destinations_pool`, `_movement_engagement_violates` |
| `test_move_eligibility.py` | 12 | `get_eligible_units` (move), activation pool, `movement_preview`, `movement_clear_preview` |
| `test_move_resolution.py` | 5 | BFS destinations : plateau vide, murs, alliés, EZ, unité FLY |
| `test_move_execution.py` | 16 | `_attempt_movement_to_destination` : position, cache, flee, EZ, enemy_adjacent_hexes + socles non ronds |
| `test_charge_eligibility.py` | 9 | `get_eligible_units` (charge) — filtres player/EZ/fled/cannot_charge/advanced/no-target |
| `test_charge_resolution.py` | — | BFS destinations charge |
| `test_charge_execution.py` | 17 | `charge_phase_start`, `_has_valid_charge_target`, `charge_build_valid_destinations_pool` (BFS) |
| `test_shooting_activation_pool.py` | 7 | `shooting_build_activation_pool` — filtres player/HP_CUR/no-targets |
| `test_shoot_resolution.py` | 4 | `_has_valid_shooting_targets` — adjacence, pistol, fuite |
| `test_shoot_execution.py` | 16 | HP partiel/létal/limites, cascade mort pools, `active_shooting_unit`, `is_unit_alive` |
| `test_shoot_attack_sequence.py` | 7 | `_attack_sequence_rng` — to_hit, to_wound, save, dégâts, AP, dés fixés |
| `test_fight_special_rules.py` | 22 | `DEVASTATING_WOUNDS` (wound=6 skip save), `HAZARDOUS` (roll=1 self-dmg), combinaisons |
| `test_fight_activation_pools.py` | 9 | `fight_build_activation_pools` — pools charging/alternating, `units_fought` |
| `test_fight_resolution.py` | 5 | `_fight_build_valid_target_pool` — EZ, mort, allié, multi-cibles |
| `test_fight_execution.py` | 20 | HP management, cascade mort fight, `resolve_dice_value` (couches 5-7) |
| `test_fight_attack_sequence.py` | 10 | `_execute_fight_attack_sequence` — to_hit, to_wound, save, dégâts, kill, logs, dés fixés |
| `test_reactive_move.py` | 18 | `maybe_resolve_reactive_move` : déclenchement, distance 9 hexes, reentrance, cleanup, logs |
| `test_phase_start.py` | 18 | `movement_phase_start`, `shooting_phase_start`, `fight_phase_start` — phase, cache, pools |
| `test_phase_transitions.py` | 14 | Transitions end-to-end move→shoot→fight : phase_start, BFS, attack sequence, kill |
| `test_reward_calculator.py` | 23 | `_calculate_wound_target`, `_calculate_expected_damage`, `_determine_winner` |
| `test_action_decoder.py` | 54 | `normalize_action_input`, `validate_action_against_mask`, `convert_gym_action` (5 phases + fight sub-phases), edge cases |
| `test_observation_builder.py` | 22 | `ObservationBuilder.__init__`, wound_target, expected_damage, favorite_target |
| `test_engine_turn_loop.py` | 32 | `W40KEngine._check_game_over`, `_advance_to_next_player`, `GameStateManager.determine_winner` |
| `test_los_cache_invalidation.py` | 7 | `_invalidate_los_cache_for_moved_unit` — invalidation sélective/totale |
| `test_combat_utils*.py` | 16 | Coordonnées, dés, voisins, LoS cachée |
| `test_shared_utils*.py` | 12 | Cache unités, HP, positions |
| `test_generic_handlers.py` | 6 | `end_activation` — tracking, step, logs |
| `test_spatial_relations.py` | 5 | Relations spatiales entre empreintes |
| Autres | ~28 | Armes, polygones, replay, hex union |
| `tests/unit/services/test_api_endpoints.py` | 22 | Flask endpoints : `/api/game/state`, `/api/game/action`, `/api/health`, `/api/game/reset`, racine |
| `tests/unit/engine/test_execute_semantic_action.py` | 13 | Flux e2e `execute_semantic_action` : skip, move valide/invalide, advance_phase (cascade), phase inconnue, game_over, action inconnue |
| `tests/unit/engine/test_cross_phase_cascade.py` | 15 | Cascade inter-phases : mort en fight/shoot retire des pools croisés, units_fled/advanced exclus de charge et tir |
| `tests/unit/engine/test_engine_init.py` | 9 | `W40KEngine.__init__` : échecs sans controlled_agent / rewards_config / board / objectives ; succès config minimale |
| `tests/unit/services/test_api_integration.py` | 14 | API Flask flux réel (engine semi-réel, sans mock execute_semantic_action ni _game_state_for_json) : sérialisation JSON, champs requis, no set leak |

#### Couverture par couche

| Couche | Périmètre | État |
|--------|-----------|------|
| 0 — Géométrie / hex | hex_utils, spatial_relations, polygones | ✅ solide |
| 1 — units_cache / shared | build_units_cache, HP, positions | ✅ solide |
| 2 — Éligibilité | move, charge, shoot, fight | ✅ solide |
| 3 — Pools d'activation | move, shoot, fight, charge | ✅ solide |
| 4 — BFS destinations / target pools | move, fight, shoot, charge, focus fire | ✅ solide |
| 5 — Exécution action | move, fight, shoot (primitives), socles non ronds | ✅ OK |
| 6 — Résolution dés | `resolve_dice_value` + expected_value | ✅ OK |
| 7 — Transitions / cascade mort | retrait pools, enemy_adjacent_hexes | ✅ OK |
| 8 — Séquences d'attaque end-to-end | `_execute_fight_attack_sequence`, `_attack_sequence_rng` | ✅ OK |
| 8b — Règles spéciales | DEVASTATING_WOUNDS, HAZARDOUS | ✅ OK |
| 9 — Initialisation de phase | `movement/shooting/fight/charge_phase_start` | ✅ OK |
| 10 — IA / Observations | `RewardCalculator`, `ActionDecoder`, `ObservationBuilder` | ✅ OK |
| 11 — Boucle tour / fin de partie | `_check_game_over`, `_advance_to_next_player`, `determine_winner` | ✅ OK |
| 12 — Mouvement réactif | `maybe_resolve_reactive_move` | ✅ OK |
| 13 — API Flask | endpoints REST `/api/game/*` | ✅ OK |
| 14 — Flux e2e `execute_semantic_action` | skip, move, advance_phase, phase inconnue, game_over | ✅ OK |
| 15 — Cascade inter-phases | mort→pools, fled/advanced exclusions | ✅ OK |
| 16 — Init W40KEngine réel | échecs config, succès config minimale | ✅ OK |
| 17 — API intégration (flux réel) | sérialisation JSON sans set leak, champs requis | ✅ OK |

### Frontend — `frontend/src/utils/`

**68 tests**

| Fichier | Tests | Ce qui est couvert |
|---|---|---|
| `blinkingHPBar.test.ts` | 16 | `buildChargeMinRollOverlay`, `buildWeaponSignature`, `calculateWoundProbability`, `calculateDamagePerAttack`, z-index |
| `movePoolRefsSync.test.ts` | 15 | `addHexKeysToSet` (formats array/objet/string), `syncMoveDestinationPoolRefs` |
| `activationClickTarget.test.ts` | 11 | Cibles de clic d'activation |
| `gameHelpers.test.ts` | 6 | Helpers généraux de jeu |
| `hexUnionBoundaryPolygon.test.ts` | 5 | Polygones d'union hex |
| `polygonSmooth.test.ts` | 5 | Lissage de polygones |
| `weaponHelpers.test.ts` | 4 | Sélection et parsing d'armes |
| `replayParser.test.ts` | 3 | Parsing de replays |
| `pointInPolygon.test.ts` | 2 | Point-dans-polygone |
| `losPreviewHelpers.test.ts` | 1 | Preview LoS |

---

## Conventions

### Principes non négociables

- Test = déterministe, rapide, isolé, explicite.
- Aucune dépendance externe réelle (réseau, DB, I/O lourd).
- Aucun fallback pour faire passer un test.
- Tout bugfix inclut un test de non-régression.
- Toute logique critique nouvelle arrive avec tests associés.

### Contrat d'erreurs

`require_key()` lève `ConfigurationError`, pas `KeyError`.  
Toujours vérifier le **type** d'exception et un fragment de message stable :

```python
from shared.data_validation import ConfigurationError

with pytest.raises(ConfigurationError, match=r"Required key 'MOVE'"):
    require_key({}, "MOVE")
```

### Nommage

- Fichier : `test_<module>.py`
- Fonction : `test_<comportement>_<condition>_<résultat>`

---

## Ajouter un test Python

### Pattern `game_state` minimal

```python
from engine.phase_handlers.shared_utils import build_units_cache, build_enemy_adjacent_hexes

def _make_game_state(units, current_player=1):
    gs = {
        "config": {"game_rules": {"engagement_zone": 1, "max_base_size_hex": 35},
                   "board": {"default": {"hex_radius": 1.0, "margin": 0.0}}},
        "board_cols": 25, "board_rows": 21,
        "current_player": current_player,
        "phase": "move",
        "wall_hexes": set(),
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
        "console_logs": [],
    }
    build_units_cache(gs)
    build_enemy_adjacent_hexes(gs, current_player)
    return gs
```

### Fonctions avec dépendances complexes (LoS, BFS)

Utiliser `monkeypatch` pour isoler les filtres :

```python
def test_unit_fled_excluded(monkeypatch):
    monkeypatch.setattr(
        "engine.phase_handlers.charge_handlers._has_valid_charge_target",
        lambda gs, unit, occupied=None: True,
    )
    # ... tester uniquement le filtre units_fled
```

---

## Ajouter un test Frontend

Les fonctions testables sont les **fonctions pures** (pas de PIXI, pas de React state).

```ts
import { describe, expect, it } from "vitest";
import { maFonction } from "./monModule";

describe("maFonction", () => {
  it("retourne X dans le cas nominal", () => {
    expect(maFonction(input)).toBe(expected);
  });
});
```

Vérifier : `npx vitest run src/utils/<module>.test.ts`

---

## CI

```yaml
# Python
pytest tests/unit/ -q
pytest tests/unit/engine/ -q --cov=engine --cov-fail-under=70
pytest tests/unit/shared/ -q --cov=shared --cov-fail-under=80

# Frontend
npm --prefix frontend run test:run
```

---

## Definition of Done

Une PR n'est pas complète si :

- Un changement métier critique n'a pas de test associé
- Un bugfix n'a pas de test de non-régression
- Des tests sont rouges en local
- Une exception attendue n'est pas vérifiée (type + message)

Checklist :
- [ ] Cas nominal couvert
- [ ] Cas d'erreur métier couvert
- [ ] Assertions explicites et lisibles
- [ ] Pas de dépendance externe réelle
- [ ] Test de non-régression présent si bugfix

---

## Périmètre non couvert

### Lacunes résiduelles (risque modéré)

| Comportement | Prochaine étape |
|---|---|
| Ghost / LoS preview (UnitRenderer.tsx) | Composant PIXI — test E2E Playwright |
| Tests UI de bout en bout | Playwright sur les parcours critiques |
| Init W40KEngine avec config réelle complète | Trop coûteux en fichiers ; mocké partiellement dans test_engine_init.py (limite documentée) |
| Action `shoot` e2e via execute_semantic_action | Exercé indirectement via attack_sequence ; flux complet API non exercé |
