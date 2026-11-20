/** Colour scales for the 3D viewer and its legends.
 *  Deviation: diverging blue ↔ neutral grey ↔ red (two hues, grey midpoint).
 *  Elevation: single-hue sequential blue. Intensity: greyscale. */

type RGB = [number, number, number];

const hex = (h: string): RGB => [parseInt(h.slice(1, 3), 16) / 255, parseInt(h.slice(3, 5), 16) / 255, parseInt(h.slice(5, 7), 16) / 255];

function ramp(stops: [number, string][]) {
  const s = stops.map(([t, c]) => [t, hex(c)] as [number, RGB]);
  return (t: number): RGB => {
    if (t <= s[0][0]) return s[0][1];
    for (let i = 1; i < s.length; i++) {
      if (t <= s[i][0]) {
        const [t0, c0] = s[i - 1];
        const [t1, c1] = s[i];
        const f = (t - t0) / (t1 - t0);
        return [c0[0] + f * (c1[0] - c0[0]), c0[1] + f * (c1[1] - c0[1]), c0[2] + f * (c1[2] - c0[2])];
      }
    }
    return s[s.length - 1][1];
  };
}

/** t in [-1, 1] where ±0.5 = ±tolerance and ±1 = ±2×tolerance */
export const DIVERGING_STOPS: [number, string][] = [
  [-1, "#104281"],
  [-0.5, "#3987e5"],
  [0, "#545c6b"],
  [0.5, "#e66767"],
  [1, "#a61e1e"],
];
export const diverging = ramp(DIVERGING_STOPS);
export const sequential = ramp([[0, "#184f95"], [0.5, "#3987e5"], [1, "#b7d3f6"]]);
export const NO_DATA: RGB = hex("#3a4250");

export function cssGradient(stops: [number, string][], min = -1, max = 1) {
  return `linear-gradient(to right, ${stops.map(([t, c]) => `${c} ${(100 * (t - min)) / (max - min)}%`).join(", ")})`;
}

export function devColorCss(d: number, tol: number) {
  const [r, g, b] = diverging(Math.max(-1, Math.min(1, d / (2 * tol))));
  return `rgb(${Math.round(r * 255)}, ${Math.round(g * 255)}, ${Math.round(b * 255)})`;
}

export const STATUS_COLOR: Record<string, string> = {
  WITHIN_TOLERANCE: "#0ca30c",
  OUT_OF_TOLERANCE: "#d03b3b",
  REDRILL_REQUIRED: "#ec835a",
  ACCEPTED_BY_ENGINEER: "#fab219",
  NOT_MEASURED: "#6b7383",
};
