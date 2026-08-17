# Où insérer / modifier chaque point dans memoire.pdf

Référence : **memoire.pdf** (66 pages), **Table des matières** (pages 1–3).

---

## 1. Présentation du contexte de réalisation (remplacer « entreprise »)

| Où dans memoire.pdf | Action précise |
|---------------------|----------------|
| **Besoins du projet** → **1. Contexte** (vers **page 9**) | Remplacer « Présentation de l'entreprise ou du service : [A compléter] » par le texte de `Presentation_contexte_formation.md`, ou ajouter un **1.3 Présentation du contexte de réalisation** avec ce texte. |

**Statut :** Done (par toi).

---

## 2. Maquettes / enchaînement des écrans

| Où dans memoire.pdf | Action précise |
|---------------------|----------------|
| **Réalisations front-end** → **2. Organisation de l'interface** | **Recommandation :** insérer le schéma d’**enchaînement des écrans** (flux auth → jeu → replay) dans la sous-section **c) Plan du site (sitemap)** (vers **page 27**), car tu as déjà un schéma à cet endroit. **Deux options :** **(A)** Remplacer le schéma actuel par l’image exportée du Mermaid de `Maquettes_enchainement_ecrans.md` s’il est plus clair (flux utilisateur). **(B)** Garder ton schéma actuel et **ajouter juste en dessous** le schéma Mermaid avec la légende « Enchaînement des écrans – Parcours utilisateur (auth → jeu → replay) ». Ainsi, **2.c) Plan du site** contient à la fois le plan des URLs/accès et l’enchaînement des écrans. Dans **2.a) Maquettes**, tu peux écrire une phrase du type : « L’enchaînement des écrans est détaillé en 2.c) Plan du site. » Pas besoin de dupliquer le schéma. |

---

## 3. Schéma BDD (MEA + physique)

| Où dans memoire.pdf | Action précise |
|---------------------|----------------|
| **Réalisation Back-end** → **2. Base de données** (vers **page 42**) | Ajouter le schéma MEA (image ou dessin) et le tableau du modèle physique (tables/colonnes), ou les mettre en annexe et y renvoyer depuis cette section. |

**Statut :** Done (par toi).

---

## 4. Jeu d’essai complet (Analyzer.py + vérification visuelle)

| Où dans memoire.pdf | Action précise |
|---------------------|----------------|
| **Jeux d'essai** (vers **page 49**) | Ajouter une sous-partie **« Jeu d'essai – Fonctionnalité représentative »** avec le contenu de `Jeu_essai_complet.md` : **Analyzer.py** (génération de `step.log`, exécution de `ai/analyzer.py`, résultat attendu 0 violations, résultat obtenu à remplir) **couplé à une vérification visuelle** (partie PvE ou replay). Tableau ou paragraphes : Données en entrée | Résultat attendu | Résultat obtenu | Analyse des écarts. Une phrase pour la vérification visuelle : « Une vérification visuelle (partie PvE ou replay) confirme l’absence d’anomalie. » |

---

## 5. Annexes – Où trouver les contenus (codes / tableaux)

| Annexe à ajouter | Fichier source dans le dépôt | Contenu |
|------------------|------------------------------|--------|
| **Annexe 3 : Script de création de la base d'authentification** | `Documentation/Memoire/Annexe_script_BDD_auth.sql` | Script SQL (CREATE TABLE + INSERT d’amorçage). Ouvrir le fichier, copier tout le contenu, coller dans le mémoire en annexe. |
| **Annexe 4 : Tableau des routes API** | `Documentation/Memoire/Annexe_tableau_routes_API.md` | Tableau (méthode, URL, paramètres, codes retour). Même chose : ouvrir, copier le tableau, coller en annexe. |
| **Annexe 5 : Extraits de code significatifs** | `Documentation/Memoire/Annexe_extraits_code.md` | Trois extraits (step moteur, movement_phase_start, appel API start game) avec fichier et contexte. Copier les trois blocs dans le mémoire en annexe. |

**Emplacements des fichiers :**

- `Documentation/Memoire/Annexe_script_BDD_auth.sql`
- `Documentation/Memoire/Annexe_tableau_routes_API.md`
- `Documentation/Memoire/Annexe_extraits_code.md`

Après ajout, renuméroter les annexes suivantes (ex. Decision Tree → 6, output Analyzer → 7, etc.).

---

## 6. Captures + code (Auth et Plateau)

**Statut :** Déjà fait (par toi).

---

## 7. Checklist de conformité

| Où dans memoire.pdf | Action précise |
|---------------------|----------------|
| **Checklist de conformité (CDC RNCP 6)** (vers **page 66**) | Les cases ont été mises à jour dans la **source** du mémoire (`memoire_reorganise.md`) : Présentation, Modèle EA/physique, Captures+code cochés ; Maquettes et Jeu d’essai final laissés avec une note ; Annexes à cocher quand les annexes 3–5 sont intégrées. Si ton PDF est exporté depuis une autre source (ex. memoire.odt), **mettre à jour la checklist dans cette source** puis régénérer le PDF. |

---

## 8. Éco-conception et tests (REAC) – En deux phrases

Le REAC demande d’**identifier les besoins en éco-conception** (réduction de l’impact environnemental du numérique) et de mentionner les **tests** (unitaires, d’acceptation, de charge). Tu n’as pas fait d’éco-conception ni de tests unitaires frontend / charge ; il suffit de le **dire en une phrase pour chaque thème**.

**Où les insérer :** **Gestion du projet** → **2. Objectifs qualité** (vers **page 16**), en **fin de section**, ou en début/fin de **Jeux d'essai** (page 49).

**Phrase 1 – Éco-conception (à copier-coller ou adapter) :**

> L’éco-conception n’a pas été un critère prioritaire du cahier des charges ; les besoins identifiés concernent la limitation des requêtes inutiles (pas de polling intensif, mise à jour de l’état après action) et l’absence de calculs superflus côté serveur (single source of truth).

**Phrase 2 – Tests (à copier-coller ou adapter) :**

> Les tests unitaires des composants React et les tests d’acceptation ou de charge n’ont pas été mis en œuvre ; la validation repose sur les tests manuels, les scripts de conformité (check_ai_rules, analyzer) et l’évaluation par bots ; des tests unitaires frontend sont prévus pour une évolution ultérieure.

Rien de plus à « comprendre » : ce sont des **formulations pour montrer au jury** que tu connais ces attendus du REAC et que tu as fait des choix explicites dans le cadre du projet.

---

## Récapitulatif par section

| Section (TDM) | Page | Modifications |
|---------------|------|----------------|
| Besoins du projet → 1. Contexte | 9 | Présentation contexte réalisation (formation). **Done.** |
| Gestion du projet → 2. Objectifs qualité | 16 | Ajouter 2 phrases : éco-conception + tests (voir §8). |
| Réalisations front-end → 2.c) Plan du site | 27 | Insérer schéma enchaînement écrans (Mermaid) avec sitemap existant. |
| Réalisation Back-end → 2. Base de données | 42 | MEA + modèle physique. **Done.** |
| Jeux d'essai | 49 | Sous-partie « Jeu d'essai représentatif » : Analyzer.py + vérification visuelle (voir `Jeu_essai_complet.md`). |
| Annexes | 57+ | Annexes 3–5 : contenu dans `Annexe_script_BDD_auth.sql`, `Annexe_tableau_routes_API.md`, `Annexe_extraits_code.md`. |
| Checklist | 66 | Mise à jour dans la source (memoire_reorganise.md) ; cocher Annexes quand annexes 3–5 intégrées. |
