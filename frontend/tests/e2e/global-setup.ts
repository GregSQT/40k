/**
 * Playwright global setup — Couche C.
 *
 * Lit le dernier token de session valide de config/users.db via Python,
 * puis enregistre un storageState (cookie + localStorage) réutilisé par
 * tous les tests pour éviter de passer par le formulaire de login.
 *
 * Requis : une session valide dans users.db (se connecter une fois via le front).
 */
import { execSync } from "child_process";
import * as fs from "fs";
import * as path from "path";
import { chromium } from "@playwright/test";

const ROOT = path.resolve(__dirname, "../../..");
const STORAGE_STATE = path.resolve(__dirname, "../../.auth/session.json");
const FRONTEND_URL = process.env.PW_FRONTEND_URL ?? "http://localhost:5175";
const SESSION_COOKIE_NAME = "w40k_session";

function readTokenFromDb(): { token: string; userId: number } {
  const script = `
import sqlite3, time, json, sys
db = '${ROOT}/config/users.db'
conn = sqlite3.connect(db)
cur = conn.cursor()
now = int(time.time())
cur.execute(
    "SELECT s.token, s.user_id FROM sessions s WHERE s.expires_at > ? ORDER BY s.created_at DESC LIMIT 1",
    (now,)
)
row = cur.fetchone()
if not row:
    print('ERROR: no valid session', file=sys.stderr)
    sys.exit(1)
print(json.dumps({'token': row[0], 'user_id': row[1]}))
conn.close()
`.trim();

  const out = execSync("python3", { input: script }).toString().trim();
  return JSON.parse(out);
}

function buildFakeAuthSession(userId: number): string {
  return JSON.stringify({
    user: { id: userId, login: "greg" },
    permissions: {
      game_modes: ["pvp", "pvp_test", "pve", "pve_test", "debug", "test"],
      options: { show_advance_warning: false, auto_weapon_selection: false },
    },
    default_redirect_mode: "pvp_test",
  });
}

export default async function globalSetup() {
  const { token, userId } = readTokenFromDb();

  // Crée le dossier .auth si nécessaire
  const authDir = path.dirname(STORAGE_STATE);
  if (!fs.existsSync(authDir)) {
    fs.mkdirSync(authDir, { recursive: true });
  }

  // Ouvre un contexte de navigateur temporaire pour écrire le storageState
  const browser = await chromium.launch();
  const context = await browser.newContext({
    baseURL: FRONTEND_URL,
  });

  // Injecte le cookie de session (HttpOnly ignoré en Playwright API direct)
  await context.addCookies([
    {
      name: SESSION_COOKIE_NAME,
      value: token,
      domain: new URL(FRONTEND_URL).hostname,
      path: "/",
      httpOnly: true,
      secure: false,
      sameSite: "Lax",
    },
  ]);

  // Ouvre une page pour pouvoir écrire dans localStorage
  const page = await context.newPage();
  await page.goto(FRONTEND_URL, { waitUntil: "domcontentloaded" });

  await page.evaluate(
    ({ key, value }: { key: string; value: string }) => {
      localStorage.setItem(key, value);
    },
    { key: "w40k_auth_session_v2", value: buildFakeAuthSession(userId) }
  );

  // Sauvegarde le storageState pour tous les tests
  await context.storageState({ path: STORAGE_STATE });
  await browser.close();
}
