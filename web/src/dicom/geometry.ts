import type { Vec3Tuple } from '../types';

const EPSILON = 1e-6;

export interface SliceGeometry {
  imageId: string;
  sourceIndex: number;
  rows: number;
  columns: number;
  rowCosines?: Vec3Tuple;
  columnCosines?: Vec3Tuple;
  imagePositionPatient?: Vec3Tuple;
  rowPixelSpacing?: number;
  columnPixelSpacing?: number;
  spacingBetweenSlices?: number;
  sliceThickness?: number;
  sliceLocation?: number;
  usingDefaultValues?: boolean;
  instanceNumber?: number;
}

export interface PreparedGeometry<T extends SliceGeometry> {
  slices: T[];
  dimensions: Vec3Tuple;
  spacing: Vec3Tuple;
  origin: Vec3Tuple;
  direction: [number, number, number, number, number, number, number, number, number];
  warnings: string[];
  sortMethod: 'spatial' | 'slice-location' | 'instance' | 'input';
}

function dot(a: Vec3Tuple, b: Vec3Tuple): number {
  return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
}

function cross(a: Vec3Tuple, b: Vec3Tuple): Vec3Tuple {
  return [
    a[1] * b[2] - a[2] * b[1],
    a[2] * b[0] - a[0] * b[2],
    a[0] * b[1] - a[1] * b[0],
  ];
}

function normalize(vector: Vec3Tuple): Vec3Tuple | undefined {
  const length = Math.hypot(vector[0], vector[1], vector[2]);
  if (length < EPSILON) {
    return undefined;
  }
  return [vector[0] / length, vector[1] / length, vector[2] / length];
}

function median(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  if (sorted.length % 2 === 0) {
    return ((sorted[middle - 1] ?? 0) + (sorted[middle] ?? 0)) / 2;
  }
  return sorted[middle] ?? 0;
}

function isFinitePositive(value: number | undefined): value is number {
  return value !== undefined && Number.isFinite(value) && value > 0;
}

function nearlyParallel(a: Vec3Tuple, b: Vec3Tuple): boolean {
  const an = normalize(a);
  const bn = normalize(b);
  return Boolean(an && bn && dot(an, bn) > 0.999);
}

/**
 * Mirrors the desktop viewer's DICOM geometry rules: sort by IPP projected on
 * row×column, use median inter-slice distance, and fall back to instance order.
 */
export function prepareGeometry<T extends SliceGeometry>(input: T[]): PreparedGeometry<T> {
  if (input.length === 0) {
    throw new Error('The DICOM series contains no decodable image slices.');
  }

  const first = input[0];
  if (!first) {
    throw new Error('The DICOM series contains no decodable image slices.');
  }

  const incompatible = input.filter(
    (slice) => slice.rows !== first.rows || slice.columns !== first.columns,
  );
  if (incompatible.length > 0) {
    throw new Error('The selected DICOM series contains incompatible slice dimensions.');
  }

  const warnings: string[] = [];
  const orientationReference = input.find((slice) => {
    const candidateRow = slice.rowCosines && normalize(slice.rowCosines);
    const candidateColumn = slice.columnCosines && normalize(slice.columnCosines);
    return Boolean(
      candidateRow &&
        candidateColumn &&
        normalize(cross(candidateRow, candidateColumn)),
    );
  });
  const candidateRow = normalize(orientationReference?.rowCosines ?? [1, 0, 0]);
  const candidateColumn = normalize(orientationReference?.columnCosines ?? [0, 1, 0]);
  const candidateNormal =
    candidateRow && candidateColumn ? normalize(cross(candidateRow, candidateColumn)) : undefined;
  const hasValidOrientation = Boolean(
    orientationReference && candidateRow && candidateColumn && candidateNormal,
  );
  const row: Vec3Tuple = candidateRow ?? [1, 0, 0];
  const column: Vec3Tuple = candidateColumn ?? [0, 1, 0];
  const normal: Vec3Tuple =
    hasValidOrientation && candidateNormal ? candidateNormal : [0, 0, 1];

  if (!hasValidOrientation) {
    warnings.push('Image orientation is missing; an identity orientation was assumed.');
  } else {
    const mixedOrientations = input.some(
      (slice) =>
        !slice.rowCosines ||
        !slice.columnCosines ||
        !nearlyParallel(slice.rowCosines, row) ||
        !nearlyParallel(slice.columnCosines, column),
    );
    if (mixedOrientations) {
      warnings.push('Slice orientations vary or are missing within the series; gantry tilt is not resampled.');
    }
  }

  let slices: T[];
  let sortMethod: PreparedGeometry<T>['sortMethod'];
  const hasSpatialPositions = input.every((slice) => Boolean(slice.imagePositionPatient));
  const sliceLocations = input.map((slice) => slice.sliceLocation);
  const instanceNumbers = input.map((slice) => slice.instanceNumber);
  const hasSliceLocations =
    sliceLocations.every(
      (value) => value !== undefined && Number.isFinite(value),
    ) && new Set(sliceLocations).size > 1;
  const hasInstanceNumbers =
    instanceNumbers.every(
      (value) => value !== undefined && Number.isFinite(value),
    ) && new Set(instanceNumbers).size > 1;

  if (hasSpatialPositions && hasValidOrientation) {
    slices = [...input].sort((a, b) => {
      const aPosition = a.imagePositionPatient ?? [0, 0, 0];
      const bPosition = b.imagePositionPatient ?? [0, 0, 0];
      return (
        dot(aPosition, normal) - dot(bPosition, normal) ||
        a.sourceIndex - b.sourceIndex
      );
    });
    sortMethod = 'spatial';
  } else if (hasSliceLocations) {
    slices = [...input].sort(
      (a, b) =>
        (a.sliceLocation ?? Number.MAX_SAFE_INTEGER) -
        (b.sliceLocation ?? Number.MAX_SAFE_INTEGER),
    );
    sortMethod = 'slice-location';
    warnings.push('Spatial position/orientation is incomplete; Slice Location order was used.');
  } else if (hasInstanceNumbers) {
    slices = [...input].sort(
      (a, b) =>
        (a.instanceNumber ?? Number.MAX_SAFE_INTEGER) -
        (b.instanceNumber ?? Number.MAX_SAFE_INTEGER),
    );
    sortMethod = 'instance';
    warnings.push('Spatial position/orientation is incomplete; Instance Number order was used.');
  } else {
    slices = [...input].sort((a, b) => a.sourceIndex - b.sourceIndex);
    sortMethod = 'input';
    warnings.push('Spatial metadata is missing; browser input order was used.');
  }

  const spacingBetweenSlices = input.find((slice) =>
    isFinitePositive(slice.spacingBetweenSlices),
  )?.spacingBetweenSlices;
  const sliceThickness = input.find((slice) =>
    isFinitePositive(slice.sliceThickness),
  )?.sliceThickness;
  const metadataSliceSpacing = spacingBetweenSlices ?? sliceThickness;
  let sliceSpacing = metadataSliceSpacing ?? Number.NaN;
  if (sortMethod === 'spatial') {
    const projected = slices.map((slice) =>
      dot(slice.imagePositionPatient ?? [0, 0, 0], normal),
    );
    const distances = projected
      .slice(1)
      .map((position, index) => Math.abs(position - (projected[index] ?? position)))
      .filter((distance) => distance > EPSILON);

    if (distances.length > 0) {
      sliceSpacing = median(distances);
      if (distances.length !== projected.length - 1) {
        warnings.push('Duplicate slice positions were detected.');
      }
      const irregular = distances.some(
        (distance) => Math.abs(distance - sliceSpacing) > Math.max(0.01, sliceSpacing * 0.01),
      );
      if (irregular) {
        warnings.push(
          `Inter-slice spacing is irregular; the median ${sliceSpacing.toFixed(2)} mm spacing is used.`,
        );
      }
    } else if (isFinitePositive(metadataSliceSpacing)) {
      if (projected.length > 1) {
        warnings.push('Duplicate slice positions were detected; input frame order was preserved.');
      }
      warnings.push(
        spacingBetweenSlices
          ? 'Slice spacing could not be measured; Spacing Between Slices was used.'
          : 'Slice spacing could not be measured; Slice Thickness was used.',
      );
    } else {
      warnings.push('Slice spacing could not be measured from spatial positions.');
    }
  } else if (isFinitePositive(metadataSliceSpacing)) {
    warnings.push(
      spacingBetweenSlices
        ? 'Slice spacing is estimated from Spacing Between Slices.'
        : 'Slice spacing is estimated from Slice Thickness.',
    );
  }

  if (!isFinitePositive(sliceSpacing)) {
    sliceSpacing = 1;
    warnings.push('Slice spacing is missing; 1 mm was assumed.');
  }

  const validSpacings = input.filter(
    (slice) =>
      isFinitePositive(slice.columnPixelSpacing) && isFinitePositive(slice.rowPixelSpacing),
  );
  const measuredSpacings = validSpacings.filter((slice) => !slice.usingDefaultValues);
  const spacingCandidates = measuredSpacings.length > 0 ? measuredSpacings : validSpacings;
  const xSpacing =
    spacingCandidates.length > 0
      ? median(spacingCandidates.map((slice) => slice.columnPixelSpacing ?? 1))
      : 1;
  const ySpacing =
    spacingCandidates.length > 0
      ? median(spacingCandidates.map((slice) => slice.rowPixelSpacing ?? 1))
      : 1;
  if (spacingCandidates.length === 0) {
    warnings.push('Pixel spacing is missing; 1 mm in-plane values were assumed.');
  } else {
    if (validSpacings.length !== input.length) {
      warnings.push('Pixel spacing is incomplete on some slices; valid series values were used.');
    }
    if (measuredSpacings.length === 0) {
      warnings.push('Pixel spacing metadata uses loader defaults; verify the physical scale.');
    }
    const spacingVaries = spacingCandidates.some(
      (slice) =>
        Math.abs((slice.columnPixelSpacing ?? xSpacing) - xSpacing) >
          Math.max(0.001, xSpacing * 0.01) ||
        Math.abs((slice.rowPixelSpacing ?? ySpacing) - ySpacing) >
          Math.max(0.001, ySpacing * 0.01),
    );
    if (spacingVaries) {
      warnings.push(
        `In-plane pixel spacing varies; median ${xSpacing.toFixed(3)} × ${ySpacing.toFixed(3)} mm values are used.`,
      );
    }
  }

  if (slices.length < 100) {
    warnings.push(
      `Only ${slices.length} slices were loaded; around 100 or more usually produces a smoother volume.`,
    );
  }

  const xAxis = row ?? [1, 0, 0];
  const yAxis = column ?? [0, 1, 0];
  const origin = slices[0]?.imagePositionPatient ?? [0, 0, 0];

  return {
    slices,
    dimensions: [first.columns, first.rows, slices.length],
    spacing: [xSpacing, ySpacing, sliceSpacing],
    origin,
    direction: [
      xAxis[0],
      xAxis[1],
      xAxis[2],
      yAxis[0],
      yAxis[1],
      yAxis[2],
      normal[0],
      normal[1],
      normal[2],
    ],
    warnings,
    sortMethod,
  };
}

export function quantizeScalarSlices<T extends SliceGeometry & { pixels: ArrayLike<number> }>(
  slices: T[],
  dimensions: Vec3Tuple,
): { data: Uint8Array; dataRange: [number, number] } {
  const [width, height, depth] = dimensions;
  const pixelsPerSlice = width * height;
  if (slices.length !== depth) {
    throw new Error('The sorted slice count does not match the volume depth.');
  }

  let minimum = Number.POSITIVE_INFINITY;
  let maximum = Number.NEGATIVE_INFINITY;

  for (const slice of slices) {
    if (slice.pixels.length !== pixelsPerSlice) {
      throw new Error('A decoded DICOM frame has an unexpected pixel count.');
    }
    for (let index = 0; index < pixelsPerSlice; index += 1) {
      const value = Number(slice.pixels[index]);
      if (Number.isFinite(value)) {
        minimum = Math.min(minimum, value);
        maximum = Math.max(maximum, value);
      }
    }
  }

  if (!Number.isFinite(minimum) || !Number.isFinite(maximum)) {
    throw new Error('The decoded DICOM pixels contain no finite scalar values.');
  }

  if (maximum <= minimum) {
    maximum = minimum + 1;
  }

  const data = new Uint8Array(width * height * depth);
  const scale = 255 / (maximum - minimum);
  let outputIndex = 0;
  for (const slice of slices) {
    for (let index = 0; index < pixelsPerSlice; index += 1) {
      const value = Number(slice.pixels[index]);
      const normalized = Number.isFinite(value) ? (value - minimum) * scale : 0;
      data[outputIndex] = Math.max(0, Math.min(255, Math.round(normalized)));
      outputIndex += 1;
    }
  }

  return { data, dataRange: [minimum, maximum] };
}

interface AsyncQuantizeOptions {
  signal?: AbortSignal;
  onProgress?: (completedSlicePasses: number, totalSlicePasses: number) => void;
  yieldEverySlices?: number;
}

function throwIfQuantizationAborted(signal?: AbortSignal): void {
  if (signal?.aborted) {
    throw new DOMException('Volume assembly was cancelled.', 'AbortError');
  }
}

function yieldToBrowser(): Promise<void> {
  return new Promise((resolve) => globalThis.setTimeout(resolve, 0));
}

/**
 * Browser-friendly two-pass packing. It yields between small slice batches so
 * the progress overlay can repaint and cancellation remains responsive on a
 * 512×512×100 stack.
 */
export async function quantizeScalarSlicesAsync<
  T extends SliceGeometry & { pixels: ArrayLike<number> },
>(
  slices: T[],
  dimensions: Vec3Tuple,
  options: AsyncQuantizeOptions = {},
): Promise<{ data: Uint8Array; dataRange: [number, number] }> {
  const [width, height, depth] = dimensions;
  const pixelsPerSlice = width * height;
  const voxelCount = pixelsPerSlice * depth;
  if (slices.length !== depth) {
    throw new Error('The sorted slice count does not match the volume depth.');
  }
  if (voxelCount > 384 * 1024 * 1024) {
    throw new Error('The volume exceeds the boilerplate 384 MiB scalar texture budget.');
  }

  const yieldEvery = Math.max(1, options.yieldEverySlices ?? 4);
  const totalSlicePasses = depth * 2;
  let minimum = Number.POSITIVE_INFINITY;
  let maximum = Number.NEGATIVE_INFINITY;

  for (let z = 0; z < depth; z += 1) {
    throwIfQuantizationAborted(options.signal);
    const slice = slices[z];
    if (!slice || slice.pixels.length !== pixelsPerSlice) {
      throw new Error('A decoded DICOM frame has an unexpected pixel count.');
    }
    for (let index = 0; index < pixelsPerSlice; index += 1) {
      const value = Number(slice.pixels[index]);
      if (Number.isFinite(value)) {
        minimum = Math.min(minimum, value);
        maximum = Math.max(maximum, value);
      }
    }
    options.onProgress?.(z + 1, totalSlicePasses);
    if ((z + 1) % yieldEvery === 0) {
      await yieldToBrowser();
    }
  }

  if (!Number.isFinite(minimum) || !Number.isFinite(maximum)) {
    throw new Error('The decoded DICOM pixels contain no finite scalar values.');
  }
  if (maximum <= minimum) {
    maximum = minimum + 1;
  }

  const data = new Uint8Array(voxelCount);
  const scale = 255 / (maximum - minimum);
  let outputIndex = 0;
  for (let z = 0; z < depth; z += 1) {
    throwIfQuantizationAborted(options.signal);
    const slice = slices[z];
    if (!slice) {
      throw new Error('A decoded DICOM frame is missing during volume assembly.');
    }
    for (let index = 0; index < pixelsPerSlice; index += 1) {
      const value = Number(slice.pixels[index]);
      const normalized = Number.isFinite(value) ? (value - minimum) * scale : 0;
      data[outputIndex] = Math.max(0, Math.min(255, Math.round(normalized)));
      outputIndex += 1;
    }
    options.onProgress?.(depth + z + 1, totalSlicePasses);
    if ((z + 1) % yieldEvery === 0) {
      await yieldToBrowser();
    }
  }

  throwIfQuantizationAborted(options.signal);
  return { data, dataRange: [minimum, maximum] };
}
