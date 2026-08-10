# Replay — implémentation & registre d'état

> **But.** Source unique sur le replay (rejeu d'un `step.log` d'entraînement/PvP dans l'UI).
> Deux parties : (1) **pipeline & contrat** (comment le log devient une partie rejouable),
> (2) **registre d'état** des chantiers replay ouverts. Le code + git portent le détail ;
> ce doc porte le *contrat* et le *statut franc* (ce qui est vraiment clos vs en l'air).
>
> Faits vérifiés par lecture directe le **2026-07-28** (contre-lecture intégrale du code).
> Les repères sont donnés en **noms de symboles** (greppables), jamais en numéros de ligne :
> ceux-ci se périment en quelques jours.

---

## 1. Pipeline

```
step.log ──parse──> ReplayData ──state N──> BoardReplay ──props──> BoardPvp / UnitRenderer
(moteur)  replayParser.ts   (épisodes,      (ghost, éligibilité,   (rendu PIXI par
                             actions, states) current_player)        figurine)
```

- **Producteur** : moteur (`engine/w40k_core.py`) via `ai/step_logger.py` — mêmes helpers gym↔PvP.
- **Parseur** : `frontend/src/utils/replayParser.ts` → `ReplayData` (épisodes → `actions[]` + `states[]`).
- **Vue** : `frontend/src/components/BoardReplay.tsx` reconstruit un `GameState` par index d'action
  et le passe à `BoardPvp` (même composant que le PvP live) → `UnitRenderer`.

Indexation (`BoardReplay.getCurrentGameState`) : index `0` = état initial ; index `N` = `states[N-1]`
(état **après** l'action `N-1`). `units_cache` est reconstruit à chaque état par `buildUnitsCache`.

---

## 2. Contrat `step.log` (segments & tags)

Le parseur est **strict** : un segment/tag attendu mais absent lève une erreur (pas de fallback).
C'est voulu — une donnée manquante doit crier, pas être masquée.

### 2.1 Positions par figurine (per-figurine)
- `[MODELS: uid#idx@(col,row,z<hauteur>) …]` — positions par socle de l'unité **qui agit** (et du
  déploiement, ligne `Starting position`).
- `[TARGET_MODELS: uid#idx@(col,row,z<hauteur>) …]` — survivants de la **cible** après pertes.
- `z<hauteur>` = hauteur du plancher sous le socle, en POUCES. Consommée par l'**analyzer** (gate
  vertical de l'engagement, §03.04 : 2" horizontal ET 5" vertical), pas par le replay, dont le
  rendu reste plan : `extractModelsSegment` la matche et l'ignore. C'est la hauteur qui est
  journalisée et pas le `level`, parce que la hauteur d'un niveau donné dépend de la POSITION
  (deux ruines peuvent avoir un étage 1 à des hauteurs différentes) et que le step.log ne porte
  aucun terrain : elle ne serait pas re-dérivable.
- Le champ est **obligatoire côté analyzer** (un journal d'archive lève plutôt que d'être lu
  comme un plateau entièrement au sol) et **optionnel côté replay** (un replay d'archive
  s'affiche encore).

Parsés par `extractModelsSegment` → posés sur l'unité via `occupied_hexes_by_model`
(`replayParser.ts` `applyModels` + `initial_models`). Présent → `BoardPvp`/`UnitRenderer` dessinent
**un socle par figurine** ; absent → fallback un socle à l'ancre.

### 2.2 Métadonnées fight
Chaque ligne `FIGHT : … FOUGHT …` porte **uniquement** `[FIGHT_SUBPHASE:…]` (sous-phase V11
pile_in/fight/consolidate ; parsé, requis). **Aucun pool n'est loggué** : le cercle vert en replay
cible la seule unité active, qui est déjà l'**attaquant** de la ligne (`Unit X FOUGHT …`). Le parser
en dérive `fight_eligible_units = [attacker_id]`.

### 2.3 Contrôle d'objectif & points de victoire — **état moteur, jamais recalculé**
Ligne dédiée, écrite **hors action** (elle n'appartient à aucune ligne de jeu) :

```
[hh:mm:ss] T{tour} OBJECTIVE CONTROL: VP1={vp} VP2={vp} CP1={cp} CP2={cp} ZONES={nom}:Ctrl={1|2|none}|{nom}:Ctrl=…
```

- **Producteur** : `StepLogger.log_objective_control_snapshot`, appelé par
  `W40KEngine._log_objective_control_snapshot_if_changed` depuis `_build_observation` — émission
  **à chaque changement** de `objective_controllers`, de `victory_points` **ou** de
  `command_points` (le contrôle bouge à la frontière de phase 14.02, les VP dans les handlers
  `apply_primary_objective_scoring` des phases command/fight, les CP à chaque phase de
  commandement 08.02 : un déclencheur unique en manquerait un). Passe par le **buffer**, comme
  `log_action` : une écriture directe s'intercalerait avant des actions non encore vidées.
- **`CP1=`/`CP2=` sont apparus le 2026-08-04**, entre les VP et `ZONES=`. Les DEUX parseurs de
  cette ligne — `frontend/src/utils/replayParser.ts` et `ai/analyzer_core.py` — les lisent en
  **groupe optionnel** ancré sur `ZONES=` : sans l'optionalité, tout step.log antérieur cesserait
  d'être rejouable et l'analyzer le déclarerait « sans instantané ». Sur ces journaux-là, le champ
  reste **absent** côté replay, jamais rempli d'un `0` — qui mentirait sur le stock de la partie.
  Toute évolution de cette ligne doit bouger les deux parseurs ensemble.
- **Clé de zone** = le **nom**, exactement celui de la ligne `Objectives:` (unique
  `StepLogger._objective_display_name`, partagé par les deux lignes). ⚠️ À ne pas confondre avec le
  récapitulatif de **fin d'épisode** `OBJECTIVE CONTROL: Obj{id}:P1_OC=…` (ni `T{tour}`, ni `VP1=`),
  que le parseur ignore délibérément.
- **Consommation** : `replayParser.ts` horodate chaque instantané par le nombre d'actions déjà lues
  et le pose sur l'état correspondant (`state.objective_control`) ; `BoardReplay.tsx` le lit tel
  quel pour les VP, **les CP** et la coloration des hexes — via le MÊME `UnitStatusTable` que le
  PvP, dont l'en-tête affiche `CP : x` et `VP : x`.
- **Pourquoi c'est journalisé et non recalculé** : le navigateur ne peut reproduire ni l'empreinte
  de socle par figurine (14.02, `sum_objective_control_oc_multi`) ni le battle-shock (01.07 : OC de
  toutes les figurines à `'-'`, 02.02) — ce drapeau n'existe nulle part dans le `step.log`. Le
  calcul local qui vivait dans `BoardReplay` en divergeait : **2 zones sur 5** avaient un
  contrôleur différent du moteur sur l'état final d'une vraie partie mesurée le 2026-07-29.
- **Décision de contrat** : un `step.log` qui déclare des objectifs **sans** aucune ligne
  `OBJECTIVE CONTROL` n'est plus rejouable — le parseur lève et demande la régénération (même règle
  que `FIGHT_ELIGIBLE`, §4.A). Un scénario **sans objectif** n'écrit aucun instantané et reste
  rejouable.

### 2.3bis Tags de règle sur les lignes d'action

Ces tags s'insèrent **entre le verbe et `from`** (mouvements) ou dans la partie dés (tir/combat).
Tout lecteur de `step.log` doit donc accepter un token optionnel à cet endroit — c'est la source
d'un défaut déjà payé trois fois : un aiguillage écrit sur la chaîne littérale `"<VERBE> from"`
laisse la ligne **sans branche**, l'action n'est pas traitée, la position de l'unité reste figée,
et toutes les adjacences calculées ensuite le sont contre un fantôme. Côté analyzer la grammaire
est centralisée dans `ai/analyzer_core.move_line_re` : un nouveau tag n'a qu'un endroit à toucher.

| Tag | Lignes concernées | Règle | Producteur |
|---|---|---|---|
| `[FLY]` | `MOVED` / `FLED` / `ADVANCED` / `CHARGED` | 21.03 — vol **déclaré** (« take to the skies »), pas le keyword | **`w40k_core`, branches `squad_*_move` ET `squad_charge`** (les deux seuls producteurs du gym), `movement_handlers` (2 sites PvP), `charge_handlers` (2 sites PvP) |
| `[SUSTAINED HITS]` | `SHOOT` et `FIGHT`, sur la ligne `Hit None(…)` | 24.36 — touche **additionnelle**, pas une attaque | `attack_sequence` (`sustainedHit`) → `_SHOT_RECORD_FIELD_MAP` |
| `[RAPID FIRE:X]`, `[HEAVY]`, `[COVER]`, `Save [DEVASTATING WOUNDS]` | `SHOOT` | 24.30 / 24.16 / 13.08 / 24.10 | idem |

Le `[FLY]` porte une **déclaration**, jamais une capacité : une unité volante qui n'a pas déclaré
marche, paie les murs et doit être contrôlée comme de l'infanterie. Exempter sur le keyword du
registre désarmerait le contrôle. La charge peut porter **deux** tags (nom de la règle de relance
+ `[FLY]`) : les regex utilisent `*`, pas `?`.

`[SUSTAINED HITS]` est la **seule** trace exploitable d'une touche additionnelle : elle n'a pas de
jet (`Hit None`), donc rien ne la distingue autrement d'une ligne malformée. Sans elle, l'analyzer
la comptait dans le plafond de tirs (`shoot_over_rng_nb` / `fight_over_cc_nb`) et affichait
simultanément la règle « NOT USED ».


#### Le champ `turn` des lignes de phase de combat — corrigé le 2026-08-04

`_append_fight_move_log` (émetteur UNIQUE de `PILED IN` et `CONSOLIDATED`, gym **et** PvP) lisait
`game_state["current_turn"]`, une clé qui n'existe dans **aucun** `game_state` de ce moteur — le
compteur s'appelle `turn` — avec un repli silencieux sur `1`. Les **1521** lignes `CONSOLIDATED`
d'un run de 600 épisodes étaient donc toutes datées `T1`, quel que soit le round.

Le repli est exactement la valeur par défaut anti-erreur que CLAUDE.md T1 interdit : c'est lui qui
a rendu le défaut invisible. Le contrat est désormais `require_key(game_state, "turn")` — absence
= erreur explicite. Onze sites portaient le même motif (`charge_handlers`, `movement_handlers`,
`fight_handlers`), tous corrigés.

~~⚠️ **Observation non expliquée au 2026-08-04** : ce même run ne contient **aucune** ligne
`PILED IN` pour 1521 `CONSOLIDATED`~~ — **EXPLIQUÉ ET CORRIGÉ le 2026-08-09**, cf. §2.3sexies :
les trois sites `advance_phase` appelaient `_process_squad_action` sans **drainer** ses
`action_logs`, or c'est cette transition qui déclenche le PILE IN groupé (12.02). La sonde du
2026-08-04 ne mentait pas — le gym émettait bien les deux action_logs `pile_in` ; ils étaient
jetés entre l'émission et le journal. Les trois sites passent par `_advance_phase_and_drain`.

**Re-mesuré le 2026-08-10** sur un `step.log` en cours d'écriture (run vivant, instantané à
5 026 lignes) : **6** lignes `PILED IN` pour **3** `CONSOLIDATED`, réparties sur 2 épisodes et
3 tours (`E12 T3`, `E22 T4/T5`), toutes avec un `T` juste. Le rapport ~2:1 est celui qu'on attend :
le pile-in groupé concerne toutes les unités engagées, la consolidation seulement celles qui ont
combattu. Le pile-in est donc de nouveau une position de référence utilisable, et le contrôle
« pile-in au-delà de 3" » de l'analyzer
(`ai/analyzer_phases/fight_handler.py`, budget `3 × inches_to_subhex`) **n'est plus un VERT
VACANT** : il voit des lignes.
⚠️ Ce qui n'est PAS mesuré ici : son **taux de violation**. Savoir qu'un contrôle reçoit des
données ne dit pas qu'il juge juste — il faut passer l'analyzer sur un journal **terminé** (pas
sur celui d'un run en cours, dont le résultat n'est pas reproductible).

### 2.3ter Move réactif

```
[hh:mm:ss] E{ep} T{tour} P{j} MOVE : Unit X(c,r) REACTIVE MOVED [<ABILITÉ>] from (c,r) to (c,r) [Roll: N] - trigger: Unit Y->(c,r)
```

**Journalisée sans consommer de step gym.** Le move réactif est *déclenché* par le déplacement
adverse, pas choisi par l'agent : l'entête du journal liste les actions qui incrémentent (move,
shoot, charge, combat, wait). Il est donc émis avec `step_increment=False`
(`W40KEngine._STEP_LOG_NON_INCREMENTING_TYPES`) — le compter décalerait `total_actions` et le
compte de steps de tous les épisodes sans qu'aucune décision supplémentaire n'ait été prise.

`[Roll: N]` est en **pouces**, comme le jet d'advance et le jet de charge : tout consommateur doit
le convertir (× `inches_to_subhex`) avant de le comparer à une distance de grille.

### 2.3quater Règles du run

```
[hh:mm:ss] Run rules: engagement_zone_subhex=… metric.engagement=… metric.ranged=… move.thru_ez=… move.thru_enemy=… move.thru_friendly=…
```

Les valeurs de règle que le moteur a **réellement appliquées**. Elles vivent dans
`config/game_config.json`, qu'on édite entre deux runs : les relire au moment de l'analyse, c'est
juger un vieux journal avec les règles du jour. Basculer `distance_metric.engagement` de `hex` à
`euclidean` changerait tous les verdicts d'engagement d'hier — sans le moindre signe, là où
l'échelle est protégée par un refus explicite depuis §2.4.

`engagement_zone_subhex` est **déjà en subhexes** : le moteur convertit au chargement et
journalise ce qu'il applique, donc le consommateur n'a aucune conversion à refaire — et aucune
occasion de diverger.

Contrat identique à celui de `Board:` : ligne absente → l'analyzer refuse d'analyser. Les
journaux produits avant cette ligne ne sont plus analysables, et c'est voulu.

### 2.3quinquies Instantané d'ÉTAT — le point de recalage (2026-08-09)

```
[hh:mm:ss] T{tour} STATE: {uid}[{mid}@({col},{row},z{hauteur}):{pv} …] {uid}[…] …
```

Une ligne par **tour**, écrite au même point de passage que `OBJECTIVE CONTROL` (le seul commun
aux 7 sites de construction d'observation, donc le seul où chaque tour est vu exactement une
fois). Source : `occupied_hexes_by_model` / `floor_height_by_model` de `units_cache` et `HP_CUR`
de `models_cache` — **la même** que le segment `[MODELS:]` des lignes d'action.

**Pourquoi.** Tout lecteur du journal reconstruit l'état par ACCUMULATION : PV initial moins
chaque `Dmg:`, position initiale plus chaque déplacement. Il n'existait aucun point de
correction, donc une donnée manquante dérivait jusqu'à la fin de l'épisode. Mesuré sur le run de
600 épisodes du 2026-08-08 :

- **546 lignes** portent une sauvegarde ratée SANS segment `Dmg:` — la blessure est écartée faute
  de figurine à qui l'allouer (la cible est morte en cours de lot), donc la mort n'est dite nulle
  part. Conséquence : 76 « action sur une unité morte » et 15 « Missing unit_hp on damage »,
  tous mesurés contre des fantômes ;
- **229 chargeurs sur 319** changent de position entre leur ligne de charge et leur ligne de
  combat sans qu'aucune ligne ne l'explique (cf. le pile-in muet, §2.3sexies).

Une unité **sans figurine vivante est absente** de la ligne : l'absence EST la mort, il n'y a
donc aucun drapeau vivant/mort à accorder avec les positions. Une unité en réserves (20.01) est
absente pour la même raison, et n'est pas un fantôme — le consommateur ne compte l'écart que
s'il connaissait déjà des socles à cette unité.

Côté analyzer : l'écart est **compté avant d'être corrigé** (section `2.8 État reconstruit vs
état moteur`, trois compteurs — fantômes, unités tuées à tort, positions). Une correction muette
ferait disparaître le symptôme sans jamais signaler sa cause, et le prochain effet non
journalisé repasserait inaperçu.

### 2.3sexies Datasheet par figurine, `PILED IN`, `[WAAAGH!]` (2026-08-09)

**`[MODEL_TYPES: {mid}={UnitType} …]`** — ajouté aux lignes `Unit … Starting position …` de
l'entête d'épisode. Une escouade n'est pas homogène : la règle 19 y replie un personnage COMME
figurine, et le roster y met sergents et armes spéciales. Cinq armes distinctes s'appellent
« Close Combat Weapon » (NB de 2 à 6) : le nom d'affichage ne tranche pas, seul le type de la
FIGURINE le fait. Écrit une seule fois — une figurine meurt, elle ne change pas de datasheet.

**`PILED IN`** — la ligne existait, son émetteur aussi, mais elle n'atteignait jamais le journal :
les trois sites `advance_phase` (« pool_empty ») appelaient `_process_squad_action` **sans
drainer** ses `action_logs`, alors que cette transition déclenche `fight_phase_start` puis tout
le PILE IN groupé (12.02). Mesuré : **zéro** ligne `PILED IN` dans 22 Mo, pour 203
`CONSOLIDATED` — la consolidation, elle, naît pendant `squad_fight`, donc dans la fenêtre.
Instrumentation : plan calculé 24 fois (jamais `None`), commité 24 fois, action_log appendu
24 fois, **drainé 0 fois**. Les trois sites passent désormais par `_advance_phase_and_drain`.

**`[WAAAGH!]`** — token posé entre `FOUGHT` et la cible, même grammaire que `CHARGED`. La règle
ajoute 1 à la Force ET aux Attaques des armes de mêlée ; le moteur appliquait les deux sans le
dire, si bien qu'un WarTrakk (Choppa NB=5) portait 6 attaques et que le plafond recalculé par
l'analyzer était inférieur d'un cran. ⚠️ Les lecteurs à grammaire rigide doivent tolérer le
token : `ai/analyzer_phases/fight_handler.py` et `ai/hidden_action_finder.py` ont été alignés sur
`replay_converter._ABILITY`. Une ligne non reconnue échappe à TOUS les contrôles de combat sans
lever la moindre erreur.

**`AGENT_PLAYER={1|2}`** — ajouté à la ligne `Rosters:`. `controlled_player_mode` accepte `p2` et
`random` (`agent_seat_mode` du training config vaut `random`) : l'agent ne tient pas toujours le
siège P1. Mesuré sur le run du 2026-08-08 — agent en P2 dans **180 épisodes sur 600**, et
l'analyzer, qui écrivait « Agent (P1) » en dur, y comptait ses victoires dans la colonne du bot :
**33,3 % affichés pour 45,3 % réels**. `bot_evaluation` (donc le gating, qui lit
`results["control"]`) attribuait déjà juste ; l'analyzer était le seul consommateur sans la donnée.

### 2.3septies Effets de règle EN VIGUEUR (2026-08-09)

```
[hh:mm:ss] T{tour} EFFECTS: P1 oath_target=104 oath_wound=+1 | P2 waaagh=on waaagh_melee_str=+1 waaagh_melee_atk=+1 waaagh_invul=5
```

Une capacité de faction (Waaagh! 24, Oath of Moment 08.04) est vraie pour une **armée pendant un
tour** — pas pour une attaque. Elle était pourtant recopiée en token sur chaque ligne de mêlée,
puis re-dérivée par expression régulière chez trois lecteurs, et Oath l'était une **seconde**
fois, indépendamment, sur les lignes de charge.

Trois choses que cette ligne ferme :

1. **La grammaire des lignes d'attaque cesse de bouger pour une capacité.** Poser `[WAAAGH!]`
   entre le verbe et la cible avait cassé QUATRE grammaires de lecteurs, dont deux rattrapées par
   un code-review — chacune échouant en silence (la ligne n'est pas rejetée, elle est *ignorée*).
2. **Le lecteur ne ré-encode plus la règle.** Le nom seul obligeait l'analyzer à savoir que
   « waaagh ⇒ +1 » : deux définitions d'une même règle, la seconde divergeant en silence le jour
   où `WAAAGH_MELEE_BONUS` bouge. La ligne porte la **contribution appliquée**, exactement comme
   `Run rules:` porte la zone d'engagement réellement utilisée. C'est une déclaration d'ÉTAT,
   jamais un verdict : le lecteur recalcule et compare.
3. **Le +1 Force devient attribuable.** Il n'était représenté nulle part : un seuil de blessure
   amélioré restait inexplicable pour tout contrôle futur.

⚠️ **Émise au CHANGEMENT, pas à la frontière de tour.** Le Waaagh se déclare en phase de
commandement, donc *au milieu* du tour : une ligne écrite une fois par tour dirait « inactif » et
ne serait jamais corrigée. Mesuré en remettant ce défaut : la déclaration devient totalement
muette (une seule ligne, `P2 none`). Même déclencheur, et pour la même raison, que
`log_objective_control_snapshot` — dont les VP bougent eux aussi dans les handlers.

Un joueur sans effet est écrit `P{n} none` : l'absence est **dite**, et ne se confond pas avec une
ligne tronquée. Le token `[WAAAGH!]` reste sur les lignes d'attaque comme confort de lecture — ce
n'est plus la donnée.

### 2.4 Décor : ce que le journal ne porte PAS, et comment le replay le retrouve

`Walls:` (hexes) et `Objectives:` sont journalisés. **Terrain, icônes, zones de déploiement et
segments de murs ne le sont pas** : le replay les relit dans la config via
`GET /api/config/board`. Deux paramètres décident de ce qu'il obtient, et tous deux viennent du
journal :

```
[hh:mm:ss] Board: cols=… rows=… inches_to_subhex=… hex_radius=… margin=…
[hh:mm:ss] Scenario file: config/agents/<Agent>/scenarios/training/scenario_bot-02.json
```

- **Résolution** (`inches_to_subhex`) → paramètre `inches_to_subhex` de la requête, transmis **tel
  quel**. Le navigateur ne traduit rien : les dossiers de plateau ne sont connus que de
  `BOARD_DIR_BY_INCHES_TO_SUBHEX` (`config_loader.py`), source unique partagée avec
  `ai/train.py --resolution`. Sans ce paramètre, l'API sert le plateau par **défaut** : sur un
  replay x1 le décor arrivait en coordonnées x5 (sommets jusqu'à `(220, 270)` sur une grille
  44×60) et se dessinait cinq fois trop loin. Résolution inconnue → erreur de l'API, affichée
  comme n'importe quel échec de configuration ; jamais de repli sur le plateau par défaut, qui
  ramènerait le mauvais décor en silence. `board_path` (surnom d'écran des modes de test) reste
  accepté, mais les deux paramètres sont exclusifs.
  **Le retour est confronté à la demande** (`useGameConfig.ts`) : une config servie dans une autre
  résolution que celle demandée devient une erreur de configuration, jamais un plateau dessiné. Ce
  contrôle vit dans le hook parce que c'est le seul endroit où la requête et sa réponse coexistent —
  le consommateur, qui fusionne le décor servi avec la grille du journal, ne verrait qu'une config
  sans savoir pour quelle demande elle a été produite, et dessinerait l'hybride sans rien signaler
  (décor cinq fois trop grand, murs et unités justes). Verrou : `useGameConfig.test.ts`.
- **Scénario tiré** (`Scenario file:`, chemin relatif à la racine du dépôt) → `scenario_file` de la
  même requête. Indispensable parce qu'un entraînement tire un scénario **par épisode** : la ligne
  `Scenario:` vaut alors « Random from N scenarios », qui ne désigne aucun fichier. Produit par
  `W40KEngine.reset` (conversion en relatif ; hors dépôt → erreur) et
  `StepLogger.log_episode_start(scenario_path=…)`.
- **Contrat, à la différence de `FIGHT_ELIGIBLE` / `OBJECTIVE CONTROL`** : `Scenario file:` absent
  ne rend pas le journal irrejouable — le replay retombe sur le scénario par défaut, exactement ce
  qu'il faisait pour tous avant cette ligne. Le décor peut alors être celui d'un autre scénario.
- **Limite assumée** : le décor reste lu dans les fichiers de config **actuels**. Réécrire un
  `terrain-*.json` change le décor des replays passés. L'alternative (dumper le terrain rasterisé
  dans le journal) coûte 175 Ko par épisode en x5 — mesuré sur `terrain-mc1.json`, 15 288 hexes —
  et a été écartée pour ça.
- **Échelle du décor.** Deux familles, deux règles. Ce qui a une taille de TABLE (icônes de
  terrain, épaisseur des murs) se dessine en **pouces** et garde la même taille à l'écran quelle
  que soit la résolution : `hex_radius × inches_to_subhex` = pixels par pouce, constant (13,90 sur
  les plateaux 44×60). Ce qui a une taille de CASE suit la case. L'erreur corrigée était de traiter
  les premières comme les secondes : `icons[].size` était multiplié par le rapport dans
  `_downscale_terrain_data`, et les murs se dessinaient sur `HEX_RADIUS` / `HEX_HEIGHT` — un mur
  x1 faisait 27,8 px d'épaisseur contre 5,6 px en x5, pour le même mur. Constantes de rendu :
  `WALL_DOT_RADIUS_INCHES` et `WALL_SEGMENT_HALF_WIDTH_INCHES` (`BoardDisplay.tsx`), calées sur
  les valeurs que le rendu x5 produisait — celui-ci est inchangé au pixel près.
- **Verrous** : `tests/unit/engine/test_engine_reset.py::TestResetLogsScenarioPath` (relatif,
  refus hors dépôt, absence de ligne sans scénario), `test_step_logger.py`
  (`…writes_scenario_path`), `replayParser.test.ts` (extraction, non-confusion avec `Scenario:`,
  journal ancien).

> **Historique.** Avant : `[CHARGING_POOL] [ACTIVE_ALT_POOL] [NON_ACTIVE_ALT_POOL]` (pools V10, vides)
> → pool vide en replay → pas de cercle vert. Un jet intermédiaire a loggué le pool V11 complet
> (`[FIGHT_ELIGIBLE:…]`), mais il éclairait **toutes** les unités activables. Choix produit retenu :
> **seule l'unité activée** est cerclée → on ne loggue plus de pool, on dérive de l'attaquant.

---

## 3. Rendu & éligibilité (cercle vert)

Le « cercle vert autour des figs » = anneau d'**éligibilité** (`UnitRenderer.renderGreenActivationCircle`,
appelé par figurine si `isEligible && !figGhost`). L'éligibilité vient de `BoardPvp`
(`isEligibleForRenderingBase`) :

**Règle produit : le cercle vert cible UNIQUEMENT l'unité active** (celle qui joue l'action courante),
dans **toutes** les phases. `BoardReplay` restreint donc `eligibleUnitIds = [replayActiveUnitId]`
(id selon le type d'action : `shooter_id` pour shoot, `attacker_id` pour fight, `unit_id` sinon ;
`[]` si aucune action). Voir `replayActiveUnitId` dans `BoardReplay.tsx`.

| Phase | Source d'éligibilité en replay | Cercle vert |
|---|---|---|
| move / charge / advance / shoot | `eligibleUnitIds = [replayActiveUnitId]` filtré par `current_player` | ✅ unité active seule |
| **fight** (`FOUGHT`) | `gameState.fight_eligible_units = [attacker_id]` (branche fight de BoardPvp, §4.A) | ✅ unité active seule |
| **fight** (`pile_in`/`consolidation`) | classé `phase="fight"` (§4.C) → `fight_eligible_units = [unit_id]` (l'unité qui bouge) | ✅ unité active seule |

`current_player` en replay = `action.player` pour les actions move/shoot/charge/fight
(`BoardReplay.replayCurrentPlayer`), sinon `state.current_player`.

Le rendu per-figurine (occupied_hexes_by_model) ne change pas quelle **unité** est éligible — il
multiplie les socles. Le cercle vert se dessine par figurine, aux mêmes centres que les socles.

**Restriction par-figurine (tir/combat).** Une action de tir/combat ne fait souvent agir qu'une
partie de l'escouade (ex. le Nob et son Kombi Rokkit). Le moteur loggue les figs ayant réellement
tiré/frappé via le segment `[SHOOTER_MODELS: <mid> …]` (émis par `_emit_squad_shoot_log` →
`shooterModels`, source = `attacker_mid` par-modèle, PAS un match par nom d'arme). Chaîne de bout
en bout :

- **Backend** : `shared_utils._emit_squad_shoot_log` (champ `shooterModels`) →
  `w40k_core._build_shot_details` (`shooter_models_segment` via
  `action_log_utils.format_shooter_models_segment`) → `ai/step_logger` l'ajoute à la ligne.
  Le regex analyzer `\[MODELS:` ne matche pas `\[SHOOTER_MODELS:` → aucun impact analyzer.
- **Parser** : `replayParser.extractShooterModelsSegment` → `action.shooter_models` (ids seuls ;
  positions déjà dans `[MODELS:]`).
- **Rendu** : `BoardReplay.replayActiveModelIdsByUnit` → prop `BoardPvp.activeModelIdsByUnit` →
  `UnitRenderer.eligibleModelIds` : le cercle vert n'entoure QUE ces figs (absent → toute
  l'escouade éligible, comportement historique).
- **Cône LoS (tir)** : `restrictShooterCentersToActive` restreint la source du cône aux figs
  tireuses, et `BoardReplay.replayActiveShootRangeByUnit` remplace la portée max d'escouade par la
  portée de l'arme réellement tirée → le cône colle à l'arme de la fig. Une arme SPÉCIALE (ex. Kombi
  Rokkit du Nob, 24") vit sur le type de la figurine porteuse, PAS sur l'unité de base (Boyz, Shoota
  18") : la portée vient donc de `UnitFactory.getRangedWeaponRangeByDisplayName` (scan global de
  TOUTES les classes d'unités par `display_name`, en pouces) × `inches_to_subhex`, pas de
  `unit.RNG_WEAPONS`. Hors replay (props absentes), le PvP live est inchangé.

---

## 3bis. Colonne droite : gabarit partagé PvP / PvP test / replay

`SharedLayout` rend la colonne droite en **deux emplacements**, et c'est ce découpage — non une
convention de rédaction du JSX — qui garantit la barre de défilement du Game Log :

| Emplacement | Contenu | Comportement |
|---|---|---|
| `rightColumnContent` | tracker, contrôles, barres d'action, **bloc illustration + Game Log** | hauteur fixe, jamais comprimé (`.game-log-with-illustration { flex-shrink: 0 }`) |
| `rightColumnScrollableContent` | les deux `UnitStatusTable` | SEULE zone qui absorbe le manque de place — `SharedLayout` l'enveloppe lui-même dans `.unit-status-tables__scroll` |

**En-tête de joueur — `CP : x` et `VP : x` (2026-08-04).** Les deux compteurs de partie vivent
dans le MÊME en-tête d'`UnitStatusTable`, donc au même endroit en PvP et en replay : le composant
est déjà partagé, et un second conteneur qui les répéterait ferait deux affichages à maintenir de
la même valeur. En replay les CP viennent de l'instantané `OBJECTIVE CONTROL` (§2.3) ; ils sont
**absents** — pas à zéro — sur un journal enregistré avant que le moteur ne les écrive.

**Pourquoi.** C'est l'illustration (hauteur fixe, 280 px) qui donne sa hauteur au Game Log. Sans
elle, le log grandissait avec son contenu et débordait de `.unit-status-tables` : les lignes
anciennes sortaient de la fenêtre **sans aucune barre pour y revenir**. Le replay n'avait ni le
panneau d'illustration, ni la zone défilante — d'où le défaut, absent du PvP. Sur fenêtre très
courte, `.unit-status-tables` défile elle-même (`overflow-y: auto`, `overflow-x: hidden`) plutôt
que de rogner son bas en silence.

**Unité illustrée.** En replay, c'est **l'unité active de l'étape courante**, dérivée du même
`replayActiveUnitId` que le cercle vert (§3) : les deux ne peuvent pas désigner des unités
différentes. En PvP, elle suit le survol / l'épinglage / la figurine inspectée. Le composant
partagé `GameLogWithIllustration` ne décide de rien : il reçoit l'unité et ne gère que la
présentation (préchargement, fondu enchaîné, replis).

**Replis du visuel**, dans l'ordre : `/icons/<type>.png` → champ `ICON` de la datasheet (26 unités
n'ont leur visuel que sous cette extension) → **initiale du `type` sur fond blanc**, avec un
`console.error` nommant l'unité et les chemins tentés. Sur les 161 classes de roster : 57 ont leur
`.png`, 26 sont récupérées par `ICON`, 78 n'ont aucun visuel et affichent l'initiale. L'image
générique *Endless duty* ne sert plus qu'au cas « aucune unité sélectionnée ».

**Échelle de l'illustration** = `ILLUSTRATION_RATIO` de la datasheet, et rien d'autre. `BASE_SIZE`
n'y entre PAS : c'est l'empreinte de la figurine sur le plateau, déjà convertie en cellules
(`_scale_socle` moteur, `scaleBaseSize` replay), donc dépendante de la résolution — la même unité
n'aurait pas la même illustration selon le plateau chargé.

**Confinement.** Le panneau est un composant enfant d'une `ErrorBoundary` **clée sur l'unité** : le
JSX en ligne aurait été évalué dans le rendu du parent, donc hors de portée du boundary. Une unité
dont le registre ne donne pas l'`ILLUSTRATION_RATIO` dégrade le seul panneau, jamais le Game Log,
et l'échec ne survit pas au changement d'unité.

**Reste :** confirmation visuelle browser (fondu, replis, défilement sur fenêtre courte).

---

## 3ter. Sauvegardes PvP : nom de fichier, libellé de point, format

- **Nom de fichier d'une partie** : `aaaammjj_hh-mm` (ex. `20260712_14-30`), dérivé de
  l'horodatage du premier point (`game_saves._party_name_from_point_ts`). ⚠️ Le séparateur est
  un tiret et **doit le rester** : `:` est interdit dans un nom de fichier Windows, et le garde
  du module (`_FORBIDDEN_NAME_CHARS`) le rejette avant d'écrire.
- **Libellé d'un point de reprise** : `T{tour}P{joueur}{Ph}` (+ `#{activation}` pour les saves
  manuelles, + la note du joueur). La phase tient sur **DEUX** lettres — `De`, `Cd`, `Mv`, `Sh`,
  `Ch`, `Ft` — parce que `command` et `charge` partagent leur initiale : un point de reprise
  ambigu se paie exactement au moment où l'on cherche le bon. Le `#` sépare plusieurs saves
  manuelles tombées dans la même phase du même tour ; sans lui elles portent toutes le même nom.
  Construit **uniquement** par `SnapshotRewind.saveDisplayName`, depuis `turn`/`player`/`phase`/
  `episode_steps`. Le backend ne renvoie plus de champ `label` : il en existait un, transmis et
  typé côté front, que rien n'affichait (retiré le 2026-08-04).
- **Format de fichier** : en-tête magique `W40KTL03`. `TL01` (sans empreinte de scénario) et
  `TL02` (sans les points de commandement de la règle 08.02) sont **refusés explicitement** au
  chargement : leur état ne peut pas être restauré dans le moteur courant — TL02 rendrait un
  `game_state` sans `command_points`, qui planterait à la phase de commandement suivante. Le
  refus nomme le format et invite à rejouer la partie ; il n'y a pas de migration.

## 4. Registre d'état des chantiers replay

| # | Chantier | État | Prochaine action |
|---|---|---|---|
| A | Cercle vert en **phase fight** | **fait — validé unit + tsc ; visuel browser à confirmer** | Confirmer le cercle vert en fight dans un replay (§4.A) |
| B | Purge legacy pools V10 du `game_state` | **fait moteur (2026-07-23), fait front (2026-08-10)** — 0 hit des 5 sous-phases V10 et des 3 champs, front comme backend ; tsc + biome propres | Confirmer l'auto-play IA en phase fight dans une session PvP réelle : le fix **change** son comportement (§4.B) |
| C | `pile_in` / `consolidation` classés en **phase `move`** | **fait (2026-07-23)** | — |
| — | Replay per-figurine (segments MODELS/TARGET_MODELS) | **fait** (commits `81e56c35`, `4ea850c3`) | — |
| — | Détail par-figurine (bouton +) move/advance/charge/reactive | **fait** (`4ea850c3`) | — |
| D | Contrôle d'objectif & VP lus du moteur (fin du recalcul navigateur) | **fait (2026-07-29)** — unit + vitest + tsc + run réel ; visuel browser à confirmer | Confirmer VP et coloration des zones dans un replay (§4.D). ~~**jumeau restant** : `ai/analyzer_core.py` recalcule encore à l'ancre~~ — **PÉRIMÉ, le jumeau est traité** (§4.D dernier bloc) : revérifié le 2026-08-08, `analyzer_core` ne reconstruit plus rien, il lit la ligne `OBJECTIVE CONTROL:` |

### 4.A — Cercle vert fight ✅ FAIT (2026-07-23)
**Décision produit (finale).** En replay fight, le cercle vert cible **UNIQUEMENT l'unité activée**
(celle qui frappe), pas le pool des unités activables. L'unité active EST l'attaquant de la ligne
`FOUGHT` → on ne loggue aucun pool, le parser pose `fight_eligible_units = [attacker_id]`.

**Implémenté (état final) :**
1. `ai/step_logger.py` (bloc combat) : émet `[FIGHT_SUBPHASE:…]` seul (contrat = fight_subphase requis).
   Aucun pool. 3 tags legacy V10 retirés.
2. `engine/w40k_core.py` : `_pre_action_fight_state` capture `{ fight_subphase }` (pré-action, pour la
   sous-phase où l'action a lieu) ; 2 sites par-attaque posent `attack_details["fight_subphase"]` seul.
3. `frontend/src/utils/replayParser.ts` : parse `FIGHT_SUBPHASE` ; `fightStateFields =
   { fight_subphase, fight_eligible_units: [attacker_id] }`. `parsePoolTag` et le champ pool supprimés.
4. `frontend/src/components/BoardReplay.tsx` : champs pool retirés de l'interface locale.
5. Tests : `test_step_logger.py` (contrat subphase + « émet FIGHT_SUBPHASE seul, aucun pool ») ;
   `replayParser.test.ts` (fight → `fight_eligible_units === [attacker]`).

**Validation (2026-07-23).** pytest step_logger + fight_execution vert ; vitest 4/4 ; tsc propre ;
run réel : 205 lignes FOUGHT, toutes `[FIGHT_SUBPHASE]`, **0 FIGHT_ELIGIBLE**, 0 « Step logging error ».
**Reste :** confirmation visuelle browser.

> Le détail ci-dessous documente le jet intermédiaire (pool complet) conservé pour mémoire des pièges.

#### Jet intermédiaire (pool complet) — abandonné
**Cause racine.** Le pool d'activation V11 = `fight_eligible_units` (écrit par `fight_handlers.py`).
Le PvP live le lit (`BoardPvp.isEligibleForRenderingBase`). Mais `step_logger` logguait
encore les 3 pools V10 (vides) et **jamais** `fight_eligible_units` → pool `[]` en replay → pas de
cercle vert en fight.

**Correction de source vs plan initial (2 pièges découverts).**
- **Champ, pas recalcul.** Le PvP live affiche `game_state["fight_eligible_units"]` (champ maintenu).
  On loggue ce champ, pas `fight_v11_current_pool()` (le `result` combat ne le porte pas toujours).
- **Capture PRÉ-action.** L'action MUTE le pool (`end_activation` retire l'unité active). Le lire au
  drain (post-action) donnerait l'état d'après. Le chemin squad capturait déjà les pools V10 en
  pré-action (`_pre_action_fight_state`, `w40k_core.py` step()) — c'est LÀ qu'il faut poser
  `fight_eligible_units`, pas au point de log.
- **Piège swallow.** `StepLogger.log_action` avale les exceptions du formateur (`print` puis rien).
  Un premier jet qui logguait `fight_eligible_units` au mauvais endroit faisait **throw** le formateur
  → **toutes les lignes FOUGHT disparaissaient silencieusement** (log avec pile_in/consolidation mais
  0 combat). Vérifier `grep "Step logging error"` sur le run.

**Implémenté :**
1. `engine/w40k_core.py` — `_pre_action_fight_state` (step(), chemin squad V11 T6) : capture
   `{ fight_subphase, fight_eligible_units }` (pré-action) au lieu des 3 pools V10 ; injecté au
   formateur via `_build_shot_details` (`details.update(fight_state)`).
2. ~~`engine/w40k_core.py` — 2 sites par-attaque de `_process_semantic_action` (chemin PvE/legacy, hors
   training) : `attack_details["fight_eligible_units"] = list(require_key(self.game_state, …))`
   (pool intact à ce point, avant `end_activation`).~~
   **Supprimé le 2026-07-29** : ces 2 sites étaient dans le bloc `step_logger` de
   `_process_semantic_action`, prouvé inatteignable (aucun appelant de `execute_semantic_action`
   n'assigne de StepLogger). Seul le point 1 alimente réellement le replay.
3. `ai/step_logger.py` (bloc combat) : émet `[FIGHT_SUBPHASE:…] [FIGHT_ELIGIBLE:…]` (contrat strict) ;
   3 tags legacy retirés.
4. `frontend/src/utils/replayParser.ts` : parse `FIGHT_ELIGIBLE` → `action.fight_eligible_units` ;
   `fightStateFields = { fight_subphase, fight_eligible_units }` ; 3 champs pools retirés de l'interface.
5. `frontend/src/components/BoardReplay.tsx` : 3 champs pools retirés de l'interface locale.
6. Tests : `tests/unit/ai/test_step_logger.py` (3 cas : contrat subphase, contrat eligible, tag émis) +
   cas fight dans `frontend/src/utils/replayParser.test.ts` (+ bloc `Board:` manquant réparé).

**Sémantique du pool (conforme PvP).** Le vert suit `fight_eligible_units` = pool d'activation V11
(alternance fights-first). Il peut **exclure l'unité qui frappe** (ex. `Unit 5 FOUGHT … [FIGHT_ELIGIBLE:
102,103,104]`) : c'est le comportement PvP, où `BoardPvp` supprime même le vert sur l'unité active en
cours d'activation (`suppressFightActiveEligibleGreen`). Le vert éclaire les unités sélectionnables pour l'activation suivante.

**Décision de contrat.** Un ancien `step.log` (sans `FIGHT_ELIGIBLE`) n'est plus rejouable →
**régénérer les logs** (conforme : donnée manquante = erreur explicite, pas de fallback).

**Validation (2026-07-23).** `pytest` step_logger + fight_execution vert ; run réel `--step` :
236 lignes FOUGHT, **toutes** avec `[FIGHT_ELIGIBLE:…]` non vide, 0 vide, 0 « Step logging error » ;
`vitest replayParser` 4/4 ; `tsc` propre. **Reste :** confirmer visuellement le cercle vert en fight
dans un replay browser (le `step.log` régénéré le permet).

### 4.D — Contrôle d'objectif & VP : lus du moteur ✅ FAIT (2026-07-29)
**Défaut.** `BoardReplay.tsx` portait **deux** `useMemo` qui resommaient l'OC dans le navigateur
(points de victoire *et* coloration des hexes). Quatre divergences avec le moteur, dont deux
irrattrapables côté client : somme par **ancre** au lieu de l'empreinte de socle ; **battle-shock**
(01.07) absent du `step.log` ; **moment d'évaluation** (le contrôle est figé en fin de phase/tour,
14.02, pas à la 1ʳᵉ action d'un couple joueur/tour) ; **barème de scoring** ré-implémenté alors que
`StateManager.apply_primary_objective_scoring` fait foi. Mesuré sur une vraie partie : 2 zones sur 5
avec un contrôleur différent.

**Implémenté :**
1. `ai/step_logger.py` : `log_objective_control_snapshot` (format §2.3) + `_objective_display_name`
   factorisé avec la ligne `Objectives:` — une seule règle de clé pour les deux lignes.
2. `engine/w40k_core.py` : `_log_objective_control_snapshot_if_changed`, appelé dans
   `_build_observation` juste après `refresh_objective_control_on_boundary`.
3. `engine/w40k_core.py` (`reset`) : purge de `_objective_control_last_boundary` — **défaut jumeau
   trouvé en chemin**, la frontière de l'épisode précédent (`fight`, T5) déclenchait un checkpoint
   14.02 au premier build d'obs du nouvel épisode, figeant des contrôleurs avant toute fin de phase.
   Purge aussi du mémo d'écriture, sinon l'instantané initial du nouvel épisode sautait.
4. `frontend/src/utils/replayParser.ts` : parse, horodate par nombre d'actions lues, pose sur
   `state.objective_control` ; **rejette** un journal à objectifs sans instantané.
5. `frontend/src/components/BoardReplay.tsx` : les deux `useMemo` supprimés (−440 lignes), lecture
   directe de l'instantané.
6. Verrous : `test_step_logger.py` (format, parité de clé, contrôleur inattendu, passage par le
   buffer), `test_squad_step_logging.py` (émission sur changement, déduplication, no-op),
   `test_engine_step.py` (purges d'épisode), `replayParser.test.ts` (attachement timeline,
   récapitulatif de fin ignoré, zone malformée, rejet d'un journal périmé).

**Validation (2026-07-29).** pytest des 4 fichiers touchés vert, pyright 0 erreur, vitest 11/11,
tsc + biome propres ; run réel headless (ArmageddonAgent, épisode complet) → 10 lignes
`OBJECTIVE CONTROL`, 5 zones appariées par nom, VP 0→35/35, rejouées par le vrai parseur.
Chaque verrou a été mis au ROUGE en remettant le défaut, puis rétabli (10 mutations).
**Reste :** confirmer visuellement VP + coloration des zones dans un replay browser.

**Jumeau analyzer — ✅ TRAITÉ dans la foulée (2026-07-29).** `ai/analyzer_core.py` refaisait le même
calcul fautif à chaque action `step_inc` (somme par **ancre**, sans battle-shock, hors frontière
14.02) puis ré-implémentait le barème primaire. **Écart mesuré sur le MÊME log réel : l'analyzer
annonçait `P1=60 / P2=20` là où le moteur avait attribué `35/35`** — une partie nulle rapportée
comme un raz-de-marée P1.
Les VP viennent maintenant de la ligne `T{tour} OBJECTIVE CONTROL:` (dernier instantané de
l'épisode ; le moteur journalise un **total**, pas un delta). Sont supprimés, sans appelant restant :
`_calculate_objective_control_snapshot`, `_calculate_primary_objective_points`,
`_get_objective_name_to_id_map`, `_resolve_terrain_path_for_scenario`,
`_get_primary_objective_ids_for_scenario`, leurs deux caches, `_resolve_scenario_path`, le champ
`objective_control_history` (**écrit, jamais lu** dans tout le dépôt), et les champs d'état
`objective_hexes` / `objective_controllers` / `last_objective_snapshot` / `scored_turns` /
`seen_turn_player` / `primary_objective_configs` / `episode_step_index`.
Effet de bord bienvenu : l'appariement nom → id positionnel disparaît, donc **la coexistence de
trois formats d'identifiant d'objectif** signalée dans `V11_tranches.md` n'a plus lieu d'être côté
analyzer. Même contrat que le replay : un journal qui déclare des objectifs sans instantané est
**rejeté** (régénérer), un scénario sans zone reste analysable.
Verrous : `tests/unit/ai/test_analyzer_utils.py` (VP = dernier instantané et non une accumulation,
récapitulatif de fin d'épisode ignoré, rejet d'un journal périmé, scénario sans zone accepté) —
4 mutations mises au rouge puis rétablies. `pyright ai/`, `hidden_action_finder.py` et
`check_ai_rules.py` propres.

### 4.B — Purge legacy V10 du `game_state` — ✅ MOTEUR (2026-07-23) + FRONT (2026-08-10)
**Audit.** Les 3 pools étaient inertes en V11 : machine V10 (`fight_build_activation_pools`,
`_update_fight_subphase`, helpers alternance/consolidation) **morte** (chaîne remontant à des fonctions
sans appelant) ; seul chemin vivant = `end_activation(FIGHT)` dont le `phase_complete` dérivé des pools
vides était déjà **jeté** par le caller squad_fight.

**Fait (moteur) :**
- `generic_handlers.end_activation` : branches FIGHT (retrait pool + `pool_empty`) retirées ; tracking
  `units_fought` + step conservés. `_rebuild_alternating_pools_for_fight` supprimée.
- `fight_handlers` : 8 fonctions V10 mortes supprimées (`fight_build_activation_pools`,
  `_fight_maybe_lazy_rebuild_alternating_pools`, `_fight_post_process_fight_activation_result`,
  `_fight_try_begin_consolidation_after_attacks`, `_handle_fight_consolidation_resolution`,
  `_update_fight_subphase`, `_fight_finish_no_more_targets_after_attack`, `_toggle_fight_alternation`)
  + bloc pool mort dans `_fight_phase_complete` (`fight_phase_end` est vivant → lisait via `require_key`)
  + scrubbing V10 dans `_remove_dead_unit_from_fight_pools` (cross-phase conservé).
- Init pools retiré (`w40k_core`, `_fight_phase_complete`) ; 3 clés retirées de
  `shared_utils._remove_unit_from_all_activation_pools`.
- Tests : `test_fight_activation_pools.py` supprimé (V10) ; 3 tests V10 retirés de `test_fight_execution`
  (+ 1 réécrit sur `shoot_activation_pool`).
- **Front sûr** : `game.ts` (types) et `BoardPvp.tsx` (deps) purgés.
- Validé : grep V10 **vide** côté moteur+front (le résidu front l'est aussi depuis le 2026-08-10,
  cf. bloc suivant), 97 tests moteur verts, run `--step` OK
  (FOUGHT + pile_in/conso, 0 KeyError/NameError), tsc propre.

**Fait (front, 2026-08-10)** — `useEngineAPI.ts` portait deux cascades `if/else if` **identiques**
(blocs `currentPoolSize` et `fightPool` de la boucle d'auto-play IA), chacune sur les cinq
sous-phases V10 `charging`/`alternating_*`/`cleanup_*`, plus **3** champs morts de son interface
locale. Motif JUMEAU de CLAUDE.md logé **dans le même fichier** : nettoyer une cascade seulement
aurait laissé l'autre sur le même chemin. Les deux lisent désormais le pool V11 par
`getFightActivationPoolUnitIds` (`utils/activationClickTarget.ts`, déjà importé par ce hook pour le
clic manuel), calculé **une seule fois** et partagé — il n'y a plus de cascade à dupliquer.
Vérifié : `grep` des 5 sous-phases et des 3 champs → **0 hit** dans `frontend/src/` comme dans
`engine/ services/ ai/` ; `tsc -p tsconfig.app.json` et `biome` propres ; `activationClickTarget.test.ts`
11/11.

⚠️ **Ce n'était pas un nettoyage neutre, et le point de contrôle est là.** Les branches mortes ne
tombaient pas dans un `else` inoffensif : `currentPoolSize` restait à **0** en phase fight, donc le
`break` « pool vide » sortait de la boucle d'auto-play **dès la première unité IA sans action
valide**, et le second bloc (`hasMoreEligibleUnits`) n'était jamais atteint. Le pool V11 étant
maintenant lu, la boucle poursuit tant qu'il reste des unités IA vivantes activables — alignée sur
les branches `move` et `charge` du même bloc, inchangées. Ce chemin ne vit qu'en **PvP live**
(aucun test ne couvre ce hook de 9 600 lignes) : la vérification est une partie PvP avec plusieurs
unités IA en phase de combat.

### 4.C — `pile_in` / `consolidation` classés en phase `move` ✅ FAIT (2026-07-23)
Le moteur loggue déjà ces lignes `FIGHT : … PILED IN/CONSOLIDATED` (phase correcte côté log). Le bug
était **parseur-only** : la phase de l'ÉTAT était déduite par `action.type.includes("fight")`, or
`"pile_in"`/`"consolidation"` ne contiennent pas `"fight"` → classés `move`.

**Implémenté :**
1. `frontend/src/utils/replayParser.ts` : `pile_in`/`consolidation` → `phase="fight"` ; `fightStateFields`
   étendu — `fight_subphase` dérivé du type (`pile_in`/`consolidate`, exact vs moteur, non loggué sur
   ces lignes) et `fight_eligible_units = [unit_id]` (l'unité qui bouge = active).
2. `tests/unit/engine/test_squad_step_logging.py` : test obsolète réaligné (`pile_in` A un formateur,
   présent dans `_STEP_LOG_TYPE_MAP`) + nouveau `test_pile_in_is_logged_as_fight`.
3. Verrou parseur : `replayParser.test.ts` (pile_in → `phase="fight"`, `fight_eligible_units=[unit_id]`).

Validé : pytest squad_step_logging vert, vitest 5/5, tsc propre. Pas de régénération de log (parseur seul).

---

## 5. Fichiers clés

| Rôle | Fichier |
|---|---|
| Log producteur | `engine/w40k_core.py`, `ai/step_logger.py` |
| Pool fight V11 | `engine/phase_handlers/fight_handlers.py` (`fight_v11_current_pool`) |
| Parseur | `frontend/src/utils/replayParser.ts` (+ `.test.ts`) |
| Vue replay | `frontend/src/components/BoardReplay.tsx` |
| Gabarit colonne droite (partagé PvP/replay) | `frontend/src/components/SharedLayout.tsx`, `GameLogWithIllustration.tsx` (§3bis) |
| Rendu partagé | `frontend/src/components/BoardPvp.tsx`, `UnitRenderer.tsx` |
