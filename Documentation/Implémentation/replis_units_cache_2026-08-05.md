# Replis silencieux sur `units_cache` — move / fight / shoot — 2026-08-05

**Chantier OUVERT, rien de livré.** Placé à la racine de `Implémentation/` parce qu'il porte du
travail à faire ET la preuve déjà acquise sur un premier module. Si tu préfères la convention
stricte du dépôt (`A_faire/` = backlog pur), il peut y descendre tel quel.

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

### Forme A — `entry_footprint(x) if x else <repli sur l'ancre>` — ~~9~~ **7** sites

**La plus dangereuse, et la plus rapide à traiter** : contrat identique à chaque fois, correctif
identique à celui du lot charge. Une empreinte de repli fait mentir la géométrie sans jamais crasher.

| Site | Fonction | Lecture |
|---|---|---|
| `fight_handlers.py:285` | `_fight_unit_is_hex_adjacent_to_enemy_footprint` | `unit_entry = units_cache.get(unit_id_str)` |
| `fight_handlers.py:302` | `_fight_pile_in_closest_enemy_snapshot` | `unit_entry = units_cache.get(unit_id_str)` |
| `fight_handlers.py:745` | `_fight_compute_pile_in_footprint_zone` | `cache_entry = units_cache.get(unit_id_str)` |
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

### Forme B — `if x is None: return <valeur>` — 14 sites

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

### Forme C — `if x is None: continue` — 6 sites

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

### Forme D — à lire avant de classer — 13 sites

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
| `shooting_handlers.py:3574` | `_resolve_target_hexes_for_los` | repli `occupied_hexes` |
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
| **T1** | **Forme A, 7 sites** (9 − les 2 du doublon `_has_los_to_enemies_within_range`, supprimé le 2026-08-05 : il était mort des deux côtés). Contrat déjà établi par le lot charge, correctif identique, risque le plus élevé (géométrie inventée sur trois phases). | 1 session |
| **T2** | Formes B + C, 20 sites. Un contrat par site ; attendre ~1/3 de légitimes. | 1 session |
| **T3** | Forme D, 13 sites. Lecture d'abord, classement ensuite. | 1 session |

Repère de coût : le lot charge (13 sites, 1 module) a consommé une session complète, investigation,
suppression de code mort, 4 tests et mutations comprises. `shared_utils.py` est le plus gros module
du dépôt — ne pas prendre les 42 en bloc.

**Ne PAS faire** : un balayage mécanique forme par forme sans contrat d'appelant. C'est l'erreur que
§3.2 de la campagne a explicitement refusée, et le lot charge a confirmé qu'un site sur trois n'est
pas à corriger.

---

## 6. Limites de preuve de ce document

1. **Aucune correction livrée.** Ce document est un inventaire, pas un rapport de travail.
2. **Le tri A/B/C/D est syntaxique**, pas sémantique : il classe la **forme** du repli, pas sa
   légitimité. Les deux ⚠️ signalés (`check_if_melee_can_charge`, `build_squad_action_mask`) sont
   des soupçons de légitimité, pas des verdicts — une liste d'audit est une liste de soupçons.
3. **Chiffre 42 vs 43** : le premier comptage annoncé en fin de lot charge disait 43. L'écart tient
   à la fenêtre de détection du script (4 vs 5 lignes après le lookup) ; le tri par site tranche de
   toute façon au cas par cas.
4. **Le dénominateur brut est 64** lookups `units_cache` sur les quatre modules ; 22 lèvent déjà ou
   portent `# get allowed`. Ce dénominateur est publié exprès (leçon §4.1 : un contrôle qui ne
   regarde rien répond « tout va bien »).
5. **Aucune vérification large** n'a été lancée : elle appartient à l'utilisateur (CLAUDE.md).
