/**
 * The sky, the sun and the lamps, as a pure function of the sim clock (WEB-0004).
 *
 * No WebGL in here. The renderer asks what the light is at a minute of the day
 * and draws it; `WorldModel.snapshot()` asks the same question, so a browser
 * spec can tell morning from midnight without reading a pixel.
 *
 * Keyframes, linearly interpolated. The audit's complaint was that 07:30,
 * 13:00 and 02:00 shared one sky, so the four looks are deliberately far
 * apart: a low gold morning, a high white noon, an orange dusk with the
 * windows coming on, and a blue night that is lit rather than black.
 *
 * Directions are in the scene's axes: x east, z south, y up. The camera sits
 * to the south-east looking north-west, so the faces it can see are the ones
 * that face east and south. The sun rises in the east, goes round by the
 * south and sets in the west, and never drops under 14 degrees while it is
 * lit: a lower sun throws shadows longer than the town.
 */

export type Sky = {
  /** Sky gradient, top and bottom, as #rrggbb. */
  top: string;
  bottom: string;
  /** The one directional light: the sun by day, the moon by night. */
  sunColor: string;
  sunIntensity: number;
  /** Unit vector from the town towards the light. */
  sunDirection: [number, number, number];
  hemiSky: string;
  hemiGround: string;
  hemiIntensity: number;
  /**
   * A shadowless light from over the camera's shoulder, in the sky's colour.
   * The two faces the camera sees are the east and the south; when the sun is
   * behind them they would otherwise be the same flat ambient, and a building
   * would lose its corner.
   */
  fillIntensity: number;
  /** 0 by day, 1 at night: how lit the windows, lamps and screens are. */
  lamps: number;
  exposure: number;
};

type Key = {
  at: number;
  top: string;
  bottom: string;
  sunColor: string;
  sunIntensity: number;
  azimuth: number;
  elevation: number;
  hemiSky: string;
  hemiGround: string;
  hemiIntensity: number;
  fill: number;
  lamps: number;
  exposure: number;
};

const h = (hours: number, minutes = 0) => hours * 60 + minutes;

// Azimuth in degrees clockwise from north, as on a compass: 90 is east, 180
// south, 270 west. The moon is parked in the south-west so that night shadows
// fall the same way as afternoon ones and nothing flips at dusk.
const NIGHT: Omit<Key, "at"> = {
  top: "#0b1236",
  bottom: "#2c3c78",
  sunColor: "#9db4ff",
  sunIntensity: 1.2,
  azimuth: 215,
  elevation: 52,
  // Warm from below: at night the light in a town comes up off lit floors.
  hemiSky: "#6f86d8",
  hemiGround: "#6a5238",
  hemiIntensity: 1.0,
  fill: 0.55,
  lamps: 1,
  exposure: 1.0,
};

const KEYS: Key[] = [
  { at: h(0), ...NIGHT },
  { at: h(5), ...NIGHT },
  {
    at: h(6, 15),
    top: "#5a6cab",
    bottom: "#f6b294",
    sunColor: "#ff9d6b",
    sunIntensity: 1.6,
    azimuth: 95,
    elevation: 16,
    hemiSky: "#b4bde6",
    hemiGround: "#6a5a5a",
    hemiIntensity: 0.85,
    fill: 0.6,
    lamps: 0.55,
    exposure: 1.0,
  },
  {
    at: h(7, 30),
    top: "#86bbea",
    bottom: "#ffe6c2",
    sunColor: "#ffd08f",
    sunIntensity: 2.7,
    azimuth: 110,
    elevation: 26,
    hemiSky: "#cfe2ff",
    hemiGround: "#8a7a66",
    hemiIntensity: 0.6,
    fill: 0.5,
    lamps: 0,
    exposure: 1.0,
  },
  {
    at: h(12, 30),
    top: "#58a6ea",
    bottom: "#d4ecfb",
    sunColor: "#fff6e6",
    sunIntensity: 2.9,
    azimuth: 165,
    elevation: 58,
    hemiSky: "#dcebff",
    hemiGround: "#8c8676",
    hemiIntensity: 0.55,
    fill: 0.55,
    lamps: 0,
    exposure: 1.0,
  },
  {
    at: h(16, 45),
    top: "#62a8e4",
    bottom: "#e9eedb",
    sunColor: "#ffe6bd",
    sunIntensity: 2.8,
    azimuth: 228,
    elevation: 38,
    hemiSky: "#d9e6fa",
    hemiGround: "#8a7e6c",
    hemiIntensity: 0.55,
    fill: 0.6,
    lamps: 0,
    exposure: 1.0,
  },
  {
    at: h(18, 30),
    top: "#4a4a9a",
    bottom: "#ffa46c",
    sunColor: "#ff8f52",
    sunIntensity: 2.4,
    azimuth: 252,
    elevation: 20,
    hemiSky: "#c4a2dc",
    hemiGround: "#80586a",
    hemiIntensity: 0.95,
    fill: 0.7,
    lamps: 0.85,
    exposure: 1.0,
  },
  {
    at: h(19, 30),
    top: "#1a2058",
    bottom: "#7a5590",
    sunColor: "#a596e0",
    sunIntensity: 0.8,
    azimuth: 235,
    elevation: 34,
    hemiSky: "#7f86d0",
    hemiGround: "#5a4840",
    hemiIntensity: 0.95,
    fill: 0.6,
    lamps: 1,
    exposure: 1.0,
  },
  { at: h(20, 30), ...NIGHT },
  { at: h(24), ...NIGHT },
];

function channels(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function mixHex(a: string, b: string, t: number): string {
  const ca = channels(a);
  const cb = channels(b);
  const value = ca
    .map((from, i) => Math.round(from + ((cb[i] ?? from) - from) * t))
    .reduce((acc, c) => (acc << 8) | c, 0);
  return `#${value.toString(16).padStart(6, "0")}`;
}

const mix = (a: number, b: number, t: number) => a + (b - a) * t;

/** The light at a minute of the sim day. Wraps, so 1500 is 01:00. */
export function skyAt(minute: number): Sky {
  const m = ((minute % 1440) + 1440) % 1440;
  let index = KEYS.findIndex((key) => key.at > m);
  if (index <= 0) index = KEYS.length - 1;
  const from = KEYS[index - 1] ?? KEYS[0]!;
  const to = KEYS[index] ?? from;
  const t = to.at === from.at ? 0 : (m - from.at) / (to.at - from.at);

  const azimuth = (mix(from.azimuth, to.azimuth, t) * Math.PI) / 180;
  const elevation = (mix(from.elevation, to.elevation, t) * Math.PI) / 180;
  const flat = Math.cos(elevation);
  return {
    top: mixHex(from.top, to.top, t),
    bottom: mixHex(from.bottom, to.bottom, t),
    sunColor: mixHex(from.sunColor, to.sunColor, t),
    sunIntensity: mix(from.sunIntensity, to.sunIntensity, t),
    // North is -z: a compass bearing of 90 (east) is +x, 180 (south) is +z.
    sunDirection: [Math.sin(azimuth) * flat, Math.sin(elevation), -Math.cos(azimuth) * flat],
    hemiSky: mixHex(from.hemiSky, to.hemiSky, t),
    hemiGround: mixHex(from.hemiGround, to.hemiGround, t),
    hemiIntensity: mix(from.hemiIntensity, to.hemiIntensity, t),
    fillIntensity: mix(from.fill, to.fill, t),
    lamps: mix(from.lamps, to.lamps, t),
    exposure: mix(from.exposure, to.exposure, t),
  };
}

/**
 * Minutes since midnight, from a sim-clock label such as `d2 Wed 02:00`.
 *
 * The label is what the model already holds from `GET /world/agents`. Noon
 * when it cannot be read — before the first frame, or if the label's format
 * changes — because a town lit like midday is the least surprising failure.
 */
export function minuteOfDay(label: string): number {
  const match = /(\d{1,2}):(\d{2})\s*$/.exec(label);
  if (match === null) return 12 * 60;
  return (Number(match[1]) % 24) * 60 + (Number(match[2]) % 60);
}
