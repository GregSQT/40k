# V11_agent_rework.md — Plan d'extraction en sous-documents

> **But.** Réduire `V11_agent_rework.md` (4399 lignes / 341 Ko) à un **index d'état** (à faire / fait
> + méthode), en sortant les chantiers clos et les axes stables dans des sous-docs, chacun avec un
> pointeur depuis l'index. Pattern déjà validé : §0.22 → `V11_move_pool_optimization.md`.
>
> **Statut : PLAN, non exécuté.** À lancer HORS run et APRÈS que l'agent move_pool ait fini sa passe
> et mis à jour le pointeur §0.22 dans `V11_agent_rework.md` (sinon édition concurrente du même
> fichier). Cadrage + mesures de couplage : 2026-07-21, par lecture directe.

---

## 1. Principe de découpe

- **L'index (`V11_agent_rework.md`)** ne garde que ce qui **change** : l'état à faire/fait, la
  méthode, le concept d'ancre, et les **pointeurs** vers les sous-docs.
- **Un sous-doc = un chantier CLOS ou un axe STABLE** (spec qui ne bouge plus au fil des sessions).
- **Règle anti-régression du refactor** : après extraction, `grep` des `§` orphelins (cible déplacée
  sans lien de fichier) doit être **vide**. Un renvoi cross-fichier non recâblé = lien mort =
  régression de navigation.

## 2. Structure des sections (frontières vérifiées le 2026-07-21)

| Ligne | Section | Nature |
|---|---|---|
| 13 | §0 État (à faire/fait) | **vivant** |
| 648 | §0bis Pièges/leçons (canonique) | **vivant** |
| 934 | §0ter Notes post-impl | **vivant** |
| 951-2324 | §0hist Historique résolu | journal clos |
| 2325 | §1 Objectif | spec |
| 2348-2479 | §1bis L'ANCRE (concept central) | spec transverse |
| 2480 | §2 État des lieux | spec |
| 2519 | §3 Ruptures | spec |
| 2692 | §4 Décisions de design | spec |
| 2757-3808 | §5 Tranches T1-T6 | spec |
| 3809 | §6 Critères d'acceptation | spec |
| 3824 | §7 Annexe smoke tests | spec |
| 3842-3994 | §8 Tests de non-régression | spec |
| 3995-4180 | §9 Phase A' (P1-P5) | spec (plan non implémenté) |
| 4181-4399 | §10 Stratégie éval/rosters | spec/décision |

⚠️ Les sous-entrées §0.N sont **interleavées par numéro** entre §0 (ouvertes : 0.14/0.15/0.16/0.17/
0.19/0.22) et §0hist (résolues : 0.-1, 0.0→0.13, 0.18, 0.20, 0.21). C'est ce qui rend l'extraction
de l'historique coûteuse (cf. §4).

## 3. Coût de recâblage mesuré (renvois traversant la future frontière)

Renvois `§x.y` qui pointent vers une section extraite depuis l'extérieur de sa zone → **à
transformer en liens de fichier** :

| Extraction | Fichier cible proposé | Liens à recâbler | Détail |
|---|---|---|---|
| §9 Phase A' | `V11_phaseA.md` | **6** | trivial |
| §2-§8 Tranches+critères+tests | `V11_tranches.md` | **27** | modéré |
| §10 Éval/rosters | `V11_eval_strategy.md` | **54** | 34 depuis §0hist, 18 depuis §0, 2 tranches |
| §0hist Historique | `V11_history.md` | **172** | 148 depuis §0, 19 depuis tranches, 3 éval, 2 §1 |

## 4. Décision-clé : l'historique sort-il ?

Extraire §0hist coûte **172 liens** (148 = le §0 « état » qui raconte « §0.X corrigé → §0.18 »).
C'est le plus gros gain de taille (1373 lignes, 31 %) MAIS le plus cher et le plus fragile.

**✅ TRANCHÉ (2026-07-21) : Option A.** L'historique reste dans l'index ; on n'extrait que la spec
§1→§10. La découpe §5 et l'ordre §7 s'appliquent tels quels.

- **Option A (RETENUE) — l'historique RESTE dans l'index.** L'index = journal complet
  (état + méthode + notes + historique résolu). On extrait seulement la **spec** (§1→§10).
  → **0 lien historique à recâbler.** Index ≈ 2000 lignes (§0*+§0hist), spec ≈ 1900 lignes sorties.
  Cohérent avec « garder l'inventaire à faire/fait » : l'historique EST l'inventaire du fait.
- **Option B — l'historique sort dans `V11_history.md`.** Index minimal (~600 lignes) mais
  **172 liens** à recâbler + risque d'ancres mortes. Justifié seulement si l'index doit être
  ultra-court. Coût/bénéfice défavorable tant que le doc n'est pas re-consulté sans cesse.

## 5. Découpe retenue (sous Option A)

| Reste dans `V11_agent_rework.md` (index) | Sort |
|---|---|
| §0, §0bis, §0ter, §0hist | §1+§1bis+§2+§3+§4+§5+§6+§7+§8 → `V11_tranches.md` |
| Tableau d'état + pointeurs | §9 → `V11_phaseA.md` |
| | §10 → `V11_eval_strategy.md` |
| | (déjà sorti : §0.22 → `V11_move_pool_optimization.md`) |

Total liens à recâbler sous Option A : **6 (§9) + 27 (§2-8) + 54 (§10) = 87**, moins les renvois
INTERNES aux blocs déplacés (qui restent locaux). Les 34 liens §0hist→§10 et 19 §0hist→tranches
deviennent index→sous-doc : mécaniques.

## 6. Convention de recâblage (robuste aux titres à accents/emoji)

Les titres portent accents/emoji → les ancres markdown auto-générées sont fragiles. À l'extraction :
1. Poser une **ancre HTML explicite** juste avant chaque titre déplacé cité de l'extérieur :
   `<a id="s10.6"></a>` avant `### 10.6 …`.
2. Recâbler les renvois entrants en lien de fichier : `§10.6` → `[§10.6](V11_eval_strategy.md#s10.6)`.
3. Ne recâbler QUE les renvois cross-fichier (ceux du §3) ; les renvois internes au sous-doc restent
   du texte `§10.6` nu.

## 7. Ordre d'exécution (du moins couplé au plus couplé, un sous-doc = un commit)

1. **`V11_phaseA.md`** (§9, 6 liens) — rodage de la méthode sur le cas trivial.
2. **`V11_tranches.md`** (§2-§8, 27 liens).
3. **`V11_eval_strategy.md`** (§10, 54 liens).
4. Réécrire l'index : tableau d'état + section « Pointeurs » listant les 4 sous-docs (+ move_pool).
5. **Garde-fou final** : script qui liste tout `§x.y` de l'index dont la cible n'est plus dans
   l'index NI un lien de fichier → doit être vide. Idem dans chaque sous-doc.

## 8. Garde-fous

- **Timing** : hors run, après la passe move_pool de l'autre agent (édition concurrente d'un même
  fichier sinon).
- **Aucune réécriture de contenu** pendant l'extraction : on **déplace** des blocs et on **recâble**
  des liens, on ne corrige pas la prose (sinon on mélange deux natures de diff et on ré-introduit le
  risque d'affirmation périmée que §0bis traque).
- **Un sous-doc = un commit** : diff lisible, réversible bloc par bloc.
- Corriger au passage l'**en-tête périmé §0.19 l.128** (« 🟠 OUVERT » alors que soldé §0.19.3) —
  c'est une correction de STATUT, pas de prose historique, donc légitime.
