// @vitest-environment jsdom
/**
 * T10 — TurnPhaseTracker : HUD — phase, tour, joueur, fin de phase.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TurnPhaseTracker } from "./TurnPhaseTracker";

afterEach(cleanup);

const PHASES = ["command", "move", "shoot", "charge", "fight"];
const BASE_PROPS = {
  currentTurn: 2,
  currentPhase: "move",
  phases: PHASES,
  maxTurns: 5,
  current_player: 1 as const,
};

// ---------------------------------------------------------------------------
// Rendu de base
// ---------------------------------------------------------------------------

describe("TurnPhaseTracker — tours", () => {
  it("rend maxTurns boutons de tour (1 à 5)", () => {
    render(<TurnPhaseTracker {...BASE_PROPS} />);
    for (let t = 1; t <= 5; t++) {
      expect(screen.getByRole("button", { name: String(t) })).toBeTruthy();
    }
  });

  it("le bouton du tour COURANT est en gras", () => {
    render(<TurnPhaseTracker {...BASE_PROPS} currentTurn={3} />);
    const btn = screen.getByRole("button", { name: "3" });
    expect(btn.style.fontWeight).toBe("bold");
  });

  it("les boutons de tour sont désactivés sans onTurnClick", () => {
    render(<TurnPhaseTracker {...BASE_PROPS} />);
    const btn = screen.getByRole("button", { name: "1" }) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });

  it("onTurnClick est appelé au clic sur le bouton de tour", () => {
    const onClick = vi.fn();
    render(<TurnPhaseTracker {...BASE_PROPS} onTurnClick={onClick} />);
    fireEvent.click(screen.getByRole("button", { name: "3" }));
    expect(onClick).toHaveBeenCalledWith(3);
  });
});

// ---------------------------------------------------------------------------
// Phases
// ---------------------------------------------------------------------------

describe("TurnPhaseTracker — phases", () => {
  it("rend tous les noms de phase capitalisés", () => {
    render(<TurnPhaseTracker {...BASE_PROPS} />);
    for (const phase of PHASES) {
      const label = phase.charAt(0).toUpperCase() + phase.slice(1);
      expect(screen.getByRole("button", { name: label })).toBeTruthy();
    }
  });

  it("onPhaseClick est appelé au clic sur une phase", () => {
    const onPhase = vi.fn();
    render(<TurnPhaseTracker {...BASE_PROPS} onPhaseClick={onPhase} />);
    fireEvent.click(screen.getByRole("button", { name: "Shoot" }));
    expect(onPhase).toHaveBeenCalledWith("shoot");
  });
});

// ---------------------------------------------------------------------------
// Joueur actif
// ---------------------------------------------------------------------------

describe("TurnPhaseTracker — joueurs", () => {
  it("rend P1 et P2 quand current_player est fourni", () => {
    render(<TurnPhaseTracker {...BASE_PROPS} current_player={2} />);
    expect(screen.getByRole("button", { name: "P1" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "P2" })).toBeTruthy();
  });

  it("n'affiche PAS P1/P2 si current_player est absent", () => {
    render(<TurnPhaseTracker currentTurn={1} currentPhase="move" phases={PHASES} maxTurns={5} />);
    expect(screen.queryByRole("button", { name: "P1" })).toBeNull();
    expect(screen.queryByRole("button", { name: "P2" })).toBeNull();
  });

  it("onPlayerClick est appelé au clic sur P2", () => {
    const onPlayer = vi.fn();
    render(<TurnPhaseTracker {...BASE_PROPS} current_player={1} onPlayerClick={onPlayer} />);
    fireEvent.click(screen.getByRole("button", { name: "P2" }));
    expect(onPlayer).toHaveBeenCalledWith(2);
  });
});

// ---------------------------------------------------------------------------
// Bouton End Phase
// ---------------------------------------------------------------------------

describe("TurnPhaseTracker — End Phase", () => {
  it("affiche le bouton End Phase quand onEndPhaseClick est fourni", () => {
    render(<TurnPhaseTracker {...BASE_PROPS} onEndPhaseClick={vi.fn()} />);
    expect(screen.getByRole("button", { name: "End Phase" })).toBeTruthy();
  });

  it("n'affiche PAS End Phase sans callback", () => {
    render(<TurnPhaseTracker {...BASE_PROPS} />);
    expect(screen.queryByRole("button", { name: "End Phase" })).toBeNull();
  });

  it("End Phase appelle onEndPhaseClick avec le joueur courant", () => {
    const onEnd = vi.fn();
    render(<TurnPhaseTracker {...BASE_PROPS} current_player={1} onEndPhaseClick={onEnd} />);
    fireEvent.click(screen.getByRole("button", { name: "End Phase" }));
    expect(onEnd).toHaveBeenCalledWith(1);
  });
});

// ---------------------------------------------------------------------------
// Bandeau fight : Pile-in et ATK
// ---------------------------------------------------------------------------

describe("TurnPhaseTracker — fight bandeaux", () => {
  it("showPileIn=true + onEndPileIn → bouton Pile-in visible", () => {
    render(<TurnPhaseTracker {...BASE_PROPS} showPileIn onEndPileIn={vi.fn()} />);
    expect(screen.queryByRole("button", { name: /Pile-in/i })).not.toBeNull();
  });

  it("clic Pile-in → onEndPileIn appelé", () => {
    const onEnd = vi.fn();
    render(<TurnPhaseTracker {...BASE_PROPS} showPileIn onEndPileIn={onEnd} />);
    fireEvent.click(screen.getByRole("button", { name: /Pile-in/i }));
    expect(onEnd).toHaveBeenCalledTimes(1);
  });

  it("showPileIn sans onEndPileIn → bouton Pile-in absent", () => {
    render(<TurnPhaseTracker {...BASE_PROPS} showPileIn />);
    expect(screen.queryByRole("button", { name: /Pile-in/i })).toBeNull();
  });

  it("showFightAtk + fightAtkPlayer=1 → bouton P1 ATK visible", () => {
    render(
      <TurnPhaseTracker
        {...BASE_PROPS}
        showFightAtk
        fightAtkPlayer={1}
        onFightAtk={vi.fn()}
      />
    );
    expect(screen.queryByRole("button", { name: "P1 ATK" })).not.toBeNull();
  });

  it("showFightAtk + fightAtkPlayer=2 → bouton P2 ATK visible", () => {
    render(
      <TurnPhaseTracker
        {...BASE_PROPS}
        showFightAtk
        fightAtkPlayer={2}
        onFightAtk={vi.fn()}
      />
    );
    expect(screen.queryByRole("button", { name: "P2 ATK" })).not.toBeNull();
  });

  it("clic ATK → onFightAtk appelé", () => {
    const onAtk = vi.fn();
    render(
      <TurnPhaseTracker
        {...BASE_PROPS}
        showFightAtk
        fightAtkPlayer={1}
        onFightAtk={onAtk}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: "P1 ATK" }));
    expect(onAtk).toHaveBeenCalledTimes(1);
  });

  it("showFightAtk + onSkipFight → bouton Skip visible", () => {
    render(
      <TurnPhaseTracker
        {...BASE_PROPS}
        showFightAtk
        fightAtkPlayer={1}
        onFightAtk={vi.fn()}
        onSkipFight={vi.fn()}
      />
    );
    expect(screen.queryByRole("button", { name: /Skip/i })).not.toBeNull();
  });

  it("clic Skip → onSkipFight appelé", () => {
    const onSkip = vi.fn();
    render(
      <TurnPhaseTracker
        {...BASE_PROPS}
        showFightAtk
        fightAtkPlayer={1}
        onFightAtk={vi.fn()}
        onSkipFight={onSkip}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: /Skip/i }));
    expect(onSkip).toHaveBeenCalledTimes(1);
  });
});

// ---------------------------------------------------------------------------
// Erreurs de props obligatoires
// ---------------------------------------------------------------------------

describe("TurnPhaseTracker — props invalides", () => {
  it("lève une erreur si phases est vide", () => {
    expect(() =>
      render(<TurnPhaseTracker currentTurn={1} currentPhase="move" phases={[]} maxTurns={5} />)
    ).toThrow("phases array is required");
  });

  it("lève une erreur si maxTurns est 0", () => {
    expect(() =>
      render(<TurnPhaseTracker currentTurn={1} currentPhase="move" phases={PHASES} maxTurns={0} />)
    ).toThrow("maxTurns must be a positive number");
  });
});
