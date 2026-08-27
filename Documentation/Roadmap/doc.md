# Hygiène documentaire — Tâches ouvertes

---

## Refonte Documentation/ — architecture par rôle {#refonte}

**Décisions actées le 2026-08-27** (audit complet du corpus, arbitrages utilisateur A/A/A) :
arborescence par RÔLE — `Documentation/Reference/<domaine>/` (décrit l'état actuel, doit rester
vrai), `Documentation/Chantiers/` (vivant : contrats permanents, `v11/`, `backlog/`),
`Documentation/Archives/` (mort : `chantiers/`, `docs/`, `prompts/`) ; `Roadmap/`, `Review/`,
`40k_rules/`, `sql/` inchangés ; mémoire RNCP → `Memoire_RNCP/` et pitchs → `Communication/`
(racine du dépôt). Détail des décisions et des phases restantes :
`Documentation/Chantiers/backlog/refonte_documentation.md`.

- **P1 structure** : ✅ livrée le 2026-08-27 — déplacements, mise à jour des scripts, des tests
  et de CLAUDE.md, README régénéré, purge des ✅ de l'index, liens réparés.
- **P2 garde machine étendue** : ✅ livrée le 2026-08-27 — passe LIENS corpus vivant, `ANCHOR_TREES` étendu à `Reference/` (23 ancres fichier:ligne purgées d'`AI_TRAINING.md`), `VALUE_CHECKS` étendus (`TOTAL_ACTION_SIZE`, dimensions `allies_cont/allies_bin`), accumulation ROADMAP ≤ 20 ✅ ; 51 fragments morts #s0.X retirés de V11_tranches/phaseA/eval_strategy.
- **P3 contenu** : 🟡 à faire — scission `V11_agent_rework.md` (ouvert → roadmap, §0bis → doc de
  méthode, §0hist → archive), réécriture `AI_TURN.md`, passes unitaires (`Weapon_rules.md`,
  `USER_ACCESS_CONTROL.md`, `AI_METRICS.md`, bandeau `AI_TRAINING.md`).

---

## Ancres de ligne périmées docs V11 {#ancres}

**Traitement au fil de l'eau** (décision 2026-08-10) — tout doc modifié voit ses ancres de ligne corrigées dans la même livraison.

Le solde du 2026-08-25 (sept symboles corrigés dans 4 docs) est archivé dans
[archives/doc.md](archives/doc.md).

**Convention** : citer `def <symbole>` ou un `grep` reproductible, jamais un numéro de ligne. La passe 5, `def check_symbol_kinds` (`scripts/check_doc_references.py`), vérifie le genre déclaré ; la passe 2, `def check_links` (`scripts/check_doc_references.py`), contrôle les liens morts.

**Couverture du script** : `check_doc_references.py` passe 4 (ANCRES) couvre `Documentation/Roadmap/`, les contrats permanents, le corpus chantiers (`Documentation/Chantiers/` + `Documentation/Archives/chantiers/`) et désormais `Documentation/Reference/` (P2 livré le 2026-08-27). Passe LIENS sur tout le corpus vivant également active depuis P2.

---

## Dette d'ancres G1/G2/G4 de V11_tranches §1bis {#dette-tranches}

Le recensement G1/G2/G4 de `Documentation/Chantiers/v11/V11_tranches.md` §1bis est en fiabilité dégradée. **Interdiction d'ouvrir un chantier depuis une ligne non ✅ de ce recensement sans la re-vérifier contre le code d'abord** — c'est ainsi qu'est né le plan T7 faux.

---

## §0.19 — T2→T5 revérifiés par lecture seule {#reverif-t2-t5}

`Documentation/Chantiers/v11/V11_agent_rework.md` §0.19 le déclare lui-même : les ✅ de T2→T5 ne sont revérifiés que par LECTURE (aucune exécution), et la conformité littérale de T2 est indécidable. Dette de spec assumée, continue — distincte de la dette d'ancres G1/G2/G4 ci-dessus, qui porte sur le recensement de `V11_tranches.md` §1bis.

---

## Bandeaux périmés V11_agent_rework §0bis {#bandeaux-0bis}

Bandeaux et chiffres périmés listés dans `Documentation/Chantiers/v11/V11_agent_rework.md` §0bis — signalés et volontairement non corrigés depuis le 2026-07-20. Assumé tant qu'aucune livraison ne rouvre ces sections ; traitement au fil de l'eau, comme les ancres.
