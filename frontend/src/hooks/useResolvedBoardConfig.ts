/**
 * Config plateau RÉSOLUE : celle servie par l'API, surchargée par le plateau du journal en replay,
 * puis mise à l'échelle d'affichage. C'est l'objet que `BoardPvp` lit ~260 fois, et dont dépendent
 * la plupart de ses mémos et son effet de dessin.
 *
 * POURQUOI CE HOOK EXISTE — pour la RÉFÉRENCE, pas pour la valeur. Les deux étapes de résolution
 * étaient des expressions non mémoïsées : chacune fabriquait un objet neuf à CHAQUE rendu, dès lors
 * qu'elle avait quelque chose à faire (une surcharge de replay à appliquer, une échelle ≠ 1). Tout
 * ce qui se mémoïse sur `boardConfig` — et non sur ses champs — était donc inopérant sur ces
 * plateaux-là, alors que la même mémoïsation tenait en PvP standard, où les deux étapes rendaient
 * l'objet du hook inchangé. Ce hook aligne les deux cas sur le comportement déjà éprouvé.
 *
 * Les deux étapes tiennent dans UN mémo : l'échelle n'est pas une entrée à part, elle se lit dans
 * l'objet lui-même (`display.display_scale`), donc rien ne peut la faire bouger sans que la
 * surcharge ait déjà changé.
 */

import { useMemo } from "react";
import type { DisplayConfig } from "./useGameConfig";

/** Surcharge de plateau du journal de replay (cf. Replay.md §2.4) : dimensions et échelle jouées. */
export interface BoardConfigOverride {
  cols: number;
  rows: number;
  hex_radius: number;
  margin: number;
  inches_to_subhex: number;
}

interface BoardConfigLike {
  hex_radius: number;
  display?: DisplayConfig;
}

/**
 * Applique l'échelle d'AFFICHAGE (`display.display_scale`) au rayon d'hex.
 *
 * Rend l'objet REÇU quand il n'y a rien à faire (pas d'échelle, ou échelle 1) : c'est ce qui
 * garde la référence stable sur le cas courant, sans dépendre de la mémoïsation.
 */
export function applyDisplayScale<T extends BoardConfigLike>(config: T): T {
  const scale = config.display?.display_scale;
  if (!scale || scale === 1) {
    return config;
  }
  return { ...config, hex_radius: config.hex_radius * scale };
}

export function useResolvedBoardConfig<T extends BoardConfigLike>(
  boardConfigFromApi: T | null,
  boardConfigOverride: BoardConfigOverride | undefined
): T | null {
  return useMemo(() => {
    if (boardConfigFromApi === null) {
      return null;
    }
    return applyDisplayScale(
      boardConfigOverride ? { ...boardConfigFromApi, ...boardConfigOverride } : boardConfigFromApi
    );
  }, [boardConfigFromApi, boardConfigOverride]);
}
