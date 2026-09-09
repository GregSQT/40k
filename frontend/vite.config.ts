import react from "@vitejs/plugin-react";
// `defineConfig` vient de `vitest/config` et non de `vite` : c'est la MÊME fonction, augmentée du
// champ `test`. Importée depuis `vite`, la section ci-dessous ne serait pas typée et `tsc` la
// refuserait — le champ n'existe pas sur la config de Vite.
import { defineConfig } from "vitest/config";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  optimizeDeps: {
    exclude: ["wasm-los-pkg"],
  },
  server: {
    host: "0.0.0.0", // Listen on all network interfaces (IPv4 and IPv6)
    port: 5175,
    strictPort: true,
    open: false, // Ne pas ouvrir automatiquement le navigateur
    proxy: {
      "/api": {
        // Cible PARAMÉTRABLE, défaut inchangé pour le développement (`npm run dev` → 5001).
        //
        // Mesuré le 2026-09-09, à la première exécution réelle de la couche C : le script
        // `scripts/front_test_all.sh` démarre un backend de test sur 5098 et un Vite sur 5198,
        // mais le navigateur passait par CE proxy, donc tapait 5001 — un port où rien n'écoute
        // pendant les tests. Tous les tests E2E échouaient sur `ECONNREFUSED 127.0.0.1:5001`,
        // quel que soit l'état de l'application. `PW_BASE_URL` ne corrigeait rien : il ne sert
        // qu'aux appels que Playwright émet lui-même, jamais à ceux de la page.
        target: process.env.VITE_API_TARGET ?? "http://localhost:5001",
        changeOrigin: true,
      },
    },
  },
  test: {
    // POURQUOI CETTE SECTION EXISTE (mesuré le 2026-09-09).
    //
    // Sans elle, `npx vitest run` — la couche B de `scripts/front_test_all.sh` — applique le motif
    // de collecte PAR DÉFAUT de Vitest, qui ramasse tout `**/*.{test,spec}.?(c|m)[jt]s?(x)` du
    // dossier. Il attrapait donc `tests/e2e/smoke.spec.ts`, un fichier PLAYWRIGHT, dont le premier
    // import est `@playwright/test` : la couche B rendait « 1 failed | 36 passed » à chaque
    // exécution, quel que soit l'état du code testé. Elle était rouge PAR CONSTRUCTION, et le
    // script qui l'orchestre ne pouvait donc jamais passer.
    //
    // Les deux harnais ne se recouvrent pas et ne partagent aucun runner : vitest tient les
    // fonctions pures et les composants sous jsdom, Playwright tient le parcours navigateur.
    // La frontière est le RÉPERTOIRE, pas l'extension — d'où un `include` ancré sur `src/`
    // plutôt qu'un `exclude` qui listerait les fichiers e2e un par un et oublierait le suivant.
    include: ["src/**/*.test.{ts,tsx}"],
    // `node_modules` et `dist` sont dans les exclusions par défaut de Vitest, mais poser un
    // `include` ne les réactive pas : cette ligne les nomme pour que la règle reste lisible sans
    // avoir à connaître les défauts du runner, et y ajoute `tests/` — le domaine de Playwright.
    exclude: ["node_modules/**", "dist/**", "tests/**"],
  },
});
