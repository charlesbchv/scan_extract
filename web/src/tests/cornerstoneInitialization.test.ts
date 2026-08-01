import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  coreInit: vi.fn(),
  dicomImageLoaderInit: vi.fn(),
}));

vi.mock('@cornerstonejs/core', () => ({
  init: mocks.coreInit,
}));

vi.mock('@cornerstonejs/dicom-image-loader/imageLoader', () => ({
  init: mocks.dicomImageLoaderInit,
}));

describe('Cornerstone initialization', () => {
  beforeEach(() => {
    vi.resetModules();
    mocks.coreInit.mockReset();
    mocks.dicomImageLoaderInit.mockReset();
  });

  it('initializes core before the DICOM loader and shares concurrent calls', async () => {
    const calls: string[] = [];
    mocks.coreInit.mockImplementation(() => {
      calls.push('core');
      return true;
    });
    mocks.dicomImageLoaderInit.mockImplementation(() => {
      calls.push('dicom');
    });
    const { ensureCornerstone } = await import('../cornerstone/initCornerstone');

    const first = ensureCornerstone();
    const second = ensureCornerstone();

    expect(first).toBe(second);
    await Promise.all([first, second]);
    expect(calls).toEqual(['core', 'dicom']);
    expect(mocks.coreInit).toHaveBeenCalledTimes(1);
    expect(mocks.dicomImageLoaderInit).toHaveBeenCalledTimes(1);
    expect(mocks.dicomImageLoaderInit).toHaveBeenCalledWith(
      expect.objectContaining({ useLegacyMetadataProvider: true }),
    );
  });

  it('allows a clean retry when bootstrap throws', async () => {
    mocks.coreInit.mockReturnValue(true);
    mocks.dicomImageLoaderInit
      .mockImplementationOnce(() => {
        throw new Error('worker bootstrap failed');
      })
      .mockImplementationOnce(() => undefined);
    const { ensureCornerstone } = await import('../cornerstone/initCornerstone');

    await expect(ensureCornerstone()).rejects.toThrow('worker bootstrap failed');
    await expect(ensureCornerstone()).resolves.toBeUndefined();

    expect(mocks.coreInit).toHaveBeenCalledTimes(2);
    expect(mocks.dicomImageLoaderInit).toHaveBeenCalledTimes(2);
  });
});
