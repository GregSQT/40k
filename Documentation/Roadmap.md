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

## **État de complétion : ~35–40%

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

**État de complétion : ~50%

> Début du travail sur la zone critique des 60%.

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

**État de complétion : 60%

> Zone critique : si l’IA multi-figurines ou cohésion échoue, le jeu n’est plus jouable.

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

**État de complétion : ~75%

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

**État de complétion : ~85–90%

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

**État de complétion : 95–100%

---

# Conseils pratiques

1. Ne pas subdiviser les hex avant Palier 2 terminé.
2. Itérations courtes et tests fréquents pour chaque palier.
3. Scope strict : ne pas ajouter de nouvelles unités ou règles avant démo jouable.
4. Logs et replay indispensables pour debugging et démonstration.
5. 60% critique : Palier 2 – IA multi-figurines et cohésion, zone à surveiller absolument.
