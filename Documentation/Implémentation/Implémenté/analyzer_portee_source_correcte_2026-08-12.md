# La portée d'un tir se juge AVANT les pertes, pas après (2026-08-12)

## Le défaut

`shoot_handler` mesurait la distance tireur→cible en prenant `[TARGET_MODELS:]` de la ligne de log
comme source **prioritaire**. Or ce segment a deux propriétés qui l'interdisent pour ce verdict, et
les deux sont documentées à sa source :

- il liste les **survivants post-pertes** ;
- il n'est émis que sur le **dernier jet** visant la cible (`w40k_core`), donc après retrait de
  toutes les pertes du lot.

La figurine visée — la plus proche, celle sur laquelle le moteur a jugé la portée — en disparaît
dès qu'elle meurt du tir. L'analyzer mesurait alors la distance au survivant suivant, plus loin, et
déclarait le tir hors portée.

`step_logger` énonçait déjà le contrat, sans ambiguïté : ce segment est « consommé **UNIQUEMENT par
le replay** », tenu distinct de `[MODELS:]` précisément « pour ne pas perturber l'analyzer ».
Le consommateur fautif violait une règle écrite noir sur blanc dans le producteur.

## La mesure, avant de corriger

Sur le run de 600 épisodes du 2026-08-12 (27 991 tirs, couverture complète — 0 sans portée connue,
0 sans état antérieur reconstruit) :

| | |
|---|---|
| Verdicts `out_of_range` rendus | 31 |
| **Réellement hors portée** (aussi avant les pertes) | **0** |
| Artefacts | **31** |

Exemples : `E39` Rokkit Launcha (24") mesuré à 23 avant, 27 après ; `E67` Bolt Rifle (24") à 23
puis 25 ; `E70` Rokkit Launcha à 24 puis 26. L'écart est toujours faible et toujours dans le même
sens — signature d'un décalage de mesure, jamais d'un moteur sans contrôle.

⚠️ **Un écart 31 / 42 m'a d'abord fait douter, à tort** : la ligne « Tirs invalides » du rapport
**agrège deux contrôles**, `out_of_range` et `engaged_non_close_quarters`. 42 − 11 = 31. Il n'y
avait pas d'écart.

## La correction

Une ligne : la cible se lit dans `state.positions_by_model`, jamais dans le segment.

Cette source est faite pour ça et le dit : `analyzer_core` la maintient avec un **décalage d'une
ligne**, elle porte l'état jusqu'à la ligne N−1, « qu'exigent les contrôles mesurés à la position
de DÉPART ». À défaut, aucun verdict n'est rendu — mieux vaut ne pas juger que juger sur l'état
d'après.

## Vérification sur le même journal, avant / après

| | avant | après |
|---|---|---|
| Tirs invalides (portée) | 35 | **0** |
| Erreurs phase de tir | 53 | 18 |
| **Total du rapport** | **67** | **32** |

35 erreurs disparaissent, et **exactement** celles-là : aucune autre famille ne bouge.

**Le contrôle n'est pas devenu aveugle** — c'était le risque, et il est écarté par la mesure :
après correction il rend encore **18 702** verdicts de portée sur ce journal, et n'en condamne
aucun. Il mesure, il ne s'est pas tu.

## Verrou (tests/unit/ai/test_analyzer_range_uses_pre_loss_positions.py)

Journal synthétique construisant exactement la situation : cible de deux figurines, une à 12" (à
portée), une à 32" (hors portée d'une arme de 24"). Le tir tue la proche, donc `[TARGET_MODELS:]`
ne liste plus que la lointaine.

Trois tests : la prémisse (les deux distances encadrent bien la portée — sans quoi le test ne
prouverait rien), l'absence de faux positif, et le fait que le contrôle **rende un verdict**.
Source fautive remise → ROUGE (`assert 1 == 0`) ; rétablie → verts.

## Les deux gardes posés ensuite — pour que ça ne recommence pas

Le correctif ci-dessus répare un cas. Deux choses le rendaient **reproductible**, et elles sont
traitées à leur tour.

### 1. Le segment ne peut plus servir à juger — liste blanche opposable

C'était la **deuxième fois** que `[TARGET_MODELS:]` faussait un verdict de distance : la mêlée le
2026-07-24 (contrôle « fight from non-adjacent » retiré), le tir le 2026-08-12. La cause est
structurelle — ce segment décrit un état POSTÉRIEUR à la décision qu'on prétend contrôler — donc
un commentaire ne suffisait pas.

`tests/unit/ai/test_analyzer_target_models_never_judges.py` porte une **liste blanche des
lecteurs** : le parseur lui-même, et `analyzer_core` qui recale l'état après l'action — le seul
usage que le segment décrit. Tout nouveau lecteur rougit, avec le rappel des deux incidents.
Un troisième test épingle le contrôle de portée sur `positions_by_model`.

Verrou prouvé : segment rebranché dans le handler → **deux** tests rouges ; rétabli → verts.

### 2. Le rapport ne peut plus agréger deux contrôles sous un seul chiffre

La section 1.2 affichait `out_of_range` et `engaged_non_close_quarters` additionnés, sous
« Tirs invalides ». Un lecteur a pris ce total pour le seul compteur de portée et a cherché un
écart de 11 avec son propre décompte — écart qui n'existait pas. Un chiffre qu'on ne peut pas
rapprocher de sa source coûte plus qu'il ne rapporte.

Deux lignes distinctes désormais : « Tirs hors portee (10.02) » et « Tirs engage, arme
non-close_quarters ». Le total reste dans la section « SHOOTING VALIDITY », qui le décomposait
déjà — c'est cette dissymétrie qui a piégé.

## Ce qui reste ouvert

Les autres erreurs de tir du rapport n'ont pas été investiguées : `engaged_non_close_quarters`
(11 sur le run du matin), tir engagé sur une unité non engagée, attaque non allouée, advance.
Le rapport de référence d'avant correction est conservé sous
`analyzer_2026-08-12_avant_fix_portee.log` (non versionné, `.gitignore` couvre `*.log`).
