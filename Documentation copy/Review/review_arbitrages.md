# Arbitrages de code review

Append-only. Chaque entree attend une decision utilisateur.

- [2026-08-07T00:47:27] `engine/w40k_core.py` — Murs de bord perdus au rechargement depuis (au moins) l'introduction de _reload_scenario : tous les modeles existants ont ete entraines sur un plateau ou les demi-cases fantomes du bord bas etaient franchissables et transparentes au tir. Re-entrainement a arbitrer.

- [2026-08-07T01:11:29] `frontend/src/components/BoardPvp.tsx` — Bloc 8287-8301 : copie inline de buildEffectiveLosWallHexes qui MUTE boardConfig.wall_hexes (le helper, lui, copie). La mutation est redondante pour la LoS (buildLosPreviewFromSource rajoute deja les demi-cases) mais porteuse pour l'overlay de drag (l.11147) et le fingerprint du board statique (l.9508). Deduplication impossible sans verification runtime : a trancher quand BoardPvp sera la cible de review.
