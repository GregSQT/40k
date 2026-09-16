# Training — Tâches ouvertes

---

## ⚠️ À FAIRE UNE FOIS — initialiser le contrat des modèles existants {#contrat-init}

**Livré le 2026-09-09** (`ai/training_contract.py`). Le prologue d'un run vérifie désormais que le
modèle repris a appris sur le **même sens** des grandeurs : registres d'observation, canaux de
grille, familles d'actions, **clés** de la table de récompense. C'est le trou que ni
`check_model_lifecycle` (qui regarde la commande), ni le verrou de parité de pool (qui parle après
la première sonde), ni `check_for_correct_spaces` de SB3 (qui ne voit que les dimensions) ne
couvrent : la dérive à taille **constante**.

**Conséquence immédiate** : un modèle antérieur à cette livraison n'a pas de contrat, donc sa
première reprise (`--append`, `--resume-from`) **s'arrête**. Après avoir vérifié que le contrat
courant est bien celui sur lequel ce modèle a appris :

```bash
python3 -m ai.training_contract --init --agent ArmageddonAgent_x1
```

Un `--new` n'a rien à faire : il écrit le contrat lui-même. Les **valeurs** de récompense ne sont
pas comparées — régler un poids reste libre, seule la disparition d'une clé arrête un run.

**Migration du 2026-09-12 (suite 115)** : le contrat est devenu un **compagnon par modèle**
(`<stem>_training_contract.json`, `CONTRACT_SUFFIX` dans `ai/model_artifacts.py`), et `--resume-from`
installe celui du modèle promu — un artefact sans contrat n'est plus promouvable. **Règle** : dans
chaque dossier d'agent, renommer l'ancien contrat unique (nom nu `training_contract`, sans stem) en
`model_<agent>_training_contract.json`, puis copier ce contrat sous le nom de chaque artefact
reprenable **de la même lignée** (modèles d'étape `_P<n>`, `ppo_checkpoint_*`, `_interrupted`).

**Fait le 2026-09-12** : `ArmageddonAgent_x1/` (canonique renommé ; copies pour `P0`, `P1`, `P2` et
les trois `ppo_checkpoint_*` — 7 fichiers identiques octet pour octet, `--agent ArmageddonAgent_x1`
répond « contrat inchangé ») et `ArmageddonAgent_x1_entnorm/` (canonique renommé, « contrat
inchangé »).

✅ **Fait le 2026-09-12 (soir), run entnorm terminé** : le contrat canonique
`model_<agent>_training_contract.json` d'`ArmageddonAgent_x1_entnorm/` copié sous le nom des trois
checkpoints survivants (`ppo_checkpoint_<n>_steps_training_contract.json`) ; le run suivant sous le
nouveau code (2026-09-13 04:07) a écrit les siens à côté.

`model_ArmageddonAgent_x1_P00.zip` (1er septembre, `obs_size` antérieur) n'est pas de cette lignée :
pas de contrat. `CoreAgent/` n'a jamais eu de contrat : inchangé (sa reprise demande `--init`, comme
avant). Les `training_contract_<stamp>.json` et `training_contract_pre_resume_<stamp>.json` déjà
écartés décrivent les archives `model_ArmageddonAgent_x1_<stamp>.zip` / `_pre_resume_<stamp>.zip` du
même horodatage : les renommer en `<stem de l'archive>_training_contract.json` seulement si l'on
compte reprendre une de ces archives.

**Correctif du 2026-09-09** : un contrat enregistré **abîmé** (section absente, vide, du mauvais
type, version non entière) **lève** au lieu d'être lu comme vide. Lu comme vide, il produisait un
diff faux — les 17 registres du code annoncés « nouveaux » sous le titre « le contrat a changé »,
avec `--new` pour seule sortie affichée, donc un modèle de plusieurs dizaines d'heures jeté sur un
fichier tronqué. Réparer le fichier et reprendre le run sont deux réponses opposées : le message
dit maintenant laquelle.

---

## ✅ Obs — couples arme→cible du tir fractionné {#couples-arme-cible-split-fire}

**Livré le 2026-09-09.** `obs_size` 17916 → **18204** : ré-entraînement `--new` obligatoire —
déjà exigé par les lots du même jour, et aucun artefact du disque n'était compatible (P0, P1 et
le dernier run sauvegardé étaient à 16791, `best_model.zip` à 17055 — mesuré dans les `.zip`).

Deuxième temps du maillon précédent, qui n'avait couvert que la PREMIÈRE arme du split-fire. Une
fois un couple arme → cible commité, l'agent choisit l'arme suivante puis sa cible sans rien voir
de ce qu'il a déjà envoyé et sur qui.

**Mesuré :** les dix bits mis à 0, deux états ne différant que par la cible déjà assignée rendent
des observations **identiques sur les 28 clés**, aux DEUX sous-états — celui qui demande l'arme
suivante comme celui qui demande sa cible. Le masque ne le disait pas non plus : une cible déjà
prise reste éligible pour l'arme suivante.

**Ce qui a été livré :**

- `split_assigned_w0..9` (`UNIT_BIN_FIELDS`, 10 bits × 32 entités = +320) : le bit `i` vaut 1 ssi
  l'arme du slot de profil RNG `i` est déjà assignée à cette escouade. Transposée exacte de
  `assignments` — sur la ligne de la cible, quelles de mes armes la visent déjà ;
- `n_weapons_assigned` **retiré** (−32) : il était la projection `popcount` de ces bits.
  L'égalité est garantie par l'injectivité `code d'arme → slot de profil`, vérifiée sur les 179
  datasheets et les 33 escouades des `config/armies/` — les armes à profils multiples portent des
  codes distincts (`plasma_pistol_standard` / `_supercharge`), `COMBI_WEAPON` marquant l'arme
  physique partagée. Garder les deux, c'était deux encodages du même fait ;
- **dix bits et non un seul « déjà ciblée »** : 04.03 « Gather Attack Dice » cumule les dés des
  armes faisant des attaques identiques sur une même cible, donc la conséquence de règle dépend de
  QUELLE arme y est déjà. Mesuré sur les 11 escouades Armageddon (SM+Orks) : 55 % portent ≥ 3
  profils de tir, jusqu'à 6 — soit 75 % de celles capables de split-fire, pour qui un bit unique
  perdrait l'appariement ;
- le slot vient de `assignments[code]["weapon_slot"]`, **RECOPIÉ** du `pending_weapon_slot` du
  moteur au moment du commit de la cible, jamais re-dérivé du code par l'observation (invariant
  D1). C'est ce qui fait passer les valeurs d'`assignments` de `str` à
  `{target_id, weapon_slot}` ; le seul autre lecteur de la table (le précheck de quantité d'armes)
  suit le même couple ;
- un seul lecteur d'activation, `read_pending_shoot_split` : les deux lecteurs de sous-état en
  dérivent, et le doublon apparu en parallèle a été supprimé plutôt que conservé ;
- **coût réseau mesuré**, pas estimé : extracteur 245 392 → 246 544 paramètres (+1 152, +0,47 %),
  l'encodeur d'entité étant partagé entre les deux camps ;
- verrous : marquage sur la ligne de la cible et sur elle seule, deux armes sur la MÊME cible →
  deux bits, clôture de la liste sur `K_WEAPONS_RANGED`, absence hors split-fire et dans
  l'observation d'une autre escouade, slot hors bloc d'armes → erreur, et un test réseau qui exige
  que **deux slots assignés différents donnent deux embeddings différents** — sans quoi le bloc de
  bits ne vaudrait pas mieux qu'un comptage.

**MESURÉ le 2026-09-11 — les bits sont CÂBLÉS mais PAS EXPLOITÉS, aux DEUX sous-états.**
`scripts/split_assigned_policy_probe.py` sur le modèle promu à 110 000 épisodes (P2, obs 18269),
12 graines des scénarios d'entraînement, distance de variation totale sur la distribution
d'actions restreinte aux actions légales. Moyennes :

| Perturbation | ARME (6 pts) | CIBLE (10 pts) |
|---|---|---|
| PLANCHER — la même observation contre elle-même | 0,000000 | 0,000000 |
| SPLIT — la cible déjà assignée change | **0,000473** | **0,000969** |
| RÉFÉRENCE — étalon propre au sous-état | 0,040231 | 0,620877 |
| SATURATION — bloc ennemi continu à zéro | 0,037428 | 0,543887 |

Médianes de SPLIT : 0,000187 (ARME) et 0,000007 (CIBLE).

**L'étalon est PROPRE À CHAQUE SOUS-ÉTAT, et c'est ce qui rend le tableau lisible.** Au choix de
cible, les actions légales désignent des escouades ennemies : la RÉFÉRENCE y fait échanger leurs
caractéristiques aux deux cibles. Au choix d'arme, elles désignent des slots de profil
(`SHOOT_WEAPON_SEL_SLOT_j`), qui ne portent aucune identité de cible : la RÉFÉRENCE y fait
échanger deux profils de tir de l'escouade observatrice. Une première version de cette mesure
appliquait l'étalon de CIBLE aux deux sous-états ; il y tombait à 0,001 et faisait conclure à tort
que « la politique est insensible au bloc ennemi tout entier » — c'était l'étalon qui était muet,
pas la politique, et la SATURATION à 0,037 le montrait déjà.

**Des deux côtés, les bits pèsent un à deux ordres de grandeur sous un champ dont la décision
dépend** : 85 fois moins que la référence au choix d'arme, 640 fois moins au choix de cible, avec
une médiane à 7 × 10⁻⁶ qui est le plancher numérique. Les perturbations ne sont pas de même
ampleur en entrée — dix bits contre des lignes entières — donc ces rapports ne se lisent pas comme
des facteurs exacts ; ce qui se lit, c'est l'écart d'ordre de grandeur, identique dans les deux
décisions.

**Ce qui borne le gain possible :** sur 156 points d'arrêt rencontrés, **109 n'ont qu'UNE action
légale** et 31 de plus n'offrent aucune autre cible éligible pour l'arme déjà assignée — 16 sont
mesurables, soit 10 %. Le masque des points mesurés est étroit (médiane 2 actions légales,
maximum 5), donc les TVD ne sont pas diluées par des actions sans rapport.

Le bras témoin (même run sans les bits, pour comparer les win-rates) n'a **pas** été lancé : à
l'écart constaté au choix de cible, et faute d'étalon lisible au choix d'arme, aucun décalage de
win-rate ne serait attribuable aux bits.

**Ce qui reste non tranché :** que les bits soient inutiles POUR TOUJOURS. La mesure porte sur une
étape de lignée à 110 000 épisodes et sur deux rosters ; elle ne dit pas ce qu'il en serait à un
horizon plus long, ni sur un roster où le tir fractionné offrirait plus souvent un vrai choix.

---

## 🔴 Plafonnement P1 contre P0 — dossier de synthèse {#plafonnement-p1}

**Ouvert le 2026-09-13.** `Documentation/Chantiers/backlog/plafonnement_p1.md`
rassemble le symptôme mesuré (sondes, courbes par quart, holdouts), la chronologie du
2026-09-11 au 2026-09-13 et ses antécédents P2, l'inventaire des causes possibles et des
solutions avec leur statut, et l'arbitrage en attente (§7 du dossier). Les mesures de détail
restent dans les sections ci-dessous ([#entropie-normalisee](#entropie-normalisee),
[#signal-p1-2026-09-13](#signal-p1-2026-09-13), [#holdout-2026-09-13](#holdout-2026-09-13),
[#run-s23-2026-09](#run-s23-2026-09)) ; toute nouvelle mesure s'ajoute aux deux endroits.

**Relecture du 2026-09-14 soir — [dossier §9](../Chantiers/backlog/plafonnement_p1.md#relecture-2026-09-14).**
Faits manqués retrouvés dans `curriculum.log` : P1 sous `x1_lineage` à **0,713** contre P0 avant
les correctifs moteur du 09-10, 0,563 après, seuil passé à 0,65 le jour même ; le zip P0 porte
lr 0,0005 et `x1_lineage` reprend à 0,001 ; le protocole à une graine ne voit pas un effet de
5 points (`vf_coef` 0,3 requalifié « nul dans le bruit »). **Décision utilisateur : 0,65 est un
seuil de confirmation, le plafond attendu contre P0 est ~0,90 ; « plateau normal » écarté.**
Plan : mesures statiques par siège (S27) → exploiteur de P0 meilleur cas sur agent dédié (S25 :
lr 0,0005, P0 déterministe, siège 0,5, 100 % P0) → leviers de mécanisme dans ce dispositif, deux
graines sous 10 points d'effet ; B6 après, sur deux graines.

**2026-09-16, 11:20 — trois champions à froid en duel ([dossier §11](../Chantiers/backlog/plafonnement_p1.md#ligue-2026-09-16)).**
300 parties par case, argmax, sièges 50/50 : **P0 → P0a 0,42** (la première tentative de P0, 0,83
contre les bots, bat le champion retenu à 0,58, ≈ 2,7 σ), P0 → témoin entnorm 0,57, P0a → entnorm
0,55 ; ordre P0a > P0 > entnorm sans cycle. Le score contre les bots, qui désigne le champion, ne
classe pas les agents entre eux ; trois départs à froid du même pipeline sont trois agents
distincts, la diversité pour un pool de P1 existe déjà sur disque.

**2026-09-16, 10:15 — pénalités ventilées (C5 fermé) et ligue d'adversaires ([dossier §11](../Chantiers/backlog/plafonnement_p1.md#ligue-2026-09-16)).**
Le poste `reward/penalties_total` (−112 / épisode) est le miroir défensif du façonnage de combat
(dégâts subis, figurines perdues, escouades détruites) + cohérence, attente, charge ratée, réserves
perdues : bonus / pénalités = 198 / 111 = 1,78 contre un rapport valeur détruite / perdue de 1,77
dans les parties — symétrique, pas contradictoire. Ligue : déjà dans le design dès P2 (champion +
ancients + exploiters, poids fixes) ; le pool d'un membre de P1 n'est pas la cause du plafond (S25
et S9 : même pool, +10 pts par l'exploration) mais celle de la non-généralisation (matrice) ; deux
champions indépendants chargeables sur disque (`robust_0.8314`, témoin entnorm), pas d'instantanés
intermédiaires de P0 (rotation 3). Minimum viable à ouvrir après B : membres externes dans le pool
de P1, rétention des checkpoints, poids adaptatifs.

**2026-09-16, 09:45 — B : régime S9 transféré dans la lignée, P1 relancé ([dossier §5.15](../Chantiers/backlog/plafonnement_p1.md#b-2026-09-16)).**
Décision utilisateur « B avec les deux clés » : `x1_lineage` de `ArmageddonAgent_x1` passe à
`learning_rate` **0,0005** et `logits_temperature` **2,0** (merge `3ef821284`, test épinglé
rouge/vert), adversité de lignée inchangée (siège 0,7, bots 30 %, P0 échantillonné). Règle écrite
avant : promotion automatique à 30 000 (trois sondes ≥ 0,65) → P2 enchaîne ; 0,60–0,65 → courir,
arrêt manuel à 60 000 ; < 0,55 → arrêt, « le protocole perd le gain » → D puis bissection. Au gate :
matrice hors entraînement et score par siège obligatoires. Run de nuit choisi au gate (C si B
passe, D sinon). Log `training_x1_06-p01-s9.log`. En tête du dossier, « En clair » réécrit au 16.

**2026-09-16, 08:45 — point de reprise ([dossier ÉTAT AU 2026-09-16](../Chantiers/backlog/plafonnement_p1.md#etat-2026-09-16)).**
Réponses consignées aux questions du 16 (P0 ne plafonne pas contre les bots : 0,695 → 0,779 → 0,868 ;
l'hypothèse « plafond introduit par les commits » est affaiblie par le 0,78 de S9 sur le code actuel ;
cause mesurée = exploration absente en reprise). Décisions ouvertes : GPU (A poids de la victoire sous
T / B transfert lignée, risque : siège 0,7, bots 30 %, lr 0,001, P0 échantillonné / C P0 neuf à froid /
D seconde graine de S9) ; mécanisme d'exploration non absorbable : mélange aléatoire à la collecte
contre température autorégulée, à comparer par écrit avant code. Liste datée de ce qui est sain et de
ce qui ne l'est pas.

**2026-09-16, 08:30 — S9, manière de gagner ([dossier §5.14](../Chantiers/backlog/plafonnement_p1.md#s9-2026-09-15)).**
Blocs 40 000–50 000, S9 / S25 : VP de l'agent 48,7 / 47,8 mais VP de P0 **36,4 / 41,3** — la marge vient
du déni des points adverses ; victoires en déploiement actif 0,78 / 0,68, en déploiement moteur 0,49 /
0,45 ; combat identique (ratio de valeur 1,77 / 1,76, S9 perd un peu plus de figurines 0,31 / 0,26) ;
S9 gagne surtout en premier joueur (0,72 / 0,59 cumulés, S25 0,66 / 0,66).

**2026-09-16, 08:00 — clôture S9, poids finaux mesurés ([dossier §5.14](../Chantiers/backlog/plafonnement_p1.md#s9-2026-09-15)).**
Processus terminé à 07:54 (curriculum.log ligne 17 : E0, 60 000, budget censuré) ; évaluation finale
90,3 % contre les bots, holdout 0,902 à 60 000. Matrice des poids finaux : P1 **0,64**, S25 (30 000)
**0,69**, témoin entnorm **0,71** (S25 0,70, P0 ≈ 0,72) — conclusion du 30 000 confirmée, gain propre à
la famille de P0, nul contre le style sans parenté. Sonde par famille à 60 000 : plus pointue sur
mouvement / activation / déploiement, plus plate sur cible de tir, choix d'arme, oath, wait ;
charge effondrée des deux côtés. GPU libre, rien lancé sans décision.

**2026-09-16, 07:20 — S9 TERMINÉ à 60 000 : plateau déplacé de ~0,68 à ~0,78, plat depuis 40 000 ([dossier §5.14](../Chantiers/backlog/plafonnement_p1.md#s9-2026-09-15)).**
Fenêtres de six sondes 0,730 / 0,760 / **0,783** / **0,767** (S25 : 0,677 / 0,683) ; onze sondes à 0,778
depuis 40 001. Holdout bots 0,922 à 50 000, instantané robuste 0,9072 (canonique = instantané holdout,
poids finaux = dernier `ppo_checkpoint`, copiés dans `logs/matrix_heldout_20260916/s9_final_ckpt/`).
Entropie de π_T 1,07 → 0,80 → 0,76 → **0,72** à 60 000 (S25 à T = 1 : 0,69) : T est absorbé, et la sonde a
cessé de monter quand le surplus d'exploration est passé sous ~0,05 nat. Établi : la collecte
exploratoire extrait +10 pts de P0 (une graine) ; non établi : que 0,90 soit atteignable par T — le
levier suivant est un mécanisme d'exploration que l'optimiseur ne peut pas défaire, à arbitrer
avec la suite (étape 3 sous T / étape 4 transfert / contrôle P0 à froid). Sonde par famille et
matrice hors entraînement des poids finaux en cours.

**2026-09-16, 04:05 — S9 lecture à 40 000 : la montée continue ([dossier §5.14](../Chantiers/backlog/plafonnement_p1.md#s9-2026-09-15)).**
Sondes 30 000 → 40 000 : 0,78 / 0,73 / 0,75 / 0,75 / 0,76 / 0,79 → moyenne **0,760** (règle du 02:30 :
≥ 0,76 → montée, à la borne exacte ; fenêtre précédente 0,730 ; S25 même fenêtre 0,683). Holdout bots
**0,907** (P0 0,910), pire bot 0,86 : aucune dégradation. Mécanisme inchangé depuis 20 000 (coupure KL
15–17 comme S25, EV 0,88, entropie de π_T 0,76 → 0,73). Prochaine lecture à 60 000, fin de budget E0.

**2026-09-16, 02:46 — S9 généralise hors de P0 ([dossier §5.14](../Chantiers/backlog/plafonnement_p1.md#s9-2026-09-15)).**
Matrice d'adversaires jamais affrontés (`scripts/seat_matrix_probe.py`, 300 parties, argmax, sièges
50/50) sur les checkpoints 30 000 : contre P1 de lignée `robust_0.9078`, P0 fait 0,36, S25 **0,50**,
S9 **0,62** — +12 pts pour S9 hors de P0 contre +5 pts sur P0 : le gain n'est pas une spécialisation
contre le champion. Matrice complète à 03:10 : S9 → S25 **0,68** ; contre le témoin entnorm sans parenté avec P0, S9 0,68, S25 0,70, P0 ≈ 0,72 (bruit) — le gain est réel mais **propre à la famille de P0**, nul contre un style étranger : ni spécialisation contre le seul champion, ni progrès général mesurable ; il manque un juge de progrès général (second champion sans parenté, témoin entnorm en cellule fixe).

**2026-09-16, 02:25 — S9 : VERDICT À 30 000 = OUI, le plateau est déplacé ([dossier §5.14](../Chantiers/backlog/plafonnement_p1.md#s9-2026-09-15)).**
Sondes exploiteur 20 000 → 30 000 : 0,80 / 0,72 / 0,69 / 0,68 / 0,71 / 0,78 → moyenne **0,730** contre
0,677 (S25, même fenêtre ; règle 2b ≥ 0,72). +5,3 pts ≈ 2 σ (erreur-type d'un écart de fenêtres
≈ 2,7 pts) : deux graines exigées au transfert (§9.3), pas à la lecture. **Holdout bots 0,893 à
30 000** (P0 0,910, S25 0,923) : pas de spécialisation visible, pas de progrès contre des bots
saturés. Mécanisme : entropie de π_T 0,80 → 0,76 (pente −0,04 nat / 10 000, 0,68 non atteint),
coupure KL revenue à 15–16 mini-lots comme S25, `a_vp_diff` +10,5 (S25 +4). **Sonde par famille
à T = 1 (checkpoints 30 000 de S9 et S25)** : S9 est PLUS pointue que S25 sur toutes les grandes
têtes (move 1,47 contre 2,23 nat, charge 0,07 / 0,14) avec des argmax différents dans 72 % des
états de mouvement — le réseau a absorbé T en affûtant ses logits, l'exploration qui a fait le
résultat vit dans la collecte π_T, pas dans π. Le run continue à 60 000 (`budget_cap` E0) ;
règle de lecture à 40 000 / 60 000 écrite dans le dossier avant les données (≥ 0,76 montée ;
0,70–0,76 tenu ; < 0,70 bruit → seconde graine).

**2026-09-16, 00:45 — S9 lecture à 20 000 ([dossier §5.14](../Chantiers/backlog/plafonnement_p1.md#s9-2026-09-15)).**
Sondes exploiteur 2 000 → 20 000 : 0,53 / 0,59 / 0,56 / 0,66 / 0,68 / 0,62 / 0,67 / 0,76 / 0,67 /
**0,80** (S25 à 20 000 : 0,68) ; garde passée à 10 000 (0,604 contre 0,536). Entropie de π_T
1,07 → 0,80 nat puis **plate depuis 14 000** (S25 : 0,78 → 0,68) : T est absorbé en partie,
la règle d'absorption (retour à 0,68) n'est pas déclenchée. Coupure KL 16 mini-lots (S25 14–15),
`a_vp_diff` +8 (S25 +4) sur les courbes échantillonnées. **Holdout bots 0,897 → 0,848 à 20 000
(S25 : 0,933)**, pire bot 0,80 : l'exploiteur recule contre les bots pendant qu'il monte contre
P0. Verdict à 30 000 par la règle 2b, rien n'est arrêté.

**2026-09-15, 20:34 — S9 lancé, S14 définitivement clos ([dossier §5.14](../Chantiers/backlog/plafonnement_p1.md#s9-2026-09-15)).**
Température des logits `logits_temperature` (collecte ET ratio sous π_T, hors zip, T = 1 en
évaluation) codée et mergée (`571b0732f`, 8 tests). Mesure 2a (tête Q sur données exploratoires
à T = 2, politique figée 40 updates) : gap hors échantillon **+0,0025 ± 0,001** → la tête Q ne
prédit rien de plus que V même avec des coups alternatifs ; S14 ne sera plus relancé (S15,
recherche par simulation, non touché). Run S9 `run_20260915-203437` (`training_x1_expl_05-e00-s9.log`)
depuis P0, règle §5.14 2b : garde 10 000, absorption sur `train/entropy_loss`, verdict 30 000
contre 0,677 ; `03_selfplay/P0` n'est pas un juge sous T.

**2026-09-15 soir — S14 RÉFUTÉ ([dossier §5.13.1](../Chantiers/backlog/plafonnement_p1.md#s14c-2026-09-15)).**
Run non centré (`run_20260915-134839`) disqualifié par audit (94 % de Var(A) = constante par
état, mesuré par `scripts/q_head_structure_probe.py`) ; centrage sous π codé et mergé
(`5288f3921`) ; rerun centré (`run_20260915-155352`) : garde déclenchée à 10 000 (0,362),
`q_loss_mb0 − value_loss_mb0` jamais négatif, entropie 0,71 → 0,28 nat, coupure KL à 6/32 —
la tête Q n'a pas de données contrefactuelles (politique à p_max 0,66–0,99), variante S14c
écartée sans run. Suite (§9.9) : **S9** température de collecte T = 2 sous GAE, précédée d'une
mesure de 30 min (tête Q sur données exploratoires, politique figée : `q_loss_mb0 −
value_loss_mb0 < −0,002` → S14-sur-S9 rejouable, sinon S14 mort).

**2026-09-15 — verdict S25, S14 lancé, ordre de la suite figé ([dossier §9.9](../Chantiers/backlog/plafonnement_p1.md#suite-2026-09-15)).**
S25 (exploiteur de P0 meilleur cas, `run_20260914-215728` + reprise `run_20260915-123205` après
un reboot Windows à 04:29) : sondes exploiteur 0,61 / 0,63 / 0,75 / 0,62 / 0,77 / 0,72 sur
30 000–40 000, moyenne **0,683** contre 0,677 sur 20 000–30 000 → **stagnation** par la règle du
03:10 : le mécanisme plafonne même dans le meilleur cas (+9 pts sur P1, puis même signature
d'update : coupure KL 15–16 sur 32, entropie plate). Holdout bots 0,933 à 20 000 (aucune
suradaptation). **S14 — tête Q d'avantage attendu — codée cette nuit (décision utilisateur
01:48), corrigée de ses deux findings de review et mergée le 2026-09-15** ([dossier
§5.13](../Chantiers/backlog/plafonnement_p1.md#s14-2026-09-15)) : `adv_heads` sur le tronc
critic, `Q = V.detach() + A` régressée sur le retour λ, l'acteur reçoit `A(s_t, a_t).detach()`
à la place du GAE, V garde sa cible ; clés `advantage_source` / `q_coef`, échauffement exigé
et jamais sauté sur une tête jamais entraînée ; zips antérieurs chargés par tous les chemins
(`MaskablePPO.load` nu compris). **Run S14 lancé dans le dispositif S25** (agent expl, E0,
`q_coef` 0,17) ; règle de lecture écrite avant : garde à 10 000, verdict à 30 000 sur la moyenne
20 000–30 000 contre 0,677 (≥ 0,72 oui, 0,64–0,72 réfuté, ≤ 0,63 régression). **Ordre figé** :
S14 → S9 (température, code) seulement si S14 réfuté → C2 / B6 seconde graine → transfert dans
`x1_lineage` avec relecture de lr / `target_kl` sous le nouvel estimateur → S11b / S15 en
dernier recours. Bissection de config suspendue ; gate 0,65, S23, `vf_coef`, S11, entnorm clos.

### Run S23 — λ 0,2 + rollout 32 640 / lot 2 040 — RÉFUTÉ (nuit du 2026-09-13 au 14) {#run-s23-2026-09}

Commande habituelle `--etape P1` sous `x1_lineage` (`gae_lambda` 0,2, `n_steps` 32 640,
`batch_size` 2 040, commit `5744e9d66`). Cinq lancements : trois tués par le watchdog RAM à 24, 16
et 12 envs (1, 2, 2 Go disponibles sur 39 — le coût RAM d'un rollout est proportionnel au rollout
**total** : chaque worker garde sa trajectoire, le learner en tenait trois exemplaires), un
correctif de collecte (`a59ff5a61` : tableaux préalloués côté worker, `iter_trajectories` côté
learner, verrou par mutation), puis le run jugé à 8 envs (`run_20260914-004747`, min 7 Go). Résultat
sur 8 340 épisodes d'étape / 26 updates : `03_selfplay/P0` **0,50 → 0,41** par tranche de 1 000,
monotone (référence 0,51 sur la même fenêtre), `win_rate_overall` 0,61 → 0,57, VP diff 5,4 → 2,
pendant que `explained_variance` monte à 0,98 et `value_loss` baisse. Lecture : λ change la **cible
du critic** (retours = avantages + valeurs) ; la prédiction f ≈ 0,18 supposait le critic fixe. Arrêté
par l'utilisateur à 02:22 (fenêtre < 20 000 : verdict sur la monotonie, pas par la règle). Profil
ramené au régime de référence (`467eff961`). Détail, tableau par tranche et série mémoire :
dossier §5.9. **Essai `vf_coef` 0,3 (02:36 → 10:26, `run_20260914-023713`) RÉFUTÉ** : par fenêtre
d'étape 0,509 / 0,519 / 0,572 / 0,577 / 0,585 contre 0,508 / 0,571 / 0,601 / 0,592 / 0,585 en
référence — même plateau, atteint plus lentement ; 0,17 rétabli (dossier §5.10). **Run S11 depuis
10:30** (`training_x1_05-p01-s11.log`) : récompense de tir et de mêlée sur l'espérance du choix
(`squad_shaping.reward_on_expectation`, `expected_attack_pool_damage` = espérance exacte du roller,
Monte-Carlo verrouillé), profil de référence. **ARRÊTÉ par la garde à 20 000 (`run_20260914-103745`)** :
sondes argmax 0,450 / 0,497 (moyenne 0,473 < 0,50) alors que la courbe échantillonnée est à 0,538 /
0,549 (référence 0,508 / 0,571) et que l'entropie MONTE (−0,78 → −0,85, référence −0,78 → −0,72).
Hypothèses et sondes à faire : dossier §5.11. Clé remise à `false`. Suivant : marge de VP B6 (§5.12).

### Marge de VP en ledger + échauffement du critic — B6, mergé, run à lancer {#marge-vp-2026-09}

**Décision utilisateur du 2026-09-14.** `objective_reward_factor × VP_propres` (versé au tour
du joueur contrôlé) devient `vp_margin_factor × Δ(VP_moi − VP_lui)`, versé à chaque changement
de score, quel que soit le joueur dont c'est le tour (`BotControlledEnv` accumule). Somme
téléscopique = 6 × marge finale, élimination comprise ; un VP concédé coûte désormais −6 (0
avant). Remplacement et non ajout : Corr(ΔVP_moi, Δmarge) = 0,82 sur 40 parties, les deux
termes ensemble auraient valu +11 / −5. Nouveau composant de ventilation `vp_margin`
(`reward/vp_margin_total`, `objective_share` = part de score, `01_VP/f_obj_rewards` = 6 × marge).
Le critic ayant appris une cible qui ignorait les VP cédés, la reprise s'ouvre par
`model_params.value_warmup_updates` updates où seule la value loss est optimisée (politique et
entropie annulées, KL désactivé, `train/value_warmup_active`) — régime de run, jamais hérité
d'un checkpoint (ni la clé ni le compteur ne voyagent dans le zip ; seul le profil l'active).
Décision B (2026-09-14) : la clé restant dans `x1_lineage`, le zip retient sous quelle table de
récompense le dernier échauffement s'est achevé (`value_warmup_done_under`, empreinte clés +
valeurs de `training_contract.reward_table_fingerprint`), et `arm_value_warmup` (ai/train.py)
SAUTE l'échauffement (`value_warmup_updates` remis à 0 sur le modèle, journalisé) quand le profil
le redemande sous la même table : `--append` d'étape suivante et `--resume-from` après crash
passent sans toucher au profil. Le refus `ValueError` du matin est retiré le soir même (review) :
il bloquait la reprise d'un run planté après la 20e update tant que la clé restait dans
`x1_lineage`.
Reviews du 2026-09-14 : l'extracteur étant PARTAGÉ (`PointerMaskablePolicy`), tout ce qui n'est
pas le critic (`mlp_extractor.value_net` + `value_net`) est GELÉ pendant le warmup — paramètres
(`grad = None`) ET statistiques d'`EntityRunningNorm` (`eval()`), sinon la value loss déplaçait
la politique via l'extracteur ; `SelfPlayWrapper` accumule désormais chaque step de P2 comme
`BotControlledEnv` (le ledger était perdu sur le chemin self-play pur) ; la porte « pool vide →
advance_phase » du moteur passe par `calculate_reward` (le dernier delta du ledger et le
±situational y étaient perdus quand la transition terminait la partie) ; format de save bumpé
en `W40KTL10` (`vp_margin_paid`). **Mergé dans main le 2026-09-14** (S11 arrêté), puis
préparé : contrat du snapshot P0 réécrit (archive `_pre_b6_20260914`), `value_warmup_updates:
20` dans `x1_lineage` (≈ 1 440 épisodes). **Reste : lancer le run « marge »** par la commande
habituelle `--etape P1`, jugé par la règle §7. Détail, tests et mutations constatées : dossier
§5.12.

---

## 🟡 Entropie normalisée par l'état — contrôle vs traité mesurés, arbitrage ouvert {#entropie-normalisee}

**Code livré le 2026-09-12 ; deux runs terminés le 2026-09-13 (résultats en fin de section) ; reste à trancher : second run traité ou clôture.** Décision utilisateur
du 2026-09-13, option B deux fois : normalisation **par l'état** plutôt qu'un poids d'entropie par
phase ; **témoin même code** plutôt que P0 du 2026-09-10, invalide comme témoin (70 commits
moteur/IA depuis, dont overrun 12.06 et New Foes sur le chemin gym).

**Cause mesurée le 2026-09-12** (sonde 6 épisodes, 1 301 décisions) : `train/entropy_loss` est une
moyenne en nats dominée par `move_cell` (194 actions légales en moyenne, ln n moyen 5,07, H 2,23)
alors que `charge_slot` vaut 0,007 nat sur 0,86 possible, `shoot_slot` 0,23 / 1,58, `deploy_slot`
0,16 / 1,95, `oath` 0,11 / 1,59, `fight_weapon_slot` 0,17 / 1,35 ; `ent_coef` 0,01 pèse 1,3 % du
gradient (`diag/grad_share_*_mb0`) et n'agit que sur le mouvement.

**Mécanisme** (`ai/patched_ppo.py`, site unique du terme d'entropie) : clé `model_params`
`entropy_normalize_by_legal`, acceptée par le constructeur de `PatchedMaskablePPO`, sérialisée
dans le zip et reposée en `--append` (`_PLAIN_CURRICULUM_KEYS`, `ai/train.py`). Active : le terme
de loss devient `−mean_i(H_i / ln n_i)` sur les échantillons à `n_i > 1` (`n_i` = somme du masque),
borné dans [−1, 0] ; aucun `n_i > 1` → terme nul relié au graphe ; entropie `None` → lève.
Absente : terme strictement inchangé. `train/entropy_loss` reste la moyenne brute ;
`train/entropy_loss_normalized` est publié au même dump sur **tous** les runs
(`Documentation/Reference/training/metriques.md`). `diag/grad_norm_entropy_mb0` porte le terme
réellement optimisé. Verrous : `tests/unit/ai/test_entropy_normalize_by_legal.py` (16 tests,
rouge/vert par mutation sur les cinq défauts réintroduits).

**Config** : `config/agents/ArmageddonAgent_x1_entnorm/` = copie complète de
`config/agents/ArmageddonAgent_x1/` (`inherits_from` inutilisable : `config_loader.py` résout
**tout** vers l'agent de base, profils compris), fichiers et clé de récompense renommés.
`x1_long` inchangé (verrou : égal au `x1_long` de base). Bras de **contrôle** `x1_40k`
(`extends: x1_long`) : **40 000** épisodes et `bot_eval_intermediate` 30, rien d'autre — décision
du 2026-09-12 : sur P1 la stagnation se lit en 30 à 40 000 épisodes (sonde vs P0 0,547 → 0,601
entre 60 000 et 120 000, plateau sous 0,65), et 100 000 par bras aurait coûté ~25 h ; les rampes
sont en fraction du run (entropie → 16 000, learning rate → 36 000), `bot_eval_final` 300 garde
la précision publiée. Ces bras se comparent **entre eux**, jamais à la référence `x1_long` 100k.
`x1_40k_entnorm` (`extends: x1_40k`) = bras **traité** : clé active + `ent_coef` {0,5 → 0,05,
`decay_fraction` 0,4}, soit ×5 ≈ ln n moyen du mouvement : pression inchangée sur les états de mouvement
(5/5,07), relevée de 5/ln n sur les têtes courtes (charge ×5,8, shoot ×3,2, deploy ×2,6, oath ×3,1,
fight ×3,7). Aucun JSON existant de `config/` n'est modifié (P1 en cours). La copie est un
**bras d'expérience** : à supprimer ou à réabsorber à la clôture, jamais à faire diverger.

**Instrument de lecture** : `scripts/family_entropy_probe.py` — table H_A / H_B / ln n / KL(A‖B)
par famille d'action sur les mêmes états (échantillonnés par A), plancher = politique UNIFORME
(logits à zéro sur la vraie architecture, H = ln n exactement, `--floor-tol` 0,01, code 2 sinon).
Vérifié le 2026-09-12 : plancher tenu sur les cinq familles visitées. Mesuré au passage : une
politique **neuve** n'est PAS uniforme sur les têtes pointées (`shoot_slot` 0,45 / 1,10,
`shoot_weapon_sel_slot` 1,04 / 1,39, `deploy_slot` 1,76 / 1,95) — d'où le plancher uniforme et non
« non entraînée ». Verrous : `tests/unit/scripts/test_family_entropy_probe.py`.

**Runs (P1 arrêté le 2026-09-12 à 70 000 épisodes d'étape sur décision utilisateur — plateau ;
un seul run GPU)**, enchaînés par une chaîne détachée (`logs/entnorm_chain.log`) :
1. Contrôle : `python3 ai/train.py --agent ArmageddonAgent_x1_entnorm --training-config x1_40k --scenario bot --resolution 1 --new`
2. Traité : `python3 ai/train.py --agent ArmageddonAgent_x1_entnorm --training-config x1_40k_entnorm --scenario bot --resolution 1 --new` — ce second `--new` **écarte** les artefacts du contrôle sous horodatage (`archive_canonical_artifacts_for_new_run`) : noter le nom archivé, c'est le modèle final du contrôle.

Sur les deux : `diag/grad_norm_entropy_mb0`, `diag/grad_share_policy_mb0`, `train/n_minibatches_done`,
`train/entropy_loss` (brut), `train/entropy_loss_normalized`.

**Critère de clôture** : deux runs terminés ; métrique décisive = win-rate holdout final contrôle
vs traité (300 ép./bot, IC95 ±5,7 par bras) et `00_critical/s_win_rate_deploy_auto` (bruité :
12,5 % des épisodes en fin de run sur fenêtre 100) ; table H / KL par famille des deux modèles
finaux ; écart rapporté **avec son intervalle** — un run par bras ne mesure pas la variance
entre entraînements, jamais un verdict sur un point. Écart holdout < ~10 points → proposer le
second run traité (option C), ne pas conclure.

**RÉSULTATS du 2026-09-13** (contrôle 22:04 → 04:07, traité 04:07 → 09:48, même code
d'apprentissage — seuls `ai/{train,model_artifacts,training_contract,curriculum}.py`, artefacts et
contrat, diffèrent entre les deux départs, `2265c2d63` → `096ff93a2` ; contrôle archivé
`model_ArmageddonAgent_x1_entnorm_20260913-040721.zip`, traité = canonique).

| mesure | contrôle `x1_40k` | traité `x1_40k_entnorm` |
|---|---|---|
| **holdout final, 6 bots × 300** | **87,5 %** | **87,9 %** (écart +0,4 pt ; IC95 de l'écart ≈ ±2,2 pt) |
| par bot (±5,7) | alpha 90,7 · attrition 84,3 · decapitation 90,0 · endgame 91,3 · racer 82,0 · scorer 86,7 | 91,7 · 85,7 · 93,3 · 91,0 · 82,0 · 83,7 |
| bot_eval intermédiaire (30 ép./bot, ±7 pt) à 10k / 20k / 30k / 40k | 0,672 / 0,750 / 0,767 / 0,856 | 0,556 / 0,772 / 0,856 / 0,879 |
| `s_win_rate_deploy_auto`, 50 derniers points | 0,574 | 0,528 |
| `d_win_rate` (entraînement), 50 derniers | 0,788 | 0,766 |
| `train/entropy_loss` (brut), 50 derniers | −0,79 | −1,07 |
| `train/entropy_loss_normalized`, 50 derniers | −0,47 | −0,70 |
| `diag/grad_norm_entropy_mb0`, 50 derniers | 0,0062 | 0,0139 |
| `diag/grad_share_policy_mb0`, 50 derniers | 0,66 | 0,64 |
| `train/n_minibatches_done` moy (plan 32) | 15,2 (13,4 → 18,2 par quart) | 15,9 (17,8 → 18,0) |
| `train/approx_kl_max` > 0,0225 | 590/590 updates | 588/588 |

**Table H / KL par famille** (`logs/entnorm_probe.log`, 6 épisodes échantillonnés par le traité ;
H en nats, H_max = ln n) — traité / contrôle : activate_slot **0,90 / 0,41** (1,12), shoot_slot
**0,77 / 0,34** (1,30), shoot_weapon_sel_slot **0,85 / 0,36** (1,35), oath **1,00 / 0,60** (1,64),
charge_slot **0,24 / 0,05** (0,80), fight_weapon_slot 0,45 / 0,25 (1,08), wait 0,75 / 0,23 (1,20),
deploy_slot 0,29 / 0,36 (1,95 — figé dans les deux bras), move_cell **3,00 / 2,28** (5,14) ;
argmax différents sur 49–86 % des états selon la famille.

**Lecture.** Le mécanisme fait ce qu'il devait sur l'entropie : les têtes courtes du traité
hésitent 2 à 5 fois plus que celles du contrôle, et `entropy_loss_normalized` reste à −0,70 contre
−0,47. Deux écarts avec le plan : le mouvement explore AUSSI davantage (3,00 contre 2,28, alors que
la pression y était calculée inchangée), et `deploy_slot` reste figé dans les deux bras. Sur la
métrique décisive, **aucun effet mesurable** : +0,4 pt de holdout, dans le bruit ; les deux
politiques sont très différentes (KL 1,5–8 nat par famille), ce qui est attendu de deux
entraînements indépendants et ne dit rien du régime. L'early-stop KL coupe toujours chaque update
dans les deux bras (~15 pas de gradient sur 32). Conformément au critère : écart < 10 points →
**pas de verdict** ; la variance entre entraînements n'est pas mesurée. Réserve d'interprétation :
le holdout bots est proche de sa saturation (90 % de référence, 87,5–87,9 ici), alors que le
plateau de P1 se mesurait contre P0 dans le pool de lignée — une métrique que ces bras ne
produisent pas.

---

## 🔴 Régime de lignée — option A livrée, P2 à relancer depuis P1 {#regime-lignee-2026-09-07}

**Livré le 2026-09-07. Ce qui reste à faire : lancer P2.** Trois runs P2 successifs ont échoué en
faisant varier des hyperparamètres étape par étape ; l'option A supprime cette possibilité au lieu
de chercher les bonnes valeurs pour chaque étape.

**1. Un PROFIL de lignée, `x1_lineage`, appliqué à TOUTE étape `init: "from:"`** — les dix
learners comme les trois exploiteurs. `learning_rate` 0.001 et `ent_coef` 0.03 **scalaires**,
`n_steps` 32640, `vf_coef` 0.15, `agent_seat_p2_ratio` 0.6 ; tout le reste, `batch_size` 1020 et
`max_grad_norm` 0.5 compris, est **hérité** de `x1_long` par `"extends"`. `batch_size` a d'abord
été surchargé à 4080 pour garder huit mini-lots ; il est rendu à l'héritage le 2026-09-07, ce
mini-lot ayant fait mourir P2 à sa première update par saturation de VRAM (pic 8,89 Go sur 8,19). Les vingt rampes
`decay_fraction` des étapes disparaissent, ainsi que les surcharges de `vf_coef` /
`max_grad_norm` de P2 et P3 ; une étape reprise ne déclare plus que `total_episodes`, et le
validateur refuse le reste. `x1_long` garde ses rampes et son `vf_coef` 0.5 pour le seul départ à
froid P0.

**Deuxième version, le 2026-09-07 même.** Le premier jet portait ces valeurs dans un bloc
`lineage_regime` du curriculum. Il les dispersait sur deux fichiers avec une règle de précédence à
connaître pour répondre à « quel `learning_rate` utilise P5 », là où le dépôt exprime déjà « un
autre régime » par « un autre profil » — six fois dans le même fichier. Le bloc est remplacé par
un profil, et le curriculum ne porte plus que les deux **noms**, dans `training_configs`
(`cold_start` / `lineage`). `ai/train.py::_prepare_curriculum_stage` **refuse au lancement** un
`--training-config` qui ne correspond pas à la nature de l'étape ; le mécanisme d'héritage vit
dans `config_loader::_resolve_profile_extends`. Détail chiffré et mesures :
`Documentation/Reference/training/entrainement.md`, section « Rampes ».

**2. `P00` supprimée, `P0` passe en `init: "new"`, E1/E2/E3 passent en `init: "from:P0"`.** La
graine n'existait que pour éviter de repayer un warmup à chaque learner, ce que le chaînage a rendu
sans objet. Les exploiteurs ne partent plus des poids de leur cible : ils en étaient une copie à
qui l'on demandait de trouver sa propre faiblesse, donc ils commençaient à la parité par
construction et ne pouvaient s'en écarter qu'en désapprenant.

**3. Contrôle de continuité à l'ouverture.** `_pin_entropy_ramp_for_warm_start` est supprimé avec
les rampes qu'il corrigeait ; à sa place, `announce_lineage_continuity` lit `ent_coef` et
`learning_rate` dans le zip repris et annonce tout écart avec le bloc. Il n'en corrige aucun.

**4. Verrou de parité, qui ARRÊTE le run.** À l'épisode 0 d'une étape reprise, le modèle **est**
l'archive dont il reprend les poids : son score contre elle vaut 0.50 par identité. La baseline de
`PoolEarlyStoppingCallback` la mesure ; hors de `[0.40, 0.60]`, le run est refusé **avant le
premier épisode**. Les 2026-09-04 et 2026-09-05 ont chacun produit des heures d'entraînement sur
une baseline aberrante (0,477 puis 0,118) lue comme une mesure.
Il ne se pose qu'à `_stage_episode() == 0`, et pas sur la seule origine du compteur : après un
`--resume-from <checkpoint>` de reprise sur crash, l'origine reste celle de l'archive source alors
que le modèle a joué des milliers d'épisodes — le tester là arrêtait toute reprise dont la
politique avait progressé hors de la fenêtre.

**5. Toutes les décisions passent sur la moyenne des `probe_window` dernières sondes**
(`pool_eval/vs_<tag>_<probe_window>ep` — 3 aujourd'hui ; le tag porte la fenêtre réelle, il
annonçait `_3ep` quelle que soit la valeur configurée). Promotion et arrêt si ≥ 0.55 contre le
champion **et** ≥ 0.50 contre chaque autre membre après 50 000 épisodes d'étape ; arrêt pour
destruction si < 0.40 contre le champion après 20 000. Le gate de fin applique les mêmes seuils sur
une moyenne de 3 blocs d'évaluation, et un seuil de promotion **sous** le plancher du gate est
refusé au chargement (sinon le run s'arrête en se déclarant promu sur un score que le gate
refusera, et jette le budget non dépensé avec l'étape). Le pool **entier** est sondé, plus
seulement le champion : une étape pouvait être promue en battant son prédécesseur immédiat tout en
ayant régressé contre tout le reste. Une archive du pool écartée par l'évaluation **arrête le
run** au lieu d'être signalée : sans elle, ni promotion ni destruction ne peuvent plus être
décidées, et l'étape brûlait son budget entier pour une ligne ⚠️ par sonde.

**6. Un verdict `destroy` est souverain : le gate ne le rejuge pas.** L'étape est refusée sans
mesure. Sous `save_best_robust` (les profils du curriculum), le zip canonique est l'instantané
robuste pris plus tôt dans le run — **d'autres poids que ceux jugés** : le gate pouvait donc
l'accepter et le promouvoir, et `curriculum.log` portait `pool_stop_verdict: "destroy"` à côté de
`gate_accepted: true`. Un verdict `promote`, lui, laisse le gate mesurer normalement.

⚠️ **`base_seed` de `evaluate_against_checkpoints` est désormais TIRÉ AU HASARD.** Il valait 42 en
dur, donc deux évaluations d'un même modèle rejouaient les mêmes parties et rendaient le même score
au bit près (vérifié le 2026-09-07 : 16/24/0 aux deux appels) — moyenner trois blocs identiques
n'est pas une moyenne. Conséquence à assumer : **un gate n'est plus reproductible à l'identique**,
et les scores de `curriculum.log` antérieurs au 2026-09-07 portent un échantillon unique et figé.

**À mesurer au prochain run** : `00_critical/g_grad_share_policy_mb0` doit monter de 0,235 vers
~0,62 dès les premières updates — effet arithmétique de `vf_coef`, pas un effet d'apprentissage.
Si elle ne bouge pas, le régime n'a pas pris et il est inutile d'attendre. `n_steps` × 4 quadruple
la mémoire du rollout buffer : **coût horloge et mémoire non chronométrés** à ce volume.

**À faire après la fin du run P1 `run_20260912-065925`** (2026-09-12, suite 110) : le `_doc` de
`x1_lineage` (`config/agents/ArmageddonAgent_x1/ArmageddonAgent_x1_training_config.json`) affirme
qu'« à 8160 avec batch_size 1020 et n_epochs 4 […] les quatre epochs vont désormais au bout » ;
**réfuté** sur ce run — `train/approx_kl_max` > 0,0225 sur 761/761 updates, chaque update est
coupée par l'early-stop KL. Le tag `train/n_minibatches_done` (doublon
`00_critical/v_n_minibatches_done`) compte désormais les pas de gradient réellement exécutés ;
la phrase du `_doc` se corrige avec ce comptage, et toute décision `target_kl` / `n_epochs` se
prend dessus — jamais sur `train/time_update`. Aucun JSON de `config/` ne se touche tant que le
run tourne.

### Fraction de signal des updates P1 — mesurée le 2026-09-13 {#signal-p1-2026-09-13}

**Verdict : branche (1) de la règle écrite avant lecture — le gradient de politique d'une update
P1 n'est pas distinguable de zéro ; la taille de lot n'est pas un levier.** Instrument :
`scripts/grad_signal_probe.py` (lecture seule ; verrous `tests/unit/scripts/test_grad_signal_probe.py`),
sur le canonique du 2026-09-12 18:52 (instantané robuste 0,9078, 110 177 épisodes cumulés), dans
l'environnement EXACT de P1 (curriculum P1, profil `x1_lineage`, 24 envs, 20 entrées de scénario,
pool P0 à 0,70, rampe de déploiement figée à 0,90, VecNormalize du checkpoint figée avec
`norm_reward` rétabli) : **24 rollouts de 8160 pas** collectés par `_collect_rollouts_distributed`
à politique figée, 8 mini-lots de 1020 par `rollout_buffer.get`, gradients de chaque terme de la
loss pris séparément, sans `optimizer.step`. Durée 19 min (36 s de collecte + 4 s de gradients
par rollout). Acceptation tenue au premier rollout : `grad_norm_policy_mb0` 0,378 (référence
0,354 ± 0,052), value 0,252 (0,218 ± 0,108), `explained_variance` 0,895 (0,889), ep_len 114,8
(111,9), returns 1,773 (1,644 ± 0,130), part d'épisodes contre P0 0,67 (0,70) ; sur les 24
rollouts : policy mb0 0,361 en moyenne, EV 0,882, ep_len 111,5, part pool 0,699, 1 743 épisodes,
0 sans vainqueur.

**Terme policy (3,25 M paramètres, tous groupes)** : ‖G‖² sans biais = 8,3 × 10⁻⁵, intervalle
jackknife **[−2,0 × 10⁻⁴, +3,7 × 10⁻⁴]** — contient 0 ; E‖G_rollout‖² = 0,0165 (norme 0,128 pour
la moyenne des 8 mini-lots) et E‖g_minibatch‖² = 0,131 (norme 0,36, la valeur publiée en
`diag/grad_norm_policy_mb0`). Donc **f_8160 = 0,005 [−0,012, 0,022]** et **f_1020 = 0,0006** :
plus de 97,8 % du carré de norme d'une update est du bruit, même à la borne haute de
l'intervalle. B_noise n'est pas estimable (point 1,6 × 10⁶, intervalle contenant 0) ; sa
**borne basse**, prise à la borne haute de ‖G‖², vaut **≈ 358 000 pas**, soit 44 rollouts de
8160 pour une update à moitié signal. Aucun groupe de paramètres ne porte de signal détectable :
sur les 20 groupes, tous les intervalles de ‖G‖² contiennent 0 ; le seul intervalle de f_8160
qui l'exclut est `shoot_weapon_sel_query_net`, 0,085 [0,015, 0,155], à ~2σ sur 20 groupes —
ce que le test multiple produit seul.
Distinguer « zéro » de « 8 × 10⁻⁵ » demanderait K ≈ 316 rollouts (~4 h) ; la règle ne le demande
pas, et les deux lectures mènent à la même décision.

**Terme value (`vf_coef` × MSE)** : ‖G‖² = 0,0138 **[0,0082, 0,0193]**, f_8160 = **0,27
[0,14, 0,40]**, f_1020 = 0,23, B_noise = 21 600 [8 100, 35 100] ; sur le `features_extractor`
f_8160 = 0,32 [0,18, 0,45]. Le critic, lui, reçoit encore un gradient réel — cohérent avec
`explained_variance` 0,85 → 0,89 sur le run. **Terme entropie** : f_8160 = 0,961 [0,959, 0,963],
B_noise = 332 — la vérification de l'instrument : un terme sans bruit d'avantage rend f ≈ 1.
**Gradient d'issue** (REINFORCE ±150 sur les 130 709 pas d'épisodes complets, retour
Monte-Carlo à γ = 0,99) : ‖G‖² = −6,7 × 10⁻⁵ [−4,4 × 10⁻⁴, +3,0 × 10⁻⁴], pas plus distinguable
de 0 que le gradient façonné. **Cosinus** (sans biais par produits croisés) : (policy, value) sur
le features_extractor 0,37 mais intervalle indéfini ; (façonné, issue) indéfini globalement et
**aucun des 20 groupes mesurable à K = 24** (le seul intervalle excluant 0, `fight_query_net`
[0,16, 1,72], sort de [−1, 1]). Les deux cosinus se rapportent « non mesurables à K = 24 ».

**Ce que ça tranche.** Le plateau de P1 contre P0 n'est pas un problème de lot : à 8160 pas
l'update de politique est du bruit à > 97,8 %, et un lot 44 fois plus grand serait le MINIMUM pour
une update à moitié signal — s'il y a un signal, ce que 24 rollouts ne peuvent pas affirmer.
Doubler ou quadrupler `n_steps` × `batch_size` ne changerait rien de mesurable. Les 761/761
updates coupées par l'early-stop KL (suite 110) se relisent avec ce chiffre : la KL qui déclenche
la coupure est produite par un pas de bruit, pas par un déplacement dirigé. La branche restante
est celle de l'objectif et de la récompense (le gradient façonné ET le gradient d'issue sont
nuls à cette précision : la politique est à un point stationnaire des deux, ou leur signal est
sous 3 × 10⁻⁴), pas celle des hyperparamètres d'optimisation — `target_kl`, `n_epochs`,
`learning_rate` opèrent sur une direction qui n'en est pas une.

Reproduire : `python3 scripts/grad_signal_probe.py --agent ArmageddonAgent_x1 --etape P1
--training-config x1_lineage --rollouts 24 --out <json>`
(refuse si `ai/train.py` tourne ; sort en code 3 si le premier rollout ne reproduit pas la référence).

#### Balayage λ appairé, décomposition de Var(δ), contrôles — 2026-09-13, suite 123 {#signal-p1-lambda-2026-09-13}

**Verdict : aucune des trois issues écrites avant lecture ne s'applique telle quelle ; la
lecture qui reste est la branche « avantage moyenné » (tête Q ou distillation), avec la
décomposition à l'appui.** La règle disait : f(λ=0) > 0,1 excluant 0 → run P1 30 000 épisodes à
ce λ ; f(λ=0) ≈ 0 et f(contrôle) > 0 → avantage moyenné ; f(contrôle) ≈ 0 → instrument à
réparer. Mesuré : **f(λ=0) = 0,053 [0,036, 0,070]** — exclut 0 mais reste cinq fois sous 0,1 :
le λ le plus bas rend une update encore à 95 % de bruit ; **f(contrôle 040721) = 0,006
[−0,005, 0,017]** — le contrôle choisi n'est pas positif ; **f(contrôle à poids ALÉATOIRES) =
0,43 [0,27, 0,59]** — l'instrument voit un gradient qui existe. Donc pas de run à λ = 0 (le
critère n'est pas atteint), pas d'instrument à réparer (réfuté par le contrôle aléatoire), et la
branche 2 par élimination argumentée : à lot fixe, ni λ (×3,4 sur ‖G‖², f plafonne à 0,05), ni le
hasard de l'adversaire (P0 déterministe : mêmes nombres) ne réduisent le bruit ; ce qui reste
est la variance du crédit lui-même, et la décomposition dit qu'elle est à l'échelle de la
récompense.

**Instrument.** `scripts/grad_signal_probe.py`, extension lecture seule (verrous :
`tests/unit/scripts/test_grad_signal_probe.py`, 24 tests). Sur CHAQUE rollout collecté, avantages
et retours sont recalculés a posteriori depuis les copies non aplaties de rewards / values /
episode_starts, `last_values` recalculé sur `model._last_obs` (`gae_advantages` : écart max **0**
sur les 24 + 24 + 24 + 12 rollouts, tolérance 1e-6), puis le gradient policy de chaque λ est pris
mini-lot par mini-lot ; les différences entre λ sont appairées (jackknife de f_a − f_b sur les
mêmes rollouts). Depuis la simplification du 2026-09-13 (après les quatre collectes) :
`gae_advantages` appelle `RolloutBuffer.compute_returns_and_advantage` de SB3 sur un buffer
jetable (une seule source de vérité), le λ du modèle est toujours balayé et `--gae-lambdas` ne
liste que les λ supplémentaires, et les pertes policy des autres λ sont prises dans la **même
passe avant** que les quatre termes (mêmes ratios, seuls les avantages changent) — le buffer de
production n'est plus muté. ⚠️ Piège rencontré par la première version (qui rejouait `get()` par
λ) : `GpuMaskableDictRolloutBuffer` uploade avantages et retours sur le GPU **une fois** au
premier `get()` — remplacer les seuls tableaux numpy fait servir les anciens avantages ; attrapé
par la vérification d'alignement mini-lot par mini-lot. Var(δ_t) = Var(r_t) + Var(ΔV_t) +
2 Cov sur les mêmes buffers, par famille de l'action jouée (`action_family`, phase lue dans le
one-hot `global_bin` de l'observation du pas, `setting_up` = `info["action"] == "ingress_move"`).
`--model` : autre politique dans le MÊME env P1, avec SON pkl compagnon (jamais celui du
canonique, verrouillé ; chemins résolus, le canonique refusé en `--model` ; `vf_coef` /
`ent_coef` du checkpoint rapportés) ; `--random-init SEED` : poids réinitialisés en mémoire ;
`--opponent-deterministic` : `self_play_deterministic = true` dans le bloc `opponent_mix` de
l'étape (la clé que `curriculum.opponent.deterministic` alimente), acceptation de plomberie
(part pool) comme pour un contrôle. Toute troncature moteur (`TimeLimit.truncated`) arrête la
sonde : « 0 sans vainqueur » ne pouvait rien attraper (limite anti-runaway = nul déclaré). Une implémentation
indépendante (session 40k-a2, avantages recalculés passés en tenseurs séparés sans toucher le
buffer) rend les mêmes nombres : λ = 0,95 f = 0,018 [−0,008, 0,045], λ = 0 f = 0,058 [0,027,
0,089] ; son contrôle synthétique (avantage = log-prob de l'action jouée, crédit cohérent de
variance unité) donne f = 0,667 [0,637, 0,696] — lu d'abord comme « plafond de l'instrument » ;
c'est en fait un estimateur à un échantillon du gradient d'entropie (E_a[∇log π · log π] = −∇H),
dont f dépend de la politique (≤ f_entropie) : pas un plafond, non repris dans main, où le
contrôle à poids aléatoires tient le rôle de contrôle positif. Ses stats par groupe et par λ, elles,
sont reprises (`lambda_sweep.per_lambda[λ][groupe]`, 2026-09-13 soir).

**P1, canonique 0,9078 dans l'env exact de P1 (24 rollouts, 1 738 épisodes, 0 sans vainqueur,
part pool 0,702, acceptation tenue : policy mb0 0,313, EV 0,892, part pool 0,66).** Terme policy,
tous groupes, par λ (‖G‖² sans biais ; f_8160) :
λ = 0,95 : 2,6 × 10⁻⁴ [−1,7 × 10⁻⁴, 6,8 × 10⁻⁴] ; **0,015 [−0,010, 0,039]** (non détecté — reproduit
la mesure du matin, 8 × 10⁻⁵ / 0,005) ;
λ = 0,80 : 1,0 × 10⁻⁴ [−1,9 × 10⁻⁴, 4,0 × 10⁻⁴] ; 0,007 [−0,014, 0,028] (non détecté) ;
λ = 0,50 : 3,9 × 10⁻⁴ [1,5 × 10⁻⁴, 6,3 × 10⁻⁴] ; 0,027 [0,010, 0,044] (détecté) ;
λ = 0,20 : 7,5 × 10⁻⁴ [4,8 × 10⁻⁴, 1,0 × 10⁻³] ; 0,048 [0,031, 0,065] ;
λ = 0 : 8,7 × 10⁻⁴ [5,8 × 10⁻⁴, 1,2 × 10⁻³] ; **0,053 [0,036, 0,070]**, B_noise = 147 000 pas
[97 000, 196 000] (18 rollouts de 8160 pour une update à moitié signal, contre > 358 000 à
λ = 0,95).
Différences appairées Δf_8160 (a − b) : 0,95 − 0 = **−0,038 [−0,070, −0,005]** (exclut 0) ;
0,95 − 0,20 = −0,033 [−0,064, −0,001] (exclut 0) ; 0,95 − 0,50 = −0,012 [−0,039, +0,015] ;
0,95 − 0,80 = +0,008 [−0,006, +0,022] ; 0,50 − 0 = −0,026 [−0,039, −0,013] ; 0,20 − 0 = −0,005
[−0,010, −0,0002]. Lecture : descendre λ fait apparaître un gradient détectable (‖G‖² × 3,4,
E‖G_rollout‖² inchangé à 0,017), mais ce gradient — celui d'un estimateur TD(0) BIAISÉ par
l'erreur du critic, pas nécessairement une direction d'amélioration — reste à f = 0,05. Termes de
contrôle interne inchangés : value f = 0,28 [0,16, 0,41] (0,27 le matin), entropie 0,96.

**Décomposition de Var(δ_t), 195 840 pas (P1) :** Var(δ) = **0,0500** = Var(r) **0,0432**
(part 0,864) + Var(ΔV) 0,0652 (part 1,303) + 2 Cov **−0,0584** (part −1,168) ; ρ(r, ΔV) =
**−0,55**. Le critic anticipe la récompense façonnée : V(s_t) monte avant qu'elle tombe et
ΔV_t = γV(s_{t+1}) − V(s_t) redescend quand elle est tombée, d'où la covariance négative qui
annule la plus grande part de Var(r) + Var(ΔV). Ce qui reste, δ, a la variance de r à 15 % près.
Par famille (part de Var(r) dans Var(δ) ; n) : shoot_slot **0,955** (18 467, Var(δ) 0,115),
fight_slot 0,82 (4 740), choice 0,79 (51 464), fight_weapon_slot 0,70 (5 853, Var(δ) 0,258 — la
plus haute), activate_slot 0,55 (60 419), **move_cell 0,12** (37 742 : un mouvement ne reçoit pas
de récompense immédiate, son δ est du seul changement de valeur), deploy_slot 0,015 (8 893),
charge_slot 0 (3 147, Var(δ) 0,003 : δ ≈ 0, ni récompense ni surprise) ; oath / coherency /
fight_no_target / wait : parts > 1 des deux côtés et covariance −2 à −5 (r et ΔV grands et
opposés, échantillons < 4 500). Ce que ça dit pour une récompense EN ESPÉRANCE : elle retire
Var(r − E[r | s, a]), part non identifiable ici parce que ΔV dépend aussi du dé (une cible tuée
change s_{t+1}) ; la borne est Var(r) = 86 % de Var(δ), et les familles où le dé décide
(tir, combat) sont celles où δ est le plus dispersé et le plus porté par r. Une tête Q ou une
distillation d'avantage moyenné vise exactement ces familles.

**Contrôle positif `--model` (entnorm_20260913-040721 = bras x1_40k, 40 002 épisodes à froid,
holdout ~0,79, dans l'env P1 avec SON pkl ; 24 rollouts, 1 783 épisodes, 0 sans vainqueur, part
pool 0,700).** Policy λ = 0,95 : ‖G‖² 1,2 × 10⁻⁴ [−9 × 10⁻⁵, 3,4 × 10⁻⁴], **f = 0,006 [−0,005,
0,017]** — même profil que P1 ; λ = 0,80 : 0,019 [0,003, 0,035] (détecté) ; λ = 0 : 9,7 × 10⁻⁴
[5,1 × 10⁻⁴, 1,4 × 10⁻³], f = 0,054 [0,028, 0,079], B_noise 144 000. Terme value : ‖G‖² 0,46,
**f = 0,876 [0,81, 0,94]**, B_noise 1 150 — son critic n'est pas ajusté à cet env (pool P0 à
70 %, jamais vu), le gradient de valeur est massif et l'instrument le voit sans ambiguïté.
Var(δ) 0,0493 : Var(r) 0,0524, Var(ΔV) 0,0685, Cov −0,0358 (ρ = −0,60). Conclusion : une
politique 30 points de holdout plus faible que le canonique a, à λ = 0,95 et B = 8160, aussi peu
de gradient de politique détectable — ce contrôle ne discrimine pas.

**Contrôle positif `--random-init 20260913` (poids du canonique réinitialisés en mémoire, mêmes
hyperparamètres, stats du canonique ; 12 rollouts, 962 épisodes, 0 sans vainqueur, part pool
0,697, ep_len 100).** Policy λ = 0,95 : ‖G‖² 5,6 × 10⁻⁵ [1,6 × 10⁻⁵, 9,5 × 10⁻⁵] (exclut 0),
E‖G_rollout‖² 1,3 × 10⁻⁴, **f_8160 = 0,43 [0,27, 0,59]**, f_1020 = 0,08, B_noise 10 800 ;
λ = 0,80 : 0,63 [0,52, 0,75] ; λ ≤ 0,5 : 0,71–0,73 ; value f = 0,97 ; entropie ‖G‖² ≈ 2 × 10⁻⁹
(politique uniforme = entropie maximale, gradient nul — attendu). Une première passe équivalente
(zip réinitialisé hors dépôt, autre tirage) avait donné 0,40 [0,12, 0,68]. L'instrument détecte
un gradient de politique à λ = 0,95 quand il existe, avec deux fois moins de rollouts. À noter :
la politique aléatoire a un gradient 130 fois plus PETIT en norme que P1 (E‖G_rollout‖²
1,3 × 10⁻⁴ contre 0,017) — ce qui grandit avec l'entraînement, c'est le bruit par échantillon
d'une politique devenue tranchée, pas le signal. ⚠️ Une passe `--random-init` sur trois a été
tuée par le MOTEUR, pas par la sonde : `_process_squad_action` (`engine/w40k_core.py`) lève « execute_squad_move a
échoué […] la destination vient du pool BFS du masque, elle DOIT être exécutable — collision
intra-plan : deux figurines en (19,29) » pendant un tour BOT (`_run_bot_until_not_bot_turn`),
dans un état que seule une politique aléatoire produit ; bug d'invariant masque/exécution,
consigné en suite, hors de ce chantier.

**P0 déterministe (`--opponent-deterministic`, seconde collecte NON appairée ; 24 rollouts,
1 748 épisodes, 0 sans vainqueur, part pool 0,699, acceptation tenue).** Policy λ = 0,95 :
‖G‖² 1,5 × 10⁻⁴ [−2,2 × 10⁻⁴, 5,3 × 10⁻⁴], f = 0,009 [−0,014, 0,031] ; λ = 0 : 9,0 × 10⁻⁴
[4,1 × 10⁻⁴, 1,4 × 10⁻³], f = 0,061 [0,029, 0,093], B_noise 126 000 ; value f = 0,26 [0,13,
0,38] ; Var(δ) 0,0492 (parts 0,877 / 1,326 / −1,203, ρ = −0,56). Indistinguable de la collecte
stochastique : l'échantillonnage de l'adversaire figé n'est pas une source de bruit mesurable —
le dé et le crédit le sont.

Durées : 24 rollouts × (34–73 s de collecte + 9–23 s de gradients pour 5 λ) = 20 à 30 min par
collecte, 4 collectes. Reproduire : `python3 scripts/grad_signal_probe.py --agent
ArmageddonAgent_x1 --etape P1 --training-config x1_lineage --rollouts 24 --gae-lambdas
0.8,0.5,0.2,0 --out <json>` (le λ du modèle, 0,95, est toujours balayé) ; `... --model
ai/models/ArmageddonAgent_x1_entnorm/model_ArmageddonAgent_x1_entnorm_20260913-040721.zip` ;
`... --random-init 20260913 --rollouts 12` ; `... --opponent-deterministic`. Aucun JSON de
`config/` ni zip/pkl touché (vérifié par mtime en sortie de chaque collecte).

**Complément 40k-a2 (collecte indépendante, sortie `--out` nommée `main`, 24 rollouts, même env) :** λ 0,95 →
0,8 → 0,5 → 0,2 → 0 : f_8160 = 0,018 [−0,008, 0,045] (non détecté) → 0,016 → 0,036 → 0,053 →
**0,058 [0,027, 0,089]** (Δ‖G‖² appairé vs profil +7,6 × 10⁻⁴ [0,6, 15] × 10⁻⁴) ; B_noise(λ = 0,2)
= 145 000 [69 000, 222 000], (λ = 0) = 133 000 [63 000, 203 000] ; par groupe à λ = 0 :
`activate_query_net` f = 0,28 [0,17, 0,39], `deploy_query_net` 0,125, `features_extractor` 0,052,
`move_cell_net` non détecté ; contrôle synthétique (crédit = log-prob de l'action, déterministe)
f = 0,667 [0,637, 0,696] (estimateur du gradient d'entropie, dépendant de la politique — pas un
plafond d'instrument, cf. note de la section précédente).
Trois points qui complètent le verdict, détaillés au §7 du dossier `plafonnement_p1.md` :
(1) λ à lot fixe et lot à λ = 0,95 ont été éliminés séparément, pas **ensemble** — à λ = 0,2 et
B = 32 640 la définition de B_noise prédit f ≈ 0,18 [0,13, 0,32] (S23 : `batch_size` 2 040, le lot de 4 080 mesuré à 7,47 Go de VRAM réservés replanterait ; **joué la nuit suivante et réfuté, [#run-s23-2026-09](#run-s23-2026-09) : la prédiction supposait le critic fixe, λ change sa cible**) ; (2) Var(r) / Var(δ) = 0,86 n'est pas une borne de ce qu'une récompense en espérance
retirerait (covariance négative, Var(E[r∣s,a]) conservée) ; (3) le contrôle aléatoire valide le
code, pas le régime (son f vient du facteur p(1−p) d'une politique d'entropie maximale) — le fait
informatif est le témoin entraîné à 28 % aussi indétectable que P1, qui penche vers « noyé »
plutôt que « stationnaire ».

### Six défauts de la livraison, fermés le 2026-09-07

**Le premier était bloquant pour toute la chaîne.** `_apply_curriculum_model_params` posait un
`ConstantSchedule` sur `model.learning_rate`, que SB3 sérialise dans le `data` du zip — un objet
cloudpickle là où `_model_scalar` attend un nombre. Tant que le LR était une **rampe**, le
callback d'ordonnancement réécrivait un flottant à chaque épisode et masquait le défaut ; le
régime posant un LR **scalaire**, aucun callback n'est monté. P2 (repris de P1, dont le zip porte
encore un flottant) tournait, mais P3 aurait levé au contrôle de continuité — et avec lui P4…P10
et E1…E3. `learning_rate` porte désormais le nombre, `lr_schedule` le callable, comme le fait déjà
`LearningRateScheduleCallback._apply`.

**Une reprise sur crash enchaînait les sondes manquées.** `_next_probe_episode` partait du premier
cran alors que le compteur d'étape, ancré sur l'archive source, valait déjà des dizaines de
milliers d'épisodes : les crans manqués se déclenchaient d'affilée sur des pas consécutifs, sans
mise à jour de politique entre eux. À la deuxième, l'historique atteignait deux points et un
verdict tombait — sur deux mesures des **mêmes** poids, au-dessus de `promote_min_episodes` : le
run de reprise pouvait être promu ou déclaré détruit après **zéro épisode entraîné**. Même défaut
que les 8 sondes consécutives mesurées le 2026-09-04, revenu par une autre porte. La cadence
rattrape désormais au prochain cran au lieu d'avancer d'un pas ; corrigé sur les deux sondes
(pool et exploiteur).

**`--close-stage` rouvrait la promotion d'une étape détruite.** Le verdict `destroy` n'existait que
dans le `run_info` du processus : la commande de reprise le reconstruit depuis les artefacts du
disque, où il n'apparaît pas. Comme une étape détruite n'écrit aucun `model_<agent>_<etape>.zip`,
le garde « déjà promue » ne voyait rien non plus, et la clôture remesurait l'instantané robuste —
d'autres poids que ceux jugés, qui pouvaient franchir le gate. Le verdict est désormais persisté
en **sidecar du modèle canonique** (`pool_stop_path`), que `_run_info_from_disk` relit.
Volontairement pas dans `curriculum.log` : ce journal est en append à la racine du projet, ses
entrées ne portent **aucune clé d'agent**, et il conserve l'historique de toutes les *tentatives*
d'une même étape — relire « la dernière ligne de P4 » aurait rendu le verdict d'une tentative
précédente, ou celui d'un autre agent. Le sidecar entre dans `canonical_run_artifacts`, donc
`--new` comme `--resume-from` l'écartent au démarrage : une étape rejouée après destruction
repart sans verdict.

**Un verdict `promote` publie désormais les poids VIVANTS** (décision du 2026-09-07, option A).
L'early-stop rend ce verdict sur les poids courants, mesurés contre tout le pool ; sous
`save_best_robust` le zip canonique était pourtant l'instantané robuste, choisi sur le score
contre les **bots** et jamais dégradé en cours de run (la copie n'a lieu que si le score robuste
progresse — `training_callbacks.py`, condition `robust_score > best_robust_score`). Le gate de fin
mesurait donc un modèle que personne n'avait jugé, pouvait le refuser, et le run s'était déjà
arrêté : le budget non dépensé partait avec l'étape — l'inverse exact de ce que l'arrêt anticipé
annonce (« le budget restant serait payé pour rien »). Publier est l'exception que
`save_best_robust` peut accepter : le verdict **est** une validation contre l'intégralité du pool.
Le verdict `destroy`, lui, ne publie rien.
⚠️ **Le seuil de score robuste du canonique (`canonical_robust_meta_path`) est effacé à cette
publication.** Il décrit le modèle remplacé. Il est bien écarté au **démarrage** d'un run, par
`--new` comme par `--resume-from` (les deux passent par `canonical_set_aside_pairs`) ; ce
qu'aucun des deux ne couvrait, c'est la **fin** de run traitée ici — le seuil serait resté en
place jusqu'au démarrage suivant en annonçant un score que le canonique n'a pas, défaut de la
même famille que V11 §0.36.

**Cadence des sondes dédoublée** (décision du 2026-09-07, option B). Sonder le pool entier à
chaque sonde faisait suivre le coût à la **taille** du pool, qui croît d'une étape à l'autre : à
P10 (13 membres, 300 000 épisodes, cadence 10 000, 300 épisodes par membre) cela fait **117 000
épisodes d'évaluation bloquants** sur le fil d'entraînement pour 300 000 entraînés, là où la sonde
champion seul d'avant en coûtait 9 000. Le champion est désormais mesuré à **chaque** sonde, les
autres membres **un tour sur `full_pool_probe_every`** (3 dans la config livrée) : il reste
~48 600 épisodes, soit **-58 %**. Les deux verdicts n'ont pas le même besoin de fraîcheur — la
destruction ne lit que le champion et doit couper vite, la promotion lit tout le pool mais ne
s'ouvre qu'à 50 000 épisodes d'étape. **Ce qui n'est pas dégradé** : le verdict lit toujours le
pool entier, les membres non sondés au tour courant gardant leur dernière moyenne connue, au plus
trois sondes en arrière. Les **deux premiers tours restent pleins** quelle que soit la valeur :
aucun verdict n'est rendu tant qu'un membre n'a pas deux points, et sans eux la destruction
attendrait 40 000 épisodes au lieu des 20 000 que son seuil demande.

**Trois fermetures plus petites.** La clôture dérivait le champion par un `next(...)` local là où
`stage_champion_label` **refuse** un pool à plusieurs champions, que `validate_curriculum` accepte
— elle prenait le premier venu en silence. Le plombage `timesteps_origin` était mort depuis la
suppression du garde `min_steps` : `stage_origin` ouvrait le zip source pour cette seule valeur.
Et la docstring de `pool_monotonicity_diagnostic` dimensionnait encore son bruit contre
`gate.target_score_vs_champion` (0.60), clé supprimée par cette même livraison.

---

## 🔴 Régime d'entraînement révisé — P2 à relancer depuis P1 {#regime-2026-09-06}

Deux changements livrés le 2026-09-06, plus un réglage d'évaluation du 2026-09-04 resté non déclaré
jusqu'ici. **Ce qui reste à faire : relancer P2 depuis P1.** P1 n'est pas rejoué (décision du
2026-09-06 : le temps est déjà payé), sa config est seulement homogénéisée.

**1. Le déploiement `auto` pose désormais les deux camps.** Il ne posait que le joueur contrôlé :
l'agent était placé au hasard pendant que son adversaire — bot à doctrine, ou champion du pool
jouant son réseau — se déployait avec sa politique apprise. `s_win_rate_deploy_auto` mesurait donc
un handicap unilatéral et non l'adaptabilité qu'elle prétend mesurer. Mesure du run x1_long du
2026-09-06 (~64 000 épisodes) : **0.304** de win-rate en `auto` contre **0.684** en `active`, avec
un différentiel d'objectifs de **-0.76** contre **+0.19** — l'agent tenait trois quarts d'objectif
de moins que son adversaire. La référence du 2026-08-12 (0.866 / 0.646, les deux différentiels
positifs) avait été prise contre des bots à doctrine de pose fixe, bien moins capables d'exploiter
une pose adverse médiocre.

⚠️ **`s_win_rate_deploy_auto` et `r_obj_held_diff_deploy_auto` changent de définition** : leurs
valeurs antérieures au 2026-09-06 ne se comparent pas aux suivantes. Attendu au prochain run : la
courbe `auto` doit remonter vers 0.5 en P2, puisque l'agent EST le champion à l'épisode 0. Si elle
reste basse, c'est qu'il reste autre chose à chercher.

**2. La part de bots tombe à 30 % en P1, 20 % en P2, 15 % de P3 à P10.** Les six bots sont saturés
— EndgameBot 0.99, DecapitationBot 0.95, RacerBot 0.94, AlphaStrikeBot 0.93, AttritionBot 0.92,
ScorerBot 0.86, aucun sous 0.86 — quand le champion du pool est à 0.502 (parité) et P0 à 0.626.
637 500 épisodes de la lignée partaient contre des adversaires dominés, soit 23 % du budget ; il
en reste 455 000. Pas 15 % partout : la part de bots suit la **taille du pool**, pas la force de
l'agent — à 15 %, P1 jouerait 85 % de ses parties contre son unique membre de pool, soit le régime
d'un exploiteur alors qu'il est promu champion. La rampe d'adversité de P1 est supprimée au
passage (elle le faisait démarrer à 100 % de bots), résidu du nettoyage qui avait retiré les neuf
autres.

**3. `bot_eval_intermediate` de `x1_long` passe à 100 épisodes par bot** (2026-09-04), pour la
précision de chaque point intermédiaire : à 30, l'erreur-type d'un win-rate autour de 0,5 valait
0,5/√30 = 9,1 points, du même ordre que les écarts qu'on cherche à lire d'un point au suivant ; à
100 elle tombe à 5,0. Contrepartie : l'évaluation intermédiaire passe de 6 × 30 = 180 à
6 × 100 = 600 épisodes, **coût horloge non rechronométré** à ce volume — les durées de
`bot_eval_freq_normal` valent pour 180. À mesurer au prochain run avant d'être citées.
`x5_long` reste à 30 : les deux profils `_long` divergent sur cette clé, et c'est assumé — le
chiffre publié sort de `x1_long`. La sonde d'entraînement, elle, reste à 3 avec son +33 %.
Le réglage et la divergence sont désormais verrouillés profil par profil
(`tests/unit/ai/test_schedule_decay_fraction.py`), ce qu'ils n'étaient pas : le verrou de
comparabilité était rouge depuis le 2026-09-04, avec quatre autres tests, et personne ne le voyait.

**Mesure incidente, non élucidée.** Le run P1 a joué **31,3 %** contre P0 (25 063 épisodes sur
80 075, `tensorboard/P1`), là où sa config annonçait 50 %. L'écart n'est pas expliqué par la rampe
seule, qui s'achève en ~417 épisodes par env et ne pèse que 12 % du run. Non investigué : le run
n'est pas rejoué. À retenir : un `ratio_end` n'est pas une mesure — la part réellement jouée se lit
sur le rapport entre les points de `03_selfplay/<membre>` et ceux de `actions/share_deploy_slot`,
à 500 près (la fenêtre de lissage).

---

## ⚠️ Courbes de santé PPO — historique des défauts {#courbes-ppo-reprise}

> **Runs antérieurs au 2026-09-11 uniquement.** Les familles `training_critical/`,
> `training_detailed/` et huit tags de `training_diagnostic/` n'existent plus : elles recopiaient
> valeur pour valeur les `train/*` et `diag/*` de SB3, sur l'axe des **pas** alors que le tracker
> date tout le reste en **épisodes**. Sur un run postérieur, ces séries se lisent sous `train/*`
> et `diag/*` (cf. [../Reference/training/metriques.md](../Reference/training/metriques.md), « Une abscisse par écrivain »). Les noms de
> tags ci-dessous sont conservés tels quels : ce sont ceux que portent réellement les fichiers
> `events` des runs dont cette section parle.

Trois défauts vivaient sur la capture des métriques PPO
(`MetricsCollectionCallback._on_training_start`), corrigés le 2026-09-04. Ce qu'ils rendent
illisible sur les runs antérieurs :

**Sur les runs REPRIS uniquement** (`--resume-from`, donc toute étape de curriculum à
`init: "from:..."`) — les quatre courbes de santé PPO de `00_critical` ne sont **pas lissées** et
ne doivent pas être lues : `g_explained_variance`, `h_clip_fraction`, `i_approx_kl`,
`j_entropy_loss` — lettres d'AVANT le 2026-09-06, conservées ici parce que ce sont celles que
portent réellement les fichiers `events` de ces runs ; depuis, l'insertion de
`g_grad_share_policy_mb0` les a décalées en `h_`, `i_`, `j_` et `k_`. L'enveloppe posée sur `logger.dump` n'était jamais retirée, et SB3 appaire
pourtant `on_training_start`/`on_training_end` autour de chaque `learn()`. Sur un run neuf le
logger est reconstruit à chaque `learn()` et l'enveloppe morte partait avec lui ; en reprise
`model.set_logger` le rend persistant et les couches s'accumulaient. Chaque update était alors
capturé autant de fois qu'il y avait de couches, et la fenêtre de vingt valeurs de
`_calculate_smoothed_metric` finissait par couvrir vingt copies du même update. Mesure sur le run
P1 du 2026-09-03 : 41 756 points sur `training_critical/clip_fraction` pour **575 updates réels**,
contre 1 063 points pour 1 063 updates sur un run neuf comparable. Les courbes paraissaient 4× à
14× plus bruitées, sans que la politique ni le régime d'update soient en cause.

**Sur TOUS les runs, neufs compris** :

- `training_diagnostic/entropy_coef` et `training_diagnostic/gradient_norm` portent **un point par
  ÉPISODE** et non par update. `_handle_episode_end` appelle `logger.dump` à chaque fin d'épisode,
  et la capture s'y déclenchait alors qu'aucun update PPO n'y figure — les gradients y sont ceux
  laissés par le dernier `train()`. Mesure sur le run neuf du 2026-08-29 : 101 415 points pour
  100 000 épisodes et 1 063 updates.
- Toutes les courbes `training_critical/*` et `training_diagnostic/*` sont **décalées d'un dump**
  sur l'axe des pas : l'abscisse était posée après l'écriture, donc chaque update partait au pas du
  dump précédent.

**Ce qu'il faut lire sur ces runs** : les séries brutes `training_critical/clip_fraction`,
`approx_kl`, `explained_variance` et `training_diagnostic/entropy_loss`. Les valeurs y sont
exactes ; sur un run repris elles sont répétées, et les copies d'un même update se superposent à
la **même** abscisse plutôt que de former un escalier — la courbe reste donc lisible, à condition
de la lire comme une suite de paliers et non comme un signal bruité.

Les courbes de jeu (`game_critical/win_rate`, `game_critical/episode_reward`, `03_selfplay/*`) ne
passent pas par ce chemin et n'ont jamais été touchées. Elles portaient alors aussi les tags
`00_critical/{d_win_rate,e_episode_reward_smooth}`, toutes deux revenues le 2026-09-10 et
écrites depuis `log_episode_end`.

Le run P1 en cours au 2026-09-04 a chargé le code avant le correctif : ses courbes restent
fausses jusqu'à sa fin. Verrou : `tests/unit/ai/test_metrics_dump_wrapper_idempotent.py`.

**Quatrième défaut, distinct des trois précédents, corrigé le 2026-09-06** — celui-ci touchait
**tous** les runs, neufs compris, et il est indépendant de l'empilement d'enveloppes. Les cinq
courbes `00_critical/f..j` et les huit lignes `thresholds/*` étaient republiées à **chaque fin
d'épisode** alors que leur source n'est alimentée qu'une fois par update : 39 430 points pour 529
valeurs distinctes sur `run_20260906-123804`, soit 74,5 copies par valeur, contre 532 points et
532 valeurs sur les jumelles `train/*` de SB3. Le curseur de lissage de TensorBoard comptant des
points, il aurait fallu le régler sur ~1 500 pour couvrir la fenêtre glissante de 20 updates. Aucune
valeur n'était fausse — l'enveloppe de l'escalier est la bonne série — mais le curseur était
inopérant et les runs de cadences d'update différentes n'étaient pas comparables point pour point.
Ces treize tags portent désormais un point par update. Verrou :
`tests/unit/ai/test_metrics_tracker_utils.py::test_les_courbes_de_sante_ppo_suivent_la_cadence_de_l_update`.
Les runs antérieurs au 2026-09-06 gardent l'escalier, à lire comme une suite de paliers.

---

## Win-rate HOLDOUT de la lignée du 2026-09-11 {#holdout-2026-09-11}

**Point de départ d'une nouvelle lignée, PAS une comparaison.** Quatre correctifs mergés le
2026-09-10 changent l'issue des parties ou le reward — contrôle d'objectif sommé par figurine
(suite 49 de `ROADMAP_INDEX.md`), caractéristiques défensives effectives dans `expected_damage`
(suite 50), table de dégâts complétée (suite 51 : 57 armes sur 231 valaient zéro, dont tout le tir
ork), exclusivité des profils combi exposée dans l'observation (suite 48). Les win-rates antérieurs
ne sont donc pas des points de référence valides pour celui-ci, et aucun « avant/après » n'est
présenté ici.

Mesure : `python3 ai/train.py --agent ArmageddonAgent_x1 --training-config x1 --resolution 1
--test-only --step` sur `model_ArmageddonAgent_x1.zip` (2026-09-11 13:09), 300 épisodes,
6 bots × 50, deux rosters holdout, siège alterné (132 épisodes en P1, 168 en P2). Dépouillement
`ai/analyzer.py`.

**WIN-RATE HOLDOUT : 270/300 = 90,0 %**, aucun nul. 259 victoires aux objectifs, 11 au départage
de valeur, **zéro par élimination**.

| dimension | résultat |
|---|---|
| EndgameBot | 48/50 = 96,0 % |
| AlphaStrikeBot / DecapitationBot | 47/50 = 94,0 % |
| RacerBot | 44/50 = 88,0 % |
| AttritionBot | 43/50 = 86,0 % |
| ScorerBot | 41/50 = 82,0 % |
| roster Space Marines | 149/156 = 95,5 % |
| roster Orks | 121/144 = 84,0 % |
| siège P1 (joue premier) | 126/132 = 95,5 % |
| siège P2 | 144/168 = 85,7 % |

⚠️ **L'écart de siège n'est pas refermé.** Le bit `i_play_first` (cf. [siège premier /
second](#siege-premier-joueur-obs)) a réduit l'écart mesuré le 2026-08-12 — 0,707 contre 0,586,
soit 12,1 points — à **9,8 points** ici. Il a donc aidé sans suffire ; l'asymétrie reste le plus
gros écart structurel de cette lignée, devant l'écart de roster (11,5 points).

**Décisions d'agent, mesurées pour la première fois** — la journalisation des décisions (suite 53)
les rend comptables, ce qui était impossible avant :

- **déclaration de réserves 20.01 : 444/1944 = 22,8 %** de `CHOICE_0`. La question ouverte depuis
  le déplacement de l'étape 20.01 avant le déploiement est tranchée : l'agent **n'élude pas** la
  réserve et ne la déclare pas systématiquement non plus — il la joue dans un peu moins d'un quart
  des cas ;
- `fly_declaration` : 2 103/2 931 = 71,8 % de montées ;
- `waaagh_call` : 290/421 = 68,9 % d'appels.

**Constats analyzer non traités**, rapportés sans être qualifiés :

- 1.1 « moves to adjacent enemy » : **2 occurrences sur 9 737 mouvements** (0,02 %), toutes en P1,
  exemple épisode 248. À vérifier avant d'appeler ça un défaut — ce dépôt a un historique de faux
  positifs analyzer sur ce motif précis (métrique hex contre euclidienne) ;
- 1.7 « special rules usage » : `mortal_wounds_on_critical_wound` / Boyz 1 invalide sur 4, et
  `mortal_wounds_on_fight_activation` / VanguardVeteranSquadJumpPack **59 invalides sur 90** — ce
  second chiffre est trop élevé pour être ignoré.

---

## Win-rate HOLDOUT du 2026-09-13 — canonique après l'arrêt de P1 {#holdout-2026-09-13}

**Nouveau point de départ, PAS un avant/après**, pour les raisons données par le prompt qui l'a
demandé : le canonique a été remis à P0 (`robust_0.8683`, 2026-09-10 22:31) puis repris par P1 ; la
référence 90,0 % ([#holdout-2026-09-11](#holdout-2026-09-11)) portait sur le modèle du 2026-09-11
13:09 (`robust_0.8933`) ; 35 commits moteur hors 20.01 sont entrés depuis (fight/pile-in/overrun
12.06 gym, New Foes gym, zone d'engagement 09.05…). Un écart n'est attribuable à rien.
**Prémisse corrigée** : P1 n'a PAS été promu — plateau contre P0 (0,547 → 0,601 entre 60 000 et
120 000 épisodes cumulés, seuil 0,65), run arrêté le 2026-09-12 à 70 000 épisodes d'étape sans
sauvegarde d'urgence. Le modèle mesuré est son instantané robuste **0,9078** (2026-09-12 18:52,
110 177 épisodes cumulés = 60 000 d'étape), identique octet pour octet à
`ArmageddonAgent_x1_12345_robust_0.9078.zip`.

Mesure : `python3 ai/train.py --agent ArmageddonAgent_x1 --training-config x1 --resolution 1
--test-only --step`, 2026-09-13 09:53–10:03, 300 épisodes, 6 bots × 50, deux rosters holdout,
siège alterné (132 en P1, 168 en P2), **0 troncature** (garde anti-runaway muet), 0 nul.
Dépouillement `ai/analyzer.py` (`analyzer.log`) et comptage siège/roster sur `step.log`.

**WIN-RATE HOLDOUT : 273/300 = 91,0 %** (σ binomiale 1,7 pt, IC95 ≈ ±3,2). 266 victoires aux
objectifs, 7 au départage de valeur, **zéro par élimination**.

| dimension | résultat | référence 2026-09-11 |
|---|---|---|
| EndgameBot | 48/50 = 96,0 % | 96,0 % |
| RacerBot | 47/50 = 94,0 % | 88,0 % |
| AlphaStrikeBot / DecapitationBot / ScorerBot | 45/50 = 90,0 % | 94,0 / 94,0 / 82,0 % |
| AttritionBot | 43/50 = 86,0 % | 86,0 % |
| roster Space Marines | 151/156 = 96,8 % | 95,5 % |
| roster Orks | 122/144 = 84,7 % | 84,0 % |
| siège P1 (joue premier) | 129/132 = 97,7 % | 95,5 % |
| siège P2 | 144/168 = 85,7 % | 85,7 % |
| pire scénario | holdout_regular_bot-03 = 83,3 % | — |

L'écart de siège reste de **12,0 points** (9,8 sur la référence) et l'écart de roster de 12,1 —
les deux asymétries structurelles n'ont pas bougé.

**Décisions d'agent** (`agent_decision_option_rate`, les deux sièges additionnés) :

- **déclaration de réserves 20.01 : 444/1944 = 22,8 %** de `CHOICE_0` — la question est toujours
  posée au siège modèle après le passage en déclaration par camp. Numérateur ET dénominateur
  identiques à la référence : mêmes graines, mêmes rosters, politique déterministe en évaluation,
  et la déclaration se joue à l'état initial de la partie — l'égalité n'est pas anormale, mais
  elle n'a pas été vérifiée épisode par épisode. Le dénominateur attendu « plus bas » (camp machine
  saturé sauté) ne s'est pas produit : 1944 questions, comme avant ;
- `fly_declaration` : 1 916/2 922 = 65,6 % de montées (référence 71,8 %) ;
- `waaagh_call` : 290/424 = 68,4 % d'appels (référence 68,9 %).

**Constats analyzer** : **2.1 « Dead unit fighting » : 5 occurrences, toutes côté joueur 2**
(première : épisode 248, T5, `Unit 105(17,36) FOUGHT Unit 4(18,36) with [Choppa]`) — **qualifiées
le 2026-09-13 : faux positif analyzer, une seule activation.** Le WarTrakk 105 tue le WeirdBoy 4
(Deadly Demise D3), l'explosion tue le WarTrakk ; le moteur résout toutes les attaques avant
d'allouer, écrit les `DEAD` pendant l'allocation et les `FOUGHT` après — le journal inversait
l'ordre du jeu, et la ligne `DEADLY DEMISE` qui aurait nommé la cause n'atteignait pas step.log.
Corrigé (ROADMAP_INDEX, suite 116) : ligne journalisée + garde `died_in_own_activation` ; **sur ce
journal-ci, antérieur à la ligne, le compteur reste à 5** (la cause n'y est pas écrite, l'analyzer
ne la devine pas). 1.8 : 18 règles d'arme jamais exercées (inchangé). Aucune erreur de move, de
tir, de charge ni de phase.

Éval incidente contre les 6 checkpoints figés (25 ép. chacun, hors gate) : 0,44 à 0,64, moyenne
0,553 — dont 0,64 contre `ckpt_0.9078`, qui EST le modèle mesuré : 25 parties ne distinguent
rien, l'indicateur est au bruit.

---

## Sonde win-rate scénarios d'entraînement {#training-probe}

**Livré 2026-09-06.** `training_probe_every_n_evals` dans `BotEvaluationCallback` publie
`bot_eval/training_combined` sur TensorBoard, calculé contre les scénarios d'ENTRAÎNEMENT (pas
holdout), en mode déterministe, tous les N evals holdout.

Motif : gap factor 2,5 mesuré le 2026-09-06 entre +13 pts sur les scénarios d'entraînement et
+5 pts holdout, invisible sur le dashboard existant. Les deux courbes permettent de distinguer :

- courbe plate → **n'apprend pas** → correction : hyperparamètres, récompense, obs.
- courbe haute / gap large → **n'généralise pas** → correction : pool de scénarios, régularisation.

Ne gate rien. Activé à 3 (`x1_long` profile, `callback_params.training_probe_every_n_evals`).
Coût : +33 % du budget eval distribué uniformément.

---

## Critères pipeline du run en cours (ex-« run x1 de vérification ») {#run-verif}

Un run `x1` de vérification dédié avait été décidé le 2026-08-11 pour prouver que le pipeline
tourne avec l'espace de décision modifié. Le run `x1_long --new` lancé le 2026-08-17
([bot.md#etape8](bot.md#etape8)) embarque le même code à HEAD : **les critères se lisent sur SES
courbes**, un run séparé n'a plus d'objet sauf si celui-ci échoue.

✅ Critères vérifiés sur le run `x1_long --new` du 2026-08-20 :

- ✅ `game_critical/invalid_action_rate` reste à **0**
- ✅ `02_combat/m_charge_attempts` **non nul**
- ✅ `02_combat/n_charge_success_rate` **non nul** (en V11 la déclaration est gratuite — l'agent déclare « au cas où » puis choisit ses cibles après le jet ; un taux bas ne signifie pas un dysfonctionnement)
- ✅ Courbes `reserves/*` et `05_charge/*` **peuplées** (`charge_distance/*` était le nom de la clé interne, le tag TensorBoard réel est `05_charge/*`)

⚠️ Pour tout re-run : `--new` et non `--append` — `--append` réapplique `ent_coef = 0,1` et écrase le modèle canonique.

---

## ✅ Curriculum R1→R3 — absorbés par le curriculum `--etape` {#curriculum}

**Décision 2026-08-30 — R1→R3 abandonnés comme runs standalone.**

Deux raisons rendent ces runs redondants :

1. Le bug d'aliasing obs Phase 3 (corrigé 2026-08-29) invalide toute ligne de base antérieure.
   La validation du fix s'est faite sur le run `--etape P2` (ratio_mb0=1.0, EV→0.85) — ce run
   tient lieu de R1.
2. Le curriculum `--etape` P0→P10 intègre déjà les trois leviers séquentiellement : P0 = bots
   purs (≡ R1), P1/P2/… = self-play progressif (≡ R2), levier récompense = à tester via
   `--etape` sur un run ultérieur si D.4 le justifie (≡ R3).

Mesurer R1/R2/R3 en standalone n'apporterait que la décomposition du gain par levier — utile
pour arbitrer, mais le curriculum `--etape` les intègre tous et la mesure J3 se fera sur le
champion final.

**Le chiffre J3 se lit sur le champion issu du curriculum P0→P10, pas sur un run standalone.**

→ `Documentation/Chantiers/backlog/curriculum_adversaires_etalons.md` §5-7 (historique)

---

## Mode exploiteur E1/E2/E3 {#exploiteur}

**Livré 2026-08-22.** `--etape E1/E2/E3` mesure l'exploitabilité de sa cible (P3, P5, P8) :
budget = épisodes pour passer de 50 % à 70 % de win-rate contre la cible figée.

- `ExploiterProbeCallback` : sonde synchrone tous les 2000 épisodes (100 ép. bon marché →
  une seule confirmation de 500 ép.), sans Future ni ThreadPoolExecutor.
- `validate_exploiter_protocol` : refuse le run si `training_config`, `ratio`, `warmup`
  ou `profile_total_episodes < budget_cap` divergent du protocole gelé (`exploiter_config`).
- `curriculum.log` : budget entier ou `'>50000'` (censuré) + courbe win_rate complète.
- 28 tests verrou (4 verrous : refus protocole, budget_cap atteignable, pas de sonde abandonnée, valeur censurée).
- `training_config_required` : `x1_long` (50 000 épisodes = `budget_cap`).

Lancer : `python3 ai/train.py --agent ArmageddonAgent --training-config x1_long --scenario bot --etape E1`

---

## É9 — Second siège + second scénario {#e9}

**Suspendu** — après entraînement bot satisfaisant (jalon J4). Second scénario écrit par l'utilisateur (décision 2026-08-02).

→ `Documentation/Chantiers/v11/index_v11.md` §0.47

**2026-08-28 — levier d'exposition livré, indépendamment de É9.** `agent_seat_p2_ratio` rend pondérable le tirage de siège en entraînement (il était figé à 50/50 par la parité d'un hachage) ; réglage posé à 0.65 sur les six profils. Motivation : 12 points d'écart p1/p2 mesurés sur le run x1_long du 2026-08-12. L'évaluation garde son tirage équitable. É9 reste ouvert : il porte le second SCÉNARIO, que ceci ne traite pas. Effet à mesurer au prochain run — voir `Documentation/Reference/training/entrainement.md`.
