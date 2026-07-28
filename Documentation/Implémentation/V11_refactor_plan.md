# V11_agent_rework.md — Plan d'extraction en sous-documents (EXÉCUTABLE PAR AGENT, séquentiel)

> **But.** Réduire `V11_agent_rework.md` (**6603 lignes / 531 Ko** au 2026-07-28) à un **index
> d'état** (à faire / fait + méthode + historique), en sortant la **spec** (§1→§10) dans 3
> sous-docs pointés depuis l'index. Pattern déjà validé : §0.22 →
> [`Implémenté/V11_move_pool_optimization.md`](Implémenté/V11_move_pool_optimization.md).
>
> **Statut : PRÊT À EXÉCUTER (remis à jour le 2026-07-28).** Le prérequis « attendre la passe
> move_pool » de la version du 2026-07-21 est **levé** (§0.22 clos, pointeur recâblé). Seule
> contrainte de timing restante : **hors run d'entraînement** et **un seul agent à la fois** sur
> ce fichier.
>
> **Décision Option A — TRANCHÉE le 2026-07-21, inchangée** : l'historique (§0hist) RESTE dans
> l'index. On n'extrait que la spec §1→§10. L'historique EST l'inventaire du fait.

---

## 1. Ce que l'agent exécutant doit savoir AVANT de commencer

- **NE JAMAIS lire le fichier en entier** (531 Ko ≈ exploserait le contexte). Travailler par
  plages : `sed -n 'A,Bp'` pour lire une zone, `grep -n` pour localiser. Les numéros de ligne
  ci-dessous datent du 2026-07-28 : **toujours re-localiser par grep du titre de section** avant
  d'éditer.
- **Aucune réécriture de contenu.** On DÉPLACE des blocs et on RECÂBLE des liens. On ne corrige
  pas la prose (sinon on mélange deux natures de diff).
- **Un sous-doc = un commit.** Diff lisible, réversible bloc par bloc.
- ⚠️ **Faux positifs de renvois** : un `§x.y` accompagné d'un nom de fichier explicite
  (« §8.3 de `move_action_space_spatial_rework.md` », « §3 de `V11_move_build_acceleration.md` »,
  « §1.9 du chantier ») pointe vers CET AUTRE fichier → **ne pas le recâbler**. Vérifier le
  contexte de chaque renvoi avant recâblage ; les comptes du §3 ci-dessous sont des majorants.

## 2. Structure actuelle (frontières mesurées le 2026-07-28)

> **AVANCEMENT — ✅ PLAN TERMINÉ le 2026-07-28.** Étapes **1** (`db75417e`), **2** (`5e93fedd`),
> **3** (`cb77f6a6`) et **4** (ce commit). Index passé de **6618 → 4094 lignes** ; **2524 lignes**
> sorties dans 3 sous-docs. Le tableau ci-dessous est celui d'AVANT extraction, conservé comme
> trace de la mesure d'origine.

| Lignes | Section | Destin |
|---|---|---|
| 1-35 | Titre + encadré pointeurs | reste (index) |
| 36-444 | §0 État (tableau + entrées ouvertes, dont §0.40) | reste |
| 445-838 | §0bis Pièges/leçons (canonique) | reste |
| 839-855 | §0ter Notes post-impl | reste |
| 856-1010 | §1 Objectif + §1bis L'ANCRE | → `V11_tranches.md` |
| 1011-2531 | §2→§8 (état des lieux, ruptures, décisions, tranches T1-T7, critères, smoke, tests) | → `V11_tranches.md` |
| 2532-3193 | §9 Phase A' (P1-P5) | → `V11_phaseA.md` |
| 3194-3415 | §10 Stratégie éval/rosters | → `V11_eval_strategy.md` |
| 3416-6618 | §0hist Historique résolu | reste (Option A) |

Index final attendu ≈ **4060 lignes** (855 de tête + 3200 d'historique) ; **2560 lignes** sortent.

## 3. Coût de recâblage (re-mesuré le 2026-07-28 par script, majorants — cf. faux positifs §1)

| Extraction | Fichier cible | Liens ENTRANTS à recâbler (index→sous-doc) | Liens SORTANTS (sous-doc→index, `§0.x` → lien fichier) | Inter-sous-docs |
|---|---|---|---|---|
| §9 | `V11_phaseA.md` | **17** (9 depuis §0*, 6 depuis §0hist, 2 depuis tranches) | **8** | 5 vers tranches |
| §10 | `V11_eval_strategy.md` | **56** (10 depuis §0*, 44 depuis §0hist, 2 depuis tranches) | **8** | — |
| §1→§8 | `V11_tranches.md` | **53** (14 depuis §0*, 34 depuis §0hist, 5 depuis §9) | **29** | 2 vers §9, 2 vers §10 |

(Ancienne mesure du 2026-07-21 : 87 entrants sur 4399 lignes — périmée, le doc a pris +50 % et
11 entrées §0.29→§0.39 depuis.)

## 4. Convention de recâblage (robuste aux titres à accents/emoji) — inchangée

1. Poser une **ancre HTML explicite** juste avant chaque titre déplacé cité de l'extérieur :
   `<a id="s10.6"></a>` avant `### 10.6 …` (convention : `s` + numéro sans `§`).
2. Recâbler les renvois entrants en lien de fichier : `§10.6` → `[§10.6](V11_eval_strategy.md#s10.6)`.
3. Dans le sous-doc, recâbler ses renvois vers l'index : `§0.14` → `[§0.14](V11_agent_rework.md#...)`
   (les ancres `### 0.x` de l'index existent déjà, id auto-généré markdown ; si douteux, poser
   aussi une ancre HTML côté index).
4. Les renvois INTERNES au sous-doc restent du texte `§x.y` nu.
5. Chaque sous-doc démarre par un en-tête : origine (« extrait de `V11_agent_rework.md` le
   AAAA-MM-JJ »), rôle, et lien retour vers l'index.

## 5. Étapes séquentielles (1 étape = 1 session d'agent = 1 commit)

**Chaque étape est calibrée pour tenir dans le contexte d'UN agent** : elle ne lit que la zone
extraite + les lignes touchées par le recâblage (hits de grep), jamais le fichier entier.

### Étape 1 — `V11_phaseA.md` (§9) — ✅ FAITE le 2026-07-28 (commit `db75417e`)

Réalisé : 659 lignes déplacées telles quelles, ancres `s9`→`s9.6`, **17 entrants** recâblés dans
l'index, **9 sortants** (`§0.19`, `§0.19.3`, `§0.30`, `§0.31`×2, `§0.32`, `§0.38`, `§8.5`) recâblés
vers l'index — `§8.5` est **provisoire** (noté dans l'en-tête du sous-doc, à re-pointer étape 3).
Faux positifs laissés nus car ils citent leur fichier : `§8` (`V11_audit_observation.md`),
`§6` (`V11_entity_encoder_pointer.md`), `§1.9` (chantier encodeur).

- Périmètre : ~660 lignes déplacées, 17+8 liens. Contexte : PETIT (~40 Ko lus).
- Localiser : `grep -n '^## 9\.' V11_agent_rework.md` (début) et `grep -n '^## 10\.'` (fin).
- Déplacer §9 intégral → `V11_phaseA.md` (+ en-tête d'origine, cf. §4.5).
- Recâbler : `grep -n '§9' V11_agent_rework.md` → transformer chaque hit restant en lien fichier
  (vérifier le contexte : exclure les faux positifs). Dans `V11_phaseA.md`, recâbler ses `§0.x`
  et laisser une note pour ses renvois vers §1-§8 (encore dans l'index à ce stade — les recâbler
  provisoirement en `V11_agent_rework.md#...`, l'étape 3 les re-pointera).
- Done quand : garde-fou (§6) vide pour `§9` dans l'index, `git diff --stat` cohérent, commit.

### Étape 2 — `V11_eval_strategy.md` (§10) — ✅ FAITE le 2026-07-28 (commit `5e93fedd`)

Réalisé : 219 lignes déplacées telles quelles, ancres `s10`→`s10.7`, **55 entrants** recâblés
(un de moins que le majorant : `§10.9` n'est pas d'ici — c'est la spec de
`move_action_space_spatial_rework.md` citée depuis un commentaire de `spatial_grid.py`, ligne
désambiguïsée), **8 sortants** (`§0`×4, `§0bis`, `§0.3`, `§0.7`, `§0.9`) recâblés vers l'index.

- Périmètre : ~220 lignes déplacées, 56+8 liens (la plupart depuis §0hist, recâblage mécanique).
- Même méthode. Contexte : PETIT-MOYEN (~50 Ko lus, dominés par les hits de grep `§10`).
- ⚠️ `grep -n '§10'` matche aussi `§10.x` — c'est voulu ; il ne matche PAS `§1.x` (vérifier
  qu'aucun `§1 `/`§1bis` n'est capturé par une regex trop large).

### Étape 3 — `V11_tranches.md` (§1→§8) — ✅ FAITE le 2026-07-28 (commit `cb77f6a6`)

Réalisé : **1676 lignes** déplacées telles quelles (index 5753 → 4077), ancres `s1`, `s1bis`,
`s2`→`s8`, `s8.1`→`s8.5`. **24 lignes** de renvois entrants recâblées dans l'index (majorant 53 =
renvois, pas lignes ; plusieurs `§x` par ligne). Sortants du sous-doc : tous les `§0.x` pointés sur
l'index (ancres `s0.0`, `s0.4`, `s0.8`, `s0.11`, `s0.19.1` ajoutées côté index), `§9`/`§10` sur les
sous-docs frères, plus 4 renvois en clair (« section 9 », « section 10.6 », « section 9.2 »).
Liens provisoires de l'étape 1 (`§8.5`, `§1`, `§8` dans `V11_phaseA.md`) **re-pointés** sur
`V11_tranches.md` ; l'encadré « Lien provisoire » est remplacé par un encadré « Sous-docs frères ».
Faux positifs **désambiguïsés en nommant leur fichier** sur la ligne (§8.3 de
`move_action_space_spatial_rework.md`, §8/§2/§2bis de `V11_move_build_acceleration.md`) — ils
n'étaient pas signalés avant l'extraction parce qu'une ancre locale homonyme les absorbait.

- Périmètre : ~1680 lignes déplacées, 53+29 liens + re-pointage des liens provisoires des
  étapes 1-2. Contexte : MOYEN (~130 Ko lus). Ça tient dans une session d'agent, mais ne rien
  faire d'autre dans cette session.
- Localiser : `grep -n '^## 1\.'` (début §1) et `grep -n '^## 0hist'` — ATTENTION, §10 est déjà
  sorti à ce stade, donc la zone va de §1 jusqu'à §0hist.
- Recâblage entrants : grep séparés `§1bis`, `§[2-8]` (mot-frontière), `T[1-7] ` si cité comme
  ancre — puis tri manuel des faux positifs (PDF 24.16, §8.3 d'autres fichiers, etc.).

### Étape 4 — Réécriture de la tête de l'index + garde-fou final — ✅ FAITE le 2026-07-28

Réalisé : section **« Pointeurs — où vit la spec »** (ancre `#pointeurs`) posée à l'emplacement
libéré par §1→§10, avec les **8 documents** (3 sous-docs neufs + `V11_entity_encoder_pointer.md`
+ `observation_deploiement.md` + `Replay.md` + `V11_move_build_acceleration.md` +
`Implémenté/V11_move_pool_optimization.md`), une ligne par doc : rôle + état vivant/clos. Le renvoi
de tête « §0hist est après §10 » est re-pointé sur les Pointeurs. Index final : **4094 lignes**
(≈ 4050 attendues). Garde-fou global : **19 hits, tous faux positifs nommant leur fichier**
(cf. §6). Sous-docs : `V11_tranches.md` **1709**, `V11_phaseA.md`, `V11_eval_strategy.md`.

- Dans `V11_agent_rework.md` : remplacer les sections parties par une section « Pointeurs » :
  les 3 sous-docs neufs + `V11_entity_encoder_pointer.md` + `V11_move_build_acceleration.md` +
  `Implémenté/V11_move_pool_optimization.md` + `observation_deploiement.md` + `Replay.md`.
  Une ligne par doc : rôle + état (vivant/clos).
- Lancer le garde-fou (§6) sur l'index ET les 3 sous-docs → doit être vide partout.
- Vérifier `wc -l` de l'index ≈ 4050. Commit final.

## 6. Garde-fou (à lancer à chaque étape, puis global à l'étape 4)

Liste tout renvoi `§x.y` d'un fichier dont la cible n'est ni dans le fichier ni un lien de
fichier — doit sortir **vide** :

```bash
python3 - <<'EOF'
import re, sys
for path in ['V11_agent_rework.md','V11_tranches.md','V11_phaseA.md','V11_eval_strategy.md']:
    try: text = open(path).read()
    except FileNotFoundError: continue
    # ancres présentes localement : titres "## 9." / "### 9.2.5" etc. + ancres HTML
    anchors = set(re.findall(r'^#{2,3} (\d+(?:bis|ter|hist)?(?:\.\-?\d+)*)', text, re.M))
    anchors |= {a.lstrip('s') for a in re.findall(r'<a id="s([^"]+)"', text)}
    for i, line in enumerate(text.splitlines(), 1):
        for m in re.finditer(r'§(\d+(?:bis|ter|hist)?(?:\.\-?\d+)*)', line):
            ref = m.group(1)
            # les sections du doc vont de §0 à §10 ; §11+ = numéros de RÈGLES PDF (§13.06…)
            if int(re.match(r'\d+', ref).group(0)) >= 11:
                continue
            # ok si ancre locale (préfixe exact) ou si le renvoi est déjà un lien [..](fichier#..)
            if any(ref == a or ref.startswith(a + '.') or a.startswith(ref + '.') for a in anchors):
                continue
            if re.search(r'\[§' + re.escape(ref) + r'[^\]]*\]\([^)]+\.md', line):
                continue
            print(f'{path}:{i}: §{ref} ORPHELIN → {line.strip()[:100]}')
EOF
```

(Sortie non vide = lien mort = régression de navigation → corriger avant commit. Les faux
positifs « §x.y d'un autre fichier nommé dans la phrase » sont tolérés s'ils citent le fichier.
**Baseline PRÉ-extraction mesurée le 2026-07-28 : 3 hits**, tous `§2bis` = section de
`V11_move_build_acceleration.md` citée avec son contexte — toute sortie AU-DELÀ de cette
baseline est une régression introduite par l'extraction.
**Après étapes 1-2 : 6 hits** = les 3 de baseline + les 3 faux positifs de `V11_phaseA.md`
(`§8`, `§6`, `§1.9`, chacun citant son fichier) — aucun lien mort introduit.
**APRÈS ÉTAPES 3-4 — baseline finale : 19 hits, tous faux positifs, chacun nommant son fichier
sur sa propre ligne** — 16 dans `V11_agent_rework.md` (`§8.3` ×2 de
`move_action_space_spatial_rework.md` ; `§2`, `§2bis` ×3, `§3` ×2, `§3.1`, `§8` ×4 de
`V11_move_build_acceleration.md` ; `§1.8`, `§1.9`, `§6.2` d'autres chantiers) et 3 dans
`V11_phaseA.md` (`§8`, `§6`, `§1.9`). **Aucun lien mort.** Toute sortie AU-DELÀ de ces 19 est
une régression.)

## 7. Budget contexte / quota — quelles étapes pour un seul agent ?

| Étape | Lecture estimée | Faisable seule par 1 agent ? |
|---|---|---|
| 1 (§9) | ~40 Ko | ✅ oui, largement |
| 2 (§10) | ~50 Ko | ✅ oui |
| 1+2 dans la même session | ~90 Ko | ✅ oui — recommandé (même méthode, 2 commits) |
| 3 (§1→§8) | ~130 Ko | ✅ oui, mais SEULE dans sa session |
| 4 (index+garde-fou) | ~30 Ko | ✅ oui — peut suivre l'étape 3 dans la même session |

**Découpage recommandé : 2 sessions d'agent.** Session A = étapes 1+2 (2 commits).
Session B = étapes 3+4 (2 commits). Ne JAMAIS fusionner 3 avec 1-2 : c'est la lecture cumulée
qui déborde, pas une étape isolée.
