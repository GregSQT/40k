# 🚨 CLAUDE AI_TURN.md STRICT COMPLIANCE WALKTHROUGH

**MANDATORY OPENING**: "I will STRICTLY follow AI_TURN.md and project documentation. Let me search project knowledge first to understand the exact requirements."

**THEN IMMEDIATELY**: Use `project_knowledge_search` to find relevant documentation BEFORE writing any code.

---

## 🎯 CORE COMPLIANCE RULES

### **Rule #1: AI_TURN.md is ABSOLUTE LAW**
- **NEVER** deviate from AI_TURN.md specifications
- **NEVER** add "improvements" or "optimizations" not in the spec
- **NEVER** use "better" patterns that contradict AI_TURN.md
- **ALWAYS** implement exactly what AI_TURN.md describes

### **Rule #2: One Unit Per Gym Action**
```
gym_action() → ONE unit activates → unit acts → unit removed from queue → DONE
```
- **NEVER** process multiple units in one gym action
- **NEVER** implement "batch processing" of units
- **NEVER** try to "optimize" by grouping actions

### **Rule #3: Phase Completion Logic**
```
Phase ends when: NO eligible units remain for current player
NOT when: Step count reached, arbitrary conditions met, etc.
```
- **ONLY** check unit eligibility to determine phase completion
- **NEVER** use step counting for phase transitions
- **NEVER** use timers, counters, or other arbitrary limits

### **Rule #4: Step Counting Built-In (NEW)**
```
Steps increment when: Unit ATTEMPTS action (move/shoot/charge/combat/wait)
Steps DON'T increment when: Auto-skip ineligible units, phase transitions
```
- **ALWAYS** increment steps for attempted actions (success OR failure)
- **NEVER** retrofit step counting as wrapper logic
- **NEVER** count phase transitions as steps

---

## 📋 IMPLEMENTATION CHECKLIST

Before writing ANY code, Claude MUST verify these requirements:

### ✅ **Architecture Requirements**
- [ ] Single controller class (no wrappers unless explicitly requested)
- [ ] Base controller delegation (not inheritance)
- [ ] Built-in step counting (not retrofitted)
- [ ] Episode steps stored in controller.game_state (not separate tracking)
- [ ] Unit queue contains ONLY unit IDs (not full unit objects)
- [ ] Current active unit is ONE unit ID or None

### ✅ **execute_gym_action() Flow**
```python
def execute_gym_action(self, action: int):
    # 1. Get current active unit (build queue if empty)
    # 2. If no active unit, advance phase/turn
    # 3. Execute action for active unit
    # 4. Update episode_steps if real action
    # 5. Remove unit from queue
    # 6. Return gym response
```
- [ ] This EXACT flow implemented
- [ ] NO additional steps or complexity
- [ ] NO wrapper delegation chains

### ✅ **Unit Queue Management**
- [ ] Queue built fresh for each phase
- [ ] Queue contains eligible units only (AI_TURN.md rules)
- [ ] Units removed after acting (no round-robin)
- [ ] Queue empty = phase complete

### ✅ **Eligibility Rules (EXACT AI_TURN.md)**
- [ ] **Move**: `unit.player == current_player AND unit.id NOT in units_moved`
- [ ] **Shoot**: `NOT fled, NOT adjacent to enemy, has RNG_NB > 0, has valid targets`
- [ ] **Charge**: `NOT fled, NOT adjacent to enemy, has enemies within (*charge_max_distance*) range`
- [ ] **Combat**: `unit.id NOT in units_attacked AND has adjacent enemies`

### ✅ **Phase Transitions**
- [ ] Move → Shoot → Charge → Combat → End Turn
- [ ] Transitions triggered by empty eligible unit queue
- [ ] Use base controller's phase_transitions methods
- [ ] Clear queue after each transition

### ✅ **Field Naming (NEW)**
- [ ] ALL unit stats use UPPERCASE: `CUR_HP, MOVE, RNG_NB, CC_ATK, etc.`
- [ ] **NEVER** use lowercase: `cur_hp, move, rng_nb` (FORBIDDEN)
- [ ] Consistent with AI_ARCHITECTURE.md requirements

---

## 🚫 FORBIDDEN PATTERNS

Claude MUST **NEVER** implement these patterns:

### ❌ **Wrapper Complexity**
```python
# FORBIDDEN
class StepLoggingWrapper(SequentialWrapper(BaseWrapper)):
    def execute_gym_action(self, action):
        return super().super().execute_gym_action(action)
```

### ❌ **Multi-Unit Processing**
```python
# FORBIDDEN
for unit in all_eligible_units:
    self.process_unit(unit)  # This violates "one unit per gym action"
```

### ❌ **Step-Based Phase Logic**
```python
# FORBIDDEN
if self.step_count >= self.max_steps_per_phase:
    self.advance_phase()  # Phases end on unit eligibility, not steps
```

### ❌ **Retrofitted Step Counting**
```python
# FORBIDDEN
steps_before = self.episode_steps
success = self.execute_action()
if steps_before != self.episode_steps:  # Retrofitted logic
    self.log_step()
```

### ❌ **Field Naming Violations (NEW)**
```python
# FORBIDDEN
unit.get("cur_hp", 1)     # Must be CUR_HP
unit["move"]              # Must be MOVE  
unit.get("rng_nb", 0)     # Must be RNG_NB
```

---

## ✅ REQUIRED CODE PATTERNS

Claude MUST use these EXACT patterns:

### ✅ **Controller Structure**
```python
class SequentialGameController:
    def __init__(self, config, quiet=False):
        self.base = TrainingGameController(config, quiet)  # Delegation, not inheritance
        self.active_unit_queue: List[str] = []  # Just unit IDs
        self.current_active_unit_id: Optional[str] = None  # One unit or None
        # NO separate episode_steps - use self.base.game_state["episode_steps"]
```

### ✅ **Built-in Step Counting**
```python
def execute_gym_action(self, action: int):
    # ... get active unit logic ...
    
    # Execute action for active unit
    success = self._execute_action_for_unit(unit_id, action)
    
    # AI_TURN.md: Built-in step counting for real actions
    if self._is_real_action(action):  # move/shoot/charge/combat/wait
        self.base.game_state["episode_steps"] += 1
    
    # Remove unit and return response
```

### ✅ **Eligibility Checking (UPPERCASE FIELDS)**
```python
def _is_unit_eligible_for_current_phase(self, unit):
    phase = self.base.get_current_phase()
    
    # REQUIRED: Check CUR_HP exists (no defaults)
    if "CUR_HP" not in unit:
        raise KeyError(f"Unit {unit['id']} missing required CUR_HP field")
    
    if unit["CUR_HP"] <= 0:
        return False
        
    if phase == "move":
        return (unit["player"] == self.base.get_current_player() and
                unit["id"] not in self.base.game_state.get("units_moved", set()))
    
    elif phase == "shoot":
        return (unit["player"] == self.base.get_current_player() and
                unit["id"] not in self.base.game_state.get("units_shot", set()) and
                unit["id"] not in self.base.game_state.get("units_fled", set()) and
                unit.get("RNG_NB", 0) > 0 and  # Must have shooting capability
                self._has_valid_shooting_targets(unit))
    
    # ... etc for charge and combat
```

### ✅ **Queue Building**
```python
def _build_current_phase_queue(self):
    current_phase = self.base.get_current_phase()
    current_player = self.base.get_current_player()
    
    all_units = self.base.get_units()
    
    if current_phase == "combat":
        candidate_units = [u for u in all_units if u.get("CUR_HP", 0) > 0]  # Both players
    else:
        candidate_units = [u for u in all_units 
                          if u["player"] == current_player and u.get("CUR_HP", 0) > 0]  # Current player only
    
    self.active_unit_queue = []
    for unit in candidate_units:
        if self._is_unit_eligible_for_current_phase(unit):  # AI_TURN.md rules
            self.active_unit_queue.append(unit["id"])
```

---

## 🔍 VALIDATION QUESTIONS

Before submitting code, Claude MUST answer YES to ALL:

1. **Does this implement EXACTLY what AI_TURN.md describes?** YES/NO
2. **Is there only ONE unit processed per gym action?** YES/NO
3. **Do phases end based on unit eligibility only?** YES/NO
4. **Is step counting built INTO the controller (not retrofitted)?** YES/NO
5. **Are all unit fields UPPERCASE (CUR_HP, not cur_hp)?** YES/NO
6. **Is episode_steps stored in game_state (not separate)?** YES/NO
7. **Does this avoid all forbidden patterns listed above?** YES/NO
8. **Can I trace the exact flow from gym action to unit action easily?** YES/NO

**If ANY answer is NO, Claude MUST rewrite the code.**

---

## 🧪 TESTING REQUIREMENTS

Claude MUST verify this behavior:

### **Test 1: Single Unit Processing**
```python
# Start episode
obs = env.reset()

# First action should activate first eligible unit
obs, reward, done, truncated, info = env.step(action)
# Verify: exactly one unit acted, episode_steps incremented by 1

# Second action should activate second eligible unit  
obs, reward, done, truncated, info = env.step(action)
# Verify: second unit acted, first unit no longer in queue
```

### **Test 2: Step Counting Verification**
```python
initial_steps = env.controller.base.game_state["episode_steps"]

# Execute real action (move/shoot/charge/combat/wait)
obs, reward, done, truncated, info = env.step(move_action)
final_steps = env.controller.base.game_state["episode_steps"]

# Verify: steps incremented by exactly 1
assert final_steps == initial_steps + 1
```

### **Test 3: Phase Completion**
```python
# Execute actions until no eligible units remain
while phase == "move":
    obs, reward, done, truncated, info = env.step(move_action)
    phase = info["current_phase"]

# Verify: phase automatically advanced to "shoot"
assert phase == "shoot"
```

---

## 🚨 EMERGENCY COMPLIANCE CHECK

If Claude ever suggests ANY of these, **IMMEDIATELY STOP AND RESTART**:

- "Let me optimize this for better performance..."
- "We could batch process multiple units..."
- "I'll add some wrapper classes for better organization..."
- "This would be cleaner with inheritance..."
- "Let me add some additional state tracking..."
- "I'll use lowercase field names for consistency..." (FORBIDDEN)

**These suggestions violate AI_TURN.md compliance.**

---

## 📞 COMMUNICATION PROTOCOL

When Claude responds, it MUST:

1. **Start with**: "✅ AI_TURN.md COMPLIANCE VERIFIED"
2. **Confirm**: Which specific requirements from this walkthrough are being followed
3. **Provide**: Simple, direct code that matches the required patterns exactly
4. **End with**: "🎯 Implementation follows AI_TURN.md specification exactly"

**Example Response Format:**
```
✅ AI_TURN.md COMPLIANCE VERIFIED

Following requirements:
- Single unit per gym action (Rule #2)
- Built-in step counting (Rule #4)  
- Phase completion by unit eligibility (Rule #3)
- UPPERCASE field names (AI_ARCHITECTURE.md)
- Simple controller with base delegation

[CODE HERE - following required patterns exactly]

🎯 Implementation follows AI_TURN.md specification exactly
```

---

## 🏆 SUCCESS CRITERIA

Claude has succeeded when:

✅ One file implements complete sequential logic  
✅ No wrappers or complex delegation  
✅ Built-in step counting (not retrofitted)
✅ UPPERCASE field names throughout
✅ AI_TURN.md rules implemented exactly  
✅ Simple unit queue management  
✅ Phase transitions work correctly  
✅ Training can begin immediately  

**This walkthrough ensures Claude creates working, compliant code that matches your project requirements exactly.**