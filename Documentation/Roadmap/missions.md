# Chantier : Force Dispositions & Missions

## Statut : EN ATTENTE — terrains à créer

---

## Décisions d'architecture

- **Un modèle par roster**, entraîné sur toutes les missions (pas un modèle par mission).
- **Mission dans l'obs** : `[disposition_self, disposition_opponent]` — 2 entiers encodés dans l'observation. L'agent lit son objectif comme il lit la carte.
- **Reward entièrement conditionnée par la mission** — pas de tronc commun à poids fixe. Les signaux denses (kills, position) existent mais leur poids dépend de la mission active. Un kill reward fixe indépendant de la mission crée un signal contradictoire (ex. chasser les kills sous Take and Hold).
- **Sampling à l'entraînement** : tirage aléatoire de `(disposition_self, disposition_opponent)` à chaque épisode. Pas un `mission: random` global — chaque roster a sa disposition tirée indépendamment.

---

## Périmètre V1 : 2 force dispositions

**Take and Hold** + **Purge the Foe** → 4 combinaisons de mission.

### Matrice

| Toi \ Adversaire   | Take and Hold        | Purge the Foe    |
|--------------------|----------------------|------------------|
| **Take and Hold**  | Battlefield Dominance *(mirror)* | Immovable Object |
| **Purge the Foe**  | Unstoppable Force    | Meatgrinder *(mirror)* |

### VP par mission

**Battlefield Dominance** (TaH vs TaH)
- End of turn R1–2 : +2VP si tu contrôles plus d'objectifs que l'adversaire
- End of Command phase R2+ : +3VP par objectif contrôlé ; +2VP cumulatif par objectif (hors home) si tu contrôles ton home objective

**Immovable Object** (TaH vs PtF)
- End of turn (tous rounds) : +3VP si tu contrôles ≥1 objectif central
- End of Command phase R2–4 : +5VP par objectif contrôlé (hors home)
- End of turn R5 : +5VP par objectif contrôlé (hors home)

**Unstoppable Force** (PtF vs TaH)
- End of turn (tous rounds) : +3VP si ≥1 unité ennemie détruite ce tour
- End of Command phase R2+ : +4VP par objectif contrôlé (hors home) ; +3VP si tu contrôles ≥1 objectif que tu ne contrôlais pas en début de tour (hors home)
- End of battle : +5VP si tu contrôles ≥1 objectif central

**Meatgrinder** (PtF vs PtF)
- End of turn (tous rounds) : +3VP si ≥1 unité ennemie détruite ce tour
- End of Command phase R2+ : +4VP par objectif contrôlé (hors home)
- End of turn R2+ : +5VP si plus d'unités ennemies détruites ce tour que d'unités alliées détruites au tour précédent ; +5VP si tu contrôles l'objectif home adverse

**Note** : aucune de ces 4 missions n'utilise d'operation markers ni de mécaniques spéciales (consecrated, triangulated, etc.). Elles dépendent uniquement de : objectifs contrôlés, kills, home objective.

---

## Prérequis identifiés

### 1. Terrains par mission — BLOQUANT
Chaque mission se joue sur un terrain spécifique. Les fichiers terrain (JSON config) sont à créer par le joueur pour chacune des 4 missions avant toute implémentation moteur.

### 2. Home objective — à implémenter
Le moteur n'a pas de notion de "home objective". Les deux briques existent séparément :
- Objectives : hex-sets via `objective_hex_zones()` (`engine/game_state.py:3578`)
- Deployment zones : polygones par joueur dans les JSON terrain (`deployment_zones` array)

Solution : intersection hex-set × polygone de déploiement au chargement du scénario → attribut `home_player` par objective.

---

## Plan d'implémentation (dans l'ordre)

**Étape 0** (utilisateur) : créer les terrains pour les 4 missions.

**Étape 1a** : classifier les objectives comme "home" au chargement — intersection hex/deployment zone, attribut `home_player` sur chaque objective.

**Étape 1b** : VP scoring des 4 missions dans le moteur — brancher les événements (end of turn, end of command phase, end of battle) sur les conditions VP de chaque mission.

**Étape 2** : Gym — ajouter `[disposition_self, disposition_opponent]` à l'obs + reward function conditionnée par la mission active + sampling aléatoire par épisode.

**Étape 3** : Training config — déclarer les force dispositions disponibles par roster.

**Étape 4** : Métriques — win-rate par combinaison de missions (4 lignes par roster) + VP breakdown kill/objectif/home par mission (détecter comportements parasites).

---

## Métriques de validation

- Win-rate par combinaison `(disposition_self, disposition_opponent)` — 4 lignes par roster.
- VP breakdown par mission : distinguer VP issus des objectifs mission vs kills vs home objective.
- Cas clé de validation : sous TaH vs PtF, l'agent TaH doit défendre les objectifs plutôt que chasser les kills même face à un adversaire agressif.
