# Training — Tâches ouvertes

---

## ⚠️ À FAIRE UNE FOIS — initialiser le contrat des modèles existants {#contrat-init}

**Livré le 2026-09-09** (`ai/training_contract.py`). Le prologue d'un run vérifie désormais que le
modèle repris a appris sur le **même sens** des grandeurs : registres d'observation, canaux de
grille, familles d'actions, **clés** de la table de récompense. C'est le trou que ni
`check_model_lifecycle` (qui regarde la commande), ni le verrou de parité de pool (qui parle après
la première sonde), ni `check_for_correct_spaces` de SB3 (qui ne voit que les dimensions) ne
couvrent : la dérive à taille **constante**.

**Conséquence immédiate** : un modèle antérieur à cette livraison n'a pas de contrat, donc sa
première reprise (`--append`, `--resume-from`) **s'arrête**. Après avoir vérifié que le contrat
courant est bien celui sur lequel ce modèle a appris :

```bash
python3 -m ai.training_contract --init --agent ArmageddonAgent_x1
```

Un `--new` n'a rien à faire : il écrit le contrat lui-même. Les **valeurs** de récompense ne sont
pas comparées — régler un poids reste libre, seule la disparition d'une clé arrête un run.

---

## ✅ Obs — `hidden` 13.09 sur toutes les entités et porte de détection {#hidden-detection-obs}

**Livré et mergé le 2026-09-08.** `obs_size` inchangé (16811), donc ce lot n'impose **par lui-même**
aucun `--new` ; il tombe dans celui que « canaux obscurant / exposition » rend déjà obligatoire.

`los_can_see` ne portait que 06.01. La porte des 15" de 13.09 ne vivait que dans l'éligibilité du
tir (`valid_target_pool_build`), donc l'observation annonçait `1` sur une cible que le moteur
refusait : l'agent ne pouvait apprendre ni à entrer dans la portée de détection, ni à se cacher
au-delà. Le bit vaut désormais **visible ET détectable**, via les mêmes oracles que le moteur
(`compute_unit_los` + `hidden_enemy_out_of_detection`) — aucune réimplémentation.

`hidden` est donc émis pour **toute entité posée** et non plus pour la seule unité active : c'est lui
qui conditionne la visibilité. `_squad_terrain_flags` prend un mode `hidden_only` plutôt qu'un second
chemin — une seule implémentation de 13.09. `gone_to_ground` / `in_cover` restent actif-seul : pour un
ennemi, `cover_vs_observer` porte déjà 13.08 EXACT et le −3" de 13.5 est plié dans la porte de
détection ; les émettre coûterait une seconde passe terrain pour une information redondante.

**Coût mesuré** (`scripts/bench_env_step.py`, 400 steps, x1_long/bot/résolution 1, sous contention) :
`hidden` seul 61,8 µs/entité contre 122,0 µs pour les trois drapeaux, et les gardes gratuites
(`hideable`, `units_shot`) écartent 54 % des entités sans aucun scan. Total **0,596 ms/step, soit
0,30 % du temps de step** et 2,8 % du temps d'observation.

**Divergence refermée le 2026-09-08** : l'obs recalcule `hidden` à chaud là où le moteur lit
`unit['hidden']`, et une perte encaissée en cours de phase les faisait diverger. Le moteur suit
désormais les pertes au choke-point de retrait de figurines, et le contrat D1 tient donc en cours de
phase et plus seulement à son début : voir [moteur.md#hidden-fraicheur](moteur.md#hidden-fraicheur).
Il reste périmé pendant le MOVE, ce qui justifie que l'obs continue de recalculer plutôt que de lire.

---

## ✅ Obs — rôle et PV par figurine (retrait de cohérence 03.03) {#role-pv-figurine}

**Livré le 2026-09-09.** `obs_size` 17795 → **17916** : ré-entraînement `--new` obligatoire — il
l'était déjà pour les lots du même jour, ce lot n'en ajoute aucun.

`COHERENCY_SLOT_i` (P3-0) demande à l'agent quelle figurine **détruire** pour regagner la
cohérence. Il désigne la ligne `i` de `self_models_*`, que `pointer_policy._point` score par un
produit scalaire nu **sans biais de slot**, sur un embedding calculé **ligne par ligne**
(`self_model_encoder`, aucune interaction entre slots). Or la ligne ne portait que
`col_rel, row_rel, fight_eligible, in_enemy_ez, elevated, present` : le rôle d'allocation
existait bien dans l'observation, mais **agrégé par TYPE**, et les PV courants n'étaient plus
observés par figurine depuis §9.4. Le tri de `_squad_models_for_observation` place pourtant les
personnages en tête — un rang qu'**aucune tête ne lit**.

**Mesuré avant correction** (16 épisodes gym du pool `training`, actions masquées aléatoires,
3 250 pas) : 8 points d'arrêt de cohérence, dont 4 mêlaient un personnage attaché et des figurines
de base et 5 des figurines de PV différents ; **67 paires de figurines de valeur différente sur
67** portaient une ligne `self_models_bin` **identique**, seule leur position les séparant. Le
choix était donc un tirage au sort entre le Warboss et un Boy. Même mesure sur l'état :
l'observation d'une escouade **avec et sans** `pending_coherency_removal` armé est strictement
identique (écart 0.0 sur toutes les clés), alors que le masque, lui, n'ouvre que les slots
COHERENCY — la politique ne pouvait pas se tromper d'action, mais la **valeur** de l'état ignorait
qu'une figurine était perdue d'office.

**Ce qui a été livré :**

- one-hot de rôle (4 bits) + `wounded` dans `SELF_MODEL_BIN_FIELDS` (+100) et `hp_ratio` dans
  `SELF_MODEL_CONT_FIELDS` (+20) — `present` reste **dernier** (§0.37) ;
- `MODEL_ROLES` devient la **source unique** des deux registres qui portent ce one-hot (bloc TYPES
  et bloc figurines) : deux tuples écrits à la main auraient pu diverger sans rien lever ;
- `wounded` double `hp_ratio` **volontairement** : les continus de ce bloc passent par
  `EntityRunningNorm`, dont la variance est minuscule sur une colonne quasi constante (une figurine
  à 1 PV max n'est jamais entamée), donc `hp_ratio` y sature à ±10 — le FAIT survit à la
  saturation, le DEGRÉ reste porté par `hp_ratio` ;
- `coherency_removal_pending` dans `GLOBAL_BIN_FIELDS` (+1), posé sur l'escouade **observée** et
  non « un retrait quelque part » : pendant l'arrêt, l'observateur EST l'escouade en attente ;
- deux verrous, l'un côté moteur (`tests/unit/engine/test_squad_obs_model_value_p3_0.py`), l'autre
  côté réseau (`tests/unit/ai/test_self_model_value_encoding.py`) : c'est exactement ce qui
  manquait à `decision_options_cont`, rempli par le moteur et lu par personne.

`ai/spatial_extractor.py` n'a **pas** été touché : ses largeurs d'encodeur sont dérivées des formes
de l'espace d'observation, donc les colonnes ajoutées entrent d'elles-mêmes — vérifié par test.

---

## ✅ Obs — CONTEXTE des points d'arrêt à deux temps {#contexte-points-arret-obs}

**Livré le 2026-09-09.** `obs_size` 17091 → **17795** : ré-entraînement `--new` obligatoire.

Deux mécanismes demandent un choix dont la moitié est déjà fixée — la sélection d'arme de mêlée
(§0.69 : la cible est désignée, l'arme reste à choisir) et le sous-état CIBLE du tir fractionné
(P3-8 : l'arme est armée, la cible reste à choisir). Ni l'une ni l'autre moitié n'était observée.
S'y ajoute, trouvée en revue puis mesurée, ce que le tir fractionné a déjà DÉCIDÉ : ses
assignations arme → cible, invisibles elles aussi.

**Mesuré avant correction :** dans les deux cas, deux états ne différant que par la moitié déjà
fixée produisaient des observations **strictement identiques** — 28 clés comparées, écart maximal
0,0. La politique n'étant pas récurrente (`MaskablePPO`), elle ne se souvient pas de l'action jouée
au step précédent : l'arme se choisissait sans voir la cible, la cible sans voir l'arme. Cause
commune : l'observation n'encodait qu'un seul des sept points d'arrêt de `PLAYER_CHOICE_MECHANISMS`,
la décision d'agent. Fréquence sur les rosters joués : 5 escouades sur 11 portent ≥ 2 armes de
mêlée, 8 sur 11 ≥ 2 armes de tir ; mesuré en jeu, 5 épisodes gym du pool `training` traversent
36 points d'arrêt de tir fractionné et 2 sélections d'arme de mêlée.

**Ce qui a été livré :**

- `fight_target_selected` (`UNIT_BIN_FIELDS`, +32 scalaires) marque la ligne ennemie de la cible
  désignée. Aucun bit de contexte global ne l'accompagne : la cible occupe toujours un slot ennemi
  observé (`_continue_squad_fight` lève sinon, et `FIGHT_SLOT_COUNT` vaut `K_ENEMY_SLOTS`), donc le
  bit est auto-porteur. L'observation lève si la cible n'y figure pas — jamais un bit muet ;
- `shoot_weapon_selected` (`PROFILE_BIN_FIELDS`, +640) marque le profil de l'arme armée. Le registre
  des profils n'avait qu'un champ, le masque : `present` reste **dernier** (§0.37), lu
  positionnellement par `ai/spatial_extractor` ;
- le slot du profil armé est **écrit par le moteur** (`pending_weapon_slot`, posé et effacé avec
  `pending_weapon`) et relu par l'observation, au lieu d'être re-dérivé du code d'arme — deux
  dérivations d'un même fait divergent ;
- le drapeau d'arme est posé **hors du cache de profils** (mémoïsé par escouade et figurines
  vivantes) : écrit dedans, il serait resté allumé après la fin du point d'arrêt ;
- un test vérifie que les trois canaux **atteignent le réseau** — c'est exactement ce qui manquait
  à `decision_options_cont`, rempli par le moteur et lu par personne ;
- `n_weapons_assigned` (`UNIT_CONT_FIELDS`, +32) comptait, par escouade ennemie, les profils
  d'armes déjà assignés pendant l'activation de tir en cours. **Ce champ n'existe plus** : il a
  cédé la place le même jour aux dix bits `split_assigned_w<i>`, qui portent le même comptage
  (`popcount`) ET l'appariement arme → cible que le comptage perdait — voir
  [Obs — couples arme→cible du tir fractionné](#couples-arme-cible-split-fire).

---

## ✅ Obs — couples arme→cible du tir fractionné {#couples-arme-cible-split-fire}

**Livré le 2026-09-09.** `obs_size` 17916 → **18204** : ré-entraînement `--new` obligatoire —
déjà exigé par les lots du même jour, et aucun artefact du disque n'était compatible (P0, P1 et
le dernier run sauvegardé étaient à 16791, `best_model.zip` à 17055 — mesuré dans les `.zip`).

Deuxième temps du maillon précédent, qui n'avait couvert que la PREMIÈRE arme du split-fire. Une
fois un couple arme → cible commité, l'agent choisit l'arme suivante puis sa cible sans rien voir
de ce qu'il a déjà envoyé et sur qui.

**Mesuré :** les dix bits mis à 0, deux états ne différant que par la cible déjà assignée rendent
des observations **identiques sur les 28 clés**, aux DEUX sous-états — celui qui demande l'arme
suivante comme celui qui demande sa cible. Le masque ne le disait pas non plus : une cible déjà
prise reste éligible pour l'arme suivante.

**Ce qui a été livré :**

- `split_assigned_w0..9` (`UNIT_BIN_FIELDS`, 10 bits × 32 entités = +320) : le bit `i` vaut 1 ssi
  l'arme du slot de profil RNG `i` est déjà assignée à cette escouade. Transposée exacte de
  `assignments` — sur la ligne de la cible, quelles de mes armes la visent déjà ;
- `n_weapons_assigned` **retiré** (−32) : il était la projection `popcount` de ces bits.
  L'égalité est garantie par l'injectivité `code d'arme → slot de profil`, vérifiée sur les 179
  datasheets et les 33 escouades des `config/armies/` — les armes à profils multiples portent des
  codes distincts (`plasma_pistol_standard` / `_supercharge`), `COMBI_WEAPON` marquant l'arme
  physique partagée. Garder les deux, c'était deux encodages du même fait ;
- **dix bits et non un seul « déjà ciblée »** : 04.03 « Gather Attack Dice » cumule les dés des
  armes faisant des attaques identiques sur une même cible, donc la conséquence de règle dépend de
  QUELLE arme y est déjà. Mesuré sur les 11 escouades Armageddon (SM+Orks) : 55 % portent ≥ 3
  profils de tir, jusqu'à 6 — soit 75 % de celles capables de split-fire, pour qui un bit unique
  perdrait l'appariement ;
- le slot vient de `assignments[code]["weapon_slot"]`, **RECOPIÉ** du `pending_weapon_slot` du
  moteur au moment du commit de la cible, jamais re-dérivé du code par l'observation (invariant
  D1). C'est ce qui fait passer les valeurs d'`assignments` de `str` à
  `{target_id, weapon_slot}` ; le seul autre lecteur de la table (le précheck de quantité d'armes)
  suit le même couple ;
- un seul lecteur d'activation, `read_pending_shoot_split` : les deux lecteurs de sous-état en
  dérivent, et le doublon apparu en parallèle a été supprimé plutôt que conservé ;
- **coût réseau mesuré**, pas estimé : extracteur 245 392 → 246 544 paramètres (+1 152, +0,47 %),
  l'encodeur d'entité étant partagé entre les deux camps ;
- verrous : marquage sur la ligne de la cible et sur elle seule, deux armes sur la MÊME cible →
  deux bits, clôture de la liste sur `K_WEAPONS_RANGED`, absence hors split-fire et dans
  l'observation d'une autre escouade, slot hors bloc d'armes → erreur, et un test réseau qui exige
  que **deux slots assignés différents donnent deux embeddings différents** — sans quoi le bloc de
  bits ne vaudrait pas mieux qu'un comptage.

**Ce qui n'est PAS prouvé :** que la politique s'en serve mieux. L'information existe, elle n'est
nulle part ailleurs, et le comptage en perdait l'appariement — mais le gain d'apprentissage se
mesure sur un run, pas ici.

---

## ✅ Obs — candidats de décision DISCERNABLES {#candidats-decision-discernables}

**Livré et mergé le 2026-09-09** (`0049f9ab`). `obs_size` 17055 → **17091** : ré-entraînement
`--new` obligatoire, décidé par l'utilisateur au moment de la livraison.

Le bloc `decision_options_cont` était rempli par le moteur depuis P3-4 mais **n'atteignait aucun
réseau** : `SpatialCombinedExtractor` ne le listait pas dans ses clés attendues, son
`decision_encoder` était dimensionné sur le seul bloc binaire, et la clé n'apparaissait dans aucun
de ses accès d'observation. Cinq types de décision sur neuf posent des candidats qui n'accordent
aucun effet et ne renoncent à rien — `allocation_model` (à chaque blessure non sauvegardée),
`charge_placement` (à chaque charge réussie), `mortal_wounds_target` et les deux décisions de Grot
Orderly : leurs lignes d'observation étaient **strictement identiques**.

Mesuré avant correction, deux candidats aux traits continus opposés sortaient à un écart
d'embedding de **exactement 0.0** ; `pointer_policy._point` scorant chaque candidat par un produit
scalaire nu, sans biais par slot, les logits étaient égaux. `CHOICE_i` était un pile-ou-face que
PPO ne pouvait pas apprendre. Après câblage, le même cas sort à 0,4544.

Les quatre autres types restaient apprenables par un autre canal, et le restent : `rule_choice`
par le one-hot de l'effet accordé, `waaagh_call`, `fly_declaration` et `ascent_declaration` par le
bit `declines`.

**Ce qui a été livré :**

- l'encodeur de candidat lit ses **deux** blocs, et la construction lève si leurs cardinalités
  divergent — un désaccord ne levait nulle part ailleurs et aurait mélangé les traits d'un
  candidat avec les drapeaux d'un autre ;
- `DECISION_OPTION_CONT_FIELDS` passe de 2 à **8 colonnes nommées**, une grandeur par colonne :
  deux types qui décrivent la même grandeur partagent la colonne (`dist_enemy_norm` sert à
  l'allocation comme au placement rendu), deux grandeurs différentes n'en partagent jamais. Les
  lignes se bâtissent par `decision_option_cont_row`, qui lève sur un champ inconnu ou hors
  [0, 1] — aucun producteur n'écrit de zéro positionnel ;
- le bloc ne passe par **aucune** `EntityRunningNorm` : ses statistiques glissantes excluent les
  candidats absents mais pas les colonnes muettes d'un type, et mélangeraient « sans objet » et
  vraies valeurs. Les colonnes sont donc normalisées à la source ;
- les cinq types sont alimentés. Pour le placement des figurines rendues, ce sont les **distances
  du plan** — jumeau exact du placement de charge — et non un one-hot d'intention : les distances
  disent ce que l'étiquette vaut sur CE plateau, et généralisent à une intention ajoutée sans
  colonne de plus.

**Défaut de fond trouvé en vérifiant, et corrigé :** `_precompute_nearest_enemy_dist` énumérait
`models_cache` sans filtrer les unités hors table. Une escouade en réserves stratégiques (20.01)
est vivante dans le cache, ses figurines y portent la sentinelle (-1,-1), et l'énumération
injectait donc une position qui n'existe pas sur la table. Les deux sites énumèrent désormais par
`enemy_entries_on_battlefield`.

**Son ampleur a été MESURÉE le 2026-09-09, et elle est nulle — la première rédaction de ce
paragraphe surestimait le défaut.** Sur 1 337 appels en bot-contre-bot (pool `training`,
2 scénarios × 20 épisodes), 14 avaient un ennemi hors table et **aucun** ne changeait de
résultat : la sentinelle est un COIN du plateau, donc le `min` ne la retient que pour une
figurine plus proche de ce coin que de tout ennemi réel — cas jamais atteint sur ce volume. Les
classements bot-contre-bot avant/après correction sont **identiques bit à bit** : 2 400 épisodes
sur `holdout`, 1 200 sur `training`, même graine, même protocole.

Conséquence pratique, contre ce qui avait été annoncé ici : **la ligne de base des bots reste
comparable**, et le run `--new` n'a pas besoin d'une re-mesure préalable du panel. Les chiffres
`{0,48 ; 0,46}` → `{0,06 ; 0,08}` cités auparavant venaient du test de non-régression, dont
l'état est construit pour que la sentinelle domine — ils prouvent le verrou, pas une fréquence de
jeu.

---

## ✅ Obs — canaux « zone obscurante » et « exposition à la vue ennemie » {#canaux-obscurant-exposition}

**Livré et mergé le 2026-09-08** (`dd8a24be`). Le lot impose un ré-entraînement `--new` : la
forme d'entrée du CNN change, et le chantier « OC live + secured », mergé le même jour, bouge en
plus `obs_size`.

`GRID_CHANNELS` passe de 9 à 11 ; la verticalité du move gym l'a depuis porté à **12**
(`occupant_level`, cf. [`moteur.md#verticalite-move-gym`](moteur.md#verticalite-move-gym)).
`obs_size` ne bouge pas — la grille est fournie à part.

- **`GRID_CH_OBSCURING`** — les zones obscurantes n'étaient pas distinguables des autres zones de
  terrain : `_static_hex_arrays` empilait tout dans le canal « couvert » sans lire
  `area["obscuring"]`. Le canal est **dilaté du rayon de socle**, comme son jumeau couvert, parce
  que le moteur tranche 13.09 par chevauchement de socle. Ce qu'il ajoute au couvert : être
  `hidden` ne dégrade pas un jet, il rend **intirable** au-delà de la portée de détection.
- **`GRID_CH_LOS_EXPOSURE`** — part des escouades ennemies vivantes et posées qui voient la
  cellule. **Non dérivable** des autres canaux : la branche spatiale est une pile de conv 3×3
  stride 1, elle n'est pas capable de tracer un rayon. Écrit sur les **cellules du pool de move
  uniquement**, à l'hexe que le décodeur y enverra — donc 0 hors phase de mouvement, même
  doctrine que le coût géodésique, et **aucune seconde réponse cellule→hexe** à côté de celle du
  décodeur (mesuré : elles divergent sur 26,7 % des cellules jouables).

**Coût, protocole graine fixe, 450 steps de mouvement** : step de move 73,31 → 80,33 ms
(**+9,6 %**, sous le seuil de 10 %) ; toutes phases 67,39 → 71,52 ms (+6,1 %). **Sans cache**, et
c'est mesuré : une carte de visibilité plateau mémoïsée par hexe source rate 26 % du temps
(l'ancre ennemie bouge à chaque déplacement ET à chaque perte de figurine), l'amorti retombe au
coût de la version sans cache.

**Reste à faire** : le ré-entraînement `--new`, commun à tous les lots d'observation du 2026-09-08 et du 2026-09-09. Tout modèle antérieur est incompatible par construction.

---

## 🔴 Régime de lignée — option A livrée, P2 à relancer depuis P1 {#regime-lignee-2026-09-07}

**Livré le 2026-09-07. Ce qui reste à faire : lancer P2.** Trois runs P2 successifs ont échoué en
faisant varier des hyperparamètres étape par étape ; l'option A supprime cette possibilité au lieu
de chercher les bonnes valeurs pour chaque étape.

**1. Un PROFIL de lignée, `x1_lineage`, appliqué à TOUTE étape `init: "from:"`** — les dix
learners comme les trois exploiteurs. `learning_rate` 0.001 et `ent_coef` 0.03 **scalaires**,
`n_steps` 32640, `vf_coef` 0.15, `agent_seat_p2_ratio` 0.6 ; tout le reste, `batch_size` 1020 et
`max_grad_norm` 0.5 compris, est **hérité** de `x1_long` par `"extends"`. `batch_size` a d'abord
été surchargé à 4080 pour garder huit mini-lots ; il est rendu à l'héritage le 2026-09-07, ce
mini-lot ayant fait mourir P2 à sa première update par saturation de VRAM (pic 8,89 Go sur 8,19). Les vingt rampes
`decay_fraction` des étapes disparaissent, ainsi que les surcharges de `vf_coef` /
`max_grad_norm` de P2 et P3 ; une étape reprise ne déclare plus que `total_episodes`, et le
validateur refuse le reste. `x1_long` garde ses rampes et son `vf_coef` 0.5 pour le seul départ à
froid P0.

**Deuxième version, le 2026-09-07 même.** Le premier jet portait ces valeurs dans un bloc
`lineage_regime` du curriculum. Il les dispersait sur deux fichiers avec une règle de précédence à
connaître pour répondre à « quel `learning_rate` utilise P5 », là où le dépôt exprime déjà « un
autre régime » par « un autre profil » — six fois dans le même fichier. Le bloc est remplacé par
un profil, et le curriculum ne porte plus que les deux **noms**, dans `training_configs`
(`cold_start` / `lineage`). `ai/train.py::_prepare_curriculum_stage` **refuse au lancement** un
`--training-config` qui ne correspond pas à la nature de l'étape ; le mécanisme d'héritage vit
dans `config_loader::_resolve_profile_extends`. Détail chiffré et mesures :
`Documentation/Reference/training/entrainement.md`, section « Rampes ».

**2. `P00` supprimée, `P0` passe en `init: "new"`, E1/E2/E3 passent en `init: "from:P0"`.** La
graine n'existait que pour éviter de repayer un warmup à chaque learner, ce que le chaînage a rendu
sans objet. Les exploiteurs ne partent plus des poids de leur cible : ils en étaient une copie à
qui l'on demandait de trouver sa propre faiblesse, donc ils commençaient à la parité par
construction et ne pouvaient s'en écarter qu'en désapprenant.

**3. Contrôle de continuité à l'ouverture.** `_pin_entropy_ramp_for_warm_start` est supprimé avec
les rampes qu'il corrigeait ; à sa place, `announce_lineage_continuity` lit `ent_coef` et
`learning_rate` dans le zip repris et annonce tout écart avec le bloc. Il n'en corrige aucun.

**4. Verrou de parité, qui ARRÊTE le run.** À l'épisode 0 d'une étape reprise, le modèle **est**
l'archive dont il reprend les poids : son score contre elle vaut 0.50 par identité. La baseline de
`PoolEarlyStoppingCallback` la mesure ; hors de `[0.40, 0.60]`, le run est refusé **avant le
premier épisode**. Les 2026-09-04 et 2026-09-05 ont chacun produit des heures d'entraînement sur
une baseline aberrante (0,477 puis 0,118) lue comme une mesure.
Il ne se pose qu'à `_stage_episode() == 0`, et pas sur la seule origine du compteur : après un
`--resume-from <checkpoint>` de reprise sur crash, l'origine reste celle de l'archive source alors
que le modèle a joué des milliers d'épisodes — le tester là arrêtait toute reprise dont la
politique avait progressé hors de la fenêtre.

**5. Toutes les décisions passent sur la moyenne des `probe_window` dernières sondes**
(`pool_eval/vs_<tag>_<probe_window>ep` — 3 aujourd'hui ; le tag porte la fenêtre réelle, il
annonçait `_3ep` quelle que soit la valeur configurée). Promotion et arrêt si ≥ 0.55 contre le
champion **et** ≥ 0.50 contre chaque autre membre après 50 000 épisodes d'étape ; arrêt pour
destruction si < 0.40 contre le champion après 20 000. Le gate de fin applique les mêmes seuils sur
une moyenne de 3 blocs d'évaluation, et un seuil de promotion **sous** le plancher du gate est
refusé au chargement (sinon le run s'arrête en se déclarant promu sur un score que le gate
refusera, et jette le budget non dépensé avec l'étape). Le pool **entier** est sondé, plus
seulement le champion : une étape pouvait être promue en battant son prédécesseur immédiat tout en
ayant régressé contre tout le reste. Une archive du pool écartée par l'évaluation **arrête le
run** au lieu d'être signalée : sans elle, ni promotion ni destruction ne peuvent plus être
décidées, et l'étape brûlait son budget entier pour une ligne ⚠️ par sonde.

**6. Un verdict `destroy` est souverain : le gate ne le rejuge pas.** L'étape est refusée sans
mesure. Sous `save_best_robust` (les profils du curriculum), le zip canonique est l'instantané
robuste pris plus tôt dans le run — **d'autres poids que ceux jugés** : le gate pouvait donc
l'accepter et le promouvoir, et `curriculum.log` portait `pool_stop_verdict: "destroy"` à côté de
`gate_accepted: true`. Un verdict `promote`, lui, laisse le gate mesurer normalement.

⚠️ **`base_seed` de `evaluate_against_checkpoints` est désormais TIRÉ AU HASARD.** Il valait 42 en
dur, donc deux évaluations d'un même modèle rejouaient les mêmes parties et rendaient le même score
au bit près (vérifié le 2026-09-07 : 16/24/0 aux deux appels) — moyenner trois blocs identiques
n'est pas une moyenne. Conséquence à assumer : **un gate n'est plus reproductible à l'identique**,
et les scores de `curriculum.log` antérieurs au 2026-09-07 portent un échantillon unique et figé.

**À mesurer au prochain run** : `00_critical/g_grad_share_policy_mb0` doit monter de 0,235 vers
~0,62 dès les premières updates — effet arithmétique de `vf_coef`, pas un effet d'apprentissage.
Si elle ne bouge pas, le régime n'a pas pris et il est inutile d'attendre. `n_steps` × 4 quadruple
la mémoire du rollout buffer : **coût horloge et mémoire non chronométrés** à ce volume.

### Six défauts de la livraison, fermés le 2026-09-07

**Le premier était bloquant pour toute la chaîne.** `_apply_curriculum_model_params` posait un
`ConstantSchedule` sur `model.learning_rate`, que SB3 sérialise dans le `data` du zip — un objet
cloudpickle là où `_model_scalar` attend un nombre. Tant que le LR était une **rampe**, le
callback d'ordonnancement réécrivait un flottant à chaque épisode et masquait le défaut ; le
régime posant un LR **scalaire**, aucun callback n'est monté. P2 (repris de P1, dont le zip porte
encore un flottant) tournait, mais P3 aurait levé au contrôle de continuité — et avec lui P4…P10
et E1…E3. `learning_rate` porte désormais le nombre, `lr_schedule` le callable, comme le fait déjà
`LearningRateScheduleCallback._apply`.

**Une reprise sur crash enchaînait les sondes manquées.** `_next_probe_episode` partait du premier
cran alors que le compteur d'étape, ancré sur l'archive source, valait déjà des dizaines de
milliers d'épisodes : les crans manqués se déclenchaient d'affilée sur des pas consécutifs, sans
mise à jour de politique entre eux. À la deuxième, l'historique atteignait deux points et un
verdict tombait — sur deux mesures des **mêmes** poids, au-dessus de `promote_min_episodes` : le
run de reprise pouvait être promu ou déclaré détruit après **zéro épisode entraîné**. Même défaut
que les 8 sondes consécutives mesurées le 2026-09-04, revenu par une autre porte. La cadence
rattrape désormais au prochain cran au lieu d'avancer d'un pas ; corrigé sur les deux sondes
(pool et exploiteur).

**`--close-stage` rouvrait la promotion d'une étape détruite.** Le verdict `destroy` n'existait que
dans le `run_info` du processus : la commande de reprise le reconstruit depuis les artefacts du
disque, où il n'apparaît pas. Comme une étape détruite n'écrit aucun `model_<agent>_<etape>.zip`,
le garde « déjà promue » ne voyait rien non plus, et la clôture remesurait l'instantané robuste —
d'autres poids que ceux jugés, qui pouvaient franchir le gate. Le verdict est désormais persisté
en **sidecar du modèle canonique** (`pool_stop_path`), que `_run_info_from_disk` relit.
Volontairement pas dans `curriculum.log` : ce journal est en append à la racine du projet, ses
entrées ne portent **aucune clé d'agent**, et il conserve l'historique de toutes les *tentatives*
d'une même étape — relire « la dernière ligne de P4 » aurait rendu le verdict d'une tentative
précédente, ou celui d'un autre agent. Le sidecar entre dans `canonical_run_artifacts`, donc
`--new` comme `--resume-from` l'écartent au démarrage : une étape rejouée après destruction
repart sans verdict.

**Un verdict `promote` publie désormais les poids VIVANTS** (décision du 2026-09-07, option A).
L'early-stop rend ce verdict sur les poids courants, mesurés contre tout le pool ; sous
`save_best_robust` le zip canonique était pourtant l'instantané robuste, choisi sur le score
contre les **bots** et jamais dégradé en cours de run (la copie n'a lieu que si le score robuste
progresse — `training_callbacks.py`, condition `robust_score > best_robust_score`). Le gate de fin
mesurait donc un modèle que personne n'avait jugé, pouvait le refuser, et le run s'était déjà
arrêté : le budget non dépensé partait avec l'étape — l'inverse exact de ce que l'arrêt anticipé
annonce (« le budget restant serait payé pour rien »). Publier est l'exception que
`save_best_robust` peut accepter : le verdict **est** une validation contre l'intégralité du pool.
Le verdict `destroy`, lui, ne publie rien.
⚠️ **Le seuil de score robuste du canonique (`canonical_robust_meta_path`) est effacé à cette
publication.** Il décrit le modèle remplacé. Il est bien écarté au **démarrage** d'un run, par
`--new` comme par `--resume-from` (les deux passent par `canonical_set_aside_pairs`) ; ce
qu'aucun des deux ne couvrait, c'est la **fin** de run traitée ici — le seuil serait resté en
place jusqu'au démarrage suivant en annonçant un score que le canonique n'a pas, défaut de la
même famille que V11 §0.36.

**Cadence des sondes dédoublée** (décision du 2026-09-07, option B). Sonder le pool entier à
chaque sonde faisait suivre le coût à la **taille** du pool, qui croît d'une étape à l'autre : à
P10 (13 membres, 300 000 épisodes, cadence 10 000, 300 épisodes par membre) cela fait **117 000
épisodes d'évaluation bloquants** sur le fil d'entraînement pour 300 000 entraînés, là où la sonde
champion seul d'avant en coûtait 9 000. Le champion est désormais mesuré à **chaque** sonde, les
autres membres **un tour sur `full_pool_probe_every`** (3 dans la config livrée) : il reste
~48 600 épisodes, soit **-58 %**. Les deux verdicts n'ont pas le même besoin de fraîcheur — la
destruction ne lit que le champion et doit couper vite, la promotion lit tout le pool mais ne
s'ouvre qu'à 50 000 épisodes d'étape. **Ce qui n'est pas dégradé** : le verdict lit toujours le
pool entier, les membres non sondés au tour courant gardant leur dernière moyenne connue, au plus
trois sondes en arrière. Les **deux premiers tours restent pleins** quelle que soit la valeur :
aucun verdict n'est rendu tant qu'un membre n'a pas deux points, et sans eux la destruction
attendrait 40 000 épisodes au lieu des 20 000 que son seuil demande.

**Trois fermetures plus petites.** La clôture dérivait le champion par un `next(...)` local là où
`stage_champion_label` **refuse** un pool à plusieurs champions, que `validate_curriculum` accepte
— elle prenait le premier venu en silence. Le plombage `timesteps_origin` était mort depuis la
suppression du garde `min_steps` : `stage_origin` ouvrait le zip source pour cette seule valeur.
Et la docstring de `pool_monotonicity_diagnostic` dimensionnait encore son bruit contre
`gate.target_score_vs_champion` (0.60), clé supprimée par cette même livraison.

---

## 🔴 Régime d'entraînement révisé — P2 à relancer depuis P1 {#regime-2026-09-06}

Deux changements livrés le 2026-09-06, plus un réglage d'évaluation du 2026-09-04 resté non déclaré
jusqu'ici. **Ce qui reste à faire : relancer P2 depuis P1.** P1 n'est pas rejoué (décision du
2026-09-06 : le temps est déjà payé), sa config est seulement homogénéisée.

**1. Le déploiement `auto` pose désormais les deux camps.** Il ne posait que le joueur contrôlé :
l'agent était placé au hasard pendant que son adversaire — bot à doctrine, ou champion du pool
jouant son réseau — se déployait avec sa politique apprise. `s_win_rate_deploy_auto` mesurait donc
un handicap unilatéral et non l'adaptabilité qu'elle prétend mesurer. Mesure du run x1_long du
2026-09-06 (~64 000 épisodes) : **0.304** de win-rate en `auto` contre **0.684** en `active`, avec
un différentiel d'objectifs de **-0.76** contre **+0.19** — l'agent tenait trois quarts d'objectif
de moins que son adversaire. La référence du 2026-08-12 (0.866 / 0.646, les deux différentiels
positifs) avait été prise contre des bots à doctrine de pose fixe, bien moins capables d'exploiter
une pose adverse médiocre.

⚠️ **`s_win_rate_deploy_auto` et `r_obj_held_diff_deploy_auto` changent de définition** : leurs
valeurs antérieures au 2026-09-06 ne se comparent pas aux suivantes. Attendu au prochain run : la
courbe `auto` doit remonter vers 0.5 en P2, puisque l'agent EST le champion à l'épisode 0. Si elle
reste basse, c'est qu'il reste autre chose à chercher.

**2. La part de bots tombe à 30 % en P1, 20 % en P2, 15 % de P3 à P10.** Les six bots sont saturés
— EndgameBot 0.99, DecapitationBot 0.95, RacerBot 0.94, AlphaStrikeBot 0.93, AttritionBot 0.92,
ScorerBot 0.86, aucun sous 0.86 — quand le champion du pool est à 0.502 (parité) et P0 à 0.626.
637 500 épisodes de la lignée partaient contre des adversaires dominés, soit 23 % du budget ; il
en reste 455 000. Pas 15 % partout : la part de bots suit la **taille du pool**, pas la force de
l'agent — à 15 %, P1 jouerait 85 % de ses parties contre son unique membre de pool, soit le régime
d'un exploiteur alors qu'il est promu champion. La rampe d'adversité de P1 est supprimée au
passage (elle le faisait démarrer à 100 % de bots), résidu du nettoyage qui avait retiré les neuf
autres.

**3. `bot_eval_intermediate` de `x1_long` passe à 100 épisodes par bot** (2026-09-04), pour la
précision de chaque point intermédiaire : à 30, l'erreur-type d'un win-rate autour de 0,5 valait
0,5/√30 = 9,1 points, du même ordre que les écarts qu'on cherche à lire d'un point au suivant ; à
100 elle tombe à 5,0. Contrepartie : l'évaluation intermédiaire passe de 6 × 30 = 180 à
6 × 100 = 600 épisodes, **coût horloge non rechronométré** à ce volume — les durées de
`bot_eval_freq_normal` valent pour 180. À mesurer au prochain run avant d'être citées.
`x5_long` reste à 30 : les deux profils `_long` divergent sur cette clé, et c'est assumé — le
chiffre publié sort de `x1_long`. La sonde d'entraînement, elle, reste à 3 avec son +33 %.
Le réglage et la divergence sont désormais verrouillés profil par profil
(`tests/unit/ai/test_schedule_decay_fraction.py`), ce qu'ils n'étaient pas : le verrou de
comparabilité était rouge depuis le 2026-09-04, avec quatre autres tests, et personne ne le voyait.

**Mesure incidente, non élucidée.** Le run P1 a joué **31,3 %** contre P0 (25 063 épisodes sur
80 075, `tensorboard/P1`), là où sa config annonçait 50 %. L'écart n'est pas expliqué par la rampe
seule, qui s'achève en ~417 épisodes par env et ne pèse que 12 % du run. Non investigué : le run
n'est pas rejoué. À retenir : un `ratio_end` n'est pas une mesure — la part réellement jouée se lit
sur le rapport entre les points de `03_selfplay/<membre>` et ceux de `actions/share_deploy_slot`,
à 500 près (la fenêtre de lissage).

---

## ⚠️ Courbes de santé PPO — historique des défauts {#courbes-ppo-reprise}

Trois défauts vivaient sur la capture des métriques PPO
(`MetricsCollectionCallback._on_training_start`), corrigés le 2026-09-04. Ce qu'ils rendent
illisible sur les runs antérieurs :

**Sur les runs REPRIS uniquement** (`--resume-from`, donc toute étape de curriculum à
`init: "from:..."`) — les quatre courbes de santé PPO de `00_critical` ne sont **pas lissées** et
ne doivent pas être lues : `g_explained_variance`, `h_clip_fraction`, `i_approx_kl`,
`j_entropy_loss` — lettres d'AVANT le 2026-09-06, conservées ici parce que ce sont celles que
portent réellement les fichiers `events` de ces runs ; depuis, l'insertion de
`g_grad_share_policy_mb0` les a décalées en `h_`, `i_`, `j_` et `k_`. L'enveloppe posée sur `logger.dump` n'était jamais retirée, et SB3 appaire
pourtant `on_training_start`/`on_training_end` autour de chaque `learn()`. Sur un run neuf le
logger est reconstruit à chaque `learn()` et l'enveloppe morte partait avec lui ; en reprise
`model.set_logger` le rend persistant et les couches s'accumulaient. Chaque update était alors
capturé autant de fois qu'il y avait de couches, et la fenêtre de vingt valeurs de
`_calculate_smoothed_metric` finissait par couvrir vingt copies du même update. Mesure sur le run
P1 du 2026-09-03 : 41 756 points sur `training_critical/clip_fraction` pour **575 updates réels**,
contre 1 063 points pour 1 063 updates sur un run neuf comparable. Les courbes paraissaient 4× à
14× plus bruitées, sans que la politique ni le régime d'update soient en cause.

**Sur TOUS les runs, neufs compris** :

- `training_diagnostic/entropy_coef` et `training_diagnostic/gradient_norm` portent **un point par
  ÉPISODE** et non par update. `_handle_episode_end` appelle `logger.dump` à chaque fin d'épisode,
  et la capture s'y déclenchait alors qu'aucun update PPO n'y figure — les gradients y sont ceux
  laissés par le dernier `train()`. Mesure sur le run neuf du 2026-08-29 : 101 415 points pour
  100 000 épisodes et 1 063 updates.
- Toutes les courbes `training_critical/*` et `training_diagnostic/*` sont **décalées d'un dump**
  sur l'axe des pas : l'abscisse était posée après l'écriture, donc chaque update partait au pas du
  dump précédent.

**Ce qu'il faut lire sur ces runs** : les séries brutes `training_critical/clip_fraction`,
`approx_kl`, `explained_variance` et `training_diagnostic/entropy_loss`. Les valeurs y sont
exactes ; sur un run repris elles sont répétées, et les copies d'un même update se superposent à
la **même** abscisse plutôt que de former un escalier — la courbe reste donc lisible, à condition
de la lire comme une suite de paliers et non comme un signal bruité.

Les courbes de jeu (`game_critical/win_rate`, `game_critical/episode_reward`, `03_selfplay/*`) ne
passent pas par ce chemin et n'ont jamais été touchées. Elles portaient alors aussi les tags
`00_critical/{d_win_rate,e_episode_reward_smooth}`, depuis retirés du namespace critique.

Le run P1 en cours au 2026-09-04 a chargé le code avant le correctif : ses courbes restent
fausses jusqu'à sa fin. Verrou : `tests/unit/ai/test_metrics_dump_wrapper_idempotent.py`.

**Quatrième défaut, distinct des trois précédents, corrigé le 2026-09-06** — celui-ci touchait
**tous** les runs, neufs compris, et il est indépendant de l'empilement d'enveloppes. Les cinq
courbes `00_critical/f..j` et les huit lignes `thresholds/*` étaient republiées à **chaque fin
d'épisode** alors que leur source n'est alimentée qu'une fois par update : 39 430 points pour 529
valeurs distinctes sur `run_20260906-123804`, soit 74,5 copies par valeur, contre 532 points et
532 valeurs sur les jumelles `train/*` de SB3. Le curseur de lissage de TensorBoard comptant des
points, il aurait fallu le régler sur ~1 500 pour couvrir la fenêtre glissante de 20 updates. Aucune
valeur n'était fausse — l'enveloppe de l'escalier est la bonne série — mais le curseur était
inopérant et les runs de cadences d'update différentes n'étaient pas comparables point pour point.
Ces treize tags portent désormais un point par update. Verrou :
`tests/unit/ai/test_metrics_tracker_utils.py::test_les_courbes_de_sante_ppo_suivent_la_cadence_de_l_update`.
Les runs antérieurs au 2026-09-06 gardent l'escalier, à lire comme une suite de paliers.

---

## Sonde win-rate scénarios d'entraînement {#training-probe}

**Livré 2026-09-06.** `training_probe_every_n_evals` dans `BotEvaluationCallback` publie
`bot_eval/training_combined` sur TensorBoard, calculé contre les scénarios d'ENTRAÎNEMENT (pas
holdout), en mode déterministe, tous les N evals holdout.

Motif : gap factor 2,5 mesuré le 2026-09-06 entre +13 pts sur les scénarios d'entraînement et
+5 pts holdout, invisible sur le dashboard existant. Les deux courbes permettent de distinguer :

- courbe plate → **n'apprend pas** → correction : hyperparamètres, récompense, obs.
- courbe haute / gap large → **n'généralise pas** → correction : pool de scénarios, régularisation.

Ne gate rien. Activé à 3 (`x1_long` profile, `callback_params.training_probe_every_n_evals`).
Coût : +33 % du budget eval distribué uniformément.

---

## Critères pipeline du run en cours (ex-« run x1 de vérification ») {#run-verif}

Un run `x1` de vérification dédié avait été décidé le 2026-08-11 pour prouver que le pipeline
tourne avec l'espace de décision modifié. Le run `x1_long --new` lancé le 2026-08-17
([bot.md#etape8](bot.md#etape8)) embarque le même code à HEAD : **les critères se lisent sur SES
courbes**, un run séparé n'a plus d'objet sauf si celui-ci échoue.

✅ Critères vérifiés sur le run `x1_long --new` du 2026-08-20 :

- ✅ `game_critical/invalid_action_rate` reste à **0**
- ✅ `02_combat/m_charge_attempts` **non nul**
- ✅ `02_combat/n_charge_success_rate` **non nul** (en V11 la déclaration est gratuite — l'agent déclare « au cas où » puis choisit ses cibles après le jet ; un taux bas ne signifie pas un dysfonctionnement)
- ✅ Courbes `reserves/*` et `05_charge/*` **peuplées** (`charge_distance/*` était le nom de la clé interne, le tag TensorBoard réel est `05_charge/*`)

⚠️ Pour tout re-run : `--new` et non `--append` — `--append` réapplique `ent_coef = 0,1` et écrase le modèle canonique.

---

## ✅ Curriculum R1→R3 — absorbés par le curriculum `--etape` {#curriculum}

**Décision 2026-08-30 — R1→R3 abandonnés comme runs standalone.**

Deux raisons rendent ces runs redondants :

1. Le bug d'aliasing obs Phase 3 (corrigé 2026-08-29) invalide toute ligne de base antérieure.
   La validation du fix s'est faite sur le run `--etape P2` (ratio_mb0=1.0, EV→0.85) — ce run
   tient lieu de R1.
2. Le curriculum `--etape` P0→P10 intègre déjà les trois leviers séquentiellement : P0 = bots
   purs (≡ R1), P1/P2/… = self-play progressif (≡ R2), levier récompense = à tester via
   `--etape` sur un run ultérieur si D.4 le justifie (≡ R3).

Mesurer R1/R2/R3 en standalone n'apporterait que la décomposition du gain par levier — utile
pour arbitrer, mais le curriculum `--etape` les intègre tous et la mesure J3 se fera sur le
champion final.

**Le chiffre J3 se lit sur le champion issu du curriculum P0→P10, pas sur un run standalone.**

→ `Documentation/Chantiers/backlog/curriculum_adversaires_etalons.md` §5-7 (historique)

---

## Mode exploiteur E1/E2/E3 {#exploiteur}

**Livré 2026-08-22.** `--etape E1/E2/E3` mesure l'exploitabilité de sa cible (P3, P5, P8) :
budget = épisodes pour passer de 50 % à 70 % de win-rate contre la cible figée.

- `ExploiterProbeCallback` : sonde synchrone tous les 2000 épisodes (100 ép. bon marché →
  une seule confirmation de 500 ép.), sans Future ni ThreadPoolExecutor.
- `validate_exploiter_protocol` : refuse le run si `training_config`, `ratio`, `warmup`
  ou `profile_total_episodes < budget_cap` divergent du protocole gelé (`exploiter_config`).
- `curriculum.log` : budget entier ou `'>50000'` (censuré) + courbe win_rate complète.
- 28 tests verrou (4 verrous : refus protocole, budget_cap atteignable, pas de sonde abandonnée, valeur censurée).
- `training_config_required` : `x1_long` (50 000 épisodes = `budget_cap`).

Lancer : `python3 ai/train.py --agent ArmageddonAgent --training-config x1_long --scenario bot --etape E1`

---

## É9 — Second siège + second scénario {#e9}

**Suspendu** — après entraînement bot satisfaisant (jalon J4). Second scénario écrit par l'utilisateur (décision 2026-08-02).

→ `Documentation/Chantiers/v11/index_v11.md` §0.47

**2026-08-28 — levier d'exposition livré, indépendamment de É9.** `agent_seat_p2_ratio` rend pondérable le tirage de siège en entraînement (il était figé à 50/50 par la parité d'un hachage) ; réglage posé à 0.65 sur les six profils. Motivation : 12 points d'écart p1/p2 mesurés sur le run x1_long du 2026-08-12. L'évaluation garde son tirage équitable. É9 reste ouvert : il porte le second SCÉNARIO, que ceci ne traite pas. Effet à mesurer au prochain run — voir `Documentation/Reference/training/entrainement.md`.
