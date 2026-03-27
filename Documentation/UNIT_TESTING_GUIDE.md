# Guide unitaire definitif (repo 40k)

Objectif: fournir une reference unique, executable et maintenable pour mettre en place les tests unitaires sur ce repo.

Ce document remplace les versions de travail precedentes et fige:
- la strategie de priorisation;
- les conventions techniques;
- les commandes locales et CI;
- la Definition of Done (DoD) tests.

---

## 1) Decisions figees

1. **Python unitaire**: `pytest` lance depuis la racine du repo.
2. **Frontend unitaire**: stack unique dans `frontend/` avec `vitest` + Testing Library.
3. **Priorite fonctionnelle**: `engine/` + `shared/` d'abord, puis `services/`, puis `ai/`, puis frontend.
4. **Qualite > volume**: assertions metier fortes avant objectifs de couverture.

---

## 2) Principes non negociables

- Unitaire = test deterministe, rapide, isole, explicite.
- Aucune dependance externe reelle (reseau, DB, I/O lourd) en test unitaire.
- Aucun fallback pour "faire passer" un test.
- Toute correction de bug inclut un test de non-regression.
- Toute logique critique nouvelle arrive avec tests associes.

---

## 3) Contrat d'erreurs (aligne code actuel)

Reference implementation:
- `shared/data_validation.py`
  - `require_key(...)` leve `ConfigurationError` si la cle est absente.
  - `require_present(...)` leve `ConfigurationError` si la valeur est `None`.

Regle de test:
- verifier **le type d'exception reel** (`ConfigurationError`);
- verifier un message d'erreur utile (nom du champ/cle), avec un `match`
  cible sur des fragments stables plutot qu'une phrase complete.
- ne pas substituer `KeyError`/`ValueError` dans les tests de ce module, sauf migration explicite du contrat.

Exemple:

```python
import pytest
from shared.data_validation import require_key, ConfigurationError


def test_require_key_raises_configuration_error_when_missing() -> None:
    with pytest.raises(ConfigurationError, match=r"Required key 'MOVE'"):
        require_key({}, "MOVE")
```

---

## 4) Structure cible des tests

```text
tests/
  conftest.py
  unit/
    engine/
    shared/
    services/
    ai/
  integration/
```

Conventions:
- fichier: `test_<module>.py`
- test: `test_<comportement>_<condition>_<resultat>`

---

## 5) Configuration Python (copier-coller)

### 5.1 `pytest.ini` (racine)

```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_functions = test_*
addopts = -q --strict-markers
markers =
    unit: fast deterministic unit tests
    integration: cross-module tests
```

Note:
- `--maxfail=1` reste recommande en local pour la boucle de dev rapide,
  mais n'est pas force dans la config partagee.

### 5.2 `tests/conftest.py` (determinisme)

```python
import random
import numpy as np
import pytest

try:
    import torch
except ImportError:  # pragma: no cover
    torch = None


@pytest.fixture(autouse=True)
def deterministic_seed() -> None:
    seed = 12345
    random.seed(seed)
    np.random.seed(seed)
    if torch is not None:
        torch.manual_seed(seed)
```

---

## 6) Decision frontend figee (unique)

Le frontend de reference est `frontend/` (Vite).

Dependances dev a ajouter dans `frontend/`:
- `vitest`
- `@testing-library/react`
- `@testing-library/jest-dom`
- `jsdom`
- `msw`

Scripts a avoir dans `frontend/package.json`:

```json
{
  "scripts": {
    "test": "vitest",
    "test:critical": "vitest run --config vitest.critical.config.ts",
    "test:run": "vitest run",
    "test:coverage": "vitest run --coverage",
    "test:coverage:global": "vitest run --coverage"
  }
}
```

Commandes locales frontend:

```bash
npm --prefix frontend run test
npm --prefix frontend run test:critical
npm --prefix frontend run test:run
npm --prefix frontend run test:coverage
npm --prefix frontend run test:coverage:global
```

---

## 7) Matrice de tracabilite (invariants -> tests)

| Invariant critique | Code cible | Test cible | Priorite |
|---|---|---|---|
| Validation stricte sans fallback | `shared/data_validation.py` | `tests/unit/shared/test_data_validation.py` | P0 |
| Normalisation coordonnees | `engine/combat_utils.py` | `tests/unit/engine/test_combat_utils.py` | P0 |
| Fin d'activation conforme (tracking/step/log) | `engine/phase_handlers/generic_handlers.py` | `tests/unit/engine/test_generic_handlers.py` | P0 |
| HP source unique via cache | `engine/phase_handlers/shared_utils.py` | `tests/unit/engine/test_shared_utils_units_cache.py` | P0 |
| Mapping erreurs HTTP explicites | handlers `services/` | `tests/unit/services/test_*` | P1 |
| Parsing/transformation IA deterministes | `ai/` | `tests/unit/ai/test_*` | P1 |

---

## 8) Les 10 premiers tests obligatoires

1. `test_require_key_raises_configuration_error_when_missing`
2. `test_require_present_raises_configuration_error_when_none`
3. `test_get_unit_coordinates_normalizes_numeric_strings`
4. `test_get_unit_coordinates_raises_key_error_when_missing_row`
5. `test_end_activation_wait_adds_wait_log_with_position`
6. `test_end_activation_arg2_increments_episode_steps`
7. `test_end_activation_arg3_fled_marks_units_moved_and_units_fled`
8. `test_update_units_cache_hp_updates_entry_when_hp_positive`
9. `test_update_units_cache_hp_removes_unit_when_hp_zero_or_less`
10. `test_get_hp_from_cache_returns_none_when_unit_absent`

Ces tests constituent le socle minimal de protection metier.

---

## 9) Commandes locales officielles

Python (depuis racine):

```bash
pytest tests/unit -q
pytest tests/unit -q --cov=engine --cov=shared --cov=services --cov=ai/reward_mapper.py --cov=ai/scenario_manager.py --cov=ai/replay_converter.py --cov=ai/metrics_tracker.py --cov=ai/game_replay_logger.py --cov=ai/step_logger.py --cov-report=term-missing --cov-fail-under=60
pytest tests/unit/ai -q --cov=ai --cov-report=term-missing
pytest tests/unit/engine -q --cov=engine --cov-fail-under=70
pytest tests/unit/shared -q --cov=shared --cov-fail-under=80
pytest tests/unit -q --maxfail=1
```

Note:
- gate bloquant: perimetre critique metier (engine/shared/services + modules ai critiques).
- reporting informatif: couverture globale `ai/*` sans seuil bloquant.
- des gates critiques par package (`engine`, `shared`) restent appliques en
  complement pour eviter l'effet "compensation".

Frontend (depuis racine):

```bash
npm --prefix frontend run test:run
npm --prefix frontend run test:coverage
```

---

## 10) CI executable (GitHub Actions)

Exemple minimal coherant avec la structure du repo:

```yaml
name: unit-tests

on:
  pull_request:
  push:
    branches: [main]

jobs:
  python-unit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install Python deps
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.runtime.txt
          pip install pytest pytest-cov pytest-mock

      - name: Run Python unit tests
        run: |
          pytest tests/unit -q
          pytest tests/unit -q --cov=engine --cov=shared --cov=services --cov=ai/reward_mapper.py --cov=ai/scenario_manager.py --cov=ai/replay_converter.py --cov=ai/metrics_tracker.py --cov=ai/game_replay_logger.py --cov=ai/step_logger.py --cov-report=term-missing --cov-fail-under=60
          pytest tests/unit/ai -q --cov=ai --cov-report=term-missing
          pytest tests/unit/engine -q --cov=engine --cov-fail-under=70
          pytest tests/unit/shared -q --cov=shared --cov-fail-under=80

  frontend-unit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Setup Node
        uses: actions/setup-node@v4
        with:
          node-version: "20"
          cache: "npm"
          cache-dependency-path: frontend/package-lock.json

      - name: Install frontend deps
        working-directory: frontend
        run: npm ci

      - name: Run frontend unit tests
        run: |
          npm --prefix frontend run test:critical
          npm --prefix frontend run test:coverage:global
```

---

## 11) Couverture et seuils

Seuil initial recommande:
- Python critique (gate bloquant): 60%
- Cible critique `engine`: gate initial 70% (hausse progressive)
- Cible critique `shared`: gate initial 80% (hausse progressive)
- Frontend critique (gate bloquant): tests critiques + seuils coverage dedies
- Frontend global: metrique informative, hausse par sprint

Seuil frontend critique initial (module `weaponHelpers`):
- lines >= 35%
- statements >= 35%
- functions >= 40%
- branches >= 60%

Important:
- la couverture ne remplace pas des assertions fortes;
- un test faible couvert a 100% reste un mauvais test.
- la couverture globale `ai/*` reste suivie en metrique informative (non bloquante).

---

## 12) DoD stricte "tests"

Une PR n'est pas complete si un des points suivants manque:

- changement metier critique sans test unitaire associe;
- bug fixe sans test de non-regression;
- tests unitaires rouges local/CI;
- un ou plusieurs tests P0 de la section "Les 10 premiers tests obligatoires" manquants ou rouges;
- exception attendue non verifiee (type + message utile);
- test non deterministe (flaky).

Template review (copier-coller):
- [ ] Cas nominal couvre le comportement attendu
- [ ] Cas d'erreur metier pertinent couvre l'echec attendu
- [ ] Assertions explicites et lisibles
- [ ] Pas de dependance externe reelle en unitaire
- [ ] Test de non-regression present si bugfix

---

## 13) Risques residuels (a ne pas confondre)

Le socle unitaire **ne couvre pas**:
- les regressions d'integration inter-modules;
- les regressions de parcours API complet;
- les regressions UI de bout en bout.

Minimum a ajouter ensuite:
1. quelques tests d'integration critiques (`engine` <-> `services`);
2. quelques tests API scenario-driven;
3. quelques tests UI E2E cibles sur parcours majeurs.

Anomalies connues detectees par les tests:
- consigner chaque anomalie dans `Documentation/KNOWN_ANOMALIES.md`;
- ajouter un test sentinelle explicite (idealement `xfail`) lie a l'anomalie;
- referencer l'identifiant d'anomalie dans le message `reason` du test.

---

## 14) Plan d'execution (7 jours)

Jour 1:
- creer `tests/`, `pytest.ini`, `tests/conftest.py`
- ecrire 4 tests `shared` + `combat_utils`

Jour 2-3:
- ecrire 6 tests `generic_handlers` + `shared_utils`

Jour 4:
- brancher job Python CI

Jour 5:
- installer stack frontend test et scripts

Jour 6:
- ajouter 3-5 tests frontend utiles

Jour 7:
- activer seuils coverage initiaux + template review PR

---

## 15) Verdict pratique

Version definitive cible:
- explicite sur les contrats reels;
- executable en local et CI sans ambiguite;
- centree sur invariants metier critiques;
- progressive pour maximiser le ROI.

Si ces sections sont appliquees telles quelles, le projet gagne une protection concrete contre les regressions majeures, sans freiner le developpement.
