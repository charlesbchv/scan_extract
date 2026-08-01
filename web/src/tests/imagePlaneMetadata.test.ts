import { describe, expect, it } from 'vitest';

import { mergeImagePlaneMetadata } from '../dicom/loadDicomSeries';

describe('image-plane metadata merging', () => {
  it('keeps valid geometry supplied by the legacy dataset provider', () => {
    const merged = mergeImagePlaneMetadata(
      {
        Rows: 128,
        Columns: 128,
        SOPClassUID: '1.2.3',
      },
      {
        rowCosines: [1, 0, 0],
        columnCosines: [0, 1, 0],
        imagePositionPatient: [-158.1, -179, -75.7],
        rowPixelSpacing: 0.661468,
        columnPixelSpacing: 0.661468,
        sliceThickness: 5,
        usingDefaultValues: false,
      },
    );

    expect(merged.imagePositionPatient).toEqual([-158.1, -179, -75.7]);
    expect(merged.rowPixelSpacing).toBe(0.661468);
    expect(merged.sliceThickness).toBe(5);
  });

  it('discards identity geometry synthesized by the modern provider', () => {
    const merged = mergeImagePlaneMetadata(
      {
        Rows: 64,
        Columns: 64,
        SOPClassUID: '1.2.3',
      },
      {
        rowCosines: [1, 0, 0],
        columnCosines: [0, 1, 0],
        imagePositionPatient: [0, 0, 0],
        usingDefaultValues: true,
        isDefaultValueSetForRowCosine: true,
        isDefaultValueSetForColumnCosine: true,
      },
    );

    expect(merged.rowCosines).toBeUndefined();
    expect(merged.columnCosines).toBeUndefined();
    expect(merged.imagePositionPatient).toBeUndefined();
  });

  it('uses real naturalized geometry when only pixel spacing is defaulted', () => {
    const merged = mergeImagePlaneMetadata(
      {
        Rows: 64,
        Columns: 64,
        SOPClassUID: '1.2.3',
        ImageOrientationPatient: [1, 0, 0, 0, 1, 0],
        ImagePositionPatient: [10, 20, 30],
      },
      {
        rowPixelSpacing: 1,
        columnPixelSpacing: 1,
        usingDefaultValues: true,
        isDefaultValueSetForRowCosine: false,
        isDefaultValueSetForColumnCosine: false,
      },
    );

    expect(merged.imageOrientationPatient).toEqual([1, 0, 0, 0, 1, 0]);
    expect(merged.imagePositionPatient).toEqual([10, 20, 30]);
    expect(merged.usingDefaultValues).toBe(true);
  });
});
