# Cursor Sub-Agents - Système de Vérification de Conformité AI_TURN.md

## 📋 Vue d'Ensemble

Ce document décrit le système de **sub-agents spécialisés** mis en place pour garantir une conformité stricte à 100% avec `AI_TURN.md` lors de toute modification du code.

### Objectif

Créer un système de vérification automatique qui empêche l'IA de proposer du code non conforme aux règles définies dans `AI_TURN.md`, notamment :
- Violations des invariants de phase (ex: recalcul inutile de caches)
- Non-respect des règles de séquencement
- Workarounds et fallbacks anti-erreur
- Incohérences de coordonnées
- Etc.

### Approche : Agents Spécialisés par Domaine

Au lieu d'une seule règle massive, nous avons créé **des agents spécialisés** qui s'activent automatiquement selon le contexte :

- **Règles générales** : Toujours actives (contrat de codage, bonnes pratiques)
- **Règles spécialisées** : Activées uniquement quand vous modifiez les fichiers correspondants

---

## 🏗️ Architecture

### Structure des Règles

```
.cursor/rules/
├── ai_turn_compliance.mdc          # Règles générales (toujours actif)
├── coding_practices.mdc             # Bonnes pratiques (toujours actif)
├── shooting_compliance.mdc          # Phase de tir (conditionnel)
├── movement_compliance.mdc          # Phase de mouvement (conditionnel)
├── charge_compliance.mdc            # Phase de charge (conditionnel)
└── fight_compliance.mdc             # Phase de combat (conditionnel)
```

### Activation Automatique

Les règles s'activent automatiquement selon les fichiers modifiés :

| Fichier modifié | Règles activées |
|----------------|-----------------|
| `engine/**/*.py` ou `ai/**/*.py` | `ai_turn_compliance` + `coding_practices` (toujours) |
| `**/shooting_handlers.py` | + `shooting_compliance` |
| `**/movement_handlers.py` | + `movement_compliance` |
| `**/charge_handlers.py` | + `charge_compliance` |
| `**/fight_handlers.py` | + `fight_compliance` |

### Détail des Règles

#### 1. `ai_turn_compliance.mdc` (Toujours Actif)

**Taille** : ~9.7 KB (~2,420 tokens)

**Contenu** :
- Contrat de codage AI (4 règles non négociables)
- Conventions de nommage (champs UPPERCASE)
- Gestion d'état (single source of truth)
- Phases et séquences (activation séquentielle)
- Points critiques (caches, pools, tracking)
- Checklist de validation

**Globs** : `engine/**/*.py,ai/**/*.py`  
**alwaysApply** : `true`

#### 2. `coding_practices.mdc` (Toujours Actif)

**Taille** : ~7.5 KB (~1,868 tokens)

**Contenu** :
- Uniformité des coordonnées (normalisation obligatoire)
- Pas de workaround
- Pas de fallback anti-erreur
- Pas de valeur par défaut anti-erreur
- Gestion d'erreurs explicite
- Type hints et docstrings obligatoires

**Globs** : `engine/**/*.py,ai/**/*.py`  
**alwaysApply** : `true`

#### 3. `shooting_compliance.mdc` (Conditionnel)

**Taille** : ~8.0 KB (~1,998 tokens)

**Contenu** :
- **Invariant critique** : `current_player` ne change pas pendant la phase
  - Exemple concret : Les hex adjacents aux ennemis ne changent PAS
  - Les caches ne deviennent PAS obsolètes à cause de mouvements ennemis
- Activation séquentielle
- Restrictions advance (ASSAULT uniquement)
- Adjacent = in fight = cannot shoot
- Arguments stricts de fonctions
- End activation parameters

**Globs** : `**/shooting_handlers.py,**/shooting*.py`  
**alwaysApply** : `false`

**Exemple de violation détectée** :
```python
# ❌ VIOLATION CRITIQUE
def build_target_pool(unit, game_state):
    # Recalculer "par sécurité" car ennemis pourraient avoir bougé
    enemy_adjacent_hexes = build_enemy_adjacent_hexes(game_state, unit["player"])
    # ERREUR : Les ennemis ne bougent PAS pendant la phase de tir du joueur actuel
```

#### 4. `movement_compliance.mdc` (Conditionnel)

**Taille** : ~8.5 KB (~2,132 tokens)

**Contenu** :
- Invariant : `current_player` ne change pas pendant la phase
- Restrictions de mouvement (pas adjacent, pas occupé, pas mur)
- Flee mechanics (détection à position de départ)
- BFS pathfinding avec contraintes
- End activation parameters

**Globs** : `**/movement_handlers.py,**/movement*.py`  
**alwaysApply** : `false`

#### 5. `charge_compliance.mdc` (Conditionnel)

**Taille** : ~7.6 KB (~1,904 tokens)

**Contenu** :
- Advanced units cannot charge
- Roll 2D6 à la sélection d'unité (pas à la destination)
- Roll discardé à la fin de l'activation
- Destinations valides (adjacent à cible, distance ≤ roll)
- BFS pathfinding pour distance

**Globs** : `**/charge_handlers.py,**/charge*.py`  
**alwaysApply** : `false`

#### 6. `fight_compliance.mdc` (Conditionnel)

**Taille** : ~9.2 KB (~2,294 tokens)

**Contenu** :
- Sub-phase 1 : Charging units priority
- Sub-phase 2 : Alternating fight (les deux joueurs)
- ATTACK_LEFT management
- Pool de cibles reconstruit avant chaque attaque
- Damage immédiat (pas à la fin)

**Globs** : `**/fight_handlers.py,**/fight*.py`  
**alwaysApply** : `false`

---

## 💰 Coût en Tokens

### Répartition

| Règle | Taille | Tokens | Statut |
|-------|--------|--------|--------|
| `ai_turn_compliance.mdc` | 9.7 KB | ~2,420 | Toujours actif |
| `coding_practices.mdc` | 7.5 KB | ~1,868 | Toujours actif |
| `shooting_compliance.mdc` | 8.0 KB | ~1,998 | Conditionnel |
| `movement_compliance.mdc` | 8.5 KB | ~2,132 | Conditionnel |
| `charge_compliance.mdc` | 7.6 KB | ~1,904 | Conditionnel |
| `fight_compliance.mdc` | 9.2 KB | ~2,294 | Conditionnel |
| **TOTAL** | **50.5 KB** | **~12,616** | |

### Coût Réel selon l'Usage

- **Modification d'un fichier de phase** (ex: `shooting_handlers.py`) : ~6,286 tokens (base + phase)
- **Modification d'un fichier général** (ex: `w40k_core.py`) : ~4,288 tokens
- **Pire cas** (plusieurs phases ouvertes) : ~12,616 tokens

L'approche spécialisée économise **~50–60 % de tokens** par rapport à une règle unique de 50 KB à chaque requête.

---

## 🎯 Effets Concrets

Les règles Cursor agissent comme un **filtre de conformité** qui influence directement le comportement de l'IA.

### Manifestations

1. **Refus de modifications non conformes** : L'IA refuse et explique pourquoi (ex: recalcul de cache en phase de tir → refus + explication de l'invariant).
2. **Suggestions automatiquement conformes** : Code conforme dès la première proposition (ex: normalisation des coordonnées via `get_unit_coordinates`).
3. **Vérifications préalables** : L'IA bloque les violations avant de coder (ex: refus de « tirer deux fois » car une unité ne peut tirer qu'une fois par phase).
4. **Corrections automatiques des patterns** : Fallbacks remplacés par `require_key` et erreurs explicites.
5. **Références explicites aux règles** : Explications qui citent `AI_TURN.md` ou les `.mdc` concernés.

### Comparaison Avant / Après

**Sans règles** : recalculs « par sécurité », pas de normalisation, pas de vérification de conformité.  
**Avec règles** : utilisation des caches existants, normalisation, préconditions vérifiées, docstrings référençant les règles.

### Indicateurs

- **Règles qui fonctionnent** : refus systématique des violations, citations des règles, code conforme dès le départ, normalisation automatique.
- **Règles qui ne fonctionnent pas** : code avec workarounds, violations acceptées, aucune mention des règles.

---

## 🔍 Détection de l'Activation

**Problème** : Les règles Cursor sont appliquées **silencieusement**. Il n’y a pas de feedback direct pour savoir si une règle a été activée.

### Méthodes indirectes

1. **Observer le comportement** : refus de modifications non conformes, références explicites aux règles, suggestions conformes, vérifications préalables.
2. **Tests proactifs** : prompts de violation (ex: « recalcule enemy_adjacent_hexes par sécurité », « compare col sans normalisation ») — refus attendu si la règle est active.
3. **Vérification manuelle** : `ls -lh .cursor/rules/*.mdc`, vérifier `globs` et `alwaysApply`.
4. **Script de test** : `scripts/test_cursor_rules.py` — vérifie la configuration et peut générer des prompts de test.

### Test rapide

1. Ouvrir `engine/phase_handlers/shooting_handlers.py`
2. Demander : « Ajoute un recalcul de enemy_adjacent_hexes dans build_target_pool »
3. Si l’IA refuse et explique l’invariant → règle active ; sinon → règle inactive ou mal configurée.

### Dépannage

- Vérifier les globs et `alwaysApply` dans `.cursor/rules/*.mdc`
- Redémarrer Cursor
- Vérifier la syntaxe YAML du frontmatter des `.mdc`

---

## 📊 Évaluation Honnête

**Utilité réelle : MODÉRÉE à ÉLEVÉE — environ 7/10.**

### Points positifs

- Projet avec règles complexes (AI_TURN.md, invariants, historique de bugs) : les règles peuvent éviter des bugs subtils.
- Coût raisonnable (~4–6k tokens/requête) et gain ~50–60 % vs règle unique.
- Complément utile à `scripts/check_ai_rules.py` (guidance proactive vs vérification).

### Limites

- **Pas de garantie à 100 %** : guidance, pas vérification déterministe.
- **Pas de feedback direct** : détection indirecte seulement.
- **Maintenance** : 6 fichiers à aligner avec `AI_TURN.md`.
- **Valeur limitée si le projet est très stable** : moins de modifications = moins de bénéfice.

### Recommandation

**Garder les règles avec des attentes réalistes** : guidance proactive, complément aux scripts, efficacité ~70–80 %, révision tous les 3–6 mois. Les règles sont un **outil**, pas une **solution** unique.

---

## ⚖️ Efficacité : Règles vs Scripts

### Comparaison

| Critère | Règles seules | Scripts améliorés | Hybride |
|---------|---------------|-------------------|---------|
| Fiabilité | ~70 % | 100 % (déterministe) | ~95 % |
| Feedback direct | ❌ | ✅ | ✅ |
| Guidance proactive | ✅ | ❌ | ✅ |
| Intégration CI | ❌ | ✅ | ✅ |

### Recommandation

- **Priorité 1** : améliorer les scripts (`scripts/check_ai_rules.py`) — détection déterministe, feedback direct, intégrable CI/CD.
- **Priorité 2** : garder/simplifier les règles — guidance proactive, couverture de ce que les scripts ne voient pas.

**Approche hybride** (scripts + règles) : ROI estimé le plus élevé. Si un seul levier : **scripts en priorité**.

---

## ✅ Avantages du Système

- **Expertise ciblée** : chaque agent maîtrise son domaine (ex: invariant `current_player` en shooting).
- **Efficacité** : activation par fichier, moins de tokens, réponses plus pertinentes.
- **Maintenabilité** : mise à jour d’une phase sans impacter les autres.

---

## 🔧 Utilisation et Maintenance

### Activation

Les règles s’activent automatiquement quand vous ouvrez ou modifiez un fichier couvert par les globs. Aucune action manuelle.

### Ajouter une règle spécialisée

1. Créer `.cursor/rules/<nom>_compliance.mdc`
2. Définir les globs, `alwaysApply: false`
3. Rédiger la règle

### Désactiver temporairement

Renommer le fichier (ex: `.mdc.bak`) ou ajuster les globs.

---

## 📝 Exemples de Violations Détectées

### Recalcul inutile de caches (Shooting)

**Violation** : recalcul de `enemy_adjacent_hexes` « par sécurité » dans `build_target_pool`.  
**Correction** : utiliser le cache construit au début de phase (clé `enemy_adjacent_hexes_player_{current_player}`).

### Coordonnées non normalisées

**Violation** : `unit["col"] == enemy["col"]` sans normalisation.  
**Correction** : `get_unit_coordinates(unit)` / `get_unit_coordinates(enemy)` puis comparaison.

### Fallback anti-erreur

**Violation** : `config.get('key', None)` ou fallback à 0 pour éviter une erreur.  
**Correction** : `require_key(config, 'key')` et erreur explicite si absent.

---

## 🎯 Checklist de Validation

### Règles générales (toujours)

- [ ] Aucune valeur assumée (config ou erreur explicite)
- [ ] Aucun fallback silencieux
- [ ] Champs UPPERCASE, single source of truth
- [ ] Coordonnées normalisées, pas de workaround
- [ ] Type hints et docstrings

### Règles spécialisées (selon phase)

- [ ] `current_player` ne change pas pendant la phase
- [ ] Activation séquentielle, caches valides
- [ ] Restrictions de phase et end activation corrects

---

## 🔗 Références

- **AI_TURN.md** : Règles de tour, phases, séquences
- **AI_IMPLEMENTATION.md** : Architecture et patterns
- **Documentation/Code_Compliance/AI_RULES_checker.md** : Script de vérification automatique
- **shared/validation** : `require_key`, `require_present`
- **scripts/test_cursor_rules.py** : Validation de la configuration des règles
- **scripts/check_ai_rules.py** : Vérification automatique (caches, coordonnées, fallbacks, etc.)

---

## 📊 Statistiques

- **Règles** : 6
- **Taille totale** : 50.5 KB (~12,616 tokens)
- **Base** : ~4,288 tokens (toujours actif)
- **Par phase** : ~2,000 tokens (conditionnel)
- **Gain vs règle unique** : ~50–60 %

---

## 🚀 Améliorations Futures

- Script de vérification automatique des recalculs, violations de phase, coordonnées, workarounds/fallbacks.
- Tests unitaires sur les invariants (ex: positions ennemies fixes pendant la phase de tir, validité des caches).
- Intégration de la vérification en CI/CD pour bloquer les violations avant merge.

---

**Dernière mise à jour** : 27 janvier 2026
