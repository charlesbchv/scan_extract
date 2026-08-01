import { imageLoader, metaData } from '@cornerstonejs/core';
import type { Types as CornerstoneTypes } from '@cornerstonejs/core';
import wadouri from '@cornerstonejs/dicom-image-loader/wadouri';
import { MetadataModules } from '@cornerstonejs/metadata/enums';

import { ensureCornerstone } from '../cornerstone/initCornerstone';
import type { LoadProgress, Vec3Tuple, VolumeData } from '../types';
import {
  prepareGeometry,
  quantizeScalarSlicesAsync,
  type SliceGeometry,
} from './geometry';
import {
  describeDicomError,
  insufficientStackMessage,
  rejectedFileContextMessage,
} from './errors';
import { localFrameImageIds } from './frameImageIds';
import { ensureModalityScaledPixels } from './pixels';
import { assertVolumeTransferSyntax } from './transferSyntax';

interface LoadOptions {
  signal?: AbortSignal;
  onProgress?: (progress: LoadProgress) => void;
}

export interface ImagePlaneMetadata {
  rowCosines?: unknown;
  columnCosines?: unknown;
  imageOrientationPatient?: unknown;
  imagePositionPatient?: unknown;
  rowPixelSpacing?: unknown;
  columnPixelSpacing?: unknown;
  spacingBetweenSlices?: unknown;
  sliceThickness?: unknown;
  sliceLocation?: unknown;
  usingDefaultValues?: unknown;
  isDefaultValueSetForRowCosine?: unknown;
  isDefaultValueSetForColumnCosine?: unknown;
}

function numberPair(value: unknown): [number, number] | undefined {
  const values =
    typeof value === 'string'
      ? value.split(/[\\,\s]+/)
      : value && typeof value === 'object'
        ? Array.from(value as ArrayLike<unknown>)
        : [];
  if (values.length < 2) {
    return undefined;
  }
  const pair: [number, number] = [Number(values[0]), Number(values[1])];
  return pair.every(Number.isFinite) ? pair : undefined;
}

function isNaturalizedImageInstance(instance: Record<string, unknown>): boolean {
  return [
    'Rows',
    'Columns',
    'PhotometricInterpretation',
    'SOPClassUID',
    'TransferSyntaxUID',
  ].some((field) => instance[field] !== undefined);
}

export function mergeImagePlaneMetadata(
  instance: Record<string, unknown>,
  providerPlane: ImagePlaneMetadata,
): ImagePlaneMetadata {
  if (!isNaturalizedImageInstance(instance)) {
    return providerPlane;
  }
  const pixelSpacing = numberPair(
    instance.PixelSpacing ?? instance.ImagerPixelSpacing,
  );
  const providerHasModernDefaultFlags =
    'isDefaultValueSetForRowCosine' in providerPlane ||
    'isDefaultValueSetForColumnCosine' in providerPlane;
  const providerOrientationIsDefault =
    providerPlane.isDefaultValueSetForRowCosine === true ||
    providerPlane.isDefaultValueSetForColumnCosine === true;
  const directOrientation = instance.ImageOrientationPatient;
  const directPosition = instance.ImagePositionPatient;
  return {
    rowCosines:
      directOrientation === undefined && !providerOrientationIsDefault
        ? providerPlane.rowCosines
        : undefined,
    columnCosines:
      directOrientation === undefined && !providerOrientationIsDefault
        ? providerPlane.columnCosines
        : undefined,
    imageOrientationPatient:
      directOrientation ??
      (!providerOrientationIsDefault
        ? providerPlane.imageOrientationPatient
        : undefined),
    imagePositionPatient:
      directPosition ??
      (!providerHasModernDefaultFlags
        ? providerPlane.imagePositionPatient
        : undefined),
    rowPixelSpacing: pixelSpacing?.[0] ?? providerPlane.rowPixelSpacing,
    columnPixelSpacing: pixelSpacing?.[1] ?? providerPlane.columnPixelSpacing,
    spacingBetweenSlices:
      instance.SpacingBetweenSlices ?? providerPlane.spacingBetweenSlices,
    sliceThickness: instance.SliceThickness ?? providerPlane.sliceThickness,
    sliceLocation:
      instance.SliceLocation ??
      (!providerHasModernDefaultFlags ? providerPlane.sliceLocation : undefined),
    usingDefaultValues: pixelSpacing
      ? false
      : providerPlane.usingDefaultValues,
  };
}

/** Merge host-naturalized metadata without mistaking loader defaults for geometry. */
function imagePlaneMetadata(
  imageId: string,
  instance: Record<string, unknown>,
): ImagePlaneMetadata {
  const providerPlane = getMetadata('imagePlaneModule', imageId) as ImagePlaneMetadata;
  return mergeImagePlaneMetadata(instance, providerPlane);
}

interface LoadedSlice extends SliceGeometry {
  pixels: ArrayLike<number>;
  seriesUid: string;
  modality: string;
}

export interface LocalDataSetIndex {
  baseImageId: string;
  uri: string;
  imageIds: string[];
  seriesUid: string;
  compatibilityKey: string;
}

export interface LocalDataSetLike {
  elements?: Record<string, unknown>;
  string(tag: string): string | undefined;
  intString(tag: string): number | undefined;
  uint16(tag: string): number | undefined;
}

function abortError(): DOMException {
  return new DOMException('DICOM loading was cancelled.', 'AbortError');
}

function throwIfAborted(signal?: AbortSignal): void {
  if (signal?.aborted) {
    throw abortError();
  }
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : {};
}

function toNumber(value: unknown): number | undefined {
  const converted = Number(value);
  return Number.isFinite(converted) ? converted : undefined;
}

function toVec3(value: unknown): Vec3Tuple | undefined {
  if (!value || (typeof value !== 'object' && !Array.isArray(value))) {
    return undefined;
  }
  const array = Array.from(value as ArrayLike<unknown>);
  if (array.length < 3) {
    return undefined;
  }
  const result: Vec3Tuple = [Number(array[0]), Number(array[1]), Number(array[2])];
  return result.every(Number.isFinite) ? result : undefined;
}

function orientationFromPlane(plane: ImagePlaneMetadata): {
  rowCosines?: Vec3Tuple;
  columnCosines?: Vec3Tuple;
} {
  const rowCosines = toVec3(plane.rowCosines);
  const columnCosines = toVec3(plane.columnCosines);
  if (rowCosines && columnCosines) {
    return { rowCosines, columnCosines };
  }

  const orientation = plane.imageOrientationPatient
    ? Array.from(plane.imageOrientationPatient as ArrayLike<unknown>).map(Number)
    : [];
  if (orientation.length >= 6 && orientation.every(Number.isFinite)) {
    return {
      rowCosines: [orientation[0] ?? 1, orientation[1] ?? 0, orientation[2] ?? 0],
      columnCosines: [orientation[3] ?? 0, orientation[4] ?? 1, orientation[5] ?? 0],
    };
  }
  return {};
}

function getMetadata(type: string, imageId: string): Record<string, unknown> {
  return asRecord(metaData.get(type, imageId));
}

function prescaledPixels(image: CornerstoneTypes.IImage): ArrayLike<number> {
  return ensureModalityScaledPixels(image.getPixelData(), {
    isPreScaled: image.isPreScaled,
    preScaleScaled: image.preScale?.scaled,
    slope: image.slope,
    intercept: image.intercept,
  });
}

function decodeConcurrency(): number {
  return Math.max(
    1,
    Math.min(4, Math.floor((navigator.hardwareConcurrency || 2) / 2)),
  );
}

async function mapWithConcurrency<T, R>(
  values: T[],
  concurrency: number,
  callback: (value: T, index: number) => Promise<R>,
): Promise<R[]> {
  const results = new Array<R>(values.length);
  let cursor = 0;

  const workers = Array.from(
    { length: Math.min(concurrency, values.length) },
    async () => {
      while (cursor < values.length) {
        const index = cursor;
        cursor += 1;
        const value = values[index];
        if (value !== undefined) {
          results[index] = await callback(value, index);
        }
      }
    },
  );
  // Wait for every in-flight decode to settle before propagating cancellation.
  // The local-file wrapper can then safely remove its file-manager entries.
  const settled = await Promise.allSettled(workers);
  const failure = settled.find(
    (result): result is PromiseRejectedResult => result.status === 'rejected',
  );
  if (failure) {
    throw failure.reason;
  }
  return results;
}

async function decodeImage(
  imageId: string,
  sourceIndex: number,
): Promise<LoadedSlice> {
  const image = await imageLoader.loadImage(imageId);
  if (image.color || image.numberOfComponents !== 1) {
    throw new Error('Color or multi-component DICOM images are not supported by this scalar demo.');
  }

  const instance = getMetadata(MetadataModules.INSTANCE, imageId);
  const plane = imagePlaneMetadata(imageId, instance);
  const series = getMetadata('generalSeriesModule', imageId);
  const generalImage = getMetadata('generalImageModule', imageId);
  const orientation = orientationFromPlane(plane);

  return {
    imageId,
    sourceIndex,
    rows: image.rows,
    columns: image.columns,
    pixels: prescaledPixels(image),
    seriesUid: String(
      series.seriesInstanceUID ??
        series.seriesInstanceUid ??
        instance.SeriesInstanceUID ??
        image.FrameOfReferenceUID ??
        'unknown',
    ),
    modality: String(series.modality ?? instance.Modality ?? 'CT'),
    rowCosines: orientation.rowCosines,
    columnCosines: orientation.columnCosines,
    imagePositionPatient: toVec3(plane.imagePositionPatient),
    rowPixelSpacing: toNumber(plane.rowPixelSpacing ?? image.rowPixelSpacing),
    columnPixelSpacing: toNumber(plane.columnPixelSpacing ?? image.columnPixelSpacing),
    spacingBetweenSlices: toNumber(plane.spacingBetweenSlices),
    sliceThickness: toNumber(plane.sliceThickness ?? image.sliceThickness),
    sliceLocation: toNumber(plane.sliceLocation),
    usingDefaultValues: plane.usingDefaultValues === true,
    instanceNumber: toNumber(generalImage.instanceNumber ?? instance.InstanceNumber),
  };
}

function chooseLargestGroup(
  slices: LoadedSlice[],
  key: (slice: LoadedSlice) => string,
): LoadedSlice[] {
  const groups = new Map<string, LoadedSlice[]>();
  for (const slice of slices) {
    const groupKey = key(slice);
    const group = groups.get(groupKey) ?? [];
    group.push(slice);
    groups.set(groupKey, group);
  }
  return [...groups.values()].sort((a, b) => b.length - a.length)[0] ?? [];
}

export function indexLocalDataSet(
  baseImageId: string,
  dataSet: LocalDataSetLike,
): LocalDataSetIndex {
  const rawFrameCount =
    dataSet.intString('x00280008') ?? dataSet.string('x00280008');
  assertVolumeTransferSyntax(dataSet.string('x00020010')?.trim());
  const imageIds = localFrameImageIds(
    baseImageId,
    rawFrameCount === undefined ? undefined : { NumberOfFrames: rawFrameCount },
  );
  const rows = dataSet.uint16('x00280010') ?? 0;
  const columns = dataSet.uint16('x00280011') ?? 0;
  const samplesPerPixel = dataSet.uint16('x00280002') ?? 1;
  const bitsAllocated = dataSet.uint16('x00280100') ?? 0;
  const hasPixelElement = Boolean(
    dataSet.elements?.x7fe00010 ?? dataSet.elements?.x7fe00008,
  );
  if (
    rows < 1 ||
    columns < 1 ||
    (dataSet.elements !== undefined && !hasPixelElement)
  ) {
    throw new Error('The selected DICOM instance does not contain a raster pixel image.');
  }
  return {
    baseImageId,
    uri: wadouri.parseImageId(baseImageId).url,
    imageIds,
    seriesUid: dataSet.string('x0020000e')?.trim() || 'unknown',
    compatibilityKey: `${columns}x${rows}:${samplesPerPixel}:${bitsAllocated}`,
  };
}

export function chooseLargestIndexedStack(
  indexed: LocalDataSetIndex[],
): LocalDataSetIndex[] {
  const groups = new Map<string, LocalDataSetIndex[]>();
  for (const instance of indexed) {
    const key = `${instance.seriesUid}:${instance.compatibilityKey}`;
    const group = groups.get(key) ?? [];
    group.push(instance);
    groups.set(key, group);
  }
  return [...groups.values()].sort(
    (a, b) =>
      b.reduce((total, item) => total + item.imageIds.length, 0) -
      a.reduce((total, item) => total + item.imageIds.length, 0),
  )[0] ?? [];
}

/**
 * Reusable plugin boundary for an existing Cornerstone application: provide
 * image IDs from an already initialized/registered loader and receive a
 * compact Three.js volume. This deliberately does not mutate host lifecycle or
 * global caches by reinitializing the DICOM loader.
 */
export async function loadCornerstoneImageIds(
  imageIds: string[],
  options: LoadOptions = {},
): Promise<VolumeData> {
  if (imageIds.length === 0) {
    throw new Error('Choose a folder containing DICOM image instances.');
  }

  throwIfAborted(options.signal);
  options.onProgress?.({
    completed: 0,
    total: imageIds.length,
    phase: 'initializing',
    message: 'Preparing the DICOM decode pipeline…',
  });

  let completed = 0;
  let skipped = 0;
  const decodeFailures = new Array<string | undefined>(imageIds.length);
  const decoded = await mapWithConcurrency(
    imageIds,
    decodeConcurrency(),
    async (imageId, sourceIndex): Promise<LoadedSlice | undefined> => {
      throwIfAborted(options.signal);
      let result: LoadedSlice | undefined;
      try {
        result = await decodeImage(imageId, sourceIndex);
        throwIfAborted(options.signal);
      } catch (error) {
        if (options.signal?.aborted) {
          throw abortError();
        }
        skipped += 1;
        decodeFailures[sourceIndex] = describeDicomError(error);
      }
      completed += 1;
      options.onProgress?.({
        completed,
        total: imageIds.length,
        phase: 'decoding',
        message: `Processed ${completed} of ${imageIds.length} frames`,
      });
      return result;
    },
  );

  throwIfAborted(options.signal);
  const valid = decoded.filter((slice): slice is LoadedSlice => Boolean(slice));
  const firstDecodeFailure = decodeFailures.find(
    (failure): failure is string => Boolean(failure),
  );
  if (valid.length < 2) {
    throw new Error(
      insufficientStackMessage(imageIds.length, valid.length, firstDecodeFailure),
    );
  }

  const series = chooseLargestGroup(valid, (slice) => slice.seriesUid);
  if (series.length < 2) {
    throw new Error(
      'The images decoded successfully, but no DICOM series contains at least two frames. Select the complete files from one series.',
    );
  }
  const compatible = chooseLargestGroup(
    series,
    (slice) => `${slice.columns}x${slice.rows}:${slice.pixels.length}`,
  );
  if (compatible.length < 2) {
    throw new Error('No dimensionally consistent DICOM stack was found.');
  }

  const prepared = prepareGeometry(compatible);
  options.onProgress?.({
    completed: 0,
    total: prepared.dimensions[2] * 2,
    phase: 'assembling',
    message: 'Sorting geometry and scanning the scalar range…',
  });
  const packed = await quantizeScalarSlicesAsync(prepared.slices, prepared.dimensions, {
    signal: options.signal,
    onProgress: (packedSlices, totalSlicePasses) => {
      const depth = prepared.dimensions[2];
      const scanningRange = packedSlices <= depth;
      const sliceInPass = scanningRange ? packedSlices : packedSlices - depth;
      options.onProgress?.({
        completed: packedSlices,
        total: totalSlicePasses,
        phase: 'assembling',
        message: `${scanningRange ? 'Scanning scalar range' : 'Packing 3D texture'} · slice ${sliceInPass} of ${depth}`,
      });
    },
  });
  const ignored = valid.length - compatible.length;
  const warnings = [...prepared.warnings];
  if (skipped > 0) {
    const detail = firstDecodeFailure
      ? ` First decoder detail: ${firstDecodeFailure}`
      : '';
    warnings.push(
      `${skipped} frames were skipped because they were not decodable scalar DICOM images.${detail}`,
    );
  }
  if (ignored > 0) {
    warnings.push(`${ignored} decoded images from other or incompatible series were ignored.`);
  }
  const modality = compatible[0]?.modality ?? 'CT';
  if (modality.toUpperCase() !== 'CT') {
    warnings.push(`Modality ${modality} was loaded, but the included transfer presets are CT-oriented.`);
  }

  return {
    data: packed.data,
    dimensions: prepared.dimensions,
    spacing: prepared.spacing,
    origin: prepared.origin,
    direction: prepared.direction,
    dataRange: packed.dataRange,
    modality,
    sourceLabel: `Local ${modality} stack`,
    warnings,
  };
}

/** Load browser File objects locally without uploading or logging identifiers. */
export async function loadDicomFiles(
  files: File[],
  options: LoadOptions = {},
): Promise<VolumeData> {
  if (files.length === 0) {
    throw new Error('Choose DICOM files or a folder containing a complete series.');
  }
  await ensureCornerstone();
  const baseImageIds = files.map((file) => wadouri.fileManager.add(file));
  let imageIds: string[] = [];
  let rejectedFiles = 0;
  let ignoredIndexedFrames = 0;
  const inspectionFailures = new Array<string | undefined>(files.length);
  try {
    let inspected = 0;
    const indexedResults = await mapWithConcurrency(
      baseImageIds.map((baseImageId) => baseImageId as string),
      decodeConcurrency(),
      async (baseImageId, sourceIndex): Promise<LocalDataSetIndex | undefined> => {
        throwIfAborted(options.signal);
        try {
          const uri = wadouri.parseImageId(baseImageId).url;
          const dataSet = (await wadouri.dataSetCacheManager.load(
            uri,
            wadouri.loadFileRequest,
            baseImageId,
          )) as LocalDataSetLike;
          throwIfAborted(options.signal);
          return indexLocalDataSet(baseImageId, dataSet);
        } catch (error) {
          if (options.signal?.aborted) {
            throw abortError();
          }
          rejectedFiles += 1;
          inspectionFailures[sourceIndex] = describeDicomError(error);
          return undefined;
        } finally {
          inspected += 1;
          options.onProgress?.({
            completed: inspected,
            total: files.length,
            phase: 'initializing',
            message: `Indexed ${inspected} of ${files.length} local DICOM files`,
          });
        }
      },
    );
    const indexed = indexedResults.filter(
      (result): result is LocalDataSetIndex => Boolean(result),
    );
    const selected = chooseLargestIndexedStack(indexed);
    const selectedBaseImageIds = new Set(selected.map((item) => item.baseImageId));
    const indexedFrameCount = indexed.reduce(
      (total, item) => total + item.imageIds.length,
      0,
    );
    imageIds = selected.flatMap((item) => item.imageIds);
    ignoredIndexedFrames = indexedFrameCount - imageIds.length;

    // Files outside the selected series/dimensions are no longer needed for
    // decode. Release their one indexing reference before allocating pixels.
    for (const item of indexed) {
      if (
        !selectedBaseImageIds.has(item.baseImageId) &&
        wadouri.dataSetCacheManager.isLoaded(item.uri)
      ) {
        wadouri.dataSetCacheManager.unload(item.uri);
      }
    }
    const firstInspectionFailure = inspectionFailures.find(
      (failure): failure is string => Boolean(failure),
    );
    if (imageIds.length === 0) {
      const detail = firstInspectionFailure
        ? ` Parser detail: ${firstInspectionFailure}`
        : '';
      throw new Error(`No readable DICOM image instances were found.${detail}`);
    }

    let volume: VolumeData;
    try {
      volume = await loadCornerstoneImageIds(imageIds, options);
    } catch (error) {
      if (
        options.signal?.aborted ||
        (error instanceof DOMException && error.name === 'AbortError')
      ) {
        throw error;
      }
      if (rejectedFiles > 0) {
        throw new Error(
          rejectedFileContextMessage(
            error,
            rejectedFiles,
            files.length,
            firstInspectionFailure,
          ),
        );
      }
      throw error;
    }
    if (rejectedFiles > 0) {
      volume.warnings.push(
        `${rejectedFiles} selected files were ignored because they were not readable DICOM images.`,
      );
    }
    if (ignoredIndexedFrames > 0) {
      volume.warnings.push(
        `${ignoredIndexedFrames} indexed frames from other series or dimensions were ignored before pixel decode.`,
      );
    }
    return volume;
  } finally {
    // Keep teardown scoped so embedding this boilerplate does not invalidate
    // other Cornerstone local-file images owned by the host application.
    // The legacy dataset loader increments one cache reference per attempted
    // frame. Balance those references before releasing the indexing reference.
    for (const imageId of imageIds) {
      const uri = wadouri.parseImageId(imageId).url;
      if (wadouri.dataSetCacheManager.isLoaded(uri)) {
        wadouri.dataSetCacheManager.unload(uri);
      }
    }
    for (const baseImageId of baseImageIds) {
      const index = Number(baseImageId.slice('dicomfile:'.length));
      if (baseImageId.startsWith('dicomfile:') && Number.isInteger(index)) {
        const uri = wadouri.parseImageId(baseImageId).url;
        if (wadouri.dataSetCacheManager.isLoaded(uri)) {
          wadouri.dataSetCacheManager.unload(uri);
        }
        wadouri.fileManager.remove(index);
      }
    }
  }
}
