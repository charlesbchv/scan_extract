import { describe, expect, it } from 'vitest';

import { createSyntheticVolume } from '../demo/createSyntheticVolume';
import {
  buildTransferLut,
  sampleTransferPreset,
  TRANSFER_PRESETS,
} from '../volume/transferFunctions';

describe('transfer functions', () => {
  it('interpolates color and opacity control points', () => {
    const sample = sampleTransferPreset(TRANSFER_PRESETS.bone, 520);
    expect(sample[0]).toBeGreaterThan(0.7);
    expect(sample[3]).toBeCloseTo(0.2, 5);
  });

  it('builds a bounded RGBA lookup texture', () => {
    const lut = buildTransferLut(TRANSFER_PRESETS.lung, [-1000, 1500], 256);
    expect(lut).toHaveLength(256 * 4);
    expect(Math.min(...lut)).toBeGreaterThanOrEqual(0);
    expect(Math.max(...lut)).toBeLessThanOrEqual(255);
    expect(lut.some((value, index) => index % 4 === 3 && value > 0)).toBe(true);
  });
});

describe('synthetic renderer fixture', () => {
  it('creates deterministic scalar data without patient files', () => {
    const first = createSyntheticVolume();
    const second = createSyntheticVolume();
    const voxelCount = first.dimensions.reduce((total, value) => total * value, 1);

    expect(first.data).toHaveLength(voxelCount);
    expect(first.dataRange).toEqual([-1000, 1500]);
    expect(first.data.slice(0, 128)).toEqual(second.data.slice(0, 128));
    expect(new Set(first.data).size).toBeGreaterThan(20);
  });
});
