# Training — Tâches ouvertes

---

## Critères pipeline du run en cours (ex-« run x1 de vérification ») {#run-verif}

Un run `x1` de vérification dédié avait été décidé le 2026-08-11 pour prouver que le pipeline
tourne avec l'espace de décision modifié. Le run `x1_long --new` lancé le 2026-08-17
([bot.md#etape8](bot.md#etape8)) embarque le même code à HEAD : **les critères se lisent sur SES
courbes**, un run séparé n'a plus d'objet sauf si celui-ci échoue.

✅ Critères vérifiés sur le run `x1_long --new` du 2026-08-20 :

- ✅ `game_critical/invalid_action_rate` reste à **0**
- ✅ `02_combat/m_charge_attempts` **non nul**
- ✅ `02_combat/n_charge_success_rate` **non nul** (en V11 la déclaration est gratuite — l'agent déclare « au cas où » puis choisit ses cibles après le jet ; un taux bas ne signifie pas un dysfonctionnement)
- ✅ Courbes `reserves/*` et `05_charge/*` **peuplées** (`charge_distance/*` était le nom de la clé interne, le tag TensorBoard réel est `05_charge/*`)

⚠️ Pour tout re-run : `--new` et non `--append` — `--append` réapplique `ent_coef = 0,1` et écrase le modèle canonique.

---

## 🔴 Curriculum R1→R3 — séquence des runs {#curriculum}

**Décision utilisateur 2026-08-21 — priorité haute.** Le curriculum démarre dès R0a+R0b livrés
([bot.md#r0a-references](bot.md#r0a-references), [bot.md#r0b-echelle](bot.md#r0b-echelle)).
**Un levier par run** :

- **R1** — run de référence `x1_long --new`, rien d'autre ne bouge : ligne de base du
  curriculum (panel + references réparées + `vs_ckpt`) et premier barreau d'échelle.
- **R2** — mix self-play (= chemin critique ligne 7, §0.59) : profil dérivé de `x1_long`,
  clés `self_play_*` récupérables au git (`x1_selfplay` purgé par `18dc8599`) ; parts
  proposées NON MESURÉES ~55-60 % doctrine / 25-30 % self / 15 % random, à trancher au chantier.
- **R3** — levier récompense ([bot.md#recompense](bot.md#recompense)), jamais dans le même
  run que R2.

→ `Documentation/Chantiers/backlog/curriculum_adversaires_etalons.md` §5-7

---

## Mode exploiteur E1/E2/E3 {#exploiteur}

**Livré 2026-08-22.** `--etape E1/E2/E3` mesure l'exploitabilité de sa cible (P3, P5, P8) :
budget = épisodes pour passer de 50 % à 70 % de win-rate contre la cible figée.

- `ExploiterProbeCallback` : sonde synchrone tous les 2000 épisodes (100 ép. bon marché →
  une seule confirmation de 500 ép.), sans Future ni ThreadPoolExecutor.
- `validate_exploiter_protocol` : refuse le run si `training_config`, `ratio`, `warmup`
  ou `profile_total_episodes < budget_cap` divergent du protocole gelé (`exploiter_config`).
- `curriculum.log` : budget entier ou `'>50000'` (censuré) + courbe win_rate complète.
- 28 tests verrou (4 verrous : refus protocole, budget_cap atteignable, pas de sonde abandonnée, valeur censurée).
- `training_config_required` : `x1_long` (50 000 épisodes = `budget_cap`).

Lancer : `python3 ai/train.py --agent ArmageddonAgent --training-config x1_long --scenario bot --etape E1`

---

## É9 — Second siège + second scénario {#e9}

**Suspendu** — après entraînement bot satisfaisant (jalon J4). Second scénario écrit par l'utilisateur (décision 2026-08-02).

→ `Documentation/Chantiers/v11/index_v11.md` §0.47

**2026-08-28 — levier d'exposition livré, indépendamment de É9.** `agent_seat_p2_ratio` rend pondérable le tirage de siège en entraînement (il était figé à 50/50 par la parité d'un hachage) ; réglage posé à 0.65 sur les six profils. Motivation : 12 points d'écart p1/p2 mesurés sur le run x1_long du 2026-08-12. L'évaluation garde son tirage équitable. É9 reste ouvert : il porte le second SCÉNARIO, que ceci ne traite pas. Effet à mesurer au prochain run — voir `Documentation/Reference/training/entrainement.md`.
