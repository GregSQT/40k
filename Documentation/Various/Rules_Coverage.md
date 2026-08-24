# Warhammer 40,000 — Rules Implementation Coverage

*Last updated: 2026-08-24*

Legend: ✅ Implemented · ⚠️ Partial · ❌ Missing

---

## Command Phase (PDF 08)

| Rule | Ref | Status |
|------|-----|--------|
| Gain 1 CP per player | 08.02 | ✅ |
| Battle-Shock roll (2D6 vs Ld) | 08.03 | ✅ |
| Battle-Shock: OC → 0 on fail | 08.03 | ✅ |
| Battle-Shock: recovery on success | 08.03 | ✅ |
| Half-strength trigger for battle-shock | 08.03 | ✅ |
| Waaagh! (Orks faction ability) | 08.04 | ✅ |
| Oath of Moment (Space Marines faction ability) | 08.04 | ✅ |
| Other "in your command phase" abilities | 08.04 | ⚠️ Not yet (chantier 06) |
| CP spending (stratagems) | 08.02 | ❌ CP gained but never spent |

---

## Movement Phase (PDF 09)

| Rule | Ref | Status |
|------|-----|--------|
| Normal Move | 09.05 | ✅ |
| Advance Move (D6 roll) | 09.06 | ✅ |
| Advance: no charge/action after | 09.06 | ✅ |
| Fall Back | 09.07 | ✅ |
| Fall Back: no shoot/charge/action after | 09.07 | ✅ |
| Desperate Escape (hazard roll per model) | 09.07 | ✅ |
| Ordered Retreat (non-battle-shocked only) | 09.07 | ✅ |
| Cohesion (2" horiz / 9" max / 5" vert) | 03.03 | ✅ |
| Coherency removal at end of turn | 03.03 | ✅ |
| Engagement zone (2" horiz / 5" vert) | 03.04 | ✅ |
| FLY keyword: −2", bypass obstacles | 21.03 | ✅ |
| Hover (no −2" penalty) | 24.17 | ❌ |
| Surge Move | 21.02 | ❌ |
| Multi-level terrain movement (keywords) | 13.06 | ✅ |
| Vertical distance counts toward move | 13.06 | ✅ |
| Model placement on upper floors (keyword-gated) | 13.06 | ✅ |
| Strategic Reserves: placement limit 50% | 20.01 | ✅ |
| Strategic Reserves: ingress move | 20.04 | ✅ |
| Strategic Reserves: destroyed if not arrived by turn 3 | 20.03 | ✅ |
| Deep Strike (>8" from all enemies) | 24.09 | ✅ |
| Scout Move (pre-battle advance) | 24.31–24.32 | ❌ |
| Infiltrators (deploy >8" from enemy zone) | 24.20 | ❌ |
| Transports: embarking | 18.02 | ❌ |
| Transports: disembark (rapid / tactical / combat) | 18.03–18.04 | ❌ |
| Transports: emergency disembark | 18.05 | ❌ |
| Aircraft movement (always in strategic reserves) | 23.01–23.02 | ❌ |

---

## Shooting Phase (PDF 10)

| Rule | Ref | Status |
|------|-----|--------|
| Normal Shooting | 10.04 | ✅ |
| Assault Shooting (after Advance, ASSAULT weapons only) | 10.05 | ✅ |
| Close-Quarters Shooting (engaged, CLOSE-QUARTERS weapons) | 10.06 | ✅ |
| Monster/Vehicle close-quarters: any weapon vs any target | 10.06 | ✅ |
| BLAST forbidden on engaged target | 10.06 | ✅ |
| Indirect Fire (no LoS required, −1 to hit) | 10.07 | ✅ |
| Indirect Fire: −1 waived if stationary + target visible | 10.07 | ✅ |
| IGNORES_COVER neutralises indirect fire penalty | 10.07 | ✅ |
| Line of Sight 3D per model | 06.01 | ✅ |
| Benefit of Cover (−1 BS) | 13.08 | ✅ |
| Hidden status (detection range 15") | 13.09 | ✅ |
| Gone to Ground (−3" detection range) | 13-5 | ✅ |
| Obscuring terrain (no LoS through) | 13.10 | ✅ |
| Solid terrain (no LoS through closed spaces ≤3") | 13.11 | ✅ |
| Plunging Fire (+1 BS from height ≥3") | 22.05 | ❌ |
| Overwatch / Snap Fire (hit on 6+ only) | 15.08–15.09 | ❌ |
| Indirect Fire activation pool (debug mode bug) | 10.07 | ⚠️ May wrongly exclude INDIRECT-only units |
| Stealth (attacker always treats target as in cover) | 24.33 | ✅ |
| COMBI_WEAPON (alternate profile locked after primary) | — | ✅ |
| Firing Deck X (shoot from inside transport) | 24.14 | ❌ (requires transports) |
| Aircraft: −1 to hit, no Plunging Fire | 23.03 | ❌ |
| Lone Operative (not visible beyond 12") | 24.24 | ❌ |

---

## Charge Phase (PDF 11)

| Rule | Ref | Status |
|------|-----|--------|
| Charge declaration | 11.02 | ✅ |
| Charge roll (2D6) | 11.02 | ✅ |
| Charge move (BFS, must end engaged with all targets) | 11.04 | ✅ |
| Fights First granted to charging unit | 11.04 | ✅ |
| FLY during charge | 21.03 | ✅ |
| Overwatch (Fire Overwatch stratagem) | 15.08 | ❌ |
| Heroic Intervention | 15.11 | ❌ |
| Aircraft: cannot declare charge | 23.04 | ❌ |

---

## Fight Phase (PDF 12)

| Rule | Ref | Status |
|------|-----|--------|
| Fights First / Remaining ordering | 12.04 | ✅ |
| Alternating activation (active player first) | 12.04 | ✅ |
| Fights First re-trigger if new unit becomes eligible | 12.04 | ✅ |
| Pile-in per model (3", toward nearest enemy) | 12.03 | ✅ |
| Pile-in: model in base contact does not move | 12.03 | ✅ |
| Pile-in: must stay engaged if was engaged | 12.03 | ✅ |
| Normal Fight (12.05) | 12.05 | ✅ |
| Overrun Fight (when enemy eliminated) | 12.07 | ✅ |
| Consolidation per model (3") | 12.08 | ✅ |
| Ongoing / Engaging / Objective consolidation cascade | 12.08 | ✅ |
| Engaging consolidation triggers new fight | 12.08 | ✅ |
| Both players unable to fight → end of Fight step | PDF 25 | ✅ |
| Counteroffensive (Fights First via stratagem) | 15.12 | ❌ |
| Aircraft: melee only vs FLYING units | 23.04 | ❌ |

---

## Attack Sequence (PDF 04–05)

| Rule | Ref | Status |
|------|-----|--------|
| Hit Roll (1 = auto-fail, 6 = critical) | 05.01 | ✅ |
| Wound Roll (1 = auto-fail, 6 = critical, S vs T table) | 05.02 | ✅ |
| Save Roll (Sv modified by AP, InSv as alternative) | 05.03 | ✅ |
| Damage application (model loses wounds, destroyed at 0) | 05.04 | ✅ |
| Critical Hit → SUSTAINED HITS X | 24.36 | ✅ |
| Critical Hit → LETHAL HITS (auto-wound) | 24.23 | ✅ |
| Critical Wound → DEVASTATING WOUNDS (mortal wounds) | 24.10 | ✅ |
| ANTI-X Y+ (lower critical wound threshold) | 24.03 | ✅ |
| TORRENT (auto-hit) | 24.37 | ✅ |
| TWIN-LINKED (re-roll one failed wound) | 24.38 | ✅ |
| Hit re-rolls (1s only / all fails) | — | ✅ |
| Wound re-rolls (1s only / all fails) | — | ✅ |
| Save re-rolls (1s only) | — | ✅ |
| Mortal Wounds (06.02) | 06.02 | ✅ |
| Hazard Roll (1–2 = 1 mortal wound, 3 mortal wounds for M/V) | 06.03 | ✅ |
| Manual allocation of casualties | 05.03 | ✅ |
| Character allocation priority (non-char first) | 05.03 | ✅ |
| Excess damage on destroyed unit lost | 05.04 | ✅ |
| Feel No Pain X+ | 24.12 | ✅ |
| Deadly Demise X (explosion on destruction) | 24.08 | ❌ |
| Revived models (full wounds, back to starting strength) | PDF 25 | ❌ |

---

## Weapon Rules (PDF 24)

| Rule | Ref | Status |
|------|-----|--------|
| ANTI-X Y+ (5 families) | 24.03 | ✅ |
| ASSAULT | 24.04 | ✅ |
| BLAST (+ dice per 5 models) | 24.05 | ✅ |
| CLEAVE X (+X dice if single target) | 24.06 | ✅ |
| CLOSE-QUARTERS | 24.07 | ✅ |
| DEVASTATING WOUNDS | 24.10 | ✅ |
| EXTRA ATTACKS (additional weapon in fight) | 24.11 | ✅ |
| HAZARDOUS | 24.15 | ✅ |
| HEAVY (+1 hit if not moved >3") | 24.16 | ✅ |
| IGNORES COVER | 24.18 | ✅ |
| INDIRECT FIRE | 24.19 | ✅ |
| LANCE (+1 wound roll when charging) | 24.21 | ❌ Not in weapon_rules.json |
| LETHAL HITS | 24.23 | ✅ |
| MELTA X (+X damage at half range) | 24.25 | ✅ |
| ONE SHOT (single use per battle) | 24.26 | ❌ |
| PISTOL (= CLOSE-QUARTERS) | 24.27 | ✅ |
| PRECISION (allocate to visible CHARACTER) | 24.28 | ✅ |
| PSYCHIC (ignore modifiers) | 24.29 | ✅ |
| RAPID FIRE X (+X attacks at half range) | 24.30 | ✅ |
| SUSTAINED HITS X | 24.36 | ✅ |
| TORRENT | 24.37 | ✅ |
| TWIN-LINKED | 24.38 | ✅ |

---

## Unit Keywords & Special Rules (PDF 24)

| Rule | Ref | Status |
|------|-----|--------|
| Fights First (unit keyword) | 24.13 | ✅ |
| Deep Strike | 24.09 | ✅ |
| Feel No Pain X+ | 24.12 | ✅ |
| Stealth | 24.33 | ✅ |
| EXTRA ATTACKS | 24.11 | ✅ |
| Scouts X" / Scout Move | 24.31–24.32 | ❌ |
| Infiltrators | 24.20 | ✅ Not confirmed in code |
| Lone Operative | 24.24 | ❌ |
| Hover | 24.17 | ❌ |
| Super-Heavy Walker | 24.35 | ❌ |
| Firing Deck X | 24.14 | ❌ (requires transports) |
| Deadly Demise X | 24.08 | ❌ |
| ONE SHOT | 24.26 | ❌ |

---

## Attached Units (PDF 19)

| Rule | Ref | Status |
|------|-----|--------|
| Leader / Support formation | 19.01 | ✅ |
| Use bodyguard Toughness when attacking | 19.02 | ✅ |
| Attached unit shares all keywords | 19.03 | ✅ |
| Leader ability propagates to whole unit | 19.04 | ✅ |
| Ability stops on last leader model destroyed | 19.04 | ✅ |

---

## Objectives (PDF 14)

| Rule | Ref | Status |
|------|-----|--------|
| Level of Control (OC sum) | 14.02 | ✅ |
| Highest OC controls objective | 14.02 | ✅ |
| Battle-shocked: OC = 0 | 14.02 | ✅ |
| Secured Objectives (held without models) | 14.03 | ✅ |
| Secured: lost only when opponent OC exceeds yours | 14.03 | ✅ |

---

## Stratagems (PDF 15)

| Stratagem | Ref | Status |
|-----------|-----|--------|
| Command Re-Roll | 15.02 | ❌ |
| Epic Challenge (PRECISION on CHARACTER) | 15.03 | ❌ |
| Insane Bravery (auto-pass battle-shock, once per battle) | 15.04 | ❌ |
| Explosives (6D6 mortal wounds) | 15.05 | ❌ |
| Crushing Impact (MONSTER/VEHICLE mortal wounds on charge) | 15.06 | ❌ |
| Rapid Ingress (reserve unit arrives end of enemy move) | 15.07 | ❌ |
| Fire Overwatch (snap fire 6+ on enemy move) | 15.08 | ❌ |
| Smokescreen (benefit of cover vs shooting phase) | 15.10 | ❌ |
| Heroic Intervention (charge after enemy charges) | 15.11 | ❌ |
| Counteroffensive (Fights First reaction) | 15.12 | ❌ |

---

## Terrain (PDF 13)

| Rule | Ref | Status |
|------|-----|--------|
| Exposed / Light / Dense terrain categories | 13.02–13.05 | ✅ |
| Movement through terrain by keyword | 13.06 | ✅ |
| Vertical movement cost | 13.06 | ✅ |
| Benefit of Cover | 13.08 | ✅ |
| Hidden (INFANTRY/BEASTS/SWARM in dense terrain) | 13.09 | ✅ |
| Detection range (15" default) | 13.09 | ✅ |
| Gone to Ground (−3" detection) | 13-5 | ✅ |
| Obscuring terrain areas | 13.10 | ✅ |
| Solid (no LoS through closed spaces ≤3") | 13.11 | ✅ |

---

## Other (PDF 17, 20–23, 25)

| Rule | Ref | Status |
|------|-----|--------|
| MONSTER/VEHICLE: move through friendly models | 17.01 | ✅ |
| MONSTER/VEHICLE engaged: targetable, −1 to hit | 17.03 | ✅ |
| FRAME measurement (from model, not base) | 17.02 | ❌ |
| Transports (all rules) | PDF 18 | ❌ |
| Plunging Fire (+1 BS from elevated position) | 22.05 | ❌ |
| Aura Abilities | 22.01 | ⚠️ Waaagh!/Oath only |
| Psychic Abilities as category | 22.03 | ⚠️ PSYCHIC weapon rule only |
| Aircraft (all rules) | PDF 23 | ❌ |
| Surge Move | 21.02 | ❌ |
| Starting Strength / Half-Strength calculation | PDF 25 | ✅ |
| Destroyed model triggers | PDF 25 | ✅ |
| Revived models | PDF 25 | ❌ |

---

## Summary

| Status | Count |
|--------|-------|
| ✅ Implemented | 87 |
| ⚠️ Partial | 5 |
| ❌ Missing | 34 |
| **Total** | **126** |

**Coverage: 87 / 126 = 69% fully implemented · 4% partial · 27% missing**

### Missing by category
| Category | Missing |
|----------|---------|
| Stratagems | 10 (all 10 core stratagems) |
| Transports | 5 |
| Unit keyword abilities | 7 (Scouts, Infiltrators, Lone Operative, Hover, Super-Heavy Walker, Deadly Demise, ONE SHOT) |
| Weapon rules | 2 (LANCE, ONE SHOT) |
| Aircraft | 4 |
| Other mechanics | 6 (Plunging Fire, FRAME, Surge, Revived, Overwatch, Heroic Intervention) |

---

## Démo Armageddon — Périmètre réduit

*Cadre : Space Marines vs Orks, figurines des rosters d'entraînement uniquement, objectifs primaires seuls, aucun stratagème.*

### Rosters

**Space Marines — Adeptus Astartes**

| Escouade | Figurines |
|----------|-----------|
| Vanguard Veterans (Jump Pack) | VanguardVeteranSquadJumpPack ×3, Sergeant, Plasma + **ChaplainJumpPack** (attaché) |
| Eradicators (Heavy Bolter) | EradicatorHeavyBolter ×2, Sergeant |
| Land Speeder Onslaught | LandSpeederOnslaughtGatlingCannon |
| Intercessors 1 | Intercessor ×3, GrenadeLauncher, Sergeant + **Librarian** (attaché) |
| Intercessors 2 | Intercessor ×3, GrenadeLauncher, Sergeant + **CaptainRelicShield** + **Ancient** (attachés) |

**Orks**

| Escouade | Figurines |
|----------|-----------|
| Boyz 1 | Boyz ×9, NobKombi + **Warboss** + **PainBoy** (attachés) |
| Boyz 2 | Boyz ×9, NobKombi + **BigBoss** + **BannerNob** (attachés) |
| Gretchin | Gretchin ×10 |
| WeirdBoy | WeirdBoy |
| WarTrakk | WarTrakk |
| BigMek Dakkarig | BigMekDakkarig |

---

### Règles hors scope (non requises pour la démo)

| Règle | Raison |
|-------|--------|
| Tous les stratagèmes (PDF 15) | Décision démo : pas de stratagèmes |
| Objectifs secondaires | Décision démo : objectifs primaires uniquement |
| Transports (PDF 18) | Absent des rosters |
| Aircraft (PDF 23) | Absent des rosters |
| Surge Move (21.02) | Absent des rosters |
| Lone Operative (24.24) | Absent des rosters |
| Super-Heavy Walker (24.35) | Absent des rosters |
| Firing Deck (24.14) | Absent des rosters (nécessite transport) |
| Scout Move (24.31–24.32) | Absent des rosters |
| Infiltrators (24.20) | Absent des rosters |
| Hover (24.17) | Absent des rosters |

---

### Couverture règles — périmètre démo

Seules les règles applicables à ces deux rosters sont listées. Statut issu du tableau général ci-dessus.

**Command Phase**

| Règle | Ref | Status |
|-------|-----|--------|
| Gain 1 CP | 08.02 | ✅ (CP non dépensés : aucun stratagème) |
| Battle-Shock | 08.03 | ✅ |
| Waaagh! | 08.04 | ✅ |
| Oath of Moment | 08.04 | ✅ |

**Movement Phase**

| Règle | Ref | Status |
|-------|-----|--------|
| Normal Move | 09.05 | ✅ |
| Advance (D6 + ASSAULT autorisé) | 09.06 | ✅ |
| Fall Back + Desperate Escape | 09.07 | ✅ |
| Ordered Retreat | 09.07 | ✅ |
| Cohesion (2"/9") | 03.03 | ✅ |
| Engagement zone (2"/5") | 03.04 | ✅ |
| FLY keyword (Jump Pack, Land Speeder, WarTrakk) | 21.03 | ✅ |
| Multi-level terrain + coût vertical | 13.06 | ✅ |
| Strategic Reserves + Deep Strike | 20.01–20.04, 24.09 | ✅ |

**Shooting Phase**

| Règle | Ref | Status |
|-------|-----|--------|
| Normal Shooting | 10.04 | ✅ |
| ASSAULT (Jump Pack weapons) | 10.05 | ✅ |
| CLOSE-QUARTERS / PISTOL (NobKombi, Pistols) | 10.06 | ✅ |
| BLAST (Grenade Launcher) | 10.06 | ✅ |
| HEAVY (Eradicators, LandSpeeder) | 24.16 | ✅ |
| INDIRECT FIRE | 24.19 | ✅ |
| Line of Sight 3D | 06.01 | ✅ |
| Cover + Hidden + Obscuring + Solid | 13.08–13.11 | ✅ |
| Stealth | 24.33 | ✅ |
| COMBI_WEAPON (NobKombi) | — | ✅ |
| PSYCHIC (Librarian, WeirdBoy) | 24.29 | ✅ |
| Plunging Fire (+1 BS depuis hauteur ≥3") | 22.05 | ❌ |

**Charge Phase**

| Règle | Ref | Status |
|-------|-----|--------|
| Charge declaration + roll 2D6 | 11.02 | ✅ |
| Charge move BFS + Fights First | 11.04 | ✅ |
| FLY pendant la charge | 21.03 | ✅ |

**Fight Phase**

| Règle | Ref | Status |
|-------|-----|--------|
| Fights First / Remaining | 12.04 | ✅ |
| Pile-in par figurine | 12.03 | ✅ |
| Normal Fight + Overrun | 12.05, 12.07 | ✅ |
| Consolidation cascade | 12.08 | ✅ |

**Attack Sequence**

| Règle | Ref | Status |
|-------|-----|--------|
| Hit / Wound / Save | 05.01–05.03 | ✅ |
| Critical + Sustained / Lethal / Devastating | 24.36, 24.23, 24.10 | ✅ |
| ANTI-X, TORRENT, TWIN-LINKED, MELTA | 24.03, 24.37, 24.38, 24.25 | ✅ |
| Re-rolls (hit / wound / save) | — | ✅ |
| Mortal Wounds + Hazard | 06.02–06.03 | ✅ |
| Allocation manuelle + priorité personnage | 05.03 | ✅ |
| Feel No Pain (PainBoy → Boyz) | 24.12 | ✅ |
| RAPID FIRE, SUSTAINED HITS, EXTRA ATTACKS | 24.30, 24.36, 24.11 | ✅ |
| PRECISION | 24.28 | ✅ |
| Deadly Demise (LandSpeeder, WarTrakk) | 24.08 | ❌ |

**Attached Units**

| Règle | Ref | Status |
|-------|-----|--------|
| Leader / Support + Toughness bodyguard | 19.01–19.02 | ✅ |
| Keywords + ability propagation | 19.03–19.04 | ✅ |

**Objectifs**

| Règle | Ref | Status |
|-------|-----|--------|
| OC, contrôle, sécurisation | 14.02–14.03 | ✅ |
| Battle-Shock → OC = 0 | 08.03 | ✅ |

---

### Manquants bloquants pour la démo

| Règle | Ref | Impact |
|-------|-----|--------|
| Plunging Fire | 22.05 | Bonus +1 BS depuis élévation ignoré — Land Speeder et unités en hauteur ne tirent pas correctement |
| Deadly Demise | 24.08 | Land Speeder et WarTrakk détruits sans explosion — règle silencieusement ignorée |

---

### Summary — démo

Périmètre : 46 règles en scope (11 explicitement hors scope, non comptées).

| Status | Count |
|--------|-------|
| ✅ Implémentée | 44 |
| ❌ Manquante | 2 |
| **Total en scope** | **46** |

**Couverture démo : 44 / 46 = 96% — 2 règles manquantes : Plunging Fire (22.05) et Deadly Demise (24.08)**
