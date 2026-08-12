# L'ENGAGEMENT d'une figurine se mesure à SON socle (2026-08-12)

Suite directe de [« l'empreinte d'une figurine se mesure à SON
socle »](empreinte_par_figurine_fight_2026-08-12.md), dont la `/code-review` avait montré que la
correction portait sur les **destinations proposées**, pas sur les **verdicts d'engagement**.

## Le défaut

Le chantier précédent faisait empreinter chaque figurine à son propre socle. Cette empreinte était
ensuite passée à `_charge_synthetic_charger_cache_entry`, qui bâtit son entrée en **copiant la
ligne `units_cache` de l'escouade**. Or les trois chemins de mesure de `entries_in_engagement_zone`
relisent `BASE_SHAPE` / `BASE_SIZE` / `MODEL_HEIGHT` **sur l'entrée** :

| Chemin | Ce qu'il lit | L'empreinte fournie est-elle lue ? |
|---|---|---|
| 2D hex | `entry_footprint` | oui |
| 2D euclidien | `socle_from_cache_entry` (base de l'entrée) | **non** |
| 3D (§03.04) | `_class_footprint` recalcule depuis la base de l'entrée | **non** |

Les onze sites concernés passent tous un `level=`, et les entrées ennemies réelles portent leurs
données verticales : **le chemin pris est le 3D**, à toute échelle, y compris à x1. Un personnage
attaché était donc jugé engagé, ou non, au gabarit du bloc — d'où les « 0 divergence de verdict sur
13 distances » mesurées à la livraison précédente, alors que son empreinte annoncée passait de 19 à
43 hexes.

## La règle, et ce qu'elle impose au code

12.03 AFTER MOVING porte **deux clauses de portées différentes** :

- « **Your unit** must be engaged » — niveau unité ;
- « **Each model** that started this move engaged with an enemy unit must still be engaged with
  that enemy unit » — par figurine.

Et 03.04 est **2" horizontal ET 5" vertical** : la hauteur (`MODEL_HEIGHT`, borne haute de
l'intervalle vertical) appartient à la mesure d'engagement au même titre que le socle.

## La forme livrée

**Par figurine — 13 sites** basculés sur `shared_utils._synth_model_entry`, documentée depuis
l'origine comme la SOURCE UNIQUE de l'engagement par-figurine (« la géométrie de base provient du
MODÈLE, pas du squad ») : onze dans `fight_handlers` (pools de pile-in et de consolidation,
previews de plan, voiles verts, engagements de départ de l'ILP d'autoplace) et **deux** dans
`charge_handlers` — `_charge_model_dest_is_legal` et `charge_preview_move_plan`, les deux seuls de
ses huit sites qui mesurent une figurine ; les six autres servent le pool d'**ancres du bloc** et
restent inchangés, lus un par un.

**Niveau unité — `_fight_synth_cache_entries_at_footprint`** (ex-`..._entry_...`) rend désormais
**une entrée par socle distinct**, chacune portant ses propres centres, empreintes, planchers et
hauteur ; le verdict d'unité est un `any` sur ces entrées. C'est le seul montage exact : une
entrée-cache ne porte qu'un socle, appliqué à tous ses centres. Le partitionnement est exact
(`any` sur les classes = minimum sur les figurines, sur les trois chemins) et **une escouade
homogène rend une seule entrée** — coût inchangé sur le cas courant, ce qui importe pour le BFS
d'ancres du pile-in AUTO.

**Hauteur par figurine.** `build_models_cache` propage `MODEL_HEIGHT` comme il propage déjà le
socle (convention `LD`/`UNIT_KEYWORDS` : la clé n'est posée que si la donnée existe, son absence
lève chez le consommateur), `_build_enhanced_unit` la recopie dans le spec des figurines à
`unit_type` propre, et `_synth_model_entry` lit celle de la figurine quand elle la porte.

**Un quatorzième site, trouvé par le grep JUMEAU et non par la liste d'ouverture** : la
classification du champ de charge (`_compute_plan_context`) ne passe pas par le constructeur
commun — elle bâtit son entrée **à la main**, une seule fois, sur la ligne d'escouade, puis la mute
par cellule pour éviter une allocation dans son poste dominant (~92 % du coût). L'empreinte
candidate venait pourtant bien de la figurine représentative du groupe. Elle est désormais établie
**par groupe de socle**, avec socle, facing et hauteur de la représentante.

Ce site portait un **effet de second ordre** que la lecture seule n'aurait pas donné : une
empreinte de socle 8 (43 hexes) posée sur une entrée de socle 6 (19 hexes) faisait passer le
candidat pour **multi-figurine**, donc basculer du chemin euclidien exact vers le chemin empreinte
dilatée, plus permissif. Sur la configuration de test, **10 cellules sur 263** étaient classées
« engagé » alors qu'aucune mesure ne les y met.

**Hauteur du tir aussi** — même motif, trois lectures dans la LoS 3D de `shared_utils` : la
figurine qui tire et la figurine visée prenaient la hauteur de leur escouade. L'héritage
escouade→figurine vit maintenant dans une source unique, `_model_height_of`, utilisée par
l'engagement comme par le tir.

**Clés de groupement corrigées dans la foulée** — trois endroits validaient les slots d'un groupe
via une figurine représentative : `pile_in_autoplace_plan`, le champ de charge multi-niveaux et
`charge_autoplace_plan`. Tant que la hauteur venait de l'escouade, socle et étage suffisaient à la
déterminer ; depuis qu'elle est par-figurine, `MODEL_HEIGHT` entre dans la clé, sans quoi une
figurine ferait valider ses slots à la hauteur d'une autre.

## Ce que la mesure a donné

Sur les 14 scénarios chargeables du dépôt, en balayant 31×31 cases autour de chaque unité ennemie
pour chaque figurine dont le gabarit diffère de son escouade :

| Mesure | Résultat |
|---|---|
| Figurines au gabarit ≠ escouade | **67 / 684** (mêmes 67 que le chantier d'empreinte) |
| Cases où le VERDICT d'engagement bascule | **21 530 / 575 515** (3,7 %) |
| dont dues à la **hauteur** | **0** |

Comparaison utile : le chantier d'empreinte ne déplaçait que **3 cases sur 330** du pool. Ici
3,7 % des positions changent de verdict — c'est un déplacement d'espace de décision d'un tout
autre ordre, cohérent avec le fait qu'un verdict d'engagement conditionne le droit de piler, de
combattre et de consolider, pas seulement une destination.

**La moitié verticale ne change rien aujourd'hui** : aucune figurine du dépôt ne porte une hauteur
différente de son escouade (0 / 684). Elle est livrée parce que 03.04 est horizontal ET vertical et
que le câblage était incomplet — corriger le socle par figurine en laissant la hauteur au bloc
aurait rendu la règle à moitié juste, sans que rien ne le signale le jour où une datasheet portera
une hauteur propre.

## Verrous (tests/unit/engine/test_engagement_par_figurine_socle.py)

Dix tests sur `scenario_attached_unit_test.json` (Captain socle 8 dans des Intercessors socle 6).
La fixture **cherche elle-même** la bande de cases où les deux socles divergent et échoue si elle
n'en trouve pas : un test posé ailleurs serait vert avec le défaut en place.

Cinq défauts remis un par un, cinq rouges obtenus, chacun rétabli ensuite :

| Défaut remis | Test devenu rouge |
|---|---|
| entrées d'unité rebâties au socle du bloc | `..._unite_est_engagee_par_le_socle_de_son_personnage_attache`, `..._entrees_synthetiques_d_unite_portent_un_socle_chacune` |
| voile vert du pile-in remesuré au socle du bloc | `..._voile_vert_suit_le_socle_de_la_figurine` |
| champ de charge reclassé au socle du bloc | `..._champ_de_charge_classe_chaque_groupe_a_son_socle` |
| `MODEL_HEIGHT` repris sur l'escouade dans `_synth_model_entry` | `..._entree_d_engagement_prend_la_hauteur_de_la_figurine` |
| `MODEL_HEIGHT` retiré de `models_cache` | `..._figurine_porte_sa_propre_hauteur` |

Le verrou du champ de charge a dû être **réécrit** : sa première version n'exigeait que « les
cellules divergentes sont classées engagé », et le défaut la passait au vert — par excès, via la
bascule multi-figurine décrite plus haut. Il compare désormais la classification à la mesure
d'engagement **dans les deux sens**.

Le pool AUTO a son propre fichier, `test_pile_in_auto_kept_engagements_par_figurine.py` (4 tests,
état synthétique) : la mise en scène met l'ennemi **en sandwich** entre deux figurines, seule forme
qui sépare « l'unité reste engagée » de « CETTE figurine reste engagée » sous une translation
rigide. Clause remise au niveau unité → rouge ; rétablie → vert. Deux contre-épreuves l'encadrent :
une ancre qui conserve tout doit rester proposée (sinon un pool vide rendrait le verrou vacant),
et les engagements de départ par figurine sont vérifiés avant tout le reste.

⚠️ Deux mises en scène ont dû être **calibrées par recherche**, pas devinées : la première
géométrie du pool AUTO faisait rejeter l'ancre par la clause WHILE (« end closer ») avant même
d'atteindre la clause testée, et la seconde vidait le pool entier. C'est le genre de faux vert que
seule une contre-épreuve attrape.

Deux contre-épreuves accompagnent les deux verdicts principaux (une figurine hors zone
d'engagement ne doit être ni « unité engagée » ni en vert) : sans elles, une fonction répondant
« engagé » en toutes circonstances passerait les tests principaux. Celle du voile vert garde la
figurine **à portée de cible** (5") — sinon le voile serait vide faute de cible, donc vert sans
rien mesurer.

Le verrou d'empreinte du chantier précédent a dû être ré-visé : son espion ne regardait que
`_candidate_footprint_charge`, et le preview de pile-in ne l'appelle plus (l'entrée d'engagement
recalcule son empreinte). Il espionne désormais **les deux** sources — c'est son assertion
« aucune empreinte calculée » qui l'a signalé.

## Suite immédiate, livrée le même jour (arbitrage tranché par l'utilisateur)

**Le pool d'ancres AUTO lisait une moitié de 12.03.** `pile_in_move_destinations_12_03` (pool du
pile-in PvE/gym, modèle **bloc atomique** déclaré dans sa docstring) vérifiait « chaque engagement
de départ conservé » au niveau UNITÉ, là où la règle l'écrit par figurine — et là où le flux
par-figurine du PvP l'appliquait déjà correctement. Deux flux, deux verdicts sur la même situation.

Corrigé : `_fight_model_start_engagements` relève, avant le move, les unités ennemies tenues par
CHAQUE figurine ; `_fight_models_keep_start_engagements` vérifie ensuite, à chaque ancre candidate
et sur la position TRANSLATÉE de chaque figurine, qu'aucune ne perd les siennes. Les figurines qui
ne partaient engagées avec personne ne sont pas interrogées.

Ce que ça change : une ancre où la figurine qui tenait l'ennemi s'en va pendant qu'une autre s'en
approche était acceptée — l'escouade restait « engagée avec lui ». Elle est maintenant refusée.
Cela **restreint** le pool du pile-in de l'IA, donc son espace de décision, une fois de plus.

## Ce qui n'est PAS traité, et pourquoi

**L'effet sur l'agent entraîné n'est pas mesuré** — comme les trois chantiers de géométrie des
2026-08-11/12, seul un run le dirait. Avec 3,7 % des positions qui changent de verdict, c'est le
plus déplaçant des quatre.

**Aucun exercice PvP en navigateur** : la vérification s'arrête aux appels directs des fonctions
migrées et à leurs tests.
