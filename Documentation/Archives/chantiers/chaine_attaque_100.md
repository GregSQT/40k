# Chaîne d'attaque 100 % — tir et mêlée conformes aux PDF 04/05/06/10/12/17/19/22/24/25

Ouvert et livré le 2026-09-18 (branche `worktree-chaine-attaque-100`, mergée dans main). Source des règles : `Documentation/40k_rules/`
uniquement ; ce qui n'y est pas (plafond ±1 des modificateurs, « Target No Longer Eligible or Viable ») n'est pas
exigible et est consigné comme tel.

## 1. Origine

En PvP, après avoir déclaré deux armes sur deux cibles et cliqué **Shoot**, « rien ne se passe ». Mesuré sur la
partie en cours (état live du backend) : `squad_shoot_validate` avait été accepté, `pending_shoot_allocation`
attendait le défenseur sur le premier lot (Blitzcannon → Land Speeder, 5 blessures, une seule figurine cliquable).
Le seul rendu de cette attente était l'anneau jaune sur la cible du lot, pendant que le réticule rouge restait
sur la cible ACTIVE du menu d'armes (la dernière cliquée). Le moteur était juste ; l'attente était invisible, et
inutile : une seule figurine candidate, aucun choix.

## 2. Décisions utilisateur (2026-09-18)

| Sujet | Décision |
|---|---|
| Ordre de résolution 04.03 | **Option B** : après validation, l'attaquant choisit lot par lot l'unité puis le profil ; les dés d'un lot sont jetés au début de ce lot (plus de pré-jet de tous les lots). La question n'est posée que s'il y a un vrai choix (≥ 2 unités désignées restantes, ou ≥ 2 profils sur l'unité en cours). Contrainte 04.03 : toutes les armes d'une unité avant la suivante. |
| Défenseur 05.04 (a) | Allocation automatique quand un seul candidat ; question quand plusieurs figurines intactes OU plusieurs figurines entamées dans le groupe courant (règle : « must be a model that has lost one or more wounds if possible » — laquelle est un choix). |
| Relances | Popup **par lot** : « relancer les échecs » / « relancer tous les non-critiques ». Affiché seulement si une relance existe ET qu'une règle se déclenche sur critique : [DEVASTATING WOUNDS] pour la blessure ; [SUSTAINED HITS] / [LETHAL HITS] pour la touche (Oath of Moment). Sinon « échecs seulement », automatique. Le moteur applique le seuil de critique réel (6 ou [ANTI-X Y+]). |
| [PRECISION] + blessures mortelles | Lecture littérale : 06.02 impose la cascade non-CHARACTER d'abord, donc les blessures mortelles ([DEVASTATING WOUNDS]) d'une arme [PRECISION] vont aux bodyguards. Clé `game_rules.precision_mortal_wounds_to_character` (défaut `false`), en attente de confirmation GW ; l'analyzer et les tests lisent la même clé. |
| Décisions automatisées conservées | [LETHAL HITS] (auto-blessure tranchée par espérance, `lethal_hits_auto_wound_is_better`). |
| Gel du moteur | « Tu merges tout dans main, on refait un `--new` de toute façon » — merge autorisé pendant le run P1. |
| Affichage | Réticule rouge sur TOUTES les figurines de chaque unité désignée pendant la déclaration ; après Shoot, réticule clignotant sur la seule unité du lot en cours et panneau de lot automatique (arme, cible, jets, blessures restantes, candidates). |

## 3. Écarts de règle corrigés (chacun avec test rouge → vert)

1. **17.03** — une unité MONSTER/VEHICLE ennemie engagée peut être ciblée au tir ; −1 au jet de touche sauf [CLOSE-QUARTERS] depuis l'unité engagée avec elle ; [BLAST] interdit (FAQ p. 88).
2. **24.07** par FIGURINE (hors MONSTER/VEHICLE) : pistolets OU autres armes, chaque figurine décide pour elle ; imposé par le moteur sur le chemin manuel, plus seulement grisé au niveau unité dans le menu.
3. **24.02** abilités dupliquées : un seul Feel No Pain par figurine (le meilleur seuil), un seul jet.
4. **24.08 / 25 DESTROYED** — Deadly Demise résolue après que l'unité attaquante a résolu toutes ses attaques ; 6" mesuré à la figurine la plus proche de chaque unité ; défenseur humain : allocation manuelle 06.02.
5. **06.02** — toute blessure mortelle (Deadly Demise, hazard, Hold Still, [DEVASTATING WOUNDS]) suit la cascade 06.02, plus le groupe courant (sauf clé `precision_mortal_wounds_to_character = true`).
6. **05.04** — plusieurs figurines entamées dans le groupe courant : choix du défenseur, plus `wounded[0]`.
7. **04.03** — ordre des lots et jets lot par lot (option B).
8. **Mêlée** — 04.02 « Splitting melee attacks » (une arme répartit ses attaques entre plusieurs unités engagées) ; 24.11 « toutes les [EXTRA ATTACKS] + une arme ordinaire » imposé au joueur.

## 4. Approximations de modélisation (consignées, non corrigées)

- 06.01 : ligne de vue « 1 mm de n'importe quelle partie à n'importe quelle partie » → grille hex, centres de figurines.
- Plafond ±1 des modificateurs de dés : règle de l'app GW, absente des PDF → non exigible.

## 5. Périmètre

Moteur : `engine/phase_handlers/shared_utils.py`, `attack_sequence.py`, `shooting_handlers.py`, `fight_handlers.py`,
`engine/w40k_core.py`, `config/game_config.json`. Analyzer : `ai/analyzer_rules.py`,
`Documentation/Chantiers/analyzer_couverture.md`. Front : `useEngineAPI.ts`, `BoardPvp.tsx`, `BoardWithAPI.tsx`.
Tests : `tests/unit/engine/`, `tests/integration/pvp/test_shoot.py`, `test_fight.py`, vitest.
Doc : `Reference/jeu/couverture_regles.md` (lignes fausses corrigées), `Chantiers/v11/decisions_du_joueur.md`.

## 6. Journal

- 2026-09-18 : ouverture. Investigation prouvée sur l'état live du backend (attente défenseur invisible).
- 2026-09-18 : moteur — option B (`select_attack_lot`, `roll_prepared_intent`, `_lot_request_payload`),
  politique de relance par lot (`RerollProfile.hit_non_crit`/`wound_non_crit`), allocation à vrai choix,
  cascade 06.02 + clé `precision_mortal_wounds_to_character`, FNP unique, Deadly Demise différée
  (`MORTAL_WOUND_QUEUE_KEY`, `drain_mortal_wound_queue`), 17.03 (`[ENGAGED TARGET]`), 24.07 par figurine,
  mêlée 04.01/04.02/24.11 ; reprise après hazard humain réparée (bug préexistant : l'unité restait active).
  Tests rouge→vert : `test_reroll_policy_par_lot` (12), `test_lot_selection_04_03` (10),
  `test_allocation_choix_reel_05_04_06_02` (8), `test_deadly_demise_apres_les_attaques` (3),
  `test_engaged_monster_vehicle_17_03` (7) ; 16 fichiers de tests adaptés ; intégration pvp
  `test_shoot` 16 / `test_fight` 8.
- 2026-09-18 : analyzer — `attacks_not_made` (formateur + `_ATTACKS_NOT_MADE_RE`), Deadly Demise
  repositionnée (`dead_models_since_explosion`), contrôle `alloc_character_over_bodyguard`
  (05.03/06.02/24.28, corpus `PROJ.1.x.alloc_character`, clé `Run rules: alloc.precision_mw_to_character`
  émise par `w40k_core._run_rules_for_step_log`) ; `test_analyzer_alloc_character` (15).
- 2026-09-18 : front — `useEngineAPI` (`attackLotRequest`, `onSelectAttackLot`, `readAttackLotPrompt`),
  `AttackLotPanel` (choix de lot / popup relance / allocation), `BoardPvp` (réticule sur toutes les unités
  désignées via `drawReticle`, réticule clignotant du lot en cours via `attackLotReticleTargets`, clic sur
  une candidate), `BoardWithAPI` (câblage + filtre de cible), bulle `[ENGAGED TARGET]` (GameLog), replay
  `NON_ABILITY_ROLL_TOKENS` (+ [POINT-BLANK], [PLUNGING FIRE], même motif). Vitest : 19 neufs.
- 2026-09-18 : clôture — merge dans main pendant le run P1 (décision utilisateur : `--new` de toute façon).
  Reste ouvert : confirmation GW sur [PRECISION] + blessures mortelles (clé à basculer si besoin).
- 2026-09-18 : findings `/code-review` (6/6 confirmés, corrigés) — 04.02 : la somme répartie vaut la
  caractéristique A MODIFIÉE (`melee_attacks_characteristic_bonus`, Waaagh! + Da Biggest and da Best),
  intents `attacks_bonus_included` non re-bonifiés par le roller ; `select_attack_lot` refusé pendant
  l'attribution du défenseur ; lot jeté sans blessure = aucune déclaration d'ordre ; Deadly Demise mise
  en file seulement pour `combat`/`hazard` (03.03 : le retrait de cohérence ne déclenche rien ; réserves
  20.04 hors table) ; fall back gym/bot : file servie AVANT le mouvement, unité vivante comprise, avec
  reprise du mouvement du bot après attribution humaine (`PENDING_GYM_FALL_BACK_RESUME_KEY`) ; actions
  hazard ET `select_coherency_removal` routées dans la chaîne des handlers pour traverser la cascade
  (`_CASCADED_OUT_OF_PHASE_ACTIONS`, gym compris) — même motif, bug préexistant mesuré : le tour de
  l'adversaire était sauté après un retrait de cohérence du joueur courant. Tests rouge→vert :
  `test_lot_selection_04_03` (+3), `test_squad_fight_declaration` (+2), `test_deadly_demise_apres_les_attaques`
  (+1), `test_gym_fall_back_desperate_escape` (+2), `test_charge_impact_hazard_cascade` (1),
  `test_coherency_removal_progression_cascade` (3) ; `test_exhortation_pvp_humain` (2 tests périmés par
  l'allocation à candidate unique, remis d'aplomb).
