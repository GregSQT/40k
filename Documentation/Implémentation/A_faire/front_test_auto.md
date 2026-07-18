# Tests automatiques du front PvP — plan de mise en place exhaustif

> **Périmètre** : vérifier automatiquement TOUT ce que le front PvP affiche et permet de faire
> (cercles verts, previews, flux d'actions par phase, HUD, rendu PIXI), sans avoir à tester à la main.
>
> **Principe fondateur (vérifié dans le code)** : le front ne décide RIEN. `useEngineAPI.ts` mappe des
> champs renvoyés par le backend (`move_activation_pool` → cercles verts, `valid_move_destinations_pool`
> + mask loops → preview move, `squad_shoot_los_overview` → cibles surlignées) et `BoardPvp`/`UnitRenderer`
> les dessinent. On teste donc en 3 couches, de la moins chère à la plus chère :
> - **Couche A — API (sans navigateur)** : la donnée que le front consomme est correcte.
> - **Couche B — vitest (jsdom)** : le mapping donnée → props/état front est correct.
> - **Couche C — Playwright (navigateur réel)** : ce qui est effectivement dessiné/cliquable est correct.
>
> Une fonctionnalité est « couverte » quand sa source de vérité (A), son mapping (B) et son rendu (C)
> sont testés. Beaucoup de bugs vus en test manuel sont des bugs de A ; la couche A est donc prioritaire.
>
> **Aucun fallback, aucune valeur par défaut masquant une erreur** — un champ absent = FAIL explicite.
> **Aucune règle 40k assertée sans référence** au PDF `Documentation/40k_rules/` (ex. 09.07 déjà utilisé).

> **Statut (2026-07-18)** : Couche A **T1 FAIT** (`scripts/pvp_smoke_test.py`, 27 checks verts :
> sanity state, move mono-figurine complet, transition move→shoot, pool shoot + exclusion fuyardes
> 09.07, cibles LoS overview). Le reste de ce document est À FAIRE.

---

## 0. Existant et infra acquise

### 0.1 Harnais couche A : `scripts/pvp_smoke_test.py`
- Client `ApiClient` (stdlib pure), auth Bearer (`--token` / `--login+--password` / `--token-from-db`
  qui lit la dernière session de `config/users.db` en LECTURE SEULE).
- `--spawn-server` : serveur Flask dédié port 5011, `use_reloader=False` (le reloader Werkzeug
  redémarrait le serveur en boucle sous WSL2 et effaçait la partie — fixé aussi dans
  `services/api_server.py` : `debug=False`, `127.0.0.1`).
- Résultats typés PASS/FAIL/SKIP, exit code exploitable en CI/script.
- Partie de référence : `mode_code=pvp_test` (board 44x60x5, 41 unités, phase initiale move, P1).

### 0.2 Contrats API appris (à réutiliser tels quels)
- Toutes les actions passent par `POST /api/game/action` ; état par `GET /api/game/state`.
- Transition de phase : JAMAIS automatique — le front envoie `advance_phase` quand le pool est vide ;
  réponse `{phase_complete: true, reason: "pool_empty", next_phase: ...}`.
- Phase shoot : le moteur REJETTE `activate_unit` — chemin escouade obligatoire
  (`squad_shoot_activate`, puis `squad_shoot_los_overview` pour les cibles).
- HP : `unit.HP_CUR` = total escouade HORS leader attaché ; HP par figurine dans `models_cache` ;
  `squad_models[uid]` = liste des ids de figurines (`"6#0"`, …).
- Leviers de test déterministes déjà exposés par l'API :
  - `charge_roll_override` (remplace le jet 2D6 de charge) ;
  - `shoot_pool_require_los` (mode pool de tir exact vs transition rapide).

### 0.3 Existant couche B
- Vitest 3 + @testing-library/react + jsdom + msw (installé, aucun handler monté).
- 10 tests unitaires utils seulement (`activationClickTarget`, `losPreviewHelpers`,
  `movePoolRefsSync`, `weaponHelpers`, …). Aucun test de `useEngineAPI` ni de composant.

### 0.4 Existant couche C
- Rien. Pas de Playwright/Cypress, pas de `data-testid`, pas de hook de test exposé.
- Points d'accroche déjà présents (bridges fonctionnels) : `window.boardUnitDoubleClickHandler`,
  `window.cancelChargeHandler`, `window.cancelAdvanceHandler`, CustomEvents `boardUnitDoubleClick`.

---

## Couche A — Tests API exhaustifs (extension de `pvp_smoke_test.py`)

Objectif : dérouler UNE partie scriptée qui traverse toutes les phases des deux joueurs sur
plusieurs tours, avec des checks par phase + des invariants transversaux revalidés après CHAQUE action.

### T2 — Invariants transversaux (à revalider après chaque action)
- Ids uniques ; HP figurines bornés ; positions dans le board ; cohérence `units` ↔ `units_cache`
  ↔ `models_cache` ↔ `squad_models`.
- Tout pool (`move/shoot/charge/command_activation_pool`, `fight_*`) ⊆ unités vivantes du bon joueur.
- Une unité ne peut jamais être dans 2 états contradictoires (`units_moved` ∩ pool = ∅, etc.).
- Toute action refusée doit laisser le state INCHANGÉ (comparaison avant/après sur les champs de jeu).
- `phase` ∈ {deployment, command, move, shoot, charge, fight} (les 6 handlers de
  `engine/phase_handlers/`) et séquence 07 (battle round) respectée, y compris l'alternance de
  joueur et l'incrément de tour. NB : `pvp_test` démarre en move ; le flux deployment/command
  se teste en mode `pvp` (T3a/T2b).

### T2b — Phase command + réactions
Champs relevés : `command_activation_pool`, `reaction_window_active`, `reactive_decision_mode`,
`reactive_decision_payload`, `units_reacted_this_enemy_turn` ; actions `force_battle_shock`,
`select_rule_choice`.
- [ ] Pool command : composition, activation, effets (battle-shock tests LD — PDF 08/01.07 à lire
      avant d'asserter), transition vers move.
- [ ] Fenêtres de réaction : quand `reaction_window_active` s'ouvre, seules les actions du payload
      réactif sont acceptées ; toute autre action → rejet explicite, state inchangé.
- [ ] `select_rule_choice` : un choix de règle en attente (`choice_timing_index`) BLOQUE les autres
      actions tant qu'il n'est pas résolu ; chaque option produit l'effet attendu.

### T3a — Déploiement (mode `pvp`)
Actions relevées : `deploy_unit`, `deploy_preview`, `deploy_generate_formation`,
`deploy_model_destinations`, `deploy_squad_destinations`, `deploy_commit`, `change_roster`.
Contrainte (mémoire projet) : le déploiement doit copier EXACTEMENT la phase de move — mêmes
fonctions de pool par figurine, jamais de logique durcie/divergente.
- [ ] Alternance de déploiement entre joueurs, unités restantes correctes.
- [ ] `deploy_model_destinations`/`deploy_squad_destinations` : destinations ⊆ zone de déploiement
      (`deployment_zone`), niveau par sœur honoré (superposition inter-étage).
- [ ] `deploy_generate_formation` → formation valide (cohérence, pas de chevauchement), commit →
      positions posées, mismatch masque/commit (bug historique T5 V11) surveillé.
- [ ] `change_roster` : nouveau roster chargé, state réinitialisé proprement.
- [ ] Fin de déploiement → première phase de bataille correcte.

### T3 — Move : escouades par figurine + advance + fall-back
Actions front relevées : `preview_move_plan`, `move_model_destinations` (BFS par figurine, avec
`provisional_plan`, `level`, `orientation`), `commit_move_plan`, `advance`, `wait`, `left_click`,
`right_click`.
- [ ] Activation d'une escouade multi-figurines → destinations PAR FIGURINE
      (`move_model_destinations`), plan provisoire, commit → positions par figurine mises à jour,
      cohérence d'escouade (06.02) respectée, sortie du pool.
- [ ] Distance : aucune destination au-delà de `MOVE` (en subhex via `inches_to_subhex` — jamais de
      seuil en pouces recodé en dur), coût de descente §13.06 inclus.
- [ ] Advance (09.06) : jet d'advance présent, portée = M + jet, unité marquée `units_advanced`,
      puis EXCLUE du pool de charge et du tir (armes non Assault — vérifier la règle exacte dans
      le PDF 10 avant d'asserter).
- [ ] Fall-back (09.07) : unité engagée → destinations qui désengagent uniquement ; marquée
      `units_fled` ; exclue de shoot ET charge ce tour.
- [ ] Pivot/orientation : `orientation` passée au BFS → empreinte honorée (EZ 2", collisions).
- [ ] Étages : `level` ≠ 0 → pool niveau-conscient (unité 1008 du scénario, level 1).
- [ ] Rejets : move hors pool de destinations → erreur explicite, state inchangé.

### T4 — Shoot : par arme et par figurine
Actions relevées : `squad_shoot_select_model`, `squad_shoot_assign_weapon_qty`,
`squad_shoot_weapon_qty_max`, `squad_shoot_unassign`, `squad_shoot_unassign_weapon`,
`squad_shoot_validate`, `squad_shoot_cancel`, `squad_shoot_allocate_model`, `move_after_shooting`.
- [ ] Sélection d'une figurine → armes disponibles correctes (RNG_WEAPONS), cibles par arme
      (portée + LoS 3D — chemin `_attacker_model_can_reach_squad`, cf. mémoire LoS).
- [ ] Assignation de quantités par arme/cible, unassign, validate → résolution : dégâts appliqués,
      HP figurines décrémentés, morts retirés de `units_cache`/`models_cache`, allocation des pertes
      (`squad_shoot_allocate_model`) conforme au moteur d'allocation mutualisé.
- [ ] Cover : `cover_by_unit_id` de `squad_shoot_los_overview` vs règle 13 (lire le PDF avant d'asserter).
- [ ] Unité engagée : seules les armes Pistol tirables (PDF 10 à lire avant d'asserter).
- [ ] `shoot_pool_require_los` true/false → même résultat final (deux modes, un seul verdict légal).
- [ ] Rejets : tirer 2× avec la même arme, cibler un allié, cibler hors LoS → erreurs explicites.
- [ ] `move_after_shooting` : disponible uniquement pour les unités/règles qui y donnent droit
      (lire la règle exacte avant d'asserter), distance bornée, state tracé.
- [ ] Unités cachées (`hidden`, `hideable`, `hidden_models`, gone to ground — PDF 13/13-5) :
      détection 12"/15" (`hidden_detection_info_by_unit_id`), une unité cachée non détectée
      n'apparaît JAMAIS dans les cibles ni dans les données envoyées au front adverse.

### T5 — Charge
Actions relevées : `charge`, `charge_plan_state`, `commit_charge_plan`, `charge_autoplace`,
`take_to_skies`, `charge_roll_override`, `force_charged`, annulation via `right_click`
(`window.cancelChargeHandler`).
- [ ] Pool charge : exclut `units_advanced`, `units_fled` (09.06/09.07), unités déjà engagées
      (PDF 11 à lire pour la liste exacte d'éligibilité 11.02).
- [ ] `charge_roll_override` : jet forcé N → cibles atteignables ssi distance ≤ N ; override à 2 →
      échec de charge tracé, unité sortie du pool sans bouger.
- [ ] Déclaration multi-cibles, mouvement de charge par figurine : chaque figurine finit en EZ
      (11.04), cohérence d'escouade maintenue.
- [ ] `units_charged` alimenté ; fight phase : les chargeurs frappent en premier (12.02 — lire PDF).
- [ ] Plan de charge par figurine : `charge_plan_state`/`commit_charge_plan` cohérents avec le
      flux manuel PvP ; `charge_autoplace` produit un placement légal identique aux règles du
      plan manuel (jamais plus permissif).
- [ ] `take_to_skies` (règle 21, flying/surging — lire le PDF avant d'asserter) :
      `units_took_to_skies`/`units_took_to_skies_charge` alimentés, restrictions induites.

### T6 — Fight
Actions relevées : `fight`, `skip_fight`, `squad_fight_assign`, `squad_fight_assign_weapon`,
`squad_fight_validate`, `squad_fight_manual_alloc`, `squad_hazard_allocate_model`,
`hazard_confirm`, pile-in : `pile_in_plan_state`, `pile_in_autoplace`, `commit_pile_in_plan`,
`end_pile_in` ; consolidation : `consolidation_plan_state`, `consolidation_select_target`,
`consolidation_select_objective`, `consolidate_autoplace`, `commit_consolidation_plan`,
`cancel_consolidation`, `end_consolidation`.
- [ ] Sous-phases (`fight_subphase`) : ordre charged-first puis alternance (12.01-12.03),
      `fight_eligible_units` conforme au pool 12.04 (cf. mémoire T6-d : une sélection = une action).
- [ ] Pile-in 3" par figurine (12.06, modèle par-figurine du PvP — le par-ancre est condamné),
      multi-niveaux, coût de descente §13.06.
- [ ] Attribution des attaques par arme/figurine (cible-d'abord, jumeau du tir), validate →
      dégâts, allocation manuelle des pertes (`squad_fight_manual_alloc`).
- [ ] Consolidation 3" (12.08) par figurine, modes mutuellement exclusifs (cible/objectif —
      `consolidation_select_target`/`_select_objective`), autoplace == mêmes règles que le plan
      manuel, annulation propre (`cancel_consolidation`).
- [ ] Mort d'une unité en mêlée : retrait complet, l'adversaire re-devient éligible ou pas selon 12.
- [ ] Fin de phase → nouveau battle round : joueur, tour, VP objectifs (`objective_controllers`,
      OC par unité, PDF 14).

### T7 — Fin de partie et systèmes annexes (API)
- [ ] Victoire : `game_over`, `winner`, VP corrects sur une partie scriptée jusqu'au bout.
- [ ] Battle-shock : `force_battle_shock` + tests LD/OC (PDF 01.07/08).
- [ ] Snapshots/rewind : `GET /api/game/snapshots`, `timeline`, `snapshot/restore` → l'état restauré
      est STRICTEMENT égal au state d'origine (diff JSON champ à champ).
- [ ] Save/load : `game/save` + `save/load` → même égalité stricte.
- [ ] Auth : accès sans token → 401 ; mode non autorisé → 403.

### T7b — Fuzzing par invariants (la vraie garantie d'exhaustivité)
Les tranches T2-T7 testent des scénarios CONNUS ; le fuzzing couvre les enchaînements imprévus.
- [ ] Agent aléatoire : à chaque étape, tirer une action LÉGALE au hasard (pools + vocabulaire de
      la phase), l'exécuter, revalider TOUS les invariants T2 après chaque action. Seed fixée et
      rejouable (`--seed N`), log des actions → tout crash/violation est reproductible.
- [ ] Fuzzing négatif : injecter des actions ILLÉGALES aléatoires (mauvais joueur, mauvaise phase,
      ids inexistants, coordonnées absurdes) → 100 % rejetées, state inchangé, jamais de 500.
- [ ] Budget : N parties complètes par run (ex. 20), sur plusieurs boards (`--board x1/x5`).
- [ ] Chaque violation trouvée devient un check nommé permanent dans la tranche concernée.

### Hors périmètre de ce document (à décider séparément)
- **Tutoriel** (BoardPvpWithTutorialAdvance, `/api/config/tutorial/steps`, scénarios étape N) :
  flux scripté à part, testable avec la même infra couche C — tranche dédiée si souhaité.
- **PvE / `ai-turn`** : le tour IA dépend d'un modèle entraîné (non déterministe entre versions de
  modèles) — tester uniquement le contrat (l'IA joue des actions légales, la main revient au joueur).
- **Endless Duty** (`endless_duty_status`/`commit`) : mode à part, mêmes couches applicables.
- **Replay viewer** (`/api/replay/*`, `replayParser` déjà testé en vitest) : tranche C dédiée si
  le viewer devient critique.

---

## Couche B — vitest : le mapping donnée → affichage

Cible : la logique front PURE, exécutée en jsdom sans navigateur ni backend (msw pour mocker l'API).

- [ ] **T8 — `useEngineAPI` (hook loué avec renderHook + msw)** :
  - `eligibleUnitIds` = exactement le pool de la phase courante (move/shoot/charge/fight) — c'est
    LA garantie « seules les unités activables ont le cercle vert » côté front.
  - `movePreview`/`targetPreview`/`attackPreview` alimentés/vidés aux bons moments ;
    normalisation `normalizeMaskLoopsFromApi` (hash/`_unchanged` : le cache ne sert jamais un
    masque périmé).
  - Gestion d'erreur : réponse `success:false` → `setError`, pas de mutation d'état de jeu.
- [ ] **T9 — utils critiques non couverts** : `probabilityCalculator` (probas de dégâts du tooltip
      vs calcul exact), `boardClickHandler` (routage clic → action selon phase/mode),
      `movePreviewFootprintMaskLoops` (déjà partiel), helpers charge/fight.
- [ ] **T10 — composants DOM non-PIXI** : HUD (phase, tour, joueur, VP), menus d'armes du tir
      (quantités, max, unassign), bandeau fight, modales hazard — via @testing-library/react,
      assertions sur le DOM réel.

---

## Couche C — Playwright : le rendu et l'interaction réels

PIXI dessine dans un canvas : le DOM ne contient PAS les cercles verts ni les previews. Deux
prérequis à implémenter dans le front (gardés par un flag, ex. `VITE_TEST_HOOKS=1`, jamais actifs
en build normal) :

### T11 — Hooks de test front (prérequis)
- [ ] `window.__W40K_TEST__` exposant l'état RENDU (pas l'état API) : par unité, le fait qu'un
      cercle vert est dessiné (`renderGreenActivationCircle` effectivement appelé, `UnitRenderer.tsx:1475`),
      les hexes de preview peints, le mode courant (`squadModelShoot`, …), la sélection, les positions
      écran des figurines (pour cliquer juste sur le canvas).
- [ ] `data-testid` sur toute l'UI DOM (boutons de phase, menus d'armes, HUD, modales).
- [ ] Helper de clic board : conversion hex → coordonnées écran exposée par le hook de test
      (le test clique sur le canvas aux coordonnées réelles, PAS en dispatchant des événements
      synthétiques internes — on teste la vraie chaîne hit-test PIXI).

### T12 — Scénarios E2E (Chromium ; backend réel spawné sans reloader, partie `pvp_test`)
- [ ] Login → lancement PvP test → board affiché (canvas non vide, 41 unités rendues).
- [ ] **Cercles verts** : ensemble des unités cerclées == pool backend, à CHAQUE phase, y compris
      après chaque activation/skip (le hook de test lit ce qui est dessiné, l'API dit ce qui doit l'être).
- [ ] **Preview move** : clic unité éligible → hexes peints == `valid_move_destinations_pool`,
      masque affiché ; clic destination → figurine déplacée à l'écran ; clic droit → annulation.
- [ ] **Preview tir** : activation → cibles qui blinkent == `valid_targets` du LoS overview ;
      cône LoS WASM affiché ; menu d'armes conforme ; résolution → HP bars mises à jour.
- [ ] Charge (avec `charge_roll_override` posé via l'UI debug si exposé, sinon via API avant le clic),
      fight (pile-in par figurine à la molette, attribution, consolidation) — chaque étape vérifiée
      visuellement via le hook + API.
- [ ] Rewind/playback : restore d'un snapshot → le board re-rend l'état restauré.
- [ ] **Assertions scene-graph PIXI (mode principal, PAS le screenshot)** : le hook de test expose
      une lecture du stage PIXI (par unité : cercle vert présent/couleur/épaisseur, hexes de preview
      peints, HP bar, blink actif). Déterministe, rapide, diff lisible — c'est lui qui vérifie
      « ce qui est dessiné == ce que dit l'API » à chaque étape des scénarios.
- [ ] **Régression visuelle (complément minimal)** : screenshots `toHaveScreenshot` sur ~10 états
      canoniques SEULEMENT (board initial, preview move, tir, mêlée, fin de partie) — seul filet pour
      les bugs que le scene-graph ne voit pas (z-order effectif, alpha, shaders). Fragile par nature :
      seuil de tolérance calibré, rendu fixé (fenêtre fixe, `deviceScaleFactor:1`, fonts embarquées),
      à ne PAS généraliser au-delà de ces ~10 états.
- [ ] Console : tout `console.error`/exception non attendu pendant un scénario = FAIL.

### T13 — Orchestration et CI
- [ ] `scripts/front_test_all.sh` : couche A (exit code) → couche B (`npm run test:run`) → couche C
      (`npx playwright test`), chacune avec son propre serveur backend éphémère (ports dédiés,
      `use_reloader=False`), token via `--token-from-db`.
- [ ] Nettoyage garanti (trap) : aucun process orphelin, aucune écriture dans `config/users.db`
      ni `ai/models/`.
- [ ] Rapport unique : total PASS/FAIL par couche + screenshots des échecs Playwright.

---

## Matrice de couverture — les 58 actions du front

Vocabulaire complet relevé dans `useEngineAPI.ts` (`action: "..."`). Une action sans tranche = trou
de couverture. État : ✅ testée (T1 fait), sinon tranche cible.

| Action | Tranche | Action | Tranche |
|---|---|---|---|
| `activate_unit` (move) | ✅ T1 | `squad_shoot_activate` | ✅ T1 |
| `move` | ✅ T1 | `squad_shoot_los_overview` | ✅ T1 |
| `skip` | ✅ T1 | `squad_shoot_cancel` | ✅ T1 |
| `advance_phase` | ✅ T1 | `squad_shoot_select_model` | T4 |
| `advance` | T3 | `squad_shoot_assign_weapon_qty` | T4 |
| `wait` | T3 | `squad_shoot_weapon_qty_max` | T4 |
| `preview_move_plan` | T3 | `squad_shoot_unassign` | T4 |
| `move_model_destinations` | T3 | `squad_shoot_unassign_weapon` | T4 |
| `commit_move_plan` | T3 | `squad_shoot_validate` | T4 |
| `left_click` | T3 | `squad_shoot_allocate_model` | T4 |
| `right_click` | T3/T5 | `move_after_shooting` | T4 |
| `end_phase` | T3 | `shoot` | T4 |
| `deploy_unit` | T3a | `charge` | T5 |
| `deploy_preview` | T3a | `charge_plan_state` | T5 |
| `deploy_generate_formation` | T3a | `commit_charge_plan` | T5 |
| `deploy_model_destinations` | T3a | `charge_autoplace` | T5 |
| `deploy_squad_destinations` | T3a | `take_to_skies` | T5 |
| `deploy_commit` | T3a | `force_charged` | T5 |
| `change_roster` | T3a | `fight` | T6 |
| `select_rule_choice` | T2b | `skip_fight` | T6 |
| `force_battle_shock` | T2b/T7 | `squad_fight_assign` | T6 |
| `pile_in_plan_state` | T6 | `squad_fight_assign_weapon` | T6 |
| `pile_in_autoplace` | T6 | `squad_fight_validate` | T6 |
| `commit_pile_in_plan` | T6 | `squad_fight_manual_alloc` | T6 |
| `end_pile_in` | T6 | `squad_hazard_allocate_model` | T6 |
| `consolidation_plan_state` | T6 | `hazard_confirm` | T6 |
| `consolidation_select_target` | T6 | `end_consolidation` | T6 |
| `consolidation_select_objective` | T6 | `cancel_consolidation` | T6 |
| `consolidate_autoplace` | T6 | `endless_duty_status` | hors périmètre |
| `commit_consolidation_plan` | T6 | `endless_duty_commit` | hors périmètre |

## Ordre de réalisation conseillé et coûts

| Étape | Contenu | Coût estimé | Valeur |
|---|---|---|---|
| T2-T3 | Invariants + move escouade/advance/fall-back (API) | faible | haute — cœur du jeu |
| T5-T6 | Charge + fight (API) | moyen | haute — zone à bugs historique |
| T4 | Shoot par arme/figurine + unités cachées (API) | moyen | haute |
| T7b | Fuzzing par invariants | faible (réutilise T2) | très haute — couvre l'imprévu |
| T2b, T3a | Command/réactions + déploiement (API) | moyen | moyenne |
| T7 | Snapshots/save/fin de partie (API) | faible | moyenne |
| T8-T10 | vitest hook + utils + composants DOM | moyen | moyenne |
| T11 | Hooks de test front (prérequis C) | moyen | — (infra) |
| T12 | E2E Playwright (scene-graph + ~10 screenshots) | élevé | haute — seul filet « rendu » |
| T13 | Orchestration/CI | faible | moyenne |

## Pièges connus (acquis pendant T1)
- Reloader Werkzeug : ne JAMAIS tester contre un serveur `debug=True` d'avant le fix — parties effacées.
- `pkill -f` avec un pattern présent dans sa propre ligne de commande se tue lui-même (utiliser
  `pgrep -af "motif[x]"`).
- Le serveur spawné par le harnais meurt avec lui (atexit) — pour sonder à la main, lancer un serveur
  séparé.
- Sémantique HP escouade/leader attaché (cf. §0.2) — toute assertion HP doit passer par `models_cache`.
- Les checks « composition de pool » doivent rester ⊆ (sous-ensemble) tant que la règle exacte
  d'éligibilité n'a pas été lue dans le PDF correspondant — l'égalité stricte exige la référence règle.
