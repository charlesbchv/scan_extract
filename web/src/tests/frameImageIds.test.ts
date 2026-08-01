import { describe, expect, it } from 'vitest';

import {
  localFrameImageIds,
  naturalizedFrameCount,
} from '../dicom/frameImageIds';

describe('local multi-frame DICOM image IDs', () => {
  it('keeps a single-frame instance on its base image ID', () => {
    expect(localFrameImageIds('dicomfile:0', {})).toEqual(['dicomfile:0']);
  });

  it('uses all 1-based frame IDs supplied by the metadata provider', () => {
    const providerIds = new Set([
      'dicomfile:0?frame=1',
      'dicomfile:0?frame=2',
      'dicomfile:0?frame=3',
    ]);

    expect(
      localFrameImageIds('dicomfile:0', { NumberOfFrames: 3 }, providerIds),
    ).toEqual([...providerIds]);
  });

  it('constructs explicit frame IDs when provider metadata is unavailable', () => {
    expect(
      localFrameImageIds('dicomfile:7?token=local', { NumberOfFrames: '3' }),
    ).toEqual([
      'dicomfile:7?token=local&frame=1',
      'dicomfile:7?token=local&frame=2',
      'dicomfile:7?token=local&frame=3',
    ]);
  });

  it('accepts naturalized values wrapped by DICOM JSON metadata', () => {
    expect(naturalizedFrameCount({ NumberOfFrames: { Value: ['12'] } })).toBe(12);
  });

  it('rejects implausibly large frame declarations before allocating IDs', () => {
    expect(() => naturalizedFrameCount({ NumberOfFrames: 20_000 })).toThrow(
      'frame safety limit',
    );
  });

  it.each([0, 2.5, 'not-a-number'])(
    'rejects an invalid Number of Frames value: %s',
    (value) => {
      expect(() => naturalizedFrameCount({ NumberOfFrames: value })).toThrow(
        'invalid Number of Frames',
      );
    },
  );
});
