# Cornerstone × Three.js volume renderer

A self-contained browser boilerplate that decodes local grayscale DICOM slices
or a multi-frame Part-10 file with Cornerstone and renders the result with a
custom Three.js WebGL2 ray marcher. Files stay in the browser; the demo has no
upload endpoint and does not print patient metadata or filenames.

## Run it

```bash
cd web
npm install
npm run dev
```

Open the local URL printed by Vite. A deterministic thorax phantom appears
immediately, so the renderer can be exercised without patient data. Choose
**Open DICOM folder** for a complete series, or use **Choose DICOM files** for
individual slices or one multi-frame file.

After changing Cornerstone dependencies, stop every existing Vite process and
restart once with `npm run dev -- --force`; this rebuilds the optimized module
graph instead of serving stale initialization bindings.

```bash
npm test
npm run build
```

## Pipeline

```text
browser File objects / existing Cornerstone imageIds
        │
        ▼
dataset-backed Part-10 inspection + multi-frame imageId expansion
        │
        ├─ preselect largest compatible series before pixel decode
        └─ support Deflated Explicit VR and padded PixelData
        │
        ▼
Cornerstone DICOM image loader (worker-backed codecs, modality prescale)
        │
        ├─ group the largest SeriesInstanceUID
        ├─ reject color/incompatible frames
        ├─ sort by dot(ImagePositionPatient, row × column)
        └─ derive [column, row, median slice] spacing
        │
        ▼
normalized R8 Data3DTexture + physical data range
        │
        ▼
Three.js BackSide proxy box
        │
        ▼
single-pass GLSL 3 ray/AABB intersection → front-to-back compositing
```

The fragment shader includes trilinear texture filtering, early alpha
termination, opacity correction for sample distance, gradient-aware transfer,
anisotropic central differences, Phong-style lighting, optional short-ray
self-shadowing, and a six-face local clipping box. The **3D cutaway** button
applies a useful crop immediately; the minimum and maximum X/Y/Z controls can
then sweep each anatomical face like the reference GIF. Interaction temporarily
reduces ray samples, framebuffer resolution, and lighting cost, then restores
the selected quality after a short idle delay; rendering is otherwise on demand
rather than a permanent animation loop.

Transfer presets mirror the desktop VTK implementation in the repository:
lung, soft tissue/mediastinum, and bone.

## Embed in an existing Cornerstone app

The useful boundary is deliberately small:

```ts
import { loadCornerstoneImageIds, VolumeRayMarcher } from './src/plugin';

const volume = await loadCornerstoneImageIds(existingImageIds, {
  onProgress: console.log,
});

const renderer = new VolumeRayMarcher(hostElement);
renderer.setVolume(volume);
renderer.setClippingBounds([0, 0, 0], [0.72, 1, 0.76]);

// On teardown:
renderer.dispose();
```

`loadCornerstoneImageIds` assumes the host has already initialized Cornerstone
and registered the loader for the supplied image-ID scheme. It intentionally
does not call the DICOM loader's global initialization routine, because doing so
inside an established viewer can reset loader-owned caches. `loadDicomFiles` is
the standalone wrapper for browser `File` objects; it performs one-time local
initialization with Cornerstone's dataset-backed local loader, then balances
every dataset-cache reference and removes only the local-file IDs that it owns.

## Why there is no 16 × 16 canvas atlas

The atlas technique was an important WebGL1 workaround. Current Three.js uses
WebGL2, where `Data3DTexture` provides native 3D addressing and trilinear
filtering. A 16 × 16 RGBA atlas of 512-pixel slices needs a 8192 × 8192 canvas
(256 MiB before the decoded stack and GPU copy); an R8 512 × 512 × 100 texture
uses about 25 MiB. The renderer checks `MAX_3D_TEXTURE_SIZE` before upload and
fails with a specific message when the volume exceeds the device limit.

The clipping bounds are expressed in local normalized texture coordinates, so
they follow the DICOM direction matrix when the patient volume is rotated. No
new texture or volume repacking occurs when switching between full-volume and
cutaway views.

## Deliberate boilerplate limits

- CT-oriented, single-component DICOM instances. Local multi-frame Part-10
  files are expanded and decoded frame by frame. Other scalar modalities load
  with a warning but need modality-specific transfer presets; RGB datasets are
  not supported. MPEG/H.264/H.265 DICOM video is rejected explicitly. Other
  cine/time-series frames are currently treated as volume depth, so production
  code should classify temporal dimensions before rendering.
- The largest compatible series in a mixed folder is selected automatically.
  A production viewer should present a series chooser before pixel decode.
- Irregular slice spacing is reported and represented with its median spacing;
  production code should resample onto a regular grid.
- Scalar data is quantized to R8 after Cornerstone modality prescale for a small,
  linearly filterable texture. Keep Float32 or implement a higher-precision
  packing path when narrow quantitative transfer windows require it.
- Fewer than 100 slices is a quality warning, not a hard error.
- This is research visualization code, not a certified medical device and not
  suitable for diagnosis.

## Dependency note

The current Cornerstone 5.6.11 line brings Node-only VTK build utilities that
remain flagged by `npm audit` through upstream `shelljs/glob` dependencies. They
are not executed by this browser path. Compatible overrides are included for
the separately reported runtime `adm-zip` and `uuid` advisories. Re-run
`npm audit --omit=dev` and review the Cornerstone release notes before promoting
this boilerplate to a production or regulated environment.

## Primary references

- [Cornerstone image loaders](https://www.cornerstonejs.org/docs/concepts/cornerstone-core/imageloader/)
- [Cornerstone DICOM image loader API](https://www.cornerstonejs.org/docs/api/dicomimageloader/globals/)
- [Three.js Data3DTexture](https://threejs.org/docs/pages/Data3DTexture.html)
- [Three.js maintained volume shader](https://github.com/mrdoob/three.js/blob/dev/examples/jsm/shaders/VolumeShader.js)
