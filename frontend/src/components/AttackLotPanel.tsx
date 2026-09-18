import type React from "react";
import { useCallback, useRef, useState } from "react";
import type { AttackLotRequest, ManualAllocation } from "../hooks/useEngineAPI";

/**
 * Panneau de LOT d'une activation d'attaque (chantier « chaîne d'attaque 100 % », 2026-09-18).
 *
 * Trois états, un seul panneau (même layout flottant que le menu d'armes) :
 * - ATTAQUANT — choix du prochain lot (04.03 : « Select Enemy Unit » puis « Gather Attack
 *   Dice » — une ligne par lot candidat, cliquable ; `locked_target_unit_id` quand l'unité en
 *   cours n'est pas terminée, la liste n'a alors que ses profils) ;
 * - ATTAQUANT — politique de relance du lot (« échecs seulement » / « tous les non-critiques »),
 *   posée seulement quand un critique vaut plus qu'une réussite ([SUSTAINED HITS] / [LETHAL HITS]
 *   côté touche, [DEVASTATING WOUNDS] côté blessure) ;
 * - DÉFENSEUR — lot en cours d'allocation (05.04 / 06.02) : arme, cible, blessures restantes,
 *   figurines candidates (cliquables ici comme sur le plateau).
 *
 * Le panneau ne décide rien : il présente ce que le moteur attend, et renvoie le choix.
 */
export interface AttackLotPanelProps {
  lotRequest: AttackLotRequest | null;
  allocation: ManualAllocation | null;
  /** Libellé d'unité pour l'affichage (type de datasheet), résolu par l'appelant. */
  unitLabel: (unitId: string) => string;
  onSelectLot: (lotId: number, rerolls?: { hit?: boolean; wound?: boolean }) => void;
  onAllocateModel: (modelId: string) => void;
}

function useDraggable(initial: { x: number; y: number }) {
  const [pos, setPos] = useState(initial);
  const dragOffset = useRef<{ x: number; y: number } | null>(null);
  const onDragStart = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      dragOffset.current = { x: e.clientX - pos.x, y: e.clientY - pos.y };
      const onMouseMove = (ev: MouseEvent) => {
        if (!dragOffset.current) return;
        setPos({ x: ev.clientX - dragOffset.current.x, y: ev.clientY - dragOffset.current.y });
      };
      const onMouseUp = () => {
        dragOffset.current = null;
        document.removeEventListener("mousemove", onMouseMove);
        document.removeEventListener("mouseup", onMouseUp);
      };
      document.addEventListener("mousemove", onMouseMove);
      document.addEventListener("mouseup", onMouseUp);
    },
    [pos]
  );
  return { pos, onDragStart };
}

/** Les lots d'un même `target_unit_id`, dans l'ordre reçu. */
export function lotsByTarget(
  lots: AttackLotRequest["lots"]
): Array<[string, AttackLotRequest["lots"]]> {
  const order: string[] = [];
  const by: Record<string, AttackLotRequest["lots"]> = {};
  for (const lot of lots) {
    if (!(lot.target_unit_id in by)) {
      by[lot.target_unit_id] = [];
      order.push(lot.target_unit_id);
    }
    by[lot.target_unit_id].push(lot);
  }
  return order.map((t) => [t, by[t]]);
}

export function AttackLotPanel({
  lotRequest,
  allocation,
  unitLabel,
  onSelectLot,
  onAllocateModel,
}: AttackLotPanelProps) {
  const { pos, onDragStart } = useDraggable({ x: 360, y: 140 });
  // Politique de relance en cours d'édition (par lot ; remise à zéro à chaque nouvelle attente
  // par remount — `key` posée par l'appelant).
  const [hitNonCrit, setHitNonCrit] = useState(false);
  const [woundNonCrit, setWoundNonCrit] = useState(false);
  // Lot choisi parmi plusieurs candidats, en attente de sa politique de relance.
  const [pendingLotId, setPendingLotId] = useState<number | null>(null);

  if (!lotRequest && !allocation) return null;

  const frame = (title: string, body: React.ReactNode) => (
    <div
      className="weapon-dropdown attack-lot-panel"
      data-testid="attack-lot-panel"
      style={{ position: "fixed", left: `${pos.x}px`, top: `${pos.y}px`, zIndex: 100000 }}
    >
      <button type="button" className="weapon-dropdown-handle" onMouseDown={onDragStart}>
        ⠿ {title}
      </button>
      {body}
    </div>
  );

  if (lotRequest) {
    const needsPolicy = (lot: AttackLotRequest["lots"][number]) =>
      lot.reroll_choices.hit || lot.reroll_choices.wound;
    const chosen =
      pendingLotId !== null
        ? lotRequest.lots.find((l) => l.lot_id === pendingLotId)
        : lotRequest.policy_only && lotRequest.lots.length === 1
          ? lotRequest.lots[0]
          : undefined;

    if (chosen && needsPolicy(chosen)) {
      // Politique de relance du lot choisi (ou imposé).
      return frame(
        `RELANCES — ${chosen.weapon_name} → ${unitLabel(chosen.target_unit_id)}`,
        <div className="weapon-dropdown-subtitle">
          <div className="alloc-weapons">
            {chosen.reroll_choices.hit && (
              <label style={{ display: "block" }}>
                <input
                  type="checkbox"
                  checked={hitNonCrit}
                  onChange={(e) => setHitNonCrit(e.target.checked)}
                />{" "}
                Touche : relancer aussi les réussites non critiques (chercher les 6)
              </label>
            )}
            {chosen.reroll_choices.wound && (
              <label style={{ display: "block" }}>
                <input
                  type="checkbox"
                  checked={woundNonCrit}
                  onChange={(e) => setWoundNonCrit(e.target.checked)}
                />{" "}
                Blessure : relancer aussi les réussites non critiques ([DEVASTATING WOUNDS])
              </label>
            )}
            <div style={{ fontSize: 12, opacity: 0.8 }}>
              Décoché = relancer les échecs seulement. Un critique n'est jamais relancé.
            </div>
          </div>
          <div className="weapon-dropdown-actions">
            <button
              type="button"
              style={{ backgroundColor: "#4caf50", color: "#fff" }}
              onClick={() => onSelectLot(chosen.lot_id, { hit: hitNonCrit, wound: woundNonCrit })}
            >
              Résoudre ce lot
            </button>
          </div>
        </div>
      );
    }

    // Choix du lot : une ligne par lot, regroupées par unité cible.
    const groups = lotsByTarget(lotRequest.lots);
    return frame(
      lotRequest.locked_target_unit_id
        ? `LOT SUIVANT — ${unitLabel(lotRequest.locked_target_unit_id)} (unité en cours)`
        : "LOT SUIVANT — choisir l'unité à résoudre",
      <div className="weapon-dropdown-subtitle">
        <div style={{ fontSize: 12, opacity: 0.8 }}>
          04.03 : toutes les armes d'une unité avant la suivante. Cliquez un lot (ou l'unité sur le
          plateau).
        </div>
        <table className="weapon-table">
          <thead>
            <tr>
              <th>Cible</th>
              <th>Arme</th>
              <th>Figs</th>
              <th>Att.</th>
            </tr>
          </thead>
          <tbody>
            {groups.map(([target, lots]) =>
              lots.map((lot) => (
                <tr
                  key={lot.lot_id}
                  className="selected"
                  data-testid={`lot-${lot.lot_id}`}
                  style={{ cursor: "pointer" }}
                  onClick={() => {
                    if (needsPolicy(lot)) setPendingLotId(lot.lot_id);
                    else onSelectLot(lot.lot_id);
                  }}
                >
                  <td>{unitLabel(target)}</td>
                  <td>{lot.weapon_name}</td>
                  <td>{lot.n_models}</td>
                  <td>{lot.n_attacks}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    );
  }

  // Défenseur : lot en cours d'allocation.
  const alloc = allocation as ManualAllocation;
  const isMortal = alloc.damage_type === "mortal";
  const weapons = alloc.weapon_names && alloc.weapon_names.length > 0 ? alloc.weapon_names : [];
  return frame(
    `ALLOCATION — ${unitLabel(alloc.target_unit_id)} encaisse`,
    <div className="weapon-dropdown-subtitle">
      <div className="alloc-saves">
        {alloc.wounds_remaining} {isMortal ? "blessure(s) mortelle(s)" : "blessure(s)"} restante(s)
        {isMortal ? " — sans sauvegarde (06.02)" : ""}
      </div>
      <div className="alloc-weapons">
        {isMortal ? <div>Mortal Wounds</div> : weapons.map((n) => <div key={n}>{n}</div>)}
      </div>
      <div style={{ fontSize: 12, opacity: 0.8 }}>
        Joueur {alloc.defender_player} : choisir la figurine qui encaisse (ici ou sur le plateau).
      </div>
      <table className="weapon-table">
        <tbody>
          {alloc.choices.map((c) => (
            <tr
              key={c.model_id}
              className="selected"
              data-testid={`alloc-${c.model_id}`}
              style={{ cursor: "pointer" }}
              onClick={() => onAllocateModel(c.model_id)}
            >
              <td>{c.model_id}</td>
              <td>
                PV {c.HP_CUR}/{c.HP_MAX}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
