# Moteur — Tâches ouvertes

---

## P3-0 — Retrait pour cohérence 03.03 {#p3-0}

**Suspendu.** Déclencheur : **le prochain dégel de `TOTAL_ACTION_SIZE`**, groupé avec les tranches de §1 qui en demanderont un (P3-5, P3-6 branchent elles aussi des décisions ; P3-4 est livré).

⚠️ Un dégel est déjà passé SANS lui : INDIRECT FIRE a consommé 1139 → 1159 le 2026-08-17 (`TOTAL_ACTION_SIZE` dans `engine/macro_intents.py`), run `--new` payé — la plage que la décision d'origine chiffrait pour P3-0 est occupée.

L'étape End of Turn retire les figurines hors cohérence en choisissant à la place du joueur (la plus éloignée du centroïde). 03.03 donne ce choix au contrôleur de l'unité.

Décisions tranchées (2026-08-12, ne pas rouvrir) :
1. Le choix est branché **pour les deux** (joueur ET agent)
2. Via une tranche d'ids d'action DÉDIÉE de 20 slots, allouée à la suite de `TOTAL_ACTION_SIZE` au moment du dégel — la valeur exacte appartient au code, ne pas la re-chiffrer ici — et non taillée dans la plage des cellules de move

⚠️ Le jalon EST le coût : ce dégel se paie en run `--new` complet.

→ `Documentation/Implémentation/A_faire/coherency_removal_choix_agent.md`

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

## Replis `unit_by_id` {#unit-by-id}

**Bloqué par décision utilisateur.** T0 = signature de `require_unit_by_id` appartient à l'utilisateur ; ~4-5 sessions ensuite.

⚠️ Chiffres du doc périmés 3× : **5** implémentations du lookup désormais, pas 4.

→ `Documentation/Implémentation/A_faire/replis_unit_by_id_2026-08-05.md`
