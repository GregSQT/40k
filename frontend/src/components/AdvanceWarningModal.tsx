import { useState } from "react";

interface AdvanceWarningModalProps {
  // dontRemind reflète l'état de la case "Ne plus me rappeler" au moment de l'action.
  onConfirm: (dontRemind: boolean) => void;
  onCancel: (dontRemind: boolean) => void;
}

export function AdvanceWarningModal({ onConfirm, onCancel }: AdvanceWarningModalProps) {
  const [dontRemind, setDontRemind] = useState(false);

  return (
    // biome-ignore lint/a11y/noStaticElementInteractions: backdrop modal — stopPropagation intentionnel
    <div
      role="presentation"
      style={{
        position: "fixed",
        inset: 0,
        backgroundColor: "rgba(0, 0, 0, 0.72)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 12000,
      }}
      onClick={() => onCancel(dontRemind)}
      onKeyDown={() => onCancel(dontRemind)}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="advance-warning-title"
        style={{
          width: "min(640px, calc(100vw - 32px))",
          backgroundColor: "#06120a",
          border: "2px solid #22c55e",
          borderRadius: "10px",
          boxShadow: "0 14px 40px rgba(0,0,0,0.55)",
          padding: "22px 24px 18px 24px",
          color: "#e5fbe9",
        }}
        onClick={(event) => event.stopPropagation()}
        onKeyDown={(event) => event.stopPropagation()}
      >
        <h2
          id="advance-warning-title"
          style={{ margin: "0 0 12px 0", color: "#86efac", fontSize: "30px" }}
        >
          Advance !
        </h2>
        <p style={{ margin: 0, lineHeight: 1.5, fontSize: "19px" }}>
          Vous êtes sur le point d&apos;effectuer une action Advance. Si vous la validez, cette
          unité ne pourra ni tirer ni charger jusqu&apos;à la fin de ce tour.
        </p>
        <div
          style={{
            marginTop: "20px",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "end",
          }}
        >
          <label style={{ display: "flex", alignItems: "center", gap: "10px", cursor: "pointer" }}>
            <input
              type="checkbox"
              checked={dontRemind}
              onChange={(event) => setDontRemind(event.target.checked)}
              style={{ width: "18px", height: "18px", cursor: "pointer" }}
            />
            <span style={{ fontSize: "16px", color: "#d1fae5" }}>Ne plus me rappeler</span>
          </label>
          <div style={{ display: "flex", gap: "10px" }}>
            <button
              type="button"
              onClick={() => onCancel(dontRemind)}
              style={{
                padding: "10px 14px",
                border: "1px solid #9ca3af",
                borderRadius: "6px",
                background: "rgba(31, 41, 55, 0.9)",
                color: "#f3f4f6",
                cursor: "pointer",
                fontSize: "16px",
              }}
            >
              Annuler l&apos;advance
            </button>
            <button
              type="button"
              onClick={() => onConfirm(dontRemind)}
              style={{
                padding: "10px 14px",
                border: "1px solid #22c55e",
                borderRadius: "6px",
                background: "#065f46",
                color: "#ecfdf5",
                cursor: "pointer",
                fontSize: "16px",
                fontWeight: 600,
              }}
            >
              Valider
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
