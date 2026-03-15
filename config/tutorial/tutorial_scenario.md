# Tutorial Scenario (grouped by stage)

But: tout regrouper par étape, au même endroit:
- config Step (référence humaine)
- config UI (référence humaine)
- textes FR/EN

---

## Runtime

- `enabled`: `true`
- `debugMode`: `false`

---

## Spotlight Catalog

- `board.activeUnit` : halo unité active sur le board
- `table.p1.nameM` : colonnes Name/M de la table P1
- `table.p1.rangedWeapons` : section armes de tir P1
- `table.p2.attributes` : section attributs unité P2
- `table.p2.unitRows` : lignes d'unités P2 (panneau droit)
- `board.unitRows` : unités P2 sur le board (cercles)
- `turnPhase.all` : highlights turn/phase tracker
- `panel.left` : panneau gauche (board area)
- `gamelog.last2Entries` : 2 lignes supérieures du game log (entrées les plus récentes)

---

## Fog Model

Le fog est décrit explicitement par zone:

- `fog.global`: voile sombre global du popup (`true|false`)
- `fog.leftPanel`: fog du panneau gauche (`true|false`)
- `fog.rightPanel`: fog du panneau droit (`true|false`)
- `fog.boardTopBand`: fog bande haute du board (`true|false`, utilisé sur certains stages)

Valeur par défaut (héritée si non précisée dans le stage):

- `fog.global = true`
- `fog.leftPanel = false`
- `fog.rightPanel = false`
- `fog.boardTopBand = false`

---

## Placeholder Glossary

Tokens utilisables dans `body_fr` / `body_en` et interprétés par le renderer frontend:

- `<cursor>`
  - Remplacé par l'icône curseur.
  - Peut être suivi d'une mini-icône de contexte selon la règle UI du stage (Intercessor, arme, etc.).

- `<Hex bleu foncé>` / `<Dark blue hex>`
  - Affiche un hexagone bleu foncé: ligne de vue directe.

- `<Hex bleu clair>` / `<Light blue hex>`
  - Affiche un hexagone bleu clair: ligne de vue partielle (couvert).

- `<icone termagant>` / `<Termagant icon>`
  - Affiche l'icône du Termagant (avec label).

- `<icone mort>` / `<death icon>`
  - Affiche l'icône d'événement de mort (même style que le game log).

- `<Range>`, `<A>`, `<BS>`, `<S>`, `<AP>`, `<DMG>`
  - Interprétés comme lignes d'attributs d'arme pour construire un tableau "attribut / description".

Notes:
- Les placeholders sont dépendants du renderer frontend (`TutorialOverlay`).
- Si un placeholder n'est pas reconnu, il reste affiché comme texte brut.

---

## Etape 1

### Stage `1-11`

**Step**
- trigger: `on_deploy`
- next_step: `Clic sur Suivant`
- layout: `Halo sur le panneau gauche (section tours). Popup centré.`

**UI**
- spotlightIds: `turnPhase.all`
- fog: `global=true`, `leftPanel=false`, `rightPanel=false`, `boardTopBand=false`

**Texts**
- title_fr: `Rounds`
- title_en: `Rounds`
- body_fr: `Une partie de Warhammer 40'000 se déroule en 5 rounds`
- body_en: `A game of Warhammer 40,000 is played over 5 rounds`

### Stage `1-12`

**Step**
- trigger: `on_deploy`
- next_step: `Clic sur Suivant`
- layout: `Halo sur le turn phase tracker (section tours). Popup centré.`

**UI**
- spotlightIds: `board.activeUnit` (hérité du `*`)
- fog: `global=true`, `leftPanel=false`, `rightPanel=false`, `boardTopBand=false`

**Texts**
- title_fr: `Tours`
- title_en: `Turns`
- body_fr: `Dans un round, chaque joueur joue son tour`
- body_en: `In each round, each player takes their turn`

### Stage `1-13`

**Step**
- trigger: `on_deploy`
- next_step: `Clic sur Suivant`
- layout: `Halo sur le panneau gauche (section tours). Popup centré.`

**UI**
- spotlightIds: `board.activeUnit` (hérité du `*`)
- fog: `global=true`, `leftPanel=false`, `rightPanel=false`, `boardTopBand=false`

**Texts**
- title_fr: `Phases`
- title_en: `Phases`
- body_fr: `Un tour est divisé en phases qui se déroulent séquentiellement`
- body_en: `A turn is divided into phases that run in sequence`

### Stage `1-14`

**Step**
- trigger: `phase_enter(move)`
- advance_on_unit_click: `true`
- popup_image: `/icons/Intercessor.webp`
- popup_first_line_with_icon: `true`
- next_step: `Clic sur l'Intercessor`
- layout: `Halo sur l'Intercessor + halo sur le bouton Move du turn phase tracker. Pas de bouton Suivant dans le popup.`

**UI**
- spotlightIds: `board.activeUnit`, `turnPhase.all`
- fog: `global=true`, `leftPanel=false`, `rightPanel=false`, `boardTopBand=false`

**Texts**
- title_fr: `1-14 Phase de Mouvement`
- title_en: `Movement phase`
- body_fr: `Intercessor (votre unité)

--------------------
<cursor> Cliquez sur l'Intercessor pour l'activer`
- body_en: `Intercessor (your unit)

--------------------
<cursor> Click on the Intercessor to activate it`

### Stage `1-15`

**Step**
- trigger: `phase_enter(move)`
- advance_on_move_click: `true`
- popup_show_move_hex: `true`
- next_step: `Clic sur une destination valide (hex vert) pour déplacer l'Intercessor`
- layout: `Deux fogs (2 bandes) sur la moitié supérieure du panneau gauche. Tableau d'unités déplié. Halo sur colonnes Name et M.`

**UI**
- spotlightIds: `table.p1.nameM`, `turnPhase.all`, `panel.left`
- fog: `global=true`, `leftPanel=true`, `rightPanel=false`, `boardTopBand=false`

**Texts**
- title_fr: `1-15 Phase de mouvement`
- title_en: `Movement phase`
- body_fr: `Les cases vertes sont des destinations valides (à une distance M maximum). 

--------------------
<cursor>Choisissez-en une pour déplacer votre Intercessor.`
- body_en: `The green hexes are valid destinations (up to M distance). 

--------------------
<cursor>Choose one to move your Intercessor.`

### Stage `1-16`

**Step**
- trigger: `phase_enter(move)`
- advance_on_move_click: `true`
- next_step: `Clic sur l'icône de l'Intercessor pour confirmer le déplacement`
- layout: `Suppression fog gauche. Table dépliée avec armes de tir. Halo sur RANGED WEAPON(S).`

**UI**
- spotlightIds: `table.p1.rangedWeapons`, `turnPhase.all`, `panel.left`
- fog: `global=true`, `leftPanel=false`, `rightPanel=false`, `boardTopBand=false`

**Texts**
- title_fr: `1-6 Phase de mouvement`
- title_en: `Movement phase`
- body_fr: `Les cases bleues représentent la ligne de vue de l'Intercessor.
<Hex bleu foncé> vue directe. 
<Hex bleu clair> vue partielle (la cible sur cette case bénéficie d'un couvert).
<icone termagant> 
La barre de points de vie du Termagant clignotte, indiquant que l'Intercessor a une ligne de vue dessus.

--------------------
<cursor>Cliquez à nouveau sur l'icône de l'Intercessor afin de valider son déplacement.`
- body_en: `The blue hexes represent the line of sight of the Intercessor.
<Dark blue hex> direct view. 
<Light blue hex> partial view (the target on this hex benefits from cover).
<Termagant icon> 
The hit points bar of the Termagant blinks, indicating that the Intercessor has line of sight on it.

--------------------
<cursor>Click again on the Intercessor icon to confirm the move.`

### Stage `1-21`

**Step**
- trigger: `phase_enter(shoot)`
- advance_on_unit_click: `true`
- hide_advance_icon: `true`
- popup_image: `/icons/Intercessor.webp`
- popup_show_green_circle: `true`
- popup_first_line_with_icon: `true`
- next_step: `Clic sur l'icône de l'Intercessor pour le sélectionner`
- layout: `Pas de fog à gauche. Fog à droite. Halo Move/Shoot + header Game Log + dernière ligne Game Log.`

**UI**
- spotlightIds: `table.p1.nameM`, `turnPhase.all`, `panel.left`, `gamelog.last2Entries`
- fog: `global=true`, `leftPanel=false`, `rightPanel=false`, `boardTopBand=false`

**Texts**
- title_fr: `1-21 Phase de Tir`
- title_en: `Shoot phase`
- body_fr: `Le cercle vert indique qu'une unité est activable.
Le mouvement est terminé, nous entrons dans la phase de tir.
L'intercessor est activable (icone entourée de vert). 

--------------------
<cursor>Cliquez sur l'icône de l'Intercessor pour l'activer.`
- body_en: `The green circle indicates that a unit is activable.
The movement phase is over, we enter the shoot phase. 
The Intercessor is activable (green circle). 

--------------------
<cursor>Click on the Intercessor icon to activate it.`

### Stage `1-22`

**Step**
- trigger: `phase_enter(shoot)`
- hide_advance_icon: `true`
- advance_on_weapon_click: `true`
- popup_image: `/icons/Termagant_red.webp`
- popup_position: `{ left: 32%, top: 12% }`
- next_step: `Clic sur l'icone du menu des armes à distance`
- layout: `Pas de fog gauche. Fog droite. Expand Intercessor + Termagant. Halos tracker + armes + attributs.`

**UI**
- spotlightIds: `table.p1.rangedWeapons`, `table.p2.attributes`, `turnPhase.all`, `panel.left`, `gamelog.last2Entries`
- allowedClickSpotlightIds: `board.activeUnit`, `table.p1.rangedWeapons`, `turnPhase.all`, `panel.left`
- fog: `global=true`, `leftPanel=false`, `rightPanel=false`, `boardTopBand=false`

**Texts**
- title_fr: `1-22 Menu de choix des armes`
- title_en: `Weapon choice menu`
- body_fr: `La ligne de vue réapparaît (en bleu), et le Termagant est une cible potentielle (sa barre de points de vie clignote).
<Hex bleu foncé> vue directe. 
<Hex bleu clair> vue partielle (une cible sur cette case bénéficie d'un couvert).
<icone termagant> 
La barre de points de vie du Termagant clignote, indiquant que l'Intercessor a une ligne de vue dessus.

--------------------
<cursor>Cliquez sur l'icone du menu des armes à distance.`
- body_en: `The line of sight reappears (in blue), and the Termagant is a potential target (its hit points bar blinks).
<Dark blue hex> direct view. 
<Light blue hex> partial view (a target on this hex benefits from cover).
<Termagant icon> 
The hit points bar of the Termagant blinks, indicating that the Intercessor has line of sight on it.

--------------------
<cursor>Click on the icon of the weapon choice menu.`

### Stage `1-23`

**Step**
- trigger: `phase_enter(shoot)`
- hide_advance_icon: `true`
- advance_on_weapon_click: `true`
- advance_on_weapon_name: `Bolt Rifle`
- popup_position: `{ left: 32%, top: 12% }`
- next_step: `Clic sur le Bolt Rifle dans le menu des armes à distance`
- layout: `Même layout que 1-22`

**UI**
- spotlightIds: `table.p1.rangedWeapons`, `table.p2.attributes`, `turnPhase.all`, `panel.left`, `gamelog.last2Entries`

**Texts**
- title_fr: `1-23 Choix de l'arme`
- title_en: `Weapon choice`
- body_fr/en: `texte complet inclus dans tutorial_scenario.yaml`

### Stage `1-24`

**Step**
- trigger: `phase_enter(shoot)`
- hide_advance_icon: `true`
- advance_on_weapon_click: `true`
- popup_image: `/icons/Termagant_red.webp`
- popup_position: `{ left: 32%, top: 12% }`
- next_step: `Le Termagant est mort.`
- layout: `Même layout que 1-22/1-23`

**UI**
- spotlightIds: `table.p1.rangedWeapons`, `table.p2.attributes`, `turnPhase.all`, `panel.left`, `gamelog.last2Entries`
- sequentialSubstepsUntilOrder: `25`
- fog: `global=true`, `leftPanel=false`, `rightPanel=false`, `boardTopBand=false`

**Texts**
- title_fr: `1-24 Choix de la cible`
- title_en: `Target choice`
- body_fr: `<cursor>Cliquez sur le termagant pour tirer dessus.`
- body_en: `<cursor>Click on the Termagant to shoot at it.`

### Stage `1-24-1`

**Step**
- trigger: `phase_enter(shoot)`
- hide_advance_icon: `true`
- advance_on_weapon_click: `true`
- popup_position: `{ left: 32%, top: 12% }`

**UI**
- afterCursorIcon: `none`
- popupImageGhost: `true`
- fog: `global=true`, `leftPanel=false`, `rightPanel=false`, `boardTopBand=false`
- hidePopupIllustrationBlock: `true`
- forceAdvanceOnWeaponClick: `false`
- spotlightIds: `table.p1.rangedWeapons`, `table.p2.attributes`, `turnPhase.all`, `panel.left`, `gamelog.last2Entries`

**Texts**
- title_fr: `1-24-1 Résolution d'un tir - Jet de Toucher`
- title_en: `Shooting resolution - Touch roll`
- body_fr/en: `texte complet inclus dans tutorial_scenario.yaml`

**Règle commune (`1-24-1` à `1-24-5`)**
- fog/halos inchangés sur toute la séquence : `même intensité que 1-25` (`fog global=true`, `rightPanel=false`), avec `spotlightIds=table.p1.rangedWeapons + table.p2.attributes + turnPhase.all + panel.left + gamelog.last2Entries`

### Stage `1-24-2`

**Step**
- trigger: `phase_enter(shoot)`
- hide_advance_icon: `true`
- advance_on_weapon_click: `true`
- popup_image: `/icons/Termagant_red.webp`
- popup_position: `{ left: 32%, top: 12% }`

**UI**
- afterCursorIcon: `none`
- popupImageGhost: `true`
- fog: `global=true`, `leftPanel=false`, `rightPanel=false`, `boardTopBand=false`
- hidePopupIllustrationBlock: `true`
- forceAdvanceOnWeaponClick: `false`
- spotlightIds: `table.p1.rangedWeapons`, `table.p2.attributes`, `turnPhase.all`, `panel.left`, `gamelog.last2Entries`

**Texts**
- title_fr: `1-24-2 Résolution d'un tir - Jet de Blessure`
- title_en: `Shooting resolution - Wound roll`
- body_fr/en: `texte complet inclus dans tutorial_scenario.yaml`

### Stage `1-24-3`

**Step**
- trigger: `phase_enter(shoot)`
- hide_advance_icon: `true`
- advance_on_weapon_click: `true`
- popup_image: `/icons/Termagant_red.webp`
- popup_position: `{ left: 32%, top: 12% }`

**UI**
- afterCursorIcon: `none`
- popupImageGhost: `true`
- fog: `global=true`, `leftPanel=false`, `rightPanel=false`, `boardTopBand=false`
- hidePopupIllustrationBlock: `true`
- forceAdvanceOnWeaponClick: `false`
- spotlightIds: `table.p1.rangedWeapons`, `table.p2.attributes`, `turnPhase.all`, `panel.left`, `gamelog.last2Entries`

**Texts**
- title_fr: `1-24-3 Résolution d'un tir - Jet de Sauvegarde`
- title_en: `Shooting resolution - Save roll`
- body_fr/en: `texte complet inclus dans tutorial_scenario.yaml`

### Stage `1-24-4`

**Step**
- trigger: `phase_enter(shoot)`
- hide_advance_icon: `true`
- advance_on_weapon_click: `true`
- popup_image: `/icons/Termagant_red.webp`
- popup_position: `{ left: 32%, top: 12% }`

**UI**
- afterCursorIcon: `none`
- popupImageGhost: `true`
- fog: `global=true`, `leftPanel=false`, `rightPanel=false`, `boardTopBand=false`
- hidePopupIllustrationBlock: `true`
- forceAdvanceOnWeaponClick: `false`
- spotlightIds: `table.p1.rangedWeapons`, `table.p2.attributes`, `turnPhase.all`, `panel.left`, `gamelog.last2Entries`

**Texts**
- title_fr: `1-24-4 Résolution d'un tir - Perte de Points de Vie`
- title_en: `Shooting resolution - Hit point loss`
- body_fr/en: `texte complet inclus dans tutorial_scenario.yaml`

### Stage `1-24-5`

**Step**
- trigger: `phase_enter(shoot)`
- hide_advance_icon: `true`
- advance_on_weapon_click: `true`
- popup_image: `/icons/Termagant_red.webp`
- popup_position: `{ left: 32%, top: 12% }`

**UI**
- afterCursorIcon: `none`
- popupImageGhost: `true`
- fog: `global=true`, `leftPanel=false`, `rightPanel=false`, `boardTopBand=false`
- hidePopupIllustrationBlock: `true`
- forceAdvanceOnWeaponClick: `false`
- spotlightIds: `table.p1.rangedWeapons`, `table.p2.attributes`, `turnPhase.all`, `panel.left`, `gamelog.last2Entries`

**Texts**
- title_fr: `1-24-5 Résolution d'un tir - Résumé`
- title_en: `Shooting resolution - Summary`
- body_fr/en: `texte complet inclus dans tutorial_scenario.yaml`

### Stage `1-25`

**Step**
- trigger: `phase_enter(shoot)`
- hide_advance_icon: `false`
- advance_on_weapon_click: `false`
- popup_position: `{ left: 32%, top: 12% }`
- next_step: `Le termagant est mort.`

**UI**
- spotlightIds: `table.p1.rangedWeapons`, `turnPhase.all`, `panel.left`, `gamelog.last2Entries`
- fog: `global=true`, `leftPanel=false`, `rightPanel=false`, `boardTopBand=false`

**Texts**
- title_fr: `1-25 Mort du termagant`
- title_en: `Termagant death`
- body_fr/en: `texte complet inclus dans tutorial_scenario.yaml`

---

## Etape 2

### Stage `2-11`

**Step**
- trigger: `phase_enter(move)`
- hide_advance_icon: `false`
- advance_on_weapon_click: `false`
- popup_position: `{ left: 58%, top: 25% }`
- next_step: `Clic sur Suivant`
- layout: `Fog droite + board haut, unit table P2 expanded, halos turn/P2/move + Hormagaunts.`

**UI**
- spotlightIds: `table.p2.unitRows`, `board.unitRows`, `turnPhase.all`, `panel.left`
- fog: `global=true`, `leftPanel=false`, `rightPanel=true`, `boardTopBand=true`

**Texts**
- title_fr: `2-11 Arrivée des Hormagaunts`
- title_en: `Hormagaunts arrival`
- body_fr/en: `texte complet inclus dans tutorial_scenario.yaml`

### Stage `2-12`

**Step**
- trigger: `phase_enter(shoot)`
- hide_advance_icon: `false`
- advance_on_weapon_click: `false`
- popup_position: `{ left: 58%, top: 25% }`
- next_step: `Clic sur Suivant`

**UI**
- spotlightIds: `table.p2.unitRows`, `board.unitRows`, `turnPhase.all`, `panel.left`
- fog: `global=true`, `leftPanel=false`, `rightPanel=false`, `boardTopBand=false`

**Texts**
- title_fr: `2-12 Phase de mouvement des Hormagaunts`
- title_en: `Movement phase of Hormagaunts`
- body_fr/en: `texte complet inclus dans tutorial_scenario.yaml`

### Stage `2-13`

**Step**
- trigger: `phase_enter(charge)`
- hide_advance_icon: `false`
- advance_on_weapon_click: `false`
- popup_position: `{ left: 58%, top: 25% }`
- next_step: `Clic sur Suivant`

**UI**
- phaseDisplayOverride: `shoot`
- spotlightIds: `table.p2.unitRows`, `board.unitRows`, `turnPhase.all`, `panel.left`
- fog: `global=true`, `leftPanel=false`, `rightPanel=false`, `boardTopBand=false`

**Texts**
- title_fr: `2-13 Phase de tir des Hormagaunts`
- title_en: `Shoot phase of Hormagaunts`
- body_fr/en: `texte complet inclus dans tutorial_scenario.yaml`

### Stage `2-14`

**Step**
- trigger: `phase_enter(fight)`
- hide_advance_icon: `false`
- advance_on_weapon_click: `false`
- popup_position: `{ left: 58%, top: 25% }`
- next_step: `Clic sur Suivant`

**UI**
- phaseDisplayOverride: `charge`
- spotlightIds: `turnPhase.all`, `panel.left`
- fog: `global=true`, `leftPanel=false`, `rightPanel=false`, `boardTopBand=false`

**Texts**
- title_fr: `2-14 Phase de charge des Hormagaunts`
- title_en: `Charge phase of Hormagaunts`
- body_fr/en: `texte complet inclus dans tutorial_scenario.yaml`

---

## Notes

- Ce document reste la référence humaine (édition/lecture).
- La source runtime active est `config/tutorial/tutorial_scenario.yaml`.
- Aucune donnée runtime JSON n'est conservée dans ce fichier.
- Toute valeur effective (rules/steps) vit dans `config/tutorial/tutorial_scenario.yaml`.

