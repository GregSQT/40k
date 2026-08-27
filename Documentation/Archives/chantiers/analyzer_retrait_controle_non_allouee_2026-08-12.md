# « Attaque non allouée, cible vivante » : un contrôle que le journal ne peut pas rendre (2026-08-12)

## Le point de départ

Le rapport du 2026-08-12 comptait **2** « attaque non allouée alors que la cible a survécu » côté
P2. Le contrôle (41ter) recoupait chaque ligne `Save [NOT ALLOCATED]` avec l'état de la cible à la
fin de l'activation de l'attaquant. Question posée : ces 2 cas sont-ils réels ?

## Ce qui a tranché : le moteur, pas le journal

`Save [NOT ALLOCATED]` a **un seul producteur** — `step_logger._save_segments`, quand le seuil de
sauvegarde est absent du record. Ce seuil n'est écrit qu'à l'allocation
(`_resolve_one_manual_wound`). Et **un seul chemin** laisse une blessure sans allocataire :
`_mark_manual_overkill_wasted`, atteint uniquement quand `_current_live_group` ne trouve plus un
seul groupe d'allocation vivant. Or les groupes sont construits sur TOUTES les figurines vivantes
de la cible au début du lot (`_build_alloc_groups`), et l'index ne franchit un groupe que s'il est
mort.

> Non alloué ⟺ escouade cible entièrement détruite. Sans exception dans le code.

Le contrôle ne pouvait donc jamais dénoncer le moteur : il opposait la règle 05 à l'état
**reconstruit** par l'analyzer, et ne signalait que les dérives de cette reconstruction.

## Les mesures

| Source | Résultat |
|---|---|
| Rapport 12 h 23 (run perdu depuis) | 2 signalements — issus d'**une seule** activation (les 2 tirs de `Smite (focused witchfire)`, NB:2) — et **1 « mort fantôme »** en §2.8 |
| Run 14 h 14, compteur de l'analyzer | **15** signalements, soit **3 activations** (E212, E404, E416), toutes en T5 P2 |
| Run 14 h 14, arbitre indépendant sur les instantanés `T{n} STATE:` du moteur | 1747 lignes `NOT ALLOCATED` → **1109 cible bien détruite, 0 cible vivante**, 638 indécidables |

Les 3 activations signalées tombent **toutes** dans les 638 : fin d'épisode, aucun instantané pour
recaler l'état reconstruit avant le verdict. Dans les trois, la cible que l'analyzer croit vivante
est au reste minimal (1 à 2 figurines, 1 à 2 PV) — signature d'une sous-application de dégâts. Le
plus net : E416, escouade 5 (7 figurines), **14 PV de dégâts journalisés** dans l'épisode, et
l'analyzer la tient encore pour 2 figurines vivantes.

## La livraison

- `ai/analyzer_allocation.py` supprimé, avec ses 4 sites d'appel (tir, mêlée, fin d'épisode,
  vidage de fin de fichier), ses 2 compteurs, leurs `first_error_lines` et leurs 2 blocs de
  rapport. Aucune clé morte laissée à sommer dans les totaux — c'est la leçon du vert vacant V2
  (`fight_from_non_adjacent`, 2026-08-10).
- L'invariant 05 est verrouillé côté moteur :
  `tests/unit/engine/test_attack_allocation_contract.py` — 3 tests × 2 chemins d'allocation. Le
  pool restant EST perdu quand la cible tombe, il ne l'est JAMAIS tant qu'une figurine vit, et une
  touche ratée n'entre pas dans le pool (contre-épreuve : sans elle, le deuxième test passerait
  faute de blessures).
- **Le miroir tir/mêlée est joué, pas déduit.** `FIGHT_CTX` délègue aujourd'hui à la même boucle
  d'allocation que le tir (`_manual_allocation_step`) et ne surcharge pas `resolve_wound_fn` —
  mais `HAZARD_CTX`, lui, le fait déjà. Un test de tir seul serait donc resté vert le jour où la
  mêlée se dote de son propre résolveur. Chaque test passe par le VRAI point d'entrée de chaque
  phase (`build_manual_shoot_allocation` / `build_manual_fight_allocation`).
- Verrou prouvé : défaut réintroduit deux fois dans `shared_utils.py` (arrêt d'allocation après la
  première blessure ; marquage `wasted` retiré) → tests ROUGES à chaque fois, sur les DEUX chemins,
  verts après remise en état.

## Ce qui reste vrai pour la suite

Le piège de méthode qui avait coûté **334 fausses erreurs** à la première version du contrôle
(2026-08-11) reste valable pour tout futur contrôle d'allocation : **l'ordre des LIGNES n'est pas
l'ordre d'ALLOCATION** — le pool est trié par jet de sauvegarde croissant (05.04) et les lots
s'enchaînent par profil d'arme (04.03). Une attaque loguée tôt peut être résolue tard.

Et la §2.8 (« mort fantôme ») reste le témoin à regarder AVANT de croire un contrôle qui dépend de
l'état reconstruit : c'est elle qui a donné le fil de celui-ci.
