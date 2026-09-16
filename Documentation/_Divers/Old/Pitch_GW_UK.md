# Balancing Warhammer 40,000 by Measurement

*Presentation document — Games Workshop*

---

## ⚡ Why now

Until recently, players who wanted to play Warhammer 40,000 remotely went through a general-purpose
physics sandbox: modelled miniatures, terrain, a tape measure, dice. And nothing else. The software
knows no rules. Players measure themselves, remember themselves, settle their own disagreements,
and trust each other.

That solution is no longer available. The need remains — and today it has no answer.

This document does not propose to replace it. It proposes something else: **an engine that knows
the rules, applies them, and makes mistakes impossible rather than leaving them to be argued out
between players.** The gap between the two is the gap between a car park and a racing circuit.

And it is an offering you control: it plays your rules, in your setting, with your approvals —
instead of a workaround you have no hold over.

What follows describes that same system and the internal use it makes possible: measuring the
game's balance.

## 1. A problem that was never solved — because it cannot be solved by hand

For forty years, the most persistent criticism levelled at Warhammer 40,000 has been neither its
setting, nor its miniatures, nor its rules: it is **balance**.

Let me clear up a misunderstanding first. This is not a failure of care, nor of competence. It is
a **mathematical wall**.

With several hundred available units and a 2000-point budget, the number of legal army lists runs
into the billions. The number of possible matchups is that number squared. And each matchup still
depends on terrain, mission, deployment, and decisions taken turn after turn.

No human playtest programme can cover that space. Not with ten testers, not with a thousand. It
is not a matter of effort — it is a matter of order of magnitude. Imbalance is not an isolated
mistake that harder work would have avoided: it is the inevitable consequence of a possibility
space no human team can explore.

**A problem of this kind is not solved by more rigour. It is solved by changing instrument.**

## 2. Why the current tools cannot get there

You already balance continuously — points updates, balance dataslates. The principle is right. It
is the **data** that is structurally insufficient:

- **It arrives too late.** Tournament feedback comes months after publication. Players have
  already lived through the imbalance — and the reputation is already made.
- **It is biased.** Only competitive players report results. And only already-popular lists get
  measured: a unit nobody plays generates no data, and therefore stays invisible — when its
  absence *is* precisely the symptom.
- **It is not counterfactual.** Tournament data tells you what happened. It never tells you what
  would have happened had that unit cost fifteen points less. Yet that is the only question that
  matters when deciding.
- **It covers almost nothing.** A few thousand games a season, across billions of combinations.

Playtesting and tournament data are not bad. They are simply **too slow, too narrow and too
retrospective** for the size of the problem.

## 3. What I bring: an AI that already plays Warhammer 40,000

This is not a concept or a feasibility study. It is a working system today:

- A **complete game engine**: movement, shooting, charging, close combat, terrain, objectives,
  three-dimensional line of sight, special weapon rules, phases and battle round.
- **Two playable modes**: against another player, or against the AI — with replay and game
  analysis.
- A **reinforcement-learning artificial intelligence** that plays the game — it deploys,
  manoeuvres, shoots, charges, fights and contests objectives.

And above all, one architectural choice that is the heart of this entire document: **the AI reads
unit characteristics before deciding.** It does not memorise "how to play Intercessors". It reads
a stat block — profile, weapons, special rules — exactly as a player would, then decides. It can
therefore handle a unit it has **never** encountered.

That is the hard part, and it is done. The consequence is decisive: **adding a unit or a rule
does not require rebuilding the AI.** The system absorbs new content.

What remains ahead is substantial but understood work: completing the catalogue of rules and
units, and providing training time. No research blocker. Time and resources.

**And the engine's reliability is not a technical detail.** A balance measurement is only worth as
much as the engine that produces it: if the rules are misapplied, everything else in this document
is worthless. That is why verification here is handled as it would be in a system where a mistake
is expensive:

- **7,113 automated tests, named after the official rules they check.** Pick a rule and I will
  show you the test that locks it down — it is readable without knowing how to code.
- **Every test is validated by deliberately reintroducing the defect** it is meant to catch. A
  test that passes first time proves nothing; you verify that it fails when it ought to.
- **Entire games played at random, continuously**, to flush out inconsistencies nobody thought to
  test — including sequences of actions no player would ever attempt. These tests do not look for a
  result, they look for a contradiction.
- **No disabled tests.** Nothing is set aside until there is time for it.

## 4. From "it plays" to "it balances" — four steps

**Step 1 — The machine composes armies.**
Thousands of legal lists, all at the same budget, including ones nobody has ever tried. That
alone is coverage beyond the reach of any playtest.

**Step 2 — It plays.**
Hundreds of thousands of games, in parallel, with no display and no human. A game that takes
three hours on a table takes a fraction of a second here.

**Step 3 — It measures what survives competition.**
Not "who won": average win rate depends entirely on which opponents were selected, so it is both
manipulable and misleading. The right question is: **which armies are left standing once everyone
optimises?** A unit appearing in 98% of surviving lists is underpriced. A unit that never appears
is overpriced. And two unremarkable units whose pairing wins more than the sum of their
contributions: that is an abusive combination, detected before a player finds it.

**Step 4 — It searches for the right price.**
This is the step that makes the tool useful rather than merely interesting. The machine changes
the price, re-runs the simulation, and repeats until the unit becomes **one option among
several** — neither compulsory nor pointless. It does not tell you "this unit is too strong". It
tells you **what it should cost**.

## 5. What a game designer receives

A report readable in five minutes, not an engineering file *(illustrative figures)*:

| Unit | Current price | Recommended | Presence in optimal armies |
|---|---|---|---|
| Intercessor | 20 | **17** | 98% — auto-include, clearly underpriced |
| Dreadnought | 135 | 135 | 41% — healthy, no change |
| Terminator | 180 | **150** | 2% — effectively never played, dormant range |

> ⚠️ **Combination detected**: *Apothecary + Terminators*. Each is correctly priced on its own.
> Together they win 23 percentage points more than the sum of their contributions. Likely cause:
> the healing rule cancels the unit's intended weakness.

And one nuance most approaches miss: **a perfect AI is not a human player.** A unit that is hard
to handle will look excellent to a machine and disappoint your players. So we replay the same
matchups with a deliberately degraded AI. If the unit collapses, it is not mispriced — it is
**skill-intensive**. The remedy is not the same, and that distinction is exactly the one a
designer needs to make.

## 6. What this changes for Games Workshop

- **Balance before publication, not after.** Imbalance is corrected during design, not in an
  emergency dataslate three months later. What changes is not only the game — it is **when** you
  learn about the problem.
- **Test a rule before it exists.** Any new rule can be simulated before it is written,
  illustrated, printed. The cost of a late reversal is yours; here it becomes a compute line.
- **Wake the dormant range.** A unit nobody plays is a miniature nobody buys. The tool identifies
  those units — including the ones that generate no tournament data today, precisely because
  nobody plays them.
- **A permanent need, not a one-off purchase.** Every codex, every edition, every season recreates
  the problem. The instrument serves indefinitely.
- **Transferable to your other systems** — Age of Sigmar, Kill Team, Necromunda. The engine
  changes; the method does not.

## 7. The same engine answers a second problem: bringing new players in

The two armies my AI trains on are not chosen at random: **they are the ones from the 11th edition
starter set.**

Consider a new player. They are interested, they are on their own, nobody around them knows the
game, and there is £200 in front of them. Their barrier is not the price: it is learning a game of
this complexity alone, with no partner and nobody to correct their mistakes. Many give up at
exactly that point — not for lack of desire, but for lack of an opponent.

What the AI puts in a shop assistant's mouth:

> *"Here, take this address. It's free. You play with the miniatures from the box, and you learn
> the rules as you play."*

- An opponent **available immediately**, with no need to find one.
- Rules learned **by playing**, not by reading — the only method that actually works.
- They play **exactly the units they are about to buy**, not an abstract demo.
- And an AI that is still imperfect is an **ideal** opponent for a beginner: here it is not a
  limitation, it is the right difficulty.

It is measurable, and quickly: conversion rate on the starter set, with and without the tool.

The decisive point is this: **this application waits for nothing.** It requires neither the
complete catalogue nor months of additional training — it rests on exactly what already exists,
those two armies and this AI. Balancing is a programme of work; onboarding is available now.

## 8. A subscription people don't cancel

This same product already has a channel at your end: a subscription service, a customer base that
already pays, distribution in place. There is nothing to build around it — no channel, no billing,
no customer acquisition.

What it offers today is content that is **consumed**: you watch it, then wait for the next thing. A
game is **practised** — every week, indefinitely.

That distinction decides whether a subscription lives or dies. **A service is not judged on what
makes people sign up, but on what stops them cancelling.** A catalogue you have finished watching
retains nobody; a game in progress brings the player back. You would not be adding one more piece
of content: you would be adding a reason to stay.

What I observed with the players I showed it to: they did not ask whether the game would come out
one day. They asked how to get access, and what it would cost. That is not market research — it is
what I saw, unprompted, every time.

And it is the only one of the three applications whose revenue can be calculated directly.
Balancing produces a diffuse saving, onboarding a conversion that is hard to isolate; a
subscription is recurring revenue — attributable and projectable.

A single engine that balances the game, brings new players into it, and gives your online offering
a reason to be renewed is not a tool: it is infrastructure.

## 9. What the simulation takes off your hands — and what it leaves you

Today, testing a balance change means playing games. And playing a game introduces two problems
nobody knows how to eliminate:

- **The players' skill.** A result depends on them as much as on the rules. Two unevenly matched
  testers, and the unit under test looks strong or weak with no way to tell which caused what.
- **The blind spot.** An interaction nobody thought to try stays invisible — until ten thousand
  players find it after publication.

**In simulation, the AI plays at the same level on both sides of the table. Player skill stops
being a variable.** What remains in the difference between results is the rules and the points:
exactly what you are trying to measure, and nothing else. This is not an argument from authority,
it is experimental control.

And a game takes one second. That change of scale changes the nature of the work: instead of
checking a handful of hypotheses picked in advance, you sweep the space — including the
combinations nobody would have thought of, which are precisely the ones that hurt.

**What does not change: you keep control.** Your designers define the reference lists, choose
which matchups to explore, and decide on the adjustments. The tool decides nothing and replaces no
judgement — it has no intent, no vision of the game, no taste. What it takes off your hands is the
work nobody wants: playing hundreds of games to test a hunch, and the standing fear of having
missed a combination the community will find on your behalf.

And something follows from that which matters beyond the studio: a balance decision stops being a
publisher's opinion set against a player's opinion. It rests on a measurement, made at equal skill
on both sides, across a volume of games no community could ever reach. The permanent controversy
over balance wears down the game's reputation as much as the imbalance itself; this is the first
lever that addresses it at the root.

Finally, **the same AI can be given back to the players** — as a training partner, a
tournament-preparation opponent, or a list-analysis tool. It is also, incidentally, a product.

## 10. Where the project stands, without embellishment

**Done:** the game engine, the playable interface, the automated replay and analysis pipeline, and
the AI architecture that reads unit characteristics — the foundation everything in this document
depends on.

**Missing:** the AI plays, but it does not yet play well enough for its verdicts to carry
authority. Measurement quality is capped by the strength of the player — I would rather state that
plainly than let you discover it. Also missing: the army generator, the analysis layer, and the
completion of the unit and rule catalogue.

**Why that gap is not a technical doubt:** nothing that remains requires a discovery. It requires
content to be entered, and compute time for training. Those are resources, not unknowns. That is
exactly why I am coming to you: I have built alone the part that cannot be bought, and I lack the
part that can.

## 11. What I am proposing

I am not here to negotiate rights today. The setting is yours, and the prototype would only make
sense in your hands.

What I bring is the **instrument**: a simulation engine and an AI able to measure what forty years
of playtesting could not reach — and the potential to turn your oldest criticism into a selling
point.

I am available for a live demonstration: the AI plays, you watch.
