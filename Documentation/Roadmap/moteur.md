# Moteur — Tâches ouvertes

---

## P3-0 — Retrait pour cohérence 03.03 {#p3-0}

✅ **Livré 2026-08-23.** TOTAL_ACTION_SIZE 1359 → 1379 (+20 slots COHERENCY). Queue multi-escouade, sièges muets auto-résolus, tête pointeur `coherency_query_net` sur `self_models`. 32 tests verts. Run `--new` requis.

→ `Documentation/Chantiers/backlog/coherency_removal_choix_agent.md`

---

## Plunging Fire (22.05) + Deadly Demise (24.08) {#plunging-fire}

✅ **Livré 2026-08-25.** Mécanisme générique + câblage WeirdBoy (chantier 06). 17 tests rouge/vert. Lot passif ⚡ — aucun changement d'action space ni d'obs.

**Plunging Fire §22.05 :** `_manual_roll_intent` dans `shared_utils.py` — +1 BS (seuil amélioré de 1) si plancher ≥3" (chemin a) ou TOWERING ≤12" cible au sol (chemin b) ; `floor_height_by_model` lu dans `units_cache` ; court-circuit 2D (hauteur 0.0 jamais ≥ 3") ; step_logger token `[PLUNGING FIRE]` ; `_build_shot_details` dans `w40k_core.py` émet `hit_rule_modifier`.

**Deadly Demise §24.08 :** `_apply_deadly_demise` + `destroy_model` dans `shared_utils.py` — D6 lancé après disembark, sur 6 chaque unité à ≤6" subit X MW via `allocate_mortal_wounds` ; valeur `deadly_demise` lue dans `units_cache[squad_id]` avant suppression du modèle ; step_logger tag `[DEADLY DEMISE]` ; analyzer + corpus §22.05 et §24.08 câblés.

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

Move réactif : la datasheet conditionne la capacité à « if this unit is not within Engagement Range of one or more enemy units », condition qu'aucun des six filtres d'éligibilité ne portait. Le pool BFS n'écarte que les cases d'ARRIVÉE adjacentes à un ennemi, jamais la position de DÉPART : un porteur au contact réagissait et quittait le corps à corps par un mouvement gratuit, sans les contraintes du Fall Back. Mesuré avant correctif — réactif engagé en (10,10) à distance 1, déplacé en (12,9) à distance 2, `applied=1`. Fix : `unit_within_engagement_zone_footprints` (primitive canonique EZ, celle des jumeaux fight/charge) après le filtre de rayon dans `maybe_resolve_reactive_move`. Rouge→vert par retrait de la porte, plus un contrôle jumeau hors zone qui distingue la porte de la scène. Livré avec le retrait de `reactive_move` au `FenrisianWolf`, qui ne porte pas cette règle — le Termagant en est le seul porteur. **Le volet REFUS n'est pas livré** : `reactive_decision_mode` vaut toujours `"auto"` en dur, la branche `"state"` et `decline_reactive_move` restent sans producteur.

---

## Replis `unit_by_id` {#unit-by-id}

**T0 livré le 2026-08-19** — `require_unit_by_id(game_state, unit_id)` dans `engine/game_utils.py`, re-exportée depuis `combat_utils`. Signature canonique `(game_state, unit_id)` alignée sur le pattern moteur.

**T1 livré le 2026-08-25** — 9 sites Forme C convertis (commit dff4e8f0). `squad_fight_activation_order` supprimée (code mort, 0 appelant depuis fb7e83b6). 7 sites shooting_handlers + `_enqueue_rule_choice_candidates` w40k_core + résidu waaagh T2 → `require_unit_by_id`. Grep 0 résidu. 5 tests mutation-prouvés.

**T2 livré le 2026-08-25** — 46 sites Forme B convertis (charge_handlers 11, movement_handlers 11, fight_handlers 4, shared_utils 12, shooting_handlers 7+1 hors AST, reward_calculator 1). `unit_is_on_battlefield` supprimée (code mort, 0 appelant de production). api_server : 5 guards 404 ajoutés (frontières user-input). Grep résidu 0 (6 sites préservés : 2 tests, 3 frontières API, 1 contrat retour None). 13 tests mutation-prouvés (ROUGE→VERT).

**T3 livré le 2026-08-25** — 20 sites Forme D. **T4 livré le 2026-08-25** — 15 sites fight_handlers. **T4-bis livré le 2026-08-25** — 7 gardes résiduelles (shared_utils ×6, action_decoder ×1) + import manquant action_decoder. Re-grep global : 0 garde is-None résiduelle. Chantier clos.

→ `Documentation/Archives/chantiers/replis_unit_by_id_2026-08-05.md`
