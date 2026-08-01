export type TransferPresetId = 'lung' | 'soft-tissue' | 'bone';

export interface TransferPreset {
  id: TransferPresetId;
  label: string;
  description: string;
  colorPoints: Array<[hu: number, red: number, green: number, blue: number]>;
  opacityPoints: Array<[hu: number, opacity: number]>;
  ambient: number;
  diffuse: number;
  specular: number;
}

export const TRANSFER_PRESETS: Record<TransferPresetId, TransferPreset> = {
  lung: {
    id: 'lung',
    label: 'Lung',
    description: 'Airways and pulmonary parenchyma',
    colorPoints: [
      [-1000, 0.02, 0.03, 0.04],
      [-850, 0.28, 0.16, 0.18],
      [-700, 0.68, 0.39, 0.36],
      [-520, 0.92, 0.72, 0.65],
      [-300, 1.0, 0.92, 0.82],
    ],
    opacityPoints: [
      [-1000, 0.0],
      [-900, 0.012],
      [-760, 0.055],
      [-560, 0.14],
      [-350, 0.02],
      [-250, 0.0],
    ],
    ambient: 0.28,
    diffuse: 0.78,
    specular: 0.18,
  },
  'soft-tissue': {
    id: 'soft-tissue',
    label: 'Soft tissue',
    description: 'Mediastinum and contrast-enhanced tissue',
    colorPoints: [
      [-200, 0.03, 0.02, 0.03],
      [-80, 0.34, 0.08, 0.1],
      [40, 0.78, 0.35, 0.3],
      [150, 0.94, 0.72, 0.62],
      [420, 1.0, 0.94, 0.82],
    ],
    opacityPoints: [
      [-200, 0.0],
      [-100, 0.008],
      [20, 0.045],
      [120, 0.12],
      [320, 0.22],
      [520, 0.28],
    ],
    ambient: 0.24,
    diffuse: 0.84,
    specular: 0.22,
  },
  bone: {
    id: 'bone',
    label: 'Bone',
    description: 'Cortical and trabecular structures',
    colorPoints: [
      [-200, 0.02, 0.02, 0.025],
      [120, 0.28, 0.16, 0.1],
      [320, 0.74, 0.55, 0.34],
      [700, 0.96, 0.87, 0.68],
      [1800, 1.0, 0.99, 0.94],
    ],
    opacityPoints: [
      [-200, 0.0],
      [120, 0.0],
      [260, 0.05],
      [520, 0.2],
      [900, 0.38],
      [2000, 0.52],
    ],
    ambient: 0.22,
    diffuse: 0.88,
    specular: 0.3,
  },
};

function interpolateScalar(points: Array<[number, number]>, value: number): number {
  const first = points[0];
  const last = points[points.length - 1];
  if (!first || !last) {
    return 0;
  }
  if (value <= first[0]) {
    return first[1];
  }
  if (value >= last[0]) {
    return last[1];
  }

  for (let index = 1; index < points.length; index += 1) {
    const upper = points[index];
    const lower = points[index - 1];
    if (upper && lower && value <= upper[0]) {
      const span = Math.max(upper[0] - lower[0], Number.EPSILON);
      const amount = (value - lower[0]) / span;
      return lower[1] + (upper[1] - lower[1]) * amount;
    }
  }
  return last[1];
}

export function sampleTransferPreset(
  preset: TransferPreset,
  value: number,
): [number, number, number, number] {
  const red = interpolateScalar(
    preset.colorPoints.map((point) => [point[0], point[1]]),
    value,
  );
  const green = interpolateScalar(
    preset.colorPoints.map((point) => [point[0], point[2]]),
    value,
  );
  const blue = interpolateScalar(
    preset.colorPoints.map((point) => [point[0], point[3]]),
    value,
  );
  const alpha = interpolateScalar(preset.opacityPoints, value);
  return [red, green, blue, alpha];
}

export function buildTransferLut(
  preset: TransferPreset,
  dataRange: [number, number],
  size = 512,
): Uint8Array {
  const safeSize = Math.max(2, Math.floor(size));
  const [minimum, maximum] = dataRange;
  const range = Math.max(maximum - minimum, 1);
  const data = new Uint8Array(safeSize * 4);

  for (let index = 0; index < safeSize; index += 1) {
    const value = minimum + (index / (safeSize - 1)) * range;
    const sample = sampleTransferPreset(preset, value);
    const offset = index * 4;
    data[offset] = Math.round(Math.max(0, Math.min(1, sample[0])) * 255);
    data[offset + 1] = Math.round(Math.max(0, Math.min(1, sample[1])) * 255);
    data[offset + 2] = Math.round(Math.max(0, Math.min(1, sample[2])) * 255);
    data[offset + 3] = Math.round(Math.max(0, Math.min(1, sample[3])) * 255);
  }

  return data;
}

export function transferGradientCss(preset: TransferPreset): string {
  const minimum = preset.colorPoints[0]?.[0] ?? 0;
  const maximum = preset.colorPoints[preset.colorPoints.length - 1]?.[0] ?? 1;
  const span = Math.max(maximum - minimum, 1);
  return preset.colorPoints
    .map(([value, red, green, blue]) => {
      const position = ((value - minimum) / span) * 100;
      return `rgb(${Math.round(red * 255)} ${Math.round(green * 255)} ${Math.round(
        blue * 255,
      )}) ${position.toFixed(1)}%`;
    })
    .join(', ');
}
