--------------------------------------------------------------------------------------------------------
GAME MECHANISM
--------------------------------------------------------------------------------------------------------

I want to develop a game based on warhammer 40k.
The player would play against an AI
For the AI training, I want it to train on the same scenaro as the game.
To evaluate the AI, i make it play vs a scripted bot.

UNIT'S LIFE AND DEATH
At the start of the game, each unit's CUR_HP attribute is equal to its MAX_HP attribute.
When a unit takes damages, reduce its CUR_HP by the attacks damages (RNG_DMG in the shooting phase or CC_DMG in the attack phase)
When a unit's CUR_HP is reduced to 0, it is "dead" and can't be activated anymore.

TURN MECHANISM
Here are the main rules of the game, and behaviour for the ai :
Each player plays his turn, alternatively.
Each turn is divided consecutive phases : move -> Shoot -> Charge -> Combat
At the end of a player's combay phase, his turn ends, and the turn of the other player begins with his movement phase.

MOVEMENT PHASE DEFINITION
- The only available action in this phase is moving.
- No unit can move more than once per movement phase.
- No unit can move through enemy units
- No unit can move through walls
- Highlight Eligible Units
    	- Only the eligible units get a green outline, and only those can be selected.
- The active player activates his unit to move by left clicking on it.
	- All the available move cells (cells within the active unit's MOVE attribute) are colored in green
		- Left click on the unit : the unit won't move, it's move action is over.
		- Left  click on a non green cell : nothing happen
		- Left click on a green cell :
			- Move the unit to this cell
			- The cells at the RNG_RNG attribute distance are in red
				- Left click on the active unit : validate the move, cancel colored cells, end of this unit's activability for the phase
				- Right click on the active unit : cancel the move, cancel colored cells, unselect the unit, the unit is still selectable
Once all the units have been moved once this way, the active player's move phase ends, and his shooting phase starts

SHOOTING PHASE DEFINITION
- The only available action in this phase is shooting.
- No unit can shoot more than once per shooting phase.
- Highlight Eligible Units
	- Only the active's player units having at least one enemy within their RNG_RNG (shooting range) and haven’t shot yet are selectable (green outline).
	- Units that cannot shoot (nobody in range, or already shot this phase) are not selectable.
- Highlight Eligible Units
    	- Only those eligible units get a green outline, and only those can be selected.
- The active player activates one of his activable unit to shoot by left clicking on it.
	- The board highlights the selected shooter.
	- The hexes within the unit's RNG_RNG are highlighted in red.
	- The enemy units in range are highlighted with a red outline/circle
		- 1st left lick on an enemy unit withing RNG_RNG range : the target unit's hp bar is temporarily displayed bigger, and alternates its value with its future value after the shoot.
		For example, the target unit has CUR_HP = 4. If the RNG_DMG of the active unit is 1, the HP bar of the target will become bigger and switch every second from 4 CUR-HP to 3 CUR_HP
		- Seconde Left click on an enemy unit withing RNG_RNG range : The active unit shoot this enemy unit.
			- Reduce target enemy unit's CUR_HP by the active unit's RNG_DMG value
			- Cancel colored cells, unselect the unit, end of this unit's activability for the phase
		- Left click on the active unit : cancel the shoot, cancel colored cells, unselect the unit, end of this unit's activability for the phase
		- Right click on the active unit : cancel the shoot, cancel colored cells, unselect the unit, the unit is still selectable
		- Left click anywhere else on the board : Nothing happens


CHARGE PHASE DEFINITION
- The only available action in this phase is charge.
- No unit can charge more than once per charge phase.
- Eligibility for Selection (charge phase):
    	- A unit is eligible (gets green outline and is selectable) if:
        	- It has NOT already charged this phase.
        	- No enemy is adjacent to it.
        	- At least one enemy is within its MOVE range.
- Highlight Eligible Units
    	- Only those eligible units get a green outline, and only those can be selected.
- The active player activates one of his activable unit to charge by left clicking on it.
	- The board highlights the selected shooter.
	- The enemy units in range are highlighted with a red outline/circle
	- Color in orage the followig cells:
        	- Any cell within the charger’s MOVE range, AND that is adjacent (distance = 1) to at least one enemy within the charger’s MOVE range.
	- Left Click on an orange cell: Moves the active unit to that cell, cancel colored cells, unselect the unit, end of this unit's activability for the phase
	- Right click on the active unit : cancel the charge, cancel colored cells, unselect the unit, the unit is still selectable
	- left click on the active unit : cancel the charge, cancel colored cells, unselect the unit, end of this unit's activability for the phase


COMBAT PHASE DEFINITION
- The only available action in this phase is attack.
- No unit can attack more than once per combat phase.
- Highlight Eligible Units
	- Only the active's player units having at least one enemy adjacent (distance = 1) and haven’t attacked yet are selectable (green outline).
	- Units that cannot attack (no enemy unit adjacent, or it already attacked this phase) are not selectable.
- The active player activates one of his activable unit to attack by left clicking on it.
	- The board highlights the selected attacker.
	- The enemy units adjacent to the active unit are highlighted with a red outline/circle
- The active player activates one of his activable unit to attack by left clicking on it.
	- The board highlights the selected attacker.
	- The enemy units in range (adjacent) are highlighted with a red outline/circle
		- Left click on an adjacent enemy unit : The active unit attacks this enemy unit:
			- Reduce target enemy unit's CUR_HP by the active unit's CC_DMG value
			- Cancel colored cells, unselect the unit, end of this unit's activability for the phase
		- Left click on the active unit : cancel the attack, cancel colored cells, unselect the unit, end of this unit's activability for the phase
		- Left click anywhere else on the board : Nothing happens


--------------------------------------------------------------------------------------------------------
AI GUIDELINES
--------------------------------------------------------------------------------------------------------


All the units on the board must respect and follow the GAME MECHANISM as described.

here are behaviour an AI should follow :

MOVEMENT PHASE
Range Unit :
	- Avoid to be charged.
	- Will try to keep at least 1 enemy unit within it RNG_RNG range

Melee Units :
	Try to be in charge position.


SHOOTING PHASE
First make the ranged units play. 
A unit will shoot in priority order : 
1 - the enemy unit at RNG_RNG range :
	- with the highest RNG_DMG or CC_DMG (pick the best of all the enemy units at range) score
	- cannot be killed by the active unit in 1 shooting phase
	- that one or more of our melee units can charge 
	- would not be killed by our units that will be able to charge it during the attack phase
	- would be killed by one of our units during the attack phase if this unit shoots it
2 - the enemy unit at RNG_RNG range :
	- with the highest RNG_DMG or CC_DMG (pick the best of all the enemy units at range) score 
	- having the less HP
	- can be killed by the active unit in 1 shooting phase
3 - the enemy unit at RNG_RNG range :
	- with the highest RNG_DMG or CC_DMG (pick the best of all the enemy units at range) score 
	- can be killed by the active unit in 1 shooting phase
4 - the enemy unit at RNG_RNG range :
	- with the highest RNG_DMG or CC_DMG (pick the best of all the enemy units at range) score 
	- cannot be killed by the active unit in 1 shooting phase

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

CHARGE PHASE
Ranged unit will charg in priority ordere :
1 - the enemy unit at MOVE range with the highest RNG_DMG or CC_DMG (pick the best of all the enemy units at range) score and :
	- has the highest current HP 
	- can be killed by the active unit in 1 melee phase

COMBAT PHASE
A unit will attack in priority order :
1 - the enemy unit with the highest RNG_DMG or CC_DMG (pick the best of all the enemy units at range) score and :
	- can be killed by the active unit in 1 combat phase
2 - the enemy unit with the highest RNG_DMG or CC_DMG (pick the best of all the enemy units at range) The 'Enhance Prompt' button helps improve your prompt by providing additional context, clarification, or rephrasing. Try typing a prompt in here and clicking the button again to see how it works. @ @ @ @ @ @ @ @ @score and :
	- if there is more than one, target the enemy unit having the less current HP

