import type { Vec3Tuple } from '../types';

export interface ClippingBounds {
  minimum: Vec3Tuple;
  maximum: Vec3Tuple;
}

export const FULL_CLIPPING_BOUNDS: ClippingBounds = {
  minimum: [0, 0, 0],
  maximum: [1, 1, 1],
};

const MINIMUM_CLIP_SPAN = 0.02;

export function normalizeClippingBounds(
  minimum: Vec3Tuple,
  maximum: Vec3Tuple,
): ClippingBounds {
  const normalizedMinimum: Vec3Tuple = [0, 0, 0];
  const normalizedMaximum: Vec3Tuple = [1, 1, 1];

  for (let index = 0; index < 3; index += 1) {
    const rawMinimum = minimum[index];
    const rawMaximum = maximum[index];
    const safeMinimum =
      typeof rawMinimum === 'number' && Number.isFinite(rawMinimum) ? rawMinimum : 0;
    const safeMaximum =
      typeof rawMaximum === 'number' && Number.isFinite(rawMaximum) ? rawMaximum : 1;
    const clampedMinimum = Math.max(
      0,
      Math.min(1 - MINIMUM_CLIP_SPAN, safeMinimum),
    );
    const clampedMaximum = Math.max(
      clampedMinimum + MINIMUM_CLIP_SPAN,
      Math.min(1, safeMaximum),
    );
    normalizedMinimum[index] = clampedMinimum;
    normalizedMaximum[index] = clampedMaximum;
  }

  return { minimum: normalizedMinimum, maximum: normalizedMaximum };
}

export function hasActiveClipping(bounds: ClippingBounds): boolean {
  const epsilon = 1e-6;
  return (
    bounds.minimum.some((value) => value > epsilon) ||
    bounds.maximum.some((value) => value < 1 - epsilon)
  );
}

export function isFullClipping(bounds: ClippingBounds): boolean {
  return (
    bounds.minimum.every((value) => value <= 0.001) &&
    bounds.maximum.every((value) => value >= 0.999)
  );
}

/** Ignore visually negligible cuts when remembering a cutaway preset. */
export function hasMeaningfulClipping(bounds: ClippingBounds): boolean {
  return (
    bounds.minimum.some((value) => value >= 0.05) ||
    bounds.maximum.some((value) => value <= 0.95)
  );
}
