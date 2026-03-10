# Jeu d'essai – Fonctionnalité représentative (REV2)

Le référentiel d'évaluation demande la **présentation d'un jeu d'essai** pour une fonctionnalité représentative, avec : **données en entrée**, **données attendues**, **données obtenues**, **analyse des écarts**.

---

## Recommandation : présenter Analyzer.py et coupler avec une vérification visuelle

**Pour la section « Jeux d'essai » du mémoire (vers p. 49)** : utiliser comme **jeu d'essai représentatif** l’analyse des logs d’entraînement par `ai/analyzer.py`, puis **coupler** avec une **vérification visuelle** (replay ou partie courte). Cela met en avant la conformité aux règles métier (REAC/plan de tests) et la traçabilité.

1. **Entrée** : fichier `step.log` produit par une campagne de test (ex. `ai/train.py --agent … --test-only --step --test-episodes 100`).
2. **Traitement** : exécution de `python ai/analyzer.py step.log` ; lecture du rapport (violations par phase, métriques).
3. **Résultat attendu** : 0 violations sur les phases mouvement / tir / charge / combat si le moteur est conforme.
4. **Résultat obtenu** : copier les chiffres réels du rapport (ex. « Mouvement: 0, Tir: 0, Charge: 0, Combat: 0 » ou détail des métriques).
5. **Vérification visuelle** : en complément, lancer une partie courte (ou un replay) et vérifier à l’écran que les transitions de phase et les actions (déplacement, tir, etc.) correspondent bien au comportement attendu. En une phrase dans le mémoire : « Une vérification visuelle (partie PvE ou replay) confirme l’absence d’anomalie sur les phases et les actions. »

---

## Exemple rédigé : Analyzer.py + vérification visuelle

*À insérer dans le mémoire, section Jeux d'essai (vers p. 49), sous-partie « Jeu d'essai – Fonctionnalité représentative ».*

### Contexte

Fonctionnalité choisie : **validation de la conformité du moteur aux règles métier** via l’analyse des logs d’entraînement (`ai/analyzer.py`) et une **vérification visuelle** (partie ou replay). Cela illustre le plan de tests (scripts de conformité, traçabilité) et la compétence « Préparer et exécuter les plans de tests ».

### Données en entrée

| Élément | Détail |
|--------|--------|
| Commande de génération du log | `python ai/train.py --agent Infantry_Troop_RangedTroop --training-config default --rewards-config Infantry_Troop_RangedTroop --scenario default --test-only --macro-eval-mode micro --test-episodes 100 --step` |
| Fichier produit | `step.log` (traces détaillées de chaque step : phase, action, unité, cible, etc.) |
| Commande d’analyse | `python ai/analyzer.py step.log` |

### Résultat attendu

- **Analyzer** : 0 violations pour les phases mouvement, tir, charge, combat (comportement conforme à AI_TURN.md).
- **Vérification visuelle** : lors d’une partie PvE ou d’un replay, les phases s’enchaînent correctement, les unités ne font pas d’actions invalides (ex. pas de tir sans ligne de vue, pas de mouvement vers hex adjacent ennemi).

### Résultat obtenu

*[À remplir après exécution réelle.]*

Exemple de remplissage :

- **Rapport analyzer** : « Mouvement: 0 violations, Tir: 0, Charge: 0, Combat: 0 » ; métriques d’usage des règles (ex. nombre d’activations par phase) cohérentes.
- **Vérification visuelle** : partie PvE jouée sur N tours ; aucune anomalie visible (transitions de phase, déplacements, tirs, charge, combat). Replay consulté pour un échantillon d’épisodes : cohérent avec le rapport analyzer.

### Analyse des écarts

- Si analyzer rapporte 0 violation et que la vérification visuelle ne montre rien d’anormal : **aucun écart** ; la conformité est validée pour la campagne testée.
- Si des violations apparaissent : indiquer brièvement la catégorie (ex. « 2 violations en phase tir »), la cause identifiée (ex. règle de ligne de vue) et la correction apportée (ex. mise à jour du handler ou des caches). Puis relancer analyzer et vérification visuelle pour confirmer.

---

## Alternative : Démarrage PvE + action mouvement

Si tu préfères un second exemple (ou un exemple complémentaire en annexe), tu peux garder le canevas « Démarrage PvE + une action mouvement » (entrée API, attendu, obtenu, écarts) comme dans la version précédente de ce fichier. L’important pour le REV2 est d’avoir **au moins un** jeu d’essai complet avec les quatre colonnes (entrée, attendu, obtenu, écarts) ; le choix « analyzer + vérification visuelle » est bien adapté à ton projet.
