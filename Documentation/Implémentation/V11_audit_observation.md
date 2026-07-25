# Audit de l'observation de l'agent (V11) — 2026-07-25

> But : dire, dimension par dimension et **sans jargon**, ce que l'agent voit réellement,
> ce qui est mort/redondant, ce qui manque. Tout est vérifié dans le code (numéros de ligne)
> et croisé avec les règles `Documentation/40k_rules/`. Une section de **re-audit** en fin de
> document reprend chaque conclusion pour vérifier qu'elle est optimale.

---

## 0. Correction d'une première conclusion fausse (important)

Une première passe avait conclu : « ~9 règles d'armes sont observées mais n'ont aucun effet →
bruit pur ». **C'est faux pour l'agent réel.** Raison :

Il existe **deux** constructeurs d'observation dans [observation_builder.py](../../engine/observation_builder.py) :

| Constructeur | Taille | Contient les 32 « rule features » ? | Utilisé par ArmageddonAgent ? |
|---|---|---|---|
| `build_observation` (mono-figurine, ancien) | **357** | Oui (index 314, `_encode_rule_features`, [ligne 1225](../../engine/observation_builder.py#L1225)) | **NON** |
| `build_squad_observation` (escouade, actuel) | **108** | **Non** (aucune) | **OUI** |

Le routage est dans [w40k_core.py:6218-6237](../../engine/w40k_core.py#L6218-L6237) : il lit `obs_size`
depuis la config et n'appelle `build_squad_observation` que si `obs_size == 108`. La config
`ArmageddonAgent` fixe **`obs_size: 108`** dans les 5 profils
([training_config](../../config/agents/ArmageddonAgent/ArmageddonAgent_training_config.json#L112)).
De plus `build_observation` **lève une erreur** si `obs_size != 357`
([ligne 1094-1098](../../engine/observation_builder.py#L1094)) — donc le chemin 357 et ses 32 règles
sont **du code mort pour cet agent**.

**Conséquence, corrigée :** le vrai problème n'est PAS du bruit de règles observées. C'est
l'**inverse** — l'observation active (108) n'observe **AUCUNE** règle spéciale ni statistique
d'arme brute, et il lui manque des informations de décision que les règles exigent.

---

## 1. Ce que l'agent voit réellement

L'observation active a **deux morceaux** donnés ensemble au réseau :

1. un **vecteur de 108 nombres** (`build_squad_observation`, [1253-1542](../../engine/observation_builder.py#L1253)),
2. une **grille égocentrique** de 6 images superposées centrées sur l'escouade active
   (`build_squad_grid`, [1548-1692](../../engine/observation_builder.py#L1548)).

L'espace d'action associé (justification config) : 1024 cases de déplacement + attendre +
5 cibles de tir + charge + fight + 15 macro (5 objectifs × 3 intentions). **Donc l'agent choisit
déjà : où bouger, quelle cible tirer/charger, quel objectif viser.** L'observation doit nourrir
ces choix-là.

### 1.1 Le vecteur — les 108 nombres, un par un (sans jargon)

> **État** : ce tableau décrit le code **actuel**, après l'étape 1 (D1 + fall_back, cf. §8).
> Les refontes décidées (données brutes, suppressions, corrections) sont en **§9** et **pas encore
> codées** — ne pas les chercher ici.

**Bloc « contexte général » (index 0 à 15)**

| # | Ce que c'est, en clair | Ligne |
|---|---|---|
| 0 | Est-ce mon tour ? (1 = oui) | [1287](../../engine/observation_builder.py#L1287) |
| 1 | Quelle phase (déploiement/commande=0, move=0.25, tir=0.5, charge=0.75, combat=1) | [1289](../../engine/observation_builder.py#L1289) |
| 2 | Numéro du tour, sur 5 | [1290](../../engine/observation_builder.py#L1290) |
| 3 | Nombre de « pas » joués dans la partie, sur 100 | [1291](../../engine/observation_builder.py#L1291) |
| 4 | Points de vie restants de mon escouade (en % du total) | [1302](../../engine/observation_builder.py#L1302) |
| 5 | Mon escouade a-t-elle déjà bougé ce tour ? | [1303](../../engine/observation_builder.py#L1303) |
| 6 | A-t-elle déjà tiré ? | [1304](../../engine/observation_builder.py#L1304) |
| 7 | A-t-elle déjà combattu ? | [1305](../../engine/observation_builder.py#L1305) |
| 8 | A-t-elle fait une avance (advance) ? | [1306](../../engine/observation_builder.py#L1306) |
| 9 | Nombre d'escouades amies vivantes (normalisé) | [1315](../../engine/observation_builder.py#L1315) |
| 10 | Nombre d'escouades ennemies vivantes (normalisé) | [1316](../../engine/observation_builder.py#L1316) |
| 11-15 | Pour chacun des 5 objectifs : +1 je le tiens, −1 l'ennemi le tient, 0 contesté/vide | [1326](../../engine/observation_builder.py#L1326) |

**Bloc « résumé de mon escouade » (index 16 à 20)**

| # | En clair | Ligne |
|---|---|---|
| 16 | Combien de figurines me restent (en % de l'effectif de départ) | [1332](../../engine/observation_builder.py#L1332) |
| 17 | Mon escouade est-elle en cohérence (bien groupée) ? | [1333](../../engine/observation_builder.py#L1333) |
| 18 | Score de contrôle d'objectif de mon escouade (somme des OC) | [1334](../../engine/observation_builder.py#L1334) |
| 19 | **Flag FALL BACK** — l'escouade s'est-elle repliée ce tour ? (ex-doublon HP% réaffecté, cf. §8) | [1335](../../engine/observation_builder.py#L1335) |
| 20 | Estimation de ma puissance de feu contre une cible générique (T4/save 4) | [1369](../../engine/observation_builder.py#L1369) |

**Bloc « mes figurines », 6 figurines max × 7 infos (index 21 à 62)**
Pour chacune des 6 premières figurines vivantes :

| décalage | En clair | Ligne |
|---|---|---|
| +0 / +1 | Position de la figurine par rapport au centre de l'escouade (colonne / ligne) | [1399](../../engine/observation_builder.py#L1399) |
| +2 | Ses points de vie (%) | [1401](../../engine/observation_builder.py#L1401) |
| +3 | Index de l'arme de corps-à-corps sélectionnée (sur 5) | [1403](../../engine/observation_builder.py#L1403) |
| +4 | Peut-elle combattre maintenant (éligible fight) ? | [1404](../../engine/observation_builder.py#L1404) |
| +5 | Est-elle au contact d'un ennemi ? | [1411](../../engine/observation_builder.py#L1411) |
| +6 | Est-elle au contact d'un ami qui, lui, touche un ennemi (règle du « copain ») ? | [1428](../../engine/observation_builder.py#L1428) |

**Bloc « ennemis », 5 emplacements × 9 infos (index 63 à 107)**
Pour chacun des 5 slots ennemis, **ordre = menace HP×OC décroissante** (`get_enemy_slot_mapping`,
même ordre que l'action tir/charge — D1 corrigé, cf. §8) :

| décalage | En clair | Ligne |
|---|---|---|
| +0 | Taille de l'escouade ennemie (nb figurines /10) | [1460](../../engine/observation_builder.py#L1460) |
| +1 | Ses points de vie totaux (/30) | [1461](../../engine/observation_builder.py#L1461) |
| +2 / +3 | Sa position par rapport à moi (colonne / ligne) | [1462](../../engine/observation_builder.py#L1462) |
| +4 | Son score de contrôle d'objectif | [1464](../../engine/observation_builder.py#L1464) |
| +5 | Emplacement occupé (1 = un ennemi est là, 0 = vide) | [1465](../../engine/observation_builder.py#L1465) |
| +6 | Est-il « bloqué » au contact d'une de mes escouades ? | [1473](../../engine/observation_builder.py#L1473) |
| +7 | Rentabilité de le tuer (sa valeur en points ÷ temps pour le tuer) | [1539](../../engine/observation_builder.py#L1539) |
| +8 | Menace qu'il représente (dégâts qu'il peut me faire) | [1540](../../engine/observation_builder.py#L1540) |

### 1.2 La grille égocentrique — 6 images (canaux)

Centrée sur l'escouade active, chaque « pixel » = un hex. 6 couches
([1566-1690](../../engine/observation_builder.py#L1566)) :

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
- **n° 19 = doublon exact du n° 4** ([1302](../../engine/observation_builder.py#L1302) vs
  [1335](../../engine/observation_builder.py#L1335)) : même calcul PV%. **1 dimension gaspillée.**
  → la réaffecter à une info utile (voir §3.4).

### 3.3 ⚠️ À CORRIGER (défauts fonctionnels)
- **n° 11-15, repli silencieux** : `try/except: pass` sur l'encodage des objectifs
  ([1327](../../engine/observation_builder.py#L1327)) — si les objectifs sont malformés, le canal
  passe à 0 **sans erreur**. Interdit par CLAUDE.md (fallback masquant). Marqué « PR4 acceptable,
  strict en PR5 » : à rendre strict.
- **n° +7 (rentabilité) et +8 (menace) des ennemis** ([1477-1538](../../engine/observation_builder.py#L1477)) :
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
([1477-1538](../../engine/observation_builder.py#L1477)) corrige la perception de toutes ces
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
- Bloc figurines = **6 max** ([SQUAD_TOP_K](../../engine/observation_builder.py#L1248)) : une
  escouade Ork Boyz (10-20) est **tronquée** — les figurines au-delà de 6 sont invisibles. Impact
  cohérence/positionnement à grande escouade. À statuer (élargir k, ou trier par pertinence).
- Bloc ennemis = **5 max**, triés par **identifiant** ([1432-1435](../../engine/observation_builder.py#L1432)) :
  tri **stable** (bon pour PPO, §9.5) mais **arbitraire** — au-delà de 5 escouades ennemies,
  certaines ne sont jamais vues, et l'ordre n'est pas « par pertinence ». Sur les rosters SM/Orks
  actuels le nombre d'escouades est probablement ≤5 (à confirmer sur les rosters réels) ; sinon
  c'est un trou. Le tri « stable par HP×OC » est explicitement différé (PR4 4d) : **le faire**
  améliorerait l'assignation de crédit.

**R6 — Réserve de méthode (inchangée, confirmée).**
L'observation optimale se définit **par rapport aux décisions**. Ici les décisions tir/charge/cible
existent **déjà** (espace d'action 1047), donc les manques §3.4 sont pertinents **maintenant**.
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
Espace d'action = 1047 ([macro_intents.py:19-32](../../engine/macro_intents.py#L19)) :
- **1024** cases de la grille égocentrique = **où bouger** (phase move).
- **wait**.
- **5** slots de tir = **quel ennemi tirer** (parmi 5 slots).
- **charge** (1 action) : la **cible est choisie par le moteur**, pas par l'agent
  ([decoder 965-994](../../engine/action_decoder.py#L965)) → l'agent décide seulement charger/pas.
- **fight** (1 action) : idem, cible = pool 12.04, l'agent décide combattre/pas.
- **15** macro = 5 objectifs × 3 intentions (invade/defend/attack).
- **L'arme n'est PAS choisie par l'agent** (aucune action de sélection d'arme) → inutile
  d'exposer tous les profils d'armes ; seule l'arme sélectionnée compte.

### 5bis.2 Deux résultats décisifs

**🔴 D1 — Désalignement obs/action sur les slots ennemis (défaut de CORRECTION).**
- L'**observation** ordonne les 5 slots ennemis par `sorted(str(sid))`
  ([1432-1435](../../engine/observation_builder.py#L1432)).
- L'**action** tir/charge les ordonne par **menace HP×OC décroissante**, mapping stable figé en
  début de partie (`init_enemy_slot_mapping`, [8406](../../engine/phase_handlers/shared_utils.py#L8406)),
  consommé par le masque ([decoder 217](../../engine/action_decoder.py#L217)) ET l'exécution
  ([decoder 971](../../engine/action_decoder.py#L971)).
- Les deux ordres **diffèrent** → « tirer slot 0 » ne vise PAS l'ennemi décrit par obs-slot-0.
  Le réseau devrait apprendre une permutation qui **dépend de l'état** (qui est alphabétiquement-i
  vs menace-i) : impossible à câbler → **le signal de choix de cible est brouillé.** C'est la
  cause la plus grave et la moins visible. **Correctif : faire consommer à `build_squad_observation`
  le MÊME `get_enemy_slot_mapping`** (source unique), au lieu de son tri local. Ne change pas
  `obs_size`.

**🟢 D2 — Le masque porte déjà « portée + LoS + engagement » par slot de tir.**
Le masque n'ouvre un slot de tir que si `_model_can_shoot_target` est vrai = **au moins une
figurine à portée (subhex) ET en ligne de vue (murs) ET cible non verrouillée**
([shoot mask 8288-8319](../../engine/phase_handlers/shared_utils.py#L8288) →
[_model_can_shoot_target 4766-4793](../../engine/phase_handlers/shared_utils.py#L4766)). MaskablePPO
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
| **0 🔴** | **Aligner l'ordre des slots ennemis de l'obs sur `get_enemy_slot_mapping`** (source unique tir/charge). Sans ça, le choix de cible est brouillé (D1). | [obs 1432](../../engine/observation_builder.py#L1432) | Non |
| **1** | Rendre **+7 (rentabilité) et +8 (menace)** conscients des **règles spéciales**, du **couvert** et de la **demi-portée** (couvre IGNORES_COVER, DEVASTATING, closest_target_penetration, rerolls, RAPID FIRE…) | [1477-1538](../../engine/observation_builder.py#L1477) | Non |
| **2** | Réemployer le **doublon n°19** → une feature utile (ex. flag `fell_back`, absent) | [1335](../../engine/observation_builder.py#L1335) | Non |
| **3** | Rendre **strict** l'encodage objectifs (retirer `except: pass`) | [1327](../../engine/observation_builder.py#L1327) | Non |
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
2. **+7/+8 (rentabilité/menace) ignorent règles, couvert et demi-portée** → faux dès que les
   capacités de cette nuit seront actives. **Levier central.**
3. **HEAVY / HAZARDOUS** (décisions structurelles) non observables.
4. **Move** : la grille ne distingue pas le terrain **couvrant** du mur bloquant.

Une fois ces 4 points traités (+ nettoyage doublon n°19 et strict objectifs), l'observation
**couvre chaque décision réelle** de l'agent : move (grille + couvert), tir (slots alignés +
rentabilité juste + masque portée/LoS), charge/fight (masque + rentabilité), objectifs (déjà bon).
C'est **à ce moment** qu'on pourra dire l'observation optimale pour l'espace d'action actuel — et il
faudra la ré-évaluer si P2/P3 change les décisions.

---

## 7. Proposition d'architecture : découpe structurée du vecteur (préparée, pas encore implémentée)

Le vecteur 108 entre aujourd'hui **tel quel** dans un MLP dense (`SpatialCombinedExtractor.forward` =
`cat[cnn_out, vec]`, [spatial_extractor.py:87](../../ai/spatial_extractor.py#L87)). Une couche dense
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
4. **Masque d'action inchangé** : les 1047 logits finaux restent masqués par MaskablePPO.

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

### 2026-07-25 — Étape 1 : D1 (réalignement des slots ennemis) + fall_back — ✅ FAIT
- **D1** : `build_squad_observation` lit désormais l'ordre des slots ennemis via
  `get_enemy_slot_mapping` (mapping stable HP×OC, **même source que le masque et l'exécution**),
  au lieu de son tri local `sorted(str(sid))`. Fin du désalignement obs↔action.
  [observation_builder.py](../../engine/observation_builder.py) (import + section 4).
- **fall_back** : `obs[19]` (ex-doublon exact de `obs[4]` HP%) réaffecté au flag « escouade
  repliée ce tour ? » (`units_fled`, même source que `build_squad_action_mask`).
- **Tests** : `tests/unit/engine/test_squad_obs_enemy_slot_alignment.py` (3) — alignement obs↔mapping,
  contre-épreuve intégrée (fixture où ordre-menace ≠ ordre-alphabétique → rouge sous l'ancien code),
  flag fall_back 0↔1. Suites `test_observation_builder` / `test_squad_grid_observation` /
  `test_model_value_per_figurine` vertes (non-régression).
- **Impact** : change les valeurs de l'observation → **retrain requis** (attendu). `obs_size`
  inchangé (108).

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
- `obs_size` : 108 → **111** (retrain, non contraignant).

**+7/+8 (rentabilité/menace) conscients des règles et du couvert.**
- Construire **UNE** fonction d'espérance de dégâts consciente des règles (source unique, remplaçant
  les 4 implémentations divergentes actuelles), **après** stabilisation du portage de cette nuit
  (HEAVY / HAZARDOUS / DEVASTATING / RAPID_FIRE ; IGNORES_COVER / closest_target_penetration /
  rerolls déjà stables). Puis brancher +7/+8 (et idéalement bots / reward) dessus. Ne pas coder de
  5ᵉ logique inline avant (divergence interdite).

> **Statut** : les deux sont **en attente du signal utilisateur** (portage non terminé). Rien codé.

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
  `try/except: pass` masquant ([1327](../../engine/observation_builder.py#L1327)).
- **Position ennemie (`+2/+3`)** : mesurer depuis la **figurine ennemie la plus proche** (pas
  l'ancre), **+ ajouter la distance** à cette figurine (les coords donnent déjà la direction ; la
  distance fig-à-fig est ce que la portée utilise).
- **Normalisations ennemies** : taille `/10 → /20`, PV `/30 → /40` (escouades jusqu'à 20 figurines,
  ex. Boyz — le `/10` saturait).
- **Contact par figurine (`base+5/+6`)** : bascule du **bord-à-bord brut** (`calculate_hex_distance
  == 1`, [1407](../../engine/observation_builder.py#L1407)) vers la **présence dans l'EZ**
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
  de l'escouade (`attached_squad`, [game_state.py:724](../../engine/game_state.py#L724)) ; chaque
  figurine porte un **rôle** `base < special_weapon < sergeant < support < leader`
  ([shared_utils.py:542](../../engine/phase_handlers/shared_utils.py#L542)). → le bloc figurines
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
  `primary_objective_scored_turns` ([game_state.py:2392](../../engine/game_state.py#L2392)) et le
  vainqueur en dépend — mais l'obs squad ne le voyait **pas**. → ajouter **mon VP / VP ennemi** (ou le
  différentiel) au Bloc A. **Trou stratégique majeur** : sans lui, l'agent ne sait pas qui gagne, donc
  ne peut pas arbitrer « je mène → défensif / je préserve » vs « je suis derrière → risques / objectifs ».
- **VALUE cumulée amie & ennemie** (% de la valeur de départ) : force d'usure, info que le simple
  compte n'a pas. La VALUE est **par figurine** (`points_per_hp_i = VALUE_i / HP_MAX_i`,
  [shared_utils.py:580](../../engine/phase_handlers/shared_utils.py#L580)) → cumul = **somme par
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
  [w40k_core.py:281](../../engine/w40k_core.py#L281)). Pour la décision de **move** (par case), l'agent
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

## 11. Reste à faire (état au 2026-07-25)

### Fait (code)
- ✅ **D1** (réalignement slots ennemis) + **fall_back** (obs[19]) — testés (§8).

### À coder — indépendant du portage des capacités (faisable dès accord)
- Score VP (Bloc A) ; VALUE cumulée amie/ennemie ; **bloc escouades amies** ; objectifs [−1,1] +
  présence ; réorg PV (HP_MAX/HP_CUR, suppr PV par-fig) ; normalisations /20 /40 ; position ennemie
  → fig proche + distance ; contact per-fig → EZ ; flags hidden / GtG / EZ / couvert ; suppression
  obs[20] / +7 / +8 / index arme CC ; **canal grille couvert** ; listes de longueur variable.

### À coder — dépendant du portage des capacités (après stabilisation)
- Profils bruts **offensifs/défensifs** (escouade, ennemis, alliées) avec **flags de règles à effet
  réel** — la liste des règles exposées suit la liste des règles résolues.
- **Feature déploiement/réserve** one-hot 3 états dérivée de `deployed_on_turn` (source partagée HEAVY,
  §8 « Décisions actées »).

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
  [train.py:1308](../../ai/train.py#L1308)). Retire la double normalisation ET protège la sémantique des
  flags. Coût faible → **pas de dette** (choix (ii) retenu sur (i)).
- **Canal « menace ennemie »** : **abandonné**. Une carte statique serait fausse (l'ennemi bouge avant
  de tirer) ; la rendre juste = anticiper le move = heuristique biaisée (péché des features calculées).
  L'agent l'apprend depuis les données brutes (positions + portée + **MOVE** ennemis).
- **Compte d'escouades (obs 9/10)** : **supprimé** (la VALUE cumulée le remplace avantageusement).

### Chantier dédié — Observation de la phase de déploiement (déficiente, vérifié)
Problèmes ([w40k_core.py:6239](../../engine/w40k_core.py#L6239), [action_decoder.py:176](../../engine/action_decoder.py#L176)/1013) :
1. Obs construite sur `next(iter(units_cache))` = **1ʳᵉ unité du cache, pas forcément celle déployée**.
2. Unité à `(-1,-1)` → **grille égocentrique dégénérée** (centrée hors plateau).
3. Les 5 actions = 5 hexes candidats **non décrits** dans l'obs (position/objectif/couvert/ennemis) et
   **seuls les 5 premiers** hexes valides triés sont offerts → **déploiement quasi à l'aveugle**.
→ Nécessite une **observation spécifique au déploiement** (grille centrée zone de déploiement,
description des hexes candidats, ennemis déjà posés, objectifs). Traité **séparément** de la refonte
du vecteur de jeu.

