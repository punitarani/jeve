/**
 * The renderer: a view over `WorldModel`, and nothing else.
 *
 * An orthographic camera at an isometric angle; flat-shaded boxes; per storey,
 * every static voxel in one instanced mesh and everything that glows in a
 * second, and every part of every person in one more, so the whole town is a
 * handful of draw calls. Nothing in here holds simulation state, and
 * everything it needs to know comes from the model each frame.
 *
 * The camera object is created whether or not WebGL is available: projection
 * is plain matrix arithmetic, and picking and labels depend on it.
 *
 * WEB-0004 is why it looks the way it does: a weak ambient and a strong sun
 * that casts real shadows, occlusion baked into the corners of every box, a
 * filmic tone curve, and a sky, a sun and lamps that follow the sim clock.
 *
 * Nothing here is sized to the town in tiles. Every distance — the camera's,
 * the fog's, how far one may pan, where the clouds are — is a multiple of the
 * map's span, worked out in `build` (WORLD-0006: the district is twice the
 * town it replaced, and will grow again).
 */
import type { Palette, TownMap } from "@jeve/contracts";
import * as THREE from "three";
import { MapControls } from "three/addons/controls/MapControls.js";

import type { Walker, WorldModel } from "./model";
import { skyAt, type Sky } from "./sky";
import {
  HAIR_TONES,
  HATS,
  HEAD_TOP,
  PERSON_BOXES,
  RIG,
  SKIN_TONES,
  STOREY,
  SURFACES,
  TROUSER_TONES,
  buildVoxels,
  facingAt,
  fountainOf,
  groundKinds,
  hash2,
  lookFor,
  shade,
  storeyKinds,
  type Glow,
  type Joint,
  type KindAt,
  type Voxel,
} from "./voxels";

/**
 * Slots the people mesh is given beyond what the frame needs, so a crowd that
 * grows by a few does not rebuild it every tick. It is rebuilt, larger, when
 * even that is not enough: capacity follows the staff, not a constant.
 */
const PEOPLE_HEADROOM = 64;
const MAX_SELECTED = 8;
const ISO_ELEVATION = Math.atan(1 / Math.SQRT2); // true isometric: ~35.26 degrees
const ISO_AZIMUTH = Math.PI / 4;
/**
 * Distances as multiples of the map's span. These are the numbers that were
 * right for a forty-tile town, over forty: the camera sat 80 out, haze began
 * at 104 and was total at 215, the target could be dragged 15 past the edge,
 * and clouds drifted within 85 of the centre.
 */
const CAMERA_SPANS = 2;
const FOG_NEAR_SPANS = 0.6;
const FOG_FAR_SPANS = 3.4;
const PAN_MARGIN_SPANS = 0.375;
const CLOUD_RADIUS_SPANS = 2.1;
/** Thin drifting clouds over the meadow, in the town's own box idiom. */
const CLOUD_COUNT = 26;
/** A cloud's lobes: offsets and scales against the puff's own size. */
const CLOUD_LOBES: [number, number, number, number, number, number][] = [
  [0, 0, 0, 1, 1, 1],
  [0.55, -0.45, 0.3, 0.55, 0.6, 0.55],
  [-0.5, 0.35, -0.3, 0.6, 0.55, 0.5],
  [0.1, 0.45, -0.55, 0.45, 0.45, 0.4],
];
/** A person whose firm has no building on the map is drawn in this. */
const NEUTRAL_BODY = "#9a9a9a";
const NEUTRAL_ACCENT = "#6a6a6a";

export type ViewTarget = { x: number; z: number; span: number };

/**
 * Is this browser's WebGL a CPU rasteriser?
 *
 * SwiftShader and llvmpipe draw every pixel on the CPU, and every GL call is a
 * synchronous wait on a GPU process shared by all tabs. A 60 fps antialiased
 * scene at 2x pixel ratio is nothing to a GPU and a great deal to a laptop
 * core that is busy with something else: under heavy system load it froze a
 * headless page outright, for minutes. So a software renderer gets a cheap
 * picture — no MSAA, 1x pixel ratio, fifteen frames a second, and (WEB-0004)
 * no shadow maps — and the town still moves. Asked of a throwaway context,
 * because antialiasing has to be chosen before the real one is created.
 */
function softwareRenderer(): string | null {
  try {
    const probe = document.createElement("canvas");
    const gl = probe.getContext("webgl2") ?? probe.getContext("webgl");
    if (!gl) return null;
    const info = gl.getExtension("WEBGL_debug_renderer_info");
    const name = info ? String(gl.getParameter(info.UNMASKED_RENDERER_WEBGL)) : "";
    gl.getExtension("WEBGL_lose_context")?.loseContext();
    return /swiftshader|llvmpipe|software|basic render/i.test(name) ? name : null;
  } catch {
    return null;
  }
}

const SOFTWARE_FRAME_MS = 1000 / 15;
const CROWD_SKIN = ["#d2cec8", "#bdb9b3", "#a9a5a0"];
const CROWD_HAIR = ["#8a8782", "#6f6c68", "#a19e99"];

function pick<T>(palette: readonly T[], key: string, fallback: T): T {
  let h = 0;
  for (let i = 0; i < key.length; i++) h = (h * 31 + key.charCodeAt(i)) >>> 0;
  return palette[h % palette.length] ?? fallback;
}

/** The shortest way round from one yaw to another. */
function turn(from: number, to: number, k: number): number {
  let delta = (to - from) % (Math.PI * 2);
  if (delta > Math.PI) delta -= Math.PI * 2;
  if (delta < -Math.PI) delta += Math.PI * 2;
  return from + delta * k;
}

// -- how a person is posed --------------------------------------------------

/** Tiles walked per full swing of the legs. */
const STRIDE = 1.7;
/** People cross the map in seconds; legs that kept up would be a blur. */
const MAX_STEPS_PER_SECOND = 3.2;
const SEAT_TOP = 0.27;

/** A person's colours, worked out once: parsing hex per box per frame is waste. */
type Look = {
  colors: THREE.Color[]; // one per box, in rig order then hat a, hat b
  sizes: ([number, number, number] | null)[]; // null hides the box
  offsets: [number, number, number][];
};

/** What the renderer remembers about somebody between frames. Not sim state. */
type Drawn = {
  x: number;
  y: number;
  yaw: number;
  /** Radians through the walk cycle, advanced by distance, not by time. */
  cycle: number;
  /** 0 standing, 1 sitting; eased, so people sit down rather than snap. */
  sit: number;
  swing: number;
  seenAt: number;
};

/** One storey's static meshes: what the level cut shows or hides together. */
type StoreyMeshes = {
  floor: number;
  town: THREE.InstancedMesh;
  glow: THREE.InstancedMesh;
  glowKinds: Glow[];
  glowBase: THREE.Color[];
  pool: THREE.InstancedMesh;
};

export class WorldView {
  readonly camera: THREE.OrthographicCamera;
  readonly glOk: boolean;
  readonly canvas: HTMLCanvasElement;
  /** The software renderer's name, or null when there is a real GPU. */
  readonly software: string | null;

  private renderer: THREE.WebGLRenderer | null = null;
  private scene = new THREE.Scene();
  private controls: MapControls | null = null;
  private width = 1;
  private height = 1;
  private target: ViewTarget = { x: 0, z: 0, span: 41 };
  private eased: ViewTarget = { x: 0, z: 0, span: 41 };
  private frames: number[] = [];
  private lastFrameAt = 0;
  private lastDrawAt = 0;

  /** The map's span in tiles, from which every distance below is derived. */
  private span = 40;
  private mapWidth = 1;
  private mapHeight = 1;

  // The scene's moving parts. All null until `build`.
  private hemi: THREE.HemisphereLight | null = null;
  private sun: THREE.DirectionalLight | null = null;
  private fill: THREE.DirectionalLight | null = null;
  private storeys: StoreyMeshes[] = [];
  private falloff: THREE.DataTexture | null = null;
  private poolsLit = false;
  private appliedCut: number | null | undefined = undefined;
  private unitBox = new THREE.BoxGeometry(1, 1, 1);
  private peopleMaterial = new THREE.MeshLambertMaterial({ color: 0xffffff, flatShading: true });
  private blobMaterial: THREE.MeshBasicMaterial | null = null;
  private people: THREE.InstancedMesh | null = null;
  private blobs: THREE.InstancedMesh | null = null;
  private capacity = 0;
  private rings: THREE.InstancedMesh | null = null;
  private markers: THREE.InstancedMesh | null = null;
  private skyTexture: THREE.DataTexture | null = null;
  private townCentre = new THREE.Vector3();
  private townRadius = 30;
  private clouds: THREE.InstancedMesh | null = null;
  private cloudSpots: { x: number; z: number; y: number; sx: number; sy: number; sz: number; speed: number }[] = [];
  /** Where the camera's target may go, in tiles: the map plus a margin. */
  private panX: [number, number] = [0, 0];
  private panZ: [number, number] = [0, 0];
  /** Each firm's colours, from its building: what its people are drawn in. */
  private palettes = new Map<string, Palette>();

  // Time of day, eased: a tick moves the clock a quarter of an hour at once,
  // and a sun that jumped would make every shadow in town twitch.
  private litMinute: number | null = null;
  private drawnMinute = -1;

  private looks = new Map<string, Look>();
  private slots: string[] = [];
  private repainted = false;
  private drawn = new Map<string, Drawn>();
  private seatYaw = new Map<number, number>();
  private faceYaw = new Map<number, number>();

  private root = new THREE.Matrix4();
  private local = new THREE.Matrix4();
  private out = new THREE.Matrix4();
  private color = new THREE.Color();
  private colorB = new THREE.Color();
  private vector = new THREE.Vector3();
  private projected = new THREE.Vector3();
  private basis = new THREE.Matrix4();
  private hidden = new THREE.Matrix4().makeScale(0, 0, 0);

  constructor(
    private container: HTMLElement,
    private model: WorldModel,
    private options: { interactive: boolean; debug: boolean },
  ) {
    this.canvas = document.createElement("canvas");
    this.canvas.style.cssText = "display:block;width:100%;height:100%;touch-action:none";
    this.canvas.dataset.testid = "world-canvas";
    container.appendChild(this.canvas);

    this.camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.1, this.cameraDistance * 5);
    this.placeCamera();

    this.software = softwareRenderer();
    let ok = false;
    try {
      this.renderer = new THREE.WebGLRenderer({
        canvas: this.canvas,
        antialias: this.software === null,
        alpha: true,
        powerPreference: "high-performance",
      });
      this.renderer.setPixelRatio(
        this.software === null ? Math.min(2, window.devicePixelRatio || 1) : 1,
      );
      // Transparent until there is a town to draw: with the API down the page's
      // own background shows through, as it always has.
      this.renderer.setClearColor(0x000000, 0);
      this.renderer.outputColorSpace = THREE.SRGBColorSpace;
      this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
      // WEB-0003 + WEB-0004: shadow maps are a second pass over the whole town
      // every frame. A GPU does not notice; a CPU rasteriser does.
      this.renderer.shadowMap.enabled = this.software === null;
      // three 0.186 removed PCFSoftShadowMap; its PCF is hardware-filtered.
      this.renderer.shadowMap.type = THREE.PCFShadowMap;
      ok = true;
    } catch (error) {
      // No GPU, a blocked context, a headless browser: the page must still
      // work. The model keeps running and picking still resolves; only the
      // picture is missing, and the container says so.
      console.warn("jeve world: WebGL is unavailable; running without a picture", error);
      container.dataset.gl = "unavailable";
    }
    this.glOk = ok;

    if (this.options.interactive) {
      this.controls = new MapControls(this.camera, this.canvas);
      this.controls.enableRotate = false; // keep the isometric angle
      this.controls.enableDamping = true;
      this.controls.dampingFactor = 0.12;
      this.controls.zoomSpeed = 1.4;
      this.controls.minZoom = 0.6;
      this.controls.maxZoom = 5;
      this.controls.target.set(this.target.x, 0, this.target.z);
      this.controls.screenSpacePanning = false;
    }
    this.resize();
  }

  // -- derived distances ---------------------------------------------------

  /** How many tiles across the whole map is, allowing for the isometric foreshortening of depth. */
  spanOf(map: { width: number; height: number }): number {
    return Math.max(map.width, map.height * 1.2);
  }

  private get cameraDistance(): number {
    return this.span * CAMERA_SPANS;
  }

  private get cloudRadius(): number {
    return this.span * CLOUD_RADIUS_SPANS;
  }

  // -- scene ---------------------------------------------------------------

  build(map: TownMap): void {
    this.mapWidth = map.width;
    this.mapHeight = map.height;
    this.span = this.spanOf(map);
    this.townCentre.set((map.width - 1) / 2, 0, (map.height - 1) / 2);
    this.townRadius = Math.hypot(map.width, map.height) / 2 + 2;
    this.palettes = new Map(map.buildings.map((b) => [b.org_id, b.palette]));
    this.learnSeats(map);

    // The camera: far enough out for the whole district, framed to it, and
    // able to see to the far end of the outskirts.
    this.camera.far = this.cameraDistance * 5;
    const whole = { x: this.townCentre.x, z: this.townCentre.z, span: this.span + 1 };
    this.target = { ...whole };
    this.eased = { ...whole };
    this.placeCamera();
    if (this.controls !== null) {
      this.controls.target.set(whole.x, 0, whole.z);
      // As close as a building filling the screen, however wide the map.
      this.controls.maxZoom = Math.max(5, this.span / 8);
    }

    this.hemi = new THREE.HemisphereLight(0xffffff, 0x8a93a6, 0.45);
    this.sun = new THREE.DirectionalLight(0xfff2dc, 3);
    // From over the camera's right shoulder, and never casting: see `Sky`.
    this.fill = new THREE.DirectionalLight(0xffffff, 0.5);
    this.fill.position
      .copy(this.townCentre)
      .add(new THREE.Vector3(1.5, 1.125, 0.7).multiplyScalar(this.span));
    this.fill.target.position.copy(this.townCentre);
    this.scene.add(this.hemi, this.sun, this.sun.target, this.fill, this.fill.target);
    if (this.software === null) this.castShadows(this.sun);

    // Each storey gets meshes of its own, so a level cut can hide the floors
    // above one without touching the rest.
    const voxels = buildVoxels(map);
    const floors = [...new Set(voxels.map((v) => v.floor))].sort((a, b) => a - b);
    this.falloff = this.falloffTexture();
    for (const floor of floors) {
      const own = voxels.filter((v) => v.floor === floor);
      this.storeys.push({
        floor,
        town: this.buildTown(own.filter((v) => v.glow === undefined)),
        ...this.buildGlow(own.filter((v) => v.glow !== undefined), this.falloff),
      });
    }
    this.buildPeople();
    this.buildSky();
    this.buildClouds(map);
    // Haze, not a wall: the meadow melts into the horizon colour, repainted
    // with the sky every time the light moves. The camera sits at
    // `cameraDistance`, so these are depths from it, and an orthographic
    // camera reads them almost as tiles from the target.
    this.scene.fog = new THREE.Fog(
      0xffffff,
      this.cameraDistance + this.span * FOG_NEAR_SPANS,
      this.cameraDistance + this.span * FOG_FAR_SPANS,
    );
    const margin = Math.round(this.span * PAN_MARGIN_SPANS);
    this.panX = [-margin, map.width - 1 + margin];
    this.panZ = [-margin, map.height - 1 + margin];
    this.debugHandle();
  }

  /**
   * One shadow map for the whole town, fitted once. The frustum never follows
   * the camera, so panning cannot make a shadow crawl; `aimSun` snaps it to
   * whole texels, so the sun's own movement cannot either.
   */
  private castShadows(sun: THREE.DirectionalLight): void {
    // 4096 is 64 MB of depth and sixteen million texels to filter against. A
    // desktop GPU does not notice; a phone draws the town a few hundred pixels
    // across, where half the resolution is already more than it can show.
    const max = this.renderer?.capabilities.maxTextureSize ?? 2048;
    const small = Math.max(this.width, this.height) < 900;
    const size = max >= 8192 && !small ? 4096 : 2048;
    sun.castShadow = true;
    sun.shadow.mapSize.set(size, size);
    const r = this.townRadius;
    const cam = sun.shadow.camera;
    cam.left = -r;
    cam.right = r;
    cam.top = r;
    cam.bottom = -r;
    cam.near = 1;
    // The sun stands `sunDistance` out; the far plane reaches through the town
    // and out the other side.
    cam.far = r + this.sunDistance + this.span;
    cam.updateProjectionMatrix();
    sun.shadow.bias = -0.0004;
    sun.shadow.normalBias = 0.035;
  }

  /** How far out the sun is placed: past the town's radius by most of a span. */
  private get sunDistance(): number {
    return this.townRadius + this.span * 0.75;
  }

  private buildTown(voxels: Voxel[]): THREE.InstancedMesh {
    const geometry = new THREE.BoxGeometry(1, 1, 1);
    const lo = new Float32Array(voxels.length * 4);
    const hi = new Float32Array(voxels.length * 4);
    // One material for the whole storey: white, flat-shaded, tinted per
    // instance and darkened per corner.
    const material = new THREE.MeshLambertMaterial({ color: 0xffffff, flatShading: true });
    material.onBeforeCompile = (shader) => {
      if (!shader.vertexShader.includes("#include <color_vertex>")) {
        throw new Error("WEB-0004: three.js has no color_vertex chunk to bake occlusion into");
      }
      shader.vertexShader = shader.vertexShader
        .replace("#include <common>", "#include <common>\nattribute vec4 aoLo;\nattribute vec4 aoHi;")
        .replace(
          "#include <color_vertex>",
          `#include <color_vertex>
          {
            vec4 aoSet = position.y > 0.0 ? aoHi : aoLo;
            int aoCorner = ( position.x > 0.0 ? 1 : 0 ) + ( position.z > 0.0 ? 2 : 0 );
            vColor.rgb *= aoSet[ aoCorner ];
          }`,
        );
    };
    const town = new THREE.InstancedMesh(geometry, material, Math.max(1, voxels.length));
    const matrix = new THREE.Matrix4();
    voxels.forEach((voxel, i) => {
      matrix.makeScale(voxel.sx, voxel.sy, voxel.sz).setPosition(voxel.x, voxel.y, voxel.z);
      town.setMatrixAt(i, matrix);
      town.setColorAt(i, this.color.set(voxel.color));
      lo.set(voxel.ao.slice(0, 4), i * 4);
      hi.set(voxel.ao.slice(4, 8), i * 4);
    });
    town.count = voxels.length;
    geometry.setAttribute("aoLo", new THREE.InstancedBufferAttribute(lo, 4));
    geometry.setAttribute("aoHi", new THREE.InstancedBufferAttribute(hi, 4));
    town.instanceMatrix.needsUpdate = true;
    if (town.instanceColor) town.instanceColor.needsUpdate = true;
    // Instances span the whole map; the mesh's own bounds are one unit cube.
    town.frustumCulled = false;
    town.castShadow = true;
    town.receiveShadow = true;
    this.scene.add(town);
    return town;
  }

  /** A radial falloff, made here: there is still no asset in this package. */
  private falloffTexture(): THREE.DataTexture {
    const size = 64;
    const data = new Uint8Array(size * size * 4);
    for (let y = 0; y < size; y++) {
      for (let x = 0; x < size; x++) {
        const d = Math.hypot(x - (size - 1) / 2, y - (size - 1) / 2) / (size / 2);
        const a = Math.max(0, 1 - d) ** 2;
        data.set([255, 255, 255, Math.round(a * 255)], (y * size + x) * 4);
      }
    }
    const falloff = new THREE.DataTexture(data, size, size, THREE.RGBAFormat);
    falloff.magFilter = THREE.LinearFilter;
    falloff.minFilter = THREE.LinearFilter;
    falloff.needsUpdate = true;
    return falloff;
  }

  /**
   * Everything unlit on one storey. Windows, lamps and screens are boxes whose
   * colour is set from the time of day; pools are soft discs of light on the
   * floor under them, added to whatever is there. None of it is tone-mapped:
   * a lit window should be the brightest thing in a night, not a filmic grey.
   */
  private buildGlow(
    voxels: Voxel[],
    falloff: THREE.DataTexture,
  ): Pick<StoreyMeshes, "glow" | "glowKinds" | "glowBase" | "pool"> {
    const boxes = voxels.filter((v) => v.glow !== "pool");
    const pools = voxels.filter((v) => v.glow === "pool");
    const matrix = new THREE.Matrix4();

    const material = new THREE.MeshBasicMaterial({ color: 0xffffff, toneMapped: false });
    const glow = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1), material, Math.max(1, boxes.length));
    boxes.forEach((voxel, i) => {
      matrix.makeScale(voxel.sx, voxel.sy, voxel.sz).setPosition(voxel.x, voxel.y, voxel.z);
      glow.setMatrixAt(i, matrix);
      glow.setColorAt(i, this.color.set(voxel.color));
    });
    glow.count = boxes.length;
    glow.frustumCulled = false;
    this.scene.add(glow);

    const poolMaterial = new THREE.MeshBasicMaterial({
      color: 0xffffff,
      map: falloff,
      transparent: true,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      toneMapped: false,
      opacity: 0,
    });
    const disc = new THREE.PlaneGeometry(1, 1).rotateX(-Math.PI / 2);
    const pool = new THREE.InstancedMesh(disc, poolMaterial, Math.max(1, pools.length));
    pools.forEach((voxel, i) => {
      matrix.makeScale(voxel.sx, 1, voxel.sz).setPosition(voxel.x, voxel.y, voxel.z);
      pool.setMatrixAt(i, matrix);
      pool.setColorAt(i, this.color.set(voxel.color));
    });
    pool.count = pools.length;
    pool.frustumCulled = false;
    pool.renderOrder = 1;
    this.scene.add(pool);
    return {
      glow,
      glowKinds: boxes.map((v) => v.glow ?? "lamp"),
      glowBase: boxes.map((v) => new THREE.Color(v.color)),
      pool,
    };
  }

  private buildPeople(): void {
    if (this.software !== null) {
      // No shadow map on a CPU rasteriser, so people keep a blob under them:
      // without it they float.
      this.blobMaterial = new THREE.MeshBasicMaterial({
        color: 0x000000,
        transparent: true,
        opacity: 0.22,
        depthWrite: false,
      });
    }
    this.ensurePeople(0);

    // Selection (audit C4: "nothing marks a selection in the scene"). A square
    // ring on the ground, and a marker over the head for when the ground is
    // behind a wall.
    const ring = new THREE.RingGeometry(0.62, 0.8, 4, 1).rotateZ(Math.PI / 4).rotateX(-Math.PI / 2);
    const bright = new THREE.MeshBasicMaterial({
      color: 0xffffff,
      toneMapped: false,
      transparent: true,
      opacity: 0.95,
      depthWrite: false,
    });
    this.rings = new THREE.InstancedMesh(ring, bright, MAX_SELECTED);
    this.rings.frustumCulled = false;
    this.rings.count = 0;
    this.rings.renderOrder = 2;
    const marker = new THREE.MeshBasicMaterial({ color: 0xffe066, toneMapped: false });
    this.markers = new THREE.InstancedMesh(this.unitBox, marker, MAX_SELECTED);
    this.markers.frustumCulled = false;
    this.markers.count = 0;
    this.scene.add(this.rings, this.markers);
  }

  /**
   * Room in the instance buffer for `need` people. WEB-0004: one mesh for
   * every box of every person — one per part was thirteen draw calls, and
   * thirteen more in the shadow pass. An instanced mesh cannot grow, so when
   * the town outgrows it a larger one takes its place and every slot is
   * repainted on the next frame.
   */
  private ensurePeople(need: number): void {
    if (this.people !== null && need <= this.capacity) return;
    const capacity = need + PEOPLE_HEADROOM;
    if (this.people !== null) {
      this.scene.remove(this.people);
      this.people.dispose();
    }
    if (this.blobs !== null) {
      this.scene.remove(this.blobs);
      this.blobs.dispose();
    }
    const people = new THREE.InstancedMesh(this.unitBox, this.peopleMaterial, capacity * PERSON_BOXES);
    people.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
    people.frustumCulled = false;
    people.castShadow = true;
    people.receiveShadow = true;
    people.count = 0;
    // Allocate the colour buffer now; `setColorAt` would do it on first use.
    people.setColorAt(0, this.color.set(0xffffff));
    this.people = people;
    this.scene.add(people);
    if (this.blobMaterial !== null) {
      this.blobs = new THREE.InstancedMesh(this.unitBox, this.blobMaterial, capacity);
      this.blobs.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
      this.blobs.frustumCulled = false;
      this.blobs.count = 0;
      this.scene.add(this.blobs);
    }
    this.capacity = capacity;
    this.slots = [];
    this.repainted = true;
  }

  /** A vertical gradient the renderer owns, because the page cannot know the sim clock. */
  private buildSky(): void {
    const rows = 32;
    const texture = new THREE.DataTexture(new Uint8Array(rows * 4), 1, rows, THREE.RGBAFormat);
    texture.colorSpace = THREE.SRGBColorSpace;
    texture.magFilter = THREE.LinearFilter;
    texture.minFilter = THREE.LinearFilter;
    this.skyTexture = texture;
    this.scene.background = texture;
  }

  /**
   * Little puffs of flat white boxes drifting east over the meadow. A single
   * slab reads as a glass pane over the field, so each cloud is a few boxes
   * clustered — a slab with lobes, in the town's own box idiom. They sell the
   * fog as weather: a cloud slides through the haze where the ground is
   * already gone, and the world reads as somewhere rather than a slab.
   * Tinted from the sky once a frame; fogged like everything else. They fly
   * above the tallest building.
   */
  private buildClouds(map: TownMap): void {
    const material = new THREE.MeshBasicMaterial({
      color: 0xffffff,
      transparent: true,
      opacity: 0.45,
      toneMapped: false,
    });
    const clouds = new THREE.InstancedMesh(
      new THREE.BoxGeometry(1, 1, 1),
      material,
      CLOUD_COUNT * CLOUD_LOBES.length,
    );
    clouds.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
    clouds.frustumCulled = false;
    const radius = this.cloudRadius;
    const tallest = Math.max(1, ...map.buildings.map((b) => b.floors)) * STOREY;
    this.cloudSpots = Array.from({ length: CLOUD_COUNT }, (_, i) => ({
      x: map.width / 2 + (hash2(i, 3, 71) - 0.5) * 2 * radius,
      z: map.height / 2 + (hash2(i, 5, 72) - 0.5) * 2 * radius,
      y: tallest + 6 + hash2(i, 7, 73) * 5.5,
      sx: 5 + hash2(i, 11, 74) * 9,
      sy: 1 + hash2(i, 13, 75) * 0.4,
      sz: 3.5 + hash2(i, 17, 76) * 3,
      speed: 0.9 + hash2(i, 19, 77) * 1.1,
    }));
    this.clouds = clouds;
    this.scene.add(clouds);
  }

  /** One number for a tile on a floor: the key the seat and facing tables use. */
  private tileKey(x: number, y: number, floor: number): number {
    return (floor * this.mapHeight + Math.round(y)) * this.mapWidth + Math.round(x);
  }

  /**
   * Which way somebody on a tile should face when nobody has said.
   *
   * A seat faces the desk or table it is drawn up to. Anybody standing next to
   * a counter or a table faces that. The map says where the seats are
   * (`seats`, keyed `zone/floor`); what is next to them is in that floor's
   * tiles — the ground for floor 0, a storey's own grid above it.
   */
  private learnSeats(map: TownMap): void {
    const seats = new Set<number>();
    for (const [key, tiles] of Object.entries(map.seats)) {
      const floor = Number(key.split("/")[1] ?? 0);
      for (const [x, y] of tiles) seats.add(this.tileKey(x, y, floor));
    }
    const learn = (
      kinds: KindAt,
      floor: number,
      x0: number,
      y0: number,
      x1: number,
      y1: number,
      centre: [number, number] | null,
    ) => {
      for (let ty = y0; ty <= y1; ty++) {
        for (let tx = x0; tx <= x1; tx++) {
          const kind = kinds(tx, ty);
          if (kind === undefined || SURFACES.has(kind)) continue;
          const side = facingAt(kinds, tx, ty, centre);
          const key = this.tileKey(tx, ty, floor);
          if (side !== null) this.faceYaw.set(key, Math.atan2(side[0], side[1]));
          if (seats.has(key)) this.seatYaw.set(key, side ? Math.atan2(side[0], side[1]) : 0);
        }
      }
    };
    learn(groundKinds(map), 0, 0, 0, map.width - 1, map.height - 1, fountainOf(map));
    for (const storey of map.storeys) {
      const x1 = storey.x0 + (storey.tiles[0]?.length ?? 1) - 1;
      const y1 = storey.y0 + storey.tiles.length - 1;
      learn(storeyKinds(storey), storey.floor, storey.x0, storey.y0, x1, y1, null);
    }
  }

  /**
   * For looking, not for visitors: pose somebody, or light the town as at some
   * other hour, from the console or a screenshot script. Hung on the handle
   * `index.ts` publishes, behind the same `debug` flag as the frame timings.
   */
  private debugHandle(): void {
    if (!this.options.debug) return;
    const handle = window.__jeveWorld?.[this.options.interactive ? "explore" : "hero"];
    if (handle === undefined) return;
    Object.assign(handle, {
      debugPose: (id: string, pose: Parameters<WorldModel["setPose"]>[1]) =>
        this.model.setPose(id, pose),
      debugClock: (minute: number | null) => {
        this.model.clockOverride = minute;
        this.litMinute = null;
      },
      // Fill the town with `count` standing figures, to measure a crowd the
      // fixture does not have yet. The next frame from the server undoes it.
      debugCrowd: (count: number) => {
        const map = this.model.map;
        if (map === null) return 0;
        const open: [number, number][] = [];
        map.tiles.forEach((row, ty) =>
          row.forEach((kind, tx) => {
            if (kind === "plaza" || kind === "path" || kind === "floor") open.push([tx, ty]);
          }),
        );
        this.model.crowd = Array.from({ length: Math.min(count, open.length) }, (_, i) => {
          const [x, y] = open[Math.floor(hash2(i, count, 7) * open.length)] ?? [0, 0];
          return { x, y, phase: hash2(i, 1, 8) * Math.PI * 2, tint: hash2(i, 2, 9) };
        });
        return this.model.crowd.length;
      },
    });
  }

  // -- light ---------------------------------------------------------------

  /** Bring the sky, the sun and the lamps to the model's minute of the day. */
  private light(dt: number): void {
    const want = this.model.minute;
    if (this.litMinute === null) this.litMinute = want;
    else {
      // Forwards round the clock, so 23:45 to 00:00 is a quarter of an hour.
      const ahead = (((want - this.litMinute) % 1440) + 1440) % 1440;
      const delta = ahead > 720 ? ahead - 1440 : ahead;
      this.litMinute += delta * (1 - Math.exp(-dt / 1200));
      if (Math.abs(want - this.litMinute) < 0.05) this.litMinute = want;
    }
    if (Math.abs(this.litMinute - this.drawnMinute) < 0.02) return;
    this.drawnMinute = this.litMinute;
    const sky = skyAt(this.litMinute);

    if (this.hemi !== null) {
      this.hemi.color.set(sky.hemiSky);
      this.hemi.groundColor.set(sky.hemiGround);
      this.hemi.intensity = sky.hemiIntensity;
    }
    if (this.sun !== null) {
      this.sun.color.set(sky.sunColor);
      this.sun.intensity = sky.sunIntensity;
      this.aimSun(this.sun, sky.sunDirection);
    }
    if (this.fill !== null) {
      this.fill.color.set(sky.hemiSky);
      this.fill.intensity = sky.fillIntensity;
    }
    if (this.renderer !== null) this.renderer.toneMappingExposure = sky.exposure;
    this.paintSky(sky);
    this.paintGlow(sky);
    if (this.scene.fog !== null) {
      // Fog is the sky at the horizon: the bottom of the gradient lifted a
      // little towards the top, so whatever it eats it eats into sky.
      this.scene.fog.color.copy(
        this.color.set(sky.bottom).lerp(this.colorB.set(sky.top), 0.35),
      );
    }
    if (this.clouds !== null) {
      // Unlit, so tinted by hand: near-white by day, settling into the murk
      // with the lamps.
      const material = this.clouds.material as THREE.MeshBasicMaterial;
      material.color.copy(
        this.color.set("#ffffff").lerp(this.colorB.set(sky.bottom), 0.2 + 0.5 * sky.lamps),
      );
    }
  }

  private aimSun(sun: THREE.DirectionalLight, direction: [number, number, number]): void {
    const dir = this.vector.set(...direction).normalize();
    const centre = this.townCentre.clone();
    if (sun.castShadow) {
      // Snap the frustum's centre to whole shadow texels in the light's own
      // frame. Without it a shadow edge shimmers as the sun creeps.
      const texel = (this.townRadius * 2) / sun.shadow.mapSize.x;
      this.basis.lookAt(dir, new THREE.Vector3(0, 0, 0), new THREE.Vector3(0, 1, 0));
      const inverse = this.basis.clone().invert();
      centre.applyMatrix4(inverse);
      centre.x = Math.round(centre.x / texel) * texel;
      centre.y = Math.round(centre.y / texel) * texel;
      centre.applyMatrix4(this.basis);
    }
    sun.target.position.copy(centre);
    sun.position.copy(centre).addScaledVector(dir, this.sunDistance);
    sun.target.updateMatrixWorld();
  }

  private paintSky(sky: Sky): void {
    const texture = this.skyTexture;
    if (texture === null) return;
    const data = texture.image.data as Uint8Array;
    const rows = data.length / 4;
    const bottom = this.color.set(sky.bottom);
    const top = this.colorB.set(sky.top);
    for (let row = 0; row < rows; row++) {
      // Row 0 is the bottom of the screen. Most of the change is low down,
      // where the horizon would be.
      const t = (row / (rows - 1)) ** 0.8;
      // The texture is tagged sRGB, so it wants sRGB bytes; `Color` is linear.
      const mixed = bottom.clone().lerp(top, t).convertLinearToSRGB();
      data.set([mixed.r * 255, mixed.g * 255, mixed.b * 255, 255], row * 4);
    }
    texture.needsUpdate = true;
  }

  private paintGlow(sky: Sky): void {
    const lit = sky.lamps;
    const glass = this.colorB.set(sky.top).lerp(this.color.set(0xffffff), 0.45);
    const warm = new THREE.Color("#ffd98a");
    const lampOff = new THREE.Color("#8d8f96");
    const lampOn = new THREE.Color("#fff1c4");
    for (const storey of this.storeys) {
      storey.glowKinds.forEach((kind, i) => {
        const base = storey.glowBase[i] ?? warm;
        const colour =
          kind === "window"
            ? glass.clone().lerp(warm, lit)
            : kind === "lamp"
              ? lampOff.clone().lerp(lampOn, lit)
              : kind === "sign"
                ? base
                : base.clone().multiplyScalar(0.75 + 0.25 * lit);
        storey.glow.setColorAt(i, colour);
      });
      if (storey.glow.instanceColor) storey.glow.instanceColor.needsUpdate = true;
      const material = storey.pool.material as THREE.MeshBasicMaterial;
      material.opacity = lit * 0.55;
    }
    this.poolsLit = lit > 0.01;
    this.applyLevelCut();
  }

  /**
   * Show each storey's meshes or not, from the model's level cut: everything
   * above the cut is hidden, pools only while the lamps are on anyway.
   */
  private applyLevelCut(): void {
    const cut = this.model.levelCut;
    this.appliedCut = cut;
    for (const storey of this.storeys) {
      const shown = cut === null || storey.floor <= cut;
      storey.town.visible = shown;
      storey.glow.visible = shown;
      storey.pool.visible = shown && this.poolsLit;
    }
  }

  // -- camera --------------------------------------------------------------

  private placeCamera(): void {
    const { x, z } = this.eased;
    const horizontal = Math.cos(ISO_ELEVATION) * this.cameraDistance;
    this.camera.position.set(
      x + Math.sin(ISO_AZIMUTH) * horizontal,
      Math.sin(ISO_ELEVATION) * this.cameraDistance,
      z + Math.cos(ISO_AZIMUTH) * horizontal,
    );
    this.camera.lookAt(x, 0, z);
    this.applyFrustum();
  }

  private applyFrustum(): void {
    const aspect = this.width / Math.max(1, this.height);
    // `span` is how many tiles should fit across the narrower dimension.
    const half = this.eased.span / 2;
    const halfW = aspect >= 1 ? half * aspect : half;
    const halfH = aspect >= 1 ? half : half / aspect;
    this.camera.left = -halfW;
    this.camera.right = halfW;
    this.camera.top = halfH;
    this.camera.bottom = -halfH;
    this.camera.updateProjectionMatrix();
    this.camera.updateMatrixWorld();
  }

  /** Ease towards a view. Used by the hero's automatic camera. */
  lookAt(target: ViewTarget): void {
    this.target = target;
  }

  resize(): void {
    const rect = this.container.getBoundingClientRect();
    this.width = Math.max(1, Math.floor(rect.width));
    this.height = Math.max(1, Math.floor(rect.height));
    this.renderer?.setSize(this.width, this.height, false);
    this.applyFrustum();
  }

  /** World (tile x, height, tile y) to CSS pixels inside the container. */
  project = (x: number, height: number, y: number): { x: number; y: number } => {
    // One scratch vector: this runs per bubble per frame, and per person per click.
    const v = this.projected.set(x, height, y).project(this.camera);
    return { x: ((v.x + 1) / 2) * this.width, y: ((1 - v.y) / 2) * this.height };
  };

  /** CSS pixels to the tile under them, on the ground plane. */
  unproject(px: number, py: number): { x: number; y: number } | null {
    const ndc = new THREE.Vector3((px / this.width) * 2 - 1, 1 - (py / this.height) * 2, -1);
    const origin = ndc.clone().unproject(this.camera);
    const direction = new THREE.Vector3();
    this.camera.getWorldDirection(direction);
    if (Math.abs(direction.y) < 1e-6) return null;
    const t = -origin.y / direction.y;
    return { x: origin.x + direction.x * t + 0.5, y: origin.z + direction.z * t + 0.5 };
  }

  // -- people --------------------------------------------------------------

  private lookOf(key: string, role: string | null, body: string, accent: string): Look {
    const cached = this.looks.get(key);
    if (cached !== undefined) return cached;
    // The crowd is demand, not people (WEB-0002), and the page says "grey
    // figures are customers": with a head this size, a grey jumper under brown
    // hair is not a grey figure. So the crowd is grey all through.
    const crowd = role === null;
    const skin = crowd ? pick(CROWD_SKIN, key, "#c9c5bf") : pick(SKIN_TONES, key, "#d9a57c");
    const hair = crowd ? pick(CROWD_HAIR, `${key}h`, "#8a8782") : pick(HAIR_TONES, `${key}h`, "#2b1d14");
    const trousers = crowd ? "#6d6f76" : pick(TROUSER_TONES, `${key}t`, "#2f3542");
    const wear = role === null ? null : lookFor(role);
    const named = (c: string) => (c === "org" ? accent : c === "hair" ? hair : c);
    const hat = HATS[wear?.hat ?? "none"];

    const colors: THREE.Color[] = [];
    const sizes: ([number, number, number] | null)[] = [];
    const offsets: [number, number, number][] = [];
    for (const part of RIG) {
      let color = body;
      let size: [number, number, number] | null = part.size;
      if (part.name === "legL" || part.name === "legR") color = trousers;
      else if (part.name === "armL" || part.name === "armR") color = shade(body, -0.12);
      else if (part.name === "head") color = skin;
      else if (part.name === "eyeL" || part.name === "eyeR") color = "#1d1a1a";
      else if (part.name === "hairBack") color = hair;
      else if (part.name === "hairTop") {
        color = hair;
        if (hat.coversHair) size = null;
      } else if (part.name === "front") {
        if (wear === null || wear.front === "none") size = null;
        else {
          color = named(wear.frontColor);
          if (wear.front === "apron") size = [0.5, 0.42, 0.02];
        }
      }
      colors.push(new THREE.Color(color));
      sizes.push(size);
      offsets.push(part.offset);
    }
    for (const piece of [hat.a, hat.b]) {
      colors.push(new THREE.Color(named(wear?.hatColor ?? "hair")));
      sizes.push(piece?.size ?? null);
      offsets.push(piece?.offset ?? [0, 0, 0]);
    }
    const look = { colors, sizes, offsets };
    this.looks.set(key, look);
    return look;
  }

  /**
   * Write one person's boxes into the instance buffer.
   *
   * `swing` is the angle of the walk cycle, `sit` runs from standing (0) to
   * seated (1), `reach` lifts the arms forward, `lift` is the breathing bob
   * of everything above the hips, and `floorY` is the height of the floor
   * they stand on.
   */
  private pose(
    slot: number,
    look: Look,
    repaint: boolean,
    x: number,
    z: number,
    floorY: number,
    yaw: number,
    swing: number,
    sit: number,
    reach: number,
    lift: number,
  ): void {
    const people = this.people;
    if (people === null) return;
    // Sitting lowers the hips onto the seat and swings the legs out in front.
    const drop = sit * (SEAT_TOP - 0.34 + 0.11);
    this.root.makeRotationY(yaw).setPosition(x, floorY + drop, z);
    const angles: Record<Joint, number> = {
      legL: swing * (1 - sit) - sit * (Math.PI / 2),
      legR: -swing * (1 - sit) - sit * (Math.PI / 2),
      armL: -swing * 0.85 * (1 - sit) - reach,
      armR: swing * 0.85 * (1 - sit) - reach,
      torso: 0,
    };
    const base = slot * PERSON_BOXES;
    for (let i = 0; i < PERSON_BOXES; i++) {
      const size = look.sizes[i];
      if (size === null || size === undefined) {
        people.setMatrixAt(base + i, this.hidden);
        continue;
      }
      const part = RIG[i];
      const joint: Joint = part?.joint ?? "torso";
      const pivot = part?.pivot ?? [0, HEAD_TOP, 0];
      const offset = look.offsets[i] ?? [0, 0, 0];
      const a = angles[joint];
      const cos = Math.cos(a);
      const sin = Math.sin(a);
      const up = joint === "legL" || joint === "legR" ? 0 : lift;
      // Rotation about x through the pivot, then the box's own size: written
      // out, because thirteen boxes times a few hundred people is every frame.
      this.local.set(
        size[0], 0, 0, pivot[0] + offset[0],
        0, cos * size[1], -sin * size[2], pivot[1] + up + cos * offset[1] - sin * offset[2],
        0, sin * size[1], cos * size[2], pivot[2] + sin * offset[1] + cos * offset[2],
        0, 0, 0, 1,
      );
      this.out.multiplyMatrices(this.root, this.local);
      people.setMatrixAt(base + i, this.out);
      const color = look.colors[i];
      if (repaint && color !== undefined) people.setColorAt(base + i, color);
    }
  }

  /**
   * Whether a slot in the instance buffer has changed hands since last frame.
   *
   * Matrices change every frame; colours only when somebody comes onto the map
   * or leaves it and everyone behind them moves up one. Uploading 3,000
   * colours sixty times a second to say the same thing was the larger half of
   * the per-frame traffic.
   */
  private claims(slot: number, key: string): boolean {
    if (this.slots[slot] === key) return false;
    this.slots[slot] = key;
    this.repainted = true;
    return true;
  }

  private drawPeople(now: number, dt: number): void {
    // An upper bound — everyone, at home or not, plus the crowd — is cheap
    // to ask for and never leaves anybody undrawn.
    this.ensurePeople(this.model.walkers.size + this.model.crowd.length);
    let count = 0;
    let selected = 0;
    const k = 1 - Math.exp(-dt / 140);

    for (const walker of this.model.walkers.values()) {
      if (!walker.visible || !this.model.shown(walker)) {
        this.drawn.delete(walker.id);
        continue;
      }
      const palette = this.palettes.get(walker.orgId);
      const look = this.lookOf(
        walker.id,
        walker.role,
        palette?.body ?? NEUTRAL_BODY,
        palette?.accent ?? NEUTRAL_ACCENT,
      );

      let state = this.drawn.get(walker.id);
      if (state === undefined) {
        state = { x: walker.x, y: walker.y, yaw: walker.heading, cycle: 0, sit: 0, swing: 0, seenAt: now };
        this.drawn.set(walker.id, state);
      }
      // The walk cycle advances with ground covered, so it looks the same at
      // 15 fps and at 120; capped, because people here cross the map in
      // seconds and legs that kept up would be a blur.
      const moved = Math.hypot(walker.x - state.x, walker.y - state.y);
      const step = Math.min((moved / STRIDE) * Math.PI * 2, (MAX_STEPS_PER_SECOND * Math.PI * 2 * dt) / 1000);
      state.cycle += moved < 3 ? step : 0;
      state.x = walker.x;
      state.y = walker.y;
      const striding = walker.walking && moved > 1e-4;
      state.swing += ((striding ? Math.sin(state.cycle) * 0.75 : 0) - state.swing) * Math.min(1, k * 2.5);

      const tile = this.tileKey(walker.x, walker.y, walker.floor);
      const still = !walker.walking;
      // WEB-0004: the one inference the renderer makes. `seated` wins when set.
      const seated = walker.seated ?? (still && this.seatYaw.has(tile));
      state.sit += ((seated ? 1 : 0) - state.sit) * k;

      const other = walker.talkingTo === undefined ? undefined : this.model.walkers.get(walker.talkingTo);
      let yaw = walker.heading;
      if (other !== undefined && other.visible) yaw = Math.atan2(other.x - walker.x, other.y - walker.y);
      else if (walker.facing !== undefined) yaw = walker.facing;
      else if (still) yaw = this.seatYaw.get(tile) ?? this.faceYaw.get(tile) ?? walker.heading;
      state.yaw = turn(state.yaw, yaw, k);

      const talking = other !== undefined && other.visible;
      const bounce = striding ? Math.abs(Math.sin(state.cycle)) * 0.07 : 0;
      const breath = Math.sin(now / 900 + walker.phase) * 0.012;
      // Seated people have their hands on the desk; talkers gesture.
      const reach = state.sit * 1.05 + (talking ? 0.35 + Math.sin(now / 230 + walker.phase) * 0.3 : 0);
      const floorY = walker.floor * STOREY;
      const repaint = this.claims(count, walker.id);
      this.pose(count, look, repaint, walker.x, walker.y, floorY, state.yaw, state.swing, state.sit, reach, bounce + breath);
      this.blob(count, walker.x, walker.y, floorY);
      if (walker.selected === true && selected < MAX_SELECTED) {
        this.select(selected++, walker, now, state.sit);
      }
      count++;
    }

    // The crowd: counterparties, drawn in greys and bare-headed so staff stay
    // legible. Demand, not people: they stand where they are put, on the ground.
    for (const dot of this.model.crowd) {
      const grey = 0.5 + dot.tint * 0.3;
      const key = `crowd:${dot.tint.toFixed(4)}`;
      let look = this.looks.get(key);
      if (look === undefined) {
        const body = `#${this.color.setRGB(grey, grey, grey * 1.05, THREE.SRGBColorSpace).getHexString()}`;
        look = this.lookOf(key, null, body, body);
      }
      // The model scatters the crowd a little about its spots. On a chair that
      // would seat somebody half off it, so a seated customer is drawn square.
      const tile = this.tileKey(dot.x, dot.y, 0);
      const seat = this.seatYaw.get(tile);
      const [x, y] = seat === undefined ? [dot.x, dot.y] : [Math.round(dot.x), Math.round(dot.y)];
      const yaw = seat ?? this.faceYaw.get(tile) ?? dot.phase;
      const breath = Math.sin(now / 900 + dot.phase) * 0.012;
      const sit = seat === undefined ? 0 : 1;
      this.pose(count, look, this.claims(count, key), x, y, 0, yaw, 0, sit, sit * 0.6, breath);
      this.blob(count, x, y, 0);
      count++;
    }

    if (this.people !== null) {
      this.people.count = count * PERSON_BOXES;
      this.people.instanceMatrix.needsUpdate = true;
      if (this.repainted && this.people.instanceColor) {
        this.people.instanceColor.needsUpdate = true;
        this.repainted = false;
      }
    }
    if (this.blobs !== null) {
      this.blobs.count = count;
      this.blobs.instanceMatrix.needsUpdate = true;
    }
    for (const mesh of [this.rings, this.markers]) {
      if (mesh === null) continue;
      mesh.count = selected;
      mesh.instanceMatrix.needsUpdate = true;
    }
  }

  private blob(slot: number, x: number, z: number, floorY: number): void {
    if (this.blobs === null) return;
    this.local.makeScale(0.8, 0.01, 0.8).setPosition(x, floorY + 0.012, z);
    this.blobs.setMatrixAt(slot, this.local);
  }

  private select(slot: number, walker: Walker, now: number, sit: number): void {
    const floorY = walker.floor * STOREY;
    const pulse = 1 + Math.sin(now / 260) * 0.08;
    this.local.makeScale(pulse, 1, pulse).setPosition(walker.x, floorY + 0.04, walker.y);
    this.rings?.setMatrixAt(slot, this.local);
    const hover = floorY + HEAD_TOP + 0.85 - sit * 0.1 + Math.sin(now / 320) * 0.08;
    this.local
      .makeRotationY(now / 600)
      .multiply(this.out.makeRotationZ(Math.PI / 4))
      .scale(this.vector.set(0.26, 0.26, 0.26))
      .setPosition(walker.x, hover, walker.y);
    this.markers?.setMatrixAt(slot, this.local);
  }

  // -- frame ---------------------------------------------------------------

  /**
   * Advance the model and, if `draw`, the picture.
   *
   * The model always moves on — positions are what tests and clicks read — but
   * nothing is drawn while the canvas is off-screen or the tab is hidden, and a
   * software renderer draws at a quarter of the rate.
   */
  frame(now: number, draw = true): void {
    const moving = this.model.update(now);
    if (!draw) return;
    if (this.software !== null && now - this.lastDrawAt < SOFTWARE_FRAME_MS) return;
    const dt = this.lastDrawAt === 0 ? 16 : Math.min(250, now - this.lastDrawAt);
    this.lastDrawAt = now;

    if (this.controls !== null) {
      this.controls.update();
      this.clampPan();
    } else {
      const k = 0.035;
      this.eased.x += (this.target.x - this.eased.x) * k;
      this.eased.z += (this.target.z - this.eased.z) * k;
      this.eased.span += (this.target.span - this.eased.span) * k;
      this.placeCamera();
    }

    if (this.people !== null) {
      this.light(dt);
      if (this.appliedCut !== this.model.levelCut) this.applyLevelCut();
      this.drawPeople(now, dt);
      this.driftClouds(dt);
    }
    this.renderer?.render(this.scene, this.camera);
    this.measure(now, moving);
  }

  /**
   * The edge of the world: the target may roam the map plus a margin of
   * meadow — far enough to feel the haze and the clouds, not so far that the
   * town leaves the screen for good. The camera is shifted by the same delta
   * so the view stops dead instead of hopping back.
   */
  private clampPan(): void {
    const controls = this.controls;
    if (controls === null) return;
    const target = controls.target;
    const x = Math.min(this.panX[1], Math.max(this.panX[0], target.x));
    const z = Math.min(this.panZ[1], Math.max(this.panZ[0], target.z));
    if (x === target.x && z === target.z) return;
    this.camera.position.x += x - target.x;
    this.camera.position.z += z - target.z;
    target.x = x;
    target.z = z;
  }

  /** Move every cloud a little east; one that leaves the field re-enters upwind. */
  private driftClouds(dt: number): void {
    const clouds = this.clouds;
    if (clouds === null) return;
    const centre = this.townCentre.x;
    const radius = this.cloudRadius;
    const seconds = dt / 1000;
    this.cloudSpots.forEach((cloud, i) => {
      cloud.x += cloud.speed * seconds;
      if (cloud.x - centre > radius) cloud.x -= radius * 2;
      CLOUD_LOBES.forEach(([dx, dy, dz, kx, ky, kz], l) => {
        this.local
          .makeScale(cloud.sx * kx, cloud.sy * ky, cloud.sz * kz)
          .setPosition(cloud.x + dx * cloud.sx, cloud.y + dy, cloud.z + dz * cloud.sz);
        clouds.setMatrixAt(i * CLOUD_LOBES.length + l, this.local);
      });
    });
    clouds.instanceMatrix.needsUpdate = true;
  }

  private measure(now: number, moving: number): void {
    if (!this.options.debug) return;
    if (this.lastFrameAt > 0) this.frames.push(now - this.lastFrameAt);
    this.lastFrameAt = now;
    if (this.frames.length >= 240) {
      const sorted = [...this.frames].sort((a, b) => a - b);
      const mean = sorted.reduce((s, v) => s + v, 0) / sorted.length;
      const p95 = sorted[Math.floor(sorted.length * 0.95)] ?? 0;
      console.debug(
        `jeve world: ${(1000 / mean).toFixed(0)} fps mean, ` +
          `${mean.toFixed(1)}ms mean / ${p95.toFixed(1)}ms p95 per frame, ${moving} walking`,
      );
      this.frames = [];
    }
  }

  dispose(): void {
    this.controls?.dispose();
    this.scene.traverse((node) => {
      if (node instanceof THREE.Mesh) {
        node.geometry.dispose();
        const materials = Array.isArray(node.material) ? node.material : [node.material];
        for (const material of materials) {
          if (material instanceof THREE.MeshBasicMaterial) material.map?.dispose();
          material.dispose();
        }
      }
    });
    this.unitBox.dispose();
    this.peopleMaterial.dispose();
    this.blobMaterial?.dispose();
    this.falloff?.dispose();
    this.skyTexture?.dispose();
    this.sun?.shadow.map?.dispose();
    this.renderer?.dispose();
    this.renderer?.forceContextLoss();
    this.canvas.remove();
  }
}
