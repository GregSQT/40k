// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { HazardWarningModal } from "./HazardWarningModal";

afterEach(cleanup);

describe("HazardWarningModal", () => {
  it("affiche le titre et le texte de la modale", () => {
    render(<HazardWarningModal onConfirm={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.getByRole("dialog")).toBeTruthy();
    expect(screen.getByRole("heading", { name: /Desperate Escape/i })).toBeTruthy();
    expect(screen.getByText(/HAZARD ROLLS/)).toBeTruthy();
  });

  it("appelle onCancel au clic sur Annuler", () => {
    const onCancel = vi.fn();
    render(<HazardWarningModal onConfirm={vi.fn()} onCancel={onCancel} />);
    fireEvent.click(screen.getByRole("button", { name: /Annuler/i }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("appelle onConfirm au clic sur Confirmer", () => {
    const onConfirm = vi.fn();
    render(<HazardWarningModal onConfirm={onConfirm} onCancel={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /Confirmer/i }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("n'appelle pas onCancel si le clic sur le fond survient < 400 ms après l'ouverture", () => {
    const onCancel = vi.fn();
    // Figer performance.now à 0 pendant le rendu → openedAt = 0
    vi.spyOn(performance, "now").mockReturnValue(0);
    render(<HazardWarningModal onConfirm={vi.fn()} onCancel={onCancel} />);
    // Simuler 100 ms écoulées au moment du clic → 100 - 0 < 400 → onCancel non appelé
    vi.spyOn(performance, "now").mockReturnValue(100);
    fireEvent.click(screen.getByRole("presentation"));
    expect(onCancel).not.toHaveBeenCalled();
    vi.restoreAllMocks();
  });

  it("appelle onCancel si le clic sur le fond survient >= 400 ms après l'ouverture", () => {
    const onCancel = vi.fn();
    // Figer performance.now à 0 pendant le rendu → openedAt = 0
    vi.spyOn(performance, "now").mockReturnValue(0);
    render(<HazardWarningModal onConfirm={vi.fn()} onCancel={onCancel} />);
    // Simuler 500 ms écoulées au moment du clic → 500 - 0 >= 400 → onCancel appelé
    vi.spyOn(performance, "now").mockReturnValue(500);
    fireEvent.click(screen.getByRole("presentation"));
    expect(onCancel).toHaveBeenCalledTimes(1);
    vi.restoreAllMocks();
  });
});
