# Distance de pathfinding exacte — suppression de la troncature silencieuse

**Statut :** ✅ IMPLÉMENTÉ (2026-07-27, vérifié code + mesuré)
**Portée réelle :** bot PvE. **Pas** le pipeline d'entraînement V11 (voir §4, mesure).

---

## 1. Le défaut

`combat_utils.calculate_pathfinding_distance` calculait une distance BFS avec **deux bornes
fausses**, cumulées :

| Borne | Valeur | Problème |
|-------|--------|----------|
| `max_search_distance` | littéral `50` | interprété en SUBHEX. Or `game_rules.max_search_distance` vaut 50 **pouces** et est déjà converti en subhex par `w40k_core` (× `inches_to_subhex`). Sur board ×5 la profondeur réelle était donc 10", pas 50". |
| `max_open_nodes` | littéral `2000` | plafond de **nœuds étendus**. Le BFS s'arrêtait en plein parcours (`break`) et retournait `max_search_distance + 1`, c.-à-d. « injoignable », pour des cellules parfaitement atteignables. |

Le BFS étend ~3·d² nœuds pour atteindre la distance d : à d ≈ 26 subhex (≈ 5 pouces sur board
×5) le plafond était épuisé. **Tout ce qui était au-delà de ~5 pouces valait 51**, quelle que
soit la géométrie réelle.

Deux défauts annexes, trouvés en corrigeant :

- le bloc qui lisait `max_open_nodes` depuis `board_config` était **mort** : il cherchait
  `game_state["config"]["board_config"]`, or la clé posée par `w40k_core` est `"board"`. La
  valeur des `board_config.json` n'a donc jamais été appliquée ;
- `game_state["pathfinding_distance_cache"]` n'était purgé **nulle part**, ni au `reset()`, ni
  à la rotation de scénario. `game_state` étant le même objet d'un épisode à l'autre et les
  murs changeant (`train_wall_ref_weights`), un cache survivant servait des distances calculées
  sur un autre plateau.

---

## 2. Le correctif

**Profondeur depuis la config.** `max_search_distance=None` (défaut) ⇒ lecture de
`config["game_rules"]["max_search_distance"]`, déjà en subhex. Clé absente ⇒ `ConfigurationError`
explicite. Plus aucun littéral de distance dans la fonction.

**Plus aucun plafond de nœuds.** La seule borne est la profondeur, qui est une borne de RÈGLE
(§9.0). Un budget de nœuds ne coûte pas la distance, il la fausse.

**Champ BFS par source.** Nouveau `hex_utils.pathfinding_field()` : une passe depuis la source
renseigne la distance vers *toutes* les cellules (`uint16`, indexé `row * cols + col`,
sentinelle `PATHFINDING_UNREACHABLE`). C'est la forme utile ici — les appelants balayent des
paires d'unités, donc une même source sert N cibles pour un seul parcours. `pathfinding_distance`
(point-à-point) devient une enveloppe de ce champ : **une seule implémentation du BFS**, donc
aucune dérive possible entre les deux formes.

Le champ est mémoïsé dans `game_state["_pathfinding_field_cache"]`, clé `(col, row, profondeur)`,
cache FIFO plafonné à `PATHFINDING_FIELD_CACHE_MAX = 128` entrées (132 Ko par champ sur 220×300
⇒ 17 Mo au plafond ; l'ensemble de travail d'une obs est le nombre d'unités vivantes, ≤ ~80).

**Lecture symétrique.** Le graphe est non orienté et le franchissement ne dépend que des murs
(aucun `occupied_set` sur ce chemin), donc `d(a,b) == d(b,a)` — propriété vérifiée par test.
`calculate_pathfinding_distance` lit donc le champ de la CIBLE s'il est déjà mémoïsé, au lieu
d'en construire un second. C'est ce qui rend gratuit le motif « N sources, une cible fixe ».

**Accesseur explicite.** `combat_utils.get_pathfinding_field(game_state, col, row)` rend le champ
mémoïsé. À utiliser dès qu'un lot de points est comparé à un même point : un parcours au lieu de N.

**Purges.** `_pathfinding_field_cache` est retiré aux trois endroits où l'état d'épisode meurt :
`reset()`, `_reload_scenario()`, et le rechargement de topologie. Il est aussi déclaré statique
côté snapshots PvP (fonction pure des murs, invariants dans une partie) et exclu de la
sérialisation client (tableaux numpy à clés tuple).

**Nettoyage.** Le bloc `pathfinding` des trois `board_config.json` est supprimé :
`max_open_nodes` n'a plus de lecteur et `time_budget_us` n'en a jamais eu.

---

## 3. Contrat conservé

- retour = distance en hex, ou `max_search_distance + 1` si injoignable ;
- cible sur un mur ⇒ injoignable ;
- départ ou cible hors plateau ⇒ injoignable ;
- `occupied_set` : hex occupé = destination légale mais non traversable — le champ renseigne sa
  distance sans l'empiler, donc aucun chemin ne le traverse.

---

## 4. Portée mesurée — ce que ça corrige et ce que ça ne corrige pas

Les trois consommateurs identifiés par lecture de code (`observation_builder._calculate_danger_probability`,
`observation_builder._get_valid_targets`, `reward_calculator._calculate_danger_probability`)
**ne sont pas exécutés par le pipeline squad V11**. Mesure sur un épisode du scénario
d'entraînement Armageddon (board ×5, moteur nu, actions masquées aléatoires) :

```
60 steps → _build_observation: 61, calculate_reward: 50,
           _calculate_danger_probability: 0, _get_valid_targets: 0
```

L'observation et le reward de l'entraînement ne passent donc **jamais** par cette distance : le
défaut ne les a pas faussés. Le consommateur vivant est le **bot PvE**
(`pve_controller._ai_select_movement_destination`), qui choisit l'ennemi le plus proche et la
destination de mouvement avec cette distance : au-delà de ~5 pouces, toutes les cibles et toutes
les destinations étaient à égalité (51), donc `min()` tranchait arbitrairement. C'est ce
comportement-là qui est réparé.

**Coût côté entraînement** : bench A/B sur un épisode complet du scénario Armageddon (board ×5,
même seed, ancienne sémantique réimplémentée pour comparaison) — 84,1 ms/step contre
87,3 ms/step, soit +3,8 %, dans le bruit et cohérent avec le fait que l'entraînement n'appelle
pas la fonction.

**Coût côté PvE**, mesuré sur board 220×300 (scénario Armageddon, un pool de mouvement réel de
2195 destinations candidates) :

| Version | Coût d'une décision de mouvement | Exactitude |
|---------|----------------------------------|------------|
| avant | 1,63 ms × 2195 = **3,6 s** | non — tout au-delà de ~5" à égalité (51) |
| champ par source, boucle PvE inchangée | 62 ms × 2195 = **136 s** | oui |
| champ + lecture symétrique + boucle PvE corrigée | 62 ms × 1 = **0,062 s** | oui |

La ligne du milieu est le piège : mémoïser par SOURCE alors que la boucle du bot fait varier la
source et fixe la cible transforme le gain en régression d'un facteur 38. Le correctif est de
calculer le champ depuis le point FIXE (l'ennemi) et de lire chaque candidat dedans — c'est ce
que fait `pve_controller._ai_select_movement_destination`, et la lecture symétrique de
`calculate_pathfinding_distance` protège les appelants qui l'ignorent.

Sujet distinct ouvert par cette mesure : les sections d'observation héritées qui portent ces
appels semblent inertes dans le pipeline squad. Leur suppression n'a pas été traitée ici.

---

## 5. Tests

`tests/unit/engine/test_pathfinding_distance_exact.py` (11 cas) : profondeur issue de la config
scalée, borne de profondeur respectée, erreur explicite si la clé manque, absence de troncature
au-delà de l'ancien plafond, détour par les murs conservé, cible sur mur injoignable, cache
indexé par source et non par paire, sens inverse servi par le même champ, motif « N sources /
une cible » ne construisant qu'un seul champ, accesseur cohérent avec l'appel scalaire, purge
effective au `reset()` d'un moteur réel.

`tests/unit/engine/test_hex_utils.py` : le test qui verrouillait la troncature
(`test_max_open_nodes_budget`) est remplacé par son inverse
(`test_far_corner_is_exact_no_node_budget`), plus la symétrie, les cellules injoignables,
l'occupation, et une comparaison du champ à un **BFS oracle écrit dans le test**. Ce dernier
point est nécessaire : `pathfinding_distance` étant une enveloppe de `pathfinding_field`, les
confronter l'un à l'autre ne prouverait rien.
