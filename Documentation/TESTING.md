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

### Python — `tests/unit/engine/`

**201 tests, ~0.35s**

| Fichier | Tests | Ce qui est couvert |
|---|---|---|
| `test_hex_utils.py` | 89 | LoS (`compute_los_visibility`, `compute_los_state`), voisins hex, distances, pathfinding |
| `test_movement_pool_build.py` | 7 | `movement_build_valid_destinations_pool`, `_movement_engagement_violates` |
| `test_move_eligibility.py` | 12 | `get_eligible_units` (move), activation pool, `movement_preview`, `movement_clear_preview` |
| `test_charge_eligibility.py` | 9 | `get_eligible_units` (charge) — filtres player/EZ/fled/cannot_charge/advanced/no-target |
| `test_shooting_activation_pool.py` | 7 | `shooting_build_activation_pool` — filtres player/HP_CUR/no-targets |
| `test_fight_activation_pools.py` | 9 | `fight_build_activation_pools` — pools charging/alternating, `units_fought` |
| `test_los_cache_invalidation.py` | 7 | `_invalidate_los_cache_for_moved_unit` — invalidation sélective/totale |
| `test_combat_utils*.py` | 16 | Coordonnées, dés, voisins, LoS cachée |
| `test_shared_utils*.py` | 12 | Cache unités, HP, positions |
| `test_generic_handlers.py` | 6 | `end_activation` — tracking, step, logs |
| `test_spatial_relations.py` | 5 | Relations spatiales entre empreintes |
| Autres | 22 | Armes, polygones, replay, focus fire |

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

| Comportement | Prochaine étape |
|---|---|
| Ghost / LoS preview (UnitRenderer.tsx) | Composant PIXI — test E2E Playwright |
| Endpoints Flask (`/api/game/action`) | Tests API dans `tests/unit/services/` |
| Transitions de phase (move→shoot→charge→fight) | Test d'intégration avec W40KEngine complet |
| Tests UI de bout en bout | Playwright sur les parcours critiques |
