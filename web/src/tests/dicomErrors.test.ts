import { describe, expect, it } from 'vitest';

import {
  describeDicomError,
  insufficientStackMessage,
  rejectedFileContextMessage,
} from '../dicom/errors';

describe('DICOM decode diagnostics', () => {
  it('unwraps Cornerstone errors without exposing the source ID or dataset', () => {
    const detail = describeDicomError({
      error: new Error(
        'No decoder for transfer syntax at dicomfile:2?frame=3',
      ),
      dataSet: { PatientName: 'private patient name' },
    });

    expect(detail).toContain('No decoder for transfer syntax');
    expect(detail).toContain('[local DICOM]');
    expect(detail).not.toContain('dicomfile:2');
    expect(detail).not.toContain('private patient name');
  });

  it('redacts complete local query strings and WADO-RS image IDs', () => {
    const detail = describeDicomError(
      'Failed dicomfile:7?token=private-value&frame=2 via wadors:https://example.test/studies/private',
    );

    expect(detail).toBe('Failed [local DICOM] via [DICOM source]');
    expect(detail).not.toContain('private-value');
    expect(detail).not.toContain('example.test');
  });

  it('keeps an actionable nested Error cause', () => {
    const detail = describeDicomError(
      new Error('Pixel decode failed', {
        cause: new Error('Unsupported transfer syntax'),
      }),
    );
    expect(detail).toBe('Pixel decode failed: Unsupported transfer syntax');
  });

  it('explains that one genuinely single-frame file cannot form a volume', () => {
    expect(insufficientStackMessage(1, 1)).toContain(
      'Select every slice in the series',
    );
  });

  it('includes the first actionable decoder failure', () => {
    expect(
      insufficientStackMessage(12, 0, 'JPEG Lossless decoder failed'),
    ).toContain('Decoder detail: JPEG Lossless decoder failed');
  });

  it('preserves parser context when one of two selected files was rejected', () => {
    const message = rejectedFileContextMessage(
      new Error('Only one readable DICOM frame was available.'),
      1,
      2,
      'DICOM Part-10 header is missing',
    );

    expect(message).toContain('1 of 2 selected file was not readable as DICOM');
    expect(message).toContain('Parser detail: DICOM Part-10 header is missing');
  });
});
