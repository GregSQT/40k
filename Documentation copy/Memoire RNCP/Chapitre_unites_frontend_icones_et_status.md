# Unités côté frontend : icônes et indicateurs de statut

Ce chapitre décrit la représentation visuelle des unités sur le plateau de jeu : icônes principales, variantes selon le joueur, et logos ou badges ajoutés autour pour indiquer la phase en cours, les cibles, les actions possibles et les résultats de jets.

---

## 1. Icône principale de l’unité

Chaque unité est représentée par une **icône** (image) centrée sur l’hexagone.

- **Source** : le champ `ICON` de l’unité (chemin vers une image, en général `.webp`). Les assets sont servis depuis `public/icons/` ou des chemins fournis par la configuration de partie.
- **Variante joueur 2** : pour distinguer les équipes, les unités du joueur 2 utilisent une version à bordure rouge du même fichier : le chemin `.webp` est remplacé par `_red.webp` (ex. `unit.webp` → `unit_red.webp`).
- **Taille** : un facteur d’échelle optionnel `ICON_SCALE` par unité, sinon une valeur globale (`ICON_SCALE`) ; les dimensions sont dérivées du rayon de l’hexagone (`HEX_RADIUS`).
- **Fallback** : si `ICON` est absent, un texte de repli affiche le nom ou l’identifiant de l’unité (`DISPLAY_NAME`, `name` ou `U{id}`).

**États visuels particuliers de l’icône :**

- **Unité « fantôme »** (replay, déplacement en cours) : icône en semi-transparence avec teinte (couleur de mouvement).
- **Unité venant d’être « tuée »** : assombrissement (gris, alpha réduit) avant retrait du plateau.
- **Cible de tir non valide** : en phase de tir, les ennemis qui ne sont pas dans le pool de cibles valides sont affichés en grisé (alpha 0,5, teinte grise).
- **Aperçu d’action** : en mode aperçu de déplacement, l’icône peut être cliquable pour valider le déplacement ; en aperçu d’attaque, légère transparence.

---

## 2. Cercle d’éligibilité (activation)

Les unités **éligibles à l’activation** dans la phase courante sont entourées d’un **cercle vert** (couleur et épaisseur définies par des variables CSS, ex. `--eligible-color`, `--eligible-outline-width`).

- En phase **combat**, les unités ayant chargé ce tour et restant éligibles ont en plus un **cercle rouge** autour du vert pour les distinguer (priorité de charge).

Ce cercle est purement indicatif ; il ne modifie pas l’icône elle-même.

---

## 3. Barre de points de vie (PV)

Au-dessus de l’icône, une **barre de PV** affiche `HP_CUR` / `HP_MAX` (couleur, largeur et hauteur pilotées par des variables CSS). Elle n’est pas dessinée si `HP_MAX` est absent.

- **Cible de tir ou de combat en cours** : la barre peut s’agrandir et clignoter pour mettre en évidence l’unité ciblée et, en aperçu, refléter les dégâts potentiels (tir ou mêlée).
- **Multi-cibles** : lorsqu’une unité peut tirer sur plusieurs cibles, les barres des cibles valides peuvent participer à un effet de clignotement synchronisé.

---

## 4. Logos d’action (phase en cours et replay)

En **mode replay** (ou lorsque le moteur signale l’unité « en cours d’action »), de petits **logos d’action** sont affichés en bas à gauche de l’icône (décalage par rapport au centre de l’hexagone). Ils indiquent **quelle action** est en cours pour cette unité.

Tous ces logos sont des images PNG dans `public/icons/Action_Logo/` :

| Fichier | Rôle |
|--------|------|
| `2 - Movemement.png` | **Mouvement** : unité en train de se déplacer (cercle vert). |
| `3 - Shooting.png` | **Tir** : unité en train de tirer (carré fond jaune/orange). |
| `3-5 - Advance.png` | **Advance** : unité en train d’avancer après tir (carré fond orange). |
| `4 - Charge.png` | **Charge** : unité en train de charger (carré fond violet). |
| `5 - Fight.png` | **Combat** : unité en train de combattre (carré fond rouge, taille légèrement plus grande). |

Les formes (cercle ou carré arrondi) et les couleurs de fond sont configurées via des variables CSS (ex. `--icon-move-bg-color`, `--icon-shoot-bg-color`, `--icon-charge-bg-color`, `--icon-fight-bg-color`, etc.). Ces logos sont affichés **uniquement sur l’unité qui effectue l’action** (identifiée par `movingUnitId`, `shootingUnitId`, `chargingUnitId`, `fightingUnitId`, `advancingUnitId` selon la phase).

---

## 5. Indicateur de cible (cible de tir, charge ou combat)

Toute unité qui est **cible** d’une action (tir, charge ou combat) affiche un **indicateur de cible** : un carré arrondi coloré (ex. orange, variable `--icon-target-bg-color`) avec une icône **cible (🎯)** au centre, positionné en bas à gauche de l’icône.

- **Cas concernés** : cible du tireur (`shootingTargetId`), cible de la charge (`chargeTargetId`), cible du combat (`fightTargetId`). Un seul type d’indicateur est utilisé pour tous ces cas (pas d’icône « explosion » distincte dans l’implémentation actuelle).
- Taille et style du carré et de l’icône sont pilotés par des variables CSS (`--icon-target-size`, `--icon-target-square-size`, bordures, etc.).

---

## 6. Icônes d’action en phase de tir (Advance et choix d’arme)

En **phase de tir**, pour l’unité du joueur courant **actuellement en train de tirer** (active shooting unit), deux icônes **cliquables** peuvent apparaître au-dessus de la barre de PV, rendues soit dans le canvas PIXI soit en overlay DOM selon la configuration :

- **Advance** (`3-5 - Advance.png`) : proposer l’action « Advance » après le tir (affichée seulement si l’unité peut encore avancer et n’est pas adjacente à un ennemi).
- **Choix d’arme** (`3-1 - Gun_Choice.png`) : ouvrir le choix d’arme de tir (affichée si l’unité a au moins une arme utilisable dans ce contexte).

Ces icônes sont positionnées côte à côte (Advance à gauche, choix d’arme à droite) et n’apparaissent que pour l’unité activée au tir et dans le bon mode d’interface (aperçu tir / cible, etc.).

---

## 7. Badges de jet (charge et advance)

Pour les **jets de dés** affichés en replay (ou en direct), des **badges** sont dessinés à côté de l’unité concernée :

- **Jet de charge** : sur l’unité qui charge (`chargingUnitId`), un badge affiche le **résultat du jet 2D6** (nombre). Couleur du badge : vert (succès) ou rouge (échec), avec bordure et texte lisible.
- **Jet d’advance** : sur l’unité qui avance (`advancingUnitId`), un badge affiche de la même façon le **résultat du jet d’advance**.

Ces badges sont des formes (rectangle arrondi) + texte PIXI, positionnés en bas à droite de l’icône, avec un z-index élevé pour rester au-dessus des autres éléments.

---

## 8. Compteurs et autres éléments

- **Compteur d’attaques** : en phase combat, les unités en mêlée peuvent afficher le nombre d’**attaques restantes** (`ATTACK_LEFT`) dans un petit badge ou texte à côté de l’icône (pour l’unité en cours d’attaque ou les unités éligibles au combat).
- **Mode debug** : optionnellement, un **badge d’identifiant** (ID d’unité) peut être affiché au centre de l’icône pour le débogage.

---

## 9. Récapitulatif des sources d’images

| Type | Emplacement / origine |
|------|------------------------|
| Icône d’unité | `unit.ICON` (ex. `.webp`), variante `_red.webp` pour le joueur 2. |
| Logos d’action | `public/icons/Action_Logo/` : 1 - Command, 2 - Movemement, 3 - Shooting, 3-1 - Gun_Choice, 3-5 - Advance, 4 - Charge, 5 - Fight (tous en `.png`). |
| Indicateur de cible | Symbole texte 🎯 dans un carré coloré (pas d’image dédiée). |
| Formes (cercles, barres, badges) | Dessin PIXI (Graphics + Text), couleurs et tailles via variables CSS. |

---

*Ce chapitre peut être inséré dans le mémoire dans la section « Réalisations front-end » (par exemple après la description du plateau et des composants PIXI), pour documenter la partie « Unités : icônes et indicateurs de statut » côté interface.*
