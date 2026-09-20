/**
 * The renderer: a view over `WorldModel`, and nothing else.
 *
 * An orthographic camera at an isometric angle; flat-shaded boxes; every static
 * voxel in one instanced mesh and every person in four (one per body part), so
 * the whole town is a handful of draw calls. Nothing in here holds simulation
 * state, and everything it needs to know comes from the model each frame.
 *
 * The camera object is created whether or not WebGL is available: projection
 * is plain matrix arithmetic, and picking and labels depend on it.
 */
import { ORG_PALETTE, type TownMap } from "@jeve/contracts";
import * as THREE from "three";
import { MapControls } from "three/addons/controls/MapControls.js";

import type { WorldModel } from "./model";
import { HAIR_TONES, PERSON_PARTS, SKIN_TONES, buildVoxels } from "./voxels";

const MAX_PEOPLE = 96;
const ISO_ELEVATION = Math.atan(1 / Math.SQRT2); // true isometric: ~35.26 degrees
const ISO_AZIMUTH = Math.PI / 4;
const CAMERA_DISTANCE = 80;

export type ViewTarget = { x: number; z: number; span: number };

function tone(palette: string[], key: string): string {
  let h = 0;
  for (let i = 0; i < key.length; i++) h = (h * 31 + key.charCodeAt(i)) >>> 0;
  return palette[h % palette.length] ?? palette[0] ?? "#888888";
}

export class WorldView {
  readonly camera: THREE.OrthographicCamera;
  readonly glOk: boolean;
  readonly canvas: HTMLCanvasElement;

  private renderer: THREE.WebGLRenderer | null = null;
  private scene = new THREE.Scene();
  private parts: THREE.InstancedMesh[] = [];
  private shadows: THREE.InstancedMesh | null = null;
  private controls: MapControls | null = null;
  private width = 1;
  private height = 1;
  private target: ViewTarget = { x: 20, z: 14, span: 41 };
  private eased: ViewTarget = { x: 20, z: 14, span: 41 };
  private scratch = new THREE.Object3D();
  private color = new THREE.Color();
  private frames: number[] = [];
  private lastFrameAt = 0;

  constructor(
    private container: HTMLElement,
    private model: WorldModel,
    private options: { interactive: boolean; debug: boolean },
  ) {
    this.canvas = document.createElement("canvas");
    this.canvas.style.cssText = "display:block;width:100%;height:100%;touch-action:none";
    this.canvas.dataset.testid = "world-canvas";
    container.appendChild(this.canvas);

    this.camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.1, 400);
    this.placeCamera();

    let ok = false;
    try {
      this.renderer = new THREE.WebGLRenderer({
        canvas: this.canvas,
        antialias: true,
        alpha: true,
        powerPreference: "high-performance",
      });
      this.renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
      this.renderer.setClearColor(0x000000, 0);
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

  // -- scene ---------------------------------------------------------------

  build(map: TownMap): void {
    const hemi = new THREE.HemisphereLight(0xffffff, 0x8a93a6, 1.15);
    const sun = new THREE.DirectionalLight(0xfff2dc, 1.7);
    sun.position.set(-30, 60, 20);
    this.scene.add(hemi, sun);

    const voxels = buildVoxels(map);
    const box = new THREE.BoxGeometry(1, 1, 1);
    // One material for the whole town: white, flat-shaded, tinted per instance.
    const material = new THREE.MeshLambertMaterial({ color: 0xffffff, flatShading: true });
    const town = new THREE.InstancedMesh(box, material, voxels.length);
    voxels.forEach((voxel, i) => {
      this.scratch.position.set(voxel.x, voxel.y, voxel.z);
      this.scratch.rotation.set(0, 0, 0);
      this.scratch.scale.set(voxel.sx, voxel.sy, voxel.sz);
      this.scratch.updateMatrix();
      town.setMatrixAt(i, this.scratch.matrix);
      town.setColorAt(i, this.color.set(voxel.color));
    });
    town.instanceMatrix.needsUpdate = true;
    if (town.instanceColor) town.instanceColor.needsUpdate = true;
    // Instances span the whole map; the mesh's own bounds are one unit cube.
    town.frustumCulled = false;
    this.scene.add(town);

    this.parts = PERSON_PARTS.map(() => {
      const mesh = new THREE.InstancedMesh(box, material, MAX_PEOPLE);
      mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
      mesh.frustumCulled = false;
      mesh.count = 0;
      this.scene.add(mesh);
      return mesh;
    });

    const shadowMaterial = new THREE.MeshBasicMaterial({
      color: 0x000000,
      transparent: true,
      opacity: 0.18,
      depthWrite: false,
    });
    this.shadows = new THREE.InstancedMesh(box, shadowMaterial, MAX_PEOPLE);
    this.shadows.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
    this.shadows.frustumCulled = false;
    this.shadows.count = 0;
    this.scene.add(this.shadows);
  }

  // -- camera --------------------------------------------------------------

  private placeCamera(): void {
    const { x, z } = this.eased;
    const horizontal = Math.cos(ISO_ELEVATION) * CAMERA_DISTANCE;
    this.camera.position.set(
      x + Math.sin(ISO_AZIMUTH) * horizontal,
      Math.sin(ISO_ELEVATION) * CAMERA_DISTANCE,
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
    const v = new THREE.Vector3(x, height, y).project(this.camera);
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

  // -- frame ---------------------------------------------------------------

  frame(now: number): void {
    const moving = this.model.update(now);

    if (this.controls !== null) {
      this.controls.update();
    } else {
      const k = 0.035;
      this.eased.x += (this.target.x - this.eased.x) * k;
      this.eased.z += (this.target.z - this.eased.z) * k;
      this.eased.span += (this.target.span - this.eased.span) * k;
      this.placeCamera();
    }

    let count = 0;
    const place = (
      x: number,
      y: number,
      heading: number,
      phase: number,
      walking: boolean,
      body: string,
      key: string,
    ) => {
      if (count >= MAX_PEOPLE) return;
      // Walking is a quick bounce; standing is a slow breath. Never still.
      const bob = walking
        ? Math.abs(Math.sin(now / 95 + phase)) * 0.09
        : Math.sin(now / 900 + phase) * 0.018;
      PERSON_PARTS.forEach((part, i) => {
        const mesh = this.parts[i];
        if (mesh === undefined) return;
        this.scratch.position.set(x, part.y + bob, y);
        this.scratch.rotation.set(0, heading, 0);
        this.scratch.scale.set(part.sx, part.sy, part.sz);
        this.scratch.updateMatrix();
        mesh.setMatrixAt(count, this.scratch.matrix);
        const tint =
          part.name === "body"
            ? body
            : part.name === "head"
              ? tone(SKIN_TONES, key)
              : part.name === "hair"
                ? tone(HAIR_TONES, `${key}h`)
                : "#2f3542";
        mesh.setColorAt(count, this.color.set(tint));
      });
      if (this.shadows !== null) {
        this.scratch.position.set(x, 0.012, y);
        this.scratch.rotation.set(0, 0, 0);
        this.scratch.scale.set(0.56, 0.01, 0.56);
        this.scratch.updateMatrix();
        this.shadows.setMatrixAt(count, this.scratch.matrix);
      }
      count++;
    };

    for (const walker of this.model.walkers.values()) {
      if (!walker.visible) continue;
      const body = ORG_PALETTE[walker.orgId]?.body ?? "#999999";
      place(walker.x, walker.y, walker.heading, walker.phase, walker.walking, body, walker.id);
    }
    // The crowd: counterparties, drawn in greys so staff stay legible.
    for (const dot of this.model.crowd) {
      const grey = 0.55 + dot.tint * 0.3;
      const body = `#${this.color.setRGB(grey, grey, grey * 1.04).getHexString()}`;
      place(dot.x, dot.y, dot.phase, dot.phase, false, body, `c${dot.tint}`);
    }

    for (const mesh of [...this.parts, this.shadows]) {
      if (mesh === null || mesh === undefined) continue;
      mesh.count = count;
      mesh.instanceMatrix.needsUpdate = true;
      if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
    }

    this.renderer?.render(this.scene, this.camera);
    this.measure(now, moving);
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
        for (const material of materials) material.dispose();
      }
    });
    this.renderer?.dispose();
    this.renderer?.forceContextLoss();
    this.canvas.remove();
  }
}
