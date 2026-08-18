# Security — Tâches ouvertes

**Étapes 1 à 7 livrées. Les quinze failles F1–F15 sont résolues.** Étape 8 partielle.

→ `Documentation/Implémentation/Security.md` (référence de conception)

⚠️ `Security.md` est à la racine d'`Documentation/Implémentation/` au lieu d'`A_faire/` — exception actée au bloc « Exceptions actées » de [ROADMAP_INDEX.md](ROADMAP_INDEX.md), seul endroit qui les recense. Elle reste valable : le fichier n'a pas bougé, et le chantier n'est pas clos tant que les trois actions ci-dessous ne le sont pas.

## Reste — une action

> **Note (2026-08-18) :** le déploiement local (action 2) a révélé un bug : waitress 3.0+ filtre
> `X-Forwarded-For` et `X-Forwarded-Proto` par défaut sans `trusted_proxy` configuré — Flask ne
> voyait jamais ces headers et `_client_ip()` levait 500 au premier login. Corrigé dans
> `services/wsgi.py` (`_resolve_waitress_trusted_proxy()` + paramètres `trusted_proxy`,
> `trusted_proxy_count`, `trusted_proxy_headers` ajoutés au `serve()`). 7 tests ajoutés.

1. ✅ **Mot de passe du compte `greg` — remplacé (2026-08-18).** Hash PBKDF2-SHA256 200 000 iter, sel aléatoire ; ancien hash trivial écrasé.
2. ✅ **Certificats TLS + `docker compose up` — validé localement (2026-08-18).** Vérifié :
   `whoami` → `appuser`, port 5001 injoignable hôte, HTTPS 200, HTTP → 301, en-têtes de sécurité
   (HSTS/X-Frame/nosniff/Referrer), cookie `Secure; HttpOnly; SameSite=Strict`, logout efface le
   cookie. UID `appuser` = 1000 = UID `greg` sur WSL2 → ownership OK sans `chown`. Certs
   auto-signés pour test local (`openssl req -x509 -newkey rsa:2048 -nodes -days 365 -keyout
   privkey.pem -out fullchain.pem -subj "/CN=localhost"`), Let's Encrypt pour le déploiement réel.
3. **Validation navigateur du cookie de session.** Le token n'est plus en `localStorage` (F13) :
   login, partie complète, déconnexion. Aucun test automatisé ne couvre le navigateur réel.

Puis, une fois la stack déployée : scan dynamique baseline OWASP ZAP (étape 8, optionnel).

## Dépendance

gzip/Brotli ([infra.md#gzip](infra.md#gzip)) se pose dans `frontend/nginx.conf`, désormais
versionné — c'est le bon moment, la configuration n'est plus écrite en `printf`.
