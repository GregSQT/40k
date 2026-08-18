# Security — Tâches ouvertes

**Étapes 1 à 7 livrées. Les quinze failles F1–F15 sont résolues.** Étape 8 partielle.

→ `Documentation/Implémentation/Security.md` (référence de conception)

⚠️ `Security.md` est à la racine d'`Documentation/Implémentation/` au lieu d'`Implémenté/` — 3ᵉ exception assumée, inchangée.

## Reste — aucune ligne de code, trois actions de déploiement

1. **Mot de passe du compte `greg` (bloquant).** L'audit de l'étape 8
   (`python3 scripts/auth_journal.py accounts`, exécuté le 2026-08-18) a trouvé le mot de passe
   égal au login, sur le **seul** compte de la base, de profil `admin`. Non corrigé par l'agent :
   `config/users.db` est un fichier protégé et le remplacement est une décision utilisateur.
   `UPDATE users SET password_hash = ?` avec la sortie de
   `shared.auth_credentials.hash_password("<nouveau>")`.
2. **Certificats TLS + `docker compose up`.** `frontend/nginx.conf` attend `fullchain.pem` et
   `privkey.pem` sous `/etc/nginx/certs` (montés depuis `SYNO_TLS_PATH`, jamais cuits dans
   l'image). nginx refuse de démarrer sans eux, volontairement. Vérifier ensuite : HTTPS servi,
   HTTP redirigé, port 5001 injoignable depuis l'hôte, `docker compose exec backend whoami` →
   `appuser`, healthcheck vert. ⚠️ Les montages hôte (`SYNO_RUNTIME_PATH`, `users.db`) doivent
   appartenir à l'UID d'`appuser` depuis le retrait de `user: "0:0"`.
3. **Validation navigateur du cookie de session.** Le token n'est plus en `localStorage` (F13) :
   login, partie complète, déconnexion. Aucun test automatisé ne couvre le navigateur réel.

Puis, une fois la stack déployée : scan dynamique baseline OWASP ZAP (étape 8, optionnel).

## Dépendance

gzip/Brotli ([infra.md#gzip](infra.md#gzip)) se pose dans `frontend/nginx.conf`, désormais
versionné — c'est le bon moment, la configuration n'est plus écrite en `printf`.
