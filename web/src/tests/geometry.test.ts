import { describe, expect, it } from 'vitest';

import {
  prepareGeometry,
  quantizeScalarSlices,
  quantizeScalarSlicesAsync,
  type SliceGeometry,
} from '../dicom/geometry';
import { ensureModalityScaledPixels } from '../dicom/pixels';

interface TestSlice extends SliceGeometry {
  pixels: Int16Array;
}

function slice(z: number, sourceIndex: number): TestSlice {
  return {
    imageId: `dicomfile:${sourceIndex}`,
    sourceIndex,
    rows: 2,
    columns: 2,
    rowCosines: [1, 0, 0],
    columnCosines: [0, 1, 0],
    imagePositionPatient: [0, 0, z],
    rowPixelSpacing: 0.8,
    columnPixelSpacing: 0.7,
    instanceNumber: sourceIndex + 1,
    pixels: new Int16Array([z, z + 1, z + 2, z + 3]),
  };
}

describe('DICOM volume geometry', () => {
  it('sorts slices by Image Position Patient projected on the slice normal', () => {
    const prepared = prepareGeometry([slice(2, 2), slice(0, 0), slice(1, 1)]);

    expect(prepared.slices.map((item) => item.imagePositionPatient?.[2])).toEqual([0, 1, 2]);
    expect(prepared.sortMethod).toBe('spatial');
    expect(prepared.dimensions).toEqual([2, 2, 3]);
    expect(prepared.spacing).toEqual([0.7, 0.8, 1]);
    expect(prepared.direction).toEqual([1, 0, 0, 0, 1, 0, 0, 0, 1]);
  });

  it('falls back to instance order and reports missing spatial metadata', () => {
    const first = { ...slice(0, 4), imagePositionPatient: undefined, instanceNumber: 4 };
    const second = { ...slice(0, 1), imagePositionPatient: undefined, instanceNumber: 1 };
    const prepared = prepareGeometry([first, second]);

    expect(prepared.slices.map((item) => item.instanceNumber)).toEqual([1, 4]);
    expect(prepared.sortMethod).toBe('instance');
    expect(prepared.warnings.join(' ')).toContain('Instance Number');
  });

  it('does not spatially sort non-axial positions without an orientation', () => {
    const first = {
      ...slice(0, 1),
      imagePositionPatient: [20, 0, 0] as [number, number, number],
      rowCosines: undefined,
      columnCosines: undefined,
      instanceNumber: 2,
    };
    const second = {
      ...slice(0, 0),
      imagePositionPatient: [10, 0, 0] as [number, number, number],
      rowCosines: undefined,
      columnCosines: undefined,
      instanceNumber: 1,
    };
    const prepared = prepareGeometry([first, second]);

    expect(prepared.sortMethod).toBe('instance');
    expect(prepared.slices.map((item) => item.instanceNumber)).toEqual([1, 2]);
  });

  it('does not let partial Slice Location metadata override complete instance order', () => {
    const first = {
      ...slice(0, 1),
      imagePositionPatient: undefined,
      sliceLocation: 10,
      instanceNumber: 2,
    };
    const second = {
      ...slice(0, 0),
      imagePositionPatient: undefined,
      sliceLocation: undefined,
      instanceNumber: 1,
    };
    const prepared = prepareGeometry([first, second]);

    expect(prepared.sortMethod).toBe('instance');
    expect(prepared.slices.map((item) => item.instanceNumber)).toEqual([1, 2]);
  });

  it('uses input order when every frame repeats the same instance number', () => {
    const first = {
      ...slice(0, 2),
      imagePositionPatient: undefined,
      sliceLocation: undefined,
      instanceNumber: 1,
    };
    const second = {
      ...slice(0, 0),
      imagePositionPatient: undefined,
      sliceLocation: undefined,
      instanceNumber: 1,
    };
    const prepared = prepareGeometry([first, second]);

    expect(prepared.sortMethod).toBe('input');
    expect(prepared.slices.map((item) => item.sourceIndex)).toEqual([0, 2]);
  });

  it('warns when physical slice spacing is irregular', () => {
    const prepared = prepareGeometry([slice(0, 0), slice(1, 1), slice(3, 2)]);
    expect(prepared.warnings.join(' ')).toContain('irregular');
    expect(prepared.spacing[2]).toBe(1.5);
  });

  it('does not treat reversed in-plane axes as a compatible orientation', () => {
    const reversed = {
      ...slice(1, 1),
      rowCosines: [-1, 0, 0] as [number, number, number],
      columnCosines: [0, -1, 0] as [number, number, number],
    };
    const prepared = prepareGeometry([slice(0, 0), reversed]);
    expect(prepared.warnings.join(' ')).toContain('orientations vary');
  });

  it('uses the first complete geometry rather than an incomplete first file', () => {
    const incomplete = {
      ...slice(0, 0),
      rowCosines: undefined,
      columnCosines: undefined,
      rowPixelSpacing: undefined,
      columnPixelSpacing: undefined,
      usingDefaultValues: true,
    };
    const complete = slice(1, 1);
    const prepared = prepareGeometry([incomplete, complete]);

    expect(prepared.direction).toEqual([1, 0, 0, 0, 1, 0, 0, 0, 1]);
    expect(prepared.spacing.slice(0, 2)).toEqual([0.7, 0.8]);
  });

  it('uses median in-plane spacing and warns when values vary', () => {
    const first = slice(0, 0);
    const second = {
      ...slice(1, 1),
      columnPixelSpacing: 0.9,
      rowPixelSpacing: 1,
    };
    const prepared = prepareGeometry([first, second]);

    expect(prepared.spacing.slice(0, 2)).toEqual([0.8, 0.9]);
    expect(prepared.warnings.join(' ')).toContain('pixel spacing varies');
  });

  it('preserves frame order and uses Spacing Between Slices for duplicate positions', () => {
    const frames = [
      { ...slice(0, 2), spacingBetweenSlices: 2.5 },
      { ...slice(0, 0), spacingBetweenSlices: 2.5 },
      { ...slice(0, 1), spacingBetweenSlices: 2.5 },
    ];
    const prepared = prepareGeometry(frames);

    expect(prepared.slices.map((item) => item.sourceIndex)).toEqual([0, 1, 2]);
    expect(prepared.spacing[2]).toBe(2.5);
    expect(prepared.warnings.join(' ')).toContain('input frame order was preserved');
    expect(prepared.warnings.join(' ')).toContain('Spacing Between Slices');
  });

  it('packs modality values into a compact normalized R8 volume', () => {
    const slices = [slice(0, 0), slice(10, 1)];
    const packed = quantizeScalarSlices(slices, [2, 2, 2]);

    expect(packed.data).toHaveLength(8);
    expect(packed.dataRange).toEqual([0, 13]);
    expect(packed.data[0]).toBe(0);
    expect(packed.data[7]).toBe(255);
  });

  it('supports cooperative cancellation during async volume packing', async () => {
    const controller = new AbortController();
    controller.abort();
    await expect(
      quantizeScalarSlicesAsync([slice(0, 0)], [2, 2, 1], {
        signal: controller.signal,
      }),
    ).rejects.toMatchObject({ name: 'AbortError' });
  });
});

describe('Cornerstone modality scaling', () => {
  it('trusts an explicit worker prescale marker and avoids double scaling', () => {
    const pixels = new Int16Array([0, 100]);
    expect(
      ensureModalityScaledPixels(pixels, {
        preScaleScaled: true,
        slope: 2,
        intercept: -1000,
      }),
    ).toBe(pixels);
  });

  it('applies slope and intercept when direct-load prescaling did not run', () => {
    const scaled = ensureModalityScaledPixels(new Int16Array([0, 100]), {
      isPreScaled: undefined,
      preScaleScaled: false,
      slope: 2,
      intercept: -1000,
    });
    expect(Array.from(scaled)).toEqual([-1000, -800]);
  });
});
