# Convergence des résolveurs de mêlée — doc d'implémentation

Statut : **PLAN — non implémenté**. Date : 2026-07-05.
Objectif : supprimer le résolveur de combat « pool de PV » et faire tourner le moteur
d'allocation par-figurine (groupes 05.03/05.04) en mode **auto (headless)** pour tous les
défenseurs non-humains (training RL, PvE, IA en PvP), afin de corriger l'attribution
to-wound / save sur les unités hétérogènes et personnages attachés.

---

## 1. Problème

La résolution de combat fige les seuils sur la **1re figurine vivante** de l'unité cible et
jette la save **avant** l'allocation. Correct pour une unité homogène, **faux** dès qu'une
unité a des profils mixtes (T/Sv/InvSv différents) ou un personnage attaché : une blessure
allouée à une figurine plus résistante est résolue avec le to-wound et la save de la figurine
de base.

## 2. Root cause (vérifiée code + règles)

### Règles (PDF)
- **05.02 Wound rolls** : un seul seuil to-wound, niveau unité (une seule Toughness).
- **19.02 Attacking attached units** : pour une unité attachée, le wound roll utilise la
  **plus haute T des figurines _bodyguard_** (jamais celle du leader, même si l'attaque lui
  est ensuite allouée). Si l'unité ne contient que du leader/support, plus haute T de ceux-ci.
- **05.03 Save rolls** : groupes d'allocation = 1 par CHARACTER, 1 par triplet (W, Sv, InvSv).
  Ordre légal : figurine blessée d'un groupe non-CHARACTER en premier ; aucun groupe CHARACTER
  avant un non-CHARACTER ; CHARACTER blessé avant CHARACTER sain.
- **05.04 Inflict damage** : save vérifiée **par groupe alloué** (sa Sv/InvSv), résolution du
  **plus bas jet de save au plus haut**, en sélectionnant une figurine du groupe courant
  (blessée d'abord si possible).

### Code — TROIS résolveurs de mêlée (corrigé après investigation 2026-07-05)
1. `resolve_squad_fight` (`shared_utils.py:7090`) — **résolveur du TRAINING/RL**
   (w40k_core.py:4982). Consomme les intents per-fig, mais **fige T/save sur `first_alive`**
   (lignes 7159-7170) et alloue via `_allocate_damage_to_squad` → `_select_allocation_model`
   (pool, sans groupes). **Même bug que le tir auto.**
2. `_execute_fight_attack_sequence` (`fight_handlers.py:3700`) — chemin **auto-step PvE/gym
   granulaire**, via `_fight_v11_resolve_attacks` (`:4949`). Attaquant traité en **agrégat**
   (1 arme, 1 cible, retarget), `target["T"]`, pool. Viole aussi 04.01 (arme par figurine) et
   04.02 (cible engagée par figurine).
3. `_manual_roll_fight_intent` (`fight_handlers.py:6945`) via le moteur mutualisé
   `_build_manual_allocation` (`shared_utils.py:6269`) — chemin **PvP humain**, seul **correct**
   (groupes `_build_alloc_groups` `:5846`, T bodyguard 19.02, save par-figurine allouée).

Le producteur d'intents auto per-figurine **existe déjà** : `squad_declare_fight`
(`shared_utils.py:7029`, `get_fighting_models` + `_auto_select_cc_weapon_for_fig`), et le
training l'appelle déjà avant `resolve_squad_fight`. Jumeau tir : `squad_declare_shoot`
(`:4097`). Le tir auto présente la même structure/bug via `resolve_squad_shoot`.

Correction règle T (fait §9.2) : `_target_majority_toughness` (T majoritaire, 9e) remplacée par
`_target_highest_bodyguard_toughness` (19.02) — utilisée par le moteur groupes.

### Corollaire tir
Le tir présente la **même dualité** : tir auto = chemin pool `resolve_squad_shoot`
(`shared_utils.py:5654`) → `_allocate_damage_to_squad` (`:5340`) → `_select_allocation_model`
(`:5302`), avec la save figée dans `_roll_squad_shot_sequence` (`:5491-5496`) ; tir manuel =
même moteur groupes que le combat. Le décideur auto conçu ici est **générique** (niveau
`_build_manual_allocation`) et bénéficie donc aussi au tir → voir phase optionnelle §8.

## 3. Pourquoi on ne supprime pas directement le pool

`_execute_fight_attack_sequence` est le **seul résolveur de mêlée entièrement automatique**.
Le moteur par-figurine rend la main au défenseur humain à deux points de décision :
- déclaration de l'ordre des groupes — `_declare_order_payload` (`shared_utils.py:5908`) ;
- choix de la figurine du groupe courant — `_manual_waiting_payload` (`shared_utils.py:6045`).

Le mode est choisi partout par `defender_human = not _is_ai_controlled_fight_unit(...)`
(`fight_handlers.py:6777-6812` et `7476-7528`). Il faut donc d'abord doter le moteur groupes
d'un **décideur auto** (headless) avant de pouvoir supprimer le pool.

---

## 4. DÉCISION D'ARCHITECTURE — Voie A (RETENUE, 2026-07-05)

**Choix acté : Voie A — convergence vers un moteur unique.** On supprime le résolveur pool
`_execute_fight_attack_sequence` et on fait tourner le moteur groupes par-figurine (celui du
PvP manuel) aussi en auto, via un décideur automatique ajouté à `_build_manual_allocation`.
Training / PvE / IA en PvP sont routés vers ce moteur.

- ✅ Un seul moteur, règles 05.03/05.04 + 19.02 correctes partout, dette supprimée.
- ⚠️ Le moteur groupes consomme le RNG dans un **ordre différent** du pool (tous les intents
  jetés d'abord, puis allocation triée par save). **Iso-RNG bit-à-bit impossible.** La
  distribution des pertes change → re-validation training obligatoire, ré-entraînement probable
  (assumé comme livrable de première classe, §7).

Alternative écartée — Voie B (corriger le pool en place, garder les deux moteurs) : préserve
le RNG du training mais laisse la dualité en place, donc « ne supprime rien ». Non retenue.
À ne reconsidérer que si le ré-entraînement s'avère un blocage dur au checkpoint §7.

---

## 5. Décideur auto (cœur du chantier)

Nouveau composant : un décideur qui répond automatiquement aux deux points de décision du
moteur groupes quand le défenseur n'est pas humain. À placer au niveau générique
(`_build_manual_allocation` / `_manual_allocation_step`), paramétré par un flag
`auto_defender: bool` (ou une callback `decider_fn` dans `ManualAllocCtx`).

### 5.1 Ordre des groupes (remplace `_declare_order_payload` en auto)
Produire un ordre **déterministe conforme 05.04**, sans attente :
1. Groupes non-CHARACTER contenant une figurine blessée (obligatoire en premier).
2. Groupes non-CHARACTER sains — tie-break heuristique : tier de rôle croissant puis
   Sv (réutiliser la logique de tri de `_select_allocation_model`, `shared_utils.py:5330-5337`).
3. Groupes CHARACTER blessés.
4. Groupes CHARACTER sains.
Contraintes dures à respecter (déjà validées côté manuel par `apply_manual_shoot_declare_order`
et le garde `un CHARACTER blesse doit preceder un CHARACTER sain`, `shared_utils.py:6540-6547`).

### 5.2 Choix de la figurine du groupe courant (remplace `_manual_waiting_payload` en auto)
Variante de `_select_allocation_model` **restreinte au groupe courant** : figurine blessée
d'abord (déjà forcé par `_manual_allocation_step` de toute façon), sinon proximité ennemi /
index. Aucune attente : le moteur enchaîne jusqu'à `_finalize_manual_allocation`.

### 5.3 Cohérence comportementale
Le décideur auto doit **reproduire l'intention tactique** de `_select_allocation_model` (finir
un blessé, exposer les characters en dernier) pour minimiser l'écart de comportement vs l'ancien
pool, même si la RNG bit diffère.

## 6. Correction règle Toughness (19.02)

Remplacer `_target_majority_toughness` (T majoritaire) par une fonction **plus haute T
bodyguard** :
- Si l'unité contient ≥1 figurine bodyguard vivante → max T des bodyguards.
- Sinon (leader/support seuls) → max T des figurines restantes.
Nécessite de distinguer bodyguard vs leader/support dans `models_cache` (rôle character /
flag leader). Vérifier le champ disponible (`role`, `_is_character_role`). Aucun fallback
silencieux : si la donnée manque → erreur explicite (`require_key`).
Corriger aux deux points d'appel : `_manual_roll_fight_intent` (`fight_handlers.py:6990`) et,
si le décideur générique le partage, le tir.

## 7. Non-régression training (livrable critique — Voie A)

L'iso-RNG bit-à-bit est **hors d'atteinte**. Plan de validation :
1. **Unité homogène, sans perso** : prouver que le **nombre de pertes** et les seuils sont
   identiques statistiquement (l'identité de la figurine tuée peut différer — sans effet gameplay).
   Méthode : `python3 ai/train.py --agent CoreAgent --scenario bot --step` + `ai/analyzer.py`,
   comparer avant/après sur N épisodes.
2. **Scénario dédié hétérogène** : `config/board/25x21/scenario/scenario_attached_unit_test.json`
   (FAIT + VALIDÉ par drive direct). Cible = unité attachée (Intercessor T4/Sv3 + CaptainTerminator
   T5/Sv2/Inv4, role leader). Résultats mesurés sur exécution réelle :
   - `_target_highest_bodyguard_toughness` = **4** (plus haute T bodyguard, 19.02 — PAS T5 leader).
   - `woundTarget` des records de jets = **[4]** → la résolution combat utilise bien T4 (preuve
     end-to-end que le bug first_alive est corrigé).
   - `_build_alloc_groups` = BODY(Sv3) + CHAR(Sv2/Inv4) ; save par-fig = Intercessor 4+, Captain 3+
     (sous AP-1) — 05.03/05.04.
   - Chemin training (defenseur IA) : `build_manual_fight_allocation` complète headless (done=True)
     et renvoie le summary fight — §9.4b-1 confirmé.
   NB géométrie : les grandes bases (Terminator) empêchent le placement au contact hex ; la
   validation utilise un intent injecté (le résolveur d'allocation n'exige pas l'engagement).
3. **Régression de perf modèle** : surveiller le score sur plusieurs scénarios (pas un pic
   isolé, cf. pièges connus catastrophic forgetting). Décider ré-entraînement si dérive.
4. Ne **rien revendiquer** comme « strictement identique » : formuler « même nombre de
   pertes / seuils corrects par figurine ».

## 8. Corollaire tir — FAIT

Tir auto convergé vers le moteur groupes (même schéma que le combat) :
- `SHOOT_CTX.auto_decider = _target_defender_is_ai` (décideur générique dans shared_utils :
  True si le propriétaire de la cible est IA → headless).
- Routing : les 2 sites `resolve_squad_shoot` (w40k_core:4668 PvP défenseur-IA, :4903 gym auto)
  remplacés par `build_manual_shoot_allocation` + garde-fou `done`.
- Le chemin manuel tir utilisait déjà `_target_highest_bodyguard_toughness` (corrigé §9.2) →
  rules-correct sans changement supplémentaire.
- `resolve_squad_shoot` supprimé (mort). Validé : `woundTarget={4}` en tir (T bodyguard),
  headless `done=True`.
- **Reste (cleanup mineur)** : helpers pool tir devenus morts
  (`_resolve_shoot_intent_pass1`, `_allocate_damage_to_squad`) + import inutilisé
  `_roll_squad_shot_sequence` dans shooting_handlers — suppression cosmétique à faire.

## 9. Ordre des étapes & fichiers touchés

1. **Checkpoint architecture** (§4) — valider Voie A/B. _Aucun code avant ça._
2. Fonction « plus haute T bodyguard » + remplacement de `_target_majority_toughness`
   → `shared_utils.py`.
3. Décideur auto (ordre groupes + choix fig) dans `_build_manual_allocation` /
   `_manual_allocation_step`, flag `auto_defender` → `shared_utils.py`.
4. **[FAIT §9.3]** Décideur auto générique dans `_manual_allocation_step` + `_auto_declared_order`.
4bis. **[FAIT §9.4a]** `auto_decider=_fight_auto_defender` câblé sur `FIGHT_CTX` (inerte tant
   que rien ne route l'auto vers le moteur groupes).
5. **[§9.4b — bascule training, à valider]** Router la résolution auto vers le moteur groupes,
   en réutilisant `squad_declare_fight` (déjà en place, aucun producteur à écrire) :
   - **Training/RL** : w40k_core.py:4982 — remplacer `resolve_squad_fight(...)` par
     `build_manual_fight_allocation(...)`. Réconcilier le contrat de retour (le moteur groupes
     renvoie `{action, done, shoot_result: summary}` ; le training attend le `summary` fight).
   - **[FAIT §9.4b-2]** Auto-step PvE/gym : corps de `_fight_v11_resolve_attacks` (`:4949`)
     remplacé par sélection cible + `squad_fight_unit_activation_start` + `squad_declare_fight`
     + `build_manual_fight_allocation`, avec adaptateur summary→`all_attack_results`
     (target_died/damage/ids). Validé : `woundTarget={4}` (T bodyguard) via le chemin auto-step,
     complétion headless, pas d'exception. Gagne 04.01/04.02 (arme + engagement par figurine).
   - Défenseur IA garanti → `auto_decider` True → exécution headless jusqu'à `done`.
6. Validation non-régression §7 (checkpoint training : même nombre de pertes en homogène,
   seuils corrects par figurine en hétérogène ; décider ré-entraînement). **RESTE À FAIRE.**
7. **[FAIT §9.7] Suppression** (reachability confirmée, imports + smoke test verts) :
   - `resolve_squad_fight` supprimé (plus aucun appelant).
   - Cluster V10 mort supprimé : `_execute_action_v10_unused`, `_handle_fight_unit_switch`,
     `_handle_fight_pile_in_resolution`, `_handle_fight_unit_activation`, `_handle_fight_attack`.
   - `_execute_fight_attack_sequence` supprimé + tests obsolètes retirés
     (`test_fight_attack_sequence.py` supprimé ; 3 tests pool retirés de `test_phase_transitions.py`,
     reste 11 tests). Le comportement hit/wound/save→HP est désormais couvert par le moteur groupes
     (validé §7.2). NB : `_handle_fight_postpone` conservé (hors cluster).
8. (Optionnel §8) convergence tir — même schéma : `squad_declare_shoot` +
   `build_manual_shoot_allocation` à la place de `resolve_squad_shoot`.

## 10. Contraintes projet
- Aucun fallback / valeur par défaut anti-erreur : donnée manquante → `require_key` / erreur explicite.
- Ne pas modifier `config/users.db` ni `ai/models/**/*.zip`.
- Toute affirmation de règle adossée au PDF (04, 05, 19).
