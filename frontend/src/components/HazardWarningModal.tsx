import { useEffect, useRef } from "react";
import TooltipWrapper from "./TooltipWrapper";

interface HazardWarningModalProps {
  onConfirm: () => void | Promise<void>;
  onCancel: () => void;
}

export function HazardWarningModal({ onConfirm, onCancel }: HazardWarningModalProps) {
  // Évite que le 2e clic d'un double-clic d'activation (qui ouvre le popup) ferme aussitôt le fond.
  const openedAtRef = useRef(0);
  useEffect(() => {
    openedAtRef.current = performance.now();
  }, []);

  const handleBackdropClick = () => {
    if (performance.now() - openedAtRef.current < 400) return;
    onCancel();
  };

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
      onClick={handleBackdropClick}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="hazard-warning-title"
        style={{
          width: "min(420px, calc(100vw - 32px))",
          background: "rgba(20, 20, 20, 0.98)",
          border: "2px solid #4caf50",
          borderRadius: "6px",
          boxShadow: "0 4px 12px rgba(0, 0, 0, 0.5)",
          padding: "16px 18px 14px 18px",
          color: "#fff",
        }}
        onClick={(event) => event.stopPropagation()}
        onKeyDown={(event) => event.stopPropagation()}
      >
        <h2
          id="hazard-warning-title"
          style={{
            margin: "0 0 16px 0",
            color: "#a5d6a7",
            background: "#0b410d",
            fontSize: "16px",
            fontWeight: 700,
            textTransform: "uppercase",
            letterSpacing: "0.5px",
            padding: "6px 10px",
            borderRadius: "4px",
          }}
        >
          ☢️ Desperate Escape !
        </h2>
        <p style={{ margin: 0, lineHeight: 1.5, fontSize: "14px", color: "#c8e6cf" }}>
          Le mouvement Desperate Escape que cette unité va effectuer entraine des{" "}
          <TooltipWrapper text="Roll D6 per model: on a 1-2, that unit suffers 1 (or 3 if it is a MONSTER/VEHICLE) mortal wounds.">
            <span
              style={{
                color: "#fde68a",
                fontWeight: 700,
                textDecoration: "underline",
                cursor: "help",
              }}
            >
              HAZARD ROLLS
            </span>
          </TooltipWrapper>
          . Continuer ?
        </p>
        <div
          style={{
            marginTop: "20px",
            display: "flex",
            justifyContent: "flex-end",
            gap: "10px",
          }}
        >
          <button
            type="button"
            onClick={onCancel}
            style={{
              padding: "10px 14px",
              border: "1px solid #41506b",
              borderRadius: "6px",
              background: "#0c3d14",
              color: "#e6e9f0",
              cursor: "pointer",
              fontSize: "14px",
            }}
          >
            Annuler
          </button>
          <button
            type="button"
            onClick={onConfirm}
            style={{
              padding: "10px 14px",
              border: "1px solid #4caf50",
              borderRadius: "6px",
              background: "#1b7a2b",
              color: "#eafff0",
              cursor: "pointer",
              fontSize: "14px",
              fontWeight: 700,
            }}
          >
            Confirmer
          </button>
        </div>
      </div>
    </div>
  );
}
