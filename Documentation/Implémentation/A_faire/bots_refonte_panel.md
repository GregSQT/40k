# Refonte du panel de bots — six styles orthogonaux + holdout qui joue pour gagner

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

Conséquence sur le roster 500 pts d'ArmageddonAgent, calculée le 2026-08-11 : **16 unités sur 23**
ont `melee > ranged` selon ce proxy, dont l'Intercessor (2.00 contre 3.00 — un fusil à 24" contre
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
2. **Six styles orthogonaux**, un axe de faiblesse chacun. Le critère n'est pas « sont-ils
   bons ? » mais « punissent-ils des erreurs différentes ? ».

   | style | doctrine | erreur punie |
   |---|---|---|
   | Racer | prend tous les objectifs au plus vite, refuse le combat | l'agent qui campe et ne conteste jamais |
   | Endgame | tient le minimum tôt, prend le maximum à partir du tour 3 | l'agent qui marque tôt et se croit gagnant |
   | Alpha strike | cherche le contact au plus tôt sur la pièce clé | l'agent qui expose ses unités de tir |
   | Attrition | joue le départage VALUE : préserve ses pièces chères, tue le rentable | l'agent qui trade mal |
   | Décapitation | concentre tout sur une escouade par tour pour la retirer entièrement | l'agent qui étale ses forces |

   Racer/Endgame sont les deux bornes du **tempo**, Attrition/Décapitation les deux façons
   opposées de dépenser ses dégâts, Alpha la distance nulle.
   `adaptive` **disparaît** : c'est un commutateur entre trois autres styles, donc corrélé par
   construction.
   ⚠️ **Le panel compte CINQ styles, pas six.** `Standoff` (« tenir ses distances ») a été
   **supprimé** le 2026-08-11 — mesures et raison en §9. Décision de l'utilisateur, reprise
   telle quelle : « je préfère des bots pertinents plutôt que forcer pour en avoir un de plus
   qui n'apprend rien ». Le nombre n'a aucune vertu ; l'orthogonalité si.
3. **Le holdout garde le nom `tactical` mais change de nature.** Il n'a pas de doctrine, il a un
   objectif : il joue pour gagner. Recherche à **un coup d'anticipation** — énumérer ses actions
   légales, les simuler, garder la meilleure. Sa fonction de valeur d'état (option C) :
   **points marqués + zones tenues + différentiel de valeur des armées, pondéré par les tours
   restants**. Il sacrifie une unité en fin de partie pour un objectif décisif et la préserve au
   tour 1. Un holdout doit différer en **nature**, pas en degré : l'agent qui apprend à battre des
   heuristiques pondérées bat par construction une heuristique pondérée plus forte.
   ⚠️ Conserver le nom rend **l'historique de `tactical` illisible** après bascule. Aucun chiffre
   de sélection de modèle n'en dépend (poids 0,0 en éval, exclu du `worst_bot_score`), mais la
   bascule se date dans la config, comme le gel du 2026-08-04.
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
| 3 | chiffrage de faisabilité du holdout à un coup | ✅ 2026-08-11, cf. §6 |
| 4 | modèle de dégâts espérés (attaquant → cible) | ✅ 2026-08-11, cf. §7 |
| 5 | les CINQ styles + le holdout | ✅ 2026-08-11, cf. §7 (6ᵉ style supprimé, §9.2) |
| 6 | réglage et orthogonalité en **bot-contre-bot** | ✅ 2026-08-12, cf. §8 et §9 |
| 7 | correspondance ancien/nouveau, puis suppression des six anciens | |
| — | **⚠️ sort du holdout : arbitrage OUVERT, cf. §10.1** | |
| 8 | mesure finale contre l'agent, commande de §2 | |

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
sur une table pré-calculée que l'observation de l'agent lit déjà
(`ObservationBuilder._score_weapon_vs_target`). Un second modèle de dégâts aurait créé le doublon
divergent que ce dépôt paie le plus cher.

Il manquait **un facteur** : la table donne un dégât **par figurine** (sa clé offensive porte `NB`,
les attaques d'une figurine), alors que les bots décident au niveau de l'escouade — dix Boyz y
valaient un Boy. `squad_expected_damage()` multiplie par l'effectif **vivant**, lu comme le fait le
moteur (ids de `squad_models` présents dans `models_cache`). Aucun repli : cache absent ou escouade
inconnue lèvent, sans quoi une unité inconnue passerait pour inoffensive.

**Nouveaux fichiers** : `ai/bot_doctrines.py` (les six styles), `ai/bot_holdout.py` (le holdout à
un coup), `ai/bot_registry.py` (source unique clé→classe).

**Un défaut jumeau trouvé en chemin** : la table clé→classe existait en DEUX copies
(`ai/bot_evaluation.py` et `scripts/bot_ranking.py`). Brancher les six styles dans la première a
suffi pour l'évaluation, et `bot_ranking.py --bots racer` levait toujours « Unknown bot type ».
`ai/bot_registry.py` est désormais la source unique, les deux appelants y passent.

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

1. **Le holdout `tactical_lookahead` n'est pas validé.** Ses deux seules mesures (0,875 puis 0,250
   contre `racer`) portent chacune sur **8 épisodes**, soit ±35 points de marge, et elles encadrent
   **six changements simultanés** — quatre corrections du bot, deux de son unique adversaire.
   Aucune conclusion n'en est tirable, ni sur sa force ni sur l'effet du retrait de son « oracle ».
   Il coûte par ailleurs ~5× un bot normal par épisode (recalcul du contrôle d'objectif par
   candidate). Son sort est un arbitrage OUVERT, pas une décision prise.
2. **Deux reviews ont trouvé 11 défauts** dans ce code, dont 3 introduits en corrigeant la review
   précédente : la simulation du holdout qui polluait les compteurs du moteur, le rembobinage du
   hasard qui en faisait un oracle, un test de dés qui ne testait rien. Tous corrigés et verrouillés
   (`tests/unit/ai/test_holdout_simulation_isolation.py`), mais le taux d'erreur sur ce fichier
   invite à la prudence.
3. **Étapes 7 et 8 non commencées** : correspondance ancien/nouveau puis suppression des six
   anciens, et mesure finale contre l'agent.
4. **Le merge dans `main` attend la fin du training en cours** — il touche `config/`, relu à chaud
   par les évaluations (cf. CLAUDE.md, « Training en cours »).
