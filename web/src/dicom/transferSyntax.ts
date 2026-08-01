import isVideoTransferSyntax from '@cornerstonejs/metadata/utilities/isVideoTransferSyntax';

/** Reject temporal video bitstreams before treating NumberOfFrames as Z depth. */
export function assertVolumeTransferSyntax(transferSyntaxUid: string | undefined): void {
  if (transferSyntaxUid && isVideoTransferSyntax(transferSyntaxUid)) {
    throw new Error(
      'This DICOM stores MPEG/H.264/H.265 cine video frames, not independently decodable spatial slices. Video DICOM is not supported by the 3D volume renderer.',
    );
  }
}
