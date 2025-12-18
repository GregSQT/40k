# ADVANCE ACTION - Implementation Plan

## Overview

**Feature**: Add "Advance" action to Shooting Phase  
**Status**: Planning  
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

### Phase 1: Backend - Engine Core

- [ ] **1.1** Add `units_advanced` tracking set to `game_state.py`
  - File: `engine/game_state.py`
  - Add to reset logic at start of movement phase

- [ ] **1.2** Add `ADVANCE` action type to action definitions
  - File: `config/action_definitions.json`
  - Define action structure with destination parameter

- [ ] **1.3** Update Shooting Phase eligibility logic
  - File: `engine/phase_handlers/shooting_phase.py` (or equivalent)
  - Change: Unit eligible if CAN_SHOOT OR CAN_ADVANCE (not just CAN_SHOOT)
  - CAN_ADVANCE = alive AND not fled AND not adjacent to enemy

- [ ] **1.4** Implement advance action execution
  - Roll 1D6 for advance_range
  - Build valid destinations using BFS (same as movement)
  - Execute move if destination valid
  - Mark unit in `units_advanced` ONLY if unit actually moved

- [ ] **1.5** Update Charge Phase eligibility
  - File: `engine/phase_handlers/charge_phase.py` (or equivalent)
  - Add check: `units_advanced.includes(unit.id)` → ineligible

### Phase 2: Backend - AI/Observation

- [ ] **2.1** Update action mask for shooting phase
  - File: `engine/observation_builder.py` (or equivalent)
  - Add advance action to valid actions mask
  - Advance should be valid for all non-fled, non-adjacent units

- [ ] **2.2** Update observation space
  - Add `can_advance` flag to unit observations (if needed)
  - Add `has_advanced` flag to track state

- [ ] **2.3** Update action decoder
  - File: `engine/action_decoder.py`
  - Add ADVANCE action type decoding
  - Handle advance_destination parameter

### Phase 3: Backend - Assault Weapon Rule

- [ ] **3.1** Add "Assault" weapon rule to config
  - File: `config/weapon_rules.json`
  - Define Assault rule that allows shooting after advance

- [ ] **3.2** Implement Assault rule check
  - After advance, if weapon has Assault rule → unit can still shoot
  - Modify shooting eligibility to check: `not advanced OR has_assault_weapon`

### Phase 4: Frontend - UI Components

- [ ] **4.1** Add Advance logo/button component
  - Display above unit icon when unit activated in shooting phase
  - Always visible (not dependent on CAN_SHOOT)

- [ ] **4.2** Implement advance click handler
  - On logo click: Roll 1D6, display result in bottom-right square
  - Point of no return: cannot cancel after clicking logo

- [ ] **4.3** Update hex highlighting
  - Show valid advance destinations in **orange**
  - File: likely `frontend/src/components/Board.tsx` or similar

- [ ] **4.4** Handle advance destination selection
  - Left click on valid hex → move unit
  - Right/Left click on unit → stay in place (no advance marking)

### Phase 5: Frontend - State Management

- [ ] **5.1** Add advance state to game state
  - `advanceRange`: number (1D6 result)
  - `advancingUnit`: unit ID currently in advance mode
  - `hasAdvanced`: boolean per unit

- [ ] **5.2** Update shooting phase UI flow
  - Detect advance mode vs shoot mode
  - Handle state transitions correctly

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

ADVANCE FLOW:
├── Click ADVANCE logo → ⚠️ POINT OF NO RETURN
├── Roll 1D6 → advance_range
├── Display advance_range on unit icon
├── Build valid_advance_destinations (BFS, advance_range)
├── Highlight destinations in ORANGE
│
├── Click valid hex → Move unit
│   ├── Unit actually moved?
│   │   ├── YES → Mark units_advanced, end_activation(ACTION, 1, ADVANCED, SHOOTING)
│   │   └── NO → end_activation without marking (unit didn't advance)
│
└── Click unit / Right-click → Stay in place
    └── end_activation without marking (unit didn't advance)

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
- **Irreversibility**: Once advance logo clicked, unit cannot shoot (unless Assault)
