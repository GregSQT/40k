# Perf géométrie — supprimer le recalcul de zone d'engagement

> **LIVRÉ le 2026-08-11.** Ouvert le 2026-08-10. Décision d'ouverture : **option B** (traiter les
> deux sources dans un seul chantier), retenue contre l'option A (ne cacher que la zone
> d'engagement) parce qu'elle laissait volontairement en place un mécanisme de cache cassé qu'il
> aurait fallu rouvrir ensuite. La suite a montré que ce mécanisme était en fait **sain** (§2bis.a) :
> l'option B a donc coûté une demi-journée pour un résultat nul de ce côté, et c'est le second volet
> — le cache par paire (§2bis.b) — qui porte tout le gain.
>
> ⚠️ **Ce document vaut surtout pour ses PIÈGES DE MÉTHODE.** Trois mesures successives ont donné
> des verdicts contradictoires avant que la bonne méthode ne soit trouvée, et le motif de
> l'exclusion des candidats a demandé quatre passes. Quiconque rouvre ce sujet doit lire §2bis
> AVANT de mesurer quoi que ce soit.

## 1. Ce qui a été mesuré

Profil `cProfile` du 2026-08-10 — évaluation `--test-only --step --resolution 1`, agent
ArmageddonAgent, 12 épisodes, 1 076 steps, 102,4 s profilées (cProfile double environ le temps
réel ; **seules les proportions comptent**).

| Bloc | cumtime | % |
|---|---|---|
| `env_wrappers.step` (tout l'env) | 74,11 s | 72,4 % |
| ├─ `build_squad_observation` | 20,34 s | 19,9 % |
| ├─ `build_squad_move_cell_map` | 14,88 s | 14,5 % |
| │  └─ `erode_move_pool_by_squad_block` | 10,28 s | 10,0 % |
| ├─ `build_squad_action_mask` | 8,17 s | 8,0 % |
| └─ `movement_build_valid_destinations_pool` | 1,94 s | 1,9 % |
| `model.predict` | 15,63 s | 15,3 % |

Poste transverse, réparti sur les trois blocs ci-dessus et donc invisible comme ligne propre :

- `unit_within_engagement_zone_footprints` — **10,57 s (10,3 %)**, 10 560 appels ;
- `_entries_in_engagement_zone_3d` — 96 626 appels, 13,63 s cumulés ;
- `min_distance_between_sets` — **331 816 appels**, 4,98 s ;
- `_vertical_classes` / `_class_footprint` — 193 252 appels chacun, 7,7 s ensemble.

Appelants de `unit_within_engagement_zone_footprints` : le masque d'actions (8 788), le générateur
de `shared_utils.py` (26 603), `_hex_legal_for_charge` (12 589), les pools de charge et de
fight, et l'observation. **Aucun cache entre eux** : la même zone est reconstruite pour le masque,
puis pour le pool, puis pour l'observation, dans le même step, sur le même état de jeu.

## 2. Les deux sources à traiter

### 2.a — Le cache de `build_squad_move_cell_map` rate 69 % de ses appels

La fonction a déjà une mémoïsation intra-step (`game_state["_squad_move_pool_cache"]`), clé sur un
fingerprint LU de l'état réel — et non sur `_unit_move_version`, ce qui avait causé une régression
masque ⊆ exécutable (§0.18). Mesure du 2026-08-10 (marqueur `SQUAD_MOVE_CELL_MAP`, 12 épisodes) :

- **915 miss, 416 hit** — 31 % de taux de hit ;
- `fp_s` (calcul du fingerprint) est payé sur les 1 331 appels, y compris les hits ;
- sur un miss : `pool_s` 476 µs/call, **`erode_s` 2,06 ms/call** (l'érosion par-figurine coûte 4×
  le BFS).

**Inconnue à lever AVANT de toucher au code** : ces 69 % de miss sont-ils légitimes (l'état a
réellement changé entre deux appels) ou la clé est-elle trop fine et jette-t-elle du travail encore
valide ? Le fingerprint a 6 composantes (`advance_roll`, take-to-the-skies, `phase`, battle-shock,
empreinte spatiale de TOUTES les unités, bloc de l'escouade). Tant qu'on ne sait pas LAQUELLE
change, toute optimisation est un pari.

### 2.b — La zone d'engagement 3D n'est cachée nulle part

C'est une **fonction pure de l'état de jeu**, et l'état ne bouge pas entre le masque, les pools et
l'observation d'un même step. La recalculer trois fois est une erreur de conception, pas un coût
inhérent.

⚠️ **Le risque est réel et il est nommé** : un cache mal invalidé sur ce chemin ne produit pas un
plantage, il produit une **règle 40K silencieusement fausse** (un engagement annoncé qui n'existe
pas, ou l'inverse). C'est exactement le mode d'échec de la régression §0.18 citée plus haut. Le
verrou de test n'est donc pas optionnel : il faut prouver qu'une entrée périmée devient ROUGE.

## 2bis. RÉSULTATS — les deux pistes ont ÉCHOUÉ, mesures à l'appui (2026-08-10)

⚠️ **Lire ceci avant de rouvrir le sujet.** Les deux corrections évidentes ont été implémentées et
mesurées le jour même de l'ouverture. Aucune ne paie. Les refaire coûterait la même journée.

### 2bis.a — Le cache de move est SAIN, il n'y avait rien à réparer

Champ `miss_cause` ajouté au marqueur `SQUAD_MOVE_CELL_MAP`, run de 12 épisodes. Répartition des
915 ratés : 235 `advance_roll` seul, 284 `advance_roll+units_fp+block_fp`, 108 `units_fp` seul,
111 `no_entry`, 177 combinaisons diverses.

Lecture initiale — FAUSSE : « le cache n'a qu'un emplacement par escouade, or deux régimes de
budget sont vivants dans un même step (masque d'activation sans jet d'Advance, puis escouade
sélectionnée avec son jet) ; ils s'évincent ». Correction implémentée (clé scindée en état /
variante, variantes gardées côte à côte).

**Résultat : 915 ratés / 416 touches AVANT, 915 / 416 APRÈS.** Gain nul, score d'éval identique
(0,7250). Le champ `miss_cause` recompté après correction l'explique : 531 `state_changed`,
235 `advance_roll`, 111 `no_entry`, 28 `advance_roll+tts`. Chaque variante n'est demandée **qu'une
seule fois** avant que le plateau ne bouge : les garder côte à côte remplit un dictionnaire que
personne ne relit. Les 69 % de ratés sont **légitimes**. Correction annulée.

### 2bis.b — Le cache par paire est un GAIN — et la méthode de mesure l'avait d'abord nié

Implémenté sur `entries_in_engagement_zone`, clé = empreinte de contenu des deux entrées (col/row,
`occupied_hexes`, `occupied_hexes_by_model`, `floor_height_by_model`, `MODEL_HEIGHT`, `BASE_SHAPE`,
`BASE_SIZE`, `orientation`) + zone + métrique + seuil vertical résolu.

**Gain mesuré**, par comptabilité interne à UN SEUL run (coût des clés d'un côté, coût réel des
mesures évitées de l'autre) :

| | touches | purges | mémoire | coût des clés | temps évité | **net** | **ratio** |
|---|---|---|---|---|---|---|---|
| x1 (`--resolution 1`, 24 ép.) | 86,2 % | 5 | 28,0 Mo | 1,20 s | 4,62 s | **+3,42 s** | **3,9×** |
| x5 (`--resolution 5`, 6 ép.) | 84,2 % | 9 | 23,1 Mo | 0,36 s | 1,13 s | **+0,76 s** | **3,1×** |

⚠️ **Lire le RATIO, pas les secondes.** Les secondes dépendent du modèle chargé et de la charge
machine. La campagne du 2026-08-10, sur le modèle précédent, donnait +12,64 s à x1 — mais pour un
ratio de 3,8×, identique. Les secondes ont varié d'un facteur 3,7 entre deux campagnes, le ratio
évité/coût de 3 %. C'est lui la grandeur transposable, et c'est lui qu'il faut comparer si le sujet
est rouvert.

#### Deux défauts trouvés à la review, tous deux réels et corrigés

**(1) Le cache était borné en NOMBRE d'entrées, pas en octets.** Une clé porte deux empreintes
complètes, donc son poids varie d'un facteur 60. Le plafond de 50 000 entrées laissait passer
**4,4 GB par processus** à x5 — et l'entraînement tourne à `n_envs: 48`. Remplacé par une borne
en POIDS (32 Mo), doublée d'un plafond en nombre (30 000) qui, lui, ne dépend d'aucun compteur
partagé.

⚠️ **Le facteur octets/élément a été estimé faux DEUX fois** (50 puis 85) avant d'être mesuré
correctement. `sys.getsizeof` récursif sur une clé isolée ne répond pas à la question : il
double-compte les objets partagés entre clés, ou ignore le surcoût du dict. La seule mesure
honnête est la **croissance RSS du processus** en remplissant le vrai dict avec 20 000 clés
distinctes :

| forme de clé | poids réel | octets/élément |
|---|---|---|
| x1, 1 figurine (1 hex) | 1,45 kB | **246,8** |
| x1, 5 figurines | 3,39 kB | 115,7 |
| x5, 5 figurines (19 hex/fig) | 23,97 kB | 116,9 |
| x5, 10 figurines (43 hex/fig) | 89,43 kB | 101,7 |

Le rapport n'est pas constant, et ce sont les **petites** clés qui paient le plus de surcoût de
conteneur — or ce sont les plus nombreuses (une synthétique par figurine). D'où la borne haute
mesurée, 250, et non une moyenne : une borne qui sous-estime ne borne rien.

**(2) Les boucles de candidats polluaient le cache.** Un pool de move et un BFS de charge
construisent une entrée par CELLULE TESTÉE : clé neuve à chaque fois, jamais redemandée. Avec la
borne en poids, ce flot déclenchait **110 purges** à x5, faisait tomber le taux de touche à 29 % et
retournait le gain à **−0,83 s** — il chassait du cache les paires unité↔unité que le masque, les
pools et l'observation du même step allaient redemander.

Les sources ont été identifiées par échantillonnage des ratés, pas par intuition : `_hex_legal_for_charge`
(60 % des ratés à x5), le générateur de plan de charge `shared_utils:5953` (32 %),
`charge_build_valid_destinations_pool`, plus `move_anchor_violates_engagement_clearance`.

**Ce défaut a demandé TROIS passes, et c'est la leçon du chantier.** (1) N'exclure que
`move_anchor_violates_engagement_clearance` — le seul site deviné par lecture — ne changeait
rien : 110 purges, net −0,83 s. (2) L'échantillonnage des ratés a désigné les 4 sites qui
comptaient dans CE run ; corrigés, le gain revenait. (3) Une review a montré que le motif se
répétait sur 11 sites de plus, dont les jumeaux *sol* et *euclidien* du site déjà corrigé,
**dans la même fonction**. Total : **15 sites** en `memoise=False`.

Le critère qui les sépare est simple et doit être appliqué à tout nouvel appel : l'entrée
décrit-elle une position OCCUPÉE (→ mémoïser) ou une CELLULE TESTÉE (→ `memoise=False`) ?
Restent volontairement mémoïsés `synth_base` (invariant du pré-filtre de charge), `placed_synths`
(plan committé), les synth par-figurine de `shared_utils`, et les entrées `units_cache` directes —
ce sont eux qui produisent les touches.

Ordre de grandeur, pour éviter la surinterprétation : le passage de 4 à 15 sites a fait passer le
gain de +10,00 à +12,64 s à x1 (+26 %), pas d'un gain à une perte. Les mesures antérieures
incluaient bien des phases de charge.

**Quatrième passe (review n°2)** : un 16ᵉ site, `_eng` dans `charge_handlers`. Il reçoit un
`synth_base` construit ~60 lignes plus haut, hors de la boucle — donc « invariant » à la lecture,
et je l'avais explicitement classé « producteur de touches » dans le commentaire du module. Il est
en fait **réécrit à chaque cellule candidate**, ~30 lignes plus BAS que l'appel. Corrigé.

La leçon vaut pour toute reprise : **ce critère ne se vérifie pas en lisant le site d'appel.** Le
nom de la variable et sa distance à la boucle mentent. La seule vérification qui tienne est
l'échantillonnage des ratés en production (une pile d'appel sur 50) : un site qui rate
systématiquement est un site à exclure.

### Mesure finale (2026-08-11, après les deux dernières corrections)

Refaite une fois l'entraînement `x1 --new` terminé, donc **sur le nouveau modèle**. Le tableau du
§2bis.b porte ces chiffres-là. Le plafond mémoire effectif ayant été divisé par 3 (facteur 85 →
250), les purges passent de 1 à 5 (x1) et de 3 à 9 (x5) — le cache reste largement gagnant, et il
tient désormais sous les 32 Mo annoncés au lieu de les dépasser silencieusement.

Commande de re-mesure :

    W40K_PERF_TIMING=1 W40K_PERF_TIMING_MIN_EPISODE=1 p ai/train.py --agent ArmageddonAgent \
      --training-config x1_debug --test-only --step --resolution 1 --test-episodes 4

Elle exige de réinstrumenter temporairement `entries_in_engagement_zone` (compteurs touches/ratés,
chrono des clés, sonde d'une touche sur vingt) : l'instrumentation n'est pas laissée dans le code,
elle coûterait sur le chemin le plus chaud du moteur.

Le prix d'une touche n'est pas déduit du prix d'un raté : une touche sur vingt est **recalculée
quand même**, uniquement pour la chronométrer. Il fallait le mesurer, parce que le résultat est
contre-intuitif — une touche coûte **plus** cher qu'un raté (42,97 µs contre 29,53 µs à x1). Les
paires redemandées sont les paires proches, celles dont les boucles 3D vont le plus loin. Estimer
le gain sur le prix moyen d'un raté le SOUS-estimait de 40 %.

#### ⚠️ L'erreur de méthode qui avait fait conclure l'inverse

Première conclusion, fausse : « le cache ralentit de 7,8 % ». Elle venait d'une comparaison de
**temps CPU entre deux runs**. Cette mesure ne vaut rien ici : les parties jouées diffèrent d'un run
à l'autre, donc le travail aussi. Constaté à x5 sur la même configuration : **184 s puis 279 s** —
50 % de variance, largement au-dessus de l'effet cherché. Les quatre mesures à x1 (46,55 / 50,43
avec, 43,11 / 46,87 sans) tombaient dans cette même bande de bruit.

**Règle pour toute reprise de ce sujet : mesurer les deux moitiés du compromis DANS le même run.**
Jamais deux runs au chronomètre.

#### Un bug que seul x5 révèle

`BASE_SIZE` est un scalaire pour un socle rond mais une **liste** pour un rectangulaire, donc non
hashable dans une clé. Invisible à x1 (roster entièrement rond) : sorti en `TypeError: unhashable
type: 'list'` au premier run à x5. Le même piège est déjà documenté dans `perf_timing.perf_field`.
Verrouillé par `test_empreinte_supporte_un_socle_rectangulaire`.

### 2bis.c — Ce qui reste

Le gain acquis est celui du cache par paire. La conception qui irait plus loin est un **jeton
d'invalidation de confiance** — un compteur d'époque spatiale bumpé par TOUT chemin d'écriture de
position, permettant une clé en O(1) au lieu d'une empreinte re-dérivée. C'est exactement le motif
qui a produit la régression §0.18 (`_unit_move_version` non bumpé par un chemin d'écriture → carte
périmée servie → divergence masque/exécution). Le rendre sûr suppose d'inventorier et de verrouiller
chaque site d'écriture, et un oubli ne lève pas : il rend un verdict d'engagement faux. Ce n'est
plus une optimisation, c'est un chantier d'invariant — à ne pas ouvrir pour un gain marginal.

## 3. Étapes (plan initial — dépassé par le §2bis)

1. **Instrumenter la cause des miss** (§2.a) — reporter, sur chaque `cache_hit=0`, LAQUELLE des
   6 composantes du fingerprint a changé par rapport à l'entrée précédente. ~20 lignes, un run de
   3 min. C'est ce qui décide de la suite : une clé trop fine se répare, un état qui change
   réellement ne se cache pas.
2. **Réparer / resserrer la clé** selon le verdict de l'étape 1.
3. **Cacher la zone d'engagement** (§2.b), invalidée sur le même critère d'état que le point 2 —
   une SEULE notion de « l'état a changé » pour les deux caches, pas deux.
4. **Verrous** — pour chaque cache : remettre le défaut (servir une entrée périmée), vérifier que
   le test devient ROUGE, rétablir, le rapporter.
5. **Re-mesurer** avec `python3 engine/perf_timing.py <avant> <après>` (colonne ms/ep, jamais
   avg/call : supprimer des appels FAIT MONTER le ms/appel restant).

## 4. Instrumentation disponible

Livrée le 2026-08-10, elle couvre les trois blocs dominants — avant elle, les compteurs perf ne
voyaient que **6,5 %** du temps réel d'une évaluation :

- `SQUAD_OBSERVATION` — `ctx_s`, `entities_s`, `entities_n`, `outcome` ;
- `SQUAD_ACTION_MASK` — `cell_map_s`, `ones_n`, `phase`, `outcome` ;
- `SQUAD_MOVE_CELL_MAP` — `cache_hit`, `fp_s`, `pool_s`, `erode_s`, `project_s`, `cells_n`.

Verrouillée par `tests/unit/engine/test_perf_timing_squad_markers.py` (5 tests, dont une
contre-épreuve du vert vacant : perf coupée ⇒ fichier vide).

## 5. Ce qui n'entre PAS dans ce chantier

- Le `--step` qui sérialise l'évaluation (`bot_evaluation.py` force `use_subprocess = False` dès
  que le step logger est actif, annulant les 4 workers configurés). C'est un facteur ~4 sur les
  évaluations, **zéro** sur l'entraînement, et ça se contourne en ne passant pas `--step`.
- Le bot `tactical` à poids 0,0 : c'est un **holdout d'évaluation délibéré et gelé** (V11 §0.55,
  justification dans `config/bot_movement_weights.json`), pas un gaspillage à supprimer.
- `require_key` (5,7 M appels, 1,5 %) et `dict.get` (10,6 M appels, 3,4 %) : c'est le prix assumé
  du style « tout par clé validée ». Hors périmètre sans décision explicite.
