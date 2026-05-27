# Squad - spec implementation finale (v3.7)

> v3.7 : corrections post-audit (round 6).
> Corrections : INVUL_SAVE convention 0->7 (aligne sentinel observation_builder:1332),
> calculate_hex_distance documente en subhexes (B2B==1, ER<=inches_to_subhex),
> PR2 = moteur uniquement (action decoder non migre avant PR4 — pas testable RL),
> OC_TOTAL vs OC singleton note explicite en PR1, fight_pile_in_plan type de retour
> list[tuple[str,int,int]]|None documente, charge_build_valid_plan : validation ER finale
> obligatoire apres construction plan (condition (b) ne garantit pas l ER),
> BFS deploiement ordre deterministe (FIFO, direction-index croissant 0-5),
> assertion obs_size==357 ajoutee aux criteres PR4 (a supprimer/adapter).
>
> v3.6 : corrections post-audit code (round 5) + sweep systematique.
> Corrections : section "etat actuel" corrigee (Discrete(31), zone_intents, MacroTraining fantomes),
> units_fled reset = Command phase (pas Movement), ARMOR_SAVE/INVUL_SAVE/T ajoutes dans models_cache,
> fight_unit_activation_start = nouvelle fonction (pas refactoring), retrait fin de tour clarifie
> (deterministe PR3, interactif eventuel PR4), BFS greedy sans backtracking documente explicitement,
> algorithme Pile In defini (greedy par index, critere B2B puis distance), algorithme charge
> defini (ordre par index, tie-break BFS), ordre cible->arme melee explicite + T/Sv depuis
> units_cache, slot mapping departage par index creation, destroy_model anti-modification-iteration,
> credit assignment Action 15 dans limitations, masque direction dry-run 6 plans pre-calcules,
> points_per_hp formule algebrique profils mixtes (VALUE/total_hp_pool), Mortal Wounds natifs
> documentes dans limitations.
>
> v3.5 : corrections post-audit code (round 4).
> Corrections : convention hex offset (even-q, parity-based, pas axiale), fight_unit_activation_start
> contrat complet ajoute, Discrete(16) micro vs 31 total clarifie, place_squad_formation BFS
> coherency sur ensemble des figs deja placees (pas seulement ancre), normalisation col_rel/row_rel
> par perception_radius, wounds reset scope (escouade ciblee uniquement), validate_squad_coherency
> contrat lecture-cache vs recalcul defini, destroy_model invalide pending intents figurine morte,
> masque Normal move seuil "au moins 1 figurine" explicit, units_fled reset global documente,
> signal terminaison reward a verifier PR4, slot mapping corner case (>5 ennemis) documente,
> re-train from scratch PR4 explicite, N_global critere acceptance PR1.
> Findings 1 (end_activation) et 3 (charge_roll) invalides — code deja correct.
>
> v3.4 : corrections post-audit code (round 3).
> Corrections : units_fell_back renomme en units_fled (alignement code existant),
> SHOOT_LEFT/ATTACK_LEFT = compteur NB (pas flag binaire), occupied_hexes marque EXISTANT
> (deja present dans shooting_handlers.py, migration set->dict uniquement),
> _occupied_hexes_fingerprint ajoute a la liste des fonctions a mettre a jour,
> format config models[] documente dans PR1 (ajout model_count + model_profile),
> buddy rule target selection alignee sur regle officielle (attaquant doit etre B2B avec relay),
> HP_MAX unifie (suppression W_per_model), numerotation risques corrigee (8,9,10).
>
> v3.3 : corrections post-revue critique (round 2).
> Corrections : weapons ajoutes dans models_cache (bloquant PR3), contrat SHOOT_LEFT/ATTACK_LEFT
> et points_per_hp profils mixtes, is_coherent dans chemins de mise a jour squad_cache,
> charge 12" mesure sur figurine la plus proche (pas l ancre), contradiction slot mapping resolue
> (mapping fixe a l init, pas recalcule par activation), Action 15 scope defini (flux complet
> Pile In+attaques+Consolidation en un gym step), formule obs_size explicite,
> timing reward OC defini (fin de tour), analyse de magnitude reward,
> limitations documentees : charge multi-cibles, wound allocation scope per-activation,
> Advance/Fall Back direction non libre.
>
> v3.2 : corrections post-revue critique.
> Corrections : melee split autorise (regle officielle), LOS par attacker->modeles cibles,
> ordre Fights First (non-actif en premier dans les deux steps), action Fall Back ajoutee,
> masque enemy-in-ER-of-friendly manquant, reward proportionnel a la valeur points,
> obs B2B features, actions 15-16 reportees PR4, obs_size calcule en PR1,
> Desperate Escape Tests hors scope documente.

---

## Objectif

Faire evoluer le moteur de `1 unit = 1 figurine` vers `1 unit = 1 escouade (N figurines)` en restant compatible avec :
- architecture actuelle `engine/w40k_core.py`,
- handlers de phase (`movement_handlers.py`, `shooting_handlers.py`, `fight_handlers.py`, etc.),
- single source of truth (`units_cache` dans `shared_utils.py`),
- pipeline RL actuel (MaskablePPO micro + macro wrapper deja present).

---

## Etat actuel a respecter (verifie dans le code)

1. Phases : `deployment -> command -> move -> shoot -> charge -> fight`.
2. Activation sequentielle via pools (`move_activation_pool`, `shoot_activation_pool`, ...).
3. Action space gym : `Discrete(31)` via `action_decoder.total_action_size` (= `TOTAL_ACTION_SIZE`
   dans `macro_intents.py` = `BASE_ZONE_INTENT(16) + MAX_OBJECTIVES(5) * 3 = 31`).
   Actions 0-15 : micro. Actions 16-30 : macro (zone intents).
4. Masques via `ActionDecoder.get_action_mask*`.
5. Single source of truth en jeu :
   - position/HP des vivants via `game_state["units_cache"]`,
   - morts absents du cache,
   - update HP via `update_units_cache_hp`,
   - checks vie via `is_unit_alive`.
6. Tir deja structure en activation de l unite active (`shooting_unit_activation_start`) avec `valid_target_pool`, `los_cache`, `units_advanced`.
7. Macro deja present :
   - `game_state["zone_intents"]` : liste de 5 entiers (INTENT_INVADE=0 / INTENT_DEFEND=1 /
     INTENT_ATTACK=2), un par objectif. Modifie par les actions 16-30.
   - `engine.build_macro_observation()` : present dans `w40k_core.py` et `observation_builder.py`.
   - Pas de MacroTrainingWrapper / MacroVsBotWrapper ni de macro_training_env.py — ces wrappers
     n existent pas. Le macro est integre directement dans `w40k_core.py` via le zone intent system.
   - Tracking sets resetes en **Command phase** (`command_handlers.py` ligne 40) :
     `units_fled`, `units_moved`, `units_shot`, `units_charged`, `units_fought`, `units_advanced`.

---

## Decision d architecture (honnete)

### Ce qui est recommande

- Garder le concept "unit active" = "escouade active".
- Introduire les figurines comme sous-entites de `unit`.
- Conserver les pools d activation au niveau escouade (pas au niveau figurine).
- Faire les actions internes (mouvement/tir/combat) au niveau des figurines de l escouade.

### Ce qui est risque

- Passer directement a un controle RL "1 action brute par figurine" fera exploser l espace d actions.
- Entrainer micro et macro en meme temps des le debut est instable.

### Perimetre MVP — decisions explicites hors scope

Les points suivants sont **hors perimetre MVP** et documentes ici pour eviter des dettes architecturales cachees :

- **Leaders / Attached Units** : un Leader qui s attache a une escouade (regle officielle 10e) et beneficie de Look Out Sir n est pas supporte. Le modele de donnees `models[]` peut accueillir une future cle `"is_leader": bool` sans casse — a ne pas fermer architecturalement.
- **Overwatch** : reaction de tir avant une charge (coute 1 CP). Hors perimetre, ne doit pas bloquer le flux de charge.
- **Desperate Escape Tests** : quand une unite tente un Fall Back et que des figurines traversent l ER ennemi, chaque figurine traversante passe un test (1D6 : sur 1-2, une figurine de l unite est detruite). Hors perimetre MVP. Consequence : le moteur applique Fall Back sans Desperate Escape Tests — les figurines ne meurent jamais du Fall Back. Documenter dans les limitations connues du training. Placeholder : `game_state["desperate_escape_pending"]` reserve pour PR5.
- **Battleshock** : test de fin de tour pour les unites ayant subi des pertes. Impact sur OC (les modeles en Battleshock ne comptent pas pour le controle d objectif). **Impact RL direct** : le scoring d objectif est imprecis sans Battleshock. Decision : hors perimetre MVP, a implementer en PR5. Documenter dans les limitations connues du training.
- **Deep Strike** : deploiement hors table. Hors perimetre — deploiement normal uniquement.
- **Strategies** : hors perimetre.
- **Weapon keywords complexes** (Lethal Hits, Devastating Wounds, Twin-linked, Melta) : hors perimetre PR1-3. Rapid Fire et Heavy sont les plus courants — a traiter en PR3 si les datasheets en ont.
- **Mortal Wounds natifs** : certains profils d armes infligent D Mortal Wounds directement
  (ignorent Wound roll et Save roll). Non implemente sauf HAZARDOUS (auto-blessure deja present).
  A documenter dans les limitations connues si des datasheets du roster en ont.
- **Charge multi-cibles** : la regle officielle autorise de charger plusieurs unites ennemies
  simultanement. L action space PR1-3 ne supporte qu une cible de charge (via macro_intent).
  Consequence : l agent ne peut pas encercler un ennemi en chargeant depuis deux escouades
  sur deux cibles differentes dans le meme tour. A implementer en PR4 si besoin tactique identifie.
- **Wound allocation scope** : la regle officielle maintient la priorite d allocation "this phase"
  (si un modele a deja recu des blessures dans la phase, tous les attaquants suivants dans la
  meme phase doivent le cibler en priorite). Ce moteur reintialise le compteur par activation
  attaquante. Consequence : entre deux activations d attaquants differents dans la meme phase,
  le defenseur peut "recycler" ses figurines blessees. Impact tactique limite (la figurine
  blessee meurt de toute facon), mais le moteur ne joue pas exactement les regles officielles.
- **Advance direction micro** : l action Advance (action 6) utilise la direction du macro_intent.
  Le micro-agent ne choisit pas la direction d Advance independamment. Consequence : un micro
  entraine seul (sans macro actif) ne peut pas utiliser Advance de facon strategique.
- **Fall Back direction** : l action Fall Back (action 7) utilise une direction auto calculee
  (maximize distance depuis ER ennemi). L agent ne choisit pas la direction. Consequence :
  des retraites vers des positions tactiquement mauvaises (bord de table, loin des objectifs)
  sont possibles. A surveiller sur les premiers runs de training.

---

## Definition des distances en hex-grid (contrat fondamental)

Ces constantes doivent etre calculees une seule fois et referencees partout.

```python
# Engagement Range : 1" horizontal (regle officielle)
ENGAGEMENT_RANGE_SUBHEX = 1 * game_state["inches_to_subhex"]
# x5 : 5 subhexes | x10 : 10 subhexes

# Base-to-Base contact : hexes directement adjacents
# En hex grid, B2B = distance hexagonale == 1 (hexes voisins immediats)
# Equivalent physique : socles qui se touchent
BASE_TO_BASE_SUBHEX = 1  # distance hexagonale stricte, pas en pouces

# Coherency : 2" horizontal (regle officielle)
COHERENCY_SUBHEX = 2 * game_state["inches_to_subhex"]
# x5 : 10 subhexes | x10 : 20 subhexes
```

**Contrat B2B vs ER :**
- `is_base_to_base(model_a, model_b)` : distance hexagonale == 1
- `is_in_engagement_range(model_a, model_b)` : distance subhex <= ENGAGEMENT_RANGE_SUBHEX

`calculate_hex_distance(col1, row1, col2, row2)` (combat_utils.py) retourne la distance
en **subhexes** (pas en inches, pas en hexes abstraits). Les coordonnees col/row du jeu
sont des coordonnees de subhexes. Donc :
- B2B : `calculate_hex_distance(...) == 1` (hexes adjacents)
- ER : `calculate_hex_distance(...) <= inches_to_subhex` (1" en subhexes)

Ces deux fonctions sont distinctes. Le B2B est plus strict que l ER.
Les regles qui referencent B2B (Pile In, Consolidation, buddy rule) doivent utiliser
`is_base_to_base`, pas `is_in_engagement_range`.

---

## Nouveau modele de donnees cible

### Unit (escouade)

```python
unit = {
    "id": str,                  # id escouade (inchange)
    "player": int,
    "unitType": str,
    "DISPLAY_NAME": str,
    # "VALUE": int — deja present dans units_cache, source de verite pour la reward
    "models": [                 # NOUVEAU — liste ordonnee de figurines
        {
            "id": str,          # model id unique (ex: "<unit_id>#0")
            "col": int,
            "row": int,
            "HP_CUR": int,      # blessures actuelles (par figurine, W du datasheet)
            "HP_MAX": int,      # blessures max (caracteristique W du datasheet)
            "wounds_allocated_this_activation": int,
            # Compteur reinitialise a chaque ACTIVATION d unite (pas par phase, pas par tour).
            # Sert a implementer la regle d allocation prioritaire :
            # une figurine qui a deja recu des blessures dans cette activation
            # doit recevoir les attaques suivantes en priorite.
            # Reset : au debut de chaque appel a shooting_unit_activation_start
            #         et fight_unit_activation_start (pas en debut de phase).
            "RNG_WEAPONS": list,
            "CC_WEAPONS": list,
            "selectedRngWeaponIndex": int | None,
            "selectedCcWeaponIndex": int | None,
            "SHOOT_LEFT": int,
            "ATTACK_LEFT": int,
            "OC": int,          # Objective Control de la figurine (du datasheet)
        }
    ],
}
```

**Notes :**
- `HP_CUR` et `HP_MAX` sont par figurine (caracteristique W par modele, regle officielle).
- `wounds_allocated_this_activation` : scope = activation de l unite tirant/frappant,
  pas la phase entiere. Si l unite A tire, reset ses compteurs au debut de son activation.
  Les compteurs des cibles (unites adverses) sont aussi resetes au debut de chaque
  activation adverse qui les cible. Voir section HP Tracking pour le contrat complet.
- `OC` par figurine : OC total de l escouade = somme des OC des figurines vivantes dans la zone.
- Pas de `COHERENCY_MAX_DIST` dans le modele : parametre calcule (voir section Cohesion).
- `selectedRngWeaponIndex` / `selectedCcWeaponIndex` par figurine : supporte les escouades
  a profils mixtes (ex: sergent avec arme speciale). Pour figurines standard homogenes,
  la valeur est identique pour toutes.

### Etat de phase (additions au game_state)

```python
# Existant (inchange)
game_state["units_advanced"]      # set de squad_ids ayant Advance ce tour

# NOUVEAU
game_state["units_fled"]          # set de squad_ids ayant Fall Back ce tour
# CHAMP EXISTANT — deja utilise dans shooting_handlers.py sous le nom "units_fled".
# Ne pas creer "units_fled" — c est le meme champ.
# Reset en debut de Command phase de chaque joueur.
# Impact : ces escouades ne peuvent pas tirer ni charger ce tour
#          (masques action shooting et charge).
```

### Caches (extension)

```python
game_state["units_cache"]      # conserve : source of truth escouade (vivantes)
game_state["models_cache"]     # NOUVEAU : source of truth figurines vivantes
                               # cle : model_id, valeur : dict figurine (col, row, HP_CUR, ...)
game_state["squad_models"]     # NOUVEAU : index inverse squad_id -> [model_id, ...]
                               # liste ordonnee (ordre creation). Acces O(1) aux figurines
                               # d une escouade. Maintenu en sync par destroy_model.
                               # Evite un scan O(N_total) de models_cache pour filtrer par squad_id.
game_state["squad_cache"]      # NOUVEAU : metriques de cohesion et geometrie par escouade
                               # cle : squad_id, valeur : voir contrat ci-dessous
```

**Contrat `units_cache` avec escouades :**
- `units_cache[squad_id]["col"]` / `["row"]` : coordonnees de la figurine ancre
  (index 0 de `models[]`, ou figurine survivante de plus bas index apres pertes).
  Utilise pour les calculs de distance inter-escouades dans les fonctions listees
  en section "Migration units_cache".
- `units_cache[squad_id]["HP_CUR"]` : somme des HP des figurines vivantes. Maintenu
  en temps reel a chaque mort de figurine.
- `units_cache[squad_id]["occupied_hexes"]` : EXISTANT dans le code (shooting_handlers.py),
  actuellement utilise comme `set` ou structure de tuples (col, row) pour la fingerprint LOS.
  **Migration PR1** : passer de set/tuple a `dict {model_id: (col, row)}` pour eviter la perte
  d information si deux figurines sont sur le meme hex — la destruction d une figurine ne retire
  son hex que si aucune autre figurine du squad ne l occupe.
- `units_cache[squad_id]["OC_TOTAL"]` : somme des OC des figurines vivantes.
  **Note PR1-3 :** `observation_builder.py` lit `unit["OC"]` (valeur singleton). En PR1,
  ce champ doit etre remplace par `OC_TOTAL` au niveau escouade, sinon le builder lit
  une valeur fausse silencieusement pour les escouades > 1 figurine. A corriger en PR1
  avant de valider l observation.
- Quand toutes les figurines d une escouade sont mortes : `remove_from_units_cache(squad_id)`.

**Procedure de mise a jour de l ancre :**
Quand `destroy_model` retire une figurine, si la figurine detruite est l ancre courante
(figurine vivante de plus bas index), `destroy_model` recalcule immediatement l ancre
en cherchant la figurine vivante de plus bas index dans `models_cache` pour cette escouade,
puis met a jour `units_cache[squad_id]["col/row"]`. Cette mise a jour se fait **avant**
tout autre recalcul de cache dans le meme appel.

**Contrat `models_cache` :**

```python
models_cache[model_id] = {
    "squad_id": str,
    "col": int,
    "row": int,
    "HP_CUR": int,
    "HP_MAX": int,
    "player": int,
    "wounds_allocated_this_activation": int,  # reset par activation attaquante (voir section HP Tracking)
    "SHOOT_LEFT": int,   # initialise a 1 par activation tir (reset dans shooting_unit_activation_start)
    "ATTACK_LEFT": int,  # initialise a nb attaques de l arme CC au debut de chaque activation fight
    "OC": int,
    "points_per_hp": float,  # pre-calcule a l init (voir contrat ci-dessous)
    "ARMOR_SAVE": int,       # copie depuis units_cache a l init
    "INVUL_SAVE": int,       # copie depuis units_cache a l init (7 = pas d invul save — sentinel aligne avec observation_builder.py:1332 has_invul = invul_save < 7)
    "T": int,                # copie depuis units_cache a l init (utile pour auto-select arme)
    # Weapons — copies depuis unit.models[] a l init, source de verite pendant la resolution
    "RNG_WEAPONS": list,              # liste de profils d armes ranged (meme structure que dans le datasheet)
    "CC_WEAPONS": list,               # liste de profils d armes melee
    "selectedRngWeaponIndex": int | None,
    "selectedCcWeaponIndex": int | None,
}
```

**Contrat SHOOT_LEFT / ATTACK_LEFT :**
- `SHOOT_LEFT` : initialise dans `shooting_unit_activation_start` via
  `resolve_dice_value(weapon["NB"])` — c est un COMPTEUR de tirs restants, pas un flag binaire.
  Pour une arme avec NB=3, SHOOT_LEFT commence a 3. Decremente de 1 apres chaque tir resolu.
  Une figurine avec `SHOOT_LEFT == 0` n est pas incluse dans la declaration auto.
  Coherent avec l initialisation existante dans `game_state.py` (lignes ~75-80).
- `ATTACK_LEFT` : meme logique — initialise via `resolve_dice_value(weapon["NB"])` dans
  `fight_unit_activation_start`. Decremente a 0 apres resolution de chaque attaque.
  Ne pas confondre avec la caracteristique `A` du datasheet (qui peut etre modifiee par des regles)
  — toujours lire depuis le profil d arme dans `models_cache["CC_WEAPONS"]`.
- Reset : uniquement dans *_activation_start. Jamais en milieu de resolution.

**Contrat `points_per_hp` :**
```python
# Escouade homogene (tous les modeles ont le meme HP_MAX) :
points_per_hp = units_cache[squad_id]["VALUE"] / (model_count_at_start * HP_MAX)

# Escouade a profils mixtes (ex: 1 sergent W=3, 4 soldats W=1) :
# Contrainte : somme(points_per_hp[i] * HP_MAX[i]) == VALUE pour toutes les figurines i.
# Formule : chaque figurine recoit une valeur proportionnelle a ses HP_MAX.
#   total_hp_pool = sum(HP_MAX[i] for i in all_models)  # ex: 3 + 4*1 = 7
#   points_per_hp[i] = VALUE / total_hp_pool             # ex: 200/7 = 28.57
# Cette formule satisfait la contrainte et est calculable sans information externe.
# Elle suppose que chaque HP a la meme valeur relative quelle que soit la figurine.
```

`models_cache` est la source de verite pendant la resolution des attaques pour tout
ce qui est par-figurine. `units_cache` est la source de verite des metriques agregees.
Aucune lecture de `units_cache[id]["models"][i]` pendant la resolution — lire
`models_cache` uniquement. Cela inclut les weapons : les profils d armes sont copies
dans `models_cache` a l init et mis a jour si une regle les modifie en cours de partie.

**Contrat `squad_cache` :**

```python
squad_cache[squad_id] = {
    "is_coherent": bool,
    "model_count": int,
    "model_count_at_start": int,  # capture a l init, jamais modifie (sert au reward)
    "oc_total": int,
    "centroid_col": float,   # centroide geometrique des figurines vivantes
    "centroid_row": float,   # Utilise par la planification du mouvement et l observation RL
    # Recalcule apres chaque destroy_model ET apres chaque update_model_position.
}
```

**Note synchronisation squad_cache :** les champs `centroid_col/row` ET `is_coherent` ET `model_count`
doivent etre recalcules dans deux chemins — et uniquement ces deux chemins :
1. `destroy_model` (figurine retiree) : recalculer centroid, is_coherent, model_count.
2. `update_model_position` dans `shared_utils.py` (figurine deplacee) : recalculer centroid, is_coherent.
Ces deux appels sont les seuls points d ecriture de position ou de presence. Ne jamais laisser
`squad_cache` obsolete entre les deux. En particulier : `is_coherent` n est pas mis a jour
"quand ca semble necessaire" — il est mis a jour systematiquement dans ces deux fonctions, sans exception.

**Regles generales :**
- Pas de fallback silencieux.
- Coordonnees toujours normalisees (`normalize_coordinates`, `get_unit_coordinates`).
- Toute ecriture HP passe par fonctions cache dediees.

### Migration units_cache — fonctions impactees

Toutes les fonctions suivantes utilisent `units_cache[id]["col"]` / `["row"]` comme
position d unite. Elles doivent etre auditees et potentiellement adaptees pour utiliser
soit la position ancre (distance inter-escouade), soit la position du modele le plus
proche (LoS, portee) :

- `movement_build_valid_destinations_pool` — utilise position ancre, OK
- `_shoot_compute_los_cache` — doit utiliser positions individuelles des figurines
- `_units_cache_fingerprint` / `_occupied_hexes_fingerprint` — le fingerprint LOS utilise
  `occupied_hexes` comme set/tuple. Apres migration vers dict, la fonction `_occupied_hexes_fingerprint`
  (shooting_handlers.py ~ligne 70) doit etre mise a jour pour iterer sur `.values()` du dict.
  Sans cela, le LOS cache retournera des resultats obsoletes silencieusement.
- `_shoot_build_valid_target_pool` — distance portee : doit checker chaque figurine
- `charge_build_eligible_units` — distance 12" : doit utiliser la figurine vivante la plus proche
  de n importe quel ennemi (pas l ancre). Une escouade est eligible si au moins une de ses figurines
  est a <= 12" d au moins une figurine ennemie. Utiliser l ancre serait incorrect pour les escouades
  deployees en arc ou apres pertes.
- `fight_build_activation_pools` — ER : doit checker figurines individuelles
- `deployment_get_valid_hexes` — position ancre de destination, OK
- `observation_builder` — centroide + features par figurine (voir section RL)

---

## Regles de cohesion — definition exacte

### Source regle officielle (Core Concepts)

- Escouade 2 a 6 figurines : chaque figurine doit etre a <= 2" horizontalement
  d au moins 1 autre figurine de la meme escouade.
- Escouade >= 7 figurines : chaque figurine doit etre a <= 2" horizontalement
  d au moins 2 autres figurines de la meme escouade.
- Escouade de 1 figurine : coherency vacuously true — aucun voisin requis.
- La regle officielle inclut aussi 5" verticalement, non applicable ici (moteur 2D).

### Traduction en hexes

```python
coherency_distance_subhex = COHERENCY_SUBHEX  # voir section distances
coherency_min_neighbors = 2 if squad_size >= 7 else 1
# squad_size == 1 : coherency_min_neighbors ignore (cas traite separement)
```

### Algorithme de validation

```python
def validate_squad_coherency(game_state: dict, squad_id: str) -> bool:
    """
    Recalcul INDEPENDANT — ne lit PAS squad_cache["is_coherent"].
    Appeler cette fonction force le recalcul depuis les positions actuelles de models_cache.
    squad_cache["is_coherent"] est maintenu en temps reel par destroy_model et
    update_model_position — il est un cache de ce calcul, pas la source de verite.
    Utiliser squad_cache["is_coherent"] pour les lectures rapides en cours de phase.
    Appeler validate_squad_coherency pour les validations critiques (fin de move, fin de tour)
    ou en mode debug pour verifier la coherence du cache.
    Cas degenere model_count == 1 : toujours True.
    Chaque figurine doit avoir au moins coherency_min_neighbors voisins
    dans un rayon coherency_distance_subhex (distance hex, horizontal only).
    La coherency est une propriete locale (1 ou 2 voisins directs),
    pas de connectivite transitive — ne pas confondre avec composant connexe.
    """
```

### Timing de validation — choix de design vs regle officielle

La regle officielle valide la coherency uniquement :
- En fin de move (impossible de terminer hors coherency : refus du move).
- En fin de tour (retrait de figurines).

**Ce moteur valide en plus :**
- Fin de resolution des degats (tir ou melee) si des figurines ont ete retirees.

Ce choix est intentionnel : il simplifie la gestion d etat en eliminant les etats
"escouade temporairement hors coherency" entre deux activations d une meme phase.
L impact est que des situations reglementairement valides (escouade hors coherency
apres pertes, avant la fin du tour) sont resolues plus tot dans ce moteur.

### Quand valider (resume)

- Deploiement initial.
- Fin de tout mouvement (Normal, Advance, Fall Back, Charge, Pile In, Consolidation).
- Apres retrait de figurine (tir ou melee) — choix moteur.
- Fin de chaque tour (retrait officiel si hors coherency).

### Regles de mouvement et coherency

- Si une unite ne peut pas terminer un move en coherency : le move est annule,
  les figurines retournent a leur position precedente (regle officielle).
- Si une figurine ne peut pas etre placee en coherency (deploiement) : elle est detruite
  (regle officielle).
- Ces deux cas sont distincts et doivent etre geres par des chemins de code separes.

### Retrait fin de tour — comportement MVP vs cible

La regle dit (Core Concepts) : chaque joueur doit retirer des figurines, une par une,
de ses unites hors coherency, jusqu a ce qu il ne reste qu un seul groupe en coherency.
Le joueur choisit quelles figurines retirer — ce n est pas automatique reglementairement.

**Comportement PR3 (MVP) : retrait automatique deterministe.**
Le moteur retire la figurine la plus isolee geometriquement (distance maximale au centroide
de l escouade). Aucune action agent requise. Appele directement dans `end_of_turn_scoring()`.
Les figurines sont detruites via `destroy_model(model_id, reason="coherency_removal")`.
Elles ne declenchent aucune regle de mort specifique (pas de score kill, pas d OC).

**Comportement PR4 (cible potentielle) : retrait interactif.**
Mesurer la frequence du cas sur les runs de validation PR3. Si > 5% des tours impliquent
un retrait : envisager d ajouter une action agent. Sinon : conserver le deterministe.
Ce n est PAS un point de decision encode dans l action space en PR3.

---

## Deploiement escouade

**Format config scenario — positions explicites (mode test) :**
Si une entree `units[]` contient un champ `"models": [{"col": int, "row": int}, ...]`,
`game_state.py` place les figurines exactement a ces positions (ordre = index figurine)
et appelle `validate_squad_coherency` immediatement apres. Si la coherency n est pas
respectee : exception levee (pas de fallback silencieux).
Si `"models"` est absent : BFS greedy depuis `col`/`row` (comportement par defaut).

```json
{
  "id": 5, "unit_type": "Intercessor", "player": 1,
  "col": 105, "row": 105,
  "models": [
    { "col": 105, "row": 105 },
    { "col": 106, "row": 105 },
    { "col": 105, "row": 106 },
    { "col": 106, "row": 106 },
    { "col": 104, "row": 105 }
  ]
}
```

**Flux deploiement escouade :**
1. Le joueur/agent choisit la position de la figurine ancre (comme aujourd hui).
2. Les N-1 figurines restantes sont placees automatiquement en BFS greedy en spirale depuis l ancre.
   Pour chaque figurine candidate, l hex est valide si :
   - libre, dans les limites du plateau, hors ER ennemi,
   - en coherency avec **l ensemble des figurines deja placees dans cette formation**
     (pas seulement avec l ancre — voir note ci-dessous).
   Pour les escouades >= 7 (regle 2 voisins) : verifier que la figurine candidate a au moins
   2 voisins parmi les figurines deja placees.
   **Ordre BFS deterministe :** file FIFO, voisins enfiles dans l ordre de `get_hex_neighbors`
   (index 0 a 5). A egalite de distance depuis l ancre, les hexes sont traites par index
   de direction croissant (0=N, 1=NE, 2=SE, 3=S, 4=SW, 5=NW).

   **Decision algorithmique : BFS greedy sans backtracking.**
   Un BFS greedy peut echouer meme si une solution existe (la figurine N bloque la N+1).
   Ce cas est acceptable en MVP : si le BFS echoue pour une figurine, elle est detruite
   (regle officielle — impossible de placer = detruite). Les scenarios de training MVP
   ciblent des escouades <= 6 figurines en formation compacte : les echecs de placement
   seront rares en pratique. Si des destructions de deploiement involontaires apparaissent
   dans les logs, passer a un algorithme avec backtracking en PR2.
3. Validation : toutes les figurines doivent etre en coherency et hors ER ennemi.
4. Si une figurine ne peut pas etre placee en coherency : elle est detruite (regle officielle).
   Si toutes les figurines sauf l ancre ne peuvent pas etre placees : l escouade est detruite.

**Fichiers impactes :**
- `engine/phase_handlers/deployment_handlers.py` : etendre `_get_valid_deployment_hexes`
  pour validation multi-figurines.
- `shared_utils.py` : helper `place_squad_formation(anchor_col, anchor_row, squad_id, game_state) -> list[tuple[int,int]]`.

---

## Mouvement coordonne (Normal, Advance, Fall Back)

### Principe moteur

Une action `move` pour une escouade reste unique au niveau engine, mais genere un plan
multi-figurines :
1. Construire destinations candidates pour toutes les figurines (plan par translation
   rigide depuis l ancre).
2. Valider collisions / murs / enemy adjacency / limites de distance individuelle /
   coherency en sortie.
3. Appliquer toutes les positions en transaction atomique (dry-run obligatoire avant
   toute ecriture dans le cache — voir section "Transaction atomique").
4. Si une destination figurine est invalide : refus global (aucun deplacement partiel).
5. Commit cache + `end_activation(...)`.

### Advance roll

Pour un mouvement Advance, avant de calculer le plan :

```python
advance_roll = roll_d6()  # 1D6, partage par toute l escouade
game_state["current_advance_roll"] = advance_roll
# Budget de deplacement par figurine = M_figurine + advance_roll
# Si les figurines ont des M differents, chaque figurine utilise son propre M + advance_roll.
# Pour la formation rigide, le deplacement maximum de l ancre est contraint par
# le M_min de l escouade + advance_roll.
```

Le roll est stocke en game_state pour les logs et le replay. Il est efface apres commit.

### Restrictions post-mouvement

- Post-Advance : escouade ajoutee a `units_advanced`. Masques : tir interdit sauf
  armes [ASSAULT], charge interdite.
- Post-Fall Back : escouade ajoutee a `units_fled`. Masques : tir interdit,
  charge interdite.
- Ces flags (`units_fled`, `units_advanced`) sont resetes en debut de **Command phase**
  dans `command_handlers.py` ligne 40 (pas en Movement phase comme dit precedemment).
  Reset global (tous joueurs). En pratique correct car la Command phase precede Movement
  dans le meme tour.

### Direction de mouvement — 6 directions hex

Le hex grid a 6 directions, pas 4. L action space encode les 6 directions.

**IMPORTANT — convention offset with parity (code existant) :**
Le moteur utilise une convention offset even-q : les deltas dépendent de la parité de la colonne
(voir `get_hex_neighbors` dans `combat_utils.py`). Il n'y a pas de deltas fixes universels.

```python
# Pour colonne paire (col % 2 == 0) :
# Direction 0 : N    (col,   row-1)
# Direction 1 : NE   (col+1, row-1)
# Direction 2 : SE   (col+1, row)
# Direction 3 : S    (col,   row+1)
# Direction 4 : SW   (col-1, row)
# Direction 5 : NW   (col-1, row-1)

# Pour colonne impaire (col % 2 == 1) :
# Direction 0 : N    (col,   row-1)
# Direction 1 : NE   (col+1, row)
# Direction 2 : SE   (col+1, row+1)
# Direction 3 : S    (col,   row+1)
# Direction 4 : SW   (col-1, row+1)
# Direction 5 : NW   (col-1, row)
```

Ne jamais hardcoder de deltas fixes pour les directions 1/2/4/5 — toujours appeler
`get_hex_neighbors(col, row)` et indexer le resultat. Les deltas de la spec v3.3
("+col, -row selon convention axiale") etaient incorrects pour les colonnes impaires.

Cela implique un agrandissement de l action space (voir section RL).

### Transaction atomique — contrat implementation

"Transaction atomique" signifie :
1. Calculer le plan complet (liste de destinations pour chaque figurine) sans
   modifier `models_cache` ni `units_cache`.
2. Valider l integralite du plan.
3. Si valide : appliquer toutes les ecritures cache en une seule passe.
4. Si invalide : aucune ecriture. Pas de rollback necessaire car aucune ecriture n a eu lieu.

Ce pattern s applique a tous les moves : Normal, Advance, Fall Back, Charge, Pile In,
Consolidation.

### Strategie long terme mouvement (moteur)

**Etage 1 — deplacement global (leader + offsets rigides)**
- Choisir une figurine ancre (deterministe : figurine vivante de plus bas index).
- Calculer une translation ancre -> destination (BFS / budget MOVE sur l ancre).
- Appliquer le meme vecteur a toutes les figs (formation rigide).
- Valider tout le plan atomiquement : plateau, murs, collisions, ER ennemi, budget
  par fig, coherency.
- Si une fig est illegale : refus global.

**Calcul du masque de direction (actions 0-5) :**
Pour chaque direction D (0-5), le masque est mis a 0 si le plan complet de formation rigide
dans cette direction est invalide (au moins une figurine hors plateau, en collision, ou budget
depasse). Ce calcul est fait a chaque construction de l observation (avant que l agent agisse).
Strategie : pre-calculer les 6 plans en dry-run a chaque step — O(6 * N_figurines).
Ne pas faire ce calcul lazy (risque de masque obsolete si le game_state a change).

**Etage 2 — placement fin**
- Apres l etage 1, deplacements par figurine bornes (budget residuel, memes regles,
  coherency verifiee au commit).

**Ce qu on evite en premier jet :**
- N BFS independantes sans plan global (explosion combinatoire).

### Infrastructure mutualisee de mouvement (source de verite unique)

Tous les types de deplacement (Normal, Advance, Fall Back, Charge, Pile In, Consolidation)
partagent le meme pipeline moteur et le meme pipeline UX. Seules les contraintes varient.

**Pipeline moteur (`shared_utils.py`) :**

```python
build_rigid_plan(anchor_dest, squad_id, game_state) -> list[tuple[str,int,int]] | None
# Translation rigide ancre → destination, appliquee a toutes les figurines.
# Utilise par : Normal, Advance, Fall Back.
# Charge, Pile In, Consolidation ont leurs propres planificateurs (deplacements individuels).

validate_move_plan(plan, game_state, constraints) -> bool
# Verifie pour chaque figurine : plateau, collisions, budget, ER ennemi, coherency.
# `constraints` = dict parametrable par type de deplacement :
#   {"budget_per_model": int, "forbid_enemy_er": bool, "require_coherency": bool, ...}
# Commun a TOUS les types de deplacement.

apply_snap_corrections(plan, game_state, radius=2) -> list[tuple[str,int,int]]
# Pour chaque figurine invalide du plan : cherche hex valide le plus proche dans `radius`.
# Ordre deterministe par index de figurine.
# Commun a TOUS les types de deplacement.

commit_move(plan, game_state, move_type) -> None
# Ecrit toutes les positions en une seule passe (models_cache, units_cache, squad_cache,
# occupied_hexes). Positionne les flags post-move selon move_type :
#   "advance"   → units_advanced.add(squad_id)
#   "fall_back" → units_fled.add(squad_id)
#   autres      → aucun flag
# Commun a TOUS les types de deplacement.
```

**Specificites par type (ce qui N EST PAS mutualise) :**

| Type         | Planificateur       | Budget                  | Contrainte specifique              |
|--------------|--------------------|--------------------------|------------------------------------|
| Normal       | build_rigid_plan   | M par figurine           | —                                  |
| Advance      | build_rigid_plan   | M + advance_roll D6      | direction depuis macro_intent      |
| Fall Back    | build_rigid_plan   | M par figurine           | direction auto (maximize dist ER)  |
| Charge       | charge_build_valid_plan | charge_roll 2D6     | B2B obligatoire si possible        |
| Pile In      | fight_pile_in_plan | 3" par figurine          | plus proche ennemi, B2B si possible|
| Consolidation| _plan_consolidation| 3" par figurine          | vers ennemi OU objectif            |

**Pipeline UX (frontend) — commun a tous les types :**

```
squad_move_start(squad_id, move_type)  → capture positions d origine, determine budget
on_drag_update(anchor_dest)            → build_rigid_plan dry-run, overlay hex
on_drop()                              → validate_move_plan + apply_snap_corrections
                                          + affichage voiles rouges
on_individual_adjust(model_id, dest)   → validate 1 figurine + LoS temps reel
on_validate()                          → commit_move atomique
```

Le `move_type` est le seul parametre qui change d un appel a l autre.
Aucune logique UX dupliquee entre les types de deplacement.

---

### UX mouvement escouade (vision cible)

Ce comportement s applique a tous les types de deplacement joueur :
Normal move, Advance, Charge, Pile In, Consolidation.

**Memoire des positions d origine :**
Les positions d origine de chaque figurine sont conservees en memoire pour toute la duree
du mode (entre le debut du drag et la validation). Elles servent a deux usages distincts :
1. Calculer le vecteur de translation pour la formation rigide pendant le drag.
2. Contraindre les ajustements individuels : le budget de deplacement de chaque figurine
   est toujours mesure depuis sa position d ORIGINE, pas depuis sa destination apres drag.
   Sans ca, un joueur pourrait drag l escouade de 3" puis deplacer une fig de 3" en plus,
   contournant son budget M.

**Phase A — MVP :**
1. Double-clic sur figurine -> mode escouade; ancre = fig cliquee.
   Les positions d origine de toutes les figurines sont capturees a ce moment.
2. Drag de l ancre : toutes les figurines suivent en formation rigide (meme vecteur).
   Overlay rouge/vert sur les hexes invalides (decors, hors plateau, ER ennemi).
3. Drop :
   - Pour chaque figurine dont la destination est invalide : le moteur cherche la position
     valide la plus proche dans un rayon limite (1-2 hexes). Si trouvee : snap automatique.
     Ordre de traitement deterministe par index de figurine (priorite aux premiers index).
   - Si aucune position valide dans le rayon : la figurine reste sur sa destination invalide
     (pas de deplacement partiel force — voir etape 4).
4. Apres drop : validation de la formation (coherency globale de l escouade).
   - Figurines hors formation ou sur hex invalide : voile rouge sur leur icone.
   - Bouton "Valider" desactive tant qu au moins une figurine a un voile rouge.
5. Ajustement individuel : le joueur peut deplacer chaque figurine individuellement
   (clic + drag fig par fig) pour corriger la formation avant de valider.
   Budget de chaque figurine = son budget M mesure depuis sa position d ORIGINE.
6. Bouton "Valider" : disponible uniquement si toutes les figurines sont valides
   (coherency OK, aucune sur hex interdit, toutes dans leur budget).
   Commit atomique de toutes les positions.

**LoS — calcul et affichage :**
- Pendant le drag global : aucun calcul LoS. Trop couteux (N_figurines * N_cibles potentielles
  a chaque frame). Seules les contraintes de position sont verifiees (plateau, collisions,
  coherency, budget).
- Une fois les figurines posees (apres drop ou apres validation) : LoS calculees et affichees
  (voile vert sur les figurines avec au moins une cible eligible).
- Pendant l ajustement individuel (fig par fig) : LoS recalculee et affichee en temps reel
  pour la figurine en cours de deplacement uniquement. Permet au joueur d optimiser
  finement la position de chaque figurine pour maximiser ses LoS.

**Phase B — apres stabilite Phase A :**
- Glissement contraint en temps reel (contraintes verifiees pendant le drag, pas seulement au drop).

**Phase C — polish :**
- Feedback visuel du budget residuel par figurine pendant l ajustement individuel.

### Fichiers impactes (mouvement)

- `engine/phase_handlers/movement_handlers.py` : etendre
  `movement_build_valid_destinations_pool` pour plan escouade, ajouter executeur
  atomique multi-figurines. Ajouter gestion du advance_roll.
- `engine/phase_handlers/shared_utils.py` : ajouter update position model-level cache,
  update `occupied_hexes` (dict), `centroid_col/row` dans `squad_cache`.

---

## Charge escouade

### Regle officielle (Charge Phase)

Eligibilite :
- Au moins une figurine vivante de l escouade doit etre a <= 12" d au moins une figurine ennemie
  au debut de la Charge phase. (Mesure figurine la plus proche, pas l ancre.)
- Interdit si l escouade a Advance ou Fell Back ce tour.
- Interdit si l escouade est dans l ER d un ennemi.

Charge roll (2D6) = distance maximale que chaque modele peut parcourir.

La charge est possible si et seulement si le roll permet a l escouade de :
1. Finir dans l ER de toutes les unites ciblees.
2. Ne pas entrer dans l ER d unites non ciblees.
3. Finir en Unit Coherency.

Si ces conditions ne peuvent pas etre remplies : la charge echoue, aucune figurine
ne bouge.

**La charge N EST PAS une translation rigide.** Chaque figurine se deplace
individuellement jusqu au maximum du roll. Chaque figurine doit :
- Finir plus proche d une des cibles.
- Se mettre en B2B avec un ennemi si possible.

Le joueur choisit l ordre de deplacement des figurines.

### Traduction moteur

```python
def charge_build_valid_plan(game_state, squad_id, target_squad_ids, charge_roll):
    """
    Verifie d abord l eligibilite (12", pas d units_advanced/fell_back, pas en ER).
    Ordre de traitement des figurines : par index croissant (deterministe).
    Pour chaque figurine de l escouade :
    - Chercher l hex valide dans un disque de rayon charge_roll * inches_to_subhex
      depuis la position actuelle, tel que :
      (a) la figurine finit en B2B avec un modele ennemi cible (prioritaire),
      (b) sinon : finit plus proche d une cible qu avant, hors ER des non-cibles.
      Si plusieurs hexes satisfont (a) : choisir le plus proche de la cible la plus proche.
      Si egalite : hex de plus petit index dans BFS (deterministe).
    - Coherency verifiee sur l ensemble du plan en cours de construction
      (pas seulement a la fin).
    Retourne un plan complet ou None si la charge echoue (une seule figurine invalide
    suffit a faire echouer toute la charge).
    Validation finale obligatoire apres construction du plan individuel : verifier que
    toutes les figurines du plan finissent dans l ER de la cible (condition legale de
    charge). La condition (b) "finit plus proche" ne garantit pas l ER — si une figurine
    satisfait (b) mais reste hors ER, la charge echoue.
    Transaction atomique : pas d ecriture cache avant validation complete.
    """
```

Apres une charge reussie : l escouade est ajoutee a `units_charged` (inchange)
et beneficie de Fights First ce tour.

### Fichiers impactes (charge)

- `engine/phase_handlers/charge_handlers.py` : remplacer logique mono-figurine par
  plan multi-figurines. Ajouter check eligibilite 12" et flags units_advanced/fell_back.
- Conserver `units_charged` au niveau escouade (inchange).

---

## Tir escouade : declaration puis resolution

### Pourquoi il faut changer

Le flux actuel est "unite active tire" avec choix cible immediate.
La regle officielle (Shooting Phase) dit : avant toute resolution, selectionner toutes
les cibles de toutes les armes. Pour une escouade, toutes les declarations doivent
etre figees avant la premiere resolution.

### Locked in combat — regle exacte

Deux contraintes distinctes issues de la regle officielle :

**Contrainte 1 — attaquant locked :**
Une escouade dont **au moins une figurine** est dans l Engagement Range (<= 1" horizontal)
d une unite ennemie est **entierement** locked in combat et ne peut pas tirer, quelle que
soit la position des autres figurines.

Exception : les figurines avec des armes [PISTOL] peuvent toujours tirer meme locked,
mais uniquement contre des cibles dans leur propre ER (enemy_engaged_with_shooter = True).
Exception : les unites Monster/Vehicle ne sont jamais locked in combat pour les tirs,
mais subissent un malus de -1 to hit sur leurs attaques ranged quand elles tirent en ER
(hors Pistol). Ce malus est dans la liste des limitations connues MVP.

**Contrainte 2 — cible protegee par ER allié :**
Une escouade ennemie dont **au moins une figurine** est dans l ER d une unite alliee
**ne peut pas etre selectionnee comme cible** d une attaque ranged, sauf par Monster/Vehicle.

Consequence sur les masques :
- Masque tir attaquant : `any(is_in_engagement_range(m, e) for m in squad_models for e in enemy_models)` → masquer slots de tir (sauf Pistol).
- Masque cible : `any(is_in_engagement_range(e, ally) for e in target_models for ally in all_friendly_models)` → masquer ce slot cible.

### Simplification RL (action space)

**Decision deliberee :** l agent choisit une **cible prioritaire** par escouade
(action 9-13 = slot i). Chaque figurine declare ensuite sa cible individuellement :
- Si la figurine a LoS + portee sur la cible prioritaire → elle cible la cible prioritaire.
- Sinon → elle cible la meilleure cible disponible (LoS + portee, slot de plus bas index).
- Si aucune cible disponible → la figurine ne tire pas.
Cette approche preserve l influence de l agent sur la direction du feu tout en autorisant
les figurines sans LoS sur la cible prioritaire a contribuer au tir.

**Contrat gym step() pour le tir :**
Une action shoot (9-13) = 1 step gym. Le moteur execute en interne : declaration
individuelle par figurine (cible prioritaire ou meilleure cible disponible) → lock de
toutes les declarations → resolution complete → mise a jour caches → `end_activation`.
L agent ne voit pas les sous-etapes.

### Contraintes de ciblage par figurine (regles officielles)

- Chaque figurine peut cibler une unite differente.
- Une figurine avec arme multi-attaque ne peut pas splitter ses attaques entre plusieurs
  cibles — toutes les attaques d une meme arme vont sur une meme cible.
- La cible doit avoir au moins un modele visible et a portee de l arme de la figurine.
- Restrictions d eligibilite au tir :
  - Interdit si l escouade a Advance ce tour (sauf armes [ASSAULT]).
  - Interdit si l escouade a Fell Back ce tour.
  - Interdit si locked in combat (sauf [PISTOL] ou Monster/Vehicle).

### Nouveau flux SHOOT

1. Activation escouade (inchange au niveau pool).
2. Reset `wounds_allocated_this_activation` sur toutes les figurines de **l escouade ciblee
   uniquement** (pas toutes les figurines ennemies du jeu). Ce reset est fait au moment
   de la declaration de cible (etape 3), pas en debut d activation.
3. **Agent action unique** : choisir `target_squad_id` (cible prioritaire, slot 9-13).
4. Declaration individuelle par figurine (ordre par index croissant) via
   `build_declarations(squad_id, eligible_targets, game_state, phase="shoot")` :
   - LoS + portee sur cible prioritaire → declare sur cible prioritaire.
   - Sinon → declare sur la meilleure cible disponible (slot de plus bas index avec LoS + portee).
   - Sinon → ne tire pas.
   - Apres chaque declaration : mettre a jour le TTK residuel de la cible declaree
     (soustraire les degats attendus de cette figurine). La figurine suivante voit
     un TTK residuel mis a jour — evite la concentration involontaire sur une cible
     dont le TTK est deja couvert par les declarations precedentes.
5. Verrouillage : aucune resolution avant que toutes les declarations soient completees.
6. Resolution (ordre deterministe par index de figurine) :
   - Resolution des attaques d une figurine morte mid-resolution : les attaques declarees
     par une figurine attaquante qui meurt pendant la resolution de cette activation
     sont annulees (la figurine n existe plus). Les attaques declarees contre elle
     par une escouade tirant dans la meme activation sont resolues normalement
     (la cible existait au moment de la declaration).
   - Sequence complete par attaque : Hit roll → Wound roll → Save roll → Damage
     (voir section Sequence de resolution ci-dessous).
   - Application de la regle d allocation prioritaire (voir section HP Tracking).
   - Gestion du damage exces : si une figurine est detruite avec X HP restants et
     que l attaque inflige X + Y points, Y est perdu — pas de carry-over.
   - Retrait du cache si HP = 0 via `destroy_model(model_id, reason="combat")`.
   - Mise a jour `units_cache[squad_id]["HP_CUR"]`, `occupied_hexes`, `OC_TOTAL`.
   - Mise a jour `squad_cache`.
7. Validation coherency de l escouade ciblee apres pertes (choix moteur, voir
   section Coherency).
8. Fin activation via `end_activation(...)`.

### LOS cache — strategie avec escouades

Le `los_cache` passe d un calcul unite-a-unite (ancre -> ancre) a un calcul par
paire (figurine attaquante, figurine cible). Contrat retenu :

- **Portee** : une figurine attaquante peut cibler l escouade ennemie si au moins
  une figurine cible est a portee de l arme de la figurine attaquante.
- **LOS** : LOS valide si au moins un modele de l escouade cible est visible
  depuis la figurine attaquante (pas seulement l ancre — la LOS est testee sur
  chaque figurine cible).
- Le meme contrat s applique a `_shoot_build_valid_target_pool` et a
  `_shoot_compute_los_cache` : toujours attacker → chaque modele cible.
- Cache invalide a chaque destruction de figurine — le cout de recalcul est
  acceptable pour des escouades standard (<= 10 figurines).
- Si la complexite devient un probleme en PR3 : passer a un cache lazy par
  `(attacker_model_id, target_squad_id)` recalcule uniquement a la demande.

### Interaction BLAST / taille d escouade

Regle officielle (Weapon Abilities) : pour une arme [BLAST], le nombre d attaques
est augmente de 1 pour chaque tranche de 5 figurines dans l unite cible au moment
de la declaration (pas de la resolution).

```python
# Lors du calcul des attaques d une arme [BLAST]
blast_bonus = (target_squad_size_at_declaration // 5)
total_attacks = base_attacks + blast_bonus
```

`target_squad_size_at_declaration` = `len(models)` au moment ou la cible est designee.
Cette valeur doit etre capturee dans `pending_squad_shoot_intents` pour la resolution.

### Structure game_state

```python
game_state["pending_squad_shoot_intents"] = {
    squad_id: [
        {
            "model_id": str,
            "weapon_index": int,
            "target_unit_id": str,
            "target_squad_size_at_declaration": int,  # OBLIGATOIRE — capture au moment de la declaration, sert au calcul BLAST
            # pas de target_model_id : ciblage au niveau escouade
        }
    ]
}
```

**Lifecycle de `pending_squad_shoot_intents` :**
- Cree au debut de l activation de tir de l escouade (`shooting_unit_activation_start`).
- Nettoye (cle supprimee) par `end_activation(...)` quelle que soit l issue
  (resolution normale ou annulation).
- Jamais persiste entre deux activations.
- Si la cle existe au debut d une activation : c est un bug — lever une assertion
  ou une exception en debug (ne pas silencer).

### UX tir joueur

**Etat initial — LoS affichee :**
Chaque figurine de l escouade active affiche sa LoS. Les figurines avec au moins une
cible eligible (LoS + portee sur au moins une escouade ennemie) ont un voile vert sur
leur icone.

**Double-clic sur une escouade ennemie — declaration automatique :**
Toutes les figurines eligibles sur cette cible (LoS + portee) la declarent comme cible.
Leurs icones passent en etat "cible assignee" (grise + indicateur couleur du slot ennemi).
Les figurines sans LoS sur aucune cible passent directement en etat "bloquee" (voir ci-dessous).

**Deux etats visuels distincts pour "grisee" :**
- **Cible assignee** : grise avec indicateur de la cible (couleur du slot ennemi).
  La figurine tirera au moment de la resolution.
- **Bloquee** : gris fonce, icone barrée. La figurine ne peut cibler aucune escouade
  ennemie (aucune LoS disponible, ou aucune arme de tir). Elle ne tirera pas mais
  compte dans le decompte "toutes les figurines grisees".

**Ajustement individuel :**
Apres la declaration automatique, le joueur peut cliquer sur chaque figurine pour
changer sa cible. Chaque figurine a une cible unique (pas de split — regle officielle).
Les figurines bloquees ne sont pas selectionnables.

**Bouton "Valider" :**
Apparait uniquement quand toutes les figurines de l escouade sont grisees
(cible assignee OU bloquee). Les figurines bloquees comptent dans ce decompte.
Declenche le lock des declarations puis la resolution complete.

### Fichiers impactes (tir)

- `engine/phase_handlers/shooting_handlers.py` : `shooting_unit_activation_start`
  devient "start escouade", ajout sous-flow declaration/lock/resolution,
  reset `wounds_allocated_this_activation`, gestion damage exces.
- `engine/action_decoder.py` : adapter mapping actions de tir (slots) pour contexte
  escouade (voir section RL).
- `engine/phase_handlers/shared_utils.py` : ajouter `build_declarations(squad_id,
  eligible_targets, game_state, phase)` — fonction mutualisee tir et fight.
  Gere la declaration sequentielle par index, la mise a jour du TTK residuel entre
  chaque declaration, et le lock final. Le parametre `phase` conditionne uniquement
  le filtre d eligibilite (LoS/portee pour "shoot", ER/buddy rule pour "fight").
  La logique de selection value_over_ttk et de TTK residuel est identique dans les deux cas.

---

## Fight phase escouade

### fight_unit_activation_start — contrat

**NOUVELLE FONCTION A CREER** dans `fight_handlers.py` (parallele a `shooting_unit_activation_start`
qui existe deja). Pas de refactoring d une fonction existante — creer ex nihilo.

Appele au debut de chaque activation d escouade en Fight phase, avant toute autre operation.
Ordre obligatoire :

```python
def fight_unit_activation_start(game_state: dict, squad_id: str) -> None:
    """
    1. Auto-selection d arme CC pour chaque figurine de l escouade active
       (voir section Declaration — formule expected damage).
    2. Reset ATTACK_LEFT pour chaque figurine de l escouade active :
       ATTACK_LEFT = resolve_dice_value(selected_CC_weapon["NB"])
       APRES auto-selection (l arme choisie determine la valeur).
    3. Reset wounds_allocated_this_activation sur les figurines de la cible.
       Ce reset se fait AU MOMENT de la declaration de cible (apres Pile In),
       pas dans cette fonction. Cette fonction ne connait pas encore la cible.
    4. Verifier que pending_squad_fight_intents ne contient pas deja une cle pour ce squad_id.
       Si oui : assertion/exception (bug — activation precedente non nettoyee).
    """
```

**Lifecycle de `pending_squad_fight_intents` :**
Meme pattern que `pending_squad_shoot_intents` :
- Cree lors de la declaration de cibles melee (apres Pile In).
- Nettoye par `end_activation(...)` quelle que soit l issue.
- Jamais persiste entre deux activations.

### Vue d ensemble

Flux fight : Pile In -> Melee Attacks -> Consolidate. Toutes les etapes operent sur
les figurines individuelles et doivent maintenir la coherency.

### Ordre d activation (regle officielle)

Dans **les deux etapes** de la Fight phase, les joueurs alternent en commencant par
**le joueur dont ce n est PAS le tour**. Ce n est pas negociable — c est une regle
fondamentale qui s applique identiquement au step Fights First et au step Remaining Combats.

Sous-ordre :
1. Les unites avec Fights First (ayant charge ce tour ou avec la regle Fights First)
   s activent en premier (step Fights First).
2. Dans ce step, alternance : non-actif d abord, puis actif (meme regle que le step suivant).
3. Ensuite les unites normales s activent (step Remaining Combats), avec alternance :
   non-actif d abord, puis actif.
4. Une unite peut uniquement s activer une fois par Fight Phase.
5. Un joueur **ne peut pas passer** quand il a des unites eligibles — il doit en selectionner une.
   Consequence masque RL : l action `wait` (end activation) est masquee si l unite est eligible
   au combat et que c est son tour de fight.

`fight_build_activation_pools` doit construire deux pools ordonnes et les fusionner
en respectant cette alternance.

### Eligibilite a combattre (regle officielle)

Une escouade est eligible a combattre si :
- Au moins une de ses figurines est dans l ER d une unite ennemie, OU
- Elle a effectue une Charge move ce tour.

### Pile In (regle officielle)

Chaque figurine non deja en B2B avec un ennemi peut se deplacer jusqu a 3" (horizontal).

Conditions :
- Chaque figurine qui bouge doit finir plus proche du modele ennemi le plus proche.
- Si possible de finir en B2B avec un ennemi tout en satisfaisant les conditions :
  **la figurine doit le faire** (obligatoire, pas optionnel).
- L escouade doit finir en coherency ET dans l ER d au moins une unite ennemie.
- Si ces conditions ne peuvent pas etre remplies : aucune figurine ne fait de Pile In,
  on passe directement aux attaques.

**Algorithme Pile In automatique (Action 15) :**
- Ordre de traitement : par index de figurine croissant (deterministe).
- Critere de placement : pour chaque figurine non en B2B, chercher l hex a <= 3" qui
  (a) met la figurine en B2B avec un ennemi si possible, sinon
  (b) minimise la distance au plus proche ennemi.
  Si plusieurs hexes satisfont (a) ou (b) a egalite : choisir l hex de plus petit index
  dans le resultat de `get_hex_neighbors` (deterministe).
- Validation globale apres placement de toutes les figurines : coherency + ER ennemi.
- Si validation echoue : aucune figurine ne bouge (Pile In annule en entier, pas partiel).
- Transaction atomique (dry-run complet avant ecriture cache).
- Note : un algorithme greedy par index peut etre sous-optimal (figurine 0 prend le
  meilleur hex, figurine 1 est bloquee). Acceptable en MVP — reproductible et deterministe.

### Quelles figurines peuvent frapper — regle du buddy

Une figurine peut faire ses attaques de melee si :
1. Elle est dans l ER d une unite ennemie (distance subhex <= ENGAGEMENT_RANGE_SUBHEX), OU
2. Elle est en B2B (`is_base_to_base`) avec une autre figurine de sa propre escouade
   qui est elle-meme en B2B avec un modele ennemi.

La condition 2 n est pas transitive : une figurine en "rang 3" (B2B avec rang 2,
mais rang 2 pas en B2B avec un ennemi) ne peut pas frapper.

```python
def get_fighting_models(game_state: dict, squad_id: str) -> list[str]:
    """
    Retourne les model_ids pouvant attaquer ce tour.
    Condition 1 : figurine dans ER ennemi.
    Condition 2 : figurine en B2B avec alliee elle-meme en B2B avec un ennemi.
    Non transitif : profondeur = 1 niveau de buddy.
    """
```

### Declaration des attaques de melee

Comme pour le tir : selectionner toutes les cibles avant de resoudre la premiere attaque.

- Chaque figurine choisit une arme de melee et une cible.
- **Les attaques d une meme arme peuvent etre splittees entre plusieurs cibles**
  (regle officielle melee — contrairement au ranged ou le split est interdit).
  En pratique pour le MVP : auto-selection de cible unique par arme pour simplifier
  l action space RL. A encoder explicitement si le split est expose en PR4.
- Cible valide (regle officielle exacte) :
  1. La figurine attaquante est dans l ER de la cible ennemie, OU
  2. La figurine attaquante est en B2B avec une figurine alliee, ET cette figurine alliee
     est elle-meme en B2B avec la cible ennemie.
  Note : la condition 2 exige que l ATTAQUANT soit B2B avec le relay allié — ce n est pas
  "la cible est en ER d un allié quelconque". Un attaquant en rang 2 peut cibler un ennemi
  uniquement si son relay de rang 1 (avec qui il est en B2B) est lui-meme en B2B avec cet ennemi.
- **Declaration sequentielle, resolution simultanee** : meme pattern que le tir.
  `build_declarations(squad_id, eligible_targets, game_state, phase="fight")` :
  chaque figurine declare sa cible par index croissant. Apres chaque declaration,
  le TTK residuel de la cible est mis a jour (degats attendus soustraits) — la figurine
  suivante voit un TTK residuel reduit et peut naturellement cibler ailleurs si le TTK
  est deja couvert. Toutes les declarations lockees avant la premiere resolution.
  Filtre d eligibilite : ER ou buddy rule (au lieu de LoS/portee pour le tir).
  Pas de split explicite : le TTK residuel produit le meme effet de facon emergente.
  Si egalite de score : cible de slot le plus bas.
- **Auto-selection de l arme** : apres selection de la cible, arme maximisant
  `P(hit) * P(wound) * P(failed_save) * D` contre la T et Sv de la cible declaree.
  Si egalite : arme d index le plus bas.
- Resolution par cible puis par profil d arme (ordre deterministe).
- Allocation prioritaire HP : meme regle que le tir.
- Damage exces : perdu a la destruction de la figurine cible (pas de carry-over).
- Resolution des attaques d une figurine morte mid-resolution : meme regle que pour
  le tir (attaques declarees par la figurine morte = annulees, attaques declarees
  contre elle = resolues).

**Overkill en fight — pas de penalite explicite.**
Meme raisonnement que pour le tir : declarations lockees avant resolution → figurines
qui attaquent une cible deja morte dans la meme activation ont leurs attaques perdues
(zero damage, zero reward HP). Signal implicite suffisant.
La selection par figurine via `value_over_ttk` incite naturellement a repartir les
attaques sur plusieurs cibles plutot que de concentrer sur une cible a faible HP —
le reseau apprend ce comportement sans penalite explicite.
Ajouter une penalite si les logs de training montrent un overkill persistant en fight.

Reset `wounds_allocated_this_activation` au debut de l activation de chaque escouade
combattante.

### Sequence complete de resolution des attaques (tir et melee)

Pour chaque attaque :
1. **Hit roll** : jet d attaque vs WS/BS de l attaquant. Modifie par Heavy (-1 si
   bouge ce tour), etc.
2. **Wound roll** : comparaison S attaquant vs T defenseur (table W40K 10e) :
   - S >= 2*T : 2+
   - S > T    : 3+
   - S == T   : 4+
   - S < T    : 5+
   - S <= T/2 : 6+
3. **Save roll** : jet de sauvegarde du defenseur (Sv ou invulnerable save si meilleure).
   Les degats en exces du save ne se cumulent pas entre figurines.
4. **Damage** : D points de degats alloues a la figurine ciblee (allocation prioritaire).
   Si `HP_CUR` descend a 0 → `destroy_model`. Les degats excedentaires ne debordent
   pas sur la figurine suivante (regle officielle W40K 10e).

Cette sequence est identique pour le tir et la melee. Si le moteur la gere deja pour
les singletons, l adaptation aux escouades consiste uniquement a router les degats vers
`models_cache` par figurine au lieu de `units_cache` directement.

### Consolidation (regle officielle)

Apres les attaques, chaque figurine non en B2B peut se deplacer jusqu a 3".

Condition pour que la Consolidation soit possible (OR officiel) :
1. Si possible : finir dans l ER d une unite ennemie ET en coherency → chaque figurine
   doit finir plus proche de l ennemi le plus proche, en B2B si possible.
2. Sinon : chaque figurine peut se deplacer vers l objectif le plus proche, a condition
   que le deplacement mette l escouade a portee de cet objectif ET en coherency.
3. Sinon : aucune consolidation.

Si aucune de ces conditions ne peut etre satisfaite : pas de Consolidation.

Transaction atomique sur le plan complet.

### Validation coherency post-combat

Apres resolution et consolidation, si des figurines ennemies ont ete detruites,
la coherency des escouades adverses doit etre verifiee et le retrait de fin de tour
eventuel planifie.

### Fichiers impactes (fight)

- `engine/phase_handlers/fight_handlers.py` :
  - `_fight_build_activation_pools` : ajouter ordre alternance non-active player first,
    Fights First en premier.
  - `_fight_build_valid_target_pool` : etendre pour regle du buddy.
  - Ajouter `fight_pile_in_plan(game_state, squad_id)` (transaction atomique).
    Type de retour : `list[tuple[str, int, int]] | None` — liste de (model_id, col, row)
    ou None si le Pile In est invalide. Aucun effet de bord sur les caches si None.
  - Ajouter `fight_get_fighting_models(game_state, squad_id)`.
  - Ajouter sous-flow declaration/lock/resolution melee.
  - `_fight_plan_consolidation_destinations` : etendre pour multi-figurines,
    OR condition ER-ou-objectif, validation coherency.

---

## HP tracking — contrat complet

### Allocation prioritaire (regle officielle)

Lors de la resolution des attaques d une activation :
1. Si une figurine ennemie a deja `wounds_allocated_this_activation > 0`, les attaques
   suivantes **doivent** lui etre allouees en priorite.
2. Ce n est qu en l absence de figurine deja blessee que le defenseur peut choisir
   une autre figurine.

Scope : par activation de l unite attaquante. Reset au debut de chaque activation.

### Damage exces

Si une attaque inflige D points de damage et que la figurine cible n a que X HP
avec X < D : elle est detruite, le surplus D - X est **perdu**. Pas de carry-over
sur la prochaine figurine du squad.

### Cascade de mise a jour

```python
def destroy_model(game_state: dict, model_id: str, reason: str) -> None:
    """
    reason : "combat" | "coherency_removal" | "deployment_no_space"

    - Recalcule l ancre si la figurine detruite etait l ancre courante
      (AVANT tout autre update de cache).
    - Retire la figurine de models_cache.
    - Retire model_id de squad_models[squad_id].
    - Met a jour units_cache : HP_CUR, occupied_hexes (dict), OC_TOTAL.
    - Met a jour squad_cache.
    - Si derniere figurine : appelle remove_from_units_cache(squad_id).
    - Si reason == "coherency_removal" : pas de score kill, pas d OC retire
      pour objectifs (le retrait est reglementaire, pas un kill de combat).
    - Si reason == "combat" : mettre a jour score / reward signal.
    - Si la figurine detruite a des attaques declarees dans pending_squad_shoot_intents
      ou pending_squad_fight_intents : invalider ces entrees (supprimer l intent de la
      figurine morte de la liste). Les attaques CONTRE elle restent resolues normalement.
      **Attention modification en cours d iteration** : ne jamais supprimer directement
      depuis une boucle for sur la liste. Pattern correct : collecter les indices a
      supprimer pendant la boucle, supprimer apres (en reverse order ou via list comprehension).
    """
```

**Contrat `occupied_hexes` :**

```python
units_cache[squad_id]["occupied_hexes"] = {
    model_id: (col, row)
    for model_id in models vivants de l escouade
}
# Retrait d une figurine : del occupied_hexes[model_id]
# Deux figurines sur le meme hex : entrees distinctes -> pas de perte d info
```

**Risque de desynchronisation :** `occupied_hexes` duplique les positions de `models_cache`.
Toute ecriture de position doit passer par `update_model_position(model_id, col, row, game_state)`
qui met a jour les deux en meme temps. Ne jamais ecrire l un sans l autre.

### Mort d escouade

Quand `models_cache` ne contient plus aucune figurine du squad :
`remove_from_units_cache(squad_id)`.

### OC mis a jour

`units_cache[squad_id]["OC_TOTAL"]` = somme des OC des figurines vivantes.

---

## Observation et action space (RL)

### Action space (micro)

**Clarification action_space_size :**
L espace d actions actuel est `Discrete(31)` = 16 micro + 15 macro (zone intents).
Ce spec decrit uniquement les **16 actions micro** (indices 0-15). Les actions macro
(indices 16-30) correspondent au systeme `zone_intents` existant et ne changent pas.
En PR4, l action space total reste 31 — seul le mapping des 16 premières actions change.
Ne pas modifier `TOTAL_ACTION_SIZE` ni `BASE_ZONE_INTENT` dans `macro_intents.py`.

L action space **micro** passe de 13 actions actives (sur Discrete(31)) a `16 actions micro`
pour accueillir les 6 directions de mouvement hex (au lieu de 4) et l action Fall Back :

```
Actions 0-5  : Normal move direction D (0=NE, 1=E, 2=SE, 3=SW, 4=W, 5=NW)
               "deplacement de l ancre dans la direction D,
                toutes les figurines suivent en formation rigide"
               Masquees si **au moins une figurine** de l escouade est en ER ennemi
               (meme regle que locked in combat — une seule figurine suffit).
Action  6    : Advance (= Normal move avec Advance roll D6, direction determinee par macro_intent)
               Masquee si l escouade est en ER ennemi.
Action  7    : Fall Back (direction auto = maximise distance depuis ER ennemi)
               Disponible uniquement si l escouade est en ER ennemi.
               Masquee si hors ER ennemi.
               Note MVP : Desperate Escape Tests non implementes (hors scope PR1-3).
Action  8    : wait / end activation
               Masquee en Fight phase si l unite est eligible au combat (un joueur
               ne peut pas passer quand il a des unites eligibles — regle officielle).
Actions 9-13 : shoot slots 0-4 (slot i = cibler l escouade ennemie i)
Action  14   : charge (vers la cible du macro_intent)
Action  15   : fight — declenche le flux complet en un seul gym step :
               Pile In automatique (plan optimal calcule par le moteur, transaction atomique)
               → declaration automatique des cibles melee (auto-selection, voir section Fight)
               → resolution complete de toutes les attaques
               → Consolidation automatique (plan optimal calcule par le moteur).
               L agent ne voit pas les sous-etapes. Le gym step retourne la prochaine observation
               apres que toute la sequence est terminee et les caches mis a jour.
               Masquee si l escouade n est pas eligible au combat (aucune figurine en ER ennemi
               et n a pas charge ce tour).
```

`Discrete(16)` pour PR1-3. Les extensions (retrait fin de tour interactif, melee split)
seront evaluees en PR4 et ajouteront des actions si necessaire.

**Mapping slot -> escouade ennemie (stabilite) :**
- Au debut de la partie, les 5 escouades ennemies a la plus grande menace estimee
  (`HP_total * OC_total`) recoivent un slot fixe (0-4). Ce calcul est fait **une seule fois**
  a l init de la partie — le mapping ne change jamais ensuite.
- Si une escouade ennemie de rang > 4 detruit une des 5 premiers en cours de partie :
  son slot reste vide (masque = 0). La 6eme escouade n est pas promue. Ce cas est acceptable
  pour le MVP ; si plus de 5 escouades ennemies sont frequentes dans les scenarios de training,
  revoir ce choix en PR4.
- Si une escouade est detruite : son slot reste reserve, le masque est mis a 0. Jamais de
  reecriture des indices.
- Si moins de 5 escouades ennemies au total : slots restants initialement a 0 (masques a 0).
- **Critere de departage a l init** : si plusieurs escouades ont le meme score de menace
  (`HP_total * OC_total`), les trier par index de creation (ordre dans `units_cache` a l init).
  Deterministe et stable.
- **Cas limite — tous les slots detruits :** si les 5 escouades mappees sont toutes detruites
  et qu il reste des escouades ennemies non mappees (possible si le roster depasse 5 unites,
  ex: swarm 16 unites), l agent n a plus aucun slot de tir utilisable. Documenter comme
  limitation connue. Si ce cas est frequent dans les scenarios de training (roster > 5 unites
  ennemies) : augmenter n_enemy_slots avant PR4.

**Retrait fin de tour :**
En PR3, retrait automatique deterministe (figurine la plus isolee geometriquement).
Aucune action agent requise — le moteur resout directement. En PR4, mesurer la frequence
du cas avant de decider si une action interactive est justifiee.

### Observation (micro)

Mettre a jour `engine/observation_builder.py` :
- Conserver sections globales existantes.
- Remplacer bloc "unit singleton" par :
  - **Features agreges escouade active** : nb figurines vivantes, is_coherent,
    OC total, HP total, puissance de feu totale estimee.
  - **Features top-k figurines** (k=6 — borne sur escouades standard W40K) :
    position relative au **centroide geometrique** normalisee par `perception_radius`
    (`col_rel / perception_radius`, `row_rel / perception_radius` → valeurs dans [-1, 1]),
    HP%, arme active index, is_fighting_eligible,
    `is_b2b_with_enemy` (bool), `is_b2b_with_ally_in_b2b` (bool — buddy rule).
    Les deux features B2B sont necessaires pour que le reseau apprenne a generaliser
    la regle du buddy sans les traiter comme un masque opaque.
    Padding zero si moins de k figurines vivantes.
  - **Features escouades ennemies** (5 slots fixes) : taille escouade (pour BLAST
    awareness), HP agreges, position ancre relative, OC total, slot actif (masque binaire),
    `is_locked_by_friendly_er` (bool — indique si ce slot est masque en tir parce qu une
    unite alliee est en ER de cette escouade ennemie).

**Pourquoi le centroide et non l ancre index-0 :**
Quand la figurine 0 (ancre) meurt, toutes les positions relatives calculees depuis elle
"sautent" discontinuellement en une etape. Du point de vue PPO, c est une perturbation
d observation sans changement d action — le gradient devient bruité sans raison metier.
Le centroide geometrique (moyenne des positions vivantes) varie continuellement a chaque
mort de figurine et ne provoque pas de saut discontinu. Si les k premieres figurines ont
toutes le meme profil, le centroide est aussi plus representatif de la position de
l escouade que n importe quelle figurine individuelle.

**k=6 justification :** les escouades standard W40K ont au plus 5-6 figurines en
contexte MVP. Pour les escouades de 7+, les figurines au-dela du rang 6 sont
representees par les features agreges (HP_total, model_count). Ce compromis est
acceptable si le moteur cible des escouades de taille <= 6 dans un premier temps.

**`obs_size` — formule et calcul obligatoire en fin de PR1 :**

```
# Features globaux (phase, tour, etc.) — a compter depuis observation_builder.py existant
N_global = <a_compter_en_PR1>

# Features escouade active agreges (nb_vivants, is_coherent, OC_total, HP_total, firepower)
N_squad_global = 5

# Features par figurine (top-k=6) :
# position relative centroide normalisee (col_rel/perception_radius, row_rel/perception_radius),
# HP%, arme_index, is_fighting_eligible, is_b2b_with_enemy, is_b2b_with_ally_in_b2b = 7 features
# Normalisation obligatoire : col_rel et row_rel sont des offsets en subhexes qui peuvent
# atteindre ±90 en x5. Diviser par perception_radius (config) pour rester dans [-1, 1].
# Coherent avec la convention de normalisation existante dans observation_builder.py.
N_per_model = 7
k = 6

# Features par slot ennemi (5 slots) :
# squad_size, HP_total, anchor_col_rel, anchor_row_rel, OC_total, slot_mask, is_locked_by_friendly_er,
# value_over_ttk, threat_level
# = 9 features
#
# value_over_ttk : VALUE_cible / TTK, normalise par la valeur max observable.
#   TTK = HP_restants / (P(hit) * P(wound) * P(failed_save) * D_moyen)
#   P(hit) depuis BS de l escouade active, P(wound) depuis table S vs T,
#   P(failed_save) depuis Sv/invul de la cible, D_moyen depuis profil d arme actif.
#   Pre-calcule par le moteur au debut de chaque activation de tir/fight.
#   Permet a l agent d apprendre a prioriser les cibles tuables rapidement et de valeur.
#
# threat_level : degats attendus de la cible sur l escouade active (ses propres armes),
#   normalise par le meme facteur que value_over_ttk.
#   Permet a l agent d apprendre a prioriser les cibles dangereuses sans formule fixe.
#
# L agent apprend seul la ponderation optimale entre value_over_ttk et threat_level,
# y compris sa dependance au contexte (tour, objectifs, HP restants).
# Pas de coeff_threat fixe — le reseau decouvre la politique optimale.
N_per_enemy_slot = 9
n_enemy_slots = 5

obs_size = N_global + N_squad_global + (N_per_model * k) + (N_per_enemy_slot * n_enemy_slots)
         = N_global + 5 + 42 + 45
         = N_global + 92
```

Verifier `N_global` dans `observation_builder.py` en fin de PR1 et fixer la valeur totale
dans `config/agents/*_training_config.json` avant de commencer PR2.
Toute evolution de structure impose une mise a jour de cette valeur.
Ne pas attendre PR4 — le modele PPO est incompatible si obs_size change entre PR1 et PR4.
**Critere d acceptance PR1 explicite** : `N_global` compte, valeur totale `obs_size` inscrite
dans la spec ET dans le config. Ne pas commencer PR2 sans cette valeur figee.

**Incompatibilite modele existant :** la nouvelle obs_size sera significativement superieure
a 357 (config actuel). Les poids du modele `x5_append` existant ne peuvent pas etre
reutilises — re-train from scratch obligatoire en PR4. Ne pas tenter de fine-tuning.

### Reward function (a finaliser avant PR4)

**Principe :** la reward est proportionnelle a la valeur points des unites, pas plate.
Tuer une unite a 200pts vaut deux fois plus que tuer une unite a 100pts.
Chaque HP retire genere un signal immediat — pas seulement a la mort de la figurine.

```python
# --- Composantes par HP retire (signal continu) ---

# A chaque damage applique a un modele ennemi (reason="combat") :
points_per_hp = models_cache[model_id]["points_per_hp"]  # pre-calcule a l init
reward += points_per_hp * hp_damage_weight * damage_dealt

# --- Bonus a la mort d une figurine ennemie ---
reward += (unit_points / model_count_at_start) * model_kill_bonus_factor

# --- Bonus squad wipe (derniere figurine de l escouade) ---
reward += unit_points * squad_kill_bonus_factor

# --- Symmetrie alliee (pertes propres) ---
reward -= points_per_hp_ally * hp_damage_weight * damage_taken
reward -= (ally_points / ally_model_count_at_start) * model_kill_bonus_factor
reward -= ally_points * squad_kill_bonus_factor  # si la derniere figurine alliee meurt

# --- Controle d objectif ---
reward_oc_control = +oc_weight  # par objectif controle en fin de tour (OC_allie > OC_ennemi)

# --- Coherency ---
reward_incoherent = -incoherent_weight  # par escouade hors coherency en fin de tour

# --- Overkill --- pas de penalite explicite.
# Signal implicite suffisant : declarations lockees avant resolution → figurines qui tirent
# sur une cible deja morte dans la meme activation ont leurs attaques perdues (zero damage,
# zero reward HP). L agent decouvre naturellement qu etaler le feu est optimal.
# Ajouter une penalite explicite si les logs de training montrent un overkill persistant.
```

**Parametres dans `config/agents/*_training_config.json` :**
```json
{
  "hp_damage_weight": 0.7,
  "model_kill_bonus_factor": 0.2,
  "squad_kill_bonus_factor": 0.3,
  "oc_weight": 0.5,
  "incoherent_weight": 0.2,
}
```

**Timing reward OC :**
`reward_oc_control` est calcule a la **fin de chaque tour** (apres les deux Fight phases du tour).
Un objectif est "controle" par le joueur dont l OC_TOTAL dans la zone > OC_TOTAL ennemi dans la zone.
La logique est appelee dans `end_of_turn_scoring()`. Pas de scoring en milieu de phase.

**Signal de terminaison de partie :**
La reward de fin de partie (victoire / defaite / limite de tours) doit etre explicitement
listee dans la revision PR4 du reward shaping. Ce signal existe probablement dans le code
existant — verifier et documenter la valeur (ex: +X pour victoire, -X pour defaite) pour
que l implémenteur PR4 ne l exclue pas par inadvertance lors de la refonte.

**Credit assignment — limitation connue du training (Action 15) :**
L action 15 (fight) compresse Pile In + resolution complete + Consolidation en 1 gym step.
Tous les kills et damages arrivent dans un seul signal reward. L agent ne peut pas apprendre
quelle figurine cibler prioritairement — la decision de ciblage est auto-selectionnee par le
moteur. Si l apprentissage du fight est lent : c est probablement le credit assignment compresse.
Mitigation : logs detailles post-step avec breakdown des kills par figurine.

**Proprietes de ce design :**
- Signal a chaque HP retire → plus de sparse reward sur figurines multi-blessures.
- Tuer vite une figurine deja blessee est recompense (kill bonus) → incite a finir
  les modeles blesses plutot que de saupoudrer les degats.
- Squad wipe capture la valeur tactique W40K de retirer une activation.
- Symetrie obligatoire : l agent valorise ses propres unites proportionnellement a leur cout.

**Analyse de magnitude (exemples de reference) :**
```
Unite A : 200pts, 5 figurines, HP_MAX=2 → points_per_hp = 200/(5*2) = 20
  Kill 1 figurine (2 HP) : HP reward = 20*0.7*2 = 28, kill bonus = (200/5)*0.2 = 8 → total 36
  Squad wipe : HP total + 5 kill bonus + squad bonus = 5*28 + 5*8 + 200*0.3 = 140+40+60 = 240

Unite B : 100pts, 10 figurines, HP_MAX=1 → points_per_hp = 100/(10*1) = 10
  Kill 1 figurine : HP reward = 10*0.7*1 = 7, kill bonus = (100/10)*0.2 = 2 → total 9
  Squad wipe : 10*7 + 10*2 + 100*0.3 = 70+20+30 = 120

Controle objectif : +0.5 par objectif par tour.
Escouade hors coherency : -0.2 par escouade par tour.
```
Ces magnitudes sont coherentes : tuer vaut plus que controler, ce qui est intentionnel
(le jeu W40K est combat-centric). Si l agent ignore les objectifs : augmenter `oc_weight`.
Si l agent est trop agressif et negllige sa survie : reduire `hp_damage_weight` ou augmenter
`incoherent_weight`. Calibrer sur les premiers runs de training.

**Contrainte :** `reason="coherency_removal"` ne genere aucun reward negatif de mort
(la figurine est retiree reglementairement, pas tuee). La composante `reward_incoherent`
penalise la situation en amont (escouade hors coherency), pas le retrait lui-meme.

### Strategie agent (micro + macro)

1. Un micro-agent PPO par type d escouade (policy sharing), pas par instance.
2. Geler le macro pendant la stabilisation du micro escouade.
3. Stabiliser le micro "escouade multi-figurines".
4. Reprendre l entrainement macro sur le nouveau micro stable.

---

## Plan de migration concret (4 PR)

### PR1 — Data model et caches

- **Format config agents a faire evoluer** : le format JSON actuel de `config/agents/<agent>/`
  stocke les stats (RNG_WEAPONS, CC_WEAPONS, M, T, W, Sv, etc.) directement a la racine de l unite,
  pas dans un tableau `models[]`. PR1 doit ajouter un champ `"model_count": int` (nombre de figurines
  dans l escouade) et un champ `"model_profile": {...}` (profil commun) ou `"models": [...]` (profils
  differencies si profils mixtes). La transformation exacte :
  ```json
  // AVANT (actuel)
  { "id": "squad_a", "W": 1, "RNG_WEAPONS": [...], ... }

  // APRES (cible PR1)
  { "id": "squad_a", "model_count": 5, "W": 1, "RNG_WEAPONS": [...], ... }
  // W, RNG_WEAPONS, CC_WEAPONS = profil par figurine (identique pour toutes si homogene).
  // Pour profils mixtes : ajouter "models": [{"id": "...", "W": 3, ...}, ...] explicitement.
  ```
  `game_state.py` lit `model_count` a l init pour construire `models[]` en memoire.
  Les fichiers JSON de config ne listent pas les figurines individuellement sauf si profil mixte.
- `engine/game_state.py` : charger `models[]` par unit depuis la config.
  `VALUE` est deja present dans `units_cache` — aucun nouveau champ de valeur necessaire.
- `shared_utils.py` :
  - Ajouter `models_cache` + `squad_models` (index inverse squad_id -> [model_id, ...])
    + helpers `update_model_position` (met a jour models_cache ET occupied_hexes
    ET squad_cache en une seule passe), `update_model_hp`,
    `is_model_alive`, `destroy_model(model_id, reason)`.
  - Pre-calculer `points_per_hp = units_cache[squad_id]["VALUE"] / (model_count_at_start * HP_MAX)`
    pour chaque modele a l init et le stocker dans `models_cache`. `VALUE` est deja
    present dans `units_cache` — pas de nouveau champ a ajouter au config.
  - Pre-calculer et stocker `model_count_at_start` dans `squad_cache` (ne jamais modifier).
  - Ajouter `squad_cache` avec `centroid_col/row` + helpers de recalcul.
    Recalcul obligatoire dans : `destroy_model` ET `update_model_position`.
  - Mettre a jour `units_cache` (HP_CUR, occupied_hexes dict, OC_TOTAL, ancre) a chaque
    destruction.
  - Ajouter `units_fled` au game_state.
  - Definir `ENGAGEMENT_RANGE_SUBHEX`, `BASE_TO_BASE_SUBHEX`, `COHERENCY_SUBHEX`
    comme constantes calculees depuis `inches_to_subhex`.
  - Implementer `is_base_to_base` et `is_in_engagement_range`.
- Deploiement : placer N figurines en formation coherente depuis l ancre (BFS spirale).
- Auditer et adapter les fonctions listees en section "Migration units_cache".
- **Supprimer `engine/phase_handlers/fight_handler_new_bugged.py`** avant tout autre changement
  (fichier marque bugged, ne doit pas coexister avec la migration fight PR3).
- Garder strictement les invariants actuels de phase et pools.
- **Calculer et fixer `obs_size` dans `config/agents/*_training_config.json`** une fois
  la structure de donnees completement definie. Ne pas commencer PR2 sans cette valeur fixee.

### PR2 — Mouvement et charge escouade

- `movement_handlers.py` : plan multi-figurines atomique (6 directions, advance roll,
  translation rigide + validation), flags post-Advance et post-Fall Back.
- `charge_handlers.py` : check eligibilite 12", plan de charge multi-figurines
  (deplacements individuels, B2B si possible).
- Validation coherency apres move et apres charge.
- Scenarios de validation : collisions, murs, ER ennemi, rupture coherency, charge
  echouee, advance roll min/max.
- **PR2 = moteur uniquement.** L action decoder actuel (actions 0-3 = 4 strategies de
  mouvement) n est pas migre en PR2. Le mouvement escouade multi-directionnel (6 directions
  + Fall Back) n est pas accessible a l agent RL avant PR4. Les runs de validation PR2
  utilisent `--step` (verification deterministe) et non un agent PPO.

### PR3 — Tir et fight declaration/resolution

- `shooting_handlers.py` : flow declaration auto / lock / resolution pour escouade,
  reset `wounds_allocated_this_activation` par activation, gestion BLAST bonus,
  damage exces, figurine morte mid-resolution, locked in combat correct.
- `fight_handlers.py` : ordre alternance non-active player first, Fights First,
  Pile In multi-figurines (B2B obligatoire si possible), regle du buddy (non transitif),
  declaration melee, Consolidation OR condition (ER ou objectif).
- Sequence Hit→Wound→Save→Damage dans les deux phases.
- Allocation prioritaire HP dans les deux phases (scope par activation).
- Retrait fin de tour : mode deterministe (figurine la plus isolee).
- Validation coherency post-pertes.
- Scenarios de validation : restrictions advance/fell_back, morts en chaine,
  ordre deterministe, buddy rule, consolidation vers objectif, B2B obligation Pile In.

### PR4 — RL et training

- `observation_builder.py` : encodage escouade (features agreges + top-k=6 figurines
  depuis centroide + features B2B + 5 slots ennemis fixes + is_locked_by_friendly_er).
- `action_decoder.py` : masks escouade, 6 directions Normal move + Fall Back,
  mapping slots stable, masque wait en fight phase si eligible.
- `observation_builder.py` : supprimer ou adapter l assertion `obs_size == 357`
  (ligne 1226) — elle leve ValueError si obs_size != PHASE2_OBS_SIZE, ce qui bloquera
  toute tentative de changement d obs_size en PR4.
- `config/agents/*_training_config.json` : verifier obs_size (fixe en PR1) +
  parametres reward shaping (hp_damage_weight, model_kill_bonus_factor,
  squad_kill_bonus_factor, oc_weight, incoherent_weight).
- Mesurer la frequence du cas "retrait fin de tour" sur runs de validation.
  Si > 5% des tours : implementer action interactive. Sinon : conserver mode deterministe.
- Re-train micro puis macro.

---

## Risques majeurs et mitigation

1. **Explosion combinatoire des declarations de tir/melee.**
   Mitigation : factorisation par escouade cible, top-k=5 cibles, auto-selection
   d arme par figurine.

2. **Bugs de coherency apres pertes.**
   Mitigation : validation systematique post-action, test case dedie "escouade
   reduite a 1 figurine" (toujours coherente), test case "2 groupes separes".

3. **Instabilite PPO.**
   Mitigation : entrainement en 2 etages (micro puis macro), policy sharing par type,
   reward function calibree pour ne pas penaliser les retraits de coherency.

4. **Regle du buddy difficile a debugger.**
   Mitigation : logs explicites des figurines eligibles par tour, scenario de test
   dedie (escouade en deuxieme rang pur).

5. **Retrait fin de tour non encode en RL.**
   Mitigation : retrait deterministe en PR3, mesure de la frequence du cas,
   decision en PR4.

6. **Migration units_cache — regression silencieuse.**
   Mitigation : lister toutes les fonctions impactees (voir section Migration),
   tests de regression sur scenarios mono-figurine avant de passer aux escouades.

7. **B2B vs ER confondus.**
   Mitigation : fonctions `is_base_to_base` et `is_in_engagement_range` explicitement
   distinctes des PR1. Revue de code obligatoire sur tout usage de distance en PR3.

8. **Reward sous-optimal sans Battleshock.**
   Battleshock (test de fin de tour apres pertes) retire le bonus OC des unites
   affectees. Sans implementation, l agent peut surestimer la valeur de ses unites
   blessees en fin de tour et mal evaluer le scoring d objectif.
   Mitigation : documenter la limitation dans le training config, surveiller les
   scenarios ou l agent ignore les objectifs en fin de tour malgre des pertes importantes.
   Implementer en PR5.

9. **Discontinuite d observation lors du changement d ancre.**
   Mitigation : utiliser le centroide geometrique comme reference dans l observation
   (pas l ancre index-0).

10. **Fall Back sans Desperate Escape Tests.**
    Les figurines qui traversent l ER ennemi lors d un Fall Back devraient passer un test
    (1D6, 1-2 = figurine detruite). Non implemente en MVP. Consequence : l agent peut
    apprendre a exploiter le Fall Back de facon plus agressive que le permettrait la regle
    officielle. Surveiller si cela cree des politiques irrealistes. Implementer en PR5.

---

## Criteres d acceptance

1. Aucune escouade ne termine une activation hors coherency.
2. Mouvement escouade atomique (tout ou rien), coherency verifiee.
3. Tous les tirs escouade declares avant la premiere resolution.
4. Toutes les attaques melee declarees avant la premiere resolution.
5. Regle du buddy appliquee correctement (1 niveau de profondeur, non transitif).
6. Action masks stricts : aucune action illegale autorisee, flags advanced/fell_back,
   Normal move masque si en ER ennemi, Fall Back masque si hors ER ennemi,
   wait masque si eligible au combat en fight phase.
7. Allocation prioritaire HP respectee (scope par activation, pas par phase).
8. La charge echoue globalement si une seule figurine ne peut pas satisfaire les
   conditions.
9. `destroy_model` distingue combat vs coherency_removal vs deployment_no_space.
10. Advance roll D6 stocke et utilise pour le budget de deplacement.
11. Ordre alternance fight phase respecte : non-active player first dans les DEUX steps
    (Fights First ET Remaining Combats).
12. Escouade dont au moins 1 figurine est en ER ennemi = entierement locked in combat
    (sauf [PISTOL] / Monster / Vehicle).
13. Escouade de 1 figurine survivante est toujours en coherency.
14. Escouade ennemie en ER d un allie = slot de tir masque (sauf Monster/Vehicle attaquant).
15. Reward proportionnel aux points : chaque HP retire sur ennemi genere
    `points_per_hp * hp_damage_weight * damage_dealt`, avec bonus kill et squad wipe.
16. `squad_cache.centroid` recalcule apres chaque destroy_model ET apres chaque
    update_model_position — verifiable par assert en mode debug.
17. `occupied_hexes` et `models_cache` toujours synchronises — toute ecriture de position
    passe par `update_model_position`.

---

## Definition of done (MVP escouade)

- Une partie complete tourne avec escouades multi-figurines sur les 6 phases.
- Les logs de phase restent lisibles et deterministes.
- Le micro PPO apprend sans chute brutale de stabilite.
- Le macro wrapper fonctionne encore sans refonte majeure.
- Validation via `--step` sur scenarios :
  - escouade 2-6 figurines (regle 1 voisin),
  - grande escouade >= 7 figurines (regle 2 voisins),
  - escouade reduite a 1 figurine (coherency triviale),
  - figurine morte mid-resolution tir,
  - buddy rule rang 2.
- Analyzer.py confirme la stabilite sur plusieurs runs consecutifs.
- **Scenarios de training cibles escouades taille <= 6** (observation top-k=6 incomplete au-dela).
  Si des scenarios avec escouades > 6 figurines sont envisages : augmenter k avant PR4.
- **Limitations connues documentees** : Battleshock absent (impact OC scoring),
  Leaders absents, Overwatch absent, Desperate Escape Tests absents (Fall Back trop safe),
  Monster/Vehicle -1 to hit en ER absent, melee split hors scope MVP,
  weapon keywords complexes hors scope, charge multi-cibles absente,
  wound allocation scope per-activation (deviation "this phase"),
  Advance/Fall Back direction non libre (dependance macro / auto).
