import { describe, expect, it } from 'vitest';

import { assertVolumeTransferSyntax } from '../dicom/transferSyntax';

describe('DICOM transfer syntax routing', () => {
  it('allows Deflated Explicit VR for the dataset-backed loader', () => {
    expect(() =>
      assertVolumeTransferSyntax('1.2.840.10008.1.2.1.99'),
    ).not.toThrow();
  });

  it.each([
    '1.2.840.10008.1.2.4.100',
    '1.2.840.10008.1.2.4.102',
    '1.2.840.10008.1.2.4.105',
  ])('rejects temporal video transfer syntax %s', (transferSyntaxUid) => {
    expect(() => assertVolumeTransferSyntax(transferSyntaxUid)).toThrow(
      'cine video frames',
    );
  });
});
