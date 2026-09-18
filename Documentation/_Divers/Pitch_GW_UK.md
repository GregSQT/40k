# The Machine Spirit at Games Workshop?

*Presentation document — Games Workshop*

---

## The question worth asking

At every AI seminar I have attended, companies shared the same awareness: they needed to embrace AI, yet had no clear sense of how to do it, nor what they might reasonably expect from it.

This document addresses a more precise question: what could an AI capable of playing Warhammer 40,000 bring to Games Workshop?

---

## 1. The first gain: internally

### Human expertise is not quantifiable. Time is.

The developers and playtesters of Warhammer 40,000 are a precious resource. Their experience, their expertise, their feel for the game are irreplaceable — built over years, and worth every one of them.
Yet their time is finite. And the pace of releases — codexes, balance updates, new editions — is relentless.

That is precisely where an AI capable of playing 40K becomes an **ideal partner**.

### From intuition to data, in minutes

Consider this scenario: an experienced playtester identifies a combination that feels too strong, a unit value that resists clean calibration, a force composition whose balance seems off.

Verifying that intuition means playing games. But beyond the logistical demands a game imposes — two players, aligned schedules, table time — even those games may not be enough to confirm or refute the hunch:

- **Objectivity.** Even after several games, adjudicating a sensitive rules point that could affect an entire dimension of play remains extraordinarily difficult.
- **Blind spots.** An untested interaction stays invisible until thousands of players encounter it in the wild, after publication.
- **Player skill.** Tournament statistics suffer from a critical blind spot of their own: they cannot account for the unequal skill levels of the players generating them.

What AI brings to the table:
Thousands of games and equally thousands of reliable data points, every hour. Objective, concrete evidence on which your team can ground their decisions.

To which a nuance must be added — one that is easily overlooked: **a perfect AI is not a human player.** A unit that is genuinely difficult to master might appear exceptional in the hands of a machine, yet disappoint the majority of players who lack the skill to exploit it fully. The same match-ups are therefore replayed using a deliberately weakened AI. If the unit collapses, it is not poorly balanced — it is **technical**. That is not the same remedy at all, and it is exactly the distinction a game designer needs to make.

### A danger defused

When AI enters the conversation, concerns are never far behind. For Warhammer 40K, the obvious one would be: might an AI simply "solve" the game, defining the optimal list for every codex — and in doing so, kill list diversity altogether?

First, a straightforward fact: the agent I have developed is a Reinforcement Learning agent. It knows how to *play* Warhammer 40,000, and nothing more. What is done with that capability is entirely up to you. Asking it to generate the ideal list for every roster would be a feature to implement. If that feature is never built, the agent will never produce it on its own. The decision of whether that capability ever exists rests entirely with you.

---

## 2. Going digital: a leap into the unknown?

### The precedent — how Magic answered the same question

The first objection this project raises is predictable: would an official digital platform cannibalise physical miniature sales?

Magic: The Gathering had to answer that very question in 2017–2018. Its economy rested on the sale of a physical product that players buy, collect, and need in order to play — precisely like Games Workshop. The fear of cannibalisation was even more direct in Magic's case: a digital card is an explicit substitute for its physical counterpart.

Wizards launched MTG Arena in open beta in September 2018. What followed offers a revealing set of projections for Games Workshop.

**In February 2018, before the open beta, Wizards estimated that approximately 30 million people had played Magic over the preceding 25 years.** By December 2018, that figure had already surpassed 35 million. **Today, it exceeds 50 million** — including more than 17 million registered digital accounts on Arena alone. Over the same period, the WPN network of physical game stores grew from approximately **6,000 stores in 2019** to more than **10,000 active stores at the end of 2025** (+20% in the final year alone), with more than one million unique players participating in organised physical play in 2025 (+22% year-on-year).

The digital did not replace the physical. Both grew together.

### The figure that answers the fear

In its 2022 annual report, Hasbro identified **hybrid** players — those who play both tabletop Magic and the digital game — as its **fastest-growing segment of Magic players**, with "the highest spending level, 40% above the average revenue per Magic player across all formats". Hasbro does not disclose the precise size of this segment, but considers it strategically significant enough to highlight in its investor report.

For Games Workshop, with a core revenue of £626.8M in 2025/26: even a modest increase in average spend among a fraction of hybrid hobbyists represents several tens of millions of pounds in potential annual value — before accounting for direct digital revenues.

That +40% figure answers the cannibalisation concern directly. Hasbro's data suggests precisely the opposite effect among hybrid players.

### What GW would have that Magic does not

Arena gives Wizards vast data *after* publication. GW would gain the same — but with two additional decisive advantages: through AI, simulation available **before** publication enables the game to be balanced objectively, while the AI-assisted weighting of data collected *after* publication allows the meta to be read with precision rather than merely described.

The cycle would become:

> design → **AI simulation** → human playtest / **AI simulation** → publication → real-world data + **AI weighting** → analysis → dataslate

Wizards has access only to part of the right half of that cycle. Games Workshop would have the full loop.

### What Games Workshop already possesses

Games Workshop would not be starting from scratch. As of the end of May 2026:

- **890,000 active My Warhammer users** (engaged within the past six months), up from 735,000 the prior year (**+21%**)
- **269,000 Warhammer+ subscribers**, up from 232,000 a year earlier (**+16%**)
- More than **1.5 million unique viewers** for the most recent World Championships

The platform, the billing infrastructure, the customer base: there is nothing to build around them. What is missing is a reason to come back every week.

### The structure that protects the physical

Wizards separated two environments. **Standard Arena** mirrors physical Standard exactly — same cards, same rules, same ban list. A player can practise on Arena and sit down at a table the following day without missing a beat. **Alchemy** is an exclusively digital space: cards native to the platform, mechanics impossible on a physical table, frequent rebalancing — and it never touches physical Standard.

For GW, an analogous architecture:

| OFFICIAL WARHAMMER | WARHAMMER LAB |
|---|---|
| Exact tabletop rules | Future balance adjustments under testing |
| Human and AI games | New units before publication |
| Tournaments and matchmaking | Experimental missions |
| Online tournament data | Pre-release AI simulation |

The first environment is entirely aligned with the tabletop. The second gives Games Workshop the ability to do what is impossible with miniatures already cast and codexes already sold — and to offer players an experience that complements, rather than competes with, the physical game.

---

## 3. The commercial gains

### An unmet need

Until recently, players wishing to play Warhammer 40,000 remotely had no official solution: third-party-modelled miniatures, a virtual measuring tape, digital dice — and a ruleset the software knew nothing of. Players measured themselves, applied the rules themselves, arbitrated disagreements themselves. The demand is real; the official answer, to this day, is silence.

What I bring is not a substitute: it is an engine that knows the rules and enforces them, making errors and disputes impossible. It offers players an experience and a level of comfort that no third-party platform — official or otherwise — has yet provided.

### Bringing new players in

The two armies on which my AI has been trained were not chosen at random: **they are the armies from the V11 starter box: Armageddon.**

Consider the scenario:
A new player, on their own, has watched videos and read up on the world of Warhammer 40,000. They want to take the plunge. Say they have a budget of €200.
Their hesitation has nothing to do with price — it is the prospect of learning an enormously complex game alone, with no partner, no one to correct their mistakes, and a more or less extended period during which they will test the patience of whoever is teaching them while knowing only the frustration of defeat. Many stop exactly there, not for lack of interest, but for lack of access to an accessible way in.

What AI puts in a retailer's mouth:

> *"Here is a URL — it's free. Learn the rules by playing with the miniatures in the box."*

- An opponent **available immediately**, with no need to find one.
- The rules learned **by playing**, not by reading — the only method that actually works.
- They play **exactly the units they are about to buy**, not an abstract demonstration — which makes the box itself that much more compelling.

This is measurable, and quickly: conversion rate on the starter box, with and without the tool. And this application asks for nothing: it rests on what already exists — those two armies and this AI.

The digital does not become a competitor to the miniature. It lowers the barrier to it.

### A subscription that does not get cancelled

You already have the service, the billing, the customers: there is nothing to build around them.

What the current service offers is content that is **consumed** — watched, and then waited upon. A game, by contrast, is **played**: every week, indefinitely.

That distinction determines the life of a subscription. **A service is not judged by what prompts sign-up, but by what prevents cancellation.** A catalogue that has been watched through retains no one. A comfortable, frictionless game at a distance, or a solo game when time does not permit gathering around a table, **sustains a player's connection to the hobby** when their capacity to play physically is reduced. You would not be adding one more piece of content to the catalogue: you would be adding a **reason to stay**.

Every player who has been shown the game has not asked whether it might eventually be released. They have asked how to access it, and what it would cost. This is not market research — it is what I have observed, spontaneously, every single time.

And it is the only application whose revenue can be calculated directly: a subscription is recurring, attributable, and projectable.

---

## 4. The image — turning a difficulty into a strength

The balancing of Warhammer 40,000 is a mathematical wall. With several hundred units and an army budget of 2,000 points, the number of possible match-ups is astronomical. No human playtesting programme can cover that space — this is not a question of effort, it is a question of scale.

With this tool, that critique does not disappear — it **reverses**.

A balancing decision ceases to be one editor's opinion set against another player's. It rests on a measurement, taken at equal skill levels, across a volume of games no community could ever produce. And crucially, it is backed by an AI that players know first-hand, because they can play against it and take the measure of it themselves. How does one dispute decisions guided by an AI one cannot consistently beat?

---

## 5. What exists — the current state

This engine was conceived and developed by me alone, outside of any organisation.

**What is done:** the complete game engine (command phase, movement, shooting, charge, close combat, terrain, 3D line of sight, objectives, weapon rules, battle round), the playable interface, the replay chain, and automated analysis.
The AI is built to **read unit characteristics before making any decision**. It does not memorise "how to play Intercessors" — it reads a datasheet exactly as a player would, and decides what to do based on what it has learned through experience. Adding a unit or a rule does not require rebuilding the AI: the system absorbs new content.

The reliability of the engine is not a technical footnote. It was designed for the long term, not merely for the demonstration:

- **7,100+ automated tests**, named after the official rules they verify — readable without any knowledge of code.
- **Each test is validated by deliberately reintroducing the defect** it is meant to catch. A test that passes on the first attempt proves nothing; the verification is that it fails when it should fail.
- **A second net, independent of unit tests:** every game played produces a trace that the analyser reads automatically, rule by rule. 952 game scenarios cover the violations that code alone cannot detect — any bug that slips through the first barrier is flagged the moment it manifests in actual play.

**Limitations and choices:** The demonstration was built on consumer hardware, working within the obvious constraints that entails. The engine, however, was designed to operate at greater scale, and the quality of the agent's play is purely a function of the resources available to train it.

The engine uses a hexagonal grid — a prerequisite for AI training: a continuous space makes Reinforcement Learning convergence prohibitively slow. The granularity chosen (1 inch = 5 hexagons) is a compromise between precision, visual rendering, and training time — not an architectural constraint. The engine already handles two different resolutions; increasing granularity is a matter of compute resources and would not require any rework of the engine itself.

In terms of gameplay, army compositions (force organisation charts), secondary objectives, stratagems, and enhancements have not yet been implemented: adding them presents no technical difficulty, but would have complicated and slowed training for elements that are not material to the demonstration.

The interface draws visual inspiration from White Dwarf battle reports — a familiar point of reference, for a project built by a single person.

---

## 6. What I am proposing

This document posed a question: what can an AI capable of playing 40K bring to the table.

I have just presented my answer.

What I bring is the foundation: a simulation engine embedding the rules of Warhammer 40,000, and — as a first step — a dual-purpose AI: a playing partner available at any moment for your players, and an objectification tool for your developers and playtesters.

The best way to judge a tool that plays is to watch it play. I am ready for a live demonstration whenever you are.

---

*Cited sources (available on request): Games Workshop Annual Report 2025/26 (revenue, My Warhammer, Warhammer+, World Championships); Hasbro Investor Relations — Magic: The Gathering page (>50M players, >17M Arena accounts); Hasbro Annual Report 2022 (hybrid players, +40%); Hasbro Q4/Full Year 2025 results (WPN stores, Organised Play); Chris Cocks interview, February 2018 (~30M players before Arena); Hasbro/Wizards press release, December 2018 (>35M players); Wizards, March 2019 (~6,000 WPN stores).*
