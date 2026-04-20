/**
 * Fusion explicite avec les classes exportées : le serveur TS ne fusionne pas toujours
 * GlobalMixins (name, eventMode, hitArea, cursor…) pour Graphics / Sprite / Container.
 */
import type { EventMode, IHitArea } from "@pixi/events";

declare module "pixi.js-legacy" {
  interface Graphics {
    name: string | null;
    eventMode: EventMode;
    hitArea: IHitArea | null;
    cursor: string;
  }
  interface Sprite {
    name: string | null;
  }
  interface Container {
    name: string | null;
  }
}
