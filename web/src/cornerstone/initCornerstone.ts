import { init as coreInit } from '@cornerstonejs/core';
import { init as dicomImageLoaderInit } from '@cornerstonejs/dicom-image-loader/imageLoader';

// `var` is intentional here. This module can be part of a Vite dependency
// cycle while Cornerstone's providers are registered; unlike a lexical
// boolean, the promise remains safe to read during module instantiation.
var initializationPromise: Promise<void> | undefined;

/** Initialize the standalone demo's Cornerstone lifecycle and codecs once. */
export function ensureCornerstone(): Promise<void> {
  if (initializationPromise) {
    return initializationPromise;
  }

  initializationPromise = Promise.resolve()
    .then(() => {
      coreInit();
      dicomImageLoaderInit({
        maxWebWorkers: Math.max(
          1,
          Math.min(4, Math.floor((navigator.hardwareConcurrency || 2) / 2)),
        ),
        // Cornerstone 5.6's NATURALIZED local loader can omit PixelData for
        // Deflated Explicit VR and some uncompressed Part-10 instances. The
        // dataset-backed loader handles those transfer syntaxes and still uses
        // the same worker codecs for pixel decode.
        useLegacyMetadataProvider: true,
      });
    })
    .catch((error: unknown) => {
      // A failed bootstrap must not poison every later retry (notably after
      // Vite HMR replaces a stale dependency graph during development).
      initializationPromise = undefined;
      throw error;
    });

  return initializationPromise;
}
