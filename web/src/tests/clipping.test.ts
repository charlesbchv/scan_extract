import { describe, expect, it } from 'vitest';

import {
  FULL_CLIPPING_BOUNDS,
  hasActiveClipping,
  hasMeaningfulClipping,
  isFullClipping,
  normalizeClippingBounds,
  type ClippingBounds,
} from '../volume/clipping';

describe('six-face volume clipping', () => {
  it('preserves valid minimum and maximum bounds', () => {
    expect(
      normalizeClippingBounds([0.08, 0.12, 0.06], [0.78, 0.92, 0.76]),
    ).toEqual({
      minimum: [0.08, 0.12, 0.06],
      maximum: [0.78, 0.92, 0.76],
    });
  });

  it('clamps values and keeps a non-empty interval on every axis', () => {
    const bounds = normalizeClippingBounds([1.2, -0.5, 0.6], [0.2, 2, 0.61]);

    expect(bounds.minimum).toEqual([0.98, 0, 0.6]);
    expect(bounds.maximum[0]).toBe(1);
    expect(bounds.maximum[1]).toBe(1);
    expect(bounds.maximum[2]).toBeCloseTo(0.62);
  });

  it('falls back safely for non-finite values and detects active cuts', () => {
    const safe = normalizeClippingBounds(
      [Number.NaN, 0, 0],
      [Number.POSITIVE_INFINITY, 1, 1],
    );

    expect(safe).toEqual(FULL_CLIPPING_BOUNDS);
    expect(hasActiveClipping(FULL_CLIPPING_BOUNDS)).toBe(false);
    expect(isFullClipping(FULL_CLIPPING_BOUNDS)).toBe(true);
    expect(
      hasActiveClipping({ minimum: [0, 0.1, 0], maximum: [1, 1, 1] }),
    ).toBe(true);
  });

  it('does not remember a nearly invisible crop as the cutaway preset', () => {
    const nearlyFull: ClippingBounds = {
      minimum: [0.04, 0, 0],
      maximum: [1, 1, 0.96],
    };
    const visibleCut: ClippingBounds = {
      minimum: [0.05, 0, 0],
      maximum: [1, 1, 1],
    };

    expect(hasMeaningfulClipping(nearlyFull)).toBe(false);
    expect(hasMeaningfulClipping(visibleCut)).toBe(true);
  });
});
