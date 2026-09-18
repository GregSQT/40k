# Mêlée 100 % (lot `melee-100`) — D+, A1–A5, B2, B3, P8, P9

Ouvert et livré le 2026-09-18 (branche `worktree-melee-100`). Source des règles :
`Documentation/40k_rules/` (PDF 04, 11, 12, 24, 25 relus). Tout le lot change les parties jouées
→ `--new` de la lignée assumé (ROADMAP_INDEX, Direction). Mesure de référence prise AVANT le
premier correctif et rejouée APRÈS (`scripts/melee_bench.py`, §5).

## 1. Origine

Mesures bot contre bot du 2026-09-18 (TacticalBot des deux côtés, moteur `5b2422dd5`, x1) : une
activation de mêlée ne faisait frapper que les porteuses du code d'arme choisi par l'agent (43 %
des figurines engagées, 178 attaques sur 403 possibles) ; les [EXTRA ATTACKS] jamais complétées sur
le chemin gym ; pile-in gym arrêté au premier anneau ; plan de charge gym à 2" quand le contact
était atteignable ; consolidation engaging « sélectionnant » tous les ennemis à 3" ; unité
éligible sans cible marquée « selected to fight » (plus de New Foe possible) ; consolidation
engaging jouée d'office par le driver (J2 : aucune décision par heuristique).

## 2. Livré (un commit par sujet, tous rouge → vert)

| Sujet | Règle | Ce qui change | Tests |
|---|---|---|---|
| P0 banc | — | `scripts/melee_bench.py` : 40 parties bot contre bot, sondes à l'émission des `action_logs` (`_append_entry`) et sur `build_manual_fight_allocation` / `squad_consolidate_plan_with_targets` / `fight_v11_consolidation_freeze_new_foes` ; JSON par joueur et par siège | `tests/unit/ai/test_melee_bench.py` (3) |
| D+ (P1) | 04.01, 04.02, 24.11 | `squad_auto_declare_fight_weapons` (arme ordinaire unique d'office + toutes les [EXTRA ATTACKS]) ; question d'arme seulement pour ≥ 2 armes ordinaires, reposée tant qu'il en reste, réponse appliquée à toutes les porteuses du profil interrogées (restriction documentée : pas de choix par figurine) ; figurines engagées seulement avec un autre ennemi : déclarées d'office s'il est unique, sinon question de cible restreinte (`PENDING_FIGHT_TARGET_KEY` + `model_ids`) ; répartition d'une arme entre deux unités non exposée (documenté). Aucune figurine des rosters Armageddon n'a deux armes ordinaires : la question d'arme n'est jamais posée sur ces rosters | `test_fight_all_engaged_models_strike.py` (4), `test_fight_weapon_slot.py` (+1), fixtures adaptées |
| A1 (P2) | 12.03 | `_assign_cells_toward_enemies` : trois paliers (contact par couplage maximum, case ENGAGÉE avec la cible la plus proche dans tout le budget, sinon case la plus proche dans tout le budget) + légalité de l'EMPREINTE entière des candidats (x5) ; `target_ids` passé par les deux appelants | `test_pile_in_gym_engaged_if_possible.py` (2) |
| A2 (P3) | 11.04 | `charge_build_valid_plan` : paliers contact / ≤ 1" / engagé (mémo de charge = palier), intention L10 = départage dans le palier le plus serré, figurines les plus proches placées en premier ; `base_contact_zone` partagé avec `model_in_base_contact` | `test_charge_plan_engagement_range.py` (+3) |
| A3 / A4 (P4) | 12.08 | `squad_consolidate_plan_with_targets` : sélection engaging = point fixe des ennemis que le plan engage ; objective « closer to it if not » ; sélection journalisée `[targets: …]` sur `CONSOLIDATED` (gym) | `test_consolidation_gym_if_possible.py` (4), `test_step_log_pile_in_consolidation.py` (+2) |
| B3 (P5) | 12.03 | pile-in d'overrun dirigé vers la cible désignée quand l'unité n'est pas engagée et que la cible est à ≤ 5" (`fight_pile_in_plan(target_ids=…)`, `_overrun_pile_in_target_ids`) | `test_fight_target_reselect_overrun.py` (+2) |
| A5 (P6) | PDF 25 | passe de l'étape FIGHT : `fight_v11_can_pass` (toutes les unités éligibles du sélecteur à > 5"), `squad_fight_pass` décodée sur le slot sans cible, `fight_pass_streak` / `fight_step_passed`, unités passées éligibles à la consolidation ; machine manuelle `fight_pass` + `can_pass` + bouton « Passer » ; ligne `PASSED FIGHT` (step.log, analyzer `fight_pass`) ; récompense 0 | `test_fight_pass_rule.py` (7), vitest `TurnPhaseTracker.test.tsx` (+2) |
| B2 (P7) | 12.07, 12.08 | décision `consolidation_engaging` (14e type, `CHOICE_0` consolider / `CHOICE_1` rester) armée par le driver gym avant le plan ; réponse mémorisée par phase ; bot de référence = `CHOICE_0` (ancien comportement) | `test_consolidation_engaging_decision.py` (5), obs (+1), `test_fight_pve_par_siege.py` adapté |
| P8 | — | `06_fight/b_engaging_consolidations_{agent,opponent}`, `c_new_foes_subies`, `d_fights_multi_niveaux`, `e_engaged_idle_models` ; logs enrichis (`newFoesFrozen`, `attackerLevels`/`targetLevels`, `fight_declaration`) ; `W40KEngine._fight_counters_from_action_logs` | `tests/unit/ai/test_metrics_fight_counters.py` (3) |
| P9 | 04.02, 11.04, 12.03, 12.08 | analyzer #70–#73 : `charge_no_contact`, `fight_engaged_idle`, `fight_pile_in_no_engage`, `fight_consolidation_not_all_selected` ; corpus `PROJ.1.3.contact`, `PROJ.1.4.engagees_inactives`, `PROJ.1.4.pile_in_engage`, `PROJ.1.4.conso_toutes_selectionnees` | 4 fichiers (20) |

## 3. Décisions prises pendant le lot

- **Bot de référence sur `consolidation_engaging` = `CHOICE_0` (consolider)** et non « rester » comme le prompt P7 le proposait : c'est l'ancien comportement du driver, donc la baseline de win-rate ne bouge pas (même doctrine que `move_after_shooting`, `reactive_move`, `fall_back_mode` dans `bot_action_for_pending_choice`). Un changement de doctrine des bots est une décision de mesure, pas d'implémentation — arbitrage rendu à l'utilisateur dans le rapport de livraison.
- **Question d'arme** : « la réponse s'applique à toutes les porteuses du profil » est une restriction documentée (pas de choix figurine par figurine) ; 04.02 « split » d'une arme entre deux unités n'est pas exposé à l'agent.
- **Passe A5** : quand la passe est possible, elle REMPLACE le combat à vide sur le même slot (aucune raison de marquer une unité qui ne peut frapper personne) ; à ≤ 5" sans cible atteignable, le combat à vide reste obligatoire.
- **Pile-in gym à x5** : la légalité de l'empreinte entière est vérifiée sur les paliers 2 et 3 (le repli d'un anneau ne pouvait pas chevaucher, un saut de 15 subhex le pouvait).

## 4. Restrictions / non couvert

- Le chemin PvP humain (machine manuelle) journalise `CONSOLIDATED` sans `[targets:]` : #73 n'y juge rien ; `newFoesFrozen` absent sur ce chemin (courbe `c_` = gym).
- `d_fights_multi_niveaux` reste à 0 sur les terrains actuels (A6 non livré, optionnel P11).
- Une figurine sans arme de mêlée n'est pas déclarée (04 « cannot make melee attacks ») ; le banc la compte engagée.

## 5. Mesure avant / après (`scripts/melee_bench.py`, 40 parties, x1, TacticalBot 0,05, graines 4242–4281)

`logs/melee_bench_avant_2026-09-18.json` (moteur `5b2422dd5`) → `logs/melee_bench_apres_2026-09-18.json` (moteur du lot).

| Mesure (deux joueurs cumulés) | Avant | Après |
|---|---|---|
| Figurines qui frappent / engagées | 318 / 598 = **0,53** | 573 / 573 = **1,00** |
| Attaques jetées / possibles | 1 049 / 2 042 = 0,51 | 1 917 / 1 917 = 1,00 |
| Figurines tuées en mêlée · VALUE | 151 · 3 275 | **242 · 5 367** |
| Figurines tuées au tir · VALUE | 457 · 8 208 | 435 · 7 308 |
| Charges réussies / déclarées | 81 / 242 | 82 / 259 |
| Après charge : contact / engagée / hors | 118 / 255 / 143 (contact 23 %) | **235** / 103 / 111 (contact **52 %**) |
| Après pile-in : contact / engagée / hors | 533 / 129 / 100 | 522 / 176 / 104 |
| Consolidations ongoing / engaging / objective / plan vide | 115 / 1 / 19 / 30 | 90 / 4 / 32 / 18 |
| New Foes déclenchés | 0 | 3 |
| Victoires J1 / J2 · siège agent / adversaire | 26 / 14 · 22 / 18 | 22 / 18 · 24 / 16 |
| VALUE mêlée J1 / J2 | 1 410 / 1 865 | 2 086 / 3 281 |

Lecture : le ratio « hors engagement après pile-in » ne bouge pas (13 %) — le banc compte toutes
les figurines, y compris celles qui n'ont aucune case engageante atteignable ; c'est le contrôle
analyzer #72 qui juge le « si possible ». Les consolidations engaging passent de 1 à 4 avec le bot
qui répond toujours « consolider » : le point de choix ne change pas le jeu du bot, la sélection
réelle (A3) rend des plans là où l'ancienne validation « au moins un engagé » suffisait déjà.

## 6. Seuils de gate / promotion relus (non modifiés)

`curriculum.json` : gate 0,65 contre le champion et 0,60 contre chaque archive, promotion aux
mêmes seuils, destruction à 0,40, exploiteurs `win_rate_target` 0,70 — tous RELATIFS (contre un
membre du pool entraîné sur le même moteur) : le déplacement d'équilibre du lot ne les rend pas
faux. Le seul seuil ABSOLU est la règle de lecture de P0′ (robuste ≥ 0,85 contre les bots) :
les bots frappent eux aussi avec toutes leurs figurines, le niveau atteint par un P0 neuf sur ce
moteur est à relire sur le premier run, pas à préjuger.

## 7. Corrections de review (2026-09-18, avant merge)

Quatre findings `/code-review` reproduits puis corrigés, chacun rouge → vert :

- **A5, passe qui rebondit sur le passeur** : `fight_v11_can_pass` ne jugeait que le pool de
  l'étape courante (FF), pas « all of that player's units that are eligible to fight » — une
  Remaining engagée n'interdisait pas la passe ; et l'alternance 12.04 rendait la main au passeur
  quand l'adversaire n'avait aucune unité FF (deux passes forcées, étape close, combats Remaining
  jamais joués). Correctif : la passe juge TOUTES les unités éligibles du sélecteur ;
  `fight_pass_handoff` (posé par `fight_v11_register_pass`, levé par toute sélection) fait
  sélectionner l'adversaire — dans FF s'il y a une unité, sinon dans Remaining ; la passe inscrit
  TOUTES les unités éligibles du passeur dans `units_eligible_when_passed` (12.08 « was eligible
  to fight this phase »), pas seulement le pool. `test_fight_pass_rule.py` (+3).
- **PvE, `/game/ai-turn` réentrait le driver avec la décision B2 en attente** : la décision
  `consolidation_engaging` armée à la fin du dernier `squad_fight` du bot était réarmée par
  `_fight_v11_gym_settle` à la requête suivante → RuntimeError hors du try/except (500). Correctif
  dans `execute_ai_turn` : décision pendante du bot → pas de driver, la politique répond
  (`agent_decision`) ; décision pendante de l'humain → `not_ai_player_turn`
  (`human_decision_pending`). `test_fight_pve_par_siege.py` (+2 ; fixture purgée de la décision
  `fall_back_mode` que `reset()` laissait en attente).
- **Analyzer #70 `charge_no_contact`, faux positifs** : `reachable_cell_engaging` acceptait une
  case à ≤ 1" de la cible située dans l'ER d'un ennemi NON-cible, que le moteur refuse (11.04
  AFTER MOVING). Correctif : `forbidden_ids` / `forbidden_zone` (ennemis vivants hors cibles de
  la ligne, zone d'engagement) — le pile-in (#72) n'a pas cette restriction et passe une liste
  vide. `test_analyzer_charge_contact.py` (+3).
- **Bouton « Passer » en consolidation** : `fight_can_pass` n'était écrit que par la branche
  FIGHT de la machine manuelle et restait True après une passe qui clôt l'étape. Correctif :
  remis à False à `fight_v11_start` et `fight_v11_enter_consolidate` (source moteur, aucun
  gating front ajouté). `test_fight_pass_rule.py` (+1).
