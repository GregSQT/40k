# Escouade - spec alignee code actuel

## Objectif

Faire evoluer le moteur de `1 unit = 1 figurine` vers `1 unit = 1 escouade (N figurines)` en restant compatible avec:
- architecture actuelle `engine/w40k_core.py`,
- handlers de phase (`movement_handlers.py`, `shooting_handlers.py`, etc.),
- single source of truth (`units_cache` dans `shared_utils.py`),
- pipeline RL actuel (MaskablePPO micro + macro wrapper deja present).

## Etat actuel a respecter (verifie dans le code)

1. Phases: `deployment -> command -> move -> shoot -> charge -> fight`.
2. Activation sequentielle via pools (`move_activation_pool`, `shoot_activation_pool`, ...).
3. Action space gym: `Discrete(13)` (0..12) dans `W40KEngine`.
4. Masques via `ActionDecoder.get_action_mask*`.
5. Single source of truth en jeu:
   - position/HP des vivants via `game_state["units_cache"]`,
   - morts absents du cache,
   - update HP via `update_units_cache_hp`,
   - checks vie via `is_unit_alive`.
6. Tir deja structure en activation de l unite active (`shooting_unit_activation_start`) avec `valid_target_pool`, `los_cache`, `units_advanced`.
7. Macro deja present:
   - `game_state["macro_intent_id"]`, `macro_detail_type`, `macro_detail_id`,
   - `engine.build_macro_observation()`,
   - wrappers `MacroTrainingWrapper` / `MacroVsBotWrapper` dans `ai/macro_training_env.py`.

## Decision d architecture (honnete)

### Ce qui est recommande

- Garder le concept "unit active" = "escouade active".
- Introduire les figurines comme sous-entites de `unit`.
- Conserver les pools d activation au niveau escouade (pas au niveau figurine).
- Faire les actions internes (mouvement/tir) au niveau des figurines de l escouade.

### Ce qui est risque

- Passer directement a un controle RL "1 action brute par figurine" fera exploser l espace d actions.
- Entrainer micro et macro en meme temps des le debut est instable.

## Nouveau modele de donnees cible

## Unit (escouade)

```python
unit = {
    "id": str,                 # id escouade (inchange)
    "player": int,
    "unitType": str,
    "DISPLAY_NAME": str,
    "models": [               # NOUVEAU
        {
            "id": str,         # model id unique (ex: "<unit_id>#0")
            "col": int,
            "row": int,
            "HP_CUR": int,
            "HP_MAX": int,
            "RNG_WEAPONS": list,
            "CC_WEAPONS": list,
            "selectedRngWeaponIndex": int | None,
            "selectedCcWeaponIndex": int | None,
            "SHOOT_LEFT": int,
            "ATTACK_LEFT": int,
        }
    ],
    "COHERENCY_MAX_DIST": int, # ex: 1 hex
}
```

## Caches (extension)

```python
game_state["units_cache"]      # conserve: source of truth escouade (vivantes)
game_state["models_cache"]     # NOUVEAU: source of truth figurines vivantes
game_state["squad_cache"]      # NOUVEAU: metriques de cohesion par escouade
```

Notes:
- Pas de fallback silencieux.
- Coordonnees toujours normalisees (`normalize_coordinates`, `get_unit_coordinates`).
- Toute ecriture HP en jeu passe par fonctions cache dediees.

## Regles de cohesion escouade

Invariants:
1. Chaque figurine vivante doit etre adjacente a au moins 1 figurine vivante de la meme escouade.
2. Une escouade vivante doit rester en un seul composant connexe.

Validation obligatoire:
- fin de mouvement escouade,
- fin de resolution tir si retrait de pertes,
- fin de toute activation modifiant positions/HP.

API cible:

```python
def validate_squad_coherency(game_state: dict, squad_id: str) -> None: ...
```

## Mouvement coordonne (aligne handlers actuels)

## Principe

Une action `move` pour une escouade reste unique au niveau engine, mais genere un plan multi-figurines:
1. construire destinations candidates pour toutes les figurines,
2. valider collisions / murs / enemy adjacency / limites de distance,
3. appliquer toutes les positions (transaction atomique),
4. valider cohesion,
5. commit cache + `end_activation(...)`.

Si une destination figurine est invalide, l action complete est refusee.

## Fichiers impactes

- `engine/phase_handlers/movement_handlers.py`
  - etendre `movement_build_valid_destinations_pool` pour plan escouade,
  - ajouter executeur atomique d un plan multi-figurines.
- `engine/phase_handlers/shared_utils.py`
  - ajouter update position model-level cache.

## Strategie long terme mouvement (moteur)

Conclusion retenue pour la **fidelite regles** et la **performance** sur le long terme:

1. **Etage 1 — deplacement global ("leader + offsets rigides")**
   - Choisir une **figurine ancre** (deterministe: ex. plus proche du centre de l escouade, ou regle fixe par type).
   - Calculer une translation ancre -> destination (BFS / budget MOVE comme aujourd hui sur l ancre).
   - Appliquer le meme vecteur a toutes les figs (formation rigide).
   - **Valider tout le plan en une transaction atomique**: plateau, murs, collisions (toutes empreintes), EZ, budget par fig si necessaire, puis **cohesion** en sortie.
   - Si une fig est illegale: **refus global** (aucun deplacement partiel).

2. **Etage 2 — placement fin**
   - Apres l etage 1 (ou a la place si le joueur ignore le mouvement groupe), deplacements **par figurine** bornes (budget residuel, memes regles, cohesion verifiee a chaque micro-action ou au commit selon le flux UI).

3. **Ce qu on evite en premier jet**
   - N destinations BFS independantes sans plan global (explosion combinatoire, invalidations en cascade, debug penible).
   - Changer la semantique de distance (ex. "distance depuis l empreinte entiere") tant que le moteur hex + ancre n est pas stabilise: risque de re-ecrire les regles deux fois.

## UX mouvement escouade (vision cible + conclusions honnetes)

### Vision UX acceptee comme cible finale (joueur)

- **Double-clic** sur une figurine de l escouade -> mode **"deplacement de l escouade"**.
- **Preview** pour toute l escouade; l enveloppe visuelle souhaitee suit les figs les plus a l exterieur (enveloppe / union des empreintes projetees), **mais** la semantique moteur doit rester: *ou peut aller l ancre tout en gardant un plan legal pour toutes les figs*.
- Pendant le geste: les figs suivent la souris en cherchant a **preserver les positions relatives** par rapport a la fig cliquee au moment du double-clic; idealement adaptation aux murs, figs alliees, zones d engagement (effet "glisse").
- **Bouton "Valider"** le mouvement d escouade; sinon possibilite de **deplacer chaque fig individuellement** pour le placement fin (comportement actuel + **contrainte de cohesion**).

Cette UX est la meilleure en termes de **ressenti plateau**; elle est aussi la plus **couteuse** techniquement si on la fait "tout reel" des le MVP.

### Definition correcte de la zone "legale" (preview)

- **Erreur courante**: l union des hex atteignables par **chaque** fig prise separement (trop optimiste: inclut des ancres ou une partie de l escouade pourrait aller mais pas le groupe coherent).
- **Definition fidele**: l ensemble des positions de l **ancre** telles qu il **existe au moins un plan complet** valide pour **toutes** les figurines (collisions, murs, EZ, MOVE, cohesion).
- En pratique: calcul **exact** de ce masque = **tres couteux** (combinatoire selon taille d escouade et carte). **Recommandation**: preview **approchante** (conservatrice ou legerement optimiste) + **validation stricte au drop** (atomique). Si la preview est optimiste, quelques cases affichees peuvent etre refusees au commit: accepter ce compromis ou investir dans un raffinement (sous-echantillonnage, cache, etc.).

### Glissement temps reel ("glisse le long des murs")

- A chaque frame (ou chaque pas discret de souris): resoudre collisions / EZ / cohesion / budget pour **N** figs = **solveur de contraintes** sur grille discrete.
- **Faisable** mais non trivial; risques: jitter, ordre d evaluation non deterministe, divergence entre **projection visuelle** et **commit moteur**.
- Les regles restent **discretes** (hex): le drag continu est une **approximation**; la verite regle est au **commit** (plan atomique valide par le moteur).

### Preservation des positions relatives au drop

- Apres translation ideale, des cases peuvent etre prises / illegales: probleme d **assignation** fig -> case legale (minimiser distance a l offset souhaite + penalites cohesion).
- **MVP**: matching **glouton priorise** (ordre fixe des figs, couts deterministes).
- **Polish**: Hungarian ou autre si besoin de qualite d assignation.

### Cohesion pendant le drag

- **Ne pas** appliquer la cohesion stricte a chaque micro-pas du drag (bloque le joueur, UX frustrante).
- **Checkpoint**: cohesion (et autres invariants) verifiees au **drop** et au **valider**; le placement fin par fig idem.

## Plan d implementation UI / moteur (recommande, par phases)

### Phase A — MVP (gros du benefice, cout raisonnable)

1. Double-clic -> mode escouade; **ancre** = fig cliquee.
2. Preview: **approximation** (ex. BFS ancre avec budget `MOVE - rayon_formation_estime` pour reduire faux positifs grossiers), assumee **non garantie exacte**; documenter le compromis.
3. Pendant le drag: **suivi visuel en formation rigide** (offsets fixes), **sans** solveur temps reel complet (les contraintes ne s appliquent qu au commit).
4. Au **drop**: proposition = offsets rigides -> **solveur d assignation** vers cases legales les plus proches -> **plan atomique** refuse si impossible.
5. Bouton **Valider** puis **placement fin** par figurine (code actuel + cohesion).

### Phase B — apres stabilite de la Phase A

- Glissement **contraint** en temps reel (projection sur hex legaux par frame ou par pas discret stable).
- Preview **raffinee** (ex. tester un plan complet sur un sous-ensemble d hex ancres + expansion / cache).

### Phase C — polish

- Feedback visuel: figs en conflit, hors budget, empreinte projetee.
- Option UI "relacher la formation" (desactive partiellement l offset rigide pour laisser le solveur rearranger plus librement).

### Anti-patterns

- Implémenter Phase B + preview exacte **avant** Phase A stable.
- Melanger validation stricte et feedback drag sans separation claire **visualisation** vs **commit moteur**.

## Tir escouade: declaration puis resolution

## Pourquoi il faut changer

Le flux actuel est "unite active tire" avec choix cible immediate.
Pour une escouade, il faut d abord figer toutes les declarations, puis resoudre.

## Nouveau flux SHOOT

1. Activation escouade (inchange au niveau pool).
2. Declaration des tirs figurine par figurine:
   - chaque figurine choisit `weapon_index` + `target_unit_id` selon LoS/range/regles.
3. Verrouillage:
   - aucune resolution avant que toutes les declarations soient validees.
4. Resolution:
   - ordre deterministe (index de figurine ou ordre declaration fixe),
   - degats via cache HP,
   - suppression morts du cache,
   - maintenance `valid_target_pool` et `los_cache`.
5. Fin activation via `end_activation(...)`.

## Structures proposees

```python
game_state["pending_squad_shoot_intents"] = {
    squad_id: [
        {
            "model_id": str,
            "weapon_index": int,
            "target_unit_id": str,
        }
    ]
}
```

## Fichiers impactes

- `engine/phase_handlers/shooting_handlers.py`
  - `shooting_unit_activation_start` devient "start escouade",
  - ajout sous-flow declaration/lock/resolution.
- `engine/action_decoder.py`
  - adapter mapping actions de tir (slots) pour un contexte escouade.

## Observation et action mask (RL)

## Observation (micro)

Mettre a jour `engine/observation_builder.py`:
- conserver sections globales existantes,
- remplacer bloc "unit singleton" par:
  - features agreges escouade (taille, cohesion, puissance),
  - features top-k figurines (position relative, HP, arme active),
  - cibles visibles par figurine (ou agregat borne).

Attention: `obs_size` est strictement validee par config. Toute evolution d observation impose mise a jour config training.

## Action space (micro)

Garder `Discrete(13)` comme enveloppe initiale (migration controlee), puis etendre si necessaire:
- move actions deviennent "strategie/plan escouade" au lieu "destination unique figurine",
- shoot slots pilotent une declaration factorisee,
- masques doivent interdire toute action impossible.

## Strategie agent (micro + macro)

## Etat reel du projet

Tu as deja un niveau macro fonctionnel dans le code:
- `macro_intent_id` et detail cible dans game_state,
- `build_macro_observation`,
- `MacroTrainingWrapper` qui choisit unite + intent, puis laisse les micro-models executer.

## Recommandation honnete

1. Continuer avec **un micro-agent PPO par type d escouade** (policy sharing), pas un modele par instance d escouade.
2. Garder le macro existant, mais le geler au debut.
3. Stabiliser d abord le micro "escouade multi-figurines".
4. Reprendre ensuite entrainement macro sur le nouveau micro stable.

Pourquoi: minimiser non-stationnarite et simplifier debug.

## Plan de migration concret (4 PR)

## PR1 - Data model et caches

- `engine/game_state.py`: charger `models` par unit.
- `shared_utils.py`: ajouter `models_cache` + helpers update/get/is_alive model-level.
- garder compatibilite stricte des invariants actuels de phase et pools.

## PR2 - Mouvement escouade

- `movement_handlers.py`: plan multi-figurines atomique.
- validation cohesion apres move.
- tests unitaires: collisions, murs, enemy adjacency, rupture cohesion.

## PR3 - Tir declaration/resolution

- `shooting_handlers.py`: intents de tir escouade.
- declaration complete avant resolution.
- tests: restrictions advance/adjacent/pistol, morts en chaine, ordre deterministe.

## PR4 - RL et training

- `observation_builder.py`: encodage escouade.
- `action_decoder.py`: masks escouade.
- `config/agents/*_training_config.json`: obs_size + params associes.
- re-train micro puis macro.

## Risques majeurs et mitigation

1. Explosion combinatoire des declarations de tir.
   - Mitigation: top-k cibles + factorisation de l action.
2. Bugs de cohesion apres pertes.
   - Mitigation: validation systematique post-action.
3. Instabilite PPO.
   - Mitigation: entrainement en 2 etages (micro puis macro).

## Criteres d acceptance

1. Aucune escouade ne termine une activation hors cohesion.
2. Mouvement escouade atomique (tout ou rien).
3. Tous les tirs escouade sont declares avant la premiere resolution.
4. Les action masks restent stricts (aucune action illegale autorisee).
5. Regression tests passent sur scenarios existants + nouveaux scenarios escouade.

## Definition of done (MVP escouade)

- Une partie complete tourne avec escouades multi-figurines sur les 6 phases.
- Les logs de phase restent lisibles et deterministes.
- Le micro PPO apprend sans chute brutale de stabilite.
- Le macro wrapper fonctionne encore sans refonte majeure.
