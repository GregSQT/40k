# V11 — Encodeur d'entités partagé + tête pointeur (et les trous qu'il ferme)

Ouvert le **2026-07-26**. Chantier issu d'une seule question de l'utilisateur — « tout est optimal
et documenté ? » — posée après la livraison de §9.2.5 (observation des règles d'armes). La
vérification a trouvé **six trous**, dont un qui rend une unité ennemie invisible et intirable dans
la majorité des épisodes.

**Convention d'ancrage** (identique au reste de la doc V11) : l'ancre est le **nom de fonction** ;
les numéros de ligne sont indicatifs. Re-localiser par grep avant d'éditer.

> **Documents liés**
> - [`V11_agent_rework.md`](V11_agent_rework.md) — §9.2.5 (observation des règles, livré), §9.2.7
>   (trou 10.05/10.06), §9.3 (P2, mécanisme générique de décision), §9.0bis (critère du *regret*).
> - [`V11_audit_observation.md`](V11_audit_observation.md) — §7 (découpe structurée du vecteur),
>   §9.9 (raisonner en ensembles), §11 (reste à faire). Ce document **exécute** le « Niveau 1/2 »
>   que §7.3 laissait en réserve.

---

## 0. Statut

| Tranche | Objet | Statut |
|---|---|---|
| **T-A** | Renommage `PISTOL` → `CLOSE_QUARTERS` | ✅ **FAIT (2026-07-26)** |
| **T-B** | Tir d'assaut 10.05 + tir à bout portant 10.06 dans le gate squad/gym | ✅ **FAIT (2026-07-26)** |
| **T-C** | Sélection d'armes : défaut correct (04.01 / 04.02) + heuristique mêlée consciente des règles | ⏳ à faire |
| **T-D** | Observation en **tenseurs d'entités** + **encodeurs partagés** | ⏳ à faire |
| **T-E** | **Tête pointeur** + slots ennemis 5 → 20 (espace d'action) | ⏳ à faire |
| **T-F** | K armes = 10 des deux côtés + bloc « types de figurines » ennemis | ⏳ à faire |
| **T-G** | Run `--new` + win-rate (§0.14) | ⏳ bloqué par T-A→T-F |

---

## 1. Constats — ce qui a été trouvé, avec sa preuve

Tous les faits ci-dessous ont été **lus dans le code ou mesurés in-engine** le 2026-07-26, pas
déduits. Les règles sont citées depuis `Documentation/40k_rules/`.

### 1.1 🔴 Six escouades ennemies pour cinq slots — une unité invisible ET intirable

`init_enemy_slot_mapping` (shared_utils) fige **5 slots** au début de partie, triés par menace
`HP × OC`, et la fonction est **idempotente** — le mapping n'est jamais recalculé. `SQUAD_ACTION_
SHOOT_SLOT_COUNT = 5`, et les actions de tir sont `slot 0..4`.

**Mesure** (10 `reset()` sur `scenario_training_armageddon.json`, rosters réels) :

| Escouades (P1, P2) | Occurrences |
|---|---|
| (5, 5) | 3 |
| **(6, 6)** | **5** |
| (6, 5) | 1 |
| (5, 6) | 1 |

⇒ **dans 6 épisodes sur 10, au moins une escouade ennemie n'a aucun slot.** Conséquences :
- elle est **absente de l'observation** (aucun bloc ne la décrit) ;
- elle est **impossible à prendre pour cible au tir** pour toute la partie ;
- quand une escouade mappée meurt, son slot passe à `None` **définitivement** — il n'est jamais
  réattribué à celle qui n'est pas mappée.

Elle reste chargeable et combattable (charge et fight sont des actions uniques dont la cible est
résolue par le moteur). C'est donc un **plafond d'espace d'action**, silencieux, non logué.

### 1.2 🔴 Le gym ignore deux types de tir entiers (10.05 et 10.06)

`build_squad_action_mask` (branche `phase == "shoot"`) calcule
`can_shoot = not has_fled and not has_advanced and not has_shot and not in_er`, **sans aucune
exception d'arme**.

- **PDF 10.05 — ASSAULT SHOOTING** : éligible si « Unengaged **and made an advance move this
  turn** » et l'unité a ≥1 arme [ASSAULT] ; *while shooting*, seules les armes [ASSAULT] peuvent
  être sélectionnées.
- **PDF 10.06 — CLOSE-QUARTERS SHOOTING** : éligible si « **Engaged** and did not make an advance
  move this turn » et l'unité a ≥1 arme [CLOSE-QUARTERS] **ou est MONSTER/VEHICLE** ; *while
  shooting*, les figurines peuvent cibler les unités avec lesquelles l'unité est engagée.

Le chemin **PvP/mono-figurine** connaît les deux (`_can_shoot` filtre les armes selon
`is_adjacent` / `has_advanced` — shooting_handlers ~2296 ; `_weapon_has_assault_rule`,
`_weapon_has_pistol_rule`). Le chemin **squad/gym** non. C'est le motif de §9.1 : une règle vive
sur un chemin, absente de l'autre.

**Sens de l'écart** : le gate gym est **plus strict** que les règles (il refuse des tirs légaux),
donc jamais laxiste — mais l'agent ne peut apprendre ni le tir d'assaut ni le tir à bout portant,
et les **30 armes [PISTOL] / 22 [ASSAULT]** des armories perdent tout intérêt tactique côté IA.

Note : une partie de la machinerie 10.06 existe déjà côté squad (`squad_shoot_blink_targets`
restreint aux armes Pistol quand l'escouade est engagée ; l'exclusion pistolet/non-pistolet est
appliquée dans `squad_shoot_weapon_profiles_for_menu`). **C'est le gate qui bloque en amont.**

### 1.3 🔴 Au tir, le gym ne choisit rien : arme 0, une seule arme, une seule cible

`squad_declare_shoot` (shared_utils) fait `weapon_idx = m.get("selectedRngWeaponIndex")` avec
**0** par défaut. Or `selectedRngWeaponIndex` n'est écrit que par `_process_squad_manual_shoot`
(w40k_core), c'est-à-dire le **chemin PvP manuel**. En gym il vaut donc **0 pendant toute la
partie**, et un seul intent est créé par figurine.

Trois écarts, dont deux sont des **violations de règle** :

| Fait | Règle | Verdict |
|---|---|---|
| Une figurine ne tire qu'**une** arme | **04.01** : « WHILE SHOOTING: You can select **one or more** ranged weapons that model has » | ❌ violation |
| Toutes les armes d'une figurine tirent la **même** cible | **04.02** : « For each weapon selected: select one enemy unit to be the target **of that weapon** » | ❌ violation |
| L'arme tirée est l'index 0, jamais choisie | 04.01 (« select which weapons ») | ❌ décision du joueur non prise |

**Mesure** (un épisode réel) : **28 figurines portent ≥2 armes de tir**, dont **6 tirent une arme
de portée inférieure à leur maximum**. Exemples : `LandSpeederOnslaughtGatlingCannon` tire
toujours son Multi-Melta et **jamais** son Stormfury Missile Launcher ; `Ancient` et `Librarian`
tirent leur Bolt Pistol au lieu de leur Bolt Rifle / Smite.

✅ **Bonne nouvelle vérifiée** : le **modèle de données du moteur est déjà correct**. Un intent est
`(model_id, weapon_index) → target_unit_id`, et `declare_attack_weapon` (moteur générique
paramétré par `ctx`, partagé tir/combat) gère déjà la **cible par arme** avec remplacement. Le
correctif porte donc sur la **déclaration gym**, pas sur la structure.

### 1.4 🟠 L'heuristique de choix d'arme de mêlée a été périmée par P1

`_auto_select_cc_weapon_for_fig` choisit l'arme maximisant
`P(hit) × P(wound) × P(failed_save) × D` — calculé sur les **caractéristiques brutes uniquement**.
Elle ignore **toutes** les règles rendues vives par P1 le 2026-07-26 : [ANTI-X] (seuil de blessure
critique abaissé), [DEVASTATING WOUNDS], [SUSTAINED HITS], [LETHAL HITS], [TWIN-LINKED], [MELTA]
(bonus de D à demi-portée), [CLEAVE], [PRECISION].

Conséquence concrète : `urty_syringe` ([ANTI-INFANTRY 1+] + [EXTRA ATTACKS] + [PRECISION]) ne sera
jamais préférée contre de l'infanterie ; `relic_greataxe` ([DEVASTATING WOUNDS]) est jugée sur ses
seules stats. **P1 a rendu cette heuristique fausse** — c'est une dette créée par la tranche
précédente, pas une dette héritée.

Elle contient par ailleurs un `try/except` qui retombe silencieusement sur `float(dmg_raw)` : repli
masquant, interdit par la convention projet.

### 1.5 🟠 K ennemi = 2 profils de tir + 1 de mêlée : trop pauvre (arbitrage corrigé)

Arbitrage pris lors de §9.2.5 pour contenir la dimensionnalité. **Mesure** : une escouade des
rosters d'entraînement porte jusqu'à **6 profils de tir et 5 de mêlée distincts** (persos attachés
compris). Avec K=2+1, l'agent ne voit donc **jamais l'arme d'exception d'un ennemi** (le fuseur du
sergent, l'arme [ANTI] du perso attaché) — tronqué à chaque épisode, logué mais bien perdu.

Décision utilisateur : **au moins 5+5, idéalement symétrique de ma propre escouade** (base, arme
spéciale, sergent, leader, support). Retenu : **K = 10 par registre, des deux côtés** (cf. §2).

### 1.6 🟠 Les ennemis n'ont aucun bloc « types de figurines »

Mon escouade dispose d'un bloc `SQUAD_N_MODEL_TYPES = 6` (profil défensif + rôle + effectif vivant
par type). Les slots ennemis n'ont qu'un **profil défensif d'escouade** issu de la datasheet
(HP_MAX / T / save / invul) + taille + PV totaux.

**Mesure** : jusqu'à **5 types défensifs distincts** par escouade (distribution sur 10 resets :
1 type → 64 escouades, 2 → 8, 4 → 32, 5 → 8). L'agent ne peut donc pas voir qu'un Nob est plus dur
que les Boyz qui l'entourent — alors que c'est exactement ce qui décide de l'allocation des pertes
et de la rentabilité d'une cible.

### 1.7 🟢 `PISTOL` vs `CLOSE-QUARTERS` — renommage, pas un bug

**PDF 24.27** : « [PISTOL] and [CLOSE-QUARTERS] are identical for all rules purposes. See
[CLOSE-QUARTERS]. *Designer's Note*: [PISTOL] is a pre-existing ability that will be superseded by
[CLOSE-QUARTERS] as this edition of Warhammer 40,000 progresses. »

**État vérifié** : `CLOSE_QUARTERS` / `CLOSE-QUARTERS` **n'existe nulle part** comme identifiant —
zéro occurrence en Python, TypeScript ou JSON, seulement deux mentions en commentaire
(shooting_handlers ~2296-2297). Tout le projet utilise `PISTOL` : **53** occurrences dans
`engine/` + `ai/`, **30** dans `frontend/src`, la clé `"PISTOL"` de `config/weapon_rules.json`, et
**30 armes** des armories.

Ce n'est donc **pas une violation de règle** (les deux termes sont fonctionnellement identiques),
mais l'utilisateur a tranché le **renommage** pour supprimer toute ambiguïté (2026-07-26).

### 1.8 📊 Le vrai coût de K : c'est le format PLAT, pas K

L'observation est aujourd'hui un **vecteur plat** : les slots ennemis sont concaténés, et la
première couche du réseau a un poids distinct par dimension **de chaque slot**.

**Mesures (2026-07-26)** :

| Grandeur | Valeur |
|---|---|
| `obs_size` après §9.2.5 | 1 011 (`vec_cont` 459 + `vec_bin` 552) |
| `features_dim` (CNN 256 + vecteur) | 1 267 |
| paramètres de la policy | **2 459 672** |
| couches consommant `features_dim` | 2 × `(320, 1267)` — une pour π, une pour V |
| **paramètres ajoutés par dimension d'observation** | **640** |
| `build_squad_observation` | 3,95 ms |
| dont bloc profils d'armes | 0,33 ms (8,4 %) |
| step moyen | 70,5 ms → l'observation = **5,6 %** d'un step |

Coût du bloc profils selon K, pour les **5 slots ennemis** :

| K | temps | dims |
|---|---|---|
| 2+1 (actuel) | 0,233 ms | 465 |
| 5+5 | 0,294 ms | 1 550 |
| 6+5 | 0,311 ms | 1 705 |

⇒ **le calcul n'est pas le sujet** (+0,06 ms = +0,09 % d'un step). Le coût est en **paramètres** :
à 640 params/dim, K=20 ennemis au format plat coûterait **~4,5 M paramètres**, soit presque le
double du réseau entier. C'est le format plat qui interdit K, pas K.

---

## 2. Décisions actées (utilisateur, 2026-07-26)

1. **Renommage `PISTOL` → `CLOSE_QUARTERS`** partout (code, config, armories, frontend, tests),
   avec un verrou interdisant la réapparition de l'ancien identifiant.
2. **Réparer 10.05 et 10.06 sur le chemin squad/gym.** Les deux, pas seulement 10.06 : c'est la
   même ligne de code, en corriger une seule serait livrer un demi-correctif.
3. **Encodeur d'entité partagé** pour les **quatre** familles : unités amies, unités ennemies,
   armes amies, armes ennemies. Une arme est une arme des deux côtés ; une unité est une unité.
4. **`K = 20` unités**, **`K = 10` armes** par registre et par unité.
5. **Tête pointeur** : les logits de ciblage sont produits par score `q · e_i` sur les embeddings,
   pas par aplatissement.
6. **Le retrain complet est accepté** (« peu importe le besoin de re-train »).
7. **Chaque arme peut avoir une cible différente** (04.02) — à traiter dans T-C, la structure
   d'intents du moteur le permet déjà.
8. **Le choix d'arme par l'agent** (vs. défaut automatique) est **différé à P2/P3** — cf. §5.3.

---

## 3. Architecture cible

### 3.1 Le critère de découpe : « une action pointe-t-elle sur cette entité ? »

Ce n'est **pas** « ami vs ennemi ». C'est ce qui décide entre agrégation et identité par slot.

| Famille | Une action la désigne ? | Traitement | K |
|---|---|---|---|
| Unités **ennemies** | ✅ `shoot slot 0..K-1` | embeddings **par slot** + **tête pointeur** | 20 |
| Unités **amies** | ❌ — le moteur impose l'unité active (`eligible_units[0]`, `w40k_core::_build_observation`) | encodeur partagé + **agrégation** | illimité |
| Armes **amies** | ❌ pas aujourd'hui (cf. §5.3) | encodeur partagé + agrégation par unité | 10 / registre |
| Armes **ennemies** | ❌ jamais | encodeur partagé + agrégation par unité | 10 / registre |
| **Types de figurines** | ❌ | encodeur partagé + agrégation (le plafond `K=6` disparaît) | illimité |

⚠️ **L'agrégation détruit l'identité par slot.** C'est pour cela qu'elle est **interdite pour les
ennemis** : l'alignement obs-slot-i ↔ action-slot-i est précisément ce que le fix **D1** a rétabli
(cf. `V11_audit_observation.md` §8). Une agrégation Deep Sets dirait « il y a un ennemi coriace »
sans dire **lequel viser**.

### 3.2 Principe à verrouiller : embeddings par entité TOUJOURS, agrégation seulement au tronc

Les embeddings par entité sont **toujours calculés et conservés** ; seule l'entrée du tronc agrège
ceux qu'aucune action ne désigne aujourd'hui.

Bénéfice direct : le jour où une action pointe sur une **arme** (choix d'arme agent, §5.3) ou sur
une **unité amie** (choix de l'ordre d'activation — une vraie décision 40K que le moteur prend
aujourd'hui à la place du joueur), il suffit de **brancher une tête pointeur de plus sur des
embeddings qui existent déjà**. Aucune réécriture, aucune migration d'observation.

### 3.3 Schéma

```
armes (K=10 × F_w)  ──► E_w partagé ──► embeddings d_w ──┐
                                                          ├─► concat ──► E_u partagé ──► e_i (d_u)
features d'unité (F_u brut, + bit is_ally) ───────────────┘

  e_own ────────────────────────────────┐
  Σ/max e_ally  (agrégation)            ├─► tronc MLP ──► q (requête)
  Σ/max e_enemy (agrégation, contexte)  │                  │
  features globales + CNN(grille)  ─────┘                  │
                                                            ▼
                              logits de tir_i = q · e_enemy_i     (K-indépendant)
                              logits de move / charge / fight / zone intent : têtes classiques
```

- `E_w` est **le même** pour mes armes et celles de l'ennemi.
- `E_u` est **le même** pour mes escouades et les ennemies, avec un bit `is_ally` et un **schéma de
  features unifié** (les features propres à un camp sont à zéro pour l'autre, avec leur masque).
- Le réseau **généralise entre slots** : ce qu'il apprend sur le slot 2 sert au slot 9. Au format
  plat, chaque slot apprend de zéro.

### 3.4 Coût estimé

⚠️ **Estimations, à confirmer à la construction** (les seules valeurs *mesurées* sont celles de
§1.8).

| | aujourd'hui | cible |
|---|---|---|
| K ennemis | 5, dur et silencieux | 20, masqué et **logué** |
| K armes / unité | 6+5 (moi), 2+1 (ennemi) | 10 par registre, des deux côtés |
| params tronc + têtes | ~2,4 M | **~0,9 M** |
| coût d'un slot ennemi supplémentaire | ~226 k params | **0** (tête pointeur) |

Le réseau devient donc **plus petit** tout en n'étant plus borné.

---

## 4. Plan d'implémentation

Ordre retenu : **T-A → T-B → T-C → T-D → T-E → T-F → T-G**. Les trois premières tranches sont du
moteur pur, testables isolément et **sans effet sur `obs_size`** ; T-D/T-E/T-F sont l'architecture
et se valident ensemble.

### T-A — Renommage `PISTOL` → `CLOSE_QUARTERS`

**Périmètre** : `config/weapon_rules.json` (clé + description alignée sur 24.07/24.27), les 3
armories `frontend/src/roster/*/armory.ts` (30 armes), les 53 sites Python, les 30 sites
TypeScript, les tests.

**Critères d'acceptation**
- `grep -rn "PISTOL"` ne renvoie plus que des mentions historiques explicites (commentaires citant
  24.27), zéro identifiant.
- Verrou de non-régression : un test échoue si l'identifiant `PISTOL` réapparaît dans un
  `WEAPON_RULES` ou dans un prédicat moteur.
- Suite d'armes et suite de tir vertes, sans modification de leur contenu métier.

### T-B — Tir d'assaut 10.05 et tir à bout portant 10.06 dans le gate squad/gym

**Point d'insertion** : `build_squad_action_mask`, branche `phase == "shoot"` — remplacer
`not has_advanced and not in_er` par la résolution du **type de tir applicable** :

| Situation | Type | Armes sélectionnables |
|---|---|---|
| unengaged, pas d'advance | 10.04 normal | toutes |
| unengaged, a advancé, ≥1 arme [ASSAULT] | 10.05 assault | [ASSAULT] uniquement |
| engagée, pas d'advance, ≥1 arme [CLOSE_QUARTERS] **ou** MONSTER/VEHICLE | 10.06 close-quarters | [CLOSE_QUARTERS] uniquement ; cibles restreintes aux unités engagées |
| sinon | — | pas de tir |

**Attention** : la restriction de **cible** de 10.06 (« target enemy units your unit is engaged
with ») doit être portée dans le masque *et* dans la déclaration, pas seulement dans l'un des deux
— sinon on rouvre la classe de bug « masque ⊄ exécutable ».

**Critères d'acceptation**
- Un test par type de tir, **bout-en-bout via le masque réel** (pas via le helper seul).
- Contre-épreuve mutation : neutraliser chaque branche rend au moins un test rouge.
- Miroir PvP : le comportement mono-figurine existant reste inchangé (verrou).
- Le `MONSTER/VEHICLE` de 10.06 est traité ou explicitement documenté comme non implémenté
  (aujourd'hui il ne l'est pas — cf. le commentaire de `_can_shoot`).

### T-C — Sélection d'armes : le défaut correct (04.01 / 04.02)

Ce n'est **pas** le choix agent (différé, §5.3) : c'est la correction du défaut, qui est
aujourd'hui une violation de règle.

1. **Tir** — `squad_declare_shoot` déclare, pour chaque figurine, **toutes ses armes éligibles**
   (04.01 « one or more »), en respectant l'exclusion 24.07 (les armes [CLOSE_QUARTERS] et les
   autres ne se mélangent pas sur une même figurine hors MONSTER/VEHICLE) et le type de tir résolu
   en T-B. Un intent **par arme**.
2. **Cible par arme** (04.02) : chaque arme choisit sa cible indépendamment, avec la même règle de
   priorité qu'aujourd'hui (cible prioritaire du slot d'action si atteignable, sinon premier slot
   éligible **pour cette arme** — la portée diffère d'une arme à l'autre). La structure d'intents
   du moteur le permet déjà (`declare_attack_weapon`).
3. **Mêlée** — `_auto_select_cc_weapon_for_fig` devient **conscient des règles** : l'espérance de
   dégâts doit passer par le socle de résolution ([`attack_sequence.py`](../../engine/phase_handlers/attack_sequence.py)),
   pas par un calcul parallèle. Une 5ᵉ implémentation d'espérance de dégâts est **interdite** (cf.
   `V11_audit_observation.md` §8, « ne pas coder de 5ᵉ logique inline »). Retirer au passage le
   `try/except` de repli sur `DMG`.

**Critères d'acceptation**
- Un test montrant qu'une figurine à 2 armes de tir produit **2 intents** et inflige les deux lots
  d'attaques (rouge avant le fix).
- Un test montrant deux armes d'une même figurine sur **deux cibles différentes** (04.02).
- Un test montrant que l'heuristique mêlée préfère une arme [ANTI-X] contre une cible portant le
  keyword, et ne la préfère pas sinon (rouge avant le fix).
- Contre-épreuve mutation sur chacun.
- ⚠️ **Impact PvP** : chemin partagé — l'équilibre PvP change aussi. À signaler et à re-jouer via
  `scripts/pvp_smoke_test.py`.

### T-D — Observation en tenseurs d'entités + encodeurs partagés

**Nouveau contrat d'observation** : le `Dict` passe de
`{vec_cont, vec_bin, grid}` à `{global_cont, global_bin, allies(K_a × F_u), enemies(20 × F_u), grid}`,
chaque entité portant ses armes en sous-tenseur `(10 × F_w)` par registre.

**Points durs identifiés** (à traiter, pas à découvrir) :
- **`VecNormalize` casse le partage de poids.** Il normalise élément par élément : chaque slot
  aurait ses propres statistiques, donc le même encodeur verrait des échelles différentes selon le
  slot. ⇒ **normaliser DANS l'encodeur** (LayerNorm ou scaler par feature) et sortir ces clés de
  `norm_obs_keys`. Ne pas laisser ce point implicite.
- Tout ce qui **lit** l'observation change de contrat : tests d'observation, outillage, analyzer.
- Les accesseurs de layout actuels (`squad_enemy_cont_base`, etc.) disparaissent au profit d'un
  accès par entité — c'est ce qui a permis aux 6 fichiers de tests d'obs de survivre à §9.2.5 sans
  modification ; il faut leur offrir un équivalent.

**Critères d'acceptation**
- L'observation reste **exactement équivalente en information** à l'actuelle sur un état donné
  (test d'équivalence entité par entité).
- La politique se construit et fait un forward (comme la vérification faite pour §9.2.5).
- Un test vérifie que le **même** encodeur d'arme est appliqué à une arme amie et à la même arme
  côté ennemi (partage effectif des poids, pas deux modules).

### T-E — Tête pointeur + slots ennemis 5 → 20

**Espace d'action** : `SQUAD_ACTION_SHOOT_SLOT_COUNT` 5 → 20, `TOTAL_ACTION_SIZE` mis à jour, avec
le miroir `engine/macro_intents.py` ↔ `shared_utils` (verrouillé par
`test_action_space_mirror.py`, cf. T2 de §5).

**Policy** : les logits de tir viennent de `q · e_i`. C'est la **zone à risque** du chantier :
`log_prob`, entropie et masquage doivent rester corrects sous `MaskablePPO`.

**Critères d'acceptation**
- `init_enemy_slot_mapping` couvre **toutes** les escouades ennemies ; le dépassement de K=20 est
  **logué**, jamais silencieux. Test sur un scénario à >20 escouades ennemies.
- Le mapping **réattribue** les slots libérés par une escouade morte, ou documente explicitement
  pourquoi non (aujourd'hui il ne le fait pas — c'est un des volets du trou §1.1).
- Test : sur un état à 6 escouades ennemies, les 6 sont dans l'observation **et** tirables.
- Tests de correction PPO : cohérence `log_prob` / entropie / masque entre la tête pointeur et une
  tête dense de référence sur un cas jouet.

### T-F — K armes = 10 des deux côtés + types de figurines ennemis

Devient quasi gratuit une fois T-D/T-E en place (coût en compute, pas en paramètres). Referme
§1.5 et §1.6.

**Critères d'acceptation**
- Aucun profil tronqué sur les rosters réels (mesuré : max 6 tir / 5 mêlée) ; dépassement logué.
- Les types défensifs ennemis sont exposés (mesuré : jusqu'à 5 par escouade).

### T-G — Run `--new` et win-rate

`python3 ai/train.py --agent ArmageddonAgent --training-config x5_new --new`.
Rejoint **§0.14**. Prérequis désormais levés : §0.27 (garde-fou d'éval) et §9.2.5 (observation des
règles) sont livrés.

---

## 5. Risques et arbitrages

### 5.1 Risques techniques

| Risque | Mitigation |
|---|---|
| Tête pointeur : `log_prob`/entropie/masquage incorrects sous MaskablePPO — **échoue silencieusement** (le training tourne, il apprend mal) | tests de correction contre une tête dense de référence, sur cas jouet, **avant** tout run long |
| `VecNormalize` par élément annule le partage de poids | normalisation dans l'encodeur, clés sorties de `norm_obs_keys` |
| Changement de contrat d'observation → outillage/analyzer périmés | traiter analyzer et outillage **dans** T-D, pas après |
| T-C change l'équilibre **PvP** (chemin partagé) | `scripts/pvp_smoke_test.py` + validation runtime utilisateur |
| Chantier long → tentation de valider « au vu » | chaque tranche = tests + contre-épreuve mutation, comme P1 |

### 5.2 Ce que ce chantier NE fait pas

- **P2** (mécanisme générique de décision agent) reste fermé. T-C corrige un **défaut**, il ne
  transfère aucune décision à l'agent.
- Le **choix de l'ordre d'activation** des unités reste au moteur (`eligible_units[0]`). C'est une
  vraie décision 40K, candidate P3 ; l'architecture §3.2 la rend branchable sans migration.
- **[INDIRECT FIRE] 24.19** reste non implémentée (cf. `V11_agent_rework.md` §9.2.1).

### 5.3 Pourquoi le choix d'arme par l'agent est différé (et pas abandonné)

Quatre risques, tous méthodologiques :

1. **Ça ouvre P2 par la petite porte.** Le choix se fait par (figurine × arme × cible) — c'est le
   mécanisme `pending_agent_decision` / `CHOICE_0..K` de §9.3, pas une action à ajouter. Le faire
   ad hoc est exactement ce que §9.3 interdit.
2. **Ça allonge l'activation** (déclarer arme → cible → …), donc le nombre de pas par épisode —
   le paramètre même qui a fait exploser le timeout d'éval en §0.27.
3. **Dilution du crédit** sur un agent sans win-rate de référence. §9.0bis impose de mesurer le
   *regret* avant de brancher.
4. **Le regret n'est pas mesurable aujourd'hui** : le défaut est cassé (arme 0, une arme, une
   cible). Toute mesure comparerait à un bug, pas à un optimum. **T-C rend la mesure possible.**

La décision a une vraie valeur tactique — tirer toutes ses armes n'est pas toujours optimal à
cause de [HAZARDOUS] (un jet de risque par arme hazardous sélectionnée) et de [BLAST] près des
alliés, et la cible par arme (04.02) est un problème d'affectation non trivial. C'est donc un
**bon candidat P3**, à brancher sur les embeddings d'armes que T-D aura déjà produits.

---

## 6. Journal

### 2026-07-26 — Ouverture

Chantier ouvert après la vérification de §9.2.5. Constats §1.1 à §1.8 établis et mesurés,
décisions §2 actées par l'utilisateur, architecture §3 arrêtée, plan §4 rédigé. Aucune tranche
implémentée à ce stade.

### 2026-07-26 — T-A livrée : renommage `PISTOL` → `CLOSE_QUARTERS`

- `config/weapon_rules.json` : clé + `name` + description alignée sur 24.07 / 10.06, avec la
  mention historique de 24.27 (« Formerly named [PISTOL] »).
- **6 armories TypeScript** (source unique : `engine/weapons/parser.py` les lit au runtime) —
  30 armes migrées.
- `engine/` + `ai/` : prédicats (`_weapon_has_close_quarters_rule`), champ d'état
  (`_shooting_with_close_quarters`), clés de stats de l'analyzer, token de log
  `[CLOSE-QUARTERS]` (la normalisation du tooltip `GameLog` ramène `_` et `-` au même espace,
  donc le tooltip résout).
- **Verrou** : `tests/unit/engine/test_close_quarters_rename.py` (**5**). Il distingue la RÈGLE
  (majuscules) des NOMS d'armes (« bolt pistol ») — ⚠️ **piège réel rencontré** : un
  remplacement en minuscules avait transformé `'bolt pistol'` en `'bolt close_quarters'` et le
  mot français « pistolet » en « close_quarterset ». Les deux sont corrigés et verrouillés.
- Vérifié in-engine : **0** arme porte encore `PISTOL`, **40** armes reconnues par le prédicat.
- PvP : 27 PASS / 0 FAIL. `pyright`, `tsc`, `biome` verts.

### 2026-07-26 — T-B livrée : les types de tir 10.04 / 10.05 / 10.06 sur le chemin squad

- Nouveau résolveur `resolve_squad_shooting_type` (shared_utils) : rend le type de tir
  applicable (`normal` / `assault` / `close_quarters` / `None`) selon les conditions **du PDF**,
  et intègre les règles d'unité du projet (`shoot_after_advance`, `shoot_after_flee`) — mêmes
  prédicats que le chemin mono, pour que les deux ne divergent plus.
- `shooting_type_allows_weapon` + `squad_model_shootable_weapon_indices` : volet « WHILE
  SHOOTING » (armes sélectionnables par type).
- **Le gate du masque** consomme le résolveur au lieu de `not has_advanced and not in_er`, et
  teste **toute arme éligible** au lieu du seul `selectedRngWeaponIndex` (qui vaut 0 pendant
  toute la partie en gym — le masque était donc aveugle aux autres armes d'une figurine).
- **10.06 volet MONSTER/VEHICLE implémenté** (le chemin mono le déclarait non implémenté) :
  éligibilité sans arme [CLOSE-QUARTERS], liberté de sélection d'arme, **-1 au jet de touche**
  sauf [CLOSE-QUARTERS] sur une unité engagée, et **[BLAST] ne peut toujours pas viser une unité
  engagée**. Le volet non-MONSTER/VEHICLE était déjà correct dans
  `_shoot_engagement_blocks_target` — c'est bien le gate qui bloquait en amont.
- **Verrou** : `tests/unit/engine/test_shooting_types_squad_gate.py` (**13**), tous sur le VRAI
  masque. Contre-épreuves mutation : ancien gate restauré → **3 rouges** ; volet MONSTER/VEHICLE
  neutralisé → **1 rouge** ; malus -1 neutralisé → **1 rouge**.
- **Effet mesuré en épisode réel** (3 épisodes) : **48** situations de tir d'assaut et **7** de
  tir à bout portant s'ouvrent, là où l'agent ne pouvait auparavant pas tirer du tout.
- Effet de bord traité : la fixture de `test_hazardous.py` devait porter `config.game_rules`
  (la résolution d'un type de tir exige la zone d'engagement).
- PvP : 27 PASS / 0 FAIL. `pyright` vert.
