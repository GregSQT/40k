# Didacticiel — Documentation d'implémentation

**Ce document est la spec complète pour le prompt qui implémentera le didacticiel.** Les sections 2.1–2.6 et 4 décrivent le scénario en 3 étapes, les positions et l'option scripté vs simplifié.

**Références projet** : `Documentation/AI_TURN.md` (phases, séquence de tour), `Documentation/AI_IMPLEMENTATION.md` (architecture).

---

## 1. Objectif et principe

Offrir aux nouveaux joueurs un **parcours guidé** : une partie pré-configurée où, à chaque étape clé, un **popup** explique une règle. Le joueur joue dans le vrai jeu (même moteur, même UI), avec des étapes et textes **data-driven** (JSON) pour faciliter la maintenance.

**Design d'immersion** : le joueur ne contrôle **qu'une seule unité** (un Intercessor). Le didacticiel est découpé en **3 étapes narratives** : (1) Mouvement + Tir, (2) Charge + Mêlée, (3) Objectifs ou règles spéciales. On n'utilise que les **murs extérieurs** du plateau pour libérer l'intérieur et garantir la LoS.

---

## 2. Périmètre fonctionnel et scénario en 3 étapes

**Murs (étapes 1 et 2)** : Pour les scénarios **etape1** et **etape2**, utiliser les murs définis dans **`config/board/25x21/walls/tutorial_walls-01.json`** (murs extérieurs uniquement : Ext-NW, Ext-NE, Ext-SW, Ext-SE). L'intérieur reste dégagé pour la ligne de vue. L'implémentation doit soit référencer ce fichier, soit injecter les hex listés dedans dans `wall_hexes` du scénario.

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

### 2.5 Fichiers scénario (tous dans `config/tutorial/`)

- **Étape 1** : `config/tutorial/scenario_etape1.json` — units : Intercessor (12, 20), Termagant (12, 0) ; **murs** : `config/board/25x21/walls/tutorial_walls-01.json` ; `objectives` optionnel.
- **Étape 2** : `config/tutorial/scenario_etape2.json` — units : Intercessor à la position choisie (ex. 12, 10), 3 Hormagaunts aux positions (0,10), (12,0), (24,10) ou **déjà au contact** (ex. (11,10), (12,9), (13,10)) ; **murs** : même fichier `config/board/25x21/walls/tutorial_walls-01.json`.
- **Étape 3** : `config/tutorial/scenario_etape3.json` (ou réutiliser etape1 + objectifs) — objectif Centre comme dans `scenario_pvp_test` ; un Intercessor à déplacer vers la zone ; **murs** : `config/board/25x21/walls/walls-01.json`.

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
| Entrée | Lien **« Tutorial »** depuis l'accueil / le menu | Lance une partie avec `mode_code` + `scenario_file` tutoriel. |

### 3.2 Flux

1. L'utilisateur clique sur **« Tutorial »** (depuis `HomePage` ou équivalent).
2. Le frontend appelle `POST /api/game/start` avec `mode_code: "pvp_test"` (ou un mode dédié) et `scenario_file` pointant vers `config/tutorial/scenario_etape1.json` (puis etape2, etape3 selon les transitions).
3. Le frontend charge `config/tutorial/tutorial_scenario.md` et lit le bloc `json tutorial-steps`.
4. Le **moteur d'étapes** (TutorialContext / useTutorialEngine) écoute les événements (phase, première action, etc.) et affiche le **TutorialOverlay** (popup) correspondant à l'étape courante.
5. Le joueur joue normalement ; les popups s'enchaînent. Transition entre étapes : chargement du scénario suivant (etape2 après kill Termagant, etape3 après combat, etc.).

### 3.3 Répertoire et fichiers — tout le tutoriel sous `config/tutorial/`

Tous les scénarios et le fichier d'étapes du tutoriel sont dans **`config/tutorial/`** :

| Fichier | Action |
|---------|--------|
| `config/tutorial/scenario_etape1.json` | **Créer** — Intercessor (12,20), Termagant (12,0) ; murs = `config/board/25x21/walls/tutorial_walls-01.json`. |
| `config/tutorial/scenario_etape2.json` | **Créer** — Intercessor + 3 Hormagaunts (positions au contact ou (0,10),(12,0),(24,10)) ; murs = `config/board/25x21/walls/tutorial_walls-01.json`. |
| `config/tutorial/scenario_etape3.json` (ou réutiliser etape1 + objectifs) | **Créer** — Objectif central, 1 Intercessor ; murs = `config/board/25x21/walls/walls-01.json`. |
| `config/tutorial/tutorial_scenario.md` | **Créer** — Source unique runtime: bloc `json tutorial-steps` (étapes) + bloc `json tutorial-ui-rules` (UI/fog/halos). |

Le frontend charge `tutorial_scenario.md` depuis ce répertoire et parse les blocs JSON taggés `tutorial-steps` et `tutorial-ui-rules`.

### 3.4 Composants frontend à créer / modifier

| Élément | Rôle |
|--------|------|
| **TutorialOverlay.tsx** | Composant React (modal) qui affiche une étape du tutoriel : **titre**, **corps** (texte du message), bouton **« Compris »** (ou « Suivant »), optionnel **« Passer le tutoriel »**. C'est l'UI du popup ; il ne gère pas la logique des étapes, seulement l'affichage et les callbacks (onClose, onSkipTutorial). |
| **TutorialContext** ou **useTutorialEngine** | **TutorialContext** : contexte React qui fournit à l'arbre l'état du tutoriel (étape courante, steps chargés, popup visible) et les fonctions (avancer d'étape, passer au scénario suivant). **useTutorialEngine** : hook qui encapsule la même logique (chargement de `tutorial_scenario.md` + parse du bloc `tutorial-steps`, écoute des triggers `phase_enter` / `after_action`, index d'étape, transition etape1 → etape2 → etape3). On peut avoir un context qui utilise le hook en interne. Les deux désignent le **moteur d'étapes** : quel popup montrer et quand, quand recharger le scénario. |
| **Lien « Tutorial » sur HomePage** | Lien ou bouton dont le **libellé visible** est **« Tutorial »** (pas « Didacticiel »). Au clic : navigation vers la partie en mode tutoriel (ex. `/game?mode=tutorial`) et lancement de la partie avec `scenario_file: "config/tutorial/scenario_etape1.json"`. |

| Fichier | Action |
|---------|--------|
| `frontend/src/components/TutorialOverlay.tsx` | **Créer** — Modal (titre, body, Compris, optionnel Passer). |
| `frontend/src/contexts/TutorialContext.tsx` ou `frontend/src/hooks/useTutorialEngine.ts` | **Créer** — État + logique triggers et transitions (voir ci-dessus). |
| `frontend/src/pages/HomePage.tsx` | **Modifier** — Ajouter un lien **« Tutorial »** (libellé exact) qui lance la partie avec mode tutoriel et scénario etape1. |
| `frontend/src/components/GamePageLayout.tsx` (ou composant qui lance la partie) | **Modifier** — Détecter le mode tutoriel et activer TutorialContext + TutorialOverlay. |
| `frontend/src/hooks/useEngineAPI.ts` (ou appel `game/start`) | **Modifier** — Passer `scenario_file` (ex. `config/tutorial/scenario_etape1.json`) pour le tutoriel. |
| `services/api_server.py` | **Optionnel** — Mode `tutorial` qui force `scenario_file` si absent ; sinon réutiliser `pvp_test` + scénario. |

---

## 4. Format des données

### 4.1 Scénarios tutoriel — murs par étape

Réutiliser le format des scénarios existants (voir `config/scenario_pvp.json` ou `config/scenario_pvp_test.json`). Types d'unités : `config/unit_registry.json` (Intercessor, Termagant, Hormagaunt).

**Murs** : **Étapes 1 et 2** : **`config/board/25x21/walls/tutorial_walls-01.json`** (murs extérieurs Ext-NW, Ext-NE, Ext-SW, Ext-SE). **Étape 3** : **`config/board/25x21/walls/walls-01.json`**. Selon le chargement des scénarios par le moteur : soit le scénario référence le fichier, soit on construit `wall_hexes` à partir des `hexes` dans `walls[]` du fichier.

**Étape 1 — Exemple `config/tutorial/scenario_etape1.json`** (avec `wall_ref`, voir §10.1) :

```json
{
  "primary_objectives": ["objectives_control"],
  "wall_ref": "tutorial_walls-01.json",
  "units": [
    { "id": 1, "unit_type": "Intercessor", "player": 1, "col": 12, "row": 20 },
    { "id": 2, "unit_type": "Termagant", "player": 2, "col": 12, "row": 0 }
  ],
  "objectives": []
}
```

(Alternative : `wall_hexes` inline, liste plate de `[col, row]` dérivée de `tutorial_walls-01.json`.)

**Étape 2 — Exemple simplifié (Hormagaunts déjà au contact)** : Intercessor (12, 10), 3 Hormagaunts (11,10), (12,9), (13,10). Même source de murs : **`config/board/25x21/walls/tutorial_walls-01.json`**.

**Étape 3** : Réutiliser objectif Centre de `scenario_pvp_test` (hex [[12,10],[11,9],[12,9],[13,9],[13,10],[12,11],[11,10]]), 1 Intercessor à placer. **Murs** : `config/board/25x21/walls/walls-01.json`.

### 4.2 Source d'étapes `config/tutorial/tutorial_scenario.md`

Fichier unique : **`config/tutorial/tutorial_scenario.md`**. Le runtime lit le bloc **`json tutorial-steps`**. Les steps peuvent être organisés par **etape** (1, 2, 3) avec des triggers `on_deploy`, `phase_enter`, `after_action`. Pour l'étape 1 : welcome, phase move, phase shoot, after shoot (kill Termagant) → transition vers scénario etape2. Pour l'étape 2 : phase fight, after fight → transition vers etape3. Pour l'étape 3 : objectif, end.

Structure possible : un tableau par etape, ou un tableau unique avec un champ `etape` (1|2|3) et ordre global. Voir 4.3 pour les types de trigger.

**Placeholders dans le corps (body_fr / body_en)** : le texte du popup peut contenir des balises remplacées par l’appli :
- **`<cursor>`** : affiche l’icône pointeur souris à cet endroit (ex. « Pour valider, <cursor> cliquez sur l’unité »). Si une ligne commence par « Cliquez » ou « Clickez » et ne contient pas `<cursor>`, l’icône est ajoutée automatiquement en début de ligne.
- Autres : `<Hex bleu foncé>`, `<icone termagant>`, `<Range>`, etc. (voir `TutorialOverlay.tsx`).

**Position du popup (optionnel)** : chaque step peut définir `popup_position` pour contrôler où s’affiche le popup dans la fenêtre (sans dépendre du plateau) :
- **Absent ou `"center"`** : popup centré (comportement par défaut).
- **`{ "left": "5%", "top": "10%" }`** : coin haut-gauche du popup à 5 % du bord gauche et 10 % du haut du viewport. On peut utiliser des pourcentages (`"20%"`) ou des pixels (`80`). L’utilisateur peut toujours déplacer le popup par glisser-déposer.

**Ancrage à un hex (extension possible)** : pour ancrer le popup près d’un hex du plateau (ex. au-dessus de l’unité ciblée), il faudrait ajouter `popup_anchor_hex: { "col": 12, "row": 10 }` et faire calculer les coordonnées viewport (hex → pixels) par le composant qui a accès au layout du plateau (ex. BoardPvp), puis passer cette position au TutorialOverlay. Non implémenté à ce jour ; la position viewport-relative ci-dessus suffit pour la plupart des cas.

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

- lance la partie avec `scenario_file: "config/tutorial/scenario_etape1.json"` ;
- active le **TutorialContext** / **useTutorialEngine** et rend le **TutorialOverlay**.

### 5.2 Moteur d'étapes et transitions

- **État** : `currentStepIndex`, `currentEtape` (1 | 2 | 3), `steps[]`, `popupVisible`.
- **Transitions** : Quand la condition de fin d'étape est remplie (ex. Termagant mort pour etape1), appeler `game/start` avec le scénario de l'étape suivante (etape2, puis etape3).
- **Logique** : Afficher les popups selon les triggers ; à « Compris », passer à l'étape suivante ou au prochain trigger.

### 5.3 Composant TutorialOverlay (popup)

- **Rôle** : afficher une étape (titre + corps) dans une modal ; pas de logique d'étapes, uniquement UI et callbacks.
- **Props** : `step: { title, body }`, `onClose: () => void`, `onSkipTutorial?: () => void`.
- **UI** : modal centré, titre, corps (texte ou HTML simple), bouton « Compris » (ou « Suivant »), optionnel « Passer le tutoriel ».
- **Accessibilité** : focus trap, fermeture à la touche Échap.

### 5.4 Phases côté frontend

Les phases dans `gameState.phase` doivent correspondre à celles du moteur (voir `frontend/src/types/game.ts` et réponses API). Valeurs typiques : `"move"`, `"shoot"`, `"charge"`, `"fight"`.

---

## 6. Backend — Optionnel

- **Aucune modification obligatoire** : le tutoriel utilise `POST /api/game/start` avec `scenario_file` pointant vers `config/tutorial/scenario_etape1.json` (puis etape2, etape3) et `mode_code: "pvp_test"` (ou `"pvp"`).
- **Option** : ajouter un `mode_code: "tutorial"` qui impose un `scenario_file` par défaut si absent.

---

## 7. Ordre d'implémentation recommandé

1. **Répertoire** : créer `config/tutorial/`.
2. **Murs** : pour etape1 et etape2, utiliser `config/board/25x21/walls/tutorial_walls-01.json` (murs extérieurs).
3. **Scénario Étape 1** : créer `config/tutorial/scenario_etape1.json` (Intercessor 12,20 ; Termagant 12,0 ; murs = tutorial_walls-01.json).
4. **Scénario Étape 2** : créer `config/tutorial/scenario_etape2.json` (Intercessor + 3 Hormagaunts au contact ou (0,10),(12,0),(24,10) ; murs = tutorial_walls-01.json).
5. **Scénario Étape 3** : créer `config/tutorial/scenario_etape3.json` (objectif central + 1 Intercessor ; murs = `config/board/25x21/walls/walls-01.json`).
6. **Étapes/UI** : créer `config/tutorial/tutorial_scenario.md` avec blocs `tutorial-steps` et `tutorial-ui-rules` pour etape 1, 2, 3 (triggers, textes, fog/halos).
7. **Popup** : implémenter `TutorialOverlay.tsx` (modal titre/corps/Compris/Passer).
8. **Moteur d'étapes** : TutorialContext ou useTutorialEngine (chargement steps, triggers, transitions etape1 → etape2 → etape3).
9. **Entrée** : lien **« Tutorial »** sur HomePage, lancement avec `scenario_file: "config/tutorial/scenario_etape1.json"`.

---

## 8. Maintenance et évolutions

- **Règles** : si les phases ou les règles changent (`AI_TURN.md`), mettre à jour `config/tutorial/tutorial_scenario.md` (blocs runtime).
- **Scénarios** : les unités doivent exister dans `config/unit_registry.json`. Adapter les positions si la portée/LoS/charge du moteur change. Tous les fichiers tutoriel restent dans `config/tutorial/`.
- **Tests** : vérifier manuellement le parcours (etape1 → etape2 → etape3) après chaque changement.

---

## 9. Résumé

| Élément | Décision |
|---------|----------|
| Config | Tous les fichiers tutoriel dans **`config/tutorial/`** : `scenario_etape1.json`, `scenario_etape2.json`, `scenario_etape3.json`, `tutorial_scenario.md`. |
| Entrée utilisateur | Lien **« Tutorial »** (libellé exact) sur HomePage ; au clic → partie avec `scenario_file: config/tutorial/scenario_etape1.json`. |
| TutorialOverlay | Composant modal (titre, corps, Compris, optionnel Passer) ; UI uniquement, pas la logique d'étapes. |
| TutorialContext / useTutorialEngine | Moteur d'étapes : état (étape courante, steps), triggers, transitions etape1→2→3 ; charge `config/tutorial/tutorial_scenario.md` (bloc `tutorial-steps`). |
| Murs | **Étapes 1 et 2** : `config/board/25x21/walls/tutorial_walls-01.json` (murs extérieurs). **Étape 3** : `config/board/25x21/walls/walls-01.json`. |
| Étape 1 | Intercessor (12,20), Termagant (12,0). Narrative : Termagant rate, joueur avance et tue. Version simplifiée : skip tour ennemi + popup. |
| Étape 2 | 3 Hormagaunts (0,10), (12,0), (24,10) ou au contact. Narrative : ils chargent, Marine -1 PV, tue 1 puis 2. Version simplifiée : Hormagaunts déjà au contact, popup « Ils viennent de charger ». |
| Étape 3 | Objectifs (tenir la zone centrale) ; règles spéciales en option (Étape 4 ou fiches). |
| Implémentation | Option B (simplifié) recommandée pour le MVP ; option A (script complet) si moteur évolue. |

---

## 10. Précisions pour l'implémentation

Points à respecter pour que l'implémentation soit complète sans ambiguïté :

### 10.1 Murs dans les scénarios JSON

Le moteur accepte **`wall_ref`** avec le **nom de fichier uniquement** (résolution depuis `config/board/25x21/walls/`). Dans les scénarios tutoriel :

- **Étapes 1 et 2** : `"wall_ref": "tutorial_walls-01.json"`
- **Étape 3** : `"wall_ref": "walls-01.json"`

Ne pas mettre de chemin (pas de `config/board/...`). L’extension `.json` peut être omise (ajoutée automatiquement). Alternative : `wall_hexes` inline (liste plate de `[col, row]`) si on ne veut pas dépendre du fichier.

### 10.2 API game/start

- **scenario_file** : chemin **relatif à la racine du projet** (CWD du serveur). Ex. `"config/tutorial/scenario_etape1.json"`.
- **mode_code** : aujourd’hui `"tutorial"` n’est pas dans les modes autorisés. Pour le MVP, utiliser **`mode_code: "pvp_test"`** avec **`scenario_file: "config/tutorial/scenario_etape1.json"`**. Option ultérieure : ajouter `"tutorial"` côté backend et imposer le scénario par défaut.

### 10.3 Chargement de tutorial_scenario.md

Le frontend charge les configs depuis `/config/...` (Vite sert `frontend/public/` à la racine). Pour `tutorial_scenario.md` :

- importer le markdown brut et parser les blocs JSON taggés `tutorial-steps` et `tutorial-ui-rules` côté frontend ;
- ou exposer un endpoint (ex. **GET /api/config/tutorial/steps**) qui lit `config/tutorial/tutorial_scenario.md` et renvoie les `steps` extraits du bloc `tutorial-steps`.

### 10.4 Conditions de transition entre étapes

- **Étape 1 → 2** : plus aucune unité ennemie vivante (Termagant mort). Le moteur d’étapes peut détecter l’absence de l’unité joueur 2 dans le cache / game_state après mise à jour.
- **Étape 2 → 3** : phase combat terminée (ou plus d’Hormagaunts vivants). Idem : détection côté frontend via game_state.
- Après validation de la condition : appeler `POST /api/game/start` avec le scénario de l’étape suivante (etape2 puis etape3) pour recharger la partie.

### 10.5 Bouton « Passer le tutoriel »

Comportement à trancher : (a) désactive uniquement les popups et le moteur d’étapes (la partie continue en mode normal), ou (b) ferme la partie et retourne au menu. Documenter le choix dans ce paragraphe ou dans `tutorial_scenario.md`.

### 10.6 Scénario étape 3 — objectifs

Comme `config/scenario_pvp.json`, le scénario etape3 doit contenir **`primary_objectives`** et **`objectives`** (ou `objectives_ref`). Pour « zone centrale » : réutiliser l’objectif Centre (ex. `[[12,10],[11,9],[12,9],[13,9],[13,10],[12,11],[11,10]]`). Les types d’unités (ex. `Intercessor`) doivent exister dans `config/unit_registry.json`.

---

Cette doc sert de spec d'implémentation pour le didacticiel ; toute modification de comportement ou de format doit être reportée ici.
