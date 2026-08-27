# ai/analyzer.py - Guide de l'analyseur step.log

> **Usage** : `python ai/analyzer.py step.log`
>
> **Sortie** : Rapport de validation des règles de jeu (console + fichier optionnel)

---

## 📋 Table des matières

- [Vue d'ensemble](#vue-densemble)
- [Utilisation](#utilisation)
- [Structure du rapport](#structure-du-rapport)
- [Comment un contrôle de déplacement est écrit](#comment-un-contrôle-de-déplacement-est-écrit)
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
python ai/train.py --agent <agent> --training-config default --test-only --step --test-episodes 300 2>&1 | tee train.log
python ai/analyzer.py step.log
```

### Options

```bash
# Filtrer une section spécifique
python ai/analyzer.py step.log 1.6

# Écrire dans un fichier
python ai/analyzer.py step.log --output analyzer.log
```

Sections disponibles : `1.1`, `1.2`, `1.3`, `1.4`, `1.5`, `1.6`, `1.7`, `2.1`, `2.2`, `2.3`, `2.4`, `2.5`, `2.6`, `2.7`, `2.8`

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
| **2.8** | ÉTAT RECONSTRUIT vs ÉTAT MOTEUR |

---

## Comment un contrôle de déplacement est écrit

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

---

## 2.8 — État reconstruit vs état moteur (2026-08-09)

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
- **CLOSE_QUARTERS** : tir d'une unité ENGAGÉE (10.06), pas « tir à distance 1 ». La grandeur est
  l'engagement — bord à bord, par figurine, zone d'engagement du run — jamais une adjacence d'hex
  mesurée d'ancre à ancre. 10.06 borne un tireur engagé non-MONSTER/VEHICLE aux armes
  [CLOSE-QUARTERS] **et** aux unités avec lesquelles son escouade est engagée ; les deux compteurs
  (`close_quarters_shot_at_unengaged_target`, `engaged_shot_with_non_close_quarters_weapon`)
  suivent exactement ces deux clauses.

**Validation ASSAULT :** L'analyzer ne compte que les tirs effectués après une action ADVANCE du même tour pour la même unité.

---

## Résumé (Summary)

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

---

## Intégration au workflow

**Documentation :**
- [Fix_violations_guideline.md](Fix_violations_guideline.md) : guideline / prompt pour automatiser les correctifs
- [Hidden_action_finder.md](Hidden_action_finder.md) : détection des actions non loguées (step.log vs debug.log)
- [../AI_TURN.md](../moteur/AI_TURN.md) : règles du jeu

**Fichiers de config :**
- `config/unit_rules.json` : règles d'unités
- `config/weapon_rules.json` : règles d'armes
