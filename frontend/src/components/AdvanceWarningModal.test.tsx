// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AdvanceWarningModal } from "./AdvanceWarningModal";

afterEach(cleanup);

describe("AdvanceWarningModal", () => {
  it("affiche le titre et le texte de la modale", () => {
    render(<AdvanceWarningModal onConfirm={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.getByRole("dialog")).toBeTruthy();
    expect(screen.getByText(/Advance !/)).toBeTruthy();
    expect(screen.getByText(/Ne plus me rappeler/)).toBeTruthy();
  });

  it("appelle onCancel(false) quand la case n'est pas cochée", () => {
    const onCancel = vi.fn();
    render(<AdvanceWarningModal onConfirm={vi.fn()} onCancel={onCancel} />);
    fireEvent.click(screen.getByRole("button", { name: /Annuler/i }));
    expect(onCancel).toHaveBeenCalledWith(false);
  });

  it("appelle onConfirm(false) quand la case n'est pas cochée", () => {
    const onConfirm = vi.fn();
    render(<AdvanceWarningModal onConfirm={onConfirm} onCancel={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /Valider/i }));
    expect(onConfirm).toHaveBeenCalledWith(false);
  });

  it("appelle onCancel(true) quand la case 'Ne plus me rappeler' est cochée", () => {
    const onCancel = vi.fn();
    render(<AdvanceWarningModal onConfirm={vi.fn()} onCancel={onCancel} />);
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: /Annuler/i }));
    expect(onCancel).toHaveBeenCalledWith(true);
  });

  it("appelle onConfirm(true) quand la case 'Ne plus me rappeler' est cochée", () => {
    const onConfirm = vi.fn();
    render(<AdvanceWarningModal onConfirm={onConfirm} onCancel={vi.fn()} />);
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: /Valider/i }));
    expect(onConfirm).toHaveBeenCalledWith(true);
  });

  it("appelle onCancel(false) au clic sur le fond (backdrop)", () => {
    const onCancel = vi.fn();
    render(<AdvanceWarningModal onConfirm={vi.fn()} onCancel={onCancel} />);
    fireEvent.click(screen.getByRole("presentation"));
    expect(onCancel).toHaveBeenCalledWith(false);
  });

  it("la case est décochée par défaut (réinitialisation à chaque montage)", () => {
    render(<AdvanceWarningModal onConfirm={vi.fn()} onCancel={vi.fn()} />);
    const checkbox = screen.getByRole("checkbox") as HTMLInputElement;
    expect(checkbox.checked).toBe(false);
  });
});
