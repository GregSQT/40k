# Refonte du panel de bots — six styles, une échelle de difficulté graduée

> Ouvert le **2026-08-11**. Chantier du benchmark d'évaluation, pas de l'agent.
> Doc de détail ; l'ordre du travail reste dans [`../ROADMAP.md`](../ROADMAP.md) §1.

## 1. Pourquoi

Le panel de six bots sert à la fois d'adversaire d'entraînement et de mètre étalon. Mesuré
aujourd'hui (protocole en §2), il ne rend que **deux signaux distincts pour six bots** : les
intervalles de confiance de `tactical`, `adaptive` et `value_trade` se recouvrent entièrement,
`greedy` et `defensive` sont indiscernables l'un de l'autre et trop hauts pour départager deux
agents. Seul `control` porte de l'information.

La cause n'est pas un réglage. Elle est **mesurée** : tous les critères de décision des bots
(menace, choix de cible, « tuable ce tour », « charger ou pas ») reposent sur
`get_max_ranged_damage` / `get_max_melee_damage`, qui valent `max(NB × DMG)` d'**une seule arme**.
Ces fonctions ignorent le jet pour toucher, la Force contre l'Endurance, l'AP contre la
sauvegarde, **le nombre de figurines** de l'escouade, la portée, et toutes les règles d'arme
(SUSTAINED, DEVASTATING, TORRENT, MELTA, ANTI_X, BLAST).

Conséquence sur le roster 500 pts d'ArmageddonAgent, **recomptée le 2026-08-12 sur les rosters
holdout** (le 2026-08-11 annonçait 16, à un profil près) : **17 profils sur 23** ont
`melee > ranged` selon ce proxy, dont l'Intercessor (2.00 contre 3.00 — un fusil à 24" contre
un couteau), l'Ancient, le Librarian et les Boyz. Or c'est exactement le test qui décide de
charger (`TacticalBot._select_charge_action`, `ValueTradeBot._charge`) et celui qui identifie une
« menace de mêlée » à contre-charger (`DefensiveBot`, `_score_melee_threat_only`). Les bots
envoient donc leurs unités de tir au contact et abandonnent leur portée.

Deux trous s'y ajoutent, établis par lecture de `ai/evaluation_bots.py` :

- **Le déplacement ne voit ni ligne de vue, ni couvert, ni portée** (sauf `TacticalBot`, qui a sa
  passe de portée). `_select_destination` ne pèse que la distance à l'objectif et la distance à
  l'ennemi, sur l'ancre. Aucun bot ne cherche une position d'où il tire.
- **Aucune coordination d'armée.** Chaque escouade vise l'objectif le plus proche d'elle (`min`
  sur les cartes de distance) ; `objective_controllers` n'est lu que par `AdaptiveBot`, et
  seulement pour sa posture, jamais pour choisir où aller. Avec `hold_bonus = 3.0` et la règle
  « à égalité on ne bouge pas », un bot qui touche un objectif s'y assied jusqu'à la fin.
  ✅ **Traité le 2026-08-12, cf. §12** — la refonte ne l'avait PAS rebouché : `objective_controllers`
  n'était lu nulle part dans `ai/bot_doctrines.py`.

## 2. Mesure de référence — 2026-08-11, à ne plus rejouer autrement

Colonne de gauche de la table de correspondance. **Toute mesure du nouveau panel se compare à
celle-ci, avec cette commande exacte.**

```bash
cd /home/greg/40k && source .venv/bin/activate
python3 ai/train.py --agent ArmageddonAgent --training-config x1 \
  --test-only --test-episodes 100 --resolution 1
```

Modèle gelé : `ArmageddonAgent_12345_robust_0.9438.zip` (+ son `_vec_normalize.pkl`), installé au
chemin canonique `model_ArmageddonAgent.zip`. Plateau **x1** (`board/44x60x1`). Pool **holdout**
(`scenario_bot-01..04`). `base_seed = 42`. 600 épisodes en 1 163 s (0,52 ép./s, mode sérial).

| bot | win-rate agent | marge 95 % (n=100) |
|---|---|---|
| greedy | 0,98 | ±2,7 |
| defensive | 0,96 | ±3,8 |
| tactical | 0,91 | ±5,6 |
| adaptive | 0,88 | ±6,4 |
| value_trade | 0,87 | ±6,6 |
| control | 0,73 | ±8,7 |

`Combined = 0,8455`. Worst bot `control = 0,73`. Worst scénario `holdout_regular_bot-03 = 0,796`.
Écart Space Marine − Ork : +0,1 pt.

⚠️ **Ne pas comparer au 96,9 % du 2026-08-11 matin** (éval finale du run `x1_long`) : autre
modèle, autre profil, autres scénarios. Les deux ne se recoupent pas.

⚠️ **La résolution se fixe AVANT de mesurer.** Sans `--resolution 1` le plateau par défaut est x5,
et le classement des bots y est différent — une campagne de réglage entière a été jetée pour cette
raison (cf. `config/bot_movement_weights.json`, entrée `tactical`).

## 3. Décisions actées (2026-08-11)

1. **Les six anciens bots sont gelés puis supprimés.** Ils ne valent que par une mesure unique :
   le facteur de conversion entre l'ancien mètre et le nouveau. Une fois la correspondance
   consignée, leur code part — un panel conservé « au cas où » mais jamais exécuté pourrit en
   silence et devient pire qu'absent. Git le restitue si besoin.
   ⚠️ **Gel = ne pas toucher une ligne des six classes actuelles.** Un flag `damage_model`
   commutable avait été envisagé puis **rejeté** : le nouveau panel n'a pas les mêmes doctrines
   que l'ancien, un paramètre ne peut pas exprimer ça.
2. ~~**Six styles orthogonaux**, un axe de faiblesse chacun~~ — **L'ORTHOGONALITÉ EST ABANDONNÉE
   comme critère, décision de l'utilisateur du 2026-08-12 sur la mesure du §11.2.** Les six bots
   se déplacent en bloc d'un modèle à l'autre (+3 à +7 points, ordre strictement identique) : ils
   forment **une seule dimension**, mesurée à six niveaux de difficulté. La cause est le format,
   pas le dessin des bots — seuls les objectifs marquent (§12.1 : zéro victoire par élimination
   sur 600 parties), donc aucun panel ne peut rendre six axes dans un jeu qui n'en a qu'un.
   Le panel reste un instrument utile, mais c'est une **échelle de difficulté**, pas une base de
   mesure multi-dimensionnelle. La table ci-dessous décrit ce que chaque style FAIT ; elle ne
   promet plus qu'il mesure un axe indépendant.

   | style | doctrine | erreur punie |
   |---|---|---|
   | Racer | prend tous les objectifs au plus vite, refuse le combat | l'agent qui campe et ne conteste jamais |
   | Endgame | tient le minimum tôt, prend le maximum à partir du tour 3 | l'agent qui marque tôt et se croit gagnant |
   | Alpha strike | cherche le contact au plus tôt sur la pièce clé | l'agent qui expose ses unités de tir |
   | Attrition | joue le départage VALUE : préserve ses pièces chères, tue le rentable | l'agent qui trade mal |
   | Décapitation | concentre tout sur une escouade par tour pour la retirer entièrement | l'agent qui étale ses forces |
   | Scorer | joue pour marquer, ne se bat que pour ça | l'agent qui gagne des combats et perd la partie |

   Racer/Endgame sont les deux bornes du **tempo**, Attrition/Décapitation les deux façons
   opposées de dépenser ses dégâts, Alpha la distance nulle, Scorer l'axe du score lui-même.
   `adaptive` **disparaît** : c'est un commutateur entre trois autres styles, donc corrélé par
   construction.
   ⚠️ `Standoff` (« tenir ses distances ») a été **supprimé** le 2026-08-11 — mesures et raison
   en §9.2. Décision de l'utilisateur, reprise telle quelle : « je préfère des bots pertinents
   plutôt que forcer pour en avoir un de plus qui n'apprend rien ». Le nombre n'a aucune vertu ;
   l'orthogonalité si. Le panel est retombé à cinq styles, puis remonté à six le 2026-08-12 avec
   `Scorer`. ⚠️ Ce raisonnement est **périmé par la décision ci-dessus** : `Scorer` a été ajouté
   au nom d'un « axe manquant », et la mesure du §11.2 dit qu'il n'y a pas d'axes. Il se justifie
   toujours — il reprend la doctrine du seul ancien bot informatif — mais comme un **barreau de
   l'échelle**, pas comme une dimension.
3. ~~**Le holdout garde le nom `tactical` mais change de nature**~~ — **ABANDONNÉ le 2026-08-12,
   cf. §11.** La refonte « joue pour gagner » (recherche à un coup) a été écrite, mesurée, puis
   supprimée : elle coûtait 9,5× un bot normal par épisode et ne gagnait pas plus souvent qu'eux.
   `tactical` reste donc l'ancien `TacticalBot`, et le holdout reste ce qu'il était.
4. **Le budget d'évaluation se répartit selon l'incertitude**, pas uniformément : un bot battu à
   98 % est confirmé en ~100 parties, un bot serré autour de 50 % en demande 600.
5. **`ai/reward_mapper.py` reste hors chantier.** Il partage le proxy faux (`:24-25`), mais
   corriger la récompense de l'agent en même temps que le benchmark rendrait les deux effets
   impossibles à démêler — ce qui viderait de son sens tout ce protocole. Chantier propre, juste
   après celui-ci.

## 4. Ordre du travail

| # | étape | état |
|---|---|---|
| 0 | consigner la mesure de référence (ce doc, §2) | ✅ 2026-08-11 |
| 1 | `step.log` nomme l'adversaire réellement affronté | ✅ 2026-08-11 |
| 2 | ~~appariement des graines entre bots comparés~~ | ❌ **retirée** 2026-08-11, cf. §4.1 |
| 3 | ~~chiffrage de faisabilité du holdout à un coup~~ | ⛔ **sans objet** — holdout abandonné 2026-08-12, §11.2 |
| 4 | modèle de dégâts espérés (attaquant → cible) | ✅ 2026-08-11, **corrigé à la racine** 2026-08-12, cf. §7 et §7.1 |
| 5 | les SIX styles | ✅ 2026-08-12, cf. §7 et §11.3 (`standoff` supprimé §9.2, `scorer` ajouté §11.3) |
| 6 | réglage en **bot-contre-bot** (~~orthogonalité~~ abandonnée, §3.2) | 🟠 **PARTIEL** — `w_contest` et `w_crowd` **non réglés** ; chiffres du §8/§9 à rejouer, cf. §11.1 |
| 7 | correspondance ancien/nouveau, puis suppression des cinq anciens | |
| 8 | mesure finale contre l'agent, commande de §2 | 🟠 **PARTIEL** — mesurée sur `robust_0.8721` (§12.5) ; reste à rejouer après réglage |

### 4.1 Pourquoi l'appariement des graines a été retiré

Les deux dérivations de graine du dépôt mettent le nom des bots dans la clé —
`ai/bot_evaluation.py:706` (le bot évalué) et `scripts/bot_ranking.py:67` (la paire). Deux bots de
noms différents jouent donc des parties différentes. L'étape 2 proposait de retirer cette
dépendance pour que l'ancien bot et son remplaçant soient comparés sur les mêmes tirages
(*common random numbers*, réduction de variance de la différence).

Elle est **sans objet**, pour trois raisons qui se cumulent :

1. **La correspondance est un match DIRECT, pas la comparaison de deux mesures.** Ancien bot
   contre nouveau bot dans la même partie (§4, étape 7) : il n'y a qu'une expérience, donc rien à
   apparier.
2. **L'effet attendu à l'étape 8 est massif**, pas marginal. Un appariement sert à extraire un
   écart du bruit ; ici l'écart est l'objet même du chantier.
3. **Le changement invaliderait la référence de §2**, mesurée avec la dérivation actuelle : elle
   cesserait d'être reproductible à l'identique, ce qui est précisément sa fonction.

S'y ajoute que `scripts/bot_ranking.py:67` porte la justification **inverse**, explicite : « sans
le nom des DEUX bots dans la graine, deux appariements différents rejoueraient la même séquence de
tirages ». Le désaccord est réel — l'appariement est une technique de réduction de variance, pas
un biais — mais le gain n'a **pas été mesuré**, et il ne le sera pas ici : il ne servirait aucune
des mesures de ce chantier.

⚠️ Le seul cas où la dépendance au nom nuirait vraiment : **renommer un bot sans changer son
comportement** ferait sauter ses graines et rendrait ses win-rates incomparables aux anciens. Ce
chantier n'en contient aucun — `tactical` garde son nom en changeant de nature (§3.3), et les six
styles sont des noms neufs.

**L'orthogonalité et la correspondance se mesurent en bot-contre-bot**, via
[`scripts/bot_ranking.py`](../../../scripts/bot_ranking.py), pas contre l'agent : mesurer un bot
par le win-rate de l'agent est **circulaire** (un bot faible contre un agent fort donne le même
chiffre qu'un bot fort contre un agent faible), et c'est la raison d'être de cet outil. La mesure
contre l'agent (étape 8) confirme, elle n'instrumente pas.

```bash
W40K_BOARD_PATH=board/44x60x1 python3 scripts/bot_ranking.py --episodes 20
```

⚠️ Ce script **n'a pas de drapeau de résolution** : sans `W40K_BOARD_PATH` il mesure sur x5, donc
un autre jeu que la référence de §2.

## 5. Pièges relevés dans le code

- **`--model` ne redirige rien.** `ai/train.py --test-only` charge toujours le chemin canonique
  `ai/models/<agent>/model_<agent>.zip` (`:4198`) ; `--model` n'est qu'un `print` (`:4138`). Pour
  évaluer un checkpoint, il faut l'installer au chemin canonique **avec son `.pkl` apparié** — un
  modèle chargé avec les statistiques de normalisation d'un autre run mesure autre chose.
- **`--scenario bot` est refusé en `--test-only`** (`:4237`) : le mode n'évalue que sur holdout.
  Omettre `--scenario`.
- **Le nom du bot n'est posé qu'en mode sérial** : le `step_logger` n'est pas picklable et n'est
  jamais transmis aux workers. Une passe parallèle donne les win-rates, pas le journal par bot.
- **`_episode_seed` dérive du nom du bot** (`ai/bot_evaluation.py:706-710`) : deux bots de noms
  différents jouent des parties différentes. Un bot et son remplaçant ne sont donc pas comparés
  sur les mêmes tirages — c'est l'objet de l'étape 2.

## 6. Chiffrage du holdout à un coup (étape 3) — mesuré le 2026-08-11

Protocole : `ArmageddonAgent`, profil `x1`, `W40K_BOARD_PATH=board/44x60x1`, scénario holdout
`scenario_bot-01`, `reset(seed=42)`, trajectoire aléatoire de 60 pas couvrant les cinq phases
(deployment, command, move, shoot, charge). Médianes.

| grandeur | mesure |
|---|---|
| `copy.deepcopy(game_state)` complet | **68,4 ms** |
| dont `weapon_damage_table` seule | 46,2 ms (**75 %**) |
| `deepcopy` en excluant les clés statiques | **9,6 ms** (×7,1) |
| `engine.step()` | **6,85 ms** |
| actions légales par décision | **médiane 5**, min 2, **max 458** |

**La copie n'est pas le problème, et la solution existe déjà.** Les trois quarts du coût sont une
table de dégâts d'armes **immuable** (`config/weapon_damage_table.json`, chargée par
`engine/weapon_damage_cache.py`) que rien ne mute en partie. `services/game_snapshots.py` a déjà
tranché exactement cette question pour le rewind PvP : `_GS_STATIC_KEYS` liste 17 clés invariantes
non copiées — les 17 sont présentes dans l'état mesuré. Le clone rapide est donc du **code de
production éprouvé à réutiliser**, pas une optimisation à inventer.

**Le branchement, lui, est rédhibitoire en phase de MOVE.** Avec le clone rapide, simuler un coup
coûte ≈ 16,5 ms (9,6 + 6,85) :

| phase | actions | coût 1-ply par décision |
|---|---|---|
| tir / charge / combat | ≈ 5 | **≈ 82 ms** |
| move | jusqu'à 458 | **≈ 7,6 s** |

Un `select_movement_destination` à 7,6 s rend le holdout inutilisable : à ~150 décisions par
épisode, une seule partie dépasserait la minute rien qu'en déplacements, contre ~2 s aujourd'hui.

⚠️ **Ces mesures valent pour x1.** Le pool BFS de move monte à ~634 cellules sur x5 (cf. en-tête
de `ai/evaluation_bots.py`) : le coût du move y est encore plus haut.

**Ce qui reste à trancher** : le holdout simule-t-il ses coups partout (impossible en l'état), ou
seulement là où le branchement le permet, ou sur un sous-ensemble filtré des destinations ?
Remonté à l'utilisateur le 2026-08-11.

## 7. Ce qui a été livré aux étapes 4 et 5

**Le socle n'était pas à écrire.** `engine/weapon_damage_cache.py` calculait déjà les dégâts
espérés attaquant→cible en O(1) (jet pour toucher, Force contre Endurance, AP contre sauvegarde),
sur une table pré-calculée. Un second modèle de dégâts aurait créé le doublon divergent que ce
dépôt paie le plus cher.

Il manquait **un facteur** : la table donne un dégât **par figurine** (sa clé offensive porte `NB`,
les attaques d'une figurine), alors que les bots décident au niveau de l'escouade — dix Boyz y
valaient un Boy. `squad_expected_damage()` agrège sur les figurines **vivantes**, lues comme le
fait le moteur (ids de `squad_models` présents dans `models_cache`). Aucun repli : cache absent ou
escouade inconnue lèvent, sans quoi une unité inconnue passerait pour inoffensive.

### 7.1 Correction du 2026-08-12 — l'agrégation était une multiplication, et elle était fausse

La première version prenait la meilleure arme de l'**escouade** et la multipliait par l'effectif.
Or le profil d'armes porté par l'objet `unit` n'est **que celui du soldat de base** : sergents,
armes spéciales et personnages attachés n'y figurent pas, et les figurines de base comptaient à
leur place. Mesuré sur `scenario_bot-01` en comparant à la vraie somme par figurine : **50 paires
(attaquant, cible, phase) sur 90 étaient fausses**, médiane **0,50×** la vraie valeur, pire cas
**0,18×** (0,78 annoncé contre 4,23 réels en mêlée). Seules les deux escouades **homogènes** du
scénario tombaient juste. Le moteur, lui, a toujours résolu par figurine — l'estimation mentait
donc sur le combat réel, et c'est le même défaut que celui que ce chantier existe pour corriger,
déplacé d'un cran : modèle juste, jeu d'armes tronqué.

`_best_weapon_cache` est désormais indexé **par figurine** (`models_cache`) et
`squad_expected_damage` **somme** sur les vivantes. Après correction : 90 paires contrôlées, **0
fausse**. Verrou : `tests/unit/engine/test_squad_expected_damage.py`, dont
`test_the_special_weapons_of_a_mixed_squad_are_counted` est le seul test qu'aucune multiplication
ne peut passer (vérifié rouge en remettant le défaut : 2,5 rendu au lieu de 6,0).

⚠️ **L'observation de l'agent n'était PAS concernée, contrairement à ce qui était écrit ici.**
Instrumentation d'une partie complète le 2026-08-12 : son unique lecteur du cache,
`ObservationBuilder._target_priority_score`, **n'avait aucun appelant**. Il portait par ailleurs
une **troisième** implémentation des dégâts (jet pour toucher et sauvegarde recodés à la main),
elle-même fausse sur deux points de plus — nombre d'attaques calculé puis jamais utilisé,
sauvegarde invulnérable ignorée. Supprimé, avec les deux aides qu'il tirait derrière lui. **Aucun
ré-entraînement n'est donc requis par cette correction** : le seul consommateur vivant du cache
est le panel de bots.

🔎 Signalé, non traité (défaut sans lien, hors périmètre) : `shared_utils.calculate_target_priority_score`
est **morte elle aussi** — définie, importée par `shooting_handlers` et `fight_handlers`, jamais
appelée. Elle porte le même proxy `max(DMG)` que ce chantier condamne.

**Nouveaux fichiers** : `ai/bot_doctrines.py` (les six styles), `ai/bot_holdout.py` (le holdout à
un coup), `ai/bot_registry.py` (source unique clé→classe).

**Un défaut jumeau trouvé en chemin** : la table clé→classe existait en DEUX copies
(`ai/bot_evaluation.py` et `scripts/bot_ranking.py`). Brancher les six styles dans la première a
suffi pour l'évaluation, et `bot_ranking.py --bots racer` levait toujours « Unknown bot type ».
`ai/bot_registry.py` est désormais la source unique, les deux appelants y passent.

⚠️ **Il y en avait cinq, pas deux** (trouvés le 2026-08-12, tous branchés depuis) : `ai/metrics_tracker.py`
n'écrivait de courbe `bot_eval/vs_<bot>` que pour les six anciens — les cinq styles refondus n'en ont eu
**aucune**, et sur `x1_panel` le `worst_bot_score` de TensorBoard ne s'écrivait plus du tout ;
`ai/train.py` levait « did not return any known bot score keys » en fin d'évaluation d'un profil qui ne
joue que les styles refondus ; et `scripts/roster_matchup_stats.py` refusait `--eval-bot racer`,
exactement comme `bot_ranking.py` avant sa correction. La table de `_build_training_bots_from_config`
(`ai/train.py`) est laissée à part **volontairement** : elle construit les adversaires
d'ENTRAÎNEMENT, et ne pas savoir instancier un holdout y est une protection (V11 §10.5), pas un oubli.

**Accès moteur du holdout** : un bot ne reçoit d'ordinaire que `game_state` et ne peut rien
simuler. `BotControlledEnv` remet le moteur aux bots qui le **déclarent** (`NEEDS_ENGINE`, attribut
de classe) — jamais par `hasattr`, dont le repli mou a déjà fait jouer `TacticalBot` en aveugle
toute une campagne. Les trois voies d'arrivée d'un bot sont couvertes (`bot=`, `bots=[...]` tiré à
chaque épisode, et l'injection au vol de `scripted_action_for_agent_side`) ; une déclaration non
honorée lève. Verrou : `tests/unit/ai/test_bot_engine_access.py`.

**Clé de transition** : le nouveau holdout est enregistré sous `tactical_lookahead`. Il prendra le
nom `tactical` à l'étape 7, quand l'ancien partira — c'est l'ancien qui a un historique de mesures
à préserver, pas lui.

## 8. Réglage (étape 6) — mesures en bot-contre-bot, x1

Protocole : `W40K_BOARD_PATH=board/44x60x1 python3 scripts/bot_ranking.py --training-config x1`,
pool holdout, les deux sièges.

**Premier tournoi des six** (120 épisodes, poids d'origine posés par doctrine) :

| bot | win-rate moyen |
|---|---|
| attrition | 0,725 |
| decapitation | 0,700 |
| standoff | 0,550 |
| racer | 0,450 |
| alpha | 0,425 |
| endgame | **0,025** |

**`endgame` était perdant par construction, pas par réglage.** Le score primaire court à partir du
tour 2 (`config/primary_objective/44x60/Objectives_Control.json` : `start_turn: 2`, 15 VP/tour) et
la partie dure 5 tours. Ne rien tenir avant le tour 4, c'est renoncer aux tours 2 et 3 — la moitié
des tours qui rapportent. Aucun jeu de poids ne rattrape ça.

Correction : « jouer la fin de partie » ne peut pas vouloir dire « ne rien marquer avant ». Il
prend le premier palier tôt (5 VP dès qu'il tient une zone) et bascule sur le maximum au tour 3,
en gardant ses unités intactes pour ce moment-là. `PUSH_TURN` 4 → 3 ; `w_objective` 0,3 → 0,9 ;
`w_enemy` −0,8 → −0,35.

Mesure après correction (sous-tournoi à trois, 16 épisodes) : **0,025 → 0,562**, et il gagne les
appariements qu'il perdait à 0,000 (racer) et 0,250 (alpha).

⚠️ Un sous-tournoi à trois bots ne se compare pas à un tournoi à six : seuls les appariements
communs le sont. Le tournoi complet des six, poids corrigés, reste à consigner ici.

**Le holdout** (`tactical_lookahead` contre `racer`, 8 épisodes) : **0,875**. Peu d'épisodes, donc
marge large — mais il joue, il ne lève pas, et il domine.

## 9. Résultats de l'étape 6 — panel corrigé (2026-08-11/12)

### 9.1 Quatre doctrines corrigées, toutes pour la MÊME cause

Chaque style décrivait « ce que je fais » sans jamais peser **ce qui fait gagner**. Les points se
comptent dès le tour 2 et la partie s'arrête au tour 5 : un bot qui gagne des combats en ignorant
les zones perd la partie. Les quatre corrections, mesurées en bot-contre-bot :

| bot | défaut | correction | effet |
|---|---|---|---|
| `endgame` | ne tenait AUCUN objectif avant le tour 4, soit la moitié des tours qui rapportent | `PUSH_TURN` 4→3, `w_objective` 0,3→0,9 | 0,025 → 0,562 |
| `racer` | visait en priorité les cibles qu'il ne pouvait PAS blesser, et **fuyait** l'ennemi tout en courant aux objectifs — il occupait les zones que personne ne dispute | `_score_contester` rend `None` au lieu de `0.0` ; `w_enemy` −0,1 → +0,2 ; facteur de distance 100 → 10 | 0,219 → 0,542 |
| `alpha` | chargeait **inconditionnellement**, y compris un tireur à 36" sur une cible qu'il n'entame pas au contact | seuil `MELEE_TRADE_FLOOR` ; `w_objective` 0,3→0,8 | 0,292 → 0,594 |
| `standoff` | `w_risk` = `w_fire` : refusait toute position exposée, donc reculait au lieu de tirer | `w_risk` 1,0→0,5, `w_objective` 0,6→1,0 | 0,396 → 0,365 (**sans effet**) |

⚠️ **Le bug de `_score_contester` mérite d'être retenu** : le score d'une cible valide vaut
`-distance × 10 + dégâts`, donc négatif ; rendre `0.0` pour « aucune arme ne peut la blesser » en
faisait le MEILLEUR score du lot. C'est exactement le défaut reproché à l'ancien panel — ignorer
si l'on peut blesser la cible — réintroduit par une erreur de signe dans le code censé le corriger.

### 9.2 `standoff` supprimé

0,92 / 0,90 / 0,97 contre trois agents de forces différentes : **amplitude 0,05**, dans le bruit.
Deux campagnes et une correction de poids n'y ont rien changé. Hypothèse retenue : l'axe
« se préserver, tenir ses distances » est **structurellement perdant dans ce format**, où le score
court dès le tour 2 et la partie s'arrête au tour 5 — un style qui attend n'a pas le temps d'être
payé. Non remplacé.

### 9.3 Mesure contre l'agent, panel corrigé

Même protocole qu'en §2, profil `x1_panel` (les cinq styles seuls).

| bot | 0.8330 | 0.8457 | 0.9438 | amplitude |
|---|---|---|---|---|
| **racer** | **0,56** | **0,64** | **0,66** | +0,10 |
| attrition | 0,60 | 0,65 | 0,79 | +0,19 |
| decapitation | 0,69 | 0,84 | 0,81 | +0,12 |
| alpha | 0,75 | 0,97 | 0,91 | +0,16 |
| endgame | 0,77 | 0,78 | 0,89 | +0,12 |
| **combined** | 0,716 | 0,798 | 0,839 | |

Trois acquis : `racer` tient l'agent à **0,66** là où `control` — le meilleur de l'ancien panel —
le laissait à 0,73 ; le combined passe de 0,899 (avant corrections) à **0,839**, soit le niveau de
l'ancien panel (0,846) avec un pire bot nettement meilleur ; et le panel **ordonne correctement**
les trois agents, ce qui est la propriété qui compte pour un thermomètre.

⚠️ **L'orthogonalité n'est PAS établie.** Trois modèles resserrés en force (0,833 / 0,846 / 0,944)
ne suffisent pas à décider si deux bots sont redondants. Le bot-contre-bot ne peut pas y répondre
non plus : il mesure la force relative, pas ce que chaque bot révèle de l'agent.

## 10. Ce qui reste ouvert — à lire avant de reprendre

1. **Étapes 7 et 8 non commencées** : correspondance ancien/nouveau puis suppression des cinq
   anciens, et mesure finale contre l'agent.
2. **VÉRIFIER LE MODÈLE CANONIQUE AVANT TOUTE MESURE COMPARABLE.** Le chemin canonique
   `ai/models/ArmageddonAgent/model_ArmageddonAgent.zip` est **partagé et volatil** : tout
   `ai/train.py --new` l'écrase, y compris un run de debug de 120 épisodes, et plusieurs sessions
   travaillent sur ce dépôt en parallèle. Il a déjà été consommé une fois (le 2026-08-11 à 23:14,
   `--test-only` rendait alors `Model not found`) puis remplacé deux fois dans la même journée.

   **Toutes les mesures des §11 et §12 portent sur `ArmageddonAgent_12345_robust_0.8721` :**

   ```bash
   md5sum ai/models/ArmageddonAgent/model_ArmageddonAgent.zip
   # 6f6b98059a0a6c279b7d11dc427461fd  = robust_0.8721, la référence de §11.3 et §12.5
   # 07ca14b4f0b4f62903718cece0ce1fdf  = robust_0.9438, la référence du §2 et de la colonne §11.2
   ```

   Réinstaller = copier le `.zip` **ET** son `_vec_normalize.pkl` apparié
   (`<stem>_vec_normalize.pkl`, cf. `ai/vec_normalize_utils.get_vec_normalize_path`). Un modèle
   chargé avec les statistiques de normalisation d'un autre run mesure autre chose.

   ⚠️ Pour une mesure longue, copier le modèle dans un `ai/models/` **privé au worktree** plutôt
   que de lire le chemin partagé : les workers d'évaluation chargent le modèle PARESSEUSEMENT, donc
   un training voisin qui l'écrase en cours de route fait lire un autre modèle à une partie des
   épisodes — sans que rien ne le signale. C'est ce qui a été fait pour la mesure du §12.5.
3. **Tous les chiffres des §8, §9.1 et §9.3 sont à rejouer** (cf. §11.1) : ils sont soit sous
   l'échantillon, soit arithmétiquement faux, soit mesurés sur un modèle de dégâts depuis corrigé.
4. **TROIS RESSOURCES PARTAGÉES rendent deux mesures simultanées incomparables.** Ce dépôt est
   travaillé par plusieurs sessions à la fois ; chacune de ces trois-là a déjà mordu :
   - **le modèle canonique** (cf. point 2) ;
   - **`step.log`** — un seul fichier, écrasé à chaque run `--step`. Deux sessions journalisant en
     même temps mélangent leurs épisodes dans le même fichier, et l'analyzer ne peut pas les
     démêler. Lancer depuis un worktree suffit à l'isoler ;
   - **les JSON de `config/`**, relus À CHAUD par les évaluations. Régler des poids pendant qu'une
     mesure tourne change ce qu'elle mesure en cours de route. `pgrep -af train.py` avant, et ne
     rien toucher tant que ça tourne.
   S'y ajoute le CPU : une évaluation occupe 4 à 6 workers. Deux en parallèle se ralentissent
   mutuellement d'un facteur 2 — mesuré le 2026-08-12 (0,70 puis 0,35 ép./s).

## 11. Relecture du 2026-08-12 — ce qui a été trouvé, mesuré et décidé

Relecture complète du chantier, code en main. Trois livraisons en sont sorties.

### 11.1 Ce que les mesures ne soutenaient pas

Le pool holdout compte **4 scénarios**, et `--episodes` de `bot_ranking.py` compte *par
appariement **et** par scénario*. « 8 épisodes » pour deux bots = 2 appariements × 4 scénarios × 1
épisode : c'est `--episodes 1` qui a servi partout. Le tournoi des six (« 120 épisodes ») donne
donc **40 épisodes par bot**, soit ±15,5 points à 95 %.

Rejoué à **n = 384 par bot** (±5,0), poids corrigés, `tactical_lookahead` exclu :

| bot | mesuré n=384 | annoncé §8 (n=40) | annoncé §9.1 |
|---|---|---|---|
| decapitation | 0,570 | 0,700 | — |
| racer | 0,565 | 0,450 | 0,542 ✅ |
| alpha | 0,529 | 0,425 | 0,594 |
| attrition | 0,464 | **0,725 (1er)** | — |
| endgame | **0,336** | 0,025 | 0,562 ❌ |

- **`endgame` n'est pas remonté à 0,562.** Il est **dernier**, à 0,336, avec 12,8 points d'écart
  au 4ᵉ pour une marge de 5. La correction l'a bien sorti du 0,025, elle ne l'a pas rendu
  compétitif. Le « sous-tournoi à trois, 16 épisodes » qui fondait ce 0,562 est en outre
  **arithmétiquement impossible** avec cet outil (6 appariements × 4 scénarios = 24 minimum).
- **`attrition` s'effondre de 1ᵉʳ (0,725) à 4ᵉ (0,464)** alors que **ses poids n'ont pas été
  touchés** — §9.1 ne corrige qu'`endgame`, `racer`, `alpha` et `standoff`. C'est la démonstration
  directe que le classement du §8 était du bruit.
- **Les « avant » du §9.1 contredisent le §8** : racer y vaut 0,219 contre 0,450, alpha 0,292
  contre 0,425. Deux tournois différents comparés comme s'ils étaient le même — ce que le §8
  s'interdit lui-même deux lignes plus bas.
- **Le `combined` du §9.3 n'est pas la combinaison de sa propre colonne.** Les poids de `x1_panel`
  sont uniformes, donc le combined doit être la moyenne simple : elle vaut 0,674 / 0,776 / 0,812,
  pas 0,716 / 0,798 / 0,839. L'arrondi à 2 décimales plafonne à ±0,005. Contrôle négatif : le §2
  se recalcule **exactement** (0,4 × 0,73 + 0,15 × 3,69 = 0,8455 ✓). Le 0,899 « avant corrections »
  n'est sourcé nulle part.
- **« Le panel ordonne correctement les trois agents »** ne vaut que pour l'agrégat : par bot,
  **3 des 5** inversent les deux meilleurs modèles. Et l'ordre « vrai » de ces trois modèles vient
  de leurs noms, c'est-à-dire du verdict de l'**ancien** panel — la validation est circulaire.
- **§9.2 (`standoff`)** : une amplitude de 0,05 est indétectable au régime d'échantillon employé.
  La suppression peut être la bonne décision ; sa justification *mesurée*, elle, n'existe pas.

### 11.2 Le holdout à un coup, supprimé

Mesuré sur le code final, pas sur des étapes intermédiaires :

- **coût : 9,5×** un bot normal (209,8 s contre 22,2 s pour 16 épisodes identiques), pas les « ~5× »
  qu'annonçait le §10 ;
- **force : 0,431 [0,354 ; 0,508] sur 160 épisodes**, dernier derrière `decapitation` (0,537) et
  `racer` (0,463). Le « 0,875, il domine » du §8 est réfuté ;
- **il n'a jamais affronté l'agent** : `tactical_lookahead` n'était dans le `bot_eval_weights`
  d'aucun des neuf profils.

Sa raison d'être (§3.3) — « un agent qui apprend à battre des heuristiques pondérées bat par
construction une heuristique pondérée plus forte » — est un bon argument, mais sa seule prédiction
testable est contredite : à 9,5× le prix, il fait jeu égal avec elles. Sa propre docstring disait
pourquoi il ne pouvait pas mieux faire : en mouvement il ne juge que 12 destinations retenues par
un score géométrique **sans simulation**. Un chercheur à qui l'on présélectionne les coups par
heuristique n'est plus un chercheur.

Supprimés avec lui : `ai/bot_holdout.py`, le mécanisme `NEEDS_ENGINE` de `BotControlledEnv` (plus
aucun client) et leurs deux fichiers de tests. `tactical` reste l'ancien `TacticalBot`.

⚠️ Ses verrous tournaient tous contre un **moteur factice** de 6 attributs, écrit pour muter
exactement les trois fuites déjà connues — alors que leur docstring affirmait comparer « l'état
COMPLET du moteur ». Ils n'auraient pas détecté une **nouvelle** fuite du vrai moteur. À se
rappeler avant de reprendre cette idée.

### 11.3 `scorer`, le style qui manquait

`ControlBot` — le seul des six d'origine à porter de l'information (0,73 quand les autres
saturaient au-dessus de 0,87) — n'avait **aucun remplaçant** dans le panel refondu : `racer` est sa
caricature (il refuse le combat sans condition), `alpha`/`attrition`/`decapitation` jouent les
pertes, `endgame` attend. `ScorerBot` reprend l'axe : cible qui conteste, charge seulement quand
elle ne coûte pas une zone tenue, déplacement vers les zones en acceptant l'exposition qui paie.

Il occupe le créneau libéré par le holdout, à **1×** son coût. Le panel repasse à six styles — non
par arithmétique, mais parce que l'axe est réel.

⚠️ **Ses poids ne sont PAS réglés** (`config/bot_movement_weights.json`, entrée `scorer`) : posés
par doctrine, à établir en bot-contre-bot avant toute mesure contre l'agent.

### 11.4 Deux défauts récupérés du holdout avant de le supprimer

Le travail en cours sur le holdout, non commité au moment de sa suppression, contenait deux
constats qui ne mouraient **pas** avec lui. Ils ont été portés sur les styles qui restent.

- **La durée d'une bataille se lit sur l'état.** `EndgameBot` basculait en mode poussée à
  `PUSH_TURN = 3`, déduit à la main de « la partie dure 5 tours ». Sur un scénario plus court la
  bascule tombait après la fin ; sur un plus long, le style devenait un Racer dès le premier
  tiers. Le seuil s'exprime désormais en **tours restants** (`PUSH_LAST_TURNS = 3`) et la durée
  vient de `get_effective_turn_limit`. ⚠️ **Comportement inchangé sur la bataille standard** :
  5 − 3 + 1 = tour 3, exactement l'ancien réglage — les chiffres du panel restent comparables.
- **`game_state.get("turn", 1)`**, deux fois, était un défaut posé pour éviter une `KeyError`
  (T1). Chez `EndgameBot` un état cassé se lisait « avant la bascule » ; chez `DecapitationBot`,
  plus grave, le marqueur de tour devenait **constant**, donc le bot gardait la même cible
  focalisée toute la partie — sa doctrine entière s'annulait en silence. Les deux lèvent.

Verrou : `tests/unit/ai/test_bot_doctrine_battle_length.py` (7 tests), dont un ancre la
non-régression sur 5 tours. Vérifié rouge en remettant la constante : 3 tests tombent.

Un troisième élément de ce travail, `engine.game_state.army_value_by_player` (source unique du
départage de fin de partie), est **indépendant du holdout** et reste à l'autre chantier — il
n'était pas encore commité.

### 11.5 Le modèle de dégâts, corrigé à la racine

Voir §7.1. En résumé : l'estimation par escouade ne lisait que le profil du soldat de base, donc
50 paires sur 90 étaient fausses (médiane 0,50×, pire cas 0,18×). Le cache est désormais indexé par
figurine. **Aucun ré-entraînement n'est requis** — contrairement à ce qui était supposé, le seul
consommateur vivant du cache était le panel de bots.

## 12. Les bots ne contestaient rien — corrigé le 2026-08-12

### 12.1 Le constat, venu du replay puis confirmé par le journal

Observation de l'utilisateur en regardant un replay : « l'agent joue mal, super passif, mais ça
passe car le bot est encore plus nul ». Un win-rate contre des bots est une mesure **relative** :
il ne peut pas, par construction, détecter que les deux camps jouent mal. Rien dans tout ce
chantier ne mesurait le niveau **absolu** de jeu.

Le journal du run du 2026-08-12 (600 épisodes, ancien panel, `analyzer.py`) le chiffre :

- **0 victoire par élimination**, des deux côtés. Aucune armée n'est jamais détruite.
- **100 % des parties vont au tour 5.** Aucune ne se conclut avant.
- **207 épisodes sur 600 (34,5 %) sans aucun mort.** 689 escouades détruites en 600 parties, pour
  dix escouades sur la table.
- **Les charges font 0,8 % / 1,0 % des actions.**
- **~34 % des décisions de phase de tir se prennent sans cible visible** (`no LOS`).
- VP moyens : **agent 53,8 sur 60**, bot **27,2**.

⚠️ Les colonnes « Joueur 1 / Joueur 2 » de l'analyzer sont par NUMÉRO DE JOUEUR, et l'agent occupe
P1 sur 240 épisodes et P2 sur 360 : ce sont des mélanges, on ne peut pas leur faire dire « l'agent
fait ceci ». Seuls les tableaux étiquetés *Agent/Bot* le permettent.

**L'agent n'est pas passif par défaut d'apprentissage : la passivité gagne.** Le primaire court à
15 VP/tour du tour 2 au tour 5, tuer ne rapporte rien directement, l'élimination n'arrive jamais et
le départage de valeur ne décide que 1,4 % des parties. Il a résolu le jeu tel qu'il est posé.

**Et c'est ce qui explique l'échec de l'orthogonalité (§11.2).** Le scénario n'a qu'une dimension —
seuls les objectifs marquent. Aucun dessin de bot ne créera six axes dans un jeu qui n'en compte
qu'un. Le seul bot qui inquiétait l'agent était `racer`, celui qui joue les zones : ce n'était pas
une coïncidence.

Piste écartée par l'utilisateur : les 34 % de tirs sans cible viennent du terrain, et **les
plateaux sont réglementaires** — ce n'est pas un défaut à corriger.

### 12.2 La cause, prouvée par absence

`objective_controllers` **n'était lu nulle part** dans `ai/bot_doctrines.py`. Aucun chemin ne
permettait à un des six styles de savoir qui tenait quoi. Et `_objective_terms` réduisait les
cartes par `np.minimum.reduce` : chaque escouade partait vers **l'objectif le plus proche d'elle**.

Conséquence : chaque camp s'asseyait sur les zones de son côté de la table et personne n'allait
disputer celles d'en face. Le bot marquait 6,8 VP/tour (≈ une zone), l'agent 13,5 (≈ le maximum).

### 12.3 La correction

La carte de distance combinée est désormais **pondérée par qui tient quoi** : un rabais en HEXES
est retiré de la distance de chaque objectif, double pour une zone tenue par l'adversaire (la lui
prendre fait basculer le score des deux côtés), simple pour une zone neutre, nul pour la sienne
(y envoyer une deuxième escouade ne rapporte rien).

Cinquième poids par style, `w_contest`, **dans le même tuple que les quatre autres** : `EndgameBot`
et `AttritionBot` échangent l'entrée entière selon leur mode (`endgame_push`, `attrition_withdraw`),
donc un poids chargé à part resterait sur la valeur du mode précédent.

`w_contest = 0.0` rend exactement la carte d'avant — le changement est donc mesurable style par
style. Le rabais est appliqué **une fois par décision**, pas par candidate : le coût est une
soustraction numpy par objectif, déjà payée par la mémoïsation des cartes.

⚠️ **Les valeurs sont POSÉES PAR DOCTRINE, non réglées** (`config/bot_movement_weights.json`).

⚠️ `objective_controllers` est lu tel quel, donc **rafraîchi aux frontières de phase seulement**.
C'est correct ICI, et c'est l'inverse de ce qu'exigeait le holdout supprimé : on veut savoir qui
tenait la zone au début de la phase, pas recalculer par candidate — la cible d'un déplacement ne
doit pas changer en cours de route. Son absence (dict créé paresseusement) vaut « personne ne tient
rien », l'état réel en début de partie et non un repli.

### 12.4 `w_contest` seul était inerte — la vraie cause était l'empilement

La pondération par le contrôleur (§12.3) a été mesurée : **aucun effet**. Combined 0,869 → 0,872
sur le même modèle, tous les bots dans ±2 points pour une marge de ±6 à 7. Un zéro franc.

L'arithmétique l'explique : une escouade posée sur sa zone a une distance nulle **et** touche le
`hold_bonus`. Pour `racer` rester vaut +3,9 ; partir vers une zone adverse à 12 hexes avec 8 de
rabais vaut −5,2. Le rabais n'agit donc que sur les escouades **pas encore garées**, c'est-à-dire
avant le tour 2.

**Le vrai gaspillage est l'empilement, et il se mesure.** Dépouillement de 600 parties :

| tour | escouades bot dans une zone | zones couvertes | **escouades par zone** |
|---|---|---|---|
| 2 | 4,22 | 1,49 | **2,85** |
| 3 | 5,03 | 1,67 | **3,01** |
| 5 | 5,00 | 1,92 | **2,61** |

L'agent étale ses cinq escouades sur 2,90 zones (~1,7 par zone). Les bots les tassent à trois par
zone. Les deux autres hypothèses sont écartées par la même lecture : **vitesse** non (92 % de
l'armée est dans une zone dès le tour 3), **OC** non (le bot contrôle 1,66 des 1,92 zones où il est
présent — il ne perd pas les décomptes, il est absent).

Et c'est pourquoi `w_contest` ne pouvait rien donner : quand cinq escouades calculent la même
réponse chacune dans son coin, rendre une zone plus attirante **déplace le tas**, il ne le disperse
pas.

### 12.5 La pénalité d'encombrement — le seul changement qui ait déplacé les chiffres

Sixième poids, `w_crowd`. Une zone déjà servie par les alliés coûte plus cher à l'escouade
suivante. C'est le dual du `hold_bonus`.

**Terme de score, pas ordre d'en haut.** Une affectation d'armée avait été envisagée puis écartée :
elle aurait imposé une zone à `alpha` (qui va au contact) et à `decapitation` (qui poursuit une
escouade), donc détruit ce qui les distingue, et exigé une table d'affectation avec sa péremption.
Ici chaque style garde ses poids et voit simplement qu'une zone est servie.

**La pénalité porte sur le SURPLUS d'OC**, `max(0, mon_OC − son_OC)` par zone, hors l'escouade qui
décide. Une zone disputée n'est donc pas pénalisée — les renforts y vont — et une zone gagnée large
repousse la suivante. En OC et non en nombre d'escouades : deux Gretchin et un Carnifex ne pèsent
pas pareil, et le contrôle se tranche à la somme des OC.

**Aucune mémoire de tour n'est nécessaire** : les escouades s'activent l'une après l'autre et
l'état est à jour entre deux activations, donc la présence physique porte déjà les déplacements
qui viennent d'être joués.

Mesure, même modèle `robust_0.8721`, `x1_panel`, 100 ép./bot :

| | avant | après |
|---|---|---|
| escouades par zone (T5) | 2,61 | **1,28** |
| zones couvertes (T5) | 1,92 | **2,47** |
| zones contrôlées (T5) | 1,61 | **1,90** |
| VP bot | 27,8 | **31,0** |
| écart de VP | 16,4 | **10,0** |
| pire bot (`racer`) | 0,78 | **0,62** |
| **combined** | **0,873** | **0,788** |

Par bot : `racer` −0,16, `endgame` −0,15, `scorer` −0,12, `attrition` −0,11, `decapitation` +0,03,
`alpha` 0,00. Les deux derniers sont dans le bruit à n=100 (±8 à 9 points) ; les quatre premiers
non.

⚠️ **Poids POSÉS par doctrine, non réglés.**

⚠️ Le run a duré 1730 s contre 863 s. Ce **n'est pas** le coût du calcul : mesuré à **0,02 ms par
décision, 3 ms par épisode**, soit 0,2 % de l'écart. Les bots font simplement plus de chemin et
plus de contact — il reste 4,76 escouades vivantes au tour 5 contre 5,27 avant.

⚠️ **Le mur du tour 2 tient toujours** : 1,61 zone couverte au tour 2 (contre 1,49). Tout le gain
arrive aux tours 3 à 5. Le prochain levier, s'il en faut un, est le déploiement.
