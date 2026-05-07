# Refactoring de analyzer.py

## Contexte et besoin

`ai/analyzer.py` contient une fonction `parse_step_log` de **3626 lignes** (lignes 941–4564).

Cette taille déclenche l'erreur Pylance `reportGeneralTypeIssues` ("Code is too complex to analyze") : Pylance abandonne l'inférence de types à partir de la ligne 941, ce qui signifie zéro autocomplétion fiable, zéro détection d'erreur de type dans toute la fonction.

Au-delà du tooling, la fonction est difficilement maintenable :
- Tous les handlers d'événements (move, shoot, charge, fight…) sont des blocs inline partageant ~30 variables locales
- Impossible d'écrire des tests unitaires sur un handler isolé
- Debugger un bug dans le handler `charge` implique de naviguer dans 3600 lignes de contexte

## Solution retenue

Découper `parse_step_log` en suivant le pattern déjà établi dans `engine/phase_handlers/`.

### Structure cible

```
ai/
  analyzer.py              # point d'entrée public (inchangé en interface)
  analyzer_core.py         # boucle principale de dispatch + orchestration
  analyzer_config.py       # chargement config + construction des caches (UnitRegistry, rules, weapons)
  analyzer_state.py        # AnalyzerState dataclass — état partagé entre handlers
  analyzer_phases/
    __init__.py
    episode_handler.py     # EPISODE START / END + reset d'état
    move_handler.py        # MOVE, FLED, ADVANCE
    shoot_handler.py       # SHOOT, WAIT, SKIP
    charge_handler.py      # CHARGE
    fight_handler.py       # FIGHT
```

`analyzer.py` conserve son interface publique (`parse_step_log`, `print_stats`) et délègue à `analyzer_core.py`.

### Pièce centrale : AnalyzerState

Le vrai obstacle au découpage n'est pas les handlers eux-mêmes mais les ~30 variables locales qu'ils partagent. Sans encapsulation, on obtient des fonctions à 15 paramètres.

`AnalyzerState` regroupe tout l'état épisodique :

```python
@dataclass
class AnalyzerState:
    # État épisode courant
    current_episode: list
    current_episode_num: int
    episode_turn: int
    episode_actions: int

    # Tracking unités
    unit_hp: Dict[str, int]
    unit_player: Dict[str, int]
    unit_positions: Dict[str, Tuple[int, int]]
    unit_types: Dict[str, str]
    unit_move: Dict[str, int]
    dead_units_current_episode: Set[str]

    # Board
    wall_hexes: Set[Tuple[int, int]]
    objective_hexes: Dict[int, Set[Tuple[int, int]]]
    objective_controllers: Dict[int, Optional[int]]

    # Tracking actions
    units_moved: Set[str]
    units_shot: Set[str]
    units_fled: Set[str]
    units_advanced: Set[str]
    units_fought: Set[str]
    # ... etc.

    # Stats globales (référence, pas une copie)
    stats: Dict
```

Chaque handler reçoit `state: AnalyzerState` et le modifie en place.

## Plan d'implémentation

### Étape 1 — AnalyzerState (prérequis)

Créer `ai/analyzer_state.py` avec le dataclass et une fonction `make_initial_state(stats) -> AnalyzerState`.

Pas de modification du code de parsing à ce stade : juste définir la structure.

### Étape 2 — analyzer_config.py

Extraire les lignes 952–1155 (chargement UnitRegistry, construction des caches weapons/rules) dans une fonction :

```python
def load_analyzer_config() -> AnalyzerConfig:
    ...
```

`AnalyzerConfig` est un dataclass contenant `unit_weapons_cache`, `unit_attack_limits`, `unit_rules_by_type`, `weapon_rule_to_weapons`, etc.

Valider : `parse_step_log` appelle `load_analyzer_config()` et les résultats sont identiques.

### Étape 3 — episode_handler.py

Extraire le bloc EPISODE START (lignes ~1458–1521) dans :

```python
def handle_episode_start(state: AnalyzerState, line: str) -> None:
    ...
```

C'est le handler le plus simple et le plus isolé — bon test de validation du pattern.

### Étape 4 — Handlers par phase

Dans l'ordre de risque croissant (du plus isolé au plus interconnecté) :

1. `fight_handler.py` — le plus court (~250 lignes), peu de dépendances croisées
2. `charge_handler.py` — ~400 lignes
3. `shoot_handler.py` — ~500 lignes (shoot + wait + skip)
4. `move_handler.py` — ~600 lignes, le plus complexe (détection fled, collisions, positions snapshot)

Chaque handler expose une seule fonction publique :

```python
def handle_fight(state: AnalyzerState, config: AnalyzerConfig, line: str, player: int) -> None:
    ...
```

### Étape 5 — analyzer_core.py

La boucle de dispatch principale devient lisible :

```python
def parse_log(filepath: str, config: AnalyzerConfig, stats: Dict) -> None:
    state = make_initial_state(stats)
    with open(filepath) as f:
        for line in f:
            if is_episode_start(line):
                handle_episode_start(state, line)
            elif action_type == 'move':
                handle_move(state, config, line, player)
            elif action_type == 'shoot':
                handle_shoot(state, config, line, player)
            # ...
```

### Étape 6 — Nettoyage

- `analyzer.py` devient un thin wrapper qui importe et expose l'interface publique
- Supprimer la fonction imbriquée `resolve_effect_rule_id_to_technical` → la promouvoir en fonction module-level dans `analyzer_config.py`

## Critères de validation

À chaque étape, avant de continuer :

```bash
python3 ai/analyzer.py <fichier_step.log> > output_after.txt
diff output_before.txt output_after.txt
```

Zéro diff = étape validée. Le refactoring est purement structurel, aucun comportement ne doit changer.

## Risques

| Risque | Mitigation |
|---|---|
| Variables d'état manquantes dans AnalyzerState | Construire le dataclass en lisant exhaustivement les 30 variables locales avant d'écrire la moindre ligne |
| Régression silencieuse dans un handler | Diff de sortie obligatoire après chaque étape |
| `move_handler` trop complexe (détection fled) | L'extraire en dernier, après que le pattern soit validé sur les handlers simples |

## Ce que ce refactoring ne change pas

- L'interface publique de `analyzer.py` (`parse_step_log`, `print_stats`)
- La logique de validation des règles
- Les performances (pas de changement algorithmique)
- Le format de sortie
