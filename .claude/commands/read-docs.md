# Read Project Documentation

Read the relevant project documentation before proceeding with the user's request.

## Determine What to Read

Based on the user's request, identify which systems are involved:

- **Phase handlers** (movement, shooting, fight, morale) → Read tour_de_jeu.md relevant sections
- **Game engine/turn logic** → Read tour_de_jeu.md (full) + architecture_moteur.md
- **Rewards/training** → Read AI_TRAINING.md
- **General code questions** → Read architecture_moteur.md

## Then Read the Files

Use the Read tool to read the relevant documentation files from the `Documentation/` folder:

1. `Documentation/Reference/moteur/tour_de_jeu.md` - Game loop and phase logic specification
2. `Documentation/Reference/moteur/architecture_moteur.md` - Implementation patterns and rules
3. `Documentation/Reference/training/AI_TRAINING.md` - Training and reward system documentation
4. `Documentation/ANTI_OVERFITTING_GUIDE.md` - Training optimization guide

## After Reading

Confirm what you read and then proceed with the user's request, ensuring compliance with the documentation.

**Example response**:
"I've read tour_de_jeu.md section 🏃 MOVEMENT PHASE LOGIC. Based on the spec, I need to verify the current implementation follows these rules: [list key rules]. Let me read the actual file now..."