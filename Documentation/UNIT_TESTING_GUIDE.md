# Guide expert des tests unitaires

Ce document explique :

1. le fonctionnement des tests unitaires (et leurs limites) ;
2. comment les mettre en place proprement sur l'ensemble de l'application ;
3. comment industrialiser leur exécution dans le workflow d'équipe.

Le périmètre couvre le moteur de jeu (`engine/`), l'IA (`ai/`), l'API Flask (`services/`), et le frontend React/TypeScript.

---

## 1) Définition et objectif

Un test unitaire vérifie le comportement d'une unité de code isolée (fonction, méthode, petit module) avec :

- des entrées maîtrisées ;
- un résultat attendu explicite ;
- des dépendances externes neutralisées (mock/stub/fake) quand nécessaire.

Objectif : détecter vite les régressions fonctionnelles, avec un feedback court et déterministe.

---

## 2) Ce qu'un test unitaire n'est pas

Un test unitaire ne remplace pas :

- les tests d'intégration (interaction réelle entre modules) ;
- les tests E2E (parcours complet API/UI) ;
- les tests de performance/profiling.

Un projet robuste combine ces niveaux ; les tests unitaires en sont la base rapide.

---

## 3) Pourquoi c'est critique pour ce projet

Dans ce repo, les risques principaux sont :

- régressions de règles de jeu dans `engine/` ;
- incohérences de validation de données dans `shared/` ;
- erreurs de mapping requête/réponse dans `services/` ;
- transformations erronées côté `ai/` ;
- régressions d'utilitaires/hooks côté frontend.

Les tests unitaires réduisent ces risques à coût faible si on cible d'abord les zones à fort impact.

---

## 4) Principes de conception (qualité des tests)

### 4.1 Méthode AAA

Chaque test suit la structure :

- **Arrange** : préparer les données minimales utiles ;
- **Act** : appeler l'unité testée ;
- **Assert** : vérifier précisément le contrat attendu.

### 4.2 Propriétés d'un bon test

- **Rapide** : quelques ms à dizaines de ms ;
- **Déterministe** : même résultat à chaque exécution ;
- **Isolé** : pas de dépendance réseau/DB réelle ;
- **Lisible** : intention claire dans le nom et les assertions ;
- **Focalisé** : une intention principale par test.

### 4.3 Erreurs à éviter

- tester des détails d'implémentation au lieu du comportement ;
- assertions floues ou trop nombreuses sans intention claire ;
- fixtures massives illisibles ;
- dépendance à l'ordre d'exécution ;
- mocks excessifs qui masquent les bugs métier.

---

## 5) Pyramide de tests recommandée

Répartition cible :

- majorité de tests unitaires ;
- moins de tests d'intégration ;
- peu de tests E2E ciblés.

Pour ce projet : investir d'abord dans l'unitaire sur les règles de jeu et validations strictes.

---

## 6) Mise en place backend Python (engine, ai, services)

### 6.1 Outils recommandés

- `pytest` : exécution des tests ;
- `pytest-cov` : couverture ;
- `pytest-mock` : mocks propres ;
- `hypothesis` (optionnel) : tests de propriétés pour invariants.

### 6.2 Arborescence proposée

```text
tests/
  unit/
    engine/
    ai/
    services/
    shared/
  integration/
  fixtures/
```

Convention : `test_<module>.py`.

### 6.3 Configuration `pytest.ini` (base solide)

```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts = -q --strict-markers --disable-warnings
```

### 6.4 Commandes utiles

- run global : `pytest -q`
- fichier ciblé : `pytest tests/unit/engine/test_x.py -q`
- couverture : `pytest --cov=engine --cov=ai --cov=services --cov=shared --cov-report=term-missing`

---

## 7) Mise en place frontend TypeScript (React + Vite)

### 7.1 Outils recommandés

- `vitest` ;
- `@testing-library/react` ;
- `@testing-library/jest-dom` ;
- `msw` pour mock API.

### 7.2 Règles de base

- tester comportement visible (texte, interactions, états) ;
- éviter de tester les détails internes React ;
- isoler les appels réseau avec `msw`.

### 7.3 Scripts standard

- `test` : exécution interactive ;
- `test:run` : run CI ;
- `test:coverage` : couverture frontend.

---

## 8) Stratégie de priorisation (ordre d'attaque)

Prioriser par impact métier et fréquence d'exécution :

1. `engine/` : logique de phases/actions et invariants ;
2. `shared/` : validation stricte et erreurs explicites ;
3. `services/` : validation payload + mapping erreurs HTTP ;
4. `ai/` : parsing config/transformation observation-action ;
5. frontend : utilitaires, hooks, composants critiques.

Règle pratique : commencer par les fonctions pures et déterministes.

---

## 9) Matrice de couverture réaliste

La couverture n'est pas une preuve de qualité ; c'est un indicateur.

Objectifs progressifs recommandés :

- **Phase 1** : 50-60% global, 80%+ sur modules `engine` critiques ;
- **Phase 2** : 65-75% global ;
- **Phase 3** : seuils par dossier critique avec blocage CI.

Mieux vaut peu de tests pertinents que beaucoup de tests superficiels.

---

## 10) Conception des données de test

### 10.1 Fixtures minimales

- créer des fixtures compactes et explicites ;
- ne garder que les champs utiles au comportement testé ;
- nommer les fixtures par intention métier.

### 10.2 Données invalides (obligatoire)

Tester aussi les cas d'erreur :

- clé obligatoire absente ;
- type invalide ;
- valeur incohérente.

Le test doit vérifier l'erreur explicite attendue.

---

## 11) Mocking : quand et comment

### 11.1 À mocker

- réseau ;
- base de données ;
- accès disque lourd ;
- chargement de modèle RL coûteux ;
- temps système si logique temporelle.

### 11.2 À garder réel

- logique métier pure ;
- validations ;
- transformations déterministes.

### 11.3 Risque du sur-mock

Un test trop mocké valide parfois le mock, pas le code réel. Mock seulement ce qui rendrait le test lent, non déterministe ou externe.

---

## 12) CI/CD : industrialiser le contrôle qualité

Pipeline recommandé :

1. installation dépendances ;
2. lint/typecheck ;
3. tests unitaires Python ;
4. tests unitaires frontend ;
5. publication rapport de couverture.

Gates minimales :

- échec si tests rouges ;
- échec si baisse de couverture sous seuil défini ;
- rapport lisible en artefact CI.

---

## 13) Plan de déploiement en 4 semaines

### Semaine 1

- installer et configurer outillage Python + frontend ;
- écrire premier lot de tests `engine/shared` (cas nominaux + erreurs).

### Semaine 2

- couvrir validations API et utilitaires IA ;
- stabiliser fixtures et helpers de test.

### Semaine 3

- couvrir frontend (hooks/utilitaires/composants critiques) ;
- ajouter couverture et seuils progressifs.

### Semaine 4

- durcir CI (gates) ;
- documenter conventions ;
- fermer les trous critiques identifiés.

---

## 14) Checklist qualité pour chaque nouveau test

- nom explicite orienté comportement ;
- structure AAA ;
- données minimales ;
- assertions précises ;
- cas nominal + cas erreur utile ;
- pas de dépendance externe réelle non contrôlée ;
- exécution rapide et déterministe.

---

## 15) Risques et limites (avis honnête)

- Les tests unitaires ne garantissent pas l'absence de bug d'intégration.
- Une couverture élevée peut cacher des assertions faibles.
- Le coût de maintenance existe : un test mal conçu devient du bruit.
- Le ROI est maximal quand les tests protègent des invariants métier critiques.

Conclusion honnête : pour ce projet, le gain le plus fort vient d'un noyau de tests unitaires exigeants sur `engine/` + validations strictes, puis d'une montée progressive.

---

## 16) Standard d'équipe recommandé

À imposer dans les revues :

- toute nouvelle logique critique doit être livrée avec tests unitaires ;
- toute correction de bug doit inclure un test de non-régression ;
- aucun merge si tests unitaires en échec ;
- seuils de couverture progressifs, pas arbitrairement agressifs au départ.

---

## 17) Démarrage rapide (minimum viable)

1. Ajouter l'outillage (`pytest`, `pytest-cov`, `vitest`) ;
2. Créer l'arborescence `tests/unit/...` ;
3. Ajouter 10 tests à forte valeur métier (`engine/shared`) ;
4. Brancher exécution dans CI ;
5. Ajouter seuil de couverture initial modéré ;
6. Augmenter progressivement selon la stabilité.

Ce chemin donne un bénéfice immédiat sans bloquer le développement.
