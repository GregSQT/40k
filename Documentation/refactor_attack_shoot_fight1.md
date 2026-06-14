# Refactor — Attribution / allocation manuelle COMBAT (miroir du TIR)

> Revue critique pré-implémentation. Tous les `fichier:ligne` ont été vérifiés dans le
> code au moment de la rédaction. Source de vérité règles : `Documentation/40k_rules/`.
> **Verdict global : NO-GO sur la proposition initiale — GO conditionnel sur l'approche recadrée (§ O/P).**

---

## 0. Constat bloquant — la proposition cible du CODE MORT

Il existe **deux** systèmes de combat dans `engine/phase_handlers/fight_handlers.py` :

- **V10 = DÉPRÉCIÉ, non atteint.**
  - `_handle_fight_attack` (la « boucle while auto » de la proposition), `_handle_fight_unit_activation`,
    dispatcher `_execute_action_v10_unused` (fight_handlers.py:2105, docstring `[DÉPRÉCIÉ V10 — code mort]`).
  - Vérifié : ces fonctions ne sont appelées QUE depuis le dispatcher `_unused`.
- **V11 = ACTIF.**
  - Entrée réelle `execute_action` (fight_handlers.py:6074-6090) → `_fight_v11_auto_step` (4937)
    / `_fight_v11_manual_step` (5922-6071).
  - Vraie boucle auto : `_fight_v11_resolve_attacks` (4835-4848).

**Conséquences :**
1. Points 5 et 6 de la proposition (« garder / reproduire `_handle_fight_attack` ») reposent sur du code mort.
   Le gym passe par `_fight_v11_auto_step`, pas par la boucle while V10.
2. **Un chemin manuel fight existe DÉJÀ** : `_fight_v11_manual_step` gère le pile-in par-figurine
   et la sélection de cible — mais la **résolution des attaques y est encore auto**
   (arme auto `select_best_melee_weapon` 4828, recible auto `_ai_select_fight_target` 4840, fight_handlers.py:6057).
   C'est exactement et seulement ce manque que le refactor doit combler.

➡️ **Tout le plan doit être recadré sur V11. Le point d'insertion est `_fight_v11_manual_step`, pas une copie du shoot.**

---

## A. Généralisation par ctx — correcte mais incomplète

Le ctx `{weapons_attr, selected_idx_attr, attacks_left_attr, intents_key, alloc_key, labels, can_target}`
couvre **tout le nominal** du moteur d'allocation manuel shoot (RNG_WEAPONS, SHOOT_LEFT,
selectedRngWeaponIndex, clés pending, labels — tous renommables ;
shared_utils.py:4536 / 4923 / 3940 …).

Spécificités tir confirmées :
- **Éligibilité portée+LoS** (`_model_can_shoot_target` 3803, `_attacker_model_can_reach_squad`,
  `range_subhex` 3797) : non réutilisable → callback `can_target` obligatoire. ✅ prévu.
- **BLAST** (`_has_blast_keyword` 4263, bonus 4552 / 4937) : inerte en combat, pas bloquant.
- **cover / IGNORES_COVER / rapid fire** : **absents** du fichier — rien à généraliser.
- **`_emit_squad_shoot_log`** hardcodé `type:"shoot"` / `phase:"shoot"` / verbe `"SHOT"`
  (shared_utils.py:4411 / 4416 / 4419). **Champ ctx manquant** → ajouter `log_type` / `log_verb` / `phase_label` (cf. I).

⚠️ Le ctx ne réconcilie PAS la divergence de modèle de données : moteur manuel shoot = **par-figurine**
(`destroy_model`) ; combat = **par-unité** (HP cache). Ce n'est pas un champ, c'est un modèle divergent (cf. D).

---

## B. Parité règles / abilities — PERTE CRITIQUE CONFIRMÉE

Le moteur manuel shoot (`_manual_roll_intent` 4895, `_resolve_one_manual_wound` 5026) ne gère
**AUCUN reroll ni ability** (la seule occurrence « re-roll » 4543 = re-roll du *nombre d'attaques* NB).

`_execute_fight_attack_sequence` (fight_handlers.py:3565-3946) gère :

| Ability | fight_handlers.py | Étape |
|---|---|---|
| `reroll_1_tohit_fight` | 3611-3624 | hit roll == 1 |
| `reroll_towound_target_on_objective` | 3647-3665 | wound échoué, cible sur objectif |
| `reroll_1_towound` | 3666-3675 | wound roll == 1 |
| `reroll_1_save_fight` | 3701-3711 | save roll == 1 (sur l'**unité** cible, pas une figurine) |
| `_tutorial_fight_lethal_save_prevented` | 3720-3728 | scénario tuto |

➡️ **Réutiliser le moteur manuel shoot tel quel = perte de ces 4 rerolls en combat. Rédhibitoire.**

- **Pré-tirage des saves** : `save_roll` tiré d'avance (shared_utils.py:4972), comparé à l'allocation
  (`_resolve_one_manual_wound` 5047). En combat le save est **unité-level**
  (`reroll_1_save_fight` testé sur `target` entier, fight_handlers.py:3701/3712) → ne dépend pas
  de la figurine, conflit pré-tirage moindre que craint, mais re-tirage du save à gérer.
- **Seuils équivalents (OK)** : `wound_threshold` (shared_utils.py:4229) ≡ `_calculate_wound_target`
  (fight_handlers.py:3989) ; `save_threshold` (shared_utils.py:4249) ≡ `_calculate_save_target`
  (fight_handlers.py:3966). **Différence mineure** : le fight clampe `max(2, min(save,6))` (3986),
  pas le manuel shoot → à aligner.
- **Abilities ni auto ni manuel** (PDF 24) : Sustained / Lethal / Devastating Hits, Anti-X, Lance,
  Twin-linked, Precision. Hors scope mais dette à documenter — **Precision (§24.28) touche
  l'allocation des pertes** que le refactor réécrit.

---

## C. Régression iso-RNG sur le tir — gérable, sous conditions strictes

Ordre RNG auto (`resolve_squad_shoot` → `_resolve_shoot_intent_pass1` → `_roll_squad_shot_sequence`,
shared_utils.py:4651 / 4652 / 4464) : NB pré-résolu à la déclaration, puis par attaque strict
**hit(4467) → wound(4473) → save(4479) → dmg(4486)** avec court-circuit. Passe 2 (allocation) déterministe.

Risques wrappers : (1) re-résoudre NB à la résolution décale tout (bug déjà corrigé, commentaire 3863) ;
(2) tout réordonnancement/regroupement d'intents (4651) ou de dégâts (4678) casse la séquence ;
(3) `resolve_dice_value` (dmg) a un `except` qui avale l'exception (4487) — divergence silencieuse possible.

➡️ **Garantie** : wrappers shoot `ctx=SHOOT_CTX` strictement iso-chemin (pas de branche dans le corps chaud),
**validés par `--step` seed-identique avant/après (diff = 0)**. Condition de mise en route #1.

---

## D. Application dégâts & caches — DIVERGENCE STRUCTURELLE (source de bug)

| | Chemin |
|---|---|
| **Manuel shoot** | `_resolve_one_manual_wound` → `destroy_model(reason="combat")` (shared_utils.py:5081) ou `update_model_hp` (5086). **Par-figurine.** |
| **Combat V11** | `update_units_cache_hp` (fight_handlers.py:3765) + `invalidate_cache_for_target` (3773) + si mort `_remove_dead_unit_from_fight_pools` (3782) + `invalidate_cache_for_unit` (3788). **Par-unité.** |

Pièges vérifiés :
- `destroy_model` **ne retire l'unité des pools de combat que si c'est la DERNIÈRE figurine**
  (via `remove_from_units_cache` → `_remove_unit_from_all_activation_pools`, shared_utils.py:2683 / 825).
- `destroy_model` **n'invalide JAMAIS `kill_probability_cache`** (cache dans engine/ai/weapon_selector.py,
  jamais touché par destroy / update_model_hp / update_units_cache_hp).

➡️ Si le combat manuel emprunte le chemin shoot (`destroy_model`) : **kill_probability_cache périmé**
+ **pas de `_remove_dead_unit_from_fight_pools`** → caches sales + unités fantômes dans les pools V11.
**Le chemin d'application doit être celui du combat** (update_units_cache_hp + invalidations + remove_from_fight_pools),
étendu pour gérer la **destruction par-figurine** (inexistante côté fight). C'est le vrai cœur technique, non couvert par le ctx.

---

## E. IA / gym — pas de `resolve_squad_fight` nécessaire ; isoler le gym

`_is_fight_auto_execution_allowed` (fight_handlers.py:82-100) : `False` pour `{pvp,pvp_test}`,
`True` pour `{pve,pve_test,endless_duty}`/None. **Seul aiguilleur auto/manuel** (6088).
Le gym (pve/pve_test) passe par `_fight_v11_auto_step` → `_fight_v11_resolve_attacks` (boucle 4835).
`gym_training_mode` n'intervient PAS dans cet aiguillage.

➡️ **Pas besoin de `resolve_squad_fight`** : la boucle V11 auto suffit pour l'IA/gym (point 4 à supprimer du plan).
**Condition** : ne brancher le manuel que sur `_is_fight_auto_execution_allowed == False` (PvP).

---

## F. Reward shaping — pas de risque

`_execute_fight_attack_sequence` retourne un dict structuré (fight_handlers.py:3928-3946) agrégé en
`all_attack_results`. **Aucun RewardMapper ne consomme ce retour** : reward RL calculé ailleurs
(reward_calculator.py) ; `RewardMapper` sert à la *sélection de cible* (`_ai_select_fight_target` 1972).
`all_attack_results` consommé par w40k_core.py pour **logging/affichage** uniquement.
➡️ Tant que le chemin **auto** V11 reste inchangé, **reward non impacté**. ✅

---

## G. Asymétrie attaquant / défenseur — décision produit

Tir : allocation manuelle déclenchée **uniquement** sur `_is_player_human(defender)` (w40k_core.py:4488),
mais atteignable seulement via actions `squad_shoot_*` émises par un attaquant humain. L'IA attaquante
passe par `squad_shoot` (string, 4709) sans branche défenseur.
➡️ En pratique : **allocation manuelle ⟺ attaquant humain ET défenseur humain (PvP)**.
Quand l'IA tire sur un humain, le défenseur humain **ne choisit pas** ses pertes.

4 combinaisons pour le combat :
- **Humain → Humain** (PvP) : attribution + allocation manuelles. ✅ cible.
- **Humain → IA** : attribution manuelle, retrait auto. Cohérent.
- **IA → Humain** : ❓ aujourd'hui en tir le défenseur humain NE choisit PAS
  (incohérence règle 05.03 déjà présente). À trancher : reproduire (iso-comportement) ou corriger (plus lourd).
- **IA vs IA** (gym) : 100% auto. ✅

➡️ Recommandation : reproduire l'asymétrie du tir, noter la dette.

---

## H. Persistence / replay / reset

- **Pas de save/load disque** du game_state (vit en mémoire Flask). Le scénario « sauvegarde au milieu
  d'une allocation » n'existe pas. « Sérialisation » = réponse JSON API (`_game_state_for_json`,
  api_server.py:532). `pending_*` **pas** dans `_GAME_STATE_EXCLUDE_KEYS` → envoyés au client
  (canal du payload waiting). `pending_fight_allocation` sera auto-inclus ; pour l'exclure → l'ajouter
  explicitement (api_server.py:310-356).
- **Replay** (training-only) : whitelist `["move","flee","shoot","charge","charge_fail","combat","wait"]`
  (w40k_core.py:1586). Ni `squad_shoot_*` ni `squad_fight_*` → rien à faire de plus que l'existant.
- **Reset (RISQUE RÉEL)** : `end_activation` **ne nettoie PAS** les pending (generic_handlers.py).
  Nettoyage via `resolve_squad_*` / `_finalize_manual_allocation` (5117) / `squad_shoot_cancel`.
  Aucun reset au changement de phase/joueur. Garde-fou `assert_no_pending_fight_intent`
  (shared_utils.py:3640) lève `RuntimeError` si leftover.
  ➡️ **Manque un `squad_fight_cancel`** (équivalent `squad_shoot_cancel` 4473). Condition de mise en route.

---

## I. Logs — paramétrer, ne pas dupliquer

`_emit_squad_shoot_log` (shared_utils.py:4386) hardcode `type:"shoot"` / `phase:"shoot"` / `"SHOT"`.
Le combat émet `type:"combat"` / `phase:"fight"` / `"FOUGHT"` (fight_handlers.py:3841) + `type:"death"`
séparé (3887) + `roll_info` NB (149). Le frontend attend un `type` distinct (gameLogStructure.ts).
➡️ Paramétrer `type/phase/verbe` via le ctx (`labels`) et **prévoir le `type:"death"`** que le manuel shoot n'émet pas.

---

## J. Cohérence multi-requêtes — garde-fou à dupliquer

Garde-fou tir : w40k_core.py:2771-2778 — tant que `pending_shoot_allocation` existe, toute action
≠ `squad_shoot_allocate_model` / `squad_shoot_declare_order` est rejetée et re-signale l'attente
(`manual_allocation_waiting_payload`, shared_utils.py:5354). **Aucun équivalent fight.**
➡️ Créer : test symétrique `pending_fight_allocation` + whitelist `squad_fight_*` + waiting payload fight.
Valider en `--step` qu'aucune action ne s'intercale pendant l'allocation.

---

## K. Règles combat (PDF 12 + 04 + 05) — granularité par-figurine CONFIRMÉE

- **Sélection cible par-figurine, multi-cibles** : PDF 04 §04.02 *« Each target must be engaged with
  the model that has that weapon. You cannot select more targets than that weapon's A characteristic. »*
  + encart SPLITTING MELEE ATTACKS. ➡️ `_model_can_fight_target` par-figurine sur engagement est la
  **bonne granularité** (le pool unité `_fight_build_valid_target_pool` fight_handlers.py:2912 est insuffisant).
- **Condition** = engagement de la **figurine attaquante** avec la cible. La formulation « base contact
  avec un ami lui-même en engagement » de la proposition **n'existe pas** dans les règles → à retirer.
- **Pas de priorité de cible** en combat (contrairement au tir). ✅ simplifie.
- **Allocation des pertes IDENTIQUE tir/combat** : PDF 05 §05.03/05.04 invoqué pareil par les deux phases
  → seule partie du manuel shoot vraiment mutualisable (groupes par W/Sv/InSv, blessés d'abord, CHARACTER en dernier).
- Granularité : `unit_entries_within_engagement_zone` (spatial_relations.py:124) compare empreintes
  d'unités ; le par-figurine devra descendre au niveau figurine (le pile-in V11 le fait déjà :
  `_fight_pile_in_build_model_pool`, models_cache).
- Fights First (PDF 12 §12.04) = ordre d'**activation**, pas de cible (`is_fights_first` fight_handlers.py:4048).

---

## L. Pile-in / consolidation — coexistence OK, recadrer sur V11

Couture « pile-in AVANT / attribution / résolution / consolidation APRÈS » conceptuellement correcte
(PDF 12 : pile-in = étape 2 avant Fight ; conso = étape 4 après). Mais :
- Pile-in par-figurine **existe déjà en V11** (`_fight_v11_manual_step` sub `"pile_in"`,
  fight_handlers.py:5938-6042 : plan_state/autoplace/commit, multi-requêtes). La nouvelle attribution
  s'insère dans la **même** machine, sous-phase `"fight"` (après `fight_v11_enter_fight_step` 4636).
  ➡️ Pas besoin de réinventer la fin d'activation V10 (point 6 obsolète).
- Frontend : pile-in = mode `pileInModelMove`, attribution = mode `squadModelFight`. Modes mutuellement
  exclusifs → pas de conflit de clic si chaque pointerdown est gardé par son `mode` (cf. `squadModelShoot` BoardPvp.tsx:3846).

---

## M. Frontend — duplication ciblée, conflits faibles

- **Double-clic en phase fight : inexistant** (gardé `phase==="move"`, boardClickHandler.ts:238,
  BoardPvp.tsx:3188) → conflit faible. **Mais** le clic fight actuel (`attackPreview`,
  boardClickHandler.ts:189-203) résout une attaque immédiatement → le mode `squadModelFight` doit **remplacer** ce routage.
- **À dupliquer** (useEngineAPI.ts) : `squadFightPlan` (state/ref/session/guard, miroir 620-638),
  `deriveFightTargets` (←444), 8 handlers `*Fight*` (← selectShootModelForUnit 4011, handleStartSquadModelShoot 4124,
  handleSelectModelForShoot 4169, handleAssignShootTarget 4179, handleAutoAssignAllModels 4238,
  handleUnassign 4292, handleCommit 4329, handleCancel 4355). Blink réutilisable tel quel.
- **Réutilisables avec ajout léger** : `handleAllocateModel` (4376, switch sur `alloc.kind` → ajouter `"fight"`
  au type ligne 393 + branche), `handleDeclareOrder` (4425). Overlay PIXI d'allocation (BoardPvp.tsx:3933-3999)
  **rendu générique**, mais **armement spécifique shoot** (`squad_shoot_manual_alloc` 1641,
  `squad_shoot_declare_order` 1618) → ajouter branches fight.
- **Menu d'armes CC : ABSENT** (`selectedCcWeaponIndex` n'existe que comme donnée d'affichage). À créer sur
  le modèle RNG (`weaponSelectionMenu` BoardPvp.tsx:1278, action `squad_select_weapon` 8359) lisant `CC_WEAPONS`.
- Pointerdown `squadModelFight` à créer (miroir BoardPvp.tsx:3717-3928) + rendu intents fight (miroir 6992-7010).

---

## N. Perf — surveiller, chemin chaud rapide

`perf_timing` instrumenté dans `_execute_fight_attack_sequence` (chemin kill, fight_handlers.py:3753-3926).
Le multi-requêtes ajoute round-trips + reconstructions de pools/caches — **mais uniquement en PvP humain**
(basse fréquence). Le gym/IA reste sur la boucle V11 auto rapide (E).
➡️ Impact acceptable **si** `_is_fight_auto_execution_allowed` isole le manuel du gym. Pas de régression training.

---

## O. Alternative recommandée — séparer 2 couches

La « généralisation par ctx du moteur **manuel** » a un défaut fatal (B) : le manuel shoot n'a aucune
ability → le combat les perdrait. Mieux :

1. **Couche résolution des jets** (hit/wound/save/dmg + abilities) : réutiliser
   **`_execute_fight_attack_sequence`** (déjà rerolls + bonnes invalidations de cache D), rendu capable
   de résoudre une **attaque attribuée** (cible/arme imposées) au lieu d'auto-sélectionner.
2. **Couche attribution + allocation des pertes** (§05.03/05.04, identique tir/combat) : **là** la
   généralisation par ctx du moteur manuel shoot est légitime.

➡️ Généraliser **l'allocation** (commun par les règles), **pas la résolution** (où le combat est plus riche).
Greffe sur `_fight_v11_manual_step` (existant). Préférable à la duplication pure (qui dupliquerait une logique règle commune).

---

## P. Verdict & plan

**NO-GO sur la proposition initiale.** Trois défauts disqualifiants :
1. cible le code mort V10 (points 5/6) ;
2. réutiliser le moteur manuel shoot pour la résolution **perd les 4 rerolls de combat** (B) ;
3. le chemin d'application dégâts du shoot (`destroy_model`) **casse les invalidations de cache fight** (D).

**GO conditionnel sur l'approche recadrée (O)** : généraliser par ctx **uniquement la couche allocation
des pertes** ; conserver `_execute_fight_attack_sequence` pour la résolution + abilities ; greffer sur `_fight_v11_manual_step`.

**Conditions bloquantes** :
- iso-RNG tir prouvé en `--step` (C) ;
- isolation gym/manuel via `_is_fight_auto_execution_allowed` (E) ;
- `squad_fight_cancel` + garde-fou `pending_fight_allocation` (H, J) ;
- application dégâts via chemin fight unité→figurine avec invalidations (D) ;
- logs `type:"combat"` + `death` paramétrés (I).

**Plan ordonné (risque croissant, validation `--step` à chaque étape) :**

| # | Étape | Risque | Validation |
|---|---|---|---|
| 1 | Extraire le module d'allocation des pertes en fonction ctx-paramétrée ; brancher shoot via wrapper `SHOOT_CTX` | Nul (tir) | Run tir IA seed-identique, diff résultats = 0 (C) |
| 2 | Backend fight sans frontend : `_model_can_fight_target[_with_weapon]` par-figurine ; `squad_declare_fight_*` ; `pending_fight_allocation` ; `squad_fight_cancel` | Faible | Déclaration/annulation sans crash |
| 3 | Résolution attribuée : adapter `_execute_fight_attack_sequence` (cible/arme imposées) + intégrer le module d'allocation, en gardant update_units_cache_hp + invalidations + remove_from_fight_pools (D) | Élevé | Combat manuel PvP-test, abilities préservées, caches propres |
| 4 | Couture V11 : brancher `squad_fight_*` dans `_fight_v11_manual_step` (sous-phase `fight`, après pile-in) ; garde-fou `pending_fight_allocation` (J) ; fin d'activation via machine V11 | Élevé | pile-in→attribution→résolution→consolidation enchaînés |
| 5 | Frontend : `squadFightPlan` + handlers + mode `squadModelFight` + menu CC + branches allocation fight (M) | Moyen | 3 mécanismes joueur en PvP |
| 6 | Non-régression gym : run training complet | Faible | Iso-comportement IA + reward inchangé (E, F) |

Étapes 1, 2, 6 = risque nul/faible pour tir et training ; le risque se concentre en 3-4.

---

## Annexe — Citations règles utilisées

- **PDF 04 §04.02** (WHILE FIGHTING) : cibles = unités *engaged with the model*, nb cibles ≤ A ; encart SPLITTING MELEE ATTACKS.
- **PDF 05 §05.01-05.04** : séquence Hit → Wound → Save (Create Groups + Allocation Order) → Inflict Damage (Select Model).
  Allocation des pertes par « the opposing player », blessés d'abord, CHARACTER en dernier. **Identique tir/combat** (seule diff : BS vs WS au hit roll).
- **PDF 12 §12.02-12.08** : pile-in (étape 2, max 3", avant Fight) ; Fight (12.04, alternance, Fights First d'abord) ; consolidation (étape 4, max 3").
- **PDF 19 §19.02-19.03** : T la plus haute des bodyguards ; CHARACTER attaché protégé par l'Allocation Order (sauf Precision).
- **PDF 24** : Sustained/Lethal/Devastating Hits, Anti-X (§24.03), Lance (§24.21), Twin-linked (§24.38), Precision (§24.28), Fights First (§24.13).
