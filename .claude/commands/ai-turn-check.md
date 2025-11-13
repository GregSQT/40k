# AI_TURN.md Compliance Verification

Before implementing any phase handler changes, verify compliance with AI_TURN.md:

## Core Principles Checklist

### ✅ Field Access Rules
- [ ] Using direct field access with explicit validation?
- [ ] NO `.get()` with default values hiding missing fields?
- [ ] Raising KeyError when required fields are missing?
- [ ] Field existence checked with `if "field" in dict:` when truly optional?

**Example CORRECT**:
```python
if "unitId" not in action:
    raise KeyError(f"Action missing required 'unitId' field: {action}")
unit_id = action["unitId"]
```

**Example WRONG**:
```python
unit_id = action.get("unitId", None)  # ❌ Hides missing field
```

### ✅ Handler Function Structure
- [ ] Functions are pure and stateless?
- [ ] No class wrappers or instance variables?
- [ ] Return tuple: `(success: bool, result: dict)`?
- [ ] All state stored in game_state dict only?

### ✅ Phase Transition Rules
- [ ] Transitions are phase-based (move → shoot → fight → morale)?
- [ ] NO step-based counters or state machines?
- [ ] Pool exhaustion triggers phase completion?
- [ ] Using eligibility checks, not step counts?

### ✅ Unit Processing Rules
- [ ] Processing ONE unit per action call?
- [ ] NO loops over multiple units in handler?
- [ ] Activation pool managed by eligibility rules?
- [ ] Unit removed from pool after completing action?

### ✅ Game State Access
- [ ] Reading from game_state dict, not copying?
- [ ] Modifying game_state in place?
- [ ] Using game_state for inter-phase communication?
- [ ] NO separate state objects or wrappers?

## Phase-Specific Checks

### Movement Phase
- [ ] Movement builds destinations via BFS pathfinding?
- [ ] Validates against enemy adjacency (can't move TO adjacent hexes)?
- [ ] Detects flee (was adjacent before move)?
- [ ] Removes unit from move_activation_pool after action?

### Shooting Phase
- [ ] Target validation before each shot?
- [ ] Line-of-sight and range checks?
- [ ] Continues until no valid targets (auto-loop)?
- [ ] Removes unit from shoot_activation_pool after all shots?

### Fight Phase
- [ ] Melee range check (CC_RNG)?
- [ ] Defender strikes back on same action?
- [ ] Both attacker and defender removed from fight_activation_pool?

## If ANY Check Fails
STOP and read the relevant AI_TURN.md section before proceeding.

The specification in AI_TURN.md is LAW - implementation must match exactly.