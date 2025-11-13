# Protocol Check - Quick Verification

Verify I'm following proper protocols by asking these checkpoint questions:

## Pre-Change Checklist
- [ ] Have you read the actual file contents with Read tool?
- [ ] Did you check related files (imports, dependencies)?
- [ ] Can you show evidence of the current behavior?
- [ ] Are you 100% confident or do you need debug logs?

## Code Change Checklist
- [ ] Does this follow AI_TURN.md rules (no wrappers, direct access)?
- [ ] Have you used exact matching (no ellipses, no approximations)?
- [ ] Did you explain what this impacts (rewards, learning, game flow)?
- [ ] Is this a root cause fix or a workaround?

## AI_TURN.md Compliance Checklist
- [ ] No wrapper patterns or state copying?
- [ ] No default values hiding missing fields?
- [ ] Stateless functions (no internal state storage)?
- [ ] Phase-based transitions (not step-based)?
- [ ] Single unit per action (no multi-unit loops)?

## Training Change Checklist
- [ ] Reviewed reward config impact?
- [ ] Checked training hyperparameters?
- [ ] Verified bot evaluation logic?
- [ ] Considered effect on learning signal?

Answer these questions before proceeding with the change.
