# Outils de conformité — Référence

Ce document regroupe la documentation des cinq outils de vérification et de diagnostic du moteur et de l'IA.

> **Correspondance des sources** (consolidation P4 du 2026-08-28, sources archivées en `Documentation/Archives/docs/`) :
>
> | Source absorbée | Section |
> |---|---|
> | `AI_RULES_checker.md` | [§1 — `scripts/check_ai_rules.py`](#1-scriptscheck_ai_rulespy--vérification-statique-du-code) |
> | `GAME_Analyzer.md` | [§2 — `ai/analyzer.py`](#2-aianalyzerpy--analyse-du-steplog) |
> | `Hidden_action_finder.md` | [§3 — `ai/hidden_action_finder.py`](#3-aihidden_action_finderpy--actions-non-loguées) |
> | `Fix_violations_guideline.md` | [§4 — Workflow de correction](#4-workflow-de-correction-des-violations) |
> | `Obs_channel_audit.md` | [§5 — `scripts/obs_channel_audit.py`](#5-scriptsobs_channel_auditpy--canaux-dobservation) |

---

## 1. `scripts/check_ai_rules.py` — vérification statique du code

**Fichier** : `scripts/check_ai_rules.py`

### Objectif

Vérifier la conformité du code à tour_de_jeu.md et coding_practices.mdc : recalculs de caches, pools d'activation, normalisation des coordonnées, fallbacks anti-erreur, patterns end_activation, termes interdits.

### Détections

1. **Recalculs de caches inutiles**
   - `build_enemy_adjacent_hexes()` appelé hors `*_phase_start`
   - `build_position_cache()` appelé hors `*_phase_start`
   - Violation de l'invariant : `current_player` ne change pas pendant la phase (non détectée automatiquement)

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

### Règle documentée (sans détection automatique)

**Pas de vérification redondante** : Une fois un pool ou un cache construit (ex. `enemy_adjacent_hexes`, `valid_*_destinations_pool`), ne pas re-vérifier la même condition (adjacence, atteignabilité, etc.) ; le pool est la source de vérité. Exemple interdit : utiliser `enemy_adjacent_hexes` puis appeler `is_adjacent_to_enemy(...)` dans le même flux. Voir `coding_practices.mdc` section « Pas de vérification redondante ».

### Usage

```bash
# Vérifier tout le périmètre (engine/ + ai/)
python3 scripts/check_ai_rules.py

# Vérifier un fichier spécifique
python3 scripts/check_ai_rules.py --path engine/phase_handlers/shooting_handlers.py

# Vérifier un répertoire
python3 scripts/check_ai_rules.py --path engine/phase_handlers/
```

`--path` exige un argument : sans chemin, le script affiche `Error: --path requires a path argument.` et quitte avec le code 1.

### Sortie

- Violations regroupées par type
- Fichier, ligne, message, extrait de code
- Exit code 0 si aucune violation, 1 sinon

### Intégration CI/CD

#### Pre-commit hook

`.git/hooks/pre-commit` :

```bash
#!/bin/bash
python3 scripts/check_ai_rules.py || exit 1
```

#### GitHub Actions / CI

```yaml
- name: Check AI Rules
  run: python3 scripts/check_ai_rules.py
```

### Résultats typiques (indicatif)

Un premier scan donne souvent un ordre de grandeur comme :

- **CACHE_RECALCULATION** : quelques violations (à juger au cas par cas, ex. recalcul si cache manquant)
- **END_ACTIVATION_PATTERN** : ~28 violations (strings au lieu de constantes)
- **COORDINATE_NORMALIZATION** : ~100+ violations
- **FALLBACK_ANTI_ERROR** : ~50+ violations
- **FORBIDDEN_TERM** : ~66+ violations

Les chiffres évoluent au fil des corrections.

### Faux positifs (fallback .get)

Un `.get(key, def)` utilisé volontairement pour une clé vraiment optionnelle (config, feature flags, etc.) peut être signalé à tort. Pour éviter le faux positif, ajouter sur la même ligne un commentaire du type `# get allowed` ou `# fallback allowed`. Filtrer au cas par cas ou via une whitelist si besoin.

### Faux négatifs (coordonnées col/row)

Les lignes contenant `"""` sont ignorées pour les comparaisons col/row (pour ne pas signaler du code d'exemple dans les docstrings). Des violations présentes uniquement dans des docstrings ou chaînes multi‑lignes ne sont donc pas détectées ; ce compromis est assumé.

### Valeur / ROI

- Feedback immédiat, déterministe, actionnable (fichier + ligne).
- Intégrable en pre-commit et CI.
- Efficace pour les violations détectables statiquement (ordre de grandeur : 8/10 en ROI).

---

## 2. `ai/analyzer.py` — analyse du step.log

> **Usage** : `python ai/analyzer.py step.log`
>
> **Sortie** : Rapport de validation des règles de jeu (console + fichier optionnel)

### Vue d'ensemble

L'analyzer parse le fichier `step.log` généré par l'entraînement (avec `--step`) et valide la conformité aux règles du jeu (tour_de_jeu.md). Il détecte :

- **Violations** : mouvements invalides, tirs illégaux, charges interdites, etc.
- **Métriques de règles spéciales** : usage des règles d'unités et d'armes.

### Utilisation

```bash
# Générer step.log puis analyser
python ai/train.py --agent <agent> --training-config default --test-only --step --test-episodes 300 2>&1 | tee train.log
python ai/analyzer.py step.log
```

#### Options

```bash
# Filtrer une section spécifique
python ai/analyzer.py step.log 1.6

# Écrire dans un fichier
python ai/analyzer.py step.log --output analyzer.log
```

Sections disponibles : `1.1`, `1.2`, `1.3`, `1.4`, `1.5`, `1.6`, `1.7`, `2.1`, `2.2`, `2.3`, `2.4`, `2.5`, `2.6`, `2.7`, `2.8`

### Structure du rapport

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
| **2.8** | ÉTAT RECONSTRUIT vs ÉTAT MOTEUR |

### Comment un contrôle de déplacement est écrit

Les quatre déplacements contrôlés — **move**, **advance**, **charge**, **pile-in/consolidation** —
suivent la MÊME forme. C'est délibéré : ce dépôt est structuré en miroirs, et son motif d'échec
n°1 est une correction faite d'un côté et pas de l'autre. La charge et les mouvements de fin de
combat ont vécu longtemps sans les trois éléments ci-dessous, et personne ne le voyait parce que
le board x1 neutralise le premier.

1. **Budget converti.** Les jets (advance, charge, réactif) et les seuils de règle (3" pour
   pile-in 12.03 et consolidation 12.08) sont exprimés en **pouces** ; les distances du journal
   sont en **cases**. Tout budget se multiplie donc par `inches_to_subhex`, lu dans l'entête
   `Board:` du log analysé — jamais dans le config courant, qui décrit le prochain run. Les
   autres valeurs de règle (zone d'engagement, métriques, toggles de traversée) viennent de
   l'entête `Run rules:`, pour la même raison (cf. Replay.md §2.3quater).
   *Sans conversion, à x5 un jet de charge de 7 devient un plafond de 7 cases au lieu de 35 :
   toute charge réussie remonte en faute. Inerte à x1.*

2. **Mesure par figurine.** La distance se mesure sur chaque socle commun entre l'état d'avant et
   le segment `[MODELS:]` de la ligne, jamais d'ancre d'escouade à ancre d'escouade.
   *L'ancre peut bondir plus loin qu'aucun socle (reformation) — faux positif — ou moins loin que
   l'un d'eux — vraie violation manquée.*

3. **Chemin vérifié.** Toutes les règles de mouvement renvoient à Moving (03) : le trajet passe
   par `_bfs_shortest_path_length` avec les obstacles de `_build_move_bfs_blockers`, qui lit les
   trois toggles de `game_config['move']` au même endroit que le moteur — on traverse ses
   **alliés** (03.01) et la bande d'engagement ennemie, jamais une figurine ennemie ni un mur.
   *Sans BFS, un déplacement par-dessus un mur n'est jamais signalé.*

   **Le moteur applique la même règle depuis 2026-08-03.** Le contrôle de l'analyzer a longtemps
   été le seul à vérifier le trajet : `charge_build_valid_plan` (11.04) et
   `_assign_cells_toward_enemies` (12.03 / 12.08) retenaient une cellule sur sa distance à vol
   d'oiseau et ne validaient que la case d'arrivée. Les 43 charges et 28 consolidations « au-delà
   du budget » d'un run de 600 épisodes étaient donc de VRAIES violations, pas des faux positifs.
   Les deux planificateurs passent désormais par `shared_utils.model_reach_predicate`, qui
   réutilise le champ géodésique du move (`explain_move_plan_rejection`).

Deux exemptions, portées par des **tags du journal** et non par le registre d'unités :
`[FLY]` (21.03 — vol déclaré : traversée libre, **et 2" retranchés au budget** ; les deux sont
indissociables, la traversée est la contrepartie des 2" payés, sur le move, l'advance ET la
charge) et le keyword `MONSTER/VEHICLE` pour le tir au contact (10.06 / 17.03).

Les cinq sites — move, advance, charge, pile-in/consolidation, move réactif — passent par le MÊME
helper, `ai/analyzer._per_model_move_violation`. Il *mesure* et rend un booléen ; chaque appelant
garde son propre compteur, seule divergence légitime entre eux. Ils ont vécu en cinq copies, et
elles avaient dérivé : le filtre des socles morts n'existait que dans deux d'entre elles.

⚠️ **Un seul verdict, délibérément.** « Trop long » et « chemin bloqué » ne sont pas distinguables
à un coût raisonnable : il faudrait explorer au-delà du budget, ce qui quadruple le flood du BFS
sur les chemins en échec (mesuré : 1,6 → 6,3 ms par socle pour une charge à x5) sans même offrir
de garantie — un détour peut dépasser n'importe quelle marge fixée d'avance. Les compteurs
séparés d'autrefois entretenaient une fiction : celui qui affichait « distance > budget » restait
à 0 en permanence, tout partant dans « chemin bloqué ». Ce que le contrôle établit, et tout ce
qu'il établit : **la figurine n'a pas pu atteindre sa destination dans son budget**.

### 2.8 — État reconstruit vs état moteur (2026-08-09)

Le rapport entier repose sur un état que l'analyzer **reconstruit** par accumulation
d'événements : PV initial moins chaque `Dmg:`, position initiale plus chaque déplacement.
Jusqu'ici, rien ne disait quand cette reconstruction dérivait — une donnée manquante se
propageait jusqu'à la fin de l'épisode, et ressortait sous forme de compteurs bizarres qu'il
fallait trier à la main. Trois triages successifs ont buté sur ce même motif.

Le moteur écrit désormais un instantané d'état par tour (`T{tour} STATE:`, cf.
`Documentation/Chantiers/Replay.md` §2.3quinquies). L'analyzer s'y recale — et **compte
l'écart avant de le corriger** :

```
2.8 ETAT RECONSTRUIT vs ETAT MOTEUR
Morts non vues par l'analyzer (fantomes)  : 0
Unites tuees a tort par l'analyzer        : 0
Figurines mal positionnees (deplacement non journalise) : 0
```

Les trois compteurs n'ont pas la même cause :
- **fantômes** : une mort dont aucune ligne ne parlait (546 lignes du run du 2026-08-08 portaient
  une sauvegarde ratée sans `Dmg:`) — c'est la source des « action sur une unité morte » ;
- **tuées à tort** : l'inverse, une sur-attribution de dégâts ;
- **positions** : un déplacement non journalisé (c'est ainsi que le pile-in muet se manifestait).

**Une valeur non nulle invalide, pour l'épisode concerné, tout contrôle mesurant une distance ou
une adjacence.** C'est le seul compteur du rapport qui se déclenche le jour où un NOUVEL effet
cesse d'être journalisé, au lieu d'attendre qu'on le découvre à la main.

⚠️ **1.6 couvre désormais la phase FIGHT.** Elle en était exclue (`phase in ('MOVE','SHOOT',
'CHARGE')`) — c'est-à-dire exactement là où le défaut vit : 24 unités combattaient deux fois dans
la même phase sur le run du 2026-08-08, sur 15 épisodes, pendant que « Double-activation : 0 »
s'affichait en vert. Le marqueur d'activation de la phase est la ligne `CONSOLIDATED` (12.07 :
une par unité et par phase) — les lignes `FOUGHT` sont par ATTAQUE, il y en a des dizaines.

⚠️ **Les colonnes des sections d'erreurs s'appellent « Joueur 1 » / « Joueur 2 »**, plus « Agent
(P1) » / « Bot (P2) ». L'agent ne tient pas toujours le siège P1 (`agent_seat_mode: random`) : sur
600 épisodes, il était en P2 dans 180. Les tableaux de RÉSULTATS (win methods, VP, wins by
scenario), eux, suivent bien l'agent — ils lisent `AGENT_PLAYER=` dans l'entête.

### Métriques détaillées

#### 1.6 SPECIAL RULES USAGE

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

#### 1.7 WEAPONS RULES USAGE

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
- **CLOSE_QUARTERS** : tir d'une unité ENGAGÉE (10.06), pas « tir à distance 1 ». La grandeur est
  l'engagement — bord à bord, par figurine, zone d'engagement du run — jamais une adjacence d'hex
  mesurée d'ancre à ancre. 10.06 borne un tireur engagé non-MONSTER/VEHICLE aux armes
  [CLOSE-QUARTERS] **et** aux unités avec lesquelles son escouade est engagée ; les deux compteurs
  (`close_quarters_shot_at_unengaged_target`, `engaged_shot_with_non_close_quarters_weapon`)
  suivent exactement ces deux clauses.

**Validation ASSAULT :** L'analyzer ne compte que les tirs effectués après une action ADVANCE du même tour pour la même unité.

### Résumé (Summary)

En fin de rapport, un résumé affiche :
- 1.1 : Erreurs de mouvement
- 1.2 : Erreurs de tir
- 1.3 : Erreurs de charge
- 1.4 : Erreurs de combat
- 1.5 : Actions dans mauvaise phase
- 1.6 : Double-activation (phase + réactif) — la ligne du résumé somme les doublons par phase ET
  ceux du move réactif, c'est-à-dire exactement la grandeur qui entre dans le total d'erreurs.
  La section 1.6 détaillée les sépare (ligne `REACTIVE`).
- 2.1 à 2.8 : Cohérence, intégrité, etc.

### Intégration au workflow

**Fichiers de config :**
- `config/unit_rules.json` : règles d'unités
- `config/weapon_rules.json` : règles d'armes

**Documentation :**
- [§4 — Workflow de correction des violations](#4-workflow-de-correction-des-violations)
- [§3 — `ai/hidden_action_finder.py`](#3-aihidden_action_finderpy--actions-non-loguées)
- [`Documentation/Reference/moteur/tour_de_jeu.md`](../moteur/tour_de_jeu.md) : règles du jeu

---

## 3. `ai/hidden_action_finder.py` — actions non loguées

> **Usage** : après une run avec `--step` (et éventuellement avec `debug.log`), exécuter `python ai/hidden_action_finder.py`
>
> **Entrées** : `step.log`, `debug.log` (optionnel pour certaines vérifications)
> **Sortie** : `hidden_action_finder_output.log` + résumé en console

### Objectif

Comparer ce qui s'est réellement passé (mouvements, attaques) avec ce qui est enregistré dans `step.log`. Le script détecte :

1. **Mouvements faits mais non logués** dans step.log (position changes dans debug vs MOVE/FLED/CHARGE/ADVANCE dans step).
2. **Attaques faites mais non loguées** dans step.log (attack_executed dans debug vs SHOOT/FIGHT dans step).
3. **Attaques manquantes en phase fight** : unités avec cibles valides qui n'ont pas attaqué (aucune attaque loguée).
4. **Avertissements** issus de debug.log (ex. unité adjacente à l'ennemi mais n'ayant pas attaqué).

### Prérequis

- **step.log** : généré par `python ai/train.py ... --step --test-episodes N`.
- **debug.log** : généré si le moteur écrit des logs `[POSITION CHANGE]`, `[FIGHT DEBUG]`, `[SHOOT DEBUG]` (selon configuration / debug du jeu). Sans debug.log, le script signale son absence et ne peut pas faire les vérifications 1–4.

### Utilisation

```bash
# Depuis la racine du projet, après avoir produit step.log (et idéalement debug.log)
python ai/hidden_action_finder.py
```

Sortie principale : **hidden_action_finder_output.log**. Un résumé (succès ou nombre d'erreurs) est aussi affiché en console.

### Intégration au workflow

Ce script est typiquement enchaîné avec l'analyzer dans le workflow de validation des règles :

1. Générer les logs : `python ai/train.py ... --step --test-episodes N 2>&1 | tee movement_debug.log`
2. Analyser les violations de règles : `python ai/analyzer.py step.log`
3. Vérifier la cohérence des logs : `python ai/hidden_action_finder.py`

Voir [§4 — Workflow de correction des violations](#4-workflow-de-correction-des-violations) pour le workflow complet et [§2 — `ai/analyzer.py`](#2-aianalyzerpy--analyse-du-steplog) pour l'analyzer.

---

## 4. Workflow de correction des violations

> Guideline / prompt pour automatiser les correctifs. À utiliser avec l'analyzer et le hidden_action_finder (voir [§2](#2-aianalyzerpy--analyse-du-steplog), [§3](#3-aihidden_action_finderpy--actions-non-loguées)).

### WORKFLOW ITÉRATIF

#### Phase 1 : EXÉCUTION & ANALYSE INITIALE
1. Exécuter : `python ai/train.py --agent SpaceMarine_Infantry_Troop_RangedSwarm --training-config default --rewards-config SpaceMarine_Infantry_Troop_RangedSwarm --test-only --step --test-episodes 15 2>&1 | tee movement_debug.log ; python ai/analyzer.py step.log ; python ai/hidden_action_finder.py`

2. Analyser les résultats dans cet ordre de priorité :
   - **FATAL ERRORS** (ValueError, exceptions) → STOP, fix immédiat
   - **Résumé de `ai/analyzer.py`** : compter les violations de règles (par catégorie) — voir [§2](#2-aianalyzerpy--analyse-du-steplog)
   - **Output de `ai/hidden_action_finder.py`** : mouvements/attaques non logués — voir [§3](#3-aihidden_action_finderpy--actions-non-loguées)
   - **Patterns récurrents** : si >50% des violations sont du même type → investiguer ce type en priorité
   - **Priorité des violations** :
     1. **UNIT POSITION COLLISIONS** (2+ unités sur même hex) → CRITIQUE
     2. **Shoot at friendly unit** → CRITIQUE
     3. **Moves to adjacent enemy** → HAUTE
     4. **Shoot at engaged enemy** → HAUTE
     5. **Charges from adjacent hex** → MOYENNE
     6. **Charge after fled** → MOYENNE
     7. **Shoot after fled** → MOYENNE
     8. **Advances from adjacent hex** → BASSE
     9. **Shoot through wall** → BASSE

#### Phase 2 : INVESTIGATION CIBLÉE (si violations détectées)

**Règle d'or** : Ne jamais modifier le code sans avoir identifié la root cause avec certitude.

##### 2.1 Pour chaque type de violation, investiguer dans cet ordre :

**UNIT POSITION COLLISIONS** :
1. Extraire 2-3 exemples spécifiques (Episode #X, Turn Y, action_type: Unit A, Unit B at (col,row))
2. Vérifier dans `step.log` les actions impliquées (mouvement/charge)
3. Vérifier dans `movement_debug.log` si les validations de position ont été effectuées
4. Identifier si le problème vient de :
   - Validation insuffisante avant mouvement/charge
   - Race condition (deux unités se déplacent simultanément)
   - Position non mise à jour correctement après mouvement

**Shoot at friendly unit** :
1. Extraire 2-3 exemples spécifiques (E1 T1 SHOOT : Unit X SHOT at Unit Y)
2. Vérifier si `target_id` est une unité amie
3. Identifier si le problème vient de :
   - Filtrage des cibles insuffisant dans `valid_target_pool_build`
   - Validation manquante avant l'exécution du tir
   - Changement d'appartenance après la construction de la pool (improbable)

**Moves to adjacent enemy** :
1. Extraire 2-3 exemples spécifiques (E1 T1 MOVE : Unit X MOVED from (a,b) to (c,d))
2. Vérifier dans `movement_debug.log` si `build_enemy_adjacent_hexes` a été appelé
3. Vérifier si la destination est dans `enemy_adjacent_hexes`
4. Identifier si le problème vient de :
   - `build_valid_destinations` ne filtre pas correctement les hex adjacents à l'ennemi
   - Validation manquante avant l'exécution du mouvement

**Shoot at engaged enemy** :
1. Extraire 2-3 exemples spécifiques (E1 T1 SHOOT : Unit X SHOT at Unit Y)
2. Vérifier si la cible est engagée (adjacente à une unité amie)
3. Identifier si le problème vient de :
   - Filtrage insuffisant dans `valid_target_pool_build` (règle de l'unité adjacente)
   - Validation manquante avant l'exécution du tir

**Charges from adjacent hex** :
1. Extraire 2-3 exemples spécifiques (E1 T1 CHARGE : Unit X CHARGED Unit Y from (a,b) to (c,d))
2. Vérifier si l'unité était déjà adjacente à la cible avant le charge
3. Identifier si le problème vient de :
   - `charge_build_valid_destinations` n'exclut pas les positions où l'unité est déjà adjacente
   - Validation manquante avant l'exécution du charge

**Charge after fled / Shoot after fled** :
1. Extraire 2-3 exemples spécifiques
2. Vérifier si l'unité a fui dans le même tour/phase
3. Identifier si le problème vient de :
   - Flag `units_fled` non mis à jour correctement
   - Validation manquante pour vérifier si l'unité a fui avant charge/shoot

**Advances from adjacent hex** :
1. Extraire 2-3 exemples spécifiques
2. Vérifier si l'unité était adjacente à un ennemi avant l'advance
3. Identifier si le problème vient de :
   - Validation manquante dans `shooting_unit_activation_start` (CAN_ADVANCE check)
   - Flag `_can_advance` mal calculé

**Shoot through wall** :
1. Extraire 2-3 exemples spécifiques
2. Vérifier si un mur bloque la ligne de vue
3. Identifier si le problème vient de :
   - `_has_line_of_sight` ne détecte pas correctement les murs
   - Cache LoS obsolète

##### 2.2 Confirmation de root cause :
- **Critère de certitude** : Avoir identifié le code exact qui cause la violation (fichier + ligne + condition)
- **Preuve** : Au moins 2 exemples concrets qui montrent le pattern
- **Si incertain** : Créer un script d'investigation ciblé (max 30 lignes) pour confirmer
- **Référence** : Vérifier que la violation est bien contraire à `tour_de_jeu.md` ou aux règles du jeu

#### Phase 3 : FIX (seulement si root cause identifiée à 100%)

**Avant chaque fix** :
1. Vérifier que le fix ne casse pas d'autres règles (lire le contexte du code)
2. Vérifier que le fix est conforme à `tour_de_jeu.md`
3. Fix minimal : modifier uniquement ce qui est nécessaire pour empêcher la violation
4. Ajouter un commentaire expliquant le fix et référençant la règle si non évident

**Après chaque fix** :
1. Relancer le workflow (Phase 1)
2. Vérifier que le nombre de violations diminue pour la catégorie concernée
3. Vérifier que le fix n'a pas introduit de nouvelles violations
4. Si violations augmentent → REVERT immédiat, investiguer plus

#### Phase 4 : CRITÈRES D'ARRÊT

**Arrêter quand** :
- Toutes les violations critiques sont résolues (UNIT POSITION COLLISIONS, Shoot at friendly unit) ET
- Violations haute priorité < 5% des actions totales OU
- 3 itérations consécutives sans amélioration significative (<10% réduction) OU
- Toutes les violations restantes sont identifiées comme faux positifs ou comportements voulus

**Si arrêt sans résolution complète** :
- Documenter les violations restantes avec exemples concrets
- Expliquer pourquoi elles ne peuvent pas être résolues (limitation de conception, edge case rare, etc.)
- Prioriser les violations les plus fréquentes pour une résolution future

### RÈGLES D'OPTIMISATION TOKENS

1. **Ne pas relire les mêmes logs** : Si déjà analysé, référencer l'analyse précédente
2. **Analyser par échantillonnage** : 2-3 exemples suffisent pour identifier un pattern
3. **Scripts d'investigation courts** : Max 30 lignes, ciblés sur un problème spécifique
4. **Pas de répétition** : Ne pas réexpliquer ce qui a déjà été fait
5. **Focus sur les changements** : Après un fix, analyser seulement ce qui a changé
6. **Prioriser par impact** : Traiter d'abord les violations les plus fréquentes

### FORMAT DE RAPPORT ITÉRATIF

Pour chaque itération, rapporter :

```
[ITÉRATION N]
Violations détectées : [catégorie: nombre, ...]
Priorité cible : [catégorie la plus fréquente]
Root cause identifiée : [description concise]
Fix appliqué : [fichier + ligne + changement]
Résultat : [réduction % ou "stagnant"]
```

### EXCEPTIONS

- **Fatal errors** : Fix immédiat sans investigation approfondie
- **Violations < 1%** : Documenter mais ne pas prioriser
- **Comportements voulus** : Si la violation fait partie des règles du jeu (documenter dans tour_de_jeu.md)

### CONTEXTE IMPORTANT

- Les violations peuvent venir de :
  - Validation insuffisante dans les handlers de phase
  - Race conditions entre actions concurrentes
  - États du jeu non synchronisés (flags, pools)
  - Logique de filtrage incomplète dans les pools de validité
- Toujours vérifier `tour_de_jeu.md` pour confirmer que c'est bien une violation
- Certaines "violations" peuvent être des faux positifs du parser `ai/analyzer.py` — voir [§2](#2-aianalyzerpy--analyse-du-steplog)

---

## 5. `scripts/obs_channel_audit.py` — canaux d'observation

> **Usage** : `python3 scripts/obs_channel_audit.py` (venv projet activé)
>
> **Entrées** : les scénarios de `config/agents/ArmageddonAgent/scenarios/training/`, découverts par
> glob (`scenario_training_*.json`) — aucune liste à tenir à jour.
> **Sortie** : rapport console. Aucune écriture : ni config, ni modèle, ni state.
> **Durée** : ~15 min (24 épisodes en actions masquées aléatoires + une passe de gradient).

### Objectif

Une observation peut être fausse de deux façons que ni les tests ni l'entraînement ne signalent :

1. **le moteur n'écrit pas le canal** — le champ existe, il vaut toujours la même chose ;
2. **le réseau ne lit pas le canal** — le champ arrive bien à la policy, mais aucun chemin de
   calcul ne le consomme.

Les deux sont **silencieux par construction** : l'entraînement converge, les tests passent, et
l'agent apprend simplement sans l'information. Le défaut fondateur de cet outil est le drapeau
`fought` de `UNIT_BIN_FIELDS`, éteint **des deux camps pendant tout le pipeline squad** :
`observation_builder` le lisait dans `game_state["units_attacked"]`, une clé que quatre sites
créaient et remettaient à zéro et qu'**aucun écrivain n'a jamais peuplée** (mesuré : 0 step sur
2455). La clé vivante était `units_fought`. Corrigé le 2026-08-08 ; la clé morte est supprimée.

Ce script mesure les deux propriétés au lieu de les déduire.

### Volet A — le MOTEUR remplit-il ?

24 épisodes (chaque scénario de la banque × 12 graines), actions masquées aléatoires sur le vrai
`W40KEngine`. Pour **chaque clé d'observation et chaque champ de son registre** : min, max,
fraction non nulle. Les libellés viennent des registres (`observation_entities.py`,
`observation_weapon_profiles.py`, `spatial_grid.GRID_CHANNEL_NAMES`), jamais d'une liste recopiée
— un canal inséré au milieu ferait sinon mentir tout le rapport.

**Un champ dont `min == max` sur tout le corpus est un canal que le moteur ne remplit pas.**

Trois familles se ressemblent dans la sortie et ne se traitent pas pareil :

| Ce qu'on lit | Ce que c'est | Quoi faire |
|---|---|---|
| Slot d'ids au-delà du nombre observé, colonne `*_reserved_*` | **pré-dimensionnement voulu** (une capacité ajoutée reste gratuite) | rien |
| Champ à masque de camp (`enemies.is_ally`, `allies.los_can_see`, `enemies.hidden`…) | **zéro par contrat** (§3.3 : les features propres à un camp sont nulles pour l'autre) | rien |
| Champ censé varier et qui ne varie pas | **canal mort, ou sans signal sur ce terrain** | investiguer |

La troisième famille demande une mesure de plus avant de conclure : un canal peut être
correctement câblé et pourtant sans signal. Deux cas mesurés le 2026-08-08, tous deux réels et
tous deux **non** des bugs de code :

- `deploy_cand_cont.los_exposure` / `potential_los_exposure` toujours nuls — les deux zones de
  déploiement sont à ~290 subhex et la LoS sol ne passe jamais entre elles ;
- `cover_vs_observer` toujours nul côté ennemi — sur 2583 paires, les 146 visibles étaient
  **toutes** `fully_visible` : 13.08 ne peut pas s'appliquer à une cible que 13.10 masque déjà.

### Volet B — le RÉSEAU lit-il ?

La vraie policy (`PointerMaskablePolicy` + `SpatialCombinedExtractor`), avec l'architecture **lue
dans le JSON de l'agent** (`model_params.policy_kwargs`), sur un échantillon de réservoir des
observations du volet A (uniforme sur tout le corpus — sans quoi les champs de combat sortiraient
« non lus » faute d'avoir été échantillonnés). On rétropropage `Σ logits + Σ valeur`.

**Un champ dont le gradient est exactement nul est reçu mais jamais lu.**

Trois précautions, sans lesquelles le volet B ment :

- **Échauffement des statistiques.** `EntityRunningNorm` clippe à ±10 σ. Avec les statistiques
  d'initialisation (mean=0, var=1), toute feature d'échelle > 10 saturerait et sortirait un
  gradient nul — faux positif. Une passe `train()` suffit : c'est un accumulateur de Chan, pas une
  moyenne mobile, donc la première passe pose déjà les statistiques exactes du lot.
- **Saturation rapportée par champ**, sur les seules entités **présentes**. Compter les lignes de
  padding ferait passer pour saturée toute feature proche d'une constante.
- **Clés d'ids** (`*_ability_ids`, `*_status_ids`, `*_wpn_rule_ids`) : non différentiables. Elles
  sont vérifiées sur le gradient des **lignes d'`EmbeddingBag`** correspondant aux ids observés.

### Interpréter la sortie

- `champs à gradient EXACTEMENT nul` → `(aucun)` : tout ce que le moteur écrit atteint le réseau.
- Un champ y apparaît avec `(déjà constant en A)` : le moteur ne l'écrit pas — c'est le volet A
  qu'il faut traiter, pas le réseau.
- Un champ y apparaît avec `<-- VARIABLE mais NON LU` : **c'est le cas grave.** Le moteur produit
  de l'information que l'extracteur jette (clé absente de son `expected_keys`, tranche mal
  découpée, masque qui annule l'entité).
- `grille : couverture par canal` : les 9 canaux doivent être non nuls. `level` reste à 0 si aucun
  terrain de la banque ne déclare d'étage ; `move_cost` reste à 0 hors phase de mouvement.
- `clés d'ids` : `lignes avec gradient` doit égaler `ids observés`.

### Quand le relancer

- **Après tout ajout de champ d'observation** — c'est sa raison d'être : le champ neuf doit
  apparaître variable en A et lu en B.
- Après une modification de `spatial_extractor.py` ou `pointer_policy.py` (une tranche décalée
  déconnecte une famille entière sans que rien ne lève).
- Après un changement de terrain ou de roster de la banque : le corpus change, donc les canaux
  « sans signal sur ce terrain » aussi.

⚠️ **Le script ne gate rien** : il imprime, il ne rend pas de code d'erreur sur un canal mort, et
il n'appartient pas à la commande de vérification large. Le lire fait partie de la tâche. Lui
donner une sortie non nulle contre une liste d'exemptions déclarée reste ouvert.

### Voir aussi

- `Documentation/Reference/training/observation_et_actions.md` — ce que chaque canal signifie.
- `engine/observation_entities.py` — les registres, source unique des noms de champs.
- [§3 — `ai/hidden_action_finder.py`](#3-aihidden_action_finderpy--actions-non-loguées) et [§1 — `scripts/check_ai_rules.py`](#1-scriptscheck_ai_rulespy--vérification-statique-du-code) — les deux autres outils de conformité, dans la commande de vérification de l'utilisateur.
