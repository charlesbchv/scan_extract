import { describe, expect, it } from 'vitest';

import { QUALITY_SETTINGS } from '../volume/VolumeRayMarcher';

describe('interactive volume quality budget', () => {
  it('uses a low-resolution preview for every final quality preset', () => {
    for (const settings of Object.values(QUALITY_SETTINGS)) {
      expect(settings.interactiveSteps).toBeLessThan(settings.steps);
      expect(settings.interactivePixelRatio).toBeLessThanOrEqual(0.9);
      expect(settings.interactivePixelRatio).toBeLessThan(settings.pixelRatio);
    }
  });

  it('keeps the balanced drag workload below one eighth of final rendering', () => {
    const balanced = QUALITY_SETTINGS.balanced;
    const finalWork = balanced.steps * balanced.pixelRatio ** 2;
    const interactiveWork =
      balanced.interactiveSteps * balanced.interactivePixelRatio ** 2;

    expect(interactiveWork / finalWork).toBeLessThan(0.125);
  });
});
