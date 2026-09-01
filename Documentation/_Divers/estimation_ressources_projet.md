# Estimation ressources / temps / budget — Warhammer 40K Game Engine + IA

> Estimation réalisée en septembre 2026 par analyse statique complète du dépôt.
> Hypothèse : équipe externe partant de zéro (règles 40K disponibles, aucune architecture préexistante).

---

## 1. Volume de travail mesuré

### Lignes de code par module

| Module | Fichiers | Lignes | Rôle |
|---|---|---|---|
| `engine/` | 48 | 76 358 | Moteur de règles complet 40K 10e éd. |
| `ai/` | 42 | 42 760 | Pipeline RL : entraînement, policy, curriculum, analyzer |
| `frontend/src/` | 351 | 75 210 | Interface React/TypeScript : board, PvP, replay |
| `tests/` | 553 | 150 473 | Suite automatisée : 5 850+ fonctions de test |
| `services/` + `scripts/` | 58 | 28 392 | API Flask, outils, benchmarks |
| **Total code productif** | **1 052** | **~373 000** | |

Hors périmètre de cette estimation (non codé manuellement) : 5 031 fichiers JSON de config, 205 fichiers de documentation, 26 PDFs de règles officielles.

### Repères de complexité

- `engine/phase_handlers/shared_utils.py` : 14 618 lignes — utilitaires combat, LoS, engagement
- `frontend/src/components/BoardPvp.tsx` : 12 876 lignes — boucle de jeu PvP complète
- `engine/w40k_core.py` : 9 539 lignes — environnement gym, FSM de phases, observation dispatch
- `ai/train.py` : 5 896 lignes — entraînement MaskablePPO, curriculum, self-play
- `ai/analyzer.py` : 4 406 lignes — validation des parties contre le moteur de règles

---

## 2. Estimation du volume de travail

### Méthodologie

Estimation par module avec vitesse différenciée selon la complexité réelle, *non* une vitesse uniforme. La vitesse "lignes/heure" capture à la fois le temps d'écriture et le temps de conception locale, de débogage et de test immédiat — pas seulement la frappe.

| Module | Lignes | Complexité | Vitesse retenue | Heures |
|---|---|---|---|---|
| Moteur de règles (`engine/`) | 76 358 | **Très haute** | 7 lig/h | 10 900 h |
| RL/IA (`ai/`) | 42 760 | **Très haute** | 12 lig/h | 3 600 h |
| Frontend (`frontend/src/`) | 75 210 | Haute | 18 lig/h | 4 200 h |
| Tests (553 fichiers, 5 850 fonctions) | 150 473 | Moyenne | 35 lig/h | 4 300 h |
| API + scripts | 28 392 | Moyenne | 18 lig/h | 1 600 h |
| **Sous-total implémentation** | | | | **24 600 h** |

**Justification des vitesses :**

- **7 lig/h pour le moteur de règles** : chaque ligne implémente une règle issue des PDFs officiels. Il faut lire la règle, comprendre ses interactions avec les autres règles, concevoir la représentation en code, écrire le test, et vérifier le comportement. Les phases de charge, mêlée et tir comportent chacune ~6 000 lignes de logique interdépendante. La LoS 3D sur grille hexagonale avec terrain multi-niveaux est un problème de géométrie computationnelle non trivial. 7 lig/h est une estimation conservatrice — certaines parties (résolution d'engagement par-figurine, curriculum pile-in) tombent à 3-4 lig/h.

- **12 lig/h pour le pipeline RL** : concevoir un espace d'observation en `gym.spaces.Dict` avec encodeurs d'entités à poids partagés, une tête pointer sur résolution pleine du CNN, et un curriculum à 15 stades avec exploiteurs n'est pas de l'implémentation standard. La littérature ne donne pas de recette directement applicable à cet espace d'action (1 389 actions discrètes) combiné à ce domaine.

- **18 lig/h pour le frontend** : React/TypeScript sur une grille hexagonale avec SVG, gestion d'état PvP multi-phases, replay step-by-step et roster builder 6 factions. La complexité est réelle mais le domaine (web) est plus standardisé.

- **35 lig/h pour les tests** : écrire un test est plus rapide qu'écrire le code testé, mais 5 850 fonctions représentent un effort de conception non négligeable — définir les fixtures, les cas limites, les invariants à vérifier.

### Overhead à ajouter

**Phase de conception/R&D** (avant le premier commit productif) :

| Travail | Durée | Personnes | Équivalent |
|---|---|---|---|
| Lecture + spécification technique des 26 chapitres de règles | 2-3 mois | 1-2 seniors | ~0,4 PA |
| Architecture moteur : state, FSM phases, géométrie hex, résolution subhex | 1-2 mois | 2 seniors | ~0,3 PA |
| R&D RL : est-ce que MaskablePPO converge sur cet espace ? Quel espace d'obs ? Quelle archi policy ? | 2-3 mois | 1-2 ML engineers | ~0,5 PA |
| Architecture frontend + contrats API | 1 mois | 1-2 personnes | ~0,2 PA |
| **Total phase conception** | **4-5 mois** | | **~1,5 PA** |

Cette phase précède l'implémentation — elle n'en réduit pas la durée, elle l'empêche d'être mal orientée dès le départ.

**Overhead de reprises et dead-ends (+30% sur l'implémentation)** :

L'historique du projet documente les reprises majeures qu'une équipe partant de zéro rencontrerait inévitablement :
- Espace d'observation revu plusieurs fois (taille, schéma d'encodage, aliasing critique Phase 3)
- Pile-in/consolidation implémenté par-ancre puis refactorisé par-figurine
- Curriculum : incompatibilité résolution x1/x5 découverte tard (EntityRunningNorm dans le `.zip`)
- LoS 3D : deux approches testées avant la bonne (ancre vs par-figurine)
- Architecture policy : pointer-head n'est pas le premier réflexe, précédé d'une MLP plate

Ces reprises ne sont pas des erreurs évitables — elles sont inhérentes à la conception de systèmes complexes. 30 % est une estimation conservatrice pour ce type de projet.

24 600 h × 1,30 = **32 000 h ≈ 18,3 personnes-années (PA)**

**Total global : 18,3 + 1,5 = ~20 personnes-années**

---

## 3. Équipe et rémunérations (France, 2025)

Coûts en chargé employeur (brut × ~1,42 pour les charges patronales France).

| Poste | Niveau | Brut/an | Chargé/an | Rôle principal |
|---|---|---|---|---|
| Lead Architecte / Expert règles | Senior 8+ ans | 88 000 € | 125 000 € | Architecture globale, moteur de règles, géométrie hexagonale |
| ML/RL Engineer | Senior 5+ ans | 95 000 € | 135 000 € | Policy network, espace d'observation, curriculum, débogage training |
| Backend Engineer | Senior 6+ ans | 78 000 € | 111 000 € | Phase handlers, LoS 3D, API Flask |
| Frontend Engineer | Mid-Senior 5+ ans | 68 000 € | 97 000 € | Board hexagonal, PvP, replay |
| QA / Test Engineer | Mid 3+ ans | 50 000 € | 71 000 € | Conception et maintenance des 5 850 tests automatisés |
| PM / Tech Lead | Confirmé 5+ ans | 68 000 € | 97 000 € | Planning, coordination, gestion des risques, domaine 40K |
| **Coût moyen pondéré** | | | **~106 000 €/an** | |

**Note sur le ML/RL senior** : c'est le profil le plus rare et le plus cher de cette liste. Concevoir un espace d'observation `gym.spaces.Dict` à encodeurs partagés, une tête pointer sur CNN full-resolution, et un curriculum auto-play avec exploiteurs n'est pas enseigné en master standard. Ce profil est activement chassé par les GAFAM et les labs de recherche (DeepMind, Meta AI). En Île-de-France, 95 k€ brut est déjà un plancher compétitif.

---

## 4. Scénarios

**Contrainte de parallélisme** : le chemin critique (spécification règles → moteur → IA → frontend + tests) est largement séquentiel. On ne peut pas entraîner un agent avant d'avoir un moteur stable. On ne peut pas tester le frontend avant d'avoir une API. Au-delà de 6-7 personnes, la durée ne diminue plus significativement — elle augmente même (loi de Brooks : la coordination entre N personnes croît en N(N-1)/2).

Les totaux ci-dessous intègrent l'ensemble des coûts réels d'un projet en entreprise :

| | Lean | **Normal** | Accéléré |
|---|---|---|---|
| Équipe | 3-4 FTE | **6 FTE** | 9-10 FTE |
| Durée totale | 48-54 mois | **30-34 mois** | 22-26 mois |
| Salaires bruts (20 PA × coût moyen) | 2 000 000 € | **2 120 000 €** | 2 380 000 € |
| + Overhead organisation¹ (+18%) | 360 000 € | **382 000 €** | 428 000 € |
| GPU cloud (A100/H100, training curriculum) | 70 000 € | **120 000 €** | 160 000 € |
| Infra serveurs, licences, outils | 30 000 € | **40 000 €** | 50 000 € |
| Recrutement (~3% masse salariale) | 40 000 € | **60 000 €** | 80 000 € |
| Legal / RGPD (si produit commercial) | 20 000 € | **30 000 €** | 50 000 € |
| Provision risque (+22%)² | 534 000 € | **565 000 €** | 635 000 € |
| **Total** | **~3 054 000 €** | **~3 317 000 €** | **~3 783 000 €** |

¹ **Overhead organisation** : en solo, zéro réunion. En entreprise, les stand-up, planification de sprint, rétros, code reviews et montée en compétence à l'embauche (1-3 mois à 50% de productivité par personne) représentent facilement 15-20% du temps facturable. À cela s'ajoute l'écart entre 1 750 h/an théoriques et ~1 500 h réelles (congés, maladie, jours fériés).

² **Provision risque** : risques techniques non identifiés, turnover, retard de recrutement sur des profils rares (ML/RL senior). Taux standard pour un projet de cette complexité dans un environnement sans précédent direct.

Le scénario normal (6 FTE, ~32 mois) reste le plus efficace : durée raisonnable sans surcoût de coordination d'une grande équipe.

---

## 5. Synthèse

**Ordre de grandeur retenu : 3 à 3,8 millions d'euros, 2,5 à 3 ans.**

### Ce qui justifie ce chiffre par rapport à un projet web classique de même taille

1. **Le moteur de règles est un problème de spécification autant que de code** — 76 000 lignes qui implémentent fidèlement 26 chapitres de règles avec toutes leurs interactions. Il n'existe pas de librairie, pas de framework, pas de tutoriel pour ça.

2. **La phase R&D RL est incompressible** — concevoir un espace d'observation apprenable pour un problème de cette taille (1 389 actions, entités hétérogènes, géométrie spatiale) est un problème ouvert. La littérature ne fournit pas de solution directement applicable. Des mois de prototypage sont inévitables.

3. **Le ML/RL senior est structurellement rare** — la combinaison "comprend profondément PPO + peut concevoir une architecture pointer-head + peut déboguer un curriculum qui ne converge pas" est activement recherchée par les meilleurs employeurs mondiaux.

4. **Les 5 850 tests automatisés sont un actif, pas une dépense** — ils représentent ~4 300 heures de travail d'ingénierie et garantissent que les 26 chapitres de règles restent corrects à chaque modification. Un projet sans cette couverture accumulerait une dette de qualité équivalente.
