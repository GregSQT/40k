import { type FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { saveAuthSession } from "../auth/authStorage";

const API_BASE = "/api";

type AuthMode = "login" | "register";

interface LoginResponse {
  access_token: string;
  user: {
    id: number;
    login: string;
    profile: string;
  };
  permissions: {
    game_modes: string[];
    options: {
      show_advance_warning: boolean;
      auto_weapon_selection: boolean;
    };
  };
  default_redirect_mode: string;
  tutorial_completed: boolean;
}

export default function AuthPage() {
  const navigate = useNavigate();
  const [mode, setMode] = useState<AuthMode>("login");
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const executeLogin = async (userLogin: string, userPassword: string): Promise<LoginResponse> => {
    const loginResponse = await fetch(`${API_BASE}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ login: userLogin, password: userPassword }),
    });

    const text = await loginResponse.text();
    let loginPayload: LoginResponse & { error?: string };
    try {
      loginPayload = text ? (JSON.parse(text) as LoginResponse & { error?: string }) : ({} as LoginResponse);
    } catch {
      console.error("Login response (non-JSON):", text.slice(0, 200));
      throw new Error(
        "Le serveur a retourné une réponse invalide. Vérifiez que le backend est démarré et accessible."
      );
    }
    if (!loginResponse.ok) {
      const errorMessage = loginPayload?.error ?? "Echec de connexion";
      throw new Error(errorMessage);
    }

    return loginPayload as LoginResponse;
  };

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();

    const trimmedLogin = login.trim();
    if (!trimmedLogin) {
      setError("Le login est requis");
      return;
    }
    if (!password) {
      setError("Le mot de passe est requis");
      return;
    }

    setLoading(true);
    setError(null);

    try {
      if (mode === "register") {
        const registerResponse = await fetch(`${API_BASE}/auth/register`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ login: trimmedLogin, password }),
        });
        const text = await registerResponse.text();
        let registerPayload: { error?: string };
        try {
          registerPayload = text ? (JSON.parse(text) as { error?: string }) : {};
        } catch {
          console.error("Register response (non-JSON):", text.slice(0, 200));
          throw new Error(
            "Le serveur a retourné une réponse invalide. Vérifiez que le backend est démarré et accessible."
          );
        }
        if (!registerResponse.ok) {
          const errorMessage = registerPayload?.error ?? "Echec de creation du compte";
          throw new Error(errorMessage);
        }
      }

      const loginPayload = await executeLogin(trimmedLogin, password);
      saveAuthSession({
        token: loginPayload.access_token,
        user: loginPayload.user,
        permissions: loginPayload.permissions,
        default_redirect_mode: loginPayload.default_redirect_mode,
        tutorial_completed: loginPayload.tutorial_completed ?? false,
      });

      navigate(`/game?mode=${loginPayload.default_redirect_mode}`, { replace: true });
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Erreur inconnue");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "#0f172a",
        color: "white",
      }}
    >
      <form
        onSubmit={handleSubmit}
        style={{
          width: "100%",
          maxWidth: "420px",
          background: "#1f2937",
          border: "1px solid #374151",
          borderRadius: "10px",
          padding: "24px",
        }}
      >
        <h1 style={{ marginTop: 0, marginBottom: "16px", fontSize: "24px" }}>Connexion utilisateur</h1>

        <div style={{ display: "flex", gap: "10px", marginBottom: "16px" }}>
          <button
            type="button"
            onClick={() => setMode("login")}
            style={{
              flex: 1,
              padding: "10px",
              borderRadius: "6px",
              border: "1px solid #4b5563",
              background: mode === "login" ? "#2563eb" : "#111827",
              color: "white",
              cursor: "pointer",
            }}
          >
            Se connecter
          </button>
          <button
            type="button"
            onClick={() => setMode("register")}
            style={{
              flex: 1,
              padding: "10px",
              borderRadius: "6px",
              border: "1px solid #4b5563",
              background: mode === "register" ? "#2563eb" : "#111827",
              color: "white",
              cursor: "pointer",
            }}
          >
            Creer un compte
          </button>
        </div>

        <label htmlFor="auth-login" style={{ display: "block", marginBottom: "8px", color: "#d1d5db" }}>
          Login
        </label>
        <input
          id="auth-login"
          type="text"
          value={login}
          onChange={(event) => setLogin(event.target.value)}
          autoComplete="username"
          style={{
            width: "100%",
            marginBottom: "14px",
            padding: "10px",
            borderRadius: "6px",
            border: "1px solid #4b5563",
            background: "#111827",
            color: "white",
          }}
        />

        <label htmlFor="auth-password" style={{ display: "block", marginBottom: "8px", color: "#d1d5db" }}>
          Mot de passe
        </label>
        <input
          id="auth-password"
          type="password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          autoComplete={mode === "login" ? "current-password" : "new-password"}
          style={{
            width: "100%",
            marginBottom: "14px",
            padding: "10px",
            borderRadius: "6px",
            border: "1px solid #4b5563",
            background: "#111827",
            color: "white",
          }}
        />

        {error && (
          <div
            style={{
              marginBottom: "14px",
              padding: "10px",
              background: "#7f1d1d",
              border: "1px solid #991b1b",
              borderRadius: "6px",
              color: "#fecaca",
            }}
          >
            {error}
          </div>
        )}

        <button
          type="submit"
          disabled={loading}
          style={{
            width: "100%",
            padding: "12px",
            borderRadius: "6px",
            border: "none",
            background: loading ? "#4b5563" : "#16a34a",
            color: "white",
            cursor: loading ? "default" : "pointer",
            fontWeight: 600,
          }}
        >
          {loading
            ? "Traitement..."
            : mode === "login"
              ? "Se connecter"
              : "Creer le compte et se connecter"}
        </button>
      </form>
    </div>
  );
}
