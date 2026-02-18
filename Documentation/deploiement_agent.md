# Deploiement autonome de l'agent (training)

## 1) Objectif

Permettre a l'agent RL de placer ses propres unites en debut de partie, sans random placement, en restant conforme a:

- `Documentation/AI_TURN.md`
- `Documentation/AI_IMPLEMENTATION.md`
- `Documentation/DEPLOYMENT_ACTIVE_V1.md`

Le but de ce document est de definir une implementation operationnelle, simple et robuste pour le training.


## 2) Principes non negociables

1. **Single source of truth**
   - Un seul `game_state`.
   - Aucune copie locale de state pour "simuler" le deploiement.

2. **Activation sequentielle**
   - Une unite active a la fois.
   - Une action de deploiement par step.

3. **Aucun fallback anti-erreur**
   - Si une cle requise manque: erreur explicite.
   - Si une zone est invalide: erreur explicite.
   - Pas de valeur inventee pour "continuer quand meme".

4. **Fin de phase par eligibilite**
   - La phase `deployment` se termine uniquement quand il n'y a plus d'unites eligibles a deployer.


## 3) Scope V1 (training)

### Inclus

- Phase explicite `deployment` dans le flow.
- Action explicite `deploy_unit`.
- Masquage strict des actions invalides.
- Training PPO/MaskablePPO incluant cette phase.

### Exclu (V1)

- UX avancee (undo/redo, presets).
- Nouveau schema de config global.
- Optimisations "intelligentes" complexes de placement (meta-heuristiques lourdes).


## 4) Sources de donnees

Sans duplication de modele:

- Board: `config/board_config.json`
- Zones de deploiement: `config/deployment/hammer.json`
- Scenario: `scenario.json` (units, `deployment_zone`, `deployment_type`)


## 5) Architecture cible

## 5.1 Nouvelle phase du tour

Quand `deployment_type == "active"`:

- le match commence en `phase = "deployment"`
- les unites sont non placees au depart
- chaque unite doit etre placee via `deploy_unit`
- deploiement alterne:
  - Player 1 commence
  - puis alternance P1 <-> P2 tant que les deux ont des unites deployables
  - si un joueur n'a plus d'unites deployables, l'autre continue seul jusqu'a la fin
- puis transition vers la phase existante suivante (`command` ou `move` selon votre flow courant)

Quand `deployment_type != "active"`:

- conserver le comportement existant (pas de regression)

## 5.2 Etat minimal dans game_state

Ajouter une structure dediee:

- `phase: "deployment"` (pendant placement)
- `deployment_state`:
  - `current_deployer` (player actif)
  - `deployable_units_by_player`
  - `deployed_units` (set d'IDs)
  - `deployment_pools_by_player` (hex autorises)
  - `deployment_order_mode` = `alternated_p1_start`
  - `deployment_complete` (bool)

Recommandation V1:

- unites non placees avec `col = -1`, `row = -1` tant qu'elles ne sont pas deployees
- une unite est "placee" si son ID est dans `deployed_units`


## 6) Action et validation

## 6.1 Action semantique

Action principale:

- `deploy_unit { unitId, col, row }`

Actions optionnelles en V1:

- `confirm_deployment { player }` (utile cote UI)
- `undeploy_unit { unitId }` (optionnel, peut rester hors V1)

## 6.2 Regles de validation strictes

Toute tentative de placement doit verifier:

1. unite appartient a `current_deployer`
2. unite est encore deployable (pas deja dans `deployed_units`)
3. hex dans les bornes du board
4. hex non wall
5. hex dans `deployment_pools_by_player[current_deployer]`
6. hex non occupe
7. restrictions supplementaires scenario (si definies)

En cas d'echec:

- erreur explicite avec message actionnable
- pas de correction implicite du `col,row`
- pas de replacement automatique ailleurs


## 7) Flow de phase deployment

Pseudo-flow cible:

1. `deployment_start`
   - construit les pools par joueur
   - initialise `deployment_state`
2. boucle d'activation:
   - selection d'une unite deployable du joueur actif
   - action `deploy_unit`
   - update state (position + marquage deploye)
3. fin de sous-phase joueur:
   - si les deux joueurs ont des unites deployables: alterner de joueur
   - si un seul joueur a encore des unites deployables: il continue seul
4. fin globale deployment:
   - si toutes les unites de tous les joueurs sont deployees:
     - `deployment_complete = true`
     - transition vers phase suivante

Important:

- Aucune activation automatique d'une unite non choisie.
- Une action invalide ne doit pas casser la phase.

## 7.1 Alignement UI (mode test)

En mode test, l'affichage deployment doit rester coherent avec `DEPLOYMENT_ACTIVE_V1.md`:

- rosters deployables des 2 joueurs visibles en parallele
- chaque roster a un bouton `reduire/etendre`
- ordre visuel explicite (du haut vers le bas):
  1. roster deployable Player 1
  2. roster deployable Player 2
  3. `UnitStatusTable` Player 1
  4. `UnitStatusTable` Player 2
- contraintes de position:
  - roster Player 1 au-dessus de `UnitStatusTable` Player 2
  - roster Player 2 entre roster Player 1 et `UnitStatusTable` Player 1


## 8) Impact sur le training RL

Le deploiement ajoute une decision tactique precoce. Cela augmente la difficulte:

- espace d'action plus grand
- credit assignment plus long (qualite du deploiement visible plus tard)
- variance de reward plus elevee

Consommation training attendue:

- souvent +50% a +200% de timesteps selon scenario et shaping


## 9) Design RL recommande (V1)

## 9.1 Action space

Deux options:

### Option A (simple, recommandee V1)

- garder un action space discret indexe
- mapper l'action vers `(unit_slot, hex_slot)` valide pour la phase deployment
- utiliser mask pour invalider tout le reste

Avantage:

- integration rapide avec MaskablePPO

### Option B (plus complexe)

- action factorisee (choix unite + choix case en deux sous-decisions)

Inconvenient:

- plus de code, plus de surface bug, pas necessaire en V1

## 9.2 Action mask (critique)

Le masque doit:

- autoriser uniquement les placements legaux
- interdire toutes les actions des autres phases
- etre recalcule a chaque step deployment

Regle cle:

- "illegal action impossible" via mask, pas via penalites massives en boucle


## 10) Observation pour le deploiement

Ajouter des features minimales dediees:

- unite active a deployer (type, role, portee utile, mobilite)
- occupancy map locale ou slots syntheses
- info zone de deploiement autorisee
- proximite objectifs/couvertures/dangers (si disponible)

Principes:

- rester compact (eviter explosion de dimension)
- coherence avec observation existante
- pas de duplication incoherente d'etat


## 11) Reward design (sans tricher)

Priorite:

1. reward principal sur resultat global (win/loss + performance)
2. shaping leger et explicite pour accelerer l'apprentissage

Exemples de shaping raisonnables:

- bonus faible si unite placee dans zone legale utile tactiquement
- malus si deploiement expose une unite fragile sans raison tactique

Interdits:

- heuristiques cachees contradictoires
- fallback reward pour masquer des erreurs de validation

Important:

- toutes les constantes reward doivent venir des configs, pas hardcodees


## 12) Curriculum d'entrainement conseille

Pour stabiliser l'apprentissage:

1. **Etape 1**: apprendre deploiement seul sur scenarios simples
2. **Etape 2**: deploiement + phases de combat simplifiees
3. **Etape 3**: match complet avec deploiement actif

Ajouter progressivement:

- taille d'armee
- complexite terrain
- diversite scenario


## 13) Configuration training

Verifier/ajouter dans la config d'agent:

- flag activation deploiement actif
- hyperparams PPO (n_steps, batch_size, lr, gamma, clip_range)
- coefficients reward deployment (si shaping)
- scenario set dedie au curriculum

Bonnes pratiques:

- commencer avec config stable existante
- changer peu de parametres a la fois
- journaliser metrics deployment separement des metrics combat


## 14) Metriques a suivre

Metriques minimales:

- taux de placements valides
- nb moyen d'actions deployment par episode
- temps moyen de fin de deployment
- winrate avec deployment actif
- impact sur reward total et variance

Metriques de diagnostic:

- distribution des zones choisies
- repetabilite des placements par type d'unite
- correlation placement initial -> survie / dommages infliges


## 15) Plan d'implementation concret (ordre conseille)

1. **Engine phase**
   - ajouter la phase `deployment` et ses transitions
2. **State**
   - ajouter `deployment_state` et initialisation stricte
3. **Handlers**
   - implementer `deployment_start` et `deploy_unit`
4. **Action decoder + mask**
   - branch deployment + mapping action -> placement
5. **Observation/reward**
   - enrichissement minimal pour deployment
6. **Training integration**
   - activer phase dans env RL + config
7. **Validation**
   - tests unitaires et scenarios end-to-end


## 16) Strategie de tests

## 16.1 Tests unitaires

- construction correcte des pools de deploiement
- refus des placements invalides (hors zone, wall, occupe, hors board)
- acceptance des placements valides
- alternance correcte (P1 commence puis alternance)
- continuation solo correcte quand un joueur n'a plus d'unites deployables
- transition joueur et fin de phase correctes

## 16.2 Tests integration env

- `reset()` en deployment quand `deployment_type=active`
- sequence complete jusqu'a phase suivante sans erreur
- mask legal a chaque step
- ordre de deploiement respecte (P1 start puis alternance)
- fin de deployment correcte quand un roster est vide avant l'autre

## 16.4 Tests UI mode test (coherence documentaire)

- affichage simultane des rosters deployables P1/P2
- bouton reduire/etendre fonctionne pour chaque roster
- ordre visuel respecte:
  - roster P1
  - roster P2
  - `UnitStatusTable` P1
  - `UnitStatusTable` P2

## 16.3 Tests training smoke

- run court de training (quelques episodes)
- verifier absence de boucle d'actions invalides
- verifier progression metriques deployment


## 17) Risques principaux et mitigation

1. **Explosion espace d'action**
   - mitigation: mapping simple + masque strict

2. **Convergence lente**
   - mitigation: curriculum + shaping leger + scenarios plus simples au debut

3. **Incoherence UI/API/engine**
   - mitigation: chemin unique `deploy_unit` pour tous les modes

4. **Bugs de transition de phase**
   - mitigation: tests explicites sur criteres de fin d'eligibilite


## 18) Checklist de conformite avant merge

- [ ] `game_state` unique, pas de copie
- [ ] phase deployment sequentielle (1 unite / 1 action)
- [ ] fin de phase basee sur eligibilite, pas sur compteur arbitraire
- [ ] alternance deployment: P1 commence puis alternance tant que possible
- [ ] continuation solo correcte quand un joueur n'a plus d'unites deployables
- [ ] erreurs explicites pour toute donnee manquante/invalide
- [ ] aucun fallback/workaround pour "faire passer"
- [ ] constantes de reward et seuils en config
- [ ] action mask deployment strictement legal
- [ ] UI mode test alignee:
  - rosters P1/P2 visibles en parallele
  - boutons reduire/etendre par roster
  - ordre visuel explicite respecte
- [ ] tests unitaires + integration + smoke training verts


## 19) Conclusion

Implementer le deploiement autonome en training est une complexite **moyenne**:

- faisable sans refonte massive
- impact reel sur convergence RL
- valeur tactique forte si observation/mask/reward sont bien calibres

La cle en V1 est de rester minimal:

- phase claire
- validation stricte
- masque fiable
- curriculum progressif

