# Campagne de code review — guide

Outil : `scripts/review_plan.py`. Il **pilote** la campagne, il ne review rien lui-même.

---

## 1. Ce que le script fait, et ce qu'il ne fait pas

| Il fait | Il ne fait pas |
|---|---|
| classer les fichiers par risque | lancer `/code-review` (impossible : commande de l'hôte, pas appelable depuis un script) |
| tenir l'avancement (à faire / en cours / fait + commit) | lancer `/simplify` |
| accumuler les arbitrages en append-only | lancer la suite de tests |
| | modifier du code |

Trois fichiers générés dans `Documentation/` :

- `review_backlog.json` — **source de vérité**, ne pas éditer à la main
- `review_backlog.md` — rendu lisible, régénéré à chaque écriture
- `review_arbitrages.md` — **append-only**, jamais réécrit : c'est ce qui survit à un plantage

---

## 2. Pourquoi le classement est un simple tri par taille

Mesuré sur ce dépôt le 2026-08-06 : 186 commits de correction, 12 519 lignes supprimées
datées par `git blame`, holdout temporel (93 fix pour dériver, 93 pour prédire).

Corrélation de Spearman avec les lignes réellement corrigées ensuite :

```
taille seule               +0.627   <- gagnant
churn x taille             +0.600
âge pondéré par bande      +0.583
churn seul                 +0.485
lignes corrigées passées   +0.480
densité corrections/kloc   +0.333
```

**Aucune pondération ne bat `wc -l`.** Churn, âge du code et historique de bugs ont été
testés et rejetés. Ne pas les réintroduire dans le score sans refaire la mesure — la
méthode complète est dans la docstring de `scripts/review_plan.py`.

Sur l'âge, la mesure a quand même donné un résultat (hors boucle write-debug < 6 h, qui
pèse 17 % des lignes corrigées et n'est pas reviewable) : code récent **sous**-représenté
dans les bugs (0,66–0,68x), code > 6 mois aussi (0,84x), pic à **3–6 mois (1,94x)**.
Signal réel, mais instable d'une fenêtre à l'autre → pas utilisable pour scorer.

**Colonnes du classement**

- `lignes` — le seul critère de tri
- `passes` — nombre de passes de review estimées, à ~2000 lignes chacune
- `churn` — nombre de commits touchant le fichier sur la fenêtre. **Informatif seul** :
  il ne sert qu'à départager deux fichiers de taille voisine (à 2000 lignes chacun,
  celui à churn 90 passe avant celui à churn 3).

---

## 3. Commandes

```bash
python3 scripts/review_plan.py rank --top 40     # explorer, n'écrit rien
python3 scripts/review_plan.py sync --top 25     # (re)génère le backlog
python3 scripts/review_plan.py status            # où j'en suis

python3 scripts/review_plan.py start <fichier>
python3 scripts/review_plan.py done  <fichier> --commit <sha>
python3 scripts/review_plan.py note  <fichier> "<arbitrage>"
python3 scripts/review_plan.py arbitrages
```

`sync` **fusionne** : il rafraîchit lignes/churn sans écraser un `doing` ou un `done`, et
conserve une cible engagée même si elle sort du top. Un chemin inconnu lève une erreur
avec la liste des cibles — pas d'ajout implicite.

`--since` ne pilote que la colonne churn (informative). Le tri n'en dépend pas.

---

## 4. La méthode — un cycle par cible

**Une cible = un commit atomique = un rollback propre.** Ne jamais empiler deux cibles
avant une vérif large : à la première régression, tu ne saurais plus laquelle l'a causée.

| # | Étape | Qui |
|---|---|---|
| 1 | `git status --short` doit être propre. Sinon, commiter ou stasher d'abord. | toi |
| 2 | Worktree dédié si la cible est grosse (≥ 3 passes) | toi |
| 3 | `review_plan.py start <fichier>` | toi |
| 4 | `/code-review <fichier>` | **toi** — commande de l'hôte, un agent ne peut pas la lancer |
| 5 | Tri des findings : garder ceux qui ont un **scénario d'échec concret** (entrées/état précis → sortie fausse, crash ou invariant violé, sur un chemin réellement atteint). Les autres sont **écartés**, pas rétrogradés en « mineurs ». | agent |
| 6 | Correction des findings retenus | agent |
| 7 | **grep JUMEAU** sur chaque motif corrigé : tir/mêlée, move/charge/fight, IA/PvP, moteur/replay/analyzer, front/back. Résultat rapporté même s'il est vide. | agent |
| 8 | Tests ciblés sur les fichiers touchés (`pytest tests/unit/engine/test_xxx.py`) | agent |
| 9 | **Vérif large** — voir la commande complète dans `CLAUDE.md` | **toi** |
| 10 | Commit, merge, suppression du worktree | toi |
| 11 | `review_plan.py done <fichier> --commit <sha>` | toi |

À l'étape 5, tout ce qui demande une décision qui t'appartient (choix métier, priorité,
budget, donnée que toi seul as) part dans `note`, pas dans le code. Et un `note` qui décrit
une tâche technique que l'agent savait faire est une dette déguisée — ça n'y a pas sa place.

---

## 5. Découpage des gros fichiers

`/code-review` prend un fichier, pas une plage de lignes. La colonne `passes` est donc une
**estimation d'effort**, pas une commande exécutable.

Méthode : lancer la review sur le fichier entier, puis juger au rendu.

- Findings avec scénario → le découpage était une précaution inutile sur ce fichier, on continue.
- Une poignée de findings cosmétiques sur 7000 lignes → symptôme du survol. On découpe alors
  le fichier en zones fonctionnelles et on repasse ciblé zone par zone.

C'est le seul point de la méthode qui reste empirique. Les 5 plus gros fichiers
(`BoardPvp.tsx`, `shared_utils.py`, `useEngineAPI.ts`, `w40k_core.py`, `charge_handlers.py`)
y passeront à coup sûr.

---

## 6. Ordre conseillé

Ne pas suivre le classement à la lettre. Le tri par taille dit **où** est le risque, pas
**par quoi commencer**.

1. **`engine/w40k_core.py`** (7180, 4 passes) ou `engine/game_state.py` (4292, 3 passes) —
   cœur du moteur, les findings y ont le plus de portée, et l'ampleur reste assez modeste
   pour valider que le cycle fonctionne avant de s'engager plus loin.
2. **Les paires miroir, groupées** — c'est là que le motif JUMEAU se vérifie :
   `shooting_handlers` + `fight_handlers`, `movement_handlers` + `charge_handlers`.
   Reviewer les deux dans le même cycle, sinon la correction d'un côté sans l'autre est
   exactement le défaut le plus fréquent de ce dépôt.
3. **Le frontend** (`BoardPvp.tsx`, `useEngineAPI.ts`, `BoardWithAPI.tsx`) — 28 000 lignes
   à eux trois, 15 passes. À aborder une fois le cycle rodé.
4. Le reste, par taille décroissante.

**Hors périmètre**, décidé et mesuré :

- `frontend/src/roster/**` — définitions d'unités, ce sont des données ; une review y rendrait du bruit
- `tests/**` — un test n'a pas de scénario d'échec en production, donc presque rien n'en sortirait
  qui survive au tri de l'étape 5. Exception : `conftest.py` et fixtures partagées, dont un bug
  contamine les autres tests
- Fichiers < 200 lignes — pas de passe dédiée, ils se reviewent avec leur appelant
