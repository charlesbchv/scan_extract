const MAX_FRAME_COUNT = 16_384;

function scalarValue(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value[0];
  }
  if (value && typeof value === 'object' && 'Value' in value) {
    const nested = (value as { Value?: unknown }).Value;
    return Array.isArray(nested) ? nested[0] : nested;
  }
  return value;
}

export function naturalizedFrameCount(
  naturalized: Record<string, unknown> | undefined,
): number {
  if (!naturalized || naturalized.NumberOfFrames === undefined) {
    return 1;
  }
  const parsed = Number(scalarValue(naturalized.NumberOfFrames));
  if (!Number.isFinite(parsed) || !Number.isInteger(parsed) || parsed < 1) {
    throw new Error('The DICOM instance contains an invalid Number of Frames value.');
  }
  if (parsed > MAX_FRAME_COUNT) {
    throw new Error(
      `The DICOM instance declares ${parsed.toLocaleString()} frames, above the ${MAX_FRAME_COUNT.toLocaleString()} frame safety limit.`,
    );
  }
  return parsed;
}

/** Resolve the explicit 1-based frame imageIds for a local Part-10 instance. */
export function localFrameImageIds(
  baseImageId: string,
  naturalized: Record<string, unknown> | undefined,
  providerImageIds?: Iterable<string>,
): string[] {
  const frameCount = naturalizedFrameCount(naturalized);
  if (frameCount <= 1) {
    return [baseImageId];
  }

  const provided = providerImageIds ? [...new Set(providerImageIds)] : [];
  if (provided.length === frameCount) {
    return provided;
  }

  const separator = baseImageId.includes('?') ? '&' : '?';
  return Array.from(
    { length: frameCount },
    (_, index) => `${baseImageId}${separator}frame=${index + 1}`,
  );
}
