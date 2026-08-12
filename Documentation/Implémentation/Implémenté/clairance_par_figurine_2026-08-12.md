# La clairance sous les étages se mesure à la hauteur de LA FIGURINE (2026-08-12)

Sorti de l'arbitrage du chantier [« l'ENGAGEMENT d'une figurine se mesure à SON
socle »](engagement_par_figurine_socle_2026-08-12.md), option B tranchée par l'utilisateur.

## Le défaut

`low_clearance_ground_hexes` rend les cases de SOL qu'un étage trop bas rend infranchissables pour
une figurine d'une hauteur donnée (§13.06). Ses **onze** appels lui passaient
`unit["MODEL_HEIGHT"]` — la hauteur de l'ESCOUADE — dans des pools qui, pour tout le reste (socle,
facing, niveau, budget), raisonnent **par figurine**. Un personnage attaché plus grand que la troupe
se voyait donc proposer des passages où il ne tient pas ; un plus petit s'en voyait refuser où il
tient.

Deux sites de déploiement allaient plus loin : ils prenaient aussi le **rayon du socle** sur
l'escouade pour le test de clairance en disque, alors que la même fonction lisait le socle de la
figurine pour tout le reste de son verdict.

## La forme livrée

| Fichier | Sites | Ce qui devient par-figurine |
|---|---|---|
| `movement_handlers` | 1 | hauteur du mover |
| `fight_handlers` | 3 | hauteur du mover (pools pile-in / conso) et **par figurine dans l'ILP d'autoplace**, dont l'atteignabilité est calculée figurine par figurine |
| `charge_handlers` | 4 | hauteur de chaque chargeur (BFS plat, champ multi-niveaux, contrôle de légalité, autoplace) |
| `deployment_handlers` | 3 | hauteur **et rayon de socle** (formation compacte, pool par-figurine, voile rouge du plan) |

Deux structures ont dû passer d'un calcul unique à une part **commune** plus une part par
figurine : `path_blocked` (charge) et `ground_obstacles_climb` (ILP de pile-in). La clairance
s'ajoute à l'appel, jamais au préalable — sans quoi elle serait celle de la première figurine
rencontrée.

`_model_height_of` (posé par le chantier d'engagement) reste la source unique de l'héritage
escouade→figurine : la figurine quand elle porte sa hauteur, l'escouade sinon, une erreur explicite
si aucune des deux ne l'a.

## Coût

`FloorIndex.low_clearance` **mémoïse désormais par hauteur demandée**. Sans ce mémo, passer de un
appel par phase à un appel par figurine referait l'union des planchers trop bas à chaque figurine.
Avec lui, une escouade homogène paie exactement ce qu'elle payait — une union — et une escouade à
deux gabarits en paie deux. Les deux sites de déploiement mémoïsent de même leur index de disque
par `(hauteur, rayon)`.

⚠️ Le set rendu est maintenant PARTAGÉ entre appels : les appelants le lisent (`|=` sur leur propre
set, `-=`, `&`), aucun ne le mute. Vérifié par grep sur les onze sites ; la contrainte est écrite
dans la docstring, parce qu'une mutation en place corromprait silencieusement la clairance de
toutes les figurines de cette taille pour le reste de la bataille.

## Effet mesuré

**Aucun aujourd'hui** : sur les 684 figurines des scénarios du dépôt, **zéro** porte une hauteur
différente de son escouade (les socles, eux, divergent sur 67). Ce chantier ne corrige donc aucun
comportement observable actuel — il ferme la moitié verticale d'une règle dont la moitié
horizontale venait d'être corrigée, et il le fait au moment où la donnée par-figurine vient
d'exister.

C'est assumé, et c'est la raison pour laquelle le verrou **fabrique** le cas au lieu de l'attendre
d'un scénario.

## Verrous (tests/unit/engine/test_clairance_par_figurine.py)

Dix-sept tests sur un état synthétique : une escouade de deux figurines (2" et 4") face à un
couloir sous un étage laissant 3" de clairance, un ennemi de l'autre côté du couloir pour que les
pools de pile-in, de consolidation et de charge aient une raison de le traverser.

| Portée | Ce qui est tenu |
|---|---|
| prémisse | `models_cache` porte bien deux hauteurs, et l'étage sépare bien les deux |
| 5 pools par-figurine (move, pile-in, consolidation, charge, déploiement) | la figurine de 2" reçoit des cases sous l'étage, celle de 4" **aucune** — chaque pool a sa contre-épreuve, sans quoi un pool vide rendrait son verrou vacant |
| voile rouge du déploiement — hauteur | les DEUX figurines dans le même plan, sur la même case : verdicts opposés. Un refus global (zone, mur, bord) frapperait les deux, il ne peut donc pas se faire passer pour une décision de clairance |
| voile rouge du déploiement — **rayon de socle** | deux figurines de MÊME hauteur et de socles différents, posées hors du couloir : seul le disque du socle large y déborde. La hauteur est neutralisée, donc seul le rayon peut décider |
| formation compacte | la figurine trop haute n'est pas posée sous l'étage, celle qui tient l'est |
| contrat de la primitive | les trois façons d'écrire l'ancien défaut sont refusées : hauteur nue, escouade passée deux fois, argument manquant |

**Preuve de rouge** : hauteur remise sur l'escouade aux sites couverts par comportement → les
verrous correspondants rougissent ; rayon repris sur l'escouade aux deux sites de déploiement → le
verrou de socle rougit. Tous rétablis → verts. Le contrat de la primitive, lui, se prouve
directement : les trois écritures fautives lèvent.

⚠️ Un défaut de ces verrous a été trouvé par la `/code-review` qui a suivi la livraison :
**le rayon de socle n'était verrouillé nulle part** — toutes les figurines du fichier avaient le
même socle, donc la moitié de la correction était non testée. Corrigé dans la foulée.

## La signature, plutôt qu'un garde (2026-08-12, arbitrage tranché)

La première livraison couvrait sept des onze appels par comportement et surveillait les quatre
autres — les branches d'ÉTAGE, qu'aucun pool de plain-pied n'exécute — avec un test qui **relisait
le texte source** des handlers. La `/simplify` qui a suivi a nommé le vrai défaut d'altitude : la
primitive acceptait un `float` nu, donc rien ne distinguait « hauteur d'une figurine » de « hauteur
d'une escouade », et c'est ce trou qui obligeait à surveiller du texte.

`low_clearance_ground_hexes(terrain_areas, model_entry, squad_entry)` exige désormais les deux
entrées et appelle `_model_height_of` lui-même. Trois façons d'écrire l'ancien défaut, trois refus :
hauteur nue (arité), escouade passée deux fois (erreur explicite), argument manquant (arité). **La
faute n'est plus détectée après coup : elle n'est plus écrivable**, sur les quatre sites d'étage
comme sur les sept autres. Le garde de source disparaît, ainsi que le compte d'appels par fichier
qui figeait la forme de l'implémentation et aurait rougi sur toute factorisation légitime.

Coût : 7 fichiers (la primitive, les 4 handlers, et deux tests qui l'appelaient en direct — dont un
qui commettait exactement la faute interdite au moteur).

⚠️ Le fichier monte le plateau à **x10**. À x1, `geometry_is_hex` court-circuite le chemin
multi-niveaux et la clairance n'est jamais consultée : la première version du test, écrite à x1,
était verte **sans exécuter la ligne corrigée**.

⚠️ Deux autres calibrations ont été nécessaires, chacune signalée par une contre-épreuve qui
refusait de passer : l'ennemi devait être placé de sorte que la bande d'engagement de la charge
recouvre le couloir (sinon le pool de charge l'ignore entièrement), et les deux figurines du plan
de déploiement devaient rester à 2 sous-hexes l'une de l'autre (au-delà, la COHÉSION rougit les
deux et le test ne mesure plus la clairance).

## Ce qui n'est pas vérifié

Le comportement en jeu réel d'une escouade à hauteurs mixtes — aucune n'existe. Et l'effet sur les
modèles entraînés : nul par construction tant que la donnée ne diverge pas, mais il le deviendra le
jour où un roster portera un personnage plus grand que sa troupe.
