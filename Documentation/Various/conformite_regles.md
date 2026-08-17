# Conformité règles 40k ↔ code — audit par phase

> Audit du 2026-07-05. Méthode : lecture des PDF officiels (`Documentation/40k_rules/`) confrontée
> au code réel des handlers (`engine/phase_handlers/`). Un ✅ = règle présente et conforme,
> ⚠️ = implémentée mais divergente/simplifiée, ❌ = absente.

## Problèmes transverses (prioritaires)

1. **Feel No Pain absent partout** — 0 occurrence dans `engine/` (concerne tir ET combat).
2. ~~**Règles spéciales d'armes sans effet en partie réelle**~~ — **RÉSOLU** (V11 P1, puis
   §0.38 le 2026-07-28). HEAVY, RAPID FIRE, TORRENT, DEVASTATING WOUNDS, LETHAL/SUSTAINED
   HITS, TWIN-LINKED, ANTI-X, HAZARDOUS, MELTA, BLAST vivent dans le socle commun
   `engine/phase_handlers/attack_sequence.py`, consommé par les deux rollers du chemin vif
   (`shared_utils._manual_roll_intent` au tir, `fight_handlers._manual_roll_fight_intent` en
   mêlée). La fonction de test `_attack_sequence_rng` qui les hébergeait a été supprimée, et
   ses 5 fichiers de tests re-pointés sur le chemin vif.
3. **Groupes d'allocation (05.03) simplifiés** — seuils to-wound/save figés sur la 1re figurine
   (`shared_utils.py:5616`) ; chemin auto fight = pool de PV unique. Unités hétérogènes /
   personnage attaché mal résolus. Correct uniquement sur le chemin PvP manuel.
4. 🐛 **Print de debug laissé en production** — `print("[PILEIN-DBG]…")` non conditionné dans
   `_fight_units_engaged_with` (`fight_handlers.py:4257`), étiqueté "LOG TEMPORAIRE JETABLE".
   S'exécute à chaque calcul d'engagement pendant le pile-in. À supprimer.

---

## Command (PDF 08)

| Règle | État | Preuve |
|---|---|---|
| 08.03 Battle-shock (joueur actif, half-strength `≤`, 2D6 vs Ld, retrait statut) | ✅ | `shared_utils.py:3270-3334`, `command_handlers.py:74-82` |
| 08.02 Gain 1 CP par joueur | ❌ | Aucun système de Command Point dans le moteur (0 occurrence) |
| 08.04 Command abilities | ❌ | Stub vide, `command_build_activation_pool` → `[]` |
| 08.05 Scoring objectif primaire | ⚠️ | Exécuté au **début** de la phase (`command_handlers.py:101`) au lieu de la fin |
| 08.01 Déclencheurs start-of-phase | ⚠️ | Reset technique seulement |

## Move (PDF 03 + 09)

| Règle | État | Preuve |
|---|---|---|
| Séquence phase, Remain Stationary, Normal (max M), Advance (+1D6), Fall Back (max M) | ✅ | `movement_handlers.py:369/573/724/848`, `get_squad_move_budget:3419` |
| Desperate Escape (traversée ennemis + hazard si battle-shocked) | ✅ | `movement_handlers.py:904-914`, `w40k_core.py:2601` |
| Traversée figs amies / pas ennemies, bornes plateau, pas de fin sur case occupée | ✅ | `game_config.json:41-42`, BFS `:2633-2653` |
| Interdiction de finir dans l'ER ennemie (Normal/Advance/Fall Back) | ✅ | `ez_anchor_forbidden`, `:2645` |
| Blocage tir/charge post-Advance/Fall Back | ✅ | `units_advanced`/`units_fled` |
| Cohésion 03.03 : ≥1 voisin ≤2" + ≤9" de toute autre fig | ✅ | `squad_min_neighbors:1` conforme (03.03 = « at least one other model ») |
| Regaining Coherency (03.03) : retrait de figs hors cohésion en fin de tour | ❌ | `end_of_turn_coherency_removal` (`shared_utils.py:7571`) défini mais jamais appelé → la vraie règle V11 (figs détruites jusqu'à recohésion) n'est pas appliquée |
| Validation distance au commit | ⚠️ | Voir détail ci-dessous |
| Vertical : ER 5", cohésion verticale, escalade (13.06) | ❌ | Moteur 2D |
| `movement_set_advance_mode_handler` ne revérifie pas l'éligibilité | ⚠️ | Gardé seulement par le flux UI |

### Détail — Validation distance au commit

**Règle (03.01)** : la distance d'un mouvement = la **longueur totale du trajet parcouru** (somme des
segments). Un détour pour contourner un mur ou une figurine consomme du budget de mouvement.

**Code** (`validate_move_plan`, `shared_utils.py:3047`) : au commit, la validation ne compare que la
distance **directe** départ→arrivée :
`calculate_hex_distance(origine, destination) > budget_per_model → refusé`.
C'est la distance « à vol d'oiseau » en hexs, pas la longueur du chemin réellement emprunté.

**Conséquence** : sans obstacle entre départ et arrivée, les deux mesures sont identiques → aucun écart.
La divergence n'apparaît **que s'il faut contourner** un obstacle : le trajet réel est plus long que la
ligne droite, mais le commit ne mesure que la ligne droite → garde-fou **plus permissif** que la règle.

**Atténuation** : le pool de destinations est généré par un **BFS géodésique** (`movement_handlers.py:2624-2653`)
qui respecte, lui, la vraie longueur de chemin. Dans le flux normal (le joueur clique une case proposée par
le pool), les destinations offertes sont déjà correctes. Le trou n'existe que dans le garde-fou final : un plan
arrivant par un autre biais (appel API direct, chemin alternatif) passerait la validation même si son trajet
réel dépasse le budget. → classé ⚠️ (non exploitable en jeu normal), pas ❌.

## Shoot (PDF 10 + 04 + 05)

| Règle | État | Preuve |
|---|---|---|
| Table blessures S vs T, save (AP/invul), dégâts (excès perdu) | ✅ | `shared_utils.py:5229-5372`, `combat_utils.py:640` |
| Sélection cible (LoS + portée + ennemi + non-engagé + pistolet) | ✅ | `shooting_handlers.py:2154-2268` |
| Split fire (cible par arme), BLAST, COVER | ✅ | `shared_utils.py:4265/5263/5515` |
| Feel No Pain | ❌ | Absent |
| HEAVY, DEVASTATING_WOUNDS, HAZARDOUS, rerolls | ✅ (2026-07-28, §0.38) | Vifs : HEAVY et les rerolls dans `_manual_roll_intent`, DEVASTATING dans `attack_sequence.roll_attack_pool` + `_resolve_one_manual_wound`, HAZARDOUS en fin d'activation (tir ET mêlée) |
| RAPID FIRE | ✅ (2026-07-25) | `weapon_rule_parameter(weapon, "RAPID_FIRE")` dans `_manual_roll_intent`, à la constitution du pool d'attaques. L'ancien helper `_get_rapid_fire_parameter`, jamais appelé, a été supprimé (§0.38) |
| TORRENT (auto-hit), LETHAL/SUSTAINED (crit 6), TWIN-LINKED, ANTI-X, MELTA | ✅ (2026-07-26) | `attack_sequence.py`, socle commun tir + mêlée |
| Groupes d'allocation (05.03) | ⚠️ | Seuils figés sur 1re figurine (`shared_utils.py:5616`) |
| Indirect / Close-quarters MONSTER-VEHICLE (−1 hit) | ❌ | Absents |

## Charge (PDF 11) — la plus conforme

| Règle | État | Preuve |
|---|---|---|
| Déclaration ≤12", jet 2D6, engagement de toutes les cibles | ✅ | `game_config.json:45`, `charge_handlers.py:2572/3680` |
| Non-engagement des non-cibles (égalité d'ensembles exacte) | ✅ | `charge_handlers.py:3680-3684` |
| Échec = aucun mouvement, cohésion finale | ✅ | `charge_handlers.py:2588-2628`, `:4384-4425` |
| Interdiction Advance/Fall Back/déjà-engagé, Fights First après charge | ✅ | `charge_handlers.py:1080-1111`, `units_charged` |
| Overwatch, Heroic Intervention | ❌ | Absents (hors PDF 11 — stratagèmes/réactions) |
| Éligibilité (exige destination BFS atteignable dès déclaration) | ⚠️ | Plus strict que la lettre, sans impact sur état final |

## Fight (PDF 12 + 05) — moteur V11

| Règle | État | Preuve |
|---|---|---|
| Ordre étapes (Pile In → Fight → Consolidate), alternance FF → Remaining | ✅ | `fight_handlers.py:4580-4608/4784-4805` |
| Pile-in / consolidation 3", 3 modes + "New Foes" | ✅ | `fight_handlers.py:1069/4720/6904` |
| Table blessures, save/AP/invul, dégâts | ✅ | `fight_handlers.py:4101-4135/6127` |
| Allocation PvP complète (CHARACTER dernier, blessé d'abord, tri par save) | ✅ | `fight_handlers.py:5846/6368/6524` |
| Pile-in par-figurine (12.03 WHILE : chaque fig bouge ≤3", plus près de la cible la plus proche) | ✅ | `_fight_pile_in_build_model_pool` (`fight_handlers.py:5139`, mode `pile_in_model_move`) : BFS par figurine, budget 3", collisions coéquipières, palier WHILE commun via `pile_in_move_destinations_12_03` |
| Chemin auto (PvE/gym) = pool de PV unique | ⚠️ | `fight_handlers.py:3700` — groupes d'allocation ignorés |
| Feel No Pain | ❌ | Absent |
| 🐛 Print debug en prod | bug | `fight_handlers.py:4257` — à supprimer |

---

## Synthèse

| Phase | Cœur conforme | Manque principal |
|---|---|---|
| Command | Battle-shock ✅ | Command Points / stratagèmes absents |
| Move | ✅ solide | Regaining Coherency fin de tour non câblé, 3D non modélisée |
| Shoot | table blessures/save ✅, **règles d'armes vives (§0.38) et visibles dans step.log/analyzer/replay depuis le 2026-07-29** | **FNP absent** ; INDIRECT FIRE (24.19) livré le 2026-08-17 — 7 pièces, journal, choix PvP et analyzer compris (cf. `Implémentation/Implémenté/indirect_fire_10_07.md`), retrain porté par le run `x1_long` du 2026-08-17 ; le nom d'abilité de relance n'est pas journalisé (feature, cf. §0hist.38) |
| Charge | ✅ le plus conforme | Overwatch/Heroic (hors scope) |
| Fight | ✅ V11 complet | Print debug en prod, chemin auto = pool PV unique, FNP |

Le plus critique pour le réalisme des règles : **le tir** (règles d'armes inactives). Le combat rapproché
est mieux loti. Charge et mouvement sont fidèles. Le commandement est volontairement minimal (pas de CP).
