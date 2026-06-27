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

The application guides the player through every phase of the game, handling the measuring, rule-checking, and dice-rolling so the player can focus on tactics. The whole turn structure — Command, Movement, Shooting, Charge, Fight — is played in its official order.

**Datasheets at a click.** Every unit's full profile, weapons, and abilities are one click away. No rulebook, no card shuffling.

**Movement preview.** When a unit is selected, the application shows exactly where it can go — all reachable squares at a glance, already accounting for terrain, models in the way, units that can fly, and enemy engagement ranges. Normal moves, Advances, Fall Backs, desperate escaptes each show their own legal area, with the consequences (no shooting after a Fall Back, etc.) applied automatically.

**Line-of-sight preview.** Before committing a move, the player sees which enemies a given position can actually see and shoot, updated live as the unit moves. Cover is shown the same way, so the player knows the real odds before deciding.

**Weapon and target selection by menu.** Units can carry several weapons; the player picks the weapon and the target from a clear menu, choosing only from legal targets. No measuring tape, no ambiguity about what is in range.

**Automatic dice resolution, player keeps the decisions.** Hits, wounds, and saves are rolled and totalled instantly. The defending player then chooses how to allocate the casualties across their models — exactly as on the tabletop. Weapon special rules (Rapid Fire, Melta, Blast, Pistol, Assault, rerolls, and so on) are applied for the player automatically.

**Charge and combat.** Charges, pile-in, and the fight itself follow the official sequence — the player declares the charge and makes the choices, the application handles the distances and the rolls.

**Faithful to the rules.** Around 100 unit datasheets across several factions, some 50 weapons, terrain, cover, and objectives are all modelled on the current edition. Distances on screen map directly to tabletop inches.

The design principle is consistent: **the application does the arithmetic; the player makes every decision.**

> **Note on the board model.** The battlefield uses a fine hexagonal grid rather than free measurement, a deliberate engineering choice that bounds the state space for reinforcement-learning training. The resolution is calibrated at **1 inch = 5 hexes**, keeping positional error well below one inch so that ranges, charges, and engagement distances remain faithful to tabletop measurement while staying tractable for the AI.

## 3. Value for Games Workshop

**List-testing before purchase.** Players build and play a list before buying and painting it, validating purchases in play rather than abandoning them after one game.

**Tournament training.** Competitive players rehearse matchups, deployments, and sequencing far more often than physical play allows, strengthening the organised-play ecosystem.

**Reduced game length.** A full game runs in roughly **one hour** versus **three to four** physically, because measurement, range-checking, and dice handling are automated. More games played means more rules learned and more reasons to stay engaged.

**New-player acquisition.** The engine enforces the rules, so newcomers learn correctly by playing, no by reading the rules or asking someone else. This lowers the single largest barrier to entry and creating a funnel toward the physical product.

The net effect: more games played per player, faster rules mastery, and de-risked miniature purchases — supporting physical sales rather than cannibalising them.

## 4. Project Status

- **PvP — functional.** Complete human-versus-human games are playable end to end, with the full four-phase core loop.
- **AI — in development.** A reinforcement-learning opponent (MaskablePPO, with action masking, parallel environment training, and evaluation against scripted bots) is being trained for solo play and sparring.
- **Additional content.** A campaign-style "Endless Duty" mode (successive enemy waves, inter-wave requisition, objective defence) demonstrates progression on top of the core engine.
- **Replay and analytics.** Action-by-action replay and training-metrics tooling are in place.
- **Alpha — privately tested.** The current build has been tested in a closed setting.

Some rules remain in progress — notably the full current-edition Fight-phase refinements (Fights First / Remaining ordering, grouped pile-in and consolidation) — and stratagems are not yet in the engine.

## 5. Proposal

The project is fully functional and actively expanding — additional game modes, deeper faction coverage, and campaign content are already in progress. An official collaboration would be mutually beneficial: Games Workshop gains a controlled, rules-accurate digital tool that drives new comers engagement and miniature sales; the project gains official sanction, access to authoritative rules data, and legitimacy with the player base.

We are open to discussing a licensing arrangement covering use of the Warhammer 40,000 intellectual property and rules content, and would welcome an initial conversation to explore terms.
