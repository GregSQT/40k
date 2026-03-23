# IA switch seat training/eval (P1, P2, random) - v2 prete implementation

## Objectif

Permettre un pipeline RL fiable avec siege agent configurable:

- `p1` : agent toujours joueur 1
- `p2` : agent toujours joueur 2
- `random` : agent alterne entre P1/P2 par episode

Sans biais de perspective (reward, metrics, eval, obs, action-mask).

---

## Resume executif

Le switch de seat n'est fiable que si on traite **toute la pipeline**, pas seulement la boucle d'entrainement:

- resolution explicite du seat par episode
- wrappers seat-aware
- reward/metrics/eval agent-relatifs
- observation **et** action-mask semantiquement invariants

La migration scenario/roster role-based (`agent`/`opponent`) est valide, mais doit etre en phase separee.

---

## Etat actuel (facts)

### Coherent cote PvE runtime

- `engine/w40k_core.py`: IA runtime PvE executee en P2
- `services/api_server.py`: mapping `player_types` coherent avec PvE
- `engine/pve_controller.py`: inference deterministe en place

### Encore oriente P1 cote training/eval

- hypotheses `winner == 1` dans modules training/eval/metrics
- `controlled_player` encore biaise P1 dans certaines branches
- wrappers `BotControlledEnv` structures agent=P1 / bot=P2
- certaines features observation restent absolues (P1-P2)

---

## Contrat cible

## 1) Seat explicite et strict

Configurer `agent_seat_mode` (obligatoire):

- `"p1" | "p2" | "random"`

A chaque reset episode:

- resoudre `agent_player` in `{1,2}`
- definir `opponent_player` = autre joueur
- persister ces champs dans `info`/state episode

Interdit:

- fallback implicite (`get(..., 1)`)
- valeur absente/invalide silencieuse

## 2) Random mode robuste PPO (env vectorises)

Contraintes minimales:

- echantillonnage equiprobable P1/P2 a long terme
- assignment par episode (pas par step)
- en vec env: tirage independant par sous-env
- audit de distribution: `%episodes_P1`, `%episodes_P2`

Critere:

- ecart absolu entre parts P1/P2 <= 5% sur une fenetre significative

## 3) Logique agent-relative partout

Tout calcul sensible au camp doit etre exprime via `agent_player`:

- reward terminale/actionnelle
- win/loss/draw metrics
- eval bots
- features globales d'observation

## 4) Invariance observation + action-mask

En plus de l'ego-centric obs, garantir:

- semantique action-space identique cote agent (quel que soit seat)
- action-mask valide et coherent en P1/P2
- pas d'inversion de sens des indices d'action

---

## Plan d'implementation en 2 phases (Go/No-Go)

## Phase 1 - Pipeline seat-aware (bloquant)

Perimetre:

1. Ajouter `agent_seat_mode` + validation stricte.
2. Resoudre `agent_player/opponent_player` a chaque episode.
3. Generaliser wrappers (`BotControlledEnv` et eval wrappers):
   - remplacer hardcodes `current_player == 2` par `current_player == bot_player`
   - controler explicitement `agent_player` et `bot_player`
4. Aligner reward/metrics/eval:
   - remplacer `winner == 1` par `winner == agent_player`
   - verifier toutes branches terminales win/lose/draw
5. Ajouter reporting par side:
   - `winrate_agent_p1`, `winrate_agent_p2`, `winrate_global`
   - compteurs episodes par side

Go/No-Go Phase 1:

- train smoke OK en `p1`, `p2`, `random` (sans crash)
- eval cross-seat coherent (meme checkpoint/seeds/scenarios):
  - wins incrementent selon `winner == agent_player`
- distribution random conforme (ecart <= 5%)
- aucune hypothese residuelle critique `winner == 1`

Si un point echoue: stop, corriger avant Phase 2.

## Phase 2 - Migration assets role-based (optionnelle apres stabilisation)

Perimetre:

1. Introduire `side: "agent" | "opponent"` dans scenarios/rosters.
2. Resoudre role -> player au reset selon seat episode.
3. Compatibilite transitoire:
   - ancien format P1/P2 + nouveau format role-based
4. Migration progressive des assets, puis nettoyage.

Go/No-Go Phase 2:

- un meme asset fonctionne en `p1`, `p2`, `random`
- pas de regression sur eval Phase 1
- scripts d'analyse historiques adaptes/versionnes

---

## Protocole d'evaluation cross-seat (obligatoire)

Pour chaque checkpoint candidate:

- meme matrice de seeds/scenarios en `p1`, `p2`, `random`
- report minimum:
  - `WR(P1)`, `WR(P2)`, `WR(global)`
  - intervalle de confiance ou au moins n episodes explicite
- comparaison avant/apres:
  - delta `WR(P2)` (objectif principal PvE)
  - verification absence de collapse `WR(P1)`

Lecture recommandee:

- promotion seulement si `WR(P2)` progresse sans degradation majeure globale

---

## Criteres d'acceptation

- `agent_seat_mode` supporte `p1`, `p2`, `random` (strict)
- pas de fallback implicite pour seat/controlled player
- aucune hypothese critique `winner == 1` residuelle
- observation **et** action-mask cohérents P1/P2
- reporting separe par side disponible en train/eval
- random distribue correctement les episodes

---

## Risques connus

- regression silencieuse si un seul point reste P1-centré
- confusion dashboards si metriques historiques non versionnees
- bruit statistique si n episodes trop faible en cross-seat

Mitigations:

- tests cross-seat standardises
- tags/version metriques
- seuils Go/No-Go explicites

---

## Scope control

- API PvE/UI PvE: pas de refonte dans ce ticket
- gameplay hors sujet: non modifie
- priorite: fiabiliser training/eval multi-seat (Phase 1)

---

## Conclusion

Le bon ordre est:

1. **Phase 1 pipeline seat-aware** (obligatoire, bloquante)
2. **Phase 2 assets role-based** (apres stabilisation)

Le mode `random` est une force seulement si la distribution est controlee et les metriques sont separees par side.

---

## Checklist implementation (fichier par fichier)

Ordre recommande: appliquer dans cet ordre pour limiter les regressions et faciliter le debug.

## 0) Point d'entree train/eval

- `ai/train.py`
  - ajouter/valider `agent_seat_mode` (`p1|p2|random`) dans les params runtime
  - resoudre `agent_player` a chaque reset episode (ou deleguer au wrapper avec trace explicite)
  - propager `agent_player`/`bot_player` aux wrappers de train
- `ai/bot_evaluation.py`
  - accepter `agent_seat_mode` ou `agent_player` explicite
  - propager le seat au wrapper d'eval
  - compter wins/losses/draws selon `winner == agent_player`

## 1) Wrappers (coeur du switch de siege)

- `ai/env_wrappers.py`
  - `BotControlledEnv`:
    - ajouter `agent_player` et `bot_player`
    - remplacer toutes les boucles `current_player == 2` par `current_player == bot_player`
    - verifier que la recompense retournee a SB3 reste celle du point de vue agent
  - `SelfPlayWrapper` (si utilise):
    - supprimer toute hypothese fixe P1/P2
    - aligner les compteurs de victoire avec `agent_player`

## 2) Moteur et config de controle

- `engine/w40k_core.py`
  - retirer hardcodes de `controlled_player=1` dans les branches training/eval
  - exiger une valeur explicite (ou erreur) quand mode seat-aware est actif
  - verifier coherence `controlled_player` dans `reset` et infos episode

## 3) Reward (source de signal PPO)

- `engine/reward_calculator.py`
  - remplacer les comparaisons `winner == 1` par logique relative au `controlled_player` effectif
  - verifier toutes les branches terminales (`win/lose/draw`)
  - verifier les rewards d'objectifs si indexees par joueur
  - retirer les fallback implicites de type `get("controlled_player", 1)` sur les chemins critiques

## 4) Metrics/callbacks (eviter faux positifs TensorBoard)

- `ai/metrics_tracker.py`
  - remplacer `winner == 1` par `winner == agent_player`
  - journaliser metriques separees:
    - `winrate_agent_p1`
    - `winrate_agent_p2`
    - `winrate_global`
- `ai/training_callbacks.py`
  - meme correction pour les logs directs model logger
  - ajouter compteurs episodes par side (`episodes_agent_p1`, `episodes_agent_p2`)

## 5) Observation et action-mask

- Fichiers de construction d'observation (selon votre architecture actuelle):
  - convertir les features absolues (P1-P2) en features agent-relatives (ally-enemy)
  - garantir schema stable independamment du seat
- Masque d'actions (`action_decoder` / wrappers):
  - verifier qu'un etat miroir renvoie une semantique d'actions miroir equivalente
  - ajouter checks explicites en debug en cas de mismatch P1/P2

## 6) Eval et scripts analyses

- `ai/analyzer.py` et scripts de stats/eval qui supposent `winner==1`
  - migrer vers logique `winner == agent_player`
  - versionner les sorties si format dashboard change

## 7) Validation minimale obligatoire (avant merge)

1. smoke train court en `p1`, `p2`, `random`
2. eval cross-seat avec meme seeds/scenarios/checkpoint
3. verifier:
   - `winner == agent_player` incremente bien les wins
   - rewards terminales signees correctement
   - distribution random P1/P2 dans la tolerance
   - pas de rupture de sens des metriques entre seats

## 8) Gate Go/No-Go

- Go uniquement si:
  - `WR(P2)` progresse ou se maintient sans effondrer `WR(P1)`
  - aucune hypothese residuelle critique P1-centree dans pipeline train/eval
  - logs par side disponibles et lisibles
- Sinon: stop, corriger, revalider.

---

## Decoupage PR par PR (execution recommandee)

Objectif: livrer de la valeur rapidement, avec risque maitrise et rollback facile.

## PR1 - Seat infrastructure + wrappers (bloquant)

Perimetre:

- `ai/train.py`
- `ai/bot_evaluation.py`
- `ai/env_wrappers.py`
- `engine/w40k_core.py` (uniquement points `controlled_player` lies train/eval)

Contenu:

- ajouter `agent_seat_mode` (`p1|p2|random`) + validation stricte
- resoudre `agent_player/opponent_player` par episode
- propager au wrapper train/eval
- remplacer hardcodes wrapper `current_player == 2` par `current_player == bot_player`
- journaliser side episode (`agent_player`) pour audit

DoD PR1:

- train smoke passe en `p1`, `p2`, `random`
- pas de crash/infinite loop wrappers sur les 3 modes
- distribution random observable (`%episodes_P1`, `%episodes_P2`)

No-Go PR1:

- toute hypothese implicite restante de bot fixe P2 dans wrappers

## PR2 - Reward + metrics + eval (integrite des signaux)

Perimetre:

- `engine/reward_calculator.py`
- `ai/metrics_tracker.py`
- `ai/training_callbacks.py`
- `ai/bot_evaluation.py` (compteurs resultats)
- scripts d'analyse critiques si relies au winrate principal

Contenu:

- remplacer logique `winner == 1` par logique `winner == agent_player`
- aligner rewards terminales win/lose/draw sur `controlled_player` effectif
- ajouter metriques par side:
  - `winrate_agent_p1`
  - `winrate_agent_p2`
  - `winrate_global`
- verifier coherence eval bots avec seat

DoD PR2:

- meme checkpoint, meme seeds/scenarios:
  - compteurs wins/losses corrects en `p1` et `p2`
- TensorBoard: metriques par side presentes et coherentes
- aucun fallback implicite critique sur seat (`get(..., 1)`) dans chemins train/eval/reward

No-Go PR2:

- courbes qui changent de sens selon le seat
- mismatch entre winner engine et compteur eval

## PR3 - Observation + action-mask invariance (qualite de generalisation)

Perimetre:

- builder(s) observation
- logique action-mask/action semantics (decoder/wrappers associes)

Contenu:

- convertir features absolues en agent-relatives (`ally - enemy`)
- verifier schema d'observation stable quel que soit seat
- verifier semantique action-space et masque en etat miroir P1/P2
- ajouter checks debug explicites pour detecter mismatch

DoD PR3:

- tests/diagnostics miroir sans inversion semantique
- pas de regression de performance brute training

No-Go PR3:

- une feature cle change de sens entre P1 et P2
- action-mask invalide sur un seat

## PR4 - Assets role-based (optionnel apres stabilisation)

Perimetre:

- scenarios/rosters + resolver de roles

Contenu:

- introduire `side: "agent" | "opponent"`
- mapping role -> player au reset selon seat
- compatibilite transitoire ancien format + nouveau format

DoD PR4:

- un meme asset tourne en `p1`, `p2`, `random`
- aucune regression sur matrice d'eval issue des PR1-PR3

No-Go PR4:

- rupture backward compatibility non assumee

---

## Ordre de merge et strategie de release

Ordre strict:

1. PR1
2. PR2
3. PR3
4. PR4 (si necessaire)

Regle de release:

- ne pas fusionner la PR suivante tant que les DoD/No-Go de la precedente ne sont pas valides
- garder un benchmark fixe (seeds/scenarios/checkpoint) pour comparer chaque PR

---

## Matrice de verification finale (post PR3 minimum)

- Train:
  - `agent_seat_mode=p1`
  - `agent_seat_mode=p2`
  - `agent_seat_mode=random`
- Eval (meme checkpoint):
  - `WR(P1)`, `WR(P2)`, `WR(global)`
  - compteurs episodes par side
- Decision:
  - promotion uniquement si gain `WR(P2)` sans collapse material de `WR(P1)`

