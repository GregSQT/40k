/**
 * Badges d'état affichés en overlay (haut-gauche) sur l'illustration de l'unité.
 * Un badge n'apparaît que si au moins une figurine de l'escouade possède le statut.
 * Symboles dessinés en SVG, volontairement cohérents avec les badges PIXI du plateau
 * (œil barré → drawHiddenEyeBadge, flèche de repli → drawFledRunnerBadge).
 * Le tooltip (nom + règle 40K) est géré par TooltipWrapper au survol.
 */
import TooltipWrapper from "./TooltipWrapper";

interface UnitStatusBadgesProps {
  hidden: boolean;
  battleShocked: boolean;
  advanced: boolean;
  moved: boolean;
  charged: boolean;
  fellBack: boolean;
  stationary?: boolean;
}

/** Œil barré sur fond noir — caché (13.09). */
function HiddenIcon() {
  return (
    <svg className="unit-status-badge__svg" viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="10" fill="#000000" stroke="#b0b0b0" strokeWidth="1.5" />
      <path
        d="M3.8 12 Q12 6.8 20.2 12 Q12 17.2 3.8 12"
        fill="none"
        stroke="#c8c8c8"
        strokeWidth="2"
      />
      <circle cx="12" cy="12" r="2.6" fill="none" stroke="#c8c8c8" strokeWidth="2" />
      <line x1="3.8" y1="3.8" x2="20.2" y2="20.2" stroke="#000000" strokeWidth="4" />
      <line x1="3.8" y1="3.8" x2="20.2" y2="20.2" stroke="#c8c8c8" strokeWidth="2" />
    </svg>
  );
}

/** 🌀 sur fond noir — battle-shock (01.07), identique au logo sous la figurine. */
function BattleShockIcon() {
  return (
    <span
      className="unit-status-badge__svg"
      aria-hidden="true"
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        borderRadius: "50%",
        background: "#000000",
        boxSizing: "border-box",
        fontSize: "17px",
        lineHeight: 1,
      }}
    >
      🌀
    </span>
  );
}

/** Double chevron droit blanc sur fond orange — avance (09.06). */
function AdvancedIcon() {
  return (
    <svg className="unit-status-badge__svg" viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="10" fill="#ea580c" stroke="#7c2d12" strokeWidth="1.5" />
      <polyline
        points="7,7 12,12 7,17"
        fill="none"
        stroke="#ffffff"
        strokeWidth="2.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <polyline
        points="12,7 17,12 12,17"
        fill="none"
        stroke="#ffffff"
        strokeWidth="2.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/** Chevron droit simple blanc sur fond vert — mouvement (09.05). */
function MovedIcon() {
  return (
    <svg className="unit-status-badge__svg" viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="10" fill="#3fa32a" stroke="#1f5214" strokeWidth="1.5" />
      <polyline
        points="10,7 15,12 10,17"
        fill="none"
        stroke="#ffffff"
        strokeWidth="2.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/** Double chevron droit blanc sur fond violet — charge / Fights First (11.04). */
function ChargedIcon() {
  return (
    <svg className="unit-status-badge__svg" viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="10" fill="#7c3aed" stroke="#3b1a78" strokeWidth="1.5" />
      <polyline
        points="7,7 12,12 7,17"
        fill="none"
        stroke="#ffffff"
        strokeWidth="2.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <polyline
        points="12,7 17,12 12,17"
        fill="none"
        stroke="#ffffff"
        strokeWidth="2.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/** Chevron gauche simple blanc sur fond jaune — repli / fall-back (09.07). */
function FellBackIcon() {
  return (
    <svg className="unit-status-badge__svg" viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="10" fill="#f4c81f" stroke="#8a6d00" strokeWidth="1.5" />
      <polyline
        points="14,7 9,12 14,17"
        fill="none"
        stroke="#ffffff"
        strokeWidth="2.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/** Carré (stop) blanc sur fond gris — immobile (09.04). */
function StationaryIcon() {
  return (
    <svg className="unit-status-badge__svg" viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="10" fill="#808080" stroke="#3f3f3f" strokeWidth="1.5" />
      <rect x="8" y="8" width="8" height="8" rx="1.2" fill="#ffffff" />
    </svg>
  );
}

export default function UnitStatusBadges({
  hidden,
  battleShocked,
  advanced,
  moved,
  charged,
  fellBack,
  stationary,
}: UnitStatusBadgesProps) {
  const badges: Array<{ key: string; text: string; icon: React.ReactElement }> = [];

  if (hidden) {
    badges.push({
      key: "hidden",
      text: 'Caché — Visible que par les ennemis à portée de détection (15").',
      icon: <HiddenIcon />,
    });
  }
  if (battleShocked) {
    badges.push({
      key: "battle-shock",
      text: "Battle-shock — OC = « - », ne peut ni être ciblée par des stratagèmes ni entamer une action.",
      icon: <BattleShockIcon />,
    });
  }
  if (advanced) {
    badges.push({
      key: "advanced",
      text: "Avance — Ne peut ni charger ni faire une action.",
      icon: <AdvancedIcon />,
    });
  }
  if (moved) {
    badges.push({
      key: "moved",
      text: "Mouvement — S'est déplacée.",
      icon: <MovedIcon />,
    });
  }
  if (charged) {
    badges.push({
      key: "charged",
      text: "Charge — Combat en premier en phase de fight (Fights First).",
      icon: <ChargedIcon />,
    });
  }
  if (fellBack) {
    badges.push({
      key: "fell-back",
      text: "Fall-back — Ne peut ni tirer, ni charger, ni faire une action.",
      icon: <FellBackIcon />,
    });
  }
  if (stationary) {
    badges.push({
      key: "stationary",
      text: "Stationary — Ne s'est pas déplacée.",
      icon: <StationaryIcon />,
    });
  }

  if (badges.length === 0) {
    return null;
  }

  return (
    <div className="unit-status-badges">
      {badges.map((b) => (
        <TooltipWrapper key={b.key} text={b.text} className="unit-status-badge">
          {b.icon}
        </TooltipWrapper>
      ))}
    </div>
  );
}
