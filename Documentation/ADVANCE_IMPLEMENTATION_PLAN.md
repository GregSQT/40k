# ADVANCE ACTION - Implementation Plan

## Overview

**Feature**: Add "Advance" action to Shooting Phase  
**Status**: Phase 1 ✅ TERMINÉE  
**Created**: 2025-12-18

---

## Summary of Rules

| Aspect | Rule |
|--------|------|
| **Phase** | Shooting Phase |
| **Distance** | 1D6 hexes |
| **Pathfinding** | Same as Movement (BFS, no walls, no enemy-adjacent) |
| **Post-Advance Shooting** | ❌ Forbidden (unless weapon has "Assault" rule) |
| **Post-Advance Charge** | ❌ Forbidden (unless special rule) |
| **Considered "Advanced"** | Only if unit actually moved (not if stayed in place) |
| **Hex Highlight Color** | Orange |

---

## Implementation Checklist

### Phase 1: Backend - Engine Core ✅ TERMINÉE

- [x] **1.1** Add `units_advanced` tracking set to `game_state.py` ✅
  - File: `engine/phase_handlers/movement_handlers.py` (ligne 27)
  - Reset dans `movement_phase_start()`

- [x] **1.2** Add `ADVANCE` action type to action definitions ✅
  - File: `config/action_definitions.json`
  - Action "4" = Advance (phase: shoot, type: movement)

- [x] **1.3** Update Shooting Phase eligibility logic ✅
  - File: `engine/phase_handlers/shooting_handlers.py`
  - Unit eligible if CAN_SHOOT OR CAN_ADVANCE

- [x] **1.4** Implement advance action execution ✅
  - File: `engine/phase_handlers/shooting_handlers.py`
  - `_handle_advance_action()` implémenté

- [x] **1.5** Update Charge Phase eligibility ✅
  - File: `engine/phase_handlers/charge_handlers.py` (ligne 86-88)
  - `units_advanced.includes(unit.id)` → ineligible

### Phase 2: Backend - AI/Observation ✅ TERMINÉE

- [x] **2.1** Update action decoder ✅
  - File: `engine/action_decoder.py`
  - Action space élargi de 12 à 13 actions (action 12 = ADVANCE)
  - `get_action_mask()`: mask[12] activé en shooting phase si unit peut advance
  - `convert_gym_action()`: gère action_int == 12 pour advance

- [x] **2.2** Update observation space ✅
  - File: `engine/observation_builder.py`
  - Ajouté `has_advanced` (obs[8]) dans Global Context
  - ⚠️ **BREAKING CHANGE**: obs_size passe de 313 à 314 floats
  - Tous les indices décalés de 1 à partir de obs[8]

- [x] **2.3** Update reward mapper ✅
  - File: `ai/reward_mapper.py`
  - Ajouté `get_advance_reward()` méthode
  - Récompense tactique pour avancement (moved_closer, moved_to_cover)

### Phase 3: Backend - Assault Weapon Rule ✅ TERMINÉE

- [x] **3.1** Add "Assault" weapon rule to config ✅
  - File: `config/weapon_rules.json`
  - Define Assault rule that allows shooting after advance
  - ⚠️ **Existait déjà dans weapon_rules.json**

- [x] **3.2** Implement Assault rule check ✅
  - After advance, if weapon has Assault rule → unit can still shoot
  - Modify shooting eligibility to check: `not advanced OR has_assault_weapon`
  - **Fichiers modifiés:**
    - `frontend/src/types/game.ts`: Ajout `rules?: string[]` au type Weapon
    - `frontend/src/roster/spaceMarine/armory.ts`: Ajout `rules: ["ASSAULT"]` au bolt_rifle
    - `engine/phase_handlers/shooting_handlers.py`: 
      - Ajout `_weapon_has_assault_rule()` helper
      - Modification `_has_valid_shooting_targets()` pour vérifier ASSAULT après advance

### Phase 4: Frontend - UI Components ✅ TERMINÉE

- [x] **4.1** Add Advance logo/button component ✅
  - File: `frontend/src/components/UnitRenderer.tsx`
  - Props `canAdvance` et `onAdvance` passés à renderUnit()
  - File: `frontend/src/components/BoardPvp.tsx` (lignes ~850-853)

- [x] **4.2** Implement advance click handler ✅
  - File: `frontend/src/components/BoardPvp.tsx`
  - Événement `boardAdvanceClick` émis par UnitRenderer
  - Listener ajouté dans BoardPvp.tsx après setupBoardClickHandler

- [x] **4.3** Update hex highlighting ✅
  - File: `frontend/src/components/BoardDisplay.tsx`
  - Interface `DrawBoardOptions` inclut `advanceCells`
  - Couleur orange (0xFF8C00, alpha 0.5) pour les destinations advance
  - `isAdvanceDestination` détecté et rendu dans shooting phase

- [x] **4.4** Handle advance destination selection ✅
  - File: `frontend/src/utils/boardClickHandler.ts`
  - Callback `onAdvanceMove` ajouté à l'interface
  - Mode `advancePreview` géré dans globalHexClickHandler

### Phase 5: Frontend - State Management ✅ TERMINÉE

- [x] **5.1** Add advance state to game state ✅
  - File: `frontend/src/hooks/useEngineAPI.ts` (lignes ~103-106)
  - `advanceDestinations`: Array<{col, row}>
  - `advancingUnitId`: number | null
  - `advanceRoll`: number | null (résultat 1D6)

- [x] **5.2** Update shooting phase UI flow ✅
  - File: `frontend/src/hooks/useEngineAPI.ts`
  - Handler `handleAdvance()` implémenté (lignes ~538-549)
  - Réponse backend `advance_destinations` / `advance_roll` gérée (lignes ~330-340)
  - Mode `advancePreview` activé automatiquement
  - Export des états et handler dans returnObject

- [x] **5.3** Implement advance warning popup ✅
  - File: `frontend/src/hooks/useEngineAPI.ts`
  - State `advanceWarningPopup` avec unitId et timestamp
  - Handlers: `handleConfirmAdvanceWarning()`, `handleSkipAdvanceWarning()`, `handleCancelAdvanceWarning()`
  - Popup affiché automatiquement quand unité activée sans cibles (allow_advance signal)
  - File: `frontend/src/components/BoardPvp.tsx`
  - Rendering PIXI.js du popup avec 3 boutons: "Confirm" (green), "Skip" (grey), "Cancel" (red)
  - Message d'avertissement: "Making an advance move won't allow you to shoot or charge in this turn."
  - File: `frontend/src/components/UnitRenderer.tsx`
  - Badge d'affichage du roll d'advance (green badge, bottom-right) après exécution

- [x] **5.4** Advance roll badge display ✅
  - File: `frontend/src/components/UnitRenderer.tsx`
  - Méthode `renderAdvanceRollBadge()` similaire à `renderChargeRollBadge()`
  - Badge vert affiché après exécution réussie de l'advance
  - Props `advanceRoll` et `advancingUnitId` ajoutés

### Phase 6: Documentation & Config

- [ ] **6.1** Update AI_TURN.md with new decision tree
  - Add advance action to shooting phase
  - Document all rules and interactions

- [ ] **6.2** Update any relevant config files
  - Ensure advance constants are in config (not hardcoded)

### Phase 7: Testing

- [ ] **7.1** Unit tests for advance eligibility
- [ ] **7.2** Unit tests for advance execution
- [ ] **7.3** Unit tests for charge phase blocking after advance
- [ ] **7.4** Unit tests for Assault weapon exception
- [ ] **7.5** Integration test: full advance flow
- [ ] **7.6** Integration test: advance + Assault weapon shooting

---

## Decision Tree Reference

```javascript
SHOOTING PHASE (with ADVANCE)

ELIGIBILITY:
├── unit.HP_CUR > 0?
├── unit.player === current_player?
├── units_fled.includes(unit.id)? → ❌ if YES
├── Adjacent to enemy? → ❌ if YES
├── CAN_SHOOT = has_ranged_weapon AND has_LOS_to_enemies
├── CAN_ADVANCE = true (always, if passed above checks)
└── (CAN_SHOOT OR CAN_ADVANCE)? → ✅ Add to pool

ACTIONS:
├── shoot (if CAN_SHOOT)
├── advance (always available)
└── wait

ADVANCE FLOW (Human Players):
├── Unit activated in shoot phase with NO valid targets
│   ├── Backend returns: {allow_advance: true, no_targets: true}
│   │
│   └── Frontend displays WARNING POPUP:
│       ├── Message: "Making an advance move won't allow you to shoot or charge in this turn."
│       │
│       └── Three buttons:
│           │
│           ├── "Confirm" (green) → Execute advance:
│           │  ├── Clear popup and shooting preview
│           │  ├── Send advance action (no destination)
│           │  ├── Backend rolls 1D6 → advance_range
│           │  ├── Backend calculates valid_advance_destinations (BFS, advance_range)
│           │  ├── Display advance_range badge on unit icon
│           │  ├── Highlight destinations in ORANGE
│           │  │
│           │  └── Click valid hex → Move unit:
│           │     ├── Unit actually moved?
│           │     │   ├── YES → Mark units_advanced, end_activation(ACTION, 1, ADVANCED, SHOOTING)
│           │     │   └── NO → end_activation without marking
│           │
│           ├── "Skip" (grey) → Skip unit activation:
│           │  └── Remove unit from shoot_activation_pool
│           │
│           └── "Cancel" (red) → Cancel selection:
│              └── Reset visual state, unit stays in pool for re-activation

POST-ADVANCE:
├── Can shoot? → ONLY if weapon has "Assault" rule
└── Can charge? → NO (unless special rule)
```

---

## Files to Modify (Estimated)

| File | Changes |
|------|---------|
| `engine/game_state.py` | Add `units_advanced` set |
| `engine/phase_handlers/shooting_phase.py` | Eligibility + advance execution |
| `engine/phase_handlers/charge_phase.py` | Block advanced units |
| `engine/action_decoder.py` | Add ADVANCE action type |
| `engine/observation_builder.py` | Update mask for advance |
| `config/action_definitions.json` | Define ADVANCE action |
| `config/weapon_rules.json` | Add Assault rule |
| `frontend/src/components/Board*.tsx` | UI for advance |
| `frontend/src/hooks/useEngineAPI.ts` | Handle advance action |
| `Documentation/AI_TURN.md` | Update decision tree |

---

## Notes

- **Color coding**: Advance hexes = Orange, Charge hexes = Violet
- **Assault rule**: Exception that allows both advance AND shoot
- **"Considered advanced"**: Only if unit actually moved to a different hex
- **Warning popup**: When unit activated without targets, popup appears with 3 options:
  - Confirm: Execute advance (point of no return)
  - Skip: Skip unit activation (removes from pool)
  - Cancel: Reset selection (unit stays in pool for re-activation)
- **Advance roll badge**: Green badge displayed at bottom-right of unit icon after advance execution (similar to charge roll badge)
