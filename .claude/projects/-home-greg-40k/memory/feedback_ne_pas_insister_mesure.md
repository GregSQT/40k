---
name: feedback_ne_pas_insister_mesure
description: Ne pas insister sur une mesure quand l'utilisateur a déjà tranché par contrainte technique
metadata:
  type: feedback
---

Ne pas proposer de rejouer une mesure ni rappeler une clôture formelle quand l'utilisateur a dit que c'est impossible (contrainte RAM, crash VM, etc.) ou que ça ne sert à rien dans le contexte actuel.

**Why:** Insister après un refus explicite fait perdre du temps et énerve — la décision est prise, pas à reposer en ARBITRAGE ni en SUITE.

**How to apply:** Si une mesure de clôture est bloquée par une contrainte technique nommée par l'utilisateur, archiver l'état « calibré, mesure non faite, raison : <contrainte> » et passer à la suite.
