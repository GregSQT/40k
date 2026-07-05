# Distance / engagement / clearance — contrat spatial final

**Chemin :** `Documentation/TODO/Distance_functions.md`  
**Statut :** référence **TODO unique** pour cartographier le moteur, limiter les régressions et piloter le refactor distance / engagement / clearance.

**Document vivant :** **revue du tableau maître (§4)** à chaque PR qui modifie un symbole listé (mise à jour de la ligne dans le même merge, ou référence explicite vers un test de non-régression qui verrouille le comportement).

**Dernière révision de ce fichier :** 2026-04-30 — notes §4 (¹–⁵), harmonisation **ε** / Board ×10, critères §4 vs **§5**, piège structurel §6 vérifiés.

Ce document **ne remplace pas** `Documentation/AI_TURN.md` ni `Documentation/AI_IMPLEMENTATION.md`. Toute règle joueur visible, ou tout changement d’architecture canonique, doit être porté dans ces documents **après** décision explicite.

**Remplace pour le quotidien :** `Distance_functions11.md` à `Distance_functions33.md`, ainsi que les variantes intermédiaires (`…13.md`, `…23.md`, etc.) — les conserver en archive avec une ligne « **voir `Distance_functions.md`** » pour éviter la maintenance parallèle.

**Note dépôt :** `Documentation/TODO/Distance_functions.md` est désormais la référence de production. Toute spec longue utile au refactor est **ici**.

**Module cible à trancher :** nouveau `engine/spatial_relations.py`, ou extension contrôlée de `engine/hex_utils.py` / `engine/combat_utils.py`, selon les cycles d’imports.

---

## 1. Objectifs

| # | Objectif |
|---|----------|
| 1 | **Séparer** trois sémantiques (**A / B / C**) au lieu d’un mot unique « adjacence ». |
| 2 | **Uniformiser** les règles partagées sans créer un booléen magique unique. |
| 3 | **Migrer par étapes** : fight → éligibilité / tir → charge → move → IA. |
| 4 | **Trancher par écrit** les ambiguïtés : pile-in, lecteurs config, PISTOL / fight, analyzer. |
| 5 | **Conserver** les inégalités, **ε** (clearance, typ. `1e-6`) et comportements actuels jusqu’à décision gameplay documentée. |

**Règles de migration :** conserver **strictement** les mêmes inégalités et epsilon jusqu’à décision documentée ; tout alias déprécié doit rester **visible** (commentaire ou log de migration), **pas** de dépréciation silencieuse.

**Lecture conseillée avant PR :** §2.2 (définitions opérationnelles) → **§9** (pièges) → **§4** (tableau maître des symboles) ; si le PR touche l’API **B** partagée ou `max_distance`, lire aussi **§5** (micro-diff perf / booléen).

---

## 2. Vocabulaire contractuel A / B / C

### 2.1 Tableau synthétique

| ID | Nom contractuel | Question métier | Primitive dominante |
|----|-----------------|-----------------|---------------------|
| **A** | **Contact empreinte** | Les empreintes sont-elles au contact utile : voisinage **hex strict** entre cellules, ou bord-à-bord rond↔rond avec tolérance de discrétisation ? | Hex : `min_distance_between_sets(..., max_distance=1) <= 1`. Rond↔rond : `euclidean_edge_clearance_round_round(...)` + `gap <= _ADJACENT_EDGE_GAP_TOLERANCE_NORM`. |
| **B** | **Engagement empreintes** | Les unités sont-elles dans la zone d’engagement réelle ? | Rond↔rond Board ×10 : `gap <= engagement_minimum_clearance_norm(ez) + ε`. Sinon : `min_distance_between_sets(unit_fp, enemy_fp [, max_distance=ez]) <= ez`, avec `ez` via `get_engagement_zone`. |
| **C** | **Clearance destination (move)** | L’ancre de placement est-elle trop proche d’un ennemi pour finir / traverser selon les règles move ? | `ez <= 1` : membership dans `enemy_adjacent_hexes`. `ez > 1` : rond↔rond `gap <= engagement_minimum_clearance_norm(ez) + ε` (ε = typ. `1e-6`) ; sinon repli hex `min_distance_between_sets(...) <= ez`. |

**Lecture rapide :** **A** = collé ; **B** = dans la bulle d’engagement entre empreintes ; **C** = interdiction de destination / traversée. **B** et **C** ne sont pas interchangeables.

**Nommage :** ne pas utiliser `adjacent` seul pour **B**. Préférer `within_engagement_zone_footprints`, `footprint_engaged`, `footprint_hex_contact`, `move_anchor_violates_engagement_clearance`, etc.

### 2.2 Définitions opérationnelles (implémenteur)

**A — Contact empreinte**

- **Hex (polyhex) :** `min_distance_between_sets(unit_fp, enemy_fp, max_distance=1) <= 1` — **0** chevauchement, **1** cellules voisines grille. **Pas** de `ENGAGEMENT_NORM_HEX_WIDTH` sur ce chemin « strict collé ».
- **Rond ×10 (pile-in) :** `euclidean_edge_clearance_round_round(...)` puis `gap <= _ADJACENT_EDGE_GAP_TOLERANCE_NORM` (= `ENGAGEMENT_NORM_HEX_WIDTH` dans `fight_handlers`).
- **Pile-in branche non-rond :** `min_distance_between_sets(..., max_distance=cc_range) <= cc_range` — **B-like**, pas équivalent au strict **A** si `ez > 1` ; voir **§10** (décision à trancher).

**B — Engagement empreintes**

- `cc_range` / `ez` = `get_engagement_zone(game_state)` — lecteur canonique de la config `engagement_zone`.
- Rond↔rond Board ×10 : même vérité bord-à-bord que le move, `gap <= engagement_minimum_clearance_norm(ez) + ε`.
- Autres formes : `min_distance_between_sets(unit_fp, enemy_fp) <= cc_range`.
- **Si `max_distance` en boucle :** arrêt anticipé → la valeur retournée peut être **`max_distance + 1`** au-delà du seuil : **≠ distance exacte** pour logging ou règles fines ; le booléen « ≤ ez » reste correct si l’implémentation respecte le contrat. **Fight** vs **tir / charge** : voir **§5**.
- **Caches move :** dilatation hex (`build_enemy_adjacent_hexes`, …) — représentation **grille** liée à **ez**, pas la géométrie euclidienne rond↔rond quand `ez > 1`.

**C — Clearance destination**

- **Rond↔rond (Board ×10) :** `gap = euclidean_edge_clearance_round_round(...)` ; `req = engagement_minimum_clearance_norm(ez)` ; violation si `gap <= req + ε` avec **ε** typiquement `1e-6`.
- **Autres formes :** repli `min_distance_between_sets(candidate_fp, enemy_fp, max_distance=ez) <= ez` (aligné `_movement_engagement_violates` / BFS).

**Rappel B vs C :** **B** et **C** partagent la vérité rond↔rond bord-à-bord (**`gap <= req + ε`**) ; les formes non-rondes restent sur la vérité hex **`<= ez`**. Permuter les chemins sans respecter cette séparation = bugs discrets en **Board ×10**.

---

## 3. Pourquoi B ≠ C

| | **B — Engagement** | **C — Clearance move** |
|--|--------------------|-------------------------|
| Espace | Norme continue bord-à-bord pour rond↔rond en `_hex_center`, repli hex sinon. | Norme continue bord-à-bord pour rond↔rond en `_hex_center`, repli hex sinon. |
| Test typique | Rond↔rond : `gap <= req + ε`; sinon `distance <= ez`. | `gap <= req + ε`, avec `req = engagement_minimum_clearance_norm(ez)`. |
| Cache | Les caches dilatés sont une représentation grille liée à `ez`. | Pour rond↔rond `ez > 1`, le cache ne remplace pas le recalcul euclidien. |

Croire qu’un cache dilaté ou une distance hex suffit pour la vérité rond↔rond produit des bugs discrets en Board ×10.

---

## 4. Tableau maître — où c’est quoi

Symboles : **●** = rôle principal ; **◐** = branche / mixte ; **—** = non applicable (hors triade A/B/C pour cette ligne) ; **\*** dans les notes = hors triade stricte ; exposants **¹–⁵** = voir légende sous le tableau. Les chemins de code restent indicatifs.

**Règle d’équipe :** toute PR modifiant un symbole listé ici met à jour la ligne correspondante, ou référence un test de non-régression qui verrouille le comportement.

| Zone | Fichier — symbole | A | B | C | Notes anti-régression |
|------|-------------------|---|---|---|------------------------|
| Fight — skip pile-in « déjà collé » | `fight_handlers.py` — `_fight_unit_is_hex_adjacent_to_enemy_footprint` → `_fight_footprint_has_enemy_hex_contact` | ● | | | `<= 1` hex strict ; pas `ENGAGEMENT_NORM_HEX_WIDTH`. Test : `tests/unit/engine/test_fight_spatial_contract.py`. |
| Fight — consolidation contact | `fight_handlers.py` — `_fight_fp_has_adjacent_enemy_footprint` → `_fight_footprint_has_enemy_hex_contact` | ● | | | Même sémantique **A**. Test : `tests/unit/engine/test_fight_spatial_contract.py`. |
| Fight — pile-in ancre « contact » | `fight_handlers.py` — `_fight_pile_in_anchor_adjacent_to_enemy_footprint` | ●¹ | ●² | | ¹ **Rond↔rond :** `euclidean_edge_clearance_round_round` puis `gap ≤` tolérance (= `ENGAGEMENT_NORM_HEX_WIDTH` / `_ADJACENT_EDGE_GAP_TOLERANCE_NORM`). ² **Non-rond :** `min_distance_between_sets ≤ cc_range` (**B-like** si `ez > 1`). Décision **§10** avant unification. |
| Fight — éligibilité | `fight_handlers.py` — `_is_adjacent_to_enemy_within_cc_range` → `engine.spatial_relations.enemy_footprint_distances` | | ● | | Nom trompeur : **B**, pas contact **A**. Fight passe `max_distance=None` pour distance complète ; voir **§5**. Test : `tests/unit/engine/test_fight_spatial_contract.py`. |
| Fight — cibles CC | `fight_handlers.py` — `_fight_build_valid_target_pool` → `engine.spatial_relations.enemy_footprint_distances` | | ● | | Exclusion si `distance > cc_range`. Test : `tests/unit/engine/test_fight_spatial_contract.py`. |
| Fight — pools alternance | `generic_handlers.py` — `_is_adjacent_to_enemy_for_fight` → `engine.spatial_relations.unit_within_engagement_zone_footprints` | | ● | | Même **B** que fight, via primitive partagée. |
| Tir / advance | `shooting_handlers.py` — `_is_adjacent_to_enemy_within_cc_range` → `engine.spatial_relations.unit_within_engagement_zone_footprints` | | ● | | Copie locale conservée comme wrapper ; utilise `max_distance=cc_range`; voir **§5**. |
| Tir — portée arme | `shooting_handlers.py` — `_has_los_to_enemies_within_range` | — | — | | **\*** Distance de portée arme (`get_max_ranged_range`), pas `engagement_zone` ; **hors** A/B/C — ne pas fusionner avec **B**. |
| Charge — déjà engagé | `charge_handlers.py` — `_is_adjacent_to_enemy`, `_is_adjacent_to_enemy_simple` → `engine.spatial_relations.unit_within_engagement_zone_footprints` | | ● | | **B** ; `max_distance=cc_range` comme le tir. |
| Charge — hex voisin ennemi | `charge_handlers.py` — `_is_hex_adjacent_to_enemy` | ● | | | **A** grille / cache `enemy_adjacent_hexes` ; distinct de `_is_adjacent_to_enemy` **B**. |
| Move — flee / pools | `movement_handlers.py` — `_is_adjacent_to_enemy` → `_movement_engagement_violates` → `engine.spatial_relations.move_anchor_violates_engagement_clearance` | | ◐ | ● | ³ **C** dominant (flee, pools) ; branche non-rond `ez > 1` **B-like** hex ; `ez <= 1` via cache dilaté. Test : `tests/unit/engine/test_spatial_relations.py`. |
| Move — BFS vectorisé | `movement_handlers.py` — `_build_multi_hex_vectorized` | | | ● | Invariants commentés : doivent rester alignés avec `_movement_engagement_violates` / `move_anchor_violates_engagement_clearance`. |
| Caches move | `shared_utils.py` — `build_enemy_adjacent_hexes`, `enemy_adjacent_hexes_player_*` | | ◐ | ● | ⁴ Dilatation hex rayon **ez** (perf) ; `ez <= 1` → sert **C** directement ; `ez > 1` rond↔rond → le moteur affine en euclidien — **ne pas confondre** cache et vérité cercles. |
| IA | `ai/analyzer.py` — `is_hex_anchor_adjacent_to_enemy` / `is_adjacent_to_enemy` (alias legacy) | ● | | | ⁵ **Ancre 1 hex** + voisinage grille — pas empreinte multi-hex ni **B** moteur / clearance Board ×10. |
| IA — engagement moteur | `ai/analyzer.py` — `is_within_engine_engagement_zone` → `engine.spatial_relations.unit_within_engagement_zone_footprints` | | ● | | Fonction séparée pour comparer/aligner les analyses avec la sémantique moteur **B** sans casser l’adjacence legacy. |

**Légende exposants (§4) :** **¹** contact pile-in rond↔rond (gap + tolérance norme). **²** pile-in non-rond, critère **B-like** (`≤ cc_range`). **³** move : **C** dominant + branche hex **B-like** si `ez > 1` + cache si `ez <= 1`. **⁴** dilatation cache : perf grille **ez** ; ne **remplace pas** l’euclidien rond↔rond pour **C** quand `ez > 1`. **⁵** IA : ancre seule, pas empreinte moteur.

**Fichiers d’ancrage :** `fight_handlers.py`, `generic_handlers.py`, `shooting_handlers.py`, `charge_handlers.py`, `movement_handlers.py`, `shared_utils.py`, `hex_utils.py`, `weapon_helpers.py`, `ai/analyzer.py`.

---

## 5. Micro-diff `min_distance_between_sets`

Pour le test **B** `distance <= cc_range` :

- `fight_handlers._is_adjacent_to_enemy_within_cc_range` calcule souvent `min_distance_between_sets(unit_fp, enemy_fp)` **sans** `max_distance` : distance complète par paire ennemie.
- `shooting_handlers` et `charge_handlers` utilisent souvent `min_distance_between_sets(..., max_distance=cc_range)` : arrêt anticipé.

Le booléen attendu est identique si le contrat de `max_distance` est respecté ; le coût et la valeur retournée hors seuil diffèrent. Une API **B** partagée doit figer ce choix et couvrir fight / tir / charge par tests.

---

## 6. Primitives — contrat d’usage

| Primitive | Fichier | Contrat utile |
|-----------|---------|---------------|
| `min_distance_between_sets` | `engine/hex_utils.py` | Distance **hex** entre deux sets `(col, row)`. **0** chevauchement, **1** voisinage. Si `max_distance > 0`, arrêt anticipé ; au-delà du seuil, la valeur peut être `max_distance + 1`, pas la distance exacte. |
| `euclidean_edge_clearance_round_round` | `engine/hex_utils.py` | Écart bord-à-bord rond↔rond en `_hex_center` ; négatif si chevauchement ; `mover_center_xy` optionnel. |
| `engagement_minimum_clearance_norm(ez)` | `engine/hex_utils.py` | `float(ez) * ENGAGEMENT_NORM_HEX_WIDTH` si `ez > 0`, sinon `0.0` ; seuil **C** rond↔rond. |
| `ENGAGEMENT_NORM_HEX_WIDTH` | `engine/hex_utils.py` | `1.5` ; pas horizontal entre centres (Board ×10). |
| `dilate_hex_set` / BFS | `hex_utils.py`, handlers | Caches, pile-in, consolidation. |
| `compute_candidate_footprint`, `is_footprint_placement_valid` | `shared_utils.py` | Ancre → empreinte ; légalité plateau. |

**Piège structurel :** en rond↔rond Board ×10, **`engagement_minimum_clearance_norm`** et la comparaison **`gap <= req + ε`** pour **B/C** ne sont **pas** interchangeables avec seul **`min_distance_between_sets <= ez`** (qui sert au repli hex). Décider l’engagement sans recalculer `gap` quand les deux modèles coexistent = erreur.

---

## 7. Constantes et lecteurs config

| Symbole | Rôle | Fichier |
|---------|------|---------|
| `_ADJACENT_EDGE_GAP_TOLERANCE_NORM` | Alias de `ENGAGEMENT_NORM_HEX_WIDTH` pour contact pile-in rond↔rond | `fight_handlers.py` |
| `get_engagement_zone` | Lecteur canonique de la règle config `engagement_zone`; `get_melee_range` supprimé car le nom historique confondait mêlée et engagement | `engine/spatial_relations.py` |
| ε (clearance) | typ. `1e-6` dans `gap <= req + ε` ; à centraliser avec **C** | `engine/spatial_relations.py` |

---

## 8. Cibles de refactor

| Famille | Exemples actuels | Livrable indicatif |
|---------|------------------|--------------------|
| **A — Contact** | `_fight_unit_is_hex_adjacent_to_enemy_footprint`, `_fight_fp_has_adjacent_enemy_footprint`, branche contact pile-in, `_is_hex_adjacent_to_enemy` | `footprint_hex_contact(...)` + `footprint_round_edge_contact(...)` si le split reste nécessaire. |
| **B — Engagement** | `_is_adjacent_to_enemy_within_cc_range` (fight + tir), `_is_adjacent_to_enemy_for_fight`, `_fight_build_valid_target_pool`, charge `_is_adjacent_to_enemy*`, blocage de cible shoot engagée avec un allié | `engine.spatial_relations.unit_within_engagement_zone_footprints(...)` + `unit_entries_within_engagement_zone(...)`, testé sur fight / tir / charge. |
| **C — Clearance** | `_movement_engagement_violates`, `destination_adjacent_to_enemy`, `_build_multi_hex_vectorized` | `engine.spatial_relations.move_anchor_violates_engagement_clearance(...)`, avec **ε** centralisé et équivalence BFS conservée. |

**Hors scope immédiat :** réécrire toute la dilatation des caches.  
**Dans le scope :** conserver l’équivalence BFS / prédicat **C**, sauf décision documentée.

---

## 9. Pièges — checklist PR

*(Placé **avant** les décisions §10 : lecture rapide avant tout refactor touchant l’engagement ou le move.)*

1. **`adjacent` dans le nom pour du B** : `_is_adjacent_to_enemy_within_cc_range` = engagement empreintes, pas contact **A**.
2. **Homonymes** : `_is_adjacent_to_enemy` dans `movement_handlers` ≠ `charge_handlers` ≠ `ai/analyzer.py`.
3. **Pile-in** : deux branches (rond↔rond vs non-rond) ; pas d’unification sans décision **§10**.
4. **Doublons B** : fight / generic / tir / charge ; fusion ou tests « mêmes entrées → même booléen » (inclure le cas **§5**).
5. **B/C rond↔rond** : `gap <= req + ε` ; caches dilatés et `<= ez` hex ≠ vérité cercles en Board ×10.
6. **Pools** : pas de re-vérification redondante (règle projet) ; noms de pools alignés sur **C** / dilatation réelle, pas « adjacent » vague.
7. **Analyzer** : ne pas assimiler à **B** moteur sans décision **§10** et tests.
8. **`max_distance` dans `min_distance_between_sets`** : avec arrêt anticipé, la valeur au-delà du seuil peut être **`max_distance + 1`** — ne pas l’utiliser comme distance exacte (logs, règles fines) ; pour l’API **B** unifiée, figer le choix perf vs distance complète et couvrir fight / tir / charge (voir **§5**).

---

## 10. Décisions à trancher par écrit

| Sujet | Options | Risque si non tranché |
|-------|---------|------------------------|
| Pile-in non-rond | Garder `<= cc_range` (**B-like**) vs `<= 1` hex (**A** strict) | Priorité ancres contact vs portée pile-in. |
| Lecteurs config | Décision appliquée : `get_engagement_zone(game_state)` est le lecteur canonique, `get_melee_range` est supprimé | Divergence terminologique supprimée. |
| Fight éligible vs PISTOL « engaged » | Décision appliquée : même primitive **B/engagement** partagée ; wrappers métier locaux conservés | Double maintenance / incohérence supprimée côté moteur. |
| `ai.analyzer.is_adjacent_to_enemy` | Décision appliquée : conserver l’alias legacy ancre hex, ajouter `is_hex_anchor_adjacent_to_enemy` et `is_within_engine_engagement_zone` | Décalage rendu explicite sans casser les analyses existantes. |

**Format attendu :** une phrase de décision dans la PR ou un ADR court, plus un test qui verrouille le choix. Si impact joueur visible : mise à jour `AI_TURN.md`. Sinon : mention « refactor nominal uniquement ».  
Si un symbole du **§4** change de sémantique : mettre à jour la ligne du tableau **dans le même merge** (ou lien vers test de non-régression).

---

## 11. Ordre de migration recommandé

1. **Fight** : factoriser **A** ; couverture **B** pour `_fight_build_valid_target_pool` et `_is_adjacent_to_enemy_within_cc_range` ; figer tests pile-in rond↔rond / non-rond, règle par défaut inchangée.
2. **Éligibilité** : introduire **B** officielle ; wrapper déprécié visible, pas de silence.
3. **Tir** : remplacer copie locale **B** par l’API partagée ; vérifier **§5** ; ne pas confondre avec `_has_los_to_enemies_within_range` (**§4**, hors A/B/C).
4. **Charge** : aligner `_is_adjacent_to_enemy*` sur **B** ; garder **A** explicite pour `_is_hex_adjacent_to_enemy`.
5. **Move** : extraire **C** ; tests BFS / destinations ; rond↔rond ×10.
6. **IA** : appliquer la décision analyzer du **§10** après stabilisation moteur.

À chaque étape : petites grilles, paires d’empreintes connues, non-régression `tests/unit/engine/test_hex_utils.py`.

---

## 12. Critères d’acceptation

- [ ] API ou module **A / B / C** nommés ; le **tableau maître (§4)** pointe vers les symboles finaux.
- [ ] Toute PR touchant un symbole listé au **§4** met à jour la ligne correspondante ou référence un test de non-régression qui verrouille le comportement.
- [ ] Toute PR qui **fusionne ou renomme** la logique **B** (`min_distance_between_sets`, `max_distance`, fight vs tir vs charge) met à jour ou valide explicitement le **§5** (micro-diff perf / contrat du booléen).
- [ ] Pas de `adjacent` seul pour **B** sans qualificatif ou doc locale.
- [ ] Doublons **B** : fusion ou tests booléens documentés, incluant le cas **§5** (early exit `max_distance + 1` vs distance complète).
- [ ] Chaque ligne du **§10** est tranchée par écrit et verrouillée par test.
- [ ] Tests minimum : rond↔rond ×10, legacy `ez = 1`, au moins un non-rond si applicable, clearance dans `tests/unit/engine/test_hex_utils.py`.
- [x] Décision analyzer (**§10**) appliquée : legacy ancre hex explicite + fonction **B** moteur séparée.
- [ ] `AI_TURN.md` mis à jour si règle joueur visible change ; sinon mention « refactor nominal uniquement ».

---

## 13. Références

- `Documentation/AI_TURN.md` — canon gameplay
- `Documentation/AI_IMPLEMENTATION.md` — architecture
- `Documentation/TODO/Boardx10-final.md` — grille Board ×10
- `engine/spatial_relations.py` — primitives partagées **B** / distances empreintes
- `tests/unit/engine/test_fight_spatial_contract.py` — garde-fous A/B fight
- `tests/unit/engine/test_spatial_relations.py` — garde-fous primitives partagées B/C
- `tests/unit/ai/test_analyzer_utils.py` — garde-fous analyzer legacy A + engagement moteur B
- `tests/unit/engine/test_hex_utils.py` — garde-fous clearance
- `generic_handlers.py` — commentaires PERF autour de `_rebuild_alternating_pools_for_fight`

---

*Contrat final — ordre **pièges (§9) avant décisions (§10)** ; §2.2 définitions opérationnelles ; §6 piège structurel B/C ; §4 tableau avec légende **¹–⁵** ; §12 critères distinguant **§4** (symboles) et **§5** (micro-diff **B**) ; harmonisation **ε** et Board ×10 ; migration fight incluant pools **B**.*
