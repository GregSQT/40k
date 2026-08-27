# V11 — Pièges et leçons de méthode

> **Source** : extrait de `Documentation/Chantiers/v11/V11_agent_rework.md` §0bis lors de la refonte P3 (2026-08-27).
> Ce document contient la **copie canonique** des leçons de méthode. En cas de divergence avec
> `V11_agent_rework.md`, cette copie fait foi (les occurrences restées dans `V11_agent_rework.md`
> §0hist ne font que documenter le raisonnement local).

## 0bis. Pièges et leçons de méthode — 📌 SECTION CANONIQUE

> **Éditer les avertissements ICI.** Chacun est reproduit **mot pour mot** depuis son entrée
> d'origine, dont la référence est donnée. Les occurrences restées dans §0hist en sont des
> **copies** : elles y documentent le raisonnement local, mais la version qui fait foi est
> celle de cette section.
>
> Ces passages existent pour **empêcher de re-diagnostiquer un faux problème**. Aucun ne doit
> être résumé ni supprimé, même si l'entrée dont il vient est close.

### Le grep du JUMEAU se fait sur chaque correction, pas sur le lot (§0.66, 2026-08-04)

CLAUDE.md désigne le miroir corrigé d'un seul côté comme le motif d'échec n°1 du dépôt. §0.66 l'a
rejoué **trois fois dans le même lot**, en le sachant, et aucune des trois n'a été vue à
l'écriture — les trois ont été trouvées par `/code-review` :

- `[FLY]` posé sur le move squad, **pas** sur `squad_charge` (même fonction, 200 lignes plus bas) ;
- la borne de trajet écrite pour la métrique `hex`, **inerte** en `euclidean` — donc dans tout le
  PvP et le bot PvE, où `distance_metric.move` vaut justement `euclidean` ;
- une fixture de test mise à jour sur les **trois** que la nouvelle exigence cassait.

Le point commun n'est pas l'inattention : c'est d'avoir fait le grep du jumeau **en fin de lot**,
sur les symboles corrigés, au lieu de le faire **à chaque correction**, sur le mécanisme touché.
Un grep de fin de lot trouve les jumeaux du *symbole* ; il ne trouve pas la branche `else` d'un
sélecteur de métrique, ni la deuxième fixture d'un test.

**Corollaire structurel**, remonté par `/simplify` : les payloads d'`action_log` du gym sont des
**copies manuelles** de ceux du PvP. C'est *pour cela* que `[FLY]` a pu manquer des deux côtés.
`fight_handlers._append_fight_move_log` est le précédent à imiter — il manque son équivalent
move/charge, consommé par les deux flux. Tant qu'il n'existe pas, le prochain champ de log sera
oublié de la même façon.

### Une plomberie complète et testée peut n'être branchée sur AUCUN chemin de production (§0.66, 2026-08-04)

Le drapeau `is_fly_move` traversait `movement_handlers` → `_build_step_log_details` →
`step_logger`, chaque maillon couvert par un test vert. `grep -c "\[FLY\]" step.log` rendait
pourtant **0** sur 24 Mo. Les tests verrouillaient le **formateur** et le **mapping** ; l'ÉMISSION,
elle, n'était posée que sur les chemins PvP, qui n'émettent pas la clé `move_type` exigée par le
drainage vers `step.log` — ils ne peuvent donc structurellement pas l'alimenter.

Un test qui part du milieu de la chaîne ne prouve rien sur ses extrémités. Pour un contrat de
journal, le verrou doit partir de **l'action de production** et finir sur **la ligne écrite**.

### Une COURBE SANS AUCUN POINT est un défaut, pas un creux de données (§0.68, 2026-08-08)

Trois métriques `obs/<phase>_*` lisaient un layout d'observation supprimé neuf jours plus tôt. Le
code n'a pas planté pour autant : sa garde (`info['phase'] ∈ ('shoot','fight','charge')`) n'était
**jamais vraie**, aucune action d'agent ne posant de `phase`. Mort deux fois — layout disparu ET
condition inatteignable — il est resté en place jusqu'à ce qu'un chantier sans rapport (`L2`)
ajoute un `phase` à son `info` et le réveille **en rollout**, sur le run le plus cher du projet.

Le signal existait et n'a été lu par personne : **la courbe n'avait aucun point dans aucun run**.
Un `grep -ac "<tag>"` sur les fichiers d'events répond en une seconde. À faire pour toute
instrumentation qu'on croit acquise, et systématiquement après une refonte du format qu'elle lit.
Corollaire : un test qui **mocke l'extracteur** qu'il prétend couvrir (c'était le cas ici) est un
vert vacant — il atteste du câblage, jamais de la donnée.

### Un « ✅ SAIN » prononcé sur UNE règle ne dit rien des règles SATELLITES qui la modifient (§0.50, 2026-07-29)

Écrit en corrigeant 01.07 (une unité **battle-shocked** contrôlait ses objectifs normalement).
[`V11_tranches.md`](V11_tranches.md) affirmait :
*« ✅ **Le vrai Objective Control est SAIN** : `_sum_objective_control_oc` compte bien
OC × figurines dans la zone (14.02). Ce sont les règles satellites qui n'ont pas suivi. »*
(la phrase est **barrée à la source** depuis le 2026-07-29, avec la mention « AFFIRMATION FAUSSE ») L'audit qui a produit cette phrase cherchait
**un** défaut précis — le calcul à l'ancre d'escouade au lieu du par-figurine — et l'a correctement
écarté. Mais la phrase écrite dit bien plus que ce qui a été vérifié, et c'est **elle** qui a rendu
le défaut invisible pendant des mois : quiconque relisait le contrôle d'objectif lisait d'abord
« SAIN » et passait. La fonction ne consultait **jamais** `battle_shocked`, alors que **01.07** met
l'OC de toutes les figurines d'une unité choquée à `'-'` et que **02.02** rend alors la figurine
incapable de contrôler.

**Règle.** Vérifier qu'une fonction applique correctement la règle **R** n'autorise à conclure que
sur **R**. Une caractéristique de jeu est presque toujours **modifiée par des règles satellites**
(états, mots-clés, auras, phases) qui vivent dans **d'autres PDF** que celui de la règle principale
— ici l'OC est décrit en 14.02, mais **modifié** en 01.07 et **interprété** en 02.02. Donc :

- **Ne jamais écrire « SAIN » / « CONFORME » sans le quantifier** : dire *« conforme à 14.02 sur le
  décompte par figurine »*, jamais *« le contrôle d'objectif est sain »*. Un verdict non borné est
  un **verdict faux dès la première règle non testée**.
- **Avant de conclure, énumérer les modificateurs** : quelles règles écrivent, annulent ou
  remplacent la caractéristique lue ? La recherche se fait dans les PDF (`Documentation/40k_rules/`),
  pas dans le code — le code ne peut pas révéler une règle qu'il n'implémente pas.
- **Le verdict le plus dangereux est le verdict RASSURANT.** Un « ÉCART » relance une lecture ; un
  « SAIN » la clôt. C'est pourquoi un ✅ mérite plus de justification écrite qu'un 🔴, et non moins.
- Corollaire pour ce document : une phrase de doc peut **couvrir** un bug aussi efficacement qu'un
  test faux. Quand un audit contredit une affirmation ✅ existante, l'affirmation doit être
  **annotée à sa source**, pas seulement contredite ailleurs.

### Un test qui contourne `__init__` atteste que la production ne peut pas construire l'objet (§0.45, 2026-07-29)

Écrit en supprimant `ai/scenario_manager.py`. Ses **9 tests** commençaient tous par le même stub :

```python
manager = ScenarioManager.__new__(ScenarioManager)   # constructeur JAMAIS appelé
manager.scenario_templates = {...}                    # etat injecte a la main
```

Le constructeur était contourné pour une raison précise : il **lève**. `_load_scenario_templates`
exige `config/scenario_templates.json`, absent du dépôt, et refuse tout fallback. Autrement dit
`ScenarioManager(…)` était **inconstructible en production depuis toujours**, et les tests
mesuraient un objet que le code applicatif ne pouvait pas obtenir. Ils étaient verts, et ils
n'ont jamais couvert un chemin exécutable.

**Règle** : `__new__`, `object.__setattr__`, un `MagicMock` substitué au constructeur, ou tout
montage qui saute l'initialisation réelle, sont des **indices de code mort**, pas des astuces de
test. Avant de les accepter, exiger la réponse à : *quel appelant de production construit cet
objet, et cette construction réussit-elle ?* Si la réponse est « aucun » ou « elle lève », le
sujet n'est pas le test — c'est la cible. Corollaire pour l'audit de code mort : **un compte de
tests verts n'est pas une preuve de vie**.

### Un canal d'observation NON VIDE ne prouve pas qu'il regarde au bon endroit (§0.40, 2026-07-28)

Écrit en corrigeant l'ancre de la grille égocentrique pendant le déploiement (§0.40 point 2).
Le premier verrou écrit était : *« pendant le déploiement, le canal murs et le canal objectifs de
la grille ne sont pas vides »*. Il était **vert AVANT le correctif** — donc il ne prouvait rien.

**Pourquoi** : le board fait 220×300 et la fenêtre égocentrique en couvre ±90. Ancrée sur la
sentinelle `(-1,-1)`, elle montrait le coin `(0,0)` du plateau — une région pleine de murs et
d'objectifs, simplement **pas celle où l'unité allait se poser** (la zone du joueur 1 commence à la
ligne 151). Une ancre fausse ne produit pas une grille vide : elle produit une grille **plausible
et fausse**, exactement le motif d'erreur le plus difficile à voir en lecture.

**Ce qui verrouille vraiment** — deux assertions, pas une :
1. une grandeur **quantifiée et comparable** (ici : la part des hexes de la zone de déploiement qui
   tombent dans la fenêtre — 0 %/25 % avant, 96 %/78 % après) plutôt qu'un `.any()` ;
2. une **égalité exacte** entre le canal produit et une rasterisation indépendante depuis l'ancre
   attendue. C'est elle, et elle seule, qui verrouille le **câblage** dans `build_squad_grid` :
   tester la fonction d'ancrage isolément laissait passer la mutation qui remettait l'ancienne
   ancre à l'appel.

**Règle** : un test d'observation spatiale doit affirmer **où** la fenêtre regarde, jamais
seulement **qu'elle contient quelque chose**. Et tout verrou d'obs se valide par mutation : casser
le correctif, exiger le rouge, restaurer, exiger le vert.

### Ne pas juger une conformité de règle par une reconstruction offline — mesurer sur le vrai chemin in-engine (§0.28, 2026-07-22)

Un soupçon de « tir à travers terrain » (obscuring 13.10) a coûté une **cascade de faux verdicts**
avant d'être **réfuté** par une mesure in-engine. Les pièges, dans l'ordre où ils ont trompé :
1. **Scan offline centre→centre** : la LoS légale est **footprint→footprint par-figurine** (06.01, un
   bord de socle voit ce que le centre ne voit pas). Tester centre→centre sur-flagge en masse. Ce
   motif est le **même** que celui qui a fait retirer le contrôle LoS de l'analyzer (§0.24 /
   `project_analyzer_los_verdict`).
2. **Rejeu headless non fidèle** : `place()` écrivait `unit["col"/"row"]` alors que le moteur lit
   `units_cache` (`require_unit_position`) → unités restées à `(-1,-1)` → LoS triviale. Puis même
   corrigé, l'arme/portée/état divergeaient du training. **Un rejeu doit vérifier son propre setup**
   (assert `require_unit_position == position attendue`) avant de conclure quoi que ce soit.
3. **Instrumenter le mauvais chemin** : 6 points instrumentés (compute_unit_los, valid_target_pool_build,
   pool cache-hit, w40k_core log, action_decoder legacy) ont montré **0 hit** — le pipeline squad V11
   n'emprunte AUCUN. Le vrai gate est `build_squad_action_mask` → `_model_can_shoot_target` →
   `_attacker_model_can_reach_squad`. **Toujours tracer `env.get_action_mask` d'abord**, ne pas deviner.
4. **Env var non propagée** : un audit gardé par `W40K_LOS_AUDIT` montrait 0 hit ; en inconditionnel,
   297. Vérifier qu'une instrumentation gardée **s'exécute vraiment** (heartbeat) avant d'interpréter un 0.

**Règle** : une affirmation de (non-)conformité de règle n'est valide **que** mesurée dans le moteur, sur
le chemin réellement emprunté, avec un heartbeat qui prouve que la sonde tourne. Une reconstruction
offline ne prouve rien sur la conformité.

### Sur ce document lui-même (§0.-1, §0.0)


**Réserve de méthode — ce qui n'a pas été revérifié (§0.0)**

**⚠️ Réserve de méthode sur ce document.** Les sections §0.x reflètent ce qui a été relu et
exécuté pendant la session du 2026-07-19 soir. **Le reste du document — T1 à T5, section 9 — n'a
PAS été revérifié ligne à ligne contre le code.** Trois affirmations périmées y ont été trouvées
et corrigées ce soir-là (« prochain bloqueur [§10.4](V11_eval_strategy.md#s10.4) » alors qu'il était résolu, « archivage des
holdouts à faire » alors qu'il l'était, « 9 échecs préexistants » alors que la suite est verte) —
**il peut en rester d'autres du même genre**. Vérifier dans le code avant de s'appuyer sur une
affirmation de ce document qui n'est pas datée de la session en cours.

➜ **Cette réserve est désormais une TÂCHE : voir §0.19** (méthode d'audit et historique des
démentis). Tant qu'elle n'est pas menée, la mise en garde ci-dessus reste pleinement valable.

➜ **Relecture T2→T5 menée le 2026-07-29 : voir [§0.47](#s0.47)** — **9 écarts** (T2 et T4 en
écart, T3 et T5 conformes). Elle confirme une fois de plus la réserve ci-dessus. **Elle ne la lève
pas** : elle s'est faite **par lecture seule, sans exécuter un seul test** (run 4 en cours,
working tree gelé), donc sans mutation-test.

➜ **Passe menée le 2026-07-20 : voir §0.19.1.** T2/T3/T4/T5 sont verrouillés par mutation-test ;
**T1 est repassée en ⏳** (R6 site 1 inatteignable au x5, R4 sans aucun test) ; la section 9 n'a
jamais été marquée ✅ (c'est un plan). La réserve reste valable pour **T1/R4**, dont le
mutation-test n'a pas pu être mené (`shared_utils.py` sous instrumentation §0.18), et pour [§7](V11_tranches.md#s7)/[§10](V11_eval_strategy.md#s10)
qui n'ont **pas** été audités.

**Comptages de tests : le seul verdict disponible est le code de sortie (§0.-1)**

⚠️ **Chiffre daté du 2026-07-19** — la suite a grossi depuis (+6 tests le 2026-07-20 : 4 en
§0.10, 2 en §0.13). **Ne pas traiter `1402` comme un compte à retrouver** : le reporter du
projet n'imprime pas la ligne de résumé de pytest, le seul verdict disponible est le **code de
sortie** (`exit 0`, vérifié après chaque lot du 2026-07-20).

**La règle de périmètre `ArmageddonAgent` et les 10 fichiers `CoreAgent` verts (§0.-1)**

⚠️ **10 fichiers de tests contiennent encore la chaîne `CoreAgent` et sont VERTS — c'est
normal.** Audités **un par un** (et non par échantillon — la première vérification avait manqué
`test_board_ref_resolver.py` ci-dessus en généralisant depuis 3 fichiers de `tests/unit/ai/`
alors que le seul cas fautif était dans `tests/unit/engine/`) : ce sont des chaînes passées à des
fonctions **pures** (`_load_bot_eval_params`, `build_agent_model_path`, `_scenario_name_from_file`),
des stubs (`SimpleNamespace`, `_DummyCfgLoader`, `_Cfg`), des arborescences **synthétiques dans
`tmp_path`**, ou de simples commentaires. **Aucun n'atteint la vraie config.** Ne pas les
« corriger » par un `sed` global.

**Leçon de méthode** : « vérifié un par un » sur un échantillon n'est pas une vérification.
Le seul contre-exemple était dans le répertoire non échantillonné.

### Un smoke à UN épisode ne voit pas un état qui fuit ENTRE épisodes (§0.42, 2026-07-28)

Le mécanisme de décision agent ([§9.3](V11_phaseA.md#s9.3) P2) a été validé par un smoke in-engine : 28 décisions
exposées et jouées, épisodes terminés, aucun masque vide. Le smoke lançait **un épisode par
moteur**. Le contre-audit a rejoué **3 épisodes enchaînés dans le MÊME moteur** : **16 décisions,
puis 2, puis 0**. `_choice_timing_fired_events` indexe ses événements sans le numéro d'épisode et
`reset()` ne le purgeait pas — le mécanisme s'éteignait après le premier épisode d'un run, sans
qu'aucun test ni aucun smoke ne rougisse.

**Règle** : tout état de `game_state` ajouté par une tranche doit être confronté au `reset()`, et
la mesure de validation doit **enchaîner plusieurs épisodes sur le même moteur** — c'est le seul
protocole qui montre une fuite d'état. Un compteur d'événements « déjà tirés » est le cas type :
il est correct dans l'épisode, faux entre deux.

### Un test qui passe du premier coup n'est pas encore un verrou (§0.43, 2026-07-28)

Les 8 premiers tests de parité masque/commit de la cible de charge sont passés **au premier
essai**. Trois mutations ont été appliquées pour vérifier qu'ils mordaient : masque sans filtre
d'éligibilité, commit sans garde d'éligibilité, décodeur décalé d'un slot — les trois ont bien
rougi. Mais l'une d'elles a révélé qu'un test **ne discriminait pas** : « les slots ouverts ==
les cibles déclarables » était vrai trivialement, parce que *toutes* les cibles mappées du
scénario étaient à portée. Il a fallu **fabriquer** le cas contraire (éloigner une cible au-delà
de 12" et vérifier que son slot se ferme) pour que l'assertion ait un contenu.

**Règle** : quand un test neuf passe sans avoir jamais échoué, appliquer la mutation qu'il est
censé attraper. Si elle ne le fait pas rougir, le test décrit la fixture, pas le code. Le même
raisonnement vaut pour une feature d'observation : la justifier exige une **contre-épreuve à
variable unique** (ici : même `edge_distance`, atteignabilité opposée), sinon rien ne prouve que
le champ existant ne suffisait pas.

### Migrer un test de code mort vers le vif est un AUDIT de conformité, pas un refactor (§0.38, 2026-07-28)

Les 5 fichiers qui tenaient `_attack_sequence_rng` en vie portaient 138 assertions vertes. En les
re-pointant sur le chemin vif, **11 d'entre elles se sont mises à contredire le moteur**. Le
réflexe naturel — assouplir l'assertion, ou « adapter le test au nouveau chemin » — aurait détruit
le seul résultat de valeur de la manœuvre : chacune de ces 11 assertions décrivait un comportement
**contraire au PDF**, que le code mort implémentait et que le vif avait corrigé ([HAZARDOUS] 24.15
jeté par attaque au lieu d'une fois par arme après toutes les attaques ; [HEAVY] 24.16 avec une
clause sur trois).

**Règle** : une assertion qui rougit en migrant est un **verdict à instruire**, pas un test à
réparer. On lit le PDF, on désigne qui a tort, et on écrit la réponse dans la doc comme un constat
de conformité. Corollaire opérationnel : ne jamais supprimer une assertion « parce qu'elle est
dupliquée ailleurs » sans avoir vérifié la couverture **assertion par assertion** — c'est ce
recensement qui a fait apparaître que [HAZARDOUS] en **mêlée** n'était couvert par rien, alors même
que le fichier censé le couvrir s'appelait `test_fight_special_rules.py` et ne testait que du tir.

**Second corollaire** : un état orphelin ne se juge jamais sur la ressemblance de son nom. Les
7 champs `_rapid_fire_*` supprimés ici étaient morts, mais [RAPID FIRE] 24.30 est bien VIVE — dans
un autre module, sous un autre mécanisme. Symétriquement, les branches `squad path expected` que
§9.2 listait comme résidus sont sur un chemin **vif** : les supprimer aurait dégradé une erreur
explicite en retour silencieux. Preuve d'appelant exigée dans les deux sens, avant toute suppression.

**Troisième corollaire, appris à la relecture** : *un grep sur un libellé n'est pas un recensement*.
Trois chiffres de la première rédaction de §0.38 étaient faux pour cette raison — « 6 fichiers de
tests » (5 appelaient réellement le mort, le 6ᵉ ne le citait qu'en commentaire), « ~159 assertions »
(138), « 4 branches-gardes » (5, la cinquième portant un autre message). Recompter coûte une
commande ; publier un chiffre repris d'un énoncé coûte la confiance dans tous les autres. Ce qui se
compte se compte **par la propriété visée** (`grep -c '= la_fonction('`, `raise RuntimeError`,
l'AST), jamais par la phrase qu'on s'attend à lire.

### Un script de mutation qui restaure par `git checkout --` DÉTRUIT le travail non commité (§0.38, 2026-07-29)

La contre-épreuve par mutation consiste à casser le code, relancer, puis restaurer. Restaurer avec
`git checkout -- <fichier>` marche tant que le fichier est **commité**. Le 2026-07-29, deux salves
ont tourné sur des correctifs **non encore commités** : chaque « restauration » a silencieusement
ramené le fichier au dernier commit, effaçant les modifications en cours. Aucune erreur, aucun
avertissement — le symptôme est apparu plus tard, sous la forme d'un « RESTAURÉ : rouge » en fin de
script, alors que le vrai dégât était déjà fait.

**Règle** : un harnais de mutation restaure depuis un **snapshot du contenu** pris juste avant la
mutation, jamais depuis git. Git ignore ce qui n'est pas commité, et c'est précisément ce qu'on est
en train d'écrire quand on teste. Corollaire : **commiter avant de lancer les mutations** — le
commit est de toute façon la bonne granularité (un fix = ses tests), et il rend le harnais inoffensif.

### Une garde « de performance » non mesurée est souvent du travail EN DOUBLE (§0.43, 2026-07-28)

`charge_reachable_max_roll` avait été écrit sous **deux** gardes : la phase de charge, et
l'éligibilité 11.02 de la cible. La première était documentée comme une garde de coût — et la
seconde aussi, dans les mêmes termes. Le contre-audit a mesuré : `charge_build_valid_plan`
**commence lui-même** par `charge_check_eligibility`, donc le pré-test était **double** pour une
cible déclarable et **sans gain** pour une cible hors portée. Il n'existait aucun cas où il
gagnait. Il a été retiré.

⚠️ Et la première rédaction de cette leçon affirmait exactement le contraire (« la seconde est
purement une garde de coût ») : **une justification de perf écrite sans mesure peut être fausse
au point de survivre à sa propre leçon.**

**Règle** : une garde présentée comme une optimisation se justifie par une **mesure**, et la
mesure la plus probante n'est pas le chrono (bruité, ici le gain — 42 µs par cible — était du
même ordre que la variance) mais le **comptage d'appels**, qui est déterministe : 4 appels
d'éligibilité pour 2 cibles disait tout. Compter avant de chronométrer.

### Un comportement obtenu par effet de bord n'est pas un comportement décidé (§0.42, 2026-07-28)

Une action `agent_decision` recevait un reward de 0.0 — la valeur voulue — mais **uniquement**
parce que son payload contient la clé `waiting_for_player`, qui la faisait classer « réponse
système » par `RewardCalculator`. Retirer cette clé du payload l'aurait basculée dans le chemin
« unité agissante » : reward d'unité arbitraire, ou `ValueError`. Le comportement était juste, sa
cause était accidentelle, et rien ne l'aurait signalé.

**Règle** : quand un chemin nouveau traverse un code de dispatch existant, vérifier **par quelle
branche** il passe, pas seulement **ce qu'il rend**. Un test qui n'observe que la valeur de sortie
ne distingue pas « par conception » de « par effet de bord » — il faut la mutation qui retire la
cause accidentelle.

### Sur le raisonnement et la preuve


**Une piste écrite dans une note « hors périmètre » est une hypothèse, pas un diagnostic (§0.34, 2026-07-28).**
La note de §0.32 désignait le bon fichier, la bonne fonction et la bonne ligne
(`erode_move_pool_by_squad_block`, court-circuit mono-figurine) — et **la mauvaise cause**. La vraie
divergence était en amont : la frontière normal/advance était calculée sur le `MOVE` **brut** quand le
pool et l'exécution appliquent `MOVE − coût de descente`. Le court-circuit ne faisait que **retirer le
filet** qui masquait le bug ailleurs : sur les escouades multi-figurines, l'érosion « corrigeait » la
bande morte en **supprimant silencieusement des Advances légaux**. Deux corollaires :
1. **Un bug partiellement masqué par un filet se déguise en cas particulier.** « Ça ne touche que les
   mono-figurines » était vrai pour le *crash* et faux pour le *défaut* : 100 % des escouades
   descendantes perdaient des coups légaux.
2. **Corriger là où ça crashe aurait aggravé le défaut** (érosion étendue au mono = crash supprimé,
   coups légaux perdus partout). Avant de corriger le site du raise, vérifier **quelle grandeur** chaque
   côté de l'invariant mesure — c'est le motif §0.18/§0.26 pour la troisième fois.

**Vérifier SUR QUEL scénario un chiffre a été mesuré avant de le transformer en blocage (§0.34, 2026-07-28).**
« 43 occurrences / 650 pas, le training ne peut pas tourner » : les 43 venaient du harnais de bench de
T-K/T-L, qui tourne sur **`scenario_pvp_test`** — le seul scénario portant une escouade à `level: 1`. Le
scénario d'ENTRAÎNEMENT mesuré dans les mêmes conditions donne **0**, en x1 comme en x5. Le bug était
réel et il est corrigé, mais il ne bloquait pas le run §0.14. Un chiffre sans son scénario n'est pas
une fréquence, c'est une anecdote.

**Prototyper + bencher AVANT d'intégrer un levier perf (§0.22, 2026-07-21) — la mesure prime sur le plan écrit.**
Le chantier `MOVE_POOL_BUILD` a fait CINQ mesures qui ont chacune démenti une hypothèse « évidente » du
plan §8 de `V11_move_build_acceleration.md`, et un prototype hors-prod les a toutes attrapées avant tout code de prod :
1. Le plan désignait le **BFS** comme reliquat n°1 (« 66 % sur petits socles », profil §2bis). Mesuré :
   le BFS deque isolé ne coûte que **0,30 ms à move_range=12** (le régime réel du training, lui aussi
   mesuré, pas supposé). Le profil §2bis englobait autre chose.
2. Le plan proposait un **wavefront bbox-NumPy** pour le BFS. Prototype prouvé équivalent (reach+dist)
   mais **plus lent à move 12** (0,46×) ; il ne gagne qu'à move≥30. Réfuté.
3. Le vrai hotspot mesuré (cProfile) = la **boucle Python sur les offsets** de `_dilate`/`_spread`
   (gros socles), que le §8 de `V11_move_build_acceleration.md` avait déclaré « caduc ». Réhabilité par la mesure.
4. **L2b par lignes** (décompo runs) : l'empreinte **ovale n'est pas contiguë par ligne** en coords hex
   → fallback sur le socle qui compte. Réfuté.
5. **L2b par colonnes** (sparse-table) : équivalent, mais 1,34× ovale seulement / <1× petits socles →
   gain net ~1,1× pour une vraie complexité. Non intégré.
**Leçon** : un profil agrégé (« X = 66 % ») ne dit PAS quel code optimiser — il faut mesurer le
**régime réel** (ici `move_range`, le socle, l'`ez`) et **prototyper le remplacement en A/B équivalent
+ bench AVANT de toucher la prod**. Le filet de tests (oracle + snapshot + A/B fenêtré==plein-board)
garantissait qu'aucune régression métier ne pouvait passer ; le bench a garanti qu'aucune complexité
inutile n'a été livrée. Seuls **L1 + L_bbox** (gain sûr, sans dépendance) ont été retenus ; décision
**(B) STOP**. Détail complet → `V11_move_build_acceleration.md §3`.

**« Un run vert ne prouve rien » — DEUX confirmations de plus la nuit du 2026-07-22 (§0.25/§0.26).**
Le motif §0.11/§0.18 s'est répété deux fois en une nuit : (1) le fix move §0.25 a passé un `--step` de
**4 épisodes mono-env**, puis a **crashé en ~1 min** sur un vrai run 48-envs (`incohérence
masque/exécution`, §0.26) — le crash dépend de la trajectoire, qu'un smoke court ne visite pas ;
(2) c'est un **test déterministe reproduisant la condition exacte du crash** (occupation sans bump de
version → cache périmé) qui a verrouillé le fix, pas un run vert. **Règle renforcée : pour un invariant
(masque⊆exécutable, terminaison, budget), la preuve est un TEST QUI REPRODUIT L'ÉCHEC, pas un run qui
passe.** Le vrai run multi-env reste le juge final (le `--step` mono-env est structurellement aveugle
aux races de cache et aux états rares). Corollaire opérationnel : ne JAMAIS relancer un run coûteux
(19 h) sur la foi d'un smoke ; passer par un run multi-env qui franchit la zone de crash connue.

**Vérifier le PÉRIMÈTRE d'un travail délégué avant de l'accepter (2026-07-22).** Un agent chargé de
corriger l'analyzer (puis un autre le moteur) a livré, **sans le déclarer**, une refonte hors-périmètre
de `services/api_server.py` (**366 lignes**, −265/+104) + un `defaults.agent` dans `config/config.json`
— non lu par le chemin d'entraînement, non demandé. Détecté par `git status` avant tout commit et
**révoqué** (`git checkout -- config/config.json services/api_server.py`). **Ne jamais faire confiance
au « je n'ai touché que X » d'un agent : diffuser `git status`/`git diff` sur l'ARBRE ENTIER, pas sur
les fichiers annoncés.** Les agents restaurent aussi leurs propres backups de modèle → vérifier le md5
du `.zip` canonique (il n'a PAS à changer hors run `--new` voulu).

**Mesurer/lire AVANT d'affirmer une root cause (2026-07-22).** Deux affirmations trop rapides corrigées
la même nuit : (a) les 5508 « erreurs » analyzer qualifiées de « faux positifs » **avant de les avoir
lues** — en réalité un mélange de vrais bugs analyzer (§0.24) ET d'un vrai bug moteur (§0.25) ; (b) le
crash §0.26 attribué à « l'érosion d'occupation » alors que la root cause était le **cache** (trouvée
en instrumentant `build_squad_move_cell_map`, pas en devinant). **Un profil/compteur agrégé ou une
analogie ne DÉSIGNENT pas la cause : instrumenter le régime réel, puis conclure.** (Même leçon que la
perf §0.22 ci-dessus, re-vérifiée côté correction de bug.)

**Fiabiliser l'INSTRUMENT avant de l'utiliser comme juge (2026-07-22, §0.23/§0.24).** L'analyzer était
l'unique validateur du training mais restait pré-squad (ancre) → il ne pouvait ni prouver la
conformité, ni être cru quand il criait. Tant qu'un instrument de validation n'est pas réaligné sur la
V11 (per-figurine) ET prouvé sans faux positif sur les vraies unités, **toute mesure produite avec est
suspecte dans les deux sens** (faux positifs qui masquent + potentiels vrais bugs non vus). Le
réalignement a **payé immédiatement** : l'analyzer fiabilisé a fait émerger un vrai bug moteur (§0.25)
invisible jusque-là.

**Une contrainte de conformité peut être INCOMPATIBLE avec une décision de perf close (2026-07-22).**
§0.22 a été clos « STOP » pour ne pas payer le BFS par-socle. Mais la conformité move (§0.25) l'EXIGE
(érosion géodésique par-figurine) : la décision perf est **rouverte de facto par une exigence règles**,
pas par un choix d'optimisation. Quand une entrée est close sur un arbitrage coût/gain, vérifier qu'une
exigence de correction ne la rend pas caduque avant de s'appuyer sur sa clôture. Conséquence vive :
§0.27 (éval trop lente).

**Une invariance est CONDITIONNELLE à son état initial (§0.1)**

**⚠️ Corollaire — une affirmation de ce document était fausse.** L'ancien §0 affirmait que
`require_coherency` est « invariante par translation cube, donc déjà garantie par le pool
d'ancre ». L'invariance est réelle mais **conditionnelle** : elle prouve *si l'origine est
cohérente, le plan l'est*. Elle ne prouve **rien** quand l'origine est déjà incohérente — et dans
ce cas le pool entier est offert alors que rien n'est exécutable. C'est cette demi-vérité qui a
laissé le trou ouvert après T6-g. **Toute contrainte « prouvée invariante » doit être relue en se
demandant : invariante à partir de quel état initial ?**

**Suite (2026-07-29) — les DEUX moitiés sont fermées.** (a) L'invariance elle-même était FAUSSE en
mode euclidien : la 2e puce de 03.03 centrait un cercle sur « la paire la plus éloignée », or
plusieurs paires sont souvent à distance maximale EXACTEMENT égale sur grille hex → le centre, donc
le verdict d'une figurine au bord, était départagé par le bruit flottant, qui change avec la position
absolue de l'escouade. Critère passé PAR PAIRES (ce que dit le PDF) ; verrou
`test_coherency_translation_invariance.py`. (b) L'état initial était réellement incohérent : la
réduction de roster x5→x1 (`_downscale_fixed_unit`) décalait chaque figurine indépendamment, borne
PAR FIGURINE qui ne dit rien de la formation. Elle pose maintenant une chaîne connexe par
construction ; verrou `test_roster_downscale_coherency.py`. C'était le SEUL chemin de placement du
moteur sans contrôle de cohérence.

**Vérifier qu'un point d'ancrage est APPELÉ avant d'y brancher quoi que ce soit (§0.1)**

⚠️ **Piège rencontré, à ne pas refaire** : le premier branchement a été posé en tête de
`_advance_to_next_player`, qui *semble* être la frontière de tour mais est **du code mort**
(cf. §0.4). Le run de vérification a reproduit le crash à l'identique. **Vérifier qu'un point
d'ancrage est appelé AVANT d'y brancher quoi que ce soit.**

**Motif récurrent : du code correct, testé, et jamais appelé (§0.4)**

> **Motif récurrent à surveiller dans ce projet** — six occurrences vérifiées à ce jour.
> **Cinq de type « jamais appelé »** : `update_frozen_model` ([§10.4](V11_eval_strategy.md#s10.4)),
> `end_of_turn_coherency_removal` (§0.1), `_advance_to_next_player` (§0.4),
> `game_replay_logger` (§0.8, 795 lignes + 8 tests), `log_unified_action` (§0.8). Du code
> correct, testé, et jamais appelé. **Devant toute fonction sur laquelle repose un
> raisonnement, vérifier d'abord qu'elle a un appelant.**
>
> **Une de type « jamais exercé »** (§0.11) : `test_move_mask_is_executable.py` est appelé, vert,
> et mesure le bon invariant sur le bon scénario — mais par exploration aléatoire, donc il ne
> visite jamais la configuration qui cassait. **Un test vert ne couvre que les états qu'il
> atteint ; sa docstring peut affirmer le contraire de bonne foi.**

**Un test qui explore au hasard ne prouve rien sur ce qu'il n'atteint pas (§0.11)**

🔴 **Pourquoi `test_move_mask_is_executable.py` n'a rien vu** — c'est le point le plus important
de cette entrée. Ce fichier mesure **cet invariant exact**, sur **ce scénario exact**, et il est
vert. Il ne vérifie l'invariant que sur les états atteints par **exploration aléatoire** (3 seeds,
400 steps) : la superposition inter-étages n'y survient jamais. Sa docstring affirme pourtant
combler précisément ce trou (« Ce test remplace ce raisonnement par une mesure »).

> **Quatrième variante du motif §0.4, et la plus sournoise.** Les trois premières étaient du code
> *jamais appelé*. Celle-ci est du code appelé, par un test vert, qui **n'exerce jamais le cas**.
> Un test qui explore au hasard ne prouve rien sur les configurations qu'il n'atteint pas — et sa
> docstring peut affirmer le contraire en toute bonne foi. **Devant un test de type « je déroule
> des parties et je vérifie un invariant », toujours se demander quelles configurations il ne
> visite jamais, et les construire explicitement.**

**Ne pas conclure à un biais de tirage sur quelques dizaines d'observations (§0.10)**

Mesuré sur **400 resets** : Ork/Ork 102 (25,5 %), Ork/SM 107 (26,8 %), SM/SM 104 (26,0 %),
SM/Ork 87 (21,8 %) — **les 4 matchups, équiprobables** (χ² = 2,38 pour un seuil de 7,81 à 3 ddl :
aucun biais détectable). Un premier tir de 40 resets donnait 15/13/9/**3** et laissait craindre un
biais : c'était du **bruit d'échantillonnage**, pas un bug. Leçon : ne pas conclure à un biais de
tirage sur quelques dizaines d'observations — refaire la mesure en grand avant de diagnostiquer.

> **Bandeau de fiabilité du recensement d'ancre** — il vit en **[§1bis](V11_tranches.md#s1bis), « Dette d'ancre restante »**
> et n'a pas été déplacé : seuls 4 sites y ont été relus à la main, le reste est un faisceau
> d'indices. **Ne pas ouvrir de chantier depuis une ligne non marquée ✅ sans avoir lu la
> fonction.** Le lire avant d'exploiter ce recensement.

### Sur les runs et l'outillage


**Un run déjà lancé n'est PAS protégé d'un changement de code : `spawn` relit le disque (§0.41, 2026-07-28)**

Les workers d'entraînement sont forkés une fois au démarrage, ce qui laisse croire qu'éditer le
code pendant un run est sans effet sur lui. **C'est faux.** `ai/bot_evaluation.py` crée ses
workers d'évaluation avec `mp.get_context("spawn")` — un worker `spawn` **ré-importe tout le code
depuis le disque**. Un changement d'espace d'action ou d'observation posé sur `main` pendant un
run fait donc diverger le modèle en mémoire (ancien `TOTAL_ACTION_SIZE`) et les workers d'éval
(nouveau) : plantage à l'évaluation suivante, ou pire, mesure fausse. **Avant de conclure qu'un
run en cours est protégé, vérifier le mode de démarrage de CHAQUE famille de sous-processus.**
Parade appliquée en §0.41 : livrer sur une branche, laisser `main` intact jusqu'à la fin du run.

> 🔴 **PARADE INSUFFISANTE — la leçon a coûté un SECOND run le 2026-07-28 (§0.43).** « Laisser
> `main` intact » ne protège rien : ce que les workers `spawn` relisent, c'est le **WORKING
> TREE**, pas la branche `main`. P3-2 a été correctement livré sur `v11-p3-2-charge-target`
> (jamais mergé, vérifié : `main` est resté sur le commit P2) — mais le working tree est **resté
> checkouté sur cette branche**. Le `git checkout` de 21 h 39 a donc réécrit sur le disque
> `pointer_policy.py`, `macro_intents.py` et le JSON de config pendant que le run tournait.
> **Diagnostic reproduit** : le snapshot d'éval portait `action_net [18, 320]` sans
> `charge_query_net` (architecture P2, celle du process en mémoire) ; les workers ont reconstruit
> `action_net [17, 320]` **avec** `charge_query_net` (architecture P3-2, celle du disque) →
> `load_state_dict` lève dans l'`initializer` du pool → `BrokenProcessPool` → 600 épisodes
> `error` en 7,1 s → le garde-fou strict d'éval arrête le training.
> **Règle qui remplace la précédente** : pendant un run, le working tree est **GELÉ**. Ni commit,
> ni checkout, ni édition — quelle que soit la branche. Un agent qui doit livrer travaille dans un
> **worktree git séparé** (`git worktree add`), pas par bascule de branche.
> **Défaut d'observabilité à traiter** (non fait) : `BrokenProcessPool` a **avalé** la vraie
> exception ; le log ne donnait que « error_episodes=600 », sans cause. Il a fallu réexécuter
> `_eval_worker_init` à la main pour la voir. Tant que l'init du worker passe par l'`initializer`
> du pool, toute panne de worker sera indiagnosticable depuis le log — l'initialiser
> **paresseusement dans la tâche** ferait remonter le message réel par le chemin d'erreur
> par-tâche qui existe déjà.

**Une spec d'action_space peut être périmée par une évolution du RÉSEAU, pas seulement du moteur (§0.41, 2026-07-28)**

[§9.3](V11_phaseA.md#s9.3) prévoyait `CHOICE_0..K-1`, K colonnes denses de `action_net`, pour tout point de décision.
Écrite le 2026-07-14, elle est antérieure à §0.30 T-E et §0.32 T-G, qui ont supprimé précisément
ce motif (une colonne dense par rang n'apprend rien des autres et ne sait pas *ce qu'est* le
candidat qu'elle score). **Règle** : quand les candidats d'une décision sont des ENTITÉS déjà
encodées dans l'observation, la paramétrisation correcte est **une dimension d'action par slot,
scorée par produit scalaire sur l'embedding** — coût nul en paramètres, alignement obs↔action
structurel. Le mécanisme générique ne se justifie que pour les candidats **non-entité**. Corollaire
de méthode : une spec non datée de la session en cours se relit contre l'ARCHITECTURE actuelle,
pas seulement contre le moteur.

**Rendre un choix à l'agent sans lui donner de quoi le faire, c'est une demi-tranche (§0.41, 2026-07-28)**

P3-1 a d'abord été livrée « complète » : action, masque, tête pointeur, tests verts. Elle ne
l'était pas. L'agent choisissait sa cible de mêlée **sans voir combien de ses figurines pouvaient
la frapper** — le premier facteur du choix. Deux champs voisins donnaient l'illusion de la
couvrir : `n_fight_eligible` (mais il AGRÈGE sur toutes les cibles) et `edge_distance` (mais il
mesure l'ESCOUADE, alors que 04.02 s'évalue par figurine). **Règle : toute tranche P3 se termine
par la question « avec quelle information l'agent tranche-t-il ? », et la réponse se prouve par un
test de DISCRIMINATION** — deux candidats que la nouvelle feature sépare et que les champs
existants confondent. Sans ce test, « la feature existe » ne dit pas « la décision est observable ».
Corollaire de séquencement : quand une tranche impose déjà un retrain (action space), le coût
marginal d'ajouter la feature d'observation qui lui manque est **nul** — c'est le moment de la
livrer, pas une tranche plus tard.

**Un oracle partagé ne doit pas imposer son coût de mise en forme à tous ses appelants (§0.41, 2026-07-28)**

`_model_can_fight_target` (prédicat 04.02) reconstruit l'empreinte synthétique de la figurine à
chaque appel. Correct pour la résolution d'attaque, ruineux pour l'observation, qui possède déjà
ces empreintes et teste N figurines × M cibles à CHAQUE step : **41,7 µs/appel contre 4,5 µs** une
fois l'empreinte fournie (9,2×), soit 2,50 ms au lieu de 0,27 ms sur le pire cas réaliste — pour
une observation qui coûte 2,5 ms au total. La parade n'est PAS de recopier le prédicat côté
appelant (il divergerait sur la métrique, et l'obs annoncerait un volume d'attaques que le combat
ne produit pas) : c'est d'**extraire le cœur en une fonction qui accepte la donnée déjà mise en
forme**, et de faire de l'ancienne signature son wrapper. Un seul corps, deux points d'entrée.

**Un point de décision « le plus urgent » peut être INERTE dans le training réel (§0.41, 2026-07-28)**

Le point 0 de [§9.4](V11_phaseA.md#s9.4) (pseudo-décision `raw_action_int % len(options)` sur les rule-choices) porte
l'étiquette « le plus urgent » depuis le 2026-07-24. Vérification faite : **une seule** unité du
projet porte un rule-choice (`TyranidWarriorMelee`, `usage: "or"`, déclaré dans les rosters **TS**
— pas dans `config/unit_rules.json`, où le grep rend 0 et laisse croire à tort qu'il n'y en a
aucun), et **aucun** roster d'entraînement ArmageddonAgent n'est tyranide. Le code est donc vif en
PvE et dans `rule_checker`, jamais dans le training. **Avant d'ouvrir une tranche sur un point de
décision, vérifier qu'il est réellement atteint par les ROSTERS du training** — sans quoi on livre
un mécanisme jamais exercé, c'est-à-dire le motif §0.4 que ce document existe pour interdire.

**Un run qui passe ne prouve pas une non-régression sur un crash stochastique (§0.18)**

🔴 **Erreur commise le 2026-07-20, à ne pas refaire.** Un run de 500 épisodes a franchi
l'épisode ~250 sans le crash `collision intra-plan`, et on en a conclu — **par écrit, dans ce
document** — que la non-régression §0.11 était « validée en bout-en-bout ». Un **second run,
même commande**, a crashé à l'épisode ~280. Le crash dépend de la **trajectoire**, donc du
hasard : un run vert est un **échantillon de taille 1**, pas une preuve.

Règle : pour un crash dont le déclenchement dépend de la trajectoire, une non-régression se
prouve par un **test qui reproduit la condition**, ou à défaut par **plusieurs runs**, jamais
par un seul run vert. Et **tout changement de code qui touche l'observation ou le reward change
les trajectoires** — un run vert d'avant le changement ne dit rien du code d'après.

**L'ETA affichée au premier épisode est un artefact de warmup (§0.13)**

⚠️ **Piège de perf, à ne pas re-diagnostiquer** : l'ETA affichée au 1ᵉʳ épisode (~16 h 45 sur le
run de 1000) est un **artefact de warmup** ; elle retombe à sa vraie valeur dès le 10ᵉ épisode.
Ne jamais extrapoler une durée de run depuis les premiers épisodes.

**Ce que `x5_debug` ne produit PAS, et pourquoi il ne se lance pas seul (§0.10)**

**Piège de lancement, préexistant** : `--training-config x5_debug` **seul** échoue pour cet agent
(`No scenario file found … scenario_x5_debug.json`). ArmageddonAgent n'a que ses scénarios
`scenario_training_armageddonN.json` (`1` = terrain mc1, `2` = terrain mc2, dédoublés le
2026-08-08 ; aucun ne porte le nom d'un profil), donc `--scenario <chemin explicite>` est
**obligatoire** :
```
python3 ai/train.py --agent ArmageddonAgent --training-config x5_debug \
  --scenario config/agents/ArmageddonAgent/scenarios/training/scenario_training_armageddon1.json \
  --new --resolution 5
```
⚠️ `x5_debug` n'est **pas** un run de quelques minutes malgré son nom : **10 000 épisodes à 48
envs** au 2026-08-02. ⏳ **Seuls les profils `x1*` sont tenus à jour** (décision utilisateur du
2026-08-02) — relire le JSON avant de citer un chiffre d'un profil `x5*`.

⚠️ **La leçon durable** : un profil de debug peut, par ses seuls `callback_params`, ne rien
produire du tout — `save_best_min_episodes` et `checkpoint_save_freq` supérieurs (ou égaux) au
nombre d'épisodes du profil ⇒ **ni « best model » ni checkpoint**, sans le moindre message.
`model_gating_enabled: False` rend en outre le `Gate 🧱` de la barre de progression purement
décoratif. **Toujours confronter ces trois clés au `total_episodes` du profil avant de lancer**,
et ne pas prendre un run de validation de pipeline pour une mesure : il ne peut pas servir le
critère [§10.6](V11_eval_strategy.md#s10.6). (Valeurs constatées le 2026-08-02 sur `x5_debug` :
`total_episodes` 10 000, `save_best_min_episodes` 10 000, `checkpoint_save_freq` 10 000,
`bot_eval_final` 100.)

**Tout run `x5_debug` ÉCRASE le modèle canonique (§0.0)**

- ⚠️ **Le modèle en place a été ÉCRASÉ par ce run** (`model_ArmageddonAgent.zip`, 2026-07-20
  02:14 — autorisation utilisateur explicite). C'est donc un modèle **de debug, 100 épisodes
  `--new`**, sans valeur de jeu : `save_best_robust: false` fait que `train.py` écrit le modèle
  final en fin de run, aux deux sites gardés par `if not save_best_robust`.
  ⚠️ Tout run de debug ultérieur écrasera à nouveau le modèle canonique : **sauvegarder avant**
  si le modèle en place compte.

**`config/users.db` réapparaît modifié après chaque run (§0.0, dette 5)**

⚠️ `config/users.db` **réapparaît modifié** après chaque run d'entraînement — fichier
**protégé** (CLAUDE.md), ne JAMAIS l'inclure dans un commit.

**`bot_eval_scenario_pool` placé au mauvais niveau est silencieusement ignoré (§0.13)**

⚠️ **Piège latent, RÉSORBÉ — la leçon reste.** `bot_eval_scenario_pool` avait été placé à la
**racine** de `x5_debug`, alors que `_resolve_callback_value` (`ai/train.py`) le cherche dans
**`callback_params`** puis retombe sur `config/agents/_training_common.json` : la clé racine était
donc **ignorée**. Vérifié le 2026-08-02 : elle vit aujourd'hui dans `callback_params`. Mais toute
surcharge par agent placée à la racine reste **silencieusement sans effet** — c'est vrai de toutes
les clés lues par `_resolve_callback_value`, pas seulement de celle-ci.

**`agent_roster_seed` neutralise le tirage de roster sans le moindre message (§0.10)**

⚠️ **Piège latent voisin — `agent_roster_seed`.** Cette clé de scénario est passée en
`random_seed` au tirage du roster AGENT (`game_state.py`, lecture puis validation de
`agent_roster_seed`), et le RNG est reconstruit à chaque appel (`random.Random(random_seed)`). Si
elle est **renseignée**, le roster agent devient **identique à tous les épisodes** — le tirage est
neutralisé sans le moindre message.
🔴 **Correction du 2026-08-02** : ce document affirmait que les scénarios holdout `bot-01..04`
« la portent, pour la reproductibilité ». **C'est faux** : les quatre portent la clé **à `null`**,
donc le tirage y est **ACTIF**. Le seul scénario du dépôt qui la renseigne réellement est
`scenario_training_benchmark.json` (CoreAgent, `12345`). Les `scenario_training_armageddonN.json` ne
la portent pas. **À contrôler avant de conclure quoi que ce soit sur une distribution de matchups** —
et à ne pas déduire de la seule PRÉSENCE de la clé.

**Une suite de tests est une mesure GLOBALE, donc un verrou GLOBAL (§0.19.1, 2026-07-20)**

🔴 **Trois mesures de suite invalidées le même jour, par trois écrivains différents.** Le partage
du dépôt « par fichier » ne protège **rien** : deux agents peuvent éditer des fichiers disjoints
sans conflit, mais ils **ne peuvent pas mesurer en parallèle**, parce qu'une suite lit tout
l'arbre.

| # | Écrivain pendant la mesure | Conséquence |
|---|---|---|
| 1 | **moi-même** : baseline lancée pendant que je mutais 5 fichiers | tuée, non exploitée |
| 2 | **la chasse §0.18** : `shared_utils.py` à 20:14:31 et son test à 20:13:58 pendant une suite de 20:05→20:45 | un `EXIT=1` pris à tort pour un « rouge attendu permanent » |
| 3 | **l'agent concurrent** : `shared_utils.py` à 21:20:33 pendant une suite de 21:17:37→21:22:54 | un `EXIT=0` non exploitable |

**Règle.** Avant de conclure d'un résultat de suite, **relever le `mtime` des fichiers de
`engine/` avant ET après le run** ; tout fichier écrit dans la fenêtre invalide la mesure.
Une consigne « ne modifie pas tel fichier » donnée à un agent **ne suffit pas** si l'autre côté
y écrit : il faut soit interdire les suites complètes, soit geler les écritures pendant la
mesure. ⚠️ Corollaire : `EXIT=0` **et** `EXIT=1` sont également suspects — le n°2 a produit un
faux rouge, le n°3 un vert non fiable. Ne pas ne se méfier que des rouges.

⚠️ **Ne JAMAIS restaurer par `git checkout` un fichier portant du travail non commité d'un
autre agent** (`shared_utils.py`, `w40k_core.py` au 2026-07-20) : la restauration détruirait ses
modifications. Pour un mutation-test sur ces fichiers, sauvegarder par `cp` et restaurer par `cp`.

### Sur les données et les sources officielles


**🔒 Règle métier : `VALUE` suit le Munitorum, ce n'est pas une variable de tuning (§0.9)**

🔒 **RÈGLE MÉTIER (utilisateur, 2026-07-20) — NON NÉGOCIABLE.** `VALUE` **suit les documents
officiels**. Ce n'est pas une variable de tuning. `VALUE` est pourtant consommé **par figurine**
(bonus de kill pondéré par `model_value` dans `_squad_combat_shaping`,
`engine/reward_calculator.py` ; différentiel d'armée `value_alive`,
`engine/observation_builder.py`) : cet
effet sur l'apprentissage est une **conséquence à assumer**, jamais un motif pour s'écarter du
Munitorum. **Ne pas « rééquilibrer » ces valeurs pour améliorer un résultat d'entraînement.**

**Les PDF Munitorum ne sont pas extractibles en texte (§0.9)**

⚠️ **Le texte de ces PDF n'est pas extractible** (contenu en image : `extract_text()` ne rend que
les en-têtes). Il faut les **rendre en PNG** (`fitz`/pymupdf, dpi≥140) et les lire visuellement.
Ne pas conclure « le PDF est vide ».

**Deux pièges de lecture des sources : Grot Orderly, contradiction Gretchin (§0.9)**

**Deux pièges de lecture des sources, à ne pas re-trébucher dessus :**
1. **Le Grot Infirmier n'est pas une figurine de jeu.** Datasheet Painboy : `UNIT COMPOSITION :
   1 Painboy`, `equipped with : … 1 Grot Orderly` → c'est de l'**équipement**. D'où 38 figurines
   physiques dans la boîte mais **37 modèles de jeu**. Le roster n'a rien qui manque.
2. **Contradiction entre deux sources officielles sur les Gretchin** : le Munitorum cote
   `11 models … 45 pts`, la datasheet dit `UNIT COMPOSITION : 10 Gretchin`. La boîte en a 10.
   Retenu : 10 modèles à 45 pts. Non tranchable depuis les documents — signalé, pas masqué.

**Limite x10 et point non tranché du fix de collision (§0.11)**

**Non tranché** : je n'ai pas l'état exact au moment du crash. Il est prouvé que le prédicat est
aveugle au niveau et qu'il produit ce message sur une configuration légale ; il n'est **pas**
prouvé que les deux figurines de l'escouade 3 étaient à des étages différents plutôt que dans un
état déjà illégal. Si un crash de cette classe réapparaît, dumper l'état avant de conclure.

**Limite connue, HORS PÉRIMÈTRE (décision utilisateur, 2026-07-20) : le cas x10.** Le contrôle
compare les **sous-hex d'ancre**. Sur Board ×10 les figurines ont une **empreinte multi-hex**
(`compute_candidate_footprint` — « *For multi-hex units on x10 boards, computes the full
round/oval/square footprint* ») : deux
socles peuvent donc s'y chevaucher **sans partager leur ancre**, et la même classe d'incohérence
masque/exécution reste ouverte à cette résolution. Sur x5 (résolution du training) l'empreinte
vaut le sous-hex, le contrôle est **exact**. Limite préexistante, non introduite par le correctif.
⚠️ Ne pas lire « l'invariant est rétabli » comme valant pour toutes les résolutions : il vaut
pour x1 et x5. **On ne s'occupe pas de x10** — si le projet y vient un jour, rouvrir ce point
AVANT d'y lancer un entraînement.

### Affirmations périmées repérées le 2026-07-20 — **signalées, NON corrigées**

> Relevées pendant la réorganisation de §0. Aucune n'a été « nettoyée » : les corriger sans
> relire le code reproduirait exactement l'erreur qu'elles illustrent. **Vérifier avant de
> s'appuyer sur l'une d'elles.** C'est le motif récurrent n°1 de ce document — au moins
> 5 avaient déjà été trouvées lors des sessions précédentes.

| # | Où | Affirmation | Pourquoi elle est suspecte |
|---|---|---|---|
| 1 | §0.-1 | « la suite est VERTE : `1402 passed, 2 skipped` » | Son propre ⚠️ la déclare datée. Le document porte aussi `1407`, `1440`, `1451`, `1396`, `1398` selon l'endroit. Seul verdict fiable : le code de sortie. |
| 2 | [§5](V11_tranches.md#s5) / tableau T6-i | « ❌ test de non-régression **NON écrit** » | `tests/unit/engine/test_end_of_turn_coherency_03_03.py` **existe sur le disque** (vérifié le 2026-07-20) et §0.0 le déclare livré. |
| 3 | [§5](V11_tranches.md#s5) / tableau T6 | « le critère T6 est désormais bloqué par `CC_DMG` (§0.3) qui plante des épisodes d'évaluation » | Le portage §0.3 est fait et le run 60/60 de §0.7 le valide runtime. |
| 4 | [§10.5](V11_eval_strategy.md#s10.5) (bandeau) | « ⚠️ Non validé runtime — cf. §0.3 (`CC_DMG`) » | Levé par §0.7 (`TacticalBot` 10/10 épisodes). |
| 5 | §0.10 | « la dette notée en **§0.0** (`--scenario bot` échoue en amont du moteur) » | Cette dette est écrite dans **§0.7**, pas §0.0. Renvoi imprécis, non corrigé. |
| 6 | §0.12, étape 4 | « **9 tests** liés à `roster_pool_schedule` échouent indépendamment de ce travail » | ✅ **TRANCHÉ le 2026-07-20 — l'affirmation était FAUSSE.** Suite complète lancée : **1417 passed, 2 skipped, 0 failed**. Aucun échec `roster_pool_schedule`. §0.-1 avait raison : un test rouge est une régression, il n'y a pas d'échec préexistant à tolérer. |
| 7 | [§2](V11_tranches.md#s2) « État des lieux vérifié » | « Tous les imports du pipeline passent (`ai.train`, `ai.env_wrappers`, **`ai.multi_agent_trainer`**, **`ai.scenario_manager`**, …) » | `ai/multi_agent_trainer.py` **n'existe plus** (supprimé en §0.8, vérifié absent du disque le 2026-07-20) ; `ai/scenario_manager.py` non plus (supprimé le 2026-07-29, §0.45). Deux des modules cités comme preuve de santé du pipeline étaient du code mort. |
| 8 | §0.17 (par construction) | l'état de commit | Périmé dès le prochain `git commit` — l'entrée porte elle-même l'ordre de la reconfronter à `git status`. |
| 10 | §0.18, note annexe | « après ce crash le process … s'est terminé avec un **code de sortie 0** » | ❌ **FAUSSE, tranchée le 2026-07-20 — voir §0.20.** Le handler `return 1`, `sys.exit` propage, et l'exécution confirme `EXIT=1`. Cause probable : un pipe (`| tee`) côté shell lors de la mesure. Enseignement : une note **« hors périmètre »** échappe à la relecture *parce qu'*elle est marquée annexe. |
| 11-13 | [§6](V11_tranches.md#s6) (T2, T4), [§8.2](V11_tranches.md#s8.2) | layout d'actions « 41 », « 61 scénarios », `test_agent_interface_contract.py` | ➜ **détaillées en §0.19.1** (audit du 2026-07-20). Signalées, NON corrigées. ⚠️ **2026-08-02** : la n°11 a été « corrigée » une fois avec des chiffres qui sont à leur tour périmés — **ne plus citer de chiffre de layout d'action ici**, seul l'invariant « zéro littéral d'action dans `ai/` » compte, et il tient. La n°12 est aggravée : `scripts/sweep_scenario_bank_v11.py` **n'existe plus dans le dépôt** (il n'est donc plus seulement non exécutable). |
| 9 | §0.14 (rédigée puis **corrigée le même jour**) | « Non-régression §0.11 ✅ **VALIDÉE EN BOUT-EN-BOUT** » | ❌ **FAUSSE, retirée le 2026-07-20** — cf. §0.18 : le run suivant a crashé sur ce même message. Cas d'école : l'affirmation a été produite **par l'auteur du run lui-même**, le jour même, à partir d'un unique run vert. Le motif n°1 de ce document ne vient pas que du passé. |

---

