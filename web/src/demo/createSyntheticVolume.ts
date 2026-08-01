import type { VolumeData } from '../types';

function hashNoise(x: number, y: number, z: number): number {
  const value = Math.sin(x * 12.9898 + y * 78.233 + z * 37.719) * 43758.5453;
  return (value - Math.floor(value)) * 2 - 1;
}

function ellipsoid(
  x: number,
  y: number,
  z: number,
  centerX: number,
  centerY: number,
  centerZ: number,
  radiusX: number,
  radiusY: number,
  radiusZ: number,
): number {
  return (
    ((x - centerX) / radiusX) ** 2 +
    ((y - centerY) / radiusY) ** 2 +
    ((z - centerZ) / radiusZ) ** 2
  );
}

/** A deterministic, non-patient thorax phantom for zero-setup renderer QA. */
export function createSyntheticVolume(): VolumeData {
  const dimensions: [number, number, number] = [144, 144, 112];
  const [width, height, depth] = dimensions;
  const minimum = -1000;
  const maximum = 1500;
  const scale = 255 / (maximum - minimum);
  const data = new Uint8Array(width * height * depth);
  let index = 0;

  for (let zIndex = 0; zIndex < depth; zIndex += 1) {
    const z = (zIndex / (depth - 1)) * 2 - 1;
    for (let yIndex = 0; yIndex < height; yIndex += 1) {
      const y = (yIndex / (height - 1)) * 2 - 1;
      for (let xIndex = 0; xIndex < width; xIndex += 1) {
        const x = (xIndex / (width - 1)) * 2 - 1;
        const noise = hashNoise(xIndex, yIndex, zIndex);
        let hu = -1000;

        const body = ellipsoid(x, y, z, 0, 0.02, 0, 0.9, 0.7, 0.96);
        if (body < 1) {
          hu = 38 + noise * 12;

          const leftLung = ellipsoid(x, y, z, -0.28, -0.04, -0.02, 0.25, 0.43, 0.76);
          const rightLung = ellipsoid(x, y, z, 0.28, -0.04, -0.02, 0.27, 0.44, 0.77);
          if (leftLung < 1 || rightLung < 1) {
            hu = -770 + noise * 48 + Math.sin(z * 19 + x * 8) * 20;

            const vesselA = Math.hypot(x - Math.sign(x || 1) * (0.2 + z * 0.045), y + 0.02);
            const vesselB = Math.hypot(x - Math.sign(x || 1) * (0.35 - z * 0.035), y + 0.12);
            if ((vesselA < 0.025 || vesselB < 0.018) && Math.abs(z) < 0.68) {
              hu = 120 + noise * 18;
            }
          }

          const spine = ellipsoid(x, y, z, 0, 0.45, 0, 0.11, 0.1, 0.78);
          if (spine < 1) {
            hu = spine < 0.48 ? 420 + noise * 55 : 980 + noise * 90;
          }

          const sternum = ellipsoid(x, y, z, 0, -0.58, 0, 0.07, 0.055, 0.65);
          if (sternum < 1) {
            hu = 820 + noise * 70;
          }

          const shellDistance = Math.abs(body - 0.84);
          const ribBand = Math.abs(Math.sin((z + 1) * Math.PI * 7.5));
          if (shellDistance < 0.018 && ribBand < 0.32 && Math.abs(y) < 0.58) {
            hu = 1050 + noise * 80;
          }

          const nodule = ellipsoid(x, y, z, -0.35, -0.1, 0.08, 0.045, 0.045, 0.055);
          if (nodule < 1) {
            hu = 85 + noise * 14;
          }
        }

        data[index] = Math.max(0, Math.min(255, Math.round((hu - minimum) * scale)));
        index += 1;
      }
    }
  }

  return {
    data,
    dimensions,
    spacing: [1.35, 1.35, 1.8],
    origin: [0, 0, 0],
    direction: [1, 0, 0, 0, 1, 0, 0, 0, 1],
    dataRange: [minimum, maximum],
    modality: 'Synthetic CT',
    sourceLabel: 'Procedural thorax phantom',
    warnings: [],
  };
}
