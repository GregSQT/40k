# Moteur — Tâches ouvertes

> **⛔ Moteur FIGÉ pour la démo (décision utilisateur, 2026-09-16 soir)** — moteur de référence
> `b2e8e241f`. Aucun chantier ci-dessous qui change les parties jouées ne démarre avant la démo
> sans décision explicite et `--new` assumé de la lignée ; règle complète dans
> [ROADMAP_INDEX.md — Direction](ROADMAP_INDEX.md#direction).

---

## Mêlée 100 % — lot melee-100 {#melee-100}

✅ **Livré 2026-09-18** (`worktree-melee-100`). D+ toutes les figurines engagées frappent (04.01 /
04.02 / 24.11) ; A1 pile-in gym « engagée si possible » en trois paliers (12.03) ; A2 charge gym
« contact si possible » (11.04) ; A3/A4 consolidation gym : sélection engaging réelle, objective
« closer if not » (12.08) ; A5 passe de l'étape Fight (PDF 25) ; B2 consolidation engaging =
décision de l'agent (`consolidation_engaging`, 15e type) ; B3 pile-in d'overrun dirigé vers la cible désignée (**parité masque/commit rétablie le 2026-09-18, suite 160** : oracle unique `overrun_pile_in_plan_for_slot`, un plan par slot ; et décision `consolidation_engaging` armée seulement si le plan existe) ; **empreintes de socles et palier contact, 2026-09-19, suite 164** : les plans gym suivent l'occupation par empreinte et non par centre, le palier contact est retiré (mort à x5) au profit d'un service par contrainte croissante et d'une passe de reprise ; P8 quatre
courbes `06_fight/` ; P9 quatre contrôles analyzer (#70–#73) ; corrections de review avant merge (passe A5 sur toutes
les éligibles + handoff à l'adversaire, driver PvE et décision B2, analyzer #70 et ER non-cible,
`fight_can_pass` — `melee_100.md` §7). **Change les parties jouées →
`--new` de la lignée.** Banc de référence `scripts/melee_bench.py` (40 parties bot contre bot, x1) :

| Mesure (deux joueurs) | Avant (`5b2422dd5`) | Après |
|---|---|---|
| Figurines qui frappent / engagées | 318 / 598 = 0,53 | 573 / 573 = 1,00 |
| Attaques jetées / possibles | 1 049 / 2 042 = 0,51 | 1 917 / 1 917 = 1,00 |
| Tuées en mêlée · VALUE | 151 · 3 275 | 242 · 5 367 |
| Tuées au tir · VALUE | 457 · 8 208 | 435 · 7 308 |
| Contact après charge | 118 / 516 = 23 % | 235 / 449 = 52 % |
| Après pile-in contact / engagée / hors | 533 / 129 / 100 | 522 / 176 / 104 |
| Consolidations ongoing / engaging / objective / vide · New Foes | 115 / 1 / 19 / 30 · 0 | 90 / 4 / 32 / 18 · 3 |
| Victoires J1 / J2 · siège agent / adversaire | 26 / 14 · 22 / 18 | 22 / 18 · 24 / 16 |

Seuils de gate / promotion relus, non modifiés (relatifs au pool ; seule la règle absolue « robuste
≥ 0,85 » de P0 est à relire sur le premier run). Décisions, restrictions et journal :
`Documentation/Archives/chantiers/melee_100.md`.

**Reste ouvert (optionnel, P11)** : A6 — pile-in et consolidation gym verticaux (13.06) : sans
effet sur les terrains actuels (planchers à 3", budget 3" consommé par la hauteur), courbe
`06_fight/d_fights_multi_niveaux` = 0 en attendant.

## Capacités Armageddon → décisions d'agent (lot du 2026-09-18) {#capacites-decisions-agent}

Huit chantiers en séquence, ordre imposé par le prompt du 2026-09-18 ; référence vivante
[capacites.md](../Reference/moteur/capacites.md). Aucun run lancé avant la fin du lot ; le `--new`
de la lignée suit le chantier 8.

1. ✅ **Hail of Bolts / Overlapping Detonations → cible DÉSIGNÉE** (2026-09-18). Le Bloc B de
   `_manual_roll_intent` bonifiait CHAQUE cible du tir fractionné ; la datasheet dit « that targeted
   that selected unit ». Modélisation : désignée = cible prioritaire (gym `SHOOT_SLOT`) ou première
   déclarée (siège humain), clé unique `designated_shoot_target_id` posée par
   `designate_shoot_target` sur les quatre chemins de déclaration (ex-`_last_shoot_target_id`, que
   lisait la suppression), visibilité vérifiée pour les porteurs. Journal `[DESIGNATED:<id>]` sur
   toute ligne SHOT (grammaire 11) ; l'analyzer ne lève le plafond `shoot_over_rng_nb` que pour
   les tirs sur la désignée, abstention sur journal antérieur. Reproduction (deux Intercessors, deux
   cibles) rendue 4 + 2 records au lieu de 4 + 4 ; 4 tests moteur + 6 analyzer rouge→vert.
2. ✅ **Refonte du bloc candidat de décision** (2026-09-18). Le one-hot positionnel `grants_*`
   (`DECISION_GRANTABLE_EFFECT_IDS`, 7 effets × 6 slots) était le dernier endroit où une règle
   coûtait des scalaires : chaque capacité ACTIVABLE aurait ajouté 6 bits et un `--new`. Un
   candidat porte désormais l'`obs_id` de son effet (`decision_options_effect_ids`, 6 × 1, lu par
   `ability_embedding` — même table que « ce que j'ai ») ; `DECISION_OPTION_BIN_FIELDS` =
   (`declines`, `present`) ; une seule liste (`UNIT_RULE_EFFECT_IDS`) dans la garde d'
   `agent_decision`. `obs_size` 18269 → **18241** (−42 + 6 + 8 : `AGENT_DECISION_TYPE_SLOTS`
   16 → 24, type `suppress_target` déclaré en fin de tuple), `TOTAL_ACTION_SIZE` 1389 inchangé
   (`test_action_space_mirror`). Socle `engine/ability_calls.py` : `push_ability_call(gs, squad,
   effet, phase)` empile un prompt `kind=ability_call` à deux candidats dans la file
   `pending_rule_choice_queue`, servie aux trois sièges (gym `CHOICE_0/1`, bot par
   `ABILITY_CALL_BOT_POLICIES` — aussi pour le bot adversaire du gym via `env_wrappers`, humain
   par le panneau rule_choice avec `decline`) ; application par `ABILITY_CALL_HANDLERS`, file
   vidée AVANT l'application pour qu'un gestionnaire puisse poser sa propre décision ; journal
   `ABILITY CALL <Nom> [USED|DECLINED]` (step.log, Game Log, replay), relevé analyzer
   `ability_call_counts`. `faction_decision_is_pending` voit un appel de phase de commandement
   (une seule source). Archives incompatibles : un seul `--new` après le chantier 8
   ([training.md#refonte-bloc-candidat](training.md#refonte-bloc-candidat)). Épisodes gym complets
   rejoués (`test_episode_combat_counters`, `test_objective_control_checkpoint_1402`).
3. ✅ **Indiscriminate Detonations = unité TOUCHÉE, choix du joueur** (2026-09-18). La fin
   d'activation supprimait la cible DÉSIGNÉE sans contrôle de touche (reproductions : désignée
   ratée → supprimée ; désignée ratée, seconde cible touchée → la désignée supprimée). Mesuré :
   l'état d'allocation connaît les touches (`counts["hits"]` par lot, `_roll_batch`) — relevé
   `alloc["hit_target_sids"]` → `unit["_shoot_hit_targets"]` (contexte tir), jamais le journal.
   Aucune touchée → rien ; une → elle ; plusieurs → décision `suppress_target` (fin d'activation
   différée, patron `move_after_shooting`), trois sièges : gym `CHOICE_k`, bots (PvE et adversaire
   du gym) par `select_bot_suppress_target` déclarée, humain par panneau + refus généralisé
   (`_ACTIVATION_DECISION_TYPES_BLOCKING_ACTIONS`). Journal `SUPPRESSES Unit M [SUPPRESSED→M]`
   (grammaire 12) ; analyzer `ai/analyzer_suppression.py` : `suppression_without_hit`
   (PROJ.1.2.suppression, bucket §1.2) juge suppression ⇔ touche ⇔ malus, au tir comme en mêlée,
   abstention sur journal antérieur. `target_health_and_value` partagé avec `mortal_wounds_target`.
   Tests rouge→vert : 6 moteur (test_primitive_f), 6 sièges/journal (test_suppress_target_decision),
   6 analyzer (test_analyzer_suppression), 2 vitest.
4. ✅ **Da Jump** (2026-09-18). Non livré jusqu'ici sur un bloqueur périmé (« slot de ciblage
   d'escouade amie », `AGENT_DECISION_TYPE_SLOTS = 8`) : la datasheet dit « place THIS unit » —
   l'escouade du WeirdBoy. Règle `da_jump` (obs_id 39, `UNIT_RULE_EFFECT_IDS`, `WeirdBoy.ts`),
   appel de capacité posé au début de la phase de mouvement à la première escouade candidate
   (chaîne sur refus, une proposition par escouade et par tour), `once_claim("da_jump", (tour,
   joueur))` sur le JET. 1 → D6 MW `is_psychic=True` (drapeau porté jusqu'au lot mortel manuel :
   Psychic Hood joue), `hazard_origin="da_jump"` ; 2-6 → `reposition_unit_to_strategic_reserves`,
   arrivée dès ce round, mise en place « anywhere » à plus de 8" (les commentaires « 9" » étaient
   l'ancien texte 24.09), Deep Strike ACCORDÉ par le registre `deep_strike_granted_squads` (purgé
   en fin de phase, jamais dans les UNIT_RULES), escouade remise au pool pour son ingress la même
   phase. Le service de la file `rule_choice` après une décision qui change de phase est ajouté
   (`_serve_queued_prompts_after_decision`) — sans lui l'appel attendait l'action suivante et
   pouvait être servi dans la phase de tir. Journal `DA JUMP (D6=n) [REPOSITIONED|MISCAST]`
   (grammaire 13 ; « MISCAST », `[FAILED]` étant le statut de ligne) + `SUFFERS n MW [DA JUMP]
   Trigger:1 MW:n` ; analyzer `ai/analyzer_da_jump.py` (`da_jump_invalid`, PROJ.1.1.da_jump,
   bucket §1.1 : once per turn, phase, issue ⇔ D6, hors table jusqu'à l'ingress, ingress > 8" en
   métrique hex, MISCAST ⇒ SUFFERS, exemption `reserves_too_early` au round 1) et dés par
   `MW_ABILITY_DICE_CHECKS["da_jump"]`. Moteur réel : 14 tests (`test_da_jump.py`, WeirdBoy
   inline 19.04) + 9 analyzer.
5. ✅ **Grot Orderly = choix d'agent, bodyguard models seulement** (2026-09-18). « You can return up to D3 destroyed bodyguard models » : la restitution était automatique et l'archive offrait les personnages attachés (un Warboss mort revenait). `_apply_return_destroyed_models` pose désormais `push_ability_call(escouade, "return_destroyed_models", "command")` AVANT le D3 à la première escouade éligible (`_grot_orderly_candidate`), 08.04 s'arrête dessus ; `apply_grot_orderly_call` : refus → `_GROT_ORDERLY_SKIPPED`, rien consommé, reproposé au tour suivant ; acceptation → D3 puis profil → placement inchangés ; le balayage reprend (second Painboy) puis Waaagh!/Oath. Trois sièges (gym `CHOICE_0/1`, bot `_bot_grot_orderly_policy` : ≥ 2 bodyguard morts ou round ≥ 4, humain `select_rule_choice`) ; la réponse à un appel de phase de commandement REPREND la phase (`_ability_call_closes_command_phase`) — le PvP n'avait aucun verbe pour en sortir ; le siège bot tolère une décision posée derrière l'appel (`_resolve_faction_decisions_for_ai_seats`). Clause bodyguard : `_returned_bodyguard_indices` (rôle ni leader ni support) filtre profils, complément du D3 et éligibilité. Client PvP de test (`tests/integration/pvp/_shared.py`) : répond aux `active_rule_choice_prompt` (passe par défaut, accepte les `accept_ability_calls`). Verrous : `test_grot_orderly_call.py` (8, trois sièges par le moteur), `test_returned_models_placement.py` (+5 : Warboss jamais rendu, refus, dépense, politique bot), `test_primitive_f_unit_state_effects.py`, `tests/integration/pvp/test_command.py::TestGrotOrderly` ; rouge/vert par mutation du filtre bodyguard (3 rouges) et de la reprise de phase (4 rouges). Doc : capacites.md §Grot Orderly ; corpus `unit.return_destroyed_models`.
6. ✅ **Finest Hour = choix à la sélection** (2026-09-18). « Once per battle … when this unit is selected to fight » : le roller décidait seul (première activation = usage consommé, +3 A sur le premier intent, DEVASTATING scoré sur « pas encore dépensée »). Appel de capacité `fight_arm_finest_hour_call` aux deux sites de sélection (gym/bot `squad_fight` après `_fight_v11_register_selection`, manuel `_fight_v11_manual_activate` sous `_fight_v11_activation_locked` étendu à `fight_finest_hour_asked`) ; combat suspendu (`FIGHT_SELECTION_FINEST_HOUR_KEY`) et repris par `_resume_fight_after_finest_hour` depuis les trois chemins de réponse ; `apply_finest_hour_call` pose `finest_hour_used` + `finest_hour_active_this_phase`, refus = rien ; résolution : +N A dans `melee_attacks_characteristic_bonus` (04.02, chaque arme du porteur), DEVASTATING sur `finest_hour_active_this_phase` seul (roller + sélecteur d'armes) ; Exhortation + Finest Hour même escouade → lève (19.01) ; bot `_bot_finest_hour_policy` (ennemie engagée ≥ 5 figurines ou CHARACTER) ; humain : garde `active_rule_choice_prompt`. Registre : `once_per_battle_melee_buff.name` = « Finest Hour ». **Grammaire 14** : `[FINEST HOUR]` exige `ABILITY CALL Finest Hour [USED]` (analyzer `_finest_hour_call_used`, plafond non levé sinon) ; correctif analyzer : l'acteur d'un `ABILITY CALL` est le préfixe de la ligne, plus le dernier `DEPLOYED`. Verrous : `test_finest_hour_call.py` (8), `test_primitive_b_granted_weapon_effects.py`, `test_squad_fight_declaration.py` (+2), `test_analyzer_finest_hour_call.py` (4) ; rouge/vert : reprise retirée (4 rouges), acteur (1 rouge).
7. ✅ **Analyzer : FNP / InSv** (2026-09-18). `ai/analyzer_save.py` : `save_threshold_mismatch` (PROJ.2.3.save_threshold — Sv/AP, InSv de datasheet, `invul_save_override` 19.04 des sources présentes au Select Targets step, `waaagh_invul` lu dans EFFECTS — clé ajoutée au producteur) et `fnp_threshold_mismatch` (PROJ.2.3.fnp — Dok's Toolz, Psychic Hood si [PSYCHIC]/Da Jump, Unbreakable Resolve sur l'Ancient alloué dans une aire ou à 6" du centre ; présence/absence/seuil/compte ; miroir SUFFERS). Corpus : 24.12 COUVERT, PROJ.1.9.* COUVERT via 24.12, unit.invul_save_override / unit.waaagh COUVERT, unit.toughness_bonus_while_waaagh COUVERT via PROJ.1.4.blessure. Détail : `analyzer.md#effets-defensifs`. Au passage, sur le journal réel : le contrôle Da Jump comptait en faute le `WAIT` hors table d'une escouade repositionnée (c'est le REFUS de l'ingress, « can ») et l'absence d'ingress avant la fin de la phase — corrigé (`ai/analyzer_da_jump.py`, +1 verrou) ; les compteurs `reserves_too_early`, `da_jump_invalid`, `suppression_without_hit` et `alloc_character_over_bodyguard` entraient dans les totaux sans ligne de rapport — lignes ajoutées (`_counter_row`).
8. ✅ **Analyzer : objectifs / REVIVED** (2026-09-18). `ai/analyzer_objectives.py` : `objective_control_mismatch` (OC resommé par zone depuis les socles, Relic Banner, battle-shock, contrôleur miroir du moteur), `objective_secured_invalid` (grammaire 15 : `Sec=` par zone + ligne `SECURES <zone> [<capacité>]`, dédup de l'instantané étendue à `secured_objectives`), `returned_models_invalid` (REVIVED : D3, mortes rendables, once per battle, phase, types, aucun leader/support). Corpus : les trois entrées unit.* → COUVERT. Correctifs au passage : découpage de `ZONES=` par `|` (noms avec espaces), parseur de replay compatible L18/15. Détail : `analyzer.md#objectifs-restitution`.

---

## Chaîne d'attaque 100 % {#chaine-attaque-100}

✅ **Livré 2026-09-18** (`worktree-chaine-attaque-100`). Ordre des lots choisi par l'attaquant lot
par lot (04.03 option B, dés jetés à l'ouverture du lot), popup de relance par lot, allocation
défenseur sans clic inutile (05.04), 8 écarts de règle corrigés (17.03, 24.07 par figurine, FNP
24.02, Deadly Demise 24.08/25 différée, cascade 06.02 + clé `precision_mortal_wounds_to_character`,
`wounded[0]`, mêlée 04.01/04.02/24.11), reprise après hazard humain réparée. **Change les parties
jouées → `--new`.** Détail, décisions et journal :
`Documentation/Archives/chantiers/chaine_attaque_100.md`.

**Reste ouvert (décision externe)** : `game_rules.precision_mortal_wounds_to_character` est à `false`
(lecture littérale 06.02) **en attente de confirmation GW** ; basculer la clé suffit, moteur,
analyzer et tests la lisent.

---

## P3-0 — Retrait pour cohérence 03.03 {#p3-0}

✅ **Livré 2026-08-23.** TOTAL_ACTION_SIZE 1359 → 1379 (+20 slots COHERENCY). Queue multi-escouade, sièges muets auto-résolus, tête pointeur `coherency_query_net` sur `self_models`. 32 tests verts. Run `--new` requis.

→ `Documentation/Chantiers/backlog/coherency_removal_choix_agent.md`

---

## Plunging Fire (22.05) + Deadly Demise (24.08) {#plunging-fire}

✅ **Livré 2026-08-25.** Mécanisme générique + câblage WeirdBoy (chantier 06). 17 tests rouge/vert. Lot passif ⚡ — aucun changement d'action space ni d'obs.

**Plunging Fire §22.05 :** `_manual_roll_intent` dans `shared_utils.py` — +1 BS (seuil amélioré de 1) si plancher ≥3" (chemin a) ou TOWERING ≤12" cible au sol (chemin b) ; `floor_height_by_model` lu dans `units_cache` ; court-circuit 2D (hauteur 0.0 jamais ≥ 3") ; step_logger token `[PLUNGING FIRE]` ; `_build_shot_details` dans `w40k_core.py` émet `hit_rule_modifier`.

**Deadly Demise §24.08 :** `destroy_model` + `drain_mortal_wound_queue` + `_roll_deadly_demise` dans `shared_utils.py` — mise en file à la mort (après disembark), D6 lancé au drainage, APRÈS les attaques de l'unité attaquante (25 DESTROYED, chantier « chaîne d'attaque 100 % » du 2026-09-18), sur 6 chaque unité à ≤6" **qui a encore une figurine** subit X MW via `allocate_mortal_wounds` — les 6" mesurés du BORD du socle détruit au bord du socle le plus proche de chaque unité (01.04) par `ranged_edge_distance` et la métrique `ranged` du run depuis le 2026-09-18, la forme/taille/orientation/empreinte du socle détruit voyageant en données plates dans la file ; valeur `deadly_demise` lue sur la FIGURINE détruite (`models_cache[mid]["UNIT_RULES"]`, ability CORE propre au porteur — un Boy mené par un WeirdBoy n'explose pas) avant son retrait de `models_cache`, aucune clé d'escouade (suite 120) ; analyzer + corpus §22.05 et §24.08 câblés. **Journalisée depuis le 2026-09-13 seulement** : le formateur `[DEADLY DEMISE]` existait mais le type manquait à `_STEP_LOG_TYPE_MAP` (0 ligne dans 29 Mo d'éval) ; la ligne `Unit <source> DEADLY DEMISE Roll:<d6> → Unit <victime>(c,r) SUFFERS N MW` est écrite AVANT les `DEAD … reason=hazard` qu'elle cause, porte le player de la SOURCE (exercice 24.08) et ne consomme pas de step ; c'est elle qui permet à l'analyzer de ne plus compter « Dead unit fighting/shooting » une unité tuée par l'explosion de la cible qu'elle vient de détruire (cf. ROADMAP_INDEX, suite 116).

---

## Stratagèmes réactifs — Fire Overwatch (15.08) et Heroic Intervention (15.11) {#reactive-stratagems}

**Obs réservée avant R1 (2026-08-24), implémentation à J4.**

Deux stratagèmes core (1 CP chacun) déclenchés pendant le tour adverse :
- **Fire Overwatch §15.08** : fin de phase de mouvement adverse — unité amie tire en snap shooting (touche sur 6 seulement, une cible visible à ≤ 24").
- **Heroic Intervention §15.11** : fin de phase de charge adverse — unité amie résout une charge. Mode *Leap to Defend* (gratuit, cibles = unités qui ont chargé) ou *Into the Fray* (+1 CP, toutes cibles à ≤ 6").

Interruptions réactives pendant le tour adverse — cas le plus complexe du gym (le joueur passif décide). Implémentées via le mécanisme `agent_decision` existant.

**Slots obs réservés maintenant (avant R1) :**
1. `"fire_overwatch"` + `"heroic_intervention"` dans `AGENT_DECISION_TYPE_IDS` — **gratuit** (AGENT_DECISION_TYPE_SLOTS = 8, 5 → 7 utilisés).
2. `"charged"` dans `UNIT_BIN_FIELDS` — **+1 scalaire/entité**, nécessaire pour le mode *Leap to Defend* (distinguer les ennemis qui ont chargé). À faire en même temps que R1 pour éviter un 2e `--new` post-J3.

→ `Documentation/Chantiers/backlog/reactive_stratagems_overwatch_hi.md`

---

## T7 — Unification validation de déploiement {#t7}

**Suspendu.** Déclencheur : « le training tourne ».

🔴 Le fix décrit est FAUX en l'état (mesuré 2026-07-20) — c'est une décision de design (plan contraint par l'ancre), pas un bug. Re-analyser avant de toucher.

→ `Documentation/Chantiers/v11/tranches_et_ruptures.md` §5 T7

---

## ✅ 20.01 — la déclaration de réserves passe avant le déploiement {#declaration-reserves-2001}

**Livré le 2026-09-10.** La mise en réserves était portée par `SQUAD_ACTION_WAIT`, ouvert PENDANT
le tour de déploiement de chaque unité. Mesuré avant, sur `scenario_training_armageddon1.json` en
déploiement actif :

```
step 1: deployer=2 mes_posees=0 ennemies_posees=1 WAIT_ouvert=True
step 7: deployer=2 mes_posees=3 ennemies_posees=4 WAIT_ouvert=True
```

Le joueur 2 déclarait donc ses réserves en voyant **quatre unités adverses déjà posées**. 20.01 le
lui refuse : « Before the battle, in the Declare Battle Formations step […] Instead of setting up
these units on the battlefield during deployment » — une étape ANTÉRIEURE au déploiement
(`25 Rules appendix.pdf` : Declare Battle Formations, puis Pre-battle Abilities, puis Begin the
Battle). La politique apprenait une décision qui n'est pas jouable dans une partie légale, et
l'écart n'était visible dans aucune métrique.

Ce qui change : au `reset`, le moteur fige une file alternée de questions (une par unité à poser,
joueur 1 d'abord) et n'ouvre aucun slot de pose tant qu'elle n'est pas épuisée —
`deployment_commit_plan` refuse par `reserves_declaration_still_open`, refus MOTEUR et non simple
absence de bouton côté client. Chaque question est un point d'arrêt du mécanisme générique
« décision agent » (type `reserves_declaration`, `CHOICE_0` = réserves, `CHOICE_1` = déploiement).
Une unité que la règle refuse (FORTIFICATION, plafond de 50 % atteint) n'est pas interrogée : un
candidat unique n'est pas une décision.

**Aucun `--new` imposé par la taille** : le type entre dans les colonnes pré-dimensionnées
d'`AGENT_DECISION_TYPE_SLOTS`, donc `obs_size` et `TOTAL_ACTION_SIZE` ne bougent pas. Mais la
politique de déploiement change et chaque épisode gagne une décision par unité déclarable : **les
win-rates mesurés avant ce lot ne sont plus comparables**.

Bots d'évaluation et déploiement `auto` DÉCLINENT toujours, par la même fonction
(`reserves_declaration_decline_slot`) : 20.01 est une décision de LISTE, jamais de doctrine — deux
implémentations feraient réserver l'adversaire de référence dans un seul des deux régimes et
déplaceraient la baseline sans que rien ne le signale.

Siège humain : la question fermée remplace le panneau à sélection libre ; l'API publie
`strategic_reserves.pending_declaration` et le client n'a plus aucune liste de candidats à
filtrer.

Verrous : `tests/unit/engine/test_reserves_declaration_step_2001.py` (20 tests, défaut réintroduit
puis constaté rouge sur les 4 invariants centraux), `tests/integration/pvp/test_deploy.py`
(`TestDeclareBattleFormations`, 6 tests). Les deux findings de `/code-review` — clôture de phase
côté siège humain quand tout part en réserves, et file non reconstruite par `change_roster` — sont
corrigés et couverts.

⚠️ **La file alternée décrite ci-dessus n'existe plus depuis le 2026-09-12** — voir la section
suivante. Le MOMENT de la déclaration (avant toute pose) et le refus moteur de `deploy_commit` sont
inchangés ; c'est la GRANULARITÉ qui a changé.

---

## ✅ 20.01 — la déclaration se compose PAR CAMP, sans ordre ni question fermée {#declaration-reserves-2001-par-camp}

**Livré le 2026-09-12.** Point de départ : en PvP, après « Start Deployment », aucune unité du
joueur 1 n'était sélectionnable — curseur interdit sur toute la liste. Ce n'était pas un bug mais
la face visible du lot précédent : l'étape interrogeait les escouades une à une, dans une file
alternée figée au reset, et toute la liste restait inerte sauf la ligne interrogée.

**Décision utilisateur (2026-09-10)**, après arbitrage à trois options : déclaration par joueur à
écran ouvert, un seul mécanisme pour tous les modes. Alternance avec pass irréversible écartée (ne
restaure pas le secret, invente une punition absente de 20.01) ; masquage avec passation d'écran
écarté (contrat social jugé irréaliste). Aux joueurs de s'organiser pour le secret. Mémoire
agent : `project_reserves_20_01_hotseat` (hors dépôt).

**Ce que dit la règle, relu avant d'écrire** (`20 Strategic reserves.pdf` §20.01) : « you can select
one or more friendly units (excluding FORTIFICATIONS) to place in strategic reserves. Instead of
setting up these units on the battlefield during deployment » — un ENSEMBLE déclaré par un camp
pour toute son armée, sans ordre, et sans question binaire : ne pas réserver, c'est déployer. La file
par escouade et le bouton `Deploy` n'avaient aucune base dans le texte.

**Ce qui change dans le moteur** (`engine/phase_handlers/deployment_handlers.py`) :
`RESERVES_DECLARATION_QUEUE_KEY` et sa file disparaissent ; l'étape porte `reserves_declaration_declined`
et `reserves_declaration_validated`, PAR JOUEUR. Qui déclare se DÉRIVE de l'état
(`current_reserves_declarer` : joueur 1 puis 2, tant qu'il lui reste une escouade déclarable et
qu'il n'a pas validé). Le siège humain compose librement — `deploy_strategic_reserves` (réserver
n'importe laquelle), `cancel_strategic_reserves` (défaire avant validation),
`validate_reserves_declaration` (figer, zéro réserve étant légal) — par le dispatcher commun, donc
avec snapshot de rewind. Le siège piloté par le modèle reste interrogé escouade par escouade
(`CHOICE_0`/`CHOICE_1`), et se fige de lui-même quand il n'a plus de question : **espace d'action
et registres d'observation inchangés, contrat d'entraînement à zéro écart mesuré avant et après —
aucun `--new`, `--append` tient.** `finalize_reserves_declaration` est l'écrivain unique du figeage
pour les deux sièges, `settle_reserves_declaration_step` la suite commune des trois gestes humains
(clôture, siège, sortie de phase).

**Le camp humain ne se ferme QUE par Validate** — y compris après avoir réservé sa dernière
escouade déclarable ou sur un roster pré-déclarant ses réserves jusqu'au plafond : il garde la main
et peut encore annuler. Le camp machine, lui, se ferme à sa dernière question (il n'a aucune action
d'annulation ; le garder ouvert armerait un masque sans question posable et
`next_reserves_declaration_question` lèverait — reproduit). La distinction passe par
`is_programmatic_owner` (`shared_utils.py`), SOURCE UNIQUE du prédicat « piloté par la machine »,
vrai pour tout camp en `gym_training_mode` — où `player_types` marque pourtant les deux camps
« human » — sinon `player_types == "ai"`. Une première écriture avait fermé tout camp sans question
posable, siège ignoré, et documenté ce coût comme « conséquence assumée » : c'était un défaut, pas
une contrainte — le discriminateur existait.

**Quatre défauts de l'écriture initiale, trouvés par relecture, revue et session parallèle avant
livraison, chacun rouge→vert** : (1) le crash du camp machine saturé ; (2) la sortie de phase
déplacée dans la seule route de validation — deux camps d'une escouade chacun, tous deux en
réserves : pools vides, étape jamais close, partie figée ; (3) `/code-review` : le point commun
clôturait sans déplacer le siège — en PvE `not_ai_player_turn` pour le bot,
`reserves_declaration_still_open` pour l'humain, partie figée ; (4) la fermeture d'office du camp
humain, ci-dessus. Les deux tests de sortie de phase avaient été SUPPRIMÉS à la réécriture du
fichier pendant que le code qu'ils gardaient déménageait : réintroduits. Verrous à double sens :
fermer d'office → 4 tests humains rouges ; ignorer le siège → 4 tests machine (gym et `ai`) rouges.

**API** (`services/api_server.py`) : `pending_declaration` remplacé par `declaring_player`,
`declarable`, `cancellable` — listes publiées par le moteur, jamais recalculées par le client, parce
que le plafond de 50 % bouge à chaque geste. `deploy_strategic_reserves` avec l'ancien paramètre
`declare` LÈVE (un appelant resté sur `declare: false` obtiendrait l'inverse de sa demande en silence).
**Save** : TL08 → TL09, les deux clés testées en aller-retour JSON (clés entières → chaînes).

**Front** : bandeau non bloquant « STRATEGIC RESERVES DECLARATION — <joueur> » avec `Validate`
(`ReservesDeclarationBanner`) ; un clic sur une ligne pendant l'étape SÉLECTIONNE sans lancer de plan
de pose (`handleSelectUnit`) ; la ligne sélectionnée porte `Reserve` si le moteur la liste
déclarable, jamais `Deploy` ; le conteneur porte `Cancel` sur les escouades listées annulables. Garde
`!isPopupVisible` du tour IA conservé tel quel.

Verrous : `tests/unit/engine/test_reserves_declaration_step_2001.py` (réécrit, 31 tests ×2 terrains,
4 mutations rouge→vert dont le crash, le blocage et le siège), `test_strategic_reserves_20.py`,
`tests/unit/services/test_api_server_helpers.py`, `test_save_format_key_contract.py` (TL09 enregistré
avec son empreinte), `tests/integration/pvp/test_deploy.py` (`TestDeclareBattleFormations` réécrit,
29 verts), vitest `strategicReservesUi.test.ts` (25) et `BoardWithAPI.test.tsx` (14). `tsc` complet
et suites larges : vérification utilisateur.

---

## Phase B — Observation des niveaux {#phase-b}

**Partiellement levé le 2026-09-09** par le lot ci-dessus : l'observation porte désormais la
hauteur des unités (`max_floor_height`, `has_ground_model`), le bit `elevated` par figurine et le
canal de grille `occupant_level`. Ce qui restait de la Phase B — la LoS 3D côté `combat_utils`/WASM
— est inchangé.

**Suspendu pour le reste.** Après Phase A' validée ET vérification du chantier LoS 3D
(`combat_utils`/WASM, câblage incomplet).

→ `Documentation/Chantiers/v11/tranches_et_ruptures.md`

---

## LoS 3D : tir à travers un mur depuis un étage {#los-mur-etage}

**Cadré le 2026-08-25 — même root cause que la Phase B, pas un chantier indépendant.**

Le tir est légitime côté backend : le tireur élevé ignore correctement les murs de sa propre ruine (`_walls_around_occupied_floor`). Mais le cône WASM ne le sait pas — il trace la LoS comme si le tireur était au sol, bloque sur le mur de la ruine, alors que la cible clignote (backend valide). Le joueur voit le cône bloqué, clique quand même, ça tire. Bug d'affichage, pas de règle.

**Côté cible (2026-09-18, fait au backend)** : la LoS étage↔sol était à sens unique — les murs de la ruine n'étaient retirés que pour la figurine tireuse, une cible à l'étage restait masquée pour un tireur au sol. Corrigé : wall_set de paire = murs − étage du tireur − étage de la cible (`_resolve_target_models_for_los`, jumeaux GtG et `_attacker_model_can_reach_squad`). Le cône WASM ne connaît toujours ni l'étage du tireur ni celui des cibles ; le backend peint les cases visibles des cibles valides (`build_visible_cells_by_target`), source autoritative, par-dessus le cône.

→ Traiter en même temps que la Phase B (`combat_utils`/WASM).

---

## Preview de tir sans deepcopy {#preview-tir}

**Lourd, re-cadrer avant reprise.** 4-8 j. Meilleure spec du lot, mais touche `compute_unit_los` = source unique (obs RL, reward, déploiement).

→ `Documentation/Chantiers/backlog/preview_tir_position_virtuelle.md`

---

## Endless Duty {#endless-duty}

**Plus aucune décision produit en attente** (constat vérifié 2026-08-28, signet
`tests/unit/services/test_endless_duty_is_broken.py` relancé vert) : les obstacles 1, 3, 5, 6 et 7
sont soldés en code — les décisions 3 (objectif fixe unique via terrain dédié) et 7 (séparation
`VALUE`/`REQUISITION_COST`) sont prises. Restent l'obstacle 2 (choix de murs, level design, ~½ j),
l'obstacle 4 (architecture d'init, ~1 j) et des résidus (FACTION_KEYWORDS vides, consommables,
scoring, UI, cohérence investi front/back — `REQUISITION_COST` écrit mais jamais lu).

→ `Documentation/Chantiers/backlog/endless_duty.md` (spec + état mesuré + obstacles, consolidés 2026-08-28)

---

## fix-reactive-move-coherency — ✅ livré 2026-08-21 {#reactive-move-coherency}

Move réactif : une escouade hors cohérence ne pouvait pas faire ce mouvement (03.01) mais le moteur ne le bloquait pas. Fix : check `_positions_in_coherency` avant le pool D6 dans `maybe_resolve_reactive_move`, log `reactive_move_declined reason=formation_incoherente`. Aligné sur le move normal (`build_squad_move_cell_map`). Test rouge→vert par mutation.

---

## 14.02 — le contrôle d'objectif se somme par figurine — ✅ livré 2026-09-10 {#oc-par-figurine}

**Change les parties jouées : `--new` obligatoire pour tout modèle entraîné avant ce correctif.**

`objective_control_contributions` (`engine/game_state.py`) multipliait un OC d'ESCOUADE par un
nombre de figurines. §14.02 dit « add together the OC characteristics of all the models in that
player's army that are within range of that objective », et §02.02 fait de l'OC une caractéristique
de FIGURINE : le produit n'est juste que sur une escouade homogène, et dès qu'un personnage est
attaché (19.01) il est faux dans les deux sens — 5 Boyz OC 2 + BannerNob OC 6 rendait 12 pour 16
attendus, 5 Intercessor OC 2 + Ancient OC 1 sous `oc_bonus` rendait 18 pour 17.

`unit_effective_oc` devient `unit_oc_bonus` : seul le bonus d'unité reste porté par l'unité, et il
s'ajoute à CHAQUE figurine. `iter_living_models_with_footprints` rend l'identifiant avec l'empreinte
pour que le contrôle puisse lire l'OC de la figurine ; `iter_living_model_footprints` en devient
l'adaptateur pour les lecteurs qui ne jugent qu'une présence. La règle 01.07 reste au niveau de
l'unité, conformément à son encadré (« the OC characteristic of all of its models is '-' »).

Sur les deux rosters de la démo, les quatre escouades de bloc sont hétérogènes en OC : 24 → 22,
24 → 27, 12 → 11, 21 → 19. Le contrôle d'objectif, les points de mission primaires et le reward
d'objectif changent donc dans toutes les parties.

Le jumeau `_enemy_threat_order` (`engine/phase_handlers/shared_utils.py`) sommait déjà par figurine :
c'est le contrôle qui divergeait. Il reste volontairement différent — un tri de menace lit la
datasheet, pas l'état de partie, donc il ignore `oc_bonus` et le battle-shock. **Cette divergence
n'est verrouillée par aucun test** (cf. la SUITE 🕳 du 2026-09-10).

---

## fix-reactive-move-engagement — ✅ livré 2026-09-09 {#reactive-move-engagement}

Move réactif : la datasheet conditionne la capacité à « if this unit is not within Engagement Range of one or more enemy units », condition qu'aucun des six filtres d'éligibilité ne portait. Le pool BFS n'écarte que les cases d'ARRIVÉE adjacentes à un ennemi, jamais la position de DÉPART : un porteur au contact réagissait et quittait le corps à corps par un mouvement gratuit, sans les contraintes du Fall Back. Mesuré avant correctif — réactif engagé en (10,10) à distance 1, déplacé en (12,9) à distance 2, `applied=1`. Fix : `unit_within_engagement_zone_footprints` (primitive canonique EZ, celle des jumeaux fight/charge) après le filtre de rayon dans `maybe_resolve_reactive_move`. Rouge→vert par retrait de la porte, plus un contrôle jumeau hors zone qui distingue la porte de la scène. Livré avec le retrait de `reactive_move` au `FenrisianWolf`, qui ne porte pas cette règle — le Termagant en est le seul porteur. Le volet REFUS a été livré depuis (`reactive_decision_mode` = `"state"`, décision `reactive_move` posée au siège qui réagit) ; la fenêtre s'ouvre sur les quatre chemins de commit depuis le 2026-09-17 (cf. [checklist-move-ecarts](#checklist-move-ecarts)).

---

## 13.06 — traversée du terrain DENSE par l'infanterie {#dense-traversal-1306}

**Ouvert le 2026-09-17** (mesuré par la checklist mouvement PvP, `tests/integration/pvp/checklist/test_move.py::TestNormalMove0905::test_infanterie_traverse_un_mur_de_terrain_dense`, `xfail(strict=True)` x5 et x1). 13.06 « INFANTRY/BEASTS/SWARM/MOBILE models can move horizontally through dense terrain features » ; le moteur fait de tout mur un obstacle absolu hors vol déclaré (`build_move_traversal_blocked`, « ils bloquent TOUJOURS », tour_de_jeu.md « Murs : ni traversée ni arrêt dessus »). Change les parties jouées → ⛔ tant que le moteur est figé pour la démo.

---

## checklist-move-ecarts — ✅ livré 2026-09-17 {#checklist-move-ecarts}

Les sept écarts mesurés par la checklist mouvement PvP (x5 et x1) sont corrigés et ses `xfail` retirés — détail dans `ROADMAP_INDEX.md`, suite 134 : fenêtre réactive sur le commit par-figurine et le squad move gym/PvE ; instantané d'adjacence de la réaction sur les empreintes (KeyError x5) ; 13.06 (mot-clé + coût vertical) dans le pool par-figurine en métrique hex ; `move_after_shooting` proposé au siège PvP à D6" × `inches_to_subhex` ; cohérence euclidienne à l'échelle 1,5 du move ; verbes legacy refusés en phase de tir au lieu d'un 500 ; `terrain_ref` en sous-dossier accepté par `/api/config/board`. Sans effet sur les parties x1 de la lignée. **Reste à décider** : fin d'activation du `squad_shoot` gym/PvE (l'agent et le bot ne reçoivent pas la décision `move_after_shooting` ; changerait les parties de la lignée). Le front qui perdait `selectedUnitId` après `move_after_shooting_select_destination` est corrigé le même jour (suite 136).

Suite 138 (2026-09-17) : deux verrous ajoutés à la checklist sans écart moteur — traversée de la bande d'engagement sans y finir (`TestNormalMove0905::test_traverse_la_zone_d_engagement_sans_y_finir`, la doc disait « non traversable » contre config/code/PDF 03.01) et Advance déclaré puis stationnaire qui reste un Advance (`TestAdvance0906::test_advance_puis_stationnaire_reste_un_advance`). Restent non couverts par la checklist : le coût de descente 13.06 sur le pool par-figurine PvP et le jumeau FLY 21.03 depuis un étage (aucune unité FLY à portée de la ruine dans le scénario figé).

Suite 139 (2026-09-18) : sans déclaration de montée, une figurine en hauteur garde son étage même sous un plancher plus haut (`FloorLevelMaps.by_level` rendu par `def floor_level_maps`, `engine/terrain_utils.py`, lu par `def model_rigid_level_map`) — la carte « niveau le plus haut » l'envoyait au sol ; détail dans `ROADMAP_INDEX.md`, suite 139. Seul `terrain-floors-test.json` superpose deux étages aujourd'hui.

Suite 140 (2026-09-18) : plan rigide à NIVEAU PAR FIGURINE (`def model_rigid_level_map`, option B tranchée par l'utilisateur) — une figurine en hauteur garde son étage là où la case le porte, descend ailleurs ; l'érosion refuse toute candidate où deux figurines atterrissent sur la même (niveau, case). Ferme le crash « collision intra-plan … (dont 1#r0) » du gate de P1 (socle rendu REVIVED sous une survivante à l'étage, pile-in inter-étage). Détail `ROADMAP_INDEX.md` suite 140.

Suite 141 (2026-09-18) : fin de tir d'escouade par la fin d'activation de DATASHEET pour les trois sièges — décision `move_after_shooting` (Purgation Run) offerte au gym et au bot PvE (réponse en requête par la politique), suppression de la cible (Indiscriminate Detonations) atteinte ; aucune colonne d'obs ni slot. Écart connu non traité : cible supprimée = première déclarée, sans contrôle « hit by one or more of those attacks » (`shooting_handlers.py` ~5350). Détail suite 141.

Suite 142 (2026-09-18) : descente 13.06 facturée au sol en métrique HEX sur le chemin par-figurine PvP (branche `_floor_start` hex : BFS amputé de la hauteur du plancher, étage vu par `ascent_field_for_model`, cases d'étage = celles que le commit résout) ; verrou FLY 21.03 (M − 2, sans descente). Détail suite 142.

Suite 172 (2026-09-19) : le rayon de socle des prunes d'engagement (charge et move) se lit dans `def socle_reach_radius_subhex` (`engine/hex_utils.py`) et non plus comme un demi-diametre recopie sur deux sites — exact pour `round` et `oval`, faux pour un `square` dont l'extreme est un coin. Mesure : l'ancienne formule tenait jusqu'a un cote de 26 subhex et cedait a 28, quand le plus grand socle du depot en vaut 24 ; aucune valeur ne change sur le roster. Deux findings de review traites au passage : le prefiltre du BFS inverse d'eligibilite ignorait l'ETALEMENT d'une escouade ennemie (zero destination rendue a x1 la ou le BFS complet en trouve 11 a 19), et la prune de l'observation plafonnait le socle ennemi, donc RETRECISSAIT son horizon. Detail `ROADMAP_INDEX.md` suite 172.

Suite 171 (2026-09-19) : les deux bornes hexagonales du pool de destinations de charge (`def _charge_impossible_by_primary_to_enemy_hex_lower_bound` et le prefiltre par-ennemi du BFS sol, `engine/phase_handlers/charge_handlers.py`) majoraient un predicat d'engagement EUCLIDIEN avec des rayons d'empreinte DISCRETS et refusaient des charges legales — 126 configurations mesurees sur les socles reels a x5, verdict vide mis en cache donc action charge jamais proposee. Les deux delegent desormais a `_charge_engage_reach` / au seuil de `_charge_enemy_prox` ; le garde-fou `round↔round` disparait avec la borne qui le motivait. Detail `ROADMAP_INDEX.md` suite 171.

Suite 168 (2026-09-19) : le disque de cellules candidates du plan de charge (`def _charge_engage_reach`, `engine/phase_handlers/shared_utils.py`) s'ecrit desormais dans la metrique d'engagement — en `euclidean` il additionnait des rayons d'empreinte DISCRETE quand le predicat soustrait les rayons CONTINUS, et perdait les destinations engageantes les plus eloignees de la cible (borne 15 pour des cellules a 16, socles round/6 a ez = 10). Aucune charge perdue n'a pu etre produite : la borne de declaration 11.04 laisse ~9 subhex de marge sur terrain degage. Detail `ROADMAP_INDEX.md` suite 168.

Suite 148 (2026-09-18) : attrition de fin d'épisode alimentée par les blessures mortelles hors chaîne d'attaque (`def mortal_wound_log_hp_lost`) ; départage des destinations de charge dans la métrique du verdict de coherency (`def coherency_euclidean_gap`) ; distance de charge journalisée non arrondie. Détail suite 148 (le split-fire 24.07 est la suite 146).

---

## Replis `unit_by_id` {#unit-by-id}

**T0 livré le 2026-08-19** — `require_unit_by_id(game_state, unit_id)` dans `engine/game_utils.py`, re-exportée depuis `combat_utils`. Signature canonique `(game_state, unit_id)` alignée sur le pattern moteur.

**T1 livré le 2026-08-25** — 9 sites Forme C convertis (commit dff4e8f0). `squad_fight_activation_order` supprimée (code mort, 0 appelant depuis fb7e83b6). 7 sites shooting_handlers + `_enqueue_rule_choice_candidates` w40k_core + résidu waaagh T2 → `require_unit_by_id`. Grep 0 résidu. 5 tests mutation-prouvés.

**T2 livré le 2026-08-25** — 46 sites Forme B convertis (charge_handlers 11, movement_handlers 11, fight_handlers 4, shared_utils 12, shooting_handlers 7+1 hors AST, reward_calculator 1). `unit_is_on_battlefield` supprimée (code mort, 0 appelant de production). api_server : 5 guards 404 ajoutés (frontières user-input). Grep résidu 0 (6 sites préservés : 2 tests, 3 frontières API, 1 contrat retour None). 13 tests mutation-prouvés (ROUGE→VERT).

**T3 livré le 2026-08-25** — 20 sites Forme D. **T4 livré le 2026-08-25** — 15 sites fight_handlers. **T4-bis livré le 2026-08-25** — 7 gardes résiduelles (shared_utils ×6, action_decoder ×1) + import manquant action_decoder. Re-grep global : 0 garde is-None résiduelle. Chantier clos.

→ `Documentation/Archives/chantiers/replis_unit_by_id_2026-08-05.md`
