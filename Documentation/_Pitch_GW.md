# Warhammer 40,000 Battle Simulator — Project Presentation

*Prepared for Games Workshop Ltd.*

## 1. Concept

A PC application that runs a complete game of Warhammer 40,000 on a digital hex-based tabletop, against another human or against a reinforcement-learning AI. The engine enforces the official rules and automates the bookkeeping — movement ranges, line of sight, dice resolution — while every tactical decision stays with the player.

**What it is:**
- A faithful digital execution of the current-edition core rules
- A way to play full games quickly, locally or against AI
- A complement to the physical hobby

**What it is not:**
- Not an action/RTS reinterpretation (no real-time combat, no lore rewrite)
- Not a replacement for miniatures, painting, or the physical product
- Not a substitute for the tabletop experience — it removes friction, not the game

The application targets the moments *around* the table: testing a list, learning a faction, training for an event, or playing when no physical setup is available.

## 2. Gameplay Features

The engine is built as discrete rules handlers — one module per phase (movement, shooting, charge, fight) — totalling tens of thousands of lines of rules code. Selected implemented features:

**Full phase sequence.** Command → Movement → Shooting → Charge → Fight, with strict sequential unit activation and eligibility-driven phase transitions, matching the official turn structure.

**Automatic movement zones.** Legal movement is computed by a multi-hex breadth-first search that accounts for terrain (walls, dense obstacles, occupied hexes), vertical movement (the *Fly* keyword), and enemy engagement zones (2"). Normal move, Advance (+D6"), and Fall Back are all distinguished, with their respective downstream restrictions enforced.

**Dynamic line of sight.** LoS is computed per hex against dense walls and obscuring terrain polygons, cached, and recalculated after every move and every casualty. The interface previews valid targets and a visibility ratio *before* the player commits a position.

**Cover.** The engine detects hideable units (Infantry / Beast / Swarm), applies cover from obscuring terrain or partially-blocked LoS as a −1 to hit, and respects the *Ignores Cover* weapon rule.

**Menu-based weapon and target selection.** Units carry multiple weapon slots (up to three ranged, two melee); the player selects weapon and target through the interface from a validated target pool. AI selections are pre-filled the same way.

**Automated shooting resolution with defender allocation.** Attacks resolve number-of-shots → hit → wound → save → damage automatically, and the **defending player allocates casualties** model by model — preserving the decision structure of the tabletop. Weapon special rules are implemented through a centralised registry: Rapid Fire, Melta, Blast, Pistol, Assault, Combi, and to-hit / damage rerolls.

**Charge phase.** 2D6 charge distance, mandatory engagement, BFS pathing with declared Fly, collision detection, pile-in, and Charge-impact resolution.

**Rules fidelity.** The rules data — ~200 unit datasheets across multiple factions (Space Marines, Tyranids, Aeldari, Chaos, Custodes), ~50 weapons, terrain, objectives, unit coherency — is treated as the single source of truth. The hex board scales dynamically (inch-to-subhex at 1/5/10 resolution) so distances map exactly to tabletop measurements.

The design principle is consistent: **automate the arithmetic, never the decisions.**

> **Note on the board model.** The battlefield uses a fine hexagonal grid rather than free measurement, a deliberate engineering choice that bounds the state space for reinforcement-learning training. The resolution is calibrated at **1 inch = 5 hexes**, keeping positional error well below one inch so that ranges, charges, and engagement distances remain faithful to tabletop measurement while staying tractable for the AI.

## 3. Value for Games Workshop

**List-testing before purchase.** Players build and play a list before buying and painting it, validating purchases in play rather than abandoning them after one game.

**Tournament training.** Competitive players rehearse matchups, deployments, and sequencing far more often than physical play allows, strengthening the organised-play ecosystem.

**Reduced game length.** A full game runs in roughly **one hour** versus **three to four** physically, because measurement, range-checking, and dice handling are automated. More games played means more rules learned and more reasons to stay engaged.

**New-player acquisition.** The engine enforces the rules, so newcomers learn correctly without an experienced opponent or a rulebook in hand — lowering the single largest barrier to entry and creating a funnel toward the physical product.

The net effect: more games played per player, faster rules mastery, and de-risked miniature purchases — supporting physical sales rather than cannibalising them.

## 4. Project Status

- **PvP — functional.** Complete human-versus-human games are playable end to end, with the full four-phase core loop.
- **AI — in development.** A reinforcement-learning opponent (MaskablePPO, with action masking, parallel environment training, and evaluation against scripted bots) is being trained for solo play and sparring.
- **Additional content.** A campaign-style "Endless Duty" mode (successive enemy waves, inter-wave requisition, objective defence) demonstrates progression on top of the core engine.
- **Replay and analytics.** Action-by-action replay and training-metrics tooling are in place.
- **Alpha — privately tested.** The current build has been tested in a closed setting.

Some rules remain in progress — notably the full current-edition Fight-phase refinements (Fights First / Remaining ordering, grouped pile-in and consolidation) — and stratagems are not yet in the engine.

## 5. Proposal

The project is technically viable and can continue independently. An official collaboration would be mutually beneficial: Games Workshop gains a controlled, rules-accurate digital tool that drives engagement and miniature sales; the project gains official sanction, access to authoritative rules data, and legitimacy with the player base.

We are open to discussing a licensing arrangement covering use of the Warhammer 40,000 intellectual property and rules content, and would welcome an initial conversation to explore terms.
