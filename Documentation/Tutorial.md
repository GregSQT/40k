# Didacticiel — Documentation d'implémentation

**Ce document est la spec complète pour le prompt qui implémentera le didacticiel.** Les sections 2.1–2.6 et 4 décrivent le scénario en 3 étapes, les positions et l'option scripté vs simplifié.

**Références projet** : `Documentation/AI_TURN.md` (phases, séquence de tour), `Documentation/AI_IMPLEMENTATION.md` (architecture).

---

## 1. Objectif et principe

Offrir aux nouveaux joueurs un **parcours guidé** : une partie pré-configurée où, à chaque étape clé, un **popup** explique une règle. Le joueur joue dans le vrai jeu (même moteur, même UI), avec des étapes et textes **data-driven** (JSON) pour faciliter la maintenance.

**Design d'immersion** : le joueur ne contrôle **qu'une seule unité** (un Intercessor). Le didacticiel est découpé en **3 étapes narratives** : (1) Mouvement + Tir, (2) Charge + Mêlée, (3) Objectifs ou règles spéciales. On n'utilise que les **murs extérieurs** du plateau pour libérer l'intérieur et garantir la LoS.

---

## 2. Périmètre fonctionnel et scénario en 3 étapes

**Murs** : Utiliser uniquement les murs **extérieurs** (périmètre du plateau). Réutiliser les `wall_hexes` de `config/scenario_pvp_test.json` en **retirant les murs intérieurs** (lignes du type [4,10]…[8,10], [20,10]…, [12,17]…, [12,3]…) pour garder seulement le contour. L'intérieur reste dégagé pour la ligne de vue.

### 2.1 Étape 1 — Mouvement et tir

- **Setup** : Intercessor (joueur) en **col 12, row 20**. Termagant (ennemi) en **col 12, row 0**. Même colonne = LoS libre.
- **Narrative** : Le Termagant avance et tire en premier, il rate. Le joueur avance puis tire et tue le Termagant.
- **Implémentation** : Voir § 2.4 (scripté vs simplifié). En version simplifiée : pas de tour Termagant ; popup « Le Termagant a tiré et raté ». Le joueur fait mouvement puis tir, tue le Termagant.

### 2.2 Étape 2 — Charge et mêlée

- **Setup** : Après l'étape 1 (Termagant mort), on passe à une scène « Charge + combat ». Trois Hormagaunts apparaissent en **(0, 10), (12, 0), (24, 10)**. Ils chargent le Space Marine.
- **Narrative** : Le Marine perd 1 PV et tue 1 Hormagaunt. À son tour, il ne fait pas de Fall back et tue les 2 restants.
- **Implémentation** : Soit scénario préchargé avec 3 Hormagaunts déjà au contact du Marine (positions adjacentes au Marine, ex. Marine (12, 10), Hormagaunts (11,10), (12,9), (13,10)) et popup « Ils viennent de charger » ; soit mode scripté (moteur exécute la charge et les dégâts imposés). Voir § 2.4.

### 2.3 Étape 3 — Objectifs (recommandé) ou règles spéciales

**Recommandation honnête** : Privilégier **les objectifs** pour l'étape 3. Une mission « Contrôlez l'objectif central » (une zone au centre du plateau) : le joueur doit faire terminer son Intercessor sur la zone pour marquer. Court à expliquer, réutilise le système d'objectifs existant, donne un but clair. Idéal pour conclure le tutoriel.

**Règles spéciales** (Advance + Assault, Fall back, Pistol en mêlée, etc.) : très utiles mais une règle = une mise en scène. Mieux en **tutoriel avancé** ou en **fiches / infobulles** séparées. Possible en « Étape 4 » ou contenu additionnel plus tard.

**Synthèse** : Étape 3 = **objectifs** (tenir la zone centrale). Règles spéciales = suite possible (Étape 4 ou fiches).

### 2.4 Implémentation réaliste : scripté vs simplifié

La narrative ci‑dessus suppose des **résultats déterminés** (Termagant rate ; Marine perd 1 PV, tue 1 puis 2 Hormagaunts). Le moteur actuel est « joueur vs joueur / bot » avec dés ; il n'a pas de mode « scénario scripté » avec actions/dés imposés.

- **Option A — Script complet** : Mode tutoriel dans le moteur qui exécute une liste d'actions (ex. « Termagant move + shoot, résultat miss ») et/ou dés forcés. Très lourd à ajouter.
- **Option B — Simplifié (recommandé pour le MVP)** : Garder la même mise en scène (positions, popups) sans script ennemi.
  - Étape 1 : Popup « Le Termagant a tiré et raté » ; pas de tour adverse (ou skip du tour joueur 2 en mode tutoriel). Le joueur fait mouvement + tir et tue le Termagant.
  - Étape 2 : Scénario ou transition où le Marine est déjà au contact de 3 Hormagaunts (positions fixes). Popup « Les Hormagaunts viennent de charger. À vous. » Le joueur résout la phase combat (les dés restent aléatoires ; on accepte que le résultat puisse varier).
  - Étape 3 : Même moteur, objectif « contrôler la zone centrale » ; le joueur déplace son Intercessor sur l'objectif et termine le tour.

Si plus tard on ajoute un vrai mode « script » (actions/dés imposés), on pourra coller à la narrative exacte (1 PV perdu, 1 puis 2 kills).

### 2.5 Fichiers scénario

- **Étape 1** : `config/scenario_tutorial_etape1.json` — units : Intercessor (12, 20), Termagant (12, 0) ; `wall_hexes` = périmètre seul (copie `scenario_pvp_test` sans murs intérieurs) ; `objectives` optionnel.
- **Étape 2** : `config/scenario_tutorial_etape2.json` — units : Intercessor à la position choisie (ex. 12, 10), 3 Hormagaunts aux positions (0,10), (12,0), (24,10) ou **déjà au contact** (ex. (11,10), (12,9), (13,10)) ; mêmes `wall_hexes` (périmètre seul).
- **Étape 3** : réutiliser le plateau avec objectifs (ex. objectif Centre comme dans `scenario_pvp_test`) ; un Intercessor à déplacer vers la zone.

### 2.6 Extensions possibles (hors MVP)

- Highlight d'un élément UI (unité, bouton).
- Restriction des actions (seule l'action en cours autorisée).
- Tutoriel « Règles spéciales » (Advance, Fall back, Pistol).
- Mode scripté (dés/actions imposés) pour coller à la narrative exacte.

---

## 3. Architecture

### 3.1 Choix techniques

| Composant | Décision | Raison |
|-----------|----------|--------|
| Données | JSON (scénario + étapes) | Édition des textes sans toucher au code ; contenu data-driven. |
| Logique tutoriel | 100 % frontend (TypeScript/React) | Déclenchement des popups selon l'état du jeu (phase, actions) ; pas de changement de règles côté moteur. |
| Backend | Inchangé ou 1 endpoint optionnel | La partie tutoriel utilise la même API que PvP (`/api/game/start`, `/api/game/action`, `/api/game/state`) avec un scénario dédié. |
| Entrée | Lien « Didacticiel » depuis l'accueil / le menu | Lance une partie avec `mode_code` + `scenario_file` tutoriel. |

### 3.2 Flux

1. L'utilisateur clique sur « Didacticiel » (ex. depuis `HomePage` ou équivalent).
2. Le frontend appelle `POST /api/game/start` avec `mode_code: "pvp_test"` (ou un mode dédié) et `scenario_file` selon l'étape (etape1, etape2, etc.).
3. Le frontend charge `tutorial_steps.json` (depuis `/config/` ou `public/config/`).
4. Un **moteur d'étapes** (hook ou module) écoute les événements (phase, première action, etc.) et affiche le popup correspondant à l'étape courante.
5. Le joueur joue normalement ; les popups s'enchaînent. Transition entre étapes : chargement du scénario suivant (etape2 après kill Termagant, etape3 après combat, etc.).

### 3.3 Fichiers à créer / modifier

| Fichier | Action |
|---------|--------|
| `config/scenario_tutorial_etape1.json` | **Créer** — Intercessor (12,20), Termagant (12,0), murs extérieurs uniquement. |
| `config/scenario_tutorial_etape2.json` | **Créer** — Intercessor + 3 Hormagaunts (positions au contact ou (0,10),(12,0),(24,10)). |
| `config/scenario_tutorial_etape3.json` (ou réutiliser etape1 + objectifs) | **Créer** — Objectif central, 1 Intercessor. |
| `config/tutorial_steps.json` ou `frontend/public/config/tutorial_steps.json` | **Créer** — Liste des étapes (id, ordre, trigger, title, body), éventuellement par `etape` (1, 2, 3). |
| `frontend/src/components/TutorialOverlay.tsx` (ou `TutorialPopup.tsx`) | **Créer** — Composant modal (titre, corps, bouton Compris/Suivant, optionnel « Passer »). |
| `frontend/src/contexts/TutorialContext.tsx` ou `frontend/src/hooks/useTutorialEngine.ts` | **Créer** — État (étape courante, numéro d'étape 1/2/3, visible/dismissed) + logique de trigger → étape + transition de scénario. |
| `frontend/src/pages/HomePage.tsx` | **Modifier** — Ajouter un lien « Didacticiel » qui lance la partie avec mode + scénario tutoriel etape1. |
| `frontend/src/components/GamePageLayout.tsx` (ou composant qui lance la partie) | **Modifier** — Détecter « mode tutoriel » et activer le moteur d'étapes + overlay. |
| `frontend/src/hooks/useEngineAPI.ts` (ou appel `game/start`) | **Modifier** — Passer `scenario_file` (et éventuellement un `mode_code` dédié) pour le didacticiel. |
| `services/api_server.py` | **Optionnel** — Ajouter un mode `tutorial` qui force `scenario_file` si non fourni ; sinon réutiliser `pvp_test` + scénario. |

---

## 4. Format des données

### 4.1 Scénarios tutoriel (murs extérieurs uniquement)

Réutiliser le format des scénarios existants (voir `config/scenario_pvp_test.json`). Types d'unités : `config/unit_registry.json` (Intercessor, Termagant, Hormagaunt). **wall_hexes** : copier uniquement les hex du **périmètre** depuis `scenario_pvp_test.json` (supprimer les blocs intérieurs [4,10]…[8,10], [20,10]…, [12,17]…, [12,3]…).

**Étape 1 — Exemple `config/scenario_tutorial_etape1.json`** :

```json
{
  "primary_objectives": ["objectives_control"],
  "units": [
    { "id": 1, "unit_type": "Intercessor", "player": 1, "col": 12, "row": 20 },
    { "id": 2, "unit_type": "Termagant", "player": 2, "col": 12, "row": 0 }
  ],
  "wall_hexes": [
    [2,5],[2,6],[2,7],[3,4],[4,4],[5,3],[6,3],[7,2],[8,2],[9,1],
    [16,2],[17,2],[18,3],[19,3],[20,4],[21,4],[15,1],[22,5],[22,6],[22,7],
    [2,14],[2,15],[2,13],[3,15],[4,16],[5,16],[6,17],[7,17],[8,18],[9,18],
    [22,13],[22,14],[22,15],[21,15],[20,16],[19,16],[18,17],[17,17],[16,18],[15,18]
  ],
  "objectives": []
}
```

(Adapter `wall_hexes` si le plateau a d'autres bords ; garder uniquement le contour.)

**Étape 2 — Exemple simplifié (Hormagaunts déjà au contact)** : Intercessor (12, 10), 3 Hormagaunts (11,10), (12,9), (13,10). Même `wall_hexes` (périmètre).

**Étape 3** : Réutiliser objectif Centre de `scenario_pvp_test` (hex [[12,10],[11,9],[12,9],[13,9],[13,10],[12,11],[11,10]]), 1 Intercessor à placer.

### 4.2 Fichier d'étapes `tutorial_steps.json`

Les steps peuvent être organisés par **etape** (1, 2, 3) avec des triggers `on_deploy`, `phase_enter`, `after_action`. Pour l'étape 1 : welcome, phase move, phase shoot, after shoot (kill Termagant) → transition vers scénario etape2. Pour l'étape 2 : phase fight, after fight → transition vers etape3. Pour l'étape 3 : objectif, end.

Structure possible : un tableau par etape, ou un tableau unique avec un champ `etape` (1|2|3) et ordre global. Voir 4.3 pour les types de trigger.

### 4.3 Types de trigger (à implémenter côté frontend)

| `trigger.type` | Paramètres | Description |
|----------------|------------|-------------|
| `on_deploy` | — | Affiché au chargement de la partie (après déploiement / premier affichage du plateau). |
| `phase_enter` | `phase`: `"move"` \| `"shoot"` \| `"charge"` \| `"fight"` | Affiché à l'entrée dans la phase donnée. |
| `after_action` | `action`: `"move"` \| `"shoot"` \| `"charge"` \| `"fight"`, `count`?: number | Affiché après la N-ième action du type (défaut 1). |
| `unit_selected` | `player`?: 1 \| 2 | Affiché quand une unité du joueur courant est sélectionnée (optionnel). |

Le moteur d'étapes garde un **index d'étape courante** et le **numéro d'étape narrative** (1, 2 ou 3). Une fois une condition de transition remplie (ex. Termagant mort), on peut recharger le scénario suivant (etape2, etape3).

---

## 5. Frontend — Détail d'implémentation

### 5.1 Détection du mode tutoriel

- Soit un paramètre d'URL : `/game?mode=tutorial`.
- Soit un `mode_code: "tutorial"` envoyé à `POST /api/game/start` (et côté backend, traité comme PvP avec `scenario_file` tutoriel).

Le composant qui monte le plateau (ex. `GamePageLayout`) lit ce mode et :

- lance la partie avec le scénario tutoriel etape1 ;
- active le **TutorialContext** (ou équivalent) et rend le **TutorialOverlay**.

### 5.2 Moteur d'étapes et transitions

- **État** : `currentStepIndex`, `currentEtape` (1 | 2 | 3), `steps[]`, `popupVisible`.
- **Transitions** : Quand la condition de fin d'étape est remplie (ex. Termagant mort pour etape1), appeler `game/start` avec le scénario de l'étape suivante (etape2, puis etape3).
- **Logique** : Afficher les popups selon les triggers ; à « Compris », passer à l'étape suivante ou au prochain trigger.

### 5.3 Composant TutorialOverlay (popup)

- **Props** : `step: { title, body }`, `onClose: () => void`, `onSkipTutorial?: () => void`.
- **UI** : modal centré, titre, corps (texte ou HTML simple), bouton « Compris » (ou « Suivant »), optionnel « Passer le didacticiel ».
- **Accessibilité** : focus trap, fermeture à la touche Échap.

### 5.4 Phases côté frontend

Les phases dans `gameState.phase` doivent correspondre à celles du moteur (voir `frontend/src/types/game.ts` et réponses API). Valeurs typiques : `"move"`, `"shoot"`, `"charge"`, `"fight"`.

---

## 6. Backend — Optionnel

- **Aucune modification obligatoire** : le tutoriel utilise `POST /api/game/start` avec `scenario_file` pointant vers les scénarios etape1/etape2/etape3 et `mode_code: "pvp_test"` (ou `"pvp"`).
- **Option** : ajouter un `mode_code: "tutorial"` qui impose un `scenario_file` par défaut si absent.

---

## 7. Ordre d'implémentation recommandé

1. **Murs** : extraire les murs extérieurs de `scenario_pvp_test.json` (sans murs intérieurs).
2. **Scénario Étape 1** : créer `config/scenario_tutorial_etape1.json` (Intercessor 12,20 ; Termagant 12,0 ; wall_hexes = périmètre).
3. **Scénario Étape 2** : créer `config/scenario_tutorial_etape2.json` (Intercessor + 3 Hormagaunts au contact ou aux positions (0,10),(12,0),(24,10)).
4. **Scénario Étape 3** : objectif central + 1 Intercessor.
5. **Étapes** : créer `tutorial_steps.json` avec steps pour etape 1, 2, 3 (triggers, textes).
6. **Popup** : implémenter `TutorialOverlay.tsx`.
7. **Moteur d'étapes** : hook/context avec transitions (reload scénario quand condition remplie).
8. **Entrée** : lien « Didacticiel » sur HomePage, lancement avec etape1.

---

## 8. Maintenance et évolutions

- **Règles** : si les phases ou les règles changent (`AI_TURN.md`), mettre à jour les textes dans `tutorial_steps.json`.
- **Scénarios** : les unités doivent exister dans `config/unit_registry.json`. Adapter les positions si la portée/LoS/charge du moteur change.
- **Tests** : vérifier manuellement le parcours (etape1 → etape2 → etape3) après chaque changement.

---

## 9. Résumé

| Élément | Décision |
|---------|----------|
| Murs | Extérieurs uniquement (périmètre de `scenario_pvp_test`, sans murs intérieurs). |
| Étape 1 | Intercessor (12,20), Termagant (12,0). Narrative : Termagant rate, joueur avance et tue. Version simplifiée : skip tour ennemi + popup. |
| Étape 2 | 3 Hormagaunts (0,10), (12,0), (24,10) ou au contact. Narrative : ils chargent, Marine -1 PV, tue 1 puis 2. Version simplifiée : Hormagaunts déjà au contact, popup « Ils viennent de charger ». |
| Étape 3 | Objectifs (tenir la zone centrale) ; règles spéciales en option (Étape 4 ou fiches). |
| Implémentation | Option B (simplifié) recommandée pour le MVP ; option A (script complet) si moteur évolue. |

Cette doc sert de spec d'implémentation pour le didacticiel ; toute modification de comportement ou de format doit être reportée ici.
