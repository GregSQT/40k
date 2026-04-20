#!/usr/bin/env node
/**
 * Crée à la racine du dépôt un lien symbolique `node_modules` → `frontend/node_modules`.
 * Utile quand l’IDE ouvre le workspace à la racine : le serveur TypeScript remonte les dossiers
 * pour résoudre les paquets et trouve ainsi pixi.js-legacy, @pixi/*, etc.
 * Ne remplace pas un `node_modules` réel déjà présent (ex. autre outil npm à la racine).
 */
import { existsSync, lstatSync, symlinkSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = join(__dirname, "..");
const linkPath = join(root, "node_modules");
const frontendModules = join(root, "frontend", "node_modules");

if (!existsSync(frontendModules)) {
  console.warn("link-root-node-modules: skip (frontend/node_modules absent)");
  process.exit(0);
}

if (existsSync(linkPath)) {
  try {
    if (lstatSync(linkPath).isSymbolicLink()) {
      process.exit(0);
    }
  } catch {
    process.exit(0);
  }
  console.warn(
    "link-root-node-modules: skip (node_modules existe déjà et n'est pas un lien symbolique)"
  );
  process.exit(0);
}

try {
  const linkType = process.platform === "win32" ? "junction" : "dir";
  symlinkSync(frontendModules, linkPath, linkType);
} catch (err) {
  const msg = err instanceof Error ? err.message : String(err);
  console.warn(`link-root-node-modules: ${msg}`);
}
