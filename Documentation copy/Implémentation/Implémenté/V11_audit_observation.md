# Audit de l'observation de l'agent (V11) — 2026-07-25

> 🗄️ **ARCHIVE — GELÉE LE 2026-07-28. NE PAS UTILISER COMME SPÉCIFICATION.**
>
> Ce document est l'**audit qui a motivé** la refonte de l'observation, plus son journal
> d'implémentation. Il décrit, sections §1 à §6, une observation qui **n'existe plus** (vecteur
> plat de 108 puis 199 dimensions, features calculées, 6 canaux de grille). Il est conservé pour
> le **pourquoi** des décisions — pourquoi `+7/+8` ont été supprimés au profit des données brutes,
> pourquoi le canal « menace ennemie » a été abandonné, pourquoi les figurines sont agrégées mais
> pas les ennemis. Ça ne se retrouve nulle part ailleurs.
>
> **État réel du code (sources vives)** :
> - [`AI_OBSERVATION.md`](../../AI_OBSERVATION.md) — le contrat d'observation actuel ;
> - [`V11_entity_encoder_pointer.md`](V11_entity_encoder_pointer.md) — l'architecture livrée ;
> - `engine/observation_entities.py` — le schéma, seule source du layout.
>
> Repères vérifiés au 2026-07-28, à confronter aux chiffres du corps du texte : `obs_size` =
> **20626** (tenseurs d'entités, plus un vecteur plat), `GRID_CHANNELS` = **9**, `SQUAD_TOP_K` =
> **20**, `SHOOT_SLOT_COUNT` = **20**, `TOTAL_ACTION_SIZE` = **1062**.
> **Les numéros de ligne cités dans ce document sont périmés** et ne sont pas maintenus.
>
> **Seul point actionnable restant**, extrait dans son propre chantier :
> [`observation_deploiement.md`](observation_deploiement.md).

> But : dire, dimension par dimension et **sans jargon**, ce que l'agent voit réellement,
> ce qui est mort/redondant, ce qui manque. Tout est vérifié dans le code (numéros de ligne)
> et croisé avec les règles `Documentation/40k_rules/`. Une section de **re-audit** en fin de
> document reprend chaque conclusion pour vérifier qu'elle est optimale.

---

## 0. Correction d'une première conclusion fausse (important)

Une première passe avait conclu : « ~9 règles d'armes sont observées mais n'ont aucun effet →
bruit pur ». **C'est faux pour l'agent réel.** Raison :

Il existe **deux** constructeurs d'observation dans [observation_builder.py](../../../engine/observation_builder.py) :

| Constructeur | Taille | Contient les 32 « rule features » ? | Utilisé par ArmageddonAgent ? |
|---|---|---|---|
| `build_observation` (mono-figurine, ancien) | **357** | Oui (index 314, `_encode_rule_features`, [ligne 1225](../../../engine/observation_builder.py)) | **NON** |
| `build_squad_observation` (escouade, actuel) | **108** | **Non** (aucune) | **OUI** |

Le routage est dans [w40k_core.py](../../../engine/w40k_core.py) : il lit `obs_size`
depuis la config et n'appelle `build_squad_observation` que si `obs_size == 108`. La config
`ArmageddonAgent` fixe **`obs_size: 108`** dans les 5 profils
([training_config](../../../config/agents/ArmageddonAgent/ArmageddonAgent_training_config.json)).
De plus `build_observation` **lève une erreur** si `obs_size != 357`
([ligne 1094-1098](../../../engine/observation_builder.py)) — donc le chemin 357 et ses 32 règles
sont **du code mort pour cet agent**.

**Conséquence, corrigée :** le vrai problème n'est PAS du bruit de règles observées. C'est
l'**inverse** — l'observation active (108) n'observe **AUCUNE** règle spéciale ni statistique
d'arme brute, et il lui manque des informations de décision que les règles exigent.

---

## 1. Ce que l'agent voit réellement

> **Section d'audit — état AVANT la refonte T1→T7** (§8). Chiffres conservés tels quels : ils
> documentent le point de départ. État réel du code : §8 et §11.

L'observation avait **deux morceaux** donnés ensemble au réseau :

1. un **vecteur de 108 nombres** (`build_squad_observation`) — devenu 199, puis 1011, et
   **aujourd'hui un jeu de TENSEURS D'ENTITÉS** de **20 626** scalaires (§0.30 T-D→T-F, puis
   §0.31) ;
2. une **grille égocentrique** de 6 images superposées centrées sur l'escouade active
   (`build_squad_grid`) — aujourd'hui **9 canaux** (§9.10 a ajouté `couvert`, §0.32 `self` et
   `coût géodésique du pool de move`).

L'espace d'action associé : 1024 cases de déplacement + attendre + **20** cibles de tir (5 à
l'époque de cet audit, cf. §0.30 T-E) + charge + fight + 15 macro (5 objectifs × 3 intentions),
soit **1 062**. **Donc l'agent choisit déjà : où bouger, quelle cible tirer/charger, quel
objectif viser.** L'observation doit nourrir ces choix-là.

### 1.1 Le vecteur — ce que l'agent voit, poste par poste

> **⚠️ État (mis à jour le 2026-07-26)** : le tableau détaillé qui figurait ici décrivait
> l'observation **108-d d'avant la refonte T1→T7** (§8). Il a été retiré plutôt que maintenu en
> double. Depuis, l'observation a changé DEUX fois de contrat : 199 → 1011 (profils d'armes et
> règles, §9.2.5) puis, avec §0.30 T-D, **elle n'est plus un vecteur du tout**.
>
> **Contrat actuel** : un `Dict` de **tenseurs d'entités** — `global_cont` / `global_bin`,
> `allies_*` (ligne 0 = l'unité ACTIVE), `enemies_*` (ordre = slots d'action de tir),
> `self_models_*`, plus la grille. Chaque UNITÉ, amie ou ennemie, porte le MÊME schéma de
> features et passe par le MÊME encodeur.
>
> **Source unique du layout** : `engine/observation_entities.py` (schéma) et l'en-tête
> « OBSERVATION SQUAD — TENSEURS D'ENTITÉS » de `build_squad_observation`
> ([observation_builder.py](../../../engine/observation_builder.py)), dont les formes sont
> **calculées** par `squad_obs_shapes()` et vérifiées à l'exécution. Recopier ce layout ici
> créerait une seconde source de vérité qui ne pourrait qu'avoir tort — c'est précisément ce
> qui vient d'être constaté sur ce paragraphe.
>
> Lecture d'ensemble : [`AI_OBSERVATION.md`](../../AI_OBSERVATION.md) — il ne décrit QUE le
> pipeline actuel depuis le 2026-07-28 ; le vecteur plat est archivé dans
> [`AI_OBSERVATION_Legacy.md`](../../Old/AI_OBSERVATION_Legacy.md). Journal et mesures :
> `V11_entity_encoder_pointer.md` §6.
>
> Le reste de ce §1 et les §2-§6 décrivent l'état **d'avant la refonte** : ils constituent
> l'audit qui l'a motivée, et sont conservés à ce titre. Les décisions sont en §9/§10, l'état
> réel du code en §8/§11.

### 1.2 La grille égocentrique — 6 images (canaux) — *7 depuis T7 (§8), avec le canal « couvert »*

Centrée sur l'escouade active, chaque « pixel » = un hex. 6 couches
([1566-1690](../../../engine/observation_builder.py)) :

| Canal | En clair |
|---|---|
| 0 | Murs |
| 1 | Où sont mes figurines |
| 2 | Où sont les figurines ennemies |
| 3 | Zone d'engagement ennemie (là où je serais « au contact ») |
| 4 | Objectifs (zones) |
| 5 | Niveau/étage du terrain (0 partout tant qu'il n'y a pas d'étages) |

---

## 2. Ce que les règles exigent que l'agent perçoive

Croisement avec `Documentation/40k_rules/` (lus) :

- **Tir (10 Shooting phase 10.02-10.07)** : pour choisir une cible il faut savoir si elle est
  **à portée**, **visible (ligne de vue)**, et si l'unité est **engagée** ou a **fait une avance**
  (change l'éligibilité et le type de tir). Le tir « normal » exige *unengaged + pas d'advance*.
- **Couvert (13 Terrain 13.07-13.08)** : la cible peut avoir le **bénéfice du couvert** (save
  améliorée) → change fortement la rentabilité d'un tir.
- **Capacités core (24)** portées cette nuit et déjà présentes :
  - `IGNORES COVER` 24.18 : annule le couvert de la cible.
  - `HEAVY` 24.16 : +1 pour toucher **si l'unité n'a pas bougé** (décision de positionnement).
  - `RAPID FIRE` 24.30 : attaques bonus **si la cible est à moins de demi-portée** (décision de distance).
  - `DEVASTATING WOUNDS` 24.10 : blessures mortelles → ignore la sauvegarde (change la rentabilité).
  - `HAZARDOUS` 24.15 : risque de se blesser soi-même (arbitrage risque).
  - `closest_target_penetration` (règle projet) : AP+1 sur la cible **la plus proche**.
- **Objectifs (14)** : déjà bien couverts (n°11-15 + n°18 + canal grille 4).

---

## 3. Verdict dimension par dimension

Légende : ✅ garder / ♻️ redondant / ⚠️ à corriger / ➕ à ajouter / ☠️ mort (obs 357, hors agent).

### 3.1 À GARDER tel quel (utile et correct)
n° 0-3 (contexte), 4 (PV), 5-8 (déjà agi ce tour), 9-10 (comptes), 11-15 (objectifs),
16-18 (effectif/cohérence/OC), 20 (puissance de feu), bloc figurines 21-62, bloc ennemis
+0..+6 (63-107 sauf +7/+8 traités plus bas), et **les 6 canaux de grille**. La grille est le
point fort : elle porte murs/positions/EZ/objectifs, donc l'agent peut apprendre à se couvrir
et contourner.

### 3.2 ♻️ REDONDANT — à récupérer
- **n° 19 = doublon exact du n° 4** ([1302](../../../engine/observation_builder.py) vs
  [1335](../../../engine/observation_builder.py)) : même calcul PV%. **1 dimension gaspillée.**
  → la réaffecter à une info utile (voir §3.4).

### 3.3 ⚠️ À CORRIGER (défauts fonctionnels)
- **n° 11-15, repli silencieux** : `try/except: pass` sur l'encodage des objectifs
  ([1327](../../../engine/observation_builder.py)) — si les objectifs sont malformés, le canal
  passe à 0 **sans erreur**. Interdit par CLAUDE.md (fallback masquant). Marqué « PR4 acceptable,
  strict en PR5 » : à rendre strict.
- **n° +7 (rentabilité) et +8 (menace) des ennemis** ([1477-1538](../../../engine/observation_builder.py)) :
  calculés avec **une arme échantillon** (RNG[0] de la 1ʳᵉ figurine) et **en ignorant toutes les
  règles spéciales ET le couvert**. C'est le **levier n°1** : ces deux nombres sont censés résumer
  « vaut-il le coup de tirer ça ? », mais ils ne tiennent compte ni d'`IGNORES COVER`, ni de
  `DEVASTATING`, ni de `closest_target_penetration`, ni du couvert réel de la cible. Une fois les
  règles portées cette nuit, ces résumés seront **faux**.

### 3.4 ➕ À AJOUTER (manquant, exigé par les décisions)
Pour les décisions que l'agent prend **déjà** (tir/charge/cible) :
- **Portée effective de mon arme vs distance de chaque ennemi** : absente. L'agent ne peut pas
  savoir si un ennemi est à portée. (§9.5 P4 du plan la liste.)
- **Ligne de vue par ennemi** : absente en tant que feature (la grille donne les murs, mais la
  LoS calculée n'est pas fournie). (§9.5 P4.)
- **Couvert par ennemi** : absent → impossible d'anticiper une save améliorée.
- **Statut « fell back » (repli) de mon escouade** : absent (seul `advanced` = n°8 existe).
  Le repli interdit de tirer/charger → décision impactée. (§9.5 P4.)
- **Profil de mon arme active (portée, PA, dégâts, règles spéciales)** : absent du vecteur (seul
  le résumé n°20 existe). Sans ça, l'agent ne peut pas relier ses règles spéciales à ses choix.

### 3.5 ☠️ MORT — ne concerne pas cet agent
Les 32 « rule features » (index 314, incluant les 9 règles d'armes « bruit ») vivent dans
`build_observation` (357), **jamais appelé** avec `obs_size=108`. Ne rien « rétablir » ni
« supprimer » côté agent : c'est du code mort à traiter avec la suppression de l'obs 357 (hors
périmètre de cet audit). **Aucune** de ces 9 règles n'est donc un bruit pour l'agent actuel.

---

## 4. Re-audit critique (vérification d'optimalité des conclusions du §3)

Reprise de chaque conclusion pour vérifier qu'elle est **optimale**, pas seulement correcte.

**R1 — « Ajouter 9 flags de règles spéciales » serait-il optimal ? → NON, corrigé.**
Exposer des drapeaux bruts (« cette arme a DEVASTATING ») forcerait l'agent à *réapprendre* la
règle. Plus optimal : **replier l'effet des règles dans les nombres déjà présents**. Les règles
qui ne changent que les **dégâts** (`IGNORES COVER`, `DEVASTATING`, `closest_target_penetration`,
rerolls, et plus tard LETHAL/SUSTAINED/TWIN/MELTA/ANTI) doivent entrer dans le calcul de
**+7 (rentabilité)** et **+8 (menace)** — qui aujourd'hui les ignorent. Un seul point de code
([1477-1538](../../../engine/observation_builder.py)) corrige la perception de toutes ces
règles d'un coup. → **le §3.3 (corriger +7/+8) est le vrai levier, pas le §3.4 « ajouter des flags ».**

**R2 — Toutes les règles peuvent-elles se replier dans +7/+8 ? → NON.**
Trois règles changent une **décision structurelle**, pas seulement les dégâts, donc elles ont
besoin d'une feature dédiée :
- `HEAVY` (+1 pour toucher **si pas bougé**) → dépend d'une décision de **mouvement** ; se relie
  au flag « ai-je bougé » (n°5) mais l'agent ignore que son arme est HEAVY. Une feature « bonus si
  stationnaire » (ou l'intégrer au n°20 conditionné par n°5) est justifiée.
- `RAPID FIRE` (bonus **à demi-portée**) → dépend de la **distance** choisie → nécessite la
  **portée effective par ennemi** (déjà listée en §3.4). Donc l'ajout « portée vs distance »
  couvre à la fois le tir de base ET RAPID FIRE.
- `HAZARDOUS` (risque de se blesser) → arbitrage risque propre ; petite feature dédiée ou repli
  dans une pénalité de « rentabilité nette ».

**R3 — Le doublon n°19 est-il vraiment inutile ? → Oui, confirmé, mais à réemployer.**
Plutôt que de le supprimer (ce qui changerait `obs_size` et casserait le modèle), le **réaffecter**
à une des features manquantes (ex. « distance au plus proche ennemi à portée » ou « flag fell_back »).
Coût zéro sur la taille du vecteur.

**R4 — La grille rend-elle la LoS/le couvert redondants ? → Partiellement, à nuancer.**
La grille porte les murs → un CNN *peut* apprendre une LoS approchée. Mais (a) le couvert dépend
aussi de la **catégorie** de terrain (light/dense, 13.04-13.05), non présente dans la grille
(canaux = mur binaire + niveau) ; (b) la LoS 3D exacte du moteur n'est pas triviale à réapprendre.
Donc une feature **LoS/couvert par ennemi pré-calculée** reste justifiée, mais sa priorité est
**moindre** que le §3.3 (corriger +7/+8), car la grille en couvre une partie.

**R5 — Limites de capacité des blocs (vérifié).**
- Bloc figurines = **6 max** ([SQUAD_TOP_K](../../../engine/observation_builder.py)) : une
  escouade Ork Boyz (10-20) est **tronquée** — les figurines au-delà de 6 sont invisibles. Impact
  cohérence/positionnement à grande escouade. À statuer (élargir k, ou trier par pertinence).
- Bloc ennemis = **5 max**, triés par **identifiant** ([1432-1435](../../../engine/observation_builder.py)) :
  tri **stable** (bon pour PPO, §9.5) mais **arbitraire** — au-delà de 5 escouades ennemies,
  certaines ne sont jamais vues, et l'ordre n'est pas « par pertinence ». Sur les rosters SM/Orks
  actuels le nombre d'escouades est probablement ≤5 (à confirmer sur les rosters réels) ; sinon
  c'est un trou. Le tri « stable par HP×OC » est explicitement différé (PR4 4d) : **le faire**
  améliorerait l'assignation de crédit.

**R6 — Réserve de méthode (inchangée, confirmée).**
L'observation optimale se définit **par rapport aux décisions**. Ici les décisions tir/charge/cible
existent **déjà** (espace d'action 1047 — **1062 depuis §0.30 T-E**, 20 slots de tir), donc les manques §3.4 sont pertinents **maintenant**.
Les features plus fines resteront à réévaluer quand P2/P3 (mécanisme de décision) précisera les
choix — mais corriger +7/+8 (§3.3) et le doublon (§3.2) est valable **quelle que soit** l'issue de
P2/P3.

**Conclusion du re-audit :** la priorité change après vérification. Le point le plus rentable n'est
pas « ajouter des dimensions » mais **rendre +7/+8 (rentabilité/menace) conscients des règles et du
couvert** — un seul site de code, corrige la perception de la majorité des capacités d'un coup.

---

## 5bis. Passe d'optimalité pilotée par les décisions réelles (2e re-audit)

Le §3-§4 raisonnait depuis le code de l'observation (corriger ce qu'on remarque). Pour **garantir**
l'optimalité, on part ici des **décisions réelles** de l'agent (espace d'action vérifié) et on
dérive l'information suffisante par décision. C'est le seul moyen de prouver la couverture.

### 5bis.1 Ce que l'agent décide RÉELLEMENT (vérifié)
Espace d'action = 1047 ([macro_intents.py](../../../engine/macro_intents.py)) — **1062 depuis §0.30 T-E** (les slots de tir passent de 5 à 20) :
- **1024** cases de la grille égocentrique = **où bouger** (phase move).
- **wait**.
- **5** slots de tir = **quel ennemi tirer** (parmi 5 slots).
- **charge** (1 action) : la **cible est choisie par le moteur**, pas par l'agent
  ([decoder 965-994](../../../engine/action_decoder.py)) → l'agent décide seulement charger/pas.
- **fight** (1 action) : idem, cible = pool 12.04, l'agent décide combattre/pas.
- **15** macro = 5 objectifs × 3 intentions (invade/defend/attack).
- **L'arme n'est PAS choisie par l'agent** (aucune action de sélection d'arme) → inutile
  d'exposer tous les profils d'armes ; seule l'arme sélectionnée compte.

### 5bis.2 Deux résultats décisifs

**🔴 D1 — Désalignement obs/action sur les slots ennemis (défaut de CORRECTION).**
- L'**observation** ordonne les 5 slots ennemis par `sorted(str(sid))`
  ([1432-1435](../../../engine/observation_builder.py)).
- L'**action** tir/charge les ordonne par **menace HP×OC décroissante**, mapping stable figé en
  début de partie (`init_enemy_slot_mapping`, [8406](../../../engine/phase_handlers/shared_utils.py)),
  consommé par le masque ([decoder 217](../../../engine/action_decoder.py)) ET l'exécution
  ([decoder 971](../../../engine/action_decoder.py)).
- Les deux ordres **diffèrent** → « tirer slot 0 » ne vise PAS l'ennemi décrit par obs-slot-0.
  Le réseau devrait apprendre une permutation qui **dépend de l'état** (qui est alphabétiquement-i
  vs menace-i) : impossible à câbler → **le signal de choix de cible est brouillé.** C'est la
  cause la plus grave et la moins visible. **Correctif : faire consommer à `build_squad_observation`
  le MÊME `get_enemy_slot_mapping`** (source unique), au lieu de son tri local. Ne change pas
  `obs_size`.

**🟢 D2 — Le masque porte déjà « portée + LoS + engagement » par slot de tir.**
Le masque n'ouvre un slot de tir que si `_model_can_shoot_target` est vrai = **au moins une
figurine à portée (subhex) ET en ligne de vue (murs) ET cible non verrouillée**
([shoot mask 8288-8319](../../../engine/phase_handlers/shared_utils.py) →
[_model_can_shoot_target 4766-4793](../../../engine/phase_handlers/shared_utils.py)). MaskablePPO
zéro-te les actions interdites → l'agent « sait » qu'il ne peut pas tirer un slot hors portée/LoS.
**Donc ajouter portée/LoS par ennemi en observation est largement redondant** (rétrograde §3.4/prio 3
et 6). Ce que le masque **ne** dit PAS et qui reste utile : le **degré** — demi-portée (RAPID FIRE),
**quantité de couvert**, et la **rentabilité** réelle. Ces trois-là restent à porter (via +7/+8).

### 5bis.3 Conséquences sur les priorités
- D1 devient **prio 0** (correction, pas confort).
- « portée/LoS par ennemi » (ex-prio 3/6) : **abandonné** en tant que feature — déjà dans le masque.
  Reste utile : un flag **« à demi-portée »** (pour RAPID FIRE) et le **couvert de la cible**,
  tous deux repliables dans +7/+8 plutôt qu'en dimensions séparées.
- Charge/fight : la cible étant auto-choisie, **pas** de features par-cible de charge/fight à
  ajouter ; l'agent décide oui/non, ce que le masque (possible/pas) + +7/+8 (rentable/pas) couvrent.
- Confirme **R1** : replier les règles dans +7/+8 est bien le levier central (l'arme n'étant pas
  choisie, exposer des profils bruts serait inutile).

### 5bis.4 Trou restant côté MOVE (nouveau)
La décision de mouvement consomme la **grille**. La grille distingue **mur (binaire)** et **niveau**,
mais **pas la catégorie de terrain** (light/dense, 13.04-13.05) : l'agent ne peut pas distinguer un
terrain **qui donne du couvert** d'un simple bloqueur de vue. Pour « se déplacer vers le couvert »,
un **canal de grille "couvert"** (ou distinguer light/dense) est justifié. Priorité moyenne.

---

## 5. Synthèse priorisée

| Prio | Action | Où | Change `obs_size` ? |
|---|---|---|---|
| **0 🔴** | **Aligner l'ordre des slots ennemis de l'obs sur `get_enemy_slot_mapping`** (source unique tir/charge). Sans ça, le choix de cible est brouillé (D1). | [obs 1432](../../../engine/observation_builder.py) | Non |
| ~~**1**~~ | ~~Rendre **+7 (rentabilité) et +8 (menace)** conscients des règles / couvert / demi-portée~~ → **ABANDONNÉ** (§9.1) : les deux features sont **supprimées**, remplacées par les profils d'armes et les bits de règles bruts (T3 + T8). Rien à faire. | — | — |
| **2** | Réemployer le **doublon n°19** → une feature utile (ex. flag `fell_back`, absent) | [1335](../../../engine/observation_builder.py) | Non |
| **3** | Rendre **strict** l'encodage objectifs (retirer `except: pass`) | [1327](../../../engine/observation_builder.py) | Non |
| **4** | Feature **HEAVY** (bonus si stationnaire) et **HAZARDOUS** (risque de se blesser) — décisions structurelles non capturées par +7/+8 | vecteur | Oui |
| **5** | **Canal de grille « couvert »** (distinguer terrain light/dense du simple mur) pour la décision de move | grille | Oui (canaux) |
| **6** | Statuer capacité des blocs : figurines >6 tronquées (Boyz) ; slots ennemis >5 jamais vus | §R5 | Oui |

**Abandonné après vérification (D2) :** « portée/LoS par ennemi » comme dimension d'observation —
déjà porté par le **masque d'action** (MaskablePPO). L'ajouter serait redondant.

**Retrain :** non contraignant (validé utilisateur) — donc prio 0-6 toutes réalisables. Les prio 0-3
ne changent même pas `obs_size`.

**Non concerné :** les 32 « rule features » et les 9 règles « bruit » de l'obs 357 — code mort pour
cet agent, à traiter avec la suppression de `build_observation`, hors périmètre de cet audit.

---

## 6. Verdict final sur l'optimalité

**Non, l'observation n'est pas optimale aujourd'hui.** Après deux re-audits (dont un piloté par les
décisions réelles vérifiées dans le code), il reste **un défaut de correction** et **trois manques
fonctionnels** :

1. 🔴 **Défaut** : slots ennemis de l'observation **désalignés** avec les slots d'action tir/charge
   (tri alphabétique vs tri par menace) → sélection de cible brouillée. **À corriger en premier.**
2. ~~**+7/+8 (rentabilité/menace) ignorent règles, couvert et demi-portée**~~ → conclusion
   **renversée par le §9.1** : plutôt que de rendre ces résumés « conscients », ils ont été
   **supprimés** et remplacés par les données brutes (profils d'armes + bits de règles, T3/T8).
   Le « levier central » de l'audit n'a donc jamais été implémenté tel quel — c'est délibéré.
3. **HEAVY / HAZARDOUS** (décisions structurelles) non observables.
4. **Move** : la grille ne distingue pas le terrain **couvrant** du mur bloquant.

Une fois ces 4 points traités (+ nettoyage doublon n°19 et strict objectifs), l'observation
**couvre chaque décision réelle** de l'agent : move (grille + couvert), tir (slots alignés +
rentabilité juste + masque portée/LoS), charge/fight (masque + rentabilité), objectifs (déjà bon).
C'est **à ce moment** qu'on pourra dire l'observation optimale pour l'espace d'action actuel — et il
faudra la ré-évaluer si P2/P3 change les décisions.

---

## 7. Proposition d'architecture : découpe structurée du vecteur (préparée, pas encore implémentée)

> ✅ **IMPLÉMENTÉE depuis T-D (2026-07-26)** — le titre « pas encore implémentée » et les offsets
> ci-dessous décrivent l'état d'AVANT. Le principe (poids partagés par entité + pooling masqué,
> embeddings ennemis conservés par slot) est en place, mais les **blocs sont devenus des clés de
> tenseurs** : la table de passage bloc logique A→E ↔ clé actuelle est dans
> [`AI_OBSERVATION.md`](../../AI_OBSERVATION.md), section « Les blocs logiques A→E, et ce qu'ils
> sont devenus ». La lire AVANT d'utiliser les offsets de §7.2, qui n'existent plus.

Le vecteur 108 entre aujourd'hui **tel quel** dans un MLP dense (`SpatialCombinedExtractor.forward` =
`cat[cnn_out, vec]`, [spatial_extractor.py](../../../ai/spatial_extractor.py)). Une couche dense
traite chaque dimension indépendamment : elle **n'exploite pas** le fait que les 6 figurines et les
5 ennemis sont des **ensembles d'entités homogènes** (mêmes 7 / 9 features par entité).

### 7.1 Principe (le gain n'est PAS « un sous-MLP par bloc »)
Séparer global/agg/figs/ennemis en 4 sous-réseaux puis reconcaténer ≈ le dense actuel (un MLP sait
router). Le vrai levier = **partage de poids sur les entités répétées** + **agrégation** :
appliquer le MÊME petit réseau à chaque figurine, puis à chaque ennemi, puis pooler (schéma
*Deep Sets* / attention). Bénéfices : invariance à l'ordre des slots, meilleure efficacité
d'échantillonnage (« évaluer un ennemi » appris une fois pour 5 slots), scalabilité au nombre
d'entités.

### 7.2 Découpe proposée (offsets fixes connus)

> **Note (2026-07-25)** : les offsets ci-dessous sont ceux du vecteur 108-d d'avant T1→T7. Le
> **principe** (poids partagés par entité + pooling masqué, embeddings ennemis conservés par slot)
> est inchangé ; les offsets réels se lisent via les accesseurs `squad_model_*_base` /
> `squad_enemy_*_base` de `ObservationBuilder`, et le vecteur arrive maintenant en **deux** clés
> (`vec_cont`, `vec_bin`) à concaténer avant découpe.

```
vec (108, déjà normalisé par VecNormalize)
 ├─ ctx  = vec[0:21]                    → φ_ctx : MLP(21 → 64)
 ├─ figs = vec[21:63].reshape(6,7)      → φ_fig : MLP(7 → 32) partagé sur les 6
 │       → pooling MASQUÉ (mean ⊕ max sur figs présentes) → 64
 └─ enem = vec[63:108].reshape(5,9)     → φ_ene : MLP(9 → 32) partagé sur les 5
         ├─ 5 embeddings PAR SLOT conservés (équivariant, pour le tir) → 5×32
         └─ pooling MASQUÉ (mean ⊕ max) → 64 (contexte)
features = cat[ cnn_out(grille), φ_ctx, pool_figs, enem_par_slot, pool_enem ] → net_arch
```
**Point décisif** : les **figs** peuvent être poolées (l'action ne cible pas une fig précise — move
via grille, fight oui/non). Les **ennemis** doivent **garder l'identité par slot** (l'action « tir
slot N » vise un slot) → on conserve les 5 embeddings, le pooling n'est qu'un contexte.

### 7.3 Deux niveaux d'ambition
- **Niveau 1 — extracteur seul (recommandé pour poser la structure).** L'extracteur sort un vecteur
  de features de taille fixe qui alimente `net_arch` + `action_net` linéaire standard, en gardant les
  5 embeddings ennemis concaténés (accès par slot préservé). Compatible MaskablePPO tel quel. Gain :
  poids partagés, généralisation.
- **Niveau 2 — têtes structurées (plus tard, si plafonnement).** Tête **tir** = produit scalaire
  tronc × embedding ennemi par slot (1 logit/slot, vraiment équivariant) ; tête **move** = conv 1×1
  sur la carte de features de la grille (32×32 logits spatiaux au lieu d'un dense de 1024). Nécessite
  une policy custom SB3 (`MlpExtractor`/`action_net`), plus lourd et plus risqué.

### 7.4 Gardes indispensables
1. **D1 réglé d'abord** : garder les embeddings par slot suppose que l'ordre obs = ordre action
   (`get_enemy_slot_mapping`). Sans ça, l'archi propage le désalignement. **Prérequis.**
2. **Masquage du padding** : le pooling doit exclure les entités absentes. Les ennemis ont
   `slot_mask` (obs +5) ; les **figs n'ont pas de flag présence** → à ajouter **au moment de
   l'archi** (dérivable de HP>0 en attendant, donc pas urgent avant le pooling).
3. **Rester en aval de `VecNormalize`** : découper le `vec` DANS l'extracteur (le Dict `{vec,grid}`
   et la normalisation running-mean restent transparents).
4. **Masque d'action inchangé** : les logits finaux (1047, **1062 depuis T-E**) restent masqués par MaskablePPO. ⚠️ Le « Niveau 2 » esquissé ici est LIVRÉ (tête pointeur, §0.30 T-E) : les logits de tir viennent d'un produit scalaire sur les embeddings ennemis, et le masquage reste celui de MaskablePPO.

### 7.5 Séquencement retenu
1. **D1** (réalignement des slots) — fait.
2. **+7/+8 conscients** + **fall_back** — voir §8.
3. **Niveau 1** de l'extracteur découpé (+ flag présence fig), retrain, **mesurer le win-rate**.
4. **Niveau 2** seulement si le Niveau 1 plafonne.

> **Note de périmètre :** le flag présence par figurine, initialement rangé en étape 1, est **différé
> à l'étape 3** (implémentation de l'archi) : il ne sert qu'au pooling masqué du Niveau 1, il est
> dérivable de HP>0 en attendant, et l'ajouter maintenant décalerait le bloc ennemis en même temps
> que le fix D1 (deux changements simultanés sur le même bloc = risque inutile).

---

## 8. Journal d'implémentation

_(rempli au fil des étapes ; preuves = tests + numéros de ligne)_

### 2026-07-26 — Étape T8 : profils d'armes + règles, mise en place, distance parcourue — ✅ FAIT

Périmètre exécuté : **les 3 points « débloqués par la fin du portage des capacités »** du §11.
`obs_size` **199 → 1011** (`vec_cont` 459, `vec_bin` 552) ⇒ **retrain from scratch**.

- **Profils d'armes bruts + bits/params de règles** (le trou principal, point 1) — nouveau module
  [`engine/observation_weapon_profiles.py`](../../../engine/observation_weapon_profiles.py) :
  encodeur **unique** partagé par mon escouade et par les slots ennemis. Un profil =
  `{NB, ATK, STR, AP, DMG, portée, nb de porteurs vivants}` + params (RAPID FIRE / SUSTAINED
  HITS / MELTA / CLEAVE / BLAST X, Y+ de ANTI) + 12 drapeaux + one-hot du **keyword ciblé par
  ANTI-X** + mask ⇒ 13 cont / 18 bin. Regroupement par **identité de profil**, ordre déterministe
  par nombre de porteurs. **K mesuré sur les rosters réels** : 6 tir + 5 mêlée pour mon escouade
  (aucune troncature de mes propres capacités), 2 tir + 1 mêlée par slot ennemi ; dépassement
  **logué**. [INDIRECT FIRE] volontairement absente (non implémentée ⇒ bit inerte).
  ⚠️ État de l'époque : la règle a été implémentée le 2026-08-16 et l'observation l'expose depuis.
- **Mise en place / réserve** (point 2) : one-hot 3 états dérivé de `deployed_on_turn` **+ le bit
  « posée CE tour »** — l'état seul ne dit pas si la pose est de ce tour, or c'est ce point qui
  supprime le bonus [HEAVY] (24.16 clause 2).
- **Distance parcourue par figurine** (point 3) : `moved_distance_by_model`, accumulée par
  `commit_move` en **distance de CHEMIN**, exposée en max + somme. Mesurée dans les **deux**
  métriques (hex géodésique en gym, euclidienne any-angle en PvP via la primitive du pool
  par-figurine) ; sinon [HEAVY] serait devenue laxiste en PvP. Elle rend la **clause 3 de
  [HEAVY] 24.16 EXACTE** (détail : `V11_agent_rework.md` §9.2.6).
- **Tests** : `test_squad_obs_weapon_profiles.py` (19) + `test_moved_distance_and_deploy_obs.py`
  (10) + `test_heavy_shoot.py` (7 → 13). Contre-épreuves mutation : 6 rouges (profils), 2 rouges
  (distance), 2 rouges (seuil HEAVY). Les 6 fichiers d'obs squad préexistants restent verts
  **sans modification** — ils passent par les accesseurs de layout.
- **Reste hors périmètre, inchangé** : bloc E « escouades amies » et listes de longueur variable
  → étape architecture set-based.

### 2026-07-25 — Étape 1 : D1 (réalignement des slots ennemis) + fall_back — ✅ FAIT
- **D1** : `build_squad_observation` lit désormais l'ordre des slots ennemis via
  `get_enemy_slot_mapping` (mapping stable HP×OC, **même source que le masque et l'exécution**),
  au lieu de son tri local `sorted(str(sid))`. Fin du désalignement obs↔action.
  [observation_builder.py](../../../engine/observation_builder.py) (import + section 4).
- **fall_back** : `obs[19]` (ex-doublon exact de `obs[4]` HP%) réaffecté au flag « escouade
  repliée ce tour ? » (`units_fled`, même source que `build_squad_action_mask`).
- **Tests** : `tests/unit/engine/test_squad_obs_enemy_slot_alignment.py` (3) — alignement obs↔mapping,
  contre-épreuve intégrée (fixture où ordre-menace ≠ ordre-alphabétique → rouge sous l'ancien code),
  flag fall_back 0↔1. Suites `test_observation_builder` / `test_squad_grid_observation` /
  `test_model_value_per_figurine` vertes (non-régression).
- **Impact** : change les valeurs de l'observation → **retrain requis** (attendu). `obs_size`
  inchangé (108).

### 2026-07-25 — Étapes T1→T7 : refonte du vecteur (hors portage des capacités) — ✅ FAIT

Périmètre exécuté : la partie « à coder — indépendante du portage des capacités » du §11.
**Hors périmètre, non fait** (arbitré avec l'utilisateur avant de coder) : profils d'armes bruts
(les bits/params de règles s'insèrent dans le même bloc → réécriture double), **bloc E escouades
amies** (spécifié en longueur variable → part avec l'archi set-based), observation de déploiement,
archi set-based. **Tout le reste du §10 est implémenté** : le rôle et le profil défensif par
figurine, d'abord omis sans être signalés, ont été ajoutés en T9.

**`obs_size` : 108 → 199**, réparti en `vec_cont` (119) + `vec_bin` (80). Les 5 profils de
[ArmageddonAgent_training_config.json](../../../config/agents/ArmageddonAgent/ArmageddonAgent_training_config.json)
sont à jour ; la cohérence config ↔ layout est **vérifiée à l'init du moteur** (erreur explicite
si `obs_size ≠ CONT+BIN`, [w40k_core.py](../../../engine/w40k_core.py)).

**T1 — deux vecteurs, valeurs brutes.** `build_squad_observation` retourne
`{"vec_cont", "vec_bin"}` ; l'obs de l'env devient `Dict {vec_cont, vec_bin, grid}`.
Toutes les divisions manuelles (`/5 /10 /20 /30 /100` + clamps) sont **supprimées** : elles
saturaient (une escouade de 20 Boyz valait 1.0 comme une de 10) et faisaient double emploi avec
`VecNormalize`, qui ne normalise plus que `vec_cont` (`norm_obs_keys`,
[train.py](../../../ai/train.py)). `vec_bin` (drapeaux, phase, contrôle d'objectif) n'est
**jamais** normalisé. Bornes de `vec_cont` = ±inf (une borne 0..1 mentirait sur des PV bruts).
Layout et constantes : [observation_builder.py](../../../engine/observation_builder.py) ;
accesseurs d'offsets + vérification des bases de blocs **à chaud** (`_check_block_base`) →
toute dérive lève au lieu de décaler une feature en silence.
Impacts : [w40k_core.py](../../../engine/w40k_core.py), [spatial_extractor.py](../../../ai/spatial_extractor.py),
[train.py](../../../ai/train.py), [bot_evaluation.py](../../../ai/bot_evaluation.py).

**T2 — Bloc A.** ➕ score de mission (VP mien/ennemi, même source que la condition de victoire) ;
➕ VALUE cumulée vivante / VALUE de départ des deux camps (`value_at_start` capturé au build des
caches, [shared_utils.py](../../../engine/phase_handlers/shared_utils.py) — les figurines
mortes disparaissent de `models_cache`, la valeur initiale ne serait plus dérivable) ;
✏️ contrôle d'objectif = **lecture** de `objective_controllers`, l'état persistant du moteur ;
➕ 5 bits de présence ; ❌ `try/except: pass` supprimé ; ❌ compte d'escouades amies/ennemies
(remplacé par la VALUE cumulée). Voir T8 ci-dessous : ce point a d'abord été implémenté comme un
recalcul par observation, ce qui était faux au regard de 14.02.

**T3 — suppressions + réorg PV.** ❌ `obs[20]` firepower générique T4/Sv4, ❌ `+7 value_over_ttk`,
❌ `+8 threat_level`, ❌ index d'arme CC par figurine, ❌ PV par figurine. ✏️ PV réorganisés :
{effectif vivant, HP_MAX, **PV de la figurine blessée**}. ➕ profil d'escouade brut
(MOVE / HP_MAX / T / save / invulnérable), lu sur la datasheet de l'unité.

**T4 — drapeaux terrain** ([observation_builder.py](../../../engine/observation_builder.py)) :
`hidden` (13.09), `gone to ground` prêt (13.5), `à couvert` (13.08), `dans l'EZ ennemie`.
Règles relues (PDF 13 + 13-5) : **13.08 a deux conditions alternatives**, la première
(`INFANTRY/BEASTS/SWARM` + *within a terrain area*) **ne dépend pas de l'attaquant** — si toutes
mes figurines la remplissent, l'escouade a le couvert contre **toute** attaque à distance : c'est
une condition suffisante exacte, pas une heuristique. Les volets « pas entièrement visible pour la
figurine attaquante » (13.08 b, 13.5) sont **par-tireur** : ils n'ont pas de valeur au niveau
escouade et restent dans `compute_unit_los`. Les trois drapeaux sont **recalculés à chaud** :
`unit['hidden']` n'est rafraîchi qu'au début de la phase de tir, donc périmé pendant le move —
exactement quand l'agent décide d'aller se couvrir. Géométrie mutualisée via
`compute_models_within_terrain` ([shooting_handlers.py](../../../engine/phase_handlers/shooting_handlers.py)),
généralisation de `compute_models_in_obscuring_terrain` (qui la consomme).

**T5 — contacts par figurine → EZ.** Le bord-à-bord brut (`calculate_hex_distance == 1`, ancre à
ancre) est remplacé par la primitive d'engagement du moteur sur des entrées synthétiques par
figurine (`_synth_model_entry` + `unit_entries_within_engagement_zone`, comme `get_fighting_models`).
Deux socles de 16 hex dont les ancres sont à 2 subhex sont engagés selon 03.04 et selon le pool de
combat — l'ancien test répondait 0.

**T6 — bloc ennemi.** ✏️ position mesurée depuis la **figurine ennemie la plus proche** (l'ancre
d'une escouade étalée peut être à l'opposé de la menace) ; ➕ **distance bord-à-bord** avec la
mesure du gate de portée du moteur (`_ranged_squad_edge_distance`) ; ➕ VALUE vivante (somme
par figurine) ; ➕ MOVE + profil défensif de la cible.

**T7 — 7e canal de grille « couvert »** ([spatial_grid.py](../../../engine/spatial_grid.py)) :
hexes des `terrain_areas`, exactement l'ensemble que le moteur peint en `cover_cells`. Le drapeau
B2 dit *si* l'escouade est couverte, ce canal dit *où* aller se couvrir. `GRID_CHANNELS` 6 → 7
(l'extracteur et le masque lisent la constante, aucun autre changement).

**T8 — contrôle d'objectif : fin de phase, pas fin de step (correction).** La règle 14.02 dit
que le contrôle est déterminé **à la fin de chaque phase et de chaque tour**. Le moteur a déjà
tout ce qu'il faut — `run_objective_control_checkpoint` + `game_config.objective_control_check`
(fin de command/move/shoot/charge/fight + fin de tour) — mais ce checkpoint n'était appelé que
depuis **l'API PvP** : en entraînement, `objective_controllers` n'était jamais rafraîchi. La
première implémentation de T2 contournait le problème en **recalculant** le contrôle à chaque
observation : coûteux (somme des OC par figurine sur 5 zones à chaque action) et surtout **faux**
— l'agent voyait un contrôle basculer au milieu d'une phase, alors que la règle (et le scoring des
VP, qui lit la même source) ne le réévalue qu'à la frontière.
Corrigé : `GameStateManager.refresh_objective_control_on_boundary`
([game_state.py](../../../engine/game_state.py)) détecte la frontière (phase, tour) et déclenche le
checkpoint ; elle est appelée par le **moteur** avant toute construction d'observation
([w40k_core.py](../../../engine/w40k_core.py)) **et** par l'API PvP, qui portait jusque-là sa propre
détection inline (deux sources → une). `calculate_objective_control` fait maintenant **une seule
passe d'empreintes** pour tous les objectifs (`sum_objective_control_oc_multi`).
Conséquences : l'observation ne calcule plus rien (lecture pure), le contrôle observé est celui du
scoring, et au début de bataille aucun objectif n'est contrôlé — ce qui est la règle, pas un défaut.

**T9 — Bloc C complété (rôle + profil défensif par figurine).** Manquants dans la première
livraison, et non signalés : le §10 les liste en ➕ et ce sont des données non-règles, donc dans le
périmètre. ➕ **rôle d'allocation** (règle 19) en **one-hot** `special_weapon / sergeant / support /
leader` (tout à 0 = figurine de base) — one-hot et non scalaire, l'ordre des tiers n'ayant pas de
sens numérique ; ➕ **profil défensif dérogatoire** : le profil d'escouade (B3) décrit **la figurine de base** et
n'est PAS répété par figurine (§9.4 : « exposer une fois au niveau escouade + exceptions »). Seules
les figurines qui **dérogent** portent leurs HP_MAX / T / save / invulnérable ; une figurine
conforme laisse ces 4 dimensions à 0, et un **bit de dérogation** lève l'ambiguïté (0 = « conforme »,
pas « T=0 »). Sans cela, un personnage attaché (fusionné *comme figurine*, règle 19) était décrit
exactement comme un Boyz de base — et une première version, elle, recopiait bêtement les mêmes 4
stats sur les 6 figurines.

**T10 — canal « couvert » dilaté au rayon de socle.** 13.08 accorde le couvert dès que le **socle**
chevauche la zone (`model_within_terrain`), pas seulement quand l'ancre y tombe : peindre les seuls
hexes de la zone laissait à 0 une couronne de cases pourtant couvrantes (~2 cellules de grille pour
un socle d'infanterie de 16 subhex sur le board ×5). Le canal est désormais dilaté de
`cover_dilation_cells(BASE_SIZE, half_extent)` cellules
([spatial_grid.py](../../../engine/spatial_grid.py)) — dilatation morphologique numpy, coût négligeable,
exacte au grain de la grille.

**T11 — le bloc figurines expose les EXCEPTIONS, plus « les 6 premières créées ».** Défaut mis en
évidence en auditant T9 sur les rosters réels : le bloc est plafonné à `SQUAD_TOP_K = 6` et prenait
les figurines dans l'ordre de création, alors que les personnages attachés (règle 19) sont ajoutés
**en fin de liste** — positions 11 et 12 d'une escouade de 12 Boyz. Résultat : sur **les quatre
escouades concernées** des rosters d'entraînement, `leader` et `support` n'étaient **jamais**
observés, ce qui rendait le rôle et le profil dérogatoire de T9 strictement inopérants.
`_squad_models_for_observation` trie désormais par pertinence décroissante — tier de rôle
(leader > support > sergeant > special_weapon > base), puis profil défensif dérogatoire, puis index
de création. Tri **déterministe à composition donnée** : il ne dépend ni de la position ni des PV,
qui feraient permuter les slots d'un step à l'autre (les figurines n'étant ciblées par aucune
action, réordonner ce bloc n'a aucun effet sur le masque — contrairement aux slots ennemis, qui
restent alignés sur `get_enemy_slot_mapping`). Vérifié sur le scénario d'entraînement : les slots 0
et 1 portent bien `leader` et `support`.
Reste borné, et assumé : au-delà de 6, des figurines **de base** ne sont pas listées — leur position
est toutefois peinte sur le canal « allié » de la grille, et la levée du plafond appartient à
l'archi set-based (§9.9).

**T12 — le bloc figurines devient un bloc de TYPES (correction de fond).** T11 réglait *quelles*
figurines entrent dans les 6 slots, mais laissait le vrai défaut : décrire des **figurines** là où
§9.4 demande « une fois au niveau escouade + exceptions ». Une escouade de 12 n'a que **4 types**
distincts (mesuré sur les rosters : 9 Boyz + 1 Nob + leader + support) — décrire des figurines
répétait le même profil et laissait la moitié de l'effectif hors du vecteur.
Nouveau **bloc C1 « types »** : 6 slots × `{HP_MAX, T, save, invulnérable, effectif vivant du
type}` + rôle one-hot + bit d'occupation. L'**effectif complet** est donc décrit quelle que soit la
taille de l'escouade (vérifié : 12/12 et 10/10 sur le scénario d'entraînement) ; un dépassement de
6 types est **logué**, jamais silencieux. Le compteur par type est le même motif `{profil, nb de
porteurs}` que celui prévu pour les armes (§11).
Le **bloc C2 « figurines »** ne garde que l'irréductiblement individuel — position relative et état
d'engagement — et trois **compteurs d'engagement sur l'escouade entière** (éligibles au combat,
dans l'EZ, via un allié) rendent l'état de combat indépendant du plafond. Ce qui reste hors des
6 slots : les positions individuelles des figurines de base, déjà peintes sur le canal « allié » de
la grille. `obs_size` 190 → **199**.

**Coût mesuré** (scénario d'entraînement réel, 11 escouades / 60 figurines) : construction du
vecteur **19,6 ms → 4,6 ms**, grille ~1,6 ms, pour un `step` complet à ~93 ms. Trois leviers, tous
**exacts** (aucun résultat modifié) : (1) le contrôle d'objectif n'est plus calculé par observation
mais une fois par frontière de phase (T8) ; (2) `sum_objective_control_oc_multi` — une seule passe
d'empreintes pour les 5 objectifs au lieu d'une par objectif ; (3) pré-filtre des escouades
candidates à l'EZ avec la **borne conservatrice du pruning du move**
(`_relevant_enemies_for_move`), le test EZ exact comparant des empreintes entières.

Deux optimisations supplémentaires ont été **essayées puis abandonnées**, chacune parce qu'elle
n'était pas exacte :
- *mémoïsation des empreintes de socle* (forme relative par parité de colonne) : déplaçait des
  cases situées pile sur le bord du socle (arrondi flottant) → modifiait la géométrie du moteur ;
- *pré-filtre du contrôle d'objectif par l'union `occupied_hexes` de l'escouade* : sur un plateau
  `engagement_zone <= 1`, `_compute_unit_occupied_hexes` réduit l'occupation à UNE case par
  figurine alors que la règle 14.02 teste l'empreinte complète — l'union n'y est pas un
  sur-ensemble, le filtre aurait perdu du contrôle d'objectif en silence (mis en évidence par un
  test d'invariant écrit pour l'occasion, resté rouge).

**Tests** — suite `tests/unit/` **entièrement verte** (1574 tests, exit 0). Nouveaux fichiers
(contre-épreuve dans chacun) :
`test_squad_obs_vector_split.py` (7), `test_squad_obs_context_block.py` (6),
`test_squad_obs_stats_and_removals.py` (5), `test_squad_obs_terrain_flags.py` (7),
`test_squad_obs_model_engagement.py` (4), `test_squad_obs_enemy_block.py` (5),
`test_squad_grid_observation.py` (+2 pour le canal couvert), `test_squad_obs_enemy_slot_alignment.py` (3),
`test_endless_duty_value_baseline.py` (2). T8/T9/T10 ajoutent : contrôle figé pendant une phase et
réévalué à la frontière, aucun contrôle avant la première frontière, objectif malformé qui lève
(observation et checkpoint), profil défensif exposé UNIQUEMENT pour un perso attaché (figurine conforme = zéros),
rôle en one-hot couvrant tous les rôles du moteur, escouade homogène décrite comme UN type, perso attaché formant son
propre type, effectif total décrit au-delà du plafond du bloc figurines, ordre des types stable
quand les figurines bougent ou sont blessées, compteurs d'engagement couvrant toute l'escouade, canal
couvert dilaté pour un grand socle. Les tests qui figeaient `obs_size: 108` passent par
`ObservationBuilder.SQUAD_OBS_SIZE_TARGET`. `test_model_value_per_figurine.py` : la classe qui
testait `value_over_ttk` (feature supprimée) est **réécrite** sur la VALUE d'escouade ennemie —
l'invariant protégé (somme PAR FIGURINE, indépendante de l'ordre) est le même.

**Effet de bord traité** : `build_units_cache` recalcule `value_at_start` pour les DEUX joueurs ;
en mode *endless duty*, `_replace_units_for_player` ne remplace qu'un camp — la référence de
l'adversaire est désormais restaurée après le rebuild
([endless_duty_runtime.py](../../../services/endless_duty_runtime.py)), sinon ses pertes déjà subies
disparaissaient de l'observation.

**Chemin PvP** : `scripts/pvp_smoke_test.py --spawn-server` → **27 PASS / 0 FAIL** (les primitives
touchées — EZ, terrain, contrôle d'objectif — sont partagées gym/PvP).

**Impact** : valeurs ET taille de l'observation changent → **retrain complet requis** (acté, hors
mission).

### Décisions actées (2026-07-25) — à implémenter APRÈS le portage des capacités (attente signal)

**Feature statut déploiement / réserve (pour HEAVY 24.16).**
- **Source unique** : un champ moteur `deployed_on_turn` par escouade (n° de tour de mise en place ;
  sentinelle = en réserve). Ajouté **avec le portage HEAVY** (une seule main sur le chemin de
  déploiement `w40k_core`), car HEAVY en a directement besoin (« posée ce tour » =
  `deployed_on_turn == turn`). L'observation en **dérive** un one-hot, elle ne stocke rien.
- **Observation = one-hot à 3 états mutuellement exclusifs** (pas un scalaire 0/1/2 : faux ordre) :
  - `0` : en réserve (hors board).
  - `1` : sur le board, déployée pendant la phase de déploiement **ou** arrivée un tour précédent.
  - `2` : sur le board, arrivée de réserve **ce tour**.
- **Lien HEAVY** : condition « pas posée ce tour » satisfaite sauf état `2`. On ne distingue
  déploiement-initial et arrivée-tour-précédent que si une règle future l'exige — sinon c'est du
  bruit non exploité (principe de l'audit). La granularité complète reste dans `deployed_on_turn`.
- `obs_size` : **+3** par rapport à la valeur courante (199 après T1→T12) — retrain, non contraignant.

**+7/+8 (rentabilité/menace) conscients des règles et du couvert.**
- Construire **UNE** fonction d'espérance de dégâts consciente des règles (source unique, remplaçant
  les 4 implémentations divergentes actuelles), **après** stabilisation du portage de cette nuit
  (HEAVY / HAZARDOUS / DEVASTATING / RAPID_FIRE ; IGNORES_COVER / closest_target_penetration /
  rerolls déjà stables). Puis brancher +7/+8 (et idéalement bots / reward) dessus. Ne pas coder de
  5ᵉ logique inline avant (divergence interdite).

> **Statut (mis à jour 2026-07-26)** : le portage des capacités est **terminé**, le signal est levé.
> - `deployed_on_turn` : ✅ **codé côté MOTEUR** (création d'unité + commit de déploiement), déjà
>   consommé par la clause 2 de [HEAVY] 24.16, et ✅ **dérivé dans l'OBSERVATION le 2026-07-26**
>   (cf. §8, étape T8). Écart assumé sur la spec ci-dessus : **+4 et non +3** — le one-hot 3 états
>   ne dit pas si la pose est de CE tour, or c'est exactement ce qui supprime le bonus [HEAVY]
>   (24.16 clause 2). Un 4ᵉ bit « posée ce tour » est ajouté ; les 3 états gardent leur sens
>   (hors board / avant la bataille / arrivée en cours de bataille).
> - `+7/+8` conscients des règles : ❌ **SANS OBJET — corrigé le 2026-07-28.** Ce statut disait
>   « ⏳ toujours à faire », ce qui contredisait le §9.1 du même document et l'état du code. Les
>   deux features ont été **supprimées** (décision §9.1, philosophie « données brutes ») et
>   livrées en T3 : ni `value_over_ttk` ni `threat_level` n'existent dans le pipeline
>   d'observation. Il n'y a rien à implémenter ici. (Les occurrences de `threat_level` qui
>   subsistent dans `engine/phase_handlers/shared_utils.py` relèvent du **ciblage du bot**, pas de
>   l'observation.)

---

## 9. Décisions de conception (discussion 2026-07-25) — refonte vers l'observation BRUTE (philosophie « a »)

Décision de fond : **exposer les données brutes** (stats + règles à effet réel) et laisser l'agent
apprendre lui-même l'efficacité, **plutôt que** des features pré-calculées. Justification : sur le
**long terme** (post-démo, pas de re-refonte), les données brutes ne périment pas et ne peuvent
contenir *moins* d'info qu'une feature dérivée (inégalité de traitement de données) ; la « perte »
de sample-efficiency est **modérée et transitoire** (la table de blessure/save est simple à
apprendre) et se résorbe sur un entraînement long. Une feature calculée ne bride l'agent que si
elle **remplace** les données en perdant de l'info (péché d'`obs[20]`).

### 9.1 Suppressions
- **`obs[20]` (firepower générique T4/Sv4)** : trompeur (une arme anti-char paraît nulle vs T4/Sv4)
  → **supprimé**.
- **`obs[+7]` value_over_ttk et `obs[+8]` threat_level (par ennemi)** : features calculées →
  **supprimées** (remplacées par les données brutes, cf. 9.3). Le §5bis/§6 « rendre +7/+8
  conscients » est **abandonné au profit de (a)**.
- **`obs[base+3]` index d'arme CC (bloc figurines)** : l'agent ne choisit pas son arme + asymétrique
  (pas d'index tir) → **supprimé**.

### 9.2 Corrections de features existantes
- **`obs[4]` PV% → réorganisation PV en 3 morceaux non-redondants** (décision affinée) :
  - **HP_MAX** (robustesse d'une figurine) → **profil défensif escouade (B3)** ; HP_MAX des figurines
    exceptions → leur profil distinct (bloc C).
  - **HP_CUR de l'unique figurine blessée** → **état escouade (B2)**.
  - **suppression du PV par figurine** dans le bloc C (obs `base+2`) : devenu redondant.
  En 40K les pertes s'allouent une figurine à la fois → au plus une figurine partiellement blessée ;
  `{nb figs vivantes (obs[16]) + HP_MAX + HP_CUR de la blessée}` capture **tout** l'état PV sans lister
  chaque figurine. (Hétérogénéité gérée par les HP_MAX des exceptions, bloc C.)
- **`obs[11:15]` objectifs** : contrôle maintenu dans **[−1, 1]** + **5 bits de présence** par
  objectif (distingue « contesté/vide » de « objectif absent du scénario »). Supprime le
  `try/except: pass` masquant ([1327](../../../engine/observation_builder.py)).
- **Position ennemie (`+2/+3`)** : mesurer depuis la **figurine ennemie la plus proche** (pas
  l'ancre), **+ ajouter la distance** à cette figurine (les coords donnent déjà la direction ; la
  distance fig-à-fig est ce que la portée utilise).
- **Normalisations ennemies** : taille `/10 → /20`, PV `/30 → /40` (escouades jusqu'à 20 figurines,
  ex. Boyz — le `/10` saturait).
- **Contact par figurine (`base+5/+6`)** : bascule du **bord-à-bord brut** (`calculate_hex_distance
  == 1`, [1407](../../../engine/observation_builder.py)) vers la **présence dans l'EZ**
  (`unit_entries_within_engagement_zone`) — le test 2D ignore la composante verticale de l'EZ
  (reliquat x1, faux dès les étages Phase B). NB : `obs[+6]` « ennemi bloqué » utilise **déjà** l'EZ,
  pas de changement.

### 9.3 Ajouts — données brutes offensives ET défensives, des DEUX côtés (symétrie)
- **Mon bloc** : profil **offensif** (armes : S/PA/DMG/portée/NB + flags de règles d'attaque) **et
  défensif** (E/save/invuln + règles de défense).
- **Bloc ennemi** : son profil **défensif** (pour choisir ma cible) **et offensif** (pour anticiper
  sa menace → me protéger / me replier / exposer la bonne unité).
- Débloque l'**adaptation défensive**, pas seulement l'attaque (ce que `+8` menace tentait de
  résumer, appris en brut).
- **N'exposer que les règles à effet RÉEL en résolution** (pas les ~9 règles observées-mais-mortes
  type TORRENT/TWIN_LINKED — sinon on recrée le bruit que l'audit dénonce). La liste exposée **suit**
  la liste des règles résolues (source unique). Les règles en cours de portage s'ajoutent au fil de
  l'eau.
- **Nouveaux flags escouade** : `hidden` (règle 13.09, `unit['hidden']` — l'ennemi ne peut pas me
  cibler) ; **« dans l'EZ ennemie »** (engagé — conditionne éligibilité tir 10.04 / charge) ;
  **« à couvert »** (13.08, formulation à préciser).

### 9.4 Granularité : niveau escouade + exceptions (pas par figurine)
- Les stats/règles (9.3) sont exposées **une fois au niveau escouade** (le mien) et **par slot
  ennemi** — pas répétées sur chaque figurine (escouades homogènes → redondance).
- **Exceptions exposées individuellement** : figurines qui dévient du profil de base — **arme
  spéciale/lourde, sergent**, et **personnages attachés** (leader/support).
- **Représentation moteur (règle 19, vérifiée)** : le perso attaché est **fusionné comme figurine**
  de l'escouade (`attached_squad`, [game_state.py](../../../engine/game_state.py)) ; chaque
  figurine porte un **rôle** `base < special_weapon < sergeant < support < leader`
  ([shared_utils.py](../../../engine/phase_handlers/shared_utils.py)). → le bloc figurines
  garde un **tag de rôle** + le profil **défensif** distinct des seules figurines déviantes (persos).
  Les **armes** des exceptions sont, elles, portées par l'**ensemble {profil, nb porteurs}** de 9.3
  (une arme spé = une entrée de compteur 1), pas par le bloc figurines.
- À cadrer : quelle(s) arme(s) exposer pour une figurine multi-armes (active selon la phase, ou
  profils RNG + CC).

### 9.5 Architecture (rappel §7, décidé)
- **Niveau 1 = Deep Sets** (poids partagés par entité + pooling masqué) : figurines → `φ_fig`
  partagé → pooling → niveau escouade ; ennemis → `φ_ene` partagé → **embeddings par slot conservés**
  (pour le tir) + pooling contexte. C'est le pooling per-fig qui réalise le « niveau escouade » de 9.4.
- **Niveau 2 = attention** : **compute négligeable** à cette échelle (5-6 entités, n² trivial,
  quelques milliers de params) ; le coût réel = **stabilité d'entraînement / tuning** (masquage
  d'attention, convergence à peu de données), **gain incertain** (n'aide que si les interactions
  entre entités comptent). Strictement plus expressive que Deep Sets (ne peut pas être *moins*
  capable) → à tester **seulement si le Niveau 1 plafonne**.

### 9.6 Non-filtrage des slots ennemis (confirmé)
Les slots ennemis = les plus menaçants (`get_enemy_slot_mapping`), **même non visibles** — pour
pouvoir décider de **bouger/charger vers eux**. Le « puis-je tirer MAINTENANT » (visibilité/portée)
est géré par le **masque d'action**, pas filtré dans l'observation.

### 9.8 Ajouts stratégiques (contexte global) — décidés 2026-07-25
- **Score de mission (victory points)** : le state tracke `victory_points {1,2}` +
  `primary_objective_scored_turns` (depuis 2026-08-05 une famille du registre `_once_claims`,
  cf. [game_utils.py](../../../engine/game_utils.py) ; réclamée par `_apply_primary_objective_scoring_single`) et le
  vainqueur en dépend — mais l'obs squad ne le voyait **pas**. → ajouter **mon VP / VP ennemi** (ou le
  différentiel) au Bloc A. **Trou stratégique majeur** : sans lui, l'agent ne sait pas qui gagne, donc
  ne peut pas arbitrer « je mène → défensif / je préserve » vs « je suis derrière → risques / objectifs ».
- **VALUE cumulée amie & ennemie** (% de la valeur de départ) : force d'usure, info que le simple
  compte n'a pas. La VALUE est **par figurine** (`points_per_hp_i = VALUE_i / HP_MAX_i`,
  [shared_utils.py](../../../engine/phase_handlers/shared_utils.py)) → cumul = **somme par
  figurine vivante**, exacte même pour une escouade hétérogène.
- **Bloc « escouades amies »** (nouveau) : les autres escouades que l'active, **résumées** comme le
  bloc ennemi (taille, PV, position, OC, VALUE, statut). Permet à l'agent de **coordonner** ses
  escouades (aujourd'hui il ne les voit que par un compte).
- **Compte d'escouades amies/ennemies (obs 9/10)** : devient **redondant** avec VALUE cumulée + bloc
  escouades amies (le compte = longueur de liste) → candidat retrait (non urgent).

### 9.9 Granularité : raisonner en ESCOUADES, listes de longueur variable
- Décision : l'unité de raisonnement est l'**escouade**, pas la figurine. Le bloc « 6 figurines max »
  arbitraire **disparaît** : résumé d'escouade + exceptions (§9.4). **Règle la troncature figs**
  (escouade de 20 Boyz = résumé + 1-2 figs spé).
- Les **escouades** (amies et ennemies) sont fournies au set-based (§9.5) en **liste de longueur
  variable** (plus de plafond à 5) → règle la troncature ennemis/alliés. Le pooling est
  permutation-invariant ; pour le tir, on conserve l'ordre `get_enemy_slot_mapping` sur les slots
  d'action.

### 9.10 Grille — canal « couvert » (on commence par là)
- Ajouter un **7e canal de grille** peignant les hexes qui **donnent le bénéfice du couvert**
  (terrains light/dense, 13.04/13.05 ; le moteur connaît déjà le sous-ensemble Solid/dense,
  [w40k_core.py](../../../engine/w40k_core.py)). Pour la décision de **move** (par case), l'agent
  voit **où** se couvrir. Le flag « à couvert » (B2) dit *si*, ce canal dit *où*.
- Canal « zone de menace ennemie » (où je me fais tirer dessus) : **différé** (après le couvert).

### 9.7 Impact global
Toutes ces modifications changent `obs_size` et/ou les valeurs → **retrain complet** (non
contraignant, acté). Séquencement : après stabilisation du portage des capacités (les règles brutes
exposées doivent avoir un effet en résolution). **En attente du signal utilisateur** pour coder.

---

## 10. VECTEUR CIBLE réorganisé (classement utilisateur + décisions §9 appliquées)

Reclassement thématique demandé, toutes décisions §9 intégrées. Statut : ✅ gardé · ✏️ corrigé ·
➕ ajouté · ❌ supprimé. **Les index numériques ne sont pas figés** (les profils bruts pèsent N dims
selon les règles retenues) : ce qui est figé ici, c'est le **contenu et l'ordre** des blocs.

### Bloc A — Contexte général
| Dim | En clair | Statut |
|---|---|---|
| Est-ce mon tour ? | 1 = oui | ✅ |
| Phase | déploiement/commande=0, move=.25, tir=.5, charge=.75, combat=1 | ✅ |
| Tour / 5 | numéro de tour normalisé | ✅ |
| Pas / 100 | steps dans la partie | ✅ |
| Escouades amies vivantes | normalisé (étalement tactique) | ✅ |
| Escouades ennemies vivantes | normalisé | ✅ |
| **Mon score de mission (VP)** | victory_points — qui gagne la partie (arbitrage offensif/défensif) | ➕ 🔴 |
| **Score de mission ennemi (VP)** | idem côté ennemi | ➕ 🔴 |
| **VALUE cumulée amie / valeur départ** | force d'usure restante — porte une info que le simple compte n'a pas | ➕ |
| **VALUE cumulée ennemie / valeur départ** | idem côté ennemi | ➕ |
| Objectifs — contrôle ×5 | +1 je tiens / −1 ennemi / 0 contesté-vide, **dans [−1,1]** | ✏️ |
| Objectifs — présence ×5 | 1 = objectif présent dans le scénario, 0 = absent | ➕ |

### Bloc B — Mon escouade
**B1 — statut d'activation (flags)**
| Dim | En clair | Statut |
|---|---|---|
| A bougé ce tour ? | | ✅ |
| A fait un advance ? | | ✅ |
| S'est repliée (fall_back) ce tour ? | source `units_fled` | ➕ (fait, obs[19]) |
| A tiré ? | | ✅ |
| A combattu ? | | ✅ |
| Hidden ? | règle 13.09, l'ennemi ne peut pas me cibler | ➕ |
| Gone to Ground ? | règle 13.5, réduit la détection ennemie (−3") | ➕ |
| Dans l'EZ ennemie (engagée) ? | conditionne éligibilité tir 10.04 / charge | ➕ |

**B2 — état de l'escouade**
| Dim | En clair | Statut |
|---|---|---|
| Figurines vivantes / effectif départ | | ✅ |
| **HP_CUR de l'unique figurine blessée** (÷ son HP_MAX) | l'info PV non couverte par le compte (HP_MAX est en B3) | ✏️ |
| En cohérence ? | | ✅ |
| À couvert (13.08) ? | formulation à préciser | ➕ |
| Score de contrôle d'objectif (somme OC vivants) | | ✅ |

**B3 — profil de l'escouade (données brutes, niveau escouade)** ➕
| Dim | En clair |
|---|---|
| Mobilité | **MOVE** (carac de déplacement) |
| Offensif | **ensemble de {profil d'arme, nb de porteurs vivants}** — K profils tir + mêlée, chaque profil = `{NB, S, PA, DMG, portée}` + bits/params de règles ; volume de feu = compteur × NB |
| Défensif | **HP_MAX** + E / save / invuln + **flags de règles de défense** |
| ❌ supprimé | ex-`obs[20]` firepower générique T4/Sv4 (trompeur) |

### Bloc C — Mes figurines (**longueur variable**, pas de plafond 6) — SEULEMENT ce qui varie par figurine
> Raisonner en escouades (§9.9) : plus de 6 slots arbitraires. On expose le résumé (B) + les
> figurines **exceptions** ; les entités sont fournies au set-based en liste variable.

| Décalage | En clair | Statut |
|---|---|---|
| Position (col/row rel au centre) | | ✅ |
| Rôle | base / special_weapon / sergeant / support / leader (règle 19) | ➕ |
| Profil **défensif** distinct | **seulement** pour les figurines à défense différente (perso : HP_MAX/save propres). Les armes spé sont déjà dans l'ensemble {profil, compteur} de B3 → plus de « profil d'arme » ici | ➕ |
| Éligible fight ? | | ✅ |
| Dans l'EZ d'un ennemi ? | ex-« au contact » bord-à-bord → **EZ** | ✏️ |
| Dans l'EZ via un allié-copain ? | ex-bord-à-bord → **EZ** | ✏️ |
| ❌ supprimé | PV de la figurine (redondant, cf. B2) ; index d'arme CC ; profil d'arme par-fig (→ B3) | ❌ |

### Bloc D — Ennemis (**longueur variable**, ordre = menace HP×OC sur les slots d'action)
| Décalage | En clair | Statut |
|---|---|---|
| Taille escouade / **20** | (ex /10, saturait) | ✏️ |
| PV totaux / **40** | (ex /30) | ✏️ |
| **VALUE de l'escouade** (somme par figurine) | force de la cible | ➕ |
| Position de la **fig ennemie la plus proche** (col/row rel) | ex-ancre | ✏️ |
| **Distance** à cette fig la plus proche | nouveau scalaire | ➕ |
| Score de contrôle d'objectif | | ✅ |
| Emplacement occupé (mask) | | ✅ |
| Bloqué/engagé par un de mes alliés (EZ) | déjà EZ, info de ciblage | ✅ |
| **MOVE** (mobilité) | pour anticiper sa menace après son move | ➕ |
| Profil **défensif** | HP_MAX + E / save / invuln + règles def (choix de cible) | ➕ |
| Profil **offensif** | ensemble {profil, nb porteurs} (comme B3) — anticiper la menace | ➕ |
| ❌ supprimés | rentabilité (value_over_ttk) **et** menace (threat_level) — features calculées | ❌ |

### Bloc E — Escouades amies (**longueur variable**, autres que l'active) ➕
Symétrique au bloc ennemi, résumé par escouade — pour **coordonner** ses unités.
| Décalage | En clair |
|---|---|
| Taille / **20**, PV totaux / **40**, VALUE | force de l'alliée |
| Position (fig la plus proche) + distance | où elle est |
| Score de contrôle d'objectif | tient-elle un objectif ? |
| Statut (bougé/tiré/combattu, engagée, hidden…) | disponibilité |
| MOVE + profils offensif {profil, nb porteurs} / défensif | complémentarité tactique |

### Bloc F — Grille égocentrique (canaux)
Canaux actuels (6) : murs, allié, ennemi, EZ ennemie, objectifs, niveau. **+ Canal « couvert »** (7e,
§9.10) : hexes donnant le bénéfice du couvert (light/dense) → l'agent voit **où** se couvrir pour le
move. Canal « menace ennemie » différé.

### Récap suppressions / ajouts
- **❌ Supprimés** : obs[20] firepower ; +7 rentabilité ; +8 menace ; index arme CC ; PV par figurine
  (bloc C) ; (candidat) compte d'escouades.
- **➕ Ajoutés** : **score VP mien/ennemi** ; VALUE cumulée amie & ennemie ; **bloc escouades amies** ;
  VALUE par escouade ennemie ; présence objectifs ×5 ; hidden ; gone to ground ; dans EZ (escouade) ;
  à couvert ; **MOVE** (escouade/ennemi/allié) ; profils bruts off/def en **ensemble {profil, nb
  porteurs}** (escouade + ennemi + alliées) ; rôle + profil défensif des persos ; distance fig proche ;
  **canal grille couvert**.
- **✏️ Corrigés** : objectifs [−1,1] ; PV réorganisé (HP_MAX en B3, HP_CUR blessée en B2) ; contact
  fig→EZ ; position ennemie→fig proche ; normalisations /20 et /40 ; **listes de longueur variable**
  (plus de plafond 6 figs / 5 escouades) ; ordre ennemis→menace (fait).

---

## 11. Reste à faire (état au 2026-07-26)

### Fait (code)
- ✅ **D1** (réalignement slots ennemis) + **fall_back** — testés (§8).
- ✅ **T1→T7** (§8, 2026-07-25) : split `vec_cont`/`vec_bin` + valeurs brutes (fin des divisions
  manuelles) ; score VP ; VALUE cumulée amie/ennemie ; objectifs [−1,1] + présence + calcul moteur
  14.02 (fin du `try/except`) ; réorg PV + profil d'escouade brut ; suppressions obs[20] / +7 / +8 /
  index arme CC / PV par-fig / compte d'escouades ; flags hidden / GtG / EZ / couvert ; contacts
  per-fig → EZ ; position ennemie → fig la plus proche + distance + VALUE + MOVE + défensif ;
  **bloc de TYPES de figurines** (profil défensif + rôle + effectif vivant, escouade entière
  décrite) + compteurs d'engagement ; **canal grille couvert** (dilaté au rayon de socle).
  `obs_size` 108 → **199**.
- ✅ **T8 (2026-07-26)** : profils d'armes bruts + bits/params de règles (escouade ET ennemis),
  one-hot mise en place/réserve, distance parcourue par figurine. `obs_size` 199 → **1011**.
- ✅ **Contrôle d'objectif branché sur le checkpoint 14.02** (fin de phase/tour) dans le chemin
  gym, qui ne l'exécutait jamais — l'observation le lit au lieu de le recalculer (§8 T8).

### ✅ FAIT le 2026-07-26 — l'architecture set-based est livrée (§0.30, T-D→T-F)
- **Bloc E « escouades amies »** : ✅ **livré**. Il attendait l'archi set-based pour une raison
  précise — en K slots fixes, il aurait fallu inventer un ordre qu'aucune action ne consomme.
  Les alliés étant désormais **agrégés** (permutation-invariant), la question disparaît.
- **Plafonds** : les slots ennemis passent de 5 à **20** (tête pointeur : un slot ne coûte plus
  de paramètres), les profils d'armes à **10 par registre des deux côtés**, et les types de
  figurines existent aussi côté ennemi. Tout dépassement résiduel est **logué**.
- Détail, mesures et verrous → [`V11_entity_encoder_pointer.md`](V11_entity_encoder_pointer.md) §6.

### ✅ FAIT le 2026-07-26 — les 3 points débloqués par la fin du portage des capacités

> **Livrés (cf. §8, étape T8).** `obs_size` 199 → **1011**. Le libellé d'origine est conservé
> ci-dessous comme spécification de ce qui a été codé ; les écarts assumés (K par camp,
> [INDIRECT FIRE] exclue, périmètre phase de mouvement pour la distance) sont documentés en §8
> et dans `V11_agent_rework.md` §9.2.5–§9.2.6.

> Le signal attendu est levé : toutes les règles d'armes du PDF 24 présentes dans les armories sont
> résolues dans le chemin vif, tir ET mêlée (cf. `V11_agent_rework.md` §9.2.1–§9.2.5).
> **L'observation est donc, à ce jour, le seul maillon qui manque** : l'agent SUBIT ces règles sans
> en percevoir une seule.

1. **Profils d'armes bruts + flags de règles à effet réel** (escouade, ennemis, alliées) — 🔴 **le
   trou principal**. Le vecteur squad (199-d) ne contient **aucun** profil d'arme ni bit de règle :
   ni NB/ATK/STR/AP/DMG/RNG, ni [DEVASTATING WOUNDS], [SUSTAINED HITS], [LETHAL HITS], [ANTI-X],
   [MELTA], [TORRENT], [TWIN-LINKED], [BLAST], [CLEAVE], [EXTRA ATTACKS], [PRECISION], [PSYCHIC],
   [HAZARDOUS], [HEAVY], [RAPID FIRE], [IGNORES COVER]. La liste exposée suit exactement la liste
   des règles **résolues** (elle est désormais stable). Deux paramètres à exposer avec leur règle
   (X de SUSTAINED/MELTA/RAPID FIRE/CLEAVE/BLAST, Y+ de ANTI-X) — et le **keyword ciblé** de ANTI-X,
   sans quoi le canal est du bruit (l'effet dépend des keywords de la CIBLE, cf. 19.03).
2. **Feature déploiement/réserve** one-hot 3 états dérivée de `deployed_on_turn` — ✅ **la source
   moteur EXISTE depuis le 2026-07-26** (`engine/game_state.py` à la création, écrite au commit de
   déploiement dans `deployment_handlers._apply_deploy_plan` ; 0 = pré-bataille, N = arrivée de
   réserve au tour N, `None` = pas encore sur le board). Elle est déjà consommée par la clause 2 de
   [HEAVY] 24.16. Reste à en **dériver le one-hot** dans l'observation (+3 dimensions).
3. **Distance de déplacement par figurine ce tour** — ➕ **à ajouter** (demande utilisateur
   2026-07-26). Deux usages, une seule donnée :
   - **Règle** : clause 3 de [HEAVY] 24.16 (« no model in that unit has moved more than 3\" this
     turn »). Aujourd'hui le moteur ne conserve **que** le booléen `units_moved`/`units_advanced`,
     donc la clause est appliquée sous sa borne conservatrice « aucune figurine n'a bougé » — plus
     stricte que la règle, jamais laxiste, mais fausse dès qu'une unité se repositionne de 2\".
   - **Observation** : savoir de combien on a déjà bougé conditionne l'advance, la charge et le
     move-after-shooting ; c'est une grandeur continue brute (subhexes), pas un drapeau.
   - **Source** : le coût GÉODÉSIQUE du chemin (pas la distance à vol d'oiseau — un contournement
     de mur coûte plus que l'écart départ↔arrivée). Il est déjà calculé par le pool de destinations
     de move ; il faut le porter jusqu'à `commit_move` (qui ne reçoit aujourd'hui que
     `(mid, col, row, level, orientation)`) et l'accumuler par figurine dans un
     `moved_distance_by_model` remis à zéro au début du tour du joueur.
   - `obs_size` : +1 par figurine observée (ou +2 : max et somme sur l'escouade) — à trancher au
     moment de l'implémentation, avec le bloc figurines.

> 🔴 **MAJ 2026-07-26 — l'architecture est OUVERTE, avec son chantier dédié :**
> [`V11_entity_encoder_pointer.md`](V11_entity_encoder_pointer.md). Décisions actées : encodeur
> d'entité **partagé** (unités ET armes, amies ET ennemies), **agrégation seulement pour ce
> qu'aucune action ne désigne** (alliés, armes, types de figurines), **embeddings par slot +
> tête pointeur** pour les ennemis (une action les désigne — c'est l'invariant D1), **K=20
> unités / K=10 armes**. Motif déclencheur : 5 slots ennemis figés pour **6 escouades mesurées**
> → une unité invisible et intirable dans 6 épisodes sur 10.

### Architecture (après les correctifs d'observation)
- **Set-based Niveau 1** (Deep Sets, listes variables) → retrain → mesurer le win-rate.
- **Niveau 2 (attention)** seulement si plafonnement.

### Décisions tranchées (2026-07-25)
- **Encodage des profils bruts** : exposer **les deux registres en permanence** (tir + mêlée), pas
  « l'arme active selon la phase » (l'agent doit anticiper tir ET mêlée en move). Par escouade / slot :
  **K armes de tir + 1 mêlée**, chacune `{NB, S, PA, DMG, portée}` + **bits de règles** ;
  **règles paramétrées** (RAPID_FIRE X, SUSTAINED_HITS X, ANTI_X, MELTA X) = **valeur du paramètre**
  normalisée, pas un bit. Défensif `{HP_MAX, E, save, invuln}` + bits def. **Inclure la carac MOVE**
  (surtout ennemie, cf. menace). « Arme principale » évitée (dépend de la cible = calcul) → K slots +
  padding.
  - **Armes multiples / profils multiples** : `RNG_WEAPONS`/`CC_WEAPONS` sont des listes, un **profil =
    une entrée** → « arme à profils » = « plusieurs armes », pas de cas spécial. Comme les profils sont
    exposés **au niveau escouade** (homogène) + exceptions, le nombre de profils **distincts** est
    petit → **(A) K slots + padding**, K dimensionné sur les rosters réels (troncature **loguée** si
    dépassement, jamais silencieuse). **(B) armes = entités set-based** (set imbriqué) gardée en réserve
    si un roster futur dépasse K.
  - **Compteur de porteurs par profil (essentiel)** : chaque profil exposé porte le **nombre de
    figurines vivantes équipées de ce profil** → le volume de feu = **compteur × NB**. Sans lui,
    l'agent ne sait pas si 1 ou 10 figurines tirent le profil. Gère l'hétérogénéité partielle
    (8 shoota + 2 rokkit = deux profils avec compteurs 8 et 2). L'escouade devient un **ensemble de
    {profil, nb de porteurs vivants}**. Calcul : grouper les figurines vivantes (`models_cache` /
    `squad_models`) par **identité de profil** (nom d'arme / tuple de stats). On expose la **capacité**
    (porteurs), pas l'éligibilité contextuelle (portée/LoS → masque + grille).
- **Normalisation** : **valeurs continues brutes normalisées par `VecNormalize` ; flags binaires bruts
  NON normalisés** — séparation `vec_cont` / `vec_bin` via `norm_obs_keys=["vec_cont"]` (natif SB3,
  [train.py](../../../ai/train.py)). Retire la double normalisation ET protège la sémantique des
  flags. Coût faible → **pas de dette** (choix (ii) retenu sur (i)).
- **Canal « menace ennemie »** : **abandonné**. Une carte statique serait fausse (l'ennemi bouge avant
  de tirer) ; la rendre juste = anticiper le move = heuristique biaisée (péché des features calculées).
  L'agent l'apprend depuis les données brutes (positions + portée + **MOVE** ennemis).
- **Compte d'escouades (obs 9/10)** : **supprimé** (la VALUE cumulée le remplace avantageusement).

### Chantier dédié — Observation de la phase de déploiement (déficiente, vérifié)

> 📤 **DÉPLACÉ le 2026-07-28 → [`observation_deploiement.md`](observation_deploiement.md).**
> C'est le seul point encore actionnable de cet audit ; il vit désormais dans son propre chantier,
> avec les constats **re-vérifiés dans le code**. Le point 3 ci-dessous est **inexact** (les 5
> actions sont des stratégies tactiques, pas « les 5 premiers hexes valides ») — il est corrigé
> dans le chantier extrait. Texte d'origine conservé ci-dessous pour mémoire uniquement.
Problèmes ([w40k_core.py](../../../engine/w40k_core.py), [action_decoder.py](../../../engine/action_decoder.py)/1013) :
1. Obs construite sur `next(iter(units_cache))` = **1ʳᵉ unité du cache, pas forcément celle déployée**.
2. Unité à `(-1,-1)` → **grille égocentrique dégénérée** (centrée hors plateau).
3. Les 5 actions = 5 hexes candidats **non décrits** dans l'obs (position/objectif/couvert/ennemis) et
   **seuls les 5 premiers** hexes valides triés sont offerts → **déploiement quasi à l'aveugle**.
→ Nécessite une **observation spécifique au déploiement** (grille centrée zone de déploiement,
description des hexes candidats, ennemis déjà posés, objectifs). Traité **séparément** de la refonte
du vecteur de jeu.

