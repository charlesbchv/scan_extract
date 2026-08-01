import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

import type { Vec3Tuple, VolumeData } from '../types';
import {
  hasActiveClipping,
  normalizeClippingBounds,
  type ClippingBounds,
} from './clipping';
import { volumeFragmentShader, volumeVertexShader } from './shaders';
import {
  buildTransferLut,
  TRANSFER_PRESETS,
  type TransferPresetId,
} from './transferFunctions';

export type RenderQuality = 'performance' | 'balanced' | 'cinematic';

export const QUALITY_SETTINGS: Record<
  RenderQuality,
  {
    steps: number;
    interactiveSteps: number;
    pixelRatio: number;
    interactivePixelRatio: number;
    label: string;
  }
> = {
  performance: {
    steps: 220,
    interactiveSteps: 72,
    pixelRatio: 1,
    interactivePixelRatio: 0.75,
    label: 'Performance',
  },
  balanced: {
    steps: 420,
    interactiveSteps: 96,
    pixelRatio: 1.45,
    interactivePixelRatio: 0.78,
    label: 'Balanced',
  },
  cinematic: {
    steps: 720,
    interactiveSteps: 128,
    pixelRatio: 2,
    interactivePixelRatio: 0.9,
    label: 'Cinematic',
  },
};

const INTERACTION_REFINEMENT_DELAY_MS = 140;

interface VolumeUniforms {
  [name: string]: THREE.IUniform;
  uVolume: THREE.IUniform<THREE.Data3DTexture>;
  uTransfer: THREE.IUniform<THREE.DataTexture>;
  uTextureSize: THREE.IUniform<THREE.Vector3>;
  uVoxelSpacing: THREE.IUniform<THREE.Vector3>;
  uClipMin: THREE.IUniform<THREE.Vector3>;
  uClipMax: THREE.IUniform<THREE.Vector3>;
  uLightDirection: THREE.IUniform<THREE.Vector3>;
  uSteps: THREE.IUniform<number>;
  uDensity: THREE.IUniform<number>;
  uSurfaceEmphasis: THREE.IUniform<number>;
  uShadows: THREE.IUniform<number>;
  uAmbient: THREE.IUniform<number>;
  uDiffuse: THREE.IUniform<number>;
  uSpecular: THREE.IUniform<number>;
  uInteractive: THREE.IUniform<number>;
}

export interface RendererMetrics {
  renderMilliseconds: number;
  samples: number;
  textureBytes: number;
  max3DTextureSize: number;
}

export type { ClippingBounds } from './clipping';

export class VolumeRayMarcher {
  readonly canvas: HTMLCanvasElement;
  readonly max3DTextureSize: number;
  onRender?: (metrics: RendererMetrics) => void;

  private readonly container: HTMLElement;
  private readonly renderer: THREE.WebGLRenderer;
  private readonly scene = new THREE.Scene();
  private readonly camera = new THREE.PerspectiveCamera(34, 1, 0.1, 5000);
  private readonly controls: OrbitControls;
  private readonly resizeObserver: ResizeObserver;
  private volumeObject?: THREE.Group;
  private boundsOutline?: THREE.LineSegments;
  private material?: THREE.ShaderMaterial;
  private uniforms?: VolumeUniforms;
  private volumeTexture?: THREE.Data3DTexture;
  private transferTexture?: THREE.DataTexture;
  private volume?: VolumeData;
  private preset: TransferPresetId = 'lung';
  private quality: RenderQuality = 'balanced';
  private density = 1;
  private surfaceEmphasis = 0.24;
  private shadowsEnabled = false;
  private readonly clipMinimum = new THREE.Vector3(0, 0, 0);
  private readonly clipMaximum = new THREE.Vector3(1, 1, 1);
  private renderFrame: number | undefined;
  private refinementTimer: number | undefined;
  private interactiveRendering = false;
  private disposed = false;

  constructor(container: HTMLElement) {
    this.container = container;
    this.canvas = document.createElement('canvas');
    this.canvas.className = 'volume-canvas';
    this.canvas.setAttribute('aria-label', 'Interactive three-dimensional volume rendering');

    const context = this.canvas.getContext('webgl2', {
      alpha: false,
      antialias: false,
      depth: true,
      powerPreference: 'high-performance',
      preserveDrawingBuffer: false,
    });
    if (!context) {
      throw new Error('This demo requires WebGL 2 and a compatible GPU.');
    }

    this.renderer = new THREE.WebGLRenderer({
      canvas: this.canvas,
      context,
      antialias: false,
      alpha: false,
      powerPreference: 'high-performance',
    });
    this.renderer.setClearColor(0x080a0c, 1);
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.max3DTextureSize = context.getParameter(context.MAX_3D_TEXTURE_SIZE) as number;
    container.append(this.canvas);

    this.camera.position.set(350, -390, 290);
    this.controls = new OrbitControls(this.camera, this.canvas);
    this.controls.enableDamping = false;
    this.controls.enablePan = true;
    this.controls.rotateSpeed = 0.72;
    this.controls.zoomSpeed = 0.85;
    this.controls.addEventListener('change', this.requestRender);
    this.controls.addEventListener('start', this.onInteractionStart);
    this.controls.addEventListener('end', this.onInteractionEnd);

    this.scene.add(new THREE.AmbientLight(0xffffff, 0.03));
    this.resizeObserver = new ResizeObserver(this.resize);
    this.resizeObserver.observe(container);
    this.applyQuality();
    this.resize();
  }

  setVolume(volume: VolumeData): void {
    if (this.disposed) {
      throw new Error('Cannot set a volume after the renderer has been disposed.');
    }
    const largestDimension = Math.max(...volume.dimensions);
    if (largestDimension > this.max3DTextureSize) {
      throw new Error(
        `The ${largestDimension}-voxel volume dimension exceeds this GPU's ${this.max3DTextureSize} 3D-texture limit.`,
      );
    }
    if (
      volume.data.length !==
      volume.dimensions[0] * volume.dimensions[1] * volume.dimensions[2]
    ) {
      throw new Error('Volume data length does not match its dimensions.');
    }

    this.disposeVolumeResources();
    this.volume = volume;

    const [width, height, depth] = volume.dimensions;
    this.volumeTexture = new THREE.Data3DTexture(volume.data, width, height, depth);
    this.volumeTexture.format = THREE.RedFormat;
    this.volumeTexture.type = THREE.UnsignedByteType;
    this.volumeTexture.internalFormat = 'R8';
    this.volumeTexture.minFilter = THREE.LinearFilter;
    this.volumeTexture.magFilter = THREE.LinearFilter;
    this.volumeTexture.wrapS = THREE.ClampToEdgeWrapping;
    this.volumeTexture.wrapT = THREE.ClampToEdgeWrapping;
    this.volumeTexture.wrapR = THREE.ClampToEdgeWrapping;
    this.volumeTexture.unpackAlignment = 1;
    this.volumeTexture.generateMipmaps = false;
    this.volumeTexture.colorSpace = THREE.NoColorSpace;
    this.volumeTexture.needsUpdate = true;

    this.transferTexture = this.createTransferTexture();
    const preset = TRANSFER_PRESETS[this.preset];
    this.uniforms = {
      uVolume: { value: this.volumeTexture },
      uTransfer: { value: this.transferTexture },
      uTextureSize: { value: new THREE.Vector3(width, height, depth) },
      uVoxelSpacing: { value: new THREE.Vector3(...volume.spacing) },
      uClipMin: { value: this.clipMinimum.clone() },
      uClipMax: { value: this.clipMaximum.clone() },
      uLightDirection: { value: new THREE.Vector3(-0.45, -0.72, 1).normalize() },
      uSteps: { value: QUALITY_SETTINGS[this.quality].steps },
      uDensity: { value: this.density },
      uSurfaceEmphasis: { value: this.surfaceEmphasis },
      uShadows: { value: this.shadowsEnabled ? 1 : 0 },
      uAmbient: { value: preset.ambient },
      uDiffuse: { value: preset.diffuse },
      uSpecular: { value: preset.specular },
      uInteractive: { value: this.interactiveRendering ? 1 : 0 },
    };

    this.material = new THREE.ShaderMaterial({
      glslVersion: THREE.GLSL3,
      vertexShader: volumeVertexShader,
      fragmentShader: volumeFragmentShader,
      uniforms: this.uniforms,
      side: THREE.BackSide,
      transparent: true,
      premultipliedAlpha: true,
      depthWrite: false,
      depthTest: true,
    });

    const group = new THREE.Group();
    const cubeGeometry = new THREE.BoxGeometry(1, 1, 1);
    const cube = new THREE.Mesh(cubeGeometry, this.material);
    cube.name = 'ray-marched-volume';
    group.add(cube);

    const outline = new THREE.LineSegments(
      new THREE.EdgesGeometry(cubeGeometry),
      new THREE.LineBasicMaterial({
        color: 0x8da3ad,
        transparent: true,
        opacity: 0.14,
        depthWrite: false,
      }),
    );
    outline.name = 'volume-bounds';
    outline.visible = !this.isClippingActive();
    this.boundsOutline = outline;
    group.add(outline);

    const direction = volume.direction;
    const xAxis = new THREE.Vector3(direction[0], direction[1], direction[2]).normalize();
    const yAxis = new THREE.Vector3(direction[3], direction[4], direction[5]).normalize();
    const zAxis = new THREE.Vector3(direction[6], direction[7], direction[8]).normalize();
    const basis = new THREE.Matrix4().makeBasis(xAxis, yAxis, zAxis);
    group.setRotationFromMatrix(basis);
    const physicalSize = new THREE.Vector3(
      width * volume.spacing[0],
      height * volume.spacing[1],
      depth * volume.spacing[2],
    );
    group.scale.copy(physicalSize);
    group.position
      .set(...volume.origin)
      .addScaledVector(xAxis, ((width - 1) * volume.spacing[0]) / 2)
      .addScaledVector(yAxis, ((height - 1) * volume.spacing[1]) / 2)
      .addScaledVector(zAxis, ((depth - 1) * volume.spacing[2]) / 2);
    this.volumeObject = group;
    this.scene.add(group);

    this.fitCamera(physicalSize, group.position);
    this.renderer.initTexture(this.volumeTexture);
    this.render();
  }

  setPreset(presetId: TransferPresetId): void {
    this.preset = presetId;
    if (!this.volume || !this.uniforms) {
      return;
    }
    const nextTexture = this.createTransferTexture();
    this.transferTexture?.dispose();
    this.transferTexture = nextTexture;
    this.uniforms.uTransfer.value = nextTexture;
    const preset = TRANSFER_PRESETS[presetId];
    this.uniforms.uAmbient.value = preset.ambient;
    this.uniforms.uDiffuse.value = preset.diffuse;
    this.uniforms.uSpecular.value = preset.specular;
    this.render();
  }

  setQuality(quality: RenderQuality): void {
    if (this.disposed) {
      return;
    }
    this.quality = quality;
    this.applyQuality();
    this.resize();
  }

  setDensity(value: number): void {
    this.density = Math.max(0.05, Math.min(2.5, value));
    if (this.uniforms) {
      this.uniforms.uDensity.value = this.density;
      this.render();
    }
  }

  setSurfaceEmphasis(value: number): void {
    this.surfaceEmphasis = Math.max(0, Math.min(1, value));
    if (this.uniforms) {
      this.uniforms.uSurfaceEmphasis.value = this.surfaceEmphasis;
      this.render();
    }
  }

  setShadows(enabled: boolean): void {
    this.shadowsEnabled = enabled;
    if (this.uniforms) {
      this.uniforms.uShadows.value = this.shadowsEnabled ? 1 : 0;
      this.render();
    }
  }

  setClip(axis: 'x' | 'y' | 'z', maximum: number): void {
    const bounds = this.getClippingBounds();
    const index = axis === 'x' ? 0 : axis === 'y' ? 1 : 2;
    const safeMaximum = Number.isFinite(maximum) ? maximum : 1;
    bounds.maximum[index] = Math.max(
      bounds.minimum[index] + 0.02,
      Math.min(1, safeMaximum),
    );
    this.setClippingBounds(bounds.minimum, bounds.maximum);
  }

  setClipMinimum(axis: 'x' | 'y' | 'z', minimum: number): void {
    const bounds = this.getClippingBounds();
    const index = axis === 'x' ? 0 : axis === 'y' ? 1 : 2;
    const safeMinimum = Number.isFinite(minimum) ? minimum : 0;
    bounds.minimum[index] = Math.max(
      0,
      Math.min(bounds.maximum[index] - 0.02, safeMinimum),
    );
    this.setClippingBounds(bounds.minimum, bounds.maximum);
  }

  /** Update all six local crop faces and submit a single render. */
  setClippingBounds(minimum: Vec3Tuple, maximum: Vec3Tuple): void {
    const normalized = normalizeClippingBounds(minimum, maximum);
    const unchanged = normalized.minimum.every(
      (value, index) =>
        Math.abs(value - this.clipMinimum.getComponent(index)) < 1e-6 &&
        Math.abs((normalized.maximum[index] ?? 1) - this.clipMaximum.getComponent(index)) < 1e-6,
    );
    if (unchanged) {
      return;
    }
    this.clipMinimum.set(...normalized.minimum);
    this.clipMaximum.set(...normalized.maximum);
    this.updateClippingState();
  }

  getClippingBounds(): ClippingBounds {
    return {
      minimum: [this.clipMinimum.x, this.clipMinimum.y, this.clipMinimum.z],
      maximum: [this.clipMaximum.x, this.clipMaximum.y, this.clipMaximum.z],
    };
  }

  resetClipping(): void {
    this.setClippingBounds([0, 0, 0], [1, 1, 1]);
  }

  resetCamera(): void {
    if (!this.volume) {
      return;
    }
    const [width, height, depth] = this.volume.dimensions;
    this.fitCamera(
      new THREE.Vector3(
        width * this.volume.spacing[0],
        height * this.volume.spacing[1],
        depth * this.volume.spacing[2],
      ),
      this.volumeObject?.position ?? new THREE.Vector3(),
    );
    this.render();
  }

  /** Temporarily lower samples while an external UI control is being dragged. */
  beginInteraction(): void {
    this.onInteractionStart();
  }

  /** Restore the selected quality after an external UI interaction. */
  endInteraction(): void {
    this.onInteractionEnd();
  }

  capturePng(): string {
    if (this.disposed) {
      throw new Error('Cannot capture an image after the renderer has been disposed.');
    }
    // Reading immediately after a synchronous render works without retaining
    // the default framebuffer between frames.
    this.render();
    return this.canvas.toDataURL('image/png');
  }

  render(): void {
    if (this.disposed) {
      return;
    }
    if (this.renderFrame !== undefined) {
      window.cancelAnimationFrame(this.renderFrame);
      this.renderFrame = undefined;
    }
    const started = performance.now();
    this.renderer.render(this.scene, this.camera);
    if (!this.interactiveRendering) {
      this.onRender?.({
        renderMilliseconds: performance.now() - started,
        samples: this.uniforms?.uSteps.value ?? 0,
        textureBytes: this.volume?.data.byteLength ?? 0,
        max3DTextureSize: this.max3DTextureSize,
      });
    }
  }

  dispose(): void {
    if (this.disposed) {
      return;
    }
    this.disposed = true;
    if (this.renderFrame !== undefined) {
      window.cancelAnimationFrame(this.renderFrame);
      this.renderFrame = undefined;
    }
    if (this.refinementTimer !== undefined) {
      window.clearTimeout(this.refinementTimer);
      this.refinementTimer = undefined;
    }
    this.resizeObserver.disconnect();
    this.controls.removeEventListener('change', this.requestRender);
    this.controls.removeEventListener('start', this.onInteractionStart);
    this.controls.removeEventListener('end', this.onInteractionEnd);
    this.controls.dispose();
    this.disposeVolumeResources();
    this.volume = undefined;
    this.onRender = undefined;
    this.renderer.dispose();
    this.canvas.remove();
  }

  private readonly requestRender = (): void => {
    if (this.disposed || this.renderFrame !== undefined) {
      return;
    }
    this.renderFrame = window.requestAnimationFrame(() => {
      this.renderFrame = undefined;
      this.render();
    });
  };

  private readonly onInteractionStart = (): void => {
    if (this.refinementTimer !== undefined) {
      window.clearTimeout(this.refinementTimer);
      this.refinementTimer = undefined;
    }
    this.interactiveRendering = true;
    this.applyQuality();
    this.requestRender();
  };

  private readonly onInteractionEnd = (): void => {
    this.requestRender();
    if (this.refinementTimer !== undefined) {
      window.clearTimeout(this.refinementTimer);
    }
    this.refinementTimer = window.setTimeout(() => {
      this.refinementTimer = undefined;
      this.interactiveRendering = false;
      this.applyQuality();
      this.requestRender();
    }, INTERACTION_REFINEMENT_DELAY_MS);
  };

  private readonly resize = (): void => {
    if (this.disposed) {
      return;
    }
    const width = Math.max(1, this.container.clientWidth);
    const height = Math.max(1, this.container.clientHeight);
    this.renderer.setSize(width, height, false);
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.render();
  };

  private applyQuality(): void {
    const settings = QUALITY_SETTINGS[this.quality];
    const targetPixelRatio = this.interactiveRendering
      ? settings.interactivePixelRatio
      : settings.pixelRatio;
    const pixelRatio = Math.min(window.devicePixelRatio || 1, targetPixelRatio);
    if (Math.abs(this.renderer.getPixelRatio() - pixelRatio) > 1e-3) {
      this.renderer.setPixelRatio(pixelRatio);
    }
    if (this.uniforms) {
      this.uniforms.uSteps.value = this.interactiveRendering
        ? settings.interactiveSteps
        : settings.steps;
      this.uniforms.uInteractive.value = this.interactiveRendering ? 1 : 0;
    }
  }

  private createTransferTexture(): THREE.DataTexture {
    if (!this.volume) {
      throw new Error('A volume must be set before creating its transfer texture.');
    }
    const data = buildTransferLut(TRANSFER_PRESETS[this.preset], this.volume.dataRange);
    const texture = new THREE.DataTexture(
      data,
      data.length / 4,
      1,
      THREE.RGBAFormat,
      THREE.UnsignedByteType,
    );
    texture.minFilter = THREE.LinearFilter;
    texture.magFilter = THREE.LinearFilter;
    texture.wrapS = THREE.ClampToEdgeWrapping;
    texture.wrapT = THREE.ClampToEdgeWrapping;
    texture.generateMipmaps = false;
    texture.colorSpace = THREE.NoColorSpace;
    texture.needsUpdate = true;
    return texture;
  }

  private fitCamera(physicalSize: THREE.Vector3, center: THREE.Vector3): void {
    const diagonal = Math.max(physicalSize.length(), 1);
    this.camera.near = Math.max(diagonal / 1500, 0.01);
    this.camera.far = diagonal * 8;
    this.camera.position
      .copy(center)
      .add(new THREE.Vector3(diagonal * 1.05, -diagonal * 1.3, diagonal * 0.85));
    this.camera.up.set(0, 0, 1);
    this.camera.lookAt(center);
    this.camera.updateProjectionMatrix();
    this.controls.target.copy(center);
    this.controls.minDistance = diagonal * 0.32;
    this.controls.maxDistance = diagonal * 3.2;
    this.controls.update();
  }

  private disposeVolumeResources(): void {
    if (this.volumeObject) {
      this.scene.remove(this.volumeObject);
      this.volumeObject.traverse((object) => {
        if (object instanceof THREE.Mesh || object instanceof THREE.LineSegments) {
          object.geometry.dispose();
          const materials = Array.isArray(object.material) ? object.material : [object.material];
          for (const material of materials) {
            material.dispose();
          }
        }
      });
    }
    this.volumeObject = undefined;
    this.boundsOutline = undefined;
    this.material = undefined;
    this.uniforms = undefined;
    this.volumeTexture?.dispose();
    this.transferTexture?.dispose();
    this.volumeTexture = undefined;
    this.transferTexture = undefined;
  }

  private isClippingActive(): boolean {
    return hasActiveClipping(this.getClippingBounds());
  }

  private updateClippingState(): void {
    if (this.uniforms) {
      this.uniforms.uClipMin.value.copy(this.clipMinimum);
      this.uniforms.uClipMax.value.copy(this.clipMaximum);
    }
    if (this.boundsOutline) {
      this.boundsOutline.visible = !this.isClippingActive();
    }
    this.render();
  }
}
