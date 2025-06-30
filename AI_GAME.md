I want to develop a game based on warhammer 40k.
The player would play against an AI
For the AI training, I want it to train on the same scenaro as the game.
To evaluate the AI, i make it play vs a scripted bot.

Here are the main rules of the game, and behaviour for the ai :

MOVEMENT PHASE DEFINITION
I want a turn base game.
Eah turn is divided is phases : move, shoot, charge, attack.
Beginning of the turn :
At the beginning of its turn, all the units of the active player are surrounded by a green hexagon.

The move phase :
- Unit selection with left click
	- All the available move cells (calculated with MOVE attribute) are colored in green
		- Left  click on a non green cell : nothing happen
		- Left click on a green cell :
			- Move the unit to this cell
			- The cells at the RNG_RNG attribute distance are in red
				- Left click on the active unit : validate the mode, cancel colored cells, end of this unit's activation
				- Right click on the active unit : cancel the move, cancel colored cells, unselect the unit, back to unit
Once all the units have been moved this way, the active player's turn ends

SHOOTING PHASE
1. Two-Phase Turn Structure
    After all your units have moved, the game does not switch to the other player. Instead, it transitions to the shooting phase for your side.
    After the shooting phase is finished (all eligible units have shot or none can shoot), then the turn passes to the other player (who starts with their movement phase).
2. Movement Phase (as before)
    You can select and move each unit once per turn, as before.
    Only your units that haven’t moved are selectable (green outline).
3. Shooting Phase: Eligible Unit Selection
    Only your units that have at least one enemy within their RNG_RNG (shooting range) and haven’t shot yet are selectable (green outline).
    Units that cannot shoot (nobody in range, or already shot this phase) are not selectable.
4. Shooting Phase: Attack Preview Activation
    When you select an eligible shooter unit in the shooting phase, the board:
        Highlights the selected shooter.
        Highlights the enemy units in range (with a red outline/circle).
        Red-cells the hexes in range (if using the attackCells logic).
    This is the "attack preview" state.
5. Clicking on Enemy Units
    When you are in attack preview mode (after selecting a shooter):
        Clicking on an enemy unit within range will attempt to call the (currently unimplemented) onShoot action.
            You will see the visual feedback from your click handler (e.g., you can log something in the callback for now).
            No HP reduction or removal yet—that’s for the next patch.
6. Shooting Once per Shooter
    After a shooter has shot (if you later implement marking them as used), they will not be selectable again for shooting in this phase.


CHARGE PHASE
1. Eligibility for Selection (charge phase):
    A unit is eligible (gets green outline and is selectable) if:
        It has NOT already charged this phase.
        No enemy is adjacent to it.
        At least one enemy is within its MOVE range.
2. Highlight Eligible Units
    Only those eligible units get a green outline, and only those can be selected.
3. When a charger is selected (chargePreview):
    Red outline: all enemy units that are within the charger’s MOVE range.
    Orange cells:
        Any cell within the charger’s MOVE range,
        And that is adjacent (distance = 1) to at least one enemy within the charger’s MOVE range.
4. Clicking orange cell
    Moves the charging unit to that cell (just move, don’t immediately “end” or unselect).
    The user can continue with the activation.
5. Right click on the active unit
    Cancels the charge, returns to step 1 (unit is still eligible and re-selectable).
6. Left click on the active unit (after charge)
    Validates the charge: marks the unit as charged, unselects, and ends activation for this unit.
7. One charge per unit per phase


COMBAT PHASE
1. Eligibility for Selection (combat phase):
    A unit is eligible (gets green outline and is selectable) if:
        It has NOT already attacked this phase.
        Enemy is adjacent to it.
2. Highlight Eligible Units
    Only those eligible units get a green outline, and only those can be selected.
3. When a combat unit is selected:
    Red outline: all enemy units that are adjacent to it.
4. Right click on the active unit
    Cancels the attack, returns to step 1 (unit is still eligible and re-selectable).
5. Clicking enemy unit
    Reduces target unit's CUR_HP by the active unit's CC_DMG value.
7. One attack per unit per phase


---------------------------------------------------------------------------------------------------------------------

AI BEHAVIOUR

Sequential (Turn-based). 
First make the ranged units play. 
A unit will shoot in preference order : 
1 - the enemy unit at RNG_RNG range :
	- with the highest RNG_DMG or CC_DMG (pick the best of all the enemy units at range) score 
	- that one or more of our melee units can charge 
	- would not kill in 1 melee phase
2 - the enemy unit at RNG_RNG range :
	- with the highest RNG_DMG or CC_DMG (pick the best of all the enemy units at range) score 
	- can be killed by the active unit in 1 shooting phase
3 - the enemy unit at RNG_RNG range with the highest RNG_DMG or CC_DMG (pick the best of all the enemy units at range) score 
	- having the less HP
	- can be killed by the active unit in 1 shooting phase

For charge phase, a melee unit will charge :
1 - the enemy unit at MOVE range with 
	- the highest RNG_DMG or CC_DMG (pick the best of all the enemy units at range) score and :
	- can be killed by the active unit in 1 melee phase
2 - the enemy unit at MOVE range :
	-  with the highest RNG_DMG or CC_DMG (pick the best of all the enemy units at range) score and :
	- has the less current HP and 
	- its HPs >= the active unit's CC_DMG
3 - the enemy unit at MOVE range with the highest RNG_DMG or CC_DMG (pick the best of all the enemy units at range) score and :
	- has the less current HP

For charge phase, a ranged unit will charge :
1 - the enemy unit at MOVE range with the highest RNG_DMG or CC_DMG (pick the best of all the enemy units at range) score and :
	- has the highest current HP 
	- can be killed by the active unit in 1 melee phase

For melee phase, a unit will attack :
1 - the enemy unit with the highest RNG_DMG or CC_DMG (pick the best of all the enemy units at range) score and :
	- can be killed by the active unit in 1 melee phase
3 - the enemy unit with the highest RNG_DMG or CC_DMG (pick the best of all the enemy units at range) score and :
	- if there is more than one, target the enemy unit having the less current HP

