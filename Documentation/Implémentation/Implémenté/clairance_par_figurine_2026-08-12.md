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
| voile rouge du déploiement | les DEUX figurines dans le même plan, sur la même case : verdicts opposés. Un refus global (zone, mur, bord) frapperait les deux, il ne peut donc pas se faire passer pour une décision de clairance |
| formation compacte | la figurine trop haute n'est pas posée sous l'étage, celle qui tient l'est |
| garde de source (4 fichiers) | aucun appel de `low_clearance_ground_hexes` ne reprend la hauteur de l'ESCOUADE, et le NOMBRE d'appels par fichier est opposable — en ajouter un force à relire la liste |

**Preuve de rouge** : hauteur remise sur l'escouade aux six sites couverts par comportement → les
six verrous correspondants rougissent, plus les trois gardes de source ; rétablis → verts.

⚠️ **Quatre des onze appels ne sont couverts que par le garde de source** : ils vivent sur des
branches d'ÉTAGE (montée, descente, ILP d'autoplace) que les pools de plain-pied n'exécutent pas,
et les couvrir par comportement demanderait une mise en scène multi-niveaux par site. Le garde ne
dit rien de ce que le code calcule — il interdit la seule régression réaliste : repasser la hauteur
de l'escouade à un appel, en silence. C'est dit ici parce qu'un garde de source présenté comme un
verrou de comportement serait un faux vert de plus.

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
