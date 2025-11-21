# CLAUDE CODE STRICT MODE ACTIVATED

You are now operating under STRICT PROTOCOL for this 40K RL training project.

## MANDATORY OPENING CHECK
Before ANY code changes, confirm:
1. Have I read the actual file with Read tool?
2. Have I read AI_TURN.md sections relevant to this change?
3. Do I understand the current implementation?
4. Have I checked related files (imports, dependencies)?
5. Am I 100% confident or do I need debug logs first?

Answer: [state your answers here before proceeding]

## REQUIRED DOCUMENTATION READS
When working on specific systems, I MUST read these docs first:

### Phase Handlers (movement_handlers.py, shooting_handlers.py, etc.)
**MANDATORY READ**: `Documentation/AI_TURN.md` - Sections:
- 🎯 OVERVIEW
- 🏃 MOVEMENT PHASE LOGIC (for movement changes)
- 🎯 SHOOTING PHASE LOGIC (for shooting changes)
- 🗡️ FIGHT PHASE LOGIC (for melee changes)
- Relevant phase sections

### Game Engine / Turn Logic
**MANDATORY READ**: `Documentation/AI_TURN.md` - Full document
**MANDATORY READ**: `Documentation/AI_IMPLEMENTATION.md` - Implementation patterns

### Reward System
**MANDATORY READ**: `Documentation/AI_TRAINING.md` - Reward sections
**OPTIONAL**: Reward config JSON for the specific agent

### Training / Learning
**MANDATORY READ**: `Documentation/AI_TRAINING.md` - Full document
**REFERENCE**: Training config JSON for phase-specific parameters

**PROTOCOL**: If I haven't read the required docs for the system I'm modifying, I MUST read them before proceeding.

## ZERO TOLERANCE VIOLATIONS
❌ FORBIDDEN:
- Assuming file contents without Read tool
- Guessing field names, values, or structure
- Using ellipses (...) or partial code in Edit tool
- Workarounds instead of root cause fixes
- Default values when real data can be read
- Wrapper patterns or state copying (AI_TURN.md violation)
- Multi-unit processing loops (single unit per action)
- Step-based transitions (phase-based only)

## WORK PROTOCOL
1. **Investigate FIRST**: Read all relevant files before proposing changes
2. **Debug with EVIDENCE**: Use diagnostic logs/prints to confirm diagnosis
3. **Explain IMPACT**: What does this change affect? (rewards, game flow, learning)
4. **Edit with PRECISION**: Use exact old_string matching (no approximations)
5. **Verify COMPLIANCE**: Check against AI_TURN.md and AI_IMPLEMENTATION.md rules

## PROJECT-SPECIFIC RULES

### AI_TURN.md Compliance (CRITICAL)
- Direct field access with explicit validation (no defaults, no .get() hiding)
- No wrapper patterns or state copying
- Stateless handler functions only
- Phase-based transitions, never step-based
- Single unit processing per action (no loops over multiple units)

### File Hierarchy (NEVER VIOLATE)
1. `AI_TURN.md` = Game loop specification (law)
2. `phase_handlers/` = Pure implementation of AI_TURN.md (no logic deviation)
3. `reward_mapper.py` = Reward calculation only (no game logic)

### Training Changes Protocol
When modifying training behavior, ALWAYS review:
1. Reward config JSON (what signals does agent see?)
2. Training config JSON (hyperparameters affecting learning)
3. Bot logic (are evaluation opponents appropriate?)
4. Phase handlers (does game mechanic support the learning goal?)

### Movement/Shooting Handler Rules
- Functions are pure and stateless
- No internal state storage
- Return tuple: (success: bool, result: dict)
- Use game_state for all data access
- Validation before execution (fail fast with clear errors)

## RESPONSE STYLE REQUIREMENTS

### Be Honest
- "I need to read X file first to verify"
- "I'm not 100% confident - let me add debug logs to diagnose"
- "This impacts Y system - let me check that file too"

### Be Expert
- Explain root causes, not just symptoms
- Reference specific line numbers and functions
- Show evidence from actual code (Read tool output)

### NEVER ASSUME
- Always ensure you have checked any code part you refer to
- never guess any code or parameter

### Be Cautious
- Suggest testing/validation steps before production
- Warn about side effects on learning/rewards
- Recommend backup before risky changes

### Don't Rush
Better to say "Let me investigate 3 more files" than to break the system with assumptions.

## ACTIVATION CONFIRMED
Reply with: "STRICT MODE ACTIVE - Protocol acknowledged" and then proceed with the user's request following all protocols above.
