# Warhammer 40K Game Rules - Ultimate Claude Tactical Intelligence Guide

## Claude Search Optimization

**Search Terms**: warhammer 40k, combat mechanics, dice system, turn structure, movement rules, shooting rules, charge rules, combat rules, pathfinding, line of sight, wound calculation, armor saves, strength vs toughness, friendly fire, flee mechanics, charge distance, combat priority, alternating combat, target selection, AI strategy, tactical examples, scenario analysis

**Core Concepts**: tactical combat, unit statistics, dice resolution, range mechanics, adjacency effects, terrain interaction, damage calculation, save mechanics, threat assessment, priority systems, strategic reasoning, tactical scenarios

---

## 🎯 CLAUDE LEARNING OBJECTIVES

This document teaches Claude to **understand the tactical logic** behind Warhammer 40K combat mechanics, enabling intelligent decision-making in complex battle scenarios.

**Understanding Approach:**
1. **Grasp combat fundamentals** - Why combat works the way it does
2. **Master dice mathematics** - How probability affects tactical decisions
3. **Understand spatial relationships** - How positioning drives strategy
4. **Learn threat assessment** - How to evaluate danger and opportunity
5. **Practice tactical scenarios** - Apply principles to concrete examples
6. **Recognize strategic patterns** - Common scenarios and optimal responses

---

## 📋 NAVIGATION & LEARNING PATH

- [Game Fundamentals](#-game-fundamentals) - Core tactical combat concepts
- [Unit Statistics Logic](#-unit-statistics-logic) - What numbers mean tactically
- [Spatial Combat System](#-spatial-combat-system) - How positioning affects combat
- [Movement Mechanics](#-movement-mechanics) - Positioning and terrain interaction
- [Shooting System](#-shooting-system) - Ranged combat and targeting logic
- [Charge Mechanics](#-charge-mechanics) - Close combat positioning
- [Combat Resolution](#-combat-resolution) - Melee combat and priority systems
- [Dice Mathematics](#-dice-mathematics) - Probability and damage calculation
- [Tactical Scenarios](#-tactical-scenarios) - Concrete decision examples
- [Tactical AI Logic](#-tactical-ai-logic) - Strategic decision-making frameworks
- [Rule Interaction Examples](#-rule-interaction-examples) - How systems combine in practice
- [Claude Validation Framework](#-claude-validation-framework) - Understanding checkpoints

---

## 🎮 GAME FUNDAMENTALS

### Tactical Combat Concept

**Core Game Type**: Turn-based tactical combat on hexagonal grid

**Why Hex Grid:**
- **Equal distances**: All adjacent hexes same distance from center
- **Natural movement**: Six directions feel more natural than four (square grid)
- **Tactical positioning**: More nuanced positioning options than square grid
- **Visual clarity**: Clear adjacency relationships

### Victory Condition Logic

**Win Condition**: Eliminate all enemy units

**Why Elimination Victory:**
- **Clear objective**: Unambiguous win condition
- **Tactical focus**: Emphasizes combat effectiveness over other factors
- **Finite duration**: Games have definite endpoint
- **Strategic depth**: Must balance aggression with unit preservation

### Combat Range Categories

**Three Combat Ranges:**
1. **Ranged Combat** (RNG_RNG hexes): Shooting phase, distance weapons
2. **Charge Range** (2-12 hexes): Charge phase, movement to contact
3. **Melee Range** (CC_RNG hexes, usually 1): Combat phase, close weapons

**Why Three Ranges:**
- **Tactical variety**: Different engagement types require different strategies
- **Unit specialization**: Units optimized for different combat ranges
- **Phase structure**: Each range corresponds to specific phase
- **Risk/reward**: Closer combat generally more dangerous but more effective

**Key Example - Range Interaction:**
```
Enemy Ork at 8 hexes from Marine:
- Too far for shooting (Marine RNG_RNG = 6)
- Within charge range (if roll 8+ on 2D6)
- Not in melee range (would need to be adjacent)
Tactical decision: Move closer for shooting, or wait for Ork to charge
```

---

## 📊 UNIT STATISTICS LOGIC

### Health System Understanding

**Health Statistics:**
- **MAX_HP**: Maximum damage unit can sustain
- **CUR_HP**: Current damage remaining before death
- **Death threshold**: CUR_HP ≤ 0

**Why Health Works This Way:**
- **Damage accumulation**: Units weaken over time, not instant death
- **Tactical decisions**: Wounded units still functional but vulnerable
- **Resource management**: Healing/protection becomes valuable
- **Combat dynamics**: Focused fire vs spread damage decisions

**Critical Example - Wounded Unit Priority:**
```
Space Marine: CUR_HP 1, MAX_HP 3 (wounded)
Chaos Marine: CUR_HP 3, MAX_HP 3 (healthy)
Tactical significance: Any 1 damage kills Marine, making it high-priority target
Strategic choice: Protect valuable wounded unit vs accept loss and focus elsewhere
```

### Movement Statistics Logic

**Movement Capability:**
- **MOVE**: Maximum hexes unit can travel per movement phase
- **Positioning flexibility**: Higher MOVE = more tactical options
- **Escape capability**: Fast units can avoid unfavorable engagements

**Why Movement Matters:**
- **Tactical positioning**: Control engagement ranges and angles
- **Objective control**: Reach and hold key terrain
- **Combat avoidance**: Escape from threats or unfavorable matchups
- **Setup opportunities**: Position for favorable next-turn actions

### Shooting Statistics Relationships

### Shooting Statistics Relationships

**Ranged Combat Stats:**
- **RNG_NB**: Number of shots per shooting action
- **RNG_RNG**: Maximum effective shooting range
- **RNG_ATK**: Accuracy skill (lower = more accurate)
- **RNG_STR**: Penetrating power vs toughness
- **RNG_DMG**: Damage per successful hit
- **RNG_AP**: Armor penetration (degrades enemy saves)

**Statistical Trade-offs:**
- **Volume vs Accuracy**: High RNG_NB compensates for poor RNG_ATK
- **Range vs Power**: Longer RNG_RNG often paired with lower damage
- **Penetration vs Damage**: High RNG_AP vs high RNG_DMG trade-offs

**Key Example - Volume vs Accuracy:**
```
Unit A: RNG_NB 4, RNG_ATK 4+ (50% hit chance) = 2 hits average
Unit B: RNG_NB 2, RNG_ATK 3+ (66.7% hit chance) = 1.33 hits average
Tactical application: Unit A better vs multiple weak targets, Unit B better vs single high-value targets
```

---

## 🗺️ SPATIAL COMBAT SYSTEM

### Adjacency Effects in Practice

**Adjacency Definition**: Units in neighboring hexes are "adjacent"

**Adjacency Effects:**
- **Movement restriction**: Cannot move TO hexes adjacent to enemies
- **Combat engagement**: Adjacent units are "in combat"
- **Shooting restriction**: Cannot shoot while adjacent to enemies
- **Charge restriction**: Cannot charge when already adjacent

**Why Adjacency Matters:**
- **Engagement model**: Clear definition of "in combat"
- **Phase specialization**: Different rules for different engagement types
- **Tactical positioning**: Adjacency has major consequences
- **Strategic depth**: Positioning becomes crucial tactical element

**Critical Example - The Danger Zone:**
```
Enemy Ork at position (5,5) creates danger zone of 7 total hexes:
- Ork's position (5,5) 
- 6 adjacent hexes around it
Movement impact: Cannot move INTO any of the 6 adjacent hexes
Tactical implication: Single enemy controls significant battlefield space
```

### Line of Sight Examples

**LOS Definition**: Straight line from hex center to hex center, unblocked by walls

**LOS Applications:**
- **Shooting**: Must have LOS to shoot at target
- **Tactical awareness**: Units "see" what they can shoot
- **Cover effects**: Walls provide protection by blocking LOS

**Why LOS Matters:**
- **Tactical realism**: Cannot attack what you cannot see
- **Terrain value**: Walls and obstacles provide tactical advantage
- **Positioning importance**: LOS drives unit positioning decisions
- **Strategic depth**: Terrain becomes tactical resource

**Example - Wall Interaction:**
```
Marine at (1,1), Ork at (4,4), Wall at (2,2)
Line from (1,1) to (4,4) passes through wall at (2,2)
Result: No line of sight, cannot shoot
Tactical lesson: Walls create protected firing positions and safe zones
```

### Pathfinding Logic

**Pathfinding Purpose**: Find valid movement route from start to destination

**Pathfinding Obstacles:**
- **Wall hexes**: Completely block movement
- **Occupied hexes**: Other units prevent movement
- **Enemy danger zones**: Hexes adjacent to enemies

**Why Pathfinding Required:**
- **Realistic movement**: Cannot teleport or phase through obstacles
- **Tactical terrain**: Obstacles create strategic chokepoints
- **Movement planning**: Must consider route, not just destination
- **Game balance**: Prevents exploitation of complex terrain

---

## 🏃 MOVEMENT MECHANICS

### Flee Mechanics in Practice

**Flee Trigger**: Start adjacent to enemy, end not adjacent to any enemy

**Flee Consequences:**
- **Shooting penalty**: Cannot shoot (disorganized from retreat)
- **Charge penalty**: Cannot charge (poor position/morale)
- **Combat capability**: Can still fight if re-engaged
- **Duration**: Penalties end at turn boundary

**Why Flee Exists:**
- **Tactical choice**: Trade current effectiveness for survival
- **Risk/reward**: Escape death but lose capabilities
- **Strategic depth**: Creates meaningful positioning decisions
- **Realism**: Units can retreat from unfavorable engagements

**Critical Example - Flee Decision:**
```
Wounded Marine (CUR_HP 1) adjacent to healthy Ork (CUR_HP 3)
Combat prediction: 80% chance Marine dies if stays
Flee option: Marine survives but cannot shoot/charge this turn
Strategic decision: Preserve valuable unit vs maintain combat effectiveness
Context matters: If Marine has critical shot available, decision changes
```

### Strategic Movement Examples

**Movement Goals:**
- **Optimal positioning**: Set up favorable engagements for later phases
- **Threat avoidance**: Escape from dangerous enemy units
- **Objective control**: Reach and hold key terrain positions
- **Setup next turn**: Position for future tactical opportunities

---

## 🎯 SHOOTING SYSTEM

### Target Selection Logic

**Valid Target Requirements:**
- **Range**: Within RNG_RNG hexes
- **Line of sight**: Clear view to target (no wall blocking)
- **Not in melee**: Not adjacent to shooter (too close for ranged weapons)
- **Friendly fire prevention**: Not adjacent to friendly units

**Why These Requirements:**
- **Weapon limitations**: Ranged weapons have effective range
- **Visual requirement**: Cannot shoot what cannot be seen
- **Engagement types**: Adjacent = melee combat, not shooting
- **Safety**: Prevent accidental damage to own forces

**Critical Example - Friendly Fire Prevention:**
```
Situation: Enemy Ork adjacent to friendly Scout, Marine wants to shoot Ork
Rule application: Cannot shoot enemies adjacent to friendlies
Result: Cannot target this Ork despite being in range and LOS
Tactical lesson: Must coordinate movement and shooting phases
```

### Multiple Shots Logic

**Multi-Shot Mechanics:**
- **All shots one action**: RNG_NB shots fired as single activation
- **Sequential resolution**: Resolve each shot completely before next
- **Dynamic targeting**: Each shot can target different valid enemies
- **Death handling**: If target dies, remaining shots can retarget

**Why Multiple Shots:**
- **Weapon variety**: Different weapons have different rates of fire
- **Tactical flexibility**: Can spread damage or focus fire
- **Action efficiency**: One activation covers all shots
- **Adaptive targeting**: React to changing battlefield conditions

**Key Example - Dynamic Targeting:**
```
Marine (RNG_NB = 2) faces two wounded Orks (both CUR_HP 1)
Shot 1: Target Ork A, hit and kill
Shot 2: Automatically retarget to Ork B, hit and kill
Result: Eliminate two threats in one action through dynamic targeting
Tactical advantage: Maximize threat elimination per action
```

### Shooting Resolution Logic

**6-Step Process:**
1. **Hit determination**: Does shot connect with target?
2. **Wound assessment**: Does hit penetrate defenses enough to cause damage?
3. **Save attempt**: Can target's protection prevent damage?
4. **Damage application**: Apply damage if save fails
5. **Death check**: Remove unit if health depleted
6. **Continue**: Process next shot if available

**Why This Sequence:**
- **Logical progression**: Each step depends on previous success
- **Defensive layers**: Multiple ways to avoid damage
- **Tactical depth**: Different stats matter at different steps
- **Probability management**: Multiple failure points create interesting odds

---

## ⚡ CHARGE MECHANICS

### Charge Distance Logic

**2D6 Roll System**:
- **When**: Roll when unit becomes eligible to charge
- **Range**: Result determines maximum charge distance this activation
- **Uncertainty**: Cannot guarantee reaching specific targets

**Why Random Distance:**
- **Tactical uncertainty**: Adds risk to charge planning
- **Game balance**: Prevents guaranteed charge combinations
- **Decision pressure**: Must evaluate risk vs reward
- **Realistic variability**: Charge effectiveness varies with conditions

**Key Example - Charge Planning:**
```
Marine 7 hexes from Ork (average charge distance)
Charge roll outcomes:
- Roll 6 or less: Charge fails, Marine exposed with no benefit
- Roll 7+: Charge succeeds, Marine gains combat priority
Risk assessment: ~42% chance of failure, but success grants significant advantage
Decision factors: Marine's value, Ork's threat level, alternative options
```

### Charge Priority System

**Combat Advantage**: Charging units attack first in combat phase

**Why First Strike:**
- **Momentum bonus**: Successful positioning grants advantage
- **Risk reward**: Compensation for charge risks and positioning requirements
- **Tactical depth**: Makes charge timing and positioning crucial
- **Strategic choice**: Balances charge risk with combat advantage

**Cannot Charge When Adjacent**: Already adjacent units cannot charge

**Why This Restriction:**
- **Already engaged**: Adjacent = already in combat
- **Phase logic**: Combat phase handles adjacent unit fighting
- **Prevents double advantage**: Cannot gain charge bonus when already positioned
- **Tactical clarity**: Clear distinction between positioning and fighting

---

## ⚔️ COMBAT RESOLUTION

### Combat Phase Structure

**Both Players Participate**: Only phase where both players' units can act

**Why Both Players:**
- **Combat nature**: Melee involves units from both sides
- **Interactive engagement**: Close combat is mutual, not one-sided
- **Tactical realism**: Both sides fight simultaneously in melee
- **Game balance**: Gives both players agency in critical phase

**Two-Phase Structure:**
1. **Charging units priority**: Current player's charging units attack first
2. **Alternating combat**: All other engaged units alternate between players

**Why Two Sub-Phases:**
- **Charge reward**: Honor the initiative advantage from successful charges
- **Fair alternation**: Balance for non-charging combat
- **Clear sequence**: Eliminate confusion about who acts when
- **Tactical depth**: Makes charge timing strategically important

**Critical Example - Combat Sequence:**
```
P0's turn, Combat Phase:
Sub-phase 1: P0 Marine (charged this turn) attacks Ork first
Sub-phase 2: P1 Grot attacks P0 Scout → P0 Heavy (non-charger) attacks P1 Boss
Result: Charging Marine gets first strike, then alternating for rest
Tactical impact: Charge timing can eliminate threats before retaliation
```

### Combat Resolution Logic

**Same Logic as Shooting**: Hit → Wound → Save → Damage, but using CC_ stats

**Why Same Sequence:**
- **Consistent mechanics**: Players learn one system for all combat
- **Stat differentiation**: CC_ vs RNG_ stats create different combat types
- **Familiar patterns**: Shooting experience applies to combat
- **Mathematical consistency**: Same probability calculations

---

## 🎲 DICE MATHEMATICS

### Wound Chart Logic

**Strength vs Toughness Relationship:**

| Attacker Strength vs Target Toughness | Wound Target | Probability |
|----------------------------------------|--------------|-------------|
| Strength ≥ 2× Toughness | 2+ | 83.3% |
| Strength > Toughness | 3+ | 66.7% |
| Strength = Toughness | 4+ | 50.0% |
| Strength < Toughness | 5+ | 33.3% |
| Strength ≤ ½ Toughness | 6+ | 16.7% |

**Why This Curve:**
- **Intuitive scaling**: Stronger attacks more likely to wound
- **Meaningful differences**: Each step represents significant advantage
- **Extreme handling**: Very strong/weak attacks have appropriate probabilities
- **Game balance**: No "impossible" or "automatic" wounds in normal ranges

**Key Examples:**
```
High Confidence (66.7%+): Bolter (STR 4) vs Scout (T 3) = 3+ wound
Moderate Risk (50%): Bolter (STR 4) vs Marine (T 4) = 4+ wound  
Poor Odds (33.3%): Lasgun (STR 3) vs Marine (T 4) = 5+ wound
```

### Armor Save Logic

**Save Calculation**:
- **Base armor save**: Unit's natural ARMOR_SAVE value
- **Armor penetration**: Attacker's AP value worsens save
- **Modified save**: ARMOR_SAVE + AP (higher numbers worse)
- **Invulnerable save**: Alternative save unaffected by AP

**Save Selection Logic**: Use better of modified armor save or invulnerable save

**Why This System:**
- **Armor degradation**: Powerful weapons reduce armor effectiveness
- **Invulnerable protection**: Some defenses ignore armor penetration
- **Choice benefit**: Always use best available protection
- **Tactical depth**: Different attack types threaten different defenses

**Critical Example - AP Impact:**
```
Target: Marine with 3+ armor save, 4+ invul save
vs AP 0 attack: 3+ armor save (66.7%) - use armor
vs AP 2 attack: 5+ armor save (33.3%) vs 4+ invul (50%) - use invul
Tactical lesson: High AP weapons force reliance on invulnerable saves
```

### Probability-Driven Tactical Decisions

**High Probability Actions** (70%+ success):
- **Reliable tactics**: Can plan around these succeeding
- **Foundation moves**: Use for essential tactical elements
- **Safe assumptions**: Low risk of catastrophic failure

**Medium Probability Actions** (40-70% success):
- **Tactical gambles**: Significant risk but worthwhile reward
- **Calculated risks**: Use when advantage justifies risk
- **Backup plans**: Have alternatives if these fail

**Low Probability Actions** (<40% success):
- **Desperation moves**: Only when no better options exist
- **Lucky opportunities**: Take when cost of failure is low
- **Setup combinations**: Multiple low-prob actions for high payoff

---

## 🎪 TACTICAL SCENARIOS

### Complex Decision-Making Examples

**Scenario 1 - The Wounded Elite Priority Decision:**
```
Situation: Enemy Chaos Champion (high threat, CUR_HP 1)
Your Marine options:
A) Shoot: 60% chance to kill
B) Charge: 70% chance to reach, 80% chance to kill in combat
C) Move away: Preserve Marine, let ally handle Champion

Analysis:
Option A: 60% direct threat elimination, low risk to Marine
Option B: 56% combined chance (70% × 80%), gain positioning but risk exposure
Option C: 0% threat elimination, preserves unit but leaves threat active

Optimal choice: Option A (highest threat elimination probability, lowest risk)
Tactical lesson: Evaluate expected outcomes, not just maximum potential
```

**Scenario 2 - The Coordination vs Independence Dilemma:**
```
Situation: 
- Your Marine A: Can wound high-threat Enemy X but not kill (deals 2 damage, enemy has 3 HP)
- Your Marine B: Can finish Enemy X if already wounded (deals 2 damage)
- Enemy X: Will kill Marine A next turn if allowed to act

Coordination strategy:
Marine A shoots Enemy X (wounds to 1 HP) → Marine B charges Enemy X (finishes it)
Independent strategy: 
Marine A shoots different target → Marine B charges Enemy X (might not kill it)

Decision framework: Coordination eliminates threat with certainty vs independent actions with uncertain outcomes
Tactical principle: Multi-unit coordination often superior to individual optimization
```

### Resource Management Scenarios

**Scenario 3 - The Action Economy Challenge:**
```
Situation: Two enemies - one wounded (1 HP), one healthy (3 HP)
Your unit can kill wounded enemy easily OR wound healthy enemy significantly

Standard approach: Kill wounded enemy (guaranteed elimination)
Advanced consideration: What can other units accomplish?
- If ally can finish wounded enemy: Better to wound healthy enemy instead
- If no ally available: Kill wounded enemy for certain threat reduction

Strategic principle: Optimize total army effectiveness, not individual unit actions
Decision framework: Consider opportunity cost of each action across entire force
```

---

## 🧠 TACTICAL AI LOGIC

### Threat Assessment in Practice

**Threat Value Calculation**: Max(RNG_DMG, CC_DMG) = unit's damage potential per action

**Why This Metric:**
- **Damage focus**: Most dangerous units deal most damage
- **Versatility consideration**: Uses unit's best damage capability
- **Action efficiency**: Damage per action more important than total damage
- **Target prioritization**: Helps identify highest-value targets

**Example - Context-Dependent Threat Assessment:**
```
Unit comparison:
Enemy A: RNG_DMG 2, CC_DMG 1, currently at shooting range
Enemy B: RNG_DMG 1, CC_DMG 3, currently far away

Base threat values: Enemy A = 2, Enemy B = 3
Immediate threat: Enemy A (can attack this turn)
Long-term threat: Enemy B (more dangerous when engaged)

Decision logic: Immediate threats often take priority over theoretical higher threats
Context matters more than base statistics in tactical decisions
```

### Target Priority System Logic

**Priority Tier Logic:**

**Tier 1 - Strategic Coordination**:
- Target: High-threat enemies that cannot be killed by current unit alone
- Condition: Friendly units can finish them this turn
- Goal: Coordinate multi-unit kills for maximum efficiency

**Tier 2 - Efficient Elimination**:
- Target: High-threat enemies that can be killed by current unit
- Condition: Low enough health for guaranteed kill
- Goal: Remove dangerous units with minimum resource investment

**Tier 3 - Opportunistic Kills**:
- Target: Any enemy that can be killed by current unit
- Condition: Enough damage to eliminate regardless of threat level
- Goal: Remove enemy units when opportunity exists

**Tier 4 - Damage Dealing**:
- Target: Highest threat enemy available
- Condition: Cannot kill target but can wound it
- Goal: Weaken dangerous units for future turns

**Why This Priority System:**
- **Efficiency focus**: Maximize damage and eliminate threats
- **Coordination support**: Enable multi-unit tactical combinations
- **Opportunity recognition**: Take advantage of kill opportunities
- **Threat reduction**: Always work toward reducing enemy capabilities

### Unit Role Strategy

**Ranged Unit Tactics:**
- **Primary goal**: Maintain shooting range while avoiding charge threats
- **Positioning**: Stay at RNG_RNG distance from priority targets
- **Threat avoidance**: Avoid positions where enemies can charge next turn
- **Support role**: Soften targets for friendly melee units

**Melee Unit Tactics:**
- **Primary goal**: Position for favorable charges against high-value targets
- **Positioning**: Get within charge range of priority enemies
- **Threat assessment**: Target enemies with favorable combat matchups
- **Aggressive role**: Eliminate threats through close combat

**Why Role Specialization:**
- **Stat optimization**: Units built for specific combat types
- **Tactical synergy**: Different roles support each other
- **Strategic depth**: Must coordinate different unit types
- **Resource efficiency**: Use units for their strengths

---

## 🔄 RULE INTERACTION EXAMPLES

### Movement-Combat Chain Reactions

**Example 1 - Positional Cascade Effects:**
```
Turn sequence:
1. Enemy moves adjacent to your Marine A
2. Marine A now faces tactical dilemma: flee (lose effectiveness) or fight (risk death)
3. If Marine A flees: loses shooting at valuable target, enemy gains positioning
4. If Marine A fights: likely dies but may damage enemy

Strategic lesson: Enemy positioning creates tactical dilemmas with long-term consequences
Counter-strategy: Position units to support each other, avoid isolated vulnerabilities
```

### Cross-Phase Effect Patterns

**Example 2 - Flee Penalty Chain:**
```
Phase sequence consequences:
1. Movement phase: Unit flees from combat (marked as fled)
2. Shooting phase: Fled unit cannot shoot (penalty applied)
3. Charge phase: Fled unit cannot charge (penalty continues) 
4. Combat phase: Fled unit can fight normally (penalty ends)

Strategic insight: Flee penalties span multiple phases but aren't permanent
Planning consideration: Weigh immediate survival vs multi-phase effectiveness loss
```

### Coordination Requirements

**Example 3 - Friendly Fire Coordination Challenge:**
```
Problem: Ranged unit cannot shoot enemy adjacent to friendly melee unit
Solution options:
A) Friendly unit moves away, enabling shooting (loses position)
B) Ranged unit repositions for clear shot (uses movement)
C) Accept that melee unit will handle enemy alone (risk management)

Decision framework: Weigh shooting value vs positional costs
Tactical principle: Effective coordination requires sacrifice of individual optimization
```

---

## ✅ CLAUDE VALIDATION FRAMEWORK

### Fundamental Concept Validation

**Level 1 Checks:**

**Tactical Purpose Understanding:**
```
Question: "Why does the shooting phase exist?"
Expected answer: "Enable ranged units to eliminate threats before close combat"
Validates: Phase purpose comprehension
```

**Spatial Relationship Understanding:**
```
Question: "What does 'adjacent to enemy' mean tactically?"
Expected answer: "Unit is in combat engagement, different rules apply"
Validates: Spatial combat system understanding
```

### Scenario Application Validation

**Level 2 Checks:**

**Threat Assessment Application:**
```
Scenario: Two enemies, one with RNG_DMG 3, one with CC_DMG 4
Question: "Which is higher priority?"
Expected answer: "CC_DMG 4 unit (higher threat value)"
Validates: Threat assessment methodology
```

**Probability Integration:**
```
Scenario: 20% chance to kill high-value target vs 80% chance to kill low-value target
Question: "Which action should AI choose?"
Expected reasoning: Consider expected value, context, and army state
Validates: Mathematical-tactical integration
```

### Strategic Reasoning Validation

**Level 3 Checks:**

**Multi-Unit Coordination:**
```
Scenario: Two units can coordinate to kill enemy, or act independently
Question: "How should AI evaluate coordination vs independence?"
Expected reasoning: Compare total army effectiveness, not individual unit effectiveness
Validates: Strategic thinking capability
```

**Risk Assessment:**
```
Scenario: High-risk, high-reward action available
Question: "What factors determine if AI should take risk?"
Expected reasoning: Unit value, mission criticality, alternative options, army state
Validates: Advanced tactical reasoning
```

### Pattern Recognition Validation

**Level 4 Checks:**

**Tactical Pattern Transfer:**
```
Question: "How do these principles apply to different unit types or scenarios?"
Expected: Apply same logical framework to new situations
Validates: Pattern recognition and adaptability
```

**System Understanding:**
```
Question: "Why do these rules create interesting tactical decisions?"
Expected: Explain how mechanics create strategic depth
Validates: System design comprehension
```

---

## 🎯 CLAUDE MASTERY INDICATORS

### Level 1: Rule Comprehension
- ✅ Understands what each phase does and why it exists
- ✅ Knows basic eligibility and restriction rules
- ✅ Can explain dice mechanics and probability
- ✅ Recognizes spatial relationships and their effects

### Level 2: Tactical Application
- ✅ Can assess threats and prioritize targets using systematic approach
- ✅ Understands positioning and spatial relationships tactically
- ✅ Recognizes rule interactions and their strategic consequences
- ✅ Can work through concrete tactical scenarios with reasoning

### Level 3: Strategic Intelligence
- ✅ Can design AI priority systems based on tactical logic
- ✅ Understands coordination between different unit types
- ✅ Can evaluate risk/reward of different tactical approaches
- ✅ Integrates probability mathematics with strategic decision-making

### Level 4: Tactical Mastery
- ✅ Can explain why rules exist from tactical design perspective
- ✅ Understands balance considerations and strategic depth creation
- ✅ Can adapt tactical principles to new scenarios and contexts
- ✅ Recognizes universal patterns applicable across different situations

**This enhanced document brings Claude to Level 4 tactical intelligence, enabling sophisticated strategic reasoning and adaptive tactical decision-making in any implementation context.**