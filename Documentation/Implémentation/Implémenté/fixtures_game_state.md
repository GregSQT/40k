# Les fixtures de test fabriquaient un `game_state` que la production ne produit jamais

**Ouvert le 2026-07-29. Livré le 2026-07-29. Suite livrée le 2026-08-04 (§8).**
Décision d'architecture prise par l'utilisateur (§4) : socle minimal, liste **répliquée** +
test de conformité. Périmètre exécuté : volets 1 et 2, puis §8 — clés de partie du `game_state`
et socle d'unité, sur la même décision d'architecture.

---

## 1. Comment ce sujet est apparu

Le commit `7addf91f` (« appliquer 10.05 apres advance ») a ajouté dans
`shared_utils._advance_blocks_weapon` une lecture obligatoire :

```python
if squad_id not in require_key(game_state, "units_advanced"):
```

**21 tests** de `test_squad_shoot_declaration.py` sont passés au rouge d'un coup, tous sur le même
`ConfigurationError: Required key 'units_advanced' is missing`.

Le réflexe naturel — assouplir la lecture en `.get("units_advanced", set())` — aurait été le pire
choix possible : il aurait fait passer **toutes** les unités pour « n'ayant pas avancé », donc
**désactivé 10.05** au lieu de le vérifier, en silence. `require_key` ne s'était pas trompé : il
venait de révéler que la fixture `_make_gs` construisait un `game_state` **impossible en
production**.

## 2. L'inventaire (mesuré à l'AST, 2026-07-29)

Balayage de `tests/` : tout dict littéral portant `units` + `phase` (ou `units` + `board_cols`).

> **62 `game_state` littéraux, répartis dans 51 fichiers. AUCUN ne posait les invariants
> d'état de tour. La médiane était à 17 manquants sur 19.**

| Invariant manquant | Fixtures concernées |
|---|---|
| `advance_rolls`, `units_shot_previous_turn` | **62** (toutes) |
| `units_took_to_skies_charge` | 59 |
| `last_move_cause`, `last_move_event_id`, `reactive_mode`, `reactive_decision_mode`, `units_took_to_skies` | 56 |
| `reaction_window_active`, `reactive_decision_payload`, `reactive_macro_order_current_window`, `units_reacted_this_enemy_turn` | 55 |
| `units_shot` | 52 |
| `units_cannot_charge` | 50 |
| `units_charged` | 44 |
| `units_fled` | 40 |
| `units_advanced`, `units_moved` | 37 |

## 3. Deux corrections à la prémisse, trouvées en instruisant

**(a) Le dict d'`__init__` n'est PAS la référence.** `w40k_core.py:435-530` ne pose que **15** des
invariants : `units_advanced`, `advance_rolls`, `units_took_to_skies` et
`units_took_to_skies_charge` n'existent que dans le dict de `reset()` (`w40k_core.py:1139-1183`),
et `__init__` n'appelle jamais `reset()`. Aucun bug de production — tout chemin réel passe par
`engine.reset()` (`api_server.py:2213`, `:3382`) — mais **un socle dérivé de l'init aurait été
amputé de `units_advanced`**, la clé même de l'incident 10.05.

**(b) Il y a 20 invariants, pas 19.** Le filet « reset() ne pose rien hors du socle » a fait
apparaître `units_fought` : posé par `command_phase_start` (`command_handlers.py:51`) et non par
`reset()`, mais présent dans tout `game_state` de production (la cascade command suit le reset) et
lu en `require_key` par la phase fight (`fight_handlers.py:1557`, `:1580`, `:1601`). Il est dans
le socle. `units_cache` / `units_cache_prev` sont au contraire des **vues dérivées** des unités,
explicitement hors socle.

## 4. Décision d'architecture retenue

**Socle minimal, liste répliquée, conformité verrouillée par test.**

`tests/_state_invariants.py` expose `turn_state_invariants()` (les 20 clés d'état de tour aux
valeurs exactes du `game_state` post-reset, plus les clés de partie ajoutées depuis — cf. §8).
Chaque fixture le fusionne en tête de son littéral, donc **ses propres clés gagnent** :

```python
gs = {**turn_state_invariants(), "phase": "shoot", "units_advanced": {"3"}, ...}
```

Le constructeur unique a été écarté : les 62 fixtures divergent sur la config, les rosters et les
caches pré-construits (`test_movement_pool_build.py:80` vs `test_phase_start.py:47`) — un builder
les couvrant toutes aurait dû reproduire `_initialize_units` et les caches, soit un second moteur
à maintenir, pour un problème qui ne portait que sur l'état de tour.

La liste est **répliquée** (pas dérivée : une fixture unitaire ne peut pas construire un engine
complet), et la dérive est fermée par trois tests dans
`tests/unit/engine/test_engine_reset.py::TestTurnStateInvariantsConformity` :
socle ⊆ post-reset, valeurs identiques, et le filet inverse (aucun invariant du moteur hors socle).

Placement en `tests/` racine : `from tests._state_invariants import …` fonctionne partout
(`pythonpath = .`), y compris pour les 5 fixtures hors `tests/unit/engine/`.

## 5. Volet 1 — poser le socle : neutre, et pourquoi

Les 62 fixtures ont été fusionnées avec le socle (51 fichiers). **Aucun test n'a changé de
verdict**, et ce n'est pas une chance : toutes les lectures silencieuses de production ont un
défaut **égal** à la valeur du socle — `set()` partout (`observation_builder.py:1122-1126`,
`shooting_handlers.py:1019-1021`, `shared_utils.py:9697-9700`) ; la seule exception,
`reactive_macro_order_current_window`, lève explicitement (`shared_utils.py:2298-2300`).

> **Conséquence à ne pas gommer : le socle ne répare aucun faux-vert.** Il aligne l'état des tests
> sur la production et supprime la classe « crash-surprise à la prochaine `require_key` ». Le
> faux-vert vient d'ailleurs : d'un test qui **devrait** peupler une clé pour exercer une règle et
> ne le fait pas. Lui donner `set()` ne le corrige pas — c'est le volet 2.

## 6. Volet 2 — les règles réellement non verrouillées

Mesure : combien de sites de `tests/` peuplent chaque invariant à une valeur **non vide**. Trois
trous nets, tous fermés, chacun prouvé rouge avant d'être rétabli.

| Trou | Mesure | Verrou posé | Mutation qui le rougit |
|---|---|---|---|
| **13.09 Hidden, membre « ni au tour précédent »** — `units_shot_previous_turn` absente des 62 fixtures, lue par 3 `.get` de `shooting_handlers` ; seul le drapeau d'observation était couvert (`test_squad_obs_terrain_flags.py:200`), pas le moteur de tir ni le preview | 1 site | `tests/unit/engine/test_hidden_1309_previous_turn.py` (3 tests : statut réel, preview, contre-épreuve) | la fixture omet la clé → `hidden` reste `True` : le demi-13.09 silencieux |
| **Les 5 bits d'état de tour de l'observation** (`moved`, `shot`, `fought`, `advanced`, `fled`) : aucun n'était vérifié allumé — une permutation du mapping bit↔clé sortait une obs fausse sans qu'une assertion bouge | `units_fought` (le mapping lisait `units_attacked`, clé sans écrivain — corrigé le 2026-08-08) | `tests/unit/engine/test_squad_obs_turn_state_bits.py` (7 tests, « ce bit et lui seul ») | (a) clé omise → bit éteint ; (b) `fought` recâblé sur `units_shot` dans le moteur → 2 tests rouges |
| **`reactive_mode="macro"`** : branche entière de `_select_reactive_unit_order` jamais exercée (0 occurrence de `"macro"` dans `tests/`), ordre et erreurs explicites compris | 0 site | `tests/unit/engine/test_reactive_move.py::TestSelectReactiveUnitOrder` (5 tests) | macro retombant sur le tri par id → 3 tests rouges |

La règle 13.09 a été relue dans `Documentation/40k_rules/13 Terrain.pdf` avant d'écrire le verrou :
« That model's unit did not make one or more ranged attacks **during this turn or during the
previous turn** ».

## 7. Vérifications faites, et ce qui ne l'est pas

**Fait :** les 51 fichiers modifiés + les 3 nouveaux lancés et verts ; `pyright` propre sur les 54
fichiers touchés ; le scanner AST reconfirme 62/62 fixtures fusionnées ; chaque verrou prouvé
rouge par mutation puis rétabli (`git status` propre sur `engine/` après chaque preuve).

**Non fait / limites :**
- La suite complète appartient à l'utilisateur — elle n'a pas été lancée ici.
- L'état vert **avant** modification n'a pas été remesuré (dépôt propre au départ) ; la neutralité
  du volet 1 est établie par la lecture des défauts de production, pas par un avant/après.
- **Le chiffre 62 reste un plancher** : le balayage ne voit que les dicts littéraux, pas les
  usines / `conftest` / factories.
- Les **44 autres clés** du dict d'init (hors état de tour) n'ont pas été instruites.
- Les invariants restants sont exercés non vides quelque part (7 à 53 sites chacun) mais leur
  couverture n'a pas été auditée règle par règle : `reactive_decision_payload` (0 site non vide)
  et `units_took_to_skies_charge` (5) sont les plus faibles après ceux traités ci-dessus.

---

## 8. Suite du 2026-08-04 — les clés de partie, puis le socle d'unité

Même motif, deux crans plus loin. Trois faits nouveaux, dans l'ordre où ils sont apparus.

### 8.1 `command_points` : le socle ne couvrait que l'état de TOUR

13 tests rouges d'un coup sur `Required key 'command_points' is missing`, après que la règle 08.02
a rendu la lecture stricte (`gain_command_points`, `observation_builder`). La clé n'est pas un
invariant d'état de tour — elle ne se réinitialise pas — mais elle est présente dans **tout**
`game_state` de production : `reset()` la pose à `initial_command_points(config)` = 0, puis la
cascade command du tour 1 accorde le CP de 08.02 aux deux joueurs. **Valeur du socle : `{1: 1, 2: 1}`**,
comme pour `units_fought`, et c'est le verrou de valeurs qui l'a imposée (`{1: 0, 2: 0}` le
rougissait). Le socle en compte donc 22 : 20 d'état de tour + `turn` + `command_points`.

### 8.2 `TURN_STATE_KEYS` supprimé : une liste de clés recopiée à côté du dict

Le frozenset répliquait la liste des clés **en parallèle** du dict. Deux trous : il ne couvrait pas
les clés de partie (`turn`, `command_points` n'y étaient pas, donc aucun des trois tests ne les
verrouillait), et il pouvait diverger du dict sans que rien ne rougisse. Il est supprimé : les
trois tests de `TestTurnStateInvariantsConformity` partent tous du dict `turn_state_invariants()`.
Le filet de dérive inverse continue de filtrer par préfixes (`units_`, `reactive_`, `last_move_`,
`advance_`, `reaction_`) — c'est ce filtre, et non une seconde liste, qui définit « invariant
d'état de tour ».

### 8.3 Le même trou existait un cran plus bas : les UNITÉS

Le `game_state` avait son socle, pas les unités. Chaque fichier recopiait à la main les champs
qu'une unité de production porte toujours — `battle_shocked` était réécrit dans une dizaine de
helpers, chacun avec son commentaire, et absent d'une trentaine d'autres.

`unit_invariants()` pose les **13 champs d'état constants** : `level`, `orientation`,
`deployed_on_turn`, `CAN_LEAD`, `_ATTACHED_RULE_GROUPS`, `hidden`, `hidden_models`,
`battle_shocked`, et les 5 champs de réserves 20.01–20.04 (`in_strategic_reserves`,
`reserves_repositioned`, `reserves_arrival_round`, `reserves_edge_distance_inches`,
`reserves_enemy_clearance_inches`).

**N'y entrent pas les champs DÉRIVÉS du roster**, qu'un socle figerait à une valeur fausse :
`SHOOT_LEFT`/`ATTACK_LEFT`, `selectedRngWeaponIndex`/`selectedCcWeaponIndex` (armes), `hideable`
(mots-clés), `_UNIT_RULES_OWN` (19.04). Cette classification est dans la docstring de
`unit_invariants()`, et le test d'exhaustivité interdit qu'un champ nouveau échappe aux deux.

Verrou : `tests/unit/engine/test_state_manager.py::TestUnitInvariantsConformity`, **5 tests** —
clés, valeurs, valeurs du second constructeur, égalité des jeux de clés des deux constructeurs,
exhaustivité. Il a mordu immédiatement : les 5 champs de réserves du chantier 04, mergé le même
jour, étaient posés par `create_unit` sans être classés nulle part.

**Les DEUX constructeurs sont exercés.** `create_unit` et `_build_enhanced_unit` (chargement de
scénario, `change_roster`) dupliquent le même bloc de champs d'état, et `initialize_units` repasse
chaque unité enrichie par `create_unit` : un champ ajouté d'un seul côté est silencieusement perdu
en production — c'est la dérive déjà vécue avec `in_strategic_reserves`. Le test d'égalité des jeux
de clés ferme ce cas ; sans lui, ajouter un champ au seul `_build_enhanced_unit` laissait tout vert.

### 8.4 Migration : 80 dicts d'unité, et les deux pièges du balayage

Le classement AST distingue **trois** sortes de dicts, et se tromper de cible est le vrai risque :

| Sorte | Reconnue à | Socle ? |
|---|---|---|
| unité du `game_state` | `id` + `player` + ≥ 4 champs de stats | **oui** |
| config d'entrée moteur | porte `ICON` / `ICON_SCALE` / `ILLUSTRATION_RATIO` | **non** — `create_unit` pose ces champs lui-même |
| figurine (`models`, `models_cache`) | `squad_id`, `role`, `points_per_hp`, `model_id` | **non** — une figurine n'est pas une unité |

Piège mesuré : le premier filtre ne connaissait que `squad_id`/`model_id` et a étalé le socle sur
**10 figurines**, dont 8 n'étaient atteignables qu'en suivant le **flux** (dict affecté à une
variable ensuite placée dans `models_cache`, fabrique `_target_model`, `models_cache[...].update()`).
Sur une figurine, `level`/`orientation` du socle prennent la précédence spec > unité dans
`_build_models_for_unit` : la figurine reste au sol et `models_cache` diverge de `units_cache`.
Les 10 ont été retirées ; le balayage final (clés-marqueurs + flux de variable + fabriques) rend
zéro.

### 8.5 Vérifications, et ce qui ne l'est pas

**Fait :** les 52 fichiers touchés lancés et verts (2 lots) ; `pyright` propre dessus ; chaque
verrou prouvé rouge par mutation puis rétabli — valeur du socle faussée, clé retirée du socle,
champ ajouté au seul `_build_enhanced_unit` — avec `git diff` vide sur `engine/` après coup.

**Non fait / limites :**
- La suite complète appartient à l'utilisateur.
- Le socle d'unité ne couvre que les dicts **littéraux** : une unité fabriquée par copie ou par
  une usine reste hors du balayage, comme au volet 1.
- 231 stubs `{"id", "player"}` passés à des mocks n'ont pas été touchés : ils ne traversent aucune
  lecture `require_key` d'unité.
- **Dette d'altitude, hors périmètre :** `create_unit` et `_build_enhanced_unit` dupliquent leur
  bloc de champs d'état dans `engine/game_state.py`. Une `default_unit_state()` en production
  rendrait le socle *et* son verrou inutiles. C'est un refactor moteur, à décider séparément.
- `_FULL_UNIT_CFG` (config d'entrée de `create_unit`) est recopié à l'identique dans
  `test_morale.py` et `test_socle_invariant.py` : dette préexistante, signalée, non traitée.
