DRAW_WINNER: int = -1

PENDING_FIGHT_ALLOCATION_KEY = "pending_fight_allocation"
PENDING_SHOOT_ALLOCATION_KEY = "pending_shoot_allocation"
PENDING_HAZARD_ALLOCATION_KEY = "pending_hazard_allocation"
#: Resultat de fin d allocation (tir/combat) garde pendant l attribution HUMAINE des blessures
#: mortelles [HAZARDOUS] 24.15 : `W40KEngine._resume_after_hazard` le relit pour terminer
#: l activation avec son `shoot_result`.
PENDING_HAZARD_RESUME_RESULT_KEY = "pending_hazard_resume_result"
#: Fall back du pipeline squad (gym, bot PvE) suspendu par l attribution HUMAINE d une Deadly
#: Demise causee par le Desperate Escape (09.07), l unite survivant : `W40KEngine` y garde
#: l action semantique et l ancre d avant le hazard, et rejoue le mouvement a la reprise.
PENDING_GYM_FALL_BACK_RESUME_KEY = "pending_gym_fall_back_resume"
#: File des blessures mortelles a attribuer (06.02) hors lot d attaques : explosions Deadly
#: Demise §24.08 differees a la fin des attaques (25 DESTROYED), impact de charge, chaines.
#: Servie par `shared_utils.drain_mortal_wound_queue` aux points surs.
MORTAL_WOUND_QUEUE_KEY = "pending_mortal_wound_queue"
