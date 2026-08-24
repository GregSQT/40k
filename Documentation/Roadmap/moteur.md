# Moteur — Tâches ouvertes

---

## P3-0 — Retrait pour cohérence 03.03 {#p3-0}

✅ **Livré 2026-08-23.** TOTAL_ACTION_SIZE 1359 → 1379 (+20 slots COHERENCY). Queue multi-escouade, sièges muets auto-résolus, tête pointeur `coherency_query_net` sur `self_models`. 32 tests verts. Run `--new` requis.

→ `Documentation/Implémentation/Implémenté/coherency_removal_choix_agent.md`

---

## Plunging Fire (22.05) {#plunging-fire}

Règle : +1 au hit roll pour les attaques à distance ciblant une unité visible dont des figurines sont au sol, si l'attaquant est sur un terrain feature ≥3" de hauteur (ou TOWERING et cible à ≤12"). Sans effet sur les AIRCRAFT.

Dernier trou de fidélité aux règles pour les rosters Armageddon (démo).

Périmètre estimé : `shooting_handlers.py` (calcul modificateur BS) + `attack_sequence.py` (token) + test rouge/vert.

---

## T7 — Unification validation de déploiement {#t7}

**Suspendu.** Déclencheur : « le training tourne ».

🔴 Le fix décrit est FAUX en l'état (mesuré 2026-07-20) — c'est une décision de design (plan contraint par l'ancre), pas un bug. Re-analyser avant de toucher.

→ `Documentation/Implémentation/1_Agent/V11_tranches.md` §5 T7

---

## Phase B — Observation des niveaux {#phase-b}

**Suspendu.** Après Phase A' validée ET vérification du chantier LoS 3D (`combat_utils`/WASM, câblage incomplet).

→ `Documentation/Implémentation/1_Agent/V11_tranches.md`

---

## LoS 3D : tir à travers un mur depuis un étage {#los-mur-etage}

**À cadrer — jamais ouvert.** Signalé le 2026-08-11 pendant le chantier socle vs mur : « on peut tirer à travers un mur quand on est à l'étage » relève de la LoS, pas du placement. Vraisemblablement le même câblage incomplet que celui qui suspend la Phase B (`combat_utils`/WASM) — à confronter au code avant d'ouvrir.

---

## Preview de tir sans deepcopy {#preview-tir}

**Lourd, re-cadrer avant reprise.** 4-8 j. Meilleure spec du lot, mais touche `compute_unit_los` = source unique (obs RL, reward, déploiement).

→ `Documentation/Implémentation/A_faire/preview_tir_position_virtuelle.md`

---

## Endless Duty {#endless-duty}

**Bloqué par décision produit.** 8-13 j. Décisions en attente : obstacle 3 (format objectifs) et 7 (double sens de `VALUE`).

→ `Documentation/Implémentation/A_faire/Endless_duty_etat_mesure.md`

---

## fix-reactive-move-coherency — ✅ livré 2026-08-21 {#reactive-move-coherency}

Move réactif : une escouade hors cohérence ne pouvait pas faire ce mouvement (03.01) mais le moteur ne le bloquait pas. Fix : check `_positions_in_coherency` avant le pool D6 dans `maybe_resolve_reactive_move`, log `reactive_move_declined reason=formation_incoherente`. Aligné sur le move normal (`build_squad_move_cell_map`). Test rouge→vert par mutation.

---

## Replis `unit_by_id` {#unit-by-id}

**T0 livré le 2026-08-19** — `require_unit_by_id(game_state, unit_id)` dans `engine/game_utils.py`, re-exportée depuis `combat_utils`. Signature canonique `(game_state, unit_id)` alignée sur le pattern moteur. Reste : T1 (10 sites Forme C), T2 (46 sites Forme B), T3 (64 sites Forme D) — ~4-5 sessions.

→ `Documentation/Implémentation/A_faire/replis_unit_by_id_2026-08-05.md`
