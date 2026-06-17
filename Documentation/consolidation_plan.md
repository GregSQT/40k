# Plan d'implémentation — Consolidation par-figurine (Fight phase 12.08)

> Document de spec autonome destiné à un agent frais.
> **Tout est tranché** (y compris les points sensibles §8, désormais décidés). Appliquer les décisions, ne pas les rouvrir. Pour toute ambiguïté **non couverte** par ce doc → demander à l'utilisateur, **ne JAMAIS assumer**.
>
> ⚠️ Les numéros de ligne sont indicatifs (état 2026-06-17). **Re-grep le symbole avant chaque édition**, le fichier bouge.
> Fichier moteur principal : `engine/phase_handlers/fight_handlers.py`.

---

## 1. But

Implémenter la **consolidation** (étape 4 de la Fight phase, règles 12.07/12.08) en mode **PvP manuel par-figurine**, en miroir du **pile-in par-figurine** déjà en place. Aujourd'hui la consolidation est **auto-skippée** en PvP manuel (UI non câblée).

Source de vérité règles : `Documentation/40k_rules/12 Fights pahse.pdf` et `14 Objectives.pdf`. **Lire le PDF avant toute décision de règle** — une réponse règle sans lecture du PDF est invalide.

**Hors scope** : l'overrun fight (12.06) et son pile-in additionnel sont déjà gérés dans l'étape Fight (`_fight_v11_auto_overrun_pile_in`, manuel ~L6442 / auto ~L5083) ; la conso ne les touche pas. Garder à l'esprit que l'overrun **partage le moteur pile-in** — ne pas le casser via la factorisation A (§4).

---

## 2. Contraintes projet (NON négociables)

- **Aucun fallback / workaround / valeur par défaut** pour masquer une erreur. Préférer une **erreur explicite** (`raise`) si une donnée requise manque. Les fallbacks ne sont permis que comme comportement métier voulu, jamais pour contourner un bug.
- **Ne jamais assumer l'état du code** : lire/grep avant d'affirmer. Pas de « devrait / probablement ».
- **Mode B imposé** (cf. §4) : créer des fonctions dédiées, **ne pas modifier le moteur pile-in existant**.
- **Pas de tests automatisés** : validation runtime **manuelle par l'utilisateur en PvP**, à la fin. À chaque tranche backend, se limiter à une validation **compile / lint / import**.
- **Travailler une tranche à la fois**, présenter le diff et **attendre validation** avant la suivante. Si plusieurs fichiers sont touchés → lister et expliquer d'abord.
- Réponses en français, directes, sans récap inutile.

---

## 3. Règles 12.08 — synthèse (validée avec l'utilisateur)

**Éligibilité** : une unité peut consolider si elle **« was eligible to fight this phase »** (= a satisfait 12.04). Move **optionnel**.

**BEFORE MOVING — mode imposé par cascade** (premier applicable) :
1. **Ongoing** — unité **engagée** → sélectionne **toutes** les unités ennemies engagées.
2. **Engaging** — sinon, à **≤3" d'une ou plusieurs unités ennemies** → le joueur **choisit** 1+ de ces unités.
3. **Objective** — sinon, à **≤3" d'un ou plusieurs objectifs** → le joueur **sélectionne un** objectif (« select **one** of those objectives ») : choix joueur si **>1** candidat, auto si **1 seul**.

**WHILE MOVING (par figurine, max 3") — 3 comportements DISTINCTS** :
| Mode | Contrainte WHILE | Verrou base-contact |
|---|---|---|
| **Ongoing** | finir **plus près de l'unité ennemie sélectionnée la plus proche**, engaged si possible | **OUI** — figurines en contact de socle ne bougent pas |
| **Engaging** | finir **plus près de l'unité ennemie sélectionnée la plus proche**, engaged si possible | **NON** (de facto vide : unité non engagée) |
| **Objective** | finir **within range de l'objectif** si possible, **sinon plus près** | **NON** |

> ⚠️ Le verrou base-contact est **Ongoing uniquement**. Le clone du `build_model_pool` doit pouvoir le **désactiver** en Engaging/Objective.

**AFTER MOVING (validité)** :
- **Ongoing** : chaque figurine engagée au départ doit **le rester**.
- **Engaging** : l'unité doit finir **engaged avec TOUTES les unités ennemies qu'ELLE a sélectionnées**. « New Foes to Face » : ennemis nouvellement engagés non encore activés → sélectionnés par l'adversaire et combattent (= « selected to fight » + résolution du combat, **sans relance de l'alternance** — cf. §8.C).
- **Objective** : l'unité doit finir **within range** de l'objectif (≥1 figurine dans la zone).

**Définition objectif (TRANCHÉE — 14.01/14.02)** :
- Un **objectif = entrée de terrain `"objective": true`** (`config/board/<board>/terrain/*.json`), polygone (`vertices`).
- **« within range of a terrain objective » = le modèle est DANS la zone du terrain** (14.02 : « while it is within that terrain area »). Pas un rayon autour d'un point central.
- **Distance à un objectif** (déclencheur « ≤3" ») = vers la **partie la plus proche** de la zone (14.01).
- ⇒ Géométrie objectif = **zone multi-hex**, jamais un marqueur ponctuel.

---

## 4. Décisions d'architecture actées

- **Mode B affiné (évite la dette dès le départ)** : écrire le moteur conso **directement comme un moteur générique paramétré** (`lock_base_contact: bool`, `tier_kind ∈ {enemy, zone}`, `after_predicate` par mode) plutôt qu'un clone collé du pile-in → **une seule** copie du cœur de mouvement, pas deux qui divergent. **Ne PAS toucher** au pile-in (il reste sur son ancienne copie jusqu'à sa validation runtime). **Trigger factorisation A** : une fois le **pile-in validé runtime**, le **brancher sur ce moteur générique** (au lieu de fusionner deux clones) — coût marginal quasi nul, risque de drift supprimé.
- **Objectif = notion générique runtime** : la **logique de jeu** ne manipule qu'un objectif `{id, hexes}`. Le lien **objectif ⟺ terrain** est **uniquement** dans le chargement (Tranche 0bis), jamais hard-codé dans la mécanique de conso. **Décidé** : aucun objectif **hors-terrain** n'est requis (14.01 « Objectives Not Within a Terrain Area » non utilisé) → **pas de voie d'authoring** à préserver, source **unique** = terrains. La généricité runtime est gardée par **propreté/découplage**, pas pour un besoin futur.
- **Objectifs = terrains `"objective": true` (NOUVELLE RÈGLE du projet, remplace l'ancien système).** L'ancien système (objectifs-disques aléatoires du scénario via `objectives_ref` / `objectives-*.json`) **n'existe plus** et est **supprimé** — il ne doit ni être maintenu, ni servir à entraîner l'IA (entraîner sur des objectifs abstraits ≠ terrains visibles = mauvais entraînement). Le champ runtime `game_state["objectives"]` est **conservé** (format `{id, hexes}`, 10 consommateurs) mais **re-sourcé** depuis les terrains au chargement. `center` peut être omis (fallback centroïde des `hexes` côté `macro_intents`/`action_decoder`). ⚠️ L'IA observe désormais les **vrais** objectifs (terrains) → modèles `ai/models/*.zip` à **ré-entraîner** sur la nouvelle règle (voulu, pas un coût).
- **Cohérence IA/PvP** : le chemin IA/auto de la conso objectif doit jouer la **même** règle que le PvP (viser la **zone**, pas un marqueur central) → cf. Tranche 6.
- **`pile_in_autoplace_plan` (ILP) NON cloné**.
- **Ordre** : Tranche 0bis (objectifs, **prérequis validé isolément** — ne pas coupler une régression objectif à une régression conso) → 1 → 2 → 3 → 4 backend → 6 (alignement IA) ; puis 5 front.

---

## 5. État actuel du code (vérifié)

### Déjà fait — Tranche 0 (pré-requis éligibilité, NE PAS refaire)
- **Skip fight gardé** dans `_fight_v11_manual_step` (`sub == "fight"`, `if skip:`) : right_click marque l'unité active `units_selected_to_fight` + `units_fought` **uniquement si aucune cible valide**, sinon skip refusé.
- **Front** : `useEngineAPI.ts` — unité fight active **sans cible** entre quand même en `attackPreview` → clic droit → skip possible.
- **Conséquence** : `units_selected_to_fight` complet en entrée de consolidate ⇒ **`fight_v11_is_consolidation_eligible` (~L4509) correct, INCHANGÉ** (vivante + `units_selected_to_fight`).
- **Invariant à asserter (testable)** : en fin d'étape Fight, **{unités vivantes éligibles 12.04} ⊆ `units_selected_to_fight`**. Le proxy « selected » couvre « was eligible to fight » grâce au snapshot `engaged_at_fight_step_start` (~L4553) + le skip fight (Tranche 0). Sans cette assertion, une unité éligible non sélectionnée perdrait **silencieusement** son droit de consolider.

### Briques existantes réutilisables
- `fight_v11_consolidation_mode` (~L4684) → cascade 12.08 `"ongoing"|"engaging"|"objective"|None`. **Utiliser tel quel.**
- `fight_v11_engaging_triggered_unit_ids` (~L4703) → ennemis engagés post-move non sélectionnés (New Foes).
- `_fight_v11_objective_hex_sets` (~L4641) → `(id, set hexes)` par objectif (zone de contrôle runtime). **Source objectif pour la conso** (après Tranche 0bis qui la remplit depuis les terrains).
- `_fight_v11_objectives_within_range` (~L4663) → objectifs à portée (distance empreinte→zone).
- `min_distance_between_sets` (hex_utils) → distance empreinte→zone objectif.
- `_fight_bfs_reachable_anchors_consolidation` (~L1166) → BFS 3" par unité (agnostique).
- `_fight_apply_pile_in_move` (~L883, `log_label` paramétré), `_fight_synth_cache_entry_at_footprint` (~L953), `_fight_footprint_in_engagement_with_any_enemy` (~L973).
- `polygon_to_hex_list` (hex_utils.py:586), `_objective_polygon_hexes` (hex_utils.py:546) → rasterisation polygone→hexes (pour Tranche 0bis).

### ⚠️ Code à NE PAS réutiliser pour la branche objectif
- `_fight_plan_consolidation_destinations` (~L1255) : consolidation **par-UNITÉ** (pas par-figurine). **Sa branche `objective` est NON CONFORME** : elle vise le **marqueur central** (médiode/centre) via `_fight_resolve_objective_marker_center_hex` + `on_marker`, alors que 14.02 demande d'être **dans la zone**. → À corriger/remplacer, **PAS un modèle de référence pour l'objectif**.
  - Sa branche **`enemy`** reste valable comme référence de palier ennemi.
  - **Attention appelants** : utilisée par le flux **IA/auto** (`_ai_select_consolidation_destination`, `_fight_try_begin_consolidation_after_attacks`). Sa branche `objective` est **corrigée en Tranche 6** (viser la zone, comme le PvP) — préserver le flux auto.
- Helpers **marqueur** — **écartés pour la branche objectif** (ponctuels, non conformes 14.02) : `_fight_resolve_objective_marker_center_hex` (~L1068), `_fight_closest_objective_marker_snapshot` (~L1111), `_fight_new_fp_strictly_closer_to_objective_marker_tier` (~L1133). Pour l'objectif, utiliser **`_fight_v11_objective_hex_sets` (zone) + `min_distance_between_sets`** à la place.

### Points de branchement à modifier (actuellement auto-skip)
- `_fight_v11_manual_state`, `sub == "consolidate"` (~L6055-6064) → présentation paresseuse.
- Dispatch `_fight_v11_manual_step`, `sub == "consolidate"` (~L6475-6480) → dispatch des actions.

### Référence pile-in par-figurine (à CLONER, ne pas modifier)
- `_fight_pile_in_build_model_pool` (~L5104) — BFS par figurine, palier `closest_tier_ids: List[str]`. Retour `{"closer":[...], "engaged":[...]}`.
- `_fight_pile_in_closest_tier_ids` (~L5242) — **générique, réutiliser** (palier ennemi).
- `_fight_pile_in_preview_plan` (~L5271), `_fight_pile_in_model_plan_state` (~L5386), `_fight_pile_in_commit_plan` (~L5486).
- `_fight_v11_pile_in_targets` (~L5932), `_fight_v11_clear_pile_in_preview` (~L5939).
- Dispatch actions pile-in (`sub == "pile_in"`) : `pile_in_plan_state` (~L6286), `pile_in_autoplace` (~L6298), `commit_pile_in_plan` (~L6309), `activate_unit` (~L6340). **Miroir exact à reproduire pour consolidate.**

---

## 6. Matrice de réutilisabilité

| Élément | Statut |
|---|---|
| `_fight_pile_in_closest_tier_ids` | **Réutiliser** (palier ennemi) |
| `_fight_apply_pile_in_move`, `_fight_synth_cache_entry_at_footprint`, `_fight_footprint_in_engagement_with_any_enemy` | **Réutiliser** |
| `_fight_v11_objective_hex_sets`, `_fight_v11_objectives_within_range`, `min_distance_between_sets` | **Réutiliser** (branche objectif = ZONE) |
| `polygon_to_hex_list`, `_objective_polygon_hexes` | **Réutiliser** (Tranche 0bis) |
| `fight_v11_consolidation_mode`, `fight_v11_engaging_triggered_unit_ids`, `fight_v11_is_consolidation_eligible` | **Réutiliser** (déjà bons) |
| `_fight_pile_in_build_model_pool` | **Référence de structure (NE PAS cloner-coller)** → réécrire en moteur générique paramétré (`lock_base_contact`, `tier_kind`, 3 sémantiques WHILE), cf. §4/Tranche 2 |
| `_fight_pile_in_preview_plan` | **Référence de structure (NE PAS cloner-coller)** → moteur générique, `after_predicate` par mode |
| `_fight_pile_in_model_plan_state` | **Référence de structure (NE PAS cloner-coller)** → état UI générique, cibles via `_fight_v11_consolidation_targets` |
| `_fight_pile_in_commit_plan` | **Cloner (trivial conseillé)** — sa signature n'a pas de type/label ; un `_fight_consolidation_commit_plan` (type/log `consolidation`) respecte le mode B. Optionnel, pas un bug. |
| `_fight_v11_pile_in_targets` | **Créer** `_fight_v11_consolidation_targets` |
| `_fight_v11_clear_pile_in_preview` | **Créer** `_fight_v11_clear_consolidation_preview` |
| Helpers **marqueur** (`_fight_resolve_objective_marker_center_hex`, `_fight_closest_objective_marker_snapshot`, `_fight_new_fp_strictly_closer_to_objective_marker_tier`) | **Écarter** pour la branche objectif (non conformes 14.02) |
| `_fight_plan_consolidation_destinations` (branche objectif) | **Non conforme → corriger/remplacer** (attention appelants IA/auto) |
| `pile_in_autoplace_plan` | **Exclu** |

---

## 7. Plan en tranches

### Tranche 0bis — Objectifs = terrains (backend, PRÉREQUIS, **validé isolément AVANT le reste**)
Refonte du système d'objectifs. ⛔ **GATE DUR** : cette tranche est un **lot livré et validé runtime SÉPARÉMENT**, **avant d'écrire la moindre ligne de conso** (elle touche scoring, observation IA et reward → tout le jeu). Ne pas démarrer la Tranche 1 tant que la 0bis n'est pas validée runtime. **Étapes ordonnées** :

1. **Propager le flag `objective`** dans la rasterisation des terrains. Aujourd'hui [`_load_terrain_areas_from_ref` ~L1343-1348](engine/game_state.py#L1343) produit `{id, obscuring, polygon_vertices, hexes}` **sans** le flag, et `objective:true` n'est lu **nulle part** ailleurs → impossible de filtrer. Ajouter `"objective": bool(area.get("objective", False))` au dict rasterisé.
2. **Construire `game_state["objectives"]`** depuis `terrain_areas` **filtrés sur `objective == True`** : pour chacun → `{"id": area["id"], "hexes": area["hexes"]}` (hexes déjà rasterisés à l'étape 1). `center` **omis** — fallback centroïde **légitime** (le centroïde EST le centre réel d'une zone ; `raise` si ni `center` ni `hexes`), cf. [`get_objective_center`](engine/macro_intents.py#L23) / `_get_objective_centers`.
3. **Câbler `terrain_ref`** dans les scénarios concernés, **en remplacement de `objectives_ref`**. `terrain_ref` est chargé conditionnellement → un scénario sans lui a `terrain_areas = []` → **zéro objectif**. Vérifier chaque scénario (ex. `scenario_pvp_test.json` a déjà `terrain-mc1.json` ; un scénario qui n'a que `objectives_ref`, ex. `scenario_pvp_test_fight.json`, doit recevoir un `terrain_ref`).
4. **Supprimer l'ancien système — TOUTES les sources, pas seulement `objectives_ref`.** ⚠️ `game_state["objectives"]` est aussi alimenté par des **cascades de fallback** dans [w40k_core.py](engine/w40k_core.py) (interdites CLAUDE.md), à énumérer et neutraliser : **~L278-286** (`scenario_result["objectives"]` → `board_config["objectives"]`/`["objective_hexes"]`/`default`), **~L568** (`_scenario_objectives` → `board["default"]["objectives"]` → `board["objectives"]` → `[]`), **~L5589-5638** (même cascade au reload scénario). Si une seule survit, l'ancien système se réactive silencieusement. Supprimer aussi : `objectives_ref` (dont `"random"` ~L1353) et fichiers `objectives-*.json`. La source devient **unique** : les terrains `objective:true`.
5. **Vérification** : confirmer que les 10 consommateurs (`macro_intents`, `action_decoder`, `observation_builder`, `reward_calculator`, `movement_handlers`, `shooting_handlers`, `fight_handlers`, `w40k_core`, `api_server`, `game_state`) ne lisent que `id`/`hexes` (+ `center` via fallback). Champ requis manquant → `raise`, pas de défaut silencieux.

**Critère** : `game_state["objectives"]` reflète les terrains `objective:true` du board chargé ; aucun consommateur ne casse (import + lancement) ; ancien système retiré. ⚠️ Modèles RL à ré-entraîner ensuite (hors scope de cette tranche).

### Tranche 1 — Cibles & palier (backend)
**Créer** `_fight_v11_consolidation_targets(game_state, unit) -> Tuple[str, Any]` via `fight_v11_consolidation_mode` :
- `ongoing` → tier = IDs **toutes** les unités ennemies engagées (imposé) ;
- `engaging` → tier = IDs ennemis **sélectionnés par le joueur** (lus depuis l'état `consolidation_engaging_selection`, cf. §B). Si la sélection est vide → pas de move encore possible (le joueur doit d'abord sélectionner) ;
- `objective` → tier = **set d'hexes de la zone** de l'objectif **sélectionné par le joueur** (`consolidation_objective_selection`). Si **>1** candidat et aucun choisi → pas de move encore (attendre la sélection) ; si **1 seul** candidat → auto-sélectionné.
Exposer aussi : `_fight_v11_consolidation_engaging_candidates(game_state, unit)` → IDs ennemis à ≤3" ; `_fight_v11_consolidation_objective_candidates(game_state, unit)` → IDs objectifs à ≤3" (les sélectionnables).
**Critère** : bon `(mode, tier)` pour les 3 cascades, `raise` si incohérence ; en Engaging/Objective, `tier` reflète exactement la sélection joueur (ou l'auto si 1 seul candidat objectif).

### Tranche 2 — Moteur par-figurine (backend, cœur)
**Écrire un moteur GÉNÉRIQUE paramétré** (cf. §4 : pas un clone collé du pile-in → une seule copie du cœur). Paramètres : `lock_base_contact: bool`, `tier_kind ∈ {enemy, zone}`, `after_predicate`. Fonctions :
- `_fight_consolidation_build_model_pool(...)` — BFS 3" par figurine, **3 sémantiques WHILE** : Ongoing (tier=enemy, engaged si possible, **`lock_base_contact=True`**) ; Engaging (tier=enemy, engaged si possible, `lock_base_contact=False`) ; Objective (tier=zone, **within range sinon plus près**, `lock_base_contact=False`).
- `_fight_consolidation_preview_plan(...)` — **AFTER par mode** : Ongoing = engagements de départ conservés ; Engaging = engaged avec **tous** les ciblés ; Objective = **≥1 figurine dans la zone**. ⚠️ **`can_validate = false` si 0 figurine n'atteint la zone** (Objective) : le « closer if not » du WHILE ne **valide pas** un move — il ne concerne que les figurines qui n'entrent pas alors qu'**au moins une** y entre ; move optionnel → on ne bouge pas. Idem Engaging : `can_validate=false` si pas engaged avec **tous** les sélectionnés.
- `_fight_consolidation_model_plan_state(...)` — état UI, branché sur `_fight_v11_consolidation_targets`.
**Réutiliser (helpers bas-niveau)** : `_fight_pile_in_closest_tier_ids` (enemy) ; `_fight_v11_objective_hex_sets` + `min_distance_between_sets` (zone) ; `_fight_synth_cache_entry_at_footprint` ; clone de `commit_plan`.
**Critère** : `model_plan_state` cohérent ; `preview_plan.can_validate` correct dans les 3 modes, **dont `false` quand la cible (zone/ciblés) est inatteignable**.

### Tranche 3 — Présentation & dispatch (backend)
- Remplacer auto-skip `manual_state` (~L6055) par présentation paresseuse miroir du bloc pile_in (~L5976-6001).
- Remplacer auto-skip dispatch (~L6475) par bloc `if sub == "consolidate":` miroir de `sub == "pile_in"` : `activate_unit`, `consolidation_plan_state`, `commit_consolidation_plan`, `skip`, `end_consolidation`.
- **Mode Engaging** : ajouter l'action `consolidation_select_target` (toggle un ennemi candidat dans `consolidation_engaging_selection` pour l'unité active). Le move par-figurine reste **bloqué tant que la sélection est vide**. Réinitialiser la sélection au changement d'unité active / fin de conso.
- **Mode Objective** : si **>1** objectif candidat, ajouter l'action `consolidation_select_objective` (single-select dans `consolidation_objective_selection`). Move **bloqué tant qu'aucun objectif choisi**. Si **1 seul** candidat → auto-sélectionné, pas d'étape de choix. Réinitialiser au changement d'unité active / fin de conso.
- Créer `_fight_v11_clear_consolidation_preview` (purge **les deux** sélections : `consolidation_engaging_selection` ET `consolidation_objective_selection`) — sinon un objectif choisi reste collé au changement d'unité active / fin de conso.
**Critère** : en PvP, l'étape consolidate présente un pool cliquable et `commit` déplace l'unité (modes ongoing + objective) ; en Engaging, la sélection de cibles précède le move.

### Tranche 4 — Engaging « New Foes to Face » (backend, point délicat)
Au commit `engaging`, récupérer `fight_v11_engaging_triggered_unit_ids(U)` (ennemis engagés avec U non sélectionnés). Les résoudre **un par un, dans l'ordre choisi par l'adversaire** (12.08 « your opponent must select each of those units, one at a time »), sélecteur = adversaire de U, sur un **pool explicite restreint à ces unités** — **PAS** `fight_v11_advance_selection` (qui relance l'alternance 12.04 complète : Fights First, handoff, retour-FF, et ramasse **toutes** les unités éligibles → trop large, cf. §C). Pour chacun : marquer `selected_to_fight`, résoudre son **normal fight** via le **flux d'allocation manuel existant** (`build_manual_fight_allocation` / déclaration / pertes). Liste épuisée → reprendre la conso via `fight_v11_grouped_next`. **Résolution immédiate** (cf. §C). **Isolé en dernier**.
**Invariants à figurer AVANT de coder (testables)** :
- **I1** : une unité consolide **une seule fois** (`consolidation_done`).
- **I2** : un New Foe combat **une seule fois** (`units_selected_to_fight`).
- **I3** : **pas de double bascule** `consolidate↔fight` pour le même commit.
- **I4 (ordre 12.07)** : le joueur actif résout **toutes** ses consolidations (y compris les fights New Foes intercalés) **avant** que l'adversaire commence les siennes.
- **I5 (New Foe → consolidable adverse)** : un New Foe marqué `selected_to_fight` devient éligible à consolider lors de la **sous-phase conso de l'adversaire** (12.07). Vérifier que `fight_v11_grouped_next("consolidate")` côté adversaire le **ramasse bien**, sans violer I4.
**Critère** : un New Foe combat immédiatement (ordre choisi par l'adversaire), la conso reprend sans sauter ni redoubler, et I1-I5 tiennent.

### Tranche 6 — Alignement IA/auto de la conso objectif (backend)
Le chemin IA/auto (`_fight_plan_consolidation_destinations`, par-unité) joue la conso objectif vers le **marqueur central** (non conforme 14.02, et peut rater une conso légale par le bord). **Corriger sa branche `objective` pour viser la ZONE** : utiliser `_fight_v11_objective_hex_sets` + `min_distance_between_sets` (plus proche hex de la zone), comme le PvP. Écarter les helpers marqueur (`_fight_resolve_objective_marker_center_hex`, etc.).
- **Attention appelants** : `_ai_select_consolidation_destination`, `_fight_try_begin_consolidation_after_attacks` — préserver le flux auto.
**Critère** : IA et PvP appliquent la **même** règle objectif (zone) ; pas de régression du flux auto (import + `--step`).

### Tranche 5 — Front (mode `consolidationModelMove`)
Miroir de `pileInModelMove` dans `BoardPvp.tsx` / `useEngineAPI.ts` / `boardClickHandler.ts` : réutilise `activeChargeLikePoolRef`, mask loops, sélection figurine, preview, commit, cancel ; câble `consolidation_plan_state` / `commit_consolidation_plan`.
- **Mode Engaging** : étape de **sélection de cibles** AVANT le move — les ennemis à ≤3" (candidats) sont cliquables (toggle → `consolidation_select_target`), feedback visuel des sélectionnés, puis bascule vers le move par-figurine. Bloquer le commit tant que la sélection est vide ou que l'AFTER (engaged avec tous les sélectionnés) n'est pas satisfait.
- **Mode Objective** : si >1 objectif candidat, étape de **sélection d'objectif** (single-select) AVANT le move — les zones objectifs à ≤3" cliquables → `consolidation_select_objective`, feedback visuel. Si 1 seul candidat → pas d'étape, move direct.
**Critère** : test runtime complet des 3 modes (utilisateur), dont sélection multi-cibles en Engaging.

---

## 8. Points sensibles — TOUS TRANCHÉS (appliquer, ne pas rouvrir)

**A. Définition « within range d'un objectif » — ✅ FERMÉ.**
Objectif = terrain `"objective": true` ; within range = **dans la zone du terrain** (14.02). Source re-sourcée en Tranche 0bis. Plus d'ambiguïté.

**A bis. Sélection de l'objectif quand >1 à portée — ✅ FERMÉ : choix joueur.**
12.08 « select **one** of those objectives » → choix joueur si **>1** candidat (cohérent avec B), **auto** si 1 seul. Pas d'enjeu de correctness (≠ Engaging), enjeu purement tactique. Mécanique : `consolidation_objective_selection` + action `consolidation_select_objective` (single-select).

**B. Sélection en mode Engaging — ✅ FERMÉ : sélection joueur explicite.**
La règle 12.08 Engaging impose que **le joueur choisisse** 1+ ennemis (parmi ceux à ≤3") AVANT le move, et l'AFTER exige d'être engagé avec **tous** les sélectionnés. **Toute auto-sélection est non conforme** : auto-all peut rendre la conso géométriquement impossible (ennemis opposés) alors qu'une sélection ciblée serait légale ; auto-atteignables retire la décision tactique « New Foes to Face » (chaque ennemi sélectionné pourra riposter). → **En mode Engaging, une étape de sélection de cibles précède le move par-figurine.** (Ongoing = tous les engagés, imposé, pas de sélection ; Objective = sélection joueur si >1 candidat, cf. A bis.)

**C. Re-trigger Fight après Engaging — ✅ FERMÉ (résolution CIBLÉE, PAS la machine d'alternance).**
⚠️ **Corrige une approche antérieure.** Ne **PAS** réutiliser `fight_v11_advance_selection` : elle implémente l'alternance 12.04 **entière** (Fights First, handoff, retour-FF) et ramasserait **toutes** les unités éligibles non sélectionnées — alors que 12.08 est étroit : « your opponent must select **each of those units**, one at a time » = **seuls** les ennemis engagés avec U non sélectionnés combattent. Le « (12.04) » du texte renvoie au **bookkeeping** « selected to fight » + résolution du combat, **pas** à une relance de l'étape Fight (on est en Consolidate 12.07).
Mécanisme : au commit `engaging`, prendre `fight_v11_engaging_triggered_unit_ids(U)` ; les résoudre **un par un** (sélecteur = adversaire), chacun marqué `selected_to_fight` puis résolu en **normal fight** via le **flux d'allocation existant**, sur un **pool explicite restreint à ces New Foes**. Puis reprendre la conso (état préservé par `consolidation_done`). **Résolution immédiate** (AFTER du move de U). Risque = orchestration (ne pas sauter/redoubler) → à tester (cf. invariants I1-I5 Tranche 4).

---

## 9. Méthode de travail

1. Lire ce document **et** les PDF `12 Fights pahse.pdf` + `14 Objectives.pdf`.
2. Re-grep les symboles cités (les numéros de ligne bougent).
3. Implémenter **une tranche**, présenter le diff (fichier + 1 phrase par changement), valider compile/lint, **attendre l'accord** avant la suivante.
4. Les points sensibles (§8) sont **tranchés** : appliquer les décisions, ne pas les rouvrir. Pour toute ambiguïté **non couverte** par ce doc → demander, ne pas assumer.
5. Aucun test runtime intermédiaire : l'utilisateur teste l'ensemble à la fin.
