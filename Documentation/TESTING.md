# Testing

## Lancer les tests

```bash
# Python — tous les tests (depuis la racine)
source .venv/bin/activate
pytest tests/unit/ -q -n 8 --dist worksteal

# Python — engine uniquement
pytest tests/unit/engine/ -q -n 8 --dist worksteal

# Frontend (depuis frontend/)
npx vitest run
```

### Pourquoi `--dist worksteal` (mesuré 2026-07-26)

`--dist load` (défaut de `pytest-xdist`) envoie à chaque worker un **gros lot initial pris dans
l'ordre de collecte**. Les fichiers lourds étant voisins dans l'ordre alphabétique, ils atterrissent
sur le **même** worker : il finit seul pendant que les sept autres dorment, et la barre de
progression stagne dans les derniers pourcents. `worksteal` (xdist ≥ 3.2, 3.8 installé) rééquilibre
en cours de route — un worker inactif vole du travail à un worker chargé.

Mesure sur les 18 fichiers les plus lourds, même machine (8 cœurs) :

| Commande | Mur | `user` (CPU réellement occupé) |
|---|---|---|
| `-n 8` (`load` par défaut) | 3 min 10 | 4 min 22 → ~1,4 cœur en moyenne |
| `-n 8 --dist worksteal` | **1 min 34** | 5 min 13 |
| `-n 12 --dist worksteal` | 1 min 40 | 5 min 42 |

`-n 12` ne paie pas : la machine a 8 cœurs, l'oversubscription coûte plus qu'elle ne comble.

### Les deux tests les plus lourds

Ils dominent le mur de la suite : ce sont eux qui fixent le plancher, aucun découpage xdist ne peut
les fractionner.

| Test | Ce qu'il vérifie | Coût |
|---|---|---|
| `test_move_mask_is_executable` (×3 seeds) | invariant « masque ⊆ exécutable » sur de vraies parties, 400 steps | ~36 s / seed |
| `test_deployment_clearance_parity::test_deployment_mask_mirrors_commit_overlap_predicate` | parité masque/commit du déploiement | ~20 s |

Ils étaient respectivement à **687 s** et **31 s** avant l'optimisation du 2026-07-26
(cf. `Implémentation/V11_move_build_acceleration.md` §3.2). Ne pas les alléger en réduisant
`MAX_STEPS` ou le nombre de seeds : à ce coût-là, la couverture d'invariant vaut plus que les
secondes gagnées.

---

## État actuel

### Python — `tests/unit/engine/` + `tests/unit/services/`

**⚠️ Chiffre périmé : « 990 tests, ~2.2s » (2 skipped).** L'inventaire ci-dessous n'a pas suivi la
croissance de la suite. Ordre de grandeur réel (2026-07-26) : **150 fichiers, ~1 550 fonctions `test_`
avant expansion des `parametrize`**. Le total collecté et le mur exacts sont à relever sur la commande
de vérification complète (§ Lancer les tests) — ils ne sont pas re-postés ici tant qu'ils ne sont pas
mesurés sur la suite entière.

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
| `tests/unit/ai/test_step_log_weapon_rule_tokens.py` | 10 | **Chaîne moteur → step.log → analyzer** pour [DEVASTATING WOUNDS], [HEAVY] et [RAPID FIRE] : le maillon de jonction que rien ne testait (V11 §0hist.38) |
| `tests/unit/ai/test_analyzer_no_heavy_after_move_false_positive.py` | 3 | L'analyzer n'invente plus d'usage invalide de [HEAVY] après un déplacement ≤ 3" |
| `test_shoot_attack_sequence.py` | 13 | Séquence de tir BOUT-EN-BOUT sur le chemin vif (`build_manual_shoot_allocation`) — les 4 issues, AP, invulnérable, 05.01/05.04 sur seuil 1, **[ANTI-X] au tir** (câblage couvert par rien avant), jusqu'aux PV retirés |
| `test_fight_special_rules.py` | 6 | `[HAZARDOUS]` 24.15 en MÊLÉE (`build_manual_fight_allocation`) — clause « or selected to fight », 1 jet par arme, 06.03 (1-2 → 1 MW, 3 si tout MONSTER/VEHICLE) |
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
| `test_engine_turn_loop.py` | 24 | `W40KEngine._check_game_over`, `GameStateManager.determine_winner` (les 8 tests de `_advance_to_next_player` ont été supprimés avec la méthode, code mort — cf. V11 §0.4) |
| `test_los_cache_invalidation.py` | 7 | `_invalidate_los_cache_for_moved_unit` — invalidation sélective/totale |
| `test_combat_utils*.py` | 16 | Coordonnées, dés, voisins, LoS cachée |
| `test_shared_utils*.py` | 12 | Cache unités, HP, positions |
| `test_generic_handlers.py` | 6 | `end_activation` — tracking, step, logs |
| `test_spatial_relations.py` | 5 | Relations spatiales entre empreintes |
| Autres | ~28 | Armes, polygones, replay, hex union |
| `tests/unit/services/test_api_endpoints.py` | 22 | Flask endpoints : `/api/game/state`, `/api/game/action`, `/api/health`, `/api/game/reset`, racine |
| `tests/unit/engine/test_execute_semantic_action.py` | 19 | Flux e2e `execute_semantic_action` : skip, move valide/invalide, advance_phase (cascade), phase inconnue, game_over, action inconnue + routing shoot/fight |
| `tests/unit/engine/test_cross_phase_cascade.py` | 15 | Cascade inter-phases : mort en fight/shoot retire des pools croisés, units_fled/advanced exclus de charge et tir |
| `tests/unit/engine/test_cascade_fight_subphases.py` | 9 | Cascade charge→fight : fight vide, unités adjacentes, sous-phases charging/alternating, player switch, pools nettoyés |
| `tests/unit/engine/test_engine_init.py` | 9 | `W40KEngine.__init__` : échecs sans controlled_agent / rewards_config / board / objectives ; succès config minimale |
| `tests/unit/engine/test_engine_reset.py` | 18 | `W40KEngine.reset()` : turn=1, game_over=False, tracking sets vidés, HP/positions restaurés, units_cache reconstruit, episode_number incrémenté |
| `tests/unit/engine/test_special_rules_e2e.py` | 8 | Règles spéciales de tir en INTERACTION, bout-en-bout sur le vif : DEVASTATING × HAZARDOUS, HEAVY × DEVASTATING, arme nue |
| `tests/unit/services/test_api_integration.py` | 14 | API Flask flux réel (engine semi-réel, sans mock execute_semantic_action ni _game_state_for_json) : sérialisation JSON, champs requis, no set leak |
| `tests/unit/engine/test_engine_step.py` | 13 | `W40KEngine.step()` : signature tuple×5, types obs/reward/terminated/truncated/info, turn_limit→terminated, pool vide→phase auto-advance |
| `tests/unit/engine/test_game_state_contract.py` | 28 | Contrat game_state produit par `__init__` réel : clés scalaires, tracking sets, pools, structures complexes (units_cache après reset) |
| `tests/unit/engine/test_objective_scoring.py` | 11 | `apply_primary_objective_scoring` : guard clauses, VP par condition (control_at_least_one/two, control_more_than_opponent), cap max_points, round5 phase spéciale, liste multi-objectifs |
| `tests/unit/engine/test_unit_rules_shoot.py` | 7 | UNIT_RULES × WEAPON_RULES sur le même dé (01 Core « Re-rolls ») : abilité + [TWIN-LINKED] ne relancent jamais deux fois ; portée des abilités `to wound` |
| `tests/unit/engine/test_activation_e2e.py` | 9 | Activation e2e via `execute_semantic_action` : routing pool, skip, game_over, tir→HP réduit, mort→units_cache cleanup, pool cleanup, units_shot, all_attack_results |

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
| 8 — Séquences d'attaque end-to-end | `_execute_fight_attack_sequence`, `attack_sequence.roll_attack_pool` (socle tir+mêlée) | ✅ OK |
| 8b — Règles spéciales | DEVASTATING_WOUNDS, HAZARDOUS | ✅ OK |
| 9 — Initialisation de phase | `movement/shooting/fight/charge_phase_start` | ✅ OK |
| 10 — IA / Observations | `RewardCalculator`, `ActionDecoder`, `ObservationBuilder` | ✅ OK |
| 11 — Boucle tour / fin de partie | `_check_game_over`, `determine_winner` ; la progression de tour réelle est en fin de phase Fight (`fight_handlers`, deux chemins) | ✅ OK |
| 12 — Mouvement réactif | `maybe_resolve_reactive_move` | ✅ OK |
| 13 — API Flask | endpoints REST `/api/game/*` | ✅ OK |
| 14 — Flux e2e `execute_semantic_action` | skip, move, advance_phase, routing shoot/fight, game_over | ✅ OK |
| 15 — Cascade inter-phases | mort→pools, fled/advanced exclusions | ✅ OK |
| 15b — Cascade charge→fight | sous-phases charging/alternating, player switch, fight vide | ✅ OK |
| 16 — Init W40KEngine réel | échecs config, succès config minimale | ✅ OK |
| 16b — Reset W40KEngine | turn/game_over/pools/HP/positions restaurés entre épisodes | ✅ OK |
| 17 — API intégration (flux réel) | sérialisation JSON sans set leak, champs requis | ✅ OK |
| 18 — Règles spéciales tir | DEVASTATING_WOUNDS, HAZARDOUS, HEAVY — résultats et flags | ✅ OK |
| 19 — step() gym interface | reset→step×N→game_over, turn_limit, phase auto-advance, tuple×5 | ✅ OK |
| 20 — Contrat game_state | clés critiques produites par `__init__` réel, types vérifiés | ✅ OK |
| 21 — Scoring objectifs primaires | VP par condition, cap, round5, déduplication, liste multi-obj | ✅ OK |
| 22 — UNIT_RULES dynamiques (tir) | reroll_1_towound, reroll_towound_on_obj, closest_target_penetration | ✅ OK |
| 23 — Activation e2e complète | tir→HP→mort→cleanup pool via execute_semantic_action | ✅ OK |

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
| Déploiement phase (`deployment_handlers`) | Trop couplé au scénario complet — exclure du périmètre unitaire |
| PvEController / chemin IA (modèle chargé) | Hors périmètre tests unitaires |
| `_reload_scenario` / `_configure_deployment_random_mix_for_episode` | Dépendances fichier lourd — exclure du périmètre unitaire |
| Rewards multi-agents (RewardMapper, phase suffixes) | Couvert partiellement via reward_calculator ; flux multi-agents non exercé |
