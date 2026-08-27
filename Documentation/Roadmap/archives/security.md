# Archives Security — Chantier clos (2026-08-19)

| Date | Étape | Détail |
|---|---|---|
| avant 2026-08-10 | Étapes 1, 2, 3, 6 | Livrées ; étape 5 partielle (durcir la stack Docker existante, pas la créer) ; détail dans `Documentation/Reference/infra/Security.md` |
| 2026-08-18 | Étapes 4, 5, 7 | F1–F15 toutes résolues ; validation locale Docker/TLS/cookie OK |
| 2026-08-19 | Étape 8 (action 3) | Validation navigateur : cookie `HttpOnly; SameSite:Strict`, pas de token en localStorage, cookie effacé au logout |

Chantier entièrement clos. Référence de conception : `Documentation/Reference/infra/Security.md`.

## Livraisons descendues de l'index (purge du 2026-08-27)

| Date | Chantier | Sujets · Fichier |
|---|---|---|
| 2026-08-19 | ✅ Chantier clos (2026-08-19) — F1–F15 résolues, validation navigateur OK, doc déplacé dans Implémenté/ | security · [archives/security.md](archives/security.md) |
