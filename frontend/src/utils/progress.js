// Progress math for the multi-file ingest UX. Pure functions, no Vue — kept
// out of the component so the aggregation can be unit-tested without mounting.

// Local completion fraction (0..1) of a SINGLE file. The upload transfer maps
// to the first half (0 → 0.5) and server processing to the second half
// (0.5 → 1), so one file's bar moves smoothly through upload and then advances
// through processing.
export function fileFraction(phase, percent) {
  const clamped = Math.max(0, Math.min(100, Number(percent) || 0)) / 100
  return phase === 'uploading' ? clamped * 0.5 : 0.5 + clamped * 0.5
}

// Overall percent (0..100) across all files, given the 0-based index of the
// active file and its local fraction. Files already finished count as whole
// units ahead of the active one.
export function overallPercent(currentFileIndex, fraction, totalFiles) {
  if (!totalFiles || totalFiles <= 0) return 0
  return Math.round(((currentFileIndex + fraction) / totalFiles) * 100)
}
