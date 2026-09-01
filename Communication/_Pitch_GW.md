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

**Movement preview.** When a unit is selected, the application shows exactly where it can go — all reachable squares at a glance, already accounting for terrain, models in the way, units that can fly, and enemy engagement ranges. Normal moves, Advances, Fall Backs, desperate escapes each show their own legal area, with the consequences (no shooting after a Fall Back, etc.) applied automatically.

**Line-of-sight preview.** Before committing a move, the player sees which enemies a given position can actually see and shoot, updated live as the unit moves. Cover is shown the same way, so the player knows the real odds before deciding.

**Weapon and target selection by menu.** Units can carry several weapons; the player picks the weapon and the target from a clear menu, choosing only from legal targets. No measuring tape, no ambiguity about what is in range.

**Automatic dice resolution, player keeps the decisions.** Hits, wounds, and saves are rolled and totalled instantly. The defending player then chooses how to allocate the casualties across their models — exactly as on the tabletop. Weapon special rules (Rapid Fire, Melta, Blast, Pistol, Assault, rerolls, and so on) are applied for the player automatically.

**Charge and combat.** Charges, pile-in, and the fight itself follow the official sequence — the player declares the charge and makes the choices, the application handles the distances and the rolls.

**Faithful to the rules.** 100+ unit datasheets and their load-out profiles, 200+ weapon stat profiles across six factions, terrain, cover, and objectives are all modelled on the current edition. Distances on screen map directly to tabletop inches. Rule accuracy is backed by 6,000+ automated regression tests, ensuring that every rules update or interaction cannot silently break existing behaviour.

The design principle is consistent: **the application does the arithmetic; the player makes every decision.**

> **Note on the board model.** The battlefield uses a fine hexagonal grid rather than free measurement, a deliberate engineering choice that bounds the state space for reinforcement-learning training. The resolution is calibrated at **1 inch = 5 hexes**, keeping positional error well below one inch so that ranges, charges, and engagement distances remain faithful to tabletop measurement while staying tractable for the AI.

## 3. Project Status

- **PvP — functional.** Complete human-versus-human games are playable end to end, with the full four-phase core loop.
- **AI — in development.** A reinforcement-learning opponent (MaskablePPO, with action masking, parallel environment training, and evaluation against scripted bots) is being trained for solo play and sparring.
- **Additional content.** A campaign-style "Endless Duty" mode (successive enemy waves, inter-wave requisition, objective defence) demonstrates progression on top of the core engine.
- **Replay and analytics.** Action-by-action replay and training-metrics tooling are in place.
- **Alpha — privately tested.** The current build has been tested in a closed setting.

Stratagems are not yet in the engine.

## 4. Industry Precedent: MTG Arena

Wizards of the Coast faced the same apparent dilemma when launching MTG Arena in 2018: how do you digitise a business whose economic foundation is a physical collectible product without cannibalising it?

The answer turned out to be the opposite of cannibalisation. Arena now has more than **17 million registered players**. Over the same period, Magic's physical organised-play network grew from roughly 6,000 stores to more than **10,000 active WPN stores**, and physical organised play reached more than **one million unique participants** in a single year. Both channels grew simultaneously.

The single most commercially significant figure Hasbro has published is this: players who engage with both tabletop Magic and Arena spend approximately **40% more** than the average Magic player. The digital platform did not redirect spending away from physical product — it increased total engagement and total spend per customer.

**Warhammer has more friction than Magic, not less.** A casual game of Magic requires two decks and a table. A casual game of Warhammer 40,000 requires an army, a painted board, terrain, a second player, and several hours. Every one of those barriers has a direct digital equivalent that a virtual platform removes. If a moderate friction reduction drove +40% hybrid spend in Magic, the effect for Warhammer — starting from a higher friction baseline — should be at least as large.

## 5. Value for Games Workshop

**Two customers, not one.** The platform serves players directly, and simultaneously serves Games Workshop as a game-development tool.

*For players:*

**List-testing before purchase.** Players build and try a list digitally before buying and painting the models — validating purchases rather than abandoning them after one game.

**Tournament training.** Competitive players rehearse matchups, deployments, and sequencing far more than physical play allows, deepening engagement with the organised-play ecosystem.

**Reduced game length.** A full game runs in roughly **one hour** versus three to four physically. More games played means faster rules mastery and stronger attachment to a faction.

**New-player acquisition.** The engine enforces the rules, so newcomers learn by playing rather than by reading. This removes the single largest barrier to entry and feeds new customers toward physical product.

*For Games Workshop:*

**AI-powered play design.** The reinforcement-learning engine can run thousands of games per hour against itself, producing matchup win-rates, first-player advantage data, and outlier unit performance across any combination of rosters — before a dataslate is published, not after. This is something MTG Arena does not provide to Wizards at this scale: simulation data ahead of publication, not only reaction data after it.

The resulting cycle: design → AI simulation → targeted human playtest → refined publication → real-world data → informed dataslate. Every step is faster and better evidenced than physical playtesting alone can achieve.

*Financial framing:*

Games Workshop's core revenue for FY2025/26 stands at **£626.8 million**, with 890,000 active My Warhammer users already on platform. Applying the Magic hybrid-spend benchmark conservatively — assuming 25% of customers become hybrid users with a +20% spend increase — implies roughly **£31 million of additional annual core revenue**. Even the most cautious scenario (10% of customers, +10% spend) implies +£6 million. These are sensitivity estimates, not forecasts; the point is that the lever is large relative to the cost of creating it.

The net effect: more games played per player, faster rules mastery, de-risked miniature purchases, and a continuous AI-assisted feedback loop for GW's own game design — all supporting physical sales rather than competing with them.

## 6. Proposal

The project's core is fully functional and actively expanding — additional game modes, deeper faction coverage, and campaign content are already in progress. An official collaboration would be mutually beneficial: Games Workshop gains a controlled, rules-accurate digital platform that drives newcomer engagement and miniature sales while providing AI-assisted game-design data; the project gains official sanction, access to authoritative rules data, and legitimacy with the player base.

We are open to discussing a licensing arrangement covering use of the Warhammer 40,000 intellectual property and rules content, and would welcome an initial conversation to explore terms.
