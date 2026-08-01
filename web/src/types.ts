export type Vec3Tuple = [number, number, number];

/**
 * A scalar volume laid out with X as the fastest-moving index:
 * `index = x + y * width + z * width * height`.
 *
 * `data` is normalized to [0, 255] for a compact, linearly-filterable R8
 * texture. `dataRange` maps those normalized samples back to modality units
 * (Hounsfield units for prescaled CT images).
 */
export interface VolumeData {
  data: Uint8Array;
  dimensions: Vec3Tuple;
  spacing: Vec3Tuple;
  origin: Vec3Tuple;
  /** Column-major basis: x axis, y axis, z axis. */
  direction: [number, number, number, number, number, number, number, number, number];
  dataRange: [number, number];
  modality: string;
  sourceLabel: string;
  warnings: string[];
}

export interface LoadProgress {
  completed: number;
  total: number;
  phase: 'initializing' | 'decoding' | 'assembling';
  message: string;
}
