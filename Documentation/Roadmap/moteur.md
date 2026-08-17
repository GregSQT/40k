# Moteur — Tâches ouvertes

---

## Pile-in / Overrun 12.06 par-figurine {#pile-in}

**Prérequis de P3-5.** 3-5 j après prérequis « le gym emprunte la machine V11 ».

→ `A_faire/pile_in_overrun_par_figurine.md`

---

## P3-0 — Retrait pour cohérence 03.03 {#p3-0}

**Suspendu.** Déclencheur : **le prochain dégel de `TOTAL_ACTION_SIZE`**, groupé avec les tranches de §1 (P3-4, P3-5, P3-6 branchent elles aussi des décisions).

L'étape End of Turn retire les figurines hors cohérence en choisissant à la place du joueur (la plus éloignée du centroïde). 03.03 donne ce choix au contrôleur de l'unité.

Décisions tranchées (2026-08-12, ne pas rouvrir) :
1. Le choix est branché **pour les deux** (joueur ET agent)
2. Via une tranche d'ids d'action DÉDIÉE (1139 → 1159) et non taillée dans la plage des cellules de move

⚠️ Le jalon EST le coût : ce dégel se paie en run `--new` complet.

→ `A_faire/coherency_removal_choix_agent.md`

---

## T7 — Unification validation de déploiement {#t7}

**Suspendu.** Déclencheur : « le training tourne ».

🔴 Le fix décrit est FAUX en l'état (mesuré 2026-07-20) — c'est une décision de design (plan contraint par l'ancre), pas un bug. Re-analyser avant de toucher.

→ `1_Agent/V11_tranches.md` §5 T7

---

## Phase B — Observation des niveaux {#phase-b}

**Suspendu.** Après Phase A' validée ET vérification du chantier LoS 3D (`combat_utils`/WASM, câblage incomplet).

→ `1_Agent/V11_tranches.md`

---

## Preview de tir sans deepcopy {#preview-tir}

**Lourd, re-cadrer avant reprise.** 4-8 j. Meilleure spec du lot, mais touche `compute_unit_los` = source unique (obs RL, reward, déploiement).

→ `A_faire/preview_tir_position_virtuelle.md`

---

## Endless Duty {#endless-duty}

**Bloqué par décision produit.** 8-13 j. Décisions en attente : obstacle 3 (format objectifs) et 7 (double sens de `VALUE`).

→ `A_faire/Endless_duty_etat_mesure.md`

---

## Replis `unit_by_id` {#unit-by-id}

**Bloqué par décision utilisateur.** T0 = signature de `require_unit_by_id` appartient à l'utilisateur ; ~4-5 sessions ensuite.

⚠️ Chiffres du doc périmés 3× : **5** implémentations du lookup désormais, pas 4.

→ `A_faire/replis_unit_by_id_2026-08-05.md`
