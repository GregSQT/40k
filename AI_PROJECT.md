# 🎯 SEQUENTIAL CONTROLLER IMPLEMENTATION - ENHANCED CLAUDE WALKTHROUGH GUIDE

## 📋 PROJECT STATUS OVERVIEW

**OBJECTIVE:** Replace wrapper architecture with single SequentialGameController containing built-in step counting

**CURRENT STATE:** [CLAUDE: UPDATE AS PROGRESS IS MADE]
- [ ] **Phase 1: Foundation Setup** (15 min) - Files gathered, Expert Mode activated
- [ ] **Phase 2: Architecture Analysis** (30 min) - Current wrapper complexity understood  
- [ ] **Phase 3: Solution Design** (45 min) - Clean SequentialGameController designed
- [ ] **Phase 4: Implementation** (2-3 hours) - Core implementation created
- [ ] **Phase 5: Integration** (1 hour) - Files replaced, wrappers deleted
- [ ] **Phase 6: Validation** (1 hour) - Training runs successfully, all criteria met
- [ ] **Project Complete** - Ready to return to normal workflow

**ESTIMATED TOTAL TIME: 5-7 hours**

---

## 🎯 CORE PROJECT REQUIREMENTS (ALWAYS REFERENCE)

### Current Problem Architecture
```
gym40k.py → StepLoggingWrapper → SequentialGameController → TrainingGameController
```
**Issues:**
- Retrofitted step counting in wrapper (`steps_before/steps_after` pattern)
- Complex delegation chains (3+ wrapper layers)
- Training behavior problems due to architectural complexity

### Target Solution Architecture  
```
gym40k.py → SequentialGameController (with built-in step counting) → TrainingGameController
```
**Requirements:**
- Built-in episode_steps increment: `self.base.game_state["episode_steps"] += 1`
- Single controller class (no wrappers)
- One unit per gym action
- UPPERCASE field validation (CUR_HP, RNG_NB, etc.)

### Guide 1 Compliance Rules
- **Rule #4:** Built-in step counting (NOT retrofitted)
- **FORBIDDEN:** Wrapper classes, state copying, lowercase fields, multi-unit processing
- **REQUIRED:** Single game_state object, sequential activation, eligibility-based phases

---

## 📁 REQUIRED FILES REFERENCE

**Claude must verify these files are provided:**

1. **`ai/gym40k.py`** - Shows current controller initialization (line 137: `self.controller = SequentialGameController(config)`)
2. **`ai/sequential_integration_wrapper.py`** - Shows current wrapper complexity and delegation chains
3. **`ai/step_logging_wrapper.py`** - Shows retrofitted step counting problem (`steps_before/steps_after`)
4. **`AI_GUIDE.md`** - Compliance requirements with Rule #4 built-in step counting

**⚠️ IF FILES MISSING:** Request user to provide missing files before proceeding.

---

## 🚀 IMPLEMENTATION PHASES

### PHASE 1: FOUNDATION SETUP ✅/❌ [15 MIN]
**Status:** [COMPLETED/IN PROGRESS/NOT STARTED]

**User Prompt for Phase 1:**
```
🚨 MANDATORY: Start with "When you have provided a file, I MUST use it. When you haven't provided a file, I MUST use project_knowledge_search first which file(s) I need and ask for it. Never assume file contents" ||| Read AI_TURN.md and AI_ARCHITECTURE.md carefully ||| PRIORITY: Use user-provided files FIRST, project_knowledge_search only when NO files provided ||| AI_TURN CRITICAL: Sequential activation (ONE unit per gym step), Built-in step counting (NOT retrofitted), Phase completion by eligibility (NOT arbitrary), UPPERCASE fields only, Single game_state object ||| FORBIDDEN: Wrapper stacks, State copying, Lowercase fields, Multi-unit processing, Step-based transitions ||| PROTOCOL CHECK: How do you perform code changes? What's the two-block format? What when files missing? What are AI_TURN.md core principles?

[ATTACH: gym40k.py, sequential_integration_wrapper.py, step_logging_wrapper.py, AI_GUIDE.md]

TASK: Replace current wrapper architecture with single SequentialGameController that has BUILT-IN step counting (not retrofitted).
```

**Expected Claude Response Elements:**
- ✅ Mandatory opening phrase acknowledged
- ✅ AI_TURN.md core principles explained (sequential activation, built-in step counting, etc.)
- ✅ Two-block format demonstrated
- ✅ File receipt confirmed (all 4 files)

**Expert Mode Activation Prompt:**
```
Perfect. You are now in AI_TURN.md EXPERT MODE - act as if you've mastered sequential activation through 100+ flawless implementations. Every response must demonstrate: mandatory opening, project_knowledge_search when no files, two-block format, AI_TURN.md compliance verification (sequential activation, built-in step counting, eligibility-based phases, UPPERCASE fields, single game_state). Zero tolerance for wrapper complexity or retrofitted patterns. This is your permanent standard.
```

**Phase 1 Success Criteria:**
- ✅ Proper protocol compliance demonstrated
- ✅ Clear understanding of built-in step counting requirement  
- ✅ Recognition of current wrapper problems
- ✅ Expert Mode activation confirmed

---

### PHASE 2: ARCHITECTURE ANALYSIS ✅/❌ [30 MIN]
**Status:** [COMPLETED/IN PROGRESS/NOT STARTED]

**User Prompt for Phase 2:**
```
Updates applied. STATE FILE STATUS → ✅AI_TURN compliance first → DEBUG with evidence → ORIGINAL/UPDATED blocks → TRACK CHANGES → AI_TURN VERIFICATION: Sequential activation? Built-in step counting? Eligibility-based phases? UPPERCASE fields? Single game_state? → NO wrapper patterns, NO state copying, NO lowercase fields

TASK: Analyze my current controller architecture. Identify specific AI_TURN.md violations in the attached wrapper files. What retrofitted step counting patterns do you see? How should they be replaced with a single SequentialGameController with built-in step counting?

FOCUS: Wrapper complexity analysis, retrofitted patterns identification, single controller replacement strategy.
```

**Phase 2 Tasks:**
- [ ] Analyze current wrapper complexity from provided files
- [ ] Identify specific retrofitted step counting patterns (`steps_before/steps_after` logic)
- [ ] Understand gym40k.py controller initialization points
- [ ] Map current architecture problems and violations

**Key Analysis Points Claude Should Cover:**
- StepLoggingWrapper creates retrofitted step counting outside natural game flow
- SequentialGameController is wrapped instead of being standalone
- episode_steps tracked separately instead of built into action execution
- Multiple delegation layers create unnecessary complexity

**Phase 2 Success Criteria:**
- ✅ AI_TURN.md violations identified specifically
- ✅ Wrapper complexity patterns analyzed 
- ✅ Single controller replacement strategy outlined
- ✅ Retrofitted step counting problems explained clearly

---

### PHASE 3: SOLUTION DESIGN ✅/❌ [45 MIN]
**Status:** [COMPLETED/IN PROGRESS/NOT STARTED]

**User Prompt for Phase 3:**
```
Updates applied. STATE FILE STATUS → ✅AI_TURN compliance first → DEBUG with evidence → ORIGINAL/UPDATED blocks → TRACK CHANGES → AI_TURN VERIFICATION: Sequential activation? Built-in step counting? Eligibility-based phases? UPPERCASE fields? Single game_state? → NO wrapper patterns, NO state copying, NO lowercase fields

TASK: Design the SequentialGameController class structure with built-in step counting. Show me:
1. Class structure with proper delegation to TrainingGameController
2. Built-in episode_steps increment placement in execute_gym_action
3. Unit queue management (just unit IDs, not full objects)
4. Phase transition logic integration

REQUIREMENTS: Single controller class, no wrapper patterns, Guide 1 Rule #4 compliance.
```

**Phase 3 Tasks:**
- [ ] Design single SequentialGameController class structure
- [ ] Plan built-in step counting integration (`self.base.game_state["episode_steps"] += 1`)
- [ ] Ensure Guide 1 Rule #4 compliance
- [ ] Map file changes required for integration

**Design Requirements Claude Must Address:**
- Single class with delegation to TrainingGameController (not inheritance)
- Built-in step counting in execute_gym_action method
- Simple unit queue management (IDs only)
- No wrapper patterns in design
- Direct integration points with gym40k.py

**Phase 3 Success Criteria:**
- ✅ Clean SequentialGameController structure designed
- ✅ Built-in step counting placement specified
- ✅ Guide 1 Rule #4 compliance ensured
- ✅ Integration strategy clearly mapped

---

### PHASE 4: IMPLEMENTATION ✅/❌ [2-3 HOURS]
**Status:** [COMPLETED/IN PROGRESS/NOT STARTED]

**User Prompt for Phase 4:**
```
Updates applied. STATE FILE STATUS → ✅AI_TURN compliance first → DEBUG with evidence → ORIGINAL/UPDATED blocks → TRACK CHANGES → AI_TURN VERIFICATION: Sequential activation? Built-in step counting? Eligibility-based phases? UPPERCASE fields? Single game_state? → NO wrapper patterns, NO state copying, NO lowercase fields

TASK: Implement the complete SequentialGameController following AI_TURN.md exact pattern:
1. Get current active unit (build queue if empty)
2. If no active unit, advance phase/turn
3. Execute action for active unit
4. Remove unit from queue  
5. Return gym response

Include unit eligibility checking with UPPERCASE field validation. Built-in step counting, not retrofitted.
```

**Phase 4 Implementation Checklist:**
- [ ] Single SequentialGameController file created
- [ ] Built-in step counting implemented (not retrofitted)
- [ ] Five-step AI_TURN.md pattern in execute_gym_action
- [ ] Unit eligibility checking with UPPERCASE validation
- [ ] No wrapper class patterns
- [ ] Proper error handling (KeyError for missing fields)
- [ ] gym40k.py integration instructions provided

**Critical Implementation Requirements:**
- `execute_gym_action` follows exact AI_TURN.md 5-step pattern
- Built-in `episode_steps` increment during unit actions
- UPPERCASE field validation (raise KeyError if CUR_HP, RNG_NB missing)
- Simple unit queue (IDs only, not full objects)
- Phase-specific eligibility rules (move/shoot/charge/combat)

**Phase 4 Success Criteria:**
- ✅ Complete SequentialGameController implementation provided
- ✅ Built-in step counting functional
- ✅ No wrapper patterns in solution
- ✅ UPPERCASE field validation included
- ✅ Integration instructions clear

---

### PHASE 5: INTEGRATION ✅/❌ [1 HOUR]
**Status:** [COMPLETED/IN PROGRESS/NOT STARTED]

**User Prompt for Phase 5:**
```
Updates applied. STATE FILE STATUS → ✅AI_TURN compliance first → DEBUG with evidence → ORIGINAL/UPDATED blocks → TRACK CHANGES → AI_TURN VERIFICATION: Sequential activation? Built-in step counting? Eligibility-based phases? UPPERCASE fields? Single game_state? → NO wrapper patterns, NO state copying, NO lowercase fields

TASK: Provide exact integration instructions:
1. Replace wrapper imports in gym40k.py with direct SequentialGameController
2. Specify exact file operations (create, modify, delete)
3. List wrapper files to delete
4. Include testing command to verify implementation

Show ORIGINAL/UPDATED blocks for gym40k.py changes.
```

**Phase 5 Tasks:**
- [ ] Provide exact file replacement instructions  
- [ ] Specify wrapper files to delete (step_logging_wrapper.py, sequential_integration_wrapper.py)
- [ ] Give gym40k.py modification details using ORIGINAL/UPDATED format
- [ ] Include testing instructions and commands

**Integration Requirements:**
- Clear file operation instructions (create/modify/delete)
- Wrapper file deletion confirmation
- Import statement updates in gym40k.py
- Testing command provided: `python ai/train.py --config debug --timesteps 1000`
- Success criteria defined for verification

**Phase 5 Success Criteria:**
- ✅ Exact file operations specified
- ✅ Wrapper deletion instructions provided
- ✅ gym40k.py integration detailed
- ✅ Testing procedure included

---

### PHASE 6: VALIDATION ✅/❌ [1 HOUR]
**Status:** [COMPLETED/IN PROGRESS/NOT STARTED]

**User Prompt for Phase 6:**
```
Updates applied. STATE FILE STATUS → ✅AI_TURN compliance first → DEBUG with evidence → ORIGINAL/UPDATED blocks → TRACK CHANGES → AI_TURN VERIFICATION: Sequential activation? Built-in step counting? Eligibility-based phases? UPPERCASE fields? Single game_state? → NO wrapper patterns, NO state copying, NO lowercase fields

TASK: Guide validation testing:
1. Verify one unit activates per gym action
2. Confirm episode_steps increment naturally during gameplay  
3. Check phases advance when no eligible units remain
4. Validate no wrapper complexity in execution
5. Answer AI_GUIDE.md 8 validation questions

Provide test procedures and debug any issues found.
```

**Phase 6 Validation Checklist:**

### Technical Validation
- [ ] **Single Controller:** Only one SequentialGameController class
- [ ] **Built-in Stepping:** `episode_steps` increment inside controller actions
- [ ] **No Wrappers:** No wrapper class patterns anywhere
- [ ] **Direct Integration:** Works with gym40k.py directly
- [ ] **UPPERCASE Fields:** Proper field naming maintained (CUR_HP, RNG_NB, etc.)

### Guide 1 Compliance (8 Questions)
- [ ] **Q1:** Implements EXACTLY what AI_TURN.md describes?
- [ ] **Q2:** Only ONE unit processed per gym action?
- [ ] **Q3:** Phases end based on unit eligibility only?
- [ ] **Q4:** Step counting built INTO controller (not retrofitted)?
- [ ] **Q5:** All unit fields UPPERCASE (CUR_HP, not cur_hp)?
- [ ] **Q6:** episode_steps stored in game_state (not separate)?
- [ ] **Q7:** Avoids all forbidden patterns?
- [ ] **Q8:** Flow traceable from gym action to unit action?

### Functional Testing
- [ ] Training runs without wrapper-related errors
- [ ] Step counting works naturally (no retrofitted patterns)
- [ ] One unit per gym action verified
- [ ] Phase transitions based on unit eligibility
- [ ] Performance equal or better than wrapper version

**Phase 6 Success Criteria:**
- ✅ All 8 AI_GUIDE.md validation questions answered YES
- ✅ Technical validation passes completely
- ✅ Functional testing successful
- ✅ Training behavior improved
- ✅ Architecture simplified

---

## 🚨 ISSUE RESOLUTION PROTOCOLS

### Emergency Stop Triggers (Claude Must Not Suggest)
- "Let me optimize this" / "We could batch process units" 
- "I'll add some wrapper classes" / "This would be cleaner with inheritance"
- "Let me add some additional state tracking"
- Any mention of retrofitted step counting patterns
- Lowercase field names (cur_hp, rng_nb, etc.)

### Emergency Recovery Responses

**If User Reports Wrapper Suggestions:**
```
🚨 GUIDE 1 VIOLATION ACKNOWLEDGED: Implementing single SequentialGameController with built-in step counting only. No wrapper patterns allowed.
```

**If Implementation Seems Complex:**
```
COMPLEXITY REDUCTION: Simplifying to core requirement - built-in step counting in single controller class. No additional layers.
```

**If Retrofitted Patterns Detected:**
```
RETROFITTED PATTERN CORRECTED: Moving step increment into natural action flow inside controller. No external step tracking.
```

**If Testing Fails:**
1. Review implementation against Guide 1 requirements
2. Check for wrapper pattern leakage  
3. Verify built-in step counting placement
4. Provide debugging guidance with specific fixes

---

## 📊 PROGRESS TRACKING

### Session Continuity (For Claude)
**When User Returns, Claude Should:**
1. **Check current phase status** from this guide
2. **Review completed phases** and identify what's done
3. **Identify current phase** and next immediate task
4. **Continue from appropriate checkpoint** without losing context

### Context Recovery Protocol
**If Context is Unclear:**
1. **Reference this guide** for project status
2. **Ask user** which phase they're currently on
3. **Review provided files** to understand current state
4. **Resume from appropriate phase** using correct prompt

### Progress Notes (Claude Should Update)
- **Phase 1 Completed:** [Date/Time] - Files analyzed, Expert Mode active
- **Phase 2 Completed:** [Date/Time] - Architecture problems identified  
- **Phase 3 Completed:** [Date/Time] - Solution design approved
- **Phase 4 Completed:** [Date/Time] - Implementation provided
- **Phase 5 Completed:** [Date/Time] - Integration instructions given
- **Phase 6 Completed:** [Date/Time] - Validation successful

---

## 🎯 SUCCESS CRITERIA REFERENCE

### Implementation Success
- ✅ Single SequentialGameController file created
- ✅ Built-in step counting implemented (`self.base.game_state["episode_steps"] += 1`)
- ✅ No wrapper classes in solution
- ✅ gym40k.py integration instructions provided
- ✅ Guide 1 Rule #4 compliance maintained

### Integration Success  
- ✅ User reports files replaced successfully
- ✅ Wrapper files deleted (step_logging_wrapper.py, sequential_integration_wrapper.py)
- ✅ Training runs without errors: `python ai/train.py --config debug --timesteps 1000`
- ✅ Step counting works naturally (no retrofitted patterns)
- ✅ No wrapper complexity remains

### Project Success
- ✅ Training behavior improved vs wrapper architecture
- ✅ Architecture simplified and maintainable
- ✅ Built-in step counting functional
- ✅ All AI_GUIDE.md validation questions pass
- ✅ User ready to return to normal workflow

---

## 🔄 PROJECT HANDOFF

### When Project Completes Successfully
1. **Confirm all success criteria met**
2. **Document lessons learned** (wrapper complexity avoidance)
3. **Guide user back to normal prompt system** (revert to original AI_PROMPT0)
4. **Archive project-specific materials** (AI_GUIDE.md, AI_PROMPT1 for future reference)

### Files Status at Completion
- ✅ **sequential_game_controller.py** - Created and functional
- ✅ **gym40k.py** - Modified (wrapper imports removed, direct controller init)
- ✅ **step_logging_wrapper.py** - Deleted
- ✅ **sequential_integration_wrapper.py** - Deleted

---

## 📋 CLAUDE QUICK REFERENCE

### Key Implementation Points (Always Remember)
- **Built-in step counting:** `self.base.game_state["episode_steps"] += 1` inside action execution
- **No wrapper patterns:** Single controller class with delegation only
- **Guide 1 Rule #4:** Built-in not retrofitted step counting
- **File operations:** Replace and delete, don't wrap existing code
- **UPPERCASE fields:** CUR_HP, RNG_NB, CC_STR (not cur_hp, rng_nb, cc_str)

### Critical Validations (Check Every Response)
- Every response must verify Guide 1 compliance
- All code must avoid wrapper patterns completely
- Step counting must be built into natural action flow
- UPPERCASE field naming must be preserved
- Single game_state object pattern maintained

### Success Indicators (Project Complete When)
- User reports successful training runs
- No wrapper complexity remains in codebase
- Step counting works naturally during gameplay
- Architecture is simplified and maintainable
- All 8 AI_GUIDE.md validation questions answered YES

**🎯 ALWAYS REFERENCE THIS GUIDE TO MAINTAIN PROJECT CONTINUITY AND ENSURE SUCCESSFUL COMPLETION**