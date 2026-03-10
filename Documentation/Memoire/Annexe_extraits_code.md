# Annexe – Extraits de code significatifs

Contexte : moteur de jeu (step, handlers), API (démarrage partie), frontend (appel API). Fichiers dans le dépôt du projet.

---

## 1. Point d’entrée `step()` – Moteur (délégation aux phases)

**Fichier :** `engine/w40k_core.py`  
**Contexte :** Exécution d’une action gym (entier) : vérification des unités éligibles, conversion en action sémantique, délégation au handler de phase, mise à jour de l’observation.

```python
# Lignes 962-976 (extrait)
# Normalize raw action once and keep it in game_state for deterministic
# policy-driven rule-choice resolution in gym training mode.
action_int = self.action_decoder.normalize_action_input(
    raw_action=action,
    phase=require_key(self.game_state, "phase"),
    source="w40k_core.step",
    action_space_size=len(action_mask),
)
self.game_state["_last_raw_action_int"] = action_int

# Convert gym integer action to semantic action (reuse precomputed mask+eligible_units)
semantic_action = self.action_decoder.convert_gym_action(
    action_int, self.game_state, action_mask=action_mask, eligible_units=eligible_units
)
self.game_state["_last_semantic_action"] = copy.deepcopy(semantic_action)
# ... puis _process_semantic_action(semantic_action) qui appelle le handler de phase
```

---

## 2. Début de phase mouvement – Pool d’activation

**Fichier :** `engine/phase_handlers/movement_handlers.py`  
**Contexte :** Initialisation de la phase de mouvement : mise à jour de la phase, précalcul des hex adjacents aux ennemis, construction du pool d’unités éligibles au mouvement.

```python
# Lignes 96-107 (extrait)
def movement_phase_start(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    AI_MOVE.md: Initialize movement phase and build activation pool
    """
    # Set phase
    game_state["phase"] = "move"
    # ...
    units_cache = require_key(game_state, "units_cache")
    # Pre-compute enemy_adjacent_hexes once at phase start for all players present.
    players_present = set()
    for cache_entry in units_cache.values():
        player_raw = require_key(cache_entry, "player")
        # ...
        players_present.add(player_int)
    # Puis construction des pools (valid_move_destinations_pool, move_activation_pool, etc.)
```

---

## 3. Appel API frontend – Démarrage de partie

**Fichier :** `frontend/src/hooks/useEngineAPI.ts`  
**Contexte :** Détection du mode depuis l’URL, récupération du token de session, envoi de la requête POST pour démarrer une partie.

```typescript
// Lignes 301-314 (extrait)
const authSession = getAuthSession();
if (!authSession?.token) {
  throw new Error("Session utilisateur manquante. Merci de vous reconnecter.");
}

const response = await fetch(`${API_BASE}/game/start`, {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    Authorization: `Bearer ${authSession.token}`,
  },
  body: JSON.stringify(requestPayload),
});
```

---

*Ces extraits peuvent être insérés dans les annexes du mémoire avec la mention du fichier et des numéros de lignes (à vérifier après évolution du code).*
