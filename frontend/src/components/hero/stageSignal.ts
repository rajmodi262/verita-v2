import type { StageSignal } from "./VaultScene";

/** What the LIVE badge says while the money is simply orbiting. */
export const IDLE = "Monitoring the money";

/**
 * Write one frame of the scene's signal to the page: how squarely the coin faces the viewer
 * (the words glint with it, via --face) and the pattern caption. Direct DOM writes, so the page
 * never re-renders per frame; the caption text is only touched when it changes.
 */
export function applyStageSignal(
  stage: HTMLElement | null,
  caption: HTMLElement | null,
  signal: StageSignal,
): void {
  stage?.style.setProperty("--face", signal.face.toFixed(3));
  if (!caption) return;
  const text = signal.caption ?? IDLE;
  if (caption.textContent === text) return;
  caption.textContent = text;
  caption.dataset.on = signal.caption ? "true" : "false";
}
