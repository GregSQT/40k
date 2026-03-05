# ai/analyzer.py - Guide de l'analyseur step.log

> **Usage** : `python ai/analyzer.py step.log`
>
> **Sortie** : Rapport de validation des règles de jeu (console + fichier optionnel)

---

## 📋 Table des matières

- [Vue d'ensemble](#vue-densemble)
- [Utilisation](#utilisation)
- [Structure du rapport](#structure-du-rapport)
- [Métriques détaillées](#métriques-détaillées)
  - [1.6 SPECIAL RULES USAGE](#16-special-rules-usage)
  - [1.7 WEAPONS RULES USAGE](#17-weapons-rules-usage)
- [Résumé (Summary)](#résumé-summary)
- [Intégration au workflow](#intégration-au-workflow)

---

## Vue d'ensemble

L'analyzer parse le fichier `step.log` généré par l'entraînement (avec `--step`) et valide la conformité aux règles du jeu (AI_TURN.md). Il détecte :

- **Violations** : mouvements invalides, tirs illégaux, charges interdites, etc.
- **Métriques de règles spéciales** : usage des règles d'unités et d'armes.

---

## Utilisation

```bash
# Générer step.log puis analyser
python ai/train.py --agent <agent> --training-config default --step --test-episodes 300 2>&1 | tee train.log
python ai/analyzer.py step.log
```

### Options

```bash
# Filtrer une section spécifique
python ai/analyzer.py step.log 1.6

# Écrire dans un fichier
python ai/analyzer.py step.log --output analyzer.log
```

Sections disponibles : `1.1`, `1.2`, `1.3`, `1.4`, `1.5`, `1.6`, `1.7`, `2.1`, `2.2`, `2.3`, `2.4`, `2.5`, `2.6`, `2.7`

---

## Structure du rapport

| Section | Description |
|---------|-------------|
| **1.1** | MOVEMENT ERRORS |
| **1.2** | SHOOTING ERRORS |
| **1.3** | CHARGE ERRORS |
| **1.4** | FIGHT ERRORS |
| **1.5** | ACTION PHASE ACCURACY |
| **1.6** | SPECIAL RULES USAGE |
| **1.7** | WEAPONS RULES USAGE |
| **2.1** | DEAD UNITS INTERACTIONS |
| **2.2** | POSITION / LOG COHERENCE |
| **2.3** | DMG ISSUES |
| **2.4** | EPISODES STATISTICS |
| **2.5** | EPISODES ENDING |
| **2.6** | SAMPLE MISSING |
| **2.7** | CORE ISSUES |

---

## Métriques détaillées

### 1.6 SPECIAL RULES USAGE

Compte l'utilisation des **règles d'unités** (UNIT_RULES) par type d'unité.
Chaque utilisation est validée : l'unité doit posséder la règle dans sa config.

**Format :**
```
--------------------------------------------------------------------------------
1.6 SPECIAL RULES USAGE      Unit                           P1         P2   Validité
--------------------------------------------------------------------------------
charge_after_advance         Hormagaunt                      0         38         OK
```

- **Rule** : identifiant de la règle (ex. `charge_after_advance`)
- **Unit** : type d'unité
- **P1 / P2** : nombre d'utilisations par joueur
- **Validité** : `OK` si l'unité a la règle, `INVALID` sinon

**Règles actuelles :**
- `charge_after_advance` : charge après advance (ex. Bounding Leap des Hormagaunts)

---

### 1.7 WEAPONS RULES USAGE

Compte l'utilisation des **règles d'armes** (WEAPON_RULES) par arme et unité.
Chaque utilisation est validée : l'arme doit posséder la règle dans sa config.

**Format :**
```
--------------------------------------------------------------------------------
1.7 WEAPONS RULES USAGE      Weapon                               P1         P2   Validité
--------------------------------------------------------------------------------
Assault                      Bolt Rifle (Intercessor)            812         52         OK
Pistol                       Bolt Pistol (Intercessor)             8         10         OK
```

- **Rule** : règle d'arme (ex. Assault, Pistol)
- **Weapon** : nom de l'arme + type d'unité
- **P1 / P2** : nombre d'utilisations
- **Validité** : `OK` si l'arme a la règle, `INVALID` sinon

**Règles actuelles :**
- **ASSAULT** : tir après advance (vérifié uniquement si l'unité a avancé avant de tirer)
- **PISTOL** : tir à distance 1 (ennemi adjacent)

**Validation ASSAULT :** L'analyzer ne compte que les tirs effectués après une action ADVANCE du même tour pour la même unité.

---

## Résumé (Summary)

En fin de rapport, un résumé affiche :
- 1.1 : Erreurs de mouvement
- 1.2 : Erreurs de tir
- 1.3 : Erreurs de charge
- 1.4 : Erreurs de combat
- 1.5 : Actions dans mauvaise phase
- 1.6 : Double-activation par phase
- 2.1 à 2.7 : Cohérence, intégrité, etc.

---

## Intégration au workflow

**Documentation :**
- [Fix_violations_guideline.md](Fix_violations_guideline.md) : guideline / prompt pour automatiser les correctifs
- [Hidden_action_finder.md](Hidden_action_finder.md) : détection des actions non loguées (step.log vs debug.log)
- [../AI_TURN.md](../AI_TURN.md) : règles du jeu

**Fichiers de config :**
- `config/unit_rules.json` : règles d'unités
- `config/weapon_rules.json` : règles d'armes
