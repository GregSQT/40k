# ROADMAP — source unique de l'ordre du travail

> **Rôle.** Ce fichier est la SEULE source de vérité sur « qu'est-ce qu'on fait ensuite ».
>
> **Trois dossiers, trois rôles distincts** (`2_Various/` dissous le 2026-08-10) :
>
> | Dossier | Contient | Ce qu'on y cherche |
> |---|---|---|
> | [`1_Agent/`](1_Agent/) | la spec et l'état du programme V11 (4 docs) | le **détail** d'une tranche, un piège de méthode |
> | [`A_faire/`](A_faire/) | le backlog des chantiers ouverts | le **contenu** d'un chantier à faire |
> | [`Implémenté/`](Implémenté/) | les chantiers livrés | la **référence** de conception d'un truc déjà fait |
> | **racine** (2 docs) | les **références transverses vivantes** : [`Replay.md`](Replay.md) (contrat `step.log`, pipeline, registre replay) et [`analyzer_couverture.md`](analyzer_couverture.md) (matrice règle → contrôle → champs de log) | ce que le journal **porte**, et ce qu'il **ne porte pas encore** |
>
> Aucun des quatre ne donne l'ordre du travail — il est **ici, et nulle part ailleurs**.
> ⚠️ Les deux docs racine ne sont ni des chantiers à faire, ni des chantiers livrés : ce sont des
> **contrats permanents**, relus à chaque livraison qui touche le journal. Ils portent en revanche
> du travail ouvert, et **ce travail a sa ligne en §4** — ajoutée le 2026-08-10, quand on a constaté
> qu'ils n'étaient cités nulle part ici alors que ce fichier se déclare source unique de l'ordre.
> ⚠️ **Une troisième chose traîne à la racine et n'y a pas sa place** : [`Security.md`](Security.md)
> est un **chantier ouvert** (étapes 4→8, §4), donc du ressort d'`A_faire/` selon la 2ᵉ ligne de ce
> tableau. Son déplacement à la racine a d'ailleurs cassé le lien relatif que
> `A_faire/perf_noyau_natif_et_gzip.md` pointait vers lui (réparé le 2026-08-10, seul lien mort du
> corpus). Le remettre en `A_faire/` est un `git mv` + 2 liens : à faire, ou assumer la 3ᵉ exception.
>
> **Règles d'arbitrage entre docs** (établies le 2026-08-10) :
> 1. **Le code fait foi** sur fait/pas fait. Un doc contredit par le code est périmé, pas le code.
> 2. **La décision datée la plus récente tranche l'approche.** Les décisions sont recensées dans
>    `V11_agent_rework.md` §0 (tableau récapitulatif) et dans les amendements des chantiers.
> 3. **Sur les priorités, ce fichier l'emporte** sur tout autre doc, y compris `V11_agent_rework.md`
>    §0 et sa colonne « Ordre ». Sur le détail et l'état de V11, c'est l'inverse.
> 4. Conflit résiduel → section « Arbitrages ouverts » ci-dessous, tranchée par l'utilisateur.
>
> **Discipline.** Tout nouveau chantier prend une ligne ici AVANT d'ouvrir un doc de détail.
> Un chantier livré passe son doc en `Implémenté/` et sa ligne ici à jour DANS la même livraison.
>
> État vérifié contre le code le **2026-08-10** (tous dossiers balayés, exécutions à l'appui).

---

## 0. En cours — ne rien casser

- ✅ **Socle vs mur : une seule géométrie, et la sortie de contact** (2026-08-11). Symptôme PvE :
  un Terminator déployé le long d'une ruine ne peut plus bouger de la partie, reste en arrière de
  son escouade et passe en voile rouge de cohésion. Cause MESURÉE : le **placement** mesurait un
  hex de mur par son CENTRE (empreinte hex) pendant que la **traversée** le mesure comme un
  HEXAGONE. Les deux critères divergent sur la bande `r < d <= r + circumradius` — une figurine
  posée là est légale et n'a aucun premier pas possible. Sur `terrain-mc1` : **664 ancres** au pool
  de mouvement VIDE, dont **198 dans les zones de déploiement**. Le défaut vit sur les géométries
  **obliques** (0 sur un mur droit, 40 sur une diagonale, 25 sur un coin).
  Corrigé en deux pièces indissociables : (A) le placement adopte la géométrie d'hexagone —
  `hex_utils.socle_blocked_anchor_cells`, source unique routée dans les 9 sites de placement, y
  compris le masque gym ; (B) les obstacles déjà chevauchés par le socle au départ ne dilatent
  plus, mais gardent leurs cases bloquantes (09.07 : seul Desperate Escape traverse les figurines
  ennemies) — sans quoi une unité **au contact ne peut pas faire son Fall Back** (mesuré : 0 → 1277
  destinations). L'exception est bornée aux pas partant de la position réelle du mobile.
  DÉCISION UTILISATEUR : les murs restent bloquants **à tous les niveaux** — la cohérence
  géométrique retire 16 ancres d'étage de plus que l'ancien critère (85 contre 69 sur 458), sans
  divergence masque/exécution. ⚠️ **L'espace de décision de l'IA change dans les deux sens** : le
  run `--new` de vérification ci-dessous doit le mesurer, les modèles antérieurs ne sont plus
  comparables.
  À FAIRE : la vérification large de l'utilisateur (suite complète, `pyright`, conformité, PvE
  navigateur) n'a **pas** été passée au merge — seuls les 12 fichiers de test du périmètre l'ont
  été (125 tests, dont 12 verrous prouvés rouges par mutation).
  SIGNALÉ, NON TRAITÉ : « on peut tirer à travers un mur quand on est à l'étage » relève de la
  LoS, pas du placement — chantier distinct, non ouvert.

- ✅ **Contrôle d'objectif perdu quand deux phases s'enchaînent dans la même action**
  (ouvert ET livré le 2026-08-12). Symptôme PvE rapporté : Dreadnought posé DANS un terrain-objectif, objectif neutre,
  et **aucune** ligne `OBJECTIVE` au journal de partie. Cause MESURÉE, et ce n'est PAS le comptage :
  une figurine en `(102,132)` est bien dans `ruin_center_OK` (colonnes 85→134, lignes 120→180) et
  `calculate_objective_control` rend `controller=1` avec `OC P1=4`. Le défaut est dans le
  DÉCLENCHEMENT : `refresh_objective_control_on_boundary` ne retient que la DERNIÈRE frontière vue
  et teste `_match(old,"end") or _match(new,"start")`. Or `execute_semantic_action` enchaîne les
  phases en cascade dans une seule action (`w40k_core` ~6740) : quand la dernière pose de
  déploiement fait passer `deployment → command → move`, la seule frontière observée est
  `deployment → move`, qui ne correspond à AUCUN point configuré. Le checkpoint de fin de phase de
  commandement du tour 1 est perdu, `_objective_control_detail` reste absent, et l'objectif reste
  neutre en silence pendant TOUTE la phase de mouvement du tour 1. Reproduit headless : roster
  ADEPTUS ASTARTES (Oath en attente → la cascade s'arrête, pas de défaut) vs roster TYRANIDS
  (aucune décision → cascade → 0 ligne `OBJECTIVE`).
  DÉCISION UTILISATEUR (2026-08-12) : option A — le moteur **mémorise la suite des phases
  franchies** et les solde une par une, au lieu de ne regarder que les deux extrémités. Ajouter
  `deployment/end` aux points configurés a été ÉCARTÉ : ça ne ferme que le cas du jour et laisse
  le même trou sur toute autre cascade.
  LIVRÉ : `game_utils.enter_phase` devient l'ÉCRIVAIN UNIQUE de `game_state["phase"]` (9 sites
  routés, plus aucune écriture directe hors du helper — grep à l'appui) et empile chaque phase
  franchie ; `refresh_objective_control_on_boundary` draine cette file et solde les frontières
  une par une, la fin de TOUR n'étant soldée que sur la dernière. Un état sans file (fixture de
  test, sauvegarde restaurée) retombe sur les deux extrémités, donc le comportement d'avant.
  Vérifié : reproduction PvE roster TYRANIDS passée de « 0 ligne `OBJECTIVE`, contrôle jamais
  calculé » à « contrôle calculé dès l'entrée en mouvement » ; reproduction roster SPACE MARINES
  inchangée ; 12 tests du fichier 14.02 verts dont le verrou prouvé rouge par mutation ; 112
  tests ciblés (cascade, step, action sémantique, déploiement, API, journal) verts.
  CORRECTIF DE SUITE (même jour, trouvé par `/code-review` et confirmé par le journal d'une
  partie réelle) : solder chaque frontière une par une REJOUAIT `calculate_objective_control`
  sur un état identique, donc `previous_controller` valait le contrôleur qu'on venait d'écrire
  et le journal disait « held by Px » sur une CAPTURE (`tri_2 Centre` n'a jamais eu sa ligne
  « captured by P1 »). Les frontières d'une cascade séparent des états IDENTIQUES : la
  détermination 14.02 est UNE, pas N. La boucle s'arrête désormais à la première frontière qui
  tire, et `run_objective_control_checkpoint` rend un booléen pour le dire.
  À FAIRE : la vérification large de l'utilisateur (suite complète, `pyright`, conformité, PvE
  navigateur) n'a **pas** été passée.

- ✅ **Un objectif capturé ne changeait jamais de couleur sur le plateau** (ouvert ET livré le
  2026-08-12). Symptôme PvE : « les Dreads ne prennent pas les objos », la ruine centrale restait
  neutre. Le moteur, l'API et le mappage étaient HORS DE CAUSE — trois diagnostics faux ont été
  rendus avant de le prouver (comptage d'empreinte, couleurs de contrôle, étages du décor), tous
  déduits d'une capture d'écran au lieu d'une mesure. Ce qui a tranché : un affichage TEXTE des
  objectifs tenus dans l'en-tête joueur, puis une trace inconditionnelle en tête de `drawBoard`.
  CAUSE MESURÉE (trace console) : le plateau PIXI a DEUX calques, statique (fond, décor, couleur
  de contrôle des objectifs, invalidé par `bcKey`) et surbrillances (previews, invalidé par
  `computeDrawBoardPartialRedrawFingerprint`). Le chemin rapide de `BoardPvp` court-circuitait
  `drawBoard` sur la SEULE réutilisabilité des surbrillances — or `objectiveControl` n'apparaît
  nulle part dans leur empreinte (`grep` → 0). Une capture qui ne change pas les surbrillances
  n'était donc jamais dessinée : trace réelle = **une** reconstruction (`rect b SE` déjà tenu,
  ruine pas encore), puis `calqueReutilise: true` pour le reste de la partie.
  CORRIGÉ : la décision passe par `utils/boardRedrawDecision.planBoardRedraw`, source UNIQUE des
  trois gestes du rendu (appeler `drawBoard`, conserver le calque statique, conserver les
  surbrillances). Instruments de diagnostic retirés (traces console) ; l'affichage
  « Objectifs tenus » a servi à prouver que le moteur avait raison, puis a été retiré.
  VALIDÉ AU NAVIGATEUR le 2026-08-12 : la ruine centrale devient bien bleue à la capture.
  DEUXIÈME PASSE, même jour (`/code-review` sur la première) : corriger le point ci-dessus avait
  rendu ATTEIGNABLES deux chemins de nettoyage de scène jusque-là morts, tous deux du même genre
  — un conteneur périmé laissé visible sur le stage. (a) le calque statique périmé était
  ré-attaché puis `drawBoard` insérait le neuf en index 0, donc EN DESSOUS (zIndex égaux, tri
  stable) : l'ancienne couleur masquait la nouvelle et les remplissages de terrain se doublaient,
  si bien que le symptôme visé n'était PAS corrigé au rendu de la capture ; (b) les surbrillances
  conservées restaient sur le stage pendant que `drawBoard` en ajoutait de nouvelles — previews
  et contours d'étage en double, alpha doublée, anciens orphelins jusqu'au balayage suivant.
  Cause commune : trois décisions prises séparément et libres de se contredire. Elles dérivent
  désormais d'un seul plan, dont l'invariant est « on ne conserve jamais un calque que
  `drawBoard` va recréer ». Trois verrous, chacun prouvé rouge par sa propre mutation.

- ✅ **Le coût de la clé de contrôle d'objectif — supprimé du chemin chaud** (ouvert ET livré le
  2026-08-12, suite directe de la ligne ci-dessus). L'effet de dessin de `BoardPvp` se réexécute à
  cadence de souris (ses dépendances portent `movePreview`, les plans d'escouade, `blinkVersion`),
  et il reconstruisait à chaque fois la table `objectiveControl` (~10 500 entrées sur
  `terrain-mc1`, ~1 Mo jeté → pression GC pendant un glisser) puis la sérialisait triée pour en
  faire `objControlKey` — une chaîne de 86 ko, pour distinguer **cinq** valeurs, une par zone.
  CORRIGÉ en deux pièces : (A) la clé est dérivée des zones (`utils/objectiveControlKey.ts`), en
  lisant l'hex ÉCHANTILLON que `BoardDisplay` lit déjà (« any zone hex works ») ; (B) la table est
  mémoïsée sur `objective_controllers` / `objective_zones` / l'override de replay, donc reconstruite
  une fois par réponse API au lieu d'une fois par mouvement de souris — sa référence devient stable.
  MESURÉ (vite-node, 5 zones × 2 116 sous-hex, moyenne sur 200 à 20 000 itérations) :
  **6,40 ms/rendu → 0,001 ms/rendu** (1,96 ms de table + 4,31 ms de clé, supprimés du chemin chaud).
  CONTRAINTE TENUE : la clé gouverne `bcKey` → `canReuseStatic` → l'invalidation du calque statique,
  et une clé qui rate un changement de contrôle réintroduirait le défaut livré plus haut (objectif
  capturé jamais bleu). L'équivalence avec la clé exhaustive est verrouillée par
  `objectiveControlKey.test.ts` (7 tests, comparaison paire à paire sur 7 instantanés successifs),
  dont quatre verrous prouvés ROUGES par mutation. Deux pièges nommés et couverts : l'override de
  replay REMPLACE la table (la clé lit la table effective, jamais le `gameState`), et la géométrie
  des zones — que l'ancienne clé portait par accident — passe dans une empreinte djb2 mémoïsée,
  sans quoi deux épisodes de replay aux zones différentes se partageraient le calque statique.
  PASSE `/simplify` le même jour : la clé `oc` sort à son tour de l'effet de dessin (mémoïsée), la
  clé `zonesKey` (identifiants + formes, une boucle par rendu) fusionne dans l'empreinte de
  géométrie, le djb2 est mutualisé avec celui des murs, et `BoardDisplay` appelle désormais
  l'échantillonneur du module à ses deux sites — l'invariant « la clé lit le même hex que le
  rendu » devient structurel au lieu d'être documenté.
  ÉCARTÉ, à arbitrer séparément : scinder `bcKey` en clé de géométrie et clé de contrôle pour ne
  plus reconstruire fond et murs à chaque capture d'objectif ; sortir tout `bcKey` dans
  `boardRedrawDecision.ts`, à côté de l'invariant qu'il alimente.
  RESTE : la validation navigateur (une capture d'objectif doit toujours recolorer la zone).
  SIGNALÉ, NON TRAITÉ (même motif, hors périmètre de clôture — un prompt de chantier existe) :
  `BoardWithAPI.tsx:581` recopie les ~10 500 hexes d'objectif à chaque rendu, `BoardPvp.tsx:9290`
  les aplatit dans l'effet de dessin, `BoardPvp.tsx:11253` rebâtit un `Set` de ~1 000 murs par
  rendu pendant le glisser de déploiement.

- ✅ **Les trois aplatissements volumineux restants du chemin de rendu** (ouvert ET livré le
  2026-08-12, suite directe de la ligne ci-dessus, qui les avait signalés sans les traiter — ils ne
  portaient pas le motif corrigé ce jour-là, donc ils n'entraient pas dans son périmètre de clôture).
  Même motif que la clé de contrôle : un tableau volumineux reconstruit à chaque rendu alors que sa
  source ne change qu'au chargement d'un plateau ou d'une réponse API.
  MESURÉ (node, 5 zones × 2 116 sous-hex = 10 580 hexes, 1 000 murs, 3 exécutions) :
  normalisation des objectifs 0,10 ms, aplatissement en couples 0,15 ms, `Set` de murs 0,07 ms —
  **≈ 0,32 ms et ~21 000 objets jetés par rendu → sous 0,0001 ms** une fois mémoïsés.
  LE VRAI COÛT n'était PAS ces 0,32 ms : la sortie de la normalisation descend en prop
  `objectivesOverride`, qui figure dans les DÉPENDANCES du gros effet de dessin de `BoardPvp`. Une
  référence neuve à chaque rendu y rejouait tout le dessin PIXI, même quand rien de dessinable
  n'avait bougé — et, en repli replay-sans-board, invalidait l'empreinte de géométrie livrée la
  veille. C'est ce lien-là, pas les millisecondes, qui justifiait le chantier.
  Les trois dérivations vivent désormais dans `hooks/useBoardHexMemos.ts`, hors des composants,
  pour que leur IDENTITÉ soit verrouillable : une mémoïsation ne se prouve pas par la valeur (elle
  rend la même dans les deux cas) mais par `Object.is` entre deux rendus. 17 tests, dont **trois
  verrous prouvés ROUGES par mutation** (un par hook).
  PIÈGE NOMMÉ ET VERROUILLÉ : l'effet de dessin COMPLÈTE `boardConfig.wall_hexes` EN PLACE (rangée
  du bas, colonnes impaires). Le tableau garde donc sa référence en changeant de contenu : le `Set`
  des murs se mémoïse sur la référence ET la longueur, sans quoi le glisser de déploiement tiendrait
  la rangée du bas pour libre. La mutation elle-même reste en place, cf. arbitrage ci-dessous.
  RESTE : la validation navigateur (glisser de déploiement le long de la rangée du bas ; couleurs
  d'objectif inchangées).
  SIGNALÉ, NON TRAITÉ (hors périmètre, arbitrage à rendre) : la mutation en place de
  `boardConfig.wall_hexes` rend le contenu de la config dépendante de l'ordre des passages de
  l'effet — cinq appels LoS lisent ce tableau et n'y voient pas la même chose avant et après le
  premier dessin. `wallsFp` (hachage djb2 des ~1 000 murs dans `bcKey`) reste calculé par rendu.

- ✅ **PvE se figeait — cause identifiée et corrigée** (2026-08-11). Le symptôme était rapporté
  « en phase de mouvement » ; la mesure a montré la phase de **déploiement**, sur des unités
  simplement **pas encore posées** (`deployed_on_turn=None`, `in_strategic_reserves=False`) — les
  réserves stratégiques n'étaient pas en cause. L'effet de « baseline de portée depuis la position
  actuelle » de `BoardPvp` tourne aussi en déploiement, où l'unité en cours de placement n'a pas
  de position : il demandait un aperçu de tir depuis la sentinelle `(-1,-1)`, le backend refusait
  (20.01), la requête partait en 500 et tuait la boucle appelante. L'effet sort désormais sans
  requête quand l'unité n'est pas sur la table, avec le **même prédicat que le moteur**.
  Le garde qui a permis le diagnostic reste en place comme assertion de contrat sur les deux
  previews « depuis une position » (`_require_preview_destination_on_table`).
- ✅ **Livraison 2026-08-11 — l'aperçu de tir se place PAR FIGURINE pendant un placement**
  (trouvé par `/code-review` sur la livraison ci-dessus, même classe de défaut, danger déplacé de
  la destination vers l'unité). Pendant un placement figurine par figurine — déploiement en cours
  ou `perModelMove` — le plan vit dans le CLIENT : le moteur n'en sait rien avant validation, donc
  l'escouade y est hors table avec `occupied_hexes_by_model` à `(-1,-1)`. L'aperçu était placé par
  l'ANCRE, or `update_units_cache_position` ne resynchronise les figurines que pour les escouades
  MONO-figurine : sur une multi-figurine, l'ancre passait sur le plateau pendant que ses figurines
  restaient à la sentinelle, et `_socle_from_entry` mesurait distances et LoS **depuis le coin du
  plateau, sans lever** — un verdict inventé, exactement ce que `require_entry_on_battlefield`
  refuse ailleurs. Le Dreadnought (mono-figurine) n'était pas touché ; toute escouade l'était.
  Nouveau `preview_shoot_valid_targets_from_model_positions` + action API
  `preview_shoot_from_model_positions`, jumeaux de ceux qui existaient déjà pour la détection
  (13.09). Les figurines sont posées par `update_model_position`, l'écrivain RÉEL de la pose :
  l'aperçu et l'état après validation décrivent la même géométrie. Le client fait désormais UN
  appel portant toutes les figurines au lieu d'un par figurine — le pool de cibles est une
  propriété de l'escouade, pas d'une figurine isolée.
  ⚠️ **Complété le jour même** (2ᵉ `/code-review`) : le premier jet n'envoyait que `(col, row)` et
  perdait le **niveau** et l'**orientation** du plan. Une figurine déployée à l'étage d'une ruine
  était donc prévisualisée AU SOL — blink et couvert basculaient après validation, c'est-à-dire la
  divergence même que ce chantier supprime, déplacée d'un cran. L'action prend désormais le plan
  au format CANONIQUE `[[model_id, col, row, level, orientation?]]`, lu par le MÊME parseur que la
  pose réelle (`parse_model_plan_with_orientation`). Éviction du cache d'aperçu alignée sur les
  trois autres écrivains, et le commentaire qui promettait un « cache hit » du survol est corrigé :
  cet aperçu porte l'escouade entière, le survol une figurine — ils ne peuvent pas partager
  d'entrée, une pose coûte donc un aperçu backend complet.
  ⚠️ **3ᵉ `/code-review`, bug reproduit headless** : le niveau du plan est celui de la **VUE** au
  drop, estampé sans distinction sur toutes les figurines. Écrit tel quel, il faisait lever le
  moteur (« figurine marquée à l'étage mais hors empreinte de plancher ») → 500 → le client
  **perdait tout son calque de LoS**, son `catch` avalant l'erreur. L'aperçu résout désormais le
  niveau EFFECTIF avec `resolve_model_floor_level`, le même résolveur que les chemins de commit :
  la garantie vit dans le moteur, pas dans la discipline de l'appelant. Trois rondes de review
  auront été nécessaires sur ce chantier, chacune trouvant la divergence aperçu/validation
  déplacée d'un cran.
  ⚠️ **Encodeur de plan re-centralisé** : ce chantier avait recopié l'encodage du plan dans
  `BoardPvp` alors qu'un encodeur partagé existait — et que son propre commentaire racontait que
  ces copies avaient déjà produit deux dialectes de défaut pour l'étage. La review suivante a
  d'ailleurs trouvé un bug de niveau à cet endroit précis. L'encodeur vit désormais dans
  `frontend/src/utils/modelPlan.ts` (et non dans `useEngineAPI`, ce qui rendait la copie tentante
  pour un composant), avec ses tests : la prochaine divergence sera visible au lieu d'être
  silencieuse.
- 🔜 **Run `--new` ArmageddonAgent `x1` de VÉRIFICATION — à lancer** (2026-08-11). Ce qu'il doit
  prouver n'est pas un progrès mais que le pipeline tourne de bout en bout avec un **espace de
  décision modifié** (l'alignement de la charge sur 11.02, ci-dessous). À lire dans l'ordre :
  `game_critical/invalid_action_rate` reste à **0** (il dirait qu'un slot ouvert n'est pas
  exécutable, le risque propre à ce chantier), `02_combat/n_charge_success_rate` proche de **1.0**,
  et `02_combat/m_charge_attempts` **non nul** — à zéro, le masque ne proposerait plus jamais de
  charge, ce qui serait la régression à attraper. Les courbes `reserves/*` et `charge_distance/*`
  doivent être **peuplées** : ce sont elles qui rendent ce run utile au-delà du contrôle de
  pipeline, et c'est la raison pour laquelle il vient APRÈS les chantiers de métriques.
  `--new` et non `--append` : ce dernier réapplique les hyperparamètres de `x1` au modèle chargé,
  dont `ent_coef` qui repart à 0,1, et écrase le modèle canonique. `--new`, lui, archive les
  artefacts précédents (`archive_canonical_artifacts_for_new_run`).
- ✅ **Livraison 2026-08-11 — la distance à un objectif se mesure à son AIRE, plus à son centroïde.**
  Un objectif est toute l'aire de terrain (14.02), soit 1 730 à 3 000 hexes sur le scénario PvE.
  Les **quatre** sites qui demandaient « quel objectif est le plus proche » la réduisaient à son
  centroïde : une unité posée sur le bord d'un objectif — donc dedans, donc en train de le
  contrôler — ressortait à une trentaine d'hexes de « son » objectif. Nouveau module
  `engine/objective_distance.py` (segments par colonne → carte mémoïsée, exactitude vérifiée
  contre une énumération naïve) ; les deux fonctions centroïde sont supprimées, plus aucun
  appelant. Mesuré : 0,3 µs par appel courant, +0,45 ms par scoring de déploiement, 645 Ko.
  ⚠️ **Deux des quatre sites alimentent l'observation de l'agent** (zone intent, scoring de
  déploiement) : le modèle actuel a appris avec le centroïde, **le gain demande un
  ré-entraînement pour être mesuré**. À joindre au prochain run `--new`.
  Livré avec le **journal de contrôle d'objectif** côté API : une ligne par objectif disputé à
  chaque frontière de phase (sommes d'OC, figurines présentes dans l'aire, verdict), qui répond
  à « pourquoi mon unité posée sur l'objectif ne le prend pas » sans ouvrir la console.
  ⚠️ **Complété le 2026-08-12** : le journal se taisait quand PERSONNE n'était sur un objectif, et
  ce silence ne se distinguait pas d'un journal cassé — il a fallu trois sondes du chemin API pour
  établir que le mécanisme fonctionnait, alors que la réponse ÉTAIT « personne n'est sur un
  objectif ». Une ligne « aucun objectif disputé » sort désormais **une fois par tour** (et non par
  frontière : six lignes identiques par tour auraient rendu illisible le journal qu'elles éclairent).
  ⚠️ **Deux trous refermés le jour même** (`/code-review`) : la déduplication du silence n'était
  jamais relâchée, donc une table qui se vidait APRÈS avoir été occupée dans le même tour — la
  dernière figurine d'une aire qui meurt en combat — retombait muette, exactement le cas ambigu
  visé ; et le test de vacuité ignorait le contrôleur, si bien qu'en méthode `secured` (14.03,
  contrôle persistant) un objectif encore tenu à 0 OC aurait été déclaré « non disputé » pendant
  que le joueur marquait dessus.
- ✅ **Livraison 2026-08-11 — distances de charge au `step.log` et en métriques.** Distance à
  l'ennemi le plus proche **à la déclaration** (11.02.1) et distance à la cible **au choix**
  (11.04), mesurées par la primitive qui porte déjà le gate 11.04 — donc par figurine, dans la
  métrique du moteur, sans second oracle. Le trajet réel n'est PAS mesuré : il n'existe ici que
  borné par le jet ou par ancre, l'un tronqué, l'autre divergent de l'oracle par-figurine.
  **Sept** sites de journalisation, pas cinq : le décompte annoncé oubliait le chemin **gym**
  (`w40k_core`), celui-là même qui produit le step.log d'entraînement.
  10 courbes `charge_distance/*` (deux camps × plus proche, cible, cible réussie, cible ratée,
  part à ≥ 9"), dérivées des **mêmes lignes de journal** que `m_charge_attempts` : un seul
  compteur par événement, pas deux qui pourraient diverger. Une activation close sur WAIT
  n'émet aucune ligne, donc n'entre dans aucune statistique.
  → [`Implémenté/metriques_reserves_et_charge_2026-08-11.md`](Implémenté/metriques_reserves_et_charge_2026-08-11.md) §Ce qui reste
- ✅ **Livraison 2026-08-11 — métriques (réserves), barème et alignement de la charge sur 11.02.**
  Sept tranches, chacune partie d'une mesure du run `x1_long` du même jour.
  → [`Implémenté/metriques_reserves_et_charge_2026-08-11.md`](Implémenté/metriques_reserves_et_charge_2026-08-11.md)
  ⚠️ **Le modèle du run de 50 000 épisodes est caduc** : la phase de charge ne propose plus les
  mêmes décisions. Ses poids restent chargeables, mais ses statistiques de charge ne veulent plus
  rien dire.
- ✅ **Run `--new` ArmageddonAgent x1 — TERMINÉ** (PID 842478 absent, dernier checkpoint 15 h 18,
  `run_20260810-111734`). C'était une **base de développement, PAS la mesure** (décision
  2026-08-10) : modèle chargeable + sortie d'`analyzer.py` pour les tranches P3, rien de plus. Son
  modèle deviendra inchargeable dès P3-4. `x1` = **10 000 épisodes** (`total_episodes`, et non
  50 000 qui est la clé de commentaire `total_episodes_normal`).
  → [`1_Agent/V11_agent_rework.md`](1_Agent/V11_agent_rework.md) §0.70
- **Conséquence immédiate : plus rien n'est gelé.** La consigne « ne rien lancer de cassant, aucun
  JSON de `config/` » tombe avec le run. Ce qui était différé à ce titre redevient faisable —
  notamment la `justification` d'`obs_size` (§5) et l'ajout d'un profil de validation P5 (§1 pt 6).
- ⚠️ **Rien n'est en cours. Cette section doit être VIDE ou décrire un run vivant** — un 🟢 périmé
  gèle du travail pour rien, ce qu'il a fait entre 15 h 18 et sa correction.

## 1. Chemin critique vers la mesure de référence

Ordre imposé par les décisions du 2026-08-07 et 2026-08-10 : la mesure de référence (`x1_long`,
600 parties/bot) est **différée** jusqu'à livraison de tout ce bloc. D'ici là le projet est SANS
mesure, et c'est assumé (§0.14).

1. **P3-4 — Allocation des pertes défenseur** (= L3) → [`1_Agent/V11_phaseA.md`](1_Agent/V11_phaseA.md) §9.4 pt 4
2. **P3-5 — Pile-in / consolidation** (= L4) — **bloqué en amont** par la migration par-figurine
   du pile-in auto V11 → [`A_faire/pile_in_overrun_par_figurine.md`](A_faire/pile_in_overrun_par_figurine.md).
   Décision spatiale ⇒ top-K d'hex interdit (§9.0bis).
   🔴 **Le périmètre décrit en §9.4 pt 5 était FAUX et a été corrigé le 2026-08-10 (lecture de
   `12 Fights pahse.pdf`) : le MODE de consolidation n'est pas un choix de joueur** (12.08 l'impose
   par la situation) ; les décisions réelles sont consolider ou non, quelles unités ennemies
   sélectionner, et la destination. S'y ajoute un **écart aux règles**, pas seulement au PvP : le
   gym ne sait pas consolider vers un objectif. → [`1_Agent/V11_phaseA.md`](1_Agent/V11_phaseA.md) §9.4 pt 5
3. **P3-6 — Move-after-shooting + reactive move** (= L5) → [`1_Agent/V11_phaseA.md`](1_Agent/V11_phaseA.md) §9.4 pt 6
4. **P3-8 — Optionnels à statuer** (= L7→L11) — le choix d'arme en mêlée (§0.69) est déjà acté
   en ordre 3 ; le reste (split-fire, multi-cibles charge, placement final, stratégies de
   déploiement) exige de **mesurer le regret** avant de trancher (§9.0bis).
   🟢 **Décision 2026-08-10 (3) — la circularité est tranchée : le regret se mesure sur la BASE DE
   DÉVELOPPEMENT en cours** (§0.70), pas après la mesure de référence. Le regret est un écart
   *relatif* (choix branché vs heuristique auto) : il supporte l'imprécision d'un run de 10 000
   épisodes, et l'alternative — statuer après la mesure — rachèterait un `x1_long` complet (~20 h)
   au premier optionnel retenu. → [`1_Agent/V11_phaseA.md`](1_Agent/V11_phaseA.md) §9.4 pt 8
5. **P4 — Observation de support** (= L12, ne se livre pas seule) → [`1_Agent/V11_phaseA.md`](1_Agent/V11_phaseA.md) §9.5
   ⚠️ **Ordre à ne pas prendre au pied de la lettre** : les features de §9.5 (LoS/couvert par slot
   ennemi, portée effective, flags advanced/fell_back) sont ce qui rend P3-4 et P3-6 apprenables.
   Livrées APRÈS, elles font échouer le critère P5 de ces tranches pour une raison connue d'avance.
   Chaque feature part **avec** la tranche qui en dépend ; ce point 5 ne garde que le reliquat.
6. **P5 — Validation par tranche** (protocole jamais appliqué depuis sa rédaction).
   🔴 **AUCUN PROFIL EXISTANT NE CONVIENT — à trancher avant d'ouvrir P3-4.**
   - Ce qui est **acquis** : le « ne PAS utiliser `x1_debug`, il porte 48 envs » de §9.6 est
     périmé. `n_steps` est un TOTAL divisé par `n_envs` en un point de passage unique depuis
     §0.33 ⇒ le buffer ne dépend plus de `n_envs`, et les **9** profils sont à 48 envs de toute
     façon, `x5_debug` compris. La mémoire n'écarte plus aucun profil.
   - Ce qui **casse** — et **DEUX variables distinctes** sont en cause, que ce fichier a confondues
     dans une première correction du 2026-08-10 :
     | | `total_episodes` (durée d'ENTRAÎNEMENT) | `bot_eval_final` (parties par bot de la MESURE) |
     |---|---|---|
     | `x1_debug` | **96** (a valu 480, puis 10, puis 1000, avant de revenir à 96 le 2026-08-11) | **0** |
     | `x5_debug` | **96** | **1** |
     | `x1` | 10 000 | **10** |
     | `x1_long` | 50 000 (valait 200 000 avant le 2026-08-11) | 600 |
     `total_episodes` est un total **GLOBAL** tous environnements confondus : c'est
     `def EpisodeTerminationCallback` (`ai/training_callbacks.py`) qui porte le budget de run, et
     son `episode_count += episodes_finished` somme les fins d'épisode de TOUS les env d'un pas.
     ⚠️ Ne pas confondre avec `def _EpisodeRampCallback`, du même fichier, qui compte pareil mais
     ne pilote que les rampes — c'est la classe que ce fichier a d'abord citée, à tort.
     Ces trois valeurs sont désormais confrontées à la config par `scripts/check_doc_references.py`
     (§5) : elles ont été fausses trois fois en vingt-quatre heures avant qu'il existe.
   - **`x1_debug` ne produit AUCUN win-rate** : `bot_eval_final = 0`, il n'y a pas d'évaluation
     finale. Ce n'est pas « trop court », c'est structurellement incapable de rendre le chiffre que
     §9.6 exige. `x5_debug` en rend un sur **1 partie par bot** (6 parties, granularité 1/6).
   - **Les deux variables doivent tenir ensemble** : assez d'épisodes d'entraînement pour que
     l'effet de la tranche apparaisse, ET assez de parties d'évaluation pour qu'un écart sorte du
     bruit. Avec 6 bots, l'erreur-type de l'écart entre deux win-rates `combined` vaut
     ≈ `0,707/√(6 × bot_eval_final)` : **2,9 points** à `bot_eval_final = 100`, 4,1 à 50, 2,0 à 200.
   - **À faire** : un profil de validation dédié dans `ArmageddonAgent_training_config.json`. Plus
     rien ne l'interdit depuis la fin du run (§0). Le dimensionnement est un arbitrage de **budget
     machine par tranche** — le run `x1` de référence a pris **4 h 01** (11 h 17 → 15 h 18) pour
     10 000 épisodes.
     → [`1_Agent/V11_phaseA.md`](1_Agent/V11_phaseA.md) §9.6
7. **Mesure de référence** `x1_long` — solde §0.14, §0.67, critère T6 (via §10.6) d'un coup.
   À ce régime mesuré (4 h 01 pour 10 000 épisodes), les **50 000** épisodes du profil valent
   ≈ **20 h** : c'est exactement le budget que le point 4 lui prête. Le profil valait 200 000
   jusqu'au 2026-08-11 — l'estimation « ~20 h » était donc fausse d'un facteur 4 tant qu'elle
   accompagnait l'ancienne valeur.
8. **§0.59 — Phase 2 self-play** (`--append x1_selfplay`) — livré, JAMAIS exécuté ; le premier
   run est aussi son premier test d'intégration. → [`1_Agent/V11_agent_rework.md`](1_Agent/V11_agent_rework.md) §0.59
9. **Refonte du panel de bots** (ouvert le 2026-08-11) — six styles, échelle de difficulté.
   → [`A_faire/bots_refonte_panel.md`](A_faire/bots_refonte_panel.md)
   🟠 **État au 2026-08-12** : six styles livrés, modèle de dégâts corrigé à la racine
   (par figurine), et les bots **s'étalent** au lieu d'empiler trois escouades par zone — le pire
   bot passe de 0,837 (ancien panel) à **0,62** et l'écart de VP est divisé par deux (§12.5).
   🔴 **L'ORTHOGONALITÉ est ABANDONNÉE comme critère** (décision du 2026-08-12) : les six bots se
   déplacent en bloc d'un modèle à l'autre, ils forment une seule dimension. La cause est le
   format — seuls les objectifs marquent, zéro victoire par élimination sur 600 parties — donc
   aucun panel n'y rendra six axes. Le panel est une **échelle de difficulté**, et c'est assumé.
   **Restent** : le réglage de `w_contest`/`w_crowd` (posés, non réglés), l'étape 7
   (correspondance puis suppression des cinq anciens) et l'étape 8 rejouée après réglage.
   ⚠️ Les chiffres des §8/§9 du doc de chantier sont **à rejouer** : échantillons insuffisants et
   une erreur d'arithmétique sur le `combined` (§11.1).
   ⚠️ **Ce point CONDITIONNE la valeur du point 7, il ne s'y ajoute pas.** Le panel actuel ne rend
   que **deux signaux distincts pour six bots** (mesuré le 2026-08-11, 100 parties/bot, x1,
   holdout, modèle `robust_0.9438` : `tactical`/`adaptive`/`value_trade` ont des intervalles de
   confiance entièrement recouvrants, `greedy` 0,98 et `defensive` 0,96 sont indiscernables ; seul
   `control` 0,73 porte de l'information). Une mesure de référence rendue contre ce panel mesure
   donc moins que ce qu'elle prétend.
   Cause **mesurée**, pas supposée : tous les critères de décision des bots reposaient sur
   `max(NB × DMG)` d'une seule arme — ni toucher, ni Force/Endurance, ni AP/sauvegarde, ni nombre
   de figurines. Sur les rosters holdout 500 pts, **17 profils sur 23** sont classés « mêlée » par
   ce proxy, Intercessor compris : c'est le test qui décide de charger, donc les bots envoyaient
   leurs unités de tir au contact.
   L'ordre interne du chantier et les décisions actées sont dans son doc ; le réglage et la
   correspondance ancien/nouveau se mesurent en **bot-contre-bot** (`scripts/bot_ranking.py`),
   la mesure contre l'agent ne servant qu'à confirmer — mesurer un bot par le win-rate de l'agent
   est circulaire.

## 2. Capacités — seul chantier restant de la série « chantiers capacités »

- **06 — Capacités Armageddon** : 0/6 passes, tous prérequis (01→05) livrés et vérifiés.
  Passes 1-2 d'abord (12 capacités sans nouvelle structure d'état) ; FNP déjà câblé côté moteur.
  ⚠️ Risque concret : `UNIT_ABILITY_SLOTS = 8` ([`engine/observation_entities.py`](file:///home/greg/40k/engine/observation_entities.py))
  est une projection — si une entité dépasse 8 capacités en vigueur, le moteur lève.
  (La constante a changé deux fois de numéro de ligne en vingt-quatre heures : 274 → 279 → 287.
  C'est l'exemple qui a fait poser la convention « le symbole, jamais la ligne » de §5.)
  → [`A_faire/06_armageddon_abilities.md`](A_faire/06_armageddon_abilities.md)
- Les chantiers **01→05 sont livrés** (vérifié code, 2026-08-10) et rangés en `Implémenté/` :
  [01 embedding](Implémenté/01_ability_embedding.md) · [02 CP/battle-shock](Implémenté/02_command_points.md) ·
  [03 capacités de faction](Implémenté/03_faction_abilities.md) · [04 réserves](Implémenté/04_strategic_reserves.md) ·
  [05 purge placeholders](Implémenté/05_purge_placeholders.md). Leur section CONCEPTION reste la
  référence vivante ; leur EXÉCUTION n'a plus que valeur d'historique.
- ✅ **Volet « Observation » du chantier 04 — FERMÉ le 2026-08-11.** `deep_strike` entre au
  vocabulaire des effets observables (`UNIT_RULE_EFFECT_IDS`, `obs_id` 16). C'est la seule
  capacité qui ne change ni un jet ni un mouvement mais l'**aire de mise en place** d'un ingress
  (20.04 / 24.09) : sans elle, deux escouades en réserves étaient indiscernables pour l'agent
  alors que l'une doit arriver dans la bande de bord et l'autre peut se poser n'importe où à plus
  de 8", zone adverse comprise. Le moteur savait déjà le faire (`unit_has_deep_strike` bascule le
  pool) ; l'agent le subissait sans le percevoir. **Aucun retrain forcé** : `obs_size` est
  inchangé (16659 avant comme après) et les tables d'embedding sont pré-dimensionnées à
  `OBS_ID_VOCAB_SIZE`, donc une capacité de plus coûte zéro paramètre.
  ⚠️ Ce chantier a été livré **sans passer par ce fichier** ; sa ligne est ajoutée après coup, le
  2026-08-11. Il n'a pas de doc de conception : la référence est le test
  `tests/unit/engine/test_squad_obs_unit_rules.py`.

## 3. Suspendus à un jalon explicite — ne pas commencer avant

- 🔵 **P3-0 — Retrait pour cohérence 03.03 : le choix passe au joueur ET à l'agent** — déclencheur :
  **le prochain dégel de `TOTAL_ACTION_SIZE`**, groupé avec les tranches de §1 qui en demanderont un
  (P3-4, P3-5, P3-6 branchent elles aussi des décisions).
  → [`A_faire/coherency_removal_choix_agent.md`](A_faire/coherency_removal_choix_agent.md)
  L'étape End of Turn retire les figurines hors cohérence en choisissant **à la place du joueur**
  (la plus éloignée du centroïde), et c'est vrai des DEUX côtés — le PvP ne l'offre pas davantage
  que le gym. La règle 03.03 donne ce choix au contrôleur de l'unité.
  DÉCISIONS UTILISATEUR du 2026-08-12, toutes deux tranchées et à ne pas rouvrir : (1) le choix est
  branché **pour les deux** ; (2) via une tranche d'ids d'action **DÉDIÉE** (1139 → 1159) et non
  taillée dans la plage des cellules de move — arbitrage pris sur la qualité d'apprentissage, pas
  sur le coût (le raisonnement complet est dans le doc de chantier §3.1).
  ⚠️ Le jalon EST le coût : ce dégel se paie en run `--new` complet. Le payer une fois par tranche
  coûterait quatre runs là où un seul suffit. C'est la raison — et la seule — pour laquelle ce
  chantier n'est pas en §1 alors qu'il corrige un écart aux règles.
- **T7 — Unification validation de déploiement** — déclencheur : « le training tourne ».
  🔴 Le fix décrit est FAUX en l'état (mesuré 2026-07-20) ; c'est une décision de design
  (plan contraint par l'ancre), pas un bug. → [`1_Agent/V11_tranches.md`](1_Agent/V11_tranches.md) §5 T7
- **Phase B — Observation des niveaux** (= L13) — après Phase A' validée ET vérification du
  chantier LoS 3D (`combat_utils`/WASM, câblage incomplet). → [`1_Agent/V11_tranches.md`](1_Agent/V11_tranches.md)
- **É9 — Second siège + second scénario** — après entraînement bot satisfaisant ; second
  scénario écrit par l'utilisateur (décision 2026-08-02). → [`1_Agent/V11_agent_rework.md`](1_Agent/V11_agent_rework.md) §0.47
- **§10.6 volet 2 — Validation qualitative par un joueur externe** — requis pour la démo, au
  même titre que le quantitatif. → [`1_Agent/V11_eval_strategy.md`](1_Agent/V11_eval_strategy.md) §10.6
- **§10.7 — MCTS à l'inférence** — plan B anti-coups-absurdes, « à ne PAS anticiper » avant la
  mesure ; risque = latence en démo. → [`1_Agent/V11_eval_strategy.md`](1_Agent/V11_eval_strategy.md) §10.7
- **Dette d'ancre G1/G2/G4** — recensement en fiabilité dégradée ; interdiction d'ouvrir un
  chantier depuis une ligne non ✅. → [`1_Agent/V11_tranches.md`](1_Agent/V11_tranches.md) §1bis

## 4. Backlog hors chemin critique (`A_faire/`)

Prêts à démarrer sans décision produit :
- ✅ **Une primitive commune « poser un plan par figurine »** — **LIVRÉ les 2026-08-11 / 08-12**.
  `resolve_model_effective_level` (résout) et `place_model_at_effective_level` (résout puis écrit)
  dans `shared_utils`. Les six sites annoncés migrés, plus **douze** trouvés au grep : deux jumeaux
  dans `movement_handlers`, le squad move rigide, dix résolveurs de `fight_handlers` /
  `charge_handlers`, et surtout `commit_move` — qui ne résolvait pas du tout, laissant charge,
  pile-in, consolidation et gym écrire le niveau brut. `update_model_position` porte désormais un
  **garde dur** : écrire un étage sous une figurine qui n'y tient pas lève à la ligne fautive au
  lieu de produire le 500 du 2026-08-11.
  Deux défauts trouvés APRÈS la première livraison, et c'est le plus instructif du chantier : le
  garde a révélé que les six tests de charge 3D posaient leur cible sur une case de BORD de
  plancher (ils mesuraient un état qu'aucun chemin de jeu ne produit) ; et le garde lui-même
  levait APRÈS avoir écrit `col`/`row`, laissant l'état corrompu qu'il devait empêcher — trouvé
  par `/code-review`, que le test ne voyait pas parce qu'il vérifiait le `raises` sans regarder
  l'état après.
  → [`Implémenté/primitive_poser_plan_par_figurine_2026-08-11.md`](Implémenté/primitive_poser_plan_par_figurine_2026-08-11.md)
- ✅ **L'empreinte d'une figurine se mesure à SON socle (pile-in / consolidation)** — ouvert et
  **LIVRÉ le 2026-08-12**, sorti de l'arbitrage du chantier ci-dessus. Les six fonctions
  par-figurine du combat empreintaient au socle de l'ESCOUADE : un personnage attaché y était
  sous-empreinté, donc le pool lui offrait des cases que le commit refuse. 21 sites migrés vers
  `_fight_model_fp_pair`. `charge_handlers` n'est PAS touché — ses 21 sites équivalents servent le
  pool d'ANCRES du bloc, où aucune figurine ne circule (lus un par un, pas extrapolés).
  Mesuré : 67 figurines sur 684 portent un socle différent de leur escouade, les 67 étaient
  sous-empreintées (19 hex annoncés contre 43 réels). **Effet réel sur le pool : 3 cases sur 330**
  — le facteur ×2,3 sur l'empreinte ne se traduit pas en ×2,3 sur les destinations, seules les
  cases proches d'un obstacle discriminent. Aucun test du dépôt ne couvrait ce cas ; six verrous
  ajoutés, un par fonction.
  ⚠️ Comme « socle vs mur », ce chantier déplace l'espace de décision du pile-in : effet sur les
  modèles entraînés non mesuré.
  ⚠️ **Il corrige les DESTINATIONS, pas les VERDICTS d'engagement** — mesuré après coup : les
  empreintes par-figurine sont transmises à une entrée d'engagement bâtie sur la ligne d'escouade,
  qui ne les lit jamais (0 divergence de verdict sur 13 distances, empreinte 19 contre 43 hexes).
  Le reste est ouvert ci-dessous.
  → [`Implémenté/empreinte_par_figurine_fight_2026-08-12.md`](Implémenté/empreinte_par_figurine_fight_2026-08-12.md)
- **L'engagement d'une figurine se mesure à SON socle** (ouvert le 2026-08-12, sorti de la
  `/code-review` du chantier ci-dessus). `kept_engagements`, `unit_engaged`, `engaged` et le voile
  vert du pile-in / de la consolidation mesurent un personnage attaché au socle du BLOC : l'entrée
  synthétique d'engagement est copiée de la ligne `units_cache` d'escouade, et l'empreinte
  par-figurine qu'on lui passe est ignorée. Confirmé par mesure, pas par lecture.
  Forme visée : `shared_utils._synth_model_entry`, déjà documentée comme la source unique de
  l'engagement par-figurine et déjà importée par `fight_handlers`, où elle ne sert qu'à UN site.
  **11 sites** de `fight_handlers` à router, **2** au niveau unité à examiner
  (`_fight_synth_cache_entry_at_footprint`), et le jumeau probable dans `charge_handlers`.
  ⚠️ Touche la sémantique de l'engagement (12.03 / 12.08), pas une géométrie de pool : plus
  risqué que le chantier d'empreinte, et il déplacera lui aussi l'espace de décision.
- **Réécrire la note `bot_eval_freq_normal` de `x1_long` avec le coût MESURÉ** (~10 min, décidé
  le 2026-08-11). Cette note fonde le réglage sur « 13 min l'unité », chiffre hérité du commit
  `42326ed0` et jamais re-mesuré ; l'évaluation finale du run du 2026-08-11 donne plutôt
  ~2 min 55 pour 600 épisodes. Un facteur ~4,5 sépare les deux, et c'est le plus élevé qui a
  écarté l'option `bot_eval_freq` 5000. Les courbes `perf/d_bot_eval_seconds` et
  `perf/e_bot_eval_episodes_per_second` existent depuis le même jour pour trancher : lire le
  débit du prochain run **nominal** (pas sous `--step` ni `W40K_PERF_TIMING`, qui ralentissent),
  puis réécrire la note avec ce chiffre. Un réglage tenu par un chiffre faux se retourne au
  premier changement de durée — c'est déjà ce qui était arrivé à `bot_eval_freq` calé sur
  200 000 épisodes.
- **Compteurs `abilities/`** (~1 j) — un compteur par règle d'unité RÉELLEMENT appliquée, par
  joueur, **plus une courbe d'exposition** : sans elle, un zéro ne distingue pas « jamais
  déclenchée » de « jamais dans le roster ». Deux familles, les deux obligatoires : celles qui
  produisent une ligne d'`action_log` (`reactive_move`, `charge_impact`, `charge_after_advance` /
  `charge_after_flee`, `move_after_shooting`) et celles qui ne modifient qu'un jet (rerolls, bonus
  Oath — elles vivent sur les `shot_records`, pas dans `action_logs`).
  → [`Implémenté/metriques_reserves_et_charge_2026-08-11.md`](Implémenté/metriques_reserves_et_charge_2026-08-11.md) §Ce qui reste
- ✅ **La portée d'un tir se juge AVANT les pertes** — **LIVRÉ le 2026-08-12**. L'analyzer mesurait
  la distance vers `[TARGET_MODELS:]`, segment que `step_logger` réserve explicitement au replay
  parce qu'il liste les survivants POST-pertes : la figurine visée, la plus proche, en disparaît
  quand elle meurt du tir, et le survivant suivant faisait déclarer le tir hors portée. Mesuré sur
  600 épisodes / 27 991 tirs : **31 verdicts, 0 réel**. Même journal avant/après : 67 → 32 erreurs,
  et rien d'autre ne bouge. Le contrôle n'est pas devenu aveugle — il rend encore 18 702 verdicts.
  **Deux gardes posés dans la foulée, parce que le défaut était reproductible** : (1) une liste
  blanche opposable interdit désormais de lire `[TARGET_MODELS:]` pour un verdict — c'était la
  DEUXIÈME fois qu'il faussait une distance, après la mêlée le 2026-07-24 ; (2) la section 1.2 du
  rapport n'agrège plus `out_of_range` et `engaged_non_close_quarters` sous un seul chiffre, ce
  qui m'a fait chercher un écart de 11 inexistant.
  → [`Implémenté/analyzer_portee_source_correcte_2026-08-12.md`](Implémenté/analyzer_portee_source_correcte_2026-08-12.md)
- ✅ **« Attaque non allouée, cible vivante » : contrôle RETIRÉ** — **LIVRÉ le 2026-08-12**. Le
  moteur ne laisse une blessure sans allocataire que sur une escouade cible anéantie (un seul
  chemin, `_mark_manual_overkill_wasted`) : le contrôle ne pouvait donc signaler que les dérives de
  l'état reconstruit par l'analyzer. Mesuré : 2 signalements sur le run de 12 h 23 (une seule
  activation, avec 1 mort fantôme en §2.8), 15 sur celui de 14 h 14 (3 activations), et **0 cible
  vivante** sur les 1747 lignes `NOT ALLOCATED` arbitrées par les instantanés `T{n} STATE:` du
  moteur. L'invariant 05 est désormais tenu par `tests/unit/engine/test_attack_allocation_contract.py`.
  → [`Implémenté/analyzer_retrait_controle_non_allouee_2026-08-12.md`](Implémenté/analyzer_retrait_controle_non_allouee_2026-08-12.md)
- ✅ **L'engagement d'un tir se juge AVANT les pertes** — **LIVRÉ le 2026-08-12**. Même famille que
  la ligne ci-dessus, autre canal : ce n'est plus `[TARGET_MODELS:]` qui fausse la mesure mais
  l'état reconstruit lui-même. `analyzer_core` applique les dégâts d'une ligne AVANT de l'aiguiller
  vers son handler ; une cible tuée par le tir qu'on juge est déjà retirée de `unit_hp` /
  `unit_positions`, donc absente de l'énumération des ennemis — le tireur est déclaré « non engagé
  avec sa cible » alors qu'il l'était quand le moteur a décidé. Mesuré : **1 verdict, 0 réel**
  (E422, un pistolet tuant à bout portant l'unité avec laquelle il était engagé). Corrigé par un gel
  au **Select Targets step de l'activation**, jumeau exact des gels d'effectif [BLAST] 24.05 déjà en
  place — pas un instantané par ligne, qui laisserait la deuxième attaque juger sur les pertes de la
  première. **Le jumeau mêlée portait le défaut SYMÉTRIQUE** : l'alternance 12.04 devenait aveugle
  quand le coup hors tour tuait la cible (faux négatif), corrigé du même geste. Même journal
  avant/après : 18 → 17 erreurs de tir, 24 tirs close-quarters reclassés « cible engagée », rien
  d'autre ne bouge.
  **Relecture du gel, même jour, trois défauts fermés** : (1) deux mesures jumelles lisaient deux
  ancres différentes de la même cible ; (2) une cible déjà détruite se voyait rendre son ancre sans
  ses PV, inventant une erreur de parsing par ligne ; (3) le contrôle de PORTÉE, jumeau resté sur la
  carte vive, ne rendait **aucun** verdict dès qu'un tir tuait — mesuré : **18 702 verdicts sur
  29 664 lignes, soit 37 % jugés par personne**, et les 10 962 regagnés n'en condamnent aucun. Le
  « 18 702 » que la livraison du matin citait comme preuve de non-aveuglement était déjà la mesure
  du trou.
  → [`Implémenté/analyzer_engagement_avant_pertes_2026-08-12.md`](Implémenté/analyzer_engagement_avant_pertes_2026-08-12.md)
- 🔴 **Conformité moteur — les 53 erreurs que l'analyzer voit VRAIMENT** (ouvert le 2026-08-11,
  **26 restantes** : la famille CC_NB, la plus lourde, est soldée le jour même ; les familles
  « tirs hors portée » et « tir engagé visant une unité non engagée » sont soldées le 2026-08-12 —
  c'étaient des artefacts, cf. ci-dessus).
  Le rapport annonçait 370 erreurs sur le run du 2026-08-11 ; le nettoyage de l'outil de mesure
  (livré le même jour, cf. plus bas) en a supprimé 317 qui étaient des faux positifs de lecture.
  **Ce qui reste n'est plus imputable à l'analyzer** et désigne des règles appliquées de travers
  en partie réelle. Par famille, sur le journal du **2026-08-11 14 h 34** — le MÊME run rejoué
  après nettoyage (600 épisodes, 83 384 actions, jets de touche identiques au journal de 11 h 39 ;
  l'écart de taille de 274 345 octets s'explique exactement par les 12 163 `[Strategy:]` retirés
  moins les 532 `[MELTA:X]` et 7 `[PRECISION]` ajoutés). Les deux journaux se comparent donc terme
  à terme, et ces chiffres sont l'état RÉEL, pas une estimation :
  | Symptôme | P1 | P2 | Règle |
  |---|---|---|---|
  | ~~Attaques au-delà de CC_NB~~ **→ 0, LIVRÉ (voir ci-dessous)** | ~~11~~ | ~~13~~ | 04.03 |
  | Collisions (2 unités, même hex) | 7 (total) | | 03.01 |
  | Fall-back qui finit ENGAGÉ | 2 | 3 | 09.07 |
  | Move normal finissant au contact | 1 | 4 | 09.05 |
  | ~~Tirs hors portée~~ **→ 0, ARTEFACTS (voir ci-dessous)** | ~~2~~ | ~~3~~ | 10 Shooting |
  | ~~Tir engagé visant une unité NON engagée avec le tireur~~ **→ 0, ARTEFACTS (voir ci-dessus)** | ~~0~~ | ~~3~~ | 10.06 |
  | Move normal PARTI d'un engagement | 0 | 2 | 09.05 |
  | Tir sur un ennemi engagé | 0 | 1 | 10.06 |
  | Mort « fantôme » (état reconstruit ≠ moteur) | 1 (total) | | — |
  ✅ **Trois familles annoncées le matin ont DISPARU** — pile-in au-delà de 3" (1), consolidation
  au-delà de 3" (1), charge depuis un hex déjà adjacent (1) sont à **0**. C'étaient des faux
  positifs de la mesure d'ancre, éteints par la reconstruction d'empreinte du même jour. Le run
  étant le même, ce n'est pas un effet du hasard.
  ⚠️ **Deux contrôles de §1.2 se sont ALLUMÉS** au même moment (tir engagé sur unité non engagée,
  tir sur ennemi engagé) : ils ne voyaient rien tant que l'arme des personnages rattachés n'était
  pas résolue. Le total d'une section qui MONTE après une correction de l'outil est le signe normal
  d'un contrôle qui regardait dans le vide, jamais d'une régression. **Suite le 2026-08-12** : les
  deux mesuraient l'engagement APRÈS les pertes de la ligne jugée — ce qu'ils voyaient en
  s'allumant était un artefact, pas une faute du moteur (cf. la ligne ✅ ci-dessus).
  ✅ **« Attaques au-delà de CC_NB » : 24 → 0, LIVRÉ le 2026-08-11. Le moteur était JUSTE.**
  Les 24 lignes sont 19 activations, et **toutes les 19** portent l'une des deux seules armes
  `[CLEAVE:1]` du dépôt (`Two-Handed Big Choppa` NB 5, `Kustom Choppa` NB 6). Le dépassement vaut
  **exactement `effectif de la cible // 5` dans les 19 cas** — la formule de [CLEAVE] 24.06 au dé
  près (PDF 24 p.2, lu). Le cas « prouvé » E76 T4 est donc l'inverse de ce qu'il annonçait :
  NB 5 + 1 × (10 // 5) = **7 attaques, le nombre correct** (mesuré en rejouant la configuration
  dans le moteur : cible de 10-14 → 7, de 5-9 → 6, de 4 → 5).
  Le défaut était que `step.log` ne portait AUCUN token `[CLEAVE:X]` (0 occurrence sur 30 Mo)
  alors que le moteur sait quel X a joué : le plafond de l'analyzer valait `Σ(NB + Waaagh)` et
  rien d'autre. **Jumeau traité en même temps** : `[BLAST] 24.05` au tir avait le même trou (0
  token, absent du plafond) — latent, aucun roster joué ne porte d'arme BLAST, mais 4 en existent
  côté Space Marine. Les deux règles passent désormais par un seul calcul partagé.
  ⚠️ **Ce que le token dit et ne dit pas** : il porte le X DÉCLARÉ par l'arme, jamais le nombre de
  dés ajoutés. Écrire le nombre rendrait le contrôle vacant — l'analyzer vérifierait le moteur
  avec le chiffre du moteur. L'effectif de la cible est reconstruit par l'analyzer, et figé à
  l'ACTIVATION (pas à la séquence par arme) : le moteur déclare toutes ses attaques avant d'en
  résoudre une, et figer par arme laissait 11 des 24 lignes fausses (le Bigboss frappe après les
  Choppa de son escouade, qui ont déjà fait tomber la cible sous la tranche de 5).
  ⚠️ **Effet visible seulement sur un run POSTÉRIEUR** : la correction ajoute un token au journal,
  le journal du 14 h 34 ne le porte pas. Mesuré en injectant `[CLEAVE:1]` sur les 242 lignes des
  deux armes concernées de ce journal : **53 → 29 erreurs**, `Attacks over CC_NB` à 0/0.
  ⚠️ **Les autres familles ont une piste, pas une cause** : ne rien corriger avant de l'avoir
  établie — c'est l'erreur que les 317 faux positifs, puis ces 24, viennent de sanctionner deux
  fois. Sur cinq familles instruites à ce jour, **quatre étaient des défauts de mesure**.
  ⚠️ **Piste ouverte, non prouvée, pour les deux familles de move** : le pool de destinations
  exclut bien la zone d'engagement sur les deux chemins single-hex de
  [`engine/phase_handlers/movement_handlers.py`](file:///home/greg/40k/engine/phase_handlers/movement_handlers.py),
  mais le commentaire y affirme que la destination l'exclut « quels que soient les toggles » alors
  que la ligne suivante écrit `_check_ez = not _thru_ez`, et le run tourne en `move.thru_ez=True`.
  Par ailleurs un déplacement d'ESCOUADE n'est pas validé par ce pool mais par
  `movement_preview_move_plan` : les deux voies sont à départager **en rejouant le cas dans le
  moteur**, pas en relisant `step.log`.
  ✅ **La chaîne des tokens créés le 2026-08-11 est vérifiée sur ce run** : `[MELTA:X]` compte
  **532** usages (Multi-Melta, déclaré « NOT USED » le matin même) et `[PRECISION]` **7**. Les deux
  traversent bien moteur → `step.log` → analyzer en conditions réelles.
  ⚠️ **`PSYCHIC` restera « NOT USED » quoi qu'il arrive** sur ses 3 armes — dont `'eadbanger`, dont
  la même page compte pourtant 7 usages de `PRECISION`. Ce n'est pas un compteur manquant : 24.29
  est un mot-clé d'INTERACTION (avec les règles anti-psychic), il n'a aucun instant où il « joue ».
  Il n'y a rien à compter, et la ligne est condamnée à afficher une absence trompeuse — à traiter
  dans l'affichage (statut distinct de `NOT USED`), pas dans la mesure.
- ✅ **Analyzer — la mesure cesse de mentir. LIVRÉ le 2026-08-11.** Sur le run du jour :
  **370 → 53 erreurs**, et quatre contrôles jusque-là muets se sont allumés. Cinq causes, toutes
  vérifiées en remettant le défaut et en constatant le rouge :
  (1) le plafond de tirs était accumulé sans le GROUPE de figurines tireuses, qui le détermine —
  **320 faux positifs**, `fight_handler` avait fermé ce défaut, le tir ne l'avait pas suivi ;
  (2) `RAPID_FIRE` (4 080 marqueurs) et `DEVASTATING_WOUNDS` par arme n'étaient comptés nulle part,
  `CLOSE_QUARTERS` mesurait l'adjacence d'ancre quand §10.06 mesurait l'engagement (43 contre
  1 280 pour le même fait), `MELTA` et `PRECISION` n'atteignaient jamais `step.log` ;
  (3) le profil d'arme était cherché dans le seul équipement du type d'ESCOUADE — **3 138 tirs sur
  23 169 (14 %)** portaient une arme que seule une figurine déclare (règle 19), donc sans portée
  contrôlable et absente du tableau d'usage ;
  (4) à la mort d'une figurine les socles de la cible étaient purgés, alors que `[TARGET_MODELS:]`
  dit qui RESTE — toute unité entamée était réduite à son ANCRE pour la géométrie ;
  (5) `[Strategy: <label>]` annonçait un choix tactique qu'**aucun code ne calculait** (deux
  valeurs par défaut fabriquaient « 100 % aggressive » sur 12 163 advances) et `WINS BY SCENARIO`
  fusionnait deux terrains sous un même libellé.
  ⚠️ **Le total remonte quand un contrôle vacant s'allume** : rendre sa portée à une arme de
  personnage a fait apparaître 4 tirs hors portée jamais vérifiés. Une hausse n'est pas une
  régression ici — c'est la contrepartie normale d'un contrôle qui regardait dans le vide.
  Verrouillé par 4 fichiers de test créés (`tests/unit/ai/test_analyzer_attack_cap_shooter_group.py`,
  `test_analyzer_close_quarters_usage.py`, `test_analyzer_weapon_usage_carrier.py`,
  `test_analyzer_target_models_restore_footprint.py`) et un étendu
  (`test_step_log_weapon_rule_tokens.py`).
- **Security étapes 4, 5, 7, 8** (~4-5 j ; étapes **1, 2, 3 et 6 livrées**, étape 5 partielle
  = durcir la stack Docker existante, pas la créer ; suivi à jour)
  → [`Security.md`](Security.md) — le document est un chantier **vivant**, à la racine d'`Implémentation/`,
  pas dans `A_faire/` (l'ancien lien de cette ligne pointait dans le vide)
- **Tests front — reste T2b/T3a/T7 (couche A) + couches B (vitest) et C (Playwright)**
  (~10 j au total, sécable) → [`A_faire/front_test_auto.md`](A_faire/front_test_auto.md)
- ~~**Perf géométrie — cache d'engagement par paire**~~ — **LIVRÉ le 2026-08-11.** Clé contenant
  la géométrie (jamais un compteur de version, cf. §0.18), donc auto-invalidante. Gain net
  **+3,42 s à x1** et **+0,76 s à x5**, soit un ratio évité/coût de **3,9× / 3,1×**, par
  comptabilité interne à un seul run ; touches 86 % / 84 % ; mémoire bornée en OCTETS
  (32 Mo/processus, `n_envs: 48`) et non en nombre d'entrées. Les 16 boucles de candidats (pool de
  move, BFS de charge) sont exclues du cache — les y laisser retournait le gain à −0,83 s à x5.
  Verrouillé par `tests/unit/engine/test_engagement_pair_cache.py` (18 tests ; 6 mutations
  vérifiées rouges). Acquis annexe : marqueurs perf `SQUAD_OBSERVATION` / `SQUAD_ACTION_MASK` /
  `SQUAD_MOVE_CELL_MAP` (les compteurs ne voyaient que 6,5 % du temps avant eux).
  ⚠️ **Trois pièges de méthode consignés dans le doc, à lire AVANT toute reprise** : (1) comparer
  deux runs au CHRONOMÈTRE ne marche pas (mêmes réglages, 184 s puis 279 s à x5) — ça avait fait
  conclure à tort que ce cache était une perte ; (2) comparer les RATIOS et jamais les secondes,
  qui ont varié d'un facteur 3,7 entre deux modèles quand le ratio bougeait de 3 % ; (3) le cache
  de la carte de cellules de move est **sain** — ses 69 % de ratés viennent d'un plateau qui change
  réellement, correction tentée, gain nul, annulée.
  → [`Implémenté/perf_geometrie_cache.md`](Implémenté/perf_geometrie_cache.md)
- ✅ **Masque de move exact sur socles non ronds — LIVRÉ le 2026-08-11.** Ce n'était pas de la
  perf, c'était une **violation de 09.05** : le masque approximait la zone d'engagement par les
  centres de cellules, ce qui la sous-estimait d'environ une case, et un WarTrakk (socle oval
  20×14) pouvait finir un move normal ENGAGÉ pendant que le masque le disait libre (témoin E8 du
  2026-08-09). Le prédicat de la règle (`euclidean_edge_distance`, contours continus) est
  désormais appliqué tel quel : le motif d'offsets interdits par une figurine ennemie ne dépend
  que du couple de géométries et de la parité de colonne, donc il est calculé une fois par couple
  puis translaté (somme de Minkowski) au lieu d'être re-mesuré partout ; seules les égalités
  flottantes sont retranchées à leur position réelle.
  ⚠️ **Le jeu des coups légaux a changé** : tout win-rate mesuré avant le 2026-08-11 — y compris
  celui de la base de développement de §0, entraînée le 2026-08-10 sur l'ancien masque — n'est
  pas comparable à ceux d'après. À prendre en compte au moment d'appliquer le protocole P5 (§1
  pt 6), qui compare précisément des win-rates de tranche en tranche.
  Verrouillé par `tests/unit/engine/test_move_ez_non_round_bases.py` (dont le témoin E8, la
  concordance masque ↔ règle case par case sur socles ovals ET carrés, et la non-régression du
  couple rond↔rond qui était déjà exact). Livré sans passer par ce fichier et sans doc de
  conception ; ligne ajoutée après coup le 2026-08-11, la référence est le test.
- ✅ **Déploiement « auto » — positions figées supprimées — LIVRÉ le 2026-08-11.** L'alternative
  au déploiement ACTIF (l'agent place ses figurines) n'est plus le placement FIXE lu dans le
  scénario, mais un déploiement joué PAR LE MOTEUR : les deux modes jouent désormais une vraie
  phase de déploiement, seul change qui décide des poses. Ça ferme l'asymétrie que la config
  documentait comme « à corriger » — un agent entraîné en placement fixe ne se déployait jamais,
  puis était NOTÉ sur des parties où il devait se déployer, et son score mesurait un comportement
  jamais appris. Le générateur de positions figées et son test sont supprimés.
  ⚠️ Même conséquence que la ligne ci-dessus sur la comparabilité des win-rates, et pour la même
  raison : ce qui est mesuré n'est plus la même partie.
  Le résidu `deployment_random_mix` qui survivait dans `tests/unit/engine/_config_helpers.py`
  est **supprimé le 2026-08-11** : il épinglait « à l'arrêt » un mécanisme moteur
  (`_should_force_random_deployment_action`) qui n'existe plus, donc il injectait une clé que
  plus personne ne lit. 0 occurrence dans le code désormais.
  Livré sans passer par ce fichier ; ligne ajoutée après coup le 2026-08-11.
- ✅ **Résidus T1/T2/T3 de l'accélération du move pool — SOLDÉS le 2026-08-11.** Les trois tâches
  restées ouvertes depuis le 2026-07-21 sont fermées. **T1** : les copies du motif slice-OR
  passent par `hex_utils.offset_slice_windows` (bornes de slice d'un décalage de grille, calculées
  une fois), verrouillé par `test_offset_slice_windows.py` — équivalence exhaustive contre
  l'indexation naïve, verrou prouvé rouge. **T2** : `numba` n'est pas une dépendance du projet,
  acté par écrit dans `requirements.runtime.txt`. **T3** : le poste coûteux du déploiement n'était
  pas l'heuristique de scoring mais le **recalcul à l'identique** du pool d'ancres valides (mesuré
  121 appels pour 12 états distincts, 90 % de redite) — désormais mis en cache derrière un
  fingerprint de tout ce dont le pool dépend, verrouillé par `test_deployment_cache_equivalence.py`.
  → [`Implémenté/V11_move_build_acceleration.md`](Implémenté/V11_move_build_acceleration.md)
- **Perf `generate_compact_formation`** (½-1 j) — MESURER avant d'implémenter, gain non acquis
  → [`A_faire/perf_generate_compact_formation.md`](A_faire/perf_generate_compact_formation.md)
- **gzip/Brotli** (½ j) — à faire AVEC l'étape 5 de Security (même proxy)
  → [`A_faire/perf_noyau_natif_et_gzip.md`](A_faire/perf_noyau_natif_et_gzip.md) §1
- ~~**Résidu front V10 des sous-phases fight**~~ — **LIVRÉ le 2026-08-10.** Les deux cascades de
  `useEngineAPI.ts` et les 3 champs morts de son interface sont supprimés ; le pool CC vient de
  `getFightActivationPoolUnitIds` (`fight_eligible_units`), source unique partagée avec le clic
  manuel. `grep` des 5 sous-phases V10 et des 3 champs : **0 hit** front comme backend.
  ⚠️ Ce n'était PAS un nettoyage neutre — voir le changement de comportement de l'auto-play PvP
  décrit en [`Replay.md`](Replay.md) §4.B, **à confirmer en session PvP fight réelle**.
- **Champs manquants du `step.log`** (sécable, **27** entrées ordonnées par nombre de règles
  débloquées : `L1`, puis `L3`→`L28` — **`L2` a été retirée**, S/T sur les jets étant livrée).
  Ce n'est pas un chantier d'un bloc : chaque champ se livre seul et fait passer des règles de
  « non vérifiable » à « vérifiable » par l'analyzer. À piocher quand un contrôle analyzer manque
  de données. *(Cette ligne a annoncé « 15 entrées, L1…L15 » jusqu'au 2026-08-10 : le tableau
  avait été lu jusqu'à `L15` seulement, sans en chercher la fin. Recompter, ne pas extrapoler.)*
  → [`analyzer_couverture.md`](analyzer_couverture.md) §7
- **Corpus de règles vérifiable** (sécable, plusieurs sessions) — sortir les 214 règles du tableau
  Markdown et en faire une DONNÉE, sur le modèle de `weapon_rules.json` / `unit_rules.json` : une
  entrée par règle portant son applicabilité (portée par une datasheet du roster ? par une arme ?
  par une phase jouée ?), le ou les contrôles qui la mesurent, et son état de vérifiabilité.
  L'analyzer rend alors une section de couverture — applicable, utilisée n fois, n erreurs,
  vérifiable ou non — avec **trois interdits par construction** : une règle applicable et JAMAIS
  utilisée sort en ⚠️ (c'est le cas 17.01 du 2026-08-10 : le rapport affichait `✅ 1.1 : 0`
  pendant que le moteur violait la règle à chaque déplacement de véhicule non volant, faute de
  produire la moindre ligne fautive) ; une règle non vérifiable n'entre dans aucun ✅ ; une règle
  hors roster ne pèse sur rien. §1.7 et §1.8 font DÉJÀ exactement ça pour les 58 règles d'unité et
  d'armes — ce chantier généralise leur mécanisme aux 156 lignes des PDF.
  **Ordre de découpe décidé le 2026-08-10 : les entrées PROUVABLES d'abord** — les 69 contrôles
  vivants, plus les règles dont l'applicabilité se dérive du journal sans être écrite à la main
  (03.01 dès qu'il y a eu un déplacement, 12.02 dès qu'il y a eu une phase de combat…). Les
  règles conditionnelles (transports, aéronefs, stratagèmes, réserves), dont l'applicabilité
  dépend d'options de partie qu'aucun champ ne porte, sortent en « non vérifiable » assumé plutôt
  qu'en prédicat inventé — c'est ce qui a produit les trois lignes fausses de la matrice.
  → [`analyzer_couverture.md`](analyzer_couverture.md) §3, §4, §5-bis

Bloqués par une décision utilisateur :
- **Replis `unit_by_id`** — T0 (signature de `require_unit_by_id`) appartient à l'utilisateur ;
  ~4-5 sessions ensuite. ⚠️ Chiffres du doc périmés 3× : **5** implémentations du lookup
  désormais, pas 4. → [`A_faire/replis_unit_by_id_2026-08-05.md`](A_faire/replis_unit_by_id_2026-08-05.md)
- **Endless Duty** (8-13 j) — décisions produit sur les obstacles 3 (format objectifs) et
  7 (double sens de `VALUE`). → [`A_faire/Endless_duty_etat_mesure.md`](A_faire/Endless_duty_etat_mesure.md)

Lourds, à re-cadrer avant toute reprise :
- **Preview de tir sans deepcopy** (4-8 j) — meilleure spec du lot, mais touche
  `compute_unit_los` = source unique (obs RL, reward, déploiement).
  → [`A_faire/preview_tir_position_virtuelle.md`](A_faire/preview_tir_position_virtuelle.md)
- **Pile-in / Overrun 12.06 par-figurine** (3-5 j après prérequis « le gym emprunte la machine
  V11 ») — **prérequis de P3-5** (§1), donc pas vraiment optionnel.
  → [`A_faire/pile_in_overrun_par_figurine.md`](A_faire/pile_in_overrun_par_figurine.md)
- **Migration PostgreSQL** (plusieurs semaines) — spec de mars 2026 visant des modules `ai/`
  réécrits par V11 depuis : re-confronter au code avant. → [`A_faire/Database/DB_migration.md`](A_faire/Database/DB_migration.md)
- **MCTS adversaire d'entraînement** (plusieurs semaines ; P0+P1 ≈ 1-2 sem.) — après stabilité
  obs/masques. → [`A_faire/MCTS/MCTS_bot_final.md`](A_faire/MCTS/MCTS_bot_final.md)

## 5. Hygiène documentaire

> **Le compte rendu du chantier du 2026-08-10 est sorti d'ici** (dissolution de `2_Various/`,
> réparation des 497 liens, recadrage de `1_Agent/`, fusions et suppressions) →
> [`Implémenté/hygiene_doc_2026-08-10.md`](Implémenté/hygiene_doc_2026-08-10.md). Il occupait
> 90 lignes sur 249 d'un fichier qui se déclare source unique de l'ordre du travail, sans jamais
> dire par quoi commencer. Extrait le 2026-08-10, en application de la règle de discipline en tête
> de ce fichier — un chantier livré passe son doc en `Implémenté/`.
>
> Ne reste ici que ce qui **sert à la prochaine passe** : le contrôle des liens, et les
> incohérences non soldées.

### Le contrôle est outillé — ne plus le refaire à la main

    python3 scripts/check_doc_references.py

Sans argument, il passe `analyzer_couverture.md`, **ce fichier** et `Security.md`. Il rend 0 s'il ne trouve rien,
1 sinon, et se lance sur n'importe quel `.md` passé en argument. Quatre passes : les fichiers cités
existent et portent les symboles cités ; les cibles de liens existent ; les **nombres recopiés**
d'une source mécanique valent encore ce qu'ils annoncent ; aucun renvoi ne porte un numéro de
ligne (`<fichier>.py:<ligne>`). Verrouillé par `tests/unit/scripts/test_check_doc_references.py`.
Il ne distingue pas une citation d'une mention : écrire la forme interdite en exemple la déclenche,
d'où la notation entre chevrons ci-dessus.

**Ce qu'il ne sait pas faire, et qui est affiché plutôt que tu, à chaque exécution** : un renvoi
sans symbole à confronter n'est pas vérifié (il est compté) ; le nombre de « contrôles analyzer
vivants » n'a aucune énumération dans le code, donc il est déclaré non vérifiable au lieu d'être
approché par un proxy ; et **rien ne peut prouver qu'un chantier livré a pris sa ligne ici** — un
chantier peut n'avoir aucun document, et un nom de branche ne se retrouve pas dans un texte
français. Le script se borne à rappeler combien de livraisons ont été mergées depuis la dernière
écriture du document, sans verdict.

### Une porte refuse la fusion quand les chantiers s'accumulent sans ligne

`scripts/check_roadmap_declared.py`, branché sur le hook `prepare-commit-msg` de `.githooks/`
(`core.hooksPath` pointe dessus, les hooks sont donc versionnés). Le hook ne s'exécute que lorsque
`MERGE_HEAD` est présent — ce qui garantit que le contrôle rate toujours les contextes hors merge.
Une fusion **dans `main`** est
refusée quand **deux** chantiers ont déjà été livrés sans que ce fichier bouge (plafond porté de 3
à 2 le 2026-08-12, voir ci-dessous). Le refus les nomme.

**Le plafond est une mesure, pas un réglage.** Le refus sec a été essayé puis abandonné sur
chiffres : « la branche doit toucher la feuille de route » refuse **22 des 25** derniers merges,
« la feuille doit avoir bougé depuis le merge précédent » en refuse **20 sur 25** — parce que le
flux réel écrit la ligne dans un commit de suivi, après la fusion. Une porte rouge en permanence se
contourne au premier usage : on aurait troqué un manque visible contre un contrôle mort.

🔴 **Ce qu'elle vaut vraiment, et il faut le savoir avant de s'y fier.** Les chiffres du calibrage,
avec leur méthode et leur date, vivent en tête de `scripts/check_roadmap_declared.py` et **nulle
part ailleurs** — ils étaient recopiés ici et dans le fichier de test, les jeux se sont contredits,
et un chiffre recopié ne vieillit pas avec sa source (constaté le 2026-08-12). Ce qu'il faut en
retenir : re-mesurée le 2026-08-12 sur toutes les fusions du tronc depuis le 2026-08-10, **au
plafond 3 la porte ne se déclenchait pas une seule fois** sur le flux moderne — ses refus étaient
tous concentrés sur l'arriéré du 2026-08-10, soldé depuis. D'où la **DÉCISION UTILISATEUR du
2026-08-12 : plafond porté à 2**, le seul réglage que la mesure distingue — il refuse exactement
les 2 oublis avérés sur 41 fusions, quand 1 en refuserait 6 et se ferait donc contourner. La limite
de fond ne change pas pour autant : la dette retombe à zéro dès que
ce fichier est **touché**, pour n'importe quel motif — une valeur corrigée, une reformulation, une
typo. Comme il est retouché souvent, la porte mesure une SÉCHERESSE d'écriture, pas la déclaration
d'un chantier précis. Elle attrape l'oubli prolongé ; elle ne remplace pas la discipline, et il ne
faut pas lui faire dire qu'un chantier a sa ligne.

Ce qu'elle NE fait pas non plus : juger si la ligne écrite est juste, ni voir un chantier livré par
un commit direct sur `main`. Contournement assumé quand la fusion n'est pas un chantier :
`ROADMAP_GATE=off git merge …` **avant** de lancer la fusion, `ROADMAP_GATE=off git commit` une
fois qu'elle est commencée — c'est le moment qui décide, et mi-fusion git refuse tout nouveau
`merge`. **Pas** `--no-verify`, qui ne saute pas `prepare-commit-msg`. Pour se débloquer APRÈS un
refus sans rien désarmer : écrire la ligne, `git add -A`, `git commit` — l'index vaut déclaration.
État courant sans rien bloquer : `--status`.

✅ **La porte ne meurt plus sur une trace Python** (2026-08-11). Deux états REPRODUITS la tuaient en
`CalledProcessError` de dix lignes : `--merge` lancé hors fusion, et — atteignable par le hook réel —
une vraie fusion faite sur un **HEAD détaché**, où `symbolic-ref` sort 128 alors que `MERGE_HEAD`
est bien là. git affichait alors « Not committing merge » sans qu'une ligne dise quoi faire, et
relancer `git commit` faisait passer la fusion : une porte cassée, pas un refus motivé. Désormais
toute sortie est un feu vert ou un refus lisible, filet de sécurité compris (`0` passe, `1` refuse,
`2` = la porte n'a PAS PU se prononcer et bloque quand même). Les deux états sont tranchés
séparément : HEAD détaché = **feu vert** (fusionner hors `main` ne livre rien, la porte est sans
objet) ; `MERGE_HEAD` absent en `--merge` = **refus**, parce que c'est exactement l'état d'un hook
mal branché — `pre-merge-commit` tourne avant l'écriture de `MERGE_HEAD`, et un « sans objet »
complaisant y rendrait la porte muette pour toujours (CLAUDE.md T1). Les trois verrous
(`tests/unit/scripts/test_check_roadmap_declared.py`) ont été vérifiés ROUGES défaut remis.

✅ **« git ne répond pas » ne se déguise plus en « HEAD détaché »** (2026-08-12, relevé par
`/code-review` sur la livraison ci-dessus). Le feu vert du cas détaché reposait sur l'échec de
`symbolic-ref`, qui échoue AUSSI quand le dépôt est illisible : script copié hors dépôt git,
`--merge` sortait « fusion hors `main`, sans objet » et **0**, quand `--status` refusait sur le même
répertoire. Une sonde (`rev-parse --is-inside-work-tree`, en `check=True`) a d'abord tranché avant
tout appel tolérant ; depuis le `/simplify` du 2026-08-12 la distinction est portée par git seul
(`branch --show-current` : `main` attaché, vide si détaché, rc 128 hors dépôt → filet), donc sans
sonde ni helper tolérant ni contrainte d'ordre. Dans les deux cas la panne part au filet → code 2.
Le verrou du cas détaché portait le même
trou : il n'affirmait que « code 0 + sans objet », soit la sortie de n'importe quelle panne — il
compare maintenant à la MÊME fusion faite sur `main`, où la porte doit se prononcer. Les deux
verrous vérifiés ROUGES défaut remis.

✅ **Un refus dit la cause, et une fusion sans ancêtre commun garde son verdict** (2026-08-12,
2ᵉ passe `/code-review`). Deux trous mesurés : (1) le filet imprimait `exit status 128` sans le
stderr de git, donc sans jamais nommer la panne (`fatal: not a git repository`) — il le porte
désormais, et le verrou le compare à ce que git dit LUI-MÊME dans le répertoire, sans figer de
formulation ni de langue ; (2) « la branche déclare-t-elle ? » se lisait en diff **trois points**,
qui exige une base commune : un `git merge --allow-unrelated-histories` sur `main` sortait 128
« no merge base » et devenait un « contrôle impossible » opaque, alors même que la branche écrivait
sa ligne. La question se lit maintenant en `log <main>..<branche> --name-only`, qui ne calcule
aucune base — vérifié IDENTIQUE au diff trois points sur les **12** dernières fusions réelles du
dépôt (déclarations et non-déclarations mélangées). Verrous vérifiés ROUGES défaut remis.

✅ **Pieuvre lue en entier, deux verts vacants fermés, calibrage re-mesuré** (2026-08-12, 3ᵉ passe
`/code-review`). (1) `rev-parse MERGE_HEAD` ne rend que la PREMIÈRE tête : sur `git merge A B`, une
livraison déclarée par `B` était refusée — toutes les têtes sont lues désormais, une seule qui
déclare suffit. (2) Le test du branchement `pytest.skip`ait sur **toute** valeur de `core.hooksPath`
non conforme : `git config core.hooksPath .git/hooks` désarmait la porte et le test restait vert par
SKIP ; seul le cas légitime (worktree visant les `.githooks` du dépôt principal, vérifiés là-bas)
saute encore, tout le reste ÉCHOUE. (3) Le test « la porte est morte en `pre-merge-commit` »
n'affirmait que `rc == 0`, soit le résultat de ne rien faire : il fusionne maintenant deux fois dans
le même dépôt, le même corps de hook branché aux deux moments, et exige que le second REFUSE.
(4) Calibrage re-mesuré (voir ci-dessus). Les trois verrous vérifiés ROUGES défaut remis.

✅ **La sortie de secours existe pour de bon, et le refus ne piège plus** (2026-08-12, 4ᵉ passe
`/code-review`). Deux défauts REPRODUITS, qui se cumulaient en impasse : (1) `git merge
--no-verify`, annoncé par le refus ET par la doc, ne saute que `pre-merge-commit` et `commit-msg`,
jamais `prepare-commit-msg` — la porte refusait quand même ; (2) la remédiation dictée (« écris
leurs lignes puis relance ») ne débloquait rien, parce que ni la dette ni la branche fusionnée ne
regardent l'INDEX : on pouvait écrire sa ligne, `git add`, `git commit`, et se faire refuser à
l'identique, coincé au milieu d'une fusion. Désormais l'index vaut déclaration, le désarmement se
fait par `ROADMAP_GATE=off` (et la porte le DIT au lieu de se taire), et le refus n'indique plus
que des issues qui existent. Un troisième vert vacant fermé au passage : les fixtures passaient
`--no-verify` avant toute installation de hook, donc rien n'y testait la sortie de secours.
Verrous vérifiés ROUGES défaut remis.

✅ **La consigne de sortie vaut pour le MOMENT où elle s'affiche** (2026-08-12, 5ᵉ passe
`/code-review`, même arête une troisième fois). Le refus indiquait `ROADMAP_GATE=off git merge …`
alors qu'il ne s'affiche QUE fusion commencée : git répond là `fatal: You have not concluded your
merge (MERGE_HEAD exists)`. La commande qui marche à cet instant est `ROADMAP_GATE=off git commit`,
et c'est elle qui est écrite — dans le refus, dans le filet d'exception (qui annonçait encore
`--no-verify`) et ici. Le test de la sortie de secours faisait par ailleurs `git merge --abort`
avant de l'exercer : il validait depuis un dépôt propre, jamais depuis l'état de refus décrit par
sa propre docstring — l'abort est retiré, la sortie s'exerce MERGE_HEAD présent. Trois verrous
vérifiés ROUGES défaut remis.

✅ **Deux verrous redevenus vacants par une livraison ULTÉRIEURE** (2026-08-12, 6ᵉ passe
`/code-review`). Les tests de la pieuvre et des histoires sans ancêtre étaient bien ROUGES le jour
où ils ont été écrits ; l'ajout de `index_declares()` — trois heures plus tard, dans une autre
livraison — les a rendus verts pour une autre raison que celle qu'ils annoncent : `declares`
court-circuite sur l'index, vrai dès qu'une fusion est en cours, donc `merge_heads()` et
`branch_touches_roadmap` n'étaient plus atteints du tout. Remettre l'un ou l'autre défaut les
laissait VERTS (mesuré). Les deux tests appellent désormais la fonction concernée EN DIRECT, en
plus du bout-en-bout, et les deux défauts d'origine les rendent de nouveau ROUGES. ⚠️ La leçon
n'est pas locale : un verrou prouvé rouge à sa naissance peut être désarmé par un raccourci ajouté
plus tard EN AMONT de lui — c'est le seul cas où « le test est passé rouge une fois » ne suffit pas.

✅ **Passe `/simplify`** (2026-08-12). Six passes de corrections avaient empilé des cas
particuliers : trois d'entre eux disparaissent sans rien perdre. La branche courante se lit par un
seul appel qui distingue lui-même attaché / détaché / hors dépôt (fin du helper tolérant, de la
sonde et de la contrainte d'ordre entre les deux) ; les deux questions « la ligne est-elle là ? »
passent le chemin à git en pathspec au lieu d'énumérer toute la branche ou tout l'index ; la dette
n'est plus calculée quand la livraison déclare, alors que le verdict n'en faisait rien. Le feu vert
dit désormais LAQUELLE des deux déclarations l'a ouvert — il affirmait « la branche fusionnée » y
compris quand c'était l'index, c'est-à-dire précisément quand l'utilisateur venait de se débloquer
à la main. Le désarmement accepte toute valeur non vide (`ROADMAP_GATE=1` refusait en silence).
Côté tests, le corps de hook monté par les verrous EST maintenant le fichier livré, plus une
transcription qui pouvait diverger sans que rien ne rougisse.

**Deux pièges déjà payés, à ne pas reprendre pour des régressions.** (1) Un contrôle de liens naïf
rend **152 hits** dont aucun n'est mort (143 dans `Implémenté/stage.md`, 5 dans `Boardx10-audit.md`,
tous des `file:///`, qui sont ABSOLUS par convention CLAUDE.md) ; le script les résout comme tels.
(2) Apparier fichiers et symboles **en prose** rendait 4 alertes fausses sur 4 : une phrase cite
couramment un fichier et, plus loin, des symboles étrangers. En prose, seule l'existence est
vérifiée ; l'appariement reste réservé aux cellules de tableau, où le renvoi est porteur.

### Incohérences factuelles restantes (non traitées, aucune ne bloque)

- **`obs_size`** — la valeur vraie à HEAD est **16659**, portée par les **9** profils de la config
  ArmageddonAgent (un `"obs_size": 16659` chacun ; ce fichier a annoncé « 3 occurrences », puis
  « 7 profils », sans jamais les compter — c'est le contrôle de §5 qui les compte désormais).
  ✅ `Implémenté/01_ability_embedding.md`, qui annonçait 14609/14615, est corrigé. Reste la
  `justification` du champ dans la config, qui raconte encore la lignée 20780 → 20727. **Le gel
  est levé** (§0, run terminé) : plus rien n'interdit d'y toucher, c'est du travail restant, pas
  une attente.
- ~~`justification` de `bot_eval_final_normal` dit « x1 (10 000 episodes) » alors que
  `x1.total_episodes` = **50 000**.~~ → **L'INCOHÉRENCE ÉTAIT DANS CE FICHIER, pas dans la config**
  (corrigé le 2026-08-10) : `x1.total_episodes` vaut bien **10 000** ; le 50 000 est
  `total_episodes_normal`, une clé de **commentaire** que `train.py` ne lit pas (il lit
  `total_episodes`). La `justification` avait raison. Même erreur propagée depuis
  `V11_agent_rework.md` §0.70, corrigée là aussi.
- ~~`A_faire/Endless_duty_etat_mesure.md` affirme que `config/agents/CoreAgent/` n'existe plus —
  **il existe**.~~ ✅ corrigé dans le doc le 2026-08-10.
- **Vitesse d'entraînement : deux régimes incompatibles, facteur ~14** (relevé le 2026-08-11).
  Les notes `total_episodes_normal` de cinq profils de la config ArmageddonAgent annoncent
  `0.1 s/ep -> 36k ep / hour` ; le seul run réellement chronométré donne **4 h 01 pour 10 000
  épisodes** (§1 pt 6), soit ~2 500 ép./h. La refonte d'observation V11 (`obs_size` 16659) a rendu
  le pas bien plus cher et le premier chiffre n'a pas suivi. Conséquence directe : **toute durée
  d'entraînement dérivée du régime ancien est fausse d'un ordre de grandeur** — dont les « ~5 h 30
  pour 200 000 épisodes » que répètent [`../AI_TRAINING.md`](../AI_TRAINING.md) et trois notes
  `bot_eval_*_normal`, et le
  `36_000` codé en dur dans `test_schedule_decay_fraction.py` (seuil conservé parce qu'il est le
  plus SÉVÈRE des deux, jamais laxiste). Les durées de `x1_long` ont été réancrées sur la mesure
  le 2026-08-11 ; le reste ne l'est pas. Le traiter = re-dériver chaque note de coût d'évaluation
  des 9 profils, donc un chantier à ouvrir, pas un périmètre de clôture.
- Bandeaux et chiffres périmés listés en `1_Agent/V11_agent_rework.md` §0bis (l.3713-3735),
  signalés et volontairement non corrigés depuis le 2026-07-20.
- `UNIT_ABILITY_SLOTS = 8` est une projection non mesurée ; le chantier 06 la rendra mesurable (§2).
- **Ancres de ligne des docs V11 : périmées en masse** (relevé le 2026-08-10). Les symboles cités
  existent tous, mais les numéros de ligne ont dérivé de 400 à 3 500 lignes — `_select_allocation_model`
  ~5643 → **7980**, `fight_pile_in_plan` ~6708 → **10240**, `squad_consolidate_plan` ~7038 →
  **10627**, `charge_build_valid_plan` ~3955 → **5720**, `_auto_select_cc_weapon_for_fig` L7370 →
  **10463**, `_auto_declared_order` L6462 → **9133**, `compute_candidate_footprint` L416 → **496**.
  Les lignes du **chemin critique** (§9.4, §9.0bis, §1bis) sont corrigées en **nom de symbole** ;
  le reste des docs n'a pas été balayé.
  🟢 **DÉCISION 2026-08-10 — traitement AU FIL DE L'EAU, pas de balayage global.** Motif : le
  porteur de risque est un doc qu'on **rouvre** (c'est ainsi qu'est né le plan T7 faux, cf.
  `V11_tranches.md` §1bis) ; un balayage complet dépenserait une journée sur `Implémenté/`, qui
  n'a plus que valeur d'historique. **Règle : tout doc modifié voit ses ancres de ligne corrigées
  dans la même livraison** — cela entre dans le périmètre de clôture T2, sans validation
  supplémentaire.
  **Convention d'écriture : citer `def <symbole>` ou un `grep` reproductible, jamais un numéro de
  ligne** — c'est la seule forme qui survit à une livraison.
