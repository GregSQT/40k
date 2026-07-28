# Observation de la phase de déploiement — déficiente (chantier ouvert)

> **Origine** : extrait de [`V11_audit_observation.md`](../Implémenté/V11_audit_observation.md) §11
> (archivé le 2026-07-28). C'était le seul point **actionnable** restant de cet audit ; il est
> sorti ici pour ne pas rester noyé en fin d'un document d'archive.
> **Constats re-vérifiés dans le code le 2026-07-28** — le point 3 d'origine était inexact, il est
> reformulé ci-dessous.

## Contexte

Le déploiement consomme le **même** pipeline d'observation que le jeu
(`build_squad_observation` + `build_squad_grid`, cf. [w40k_core.py](../../../engine/w40k_core.py)
`_build_observation`), alors que la décision qu'il porte n'a rien à voir : il ne s'agit pas de
bouger/tirer/charger une escouade en place, mais de **choisir où poser une unité qui n'est pas
encore sur le plateau**. Résultat : l'agent déploie quasiment à l'aveugle.

L'espace d'action du déploiement = **5 slots** (`DEPLOY_SLOT_BASE = 4`, `DEPLOY_SLOT_COUNT = 5`,
[macro_intents.py](../../../engine/macro_intents.py)).

## Les défauts (vérifiés)

### 1. 🔴 L'observation décrit une unité qui n'est pas forcément celle qu'on déploie

`_build_observation` construit l'obs pour `next(iter(units_cache.keys()))` — la **première clé du
cache d'unités**, tous joueurs confondus, déployées comme non déployées
([w40k_core.py](../../../engine/w40k_core.py), branche `phase == "deployment"`).

Le masque d'action, lui, prend `eligible_units[0]`, issu de
`deployment_state["deployable_units"][current_deployer]`
([action_decoder.py](../../../engine/action_decoder.py),
`_get_eligible_units_for_current_phase` / `build_action_mask`).

**Rien ne garantit que les deux désignent la même unité.** C'est le même motif de défaut que D1
(désalignement obs ↔ action) corrigé pour les slots ennemis : l'agent décrit A et agit sur B.
→ **Correctif minimal, indépendant du reste** : faire lire à l'obs la même source que le masque
(`deployable_units[current_deployer][0]`), source unique.

### 2. 🔴 Grille égocentrique dégénérée (centrée hors plateau)

Une unité non déployée a une position négative : `create_unit` écrit
`"deployed_on_turn": None if int(config["col"]) < 0 else 0`
([game_state.py](../../../engine/game_state.py)) — `col < 0` **est** le marqueur « pas sur le
board ». Or `build_squad_grid` centre la grille sur `active_entry["col"] / ["row"]`
([observation_builder.py](../../../engine/observation_builder.py)).

→ La grille est centrée sur des coordonnées hors plateau : tous les canaux (murs, alliés, ennemis,
objectifs, couvert, coût de move) sont vides ou tronqués. L'agent ne voit **pas le terrain** au
moment précis où il choisit son point d'entrée dans la partie.

→ **Piste** : centrer la grille sur la **zone de déploiement** du joueur (ou sur le barycentre des
hexes candidats) au lieu de l'ancre de l'unité, tant que `deployed_on_turn is None`.

### 3. ⚠️ Les hexes candidats ne sont pas décrits (reformulé — l'énoncé d'origine était faux)

**Ce qui était écrit et qui est FAUX** : « les 5 actions = les 5 premiers hexes valides triés ».
En réalité les 5 slots sont **5 stratégies tactiques** évaluées sur **tous** les hexes valides
(`_select_deployment_hex_for_action`, [action_decoder.py](../../../engine/action_decoder.py)) :

| Action | Stratégie |
|---|---|
| 4 | front agressif |
| 5 | pression sur objectif |
| 6 | sûr / cohésion |
| 7 | flanc gauche |
| 8 | flanc droit |

**Ce qui reste vrai, et qui est le vrai défaut** :
- l'observation ne décrit **aucun** des hexes que ces stratégies vont choisir (position, distance
  aux objectifs, couvert, exposition LoS aux ennemis déjà posés) — alors que le décodeur, lui,
  calcule déjà tout ça dans son cache de scoring (`_get_or_build_deployment_scoring_cache` :
  `los_exposure_by_hex`, `potential_los_exposure_by_hex`, `ally_col_counts`, centres d'objectifs) ;
- le masque n'ouvre que `min(5, num_hexes)` slots : quand il reste moins de 5 hexes valides, ce
  sont les **stratégies d'indices bas** qui survivent, pas les plus pertinentes — le lien
  slot ↔ stratégie n'est plus stable en fin de déploiement ;
- le choix final de l'hexe reste une **heuristique du moteur**, pas une décision de l'agent.

→ **Piste** : exposer par slot le résumé déjà calculé par le cache de scoring (l'hexe que la
stratégie N sélectionnerait, et ses caractéristiques). Aucune nouvelle géométrie à écrire — c'est
une lecture du cache existant, donc source unique préservée.

## Périmètre / séquencement

- Les points **1** et **2** sont des corrections indépendantes et peu coûteuses ; le point **3**
  est une extension de contrat d'observation (change `obs_size` → retrain).
- Traité **séparément** de la refonte du vecteur de jeu (livrée, cf.
  [`V11_entity_encoder_pointer.md`](../V11_entity_encoder_pointer.md) et
  [`AI_OBSERVATION.md`](../../AI_OBSERVATION.md)).
