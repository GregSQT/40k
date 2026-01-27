# Script de Vérification AI_TURN.md et coding_practices.mdc — check_ai_rules.py

**Fichier** : `scripts/check_ai_rules.py`

## Objectif

Vérifier la conformité du code à AI_TURN.md et coding_practices.mdc : recalculs de caches, pools d'activation, normalisation des coordonnées, fallbacks anti-erreur, patterns end_activation, termes interdits.

## Détections

1. **Recalculs de caches inutiles**
   - `build_enemy_adjacent_hexes()` appelé hors `*_phase_start`
   - `build_position_cache()` appelé hors `*_phase_start`
   - Violation de l’invariant : `current_player` ne change pas pendant la phase (non détectée automatiquement)

2. **Pool d'activation : construit seulement au début de la phase**
   - `shooting_build_activation_pool()`, `movement_build_activation_pool()`, `charge_build_activation_pool()`, `fight_build_activation_pools()` appelés hors `*_phase_start` → violation.
   - Pour les unités mortes : utiliser `_remove_dead_unit_from_pools` ou retrait in-place (liste en compréhension), ne pas reconstruire le pool.

3. **Coordonnées non normalisées**
   - Comparaisons directes `unit["col"] == other["col"]` ou `unit['col'] == other['col']` (double et simple quotes)
   - À remplacer par `get_unit_coordinates()` ou `normalize_coordinates()`

4. **Fallbacks anti-erreur**
   - `.get(key, None)`, `.get(key, 0)`, `.get(key, [])`, `.get(key, {})` (signalés même sans `if` sur la ligne suivante)
   - Exceptions : lignes contenant `require_key(`, `require_present(`, ou commentaires `# get allowed`, `# fallback allowed`, `# TODO fix`, `# exception.*get`
   - À remplacer par `require_key()` ou erreur explicite

5. **Patterns end_activation**
   - `end_activation()` avec des strings au lieu de constantes
   - Importer les constantes depuis `shared_utils`

6. **Termes interdits**
   - Workaround, fallback, magic number
   - Les commentaires qui documentent l'interdiction (ex. « no fallback », « interdit », « do not use workaround ») sont ignorés.

## Règle documentée (sans détection automatique)

**Pas de vérification redondante** : Une fois un pool ou un cache construit (ex. `enemy_adjacent_hexes`, `valid_*_destinations_pool`), ne pas re-vérifier la même condition (adjacence, atteignabilité, etc.) ; le pool est la source de vérité. Exemple interdit : utiliser `enemy_adjacent_hexes` puis appeler `is_adjacent_to_enemy(...)` dans le même flux. Voir `coding_practices.mdc` section « Pas de vérification redondante ».

## Usage

```bash
# Vérifier tout le périmètre (engine/ + ai/)
python3 scripts/check_ai_rules.py

# Vérifier un fichier spécifique
python3 scripts/check_ai_rules.py --path engine/phase_handlers/shooting_handlers.py

# Vérifier un répertoire
python3 scripts/check_ai_rules.py --path engine/phase_handlers/
```

`--path` exige un argument : sans chemin, le script affiche `Error: --path requires a path argument.` et quitte avec le code 1.

## Sortie

- Violations regroupées par type
- Fichier, ligne, message, extrait de code
- Exit code 0 si aucune violation, 1 sinon

## Intégration CI/CD

### Pre-commit hook

`.git/hooks/pre-commit` :

```bash
#!/bin/bash
python3 scripts/check_ai_rules.py || exit 1
```

### GitHub Actions / CI

```yaml
- name: Check AI Rules
  run: python3 scripts/check_ai_rules.py
```

## Résultats typiques (indicatif)

Un premier scan donne souvent un ordre de grandeur comme :

- **CACHE_RECALCULATION** : quelques violations (à juger au cas par cas, ex. recalcul si cache manquant)
- **END_ACTIVATION_PATTERN** : ~28 violations (strings au lieu de constantes)
- **COORDINATE_NORMALIZATION** : ~100+ violations
- **FALLBACK_ANTI_ERROR** : ~50+ violations
- **FORBIDDEN_TERM** : ~66+ violations

Les chiffres évoluent au fil des corrections.

## Prochaines étapes suggérées

1. **Revoir les violations**  
   Certaines peuvent être légitimes (ex. recalcul si cache manquant). Prévoir une whitelist si besoin.

2. **Corriger par priorité**  
   Caches et coordonnées d’abord, puis end_activation, puis fallbacks.

3. **Intégrer au workflow**  
   Pre-commit, CI/CD ou vérification avant merge.

## Notes

- Le script est **conservateur** : il privilégie les faux positifs.
- Certaines violations peuvent être **acceptables** (ex. recalcul après mort de cible).
- À valider manuellement avant de corriger.

### Faux positifs (fallback .get)

Un `.get(key, def)` utilisé volontairement pour une clé vraiment optionnelle (config, feature flags, etc.) peut être signalé à tort. Pour éviter le faux positif, ajouter sur la même ligne un commentaire du type `# get allowed` ou `# fallback allowed`. Filtrer au cas par cas ou via une whitelist si besoin.

### Faux négatifs (coordonnées col/row)

Les lignes contenant `"""` sont ignorées pour les comparaisons col/row (pour ne pas signaler du code d’exemple dans les docstrings). Des violations présentes uniquement dans des docstrings ou chaînes multi‑lignes ne sont donc pas détectées ; ce compromis est assumé.

## Valeur / ROI

- Feedback immédiat, déterministe, actionnable (fichier + ligne).
- Intégrable en pre-commit et CI.
- Efficace pour les violations détectables statiquement (ordre de grandeur : 8/10 en ROI).

## Améliorations futures

- [ ] Détection de violations de séquencement
- [x] Vérification de conformité des pools (construit seulement en phase_start ; retrait des morts sans reconstruction) — implémentée
- [ ] Détection de violations d'invariants de phase
- [ ] Whitelist pour exceptions légitimes
- [ ] Warning ciblé « pas de vérification redondante » (ex. adjacency après usage de enemy_adjacent_hexes) — règle documentée, pas de check pour l'instant
