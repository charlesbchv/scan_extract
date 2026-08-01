import { describe, expect, it } from 'vitest';

import {
  chooseLargestIndexedStack,
  indexLocalDataSet,
  type LocalDataSetIndex,
  type LocalDataSetLike,
} from '../dicom/loadDicomSeries';

function dataSet(
  fields: Record<string, string | number>,
  hasPixelData = true,
): LocalDataSetLike {
  return {
    elements: hasPixelData ? { x7fe00010: {} } : {},
    string: (tag) => {
      const value = fields[tag];
      return value === undefined ? undefined : String(value);
    },
    intString: (tag) => {
      const value = fields[tag];
      return value === undefined ? undefined : Number(value);
    },
    uint16: (tag) => {
      const value = fields[tag];
      return value === undefined ? undefined : Number(value);
    },
  };
}

function indexed(
  baseImageId: string,
  seriesUid: string,
  frames: number,
  compatibilityKey = '512x512:1:16',
): LocalDataSetIndex {
  return {
    baseImageId,
    uri: baseImageId.slice('dicomfile:'.length),
    imageIds: Array.from(
      { length: frames },
      (_, frame) => `${baseImageId}?frame=${frame + 1}`,
    ),
    seriesUid,
    compatibilityKey,
  };
}

describe('local dataset indexing', () => {
  it('indexes Deflated Explicit VR as a normal image instance', () => {
    const result = indexLocalDataSet(
      'dicomfile:4',
      dataSet({
        x00020010: '1.2.840.10008.1.2.1.99',
        x0020000e: 'series-a',
        x00280010: 512,
        x00280011: 512,
        x00280002: 1,
        x00280100: 8,
      }),
    );

    expect(result.imageIds).toEqual(['dicomfile:4']);
    expect(result.compatibilityKey).toBe('512x512:1:8');
  });

  it('expands every declared frame before decode', () => {
    const result = indexLocalDataSet(
      'dicomfile:2',
      dataSet({
        x00020010: '1.2.840.10008.1.2.1',
        x0020000e: 'series-a',
        x00280008: 3,
        x00280010: 64,
        x00280011: 64,
      }),
    );

    expect(result.imageIds).toEqual([
      'dicomfile:2?frame=1',
      'dicomfile:2?frame=2',
      'dicomfile:2?frame=3',
    ]);
  });

  it('rejects non-image DICOM objects before pixel decode', () => {
    expect(() =>
      indexLocalDataSet(
        'dicomfile:3',
        dataSet(
          {
            x00020010: '1.2.840.10008.1.2.1',
            x00280010: 512,
            x00280011: 512,
          },
          false,
        ),
      ),
    ).toThrow('does not contain a raster pixel image');
  });

  it('preselects the series and dimensions containing the most frames', () => {
    const largest = chooseLargestIndexedStack([
      indexed('dicomfile:0', 'series-a', 2),
      indexed('dicomfile:1', 'series-a', 3),
      indexed('dicomfile:2', 'series-b', 4),
      indexed('dicomfile:3', 'series-a', 8, '256x256:1:16'),
    ]);

    expect(largest.map((item) => item.baseImageId)).toEqual(['dicomfile:3']);
  });
});
