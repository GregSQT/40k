# Architecture Training RL: 3 Agents Tanking + Sampling Matrix

## Objectif

Ameliorer la robustesse PPO sans fragmenter excessivement les donnees:
- Split principal par `Tanking` (`Swarm`, `Troop`, `Elite`)
- Pas de split dur par `BlendCategory`
- Utilisation du blend/profils pour exposer l'agent a des distributions variees via sampling/curriculum.

Cette architecture privilegie la stabilite et la generalisation holdout plutot qu'une specialisation trop fine.

---

## Pourquoi ce design

Le split `Tanking x Blend` (9 cellules) est souvent trop fragmentant quand certaines cellules sont peu peuplees.
Avec PPO, les classes rares augmentent:
- la variance des gradients,
- le risque d'overfit local,
- l'instabilite entre seeds.

Le compromis retenu:
- **3 agents tanking** pour conserver un biais inductif utile,
- **sampling profile-aware** pour conserver la richesse tactique.

---

## Composants

## 1) Classifier unifie

Script: `scripts/unit_classifier.py`

Role:
- classer les unites en `Tanking` et `BlendCategory`,
- produire `Blend_R` et `Ratio_R_M`,
- exporter un CSV de reference (`reports/unit_classification.csv`).

Usage type:
```bash
python scripts/unit_classifier.py --roster all
```

Le classifieur sert de source de verite pour la couverture des profils.

## 2) Matrice de sampling

Source: derivee du CSV du classifieur (et/ou JSON dedie si disponible dans ton pipeline).

Role:
- representer les distributions de profils par tanking,
- calculer des poids de sampling (anti-sous-representation),
- piloter les matchups de training sans changer le split d'agents.

Principe:
- split agent = `Tanking`,
- sampling = `BlendGroup`, `MobilityBucket`, `WeaponProfile` (si exposes dans ta matrice).

## 3) Generation dynamique de rosters

Script recommande: `scripts/build_dynamic_rosters.py`

Role:
- lire la matrice de sampling,
- generer des rosters synthetiques selon des contraintes,
- ecrire des JSON compatibles avec le format roster existant.

Entrees minimales:
- `--matrix`
- `--target-tanking`
- `--num-rosters`
- `--units-per-roster` (ou budget points)
- `--seed`
- `--output-dir`

Sortie:
- fichiers roster JSON directement referencables par les scenarios existants.

## 3.b) Contrainte `VALUE` (obligatoire)

Le point critique pour des trainings productifs n'est pas seulement la diversite des profils:
il faut aussi controler l'equilibre de puissance des affrontements.

### Pourquoi `VALUE` est central

- Sans contrainte de budget, le sampler peut creer des matchups structurellement biaises.
- Un policy PPO peut alors apprendre des patterns opportunistes de dataset
  ("gagner car roster plus fort") au lieu de vrais comportements tactiques.
- La variance inter-seed augmente artificiellement.

### Regles minimales a imposer

1. **Budget roster cible**
- Chaque roster genere doit respecter un budget points cible (`target_points`),
- avec tolerance explicite (`points_tolerance`), par exemple `100 +/- 2`.

2. **Equilibre de matchup (P1 vs P2)**
- Pour chaque episode, imposer:
  `abs(total_value_p1 - total_value_p2) <= matchup_value_tolerance`
- Exemple pragmatique: tolerance `<= 3` points.

3. **Hard constraints avant export**
- Rejeter tout roster qui depasse tolerance budget.
- Rejeter tout matchup qui depasse tolerance d'ecart de valeur.
- Aucun fallback silencieux: erreur explicite + compteur de rejets.

4. **Soft constraints de diversite**
- Apres satisfaction des hard constraints `VALUE`, appliquer les quotas de profils
  (`BlendGroup`, `MobilityBucket`, `WeaponProfile`).
- Priorite stricte: `VALUE` -> validite roster -> diversite profils.

### Algorithme recommande (ordre d'execution)

1. Echantillonner une cellule cible de la matrice (tanking/blend/mobility/weapon).
2. Proposer une unite candidate.
3. Verifier l'ajout vis-a-vis du budget restant (`VALUE`).
4. Accepter/rejeter la candidate.
5. Iterer jusqu'a roster complet ou echec explicite.
6. Une fois P1 et P2 generes, verifier la contrainte `matchup_value_tolerance`.
7. Si KO: resampler matchup (pas de correction cachée).

### KPI a logger en continu

- `roster_value_mean`, `roster_value_std`
- `matchup_value_gap_mean`, `matchup_value_gap_p95`
- `%matchups_within_value_tolerance`
- `rejection_rate_value_constraint`
- performance holdout conditionnee par bins de value-gap

Ces metriques doivent etre affichees en meme temps que les scores RL pour detecter
rapidement un biais de puissance dans le generateur.

## 4) Integration training/eval

Le training ne change pas conceptuellement:
- on alimente le pipeline avec des rosters mieux distribues,
- on conserve la compatibilite `p1_roster_ref` / `p2_roster_ref`,
- on garde les evals complètes `holdout_regular + holdout_hard`.

Selection du meilleur modele:
1. `holdout_overall_mean` (objectif principal)
2. contraintes minimales sur `holdout_hard_mean`
3. contraintes minimales sur `worst_bot_score`

---

## Regles de robustesse

- Pas de fallback silencieux.
- Erreurs explicites si cle requise absente.
- Aucune valeur inventee dans le code; parametres dans config.
- `VALUE` est une contrainte de premier niveau, pas un critere secondaire.
- Verification de coherence apres generation:
  - format roster valide,
  - budget `VALUE` respecte par roster,
  - ecart `VALUE` matchup dans tolerance,
  - referencement scenario valide,
  - distribution profils conforme aux objectifs.

---

## Protocole de validation conseille

1. Rebuild classifieur:
```bash
python scripts/unit_classifier.py --roster all
```
2. Generer N rosters dynamiques par tanking.
3. Verifier les KPI `VALUE` (budget + gap matchup) avant training.
4. Lancer training/eval sur seeds fixes.
5. Comparer contre baseline statique:
   - `holdout_overall_mean`
   - `holdout_hard_mean`
   - `worst_bot_score`
   - variance inter-seed
   - `matchup_value_gap_mean/p95`

---

## Option alternative: 1 agent multi-head

## Ce que c'est

Un seul backbone (trunk) partage les representations, avec plusieurs têtes specialisees (par exemple par tanking/profil).

## Avantages potentiels

- meilleure mutualisation des features,
- moins de duplication de training,
- possibilite d'ameliorer la sample efficiency quand les profils partagent beaucoup.

## Couts/risques reels (dans ce projet)

- complexite implementation plus elevee (policy custom + losses multi-head),
- SB3 PPO standard ne fournit pas ce schema "plug-and-play",
- risque de negative transfer entre profils (une tete degradee peut polluer le trunk),
- tuning plus difficile (pondération des losses, scheduling d'echantillonnage, stabilite).

## Avis franc (recommandation)

**Court/moyen terme**: la meilleure solution pragmatique est l'architecture actuelle
`3 agents tanking + sampling matrix`.

**Long terme (R&D)**: un multi-head peut depasser ce setup **si**:
- tu as plus de donnees par profil,
- une infra d'experimentation solide,
- du temps pour tuner proprement la stabilite.

Donc:
- pour la performance fiable maintenant: **3 agents + sampling profile-aware**,
- pour un pari d'optimisation future: **prototype multi-head en branche experimentale**, sans remplacer la prod avant preuves holdout robustes.

---

## Decision framework

- Si objectif = robustesse rapide et risque faible -> `3 agents tanking + sampling matrix`.
- Si objectif = performance max a long terme et budget R&D eleve -> tester multi-head en ablation, puis promotion seulement si gains robustes confirmes.

---

## Spec executable (recommandee)

Ce bloc definit une specification directement exploitable pour la generation de rosters et le pilotage PPO.

### Parametres par defaut

- `target_points`: `100`
- `points_tolerance`: `2`
- `matchup_value_tolerance_strict`: `3`
- `matchup_value_tolerance_medium`: `7`
- `matchup_value_tolerance_wide`: `12`
- `max_roster_build_attempts`: `200`
- `max_matchup_build_attempts`: `300`

### Distribution recommandee des gaps de matchup

Pour eviter un entrainement "trop propre" (peu robuste hors distribution):

- `70%` episodes: bucket `strict` (`abs(gap) <= 3`)
- `20%` episodes: bucket `medium` (`4..7`)
- `10%` episodes: bucket `wide` (`8..12`)

Regle de symetrie:
- Sur une fenetre glissante (ex: 100 episodes), la moyenne du signe du gap doit tendre vers `0`:
  - autant de cas favorables P1 que favorables P2.

### Regles hard (bloquantes)

1. Roster invalide si `abs(roster_value - target_points) > points_tolerance`.
2. Matchup invalide si gap hors bucket cible de l'episode.
3. Si echec apres `max_*_attempts`:
   - lever une erreur explicite,
   - logger les causes (budget impossible, cellule vide, contraintes incompatibles).

### Regles soft (apres hard constraints)

Une fois les contraintes VALUE validees:
- appliquer les poids de diversite (`BlendGroup`, `MobilityBucket`, `WeaponProfile`),
- limiter la repetition d'une meme unite sur une fenetre courte (anti-collapse de sampling),
- verifier que la distribution observee converge vers la distribution cible.

### KPI obligatoires a logger

- `roster_value_mean`, `roster_value_std`
- `matchup_value_gap_mean`, `matchup_value_gap_p95`
- `%matchups_in_strict_bucket`
- `%matchups_in_medium_bucket`
- `%matchups_in_wide_bucket`
- `rejection_rate_roster_budget`
- `rejection_rate_matchup_gap`
- `unit_pick_frequency` (top-k + queue longue)
- `distribution_drift_blend/mobility/weapon_profile`

### Gates go / no-go (promotion pipeline)

Promouvoir une nouvelle config de generation seulement si:

1. `holdout_overall_mean` >= baseline (marge configurable)
2. `holdout_hard_mean` >= baseline
3. `worst_bot_score` >= baseline
4. `matchup_value_gap_p95` dans la cible definie
5. Pas de collapse de distribution (`distribution_drift` sous seuil)

Sinon:
- rollback a la config precedente,
- conserver les logs de rejet + drift pour ajuster les poids et buckets.

### Commandes de verification minimales

1. Rebuild classifieur:
```bash
python scripts/unit_classifier.py --roster all
```

2. Generer rosters dynamiques (script dedie):
```bash
python scripts/build_dynamic_rosters.py \
  --matrix reports/unit_sampling_matrix.json \
  --target-tanking Swarm \
  --points-scale 100 \
  --num-rosters 200 \
  --units-per-roster 5 \
  --seed 42
```

3. Verifier KPIs VALUE avant training:
- budget roster,
- distribution des gaps,
- taux de rejet.

4. Lancer training/eval et comparer aux gates de promotion.

