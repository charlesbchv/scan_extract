export interface ModalityScaleState {
  isPreScaled?: boolean;
  preScaleScaled?: boolean;
  slope?: number;
  intercept?: number;
}

/**
 * Ensure scalar pixels are in modality units exactly once. Direct Cornerstone
 * image loads report the authoritative worker state through `preScale.scaled`;
 * `isPreScaled` is commonly populated only after a viewport consumes an image.
 */
export function ensureModalityScaledPixels(
  pixels: ArrayLike<number>,
  state: ModalityScaleState,
): ArrayLike<number> {
  if (state.isPreScaled === true || state.preScaleScaled === true) {
    return pixels;
  }

  const slope = Number.isFinite(state.slope) ? (state.slope ?? 1) : 1;
  const intercept = Number.isFinite(state.intercept) ? (state.intercept ?? 0) : 0;
  if (slope === 1 && intercept === 0) {
    return pixels;
  }

  const scaled = new Float32Array(pixels.length);
  for (let index = 0; index < pixels.length; index += 1) {
    scaled[index] = Number(pixels[index]) * slope + intercept;
  }
  return scaled;
}
