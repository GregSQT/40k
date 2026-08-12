# P3-0 — Retrait pour cohérence (03.03) : le choix passe au joueur et à l'agent

> Ouvert le 2026-08-12. Ligne ROADMAP : **§3 (suspendu à un jalon)** — déclencheur = le prochain
> dégel de `TOTAL_ACTION_SIZE`, groupé avec P3-4 / P3-5 / P3-6.
>
> **État : RIEN N'EST LIVRÉ.** Un premier câblage a été écrit puis **entièrement reverté** le
> 2026-08-12 (cf. §6) — aucune ligne de ce chantier n'est dans le code. Ce document porte la
> conception, les décisions prises, et ce que ce câblage a MESURÉ : c'est la seule trace, et elle
> évite de repayer l'exploration.

## 1. Ce qui ne va pas

Règle 03.03, étape End of Turn : « if one or more units on the battlefield are not in coherency,
those units' **controlling players must remove models from them**, one at a time, until they are in
coherency again. Models removed in this way are destroyed, but they do not trigger rules that apply
when a model is destroyed. »

Le moteur choisit à la place du joueur : `shared_utils.end_of_turn_coherency_removal` retire la
figurine la plus éloignée du centroïde (tie-break par index croissant).

**C'est vrai des DEUX côtés** — vérifié le 2026-08-12, et c'est le point que l'intuition inverse :
le PvP n'offre pas ce choix davantage que le gym. `grep coherency services/` → 0 hit ; aucune action
sémantique ; côté front, les `coherencyOk` de `useEngineAPI` sont ceux de la **validation du plan de
move** (le voile rouge), un autre moment de la règle. Les deux chemins de fin de combat
(`_fight_phase_complete`, `_fight_v11_phase_complete`) appellent le retrait automatique quel que soit
le mode.

Le critère automatique n'est pas neutre sur une escouade hétérogène : il retire la figurine la plus
isolée, alors qu'un joueur sacrifierait un socle de base pour conserver une arme spéciale. L'écart
porte sur la PUISSANCE conservée, pas seulement sur la position.

## 2. Ce qu'on livre

Le retrait devient un CHOIX, offert au contrôleur de l'escouade :
- **agent** : une tranche d'ids d'action dédiée, un id par ligne du bloc figurines de l'observation ;
- **joueur PvP** : la même désignation, par clic sur la figurine ;
- **sièges muets** (bot PvE) : tranchés par le critère géométrique actuel, comme
  `_resolve_faction_decisions_for_ai_seats` tranche 08.04 — sans quoi une partie bloque sur une
  décision que personne ne joue.

## 3. Décisions prises — tranchées, à ne pas rouvrir

### 3.1 Tranche d'ids DÉDIÉE, pas de réemploi des cellules de move (utilisateur, 2026-08-12)

`TOTAL_ACTION_SIZE` passe de **1139 à 1159** (20 ids, dérivés du nombre de lignes figurines).

L'alternative écartée était de tailler les ids dans la plage des cellules de move, comme les 8 slots
de déploiement (`DEPLOY_SLOT_BASE = 4`) — taille d'action inchangée, aucun retrain. Elle a été
rejetée sur la **qualité d'apprentissage**, pas sur le coût :

> les logits des slots de déploiement sortaient de la conv 1x1 « sur des cellules sans rapport avec
> les hexes candidats », et il a fallu ajouter `deploy_query_net` **plus** un routage par échantillon
> sur le bit `phase_deployment` pour le réparer (`ai/pointer_policy.py`, docstring de module).

Réemployer les cellules ici imposerait une **troisième** branche de routage dans ce même fichier —
celui qui, de son propre aveu, « échoue EN SILENCE si `log_prob`, l'entropie ou le masquage sont
faux ». Une tranche dédiée rend l'attribution des gradients structurelle au lieu de la conditionner
à un bit d'observation.

⚠️ Ce choix est ce qui met le chantier en §3 : il se paie en run `--new` complet.

### 3.2 Les logits sortent de la TÊTE POINTEUR, pas d'une ligne dense

`logit_i = (q · e_i)/√d` où `e_i` est l'embedding de la figurine `i`. Même raison que les slots
ennemis passés de 5 à 20 sans coût en paramètres : le nombre de candidats devient gratuit et ce qui
est appris sur une figurine vaut pour toutes. Une tête dense ré-apprendrait chaque index séparément,
et les index hauts (escouades de 12) seraient vus trop rarement pour être appris.

### 3.3 Les candidats sont des entités DÉJÀ OBSERVÉES

L'observation porte `self_models_cont` / `self_models_bin` (position relative, `fight_eligible`,
`in_enemy_ez`, `present`). C'est ce qui rend `CHOICE_k` inapplicable : `macro_intents` réserve ce
mécanisme aux décisions dont les candidats ne sont PAS observés, et il plafonne à
`MAX_DECISION_OPTIONS = 6` là où une escouade compte jusqu'à 12 figurines.

**Invariant D1, côté figurines** : le slot `i` désigne la LIGNE `i` du bloc figurines. Les
désolidariser ferait retirer une figurine différente de celle que l'agent a observée — sans qu'aucune
erreur ne soit levée, puisque les deux index sont valides.

### 3.4 Tous les socles vivants sont désignables

03.03 dit « remove models from them until they are in coherency again » sans restreindre lesquels.
Restreindre aux figurines que `coherency_violation_flags` marque reprendrait à l'agent une partie du
choix — précisément ce que ce chantier lui rend. La boucle termine : chaque retrait réduit
l'escouade, et elle s'arrête à une survivante.

## 4. Ce que le câblage a MESURÉ (2026-08-12) — à ne pas re-découvrir

Ces quatre points ne sont pas dans le code (tout a été reverté) et ne se déduisent d'aucune lecture
rapide. Ils sont la vraie valeur de ce document.

1. **L'extracteur JETTE les embeddings par figurine.** `ai/spatial_extractor.py` calcule
   `self_model_encoder(...)` puis n'en garde que l'agrégat `sm_agg = _masked_mean_max(...)` pour le
   tronc. Les ennemis et les candidats de déploiement, eux, voient leurs embeddings **par slot**
   partir en queue du vecteur de features, à destination de la tête pointeur. Brancher le pointeur
   sur les figurines exige donc d'élargir la sortie de l'extracteur (donc `features_dim`), en plus
   d'ajouter la requête dans `pointer_policy`. **C'est le vrai coût de T5, et il n'était pas dans
   l'estimation initiale.**
2. **L'ordre des lignes figurines devient opposable.** `ObservationBuilder._squad_models_for_observation`
   (statique, déterministe : tier de rôle, puis profil défensif dérogatoire, puis index de création)
   porte une docstring qui dit aujourd'hui « aucune action ne cible une figurine par son slot, donc
   réordonner ce bloc n'a pas d'effet de bord sur le masque ». **Cette phrase devient fausse** : elle
   doit être corrigée dans la même livraison, et l'ordre exposé en source unique (le câblage l'avait
   nommée `squad_model_slot_order`) lue par le builder, le masque et le décodeur.
3. **La troncature à `SQUAD_TOP_K` cesse d'être une simple perte d'observation** : au-delà, une
   figurine n'a plus de ligne, donc plus d'id d'action — elle devient inadressable. 20 couvre les
   rosters d'entraînement (max mesuré : 12 figurines vivantes), le dépassement est déjà logué.
4. **Le point d'arrêt de la phase existe déjà, et son contrat est écrit** : « `phase_complete` faux
   signifie que la phase attend une réponse » (`w40k_core.start_command_phase`). L'armement se pose
   là où le retrait automatique vit aujourd'hui — dans les DEUX chemins de fin de combat, juste avant
   la progression de joueur et avant le test de limite de tour — et la fin de phase se rejoue après
   chaque désignation, comme `command_phase_resume` est rejouée après chaque décision de 08.04.
   Deux gardes mesurées à cette occasion : lire le joueur d'une escouade dans **`units_cache`** et non
   dans la liste `units` (les fixtures minimales n'ont pas `unit_by_id`, et le cache est la source
   canonique) ; et le prédicat « ce siège décide-t-il ? » doit tester `gym_training_mode` AVANT
   `is_programmatic_owner`, qui rend `True` en gym pour les deux sièges.

## 5. Tranches

| # | Contenu | Note |
|---|---|---|
| T1 | Constantes : lignes figurines en source unique (`K_SELF_MODEL_SLOTS`), tranche d'ids, `TOTAL_ACTION_SIZE` 1159 | écrite puis revertée, cf. §6 |
| T2 | Moteur : état en attente, armement dans les deux fins de combat, résolution une figurine à la fois, sièges muets tranchés | idem |
| T3 | Masque + décodeur : exclusivité de la tranche (modèle = `oath_selection_slots`), slot → figurine | |
| T4 | Politique de bot d'évaluation | sans elle l'éval bloque |
| T5 | Extracteur (embeddings par figurine en queue) **+** tête pointeur | le morceau risqué |
| T6 | Observation : pendant la décision, le bloc figurines décrit l'escouade concernée | |
| T7 | PvP : endpoint + désignation par clic | aucun existant, flux entier à écrire |
| T8 | Tests de verrou, `analyzer_couverture.md`, ligne ROADMAP à jour | |

## 6. Ce qui a été écrit puis reverté, et pourquoi

T1 et T2 ont été écrits le 2026-08-12 puis **annulés avant tout commit**. Deux raisons, et elles sont
la règle plutôt que l'exception :

- une taille d'action dégelée que **rien ne joue** coûte un run `--new` pour zéro fonctionnalité ;
- un armement **sans décideur** en face fait bloquer la partie sur une décision que ni le masque ni
  l'UI ne peuvent répondre — pire que le défaut qu'il corrige.

Autrement dit : ce chantier n'a pas de livraison partielle sûre en dessous de T1→T4 (moteur + gym
complets). T5 à T7 peuvent suivre, T7 est indépendant du reste.

## 7. Critère de fin

- L'étape ne retire plus AUCUNE figurine sans qu'un décideur l'ait désignée (agent, joueur PvP), les
  sièges muets exceptés — et leur automatisme est alors explicite, pas subi.
- Le journal nomme la figurine retirée : la ligne `COHERENCY REMOVED … (03.03)` existe depuis le
  2026-08-12 et porte déjà les figurines (analyzer et replay la lisent).
- Un run `--new` mesure le win-rate : la taille d'action a changé, les modèles antérieurs ne sont
  plus comparables.
