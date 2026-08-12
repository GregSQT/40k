# L'engagement d'un tir se juge AVANT les pertes, pas après (2026-08-12)

Suite directe de [`analyzer_portee_source_correcte_2026-08-12.md`](analyzer_portee_source_correcte_2026-08-12.md) :
même famille, même journée, autre canal. La portée était faussée par le segment `[TARGET_MODELS:]` ;
l'engagement l'était par l'**état reconstruit lui-même**, que la liste blanche ne pouvait pas garder.

## Le défaut

`analyzer_core` applique les dégâts d'une ligne **avant** d'aiguiller cette ligne vers son handler.
Quand un contrôle d'engagement s'exécute, la cible a donc déjà encaissé les pertes de l'attaque
qu'il prétend juger :

- `_apply_damage_and_handle_death` **purge ses socles** (`positions_by_model`) dès qu'elle perd une
  figurine — le log ne dit pas laquelle tombe ;
- si l'escouade meurt, elle est **retirée** de `unit_hp` et `unit_positions`.

Une cible morte disparaît de l'énumération des ennemis. Le tireur est alors déclaré « non engagé
avec sa cible » alors qu'il l'était quand le moteur a décidé — et s'il est engagé par ailleurs, le
contrôle 10.06 « tir engagé sur une unité non engagée » se déclenche sur un tir parfaitement légal.

## La mesure, avant de corriger

Run du 2026-08-12 (`step.log` de 14 h 14, 600 épisodes, 3 152 tirs `[CLOSE_QUARTERS]`) : **1 verdict
rendu, 0 réel**.

`E422 T4 P1` — `Unit 1(34,13)` tire son Absolvor Pistol sur `Unit 101(35,12)`, `Dmg:2HP`, et 101 a
exactement 2 PV. L'instrumentation du handler nomme les unités qui engagent le tireur au moment du
verdict : **103 seulement**. 101 avait disparu. Mesure directe avec la primitive du moteur (EZ = 2
subhex, métrique `hex` de l'entête du run) : `1 vs 101 → engagé`, `1 vs 103 → engagé`. Le tir était
légal ; le tour d'après, la même unité 1 combat 103 au contact.

## La correction

Le gel d'effectif déjà en place (`shot_sequence_target_models`, [BLAST] 24.05) est ÉLARGI plutôt que
doublé : `analyzer_core` instantanie vivacité, ancre et socles **avant** les dégâts
(`unit_hp_pre_line`, `unit_positions_pre_line`, `positions_by_model_pre_line`) et
`AnalyzerState.freeze_select_targets` en fait un `SelectTargetsFreeze` unique — effectif ET
géométrie de la cible au **Select Targets step de l'activation**, que `engagement_maps` rend aux
contrôles sous forme de cartes complètes.

Les deux moitiés ont vécu un temps dans deux dictionnaires séparés, l'invariant « même instant »
tenu par un commentaire : il a cédé le jour même (défaut n°1 ci-dessous). Un seul enregistrement le
rend structurel — un site ne peut plus geler une moitié en oubliant l'autre.

**Par activation, pas par ligne.** 10.06 et 04.02 sont des règles de CIBLAGE : le moteur les tranche
une fois pour l'activation entière (`_shoot_engagement_blocks_target`), avant d'en résoudre la
moindre attaque. Un instantané par ligne laisserait la deuxième attaque juger sur les pertes de la
première — même défaut, un tir plus tard.

Les autres unités restent lues sur les cartes vives : une activation n'inflige de pertes qu'à sa
cible, et le reste du plateau doit rester au plus frais.

Cinq mesures étaient concernées, toutes réalignées : cible engagée (04.02), tireur engagé,
tireur engagé **avec sa cible** (10.06, les deux branches du handler) — et le jumeau mêlée,
l'alternance 12.04.

## Le jumeau mêlée, et son défaut SYMÉTRIQUE

`fight_handler` demande « existe-t-il une unité ayant chargé, pas encore activée, encore engagée ? »
(12.04). Quand l'unité qui combat hors tour **tue** la cible, la chargeuse qu'on venait de sauter
n'est plus engagée avec personne au moment de la mesure : la faute d'alternance devenait **invisible**.
Même cause, verdict inverse — un faux négatif. Corrigé par le même gel.

## Trois défauts du gel lui-même, trouvés en relecture (même jour)

Le gel a été relu après livraison. Trois défauts, tous corrigés et verrouillés — les deux premiers
sont des incohérences INTERNES au gel, le troisième un jumeau qu'il fallait traiter avec lui.

**1. Un seul instant.** Une cible sans socles connus est mesurée comme un POINT : son ancre décide
seule. La mesure 04.02 gardait l'ancre de la LIGNE quand sa jumelle 10.06 prenait l'ancre gelée. Dès
que le moteur ré-ancre l'escouade sur un survivant en cours d'activation, les deux décrivaient deux
instants différents et la faute disparaissait à la deuxième attaque.

**2. Tout ou rien.** Le gel rendait l'ancre d'une cible sans lui rendre ses PV quand elle n'en avait
plus au Select Targets step (tir sur une escouade déjà détruite — cas réel, il a son propre
contrôle). Elle ressortait alors « unité sans données » à chaque ligne : une erreur de parsing
inventée par le gel, que les cartes vives ne produisaient pas. La vivacité commande désormais les
trois cartes d'un seul geste.

**3. Le contrôle de PORTÉE, jumeau resté sur la carte vive.** Corrigé le matin même pour lire
`positions_by_model`, il lisait la carte VIVE — purgée dès qu'une figurine de la cible tombe. Un tir
qui tue ne rendait donc **aucun** verdict de portée, ni sur sa propre ligne ni sur le reste de
l'activation : le contrôle ne se trompait plus, il se taisait. Il lit maintenant la même géométrie
gelée que l'engagement — c'est aussi l'instant du moteur, qui juge la portée au Select Targets step
(`_target_within_half_range`).

MESURÉ sur le même journal, en comptant les deux sources ligne à ligne :

| Lignes de tir à portée d'arme connue | verdicts rendus |
|---|---|
| carte vive (avant) | 18 702 / 29 664 — **37 % jugés par personne** |
| géométrie gelée (après) | **29 664 / 29 664** |

Le « 18 702 verdicts » que la livraison du matin citait comme preuve de non-aveuglement était donc
déjà la mesure du trou, sans qu'on le sache : les 10 962 lignes manquantes sont exactement les tirs
qui tuent. Et les 10 962 verdicts regagnés ne condamnent **aucun** tir — `Tirs hors portee` reste à
0 / 0.

## Vérification sur le même journal, avant / après

| | avant | après |
|---|---|---|
| Tir engagé visant une unité NON engagée (10.06) | 1 | **0** |
| Erreurs phase de tir (§1.2) | 18 | **17** |
| Tirs `[CLOSE_QUARTERS]` classés « cible engagée » | 58 / 224 | 70 / 236 |
| Tirs `[CLOSE_QUARTERS]` classés « cible non engagée » | 1157 / 1713 | 1145 / 1701 |
| Usage de la règle CLOSE_QUARTERS (§1.8) | 13 825 | 13 849 |

Ces chiffres isolent CETTE livraison (journal du 2026-08-12 14 h 14, rejoué avant/après sur la même
base). Le rapport du jour affiche §1.2 à **2** et non 17 : les 15 restants étaient le contrôle
« attaque non allouée », retiré le même jour par une livraison indépendante.

Le total de tirs close-quarters ne bouge pas (1 215 / 1 937) : ce sont **24 tirs reclassés**, ceux
dont la cible mourait du coup. Les 24 usages de règle en plus sont la même cause, au même endroit
(`shoot_handler`, compteur §1.8 conditionné à `shooter_engaged_with_target`). **Aucune autre famille
du rapport ne bouge.**

## Deux résidus de la même famille, fermés ensuite

**La priorité de ciblage se jugeait, elle aussi, sur l'état d'après.** `target_priority` lit
`stats['wounded_enemies']`, que `_apply_damage_and_handle_death` mute avant que le handler ne voie
la ligne : la cible y ENTRE quand le tir qu'on juge la blesse, et en SORT quand il l'achève. Deux
verdicts faux en sens inverse — tout premier tir blessant une escouade intacte était crédité « a
visé une cible déjà blessée » (échec masqué), et un tir achevant un blessé était compté « a visé du
plein PV alors qu'un blessé était en vue » (échec inventé). Le gel géométrique ne pouvait pas
l'attraper : il porte sur des cartes d'état, pas sur les sets de `stats`. Le set des blessés rejoint
donc `SelectTargetsFreeze` — c'est le même instant et la même question, celle du CHOIX de cible.

MESURÉ sur un journal de 41 épisodes (2 964 tirs) : **échecs de priorité 66 → 83 (P1) et 16 → 40
(P2)**. Le masquage domine largement : le rapport annonçait l'agent meilleur qu'il n'est, de 41
tirs. Aucun autre compteur ne bouge.

**Le bloc WAIT réécrivait 10.06/17.03 à la main.** `handle_wait` construit le pool de cibles qu'une
unité aurait pu viser ; il transcrivait la règle une deuxième fois, à quelques lignes de
`handle_shoot`, et il lui manquait le volet CIBLES de 10.06 (un tireur engagé, pistolet au poing,
gardait dans son pool les unités avec lesquelles il n'était PAS engagé). Aucun verdict faux à ce
jour — une ligne WAIT n'inflige pas de dégâts, et l'unité avec laquelle on est engagé reste de toute
façon une cible valide, donc le compartiment `wait_with_targets` ne bougeait pas. C'est le motif du
dépôt : « pas encore faux » ne se maintient pas tout seul. Les deux lecteurs passent par
`ranged_engagement_verdict`, source unique, dont la table de vérité est un test.

## Verrou

`tests/unit/ai/test_analyzer_target_priority_pre_loss.py` (nouveau) : les DEUX sens du défaut, dont
le second isolé par une blessure infligée en MÊLÉE — une blessure de tir compterait elle-même dans
la priorité et masquerait l'effet mesuré. Correctif retiré → `assert 0 == 1` et `assert 1 == 0`.

`tests/unit/ai/test_analyzer_ranged_engagement_rule.py` (nouveau) : la table de vérité 10.06 /
04.02 / 17.03, plus un test d'USAGE — le défaut réparé était un doublon, qu'aucun test de valeurs
n'aurait attrapé, donc c'est le NOMBRE de lecteurs qui est verrouillé. Règle ré-inlinée dans
`handle_wait` → `assert 2 >= 3` rouge.

`tests/unit/ai/test_analyzer_close_quarters_engagement.py` (3 tests ajoutés) : un troisième ennemi
tient le tireur engagé quand sa cible meurt — sans lui le contrôle se tairait pour une raison
étrangère, et le vert serait vacant. Le pistolet qui tue sa cible engagée ne doit rien compter ;
l'attaque en excès de la MÊME activation non plus (c'est ce cas qui distingue le gel par activation
d'un gel par ligne) ; et tuer une unité avec laquelle on n'est PAS engagé reste une faute.

`tests/unit/ai/test_analyzer_fight_alternation_pre_loss.py` (nouveau) : la faute d'alternance doit
survivre au coup mortel, avec la prémisse sans mort pour prouver que le contrôle voit quelque chose.

`tests/unit/ai/test_analyzer_shoot_at_engaged_enemy.py` (nouveau) : le contrôle 04.02 valait 0 sur
tous les runs disponibles, avant comme après — un compteur à zéro sans verrou ne se distingue pas
d'un contrôle mort, et c'est précisément ce qui a laissé vivre les trois faux positifs de cette
famille. Quatre tests : les prémisses géométriques, la faute réelle (cible au contact d'un allié du
tireur), le témoin négatif (allié à l'autre bout → aucune faute), et la faute qui doit **survivre au
tir mortel**.

`tests/unit/ai/test_analyzer_select_targets_freeze.py` (nouveau) verrouille les deux contrats
internes du gel (défauts 1 et 2 ci-dessus) : les deux lignes d'une activation jugent la MÊME ancre
même après ré-ancrage, et une cible déjà détruite ne produit aucune erreur de parsing.
`test_analyzer_range_uses_pre_loss_positions.py` gagne le cas du défaut 3 : une activation de deux
tirs hors portée dont le premier tue — les DEUX doivent être comptés.

Correctif retiré → `assert 2 == 0`, `assert 0 == 1`, `assert 0 == 1`, `assert 1 == 2`,
`assert 0 == 2` et une erreur de parsing inventée ; rétabli → verts. Les fichiers de test analyzer
voisins (20 fichiers) restent verts.

## Ce qui reste ouvert

Les autres familles du tableau de conformité (collisions, fall-back finissant engagé, move finissant
au contact) ne sont pas investiguées.
