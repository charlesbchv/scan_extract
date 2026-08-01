import './styles.css';

import { createSyntheticVolume } from './demo/createSyntheticVolume';
import { loadDicomFiles } from './dicom/loadDicomSeries';
import type { Vec3Tuple, VolumeData } from './types';
import {
  QUALITY_SETTINGS,
  VolumeRayMarcher,
  type RenderQuality,
} from './volume/VolumeRayMarcher';
import {
  FULL_CLIPPING_BOUNDS,
  hasMeaningfulClipping,
  isFullClipping,
  type ClippingBounds,
} from './volume/clipping';
import {
  TRANSFER_PRESETS,
  transferGradientCss,
  type TransferPresetId,
} from './volume/transferFunctions';

const app = document.querySelector<HTMLDivElement>('#app');
if (!app) {
  throw new Error('Application root was not found.');
}

app.innerHTML = `
  <div class="app-shell" data-ready="false" aria-busy="false">
    <header class="topbar">
      <a class="brand" href="#" aria-label="Voxel Lab home">
        <span class="brand-mark" aria-hidden="true">
          <i></i><i></i><i></i>
        </span>
        <span>
          <strong>Voxel Lab</strong>
          <small>Cornerstone × Three.js</small>
        </span>
      </a>

      <div class="topbar-center" aria-live="polite">
        <span class="system-status"><i></i><span id="system-status">Starting renderer</span></span>
      </div>

      <div class="topbar-actions">
        <button class="icon-button" id="reset-camera" type="button" aria-label="Reset camera" title="Reset camera">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4.9 7.7A8 8 0 1 1 4 12M4 5v4h4" /></svg>
        </button>
        <button class="icon-button" id="capture-image" type="button" aria-label="Save PNG capture" title="Save PNG capture">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 7.5h3l1.2-2h5.6l1.2 2h3a1.5 1.5 0 0 1 1.5 1.5v9A1.5 1.5 0 0 1 19 19.5H5A1.5 1.5 0 0 1 3.5 18V9A1.5 1.5 0 0 1 5 7.5Z"/><circle cx="12" cy="13" r="3.2"/></svg>
        </button>
        <button class="primary-button" id="open-dicom" type="button">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3.5 6.5h6l1.8 2H20a1 1 0 0 1 1 1v8.5a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 18V7a.5.5 0 0 1 .5-.5Z"/></svg>
          Open DICOM folder
        </button>
        <input id="dicom-folder-input" type="file" multiple webkitdirectory aria-label="Choose DICOM folder" />
        <input id="dicom-input" type="file" multiple aria-label="Choose DICOM files" />
      </div>
    </header>

    <main class="workspace">
      <section class="viewer-panel" aria-label="Volume viewer">
        <div class="render-host" id="render-host">
          <div class="viewport-header">
            <div>
              <span class="eyebrow">Volume source</span>
              <strong id="source-label">Preparing demo phantom</strong>
            </div>
            <span class="source-chip" id="source-chip">Local only</span>
          </div>

          <div class="view-mode-switch" role="group" aria-label="Volume view mode">
            <button type="button" data-view-mode="volume" class="active" aria-pressed="true" aria-label="Show full volume" title="Full volume" disabled>
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m12 3 8 4.5v9L12 21l-8-4.5v-9L12 3Z"/><path d="m4 7.5 8 4.5 8-4.5M12 12v9"/></svg>
              <span>Volume</span>
            </button>
            <button type="button" data-view-mode="cutaway" aria-pressed="false" aria-label="Show three-dimensional cutaway" title="3D cutaway" disabled>
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m12 3 8 4.5v9L12 21l-8-4.5v-9L12 3Z"/><path d="m4 7.5 8 4.5 8-4.5M12 12v9M8 9.8l8 4.4M8 14.2l8-4.4"/></svg>
              <span>3D cutaway</span>
            </button>
          </div>

          <div class="interaction-hint">
            <span>Drag to orbit</span><i></i><span>Scroll to zoom</span><i></i><span>Right-drag to pan</span>
          </div>

          <div class="drop-overlay" id="drop-overlay" aria-hidden="true">
            <div class="drop-icon">
              <svg viewBox="0 0 24 24"><path d="M12 4v10m0 0 4-4m-4 4-4-4M5 18.5h14"/></svg>
            </div>
            <strong>Drop the DICOM series</strong>
            <span>Processing stays inside this browser</span>
          </div>

          <div class="loading-overlay" id="loading-overlay" aria-live="polite" hidden>
            <div class="loading-card">
              <div class="voxel-loader" aria-hidden="true"><i></i><i></i><i></i><i></i></div>
              <span class="eyebrow" id="loading-phase">DICOM pipeline</span>
              <strong id="loading-message">Starting Cornerstone codecs…</strong>
              <div class="progress-track" id="progress-track" role="progressbar" aria-label="DICOM loading progress" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"><i id="progress-bar"></i></div>
              <span class="progress-copy" id="progress-copy">0%</span>
              <button class="ghost-button" id="cancel-load" type="button">Cancel</button>
            </div>
          </div>

          <div class="renderer-error" id="renderer-error" hidden role="alert">
            <strong>WebGL renderer unavailable</strong>
            <p id="renderer-error-copy"></p>
          </div>
        </div>

        <div class="metrics" aria-label="Volume metrics">
          <div><span>Dimensions</span><strong id="metric-dimensions">—</strong></div>
          <div><span>Voxel spacing</span><strong id="metric-spacing">—</strong></div>
          <div><span>Scalar range</span><strong id="metric-range">—</strong></div>
          <div><span>GPU texture</span><strong id="metric-memory">—</strong></div>
          <div><span>Ray samples</span><strong id="metric-samples">—</strong></div>
          <div><span>Render submit</span><strong id="metric-render">—</strong></div>
        </div>
      </section>

      <aside class="control-panel" aria-label="Rendering controls">
        <div class="panel-scroll">
          <section class="control-section source-section">
            <div class="section-heading">
              <div><span>01</span><h2>Source</h2></div>
              <button class="text-button" id="load-demo" type="button">Use demo</button>
            </div>
            <button class="source-dropzone" id="source-dropzone" type="button">
              <span class="source-dropzone-icon">
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3.5 6.5h6l1.8 2H20a1 1 0 0 1 1 1v8.5a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 18V7a.5.5 0 0 1 .5-.5Z"/></svg>
              </span>
              <span><strong>Choose DICOM files</strong><small>Grayscale slices or one multi-frame file</small></span>
              <svg class="chevron" viewBox="0 0 24 24" aria-hidden="true"><path d="m9 6 6 6-6 6"/></svg>
            </button>
            <p class="privacy-note"><i></i> Files are decoded locally and never uploaded.</p>
            <div class="warning-box" id="warning-box" role="status" aria-live="polite" hidden>
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 8v5m0 3.2v.1M10.7 4.8 3.5 17.3a1.5 1.5 0 0 0 1.3 2.2h14.4a1.5 1.5 0 0 0 1.3-2.2L13.3 4.8a1.5 1.5 0 0 0-2.6 0Z"/></svg>
              <p id="warning-copy"></p>
            </div>
          </section>

          <section class="control-section">
            <div class="section-heading"><div><span>02</span><h2>Transfer function</h2></div></div>
            <div class="preset-tabs" role="group" aria-label="Transfer function preset">
              <button type="button" data-preset="lung" class="active" aria-pressed="true">Lung</button>
              <button type="button" data-preset="soft-tissue" aria-pressed="false">Soft</button>
              <button type="button" data-preset="bone" aria-pressed="false">Bone</button>
            </div>
            <div class="transfer-preview">
              <div class="transfer-gradient" id="transfer-gradient"></div>
              <svg viewBox="0 0 300 66" preserveAspectRatio="none" aria-label="Opacity curve">
                <path class="curve-fill" id="curve-fill"></path>
                <path class="curve-line" id="curve-line"></path>
              </svg>
              <div class="transfer-scale"><span id="transfer-min">−1000</span><span id="transfer-unit">HU</span><span id="transfer-max">2000</span></div>
            </div>
            <p class="preset-description" id="preset-description"></p>

            <label class="range-control" for="density">
              <span><b>Opacity</b><output id="density-output">1.00×</output></span>
              <input id="density" type="range" min="0.2" max="2" step="0.05" value="1" />
            </label>
            <label class="range-control" for="surface-emphasis">
              <span><b>Surface emphasis</b><output id="surface-output">24%</output></span>
              <input id="surface-emphasis" type="range" min="0" max="1" step="0.01" value="0.24" />
            </label>
            <label class="toggle-row" for="shadows">
              <span><b>Volumetric shadows</b><small>Seven-tap light transmittance</small></span>
              <input id="shadows" type="checkbox" /><i aria-hidden="true"></i>
            </label>
          </section>

          <section class="control-section">
            <div class="section-heading"><div><span>03</span><h2>Quality</h2></div></div>
            <div class="quality-grid" role="group" aria-label="Ray marching quality">
              <button type="button" data-quality="performance" aria-pressed="false"><span>220</span>Fast</button>
              <button type="button" data-quality="balanced" class="active" aria-pressed="true"><span>420</span>Balanced</button>
              <button type="button" data-quality="cinematic" aria-pressed="false"><span>720</span>High</button>
            </div>
            <p class="helper-copy">Resolution and shading simplify while moving, then refine on release.</p>
          </section>

          <section class="control-section clipping-section">
            <div class="section-heading">
              <div><span>04</span><h2>Clipping planes</h2></div>
              <button class="text-button" id="reset-clipping" type="button" aria-label="Reset all clipping planes" disabled>Reset</button>
            </div>
            <div class="clip-axis-control" role="group" aria-labelledby="clip-x-label">
              <div class="clip-axis-heading"><b id="clip-x-label"><i class="axis-dot x"></i>Local axis · X</b><output id="clip-x-range-output">0–100%</output></div>
              <label class="range-control compact" for="clip-x-min">
                <span><small>Minimum</small><output id="clip-x-min-output" for="clip-x-min">0%</output></span>
                <input id="clip-x-min" type="range" min="0" max="0.98" step="0.01" value="0" aria-label="Local X minimum clipping plane" aria-valuetext="0%" disabled />
              </label>
              <label class="range-control compact" for="clip-x-max">
                <span><small>Maximum</small><output id="clip-x-max-output" for="clip-x-max">100%</output></span>
                <input id="clip-x-max" type="range" min="0.02" max="1" step="0.01" value="1" aria-label="Local X maximum clipping plane" aria-valuetext="100%" disabled />
              </label>
            </div>
            <div class="clip-axis-control" role="group" aria-labelledby="clip-y-label">
              <div class="clip-axis-heading"><b id="clip-y-label"><i class="axis-dot y"></i>Local axis · Y</b><output id="clip-y-range-output">0–100%</output></div>
              <label class="range-control compact" for="clip-y-min">
                <span><small>Minimum</small><output id="clip-y-min-output" for="clip-y-min">0%</output></span>
                <input id="clip-y-min" type="range" min="0" max="0.98" step="0.01" value="0" aria-label="Local Y minimum clipping plane" aria-valuetext="0%" disabled />
              </label>
              <label class="range-control compact" for="clip-y-max">
                <span><small>Maximum</small><output id="clip-y-max-output" for="clip-y-max">100%</output></span>
                <input id="clip-y-max" type="range" min="0.02" max="1" step="0.01" value="1" aria-label="Local Y maximum clipping plane" aria-valuetext="100%" disabled />
              </label>
            </div>
            <div class="clip-axis-control" role="group" aria-labelledby="clip-z-label">
              <div class="clip-axis-heading"><b id="clip-z-label"><i class="axis-dot z"></i>Local axis · Z</b><output id="clip-z-range-output">0–100%</output></div>
              <label class="range-control compact" for="clip-z-min">
                <span><small>Minimum</small><output id="clip-z-min-output" for="clip-z-min">0%</output></span>
                <input id="clip-z-min" type="range" min="0" max="0.98" step="0.01" value="0" aria-label="Local Z minimum clipping plane" aria-valuetext="0%" disabled />
              </label>
              <label class="range-control compact" for="clip-z-max">
                <span><small>Maximum</small><output id="clip-z-max-output" for="clip-z-max">100%</output></span>
                <input id="clip-z-max" type="range" min="0.02" max="1" step="0.01" value="1" aria-label="Local Z maximum clipping plane" aria-valuetext="100%" disabled />
              </label>
            </div>
            <p class="helper-copy clipping-helper">Move either bound to reveal an anatomical face. The Soft transfer most closely matches the reference look.</p>
          </section>
        </div>

        <footer class="panel-footer">
          <span>Research visualization boilerplate</span>
          <p>Not a certified medical device. Do not use for diagnosis.</p>
        </footer>
      </aside>
    </main>

    <div class="toast" id="toast" role="status" aria-live="polite" hidden></div>
  </div>
`;

function element<T extends Element>(selector: string): T {
  const match = document.querySelector<T>(selector);
  if (!match) {
    throw new Error(`Expected UI element ${selector}`);
  }
  return match;
}

const shell = element<HTMLDivElement>('.app-shell');
const renderHost = element<HTMLDivElement>('#render-host');
const fileInput = element<HTMLInputElement>('#dicom-input');
const folderInput = element<HTMLInputElement>('#dicom-folder-input');
const loadingOverlay = element<HTMLDivElement>('#loading-overlay');
const progressTrack = element<HTMLDivElement>('#progress-track');
const progressBar = element<HTMLElement>('#progress-bar');
const progressCopy = element<HTMLElement>('#progress-copy');
const loadingPhase = element<HTMLElement>('#loading-phase');
const loadingMessage = element<HTMLElement>('#loading-message');
const dropOverlay = element<HTMLDivElement>('#drop-overlay');
const warningBox = element<HTMLDivElement>('#warning-box');
const warningCopy = element<HTMLParagraphElement>('#warning-copy');
const systemStatus = element<HTMLElement>('#system-status');
const sourceLabel = element<HTMLElement>('#source-label');
const sourceChip = element<HTMLElement>('#source-chip');
const toast = element<HTMLDivElement>('#toast');
const viewModeButtons = [
  ...document.querySelectorAll<HTMLButtonElement>('[data-view-mode]'),
];

type ViewMode = 'volume' | 'cutaway';
type ClipAxis = 'x' | 'y' | 'z';
type ClipBound = 'min' | 'max';

const CLIP_AXES: ClipAxis[] = ['x', 'y', 'z'];
const DEFAULT_CUTAWAY_BOUNDS: ClippingBounds = {
  minimum: [0, 0, 0],
  maximum: [0.72, 1, 0.76],
};

let renderer: VolumeRayMarcher | undefined;
let activeLoad: AbortController | undefined;
let toastTimer: number | undefined;
let toastHideTimer: number | undefined;
let currentPreset: TransferPresetId = 'lung';
let currentViewMode: ViewMode = 'volume';
let cutawayBounds = cloneClippingBounds(DEFAULT_CUTAWAY_BOUNDS);

function cloneClippingBounds(bounds: ClippingBounds): ClippingBounds {
  return {
    minimum: [...bounds.minimum] as Vec3Tuple,
    maximum: [...bounds.maximum] as Vec3Tuple,
  };
}

function setText(selector: string, value: string): void {
  element<HTMLElement>(selector).textContent = value;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(0)} KiB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
}

function showToast(message: string, tone: 'neutral' | 'success' | 'error' = 'neutral'): void {
  window.clearTimeout(toastTimer);
  window.clearTimeout(toastHideTimer);
  toast.textContent = message;
  toast.dataset.tone = tone;
  toast.hidden = false;
  requestAnimationFrame(() => toast.classList.add('visible'));
  toastTimer = window.setTimeout(() => {
    toast.classList.remove('visible');
    toastHideTimer = window.setTimeout(() => {
      toast.hidden = true;
    }, 160);
  }, tone === 'error' ? 9000 : 3600);
}

function setBusy(busy: boolean): void {
  loadingOverlay.hidden = !busy;
  shell.classList.toggle('is-busy', busy);
  shell.setAttribute('aria-busy', String(busy));
  fileInput.disabled = busy;
  folderInput.disabled = busy;
  element<HTMLButtonElement>('#open-dicom').disabled = busy;
  element<HTMLButtonElement>('#source-dropzone').disabled = busy;
  updateViewModeAvailability();
}

function updateViewModeAvailability(): void {
  const disabled =
    shell.classList.contains('is-busy') || !renderer || shell.dataset.ready !== 'true';
  viewModeButtons.forEach((button) => {
    button.disabled = disabled;
  });
  document
    .querySelectorAll<HTMLInputElement | HTMLButtonElement>(
      '.clipping-section input, #reset-clipping',
    )
    .forEach((control) => {
      control.disabled = disabled;
    });
}

function updateTransferPreview(presetId: TransferPresetId): void {
  const preset = TRANSFER_PRESETS[presetId];
  element<HTMLElement>('#transfer-gradient').style.background =
    `linear-gradient(90deg, ${transferGradientCss(preset)})`;
  setText('#preset-description', preset.description);
  const first = preset.opacityPoints[0]?.[0] ?? 0;
  const last = preset.opacityPoints[preset.opacityPoints.length - 1]?.[0] ?? 1;
  const range = Math.max(last - first, 1);
  const points = preset.opacityPoints.map(([value, opacity]) => [
    ((value - first) / range) * 300,
    62 - opacity * 108,
  ]);
  const line = points
    .map(([x, y], index) => `${index === 0 ? 'M' : 'L'} ${x?.toFixed(1)} ${Math.max(4, y ?? 62).toFixed(1)}`)
    .join(' ');
  element<SVGPathElement>('#curve-line').setAttribute('d', line);
  element<SVGPathElement>('#curve-fill').setAttribute('d', `${line} L 300 66 L 0 66 Z`);
  setText('#transfer-min', Math.round(first).toLocaleString());
  setText('#transfer-max', Math.round(last).toLocaleString());
}

function applyVolume(volume: VolumeData): void {
  if (!renderer) {
    return;
  }
  renderer.setVolume(volume);
  sourceLabel.textContent = volume.sourceLabel;
  sourceChip.textContent = volume.modality;
  const [width, height, depth] = volume.dimensions;
  setText('#metric-dimensions', `${width} × ${height} × ${depth}`);
  setText('#metric-spacing', volume.spacing.map((value) => value.toFixed(2)).join(' × ') + ' mm');
  setText(
    '#metric-range',
    `${Math.round(volume.dataRange[0]).toLocaleString()} — ${Math.round(volume.dataRange[1]).toLocaleString()} ${volume.modality.toUpperCase().includes('CT') ? 'HU' : 'units'}`,
  );
  setText('#transfer-unit', volume.modality.toUpperCase().includes('CT') ? 'HU' : 'units');
  setText('#metric-memory', formatBytes(volume.data.byteLength));
  warningBox.hidden = volume.warnings.length === 0;
  warningCopy.textContent = volume.warnings.join(' ');
  systemStatus.textContent = 'WebGL 2 · renderer ready';
  shell.dataset.ready = 'true';
  updateViewModeState(currentViewMode);
  updateViewModeAvailability();
}

function loadDemoVolume(): void {
  if (!renderer) {
    return;
  }
  activeLoad?.abort();
  activeLoad = undefined;
  setBusy(false);
  sourceLabel.textContent = 'Generating demo phantom';
  systemStatus.textContent = 'Building synthetic volume';
  window.setTimeout(() => {
    try {
      applyVolume(createSyntheticVolume());
      showToast('Procedural CT phantom loaded.', 'success');
    } catch (error) {
      showToast(error instanceof Error ? error.message : 'Demo volume failed to load.', 'error');
    }
  }, 0);
}

async function loadFiles(files: File[]): Promise<void> {
  if (!renderer || files.length === 0) {
    if (files.length === 0) {
      showToast('No files were found in that selection.', 'error');
    }
    return;
  }

  activeLoad?.abort();
  const controller = new AbortController();
  activeLoad = controller;
  setBusy(true);
  warningBox.hidden = true;
  sourceLabel.textContent = 'Reading local DICOM series';
  systemStatus.textContent = 'Cornerstone is decoding';
  progressBar.style.transform = 'scaleX(0)';
  progressCopy.textContent = '0%';
  progressTrack.setAttribute('aria-valuenow', '0');

  try {
    if (activeLoad !== controller || controller.signal.aborted) {
      return;
    }
    const volume = await loadDicomFiles(files, {
      signal: controller.signal,
      onProgress: (progress) => {
        if (activeLoad !== controller || controller.signal.aborted) {
          return;
        }
        const phaseRatio = progress.total > 0 ? progress.completed / progress.total : 0;
        const ratio =
          progress.phase === 'decoding'
            ? 0.05 + phaseRatio * 0.75
            : progress.phase === 'assembling'
              ? 0.8 + phaseRatio * 0.2
              : 0.02;
        const percent = Math.round(Math.max(0, Math.min(1, ratio)) * 100);
        progressBar.style.transform = `scaleX(${Math.max(0.02, ratio)})`;
        progressCopy.textContent = `${percent}%`;
        progressTrack.setAttribute('aria-valuenow', String(percent));
        loadingPhase.textContent =
          progress.phase === 'decoding'
            ? 'Worker decode'
            : progress.phase === 'assembling'
              ? 'Volume assembly'
              : 'DICOM pipeline';
        loadingMessage.textContent = progress.message;
      },
    });
    if (activeLoad !== controller) {
      return;
    }
    applyVolume(volume);
    showToast(`Loaded ${volume.dimensions[2]} spatially sorted slices.`, 'success');
  } catch (error) {
    console.error('[DICOM load failed]', error);
    if (activeLoad !== controller) {
      return;
    }
    if (error instanceof DOMException && error.name === 'AbortError') {
      showToast('DICOM loading cancelled.');
    } else {
      const message = error instanceof Error ? error.message : 'The DICOM stack could not be loaded.';
      showToast(message, 'error');
      systemStatus.textContent = 'Load failed · demo remains available';
      sourceLabel.textContent = 'DICOM load failed';
    }
  } finally {
    if (activeLoad === controller) {
      activeLoad = undefined;
      setBusy(false);
    }
    fileInput.value = '';
    folderInput.value = '';
  }
}

interface LegacyFileEntry {
  isFile: boolean;
  isDirectory: boolean;
  file?: (success: (file: File) => void, failure?: () => void) => void;
  createReader?: () => {
    readEntries: (success: (entries: LegacyFileEntry[]) => void, failure?: () => void) => void;
  };
}

async function filesFromEntry(entry: LegacyFileEntry): Promise<File[]> {
  if (entry.isFile && entry.file) {
    return new Promise((resolve) => entry.file?.((file) => resolve([file]), () => resolve([])));
  }
  if (!entry.isDirectory || !entry.createReader) {
    return [];
  }
  const reader = entry.createReader();
  const entries: LegacyFileEntry[] = [];
  while (true) {
    const batch = await new Promise<LegacyFileEntry[]>((resolve) =>
      reader.readEntries(resolve, () => resolve([])),
    );
    if (batch.length === 0) {
      break;
    }
    entries.push(...batch);
  }
  const nested = await Promise.all(entries.map(filesFromEntry));
  return nested.flat();
}

async function filesFromDrop(dataTransfer: DataTransfer): Promise<File[]> {
  const entries = [...dataTransfer.items]
    .map((item) => {
      const method = (item as DataTransferItem & {
        webkitGetAsEntry?: () => LegacyFileEntry | null;
      }).webkitGetAsEntry;
      return method?.call(item) ?? null;
    })
    .filter((entry): entry is LegacyFileEntry => Boolean(entry));
  if (entries.length === 0) {
    return [...dataTransfer.files];
  }
  return (await Promise.all(entries.map(filesFromEntry))).flat();
}

function selectFolder(): void {
  folderInput.click();
}

function selectFiles(): void {
  fileInput.click();
}

function clipAxisIndex(axis: ClipAxis): 0 | 1 | 2 {
  return axis === 'x' ? 0 : axis === 'y' ? 1 : 2;
}

function clippingInput(axis: ClipAxis, bound: ClipBound): HTMLInputElement {
  return element<HTMLInputElement>(`#clip-${axis}-${bound}`);
}

function readClippingControls(): ClippingBounds {
  const minimum: Vec3Tuple = [0, 0, 0];
  const maximum: Vec3Tuple = [1, 1, 1];
  CLIP_AXES.forEach((axis) => {
    const index = clipAxisIndex(axis);
    minimum[index] = Number(clippingInput(axis, 'min').value);
    maximum[index] = Number(clippingInput(axis, 'max').value);
  });
  return { minimum, maximum };
}

function syncClippingControls(bounds: ClippingBounds): void {
  CLIP_AXES.forEach((axis) => {
    const index = clipAxisIndex(axis);
    const minimum = bounds.minimum[index];
    const maximum = bounds.maximum[index];
    const minimumInput = clippingInput(axis, 'min');
    const maximumInput = clippingInput(axis, 'max');
    const minimumPercent = `${Math.round(minimum * 100)}%`;
    const maximumPercent = `${Math.round(maximum * 100)}%`;
    minimumInput.max = Math.max(0, maximum - 0.02).toFixed(2);
    maximumInput.min = Math.min(1, minimum + 0.02).toFixed(2);
    minimumInput.value = minimum.toFixed(2);
    maximumInput.value = maximum.toFixed(2);
    minimumInput.setAttribute('aria-valuetext', minimumPercent);
    maximumInput.setAttribute('aria-valuetext', maximumPercent);
    setText(`#clip-${axis}-min-output`, minimumPercent);
    setText(`#clip-${axis}-max-output`, maximumPercent);
    setText(
      `#clip-${axis}-range-output`,
      `${Math.round(minimum * 100)}–${Math.round(maximum * 100)}%`,
    );
  });
}

function updateViewModeState(mode: ViewMode): void {
  currentViewMode = mode;
  shell.dataset.viewMode = mode;
  viewModeButtons.forEach((button) => {
    const selected = button.dataset.viewMode === mode;
    button.classList.toggle('active', selected);
    button.setAttribute('aria-pressed', String(selected));
  });
}

function setViewMode(mode: ViewMode): void {
  const requested =
    mode === 'volume' ? FULL_CLIPPING_BOUNDS : cutawayBounds;
  renderer?.setClippingBounds(requested.minimum, requested.maximum);
  const applied = renderer?.getClippingBounds() ?? cloneClippingBounds(requested);
  if (mode === 'cutaway') {
    cutawayBounds = cloneClippingBounds(applied);
  }
  syncClippingControls(applied);
  updateViewModeState(mode);
}

function applyClippingControl(axis: ClipAxis, bound: ClipBound): void {
  const minimumInput = clippingInput(axis, 'min');
  const maximumInput = clippingInput(axis, 'max');
  let minimum = Math.max(0, Math.min(0.98, Number(minimumInput.value)));
  let maximum = Math.max(0.02, Math.min(1, Number(maximumInput.value)));
  if (maximum - minimum < 0.02) {
    if (bound === 'min') {
      minimum = Math.max(0, maximum - 0.02);
    } else {
      maximum = Math.min(1, minimum + 0.02);
    }
  }
  minimumInput.value = minimum.toFixed(2);
  maximumInput.value = maximum.toFixed(2);

  const requested = readClippingControls();
  renderer?.setClippingBounds(requested.minimum, requested.maximum);
  const applied = renderer?.getClippingBounds() ?? requested;
  syncClippingControls(applied);
  if (isFullClipping(applied)) {
    updateViewModeState('volume');
  } else {
    if (hasMeaningfulClipping(applied)) {
      cutawayBounds = cloneClippingBounds(applied);
    }
    updateViewModeState('cutaway');
  }
}

element<HTMLButtonElement>('#open-dicom').addEventListener('click', selectFolder);
element<HTMLButtonElement>('#source-dropzone').addEventListener('click', selectFiles);
fileInput.addEventListener('change', () => void loadFiles([...(fileInput.files ?? [])]));
folderInput.addEventListener('change', () => void loadFiles([...(folderInput.files ?? [])]));
element<HTMLButtonElement>('#load-demo').addEventListener('click', loadDemoVolume);
element<HTMLButtonElement>('#cancel-load').addEventListener('click', () => activeLoad?.abort());
element<HTMLButtonElement>('#reset-camera').addEventListener('click', () => renderer?.resetCamera());
element<HTMLButtonElement>('#capture-image').addEventListener('click', () => {
  if (!renderer) {
    return;
  }
  try {
    const link = document.createElement('a');
    link.download = 'dicom-volume-render.png';
    link.href = renderer.capturePng();
    link.click();
    showToast('PNG capture saved.', 'success');
  } catch (error) {
    showToast(error instanceof Error ? error.message : 'PNG capture failed.', 'error');
  }
});

viewModeButtons.forEach((button) => {
  button.addEventListener('click', () => {
    const mode = button.dataset.viewMode as ViewMode;
    if (mode !== currentViewMode) {
      setViewMode(mode);
    }
  });
});

document.querySelectorAll<HTMLButtonElement>('[data-preset]').forEach((button) => {
  button.addEventListener('click', () => {
    currentPreset = button.dataset.preset as TransferPresetId;
    document.querySelectorAll<HTMLButtonElement>('[data-preset]').forEach((item) => {
      const selected = item === button;
      item.classList.toggle('active', selected);
      item.setAttribute('aria-pressed', String(selected));
    });
    updateTransferPreview(currentPreset);
    renderer?.setPreset(currentPreset);
  });
});

document.querySelectorAll<HTMLButtonElement>('[data-quality]').forEach((button) => {
  button.addEventListener('click', () => {
    const quality = button.dataset.quality as RenderQuality;
    document.querySelectorAll<HTMLButtonElement>('[data-quality]').forEach((item) => {
      const selected = item === button;
      item.classList.toggle('active', selected);
      item.setAttribute('aria-pressed', String(selected));
    });
    renderer?.setQuality(quality);
    setText('#metric-samples', QUALITY_SETTINGS[quality].steps.toString());
  });
});

const density = element<HTMLInputElement>('#density');
function onNextAnimationFrame(callback: () => void): () => void {
  let queued = false;
  return () => {
    if (queued) {
      return;
    }
    queued = true;
    requestAnimationFrame(() => {
      queued = false;
      callback();
    });
  };
}

function bindRangeInteraction(input: HTMLInputElement): void {
  const begin = (): void => renderer?.beginInteraction();
  const end = (): void => renderer?.endInteraction();
  input.addEventListener('pointerdown', begin);
  input.addEventListener('pointerup', end);
  input.addEventListener('pointercancel', end);
  input.addEventListener('keydown', begin);
  input.addEventListener('keyup', end);
  input.addEventListener('blur', end);
}

density.addEventListener('input', onNextAnimationFrame(() => {
  const value = Number(density.value);
  setText('#density-output', `${value.toFixed(2)}×`);
  renderer?.setDensity(value);
}));
bindRangeInteraction(density);

const surface = element<HTMLInputElement>('#surface-emphasis');
surface.addEventListener('input', onNextAnimationFrame(() => {
  const value = Number(surface.value);
  setText('#surface-output', `${Math.round(value * 100)}%`);
  renderer?.setSurfaceEmphasis(value);
}));
bindRangeInteraction(surface);

element<HTMLInputElement>('#shadows').addEventListener('change', (event) => {
  renderer?.setShadows((event.currentTarget as HTMLInputElement).checked);
});

CLIP_AXES.forEach((axis) => {
  (['min', 'max'] as const).forEach((bound) => {
    const input = clippingInput(axis, bound);
    input.addEventListener(
      'input',
      onNextAnimationFrame(() => applyClippingControl(axis, bound)),
    );
    bindRangeInteraction(input);
  });
});

element<HTMLButtonElement>('#reset-clipping').addEventListener('click', () => {
  cutawayBounds = cloneClippingBounds(DEFAULT_CUTAWAY_BOUNDS);
  setViewMode('volume');
});

let dragDepth = 0;
window.addEventListener('dragenter', (event) => {
  event.preventDefault();
  dragDepth += 1;
  dropOverlay.classList.add('visible');
});
window.addEventListener('dragover', (event) => event.preventDefault());
window.addEventListener('dragleave', (event) => {
  event.preventDefault();
  dragDepth = Math.max(0, dragDepth - 1);
  if (dragDepth === 0) {
    dropOverlay.classList.remove('visible');
  }
});
window.addEventListener('drop', (event) => {
  event.preventDefault();
  dragDepth = 0;
  dropOverlay.classList.remove('visible');
  if (event.dataTransfer) {
    void filesFromDrop(event.dataTransfer).then(loadFiles);
  }
});

updateTransferPreview(currentPreset);
syncClippingControls(FULL_CLIPPING_BOUNDS);
updateViewModeState('volume');
setText('#metric-samples', QUALITY_SETTINGS.balanced.steps.toString());

try {
  renderer = new VolumeRayMarcher(renderHost);
  renderer.onRender = (metrics) => {
    setText('#metric-render', `${metrics.renderMilliseconds.toFixed(1)} ms`);
    setText('#metric-samples', metrics.samples.toString());
  };
  loadDemoVolume();
} catch (error) {
  const message = error instanceof Error ? error.message : 'The GPU renderer could not start.';
  element<HTMLDivElement>('#renderer-error').hidden = false;
  setText('#renderer-error-copy', message);
  systemStatus.textContent = 'Renderer unavailable';
  shell.classList.add('renderer-unavailable');
  document.querySelectorAll<HTMLButtonElement | HTMLInputElement>('button, input').forEach((control) => {
    control.disabled = true;
  });
}

window.addEventListener('beforeunload', () => {
  activeLoad?.abort();
  renderer?.dispose();
});
