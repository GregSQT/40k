# Deux lots issus du chantier `units_cache` — ménage V10 pile-in, et perf de la charge — 2026-08-05

**Lot A : CLOS** (fusion `b898bb95`). **Lot B : OUVERT**, pas commencé.

⚠️ Ce document reste dans `A_faire/` tant que le lot B n'est pas traité. Ne pas le déplacer
dans `Implémenté/` : il porte encore du travail.

**Origine** : sortis du lot `units_cache`
([`replis_units_cache_2026-08-05.md`](../replis_units_cache_2026-08-05.md) §8.4 et §9). Ce
document-ci porte le **détail exploitable** — chaîne morte tracée, protocole de mesure, prompts —
que ces deux paragraphes ne donnent pas.

| Lot | Worktree | Base | État |
|---|---|---|---|
| ~~A — ménage V10 pile-in / consolidation~~ ✅ | `menage_v10_frontend` | — | **CLOS** : partie 1 `b8c5e0ef`, chaîne morte `b898bb95` |
| B — perf boucle de collision de charge | `perf_collision_charge` | `34b94c3d` | non commencé |

⚠️ Les deux worktrees ont été créés AVANT ce document ET avant la fusion `b8c5e0ef`. Faire
`git merge main` dedans avant de commencer — sinon l'agent du lot A refera du travail déjà
présent dans `main`.

---

## Lot A — Ménage V10 pile-in / consolidation

### A.1 Ce qui est DÉJÀ fait — **dans `main`** depuis la fusion `b8c5e0ef`

- Moteur : `_fight_v11_clear_pile_in_preview` supprimée + ses 4 appels. Elle ne faisait plus que
  `pop` deux clés que plus aucun écrivain ne produit.
- `useEngineAPI.ts` : les deux branches V10 mortes retirées (pile-in ~39 l., consolidation ~50 l.),
  et les trois conditions `!waiting_for_*` devenues toujours vraies simplifiées.

Un commentaire rendu faux par la suppression a été corrigé au merge (il renvoyait aux branches
V10 disparues).

**Vérifié sur l'arbre fusionné** : pyright 0, pytest 0 (71 tests), tsc 0.
**NON vérifié** : l'essai PvP réel — aucun test de rendu n'existe sur ces fichiers.

⚠️ **Conséquence du merge partiel, à connaître avant de reprendre** : `main` contient désormais
2 modes UI (`pileInPreview`, `consolidationPreview`) qu'aucun code ne peut plus atteindre, et
~26 sites qui les lisent. Ce n'est pas cassé, c'est du mort que plus rien ne signale — d'où
l'intérêt de ne pas laisser traîner le §A.3.

### A.2 Le constat qui fonde le lot — ne PAS refaire l'enquête

Le moteur ne produit plus **aucune** de ces clés (grep `engine/` + `services/` → 0 producteur) :

```
waiting_for_pile_in            valid_pile_in_destinations
waiting_for_consolidation      valid_consolidation_destinations
fight_pile_in_footprint_zone   fight_consolidation_footprint_zone
_fight_v11_pile_in_dests
```

🔴 **Le chemin VIVANT, à ne surtout pas toucher** : le pile-in et la consolidation PvP passent par
le **V11 par-figurine** — `pile_in_model_move` / `consolidation_model_move` + `plan_state`, modes
`pileInModelMove` / `consolidationModelMove`. **L'aperçu fonctionne.** Une première rédaction de
§8.4 avait conclu l'inverse (« ce voile ne peut plus s'afficher ») en s'arrêtant à « plus
d'écrivain » sans chercher si un autre chemin servait la fonctionnalité : c'était faux. *Constater
la mort d'un symbole n'est pas constater la mort d'une fonctionnalité.*

### A.3 La chaîne morte, tracée — ✅ TRAITÉE (fusion `b898bb95`)

`setMode("pileInPreview")` et `setMode("consolidationPreview")` n'existaient QUE dans les deux
branches supprimées. Ces deux modes sont donc **inatteignables**, et tout ce qui en dépend est du
code conditionnel jamais exécuté :

| Cible | Où |
|---|---|
| ~26 sites de lecture des 2 modes | `BoardPvp.tsx`, `BoardDisplay.tsx`, `boardClickHandler.ts`, `types/game.ts` |
| unions de type `mode` | `types/game.ts`, `useEngineAPI.ts`, `BoardPvp.tsx` |
| branche de clic | `boardClickHandler.ts` — `(mode === "pileInPreview" \|\| mode === "consolidationPreview")` |
| handlers | `handlePileInMove`, `handleSkipPileIn` (`useEngineAPI.ts`) |
| props threadées à ≥4 niveaux | `onPileInMove`, `onSkipPileIn` (`BoardPvp.tsx`) |
| 3 clés mortes + leur typage | `types/game.ts`, `useEngineAPI.ts` |

**Le contrôle du dernier maillon a été fait, et il a tranché dans l'autre sens** : les actions
moteur `"pile_in"` / `"consolidation"` de `w40k_core` sont **conservées** — elles servent le
chemin gym (`_gym_commit_fight_move`). Le mort ne remontait donc PAS au backend. C'est le genre
de vérification qui évite de casser l'entraînement en croyant nettoyer l'UI.

### A.4 Bilan

−245 lignes sur 6 fichiers. Vérifié : pyright 0, tsc 0, biome 0, tests ciblés au vert.
Deux erreurs biome **préexistantes** (commit WIP `3a2a67c1` — dépendance `isDeploymentMove`
manquante, `setError` Ingress/Deploy à reformater) ont été corrigées au passage : `biome check`
passe désormais à 0 sur `main`.

⚠️ **Ce qui n'a PAS été validé** : l'essai PvP réel. Il n'existe aucun test de rendu sur
`BoardPvp.tsx` / `BoardDisplay.tsx` ; `tsc` vert prouve seulement que rien ne casse au typage.
L'aperçu pile-in PvP passe par le chemin V11 par-figurine, laissé intact et vérifié présent —
mais seul un essai le confirme.

---

## Lot B — Boucle de collision de `_hex_legal_for_charge`

### B.1 Ce qui est déjà fait, et à ne pas refaire

Commit `8f81cee4` : le joueur de l'escouade chargeuse et la liste des ennemis non-ciblés sont
résolus **une fois** dans `charge_build_valid_plan` et passés en paramètre
`non_target_enemy_entries`. Gain : 1 balayage de `units_cache` au lieu de ~14 641, et `E` lookups
au lieu de ~14 641 × `E`.

### B.2 Ce qui reste

La boucle de **collision** n'a pas été touchée :

```python
for _sid, entry in entries_on_battlefield(units_cache, exclude_id=squad_id):
    if cell in entry_footprint(entry):
        return False
```

Elle réénumère TOUTES les escouades et reconstruit l'empreinte de chacune, **à chaque cellule**,
pour répondre « cette case est-elle occupée ? ». Le résultat est invariant sur tout le plan :
`units_cache` n'est pas muté entre le début de `charge_build_valid_plan` et la fin des BFS.

Forme visée : précalculer une fois l'union des cases occupées dans un `set`, la passer en
paramètre, et remplacer la boucle par `if cell in occupied`. Strictement équivalent
(`cell ∈ union(empreintes)` ⟺ `∃ empreinte, cell ∈ empreinte`).

Pourquoi c'est chaud : `_hex_legal_for_charge` est appelée **par cellule** dans les deux BFS (le
commentaire du fichier chiffre le pire cas à ~14 641 itérations par anneau, pour chaque figurine),
et `charge_build_valid_plan` est sur le chemin RL — `observation_builder.py:1420`, à chaque step.

### B.3 Protocole de mesure — IMPOSÉ, ne pas corriger avant

Le benchmark doit construire un roster de **taille réaliste** : le duo chargeur/cible des tests
unitaires masque le coût, il n'a que 2 entrées dans `units_cache`. Mesurer à 2, 12 et 22 escouades.

```python
"""Compte les appels RÉELS et le temps mur sur un charge_build_valid_plan."""
import sys, time
sys.path.insert(0, "<racine du worktree>")
from tests.unit.engine.test_charge_and_pile_in_follow_the_path import _unit, _gs
from engine.phase_handlers import shared_utils as su

CALLS = {"eob": 0, "fp": 0}
_real_eob, _real_fp = su.entries_on_battlefield, su.entry_footprint
def _c_eob(*a, **k):
    CALLS["eob"] += 1; return _real_eob(*a, **k)
def _c_fp(*a, **k):
    CALLS["fp"] += 1; return _real_fp(*a, **k)

def build(n):
    units = [_unit("1", 1, [(26, 20), (26, 21), (26, 22)]), _unit("101", 2, [(34, 20)])]
    for i in range(n):
        c, r = 5 + (i % 10) * 4, 45 + (i // 10) * 3
        units.append(_unit(f"b{i}", 1 if i % 2 else 2, [(c, r), (c, r + 1)]))
    return _gs(units, [], "charge")

def measure(n, roll):
    gs = build(n); CALLS["eob"] = CALLS["fp"] = 0
    su.entries_on_battlefield, su.entry_footprint = _c_eob, _c_fp
    try:
        t0 = time.perf_counter()
        plan = su.charge_build_valid_plan(gs, "1", ["101"], roll)
        dt = time.perf_counter() - t0
    finally:
        su.entries_on_battlefield, su.entry_footprint = _real_eob, _real_fp
    return dt, dict(CALLS), plan is not None

for n in (0, 10, 20):
    for roll in (8, 12):
        print(n + 2, roll, *measure(n, roll))
```

1. Mesurer AVANT, publier le tableau. 2. Corriger. 3. Re-mesurer, publier.
4. **Si le gain n'est pas net, le DIRE et proposer d'annuler** : un refactor de chemin chaud sans
   gain mesuré n'a pas à être livré.

### B.4 Verrou

Test qui CONSTRUIT une géométrie où une case est occupée par une escouade tierce et vérifie
qu'elle est refusée, plus la contre-épreuve sans cette escouade. Prouver par mutation : remettre
l'ancienne boucle, voir le test ROUGE, rétablir, le rapporter.

---

## Pièges d'outillage — vécus dans la session qui a produit ces lots

🔴 **Un worktree n'a PAS de `node_modules`.** Avant `tsc` / `biome` :
```bash
[ -e frontend/node_modules ] || ln -s /home/greg/40k/frontend/node_modules frontend/node_modules
```
Sans ça, l'outil échoue sur des dépendances absentes — pas sur le code.

🔴 **Lire le code de sortie, jamais la sortie visuelle.** Deux fois dans la même session un lot de
tests a été annoncé vert sans avoir tourné : `pytest … | tail` renvoie le code de `tail` (toujours
0), et un chemin de test inexistant sort en erreur avec une sortie VIDE qui ressemble à un succès.
Rediriger vers un fichier, puis `echo "CODE = $?"`. `5` = aucun test collecté, pas « tout va bien ».

🔴 **`biome` sort DÉJÀ en 1 sur `main`** (constaté à `4636b7ea`) : 2 erreurs issues du commit WIP
`3a2a67c1` — `BoardPvp.tsx:4421` (dépendance de hook manquante) et un `setError` Ingress/Deploy à
reformater. Ne pas les attribuer à ces lots.

🔴 **Balayage de code mort** : énumérer par parcours disque, **jamais** `git ls-files` (il ignore
les fichiers non suivis — un test neuf non commité fait passer une fonction vivante pour morte), et
**exclure `tests/` du décompte des appelants** (sinon un test suffit à faire paraître vivante une
fonction morte : c'est arrivé, cf. §8.3 du document d'origine).

## Borne du verdict — non négociable sur le lot A

Il n'existe **aucun** test de rendu sur `BoardPvp.tsx` / `BoardDisplay.tsx`. `tsc` vert prouve
seulement que rien ne casse au typage. Ne jamais écrire que l'aperçu pile-in « fonctionne » :
seul l'essai PvP de l'utilisateur le dit. Conclure par « reste à valider en PvP ».
