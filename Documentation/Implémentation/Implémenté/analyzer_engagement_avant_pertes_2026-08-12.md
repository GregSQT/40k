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

Un gel, posé au même endroit et au même rythme que les gels d'effectif déjà en place
(`shot_sequence_target_models`, [BLAST] 24.05) : `analyzer_core` instantanie vivacité, ancre et
socles **avant** les dégâts (`unit_hp_pre_line`, `unit_positions_pre_line`,
`positions_by_model_pre_line`), et `AnalyzerState.select_targets_engagement_maps` rend aux contrôles
les trois cartes avec la cible telle qu'elle était au **Select Targets step de l'activation**.

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

## Vérification sur le même journal, avant / après

| | avant | après |
|---|---|---|
| Tir engagé visant une unité NON engagée (10.06) | 1 | **0** |
| Erreurs phase de tir (§1.2) | 18 | **17** |
| Tirs `[CLOSE_QUARTERS]` classés « cible engagée » | 58 / 224 | 70 / 236 |
| Tirs `[CLOSE_QUARTERS]` classés « cible non engagée » | 1157 / 1713 | 1145 / 1701 |
| Usage de la règle CLOSE_QUARTERS (§1.8) | 13 825 | 13 849 |

Le total de tirs close-quarters ne bouge pas (1 215 / 1 937) : ce sont **24 tirs reclassés**, ceux
dont la cible mourait du coup. Les 24 usages de règle en plus sont la même cause, au même endroit
(`shoot_handler`, compteur §1.8 conditionné à `shooter_engaged_with_target`). **Aucune autre famille
du rapport ne bouge.**

## Verrou

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

Correctif retiré → `assert 2 == 0`, `assert 0 == 1` et `assert 0 == 1` (le faux positif de tir
10.06, le faux négatif de mêlée 12.04, le faux négatif de tir 04.02) ; rétabli → verts. Les fichiers
de test analyzer voisins (20 fichiers) restent verts.

## Ce qui reste ouvert

Les autres familles du tableau de conformité (collisions, fall-back finissant engagé, move finissant
au contact) ne sont pas investiguées.
