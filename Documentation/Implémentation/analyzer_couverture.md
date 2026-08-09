# Couverture analyzer — matrice RÈGLE → CONTRÔLE → CHAMPS step.log → STATUT

> Cartographie exhaustive, produite le 2026-08-08, **remise à jour le 2026-08-09** sur `main`
> après les quatre lots de nuit (`52b250fc`, `1be72f3f`, `089fec52`, `21cea5a8`).
> Document d'ENTRÉE des lots suivants : il dit ce qui est vérifié, ce qui ne l'est pas, et
> **pourquoi**. Aucun code n'a été modifié pour le produire.
>
> **Ce que la mise à jour a changé** — trois lignes de journal neuves (`AGENT_PLAYER=`,
> `T{tour} STATE:`, `T{tour} EFFECTS:`) et un segment neuf (`[MODEL_TYPES:]`) ; une section de
> rapport neuve (§2.8) et ses 3 compteurs ; la double-activation étendue à la phase FIGHT ;
> une **correction de ma part** sur `oath_of_moment` (§5-bis). Le reste du fond est inchangé.

## 0. Méthode et sources

| Source | Ce qui en a été tiré |
|---|---|
| `Documentation/40k_rules/*.pdf` (25 fichiers, texte intégral extrait) | 156 règles numérotées `NN.MM` |
| `config/weapon_rules.json` | 23 règles d'armes |
| `config/unit_rules.json` | 35 règles spéciales d'unité |
| `ai/analyzer.py` (3469 l.) + `analyzer_core.py` (1265) + `analyzer_config.py` + `analyzer_perfig.py` + `analyzer_state.py` + `analyzer_phases/*` (9287 l. au total) | 62 contrôles vivants, 3 morts, 5 supprimés documentés |
| `ai/step_logger.py` (1186 l.), `engine/w40k_core.py` (`_STEP_LOG_TYPE_MAP`, `_build_step_log_details`, `_build_shot_details`, `_models_segment_for_unit`, `_run_rules_for_step_log`, `_log_effects_snapshot_if_changed`), `engine/action_log_utils.py` | format réel de `step.log`, champ par champ, type d'action par type d'action |

### Légende des STATUTS

| Statut | Définition stricte |
|---|---|
| **COUVERT** | Un contrôle existe, il regarde la bonne grandeur (par-figurine, métrique du run), et tous les champs nécessaires sont journalisés. |
| **PARTIEL** | Un contrôle existe mais ne couvre qu'une partie de la règle, **ou** regarde la mauvaise chose (ancre au lieu du socle, hex au lieu d'euclidien, adjacence au lieu de zone d'engagement). Le trou est nommé. |
| **ABSENT-LOGGABLE** | `step.log` porte déjà toute l'information ; il ne manque que le contrôle. |
| **ABSENT-LOG-MANQUANT** | Le contrôle est impossible en l'état : les champs à ajouter au StepLogger sont nommés. |
| **NON-TESTABLE-OFFLINE** | Structurellement hors de portée d'un contrôle post-hoc sur journal (définition, donnée de registre, terrain absent du log, jet non reproductible, ou contrôle qui serait tautologique). |

**Vert vacant** : un contrôle qui existe mais mesure la mauvaise chose est classé **PARTIEL**, jamais COUVERT.
La §5 liste les verts vacants trouvés.

---

## 1. Format réel de `step.log`

### 1.1 Entête d'épisode (`StepLogger.log_episode_start`, `ai/step_logger.py:265`)

```
[hh:mm:ss] === EPISODE N START ===
[hh:mm:ss] Scenario: <texte>                       (optionnel)
[hh:mm:ss] Scenario file: <chemin relatif>          (optionnel)
[hh:mm:ss] Rosters: scale=<n> AGENT_PLAYER=<1|2> AGENT=<id> (<ref>) OPPONENT=<id> (<ref>)  (optionnel)
[hh:mm:ss] Opponent: <Nom>Bot                       (optionnel)
[hh:mm:ss] Walls: (c,r);(c,r);…      |  Walls: none
[hh:mm:ss] Objectives: <nom>:(c,r);(c,r)|<nom>:…   |  Objectives: none
[hh:mm:ss] Rules: {"primary_objective":…}
[hh:mm:ss] Board: cols=<n> rows=<n> inches_to_subhex=<n> hex_radius=<n> margin=<n>
[hh:mm:ss] Run rules: engagement_zone_subhex=… engagement_zone_vertical_inches=…
           metric.engagement=… metric.ranged=… move.thru_ez=… move.thru_enemy=… move.thru_friendly=…
[hh:mm:ss] Unit <id> (<unitType>) [<DISPLAY_NAME>] P<n>: Starting position (c,r), HP_MAX=<n>
           base=<shape>/<size> [MODELS: <mid>@(c,r,z<h>) …] [MODEL_TYPES: <mid>=<UnitType> …]
[hh:mm:ss] === ACTIONS START ===
```

`Board:` et `Run rules:` sont **exigés** par l'analyzer (`analyzer_config.get_run_inches_to_subhex` /
`get_run_rule` lèvent sinon) : ils figent l'échelle et les règles du run analysé, jamais celles du
`config/` du jour. **`AGENT_PLAYER=` l'est aussi** depuis le 2026-08-09 (`analyzer_core.py:283`
puis levée en fin d'épisode) : `controlled_player_mode` accepte `p2` et `random`, et supposer
« agent == P1 » attribuait les victoires de l'agent au bot dans 30 % des épisodes.

`[MODEL_TYPES:]` donne la **datasheet par figurine** : une escouade n'est pas homogène (règle 19,
sergents, armes spéciales), et tout plafond calculé par socle à partir du type d'ESCOUADE est faux.
C'est ce segment qui rend le plafond d'attaques de §1.4 juste (`fight_handler.py:24`).

### 1.2 Ligne d'action (`log_action`, `ai/step_logger.py:156`)

```
[hh:mm:ss] E<ep> T<turn> P<player> <PHASE> : <message> [<MODELS:…>] [<TARGET_MODELS:…>] [<SHOOTER_MODELS:…>] [SUCCESS|FAILED]
```

Segments per-figurine (`engine/action_log_utils.py:12`) :

| Segment | Contenu | Consommateur |
|---|---|---|
| `[MODELS: <mid>@(c,r,z<h>) …]` | socles VIVANTS de l'unité qui agit ; `mid = <unit_id>#<index>` ; `z` = hauteur de PLANCHER en pouces | analyzer (source de vérité par-socle) + replay |
| `[TARGET_MODELS: …]` | survivants de la CIBLE après pertes, uniquement sur le DERNIER jet visant cette cible | replay + `shoot_handler` (portée) |
| `[SHOOTER_MODELS: <mid> …]` | figurines ayant EFFECTIVEMENT tiré/frappé | replay seul |

### 1.3 Messages par type d'action

Seuls ces types atteignent `step.log` (`_STEP_LOG_TYPE_MAP` + `_STEP_LOG_MOVE_TYPE_MAP` +
l'écriture directe de `rule_choice`) :

| `action_type` | Message | Champs porteurs de règle |
|---|---|---|
| `move` | `Unit N(c,r) MOVED [FLY] from (a,b) to (c,d)[R:±x]` | `[FLY]` (21.03), positions, `[MODELS:]` |
| `advance` | `Unit N(c,r) ADVANCED [FLY] from … to … [Roll: N] [Strategy: <label>]` | jet D6 (en **pouces**), `[FLY]` |
| `flee` | `Unit N(c,r) FLED [FLY] from … to …` | `[FLY]`, positions |
| `move_after_shooting` | `Unit N(c,r) MOVED AFTER SHOOTING [<CAPACITÉ>] from … to …` | nom de la capacité (obligatoire) |
| `reactive_move` | `Unit N(c,r) REACTIVE MOVED [<CAPACITÉ>] from … to … [Roll: N] - trigger: Unit M->(c,r)` | jet, déclencheur ; **pas de `[MODELS:]` d'arrivée** |
| `deploy_unit` | `Unit N(c,r) DEPLOYED from (-1,-1) to (c,r)` | sentinelle hors-table `(-1,-1)` (20.01) |
| `shoot` | `Unit N(c,r) SHOT [ASSAULT] [CLOSE-QUARTERS] [RAPID FIRE:X] Unit M(c,r) with [<arme>] - Hit R(T+ ou base+->eff+) [HEAVY\|COVER] [REROLLED:n] [SUSTAINED HITS] [<CAPACITÉ>] - Wound R(T+) [<CAPACITÉ>] [REROLLED:n] - Save R(T+) [REROLLED:n] [<CAPACITÉ>] - Dmg:NHP [HAZARDOUS] Roll:N` ; ou `Save [DEVASTATING WOUNDS]` | jets, seuils, tokens de règle |
| `hazardous` | `Unit N(c,r) SUFFERS X Mortal Wounds [HAZARDOUS]` / `… was DESTROYED [HAZARDOUS]` | MW infligées |
| `charge` | `Unit N(c,r) CHARGED [<CAPACITÉ>] [FLY] Unit M(c,r) from … to … [Roll: N]` | jet 2D6 (pouces), `[FLY]`, **une seule** cible |
| `charge_fail` | `Unit N(c,r) FAILED CHARGE to unit M(c,r) [Roll: N]` | jet |
| `charge_impact` | `Unit N(c,r) IMPACTED [<CAPACITÉ>] Unit M(c,r) - Hit:T+:R(HIT\|FAIL) Wound:AUTO Save:NONE[MW] Dmg:NHP` | seuil, jet, MW |
| `combat` | `Unit N(c,r) FOUGHT [WAAAGH!] Unit M(c,r) with [<arme>] - Hit R(T+) [SUSTAINED HITS] [<CAPACITÉ>] [REROLLED:n] - Wound … - Save … - Dmg:NHP [FIGHT_SUBPHASE:<x>]` | idem tir + sous-phase de combat + `[WAAAGH!]` (confort de lecture — la **donnée** est dans `T{tour} EFFECTS:`) |
| `pile_in` / `consolidation` | `Unit N(c,r) PILED IN\|CONSOLIDATED from … to …` | positions, `[MODELS:]` |
| `wait` | `Unit N(c,r) WAIT` | — |
| `rule_choice` | `Unit N(c,r) chose [<NOM DE RÈGLE>]` | nom d'affichage |

**Formateurs sans producteur** (code mort côté moteur) : `skip`, `shoot_summary`, `combat_summary`.
Conséquence directe : le contrôle §2.1 « Dead unit skipping » et tout `handle_skip`
(`shoot_handler.py:969`) sont inatteignables.

### 1.4 Lignes hors action

| Ligne | Producteur | Lue par l'analyzer ? |
|---|---|---|
| `[ts] T<n> P<n> <PHASE> phase Start` | `log_phase_transition` | **Non** — jamais parsée |
| `[ts] T<n> OBJECTIVE CONTROL: VP1= VP2= CP1= CP2= ZONES=<nom>:Ctrl=…` | `log_objective_control_snapshot` | Oui — VP uniquement |
| `[ts] T<n> STATE: <uid>[<mid>@(c,r,z<h>):<pv> …] …` | `log_state_snapshot` (`step_logger.py:199`) | **Oui** — `_apply_state_snapshot` (`analyzer_core.py:123`) : compte l'écart, PUIS recale |
| `[ts] T<n> EFFECTS: P1 <clé>=<val> … \| P2 none` | `log_effects_snapshot` (`step_logger.py:156`) | Partiellement — `_parse_effects_snapshot` (`analyzer_core.py:105`) lit tout, mais seul `waaagh_melee_atk` est consommé |
| `[ts] EPISODE END: Winner=, Method=, Actions=, Steps=, Total=, Duration=…s` | `log_episode_end` | Oui |
| `[ts] OBJECTIVE CONTROL: Obj<id>:P1_OC=,P2_OC=,Ctrl=` (récap de fin) | `log_episode_end` | Non (motif distinct, non matché) |

Clés émises par `T{tour} EFFECTS:` (`w40k_core.py:7189`, valeurs prises aux constantes du moteur —
le journal dit ce qui a été appliqué, il ne le redécrit pas) : `waaagh=on`, `waaagh_melee_str=+X`,
`waaagh_melee_atk=+X`, `waaagh_invul=<n>`, `oath_target=<unit_id>`, `oath_wound=+X`.
**Une seule est lue** aujourd'hui : `waaagh_melee_atk`. Les cinq autres sont dans le journal et
n'alimentent aucun contrôle — c'est le gisement le moins cher de la liste §7.

---

## 2. Inventaire des contrôles analyzer (62 vivants)

### §1.1 MOVEMENT ERRORS (`analyzer.py:2297`)

| # | Compteur | Site | Ce qu'il regarde VRAIMENT |
|---|---|---|---|
| 1 | `wall_collisions` | `move_handler.py:180,580` ; `shoot_handler.py:1321` | destination d'ANCRE ∈ `wall_hexes` |
| 2 | `move_to_adjacent_enemy` | `move_handler.py:568` | zone d'engagement per-figurine, socles d'ARRIVÉE + hauteurs d'arrivée |
| 3 | `move_adjacent_before_non_flee` | `move_handler.py:545` | zone d'engagement per-figurine, socles de DÉPART (survivants) |
| 4 | `move_distance_over_limit['move']` | `move_handler.py:431` | `_per_model_move_violation` : BFS par socle, budget `M` (−2" si `[FLY]`) |
| 5 | `move_after_shooting_distance_over_limit` | `move_handler.py:425` | idem, budget = `rule_args.distance` × échelle |
| 6 | `reactive_move_stats.abnormal` | `analyzer_core.py:1061` | phase ∉ {MOVE,SHOOT} **ou** `calculate_hex_distance` ANCRE > jet×échelle |
| 7 | `reactive_move_checks.to_adjacent_enemy` | `analyzer_core.py:1155` | engagement, sujet mesuré à l'ANCRE (pas de `[MODELS:]` réactif) |
| 8 | `reactive_move_checks.into_wall` | `analyzer_core.py:1163` | ancre ∈ `wall_hexes` |
| 9 | `reactive_move_checks.distance_over_roll` | `analyzer_core.py:1114` | `_per_model_move_violation`, budget jet×échelle |

### §1.2 SHOOTING ERRORS (`analyzer.py:2400`)

| # | Compteur | Site | Ce qu'il regarde VRAIMENT |
|---|---|---|---|
| 10 | `shoot_invalid.out_of_range` | `shoot_handler.py:674` | `squads_min_ranged_distance` socle→socle, métrique `metric.ranged` du run, cap **non tronqué** depuis le 2026-08-09 ; **aucun verdict** si ni `[TARGET_MODELS:]` ni socles connus |
| 11 | `shoot_invalid.engaged_non_close_quarters` / `engaged_shot_with_non_close_quarters_weapon` | `:633` | tireur engagé (per-fig) ∧ arme non-CQ ∧ non-M/V |
| 12 | `shoot_over_rng_nb` | `:411` | compteur de séquence vs `NB × socles vivants` (+ `RAPID FIRE` si marqueur) ; `[SUSTAINED HITS]` exclu |
| 13 | `shoot_combi_profile_conflicts` | `:327` | 2 profils d'un même `COMBI_WEAPON` dans le même tour |
| 14 | `shoot_after_flee` | `:163` | `units_fled` ∧ pas de règle `shoot_after_flee` |
| 15 | `shoot_at_friendly` | `:186` | `unit_player[cible] == unit_player[tireur]` |
| 16 | `shoot_at_engaged_enemy` | `:594` | cible engagée (per-fig) ∧ arme non-CQ ∧ ¬exemption 17.03 ∧ ¬tireur engagé avec elle |
| 17 | `close_quarters_shot_at_unengaged_target` | `:622` | tireur engagé non-M/V visant une unité avec laquelle il n'est PAS engagé (10.06) |
| 18 | `advance_after_shoot` | `:1192` | `units_shot` puis `ADVANCED` |
| 19 | `advance_twice_in_shoot_phase` | `:1183` | 2e `ADVANCED` en phase SHOOT |
| 20 | `move_distance_over_limit['advance']` | `:1176` | BFS par socle, budget `M + D6×échelle` (−2" si `[FLY]`) |
| 21 | `advance_from_adjacent` | `:1240` | engagement per-fig aux socles de départ |

### §1.3 CHARGE ERRORS (`analyzer.py:2541`)

| # | Compteur | Site | Ce qu'il regarde VRAIMENT |
|---|---|---|---|
| 22 | `charge_from_adjacent` | `charge_handler.py:215` | engagement per-fig aux socles de départ |
| 23 | `charge_invalid.advanced` | `:81` | `units_advanced` ∧ ni `[WAAAGH!]` ni `charge_after_advance` |
| 24 | `charge_invalid.fled` | `:91` | `units_fled` ∧ pas de `charge_after_flee` |
| 25 | `charge_invalid.distance_over_roll` | `:132` | BFS par socle, budget `2D6×échelle` (−2" si `[FLY]`, obstacles ignorés si vol) |
| 26 | `charge_after_flee` | `:227` | doublon du #24, compteur distinct |

### §1.4 FIGHT ERRORS (`analyzer.py:2588`)

| # | Compteur | Site | Ce qu'il regarde VRAIMENT |
|---|---|---|---|
| 27 | `fight_friendly` | `fight_handler.py:283` | même joueur |
| 28 | `fight_over_cc_nb` | `:235` (plafond : `_cc_cap_for_line`, `:24`) | séquence vs plafond **par figurine** depuis le 2026-08-09 : `[SHOOTER_MODELS:]` donne les socles qui ont frappé, `[MODEL_TYPES:]` la datasheet de chacun, `T{tour} EFFECTS:` le bonus `waaagh_melee_atk`. Le groupe de frappeurs entre dans la clé de séquence. Repli explicite sur `NB d'escouade × effectif` si le journal n'a pas ces segments. `[SUSTAINED HITS]` exclu |
| 29 | `fight_alternation_violations` | `:151` | une unité ayant chargé, encore engagée et non encore activée, existait au moment où une autre a frappé |
| 30-31 | `fight_move_invalid.pile_in` / `.consolidation` | `:416` | BFS par socle, budget `3"×échelle` |

### §1.5–§1.8

| # | Contrôle | Site |
|---|---|---|
| 32 | `action_phase_accuracy` (move / move_after_shooting / fled / shoot / advance / charge / fight → phase attendue) | `analyzer.py:909` |
| 33 | `double_activation_by_phase` — **MOVE/SHOOT/CHARGE/FIGHT** depuis le 2026-08-09 | `analyzer_core.py:901` ; marqueurs `:876-883` |
| 34 | `double_activation_reactive_move` (2e réactif / tour / joueur) | `analyzer_core.py:1026` |
| 35 | `special_rule_usage` → colonne `Validité` : l'unité porte-t-elle la règle qu'elle a utilisée ? | `analyzer.py` §1.7 |
| 36 | `rule_choice_selection_invalid` (label inconnu/ambigu, ou choix hors des sources de l'unité) | `analyzer_core.py:743,772` |
| 37 | `rule_choice_usage.missing` (effet utilisé sans choix préalable) | `analyzer_core.py` §1.7 |
| 38 | `rule_choice_usage.mismatch` (effet utilisé ≠ effet choisi) | `analyzer_core.py` §1.7 |
| 39 | `weapon_rule_usage` → `Validité` : la paire (règle, arme) existe-t-elle dans l'armurerie ? + `NOT USED` | `analyzer.py` §1.8 |
| 40 | `devastating_wounds_incorrect` | `shoot_handler.py:429` |
| 41 | marqueur `[RAPID FIRE:X]` absent de l'armurerie ou valeur ≠ armurerie → `parse_error` | `shoot_handler.py:289,300` |
| 42 | marqueur `[SUSTAINED HITS]` sur arme sans la règle → `parse_error` | `shoot_handler.py:351` |

Le marqueur d'activation de la phase FIGHT est `) CONSOLIDATED ` (`analyzer_core.py:876`) : les
lignes `FOUGHT` sont par ATTAQUE (des dizaines par activation), la consolidation est la seule
frontière d'activation d'une par unité et par phase (12.07). **SHOOT reste sans marqueur propre** :
`SHOT` n'est pas dans `is_activation_marker`, donc 10.02 n'est toujours pas couvert.

### §2.1 DEAD UNITS (11 compteurs)

| # | Compteur | Site |
|---|---|---|
| 43 | `dead_unit_moving` | `move_handler.py:281` |
| 44 | `shoot_dead_unit` | `shoot_handler.py:151` |
| 45 | `shoot_at_dead_unit` | `analyzer_core.py:648` |
| 46 | `dead_unit_advancing` | `shoot_handler.py:1120` |
| 47 | `dead_unit_charging` | `charge_handler.py:183` |
| 48 | `charge_dead_unit` | `charge_handler.py:251` |
| 49 | `fight_dead_unit_attacker` | `fight_handler.py:308` |
| 50 | `fight_dead_unit_target` | `fight_handler.py:337` |
| 51 | `dead_unit_waiting` | `shoot_handler.py:790` |
| 52 | `dead_unit_skipping` | `shoot_handler.py:1009` — **inatteignable** (pas de producteur `skip`) |
| 53 | `unit_revived` | `analyzer.py:352` |

Tous appliquent la même exception 05 (« excess attacks lost » de la même activation, via `unit_kill_context`).

### §2.2–§2.3

| # | Contrôle | Site |
|---|---|---|
| 54-56 | `position_log_mismatch` move / advance / charge (`move_start_status`, per-figurine, avec catégorie informative `anchor_absorbed`) | `analyzer_perfig.py:164` |
| 57 | `unit_position_collisions` (2 unités vivantes sur la même ANCRE, après mouvement le même tour) | 3 sites |
| 58 | `damage_missing_unit_hp` | `analyzer.py:269` |
| 59 | `damage_exceeds_hp` | affiché `analyzer.py:2973` — **jamais incrémenté** |

### §2.8 ÉTAT RECONSTRUIT vs ÉTAT MOTEUR — section neuve (2026-08-09)

Le reste du rapport repose sur un état **reconstruit par accumulation** (PV initial moins chaque
`Dmg:`, position initiale plus chaque déplacement). Rien ne disait quand cette reconstruction
dérivait. La ligne `T{tour} STATE:` est le point de recalage : `_apply_state_snapshot`
(`analyzer_core.py:123`) **compte l'écart avant de le corriger** — une correction muette ferait
disparaître le symptôme sans jamais signaler sa cause.

| # | Compteur | Site | Ce qu'il signifie |
|---|---|---|---|
| 60 | `state_resync.dead_missed` | `analyzer_core.py:190` | l'analyzer croyait l'unité vivante, le moteur ne la voit plus — le **fantôme** (une escouade hors table n'est pas comptée : réserves ≠ mort) |
| 61 | `state_resync.alive_missed` | `analyzer_core.py:159` | l'analyzer a tué une unité que le moteur garde — sur-attribution de dégâts |
| 62 | `state_resync.pos_mismatch` | `analyzer_core.py:164` | une figurine n'est pas là où l'analyzer la croyait — déplacement non journalisé (c'est ainsi que le pile-in muet s'est manifesté) |

Affiché en §2.8 (`analyzer.py:3038`), au SUMMARY (`:3219`) et compté dans le total d'erreurs de la
CLI (`:3411`). **Portée du verdict** : une divergence non nulle invalide, pour l'épisode concerné,
tout contrôle mesurant une distance ou une adjacence — donc §1.1 à §1.4.

### Contrôles SUPPRIMÉS (documentés dans le code, à ne pas ré-écrire à l'identique)

| Contrôle | Règle | Date | Raison |
|---|---|---|---|
| « Shoot through wall » | 06.01 | 2026-07-16 | LoS ancre-à-ancre sur ancres d'ESCOUADE ≠ prédicat moteur per-figurine. Déplacé dans `tests/unit/engine/test_shoot_los_perfig_parity.py` |
| « Fight from non-adjacent » | 12.05 | 2026-07-24 | métrique hex ≠ euclidien du moteur ; position cible pré-perte non journalisable. Déplacé dans `tests/unit/engine/test_fight_spatial_contract.py` |
| Validité `[HEAVY]` | 24.16 | 2026-07-29 | critère « aucune figurine n'a bougé > 3" » non re-dérivable (chemin géodésique par figurine) |
| `[RAPID FIRE]` per-shot | 24.30 | 2026-07-29 | le moteur résout un POOL ; « quelle attaque est la bonus » n'existe pas |
| Recalcul du contrôle d'objectif | 14.02 | — | sommait par ANCRE, ignorait le battle-shock, évaluait hors frontière de phase |

---

## 3. Matrice A — corpus de règles PDF (156 lignes)

### 01 Core concepts

| Règle | Contrôle analyzer | Champs step.log nécessaires | Statut |
|---|---|---|---|
| 01.01 Armies | — | — | NON-TESTABLE-OFFLINE (structure d'armée, pas un invariant de partie) |
| 01.02 Units and models | — (présupposé de la couche per-fig) | `base=`, `[MODELS:]` | NON-TESTABLE-OFFLINE (définition) |
| 01.03 Active / opposing player | — | `T`, `P`, `PHASE` (présents) | ABSENT-LOGGABLE — vérifier qu'aucune ligne P2 n'apparaît dans le tour P1 hors FIGHT et hors réactif |
| 01.04 Measuring distances (bord de socle le plus proche) | #10, #16, #2-#5, #21, #22, #25 (`model_cache_entries`, `squads_min_ranged_distance`) | `[MODELS:]`, `base=`, `Board:` | **COUVERT** |
| 01.05 Dice | — | valeurs des jets présentes | NON-TESTABLE-OFFLINE (jets non reproductibles ; seule la distribution serait testable) |
| 01.06 Leadership rolls | — | — | ABSENT-LOG-MANQUANT — ligne de jet de commandement (2D6, Ld) |
| 01.07 Battle-shock rolls | — | — | ABSENT-LOG-MANQUANT — jet + drapeau `battle_shocked` par unité (explicitement noté impossible dans `step_logger.py:110`) |

### 02 Datasheets

| Règle | Contrôle | Champs | Statut |
|---|---|---|---|
| 02.01 Datasheet name | — | `Unit N (<unitType>)` | NON-TESTABLE-OFFLINE (registre) |
| 02.02 Profiles (M/T/Sv/InSv/W/Ld/OC) | — | `HP_MAX` seul est loggué | ABSENT-LOG-MANQUANT — `T`, `Sv`, `InSv`, `OC`, `Ld` ; + `OC='-'` quand battle-shocked |
| 02.03 Abilities | §1.7 (indirect) | tokens `[<CAPACITÉ>]` | NON-TESTABLE-OFFLINE (registre) |
| 02.04 Weapons (R/A/BS/WS/S/AP/D) | §1.2 #12, §1.4 #28 (A seul) | `with [<arme>]`, seuils | NON-TESTABLE-OFFLINE (registre) |
| 02.05 Keywords | — | — | NON-TESTABLE-OFFLINE (registre) |
| 02.06 Unit composition | — | `[MODELS:]` (effectif) | NON-TESTABLE-OFFLINE (registre) |
| 02.07 Wargear options | — | — | NON-TESTABLE-OFFLINE (registre) |

### 03 Moving

| Règle | Contrôle | Champs | Statut |
|---|---|---|---|
| 03.01 Moving units (ligne droite ; traverse ami ; pas ennemi ; pas hors plateau ; rotation gratuite) | #4, #5, #9, #20, #25, #30-31 via `_per_model_move_violation` + `_build_move_bfs_blockers` (toggles `move.thru_*` du run) | `[MODELS:]` avant/après, `Walls:`, `Run rules:` | **PARTIEL** — le bord de plateau n'est PAS un obstacle du BFS (`_bfs_shortest_path_length` ne teste que murs/occupation/EZ) ; la rotation n'est pas journalisée ; l'exemption M/V (17.01) n'est pas appliquée |
| 03.02 Set up | — (ligne `DEPLOYED` parsée mais non contrôlée) | positions présentes ; **zones de déploiement absentes** | ABSENT-LOG-MANQUANT — bornes de la zone de déploiement de chaque joueur |
| 03.03 Coherency (2" / 9", et purge End of Turn) | — | `[MODELS:]` suffit intégralement | **ABSENT-LOGGABLE** — trou identifié de longue date (V11 T6-i) |
| 03.04 Engagement (2" horizontal ET 5" vertical) | #2, #3, #7, #16, #17, #21, #22 via `is_within_engine_engagement_zone` (primitive moteur, gate vertical « tout ou rien ») | `[MODELS:]` avec `z`, `base=`, `Run rules:` (`engagement_zone_subhex`, `engagement_zone_vertical_inches`, `metric.engagement`) | **COUVERT** |

### 04 Making attacks

| Règle | Contrôle | Champs | Statut |
|---|---|---|---|
| 04.01 Select weapons | #39 (usage par arme) | `with [<arme>]` | **PARTIEL** — le volet 24.07 (« une figurine choisit SOIT ses CQ SOIT ses autres armes ») et 24.11 EXTRA ATTACKS ne sont pas contrôlés ; l'arme est loguée au niveau ESCOUADE, pas par figurine |
| 04.02 Select targets (visible / à portée / non engagé ; en mêlée : engagé, ≤ A cibles) | #10 (portée), #16-#17 (engagé) | portée et engagement OK ; visibilité impossible | **PARTIEL** — volet « visible » (06.01) supprimé ; volet mêlée « engagé » supprimé ; « pas plus de cibles que A » non contrôlé (loggable) |
| 04.03 Resolve attacks (gather dice = A) | #12 (tir), #28 (mêlée) | séquence de lignes, `[MODELS:]`, `[SHOOTER_MODELS:]`, `[MODEL_TYPES:]`, `T{tour} EFFECTS:`, `[RAPID FIRE:X]`, `[SUSTAINED HITS]` | **PARTIEL** — le plafond de MÊLÉE est passé **par figurine** le 2026-08-09 (datasheet du socle, frappeurs réels, bonus lu) ; celui du TIR reste au niveau ESCOUADE (`NB × socles vivants`, `shoot_handler.py:388`), donc faux dès qu'une escouade est hétérogène — c'est le jumeau non traité. « Identical attacks » et le regroupement par cible ne sont pas journalisés |

### 05 Attack sequence

| Règle | Contrôle | Champs | Statut |
|---|---|---|---|
| 05.01 Hit rolls (1 = échec, 6 = critique, sinon ≥ BS/WS) | — | `Hit R(T+)` + `hit_result` : **tout est là** | **ABSENT-LOGGABLE** |
| 05.02 Wound rolls (table S vs T) | — | seuil loggué, mais **ni S ni T** | ABSENT-LOG-MANQUANT — `S` de l'arme et `T` de la cible (le volet « jet ≥ seuil ⇒ WOUND » est, lui, ABSENT-LOGGABLE) |
| 05.03 Save rolls (groupes d'allocation, ordre) | — | aucun groupe, aucune figurine cible nommée | ABSENT-LOG-MANQUANT — groupes d'allocation + ordre déclaré |
| 05.04 Inflict damage (excès perdu, du plus bas au plus haut) | #59 `damage_exceeds_hp` — **jamais incrémenté** ; modèle correct dans `_apply_damage_and_handle_death` | `Dmg:NHP` ; `Sv`/`InSv`/`AP` absents | **PARTIEL** (vert vacant, cf. §5) |

### 06 Other concepts

| Règle | Contrôle | Champs | Statut |
|---|---|---|---|
| 06.01 Visibility | supprimé 2026-07-16 ; `has_line_of_sight` ne sert plus qu'aux métriques comportementales | `Walls:` binaire seulement, aucun terrain | NON-TESTABLE-OFFLINE — reproduire le prédicat moteur exige `game_state` (empreintes, 13.10, LoS 3D) |
| 06.02 Mortal wounds (sélection de figurine) | — | MW infligées visibles (`charge_impact`, `hazardous`, `DEVASTATING WOUNDS`) ; figurine choisie absente | ABSENT-LOG-MANQUANT — `mid` de la figurine sélectionnée |
| 06.03 Hazard rolls (1-2 → 1 MW, ou 3 si tous M/V) | — | `[HAZARDOUS] Roll:N` + `SUFFERS X Mortal Wounds` : **tout est là** | **ABSENT-LOGGABLE** |

### 07 The battle round

| Règle | Contrôle | Champs | Statut |
|---|---|---|---|
| 07.01 Start of battle round | — | — | NON-TESTABLE-OFFLINE (hook) |
| 07.02 Player turns (ordre COMMAND→MOVE→SHOOT→CHARGE→FIGHT, alternance) | — | `T`, `P`, `PHASE` sur chaque ligne ; ligne `phase Start` produite mais **jamais lue** | **ABSENT-LOGGABLE** |
| 07.03 End of battle round | — | — | NON-TESTABLE-OFFLINE (hook) |

### 08 Command phase

| Règle | Contrôle | Champs | Statut |
|---|---|---|---|
| 08.01 Start of Command phase | — | — | NON-TESTABLE-OFFLINE |
| 08.02 Gain Core CP (+1 chacun) | — | `CP1=`/`CP2=` dans l'instantané `OBJECTIVE CONTROL` | **ABSENT-LOGGABLE** |
| 08.03 Battle-shock | — | — | ABSENT-LOG-MANQUANT — jet, seuil Ld, effectif vs starting strength, drapeau résultant |
| 08.04 Command abilities (Waaagh!, Oath of Moment) | §1.7 partiellement, via tokens sur les lignes d'ACTION | tokens `[WAAAGH!]`, `[OATH OF MOMENT]` | ABSENT-LOG-MANQUANT — ligne de DÉCLARATION (« Waaagh! appelé », « cible Oath = unité X ») |
| 08.05 End of Command phase | — | — | NON-TESTABLE-OFFLINE |

### 09 Movement phase

| Règle | Contrôle | Champs | Statut |
|---|---|---|---|
| 09.01 Start of Movement phase | — | — | NON-TESTABLE-OFFLINE |
| 09.02 Move units (une sélection par unité et par phase, toutes les unités sélectionnées) | #33 (double-activation MOVE) | marqueurs de mouvement | **PARTIEL** — le volet « toutes les unités doivent être sélectionnées » est loggable et non contrôlé |
| 09.03 End of Movement phase | — | — | NON-TESTABLE-OFFLINE |
| 09.04 Remain stationary | — | aucune ligne dédiée (indistinct d'un `WAIT`) | ABSENT-LOG-MANQUANT — type de move « remain stationary » |
| 09.05 Normal move (max M, unengaged avant ET après) | #4 + #3 + #2 | `[MODELS:]`, `Run rules:` | **COUVERT** |
| 09.06 Advance move (max M+D6, unengaged, ni charge ni action après) | #20, #21, #23 | `[Roll: N]`, `[MODELS:]` | **PARTIEL** — le volet « pas d'action après » n'est pas contrôlable (16 non journalisé) |
| 09.07 Fall-back move (max M, engagé au départ, unengaged après, ni tir ni charge ; Desperate Escape = hazard + battle-shock) | #14, #24 seulement | `FLED from … to …`, `[MODELS:]` | **PARTIEL — trou majeur** : `_handle_fled` (`move_handler.py:81`) ne fait **AUCUN** contrôle de budget/chemin. C'est le seul des six déplacements sans `_per_model_move_violation`. Le mode (ordered/desperate) et son jet de hasard ne sont pas journalisés |

### 10 Shooting phase

| Règle | Contrôle | Champs | Statut |
|---|---|---|---|
| 10.01 Start of Shooting phase | — | — | NON-TESTABLE-OFFLINE |
| 10.02 Shoot (une sélection par unité et par phase ; choix du type de tir) | — | `is_activation_marker` (`analyzer_core.py:628`) **exclut** `SHOT` | **ABSENT-LOGGABLE** — la double-sélection de tir n'est pas détectée ; le TYPE de tir choisi n'est pas loggué explicitement (déduit des tokens) |
| 10.03 End of Shooting phase | — | — | NON-TESTABLE-OFFLINE |
| 10.04 Normal shooting (unengaged ∧ pas d'advance) | #11, #16 | `[ASSAULT]`, `units_advanced` | **PARTIEL** — tirer après un advance **sans** `[ASSAULT]` ni règle d'unité n'est compté que comme métrique (`shots_after_advance`), pas comme faute |
| 10.05 Assault shooting | #39 (usage `ASSAULT`) | `[ASSAULT]` | **PARTIEL** — « seules les armes [ASSAULT] peuvent être sélectionnées » non contrôlé |
| 10.06 Close-quarters shooting | #11, #16, #17 (+ exemptions M/V) | `[CLOSE-QUARTERS]`, `[MODELS:]`, engagement | **PARTIEL** — le `-1` au jet de touche n'est pas vérifié (`hit_target_base` n'est fourni que pour `HEAVY`/`COVER`) ; l'interdiction [BLAST] sur cible engagée n'est pas contrôlée |
| 10.07 Indirect shooting | — | aucun marqueur | ABSENT-LOG-MANQUANT — token `[INDIRECT FIRE]` + seuil de touche modifié |

### 11 Charge phase

| Règle | Contrôle | Champs | Statut |
|---|---|---|---|
| 11.01 Start of Charge phase | — | — | NON-TESTABLE-OFFLINE |
| 11.02 Charge (éligibilité : sur le plateau, ≤12" d'un ennemi, non engagé, pas d'advance/fall-back) | #22, #23, #24 | positions, `[MODELS:]` | **PARTIEL** — la condition « à moins de 12" d'un ennemi » n'est pas contrôlée (loggable) |
| 11.03 End of Charge phase | — | — | NON-TESTABLE-OFFLINE |
| 11.04 Charge move (max = jet ; chaque figurine finit plus près ; après : engagé avec TOUTES les cibles, avec AUCUNE autre) | #25 (budget/chemin per-socle) | `[Roll: N]`, `[FLY]`, `[MODELS:]`, **une seule** cible loguée | **PARTIEL** — aucune post-condition contrôlée ; le log ne porte qu'UNE cible de charge alors que la règle en autorise plusieurs |

### 12 Fight phase

| Règle | Contrôle | Champs | Statut |
|---|---|---|---|
| 12.01 Start of Fight phase | — | — | NON-TESTABLE-OFFLINE |
| 12.02 Pile in (une seule par unité et par étape) | — | lignes `PILED IN` datées T/P | **ABSENT-LOGGABLE** — §1.6 couvre désormais FIGHT, mais son marqueur est `CONSOLIDATED`, pas `PILED IN` : un double pile-in n'est pas compté pour lui-même |
| 12.03 Pile-in move (3" ; figurines au contact immobiles ; finir plus près ; rester engagé) | #30 (budget/chemin 3") | `[MODELS:]` | **PARTIEL** — les trois conditions « While/After Moving » ne sont pas contrôlées (toutes loggables depuis `[MODELS:]`) |
| 12.04 Fight (éligibilité ; alternance ; Fights First d'abord ; une activation par unité) | #29, **#33 (FIGHT)** | `[FIGHT_SUBPHASE:<x>]` présent mais **non lu** | **PARTIEL** — la double activation en phase FIGHT est désormais comptée (via `CONSOLIDATED`) ; #29 ne modélise toujours que « une unité ayant chargé restait éligible », ni l'alternance joueur↔joueur ni la priorité Fights First |
| 12.05 Normal fight (engagé) | supprimé 2026-07-24 | position cible pré-perte non journalisable | NON-TESTABLE-OFFLINE (justifié : métrique + `[TARGET_MODELS:]` post-pertes ; un contrôle relisant le log referait le calcul du moteur → tautologie) |
| 12.06 Overrun fight | — | `[FIGHT_SUBPHASE:<x>]` | **ABSENT-LOGGABLE** — le champ existe, l'analyzer ne le lit pas |
| 12.07 Consolidate (une seule par unité) | **#33 (FIGHT)** — `) CONSOLIDATED ` est le marqueur d'activation de la phase | lignes `CONSOLIDATED` datées T/P | **COUVERT** (2026-08-09) |
| 12.08 Consolidation move (3" ; 3 modes mutuellement exclusifs, mandatoires) | #31 (budget/chemin 3") | `[MODELS:]`, objectifs | **PARTIEL** — le MODE choisi n'est pas loggué, donc aucune post-condition de mode n'est vérifiable |
| 12.09 End of Fight phase | — | — | NON-TESTABLE-OFFLINE |

### 13 Terrain

`step.log` ne porte que `Walls:` (hexes binaires). Aucune catégorie, aucune hauteur, aucune aire de terrain.

| Règle | Statut |
|---|---|
| 13.01 Placing terrain | NON-TESTABLE-OFFLINE |
| 13.02 Terrain categories | NON-TESTABLE-OFFLINE |
| 13.03 Exposed | NON-TESTABLE-OFFLINE |
| 13.04 Light | NON-TESTABLE-OFFLINE |
| 13.05 Dense | NON-TESTABLE-OFFLINE |
| 13.06 Terrain and movement (coût vertical) | NON-TESTABLE-OFFLINE — `z` par socle est loggué, mais le coût de montée/descente n'est pas re-dérivable sans le terrain |
| 13.07 Terrain and visibility | NON-TESTABLE-OFFLINE |
| 13.08 Benefit of cover (−1 BS) | **PARTIEL** — token `[COVER]` + affichage `base+->eff+` présents, usage traçable ; la VALIDITÉ (tous les modèles dans une aire / non pleinement visibles) n'est pas re-dérivable |
| 13.09 Hidden | NON-TESTABLE-OFFLINE |
| 13.10 Obscuring | NON-TESTABLE-OFFLINE |
| 13.11 Solid | NON-TESTABLE-OFFLINE |

### 14 Objectives

| Règle | Contrôle | Champs | Statut |
|---|---|---|---|
| 14.01 Terrain objectives | parsing `Objectives:` (`analyzer_core.py:178`) | `Objectives:` | **COUVERT** (présence/géométrie) |
| 14.02 Level of control | l'analyzer **LIT** l'état du moteur, il ne le recalcule plus | `T<n> OBJECTIVE CONTROL: ZONES=` | NON-TESTABLE-OFFLINE — un recalcul exigerait l'OC par figurine et le drapeau battle-shock ; avec eux il serait tautologique |
| 14.03 Secured objectives | — | aucun drapeau `secured` | ABSENT-LOG-MANQUANT |

### 15 Stratagems

Aucun stratagème n'est journalisé (aucun type dans `_STEP_LOG_TYPE_MAP`), ni le stock de CP dépensé.

| Règles | Statut |
|---|---|
| 15.01 Using stratagems, 15.02 Command Re-roll, 15.03 Epic Challenge, 15.04 Insane Bravery, 15.05 Explosives, 15.06 Crushing Impact, 15.07 Rapid Ingress, 15.08 Fire Overwatch, 15.09 Snap Shooting, 15.10 Smokescreen, 15.11 Heroic Intervention, 15.12 Counteroffensive | ABSENT-LOG-MANQUANT ×12 — ligne `stratagem` (nom, CP, cible, phase) |

### 16 Actions

| Règle | Statut |
|---|---|
| 16.01 Performing actions | ABSENT-LOG-MANQUANT — ligne `action_start` / `action_complete` (+ le drapeau battle-shock qui conditionne l'éligibilité) |

### 17 Monsters and vehicles

| Règle | Contrôle | Statut |
|---|---|---|
| 17.01 Moving M/V (traversent toutes figurines sauf autres M/V) | — | **PARTIEL** — `_build_move_bfs_blockers` (`analyzer.py:715`) applique les toggles globaux `move.thru_*` mais **ignore le keyword M/V du mobile** : faux positifs de chemin bloqué pour tout M/V (voir §5) |
| 17.02 Frame | — | NON-TESTABLE-OFFLINE (registre) |
| 17.03 Shooting at engaged M/V | #16, #17 (exemptions implémentées dans `handle_shoot` ET `handle_wait`) | **PARTIEL** — le `-1` au jet de touche n'est pas vérifié |

### 18 Transports

Aucun TRANSPORT journalisé (ni embark, ni disembark, ni capacité).

| Règles | Statut |
|---|---|
| 18.01 Transport capacity, 18.02 Embarking, 18.03 Disembarking, 18.04 Disembark move, 18.05 Emergency disembark move | ABSENT-LOG-MANQUANT ×5 |

### 19 Attached units

| Règle | Contrôle | Statut |
|---|---|---|
| 19.01 Forming attached units | `leader` / `support` dans `unit_rules.json` ; §1.7 | **PARTIEL** — aucune ligne de log ne dit quelle unité est attachée à quelle autre |
| 19.02 Attacking attached units (T le plus haut des bodyguards) | — | ABSENT-LOG-MANQUANT — `T` utilisée pour l'attaque |
| 19.03 Keywords in attached units | — | NON-TESTABLE-OFFLINE (registre) |
| 19.04 Abilities in attached units | — | ABSENT-LOG-MANQUANT — portée/extinction des capacités conférées |

### 20 Strategic reserves

| Règle | Contrôle | Statut |
|---|---|---|
| 20.01 Placing units in strategic reserves | sentinelle `(-1,-1)` reconnue partout (`position_is_on_battlefield`, `model_cache_entries`, `_build_enemy_adjacent_hexes`, `get_adjacent_enemies`) | **PARTIEL** — le plafond de 50 % des points n'est pas contrôlable (points non loggués) |
| 20.02 Repositioned units | — | ABSENT-LOG-MANQUANT — retrait volontaire du plateau non journalisé |
| 20.03 Arriving (2e round minimum) | — | **ABSENT-LOGGABLE** — la ligne `DEPLOYED` en phase MOVE porte `T<turn>` |
| 20.04 Ingress move (6" d'un bord, >8" des ennemis, hors ZD adverse avant R3, aucun autre move ensuite) | #33 partiellement (`is_ingress_marker` compte l'ingress comme activation) | **PARTIEL** — les trois contraintes géométriques sont loggables (positions présentes, bords déductibles de `Board:`) et non contrôlées ; la ZD adverse manque |

### 21 Flying and surging

| Règle | Contrôle | Statut |
|---|---|---|
| 21.01 Surge moves | — | ABSENT-LOG-MANQUANT — type `surge` absent de `_STEP_LOG_TYPE_MAP` |
| 21.02 Surge move | — | ABSENT-LOG-MANQUANT (idem) |
| 21.03 Flying models (déclaration, −2", traversée, distance verticale ignorée) | #4, #9, #20, #25 lisent le marqueur `[FLY]` et retranchent 2"×échelle ; en vol la distance est mesurée à vol d'oiseau | **PARTIEL** — la ligne `FLED [FLY]` porte le marqueur mais n'est soumise à aucun contrôle de budget (cf. 09.07) ; `HOVER` (24.17) n'annule pas les −2" côté analyzer |

### 22 Other rules and abilities

| Règle | Statut |
|---|---|
| 22.01 Aura abilities | ABSENT-LOG-MANQUANT — aucune trace d'aura appliquée |
| 22.02 Faction abilities | **PARTIEL** — `waaagh` / `oath_of_moment` reconnues via `FACTION_ABILITY_KEYWORD_BY_RULE_ID` (`analyzer_config.py:323`) et comptées en §1.7 ; leurs effets ne sont pas vérifiés |
| 22.03 Psychic abilities | ABSENT-LOG-MANQUANT |
| 22.04 Wargear abilities | NON-TESTABLE-OFFLINE (registre) |
| 22.05 Plunging fire (+1 BS) | ABSENT-LOG-MANQUANT — aucun token ; `hit_target_base` réservé à `HEAVY`/`COVER` |

### 23 Aircraft

| Règles | Statut |
|---|---|
| 23.01 Deployment, 23.02 Movement, 23.03 Shooting, 23.04 Charging and fighting | ABSENT-LOG-MANQUANT ×4 — aucun AIRCRAFT dans le flux journalisé |

### 24 Core abilities (38)

| Règle | Contrôle | Statut |
|---|---|---|
| 24.01 Abilities (définition) | — | NON-TESTABLE-OFFLINE |
| 24.02 Duplicated abilities | — | ABSENT-LOG-MANQUANT — instance retenue non loggée |
| 24.03 [ANTI-X Y+] | — | ABSENT-LOG-MANQUANT — token + seuil critique effectif |
| 24.04 [ASSAULT] | #39 (usage) | **PARTIEL** — validité non contrôlée (cf. 10.05) |
| 24.05 [BLAST] | — | ABSENT-LOG-MANQUANT — dés bonus + interdiction sur cible engagée |
| 24.06 [CLEAVE] | — | ABSENT-LOG-MANQUANT |
| 24.07 [CLOSE-QUARTERS] | #11, #16, #17 + #39 | **PARTIEL** — le compteur d'USAGE §1.8 mesure `calculate_hex_distance(ancre,ancre)==1` (`shoot_handler.py:700`), pas l'engagement per-figurine (vert vacant, cf. §5) ; le volet « un seul choix par figurine » manque |
| 24.08 Deadly Demise | — | ABSENT-LOG-MANQUANT |
| 24.09 Deep Strike | — | **PARTIEL** — règle déclarée, ingress loggué, contrainte >8" non contrôlée (loggable) |
| 24.10 [DEVASTATING WOUNDS] | #40 | **PARTIEL** — le contrôle suppose que seul un 6 est critique ; ignore [ANTI-X Y+] |
| 24.11 [EXTRA ATTACKS] | — | ABSENT-LOG-MANQUANT — le plafond `fight_over_cc_nb` ne les distingue pas des attaques normales |
| 24.12 Feel No Pain | — | ABSENT-LOG-MANQUANT — jet FNP + seuil |
| 24.13 Fights First | — | ABSENT-LOG-MANQUANT — statut Fights First de l'unité activée |
| 24.14 Firing Deck | — | ABSENT-LOG-MANQUANT |
| 24.15 [HAZARDOUS] | ligne `hazardous` + `[HAZARDOUS] Roll:N` | **PARTIEL** — le nombre de jets doit égaler le nombre d'armes Hazardous sélectionnées : ce nombre n'est pas loggué |
| 24.16 [HEAVY] | #39 (usage) ; validité **supprimée** 2026-07-29 | **PARTIEL** (suppression justifiée : distance de chemin par figurine non re-dérivable) |
| 24.17 Hover | — | ABSENT-LOG-MANQUANT (et fausse les budgets de vol, cf. 21.03) |
| 24.18 [IGNORES COVER] | — | ABSENT-LOG-MANQUANT |
| 24.19 [INDIRECT FIRE] | — | ABSENT-LOG-MANQUANT |
| 24.20 Infiltrators | — | ABSENT-LOG-MANQUANT (zone de déploiement absente) |
| 24.21 [LANCE] | — | ABSENT-LOG-MANQUANT (absente aussi de `weapon_rules.json`) |
| 24.22 Leader | — | ABSENT-LOG-MANQUANT |
| 24.23 [LETHAL HITS] | — | ABSENT-LOG-MANQUANT — l'auto-blessure n'est pas distinguable dans le message |
| 24.24 Lone Operative | — | ABSENT-LOG-MANQUANT |
| 24.25 [MELTA X] | — | ABSENT-LOG-MANQUANT — bonus de D + marqueur « demi-portée » |
| 24.26 [ONE SHOT] | — | ABSENT-LOG-MANQUANT |
| 24.27 [PISTOL] | = 24.07 (alias) | **PARTIEL** (même statut que 24.07) |
| 24.28 [PRECISION] | — | ABSENT-LOG-MANQUANT — groupe d'allocation courant |
| 24.29 [PSYCHIC] | — | ABSENT-LOG-MANQUANT |
| 24.30 [RAPID FIRE X] | #41 (présence + valeur vs armurerie), #12 (lève le plafond) | **PARTIEL** — la condition « cible à demi-portée » n'est pas vérifiée, alors qu'elle est MESURABLE per-socle depuis `[MODELS:]`/`[TARGET_MODELS:]` |
| 24.31 Scouts | — | ABSENT-LOG-MANQUANT |
| 24.32 Scout move | — | ABSENT-LOG-MANQUANT (type de move absent) |
| 24.33 Stealth | — | ABSENT-LOG-MANQUANT |
| 24.34 Support | — | ABSENT-LOG-MANQUANT |
| 24.35 Super-heavy Walker | — | ABSENT-LOG-MANQUANT |
| 24.36 [SUSTAINED HITS X] | #42 (présence vs armurerie), #12/#28 (exclu du plafond), #39 (usage) | **PARTIEL** — le NOMBRE de touches additionnelles (X) n'est pas vérifié |
| 24.37 [TORRENT] | — | ABSENT-LOG-MANQUANT — aucun token ; le motif « auto-hit » n'est pas distinguable de `[SUSTAINED HITS]` |
| 24.38 [TWIN-LINKED] | #39 (usage) + token `wound_reroll_rule_name` + `[REROLLED:n]` | **PARTIEL** — aucun contrôle de cohérence entre le token et la relance effective |

---

## 4. Matrice B — `config/weapon_rules.json` (23 règles)

Toutes les paires (règle, arme) déclarées par l'armurerie apparaissent en §1.8 avec
`OK` / `NOT USED` / `INVALID`. **Présence dans ce tableau ≠ contrôle de conformité** : `INVALID`
ne qualifie qu'une chose — une paire observée que l'armurerie ne déclare pas.

| Règle d'arme | Règle PDF | Contrôle de conformité | Statut |
|---|---|---|---|
| `ANTI_FLY` | 24.03 | — | ABSENT-LOG-MANQUANT |
| `ANTI_INFANTRY` | 24.03 | — | ABSENT-LOG-MANQUANT |
| `ANTI_MONSTER` | 24.03 | — | ABSENT-LOG-MANQUANT |
| `ANTI_PSYKER` | 24.03 | — | ABSENT-LOG-MANQUANT |
| `ANTI_VEHICLE` | 24.03 | — | ABSENT-LOG-MANQUANT |
| `ASSAULT` | 24.04 / 10.05 | #39 usage (`shoot_handler.py:696`) | PARTIEL |
| `BLAST` | 24.05 | — | ABSENT-LOG-MANQUANT |
| `CLEAVE` | 24.06 | — | ABSENT-LOG-MANQUANT |
| `CLOSE_QUARTERS` | 24.07 / 10.06 | #11, #16, #17 + usage §1.8 (ancre, cf. §5) | PARTIEL |
| `DEVASTATING_WOUNDS` | 24.10 | #40 | PARTIEL |
| `EXTRA_ATTACKS` | 24.11 | — | ABSENT-LOG-MANQUANT |
| `HAZARDOUS` | 24.15 / 06.03 | ligne `hazardous`, jet loggué | PARTIEL |
| `HEAVY` | 24.16 | #39 usage ; validité supprimée | PARTIEL |
| `IGNORES_COVER` | 24.18 | — | ABSENT-LOG-MANQUANT |
| `INDIRECT_FIRE` | 24.19 / 10.07 | — | ABSENT-LOG-MANQUANT |
| `LETHAL_HITS` | 24.23 | — | ABSENT-LOG-MANQUANT |
| `MELTA` | 24.25 | — | ABSENT-LOG-MANQUANT |
| `PRECISION` | 24.28 / 05.03 | — | ABSENT-LOG-MANQUANT |
| `PSYCHIC` | 24.29 | — | ABSENT-LOG-MANQUANT |
| `RAPID_FIRE` | 24.30 | #41 + #12 | PARTIEL |
| `SUSTAINED_HITS` | 24.36 | #42 + #12/#28 + #39 | PARTIEL |
| `TORRENT` | 24.37 | — | ABSENT-LOG-MANQUANT |
| `TWIN_LINKED` | 24.38 | #39 + tokens | PARTIEL |

**0 COUVERT / 8 PARTIEL / 15 ABSENT-LOG-MANQUANT.**

---

## 5-bis. Matrice C — `config/unit_rules.json` (35 règles)

Base commune : §1.7 compte l'usage par (règle, type d'unité) et marque `INVALID` si le type
d'unité ne porte pas la règle. Les capacités de FACTION (`waaagh`, `oath_of_moment`) sont
rattachées par mot-clé de faction (`analyzer_config.py:318-328`), pas par `UNIT_RULES`.

| Règle | Contrôle | Statut |
|---|---|---|
| `charge_after_advance` | §1.7 + #23 (`charge_invalid.advanced`) | **COUVERT** |
| `charge_after_flee` | §1.7 + #24 | **COUVERT** |
| `shoot_after_advance` | §1.7 + `shots_after_advance` | **COUVERT** |
| `shoot_after_flee` | §1.7 + #14 | **COUVERT** |
| `move_after_shooting` | ligne dédiée + #5 (budget) + §1.7 | **COUVERT** |
| `reactive_move` | #6-#9 + §1.7 | **COUVERT** |
| `reroll_1_towound` | §1.7 via token `[TARGETED INTERCESSION]` ; `wound_ability_display_name` + `[REROLLED:n]` | PARTIEL — le jet de 1 relancé n'est pas recoupé avec le token |
| `reroll_1_tohit_fight` | `hit_ability_display_name` + `[REROLLED:n]` en mêlée | PARTIEL — usage compté seulement via la chaîne rule-choice |
| `reroll_1_save_fight` | `[REROLLED:n]` sur `Save` | PARTIEL — aucun nom de capacité côté save en mêlée → cause invisible |
| `reroll_towound_target_on_objective` | §1.7 (compté avec `targeted_intercession`) | PARTIEL — « la cible est sur un objectif » n'est pas vérifié |
| `reroll_charge` | — | ABSENT-LOG-MANQUANT — la ligne `CHARGED` ne porte que le jet final |
| `charge_impact` | ligne `IMPACTED` complète (seuil, jet, MW) + dégâts appliqués | **ABSENT-LOGGABLE** — 4+ → 1 MW et « cible dans l'engagement » sont vérifiables |
| `closest_target_penetration` | — | ABSENT-LOG-MANQUANT — AP non loggué |
| `cp_gain_on_objective` | — | **ABSENT-LOGGABLE** — `CP1=`/`CP2=` dans l'instantané ; gain GLOBAL, 1 CP max |
| `adrenalised_onslaught` | §1.7 rule-choice (source) | PARTIEL |
| `aggression_imperative` | §1.7 rule-choice (effet, alias `reroll_1_tohit_fight`) | PARTIEL |
| `preservation_imperative` | §1.7 rule-choice (effet, alias `reroll_1_save_fight`) | PARTIEL |
| `adaptable_predators` | §1.7 (parapluie) | PARTIEL |
| `adaptable_predators_shoot_after_flee` | alias → `shoot_after_flee` | PARTIEL (alias d'affichage) |
| `adaptable_predators_charge_after_flee` | alias → `charge_after_flee` | PARTIEL (alias d'affichage) |
| `cunning_hunters` | §1.7 (parapluie) | PARTIEL |
| `cunning_hunters_shoot_after_advance` | alias | PARTIEL |
| `cunning_hunters_shoot_after_flee` | alias | PARTIEL |
| `targeted_intercession` | §1.7 (parapluie) | PARTIEL |
| `targeted_intercession_reroll_1_towound` | alias | PARTIEL |
| `targeted_intercession_reroll_towound_target_on_objective` | alias | PARTIEL |
| `target_priority` | — (aucun `grants_rule_ids` déclaré) | PARTIEL — si une unité la porte sans grants, §1.7 comptera ses effets `INVALID` |
| `oath_of_moment` | **aucun** | **ABSENT-LOGGABLE** — ⚠️ **correction du 2026-08-09**. La première version de ce document le donnait PARTIEL en affirmant que §1.7 comptait son usage via le mot-clé de faction. C'est faux : `FACTION_ABILITY_KEYWORD_BY_RULE_ID` ne fait qu'inscrire la **ligne** dans le tableau (colonne Validité), et `grep "oath_of_moment\|OATH OF MOMENT"` sur les six fichiers de l'analyzer rend **0 hit**. Le compteur est structurellement à 0 — 1657 tokens `[OATH OF MOMENT]` relevés dans un journal réel, zéro usage compté. La ligne `T{tour} EFFECTS:` porte maintenant `oath_target` ET `oath_wound=+X` : il ne manque que le comptage et la vérification du seuil de blessure |
| `waaagh` | §1.7 + #23 (charge après advance) + `waaagh_melee_atk` lu par #28 | PARTIEL — le `+1 Attaques` est désormais LU dans `T{tour} EFFECTS:` et entre dans le plafond de mêlée ; `waaagh_melee_str` (+1 Force) et `waaagh_invul` (5++) sont journalisés mais **n'alimentent aucun contrôle** |
| `deep_strike` | — | PARTIEL — cf. 24.09 |
| `leader` | — | ABSENT-LOG-MANQUANT |
| `support` | — | ABSENT-LOG-MANQUANT |
| `feel_no_pain` | — | ABSENT-LOG-MANQUANT |
| `special_weapon` | — | NON-TESTABLE-OFFLINE (marqueur de rôle) |
| `sergeant` | — | NON-TESTABLE-OFFLINE (marqueur de rôle) |

**6 COUVERT / 19 PARTIEL / 3 ABSENT-LOGGABLE / 5 ABSENT-LOG-MANQUANT / 2 NON-TESTABLE.**

---

## 5. Verts vacants et pièges identifiés

| # | Constat | Emplacement | Effet |
|---|---|---|---|
| V1 | `damage_exceeds_hp` n'est **jamais incrémenté** | affiché `analyzer.py:2973`, sommé `:3192` et `:3372` | La ligne « Dmg > HP_CUR (overkill) » affiche 0 en permanence et **contribue à un ✅ dans le SUMMARY**. *Toujours vrai au 2026-08-09* |
| V2 | `fight_from_non_adjacent` n'est **jamais incrémenté** depuis 2026-07-24 | sommé `analyzer.py:3081` et `:3342` | Le total FIGHT ERRORS inclut un terme mort. *Toujours vrai* |
| V3 | `dead_unit_skipping` / `handle_skip` sont **inatteignables** | `shoot_handler.py:974-1011` | `skip` n'a aucun producteur (`_STEP_LOG_TYPE_MAP` ne le contient pas). *Toujours vrai* |
| V4 | §1.8 usage `CLOSE_QUARTERS` mesure `calculate_hex_distance(ancre_tireur, ancre_cible) == 1` | `shoot_handler.py:705` | Ancre au lieu du socle **et** adjacence au lieu de la zone d'engagement — exactement le motif corrigé 80 lignes plus haut pour les contrôles d'erreur. À x5, `ez=10` : le compteur d'usage est quasi toujours à 0. *Toujours vrai* |
| V5 | `reactive_move_abnormal` mesure la distance à l'**ancre** (`calculate_hex_distance`) | `analyzer_core.py:1056` | Son jumeau immédiat `distance_over_roll` (`:1114`) est per-socle : deux mesures contradictoires sur la même ligne. *Toujours vrai* |
| V6 | `_build_move_bfs_blockers` ignore l'exemption 17.01 (M/V traversent les figurines) | `analyzer.py:715` | Faux positifs « au-delà du budget » pour tout MONSTER/VEHICLE dont le chemin passe près d'une figurine. *Toujours vrai* |
| V7 | Le BFS de mouvement ne connaît pas le **bord du plateau** | `analyzer.py:777` | Un chemin sortant du plateau est accepté (03.01) ; `Board:` porte pourtant `cols`/`rows`. *Toujours vrai* |
| V8 | `devastating_wounds` suppose que **seul un 6** est critique | `shoot_handler.py:426-429` | Faux « incorrect » dès qu'une arme [ANTI-X Y+] rend critique un Y+ < 6. *Toujours vrai* |
| V9 | Le contrôle de portée ne rend **aucun verdict** quand ni `[TARGET_MODELS:]` ni les socles de la cible ne sont connus | `shoot_handler.py:667` | Choix délibéré et documenté, mais silencieux : rien ne compte les tirs non évalués. *Toujours vrai* |
| V10 | `FLED` n'a **aucun** contrôle de budget ni de chemin | `move_handler.py:81-187` | Seul déplacement sur six sans `_per_model_move_violation` (09.07). *Toujours vrai* |
| ~~V11~~ | ~~La double-activation ne couvre ni SHOOT ni FIGHT~~ | `analyzer_core.py:876-891` | **PARTIELLEMENT FERMÉ le 2026-08-09** : FIGHT est entrée dans la liste des phases, avec `) CONSOLIDATED ` pour marqueur. **SHOOT reste découvert** — `SHOT` n'est pas un marqueur d'activation, donc 10.02 (« une unité ne peut être sélectionnée qu'une fois pour tirer ») n'est toujours pas contrôlé |
| V12 | La ligne `phase Start` est produite et **jamais lue** | `step_logger.py` (`log_phase_transition`) | 07.02 (ordre des phases) reste non vérifié alors que la donnée existe. *Toujours vrai* |
| V14 | Le plafond de tir reste **par escouade** alors que celui de mêlée est passé par figurine | `shoot_handler.py:388` | Jumeau non traité du lot du 2026-08-09 : `[MODEL_TYPES:]` et `[SHOOTER_MODELS:]` existent et sont lus côté mêlée (`fight_handler.py:24`), pas côté tir. Même cause de faux positif (escouade hétérogène, arme homonyme), même remède disponible |
| V15 | Cinq des six clés de `T{tour} EFFECTS:` ne sont lues par personne | `analyzer_core.py:105` (parse) vs `fight_handler.py:24` (seul consommateur) | `waaagh_melee_str`, `waaagh_invul`, `oath_target`, `oath_wound` sont dans le journal et n'alimentent aucun contrôle. Le producteur a payé le coût, le lecteur n'a pas encaissé le gain |
| V13 | `has_line_of_sight` (ancre-à-ancre, documentée comme inexacte) classe les `WAIT` en `wait_with_los` / `wait_no_los` | `shoot_handler.py:866`, `:725` | Usage assumé « métriques comportementales », mais ces métriques servent au pilotage |

**Grep JUMEAU** `calculate_hex_distance|is_adjacent(` sur les 6 fichiers de l'analyzer → 4 sites de
mesure : `analyzer.py:874` (distance à vol d'oiseau **par socle**, légitime — 21.03),
`analyzer.py:954` (`get_adjacent_enemies`, **diagnostic seul** : n'alimente que les payloads
`first_error_lines` et les traces de debug, jamais un verdict), et les deux verts vacants
V4 (`shoot_handler.py:700`) et V5 (`analyzer_core.py:797`). Aucun autre résidu ancre-à-ancre.

---

## 6. Synthèse chiffrée

### 6.1 Règles PDF (156)

| Statut | Nombre | % |
|---|---|---|
| COUVERT | 5 | 3,2 % |
| PARTIEL | 35 | 22,4 % |
| ABSENT-LOGGABLE | 10 | 6,4 % |
| ABSENT-LOG-MANQUANT | 68 | 43,6 % |
| NON-TESTABLE-OFFLINE | 38 | 24,4 % |

Par famille :

| PDF | Total | COUVERT | PARTIEL | ABS-LOGGABLE | ABS-LOG-MANQ | NON-TESTABLE |
|---|---|---|---|---|---|---|
| 01 Core concepts | 7 | 1 | 0 | 1 | 2 | 3 |
| 02 Datasheets | 7 | 0 | 0 | 0 | 1 | 6 |
| 03 Moving | 4 | 1 | 2 | 1 | 0 | 0 |
| 04 Making attacks | 3 | 0 | 3 | 0 | 0 | 0 |
| 05 Attack sequence | 4 | 0 | 1 | 1 | 2 | 0 |
| 06 Other concepts | 3 | 0 | 0 | 1 | 1 | 1 |
| 07 Battle round | 3 | 0 | 0 | 1 | 0 | 2 |
| 08 Command phase | 5 | 0 | 0 | 1 | 2 | 2 |
| 09 Movement phase | 7 | 1 | 3 | 0 | 1 | 2 |
| 10 Shooting phase | 7 | 0 | 3 | 1 | 1 | 2 |
| 11 Charge phase | 4 | 0 | 2 | 0 | 0 | 2 |
| 12 Fight phase | 9 | 1 | 3 | 2 | 0 | 3 |
| 13 Terrain | 11 | 0 | 1 | 0 | 0 | 10 |
| 14 Objectives | 3 | 1 | 0 | 0 | 1 | 1 |
| 15 Stratagems | 12 | 0 | 0 | 0 | 12 | 0 |
| 16 Actions | 1 | 0 | 0 | 0 | 1 | 0 |
| 17 Monsters & vehicles | 3 | 0 | 2 | 0 | 0 | 1 |
| 18 Transports | 5 | 0 | 0 | 0 | 5 | 0 |
| 19 Attached units | 4 | 0 | 1 | 0 | 2 | 1 |
| 20 Strategic reserves | 4 | 0 | 2 | 1 | 1 | 0 |
| 21 Flying & surging | 3 | 0 | 1 | 0 | 2 | 0 |
| 22 Other rules | 5 | 0 | 1 | 0 | 3 | 1 |
| 23 Aircraft | 4 | 0 | 0 | 0 | 4 | 0 |
| 24 Core abilities | 38 | 0 | 10 | 0 | 27 | 1 |
| **Total** | **156** | **5** | **35** | **10** | **68** | **38** |

### 6.2 Règles d'armes (23) et d'unité (35)

| Corpus | Total | COUVERT | PARTIEL | ABS-LOGGABLE | ABS-LOG-MANQ | NON-TESTABLE |
|---|---|---|---|---|---|---|
| `weapon_rules.json` | 23 | 0 | 8 | 0 | 15 | 0 |
| `unit_rules.json` | 35 | 6 | 19 | 3 | 5 | 2 |

### 6.3 Tous corpus confondus (214 lignes)

| Statut | Nombre | % |
|---|---|---|
| COUVERT | 11 | 5,1 % |
| PARTIEL | 62 | 29,0 % |
| ABSENT-LOGGABLE | 13 | 6,1 % |
| ABSENT-LOG-MANQUANT | 88 | 41,1 % |
| NON-TESTABLE-OFFLINE | 40 | 18,7 % |

### 6.4 Côté analyzer

| | Nombre |
|---|---|
| Contrôles de conformité vivants | 62 (59 + les 3 de §2.8) |
| dont morts / inatteignables | 3 (V1, V2, V3) |
| dont mesurant la mauvaise grandeur | 6 (V4, V5, V6, V7, V8, V14) |
| Contrôles supprimés, documentés, à ne pas ré-écrire | 5 |
| Sections de rapport | 16 (§1.1–§1.8, §2.1–§2.8) — dont 4 purement diagnostiques (§2.4, §2.5, §2.6, §2.7) |

### 6.5 Mouvement net depuis la première version (2026-08-08 → 2026-08-09)

| | Avant | Après |
|---|---|---|
| COUVERT (tous corpus) | 10 | 11 |
| ABSENT-LOGGABLE | 13 | 13 (12.07 fermé, `oath_of_moment` reclassé) |
| Contrôles vivants | 59 | 62 |
| Verts vacants ouverts | 13 | 14 (V11 partiellement fermé, V14 et V15 ouverts) |

Le gain de couverture est **modeste par construction** : les quatre lots de nuit ont surtout
supprimé des **faux positifs** (2218 → 18 erreurs sur un run) et ajouté un point de recalage
(§2.8). Ils rendent le rapport *fiable*, pas plus *complet*. Les 88 `ABSENT-LOG-MANQUANT`
n'ont pas bougé.

**Lecture d'ensemble.** La couverture réelle se concentre sur la géométrie du mouvement et de
l'engagement (03, 09, 11, 12 partiels, 21) et sur l'éligibilité au tir (10). Les 41 % de
`ABSENT-LOG-MANQUANT` se répartissent en trois blocs quasi disjoints :
**(a)** les sous-systèmes non implémentés ou non journalisés (15 Stratagems, 16 Actions,
18 Transports, 23 Aircraft, 21.01–21.02 Surge) — 26 règles ;
**(b)** les abilités d'arme sans token (24.03/05/06/11/18/19/21/23/25/26/28/29/31–35/37) — 20 règles ;
**(c)** la mécanique de résolution d'attaque au niveau figurine (05.02, 05.03, 06.02, 24.12, 24.28,
02.02) et le battle-shock (01.06, 01.07, 08.03, 14.03).

---

## 7. Liste consolidée des champs manquants du StepLogger

Ordonnée par nombre de règles débloquées. « Débloque » = fait passer la règle de
`ABSENT-LOG-MANQUANT` à au moins `ABSENT-LOGGABLE`.

**Déjà livré par les lots du 2026-08-09** (retiré de la liste ci-dessous) : `AGENT_PLAYER=`
(siège de l'agent), `[MODEL_TYPES:]` (datasheet par figurine), `T{tour} STATE:` (point de recalage
d'état) et `T{tour} EFFECTS:` (effets en vigueur avec contribution chiffrée). Ce dernier livre
`waaagh_melee_str` (+1 Force), qui était le **volet manquant de L2** : le seuil de blessure
modifié devient explicable, même si `S` et `T` de base restent absents.

| # | Champ / ligne à ajouter | Format proposé | Débloque |
|---|---|---|---|
| L1 | **Drapeau `battle_shocked` par unité** + jet de battle-shock | ligne `Unit N BATTLE-SHOCK Roll:2D6=<n> vs Ld<n>+ → SHOCKED\|OK` | 01.06, 01.07, 02.02 (OC='-'), 08.03, 14.02, 16.01, 15.04 |
| L2 | **`S` de l'arme et `T` de la cible** sur chaque jet | `Wound R(T+) [S<n> vs T<n>]` | 05.02, 19.02, 24.03 |
| L3 | **Figurine cible allouée** + groupe d'allocation | `→ <mid>` sur la partie `Save`/`Dmg` | 05.03, 05.04, 06.02, 24.28 |
| L4 | **`AP` de l'arme, `Sv`/`InSv` du groupe** | `Save R(<base>+ AP<n> → <eff>+)` | 05.04, `closest_target_penetration`, 24.18 |
| L5 | **Tokens d'abilité d'arme manquants** | `[ANTI-X:Y+]`, `[LETHAL HITS]`, `[TORRENT]`, `[MELTA:X]`, `[BLAST:+n]`, `[CLEAVE:+n]`, `[IGNORES COVER]`, `[INDIRECT FIRE]`, `[PRECISION]`, `[PSYCHIC]`, `[EXTRA ATTACKS]`, `[LANCE]` | 24.03, 24.05, 24.06, 24.11, 24.18, 24.19, 24.21, 24.23, 24.25, 24.28, 24.29, 24.37, 10.07 |
| L6 | **Ligne `stratagem`** (nom, CP dépensés, cible, phase) | `P<n> STRATAGEM [<NOM>] -<n>CP → Unit M` | 15.01–15.12 (12 règles) |
| L7 | **Lignes `action_start` / `action_complete`** | `Unit N ACTION START [<nom>]` / `… COMPLETE` | 16.01, 09.06, 09.07, 10.04–10.07 (volets « AFTER: pas d'action ») |
| L8 | **Transports** : capacité, embark, disembark (mode + jet de hasard) | types `embark`, `disembark` dans `_STEP_LOG_TYPE_MAP` | 18.01–18.05 |
| L9 | **Zones de déploiement + bords de plateau utilisables** | entête `Deployment: P1=<rect> P2=<rect>` | 03.02, 20.04, 24.09, 24.20, 24.31, 24.32 |
| L10 | **Type de move / de tir / de fight EXPLICITE** (au lieu d'être déduit des tokens) | suffixe `[MOVE_TYPE:normal\|advance\|fall_back\|remain_stationary\|ingress\|surge\|scout]`, `[SHOOT_TYPE:normal\|assault\|close_quarters\|indirect]` | 09.02, 09.04, 09.07, 10.02, 10.04–10.07, 12.05, 12.06, 21.02, 24.32 |
| L11 | **Mode de fall-back** (`ordered_retreat` / `desperate_escape`) + jets de hasard associés | `FLED [DESPERATE ESCAPE] … Hazard:<n>,<n>,…` | 09.07, 06.03, 18.04 |
| L12 | **Jets Feel No Pain** | `FNP:<n>/<seuil>+ ×<n>` | 24.12 |
| L13 | **Distance tireur↔cible au Select Targets** (ou marqueur `[HALF RANGE]`) | `[HALF RANGE]` | 24.25, 24.30 |
| L14 | **Statut Fights First** de l'unité activée | `[FIGHTS FIRST]` sur la ligne `FOUGHT` | 24.13, 12.04, 11.04, 15.12 |
| L15 | **Nombre d'armes [HAZARDOUS] sélectionnées** | `[HAZARDOUS:<n>] Roll:<n>,<n>,…` | 24.15 |
| L16 | **Cibles de charge multiples** (11.04 autorise plusieurs) | `CHARGED Unit M(…),Unit K(…)` | 11.04 |
| L17 | **Cibles de pile-in / mode de consolidation** | `PILED IN [targets: M,K]`, `CONSOLIDATED [ONGOING\|ENGAGING\|OBJECTIVE:<id>]` | 12.03, 12.08 |
| L18 | **Objectifs : drapeau `secured` + OC par figurine** | extension de `ZONES=` | 14.02, 14.03 |
| L19 | **Attached units** : lien leader/support ↔ bodyguard | entête `Attached: <leader_id>→<bodyguard_id>` | 19.01, 19.02, 19.04, 24.22, 24.34 |
| L20 | **Terrain** : catégorie et hauteur par hexe | entête `Terrain: <cat>@(c,r,h)…` | 13.02–13.11, 06.01, 22.05 (lève aussi 10 NON-TESTABLE) |
| L21 | **Aircraft** : keyword et placement forcé en réserves | — | 23.01–23.04 |
| L22 | **Segment `[MODELS:]` sur la ligne `REACTIVE MOVED`** | segment existant, non émis | rend #7 per-figurine (03.04) et supprime V5 |
| L23 | **Type `surge` dans `_STEP_LOG_TYPE_MAP`** | — | 21.01, 21.02 |
| L24 | **Producteur pour `skip`** (le formateur existe) | — | rend #52 atteignable |
| L25 | **Capacités de commandement déclarées** (Waaagh! appelé, cible Oath of Moment) | `P<n> COMMAND [WAAAGH!]` / `[OATH OF MOMENT] → Unit M` | 08.04, 22.02, `waaagh`, `oath_of_moment` |
| L26 | **Modificateurs de touche hors HEAVY/COVER** (`hit_target_base` généralisé) | `Hit R(<base>+->_<eff>+) [<cause>]` | 10.06 (−1 M/V), 17.03, 22.05, 24.29, 15.09 |
| L27 | **Relance de sauvegarde en mêlée : nom de la capacité** | `_ability_token` côté `Save` de `combat` | `reroll_1_save_fight`, `preservation_imperative` |
| L28 | **Relance de charge : token** | `CHARGED [<CAPACITÉ>] … [REROLLED:<jet initial>]` | `reroll_charge` |

**Champs déjà présents et simplement non exploités** (aucune modification du StepLogger requise —
c'est le gisement le moins cher) :

| Champ présent | Non exploité par | Débloquerait |
|---|---|---|
| `T{tour} EFFECTS: oath_target`, `oath_wound=+X` | aucun contrôle | `oath_of_moment` (usage + validité du `+1` blessure), 08.04, 22.02 |
| `T{tour} EFFECTS: waaagh_melee_str`, `waaagh_invul` | aucun contrôle | volet Force et 5++ de `waaagh` |
| `[MODEL_TYPES:]` + `[SHOOTER_MODELS:]` côté TIR | `shoot_handler.py:388` | plafond de tir par figurine (V14) — le jumeau de ce que la mêlée vient d'obtenir |
| `[FIGHT_SUBPHASE:<x>]` | aucun contrôle | 12.06 (overrun fight) |
| ligne `phase Start` | aucun contrôle | 07.02 (ordre des phases) |
| `CP1=` / `CP2=` | aucun contrôle | 08.02, `cp_gain_on_objective` |
| `[MODELS:]` complet | aucun contrôle de cohérence | 03.03 (coherency, y compris la purge End of Turn) |
| positions + `Board: cols/rows` | BFS (`analyzer.py:777`) | bord de plateau (V7, 03.01), `>8"` d'ingress (20.03, 20.04) |
| `Hit R(T+)` + `hit_result` | aucun contrôle | 05.01 (cohérence jet/seuil/résultat) |
| `[HAZARDOUS] Roll:N` + `SUFFERS X MW` | aucun contrôle | 06.03 |

---

## 8. Ce qui a été vérifié, et ce qui ne l'a pas été

**Vérifié par lecture intégrale** : `ai/step_logger.py`, `ai/analyzer_perfig.py`,
`ai/analyzer_state.py`, `ai/analyzer_config.py`, `ai/analyzer_core.py`,
`ai/analyzer_phases/{move,charge,fight,shoot,episode}_handler.py`, les helpers géométriques et de
dégâts de `ai/analyzer.py` (l. 196-982) et la totalité de sa section de rapport (l. 1535-3320),
`config/weapon_rules.json`, `config/unit_rules.json`, le texte intégral des 25 PDF, et les points
d'émission `step.log` de `engine/w40k_core.py` (`_STEP_LOG_*`, `_build_step_log_details`,
`_build_shot_details`, `_models_segment_for_unit`, `_run_rules_for_step_log`,
`_record_rule_choice_action_log`) + `engine/action_log_utils.py`.

**Mise à jour du 2026-08-09** : relecture du `git diff` complet des quatre lots sur
`ai/analyzer*.py`, `ai/analyzer_phases/*`, `ai/step_logger.py` et `engine/w40k_core.py`
(`_log_effects_snapshot_if_changed`), puis re-grep de tous les sites d'incrémentation cités pour
en refixer les numéros de ligne. Les verts vacants V1–V10 et V12 ont été **re-vérifiés un par un**
sur `main` : tous encore ouverts.

**Non vérifié** :
- Aucun `step.log` réel n'a été analysé : les statuts décrivent le CODE, pas une mesure sur un run.
  Les verts vacants V1–V3 sont prouvés par absence de site d'incrémentation (grep exhaustif) ;
  V4–V15 par lecture du prédicat. Les chiffres de run cités par les lots de nuit (2218 → 18,
  1657 tokens Oath) proviennent de leurs rapports, je ne les ai pas reproduits.
- Les tests ajoutés par les quatre lots n'ont pas été lus : je ne dis rien de ce qu'ils
  verrouillent.
- La régénération d'une référence en x1 (plateau 44×60) reste ouverte : sans elle, les compteurs
  §1.1–§1.4 d'un run x5 ne sont pas comparables au baseline historique.
- `ai/unit_registry.py` et le contenu des datasheets n'ont pas été relus : les statuts
  « NON-TESTABLE-OFFLINE (registre) » supposent que le registre porte bien ces champs.
- Les chemins PvP/replay (`services/`, `frontend/`) sont hors périmètre : cette matrice ne
  concerne que `step.log` → `analyzer`.
- `target_priority` (`unit_rules.json`) : son classement PARTIEL dépend de la présence de
  `grants_rule_ids` dans les datasheets, non relues.
