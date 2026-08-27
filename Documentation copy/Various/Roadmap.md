# Roadmap Démo Jouable Boîte de Base 40k-like

---

## Palier 0 – État actuel (base)

**Objectif :** Stabiliser le moteur et vérifier la logique fondamentale.

**Ce que tu as déjà :**

* Backend Python stable, frontend simple pour l’affichage
* Unité d’Intercessors vs Tyranides (Hormagaunts + Guerriers Tyranides)
* Plateau hex simple
* Règles spéciales loguées et testées sur 10k+ épisodes
* IA minimale fonctionnelle (agent + meta-agent) mais apprend peu

**Livrable :** Partie jouable sur 1 unité par faction, logs complets, sans crash.

**Tests :**

* Vérification cohérence des règles
* Vérification occupation hex
* Simulation de milliers de tours pour détecter erreurs

**État actuel (vérifié code — 2026-07-05)** : Moteur complet et stable (`engine/`), phases `deployment/command/move/shoot/charge/fight` (`action_decoder.py:35`). Déploiement actif et fonctionnel via `execute_deployment_action` + système de plans/formations (`deployment_handlers.py`). Plateau hex complet (`hex_utils.py` : coords cube, LOS, pathfinding). Logs `step.log` + `analyzer.py` en place. Aucun manque bloquant.
> Audit de conformité règles↔code détaillé par phase : `Documentation/Various/conformite_regles.md` (2026-07-05). Écarts majeurs : Feel No Pain absent, règles d'armes (RAPID FIRE/HEAVY/TORRENT/DEVASTATING…) inactives en prod, pas de Command Points.

**État de complétion : ~85%**

## Palier 1 – IA réellement apprenante (unités simples)

**Objectif :** Transformer l’agent en IA capable d’apprendre et prendre des décisions cohérentes.

**Tâches :**

1. Adapter l’encoding de l’état pour que toutes les unités et figurines aient leurs stats + positions
2. Renforcer le meta-agent pour gérer plusieurs unités Tyranides simultanément
3. Implémenter apprentissage RL (PPO ou DQN selon complexité du state space)
4. Mettre en place replay buffer / rollouts pour apprentissage incrémental
5. Tests unitaires et intégration sur matchs simples

**Livrables :**

* IA qui joue et prend des décisions cohérentes sur unités simples
* Partie jouable stable avec logs complets

**Tests / Critères :**

* Winrate >50% contre IA basique
* Logs stables et sans crash
* Partie jouable sans erreurs critiques

**État actuel (vérifié code — 2026-07-05)** : MaskablePPO réel (`train.py:80`), bots d'éval nombreux (`evaluation_bots.py` : Random/Greedy/Defensive + 5 autres), TensorBoard + `metrics_tracker.py`, déploiement actif en training.

> Architecture mono-agent assumée : un unique agent `CoreAgent` gère tous les types d'unité (`unit_registry.py:722` `_generate_advanced_agent_key` → `CoreAgent`, modèles dans `ai/models/CoreAgent/`). Choix délibéré : plus efficace à entraîner qu'un agent par type d'unité (mutualisation de l'expérience, pas de fragmentation du signal d'apprentissage). Le meta-agent gère la coordination de plusieurs unités au sein de cet agent unique.

**État de complétion : ~65%**

> Zone critique restante : Palier 2 (multi-figurines / cohésion / décision IA par figurine).

---

## Palier 2 – Gestion d’unités multi-figurines et cohésion

**Objectif :** Chaque unité est composée de figurines individuelles, avec règles de cohésion et mouvements coordonnés.

**Tâches :**

1. Définir la structure des unités (chaque figurine avec stats + position)
2. Implémenter règles de cohésion (pas de déplacement isolé hors formation)
3. Gérer l’occupation des hex pour chaque figurine/unité
4. Adapter l’IA pour prendre des décisions au niveau unité + figurines
5. Tests croisés avec règles spéciales

**Livrables :**

* IA capable de gérer toutes les figurines d’une unité
* Parties stables, cohésion respectée, occupation hex correcte

**Tests / Critères :**

* Cohésion respectée dans tous les mouvements
* IA capable de gérer toutes les figurines d’une unité
* Occupation hex correcte et sans chevauchement
* Logs et replay valides

**État actuel (vérifié code — 2026-07-05)** :
- ✅ Modèle par-figurine réel : chaque fig a stats + position propres (`shared_utils.py:464` `_build_models_for_unit`), squads hétérogènes gérés.
- ✅ Occupation / collisions par empreinte socle-à-socle (`is_footprint_placement_valid`, `candidate_overlaps_any_unit`).
- ✅ Pipeline combat par-figurine PvP HUMAIN complet et câblé : tir, fight, pile-in/consolidation, allocation manuelle des pertes — backend (`shared_utils.py`, `fight_handlers.py`) + frontend (`BoardPvp.tsx`). C'est le gros du travail récent, bien branché.
- ⚠️ Cohésion "molle" : calcul par-fig OK (blocage preview/commit + pénalité reward), MAIS `end_of_turn_coherency_removal` (`shared_utils.py:7571`) est défini et JAMAIS appelé → la vraie règle 40k (destruction des figs hors-cohésion en fin de tour) n'est pas appliquée.
- ❌ L'IA ne décide PAS au niveau figurine : translation rigide d'ensemble (`movement_handlers.py:1065`), ciblage au niveau unité. Le placement libre par-fig est réservé au joueur humain. → objectif "IA capable de gérer toutes les figurines" NON atteint côté décision tactique.
- ❌ Quasi pas de tests dédiés cohésion/multi-fig.

**État de complétion : ~55%** (combat par-fig humain fait ; restent : cohésion dure fin de tour + décision IA par figurine)

> Zone critique : si l’IA multi-figurines ou cohésion échoue, le jeu n’est plus jouable.
> Points bloquants restants ciblés : (1) câbler `end_of_turn_coherency_removal`, (2) décision IA par figurine.

---

## Palier 3 – Modes de jeu et scoring

**Objectif :** Ajouter des modes intéressants pour joueurs débutants et expérimentés.

**Tâches :**

1. Mode 1v1 “boîte de base”
2. Mode survie avec vagues successives
3. Leaderboards et scoring simple
4. Replay system pour analyser parties
5. Vérification compatibilité avec toutes les unités et règles

**Livrables :**

* Partie jouable complète avec scoring et rejouabilité
* Replays enregistrés et accessibles

**Tests / Critères :**

* Mode 1v1 jouable et équilibré
* Survie avec vagues successives fonctionnelle
* Leaderboard mis à jour correctement
* Replays valides et exploitables

**État actuel (vérifié code — 2026-07-05)** :
- ✅ Mode 1v1 PvP "boîte de base" (`api_server.py:724`, `BoardPvp.tsx`, table SQL `game_modes`) — cœur du palier.
- ✅ Scoring objectifs / VP (`game_state.py:1893`, testé `test_objective_scoring.py`).

> HORS SCOPE (features différées, ne comptent PAS dans la complétion) :
> - Mode survie / vagues successives : déjà amorcé côté code ("endless_duty", `services/endless_duty_runtime.py`) mais considéré comme feature à finaliser plus tard.
> - Leaderboards / classement joueurs : à ajouter plus tard.
> - Replay system : déjà amorcé (`ai/game_replay_logger.py`, `BoardReplay.tsx`) mais considéré comme feature à finaliser plus tard.

**État de complétion : ~90%** (scope réduit au mode 1v1 + scoring ; les 3 items ci-dessus sont différés)

---

## Palier 4 – UX léger / polish

**Objectif :** Rendre le jeu plus clair et agréable visuellement.

**Tâches :**

1. Tooltips et highlights pour règles spéciales
2. Stabilisation des logs et performances
3. Préparer captures/vidéos pour démonstration

**Livrables :**

* Démo jouable “propre” prête pour présentation ou portfolio

**Tests / Critères :**

* Affichage clair des règles
* Logs et performance stables
* Démo fonctionnelle et prête à montrer

**État actuel (vérifié code — 2026-07-05)** : Conforme. Tooltips règles spéciales (`UnitStatusTable.tsx` + `unit_rules.json`/`weapon_rules.json`, `TooltipWrapper.tsx`), highlights BoardPvp (cohésion, move preview, probabilité de blessure). Frontend riche : ~15 composants, 7 hooks, LOS accéléré WASM, rosters multi-factions. Rien de bloquant.

**État de complétion : ~85–90%**

---

## Palier 5 – Subdivision hex (optionnel, visuel)

**Objectif :** Rendu proche “sans quadrillage” pour un aspect visuel plus proche du jeu final.

**Tâches :**

1. Diviser chaque hex en 10×10 sous-hex
2. Adapter occupation et collisions
3. Vérifier line-of-sight et pathfinding

**Livrables :**

* Rendu visuel amélioré
* Moteur et IA inchangés

**Tests / Critères :**

* Occupation et collisions correctes
* Ligne de vue calculée correctement
* Visuel “sans quadrillage” agréable

**État actuel (vérifié code — 2026-07-05)** : Implémenté et actif. `inches_to_subhex:10` sur board `44x60x10` (`config/board/*/board_config.json`), point de conversion unique documenté (`ENGAGEMENT_NORM_HEX_WIDTH = 1.5`). Tout le pipeline backend écrit en sous-hex : occupation/empreintes (`hex_utils.py:1034+`), combat/portées (`combat_utils.py:350+`), zone d'engagement, LOS par footprint, pathfinding wavefront (`movement_handlers.py:1645`). Data-driven : `inches_to_subhex:1` désactive la subdivision. Frontend miroir (`hexFootprint.ts`).

**État de complétion : 95–100%**

---

# Conseils pratiques

1. Ne pas subdiviser les hex avant Palier 2 terminé.
2. Itérations courtes et tests fréquents pour chaque palier.
3. Scope strict : ne pas ajouter de nouvelles unités ou règles avant démo jouable.
4. Logs et replay indispensables pour debugging et démonstration.
5. 60% critique : Palier 2 – IA multi-figurines et cohésion, zone à surveiller absolument.
