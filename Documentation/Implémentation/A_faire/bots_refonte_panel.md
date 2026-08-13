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
| 6 | réglage en **bot-contre-bot** (~~orthogonalité~~ abandonnée, §3.2) | ✅ **2026-08-13, §12.8 à §12.14** — les deux hausses du §12.7 réfutées et défaites (§12.8) ; `scorer`, dernier profil posé sans mesure, réglé (§12.9) ; `decapitation` corrigé au déplacement puis son `w_objective` rejoué sur la forme retenue (§12.11, §12.14). Tous mesurés à 60 ép./bot, un poids par run, dérive des cinq contrôles 0,000. ⚠️ Restent `decapitation.w_crowd` et `w_contest`, jamais isolés APRÈS le correctif (§12.14) |
| 7 | correspondance ancien/nouveau, puis suppression des cinq anciens | |
| 8 | mesure finale contre l'agent, commande de §2 | ✅ **2026-08-13, §12.14** — 100 ep/bot sur `robust_0.8721`, panel unifié : `combined = 0,7433`, pire bot `racer = 0,630`, pire scénario 0,6867. Les `0,7767`, `0,7600` et `0,7400` sont des états intermédiaires de la même journée |

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

1. **Étape 7 non commencée** : correspondance ancien/nouveau puis suppression des cinq anciens.
   L'étape 8 est close (§12.8, `combined = 0,7767`).
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
   épisodes — sans que rien ne le signale. C'est ce qui a été fait pour la mesure du §12.5, puis
   pour celle du §12.8.

   ✅ **`scripts/bot_zone_direct.py` n'a plus besoin de cette copie** (2026-08-13) : son `--model`
   vise l'archive nommée et il **imprime le md5 chargé** au-dessus du tableau. `ai/train.py`, lui,
   n'a pas d'équivalent — son `--model` n'est lu que par `--replay` (vérifié : c'est le seul usage
   de `args.model` dans le fichier) — donc toute mesure passant par `--test-only` reste tributaire
   du chemin canonique, et de la copie privée.
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

⚠️ **CES CHIFFRES SONT ANTÉRIEURS AU §12.6.** Ils ont été obtenus avec les deux défauts corrigés
là-bas : les profils à `w_crowd` fractionnaire n'avaient donc **aucune** pénalité, et le surplus se
comptait autrement que le contrôle réel.
✅ **REJOUÉS le 2026-08-13, §12.8** : `combined = 0,7767` et pire bot `racer = 0,630` post-§12.6,
contre 0,788 et 0,62 ici. L'amplitude annoncée tient à la marge près — c'est la ligne
« zones contrôlées / VP / escouades par zone » de cette table qui reste, elle, non rejouée.

### 12.6 Deux défauts de la pénalité et le trou de test qui les cachait — 2026-08-12

Trouvés en relisant le verrou de la §12.5, pas en jouant : le test d'ensemble d'alors posait ses
deux zones à distance ÉGALE, or la carte rendue est leur **minimum**. Appliquer la pénalité à la
mauvaise zone rendait donc exactement la même valeur, et le test restait vert. Il est maintenant
écrit avec deux distances différentes, et une mutation qui inverse cartes et zones le fait rougir.

**a) Les poids inférieurs à 1 étaient purement annulés.** Le score de destination tronquait la
distance à l'entier **avant** d'appliquer les poids. Or la carte n'est plus la distance entière du
moteur : `_objective_terms` y a déjà ajouté `w_crowd × surplus` et retranché le rabais de
contestation, tous deux fractionnaires. Avec `w_crowd: 0.5` et un surplus de 1, `5 + 0,5` se
relisait `5` — aucune pénalité. Deux profils du panel sont dans ce cas, et `w_contest` à `1.5` /
`3.5` perdait de même sa demi-unité. C'est le **même « poids inerte »** que la §12.4 reproche à
`w_contest` : les paliers bas du panel ne mesuraient pas ce qui y était écrit.

**b) Le surplus ne comptait pas comme le moteur compte.** Il tranchait la présence sur l'hexe
**centre** de chaque figurine et ignorait la règle 01.07, quand `sum_objective_control_oc_multi`
compte dès qu'une case de l'**empreinte de socle** recouvre la zone et retire les escouades
battle-shockées (02.02, leur OC vaut `-`). Les deux écarts poussaient vers le défaut que ce §12
corrige : un gros socle au bord tenait la zone pour le moteur mais pas pour le bot, qui y renvoyait
une escouade de plus ; une escouade choquée fabriquait à l'inverse un surplus **fantôme** et faisait
déserter une zone que le camp ne tenait pas.

Le surplus est désormais **dérivé** du décompte du moteur : celui-ci rend les contributions par
escouade, et le bot écarte la sienne par un filtre. Il n'y a donc plus deux comptages de contrôle
à garder en phase — c'était le motif ancre-contre-par-figurine, déjà payé plusieurs fois dans ce
dépôt. (Une version intermédiaire de ce §12.6 faisait passer un `exclude_unit_id` au moteur ;
c'est ce qu'a corrigé la décomposition décrite plus bas.)

Coût **mesuré** (10 escouades × 5 figurines, 5 zones) : **0,043 ms par décision**, contre 0,014 ms
pour le comptage maison. Le calcul est fait une fois par DÉCISION, pas par candidate — à comparer
aux **2,88 ms** que coûte la boucle de score qui l'entoure (458 candidates × 25 ancres ennemies) :
le surcoût introduit vaut **1 % de la décision**.

⚠️ Ne PAS écrire, comme une première version de cette section le faisait, que « le moteur paie déjà
la même passe à chaque step pour l'observation ». C'est faux : `ObservationBuilder`
`_squad_objective_control` relit `objective_controllers`, l'état persistant, et n'appelle jamais
`sum_objective_control_oc_multi`. Ses appelants réels sont `calculate_objective_control` (aux
frontières de phase), le wrapper mono-zone, et ce surplus.

**Deux suites données le même jour, sur décision de l'utilisateur.**

*Le décompte de contrôle, moitié moins cher.* Le temps partait dans le générateur d'empreintes,
alors qu'à `inches_to_subhex == 1` tous les socles sont normalisés en `round`/1 et que l'empreinte
y vaut toujours l'ancre. Trois changements : `iter_living_model_footprints` rend `{(col, row)}`
directement dans ce cas, les conversions d'ancre ne sont plus faites deux fois, et une empreinte
disjointe de l'UNION des zones saute la boucle par zone (filtre exact : disjoint de l'union ⇒
disjoint de chacune).

Mesuré **entrelacé** (round-robin, même processus, résultats assertés identiques), sur cinq zones
de **2000 hexes** — la taille réelle du scénario d'entraînement : **−51 %** à 12 escouades × 6
figurines, **−62 %** à 20 × 10.

⚠️ **DEUX PIÈGES DE MESURE, tous deux tombés dedans le 2026-08-12 avant d'être rattrapés.**
1. *Mesurer en deux processus séquentiels.* La dérive atteint ±40 % sur cette machine ; une
   première mesure ainsi obtenue annonçait −42 % pour le seul générateur là où l'entrelacé rend
   −41 à −46 %. Toute mesure de ce poste doit être entrelacée.
2. *Mesurer sur des zones jouets.* Le pré-filtre a d'abord été validé sur des zones de 9 hexes, où
   reconstruire l'union à chaque appel semblait gagner 29 %. Aux 2000 hexes réels, la même
   reconstruction coûte **+625 %** — six fois le coût qu'elle prétend éviter. C'est la mémoïsation
   de l'union (`objective_hexes_union`) qui rend le filtre payant, et elle seule.

Le gain porte aussi sur `calculate_objective_control` et `unit_is_within_objective`, qui
consomment le même générateur.
⚠️ **Un défaut du moteur a été trouvé en chemin, et corrigé** (arbitrage tranché par l'utilisateur).
`socle_is_single_hex`, qui se déclare source unique du prédicat « ce socle tient-il dans une
case ? », rendait `True` pour un `round` de taille NON SCALAIRE — état que le validateur de
datasheet refuse et sur lequel le calcul d'empreinte LÈVE (mesuré sur 1 344 couples forme/taille).
Il affirmait donc « une seule case » exactement là où le calcul refuse de répondre. C'était le
résidu du prédicat naïf `not isinstance(base_size, int)` que ce dépôt avait déjà corrigé deux fois
ailleurs, et il vivait dans la fonction censée l'avoir remplacé. La forme tranche maintenant
d'abord, puis la taille, qui doit être scalaire. Le prédicat reste volontairement CONSERVATEUR
dans l'autre sens (`round`/2 et `square`/1 sont classés multi-hexes alors que leur empreinte est
l'ancre) : un « non » de trop ne coûte qu'un calcul, un « oui » de trop fait sauter tous les
contrôles de mur et de chevauchement du masque de mouvement.
La variante « carte plate cellule → index de zone » a été mesurée et REJETÉE (aucun gain,
régression à 20 escouades).

*La décomposition par escouade.* `objective_control_contributions` devient la source unique du
comptage et rend `{escouade: (joueur, [OC par zone])}` ; le pli qui ramène ces parts à `(OC1, OC2)`
par zone est lui aussi exposé (`fold_control_contributions`), et `sum_objective_control_oc_multi`
n'est plus que la composition des deux. Sans ce pli partagé, chaque appelant réécrivait sa double
boucle d'agrégation — la série des contrefactuels aurait changé de nature au lieu de se fermer. Le `exclude_unit_id` ajouté plus haut dans ce §12.6 **disparaît** : il faisait
porter une question HYPOTHÉTIQUE de l'IA (« qui tiendrait quoi si je n'étais pas là ») à la
fonction qui énonce la RÈGLE, et le contrefactuel suivant — « sans mes escouades condamnées », « si
je me posais ici » — aurait ajouté son paramètre à son tour. Le surplus compose maintenant son
exclusion par arithmétique. Coût : nul à la mesure (0,034 ms pour les contributions contre 0,037 ms
pour la somme complète).

**c) Le câblage est enfin testé par l'entrée publique.** Aucun test n'instanciait de bot de
doctrine : tout s'arrêtait aux fonctions privées, et trois décisions n'étaient couvertes par rien
— l'ordre des six poids déballés, le joueur, l'identité de l'escouade activée. Intervertir
`w_contest` et `w_crowd` laissait les quinze tests des deux fichiers verts. Un test joue maintenant
`select_movement_destination` sur deux destinations, une zone servie contre une zone libre.

⚠️ **À REJOUER** : la mesure du §12.5 sur 600 parties. Les poids agissent désormais tels qu'ils sont
écrits dans `config/bot_movement_weights.json`, ce que les chiffres actuels ne reflètent pas.
✅ **REJOUÉE le 2026-08-13, §12.8** (100 ep/bot, `robust_0.8721`) : `combined = 0,7767`, pire bot
`racer = 0,630`. Corollaire à retenir : les deux défauts corrigés ici ne déplaçaient PAS le
résultat d'ensemble — c'est bien la pénalité elle-même qui portait le gain, pas la moitié qui
agissait.

### 12.7 Calibration `w_crowd`/`w_contest` par étalement (2026-08-13) — ⛔ INVALIDÉE

> ⛔ **SECTION INVALIDÉE le 2026-08-13, conservée exprès.** Ses chiffres ne valent rien et ses
> deux corrections de poids ont été DÉFAITES (cf. §12.8). Elle reste ici parce que c'est la
> MÉTHODE qu'il ne faut pas refaire, et les trois défauts ci-dessous sont chacun suffisant à eux
> seuls pour annuler la conclusion :
>
> **(a) L'instrument n'était pas celui décrit.** Les deux runs ont été joués avec une version de
> `scripts/bot_zone_direct.py` où la graine de base valait `42` en dur et où l'instantané des
> zones était pris AVANT le `step`. Le script consigné depuis lit `tc["seed"]` (12345) et relève
> APRÈS. Aucun des tableaux ci-dessous n'est donc rejouable, ni comparable à quoi que ce soit.
> Et le défaut était PLUS PROFOND qu'un décalage de valeurs : l'instrument consigné, lui, est
> déterministe (§12.8), donc les 0,10 à 0,30 d'écart entre les deux runs sur des bots NON MODIFIÉS
> ne sont pas une marge d'échantillonnage — cette version-là ne rejouait pas les mêmes parties.
>
> **(b) La « référence panel » citée n'existe pas.** La ligne « §12.5 (post-§12.6) : T2=1.61,
> T5=1.90 » est fausse deux fois : le §12.5 déclare lui-même ses chiffres ANTÉRIEURS au §12.6, et
> 1,61 → 1,90 y est le couple **avant → après** d'une SEULE métrique (zones contrôlées au T5),
> pas un T2 suivi d'un T5. Toute la lecture « alpha est sous la référence » repose sur ce chiffre
> inventé.
>
> **(c) Le « seuil `w_crowd` > 1.5 » est faux, et la table le montrait déjà.** Il est contredit
> par ses propres lignes — `endgame` et `attrition` sont à `w_crowd = 1.0` et ne déclinent pas —
> et par le code : dans `select_movement_destination` (`ai/bot_doctrines.py`), le `hold_bonus`
> est ajouté à TOUTE destination située dans une zone, y compris celle où l'escouade voudrait
> partir. Il **s'annule donc entre deux zones** et n'a jamais été le terme à franchir. Ce qui
> retient une escouade sur sa zone, c'est la DISTANCE à l'autre zone : rester bat partir dès que
> `w_crowd × (surplus_ici − surplus_là-bas) < distance`. Ne jamais réutiliser ce seuil.
>
> **Ce que le §12.8 en retient quand même** : `decapitation` décline bien entre T2 et T5, et ça,
> c'est vrai (mesuré à nouveau, n=60). Le reste — le diagnostic, le seuil, les valeurs 2.0 — est
> à jeter.

Instrument : `scripts/bot_zone_direct.py --episodes 20`, plateau `x1` (board/44x60x1), modèle
`robust_0.8721`. Lit `game_state["objective_controllers"]` directement — contourne le problème
step.log non-journalisé en bot eval.

Référence panel (§12.5, **pre-§12.6, jamais rejouée**) : **T2=1.61, T5=1.90**. Le « post-§12.6 »
qu'a porté cette ligne jusqu'au 2026-08-13 était faux et contredisait le §12.5 lui-même (cf. ses
deux avertissements, « CHIFFRES ANTÉRIEURS AU §12.6 » et « À REJOUER ») ; `scripts/bot_zone_direct.py`
l'avait recopié. La référence chiffrée n'a plus qu'une source dans le code,
`scripts/bot_panel_reference.py`, d'où les scripts du panel l'impriment.

Seuil effectif pour `w_crowd` : `w_crowd × OC_surplus(≈2) > hold_bonus(3.0)` → **`w_crowd > 1.5`**.
En dessous, le penalty anti-stacking est inactif — les bots s'empilent sur une zone et n'en
bougent plus. Les deux profils à `w_crowd: 0.5` étaient sous ce seuil.

**Mesure avant (20 ep) :**

| Bot | w_crowd | T2 | T5 | Diagnostic |
|-----|---------|----|----|-----------|
| alpha | 0.5 | 1.10 | 0.75 | Déclin — stacking actif |
| decapitation | 0.5 | 1.35 | 0.95 | Déclin — stacking actif |
| endgame | 1.0 | 1.50 | 1.95 | OK (doctrine patience, T5 ≈ réf.) |
| attrition | 1.0 | 1.85 | 2.05 | OK |
| scorer | 2.5 | 1.85 | 1.90 | OK |
| racer | 3.0 | 2.20 | 2.30 | OK |

**Correction appliquée :**

- `alpha` : `w_crowd` 0.5 → **2.0** (penalty = 4.0 > hold_bonus). `w_contest` inchangé (1.0) : le
  bot chasse déjà les ennemis via `w_enemy=1.2`.
- `decapitation` : `w_crowd` 0.5 → **2.0** + `w_contest` 1.0 → **1.5** : `w_enemy=0.6` plus faible,
  pull supplémentaire nécessaire pour contester.

**Mesure après (20 ep) :**

| Bot | T2 avant→après | T5 avant→après |
|-----|---------------|----------------|
| alpha | 1.10 → **1.35** | 0.75 → **1.00** |
| decapitation | 1.35 → **1.85** | 0.95 → **1.60** |

Le déclin est arrêté sur les deux profils. `alpha` reste sous la référence T5 (1.00 vs 1.90) par
construction de la doctrine (poursuite ennemie prioritaire) — ce n'est pas un défaut à corriger.
`decapitation` passe de 0.95 à 1.60, amélioration significative.

**Bots non modifiés (mesures cohérentes entre les deux runs) :**

| Bot | T2 run1 | T2 run2 | T5 run1 | T5 run2 |
|-----|---------|---------|---------|---------|
| attrition | 1.85 | 1.95 | 2.05 | 2.05 |
| racer | 2.20 | 2.15 | 2.30 | 2.60 |
| scorer | 1.85 | 2.05 | 1.90 | 2.20 |
| endgame | 1.50 | 1.40 | 1.95 | 1.95 |

> ⛔ Cette dernière table est le signe qui aurait dû arrêter la conclusion sur place : quatre bots
> NON MODIFIÉS bougent de 0,10 à 0,30 entre deux runs à graines censément identiques. Ce n'était
> pas du bruit — l'instrument consigné rend, lui, des relevés IDENTIQUES AU BIT d'un run à l'autre
> (§12.8). Un contrôle qui dérive dénonce un défaut de protocole, jamais une marge d'erreur.

⚠️ **CES CHIFFRES NE SONT PAS REPRODUCTIBLES** (constaté le 2026-08-13, cf. §12.11) : l'instrument
lisait alors le chemin **canonique** du modèle, que tout entraînement réécrit — il ne mesurait donc
pas `robust_0.8721` malgré ce qui est écrit ci-dessus. Rejoués à 60 ép. sur le modèle de référence,
les quatre bots de contrôle donnent 1.67/2.08 (attrition), 1.77/2.07 (racer), 1.65/1.93 (scorer),
1.57/2.08 (endgame). Son **sens** ne tient pas davantage : le seuil `w_crowd > 1.5` a ete mesure ISOLEMENT au §12.8 et
refute — monter `w_crowd` RETIRE des zones a `alpha`, et ne rend rien a `decapitation`.

### 12.8 Recalibration de `w_crowd`/`w_contest`, refaite proprement (2026-08-13)

Reprise complète après invalidation du §12.7. Rien n'y est repris : ni la référence, ni le seuil,
ni les tableaux.

**Ce qui a été rétabli avant de mesurer.** Les deux hausses du §12.7 ont été DÉFAITES —
`alpha.w_crowd` et `decapitation.w_crowd` 2.0 → 0.5, `decapitation.w_contest` 1.5 → 1.0 — et les
deux `_justification` qui invoquaient le faux seuil, supprimées. Mesurer à partir de poids posés
sur une mesure invalidée aurait fait porter le même doute à toute la suite.

#### L'instrument, et ce qu'il change au protocole

`scripts/bot_zone_direct.py`, corrigé sur deux points :

- **le modèle ne se lit plus au chemin canonique.** `--model` pointe l'archive nommée
  `ArmageddonAgent_12345_robust_0.8721.zip`, que rien n'écrase, et le **md5 chargé est imprimé
  au-dessus de chaque tableau**. Le chemin `model_ArmageddonAgent.zip` portait ce jour-là
  `1072b0c6…`, soit un AUTRE modèle : toute mesure lancée sans ce garde aurait été muette
  là-dessus (c'est le §10.2, qui n'était pas armé dans l'instrument) ;
- **`--json-out`** consigne le relevé PAR ÉPISODE, plus les poids réellement consommés
  (`load_doctrine_weights`, pas une copie du fichier) et le `hold_bonus`. C'est ce qui rend la
  comparaison APPARIÉE possible.

**Le script est reproductible au bit, et c'est ça qui porte le protocole.** Deux exécutions
consécutives à graines identiques rendent des `--json-out` dont le `diff` est vide hors
l'étiquette. La politique joue en `deterministic=True` et `W40KEngine.reset` sème `random` avec la
graine d'épisode, ce qui couvre la part aléatoire des bots. Trois conséquences, toutes utilisées
ci-dessous :

1. **la dérive d'un bot de contrôle vaut exactement 0,000** — vérifié à chaque run, sur les cinq
   bots non modifiés et sur les quatre tours. Ce n'est plus une marge à franchir, c'est un
   INVARIANT : un contrôle qui bouge signe une erreur de protocole (modèle, plateau ou graine
   changés en route), et le run est à jeter, pas à moyenner ;
2. **la comparaison est appariée** : l'épisode *i* de deux runs ne diffère que par le poids changé,
   donc l'écart se lit épisode par épisode. L'erreur-type de la différence est 3 à 4 fois plus
   petite que celle des moyennes prises séparément (±0,08 contre ±0,13 en combinant deux ±0,09) ;
3. **le « n ≥ 60 » ne sert plus à couvrir une dérive** — il n'y en a pas — mais à échantillonner
   assez de parties pour que l'écart, lui, sorte du bruit d'échantillonnage.

⚠️ Deux `random.seed`/`np.random.seed` par épisode ont été ajoutés en tête de boucle, copiés de
`ai/bot_evaluation.py`. **Mesuré : les retirer ne change aucun relevé** — le moteur sème déjà. Ils
ne corrigent donc rien aujourd'hui et le doc du script le dit ; ils sont là pour que l'instrument
et la vraie boucle d'évaluation ne divergent pas en silence.

#### Référence rejouée — 60 épisodes/bot, poids rétablis

`W40K_BOARD_PATH=board/44x60x1`, modèle `robust_0.8721` (md5 `6f6b9805…`), graine de base 12345,
sièges `random`, pool holdout. Zones contrôlées par le bot, moyenne sur 60 épisodes.

| bot | T1 | T2 | T3 | T4 | T5 | sem T2 | sem T5 |
|---|---|---|---|---|---|---|---|
| alpha | 0,97 | 1,12 | 0,93 | 1,13 | 1,10 | ±0,09 | ±0,10 |
| attrition | 1,20 | 1,67 | 1,90 | 2,18 | **2,08** | ±0,09 | ±0,10 |
| decapitation | 1,22 | 1,60 | 1,43 | 1,22 | **1,08** | ±0,09 | ±0,10 |
| endgame | 1,15 | 1,57 | 1,77 | 1,88 | **2,08** | ±0,08 | ±0,11 |
| racer | 1,38 | 1,77 | 1,88 | 1,97 | **2,07** | ±0,10 | ±0,11 |
| scorer | 1,37 | 1,65 | 1,85 | 2,08 | 1,93 | ±0,10 | ±0,11 |

C'est CETTE table qui sert de référence, et elle n'a pas d'équivalent antérieur : le §12.5 ne
publie pas de relevé par bot et par tour, il publie une moyenne de panel avant/après pénalité.

#### Les deltas, appariés, avec la dérive des contrôles en regard

Un run par poids, un seul poids changé, les cinq autres bots joués en contrôle. Chaque case est la
moyenne des différences épisode par épisode contre la référence.

| run | poids changé | Δ T2 | Δ T3 | Δ T4 | Δ T5 | dérive des 5 contrôles |
|---|---|---|---|---|---|---|
| R3 | `alpha.w_crowd` 0.5 → **0.0** | +0,000 ±0,041 | +0,033 ±0,071 | −0,017 ±0,061 | −0,100 ±0,078 | **0,000 ±0,000** |
| R1 | `alpha.w_crowd` 0.5 → **1.0** | +0,050 ±0,044 | +0,083 ±0,055 | +0,017 ±0,061 | −0,150 ±0,078 | **0,000 ±0,000** |
| R2 | `alpha.w_crowd` 0.5 → **2.0** | +0,033 ±0,058 | +0,083 ±0,055 | −0,050 ±0,069 | **−0,233 ±0,093** | **0,000 ±0,000** |
| R4 | `decapitation.w_crowd` 0.5 → **2.0** | −0,083 ±0,064 | −0,033 ±0,082 | −0,017 ±0,084 | −0,050 ±0,129 | **0,000 ±0,000** |
| R5 | `decapitation.w_contest` 1.0 → **1.5** | +0,000 ±0,041 | +0,000 ±0,053 | +0,000 ±0,079 | +0,033 ±0,082 | **0,000 ±0,000** |

**Les deux corrections du §12.7 sont réfutées, et l'une d'elles a le signe inverse.**

- `alpha` : monter `w_crowd` **retire** des zones au tour 5, et de plus en plus haut on monte
  (−0,10 / −0,15 / −0,23 pour 0.0 / 1.0 / 2.0). Le 2.0 posé le matin est le seul point de la série
  qui sorte franchement de sa marge — **dans le mauvais sens**, là où le §12.7 annonçait
  +0,25. Lecture : ce bot traverse la table vers l'ennemi (`w_enemy` 1.2), ses escouades ne
  s'empilent pas sur une zone ; les écarter l'une de l'autre ne fait que les écarter des zones.
  `w_crowd` reste à **0.5**, qui est le maximum des quatre valeurs essayées.
- `decapitation` : `w_crowd` 2.0 rend **−0,05 ±0,13**, soit rien, et `w_contest` 1.5 rend
  **+0,03 ±0,08**, soit rien non plus — avec des zéros EXACTS aux tours 2, 3 et 4. Les deux poids
  restent à **0.5** et **1.0**.

**Ce que le §12.7 avait vu juste, et qui reste ouvert** : `decapitation` décline bien, de 1,60 au
tour 2 à 1,08 au tour 5, et c'est le seul bot du panel dans ce cas avec `alpha`. Le déclin est
réel et rejoué à n=60. Mais aucun des deux poids incriminés ne le corrige, donc **la cause est
ailleurs** : la chercher dans le terme d'encombrement a déjà coûté une campagne, et ce §12.8 est
la deuxième.

#### Mesure finale contre l'agent (étape 8) — poids rétablis, `robust_0.8721`

Sans elle, tout ce qui précède serait un déplacement de zones sans effet démontré sur l'objectif.
Commande du §2, profil `x1_panel`, **100 épisodes par bot** (600 au total, 452 s, 1,33 ép./s) :

```bash
python3 ai/train.py --agent ArmageddonAgent --training-config x1_panel \
  --test-only --test-episodes 100 --resolution 1
```

| bot | win-rate agent | W / L / D |
|---|---|---|
| **racer** | **0,63** | 63 / 37 / 0 |
| attrition | 0,71 | 71 / 28 / 1 |
| scorer | 0,76 | 76 / 23 / 1 |
| endgame | 0,80 | 80 / 19 / 1 |
| decapitation | 0,83 | 83 / 17 / 0 |
| alpha | 0,93 | 93 / 7 / 0 |

**`Combined = 0,7767`. Pire bot `racer` = 0,630. Pire scénario `holdout_regular_bot-01` = 0,733.**
Écart Space Marine − Ork : −4,7 pt.

C'est **le premier combined post-§12.6 sur ce modèle**, donc ce chiffre-là remplit la case laissée
ouverte par le « ⚠️ À REJOUER » des §12.5 et §12.6 : l'amplitude annoncée là-bas (0,873 → 0,788,
pire bot 0,78 → 0,62) est **confirmée, pas révisée** — 0,7767 et 0,630 tombent à la marge près sur
les mêmes valeurs, alors que les deux défauts de la pénalité ont été corrigés entre-temps.

⚠️ **Ce que cette mesure NE dit pas.** Elle ne compare pas deux jeux de poids : les hausses du
§12.7 n'ont pas été portées jusqu'ici, parce que l'étalement — la grandeur qu'elles prétendaient
améliorer — les a déjà réfutées à un coût vingt fois moindre. Elle établit la ligne de base du
panel rétabli, et c'est à elle que se comparera le prochain réglage.

⚠️ **Modèle lu dans un `ai/models/` PRIVÉ AU WORKTREE** (§10.2), `md5 6f6b9805…` vérifié avant et
après. Le chemin canonique partagé portait ce jour-là `1072b0c6…` — un autre modèle, 35 Mo contre
48 : lancer cette mesure dessus aurait rendu un combined sans rapport avec les §11 et §12, et rien
dans la sortie ne l'aurait signalé.

### 12.9 `scorer` réglé — le dernier style posé sans mesure (2026-08-13)

`scorer` était le seul profil du panel dont les six poids n'avaient jamais été confrontés à une
mesure : posés par doctrine à sa création (§11.3), et sa `_justification` le disait. Protocole du
§12.8, repris sans rien y changer.

**La référence a d'abord été rejouée, et elle reproduit le §12.8 case pour case** — six bots, cinq
tours, au centième : alpha 1,12/1,10 · attrition 1,67/2,08 · decapitation 1,60/1,08 · endgame
1,57/2,08 · racer 1,77/2,07 · scorer 1,65/1,93 (T2/T5). La reproductibilité au bit sur laquelle
repose tout ce protocole tient donc aussi **d'une session à l'autre**, ce que le §12.8 n'avait pas
vérifié : il ne l'avait constatée qu'entre deux exécutions consécutives.

#### La grille — les six poids encadrés dans les deux sens

Douze runs, 60 épisodes/bot, un seul poids changé par run, les cinq autres bots en contrôle.
**Dérive des contrôles : 0,000 sur les quatre tours dans les douze cas.** Chaque case est la
moyenne des différences épisode par épisode contre la référence.

| poids changé | Δ T2 | Δ T3 | Δ T4 | Δ T5 |
|---|---|---|---|---|
| `w_objective` 1.0 → 0.7 | −0,033 ±0,047 | −0,050 ±0,060 | −0,067 ±0,085 | −0,067 ±0,106 |
| `w_objective` 1.0 → 1.3 | +0,017 ±0,044 | +0,150 ±0,082 | +0,117 ±0,079 | +0,133 ±0,102 |
| `w_enemy` 0.3 → **0.0** | +0,083 ±0,068 | +0,150 ±0,106 | +0,133 ±0,115 | **+0,400 ±0,163** |
| `w_enemy` 0.3 → 0.6 | +0,100 ±0,074 | −0,117 ±0,104 | **−0,283 ±0,104** | −0,200 ±0,142 |
| `w_fire` 0.6 → 0.0 | +0,083 ±0,064 | **+0,233 ±0,102** | +0,133 ±0,099 | +0,233 ±0,127 |
| `w_fire` 0.6 → 1.0 | −0,067 ±0,047 | −0,117 ±0,083 | −0,067 ±0,078 | +0,100 ±0,081 |
| `w_risk` 0.4 → 0.0 | −0,033 ±0,053 | −0,117 ±0,092 | −0,217 ±0,117 | +0,000 ±0,126 |
| `w_risk` 0.4 → 0.9 | +0,000 ±0,048 | +0,133 ±0,077 | −0,050 ±0,096 | +0,233 ±0,133 |
| `w_contest` 3.5 → **1.5** | +0,100 ±0,052 | +0,133 ±0,105 | +0,083 ±0,102 | **+0,367 ±0,136** |
| `w_contest` 3.5 → 5.0 | −0,067 ±0,071 | −0,117 ±0,104 | −0,133 ±0,105 | −0,117 ±0,126 |
| `w_crowd` 2.5 → 1.0 | +0,067 ±0,047 | +0,000 ±0,098 | +0,067 ±0,103 | +0,083 ±0,115 |
| `w_crowd` 2.5 → **4.0** | −0,017 ±0,061 | +0,100 ±0,070 | +0,083 ±0,080 | **+0,333 ±0,111** |

**Règle de rétention, appliquée uniformément** : franchir 2 sem au tour 5 **et** être monotone sur
les deux points d'encadrement. Trois changements la passent — `w_enemy` → 0.0, `w_contest` → 1.5,
`w_crowd` → 4.0 — et l'encadrement est ce qui les distingue du bruit : chacun a son point opposé
de signe contraire.

**Deux d'entre eux contredisent la doctrine qui les avait posés, même motif que le §12.8 sur
`alpha`.** `w_contest` valait 3.5 « parce que scorer conteste » : le BAISSER à 1.5 est ce qui lui
fait tenir le plus de zones. `w_enemy` valait 0.3 « il s'approche pour contester » : 0.0 fait
mieux, et 0.6 fait pire. Poser un poids au nom de ce que le style est censé faire a maintenant
échoué **trois fois de suite** dans ce chantier ; c'est un résultat sur la méthode, pas sur ce bot.

**Trois changements positifs ne sont PAS retenus**, sous le seuil : `w_fire` → 0.0 (+0,233 ±0,127
au T5, mais 2,3 sem au T3), `w_risk` → 0.9 (+0,233 ±0,133), `w_objective` → 1.3 (+0,133 ±0,102).
Ce sont exactement les trois poids qui séparent `scorer` de `racer` (1.3 / 0.2 / 0.0 / 0.0) : les
retenir tous aurait fait converger les deux styles et coûté un barreau à l'échelle. La règle de
seuil les écarte d'elle-même — ce n'est pas un choix de doctrine posé après coup.

#### La combinaison, mesurée et non déduite

| | T2 | T3 | T4 | T5 |
|---|---|---|---|---|
| Δ apparié des trois poids ensemble | +0,217 ±0,072 | +0,300 ±0,102 | +0,233 ±0,112 | **+0,400 ±0,135** |

`scorer` passe de 1,93 à **2,33** zones au tour 5 — premier du panel devant `attrition`/`endgame`
(2,08) et `racer` (2,07) — et son déclin T4→T5 disparaît.

⚠️ **Les trois effets se RECOUVRENT largement** : pris isolément ils totalisent +1,10 au tour 5,
ensemble ils rendent +0,40. Aucune mesure poids-par-poids ne pouvait le dire, et un jeu de poids
retenu sans ce run aurait été annoncé sur une somme trois fois trop grande. C'est la raison d'être
du run de confirmation, et elle vaut pour tout réglage multi-poids à venir.

#### Mesure contre l'agent (étape 8) — 100 épisodes/bot

Commande du §2, profil `x1_panel`, modèle `robust_0.8721` (md5 `6f6b9805…`) lu dans le `ai/models/`
privé au worktree, 600 épisodes en 556 s.

| bot | §12.8 | §12.9 |
|---|---|---|
| racer | 0,63 | 0,63 |
| **scorer** | **0,76** | **0,66** |
| attrition | 0,71 | 0,71 |
| endgame | 0,80 | 0,80 |
| decapitation | 0,83 | 0,83 |
| alpha | 0,93 | 0,93 |
| **combined** | **0,7767** | **0,7600** |

**Les cinq bots non touchés rendent EXACTEMENT leur chiffre du §12.8**, ce qui étend l'invariant de
dérive nulle à la boucle d'évaluation complète — il n'avait été établi que sur l'instrument
d'étalement. `scorer` gagne 10 points sur l'agent et devient le deuxième bot le plus dur du panel,
à 3 points de `racer`. Pire scénario `holdout_regular_bot-01` : 0,733 → **0,7067**. Écart Space
Marine − Ork : −4,7 → −6,0 pt.

**Le gain d'étalement se transmet donc bien à l'objectif**, et c'est la première fois qu'on le
vérifie dans ce chantier : le §12.8 n'avait porté aucun de ses réglages jusqu'à cette mesure,
puisque l'étalement les avait déjà réfutés.

### 12.10 Distance hex et taux de pertes — deux grandeurs de diagnostic (2026-08-13)

**Contexte.** Le réglage du §12.7 est depuis **invalidé** (§12.8), mais le manque qu'il avait mis
au jour est réel et lui survit : les chiffres de zones ne suffisent pas à distinguer
un bot qui s'étale correctement d'un bot qui progresse vers les zones *en passant à côté des
ennemis* : `alpha` et `decapitation` avaient un T5 bas alors qu'ils pourchassaient l'ennemi par
doctrine. Deux grandeurs lisibles directement sur le même `game_state` comblent ce trou.

**Protocole (immuable, cf. gardes du script) :**

```bash
W40K_BOARD_PATH=board/44x60x1 python3 scripts/bot_zone_direct.py --episodes 60
```

- Plateau : `board/44x60x1` (x1) — sans `W40K_BOARD_PATH` le script lève.
- Modèle : `ArmageddonAgent_12345_robust_0.8721.zip` vérifié au md5
  `6f6b98059a0a6c279b7d11dc427461fd` — si le fichier a changé le script lève.
- 60 épisodes par bot (variance acceptable sur les deux nouvelles grandeurs).

**Deux nouvelles grandeurs :**

| clé JSON | définition | lecture |
|----------|-----------|---------|
| `dist_by_turn` | distance hex moyenne de chaque escouade bot au plus proche ennemi vivant sur table | un bot qui s'approche : distance décroissante de T1 à T5 |
| `squads_by_turn` | nombre d'escouades bot vivantes (table + réserves) | `_loss_rate_by_turn` dérive le taux cumulé `(baseline − alive) / baseline` |

Les escouades en réserves sont exclues côté ennemi (sentinel `(-1,-1)`) mais **comptées côté bot**
dans `squads_by_turn` — elles sont vivantes, elles ne sont pas encore sur table. La distance n'est
calculée que lorsqu'au moins un ennemi est sur table ; `None` (absent du JSON) = tour de réserves pur.

**Gardes du script :**

- `_require_board_path()` : lève `RuntimeError` sans `W40K_BOARD_PATH`.
- `_require_reference_model()` : lève `RuntimeError` si le md5 du checkpoint ne correspond pas à
  `REFERENCE_MD5`. Les deux constantes (`REFERENCE_MODEL`, `REFERENCE_MD5`) sont au niveau du
  module pour être monkeypatchables en test sans écrire dans `ai/models/`.

**Verrou automatisé :** `tests/unit/scripts/test_bot_zone_direct_gardes.py` (gardes) +
`tests/unit/scripts/test_bot_zone_direct_metrics.py` (fonctions de calcul). Rouge prouvé par
mutation sur les deux gardes (2026-08-13).

### 12.11 `decapitation` marchait vers un ennemi, tirait sur un autre (2026-08-13)

**Le constat.** Le style concentre ses TIRS sur une cible unique par tour (`target_score` +
`_focus`, mémoire de tour), mais son DÉPLACEMENT passait par le socle : le terme `w_enemy` du
score de destination portait sur *toutes* les ancres ennemies sur table, donc sur la plus proche
de chaque escouade. Une escouade tirait sur A puis marchait vers un B différent — au tour suivant
elle n'était plus à portée de A, et la doctrine (« retirer une escouade entière retire son OC et
ses tirs ») ne pouvait pas se boucler. C'est la contradiction que `w_enemy: 0.6` ne pouvait pas
corriger par le réglage : le poids était bon, la cible était la mauvaise.

**La correction.** Un hook `_DoctrineBot._enemy_anchors(unit, game_state, enemies)` isole la liste
d'ancres sur laquelle porte `w_enemy` ; le socle rend le calcul d'avant (toutes les escouades
ennemies vivantes sur table), `DecapitationBot` la restreint à sa cible du tour. Aucun autre style
ne l'override, aucun autre chemin ne lit ce motif (`grep _enemy_anchors` → seul
`bot_doctrines.py`). `enemies` est PASSÉ par `select_movement_destination`, qui a déjà payé ce
parcours pour `w_fire`/`w_risk` : le hook ne refait ni le filtrage ni les lectures de cache.

**Le hook seul ne suffisait pas — l'élection au mouvement (corrigé le 2026-08-13, même jour).**
La première version se contentait de LIRE `_focus(game_state)` et retombait sur le socle quand la
mémoire était vide. Elle ne s'appliquait donc quasiment jamais : `_focus_target` n'est écrit que
par `_remember`, appelé depuis le tir et la mêlée, alors que le mouvement les précède (07.01) — et
un `turn` couvre les DEUX joueurs (`fight_handlers` ne l'incrémente qu'après la mêlée de J2), donc
la mémoire du tour d'avant est périmée pile avant le déplacement. Résultat : le camp qui joue en
premier n'avait JAMAIS de cible au mouvement, et le second n'en avait une que s'il avait combattu
défensivement dans la mêlée adverse de la même ronde. Le siège du bot alterne
(`env_wrappers._apply_episode_seat`), donc l'override était inerte sur la majorité des décisions.

`_enemy_anchors` ÉLIT donc la cible quand il n'y en a pas, et l'écrit dans `_focus_target` :

- critère d'élection = `_score_kill_now` (« tuable ce tour d'abord, puis efficacité »), c'est-à-dire
  le critère que le TIR appliquera ensuite, pris au meilleur des deux modes — au mouvement on ne
  sait pas encore si l'escouade tirera ou chargera, et `squad_expected_damage` ne dépend pas de la
  position (c'est déjà ce qui permet à `_firepower_profile` de se calculer une fois par décision) ;
- l'écriture est ce qui fait la concentration : les escouades suivantes LISENT l'élection de la
  première au lieu d'en faire une chacune ;
- cible morte ou hors table (réserves, 20.01, sentinelle `(-1,-1)`) → RÉÉLECTION, pas retour au
  socle : `enemies` ne contenant que des escouades sur table, l'appartenance à cette liste tranche
  les deux cas d'un coup, et une escouade qui n'a plus de cap se remettrait sinon à suivre son plus
  proche voisin — exactement l'éparpillement que le style existe pour éviter.

Effet de bord assumé et voulu : le tir du même tour hérite de la cible élue au mouvement. La cible
du tour n'est donc plus « celle que le premier tireur avait choisie » mais « celle que la première
escouade à décider pouvait le mieux entamer » — même famille de critère, appliquée une phase plus
tôt, et `target_score` n'accorde son bonus que si l'escouade peut réellement l'entamer (`base > 0`).

**L'élection seule ne suffisait pas non plus — la confirmation par la première attaque (corrigé le
2026-08-13, même jour).** Le critère d'élection classe sur `squad_expected_damage`, qui ne dépend
PAS de la position : rien n'empêche d'élire une escouade que le masque n'ouvrira à personne au tir
(hors portée, hors LoS). Le bonus de `target_score` ne se déclenchait alors chez AUCUNE escouade et
chacune repartait sur sa propre meilleure cible, c'est-à-dire une dispersion PIRE que celle du
socle, dans le style qui existe pour la supprimer. Avant l'élection au mouvement ce cas n'existait
pas : la cible venait du premier tireur, donc parmi SES cibles valides — attaquable par
construction. En passant l'écriture au mouvement, la première version avait perdu cette propriété
sans la remplacer, et `_remember` était devenu du code mort (il sortait sur
`_focus_target is not None`, désormais toujours vrai après le premier déplacement).

La cible élue est donc PROVISOIRE, et `_focus_confirmed` porte la distinction :

- `_remember` sort sur `_focus_confirmed`, plus sur `_focus_target is not None` : la **première
  attaque réelle du tour** (tir ou mêlée) écrit la cible qu'elle a effectivement frappée et la
  confirme. Une cible différente de l'élue signifie que le bonus ne s'est pas appliqué — l'élue
  n'était pas dans le masque, ou l'escouade ne peut pas l'entamer — donc la reprendre est ce qui
  reconcentre le reste du tour. C'est la sémantique d'avant l'élection, rendue au tir ;
- le VERROU après cette première attaque est ce qui empêche le balayage : sans lui, deux escouades
  aux portées disjointes se voleraient la cible à chaque activation et aucune troisième n'aurait de
  cap à suivre. Une seule attaque confirme, définitivement ;
- `_focus_confirmed` s'oublie EXACTEMENT quand `_focus_target` s'oublie (changement de tour, mort
  de la cible), jamais séparément : une confirmation qui survivrait à sa cible ferait sortir
  `_remember` trop tôt et plus personne n'écrirait de cible jusqu'au tour suivant.

Le déplacement, lui, n'est pas rejoué : la destination est déjà choisie quand la correction
intervient. C'est l'ordre voulu — on marche vers la cible la plus payante, on tire sur celle qu'on
atteint.

`enemies` (liste complète) reste utilisée telle quelle par `_firepower_profile` : `w_fire` et
`w_risk` chiffrent ce qu'on inflige et ce qu'on subit de TOUT le monde. Restreindre aussi la
menace à une escouade aurait fait un autre bot, pas une concentration.

**Verrou :** `tests/unit/ai/test_decapitation_movement.py`, 14 tests, tous partant d'une mémoire
VIERGE — l'état réel d'un premier déplacement. La série précédente posait `_focus_target` à la
main et prouvait un chemin que la production n'atteignait pas : c'est ce qui avait laissé passer
l'override inerte. Les cinq tests de confirmation passent par `_shoot` de bout en bout (donc par
`_best_slot_action` ET `_remember`, dont les deux lectures du mapping de slots sont stubbées
ensemble — n'en stubber qu'une ferait tirer sur une cible et en mémoriser une autre). Rouge prouvé
par mutation (2026-08-13, `__pycache__` purgé) :

| mutation | tests rouges |
|----------|--------------|
| l'élection retirée (retour au socle quand la mémoire est vide) | 7 des 9 |
| `_remember` re-sorti sur `_focus_target is not None` (état d'avant la confirmation) | 5 des 14 |
| `_focus_confirmed` non remis à faux à la mort de la cible | 1 des 14 |

Le test `..._the_movement_really_walks_toward_the_elected_target` est le garde-fou VERT VACANT : il
passe par `select_movement_destination` de bout en bout, donc il prouve que l'élection est atteinte
par le chemin de production — un override jamais appelé par le vrai chemin ne corrige rien.

**Non mesuré :** l'effet sur les zones et le win-rate. Le protocole du §12.8
(`bot_zone_direct.py --episodes 60`, plateau x1) est celui à rejouer pour chiffrer le gain ;
`w_enemy: 0.6` reste à re-régler une fois ce chiffre connu, puisqu'il agit désormais sur une
distance beaucoup plus longue (la cible focalisée, pas l'ennemi collé).


### 12.12 Nouvelles métriques de convergence (2026-08-13)

Les trois grandeurs du §12.8 ne disent pas si les escouades d'un même bot visent **le même**
ennemi. Deux s'y ajoutent, écrites dans le relevé par épisode comme les précédentes :

| clé JSON | définition | lecture |
|----------|-----------|---------|
| `focus_targets_by_turn` | nombre d'ennemis **distincts** élus « plus proche » par au moins une escouade bot sur table | `1` = toutes les escouades convergent ; `N` = chacune part de son côté |
| `focus_dist_by_turn` | distance hex moyenne des escouades bot sur table à la **cible focalisée** du bot (`_focus_target`) | ce que « suivre la cible commune » coûte en distance parcourue |

`focus_dist_by_turn` n'existe **que** pour les doctrines qui élisent une cible commune
(`DecapitationBot`). Les cinq autres n'ont pas d'attribut `_focus_target` : la clé est **absente**
du JSON et la ligne vaut `—` dans le tableau — jamais `0`, qui se lirait comme « distance nulle »
(T1). Même règle qu'au §12.8 pour les réserves : sentinel `(-1,-1)` exclu des deux côtés, une
cible morte ou hors table rend `None`.

⚠️ La mesure lit `bot._focus_target` **nu**, jamais `bot._focus(game_state)`. `_focus` périme la
cible sur le marqueur de tour : l'appeler depuis l'instrumentation muterait l'état du bot à la
frontière de tour, donc changerait la grandeur mesurée par le fait de la mesurer.

**Verrou automatisé :** 14 tests dans `tests/unit/scripts/test_bot_zone_direct_metrics.py`. Rouge
prouvé par mutation sur `_ennemi_en_reserves_exclu` et `_none_si_cible_en_reserves` (2026-08-13).

#### 12.12.1 Mesure avant/après l'élection de cible au mouvement

**Ce qui est comparé.** « Avant » = `5833c826` ; « après » = le tree du 2026-08-13, où
`DecapitationBot` surcharge `_enemy_anchors` pour que `w_enemy` tire vers la cible **élue** au lieu
de l'ennemi le plus proche de chaque escouade (§12.11). Le SHA `e4a44b1a`, qui porte une version
intermédiaire de ce travail, vit sur une branche non fusionnée : il ne se retrouve pas depuis
`main`, d'où les deux repères ci-dessus.

**Les poids ne changent pas entre les deux états** — comparaison faite valeur par valeur sur
`config/bot_movement_weights.json`, seul le texte `_justification` de `decapitation` diffère. Il
n'y a donc rien à démêler entre « élection » et « réglage de poids » : l'élection est le **seul**
facteur.

**Protocole.** `--episodes 60`, plateau `x1`, modèle `robust_0.8721`, mêmes graines des deux côtés
(`_episode_seed` est déterministe) — les épisodes s'apparient un à un, ce qui autorise une
comparaison appariée bien plus fine que deux moyennes indépendantes. Instrument identique dans les
deux arbres : le script de mesure et ses deux dépendances ont été recopiés dans le worktree.

**Contrôle de validité.** Les cinq autres bots rendent des relevés **bit-identiques** entre les deux
runs, sur les cinq grandeurs et les cinq tours. Seul `decapitation` bouge : l'écart mesuré vient de
la doctrine, pas du bruit ni de l'instrument.

**`focus_targets_by_turn` — cibles distinctes (60 ép./bot) :**

| Bot | T1 | T2 | T3 | T4 | T5 |
|-----|----|----|----|----|----|
| alpha (identique) | 1.33 | 1.88 | 1.95 | 1.72 | 1.58 |
| attrition (identique) | 1.33 | 1.87 | 1.80 | 2.02 | 1.77 |
| endgame (identique) | 1.32 | 1.62 | 1.58 | 1.75 | 1.82 |
| racer (identique) | 1.33 | 1.95 | 1.85 | 1.90 | 1.75 |
| scorer (identique) | 1.40 | 1.82 | 1.88 | 1.95 | 1.92 |
| **decapitation avant** | 1.25 | 1.85 | 1.78 | 1.87 | 1.67 |
| **decapitation après** | 1.22 | 1.93 | 1.60 | 1.58 | 1.47 |
| Δ apparié (±IC 95 %) | −0.03 ±0.07 | +0.08 ±0.21 | −0.18 ±0.24 | **−0.28 ±0.25** | −0.20 ±0.22 |

**`focus_dist_by_turn` — distance à la cible focalisée (`decapitation` seul) :**

| | T1 | T2 | T3 | T4 | T5 |
|-|----|----|----|----|----|
| **avant** | 26.5 | 22.1 | 21.4 | 20.0 | 19.3 |
| **après** | 32.8 | 31.2 | 22.0 | 20.2 | 20.2 |
| Δ apparié (±IC 95 %) | **+5.85 ±3.79** | **+9.05 ±4.10** | +0.94 ±3.00 | −0.24 ±2.61 | +0.45 ±2.58 |
| ép. avec une cible, avant → après | 54 → 58 | 58 → 60 | 58 → 60 | 57 → 54 | 55 → 60 |

Les cinq autres bots valent `—` sur toute la ligne, aux deux runs.

**Rappel des deux grandeurs du §12.8, sur les mêmes runs (`decapitation`) :**

| | T1 | T2 | T3 | T4 | T5 |
|-|----|----|----|----|----|
| `dist_by_turn` avant | 31.3 | 20.8 | 15.7 | 14.6 | 15.0 |
| `dist_by_turn` après | 30.5 | 20.7 | 15.8 | 15.9 | 15.1 |
| Δ apparié (±IC 95 %) | −0.82 ±0.76 | −0.07 ±1.11 | +0.06 ±1.63 | +1.23 ±1.69 | +0.08 ±1.92 |
| `zones_by_turn` avant | 1.22 | 1.43 | 1.28 | 1.08 | 0.98 |
| `zones_by_turn` après | 1.17 | 1.40 | 1.17 | 0.93 | 0.92 |
| Δ apparié (±IC 95 %) | −0.05 ±0.09 | −0.03 ±0.14 | −0.12 ±0.23 | −0.15 ±0.25 | −0.07 ±0.20 |

**Conclusion causale.** L'élection au mouvement fait bien ce pour quoi elle a été écrite — elle
envoie les escouades vers une cible commune plus lointaine (`focus_dist` +9.1 hex à T2) et resserre
la convergence en milieu de partie (`focus_targets` −0.28 à T4, seul écart de convergence
significatif) — mais **elle n'explique pas la distance au plus proche ennemi du §12.8** : à graine
égale, `dist_by_turn` est inchangée sur T2–T5. La montée observée au §12.8 vient donc d'ailleurs.

#### 12.12.2 La montée de `dist_by_turn` au dernier tour est un BIAIS DE SURVIE

Élucidé le 2026-08-13 **sans nouveau run**, par relecture du relevé par escouade des 60 épisodes
du §12.8 (mêmes graines, même modèle, même plateau).

`dist_by_turn` moyenne sur les escouades **vivantes sur table**, donc sa population change à chaque
tour. Or les escouades qui meurent sont, de très loin, les plus proches de l'ennemi — relevé sur
les mêmes parties, distance au tour `t` selon qu'elles sont mortes ou vives au tour `t+1` :

| bot | T3 mortes → | T3 vives → | T4 mortes → | T4 vives → |
|---|---|---|---|---|
| decapitation | **5,6** (n=32) | 17,1 (n=232) | **6,0** (n=48) | 16,8 (n=184) |
| racer | 5,8 (n=29) | 19,3 (n=241) | 6,9 (n=34) | 19,4 (n=207) |
| attrition | 4,9 (n=14) | 21,0 (n=270) | 6,2 (n=25) | 20,7 (n=245) |

Les retirer relève mécaniquement la moyenne du tour suivant. **La preuve tient en une COHORTE
FIXE** : en ne suivant que les escouades vivantes au tour 5, et en les remontant dans le temps, la
montée disparaît entièrement chez les deux bots concernés.

| bot | population | T1 | T2 | T3 | T4 | T5 |
|---|---|---|---|---|---|---|
| decapitation | toutes vivantes (= §12.8) | 31,3 | 20,9 | 15,7 | 14,5 | **14,9 ↑** |
| decapitation | **cohorte fixe (vivantes à T5)** | 32,8 | 23,5 | 18,9 | 16,8 | **14,9 ↓** |
| racer | toutes vivantes | 32,5 | 21,5 | 17,9 | 17,6 | **18,8 ↑** |
| racer | **cohorte fixe** | 34,1 | 24,0 | 20,7 | 19,4 | **18,8 ↓** |
| attrition | toutes vivantes | 34,5 | 24,2 | 20,2 | 19,4 | 22,2 ↑ |
| attrition | **cohorte fixe** | 35,0 | 25,2 | 21,9 | 20,7 | **22,2 ↑** |

⚠️ **`attrition` est le seul cas où il reste une montée RÉELLE** (+1,5 hex à cohorte fixe) : c'est
son mode `attrition_withdraw` (`w_enemy` −1,0), qui recule pour de bon. Chez `decapitation` et
`racer`, il ne reste rien — la montée était entièrement l'artefact.

**Trois conséquences, dont une qui change la lecture du §12.8 :**

1. Il n'y a **rien à expliquer côté doctrine** pour `decapitation` : le bot ne s'éloigne pas au
   dernier tour, il perd ses escouades avancées.
2. **Le §12.8 sous-estime l'exposition de `decapitation`**, il ne la surestime pas. Le biais joue
   dans le sens de la prudence : c'est le bot qui perd le plus d'escouades (33 % à T5 contre 16 %
   à `attrition`), donc celui dont la moyenne est la plus tirée vers le haut. Sa proximité réelle
   à l'ennemi est **pire** que ce que le tableau affiche.
3. **`dist_by_turn` ne se lit jamais seule au dernier tour.** La ligne « un bot qui s'approche :
   distance décroissante de T1 à T5 » du §12.8 est vraie à effectif constant, fausse dès qu'un
   camp perd des escouades. Toute lecture de cette grandeur au-delà de T3 se fait à cohorte fixe,
   ou accompagnée du taux de pertes (`squads_by_turn`, déjà au relevé).


### 12.13 Protocole de mesure d'un changement de poids (§12.13)

**Contexte.** Calibrer `w_enemy` de `DecapitationBot` après le §12.11 exige de mesurer l'effet
d'un changement de poids sans pollution par l'agent ni par les autres bots. Ce protocole isole
le signal : un run de référence et un run de variante sur les mêmes graines, avec les bots de
contrôle comme témoin d'invariance.

**Instrument :** `--label` dans `bot_zone_direct.py` — stocké dans `run.label` du JSON, absent
si omis. Permet d'identifier les deux runs dans les fichiers produits sans ambiguïté.

**Les cinq runs du protocole :**

| run | commande | `--label` | rôle |
|-----|----------|-----------|------|
| R1 — référence | `bot_zone_direct.py --episodes 60 --json-out ref.json --label ref` | `ref` | baseline poids actuels |
| R2 — variante A | `bot_zone_direct.py --episodes 60 --json-out var_a.json --label var_a` | `var_a` | config testée A |
| R3 — variante B (si besoin) | idem `--label var_b` | `var_b` | config testée B |
| R4 — re-référence (si besoin) | rejouer R1 après plusieurs jours | | vérifier la stabilité |
| R5 — mesure finale | protocole §12.8 avec 60 épisodes | | point de comparaison §12.7 |

⚠️ Chaque run DOIT passer les gardes du script (plateau `W40K_BOARD_PATH=board/44x60x1`,
modèle `REFERENCE_MD5`). Un run qui lève n'est PAS à comparer.

**Valeurs à remplir après les runs :**

| run | T2 | T5 | mean(Δ_T5 vs ref) | IC 95 % |
|-----|----|----|-------------------|---------|
| ref (R1) | — | — | — | — |
| var_a (R2) | — | — | — | — |

**Commande de mesure (à lancer sur la paire ref/var) :**

```bash
python3 scripts/bot_compare_weights.py ref.json var_a.json --bot decapitation
```

Lit les épisodes du bot cible de chaque fichier par index (même graines garanties par le
script de mesure), calcule `Δ_T5 = var[i].zones_T5 − ref[i].zones_T5`, affiche mean, std,
IC 95 % = mean ± t(n−1) × std / √n.

**Student, pas 1,96** (corrigé le 2026-08-13) : σ est estimé sur l'échantillon et n vaut 60 ou
moins, donc le quantile normal rétrécit l'intervalle (t(59) = 2,001, et 3,182 dès n = 4). Il
déclarait significatif ce qui ne l'est pas — sur un seuil de décision qui est exactement « l'IC
ne contient pas 0 ». À n = 1 l'intervalle n'existe pas : le script écrit « non défini », il
n'affiche plus `± 0,000`.

**Épisodes terminés avant le T5** (annihilation) : `zones_by_turn` n'a alors pas de clé `"5"`
(`bot_zone_direct.py` ne pose une clé que pour les tours joués). La PAIRE est ÉCARTÉE du calcul,
et les deux comptes sont affichés (`épisodes écartés : ref X, var Y`). Avant le 2026-08-13 elle
était comptée « 0 zone tenue », ce qui punissait de −2 une variante qui gagne au T3 et pouvait
inverser la conclusion. C'est aussi la lecture du tableau du §12.7, dont la moyenne T5 ne porte
que sur les épisodes parvenus au T5 — **l'asymétrie des exclusions est à lire** : « var écarte 8
épisodes contre 2 pour ref » dit que la variante finit ses parties plus tôt, ce que la moyenne
sur les survivants ne dit pas.

Vérifie d'abord l'invariance des contrôles — tous les bots hors `--bot`. Les deux fichiers
doivent porter EXACTEMENT le même panel et le même nombre d'épisodes par bot, et chaque relevé
de contrôle doit être identique épisode par épisode, le relevé ENTIER (graine, siège, zones,
distances, escouades). Tout écart lève `RuntimeError` et invalide les deux runs ; un relevé sans
aucun bot de contrôle lève aussi, puisqu'il n'y a alors rien qui valide la comparaison. Le
nombre de bots et d'épisodes réellement comparés est imprimé à côté de la coche : une coche
verte sans compte ne prouvait rien.

Le nombre d'épisodes du bot cible doit lui aussi être identique dans les deux fichiers — les
graines sont indexées, donc un run interrompu s'appariait parfaitement sur son préfixe et
rendait un `n` amputé en silence.

**Seuil de décision :** un changement de poids est retenu si l'IC 95 % ne contient pas 0 et
si le T5 de la variante reste dans la plage des autres bots réglés (§12.7 : 1,0 à 2,6 zones).
Un IC qui contient 0 = bruit, augmenter n (60 → 120).

**Commande de mesure agent finale (étape 8 du §4) :**

```bash
cd /home/greg/40k && source .venv/bin/activate
python3 ai/train.py --agent ArmageddonAgent --training-config x1 \
  --test-only --test-episodes 100 --resolution 1
```

Même modèle (`robust_0.9438`) et même commande qu'en §2 — c'est ce qui rend les colonnes
comparables. À rejouer en dernier, une seule fois les poids stabilisés.

### 12.14 Quatre lignes de travail réunies, et la ligne de base qui en sort (2026-08-13)

Le chantier a été travaillé le même jour par **quatre sessions en parallèle**, chacune ignorant
les autres. Chacune a produit du travail juste, et elles se contredisaient : trois sections
numérotées `§12.8` le matin, deux `§12.11` et deux `§12.12` l'après-midi, trois copies
divergentes de `scripts/bot_zone_direct.py` (207, 271 et 512 lignes), et jusqu'à **quatre
mesures de 60 épisodes tournant en même temps** sur seize cœurs — chacune valide, toutes
ralenties d'un facteur trois.

⚠️ **C'est le coût réel du travail parallèle sur un chantier de mesure, et il ne se voit pas au
moment où on le paie** : les quatre sessions suivaient le protocole, et c'est justement pour ça
qu'aucune n'avait de raison de se méfier. Le §10.4 listait trois ressources partagées (le modèle
canonique, `step.log`, les JSON de `config/`) ; il en manquait deux, les plus coûteuses — **la
ligne de base elle-même**, et **la numérotation de ce document**. Une première unification a été
faite en milieu de journée ; elle a été défaite en quatre heures par les sessions qui
continuaient. La seconde n'a tenu que parce que les autres ont été gelées sur ces deux fichiers.

#### Ce qui a été tranché, et sur quelle mesure

- **`alpha` reste à `w_crowd` 0.5.** La table de contrôle de la session `decapitation`, mesurée
  indépendamment avec `alpha` à 2.0, donne T5 = 0,87 ; la référence du §12.8 à 0.5 donne 1,10.
  L'écart vaut 0,23 — exactement le **−0,233 ±0,093** que le §12.8 avait mesuré en apparié. Deux
  sessions, deux instruments, le même chiffre : la réfutation du §12.7 est confirmée de l'extérieur.
- **La forme du correctif de `decapitation` retenue est celle du §12.11**, et l'autre est
  abandonnée avec sa section. Elle place l'élection dans `_enemy_anchors` et la garde
  **provisoire** jusqu'à la première attaque du tour : le critère pris au mouvement ne regarde
  pas la portée, donc figer la cible dès le déplacement — ce que faisait l'autre forme — décide
  trop tôt. Elle rend un peu moins en zones (1,68 contre 1,77 au T5) et c'est cohérent.
- **`decapitation.w_objective` 1.0 a été REJOUÉ sur cette forme-là**, parce que le sweep qui
  l'avait établi portait sur l'autre. Apparié contre 1.0, dérive des cinq contrôles 0,000 :
  0.5 rend **−0,750 ±0,146** zone au T5, 0.8 rend **−0,233 ±0,117**, 1.2 rend **+0,067 ±0,114**,
  soit rien. Ce n'est donc **pas le « pic » qu'annonçait l'autre forme, mais un PLATEAU qui
  commence à 1.0** — la plus petite valeur qui l'atteigne. Le chiffre retenu est le même ; sa
  justification, elle, était fausse.
- **L'instrument garde les gardes de `main`** (checkpoint nommé et vérifié au md5,
  `W40K_BOARD_PATH` exigé, relevé par épisode) **et les deux champs sans lesquels la comparaison
  appariée ne s'appuie sur rien** : l'étiquette de run, et les poids RÉELLEMENT consommés
  (`load_doctrine_weights`, plus `hold_bonus` qui fixe l'échelle où `w_crowd` se lit).

#### La ligne de base — 60 ép./bot en étalement, 100 ép./bot contre l'agent

| bot | zones T2 | zones T5 | win-rate agent |
|---|---|---|---|
| racer | 1,77 | 2,07 | **0,63** |
| scorer | **1,87** | **2,33** | 0,66 |
| attrition | 1,67 | 2,08 | 0,71 |
| decapitation | 1,63 | 1,68 | 0,73 |
| endgame | 1,57 | 2,08 | 0,80 |
| alpha | 1,12 | 1,10 | 0,93 |

`Combined = 0,7433`. Pire bot `racer = 0,630`. Pire scénario `holdout_regular_bot-01 = 0,6867`.
Écart Space Marine − Ork : −4,7 pt. **C'est cette ligne-là qui sert de référence désormais**, et
c'est elle que porte `scripts/bot_panel_reference.py`.

#### Ce que chaque livraison a coûté à l'agent

| bot | avant réglage | après `scorer` (§12.9) | après `decapitation` (§12.11) |
|---|---|---|---|
| racer | 0,63 | 0,63 | 0,63 |
| scorer | 0,76 | **0,66** | 0,66 |
| attrition | 0,71 | 0,71 | 0,71 |
| decapitation | 0,83 | 0,83 | **0,73** |
| endgame | 0,80 | 0,80 | 0,80 |
| alpha | 0,93 | 0,93 | 0,93 |
| **combined** | 0,7767 | 0,7600 | **0,7433** |

**Chaque baisse est imputable à une seule livraison, et les bots non touchés ne bougent pas d'un
centième** — quatre d'entre eux rendent le même chiffre aux trois colonnes. L'invariant de dérive
nulle, établi au §12.8 sur l'instrument d'étalement, tient donc aussi sur la boucle d'évaluation
complète, sur trois mesures successives et sur deux formes différentes du correctif.

⚠️ **`decapitation` n'est plus le bot qui décline** : de 1,60 → 1,08 au §12.8, il passe à
1,63 → 1,68. `alpha` reste seul dans ce cas (1,12 → 1,10), pour une raison connue et assumée —
il traverse la table vers l'ennemi, c'est sa doctrine. Il est aussi le bot le plus facile du
panel (0,93) et celui qui perd le plus d'escouades : **c'est là qu'est le prochain sujet**, s'il
en faut un.

⚠️ **Reste ouvert** : `decapitation.w_crowd` (2.0) et `w_contest` (1.5) n'ont **jamais été
isolés après le correctif de déplacement**. Le seul run qui les ait isolés (§12.8) précède le
changement de géométrie, donc il ne transfère pas ; le sweep de `w_objective` les incluait sans
les séparer. Ce sont les deux derniers poids du panel qui reposent sur autre chose qu'une mesure
faite sur le code courant.