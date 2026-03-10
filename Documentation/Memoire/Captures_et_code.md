# Captures d’écran et code correspondant (REV2)

Structure pour relier **captures d’écran** et **extraits de code** pour au moins la page d’authentification et l’interface de jeu (plateau). À intégrer dans le mémoire ou en annexe. **Tu dois ajouter toi-même les captures** (screenshot de l’app en fonctionnement).

---

## 1. Page d’authentification (/auth)

### Capture d’écran

**[Insérer ici une capture d’écran de la page de connexion : formulaire login/mot de passe, bouton Connexion / Inscription.]**

*Légende suggérée :* « Page d’authentification – Connexion et inscription (route /auth). »

### Code correspondant

**Fichier :** `frontend/src/pages/AuthPage.tsx`

**Extrait :** envoi de la requête de connexion et gestion de la réponse (token, redirection).

```tsx
const executeLogin = async (userLogin: string, userPassword: string): Promise<LoginResponse> => {
  const loginResponse = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ login: userLogin, password: userPassword }),
  });

  const loginPayload = await loginResponse.json();
  if (!loginResponse.ok) {
    const errorMessage = loginPayload?.error ?? "Echec de connexion";
    throw new Error(errorMessage);
  }

  return loginPayload as LoginResponse;
};
```

*Contexte :* Le formulaire (login, password) est soumis via `handleSubmit` ; en mode "login", `executeLogin` est appelé puis la session est enregistrée (`saveAuthSession`) et l’utilisateur est redirigé vers la page de jeu.

---

## 2. Interface de jeu – Plateau et panneau de contrôle (/game)

### Capture d’écran

**[Insérer ici une capture d’écran de l’interface de jeu : plateau hex (PIXI), panneau de contrôle (unités, phase, log), barre de mode (PvP, PvE, etc.).]**

*Légende suggérée :* « Interface de jeu – Plateau hexagonal et panneau de contrôle (route /game). »

### Code correspondant

**Fichier :** `frontend/src/hooks/useEngineAPI.ts`

**Extrait :** appel API pour démarrer une partie (mode PvE) et mise à jour de l’état de jeu.

```tsx
const response = await fetch(`${API_BASE}/game/start`, {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    Authorization: `Bearer ${authSession.token}`,
  },
  body: JSON.stringify(requestPayload),
});
// ...
if (data.success) {
  setGameState(data.game_state);
  // ...
}
```

*Contexte :* Au chargement de la page de jeu, `startGame()` est appelé ; il construit `requestPayload` (mode depuis l’URL, scénario éventuel), envoie la requête avec le token, et met à jour `gameState` avec la réponse. Le plateau et le panneau se rafraîchissent à partir de cet état.

**Fichier complémentaire (rendu du plateau) :** les composants qui affichent le plateau et les unités consomment `gameState` (ex. unités, phase, objectifs) ; le rendu des hexagones et des pions est géré par PIXI dans les composants dédiés au plateau (ex. dans `frontend/src/` selon ton architecture).

---

## Intégration au mémoire

- Dans la section **4.5** (ou équivalent) : pour chaque écran (auth, plateau), insérer la capture puis l’encadré « Code correspondant : fichier + extrait » comme ci-dessus.
- En **annexe** : tu peux répéter les mêmes blocs (capture + code) ou faire référence à cette structure.

Une fois les captures réalisées (screenshot depuis le navigateur sur l’app en local ou déployée), remplace les lignes « [Insérer ici…] » par les images dans ton document final (ODT/PDF).
