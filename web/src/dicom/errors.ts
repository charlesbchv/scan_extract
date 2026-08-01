const LOCAL_IMAGE_ID = /\bdicomfile:[^\s"'<>]+/gi;
const DICOM_SOURCE_ID = /\b(?:https?:\/\/|wadouri:|wadors:|dicomweb:|file:|blob:)[^\s"'<>]+/gi;

function sanitizeMessage(message: string): string | undefined {
  const sanitized = message
    .replace(LOCAL_IMAGE_ID, '[local DICOM]')
    .replace(DICOM_SOURCE_ID, '[DICOM source]')
    .replace(/\s+/g, ' ')
    .trim();
  if (!sanitized) {
    return undefined;
  }
  return sanitized.length > 320 ? `${sanitized.slice(0, 317)}…` : sanitized;
}

/** Extract only a safe message from Cornerstone's nested rejection objects. */
export function describeDicomError(error: unknown, depth = 0): string | undefined {
  if (depth > 4) {
    return undefined;
  }
  if (typeof error === 'string') {
    return sanitizeMessage(error);
  }
  if (error instanceof Error) {
    const message = sanitizeMessage(error.message);
    const cause = describeDicomError(error.cause, depth + 1);
    if (message && cause && message !== cause) {
      return sanitizeMessage(`${message}: ${cause}`);
    }
    return message ?? cause;
  }
  if (!error || typeof error !== 'object') {
    return undefined;
  }

  const record = error as Record<string, unknown>;
  for (const key of ['error', 'cause', 'reason']) {
    const nested = describeDicomError(record[key], depth + 1);
    if (nested) {
      return nested;
    }
  }
  return typeof record.message === 'string'
    ? sanitizeMessage(record.message)
    : undefined;
}

export function insufficientStackMessage(
  requested: number,
  decoded: number,
  firstFailure?: string,
): string {
  let message: string;
  if (decoded === 1 && requested === 1) {
    message =
      'Only one readable DICOM frame was available. A 3D volume needs at least two slices. Select every slice in the series; multi-frame integrations must provide an explicit image ID for each frame.';
  } else if (decoded === 1) {
    message =
      `Only 1 of ${requested} DICOM frames decoded successfully. ` +
      'A 3D volume needs at least two compatible grayscale frames.';
  } else {
    message =
      requested === 1
        ? 'The selected DICOM frame could not be decoded as a grayscale image.'
        : `None of the ${requested} candidate DICOM frames could be decoded as grayscale images.`;
  }
  const safeFailure = firstFailure ? sanitizeMessage(firstFailure) : undefined;
  return safeFailure ? `${message} Decoder detail: ${safeFailure}` : message;
}

export function rejectedFileContextMessage(
  loadError: unknown,
  rejectedFiles: number,
  selectedFiles: number,
  parserFailure?: string,
): string {
  const base =
    describeDicomError(loadError) ?? 'The readable DICOM frames could not form a volume.';
  const noun = rejectedFiles === 1 ? 'file was' : 'files were';
  const context = `${rejectedFiles} of ${selectedFiles} selected ${noun} not readable as DICOM.`;
  const safeParserFailure = parserFailure ? sanitizeMessage(parserFailure) : undefined;
  return safeParserFailure
    ? `${base} ${context} Parser detail: ${safeParserFailure}`
    : `${base} ${context}`;
}
