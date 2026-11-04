/* Where each head is on screen, written by the 3D scene every frame and read
 * by the DOM overlay (markers and labels stay crisp HTML, outside WebGL). */

export type Spot = {
  x: number;
  y: number;
  visible: boolean;
  thinking: boolean;
};

export class ScreenBus {
  spots = new Map<string, Spot>();
  hovered: string | null = null;
  set(key: string, spot: Spot) {
    this.spots.set(key, spot);
  }
}
