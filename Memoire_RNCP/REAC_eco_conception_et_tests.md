# REAC – Éco-conception et tests (explication courte)

Le REAC CDA demande deux choses que tu avais notées comme peu claires :

1. **Éco-conception**
2. **Tests unitaires frontend / tests d’acceptation ou de charge**

Voici ce que ça signifie et comment en parler en une phrase dans le mémoire.

---

## 1. Éco-conception

**Ce que demande le REAC :**  
Dans la compétence « Définir l’architecture logicielle d’une application », il est demandé d’**identifier les besoins d’éco-conception** de l’application. L’éco-conception des services numériques vise à réduire l’impact environnemental (énergie, ressources, données transférées, etc.).

**En pratique pour ton projet :**  
Tu n’as pas mené une démarche d’éco-conception formalisée. Tu peux quand même **répondre en une phrase** en disant soit ce que tu as fait, soit ce que tu as identifié (même minimal).

**Exemple de phrase à placer** (dans la section architecture ou objectifs qualité) :

> « Pour ce projet, l’éco-conception n’a pas été un critère prioritaire du cahier des charges. Les besoins identifiés concernent la limitation des requêtes inutiles (pas de polling intensif côté client, mise à jour de l’état uniquement après une action) et l’absence de calculs lourds superflus côté serveur (single source of truth, pas de duplication du game_state). »

Tu peux adapter (ex. ajouter « réduction du volume de données échangées en JSON » si pertinent).

---

## 2. Tests unitaires frontend / tests d’acceptation / tests de charge

**Ce que demande le REAC :**  
- **Tests unitaires** des composants (ex. interfaces) : vérifier qu’un composant se comporte comme prévu (rendu, props, événements).  
- **Tests d’acceptation** : un utilisateur (ou un scénario automatisé) valide que la fonctionnalité correspond au besoin (ex. « je me connecte et je démarre une partie »).  
- **Tests de charge** : vérifier le comportement sous charge (nombre de requêtes, utilisateurs simultanés, etc.).

**En pratique pour ton projet :**  
Tu as des tests côté moteur / conformité (check_ai_rules, analyzer, bots) mais pas de suite de tests unitaires frontend (ex. Vitest/Jest sur composants React) ni de tests d’acceptation ou de charge formalisés.

**Exemple de phrase à placer** (dans la section plan de tests ou objectifs qualité) :

> « Les tests unitaires des composants React (par ex. avec Vitest) et les tests d’acceptation (scénarios utilisateur end-to-end) ou de charge n’ont pas été mis en œuvre dans le cadre du projet. La validation repose sur les tests manuels, les scripts de conformité du moteur (check_ai_rules, analyzer) et l’évaluation par bots. Les tests unitaires frontend et les tests d’acceptation sont prévus pour une évolution ultérieure (voir Roadmap). »

Ainsi tu montres que tu connais ces notions (REAC) et que tu as fait des choix explicites dans le périmètre et le temps du projet.

---

## Où placer ces phrases dans le mémoire

- **Éco-conception :** dans la section **Architecture logicielle** (3.3) ou **Objectifs de qualité** (2.3), en 1–2 phrases.
- **Tests :** dans la section **Plan de tests** (4.7) ou **Objectifs de qualité** (2.3), en 1–2 phrases.

Cela suffit pour satisfaire les attendus du REAC sur ces points sans détailler une démarche que tu n’as pas menée.
