# Endless Duty — mode exposé, jamais démarrable : état mesuré

Mesuré le **2026-07-29**. **Le mode n'a jamais pu démarrer** : `POST /game/new` en
`mode_code = "endless_duty"` lève avant même d'atteindre la logique de vagues. Décision de
l'utilisateur : **on ne supprime pas, on ne répare pas maintenant — on mesure et on consigne.**
Réactivation prévue à moyen-long terme.

Ce document est le résultat d'une **exécution réelle** : chaque obstacle listé a été atteint en
bouchant les précédents, puis tous les bouchons ont été retirés (dépôt propre). Ce qui n'a pas été
atteint est signalé comme **non exploré**, pas comme sain.

Spécification fonctionnelle du mode (V1, antérieure) : [`Documentation/Endless_duty.md`](../../Endless_duty.md).
Signet exécutable : [`tests/unit/services/test_endless_duty_is_broken.py`](../../../tests/unit/services/test_endless_duty_is_broken.py).

---

## 1. Ce que le mode est, et ce qui existe déjà

Un mode « survie » solo : le joueur tient **un objectif** avec une escouade de 1 à 3 slots
(`leader` / `melee` / `range`) contre des **vagues de tyranides** de budget croissant. Entre deux
vagues, il dépense des **points de réquisition** (capital, pas de revente) pour faire évoluer ses
slots. Défaite si toutes ses unités meurent, ou si les tyranides tiennent l'objectif N fins de
round d'affilée.

Ce qui est déjà écrit :

| Brique | Où | État |
|---|---|---|
| Moteur du mode | `services/endless_duty_runtime.py` (**1 289 lignes**) | complet en apparence : budget de vague, spawn en bordure, compteur de perte d'objectif, économie inter-vague, évolution de slots |
| Câblage API | `services/api_server.py` : `initialize_endless_duty_state` (~L2125), garde `inter_wave_pending` dans `execute_ai_turn` (~L3991), actions `endless_duty_status` / `endless_duty_commit` | présent |
| Scénario | `config/scenario_endless_duty.json` | présent, **format périmé** (cf. obstacles 1-4) |
| Données d'évolution | `config/endless_duty/{leader,melee,range}_evolution.json`, `wave_forced_spawns.json` | présentes |
| Fiches d'unités | `frontend/src/roster/spaceMarine/units/endlessDuty/` (**18 fiches** + `index.ts`) | présentes, **incomplètes** (obstacle 5) |
| Interface | `SharedLayout.tsx` (bouton `/game?mode=endless_duty`), `Routes.tsx`, `useEngineAPI.ts` (`endlessDutyState`, commit de réquisition), `useGameConfig.ts` | présent |
| Base | `config/users.db` : `game_modes` id 5 `endless_duty`, autorisé aux profils 1 et 2 dans `profile_game_modes` | présent |

Il y a donc bien un chantier réel à reprendre, pas une coquille vide.

---

## 2. Comment ça a été mesuré

Sonde jetable **hors dépôt**, rejouant le chemin exact de `POST /game/new` sans la couche HTTP/auth :

```
initialize_test_engine(scenario_file="config/scenario_endless_duty.json", forced_agent_key=...)
  → engine.reset()
  → initialize_endless_duty_state(...)
  → handle_endless_duty_post_action / spawn_next_wave_for_current_index /
    commit_inter_wave_requisition / engine._build_observation() / engine.execute_ai_turn()
```

À chaque erreur : noter, boucher au minimum, relancer. **7 obstacles** ont été franchis avant
d'obtenir une boucle de jeu qui tourne. Tous les bouchons ont ensuite été retirés
(`git status` propre) — **aucun n'est livré**.

Note d'environnement (sans rapport avec le mode) : `ai/models/ArmageddonAgent/model_ArmageddonAgent.zip`
n'existait pas au moment de la mesure (entraînement en cours, seul `_interrupted.zip` présent) ;
la sonde a pointé un lien symbolique hors dépôt vers ce checkpoint. `CoreAgent` n'est plus
utilisable : `config/agents/CoreAgent/` n'existe plus.

---

## 3. Obstacles, dans l'ordre où ils tombent

**Nature** : `DONNÉE` = remplir une donnée existante (mécanique) · `CODE` = écrire du code absent
ou corriger un code dérivé · `CONCEPTION` = une décision produit à prendre AVANT de coder.

### Obstacle 1 — `CODE`/`DONNÉE` · le scénario n'est plus localisable (½ j)

```
ValueError: Scenario 'config/scenario_endless_duty.json' must either be located in a
'config/board/<board>/scenario/' directory OR declare a 'board_ref' key to resolve wall_ref
```

Depuis V11 T3/T4, `GameStateManager._resolve_board_dir` n'accepte que ces deux formes. Le
scénario ED est resté à la racine de `config/` sans `board_ref`. **Ce qu'il faut faire** : le
déplacer sous `config/board/<board>/scenario/` (aligné sur les autres) ou lui ajouter `board_ref`.
Le déplacement impose de corriger `ED_SCENARIO_DEFAULT` (`endless_duty_runtime.py` L27) et
`useGameConfig.ts` L236.

### Obstacle 2 — `DONNÉE` · le `wall_ref` pointe un plateau non jouable (½ j)

```
ValueError: board_ref '44x60x10' (360x312 en x10) ne se réduit pas au plateau actif
(220x300 en x5) — ce n'est pas le même plateau physique
```

`"wall_ref": "walls-11.json"` n'existe que sous `config/board/44x60x10/walls/`, et `44x60x10`
n'est **pas** dans `BOARD_PATH_MAP` (`api_server.py` L57 : seuls `x1` et `x5_44x60`). Le plateau
x5 ne propose que `walls-33`, `walls-mc1`, `walls-none`. **Ce qu'il faut faire** : choisir (ou
créer) un jeu de murs pour un plateau jouable — c'est un **choix de level design**, pas une
substitution mécanique.

### Obstacle 3 — `CONCEPTION` · les objectifs du mode n'ont plus de format (2 à 4 j)

```
ValueError: Scenario file config/scenario_endless_duty.json uses removed objective key
'objectives'. Objectives are now sourced exclusively from terrain areas flagged "objective": true
```

C'est le plus lourd. Le mode entier est bâti sur **un** objectif de 7 hexes, tiré au sort par run
dans un `objective_pool` de 5 (`endless_duty.objective_selection` / `objective_pool`) ; toute la
condition de défaite (`_update_objective_loss_counter`, `objective_rules.loss_counter_threshold`)
s'y appuie. Ce format a été supprimé : les objectifs viennent désormais des zones de terrain.

Mesuré en branchant `terrain_ref: terrain-mc1.json` : le moteur produit **5 objectifs de 1 730 à
3 000 hexes chacun** — sans rapport avec les 7 hexes attendus. Le tirage par run et la géométrie
« un point à tenir » n'existent plus.

**Ce qu'il faut faire** : décision produit. Soit créer un `terrain_ref` dédié à Endless Duty avec
des zones-objectifs de la bonne taille et gérer le tirage aléatoire autrement (la sélection par
run n'a plus de support dans le format terrain), soit rendre au mode un mécanisme d'objectif qui
lui est propre. **À trancher par l'utilisateur** — `objective_pool` et `objective_selection` sont
aujourd'hui de la donnée morte.

### Obstacle 4 — `CODE` · aucune unité ennemie à `reset()` (1 j)

```
ConfigurationError: Required key '2' is missing from mapping.   (value_at_start[2])
```

Le scénario ne déclare qu'une unité, joueur 1. Or `engine.reset()` construit une observation qui
exige les deux joueurs, et `api_server.py` reconnaît lui-même l'ordre : *« Endless Duty spawns
tyranids after reset »*. L'ordre `reset()` → observation → `initialize_endless_duty_state()` est
**structurellement inversé**. **Ce qu'il faut faire** : soit déclarer une garnison de vague 1 dans
le scénario, soit spawner la vague avant la première construction d'observation. C'est un choix
d'architecture d'initialisation, pas une ligne de donnée.

### Obstacle 5 — `DONNÉE` · les 18 fiches endlessDuty sont incomplètes (½ j)

```
ConfigurationError: Required key 'ILLUSTRATION_RATIO' is missing from mapping.
```

Mesuré sur le registre réel : les **18 fiches sur 18** n'ont ni `ILLUSTRATION_RATIO` ni
`FACTION_KEYWORDS` (comparaison avec `Intercessor`, fiche de production). `MeleeTerminator` n'a en
plus ni `RNG_WEAPON_CODES` ni `selectedRngWeaponIndex`. **Ce qu'il faut faire** : compléter ; c'est
mécanique (les fiches délèguent déjà leurs autres champs à leur unité de production, ex.
`static VALUE = Intercessor.VALUE`).

### Obstacle 6 — `CODE` · `_build_unit_from_registry` est un doublon qui a dérivé (2 à 3 j)

```
KeyError: 'BASE_SHAPE'        (dans build_units_cache, via _replace_units_for_player)
```

`_build_unit_from_registry` (`endless_duty_runtime.py` L578) réimplémente à la main
`GameStateManager._build_enhanced_unit` (`game_state.py` ~L920). Le doublon n'a pas suivi la
migration V11. Diff mesuré contre une unité réellement construite par le loader de scénario —
**14 champs absents de sa sortie** :

`BASE_SHAPE`, `BASE_SIZE`, `MODEL_HEIGHT`, `orientation`, `level`, `deployed_on_turn`,
`battle_shocked`, `hidden`, `hidden_models`, `hideable`, `CAN_LEAD`, `_UNIT_RULES_OWN`,
`_ATTACHED_RULE_GROUPS`, `_wdc_def_key`.

Et **trois conversions subhex manquantes** (plateau actif : `inches_to_subhex = 5`) :

| Champ | Builder ED | Loader de scénario |
|---|---|---|
| `MOVE` (Termagant) | `6` | `30` |
| `RNG` arme 0 (Termagant) | `18` | `90` |
| `BASE_SIZE` | chaîne brute `"X.BASE_SIZE"` non résolue | `6` (via `_scale_socle`) |

Autrement dit : même une fois la donnée complétée, les unités produites seraient **5× trop lentes
et 5× trop courtes de portée**, avec un socle inexploitable.

**Ce qu'il faut faire** : ne pas rapiécer clé par clé. `_build_unit_from_registry` doit
**déléguer à la fabrique canonique du moteur** (`_build_enhanced_unit`) et ne garder en propre que
ce qui est spécifique à ED (résolution des références statiques `X.FIELD`, application des picks
de slot). C'est la seule forme qui empêche la dérive de recommencer. L'effort est dominé par le
découplage de `_build_enhanced_unit`, aujourd'hui méthode d'instance de `GameStateManager`.

### Obstacle 7 — `CONCEPTION` · `VALUE` porte deux sens incompatibles (1 à 3 j selon l'arbitrage)

```
ValueError: value_at_start[1] = 0.0 : une armee de valeur nulle rend la force d usure indefinie
(donnee de roster invalide).
```

Le premier obstacle qui n'est **pas** une panne de plomberie.

- Le **moteur** lit `VALUE` comme la valeur de **combat** : `build_units_cache` en dérive
  `value_at_start`, référence de la force d'usure observée par l'agent (V11 §9.8), et
  `build_squad_observation` **refuse** une valeur nulle.
- **Endless Duty** écrase `VALUE` avec le **coût en points de réquisition**
  (`_apply_slot_picks_to_unit` L1306, depuis `_resolve_slot_pick_override`).
  `config/endless_duty/leader_evolution.json` donne `catalog.Sergeant.base = 0` et un coût `0` à
  chacun des trois picks de départ — conforme à `economy.starting_leader_requisition_cost: 0`.

Résultat mesuré : le leader construit a `VALUE = 0`, `value_at_start[1] = 0`, **aucune
observation ne peut être construite → le tour IA est impossible**. La fiche `LeaderSergeant.ts`
déclare pourtant `static VALUE = 18` (« Combat value target for ED starting leader ») : la valeur
de combat existe, elle est simplement écrasée par le coût.

**À trancher par l'utilisateur** : séparer les deux notions (par ex. un champ de coût distinct,
`VALUE` restant la valeur de combat) ou donner un coût de départ non nul. La première option est
la seule qui tienne si les deux grandeurs doivent diverger — et elles divergent par construction,
puisque le mode facture des améliorations qui ne changent pas la valeur de combat de la même façon.

---

## 4. Total et point d'arrivée

| # | Nature | Effort |
|---|---|---|
| 1 — localisation du scénario | CODE/DONNÉE | ½ j |
| 2 — `wall_ref` sans plateau | DONNÉE (level design) | ½ j |
| 3 — objectifs sans format | **CONCEPTION** | 2 à 4 j |
| 4 — pas d'ennemi à `reset()` | CODE (architecture d'init) | 1 j |
| 5 — 18 fiches incomplètes | DONNÉE | ½ j |
| 6 — builder d'unité dérivé | CODE | 2 à 3 j |
| 7 — double sens de `VALUE` | **CONCEPTION** | 1 à 3 j |
| **Total** | | **≈ 8 à 13 jours**, dont **2 décisions produit** (3 et 7) qui commandent le reste |

**Jusqu'où la mesure est allée**, une fois les 7 obstacles bouchés temporairement — tout ceci a
été **exécuté**, pas déduit :

- `initialize_endless_duty_state` va au bout : leader reconstruit, vague 1 composée
  (`budget_target 15` → 3 tyranides, valeur 17) et posée en bordure de plateau ;
- 12 `advance_phase` d'affilée : phases `move`/`shoot`/`charge` s'enchaînent sur 3 tours sans erreur ;
- sérialisation d'état API (`_game_state_for_json` + `make_json_serializable`) : **OK**, ~1,8 Mo ;
- fin de vague : `handle_endless_duty_post_action` détecte le nettoyage, crédite (`credits_delta 6`)
  et passe `inter_wave_pending` à vrai ;
- réquisition inter-vague : `commit_inter_wave_requisition` accepte un achat de slot `range` à la
  vague 10, débite le capital et déclenche le spawn de la vague suivante ;
- observation et **tour IA** : construits et joués **une fois `VALUE` forcée à 18 dans la sonde**
  (obstacle 7 contourné) — `execute_ai_turn` rend une activation valide.

Le mode est donc **plus proche qu'il n'y paraît** : la boucle de jeu, l'économie et le cycle de
vagues fonctionnent. Ce qui bloque, ce sont sept trous en amont, dont deux seulement demandent une
décision.

---

## 5. Ce qui reste NON EXPLORÉ

À dire tel quel : ce n'est pas « sain », c'est **non testé**.

- **Le parcours HTTP réel** (`POST /game/new` avec auth + permissions de profil, puis
  `/api/game/action`, `/api/game/ai-turn`) : la sonde court-circuite la couche Flask. Rien ne dit
  que les routes ED répondent correctement bout en bout.
- **Le frontend** : aucun rendu vérifié. Le bouton, la route et le hook existent ; leur
  comportement face à un état ED réel est inconnu.
- **Plusieurs vagues d'affilée**, la montée en budget (`budget_growth_after_wave_20`, `wave_spike`),
  et les `wave_forced_spawns` au-delà de la vague 1.
- **La condition de défaite par objectif** : `_update_objective_loss_counter` n'a **jamais été vu
  s'incrémenter**. Elle dépend entièrement de l'obstacle 3 ; sa sémantique face à des zones
  d'objectif de 3 000 hexes est indéterminée.
- **Les consommables** (`endless_duty.consumables` : 4 items, plafonds d'usage) : **conception
  absente, assumée** — `_compute_wave_credits` le dit noir sur blanc (`endless_duty_runtime.py`
  L719 : *« V1: no consumables pipeline yet in engine => treat as unused for scoring »*) et aucune
  occurrence de `consumable` n'existe dans `engine/`, `ai/` ni `frontend/src`. Le bonus
  `no_consumable_bonus` est donc toujours acquis. À concevoir, pas à réparer.
- **Les coordonnées de départ** : `ED_START_LEADER_COL/ROW = (12, 10)` (`endless_duty_runtime.py`
  L29-30) sont des coordonnées **d'avant la migration subhex**. Sur le plateau actif (220 × 300),
  c'est un coin, et le leader n'y est sur aucun objectif. Constaté, non traité — dépend de
  l'obstacle 3.
- **Le combat lui-même** en mode ED (phase `fight`, pertes, morale) : jamais atteint, les unités
  étant trop éloignées dans les tours joués.

---

## 6. Le signet

[`tests/unit/services/test_endless_duty_is_broken.py`](../../../tests/unit/services/test_endless_duty_is_broken.py)
— 5 tests qui **affirment l'état cassé** (obstacles 1-7) avec les valeurs exactes mesurées ici.

Forme retenue : **affirmer l'état cassé**, pas `xfail(strict=True)`. Deux raisons.
(1) La vérification large de l'utilisateur doit rester exploitable : un rouge durable finit par
être ignoré, ce qui reproduirait exactement le problème que ce document constate. Ces tests sont
**verts aujourd'hui**.
(2) Un `XPASS(strict)` signale qu'« un truc a changé » sans dire lequel ; ici chaque assertion
nomme son obstacle et renvoie à ce document dans son message d'échec.

Le jour où quelqu'un bouche un trou, le test correspondant passe au rouge avec un message du
type « obstacle 5 levé : mettre à jour Endless_duty.md ». C'est le signal de réparation.

Voir aussi : `tests/unit/services/test_endless_duty_value_baseline.py`, dont le helper `_unit()`
fabrique à la main les champs de socle et un `VALUE` non nul — il compensait précisément les trous
6 et 7, ce qui explique que la panne soit restée invisible. Sa complaisance est désormais écrite
dans sa docstring.
