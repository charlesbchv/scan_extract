import { describe, expect, it } from 'vitest';

describe('DICOM browser module graph', () => {
  it('evaluates the public loader entry without a temporal-dead-zone error', async () => {
    const module = await import('../dicom/loadDicomSeries');

    expect(module.loadCornerstoneImageIds).toBeTypeOf('function');
    expect(module.loadDicomFiles).toBeTypeOf('function');
  });
});
