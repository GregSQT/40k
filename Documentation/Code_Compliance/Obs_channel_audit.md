# scripts/obs_channel_audit.py — Le moteur remplit-il, et le réseau lit-il, chaque canal de l'obs ?

> **Usage** : `python3 scripts/obs_channel_audit.py` (venv projet activé)
>
> **Entrées** : les scénarios de `config/agents/ArmageddonAgent/scenarios/training/`, découverts par
> glob (`scenario_training_*.json`) — aucune liste à tenir à jour.
> **Sortie** : rapport console. Aucune écriture : ni config, ni modèle, ni state.
> **Durée** : ~15 min (24 épisodes en actions masquées aléatoires + une passe de gradient).

---

## Objectif

Une observation peut être fausse de deux façons que ni les tests ni l'entraînement ne signalent :

1. **le moteur n'écrit pas le canal** — le champ existe, il vaut toujours la même chose ;
2. **le réseau ne lit pas le canal** — le champ arrive bien à la policy, mais aucun chemin de
   calcul ne le consomme.

Les deux sont **silencieux par construction** : l'entraînement converge, les tests passent, et
l'agent apprend simplement sans l'information. Le défaut fondateur de cet outil est le drapeau
`fought` de `UNIT_BIN_FIELDS`, éteint **des deux camps pendant tout le pipeline squad** :
`observation_builder` le lisait dans `game_state["units_attacked"]`, une clé que quatre sites
créaient et remettaient à zéro et qu'**aucun écrivain n'a jamais peuplée** (mesuré : 0 step sur
2455). La clé vivante était `units_fought`. Corrigé le 2026-08-08 ; la clé morte est supprimée.

Ce script mesure les deux propriétés au lieu de les déduire.

---

## Volet A — le MOTEUR remplit-il ?

24 épisodes (chaque scénario de la banque × 12 graines), actions masquées aléatoires sur le vrai
`W40KEngine`. Pour **chaque clé d'observation et chaque champ de son registre** : min, max,
fraction non nulle. Les libellés viennent des registres (`observation_entities.py`,
`observation_weapon_profiles.py`, `spatial_grid.GRID_CHANNEL_NAMES`), jamais d'une liste recopiée
— un canal inséré au milieu ferait sinon mentir tout le rapport.

**Un champ dont `min == max` sur tout le corpus est un canal que le moteur ne remplit pas.**

Trois familles se ressemblent dans la sortie et ne se traitent pas pareil :

| Ce qu'on lit | Ce que c'est | Quoi faire |
|---|---|---|
| Slot d'ids au-delà du nombre observé, colonne `*_reserved_*` | **pré-dimensionnement voulu** (une capacité ajoutée reste gratuite) | rien |
| Champ à masque de camp (`enemies.is_ally`, `allies.los_can_see`, `enemies.hidden`…) | **zéro par contrat** (§3.3 : les features propres à un camp sont nulles pour l'autre) | rien |
| Champ censé varier et qui ne varie pas | **canal mort, ou sans signal sur ce terrain** | investiguer |

La troisième famille demande une mesure de plus avant de conclure : un canal peut être
correctement câblé et pourtant sans signal. Deux cas mesurés le 2026-08-08, tous deux réels et
tous deux **non** des bugs de code :

- `deploy_cand_cont.los_exposure` / `potential_los_exposure` toujours nuls — les deux zones de
  déploiement sont à ~290 subhex et la LoS sol ne passe jamais entre elles ;
- `cover_vs_observer` toujours nul côté ennemi — sur 2583 paires, les 146 visibles étaient
  **toutes** `fully_visible` : 13.08 ne peut pas s'appliquer à une cible que 13.10 masque déjà.

---

## Volet B — le RÉSEAU lit-il ?

La vraie policy (`PointerMaskablePolicy` + `SpatialCombinedExtractor`), avec l'architecture **lue
dans le JSON de l'agent** (`model_params.policy_kwargs`), sur un échantillon de réservoir des
observations du volet A (uniforme sur tout le corpus — sans quoi les champs de combat sortiraient
« non lus » faute d'avoir été échantillonnés). On rétropropage `Σ logits + Σ valeur`.

**Un champ dont le gradient est exactement nul est reçu mais jamais lu.**

Trois précautions, sans lesquelles le volet B ment :

- **Échauffement des statistiques.** `EntityRunningNorm` clippe à ±10 σ. Avec les statistiques
  d'initialisation (mean=0, var=1), toute feature d'échelle > 10 saturerait et sortirait un
  gradient nul — faux positif. Une passe `train()` suffit : c'est un accumulateur de Chan, pas une
  moyenne mobile, donc la première passe pose déjà les statistiques exactes du lot.
- **Saturation rapportée par champ**, sur les seules entités **présentes**. Compter les lignes de
  padding ferait passer pour saturée toute feature proche d'une constante.
- **Clés d'ids** (`*_ability_ids`, `*_status_ids`, `*_wpn_rule_ids`) : non différentiables. Elles
  sont vérifiées sur le gradient des **lignes d'`EmbeddingBag`** correspondant aux ids observés.

---

## Interpréter la sortie

- `champs à gradient EXACTEMENT nul` → `(aucun)` : tout ce que le moteur écrit atteint le réseau.
- Un champ y apparaît avec `(déjà constant en A)` : le moteur ne l'écrit pas — c'est le volet A
  qu'il faut traiter, pas le réseau.
- Un champ y apparaît avec `<-- VARIABLE mais NON LU` : **c'est le cas grave.** Le moteur produit
  de l'information que l'extracteur jette (clé absente de son `expected_keys`, tranche mal
  découpée, masque qui annule l'entité).
- `grille : couverture par canal` : les 9 canaux doivent être non nuls. `level` reste à 0 si aucun
  terrain de la banque ne déclare d'étage ; `move_cost` reste à 0 hors phase de mouvement.
- `clés d'ids` : `lignes avec gradient` doit égaler `ids observés`.

---

## Quand le relancer

- **Après tout ajout de champ d'observation** — c'est sa raison d'être : le champ neuf doit
  apparaître variable en A et lu en B.
- Après une modification de `spatial_extractor.py` ou `pointer_policy.py` (une tranche décalée
  déconnecte une famille entière sans que rien ne lève).
- Après un changement de terrain ou de roster de la banque : le corpus change, donc les canaux
  « sans signal sur ce terrain » aussi.

⚠️ **Le script ne gate rien** : il imprime, il ne rend pas de code d'erreur sur un canal mort, et
il n'appartient pas à la commande de vérification large. Le lire fait partie de la tâche. Lui
donner une sortie non nulle contre une liste d'exemptions déclarée reste ouvert.

---

## Voir aussi

- `Documentation/AI_OBSERVATION.md` — ce que chaque canal signifie.
- `engine/observation_entities.py` — les registres, source unique des noms de champs.
- `Documentation/Code_Compliance/Hidden_action_finder.md` et `AI_RULES_checker.md` — les deux
  autres outils de conformité, eux dans la commande de vérification de l'utilisateur.
