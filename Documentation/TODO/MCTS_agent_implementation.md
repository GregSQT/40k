# MCTS — documentation d’implémentation (temporaire)

> **Fichier** : `Documentation/TODO/MCTS_agent_implementation.md`  
> **Périmètre** : **implémentation technique uniquement** (API, hyperparamètres, config, bench).  
> **Spécification fonctionnelle** (rôle du macro, MCTS + PPO, objectifs produit, A/B) : **`Documentation/TODO/Macro_agent.md`** §**2.7** (et §**2.5–2.6** pour intents / criticité).

**Cycle de vie** : ce document est **provisoire**. Il doit être **supprimé** une fois l’implémentation **mergée** et la vérité portée par le **code**, les **tests** et la doc alignée (ex. `Documentation/TODO/MCTS_bot_final.md` ou équivalent). Aucune duplication fonctionnelle à maintenir ici après livraison.

**Hors périmètre** : MCTS comme **adversaire d’entraînement** (`opponent_mix`) — voir **`Documentation/MCTS_bot2.md`**, **`Documentation/MCTS_bot.md`**.

---

## 1. Contrat moteur : `GameAdapter`

MCTS ne duplique pas les règles dans `engine/` : un **`GameAdapter`** fournit au minimum :

| Opération | Rôle |
|-----------|------|
| `clone(state)` | État simulé indépendant |
| `legal_actions(state)` | Liste dans l’**espace de décision MCTS** choisi |
| `apply(state, action)` | Transition légale ; même sémantique que le jeu |
| `terminal(state)` | Fin de partie ? |
| `outcome_utility(state, joueur)` | Optionnel si feuille terminale |

Algorithmes UCT / backprop **deux joueurs** : **`Documentation/MCTS_bot2.md` §5–7** ; injection **prior** PPO et feuille \(V_\theta\) : voir spec projet.

---

## 2. Complexité de mise en œuvre (ordre de grandeur)

| Aspect | Commentaire |
|--------|-------------|
| **Ce n’est pas un simple `if`** | **GameAdapter**, arbre **PUCT/UCT**, **clones**, **backprop deux joueurs**, alignement **obs/masques** avec le train. |
| **Difficulté** | **Moyenne à élevée** : **macro + feuille value seule** = prototype plus simple ; **micro à chaque activation + rollouts** = beaucoup plus lourd. |
| **Config `enabled`** | Ne suffit pas sans **chemin code** réel ; le JSON ne fait que **router**. |

---

## 3. Configuration inférence (schéma illustratif)

Déclaration typique dans `config/agents/<Agent>/<Agent>_training_config.json` (charger aussi côté API : `services/api_server.py`, `config_loader.py`) :

```json
{
  "inference": {
    "mcts": {
      "enabled": false,
      "timeout_ms": 500,
      "max_simulations": 800,
      "c_puct": 1.5
    }
  }
}
```

- **`enabled: false`** : baseline forward **sans** arbre.  
- **`enabled: true`** : chemins et clés **validés** explicitement (pas de défauts silencieux anti-erreur).

Tant que le code MCTS n’est pas branché : erreur explicite ou comportement documenté.

---

## 4. Paramètres : deux familles

### 4.1 Garde-fous système / intégration

| Sujet | Point de vigilance |
|-------|---------------------|
| **Budget** | `N` simulations et/ou **timeout ms** par décision |
| **Device** | Policy/value GPU batchées si besoin ; sinon CPU si `N` petit |
| **Cohérence obs** | Même normalisation / masques qu’à l’entraînement ; clone aligné sur l’obs réseau |
| **Deux joueurs** | Alternance des perspectives — **`MCTS_bot2.md` §7.5** |
| **Erreurs** | Pas de fallback silencieux : erreur explicite ou repli **documenté** |

### 4.2 Hyperparamètres algorithme

| Famille | Exemples | Effet typique |
|---------|----------|----------------|
| **Budget** | `N` max ; `timeout_ms` | Qualité vs latence |
| **PUCT** | `c_puct` | Exploration vs prior |
| **Bruit racine** | Dirichlet (AlphaZero) | Ouvertures |
| **Feuille** | \(V_\theta\) seul ; rollout \(H\) ; mélange \(\lambda\) | Biais / coût |
| **Sélection finale** | Max visites vs max Q/N | Robustesse |
| **τ visites** | Échantillonnage à la racine | Stochasticité |
| **Périmètre** | Fréquence nœuds macro vs micro | Coût dominant |

Nommer en **config** ; versionner avec les benchmarks.

---

## 5. Évaluation et optimisation (implémentation)

### 5.1 Principe

1. Baseline : **même** checkpoint, **sans** MCTS.  
2. MCTS : même checkpoint, **sweep** §4.2 sous **budget temps** fixe.

### 5.2 Métriques externes

Winrate, Elo si dispo, protocole humain — voir aussi besoins **§2.7.5** dans `Macro_agent.md`.

### 5.3 Métriques internes

Latence p50/p95/p99 ; sims/s ; désaccord argmax policy vs max visites ; entropie des visites à la racine.

### 5.4 Protocole

Budget temps plafonné ; grille sur `c_puct`, `N`/timeout, feuille ; courbe **Pareto** qualité–latence ; geler le checkpoint pendant un sweep.

### 5.5 Pièges

Holdout ; ne pas ignorer la latence ; baseline **équitable** (même masque / obs).

---

## 6. Entraînement des poids utilisés en feuille / prior

Voir **`Documentation/AI_TRAINING.md`** — diversité scénarios / adversaires ; pas redocumenté ici.

---

## 7. Références techniques

| Document | Contenu |
|----------|---------|
| `Documentation/MCTS_bot2.md` | UCT, rollout, feuille §7.4, `GameAdapter` |
| `Documentation/MCTS_bot.md` | Variante |
| `Documentation/AI_OBSERVATION.md` | Obs / masques |
| `Documentation/TODO/Macro_agent.md` | **Fonctionnel** §2.5–2.7 |

---

## 8. Checklist avant suppression de ce fichier

- [ ] `GameAdapter` + MCTS branchés en inférence réelle  
- [ ] Config `inference.mcts` validée au chargement  
- [ ] Tests ou bench reproduisent les métriques §5  
- [ ] Spec fonctionnelle à jour dans `Macro_agent.md` si le comportement a divergé  
- [ ] Références pointant vers ce fichier mises à jour ou retirées  
