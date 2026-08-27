# Allocation des attaques — moteur d'allocation manuelle mutualisé tir/mêlée

> **Objet** : référence du mécanisme d'attribution des attaques et d'allocation des pertes
> (PDF 04 / PDF 05), mutualisé entre tir et mêlée, par-figurine : flux, couches, invariants,
> et les décisions de conception qui les fondent.
> **Source absorbée** : `refactor_attack_shoot_fight1.md` (revue fondatrice du refactor,
> 2026-06-14) — déplacée dans `Documentation/Archives/docs/` avec bandeau retour.
> **L'état des chantiers fait foi dans `Documentation/Roadmap/`, jamais ici.**
> Source de vérité règles : `Documentation/40k_rules/` (le PDF tranche toujours).

---

## 1. Vue d'ensemble — trois couches, un seul chemin

Le mécanisme est découpé en trois couches, chacune paramétrée par un contexte de phase
(tir / mêlée) plutôt que dupliquée :

| Couche | Mécanisme partagé | Contextes | Fichier |
|---|---|---|---|
| **Déclaration offensive** (attribution cible/arme par figurine) | `class DeclareAttackCtx`, `def declare_attack_model`, `def declare_attack_weapon`, `def declare_attack_weapon_qty` | `SHOOT_DECLARE_CTX` (shared_utils) / `FIGHT_DECLARE_CTX` (fight_handlers) | [shared_utils.py](../../../engine/phase_handlers/shared_utils.py) |
| **Résolution des jets** (hit → wound → save_roll) | module commun `attack_sequence` (`class WeaponAttackProfile`, `class RerollProfile`) consommé par les deux rollers de phase : `def _manual_roll_intent` (tir) et `def _manual_roll_fight_intent` (mêlée) | — | [attack_sequence.py](../../../engine/phase_handlers/attack_sequence.py) |
| **Allocation des pertes** (05.03 / 05.04) | `class ManualAllocCtx`, `def _build_manual_allocation`, `def apply_manual_shoot_declare_order`, `def apply_manual_shoot_allocation` | `SHOOT_CTX` (shared_utils) / `FIGHT_CTX` (fight_handlers) | [shared_utils.py](../../../engine/phase_handlers/shared_utils.py) |

**Convergence** : il n'existe plus qu'UN chemin de résolution, PvP manuel comme PvE/gym.
Le chemin auto passe par le même moteur d'allocation en mode headless : le champ
`auto_decider` du `ManualAllocCtx` (branché sur `def is_programmatic_defender`,
source unique `def is_programmatic_owner`) fait trancher au moteur l'ordre des groupes
et le choix de figurine quand le défenseur est piloté par la machine, au lieu de rendre
la main. Côté tir, l'entrée auto est `build_manual_shoot_allocation` appelée depuis le
chemin `squad_shoot` de [w40k_core.py](../../../engine/w40k_core.py) ; côté mêlée,
`build_manual_fight_allocation` appelée depuis `def _fight_v11_resolve_attacks`
([fight_handlers.py](../../../engine/phase_handlers/fight_handlers.py)), qui a remplacé
l'ancien résolveur « pool de PV homogène ».

Le moteur d'allocation sert aussi les blessures mortelles **[HAZARDOUS] 24.15**
(champs `mortal` / `hazard_origin` du ctx, `def _resolve_one_hazard_wound`) : pas d'arme,
pas de save, allocation par figurine identique.

---

## 2. Décision fondatrice — mutualiser l'allocation, pas la résolution (§O)

Décision actée en revue (2026-06-14), **citée par la docstring de `class ManualAllocCtx`** :

1. **Couche résolution des jets** : elle reste **spécifique à chaque phase**. Raison
   d'origine (§B) : le moteur manuel tir de l'époque ne gérait aucun reroll ; réutiliser
   sa résolution en mêlée aurait perdu les rerolls de combat — rédhibitoire. La résolution
   mêlée garde donc son roller propre (`def _manual_roll_fight_intent`), qui préserve les
   rerolls, et le socle commun des jets a depuis été extrait dans `attack_sequence.py`
   (une seule implémentation des critiques 05.01/05.02 et des règles d'armes qui s'y
   accrochent), consommé par les deux rollers.
2. **Couche attribution + allocation des pertes** : les règles sont **identiques
   tir/mêlée** (PDF 05 §05.03/05.04 invoqué pareil par les deux phases — seule différence
   au hit roll : BS vs WS). C'est là que la généralisation par ctx est légitime, et elle
   est faite une seule fois dans le module commun.

Principe directeur conservé de la revue : **coller à la règle, pas à l'historique** — on
ne cherche pas à reproduire le comportement existant, on vérifie qu'il respecte le PDF.
La validation d'un changement de cette zone passe par la conformité règle + test PvP
manuel, jamais par une exigence d'iso-RNG.

Verdict historique de la revue : NO-GO sur la proposition initiale (elle ciblait le code
mort V10 et aurait perdu les rerolls et les invalidations de cache fight) ; GO sur cette
approche en deux couches, greffée sur la machine V11 existante. Détail en fin de document.

---

## 3. Couche déclaration — attribution par figurine, par arme, par quantité

- **Granularité par-figurine imposée par la règle (§K)** : PDF 04 §04.02 (mêlée) — les
  cibles sont les unités *engaged with the model*, nombre de cibles ≤ caractéristique A ;
  encart SPLITTING MELEE ATTACKS. L'éligibilité se teste donc au niveau de la **figurine
  attaquante**, pas de l'unité : `def _model_can_fight_target` et
  `def _model_can_fight_target_with_weapon` (fight_handlers) côté mêlée,
  `def _model_can_shoot_target` (portée + LoS via `def _attacker_model_can_reach_squad`,
  shared_utils) côté tir. Ces tests sont injectés dans le moteur générique par les
  callbacks `can_target` / `can_target_with_weapon` du `DeclareAttackCtx`.
  Le pool unité-niveau (`def _fight_build_valid_target_pool`) sert à la sélection de
  cible auto, pas à l'éligibilité par-figurine. La formulation « base contact avec un ami
  lui-même en engagement » n'existe pas dans les règles (vérifié en revue) — l'engagement
  de la figurine attaquante est la seule condition.
- **Répartition multi-cibles (04.03, encart SPLITTING)** : le flux par arme/quantité
  (`def declare_attack_weapon_qty`, wrappers mêlée `def squad_declare_fight_weapon_qty`
  et actions `squad_fight_assign_weapon_qty` / `squad_fight_unassign_weapon_qty` /
  `squad_fight_toggle_model_weapon` de la machine V11) permet de répartir les attaques
  d'une même arme sur plusieurs unités. La clause « une seule cible » de certaines règles
  ([CLEAVE] 24.06) est testée par `def _weapon_attacks_single_target` (fight_handlers).
- **Invariant NB (fix F3)** : le nombre d'attaques d'un intent est résolu **une seule
  fois, à la déclaration** (`n_attacks_resolved` porté par l'intent), jamais re-résolu à
  la résolution — un double tirage découplerait le NB affiché du NB résolu. Le
  `DeclareAttackCtx` centralise cette résolution unique.
- **Pas de priorité de cible en mêlée** (contrairement au tir) — confirmé règles, cela
  simplifie la couche mêlée.
- Les différences injectées par ctx : clé d'intents (`pending_squad_shoot_intents` /
  `pending_squad_fight_intents`), attribut d'arme sélectionnée (`selectedRngWeaponIndex` /
  `selectedCcWeaponIndex`), liste d'armes (`RNG_WEAPONS` / `CC_WEAPONS`).

---

## 4. Couche résolution — parité rerolls et règles d'armes (§B)

**Le point critique de la revue fondatrice** : la résolution mêlée gère des rerolls que le
moteur manuel tir de l'époque ignorait. Les réutiliser tels quels aurait été une perte de
règles. Les 4 rerolls de combat sont préservés dans `def _manual_roll_fight_intent`
(fight_handlers), via `class RerollProfile` (attack_sequence) et
`def stamp_reroll_abilities` (shared_utils) :

| Ability (unit_rules) | Étape |
|---|---|
| `reroll_1_tohit_fight` | hit roll == 1 (attaquant) |
| `reroll_towound_target_on_objective` | wound échoué, cible sur objectif (attaquant) |
| `reroll_1_towound` | wound roll == 1 (attaquant) |
| `reroll_1_save_fight` | save roll == 1 (testé sur l'**unité** cible, pas une figurine) |

Répartition des responsabilités (docstring d'`attack_sequence.py`, source de vérité) :

- **Dans le module commun** : critiques 05.01/05.02 et règles d'armes qui s'y accrochent —
  [TORRENT] 24.37, [SUSTAINED HITS] 24.36, [LETHAL HITS] 24.23, [TWIN-LINKED] 24.38,
  [ANTI-X] 24.03, [DEVASTATING WOUNDS] 24.10.
- **Chez l'appelant (spécifique phase)** : le pool d'attaques ([BLAST] 24.05,
  [RAPID FIRE] 24.30, [CLEAVE] 24.06, [EXTRA ATTACKS] 24.11), les modificateurs du seuil
  de touche ([HEAVY] 24.16, couvert via `def _cover_worsened_bs`, [PSYCHIC] 24.29),
  l'AP effectif, les dégâts et l'allocation.

**Save et dégâts différés** : le roller tire le `save_roll` BRUT mais ne compare pas la
save et ne tire pas les dégâts — les deux sont différés à l'allocation, par figurine
choisie (la save effective dépend de la figurine allouée : `def save_threshold` gère
armure + invulnérable + AP ; `def wound_threshold` est le seuil de blessure unique,
jumeau de `def _calculate_wound_target` côté mêlée).

**Ordre de résolution et RNG (§C)** : `def resolve_dice_value`
([combat_utils.py](../../../engine/combat_utils.py)) tire `random.randint` à l'appel —
l'ordre de résolution EST l'ordre de tirage des dégâts variables (D3/D6/2D6/D6+x). Tout
réordonnancement du pool change donc les valeurs tirées : c'est **attendu et voulu**
quand l'ordre suit la règle (cf. décision Q.1), ce n'est pas une régression. Une valeur
de dés non supportée lève une erreur explicite (pas de repli silencieux).

---

## 5. Couche allocation des pertes — 05.03 / 05.04

Cœur mutualisé, conforme PDF 05 (vérifié en revue, complété depuis) :

- **Lots** : `def _build_manual_allocation` persiste `game_state[ctx.alloc_key]` sous
  forme de LOTS (cible × profil d'arme) — règle 04.03 IDENTICAL ATTACKS : mêmes
  BS/WS, S, AP, D **et mêmes règles applicables** (les X réellement appliqués des règles
  additives entrent dans la clé de groupe). Chaque lot est résolu indépendamment.
- **Create Groups (05.03)** : `def _build_alloc_groups` — 1 groupe par CHARACTER,
  1 par profil (W, Sv, InSv).
- **Allocation Order (05.04)** : `def apply_manual_shoot_declare_order` (nom historique,
  utilisé par les DEUX phases via ctx) valide les 3 contraintes — non-CHARACTER jamais
  après CHARACTER ; non-CHARACTER blessé d'abord ; CHARACTER blessé avant CHARACTER sain.
- **Select Model** : `def apply_manual_shoot_allocation` — figurine blessée forcée,
  choix restreint au groupe courant (`def _current_live_group`).
- **Ordre du pool** : résolu du **save croissant** (05.04) — décision Q.1, implémentée
  dans le moteur commun (docstring de `_build_manual_allocation` : « groupes + ordre +
  save croissant 05.04 »).
- **Unités attachées (19.02/19.03)** : T la plus haute des bodyguards au wound roll ;
  le CHARACTER attaché est protégé par l'Allocation Order — sauf **[PRECISION] 24.28**,
  qui restreint les figurines cibles allouables (branché dans le moteur d'allocation,
  shared_utils).
- **Application par-figurine** : `def update_model_hp` / `def destroy_model`
  (shared_utils), jamais un pool de PV d'unité.

L'allocation ne rend la main au défenseur (déclaration d'ordre puis choix de figurines)
que s'il est humain ; sinon `auto_decider` tranche headless (§7).

---

## 6. Application des dégâts et caches — invariants fight (§D)

Divergence structurelle identifiée en revue, toujours vraie, résolue par les hooks du ctx :

- `def destroy_model` (shared_utils) ne retire l'unité des pools d'activation que si
  c'est la DERNIÈRE figurine (via `def remove_from_units_cache` →
  `def _remove_unit_from_all_activation_pools`) et **n'invalide jamais**
  `kill_probability_cache` (cache de [weapon_selector.py](../../../engine/ai/weapon_selector.py),
  rempli à la demande).
- La mêlée exige en plus : invalidation du `kill_probability_cache` de la cible à chaque
  blessure, et à la destruction de l'unité le retrait des pools de combat
  (`def _remove_dead_unit_from_fight_pools`) + invalidation complète.

➡️ C'est le rôle des hooks `on_target_damaged` / `on_unit_destroyed` du `ManualAllocCtx` :
`FIGHT_CTX` les branche sur `def _fight_on_target_damaged` (→
`def invalidate_cache_for_target`) et `def _fight_on_unit_destroyed` (→
`_remove_dead_unit_from_fight_pools` + `def invalidate_cache_for_unit`). `SHOOT_CTX` n'en
a pas besoin (comportement tir pur). **Invariant** : toute nouvelle voie d'application de
dégâts en mêlée doit passer par ces hooks — appliquer des dégâts fight par le chemin tir
nu laisserait caches périmés et unités fantômes dans les pools V11.

---

## 7. Aiguillage humain/machine (§E) et asymétrie attaquant/défenseur (§G)

- **Aiguilleur de phase fight** : `def _is_fight_auto_execution_allowed`
  (fight_handlers) — `False` pour `{pvp, pvp_test}` (strictement manuel : pas
  d'auto-activation, pas d'auto-ciblage, pas d'enchaînement auto), `True` pour
  `{pve, pve_test, endless_duty}` et mode absent ; toute autre valeur lève. C'est le SEUL
  aiguilleur auto/manuel de la phase.
- **Décideur d'allocation** : `def is_programmatic_owner` (shared_utils), source unique
  du prédicat « ce joueur est piloté par la machine » — vrai en gym
  (`gym_training_mode`), sinon `player_types == "ai"`. Branché UNIQUEMENT sur les
  décisions d'allocation/résolution, jamais sur le choix de l'escouade à activer
  (ce choix appartient à l'agent).
- **Asymétrie résorbée** : la revue avait constaté qu'au tir, un défenseur humain ne
  choisissait pas ses pertes quand l'attaquant était l'IA (incohérence 05.03, dette
  notée). La convergence sur le moteur unique l'a résorbée : le chemin `squad_shoot`
  de w40k_core rend la main (`waiting_for_player`) quand `build_manual_shoot_allocation`
  rencontre un défenseur humain, et le chemin fight fait de même (allocation manuelle
  des pertes, défenseur humain — §G cité en commentaire de fight_handlers).
- **Reward RL non impacté (§F)** : le reward est calculé dans
  [reward_calculator.py](../../../engine/reward_calculator.py), jamais depuis les
  résultats d'attaque retournés ; `class RewardMapper` (ai/reward_mapper.py) sert à la
  *sélection de cible* (`def _ai_select_fight_target`). Les résultats d'attaque servent
  au logging/affichage.
- **Perf (§N)** : le flux multi-requêtes (round-trips + reconstructions) n'existe qu'en
  PvP humain (basse fréquence) ; le gym reste headless en une passe.

---

## 8. Garde-fous multi-requêtes et cycle de vie des pending (§J, §H)

- **Garde-fou tir** : tant que `pending_shoot_allocation` existe, w40k_core rejette toute
  action hors `squad_shoot_allocate_model` / `squad_shoot_declare_order` et re-signale
  l'attente (`def manual_allocation_waiting_payload`).
- **Garde-fou mêlée (symétrique)** : tant que `pending_fight_allocation` existe, seules
  `squad_fight_declare_order` / `squad_fight_manual_alloc` / `squad_fight_cancel`
  passent — contrôlé à la fois dans w40k_core et en tête de
  `def _fight_v11_manual_step`. Les actions de déclaration cible-d'abord mêlée sont
  traitées DANS la machine V11, donc automatiquement couvertes par ce garde-fou.
- **Annulation** : `squad_shoot_cancel` et `squad_fight_cancel` libèrent le pending.
- **Aucun nettoyage implicite** : `def end_activation` (generic_handlers) ne nettoie PAS
  les pending ; le nettoyage passe par la résolution complète
  (`def _finalize_manual_allocation`) ou l'annulation. Garde-fou anti-leftover :
  `def assert_no_pending_fight_intent` (shared_utils) lève `RuntimeError`.
- **Pas de persistance disque** : le game_state vit en mémoire Flask ; « sérialisation »
  = réponse JSON API (`def _game_state_for_json`,
  [api_server.py](../../../services/api_server.py)). Les clés `pending_*` ne sont pas
  dans `_GAME_STATE_EXCLUDE_KEYS` → elles partent au client : c'est le canal du payload
  d'attente. Pour exclure une clé pending du payload, l'ajouter explicitement.

---

## 9. Couture dans la machine fight V11 (§L)

Séquence PDF 12 : pile-in (étape 2, max 3") → Fight (12.04, alternance, Fights First
d'abord — `def is_fights_first`, un ordre d'**activation**, pas de cible) → consolidation
(étape 4, max 3").

- Sous-phases de la machine : `fight_subphase` ∈ `"pile_in"` → `"fight"` (entrée par
  `def fight_v11_enter_fight_step`) → `"consolidate"`. L'attribution et l'allocation
  vivent dans la sous-phase `"fight"`, dans la MÊME machine multi-requêtes que le
  pile-in par-figurine (`def _fight_pile_in_build_model_pool`).
- Chemin manuel : `def _fight_v11_manual_step` — expose le pool éligible du sélecteur
  courant (`fight_eligible_units` → cercles verts), activation en 2 temps
  (`activate_unit` puis déclaration), puis allocation.
- Chemin auto : `def _fight_v11_auto_step` → `def _fight_v11_resolve_attacks` —
  sélection de cible auto (`def _ai_select_fight_target`, arme via
  `def select_best_melee_weapon` de weapon_selector), puis MÊME moteur : déclaration
  per-figurine (`def squad_declare_fight`, shared_utils) + allocation headless.
- Granularité spatiale : `def unit_entries_within_engagement_zone`
  ([spatial_relations.py](../../../engine/spatial_relations.py)) compare des empreintes
  d'unités ; l'éligibilité par-figurine descend au niveau figurine via les callbacks §3.

---

## 10. Logs — paramétrés par ctx, jamais dupliqués (§I)

`def _emit_squad_shoot_log` (shared_utils, nom historique — sert les deux phases) est
paramétré par le ctx : `log_type` / `log_verb` / `phase_label` (`"shoot"`/`"SHOT"` vs
`"combat"`/`"FOUGHT"`). Le type `"combat"` n'a qu'UN émetteur (`FIGHT_CTX`) — invariant
exploité par w40k_core pour distinguer mêlée et tir dans le post-traitement. Le log
`type:"death"` est émis par le moteur d'allocation quand `emit_unit_death_log` est vrai
(mêlée : parité avec l'ancien chemin auto ; le tir ne l'émet pas). Le frontend distingue
ces types dans [useGameLog.ts](../../../frontend/src/hooks/useGameLog.ts) et
[GameLog.tsx](../../../frontend/src/components/GameLog.tsx).

---

## 11. Frontend — état courant

- **Plan de combat** : prop/état `squadFightPlan`
  ([useEngineAPI.ts](../../../frontend/src/hooks/useEngineAPI.ts),
  [BoardPvp.tsx](../../../frontend/src/components/BoardPvp.tsx)) porte l'attribution
  mêlée côté client (unité active, figurine active), jumeau du mode tir `squadModelShoot`.
- **Handlers d'allocation communs** : `handleAllocateModel` et `handleDeclareOrder`
  (useEngineAPI.ts) servent les deux phases (le payload porte l'action du ctx).
- **Modes PIXI mutuellement exclusifs** : le pile-in (`pileInModelMove`) et l'attribution
  ne se disputent pas les clics — chaque pointerdown est gardé par son mode.
- **Menu d'armes** : `weaponSelectionMenu` (BoardPvp.tsx) couvre tir et mêlée ;
  l'arme de mêlée sélectionnée est portée par `selectedCcWeaponIndex` (miroir de
  `selectedRngWeaponIndex`).
- **Routage clic fight** : [boardClickHandler.ts](../../../frontend/src/utils/boardClickHandler.ts)
  (`attackPreview` : clic gauche cible, clic droit report).

---

## 12. Règles 40K mobilisées

- **PDF 04 §04.02** (WHILE FIGHTING) : cibles = unités *engaged with the model*, nb de
  cibles ≤ A ; encart SPLITTING MELEE ATTACKS. §04.03 IDENTICAL ATTACKS (lots).
- **PDF 05 §05.01–05.04** : séquence Hit → Wound → Save (Create Groups + Allocation
  Order) → Inflict Damage (Select Model). Allocation des pertes par « the opposing
  player », blessés d'abord, CHARACTER en dernier. **Identique tir/mêlée** (seule
  différence : BS vs WS au hit roll). Jet non modifié de 6 = critique, de 1 = échec.
- **PDF 12 §12.02–12.08** : pile-in (max 3", avant Fight) ; Fight (12.04, alternance,
  Fights First d'abord) ; consolidation (max 3", après).
- **PDF 19 §19.02–19.03** : T la plus haute des bodyguards ; CHARACTER attaché protégé
  par l'Allocation Order (sauf Precision).
- **PDF 24** : Sustained/Lethal/Devastating Hits, Anti-X (§24.03), Twin-linked (§24.38),
  Precision (§24.28), Fights First (§24.13), Hazardous (§24.15), Cleave (§24.06),
  Blast (§24.05), Rapid Fire (§24.30).

---

## 13. Décisions datées

### Q.1 — Ordre d'allocation : save croissant (2026-06-14, implémentée)

Le pool d'un lot est résolu du save le plus bas au plus haut (05.04), PAS en ordre
d'attaque — l'ancien ordre était une déviation confirmée, corrigée directement dans le
moteur commun (dette commune tir+mêlée, traitée une fois). Conséquence RNG assumée :
`resolve_dice_value` tirant à l'appel, le tri change les valeurs tirées sur armes à
dégâts variables — attendu et voulu (on suit la règle), pas une régression.

### Q.2 — Cover −1 BS (dette TIR identifiée en revue, livrée depuis)

Règle 13.08 : Benefit of Cover = −1 BS, ranged only, niveau unité tout-ou-rien — donc
inexistant en mêlée, la couche allocation n'a rien à gérer. La revue avait constaté que
l'effet n'était pas appliqué au hit roll ; il l'est désormais (`def _cover_worsened_bs`,
shared_utils — plafond : un 6 naturel touche toujours, 05.01), consommé par le roller tir.

### Q.3 — Hidden 13.09 : visibilité par-modèle, décision B2 (actée puis livrée)

Un modèle *hidden* n'est visible qu'aux modèles ennemis à ≤ 15" (détection). Décision B2 :
filtrage par-modèle en amont du ciblage, du cover et du ratio `fully_visible`, la
géométrie LoS restant unité→unité (13.09 = distance, pas ligne de vue — ne PAS recalculer
la LoS par tireur). Implémentation : `def compute_hidden_statuses`,
`def hidden_enemy_out_of_detection`, `def preview_hidden_models_from_position`
([shooting_handlers.py](../../../engine/phase_handlers/shooting_handlers.py)).
**Invariant de config à préserver** : toute terrain area marquée `obscuring` contient au
moins une *dense feature* — `def hexes_in_obscuring_terrain`
([terrain_utils.py](../../../engine/terrain_utils.py)) teste le flag `obscuring` comme
proxy de « dense » pour 13.09 ; une zone obscuring *light-only* déclencherait `hidden` à
tort, sans erreur visible.

### Verdict de revue (2026-06-14) — NO-GO initial, GO sur l'approche en couches

La proposition initiale est refusée pour trois défauts disqualifiants : elle ciblait le
système V10 (code mort, supprimé depuis) ; réutiliser la résolution du manuel tir aurait
perdu les rerolls de combat (§B) ; le chemin d'application dégâts du tir nu aurait cassé
les invalidations de cache fight (§D). Le GO porte sur : généraliser par ctx UNIQUEMENT
l'allocation des pertes ; garder une résolution mêlée propre (rerolls) ; greffer sur la
machine V11 (`_fight_v11_manual_step`) ; isolation gym via
`_is_fight_auto_execution_allowed` ; `squad_fight_cancel` + garde-fou
`pending_fight_allocation` ; application dégâts via le chemin fight avec invalidations ;
logs paramétrés. Toutes ces conditions sont dans le code aujourd'hui (sections 5–10).

---

## Historique et sources

Ce document absorbe `Documentation/Reference/moteur/refactor_attack_shoot_fight1.md`
(413 lignes) : la revue critique pré-implémentation du refactor « attribution/allocation
manuelle COMBAT, miroir du TIR » (2026-06-14), son verdict (§P), ses décisions (§Q) et
ses dettes différées (§R). L'implémentation s'est faite en tranches verticales
(backend + frontend validées ensemble en PvP), puis le chantier « fight cible-d'abord /
attribution par arme » et la convergence V11 ont unifié les chemins auto et manuel sur le
moteur décrit ici. Les constats d'époque périmés (code mort V10, symboles renommés,
dettes depuis livrées) ont été purgés ou corrigés lors de la consolidation (2026-08-28) ;
l'état des chantiers restants se lit dans `Documentation/Roadmap/`, jamais ici.

## Correspondance des sources

| Source | Ancien § | Section actuelle |
|---|---|---|
| refactor_attack_shoot_fight1.md | §0 (code mort V10) | Historique et sources ; §13 (verdict) |
| refactor_attack_shoot_fight1.md | §A (généralisation par ctx) | §1, §3, §5 |
| refactor_attack_shoot_fight1.md | §B (parité rerolls) | §4 « Couche résolution — parité rerolls (§B) » |
| refactor_attack_shoot_fight1.md | §C (ordre RNG) | §4 (fin) ; principe « règle > historique » en §2 |
| refactor_attack_shoot_fight1.md | §D (dégâts & caches) | §6 « Application des dégâts et caches (§D) » |
| refactor_attack_shoot_fight1.md | §E (IA/gym) | §7 (aiguillage) |
| refactor_attack_shoot_fight1.md | §F (reward) | §7 (note reward) |
| refactor_attack_shoot_fight1.md | §G (asymétrie) | §7 (asymétrie résorbée) |
| refactor_attack_shoot_fight1.md | §H (persistence/reset) | §8 |
| refactor_attack_shoot_fight1.md | §I (logs) | §10 « Logs (§I) » |
| refactor_attack_shoot_fight1.md | §J (garde-fou multi-requêtes) | §8 |
| refactor_attack_shoot_fight1.md | §K (granularité règles) | §3, §12 |
| refactor_attack_shoot_fight1.md | §L (pile-in/consolidation) | §9 |
| refactor_attack_shoot_fight1.md | §M (frontend) | §11 |
| refactor_attack_shoot_fight1.md | §N (perf) | §7 (note perf) |
| refactor_attack_shoot_fight1.md | §O (deux couches) | §2 « Décision fondatrice (§O) » |
| refactor_attack_shoot_fight1.md | §P / §P-bis (verdict & plan) | §13 (verdict) ; Historique et sources |
| refactor_attack_shoot_fight1.md | §Q.1 / §Q.2 / §Q.3 | §13 (décisions datées) |
| refactor_attack_shoot_fight1.md | §R (dettes différées) | §3 (R.1, livré) ; §13 Q.2/Q.3 (R.2/R.3) |
| refactor_attack_shoot_fight1.md | Annexe (citations règles) | §12 |
