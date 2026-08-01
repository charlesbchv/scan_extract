/** Public surface for embedding the boilerplate in an existing web viewer. */
export { ensureCornerstone } from './cornerstone/initCornerstone';
export {
  loadCornerstoneImageIds,
  loadDicomFiles,
} from './dicom/loadDicomSeries';
export {
  QUALITY_SETTINGS,
  VolumeRayMarcher,
  type ClippingBounds,
  type RendererMetrics,
  type RenderQuality,
} from './volume/VolumeRayMarcher';
export {
  TRANSFER_PRESETS,
  type TransferPreset,
  type TransferPresetId,
} from './volume/transferFunctions';
export type { LoadProgress, Vec3Tuple, VolumeData } from './types';
