# Endless Duty - Specification V1

## 1) Vision

`Endless Duty` est un mode survie orienté high score.
Le joueur contrôle une escouade Space Marines et affronte des vagues Tyranides de plus en plus dangereuses.

Objectif principal: tenir le plus grand nombre de vagues possible.

## 2) Core Loop

1. Lancer une vague Tyranide.
2. Résoudre le combat sur la carte.
3. Fin de vague: attribuer des points.
4. Ouvrir la boutique inter-vague.
5. Recommencer avec une vague plus difficile.

## 3) Roster Rules (Hard Constraints)

- Escouade limitee a 3 slots maximum.
- Composition imposee:
  - Slot 1: `Leader` (unique) - seule unite autorisee a prendre un grade eleve (Sergent/Capitaine).
  - Slot 2: `Melee` - acces uniquement aux unites orientees corps a corps.
  - Slot 3: `Heavy/Special` - acces uniquement aux unites a armes lourdes/speciales.
- Le Leader est l'avatar principal du joueur.

Configuration de depart V1:
- Le joueur commence avec 2 unites:
  - `Leader`: Intercessor (obligatoire)
  - `Slot 2`: unite de base melee (configuration par defaut) ou selection initiale simple
- `Slot 3` est verrouille au debut et doit etre debloque en boutique.

## 4) Progression Economy

Les achats ne sont possibles qu'entre les vagues.

Le joueur depense ses points librement (pas de limite fixe du type "1 upgrade max par vague").

Recompense en points (fin de vague):
- `points_vague = 6 + floor(vague * 1.5)`
- Bonus no-consumable: `+3` si aucun consommable n'a ete utilise sur la vague.
- Bonus perfect defense: `+2` si objectif non conteste en fin de vague.

Exemples:
- Vague 1: `7` points base
- Vague 5: `13` points base
- Vague 10: `21` points base

Categories d'achat:

1. Ajouter une figurine dans l'escouade (dans la limite des 3 slots).
2. Changer le modele d'une unite (ex: Intercessor -> Aggressor, ou Intercessor -> Intercessor Sergeant selon slot).
3. Acheter des variantes d'armes deja presentes dans le jeu.
4. Acheter des consommables (stimpacks/buffs temporaires).

Pricing V1 (chiffres cibles):
- Debloquer `Slot 3`: `18` points
- Upgrade `Leader` vers Sergent: `12` points
- Upgrade `Leader` vers Capitaine: `24` points (Sergent prerequis)
- Upgrade modele `Melee`: `10` a `16` points selon unite cible
- Upgrade modele `Heavy/Special`: `12` a `18` points selon unite cible
- Variante arme standard: `6` points
- Variante arme specialisee/lourde: `9` points

Principe d'immersion:
- Uniquement des unites, armes et variantes existantes dans le roster du jeu.
- Aucun combo attribut/arme "hors catalogue".

## 5) Consumables (Stimpacks/Buffs)

Objectif: fournir des outils de clutch sans remplacer la progression permanente.

Regles V1:
- Disponibles uniquement en boutique inter-vague.
- Quantite limitee (stock cap par type = `2`).
- Cout qui augmente avec les achats repetes dans une meme run.
- Effets temporaires uniquement (pas de bonus permanents).
- Limite d'utilisation en combat: `3` consommables max par vague (tous types confondus).

Liste V1 recommandee:
- `Med Stim` (soin leger sur une unite): cout base `5`
- `Adrenal Stim` (+mobilite temporaire): cout base `4`
- `Targeter Stim` (+precision tir temporaire): cout base `4`
- `Armor Stim` (+resistance temporaire): cout base `5`

Escalade de prix par type dans une run:
- 1er achat: `x1.0`
- 2eme achat: `x1.5`
- 3eme achat et +: `x2.0` (cap)

Note d'equilibrage:
- Les consommables doivent etre utiles mais moins rentables sur la duree que les upgrades permanents.

## 6) Map and Objective Structure

Approche recommandee V1:
- Une map fixe (plus simple a equilibrer et plus lisible pour le joueur).
- Objectif de defense fixe sur la carte.
- Le joueur peut se deplacer librement; il n'est pas "statique".
- Les ennemis arrivent en vagues avec variations de points d'entree.

Regle de controle objectif V1:
- L'objectif est perdu si les Tyranides le controlent pendant `2` fins de round consecutives.
- Controle Space Marine = au moins une unite vivante dans la zone d'objectif et aucune superiorite Tyranide nette.

Condition de defaite:
- Escouade detruite, ou
- Objectif perdu (selon regle de contestation definie).

## 7) Wave Scaling

La difficulte n'augmente pas seulement par le nombre d'unites, mais via un "budget de menace" par vague:

- Le budget augmente a chaque vague.
- Les compositions ennemies deviennent plus exigeantes (quantite + qualite).
- Les pics de difficulte doivent rester lisibles (pas de saut injuste).

Principe cle V1 (reutilisation maximale):
- Le cout de menace d'une unite Tyranide est strictement sa valeur `static VALUE` existante.
- Source de verite: `frontend/src/roster/tyranid/units/*.ts`.
- Aucune table de cout parallele n'est introduite.

Valeurs Tyranides de reference (existant):
- Termagant: `6`
- Hormagaunt: `7`
- Gargoyle: `7`
- RipperSwarm: `15`
- Genestealer: `19`
- TyranidWarriorRanged: `24`
- Zoanthrope: `30`
- Pyrovore: `30`
- TyranidWarriorMelee: `32`
- HiveGuard (Impaler/Shockcannon): `32`
- TyrantGuard (all variants): `32`
- Biovore: `45`
- GenestealerPrime: `90`
- Carnifex: `125`

Table budget de menace V1 (vagues 1-20, en points VALUE):

| Vague | Budget |
|---|---:|
| 1 | 18 |
| 2 | 24 |
| 3 | 30 |
| 4 | 36 |
| 5 | 44 |
| 6 | 52 |
| 7 | 60 |
| 8 | 70 |
| 9 | 80 |
| 10 | 92 |
| 11 | 104 |
| 12 | 118 |
| 13 | 132 |
| 14 | 148 |
| 15 | 164 |
| 16 | 182 |
| 17 | 200 |
| 18 | 220 |
| 19 | 242 |
| 20 | 266 |

Convention de generation:
- Le generateur compose la vague tant que `somme(VALUE_unites_spawn) <= budget_vague`.
- Tolerance de remplissage: si aucun choix exact possible, autoriser un reliquat <= `5`.
- Vagues 1-4: unites `VALUE <= 24` uniquement.
- Vagues 5-9: deblocage progressif des unites `VALUE 30-45`.
- Vague 10+: deblocage des menaces `VALUE >= 90` (rare, plafonnees).
- Toutes les 5 vagues: mini-spike controle (`+10%` budget de menace de la vague).

## 8) Scoring

Score principal:
- Base: vague la plus haute atteinte.

Formule score V1:
- `score_run = (vague_max * 100) + bonus_mastery + bonus_objective`
- `bonus_mastery = 15 * nb_vagues_sans_consumable`
- `bonus_objective = 10 * nb_vagues_objectif_non_conteste`

Exemple:
- Vague max 12, 7 vagues sans consommable, 9 vagues objectif propre
- Score = `1200 + 105 + 90 = 1395`

Objectif metagame:
- Leaderboard local / high score run-to-run.
- Encourager la prise de risque et l'optimisation du build.

## 9) UX Expectations

- Afficher clairement:
  - Numero de vague.
  - Points disponibles.
  - Menace de la prochaine vague (qualitative ou numerique).
  - Slots de l'escouade et role de chaque slot.
  - Effets actifs des buffs temporaires.
- Boutique lisible par categories: `Unit`, `Model`, `Weapons`, `Consumables`.

## 10) Balancing Priorities

Priorite 1:
- Equilibre escouade globale vs vagues Tyranides.

Priorite 2:
- Eviter les strategies dominantes absolues (sans forcer la parite parfaite entre slots).

Priorite 3:
- Maintenir une progression satisfaisante meme sans consommables.

## 11) Non-Goals (V1)

- Pas de traversal/extraction multi-objectifs.
- Pas de rotation de nombreuses maps.
- Pas d'arbre de talents complexe.

Ces axes peuvent etre traites en V2/V3 apres stabilisation du coeur survie.

## 12) Implementation Roadmap (Suggested)

1. Definir les regles de run (slots, boutique, scoring).
2. Integrer la boucle vagues + recompenses.
3. Integrer la boutique inter-vague.
4. Integrer les consommables temporaires.
5. Ajouter persistence du high score et telemetry de run.
6. Ajuster les couts et le budget de menace a partir des tests.

## 13) Telemetry minimale a enregistrer

- `wave_reached`
- `final_score`
- `points_earned_total`
- `points_spent_total`
- `consumables_used_total`
- `leader_model_end_run`
- `slot3_unlocked_wave`

## 14) Success Criteria

Le mode est considere valide si:

- Les joueurs comprennent la boucle en moins de 2 runs.
- Le score augmente via maitrise et decisions (pas uniquement RNG).
- Les runs sont rejouables et donnent envie de battre son record.
- Le tuning est stable sur les 10-15 premieres vagues.
- Le taux de "defaite avant vague 3" reste inferieur a 25% sur panel test interne.

## 15) Exemples de compositions de vagues (VALUE reel)

Objectif:
- Donner des presets concrets pour les premiers tests.
- Reutiliser uniquement les unites Tyranides existantes et leurs `static VALUE`.

Regle:
- Chaque exemple doit respecter `somme(VALUE) <= budget_vague`.
- Les exemples ci-dessous servent de templates, pas de liste ferme.

### Vague 1 (budget 18)

- Profil `Swarm`: 3x Termagant (`3*6 = 18`)
- Profil `Rush`: 2x Hormagaunt + 1x Termagant (`2*7 + 6 = 20`) -> non valide en strict, a eviter si pas de depassement autorise
- Profil `Mix valide`: 1x Hormagaunt + 1x Gargoyle + 1x Termagant (`7 + 7 + 6 = 20`) -> non valide en strict, garder pour mode "soft cap"

Recommendation V1:
- En mode strict, utiliser 3x Termagant.
- En mode soft cap (ecart max +2), autoriser mix gaunt/gargoyle.

### Vague 4 (budget 36)

- Profil `Swarm`: 6x Termagant (`36`)
- Profil `Mix`: 3x Termagant + 2x Hormagaunt + 1x Gargoyle (`18 + 14 + 7 = 39`) -> soft cap
- Profil `Pression melee`: 5x Hormagaunt (`35`)

### Vague 8 (budget 70)

- Profil `Swarm`: 8x Termagant + 3x Hormagaunt (`48 + 21 = 69`)
- Profil `Mix troop`: 1x TyranidWarriorRanged + 4x Termagant + 3x Hormagaunt (`24 + 24 + 21 = 69`)
- Profil `Mid elite`: 1x Zoanthrope + 2x Hormagaunt + 4x Termagant (`30 + 14 + 24 = 68`)

### Vague 12 (budget 118)

- Profil `Elite pressure`: 2x TyranidWarriorMelee + 1x Zoanthrope + 4x Hormagaunt (`64 + 30 + 28 = 122`) -> soft cap
- Profil `Mix stable`: 2x TyranidWarriorRanged + 1x Pyrovore + 2x Hormagaunt + 2x Termagant (`48 + 30 + 14 + 12 = 104`)
- Profil `Artillery`: 1x Biovore + 1x TyranidWarriorMelee + 3x Hormagaunt + 3x Termagant (`45 + 32 + 21 + 18 = 116`)

### Vague 16 (budget 182)

- Profil `Heavy wave`: 1x GenestealerPrime + 2x TyranidWarriorMelee + 5x Termagant (`90 + 64 + 30 = 184`) -> soft cap
- Profil `Mix control`: 1x Biovore + 2x Zoanthrope + 2x TyranidWarriorRanged + 3x Hormagaunt (`45 + 60 + 48 + 21 = 174`)
- Profil `Brawler`: 1x Carnifex + 4x Termagant + 3x Hormagaunt (`125 + 24 + 21 = 170`)

### Vague 20 (budget 266)

- Profil `Boss + swarm`: 1x Carnifex + 1x GenestealerPrime + 4x Hormagaunt + 4x Termagant (`125 + 90 + 28 + 24 = 267`) -> soft cap
- Profil `Elite synapse`: 2x Zoanthrope + 2x TyranidWarriorMelee + 1x Biovore + 4x Termagant (`60 + 64 + 45 + 24 = 193`) + renforts dynamiques
- Profil `Double heavy`: 1x Carnifex + 1x Biovore + 2x TyranidWarriorRanged + 5x Hormagaunt (`125 + 45 + 48 + 35 = 253`)

Note importante:
- Si tu veux rester strict et deterministic, n'utiliser que des compositions `<= budget`.
- Si tu preferes plus de variete, activer un `soft cap` configurable (+2% a +5% max).

## 16) Todo implementation technique (ordre recommande)

### Backend engine (priorite haute)

1. Ajouter un scenario/mode `endless_duty` (config dediee):
- fichier scenario (ex: `config/scenario_endless_duty.json`)
- parametres: budget de menace par vague, regles objectif, economie run

2. Ajouter un orchestrateur de run:
- suivi `wave_index`, `points_current`, `score_current`, `consumables_stock`
- transitions: `combat -> end_wave -> shop -> next_wave`

3. Ajouter generateur de vague sur `VALUE` existant:
- lecture des unites Tyranides disponibles (registry existant)
- composition automatique sous contrainte budget
- regles de deblocage selon palier de vague

4. Ajouter logique objectif:
- etat contestation
- compteur de rounds contestes consecutifs
- condition de defaite objective

5. Ajouter economie boutique:
- unlock slot 3
- upgrades modele/armes existantes uniquement
- consommables temporaires + limites + escalade cout

6. Ajouter score & telemetry:
- calcul score de fin de run
- enregistrement KPIs definis section 13

### Frontend (priorite haute)

1. Ajouter entree de mode dans UI:
- bouton/selection `Endless Duty`
- ecran de briefing (regles courtes + objectifs)

2. Ajouter HUD run:
- vague en cours
- budget/prochaine menace (indicatif)
- points dispo
- score courant
- etat objectif (controle/conteste/perdu)

3. Ajouter shop inter-vague:
- categories `Unit / Model / Weapons / Consumables`
- validation role slots (Leader/Melee/Heavy-Special)
- preview impact cout + confirmation achat

4. Ajouter feedback consommables:
- stock restant
- usage sur vague
- effets actifs temporaires

### Data/config (priorite moyenne)

1. Ajouter config V1 du mode:
- table budgets vagues 1-20
- couts boutique
- limites consommables
- regles score

2. Ajouter presets de composition pour tests QA:
- 2-3 profils par palier de vague
- seed fixee pour reproduire les runs

### QA et tuning (priorite haute)

1. Smoke tests:
- run complete jusqu'a vague 5 sans crash
- verification shop, unlock slot 3, score, defaite objectif

2. Test d'equilibrage initial:
- 20 runs internes avec profils joueurs differents
- mesurer "defaite avant vague 3" et "vague mediane atteinte"

3. Ajustements rapides:
- budget vague
- prix upgrades
- puissance/limites consommables

## 17) Time-to-Maturation Model (VALUE-driven)

Objectif:
- Estimer en amont a quelle vague un joueur atteint son build "mature".
- Piloter la duree de progression sans casser la difficulte progressive des vagues.

Point cle:
- Ici, `difficulty` ne veut pas dire "IA plus forte/faible".
- Ici, `difficulty profile` = vitesse de progression economique (`fast/standard/slow`).
- La menace reste progressive dans tous les cas; seul le rythme d'acces aux upgrades change.

### 17.1 Definitions

- `VALUE(u)`: valeur officielle d'une unite existante (`static VALUE`).
- `C_upgrade`: cout d'upgrade d'une unite courante vers unite cible.
- `C_unlock`: cout de debloquage d'un slot.
- `B_w`: budget de menace de la vague `w`.
- `alpha`: taux de conversion menace -> credits.
- `bonus_w`: bonus fixes de fin de vague (`no-consumable`, `objectif`).
- `sink_w`: depenses en consommables sur la vague.

### 17.2 Cout de maturation cible

On calcule le cout total pour atteindre un build cible:

- `C_upgrade = max(0, VALUE(cible) - VALUE(courante))`
- `C_total = somme(C_upgrade_slots) + somme(C_unlock_slots)`

Exemple cible (a ajuster selon roster final):
- Leader: `Intercessor (18) -> CaptainTerminator (95)` => `77`
- Slot melee: `AssaultIntercessor (17) -> AssaultTerminator (36)` => `19`
- Slot heavy: `unlock slot 3` + `TerminatorAssaultCannon (38)` => `C_unlock + 38`
- Si `C_unlock = 10`, alors `C_total = 77 + 19 + 10 + 38 = 144`

### 17.3 Credits gagnes par vague

Modele de gain recommande:

- `credits_w = floor(alpha * B_w) + bonus_w - sink_w`
- `credits_cumules(N) = somme(credits_w) pour w=1..N`

Critere de maturation:
- la run est "mature" a la premiere vague `N` telle que:
- `credits_cumules(N) >= C_total`

### 17.4 Profils de progression (pas de "difficulte combat")

| Profil progression | alpha | C_unlock slot 3 | Bonus fin de vague cible | Vague cible de maturation |
|---|---:|---:|---:|---:|
| Fast | 0.30 | 8 | 4-6 | 8-9 |
| Standard | 0.25 | 10 | 3-5 | 10-12 |
| Slow | 0.20 | 12 | 2-4 | 13-15 |

Interpretation:
- `Fast`: mode plus arcade/power fantasy.
- `Standard`: rythme recommande pour V1.
- `Slow`: progression plus tendue, orientee endurance.

### 17.5 Table de tuning prete a utiliser

Reglages principaux:
- `alpha`: levier #1 sur vitesse de progression.
- `C_unlock`: retarde ou accelere l'acces au slot 3.
- `bonus_w`: recompense l'execution propre.
- `sink_w`: frein economique via consommables.

Procedure de tuning:
1. Fixer un build de maturation cible (`C_total`).
2. Choisir la vague de maturation cible (ex: 10-12).
3. Simuler `credits_cumules` sur 20 vagues avec `sink_w` moyen.
4. Ajuster `alpha` puis `C_unlock`.
5. Ajuster bonus/sinks pour stabiliser l'ecart entre bons et moyens joueurs.

Validation telemetrie:
- comparer `wave_maturation_observee` vs `wave_maturation_cible`
- garder un ecart median <= 1.5 vague
- surveiller les extremes (snowball trop rapide ou stagnation)

## 18) Protocole de tests IA vs IA (achats scripts)

Objectif:
- Tuner rapidement l'economie et la courbe de menace sans boucle manuelle.
- Reutiliser le moteur existant en automatisant uniquement les achats inter-vagues.

Perimetre:
- Combat: IA joueur vs IA tyranide.
- Entre vagues: un script applique une politique d'achat deterministe.
- Aucun changement de regles de combat pour ces tests.

### 18.1 Pourquoi c'est utile

- Mesure robuste de la vitesse de progression (`time-to-maturation`).
- Detection rapide des economies cassees (snowball/stagnation).
- Comparaison objective de plusieurs parametrages (`alpha`, `unlock`, consommables).

### 18.2 Limites

- Ne mesure pas le ressenti joueur (fun, lisibilite, frustration UX).
- Peut sur-optimiser vers des comportements IA non representatifs d'un humain.

Conclusion:
- Excellent pour equilibrage systemique.
- A completer ensuite par playtests humains.

### 18.3 Profils d'achats scripts (V1)

Policy A - `GreedyPower`:
- Priorite: upgrades VALUE eleve en premier.
- Debloque slot 3 tard si upgrade Leader plus rentable immediatement.
- Utilise peu de consommables.

Policy B - `Balanced`:
- Debloque slot 3 des que possible.
- Repartit les upgrades sur les 3 slots.
- Usage modere des consommables.

Policy C - `Survivor`:
- Priorite a la survie court terme.
- Achete plus de consommables et upgrades defensifs.
- Repousse les upgrades premium.

Recommandation:
- Utiliser les 3 policies en parallele sur les memes seeds pour comparer les tendances.

### 18.4 Regles d'achat script (VALUE-driven)

- Recrutement unite: `cout = VALUE(unite)`
- Upgrade modele/variante: `cout = max(0, VALUE(cible) - VALUE(courante))`
- Unlock slot: `cout = C_unlock` (configurable)
- Consommables: cout base * multiplicateur d'escalade par type

Tie-break standard pour l'IA acheteur:
1. Action legalement possible
2. Meilleur ratio `gain_estime / cout`
3. Cout le plus bas (si egalite)
4. Ordre alphabetique stable (dernier tie-break)

### 18.5 Boucle de simulation (pseudo-flow)

1. Initialiser run (`seed`, profil policy, config eco).
2. Jouer la vague en IA vs IA.
3. Calculer credits de fin de vague.
4. Appeler le script d'achat policy.
5. Appliquer achats (en respectant slots/contraintes).
6. Passer a la vague suivante.
7. Stop sur defaite ou vague max de test.
8. Ecrire les metrics de run.

### 18.6 Metrics minimales a logger

Par run:
- `seed`
- `policy_name`
- `wave_reached`
- `wave_maturation`
- `final_score`
- `credits_earned_total`
- `credits_spent_total`
- `credits_unspent_end`
- `consumables_bought_total`
- `consumables_used_total`
- `slot3_unlock_wave`
- `leader_final_unit`
- `melee_final_unit`
- `heavy_final_unit`

Par vague (timeseries):
- `wave_index`
- `budget_wave`
- `credits_gained_wave`
- `credits_spent_wave`
- `army_value_player_wave`
- `army_value_enemy_wave`
- `objective_state_end_wave`

### 18.7 Plan d'execution recommande

- `30` seeds par policy minimum (`90` runs total).
- Relancer pour chaque preset eco (`Fast`, `Standard`, `Slow`).
- Conserver les memes seeds entre presets pour comparabilite.

### 18.8 Criteres de validation (gates)

Gate economie:
- `wave_maturation_mediane` conforme a la cible preset:
  - Fast: 8-9
  - Standard: 10-12
  - Slow: 13-15

Gate stabilite:
- Ecart interquartile de `wave_reached` non excessif (pas de mode roulette).
- Taux de defaite avant vague 3 sous seuil cible.

Gate anti-snowball:
- Eviter une part trop forte de runs qui "cassent" la courbe trop tot.
- Regle pratique: si >20% runs depassent la vague cible de maturation de +4 vagues,
  reduire `alpha` ou augmenter les sinks.

### 18.9 Actions correctives typiques

Si maturation trop rapide:
- baisser `alpha`
- augmenter `C_unlock`
- augmenter cout/consommation des consommables

Si maturation trop lente:
- augmenter `alpha`
- baisser `C_unlock`
- augmenter bonus de fin de vague

Si variance trop forte:
- lisser les spikes de budget
- reduire l'impact des consommables offensifs
- renforcer les rewards de maitrise stable (objectif/no-consumable)

### 18.10 Logging: `--step` comme source unique

Decision:
- Ne pas introduire un format de log parallele dedie Endless Duty.
- Reutiliser le flux existant base sur `--step` comme source de verite unique.

Rationale:
- `--step` trace deja la timeline complete de la partie.
- Evite la duplication de donnees et les incoherences entre deux pipelines.
- Limite le cout d'integration cote moteur et agregation.

Extension minimale requise (ajout de champs, pas de nouveau format):
- Evenements credits:
  - `credits_delta`
  - `credits_balance_before`
  - `credits_balance_after`
  - `credits_reason` (ex: `wave_clear`, `no_consumable_bonus`, `objective_bonus`)
- Evenements achats:
  - `purchase_type` (ex: `unlock_slot`, `unit_upgrade`, `weapon_variant`, `consumable`)
  - `purchase_item_id`
  - `purchase_item_from` (si upgrade)
  - `purchase_item_to` (si upgrade)
  - `purchase_cost`
  - `credits_balance_before`
  - `credits_balance_after`

Contrainte de compatibilite:
- Les nouveaux champs doivent etre optionnels pour ne pas casser les anciens parseurs.
- L'agregateur Endless Duty doit ignorer proprement les steps sans metadata eco.

## 19) Decisions V1 lock (ready-to-implement)

Cette section fige les choix proposes pour lancer l'implementation.

### 19.1 Economie finale (VALUE-driven)

Formule credits par vague:
- `credits_wave = floor(0.20 * enemy_value_killed_wave) + wave_clear_bonus + no_consumable_bonus + objective_hold_bonus`

Definitions:
- `enemy_value_killed_wave`: somme des `VALUE` ennemies eliminees pendant la vague.
- `wave_clear_bonus = 2` si la vague est nettoyee.
- `no_consumable_bonus = 1` si aucun consommable utilise sur la vague.
- `objective_hold_bonus = 1` si objectif tenu en fin de vague.

Decisions de cout:
- `unlock_slot3_cost = 10` credits (fixe).
- Recrutement unite: `cost = VALUE(unite_cible)`.
- Upgrade modele/variante/arme: `cost_delta = VALUE(cible) - VALUE(courante)` (delta signe).

Modele "capital de requisition":
- Le joueur dispose d'un `capital_requisition_total` (cumule sur la run).
- Chaque configuration d'escouade correspond a un `investissement_actuel` (somme des VALUE/overcosts equipes).
- Le budget disponible entre vagues est:
- `capital_disponible = capital_requisition_total - investissement_actuel`.
- Entre vagues, le joueur peut reconfigurer son equipement (armures + armes):
  - passer vers plus cher consomme du capital,
  - passer vers moins cher libere du capital.
- Ce n'est pas une revente: l'equipement retire est rendu au pool et le capital est recalcule via le nouveau total investi.

Rationale:
- Meme echelle `VALUE` pour ennemis, progression et achats.
- Maturation cible en profil standard: vague ~10-12 avec execution correcte.

### 19.1.b Slot unlock schedule (wave unlock)

Decision V1:
- `Leader` disponible des la wave 1.
- `Range` disponible a partir de la wave 10.
- `Melee` disponible a partir de la wave 15.

Regle:
- Avant le palier, le slot est visible mais locke en boutique/requisition.
- A l'atteinte de la wave de deblocage, le slot devient achetable/utilisable immediatement entre vagues.

### 19.2 Objectif/defaite (regle non ambigue)

Etat objectif a la fin de chaque round:
- `SM_CONTROL`: Space Marines controlent l'objectif.
- `TYR_CONTROL`: Tyranides controlent l'objectif.
- `NEUTRAL`: objectif conteste/egalite.

Compteur de contestation:
- `objective_lost_counter` incremente de `+1` uniquement si etat fin de round = `TYR_CONTROL`.
- `objective_lost_counter` reset a `0` si etat fin de round = `SM_CONTROL` ou `NEUTRAL`.
- Defaite immediate si `objective_lost_counter >= 2`.

Interpretation:
- Les Tyranides doivent conserver le controle pendant 2 fins de round consecutives.

### 19.2.b Regle de deploiement ennemi ED

Decision V1:
- Les Tyranides spawnent uniquement sur les hex de bord du board.
- Les positions de spawn sont choisies aleatoirement a chaque vague.
- ED ne redefinit pas les regles de combat: uniquement orchestration vagues + spawn.

Contraintes spawn:
- bords autorises: `north`, `south`, `east`, `west`
- exclusion des hex d'objectif
- distance minimale de l'objectif: `3`
- distance minimale entre nouveaux spawns de la vague: `1`
- tentative max de placement par unite: `50` (sinon fallback de regeneration de tirage)

Config source:
- `config/scenario_endless_duty.json` -> `endless_duty.enemy_spawn_rules`

### 19.3 Consommables V1

Catalogue:
- `med_stim`: soigne `+1 HP` instantane sur une unite.
- `adrenal_stim`: `+2 MOVE` jusqu'a la fin du tour courant.
- `targeter_stim`: `+1 to-hit` sur la prochaine activation de tir de l'unite.
- `armor_stim`: `+1 armor_save` (borne max 2+) jusqu'a la fin de la prochaine phase de tir ennemie.

Contraintes:
- Achat uniquement entre vagues.
- Stock max par type: `2`.
- Usage max: `3` consommables par vague (global).
- Escalade cout par type dans une run: `x1.0`, `x1.5`, `x2.0` (cap).

Stacking:
- Non-stackable pour un meme buff (reprendre le plus fort/plus recent, sans cumul).
- Buffs de types differents peuvent coexister.
- Max `1` consommable utilise par unite et par round.

### 19.4 Contrat de logs `--step` (noms proposes)

Credits events:
- `credits_delta`
- `credits_balance_before`
- `credits_balance_after`
- `credits_reason` (`kill_value`, `wave_clear_bonus`, `no_consumable_bonus`, `objective_hold_bonus`)
- `wave_index`

Purchase events:
- `purchase_type` (`unlock_slot`, `recruit_unit`, `upgrade_unit`, `weapon_variant`, `consumable`)
- `purchase_item_id`
- `purchase_item_from`
- `purchase_item_to`
- `purchase_cost`
- `purchase_delta` (peut etre negatif lors d'une reconfiguration vers moins cher)
- `credits_balance_before`
- `credits_balance_after`
- `wave_index`

Compatibilite:
- Tous ces champs restent optionnels.
- Les parseurs existants qui lisent `--step` sans ces champs doivent continuer a fonctionner.

## 20) UI spec: Requisition / Equipment Management Window

Objectif:
- Permettre une reconfiguration rapide entre vagues sans ambiguite economique.
- Afficher en permanence le modele "capital de requisition".

### 20.1 Wireframe fonctionnel (desktop)

Header (ligne 1):
- `Wave {n} complete`
- `Capital total: X`
- `Investi (projete): Y`
- `Disponible (projete): Z`
- Badge delta session: `Net delta: +/-D`

Body 2 colonnes:
- Colonne gauche (35%): `Squad Slots`
  - Carte `Leader`
  - Carte `Melee`
  - Carte `Range`
  - Chaque carte: unite actuelle, VALUE, loadout, statut unlock, bouton `Edit`
- Colonne droite (65%): `Requisition Builder`
  - Onglets: `Profile`, `Armor`, `Weapons`, `Consumables`
  - Liste d'options avec:
    - nom
    - VALUE cible
    - delta vs current (`+5`, `-2`, `0`)
    - lock badge (`Unlock at wave 20`)
    - affordance (`Affordable` / `Insufficient capital`)

Footer:
- `Reset Slot`
- `Reset All`
- `Apply Changes`
- `Cancel`

### 20.2 Comportements UX obligatoires

- Recalcul live apres chaque changement local (sans roundtrip).
- Impossible de valider si `disponible_projete < 0`.
- Les options lockees sont visibles mais non selectionnables.
- Le joueur peut passer sur une option moins chere: le disponible augmente.
- Confirmation finale avant commit:
  - resume des deltas par slot
  - net delta global
  - capital final apres application

### 20.3 Composants React proposes (frontend)

Conteneur:
- `RequisitionModal`

Sous-composants:
- `RequisitionHeader`
- `SlotSummaryList`
- `SlotSummaryCard`
- `RequisitionBuilder`
- `OptionList`
- `OptionRow`
- `ConsumablePanel`
- `RequisitionFooter`
- `RequisitionConfirmDialog`

### 20.4 Etat minimal (TypeScript, suggestion)

```ts
type SlotKey = "leader" | "melee" | "range";

type RequisitionState = {
  waveIndex: number;
  capitalTotal: number;          // cumul run
  investedCurrent: number;       // loadout actuellement equipe
  investedDraft: number;         // loadout en edition
  availableDraft: number;        // capitalTotal - investedDraft
  selectedSlot: SlotKey | null;
  squadCurrent: Record<SlotKey, string | null>; // unit ids
  squadDraft: Record<SlotKey, string | null>;
  draftConsumables: Record<string, number>;     // id -> qty
  locksByOption: Record<string, { locked: boolean; reason?: string }>;
  deltasBySlot: Record<SlotKey, number>;
  canApply: boolean;
  validationErrors: string[];
};
```

### 20.5 Contrat de calcul (frontend)

- `investedDraft = somme(VALUE de tous les choix draft + consommables draft)`
- `availableDraft = capitalTotal - investedDraft`
- Delta d'une option:
- `optionDelta = VALUE(optionCible) - VALUE(optionCourante)`
- Regle de validation:
  - `availableDraft >= 0`
  - slot unlock respecte
  - `wave_unlock_rules` respectees

### 20.6 Payload API propose (apply changes)

```json
{
  "mode": "endless_duty",
  "wave_index": 12,
  "changes": [
    {
      "slot": "leader",
      "from_unit": "CaptainGravisBladeBoltstorm",
      "to_unit": "CaptainTerminatorRelicFistCombi",
      "delta": 16
    },
    {
      "slot": "range",
      "from_unit": "TerminatorAssaultCannon",
      "to_unit": "TerminatorHeavyFlamer",
      "delta": -1
    }
  ],
  "consumables_changes": [
    {"id": "med_stim", "qty_delta": 1, "delta": 5}
  ],
  "invested_before": 108,
  "invested_after": 128,
  "capital_total": 132,
  "available_after": 4
}
```

### 20.7 Logs `--step` lies a l'UI

A l'application des changements:
- emettre 1 event `purchase` par changement de slot
- emettre 1 event `purchase` par variation consommable
- inclure:
  - `wave_index`
  - `purchase_type`
  - `purchase_item_from`
  - `purchase_item_to`
  - `purchase_delta`
  - `credits_balance_before`
  - `credits_balance_after`

### 20.8 Etats d'erreur / edge cases

- Slot non debloque mais draft cible present -> erreur bloquante.
- Option retiree du roster entre deux versions -> fallback UI "invalid selection" + reset local.
- Capital negatif apres mise a jour serveur -> refuser commit et recharger etat serveur.
- Double clic `Apply` -> bouton desactive + idempotency token cote API.

### 20.9 Integration minimale (ordre)

1. Creer `RequisitionModal` avec donnees mock.
2. Brancher calcul local `investedDraft/availableDraft`.
3. Ajouter validations (locks + budget).
4. Brancher endpoint d'application.
5. Brancher emission des logs `--step`.
6. Ajouter tests UI sur 3 flows: upgrade+, downgrade-, mix slot+consumable.

## 21) ED-specific unit variants (`*_ED`)

Decision:
- Les profils standards restent inchanges pour PvE/PvP.
- Endless Duty utilise des variantes dediees suffixees `_ED`.
- Objectif: permettre des valeurs d'equipement differenciees en ED sans impacter les modes standards.

Conventions:
- Classe/fichier ED: `<StandardUnitName>_ED` (ex: `CaptainPowerFistPlasmaPistol_ED`).
- `NAME`/identifiant runtime ED doit etre unique et explicite.
- Whitelist ED pointe uniquement vers les IDs `_ED`.
- Les regles de combat, armes et comportements restent alignes avec la version standard (pas de fork gameplay).

Source de verite economie ED:
- Les couts d'evolution/achat ED sont pilotables via config ED (ex: `leader_evolution.json`).
- Les classes `_ED` portent les valeurs appliquees dans le mode ED.
- Le moteur ED n'utilise pas les profils standards pour les calculs d'achat.

Regle anti-drift:
- Toute modification d'un profil standard leader doit etre repercutee sur son equivalent `_ED` (stats/regles/armes), sauf ce qui est explicitement economique.

## 22) Random board bonuses (anti-monotony)

Avis produit:
- Bonne idee. Ca peut casser la monotonie et forcer des choix de risque/position.
- A condition de rester leger et lisible pour ne pas ecraser la boucle principale vague+requisition.

Design V1 recommande:
- Bonus rares, pas permanents.
- Spawn aleatoire sur le board, jamais sur objectif.
- Fenetre de collecte courte (expiration).
- Effets simples, peu nombreux.

Types de bonus V1:
- `requisition_cache`: +`2` requisitions
- `med_kit_small`: soigne `+1 HP` (une unite)
- `target_uplink`: +`1` to-hit sur prochaine activation de tir
- `adrenal_push`: +`1 MOVE` jusqu'a fin de tour

Regles de spawn (proposition):
- Max `1` bonus actif a la fois sur la carte.
- Chance de spawn par vague: `35%`.
- Spawn au debut de la vague ou a mi-vague (une seule apparition).
- Exclusions: hex objectifs, hex occupes, hex invalides.
- Duree de vie: `2` rounds, puis disparition.

Garde-fous d'equilibrage:
- Pas de stacking du meme bonus.
- Pas de drop garanti chaque vague.
- Effets numeriques modestes (micro-avantage, pas retournement automatique).

Priorite implementation:
- V1 sans bonus possible pour stabiliser le coeur.
- Activer les bonus en V1.1 derriere un flag config (`endless_duty.bonuses.enabled`).
