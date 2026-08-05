# Replis silencieux sur `units_cache` — move / fight / shoot — 2026-08-05

**Chantier CLOS — T1, T2 et T3 livrés le 2026-08-05.** Placé à la racine de
`Implémentation/` parce qu'il porte du travail à faire ET la preuve déjà acquise. Si tu préfères la
convention stricte du dépôt (`A_faire/` = backlog pur), il peut y descendre tel quel.

**État final** : les 40 sites de l'inventaire ont été instruits un par un, plus **7 sites jumeaux
découverts hors inventaire** dans `ai/evaluation_bots.py` (cf. §3, encadré « Jumeau hors
périmètre »). Verrou : `tests/unit/engine/test_units_cache_desync_raises.py`, **15 tests, 15
mutations ROUGES** vérifiées une par une. Bilan par verdict en §7.

**Origine** : lot des jumeaux de la charge, clos le 2026-08-05 — voir
[`Implémenté/campagne_typage_et_replis_2026-07-29.md`](Implémenté/campagne_typage_et_replis_2026-07-29.md)
§3.6. Ce document-ci porte le **détail par site** que §3.6 ne donne pas.

**Convention d'ancrage** : l'ancre de référence est le **nom de fonction** ; les numéros de ligne
sont indicatifs, relevés le 2026-08-05 sur un working tree où l'utilisateur avait des
modifications en cours. Re-localiser par `grep` avant d'éditer.

---

## 1. Le défaut

`units_cache` est le **miroir de `units`**, reconstruit par `build_units_cache`. Toute unité vivante
y est. Pourtant 42 lectures de ce cache, réparties sur les quatre modules de phase, répondent à une
absence par une **valeur crédible** au lieu de lever :

```python
unit_fp = entry_footprint(unit_entry) if unit_entry else {(unit_col, unit_row)}
```

Ce n'est pas un repli métier. C'est un **verdict inventé** : l'unité est alors mesurée sur son ancre
seule, donc l'adjacence de mêlée, la ligne de vue de tir et la zone d'engagement du move rendent
« pas d'engagement » / « pas de LoS » sur une géométrie qui n'est pas la vraie — et **rien ne
crashe**. C'est exactement le motif que `require_entry_on_battlefield`
([`engine/spatial_relations.py`](../../engine/spatial_relations.py)) a été écrit pour rendre bruyant,
et exactement celui que le lot charge vient de supprimer de `charge_handlers.py`.

⚠️ **Tous les 42 ne sont PAS des défauts.** Le tri fait partie du travail, il ne le précède pas —
voir §4.

---

## 2. Ce que le lot charge a prouvé (précédent utilisable)

13 sites inventoriés à l'AST dans `charge_handlers.py`. Résultat après instruction :

| Verdict | N | Enseignement |
|---|---|---|
| déjà bruyants | 3 | le contrat était **déjà écrit dans le même fichier** — un site levait dix lignes sous son jumeau qui retombait sur `False` |
| corrigés | 10 | dont 2 qui faisaient **disparaître une cible déclarée** des voiles UI |
| **code mort** | 1 fonction (49 l.) | `_build_charge_anchors_in_zone` — aucun appelant ; elle portait les deux pires sites, dont un qui rendait la case **`(0, 0)`**, une case RÉELLE du plateau |
| classé « métier » **à tort** | 1 | ⚠️ voir ci-dessous |

🔴 **Le piège à ne PAS répéter, mesuré sur ce lot.** `charge_preview_move_plan` rangeait la cible
absente du cache dans `missing_targets` : classé « refus métier légitime, l'UI le voit », donc
écarté. **C'était faux** — `charge_commit_move_plan_handler` renvoie ce champ tel quel dans
`invalid_charge_plan`, si bien qu'une désynchronisation d'état sortait sous le message « cible non
engagée ». Trouvé par `/code-review`, pas par l'inventaire. **Un canal de sortie « visible » ne
prouve rien : il faut lire ce que l'appelant en FAIT.** Un champ qui mélange refus métier et erreur
d'état est un repli silencieux déguisé.

**À retenir pour ce lot-ci** : environ **un site sur quatre n'est pas à corriger** (déjà correct ou
dans du code mort) — mais la catégorie « métier » ne se décrète pas à la lecture du site, elle se
prouve chez l'appelant. Un balayage mécanique produirait des régressions ; c'est la leçon §3.2 de la
campagne (105 des 143 `str()` de `charge_handlers` étaient la normalisation elle-même).

**Outil livré par le lot charge, à utiliser pour les 42** :
`require_unit_from_cache(unit_id, game_state, what)`
([`engine/phase_handlers/shared_utils.py`](../../engine/phase_handlers/shared_utils.py), jumeau
bruyant de `get_unit_from_cache`). Il lève un `KeyError` uniforme `"{what}: unit {id} missing from
units_cache"`. **Ne pas réécrire de `raise` à la main** : le lot charge en a écrit dix, et la revue
a montré que la même condition levait alors trois types d'exception différents (`KeyError`,
`ValueError`, `ConfigurationError`) — dont `ValueError`, qui est un canal de **refus métier** ailleurs
dans le moteur et se fait avaler par des `except ValueError`. Les dix sites y sont passés.

⚠️ Il ne contrôle **PAS** le placement : une unité en réserves (20.01) EST dans `units_cache` avec la
sentinelle `(-1,-1)`. « Exister » et « être sur la table » sont deux contrats distincts — le second
est `require_entry_on_battlefield`. Ne pas les fusionner en traitant les 42.

**Argument de contrat, réutilisable tel quel** : les entrées de phase valident l'unité et les cibles
(`get_unit_by_id` + `is_unit_alive`) avant d'appeler la géométrie, et rien ne meurt entre ces deux
points à l'intérieur d'une phase. Un miss est donc une **désynchronisation `units` / `units_cache`**.
Cet argument **doit être re-vérifié par site** : il tient pour la charge, il n'est pas acquis
partout (le tir retire des figurines en cours de séquence).

---

## 3. Inventaire — 42 sites

Relevé par analyse syntaxique (AST) : tout `X.get(...)` où `X` est lié à `units_cache`, moins ceux
qui lèvent déjà et ceux portant le marqueur `# get allowed`. **Dénominateur brut avant filtre : 64.**

### Forme A — `entry_footprint(x) if x else <repli sur l'ancre>` — ~~9~~ ~~7~~ **6 sites vivants** — ✅ TRAITÉE

(le 7ᵉ, `_fight_compute_pile_in_footprint_zone`, était du code mort — cf. §8.3)

**La plus dangereuse, et la plus rapide à traiter** : contrat identique à chaque fois, correctif
identique à celui du lot charge. Une empreinte de repli fait mentir la géométrie sans jamais crasher.

| Site | Fonction | Lecture |
|---|---|---|
| `fight_handlers.py:285` | `_fight_unit_is_hex_adjacent_to_enemy_footprint` | `unit_entry = units_cache.get(unit_id_str)` |
| `fight_handlers.py:302` | `_fight_pile_in_closest_enemy_snapshot` | `unit_entry = units_cache.get(unit_id_str)` |
| ~~`fight_handlers.py:745`~~ | ~~`_fight_compute_pile_in_footprint_zone`~~ | **SUPPRIMÉE** — CODE MORT (transitif), cf. §8.3 |
| ~~`fight_handlers.py:2168`~~ | ~~`_has_los_to_enemies_within_range`~~ | **SITE DISPARU** — fonction supprimée le 2026-08-05 (cf. note ci-dessous) |
| `movement_handlers.py:1476` | `_is_in_enemy_engagement_zone` | `unit_entry = units_cache.get(unit_id_str)` |
| `shooting_handlers.py:2120` | `_unit_has_firable_target` | `shooter_entry = units_cache.get(shooter_id_str)` |
| `shooting_handlers.py:2299` | `_is_valid_shooting_target` | `shooter_entry = units_cache.get(shooter_id_str)` |
| `shooting_handlers.py:2300` | `_is_valid_shooting_target` | `target_entry = units_cache.get(target_id_str)` |
| ~~`shooting_handlers.py:6048`~~ | ~~`_has_los_to_enemies_within_range`~~ | **SITE DISPARU** — fonction supprimée le 2026-08-05 (cf. note ci-dessous) |

🔴 **Jumeau évident dans la liste — RÉSOLU le 2026-08-05, et la réponse est « les deux ».**
`_has_los_to_enemies_within_range` existait en double dans `fight_handlers` ET `shooting_handlers`,
avec le même défaut. Vérification faite (grep dépôt entier, `.py` / `.ts` / `.tsx` / `.json`) :
**aucune des deux copies n'avait d'appelant**. Les deux ont été **supprimées** — 2 sites de moins
dans la Forme A, qui en compte donc **7** à traiter, et 40 au total.

L'intuition du lot charge était la bonne, et vaut d'être retenue : sur ce dépôt, un jumeau parfait
qui n'a jamais divergé est un candidat sérieux au code mort. Le vérifier AVANT de corriger évite
d'écrire un correctif — et pire, un test — sur du code que personne n'appelle.

🔴 **JUMEAU HORS PÉRIMÈTRE DE L'INVENTAIRE — trouvé au traitement de T1, 6 sites de plus.**
`grep -rn "entry_footprint(.*) if .* else {(" --include=*.py .` rend **6 hits dans
`ai/evaluation_bots.py`** (un 7ᵉ, `_living_enemy_positions`, écrit en `if entry is not None: … else:`,
a survécu à ce grep et n'a été trouvé qu'au balayage final — voir §7) : `_count_nearby_threats` (×2), `_find_nearest_enemy` (×2),
`_find_safest_position` (×1), `_find_best_offensive_position` (×1). Ils portent le motif Forme A
mot pour mot, et le repli y était pire : il retombait sur le `col`/`row` de la **DATASHEET**
(`game_state["units"]`), qui n'est pas la source de vérité spatiale — donc une position
potentiellement périmée, pas seulement une empreinte amputée. Les 6 sont traités.

**Ce que ça dit du dénominateur de §3** : le balayage AST n'a couvert que les quatre modules de
phase. Il ne borne donc PAS le motif au dépôt. Toute reprise de T2/T3 doit relancer le grep large
avant de conclure, et non se fier au « 42 ».

**Ce que ça dit des tests** : deux tests de `tests/unit/ai/test_evaluation_bots.py`
(`test_tactical_bot_find_helpers`, `test_tactical_bot_movement_position_helpers`) construisaient un
`units_cache` **VIDE** avec `is_unit_alive` doublé à `True` — c'est-à-dire qu'ils VALIDAIENT le
repli, sur un état que la production ne produit jamais. Ils ont été remis sur un cache miroir de
`units`. Un test qui a besoin du défaut pour passer n'est pas un test de non-régression.

### Forme B — `if x is None: return <valeur>` — 14 sites — ✅ TRAITÉE

Le refus est explicite mais **muet sur sa cause** : l'appelant ne distingue pas « pas de cible » de
« état corrompu ». Tri nécessaire : certains sont un vrai cas de jeu.

| Site | Fonction | Repli constaté |
|---|---|---|
| `fight_handlers.py:1790` | `_model_can_fight_target` | `if target_entry is None:` |
| `fight_handlers.py:3417` | `_fight_pile_in_closest_tier_ids` | `if entry is None:` |
| `shared_utils.py:1677` | `check_if_melee_can_charge` | `if target_entry is None or not entry_is_on_battlefield(...)` ⚠️ **probablement légitime** (hors table = 20.01) |
| `shared_utils.py:3288` | `_recompute_squad_occupied_hexes` | `if entry is None:` |
| `shared_utils.py:5788` | `_attacker_model_can_reach_squad` | `if base_unit is None:` |
| `shared_utils.py:5932` / `:5933` | `_shoot_engagement_blocks_target` | `if shooter_entry is None or target_entry is None:` |
| `shared_utils.py:6932` / `:6933` | `_squads_are_engaged` | `if a is None or b is None:` |
| `shared_utils.py:9432` | `fight_pile_in_plan` | `if our_entry is None:` |
| `shared_utils.py:9771` | `squad_consolidate_plan` | `if our_entry is None:` |
| `shared_utils.py:9903` | `_squad_is_in_enemy_er` | `if entry is None:` |
| `shared_utils.py:10349` | `build_squad_move_cell_map` | `if entry is None:` |
| `shooting_handlers.py:1101` | `preview_hidden_models_from_position` | `if entry is None:` |

### Forme C — `if x is None: continue` — 6 sites — ✅ TRAITÉE

**Pire que B** : l'élément disparaît de l'énumération sans trace. C'est le défaut exact de
`_compute_plan_context` corrigé dans le lot charge, où une cible déclarée devenait *ni satisfaite,
ni insatisfaite* — donc invisible dans l'UI.

| Site | Fonction |
|---|---|
| `fight_handlers.py:2377` | `pile_in_move_destinations_12_03` |
| `fight_handlers.py:3426` | `_fight_pile_in_closest_tier_ids` |
| `fight_handlers.py:3840` | `pile_in_autoplace_plan` |
| `shared_utils.py:5296` | `_hex_legal_for_charge` |
| `shooting_handlers.py:1676` | `build_hidden_too_far_by_unit_id` |
| `shooting_handlers.py:1779` | `build_hidden_detection_info_by_unit_id` |

### Forme D — à lire avant de classer — 13 sites — ✅ TRAITÉE

Compréhensions filtrantes (`... for x in ... if x is not None`), gardes composites, replis sur
`occupied_hexes`. Aucune hypothèse posée ici.

| Site | Fonction | Note |
|---|---|---|
| `fight_handlers.py:357` | `_fight_pile_in_new_fp_strictly_closer_to_closest_tier` | |
| `fight_handlers.py:1265` | `_fight_plan_consolidation_destinations` | |
| `fight_handlers.py:1533` | `_ai_select_pile_in_destination` | |
| `fight_handlers.py:4887` | `_fight_consolidation_preview_plan` | garde composite |
| `movement_handlers.py:3159` | `movement_build_valid_destinations_pool` | repli `occupied_hexes_by_model` → `None` |
| `shared_utils.py:5408` | `charge_build_valid_plan` | compréhension filtrante |
| `shared_utils.py:9468` | `fight_pile_in_plan` | compréhension filtrante |
| `shared_utils.py:9542` | `get_fighting_models` | compréhension filtrante |
| `shared_utils.py:9779` | `squad_consolidate_plan` | |
| `shared_utils.py:10588` | `build_squad_action_mask` | ⚠️ **probablement légitime** — commentaire en place : « Ennemi hors table (réserves 20.01) : intirable, et sans géométrie à mesurer » |
| `shooting_handlers.py:3493` | `shooting_build_valid_target_pool` | |
| ~~`shooting_handlers.py:3574`~~ | ~~`_resolve_target_hexes_for_los`~~ | **SUPPRIMÉE** — code mort, cf. §7 |
| `shooting_handlers.py:4288` | `_resolve_unit_anchor_and_footprint` | repli `occupied_hexes` |

---

## 4. Méthode imposée (non négociable, tirée du lot charge)

1. **Établir le contrat d'appelant AVANT de toucher.** Remonter les appelants, citer `fichier:ligne`.
   Un site dont l'appelant ne garantit pas la présence n'est **pas** à convertir en `raise` : c'est
   peut-être un cas de jeu (unité en réserve, cible détruite en cours de séquence de tir).
   **Corollaire, appris à ses dépens (§2)** : un site qui remonte le manque dans une structure de
   sortie (`missing_*`, liste d'erreurs, drapeau) n'est PAS classable « métier » sans lire ce que
   l'appelant fait de cette structure. S'il la confond avec un refus de règle, c'est un repli
   silencieux déguisé.
2. **Chercher le code mort d'abord.** Le lot charge a supprimé 49 lignes plutôt que de corriger deux
   sites dedans. Patron de preuve en quatre directions : (a) aucun appel ni import, (b) aucune
   référence par chaîne ni réflexion, (c) aucune route d'API ni chemin frontend, (d) aucune mention
   en documentation.
3. **Vérifier le jumeau frontend.** Sur la charge, `closestChargerHexToTargetFootprint`
   ([`frontend/src/components/BoardPvp.tsx`](../../frontend/src/components/BoardPvp.tsx)) s'est
   révélé **sain** — c'était le backend qui divergeait. Ne pas propager un correctif sans regarder.
4. **Prouver le verrou par mutation.** Remettre le repli, voir le test ROUGE, rétablir, le rapporter.
   Un test qui passe du premier coup n'est pas un verrou.
5. **Borner le verdict.** Certains sites ne sont pas atteignables par un test unitaire sans état
   corrompu construit à la main, et une garde amont peut mordre avant (mesuré sur la charge :
   `require_unit_position` masque le site de `charge_build_valid_destinations_pool`). Dans ce cas la
   preuve est **statique** et doit être écrite comme telle — pas présentée comme un vert de test.

---

## 5. Découpage recommandé

| Tranche | Contenu | Charge |
|---|---|---|
| ~~**T1**~~ ✅ | **Forme A, 7 sites** + 6 jumeaux `evaluation_bots` — LIVRÉ le 2026-08-05. | fait |
| ~~**T2**~~ ✅ | Formes B + C, 20 sites — LIVRÉ le 2026-08-05. | fait |
| ~~**T3**~~ ✅ | Forme D, 13 sites — LIVRÉ le 2026-08-05. | fait |

Repère de coût : le lot charge (13 sites, 1 module) a consommé une session complète, investigation,
suppression de code mort, 4 tests et mutations comprises. `shared_utils.py` est le plus gros module
du dépôt — ne pas prendre les 42 en bloc.

**Ne PAS faire** : un balayage mécanique forme par forme sans contrat d'appelant. C'est l'erreur que
§3.2 de la campagne a explicitement refusée, et le lot charge a confirmé qu'un site sur trois n'est
pas à corriger.

---

## 6. Limites de preuve de ce document

1. ~~**Aucune correction livrée.**~~ **Les trois tranches sont livrées** ; ce document est devenu un
   rapport de travail. Bilan par verdict : §7.

   **Portée exacte des verrous, à ne pas surestimer.** 17 tests couvrent les sites ATTEIGNABLES.
   Les autres sont précédés d'une garde qui mord d'abord (`is_unit_alive`,
   `require_unit_position`, `charge_check_eligibility`, `require_hp_from_cache`) et rendent le
   `raise` **statiquement inatteignable** : leur preuve est écrite dans le code, ce n'est pas un
   vert de test (méthode §4.5). Le `require_unit_from_cache` y reste, parce qu'il documente
   l'invariant et survivra au jour où la garde amont bougera.

   **Ce qui n'a PAS été vérifié** : la vérification large (suite complète, `check_ai_rules.py`,
   `hidden_action_finder.py`, biome, tsc) appartient à l'utilisateur — cf. limite 5. Environ 40
   fichiers de test ciblés ont été joués (fight, shoot, move, charge, masque, obs, réserves,
   bots) : tous verts. `pyright` : 0 erreur sur les 4 modules de phase et `evaluation_bots`.
2. ~~**Le tri A/B/C/D est syntaxique**~~ — confirmé à l'usage, et les deux ⚠️ signalés ont été
   **tranchés en sens inverse l'un de l'autre** : `build_squad_action_mask` est bien légitime (le
   contrat du masque est « squad absent/mort → all-zero »), `check_if_melee_can_charge` ne l'est
   PAS (son unique appelant lève sur la même cible dix lignes plus haut). Une liste d'audit est
   bien une liste de soupçons.
3. **Chiffre 42 vs 43** : le premier comptage annoncé en fin de lot charge disait 43. L'écart tient
   à la fenêtre de détection du script (4 vs 5 lignes après le lookup) ; le tri par site tranche de
   toute façon au cas par cas.
4. **Le dénominateur brut est 64** lookups `units_cache` sur les quatre modules ; 22 lèvent déjà ou
   portent `# get allowed`. Ce dénominateur est publié exprès (leçon §4.1 : un contrôle qui ne
   regarde rien répond « tout va bien »).
5. **Aucune vérification large** n'a été lancée : elle appartient à l'utilisateur (CLAUDE.md).

---

## 7. Bilan par verdict — livré le 2026-08-05

**Comptage vérifiable, relevé APRÈS les suppressions de code mort et les deux passes
`/simplify`** (les chiffres publiés plus tôt dans la vie de ce document étaient antérieurs) :

```
grep -c "require_unit_from_cache(" <fichier>     # retrancher la définition dans shared_utils
```

| Fichier | Appels |
|---|---|
| `shared_utils.py` | 15 |
| `fight_handlers.py` | 10 |
| `shooting_handlers.py` | 10 |
| `ai/evaluation_bots.py` | 7 |
| `movement_handlers.py` | 2 |
| **total du lot** | **44** |
| `charge_handlers.py` (lot charge, hors périmètre) | 10 |

| Verdict | N | Détail |
|---|---|---|
| **replis silencieux corrigés** | 42 | dont 7 hors inventaire (`ai/evaluation_bots.py`) |
| **`raise` manuels unifiés** | 2 | `build_hidden_*_by_unit_id` volet tireur : `raise KeyError` recopié, même condition, libellé propre à chaque copie |
| **légitimes, laissés en l'état** | 4 | voir ci-dessous |
| **sites de l'inventaire qui étaient du CODE MORT** | 3 | §8.1, §8.2, §8.3 — corrigés, puis supprimés |
| **verrous** | 15 tests | 15 mutations ROUGES vérifiées une par une |

L'écart entre 44 appels et les 40 sites de l'inventaire vient des deux sens : certains sites
portaient DEUX lectures (tireur + cible), 7 sites sont hors inventaire, et **3 sites de
l'inventaire se sont révélés être du code mort** (§8.1, §8.2, §8.3) — corrigés puis supprimés,
donc ils ne comptent plus.

**Les 4 sites LÉGITIMES, et pourquoi** — ce sont des contrats de jeu, pas des replis :

1. `build_squad_action_mask` (squad absent) et `build_squad_move_cell_map` (idem) : le contrat
   documenté du masque est « squad absent/mort → all-zero ». Lever y ferait planter l'observation
   sur un slot mort, qui est un état NORMAL.
2. `_squad_is_in_enemy_er` : même chose, c'est le prédicat que lit ce masque — le miroir devait
   suivre, sinon les deux divergent.
3. `_recompute_squad_occupied_hexes` : `remove_from_units_cache` retire l'escouade **sans purger
   `models_cache`**, donc le retrait d'une figurine d'une escouade déjà morte atteint réellement ce
   chemin. Il n'y a alors rien à recalculer.

Dans les trois cas, seul le **cache absent** (`game_state.get("units_cache", {})`) et les
**valeurs par défaut** (`player=-1`, `entry.get("player", -1)`) ont été convertis en `require_key` :
un `{}` vidait l'énumération de collision (toute cellule libre) et `-1` faisait de TOUTES les
escouades des ennemies (toute cellule interdite) — deux verdicts inventés, opposés, sans bruit.

**Trois défauts trouvés hors des formes A/B/C/D**, tous du même motif et corrigés avec :
`player=-1` par défaut dans `_hex_legal_for_charge`, `fight_pile_in_plan` et `get_fighting_models`.

**Ce qui a été SIGNALÉ et NON traité** (motif différent, hors périmètre de clôture) :
- `_shoot_engagement_blocks_target` : `shooter_unit is None → return False` lit `units`, pas
  `units_cache` — il n'existe pas de jumeau bruyant à `get_unit_by_id`. Même famille de défaut,
  autre index : c'est un chantier à part.
- `charge_check_eligibility:5251` : `models_cache` assigné jamais lu (local mort, sans effet).

**Leçon principale de ce lot, à reprendre au prochain audit du même genre** : le balayage AST
initial ne couvrait que les quatre modules de phase. Un `grep` dépôt entier sur le motif corrigé a
rendu **6 sites de plus**, plus dangereux que ceux de l'inventaire (repli sur le `col`/`row` de la
DATASHEET, qui n'est pas la source de vérité spatiale) — et **deux tests qui validaient le repli**
en construisant un `units_cache` VIDE. Un inventaire borne un périmètre de lecture, jamais un
périmètre de défaut.

**Ce qui reste NON audité, et il faut le dire** : `grep -rn "units_cache.get(" engine/ ai/` rend
encore **26 lectures** hors `# get allowed`, réparties sur `w40k_core.py`, `spatial_relations.py`,
`terrain_utils.py`, `action_decoder.py` et les sites des 4 modules de phase dont le `raise` suit
immédiatement. L'inventaire AST de ce document ne portait que sur les **quatre modules de phase** :
ces 26 n'ont **pas** été instruites. Ne pas lire « chantier clos » comme « le motif a disparu du
dépôt ».

---

## 8. Ce que la relecture du lot a trouvé — du CODE MORT, jusque sous mes propres tests

La méthode §4.2 dit « chercher le code mort d'abord ». **Ce lot ne l'a pas fait**, et la relecture
du diff l'a payé : deux des sites traités sont dans des fonctions **sans aucun appelant**.

### 8.1 — `_resolve_target_hexes_for_los` (`shooting_handlers.py`, 26 l.) — SUPPRIMÉE
 Preuve en
   quatre directions : aucun appel ni import (hors le test que ce lot venait d'écrire dessus),
   aucune référence par chaîne, rien côté API ni frontend, aucune mention en documentation à part
   la ligne d'inventaire de ce document. Le test écrit sur elle a été supprimé aussi — **écrire un
   test sur du code mort est pire qu'écrire un correctif dessus** : il fige une fonction morte et
   la fait passer pour vivante au prochain audit.

### 8.2 — `_fight_plan_consolidation_destinations` (`fight_handlers.py`, 258 l.) — SUPPRIMÉE

**Après enquête.** Le doute levé en §8 est tranché : elle est morte, pas orpheline
   d'un appelant perdu.

   **Preuve, en trois temps.** (a) Balayage AST du dépôt entier (`Name`, `Attribute`, `import`,
   littéraux) : **zéro référence** hors sa propre définition. (b) `git log -S` : le dernier appel
   a disparu le **2026-07-23**, commit `d69dfe0a` — *« V11 : purge de la machine d'activation
   fight V10 morte (3 pools + 8 fonctions + init/tests) »*, 597 lignes retirées de
   `fight_handlers`. L'appelant supprimé était `_fight_try_begin_consolidation_after_attacks`,
   c'est-à-dire la machine V10 elle-même. **La purge a retiré l'appelant et oublié l'appelée.**
   (c) Les quatre mentions en documentation sont donc PÉRIMÉES, pas des preuves de vie — deux
   d'entre elles (`consolidation_plan.md` 2026-08-01, `squad.md` 2026-08-04) ont même été
   éditées APRÈS la purge sans que personne ne le remarque.

   **Résidus traités avec elle** : le libellé `FIGHT_CONSOLIDATION_PLAN` de
   [`engine/perf_timing.py`](../../engine/perf_timing.py) (plus émis par personne) et la chaîne
   d'appel affirmée par [`A_faire/bug_pile_in_bfs_clearance_mismatch.md`](A_faire/bug_pile_in_bfs_clearance_mismatch.md)
   (`consolidate_autoplace_plan → _fight_plan_consolidation_destinations`), qui n'existe pas —
   la mesure d'impact PvP de ce document de bug (« −19 ancres ») est donc à refaire sur le chemin
   V11 réel avant de le traiter.

🔴 **ET ELLE N'ÉTAIT PAS SEULE — 35 FONCTIONS MORTES AU TOTAL, 1 101 LIGNES, TOUTES SUPPRIMÉES.**

Le balayage AST qui a tranché son cas a été généralisé à tout `engine/phase_handlers/`, **itéré
jusqu'au point fixe** (supprimer une fonction en orpheline d'autres : la passe 2 en a rendu 6 de
plus). Résultat : 29 fonctions en passe 1, 6 en passe 2, 0 en passe 3.

| Module | Fonctions | Lignes |
|---|---|---|
| `fight_handlers.py` | 15 | 598 |
| `shooting_handlers.py` | 14 | 389 |
| `shared_utils.py` | 4 | 66 |
| `charge_handlers.py` | 2 | 48 |
| **sous-total balayage** | **35** | **1 101** |
| + `_fight_compute_pile_in_footprint_zone` (§8.3) | 1 | 20 |
| + `_fight_plan_consolidation_destinations` (supprimée avant le balayage) | 1 | 258 |
| + `_resolve_target_hexes_for_los` (§8.1) | 1 | 26 |
| **TOTAL de la session** | **38** | **1 405** |

Les plus grosses : `_fight_build_pile_in_valid_destinations` (182 l.),
`_fight_plan_consolidation_destinations` (258 l.), `_fight_pile_in_bfs_numpy` (110 l.),
`_dump_los_contradiction_diagnostic` (94 l.), `_ai_select_shooting_target` (49 l.).
`_calculate_save_target` existait **en double** (fight + shooting) : les deux copies étaient
mortes.

**Preuve appliquée aux 35, dans cet ordre** : (a) zéro référence AST dans tout le dépôt (`Name`,
`Attribute`, `import`, alias) ; (b) zéro mention en littéral de chaîne, hors les trois
auto-références recensées (un message d'erreur, un renvoi de docstring, un commentaire
historique) ; (c) zéro occurrence dans `*.ts` / `*.tsx` / `*.json` / `*.html` / `*.js` ; (d)
aucune résolution dynamique possible — `grep -rnE "getattr\(|globals\(\)|eval\("` sur
`phase_handlers` ne rend aucun accès à nom calculé. Puis `git log -S"<nom>("` sur chacune : toutes
perdent leur dernier appelant dans un commit de nettoyage DÉLIBÉRÉ (`d69dfe0a` purge V10,
`64db328a`, `ea18e9ae` §0.39, `ac38a9c4`). Ce sont des résidus de purge, pas des appelants perdus.

🔴 **PIÈGE MESURÉ SUR CE BALAYAGE, à ne pas répéter.** La première version listait
`_is_in_enemy_engagement_zone` comme morte — une fonction que ce lot venait de corriger ET de
verrouiller par un test. Cause : le script énumérait ses fichiers avec `git ls-files`, qui
**ignore les fichiers non suivis** ; le test neuf, pas encore commité, n'entrait pas dans le
périmètre de recherche. Un outil de détection de code mort qui ne voit pas tous les appelants
invente des morts. Énumérer par parcours disque, jamais par l'index git.

🔴 **SECOND PIÈGE, même famille, sur la VÉRIFICATION cette fois.** Un lot de tests lancé en
`pytest <fichiers> | tail -12` a rendu `exit 0` sans avoir exécuté un seul test : la liste
contenait un chemin inexistant (`tests/unit/engine/test_debug_los.py` — le fichier est sous
`tests/unit/ai/`), pytest est sorti en erreur immédiatement, et **le code de sortie d'un pipeline
shell est celui de sa DERNIÈRE commande** — donc celui de `tail`, toujours 0. Le lot a été
compté vert deux fois avant que la sortie vide ne trahisse le problème. Règle : capturer `$?` de
`pytest` lui-même (rediriger vers un fichier, puis lire), jamais à travers un tube ; et se méfier
d'une sortie de test VIDE autant que d'une sortie rouge.

**Trois renvois devenus pendants ont été traités avec les suppressions** : le docstring de
`_fight_footprint_has_enemy_hex_contact` (pointait vers un jumeau par-ancre supprimé), celui de
`_move_preview_footprint_span` (« alignée sur `charge_handlers._charge_base_diameter` », lui aussi
mort), et le libellé `FIGHT_CONSOLIDATION_PLAN` de `perf_timing.py`. Le commentaire de
`w40k_core.py:5368` est CONSERVÉ : il explique pourquoi un contrôle a été retiré sciemment, ce que
CLAUDE.md demande de garder.

**Leçon, à ajouter à la méthode pour le prochain lot** : l'étape « code mort » doit être faite
AVANT le premier correctif, pas découverte en relecture. Sur ce dépôt le taux est réel — le lot
charge : 1 fonction morte sur 13 sites ; le lot `units_cache` : 2 fonctions mortes déjà supprimées
en amont (`_has_los_to_enemies_within_range` ×2) **plus** ces deux-ci trouvées trop tard.


### 8.3 — Le même piège, une troisième fois, et masqué par mon propre verrou

`_fight_compute_pile_in_footprint_zone` faisait partie des **7 sites de Forme A** traités en T1 :
corrigée, puis verrouillée par un test avec mutation ROUGE. Elle était **morte**.

Son unique appelant était `_fight_v11_pile_in_present`, elle-même sans appelant — donc morte
TRANSITIVEMENT, et depuis avant ce lot. Le balayage AST ne l'a pas vue **parce que mon propre test
la référençait** : un test suffit à faire passer une fonction morte pour vivante aux yeux d'un
détecteur qui compte les références. C'est la troisième occurrence du même défaut dans cette
session (après `_resolve_target_hexes_for_los` et `_fight_plan_consolidation_destinations`), et la
plus instructive : **l'outil de détection doit exclure les fichiers de test du décompte des
appelants**, ou au minimum les compter séparément. Fonction, test et libellé perf
`FIGHT_CONSOLIDATION_FP_ZONE` supprimés.

**Correctif de comptage** : la Forme A ne comptait donc que **6 sites vivants**, pas 7.

### 8.4 — Plomberie frontend V10 morte (PARTIELLEMENT TRAITÉE — lot à part ouvert)

Deux clés de `game_state` n'ont plus **aucun écrivain** côté moteur :
`fight_pile_in_footprint_zone` et `_fight_v11_pile_in_dests`. Leur seul producteur était
`_fight_v11_pile_in_present`, supprimée ici — mais elle était **déjà inatteignable**, donc ces
clés n'étaient déjà plus alimentées : la suppression rend la panne visible, elle ne la crée pas.

Conséquences, à arbitrer hors de ce lot :
- `_fight_v11_clear_pile_in_preview` (`fight_handlers.py`, 4 appelants) ne fait plus que `pop`
  deux clés que personne n'écrit — un no-op ;
- le frontend lit `fight_pile_in_footprint_zone` — mais **uniquement dans sa branche V10**
  (`useEngineAPI.ts`, sous `data.result?.waiting_for_pile_in && data.result?.valid_pile_in_destinations`),
  clés que le moteur ne produit plus non plus.

🔴 **CORRECTION d'une affirmation trop rapide de la première rédaction de ce §.** Il y était écrit
que « ce voile ne peut donc plus s'afficher ». **C'est FAUX, et vérifié** : l'aperçu du pile-in
PvP passe par le chemin **V11 par-figurine**, `pile_in_model_move: True`
(`fight_handlers.py`, produit et vivant) + `plan_state`, que le frontend traite dans une branche
qui PRÉCÈDE explicitement les branches V10 (son propre commentaire le dit). L'aperçu fonctionne.

La leçon est la même que celle du §8 : « plus d'écrivain » ne se conclut pas en « la
fonctionnalité est perdue » sans avoir cherché si un AUTRE chemin la sert. Constater la mort d'un
symbole n'est pas constater la mort d'une fonctionnalité.

**Rien n'est donc cassé, ni par ce lot ni avant lui.**

**SUITE DONNÉE (2026-08-05)** — un lot dédié a été ouvert, et le périmètre réel s'est révélé
**bien plus large** que les « 4 points » annoncés ici : 3 clés mortes (pas 2), 2 branches TS
(pile-in ET consolidation), et surtout **2 modes UI devenus inatteignables**
(`pileInPreview` / `consolidationPreview`) dont dépendent ~26 sites de lecture, 2 handlers et des
props threadées dans `BoardPvp.tsx` (12 223 lignes).

Déjà fait, commit `7b5871dc`, branche `worktree-charge_collision_et_menage_v10`, **non mergé** :
le moteur (`_fight_v11_clear_pile_in_preview` + ses 4 appels) et les 2 branches V10 du hook.
Vérifié pyright/pytest/tsc ; **pas** par un essai PvP.

Le détail exploitable — chaîne morte tracée, découpage, pièges d'outillage — est dans
[`A_faire/menage_v10_pile_in_et_perf_charge_2026-08-05.md`](A_faire/menage_v10_pile_in_et_perf_charge_2026-08-05.md).


---

## 9. Effets de bord du lot hors « repli » — signature changée, et un gaspillage NON traité

Deux passes `/simplify` ont produit des changements qui ne sont pas des corrections de repli et
qui doivent être trouvables :

**`_hex_legal_for_charge` a changé de signature.** Elle est appelée **par cellule** dans les deux
BFS de `charge_build_valid_plan` (jusqu'à ~14 641 itérations par anneau, chiffre porté par le
commentaire du fichier). Elle y résolvait à chaque cellule : le joueur de l'escouade chargeuse,
puis `_enemy_squad_ids` — un **balayage complet de `units_cache`** — puis un lookup par ennemi.
Ces trois choses sont invariantes sur tout le plan (rien n'écrit dans `units_cache` entre le début
du plan et la fin des BFS). Elles sont désormais résolues **une fois** dans l'appelant et passées
en paramètre `non_target_enemy_entries`. Les paramètres `target_squad_ids` et `our_player` ont
disparu de la signature : ils ne servaient plus qu'à construire cette liste.

Mesure : 1 balayage de `units_cache` au lieu de ~14 641, et `E` lookups au lieu de ~14 641 × `E`.
⚠️ Le lot `units_cache` avait **aggravé** ce site avant de le corriger (`require_unit_from_cache`
coûte plus qu'un `.get()` sur une variable locale) : remplacer un repli par un `require` sur un
chemin chaud oblige à regarder la boucle englobante, pas seulement la ligne.

🔴 **CE QUI N'A PAS ÉTÉ TRAITÉ, et qui n'est pas une dette de ce lot mais doit être visible** :
dans la même fonction, la boucle de collision
`for _sid, entry in entries_on_battlefield(units_cache, exclude_id=squad_id)` rescanne elle aussi
`units_cache` en entier **à chaque cellule**, avec un `entry_footprint(entry)` par entrée. Même
ordre de grandeur que ce qui vient d'être corrigé, et **antérieur à ce lot** (le `.get()` d'origine
ne le rendait pas moins cher). Le corriger proprement demande de précalculer l'union des hexes
occupés en un `set` avant les BFS — une transformation sémantique, pas un hissage, sur un chemin
chaud qui mérite une mesure avant/après. **À traiter comme un sujet en soi** — lot ouvert, worktree `perf_collision_charge`, protocole de
mesure et benchmark dans
[`A_faire/menage_v10_pile_in_et_perf_charge_2026-08-05.md`](A_faire/menage_v10_pile_in_et_perf_charge_2026-08-05.md)
(lot B). **Rien n'a encore été mesuré ni corrigé.**

**Le contrat de `is_unit_alive` est désormais écrit dans son docstring** (`shared_utils.py`) :
« un `True` PROUVE la présence dans `units_cache` ». C'est ce qui autorise les sites en aval à
utiliser `require_unit_from_cache` sans repli, et ce qui explique que leur `raise` y soit
statiquement inatteignable. Les commentaires qui recopiaient cet argument y renvoient maintenant
au lieu de le répéter.
