# [TODO] Macro Agent (Reference Unique)

> Ce document contient des recommandations et des cibles de design macro qui ne sont pas toutes garanties comme implémentees.
> Le statut "implémente aujourd'hui" est maintenant maintenu dans `Documentation/AI_TRAINING.md` (section "Macro Training Status").

## Objectif

Ce document est la reference unique pour le macro agent: architecture, mecanismes macro/micro, configuration, scenarios, entrainement, evaluation, tuning et bonnes pratiques.

**Documentation fonctionnelle** : tout ce qui définit **le comportement attendu** (intentions, criticité, rôle du macro, MCTS comme planification, objectifs produit) est regroupé **ici**. Le détail **technique d’implémentation** MCTS (API `GameAdapter`, hyperparamètres, JSON d’inférence, protocole de bench) vit dans **`Documentation/TODO/MCTS_agent_implementation.md`** jusqu’à ce que le code soit livré ; **ce fichier d’implémentation sera supprimé** une fois la fonctionnalité mergée (la vérité devient le code + tests + specs alignées).

Il remplace et complete:
- `Documentation/meta_controller.md`
- `Documentation/macro_micro_load.md`

---

## 1) Vue d'ensemble

Le projet supporte deux niveaux de decision:
- **Micro**: selection d'action tactique d'une unite (move/shoot/charge/fight/wait) via modeles PPO specialises.
- **Macro**: orchestration de l'ordre/unite/intention strategique, puis delegation au micro.

Implementation actuelle:
- Wrapper principal: `ai/macro_training_env.py` (`MacroTrainingWrapper`, `MacroVsBotWrapper`).
- Entrainement/evaluation: `ai/train.py`.
- Scenarios macro actuels: `config/agents/MacroController/scenarios/*.json`.
- Config macro: `config/agents/MacroController/MacroController_training_config.json`.

**Cible d’architecture** : le **macro** est le niveau où s’applique la **recherche arborescente (MCTS)** guidée par une **policy** et une **value** PPO (prior sur les actions macro légales, valeur de feuille) ; le **micro** reste des **forwards PPO** tactiques par activation. Voir **§2.7** pour la spécification fonctionnelle complète de cette pile.

---

## 2) Architecture macro/micro

### 2.1 Flux de decision

1. Le macro observe l'etat global (tour, phase, objectifs, unites, eligibilite).
2. Le macro choisit une action macro.
3. Cette action est decodee en:
   - unite ciblee,
   - intention (`intent_id`),
   - detail de l'intention (`detail_index`).
4. Le wrapper priorise l'unite dans le pool d'activation.
5. Le micro-modele de cette unite est charge et predit l'action micro.
6. L'environnement execute l'action micro.

### 2.2 Action space macro (etat actuel)

Action discrète encodee comme:
- `Discrete(max_units * INTENT_COUNT * detail_max)`

Avec:
- `max_units`: borne haute (`macro_max_units` dans training config)
- `INTENT_COUNT`: nombre d'intentions macro (voir `engine/macro_intents.py`)
- `detail_max`: max entre slots unites et slots objectifs.

### 2.3 Observation macro (etat actuel)

Observation vectorielle fixe:
- features globales (tour, phase, joueur, objectifs controles, diff valeur armee)
- bloc unites (features par unite, padde a `max_units`)
- bloc objectifs (features par objectif, padde a `max_objectives`)

Points stricts:
- `max_units` doit couvrir le pire scenario.
- `max_objectives` derive des scenarios.
- incoherence de taille => erreur explicite.

### 2.4 Interaction avec les micro modeles

Le wrapper charge les modeles micro **requis par les unites presentes dans les scenarios**:
- chemin attendu: `ai/models/<model_key>/model_<model_key>.zip`
- chargement fail-fast si un modele manque.

Le `model_key` est derive via `UnitRegistry`:
- classification par type de deplacement, tanking, cible, role
- methode: `UnitRegistry.get_model_key(unit_type)`.

### 2.5 Intentions macro : encodage, cibles moteur, succes (evaluation)

Source de verite des identifiants : `engine/macro_intents.py` (`INTENT_COUNT = 5`).  
Les champs `game_state` ci-dessous sont poses par `MacroTrainingWrapper._set_macro_intent_target` (et equivalent PvE dans `engine/pve_controller.py`).

**Statut des criteres de succes / score partiel / horizon** : specification **pour evaluation offline** (bench, logging, futur shaping). **Aucune garantie** qu’ils existent tels quels comme termes dans la config de rewards — a valider contre `engine/` et les regles VP.

#### Tableau par intention

| `intent_id` | Nom (`INTENT_NAMES`) | `detail` pointe vers | Apres decode, cible principale dans `game_state` |
|-------------|----------------------|----------------------|-----------------------------------------------|
| 0 | `take_objective` | index d’**objectif** (liste `objectives`) | `macro_target_objective_id`, `macro_target_objective_index` |
| 1 | `hold_objective` | index d’**objectif** | idem |
| 2 | `focus_kill` | index dans `enemy_ids` (unite ennemie) | `macro_target_unit_id` = id ennemi |
| 3 | `screen` | index dans `ally_ids` (unite alliee a couvrir / screen) | `macro_target_unit_id` = id allie |
| 4 | `attrition` | **non libre** : `detail_index` **force** = `attrition_objective_index` du scenario | meme structure qu’objectif : zone / objectif d’attrition |

#### Succes operationnel et signaux de reward (spec cible — a valider moteur / rewards)

Les **predicats** ci-dessous doivent utiliser les **memes** definitions que le moteur pour **controle d’objectif**, **PV**, **mort** (`units_cache` / regles VP). Les **cles numeriques** (`reward_*`) sont des **noms logiques** : les lier aux champs **nommes** du fichier de rewards associe a l’agent (chaine depuis `*_training_config.json`), **sans valeur inventee**.

##### `take_objective` (detail = index d’objectif `i`)

- **Signal binaire (evaluation / flag succes)** : `1` si le joueur **controle** l’objectif `i` selon la **regle de controle** du moteur (VP / hexes), `0` sinon.

##### `hold_objective` (detail = `i`)

- **Meme predicat binaire** que `take_objective` a l’instant d’evaluation : `1` si controle, `0` sinon.  
- **Evolution possible** (hors scope minimal) : succes = controle **maintenu** sur une fenetre de **N** pas / tours — a specifier si tu separes `hold` de `take` en prod.

##### `focus_kill` (detail = index dans `enemy_ids`)

- **Cible** : au minimum l’unite ennemie `E = enemy_ids[detail_index]` (etendre a un **ensemble** d’indices si la spec macro le permet plus tard).
- **Signal de reward graduel (proposition)** : a deux instants (reference debut d’ordre / fenetre vs courant), calculer une **masse** sur les unites concernees, ex. somme des **valeur de modele × (HP courant / HP max)** ou somme des **valeur de modele** ponderee par les PV restants — **une seule** formule fixee en config. Soit `M_debut` et `M_maintenant`. La **proportion abattue** est `p = (M_debut - M_maintenant) / max(M_debut, eps)`. La **recompense** = `p × reward_focus_kill_base` ou `p ×` une constante **nommee** dans la config rewards (ex. alignement sur les blocs definis pour `CoreAgent` / agent macro), **pas** un nombre magique dans le code.
- **Clarification** : tu es coherent — il s’agit d’un **shaping** proportionnel a la **valeur armee enlevee** sur la cible (ou le groupe indexe), pas seulement d’un booleen « mort ».

##### `screen` (detail = index dans `ally_ids`)

- **Cible** : allie `A = ally_ids[detail_index]`.
- **Signal (formule inverse de `focus_kill` sur les pertes subies)** : mesurer la **baisse** de la meme masse `M` (ex. valeur × fraction PV) sur **A** entre reference et courant ; `p_dommage = (M_debut - M_maintenant) / max(M_debut, eps)`. **Recompense** = `(1 - p_dommage) × reward_screen_base` (si **aucune** perte sur A, `p_dommage = 0` → **100 %** du coefficient de reward configure). Constantes **nommees** en config rewards.

##### `attrition` (zone = `attrition_objective_index` du scenario)

- **Qu’est-ce que la « cible » ?** : ce n’est pas un rayon libre en hex : l’index pointe vers un **objectif** dans `objectives` du scenario. La **zone** = l’ensemble des **hexes** (et regles de controle) definis pour cet objectif dans le moteur — **taille et forme** viennent du **scenario**, pas d’un parametre separe « taille d’attrition ».
- **But tactique (attrition classique)** : maximiser la **valeur** enlevee aux unites **adverses** qui sont **dans / engagees sur** cette zone (ou selon une regle explicite : degats infliges **depuis** la zone, **vers** des unites dans la zone, etc.). Le signal de reward est typiquement une **somme** de valeur abattue (ou degats normalises) sur la fenetre, avec **seuils** et coefficients **nommes** en config — a calibrer comme pour `focus_kill`.

#### Definition proposee : succes / partiel / horizon (synthese)

| Intention | Signal principal (resume) |
|-----------|---------------------------|
| `take_objective` | Binaire : controle objectif `i` oui/non |
| `hold_objective` | Idem `take` a l’instant T ; variante temporelle optionnelle |
| `focus_kill` | Graduel : proportion de masse valeur/HP enlevee sur la (les) cible(s) |
| `screen` | Graduel : `(1 - proportion de perte subie)` sur l’allie |
| `attrition` | Graduel : valeur (ou degats) adverses lies a la **zone objectif** d’index fixe |

#### 2.5.2 Masse VALUE×HP, recompenses agregees, gate resultat, obs v2.6

Cette sous-section **fixe les notations** communes au **shaping** (rewards) et aux **deux scalaires** documentes dans `Documentation/AI_OBSERVATION.md` (indices `[355:357]`, spec v2.6). Toutes les constantes (`eta`, `eps`, `alpha`, `beta`, `tau`, plafonds de normalisation) sont des **cles nommees** en config rewards / `observation_params` — **aucune** valeur magique dans le moteur.

##### Ensembles et reference temporelle

- **`U`** : ensemble d’unites **concernées** par l’ordre macro courant (selon `intent_id` / `detail_index`). Pour **`attrition`**, `U` est la liste des ennemis **dans la zone** de `attrition_objective_index`, **figée au debut du tour** (ou au debut de l’ordre — **une seule** convention nommée en config) pour éviter qu’un ennemi qui **entre** dans la zone en cours de tour ne dilue artificiellement la proportion `p`.
- **`M_ref`** : valeur de `M` (ou `M^W`) a l’instant de reference (**debut d’ordre** ou **debut de tour** — aligné sur la spec rewards).
- **`M_now`** : meme somme a l’instant courant du pas de reward.

##### Masse brute et masse ponderee

**Masse brute** (alignée sur l’intuition « valeur armee restante » sur le pool designé) :

\[
M = \sum_{i \in U} \mathrm{VALUE}_i \cdot \mathrm{HP\_CUR}_i
\]

**Masse ponderee** (priorise les cibles « faciles a convertir » via une menace / probabilite de kill agregee) : pour chaque \(i \in U\), soit \(\psi_i\) un scalaire derive de `best_kill_probability` (ou équivalent **deja** dans l’obs / le cache arme — **borne** et definition **nommees**). Avec \(\eta \geq 0\) **nomme** :

\[
W_i = \mathrm{VALUE}_i \cdot (1 + \eta \psi_i), \qquad
M^W = \sum_{i \in U} W_i \cdot \mathrm{HP\_CUR}_i
\]

##### Proportion abattue et termes de reward (symboles)

- **Attrition / focus** (forme type) : \(r_A = p = \dfrac{M_{\text{ref}} - M_{\text{now}}}{\max(M_{\text{ref}}, \varepsilon)}\) avec \(\varepsilon\) **nomme** (evite division par zero ; pas de valeur implicite).
- **Terme complementaire** (ex. screen / preservation) : meme logique avec la masse sur l’allie ou autre pool — toujours **une** formule **fixee** en config par intention.

##### Gate resultat / anti-farming (forme illustrative)

Pour éviter d’optimiser une **metrique locale** sans **alignement** victoire / VP, on peut combiner un signal d’**agregat** \(r_A\) avec un signal de **resultat** \(r_B\) (ΔVP, victoire, objectif) et la **criticité** \(c\) (§2.6) :

\[
r_C = \alpha \, r_B + \beta \cdot c \cdot \min\!\left(1,\, \frac{r_A}{\tau}\right)
\]

Ici \(\alpha,\beta,\tau\) sont des **poids / seuils nommes** ; variante équivalente permise si documentée. **Intérêt** : le terme \(\min(1, r_A/\tau)\) **sature** l’incitation a « farmer » des degats marginaux une fois la masse locale suffisamment réduite.

##### Observation v2.6 : redondance utile

Les scalaires `strategic_pool_mass_norm` et `strategic_pool_weighted_norm` encodent \(M\) et \(M^W\) **normalises** (voir `AI_OBSERVATION.md` §10). **Motivation** : **accélération** d’apprentissage et **stabilité** (moins de recomposition non linéaire côté réseau) ; **coût** : couplage conceptuel reward/obs et maintenance d’un **helper** partagé.

##### Exemple numerique fictif (illustration des formules)

Hypothèse : `focus_kill` sur un **groupe** \(U = \{A,B,C\}\) avec \(\mathrm{VALUE}\times\mathrm{HP\_CUR}\) au **ref** :

| Unite | VALUE | HP_CUR (ref) | contribution a \(M_{\text{ref}}\) |
|-------|-------|--------------|-----------------------------------|
| A (gros) | 100 | 2 | 200 |
| B (moyen) | 50 | 4 | 200 |
| C (chaff) | 10 | 10 | 100 |
| **Total** | | | **\(M_{\text{ref}} = 500\)** |

**État courant** : A détruit, B à 2 PV restants (HP_CUR=2), C intact (10). Contributions : A=0, B=\(50\times2=100\), C=\(10\times10=100\) → \(M_{\text{now}} = 200\).

\[
p = \frac{500 - 200}{\max(500,\varepsilon)} = 0{,}6
\]

Le **chaff** C pèse **100** sur 500 au ref (20 % de la masse) : une politique qui ne tape que C peut montrer un \(p\) modéré **sans** réduire la menace principale — d’où l’intérêt de \(M^W\) (si \(\psi\) est plus élevé sur A/B) ou de **multi-cibles** / limites en code documentées ailleurs.

**Weighted (illustratif)** : supposons \(\eta=1\), \(\psi_A=0{,}5\), \(\psi_B=0{,}3\), \(\psi_C=0{,}1\) (fictif). Alors \(W_A=100\times1{,}5=150\), \(W_B=50\times1{,}3=65\), \(W_C=10\times1{,}1=11\). Au ref : \(M^W_{\text{ref}} = 150\times2 + 65\times4 + 11\times10 = 300 + 260 + 110 = 670\). Les poids relatifs **shiftent** la priorité vers A par rapport à l’exemple brut ci-dessus.

#### Score d’execution micro (forme recommandee)

Pour comparer des policies micro sur le **meme** ordre macro, une forme utile est :

\[
\text{score} = \alpha \, \mathbf{1}_{\text{succes}} + (1-\alpha) \, s_{\text{partiel}} - \beta \, f(\text{pas micro}, \text{tours})
\]

- \(s_{\text{partiel}} \in [0,1]\) selon la ligne du tableau (distance, degats, controle partiel).
- \(f\) : penalite croissante avec le nombre d’**activations** ou de **tours** avant succes (eviter l’abus du WAIT si mal calibre).
- \(\alpha, \beta\) : **constants nommees en config** de benchmark, pas des valeurs implicites.

**Alternative simple** (alignee sur ton idee) : `100%` si succes dans la fenetre, sinon `partiel * (1 - ratio depassement / plafond)` avec plafond d’actions explicite.

### 2.6 Criticité / urgence (\(c\)) et pénalité de pertes (micro)

**Nom** : preferer **criticité** ou **urgence** dans la doc et la config — eviter le terme **temperature** (confusion avec le softmax).

**Role** : \(c \in [0{,}1]\) indique **combien** l’ordre autorise de **sacrifier les PV** pour la mission. Il doit etre **present dans l’observation** du micro (comme les intents) pour que la policy puisse s’y conditionner.

**Qui choisit `c`** : uniquement le **macro** (pas le micro). En **configuration cible**, le macro est **MCTS** (recherche + prior/value) ; `c` est émis **avec** l’ordre (unité, intent, detail) — ou produit par une **règle déterministe** `c = f(intent, scenario)` **une seule** politique documentée.

#### Garde-fou sur \(c\)

- **Contrainte** : \(c \geq 0{,}1\) (**pas** de valeur nulle).  
- **Raison** : eviter un regime ou la mission domine **sans aucune** prise en compte des pertes (comportements suicidaires cote reward). Avec un plancher, le coefficient \((1-c)\) sur la pénalité de pertes ne depasse jamais **0,9** : il reste toujours une partie de la pénalité HP active au regime le plus « mission-first » compatible (\(c = 0{,}1\)).  
- **Implementation** : validation **fail-fast** si \(c < 0{,}1\) (ou clamp **documente** explicitement — preferer l’erreur si les regles projet l’imposent).

#### Portee des pertes

- Uniquement l’**unite activee sous l’ordre macro** (celle a laquelle s’applique l’intention / le pilotage micro courant).

#### Pénalité « de base » sur les pertes de PV (proposition)

1. Definir une **pénalité de base** (constante nommee en config rewards, pas de magic number inline).  
2. **Reference HP — phrase canonique (implémentation / reprise par un LLM)** :

   > A la **fin** de chaque **activation** d’une unité, enregistrer un snapshot `hp_end_activation[unit_id]` = `HP_CUR` lu depuis la **source de vérité** des PV en jeu. Au **premier pas de reward** de l’**activation suivante** de cette même unité, la perte de PV utilisée pour le terme de pénalité est la différence entre ce snapshot et le `HP_CUR` courant (même source), exprimée en **fraction des PV max** de l’unité. **Première activation** de la partie pour cette unité : utiliser `HP_MAX` (ou un snapshot unique post-deploiement — **une seule** règle, documentée). Ne pas compter deux fois la même perte entre deux snapshots.

3. Chaque pas de reward retenu, calculer le **pourcentage de PV max perdus** sur cette fenetre (ou la variation depuis le snapshot selon la spec retenue), multiplier par la pénalité de base, puis par **\((1-c)\)** :

\[
\text{pénalité}_{\text{PV}} = (\%\,\text{PV perdus}) \times P_{\text{base}} \times (1 - c)
\]

- \(c = 1\) : **aucune** pénalité sur ces pertes pour la resolution de l’objectif (rush maximal autorise par le signal).  
- \(c = 0{,}1\) : **90 %** de la pénalité « pleine » sur le terme HP (garde-fou : jamais 100 % du coefficient sur \((1-c)\), par construction du plancher sur \(c\)).

#### Interaction avec les autres rewards

- **Macro** : conserver les recompenses actuelles (prises d’objectifs, kills, etc.).  
- **Micro** : cette pénalité **complete** les signaux existants (ex. anti-WAIT, remplissage d’objectif) : seuls WAIT + objectif **ne suffisent pas** toujours a motiver la survie ; le terme \((1-c) \times\) pertes PV cible explicitement la **preservation** quand \(c\) est bas.  
- **Positionnement** : possibilite d’ajouter des termes par **type d’action** et modulations (ex. pénalité par hex de distance a l’hex cible) — **spec separee**, a calibrer pour eviter l’exploitabilité.

#### Statut

Spec **cible** pour implementation ; champs obs (`c`), hooks HP et constantes doivent etre **verifies** dans `engine/` et la config de rewards avant de considerer le comportement comme garanti.

### 2.7 MCTS comme moteur de decision macro (specification fonctionnelle)

Cette section decrit **ce que** le systeme doit faire du point de vue **produit / comportement**, pas les modules Python ni les formules d’implementation (voir `MCTS_agent_implementation.md` jusqu’a suppression post-livraison).

#### 2.7.1 Limite d’un reseau seul pour le macro

Un forward PPO sur l’action macro produit une **distribution** et une **valeur** ; ce n’est pas un **plan explicite** sur plusieurs enchainements de decisions. Contre un adversaire qui sort de la distribution d’entrainement, une politique greedy ou echantillonnee reste souvent exploitable. **MCTS** apporte un **lookahead** en explorant des **suites** d’actions macro sous budget (simulations / temps).

#### 2.7.2 Roles de la policy et de la value PPO dans la recherche

- **Policy** : sert de **prior** sur les actions macro **legales** (masque) pour orienter l’exploration (ne pas confondre avec une coupe arbitraire : toutes les actions legales restent atteignables).
- **Value (critic)** : sert d’**evaluateur de feuille** (seul ou melange avec rollout / fin de partie selon spec technique).

Sans policy/value **assez bonnes**, MCTS ne compense pas tout ; sans **budget** temps / simulations, pas de niveau « tournoi » garanti.

#### 2.7.3 Flux fonctionnel a l’inference (vue produit)

```
Etat de jeu -> observation (meme pipeline qu’a l’entrainement)
    -> policy PPO (prior) + value PPO (feuille)
    -> MCTS sur clones (pas sur l’etat live)
    -> action macro choisie a la racine (ex. max visites)
    -> apply une fois sur l’etat reel
    -> micro PPO execute l’activation comme aujourd’hui
```

**Invariant fonctionnel** : les simulations ne **mutent jamais** l’etat de partie « live » ; uniquement des **clones** jetes apres la decision.

#### 2.7.4 Grain de la recherche : MCTS « macro » vs « micro »

| Mode | Sens | Cout typique |
|------|------|----------------|
| **MCTS au grain macro** | Arbre sur les **decisions d’orchestration** (unite, intention, detail) a **faible cardinalite** ; entre deux nœuds, **micro PPO** sans arbre. | Latence moderee si les nœuds sont rares. |
| **MCTS au grain micro** | Arbre a **chaque** pas tactique type CoreAgent ; branching enorme. | Tres couteux ; plutot bench ou budgets extremes. |

En pratique, la cible **produit** est en general **MCTS macro + PPO micro** entre les nœuds.

#### 2.7.5 Objectifs d’evaluation (fonctionnels)

- **Winrate** contre bots de reference et **holdout** ; objectif long terme **winrate contre humain** sous **temps par coup** borne.
- Comparer **systematiquement** a une **baseline** : meme checkpoint, **sans** MCTS (forward macro seul), meme observations et masques.

#### 2.7.6 Besoin produit : activer / desactiver MCTS (A/B)

- Pouvoir basculer **MCTS on/off** via la config agent (ex. bloc `inference.mcts.enabled` dans `*_training_config.json`) pour **benchmarks** equitables : **meme** modele, seul le chemin de decision macro change.
- Tant que le code n’est pas branche, le flag ne peut qu’**echouer explicitement** ou etre ignore — pas de fallback silencieux.

#### 2.7.7 Entrainement : nourrir policy/value utiles comme prior / feuille

Une policy/value **utiles** pour MCTS viennent d’un entrainement **diversifie** (scenarios, adversaires, self-play — voir `Documentation/AI_TRAINING.md`). Option future : distillation depuis parties MCTS plus lourdes.

#### 2.7.8 Hors perimetre fonctionnel (documente ailleurs)

- MCTS comme **adversaire d’entrainement** uniquement : `Documentation/MCTS_bot2.md`, `Documentation/MCTS_bot.md`.

#### 2.7.9 Documentation d’implementation (temporaire)

Le detail **technique** (contrat `GameAdapter`, `c_puct`, budgets, JSON, protocole de tuning, metriques internes latence/visites) est dans **`Documentation/TODO/MCTS_agent_implementation.md`**. Ce fichier est **provisoire** : **suppression prevue** apres implementation et validation, pour eviter la duplication avec le code.

---

## 3) Modes macro cotes app/PvE

Fichiers:
- `config/agents/MacroController/pve_macro_controller_app.json`
- `config/agents/MacroController/pve_macro_controller.json`

Modes:
- `micro_only`: pas de pilotage macro (pipeline micro seulement)
- `macro_micro`: macro actif + delegation micro

Recommandation:
- production stable: `macro_micro` uniquement quand micro est solide et scenarios macro valides.

---

## 4) Scenarios macro: regles de conception

## 4.1 Regles minimales obligatoires

Chaque scenario doit avoir:
- `units` valide (ids uniques, positions valides, unit_type connu)
- `objectives` non vide
- `primary_objectives` explicite
- cohérence de roster et budget

Interdits:
- ids dupliques
- unit_type absent du registry
- incoherence volontaire "cassee" pour forcer un comportement
- fallback silencieux en cas de donnees manquantes

## 4.2 Etat actuel du repository

Le dossier `config/agents/MacroController/scenarios/` contient 5 scenarios `default-*`.

Constats:
- couverture partielle seulement (pas encore de split `training/holdout` propre pour macro).
- variation de roster presente, mais pool reduit.
- au moins une anomalie de qualite detectee: id duplique dans `MacroController_scenario_default-3.json`.

Conclusion:
- base exploitable pour prototype, insuffisante pour robustesse macro long terme.

## 4.3 Cible recommandee (efficacite + solidite)

Par macro-agent:
- **training**: 12 a 20 scenarios
- **holdout**: 6 a 10 scenarios

Etager la complexite:
- petit roster: 8-10 unites
- moyen roster: 12-16 unites
- dense roster: 18-22 unites

Varier:
- topologie (ouvert/contraint)
- densite de murs
- placements
- asymetrie de valeurs
- repartition types d'unites

---

## 5) Strategie de modelisation recommandee

## 5.1 Un macro-agent par armee (recommande)

Oui: preferer **un macro par armee**.

Pourquoi:
- regles et profils differents par armee
- convergence plus rapide
- debug plus simple
- moins de non-stationnarite

## 5.2 Faut-il entrainer "chaque unite"?

Non.

Il faut couvrir:
- les **roles tactiques** (swarm/troop/elite, melee/ranged)
- les **regles speciales structurantes**
- les **interactions de compo**

Pas necessaire d'avoir 1 scenario par datasheet.

## 5.3 Macro vs micro: ordre d'entrainement

Ordre recommande:
1. stabiliser micro (modeles figes)
2. entrainer macro avec micros figes
3. eventuellement fine-tune micro ensuite, puis re-stabiliser macro

A eviter au debut:
- co-training macro+micro simultane (instable, bruit de cible trop fort).

---

## 6) Configuration macro

Fichier principal:
- `config/agents/MacroController/MacroController_training_config.json`

Champs macro specifiques:
- `macro_player` (1 ou 2)
- `macro_max_units` (borne stricte du nombre d'unites)

Champs PPO importants:
- `n_envs`
- `model_params.n_steps`
- `model_params.batch_size`
- `model_params.learning_rate`
- `model_params.clip_range`
- `model_params.ent_coef`
- `model_params.target_kl`
- `total_episodes`

Evaluation bots:
- `callback_params.bot_eval_freq`
- `callback_params.bot_eval_intermediate`
- `callback_params.bot_eval_final`
- `callback_params.save_best_robust`
- `callback_params.robust_window`
- `callback_params.robust_drawdown_penalty`
- `callback_params.model_gating_enabled`
- `callback_params.model_gating_min_combined`
- `callback_params.model_gating_min_worst_bot`
- `callback_params.model_gating_min_worst_scenario_combined`

Holdout split (si utilise):
- `callback_params.holdout_regular_scenarios`
- `callback_params.holdout_hard_scenarios`

---

## 7) Lancement train/eval macro

## 7.1 Entrainement macro

Exemple:
```bash
python ai/train.py \
  --agent MacroController \
  --training-config default \
  --rewards-config MacroController \
  --scenario all \
  --new
```

Notes:
- `--scenario all` active la rotation des scenarios trouves.
- en macro, `self/bot` ne sont pas des modes de scenario train valides.

## 7.2 Evaluation macro

Deux modes:
- `--macro-eval-mode micro`: macro vs pipeline micro
- `--macro-eval-mode bot`: macro vs bots d'evaluation

Exemple:
```bash
python ai/train.py \
  --agent MacroController \
  --training-config default \
  --rewards-config MacroController \
  --test-only \
  --scenario default-0 \
  --macro-eval-mode bot \
  --test-episodes 100
```

---

## 8) Tuning PPO macro (pratique)

## 8.1 Regles simples

- commencer simple, augmenter la complexite des scenarios ensuite
- garder `n_steps * n_envs` stable entre runs comparatifs
- ne changer que 1-2 hyperparametres a la fois
- selectionner par score robuste (pas par pic unique)

## 8.2 Plage de depart conseillée

Pour macro:
- `n_envs`: 16 a 48 selon CPU
- `n_steps` (base globale): 8k a 16k (ajustement interne par env possible)
- `batch_size`: 2k a 4k
- `learning_rate`: 2e-4 -> 6e-5 (schedule)
- `clip_range`: 0.10 a 0.15
- `ent_coef`: 0.04 -> 0.02 (schedule)
- `target_kl`: 0.008 a 0.02

## 8.3 Signaux d'alerte

- winrate training monte, holdout baisse => overfit scenarios train
- fort ecart Random vs Greedy/Defensive => policy fragile
- oscillations fortes score combine => instabilite, revoir LR/ent_coef/variete scenarios
- duree episode explose => scenarios trop lourds ou politique indecise

---

## 9) Metriques a suivre (minimum)

Training:
- progression episodes
- duree/throughput
- clip_fraction
- explained_variance
- entropy_loss
- gradient_norm

Evaluation:
- winrate par bot
- score combine
- score par scenario
- split holdout regular/hard
- worst-bot-score

Decision de validation:
- gate sur holdout (pas training)
- gate multi-bot
- gate robustesse temporelle (fenetre glissante)
- gate de promotion modele (seuils explicites, sinon promotion bloquee)

Comportement concret du gating de promotion (implante):
- evaluation PASS seulement si:
  - `combined >= model_gating_min_combined`
  - `worst_bot_score >= model_gating_min_worst_bot`
  - `worst_scenario_combined >= model_gating_min_worst_scenario_combined`
- si FAIL:
  - pas de promotion `best_model`
  - pas de promotion robust vers le modele canonique
  - logs explicites `PASS/FAIL` + detail des criteres

---

## 10) Simulation de charge macro/micro

Script:
- `scripts/macro_micro_load.py`

Objectif:
- simuler une charge macro/micro
- mesurer CPU/RAM/IO/reseau
- obtenir un debit steps/sec

Exemple:
```bash
python scripts/macro_micro_load.py \
  --scenario-file config/agents/MacroController/scenarios/MacroController_scenario_default-0.json \
  --controlled-agent MacroController \
  --training-config default \
  --rewards-config MacroController \
  --episodes 20 \
  --macro-player 1 \
  --macro-every-steps 5
```

Usage recommande:
- smoke test avant long run
- comparaison de perf avant/apres changement architecture/scenarios

---

## 11) Qualite des donnees scenarios (checklist stricte)

Avant un run macro:
- ids unites uniques
- unit_type existants dans `config/unit_registry.json`
- objectifs et primary_objectives presents
- pas de position invalide
- split train/holdout coherent
- couverture des roles tactiques ciblee
- budget et densite unites documentes

Commande recommandee (pipeline qualite):
```bash
python ai/hidden_action_finder.py
python scripts/check_ai_rules.py
python ai/analyzer.py step.log
```

---

## 12) Plan de mise en place robuste (recommande)

1. **Nettoyer** les scenarios macro existants (qualite data, ids, coherence).
2. **Structurer** macro en `scenarios/training` + `scenarios/holdout`.
3. **Creer 1 macro-agent par armee**.
4. **Fixer les micros** avant macro.
5. **Entrainer par curriculum de complexite roster**.
6. **Valider sur holdout + bots ponderes**.
7. **Deployer en `macro_micro`** seulement apres gate robuste.

---

## 13) Points de verite (code)

- Macro wrapper: `ai/macro_training_env.py`
- Entrainement/eval: `ai/train.py`
- Utils scenarios: `ai/training_utils.py`
- Eval bots: `ai/bot_evaluation.py`
- Callbacks/robust selection: `ai/training_callbacks.py`
- Registry unites/model_keys: `ai/unit_registry.py`
- Config macro: `config/agents/MacroController/*.json`

---

## 14) Decisions d'architecture recommandees

- **Oui**: un macro par armee
- **Oui**: scenarios representatifs des roles, pas exhaustivite datasheet
- **Oui**: micro stable puis macro
- **Non**: fallback silencieux
- **Non**: co-training macro+micro des le debut
- **Non**: evaluation uniquement sur scenarios train

Ce cadre maximise la probabilite d'obtenir une policy macro a la fois efficace, stable et maintenable.
