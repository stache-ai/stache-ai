# Regression Metrics Comparison Report

**Generated**: 2026-01-11T12:29:08.528090

**Baseline**: 2026-01-11T18:08:38.175489+00:00
**Current**: 2026-01-11T18:28:23.985144+00:00

## Executive Summary

✅ **NO REGRESSIONS DETECTED**

All performance and accuracy metrics are within acceptable thresholds.

## Performance Metrics

| File | Loader | Baseline (ms) | Current (ms) | Change | Status |
|------|--------|---------------|-------------|--------|--------|
| 01-text-based.pdf | stache-ai-ocr | 32.05 | 32.20 | +0.5% | ✓ OK |
| 01-text-based.pdf | stache-tools-ocr | 3.30 | 3.08 | -6.7% | ✓ OK |
| 02-empty.pdf | stache-ai-ocr | 1.36 | 1.32 | -2.9% | ✓ OK |
| 02-empty.pdf | stache-tools-ocr | 0.85 | 0.87 | +2.4% | ✓ OK |
| 03-single-page.pdf | stache-ai-ocr | 3.22 | 3.11 | -3.4% | ✓ OK |
| 03-single-page.pdf | stache-tools-ocr | 0.80 | 0.77 | -3.8% | ✓ OK |
| 04-scanned.pdf | stache-ai-ocr | 1.12 | 1.12 | +0.0% | ✓ OK |
| 04-scanned.pdf | stache-tools-ocr | 0.75 | 0.72 | -4.0% | ✓ OK |
| 05-large-multipage.pdf | stache-ai-ocr | 111.90 | 115.97 | +3.6% | ✓ OK |
| 05-large-multipage.pdf | stache-tools-ocr | 8.63 | 8.72 | +1.0% | ✓ OK |
| 06-hybrid.pdf | stache-ai-ocr | 6.01 | 6.05 | +0.7% | ✓ OK |
| 06-hybrid.pdf | stache-tools-ocr | 1.10 | 1.07 | -2.7% | ✓ OK |

## Accuracy Metrics (Text Length)

| File | Loader | Baseline (chars) | Current (chars) | Status |
|------|--------|------------------|-----------------|--------|
| 01-text-based.pdf | stache-ai-ocr | 928 | 928 | ✓ Match |
| 01-text-based.pdf | stache-tools-ocr | 929 | 929 | ✓ Match |
| 02-empty.pdf | stache-ai-ocr | 0 | 0 | ✓ Match |
| 02-empty.pdf | stache-tools-ocr | 0 | 0 | ✓ Match |
| 03-single-page.pdf | stache-ai-ocr | 156 | 156 | ✓ Match |
| 03-single-page.pdf | stache-tools-ocr | 157 | 157 | ✓ Match |
| 04-scanned.pdf | stache-ai-ocr | 0 | 0 | ✓ Match |
| 04-scanned.pdf | stache-tools-ocr | 0 | 0 | ✓ Match |
| 05-large-multipage.pdf | stache-ai-ocr | 6276 | 6276 | ✓ Match |
| 05-large-multipage.pdf | stache-tools-ocr | 6287 | 6287 | ✓ Match |
| 06-hybrid.pdf | stache-ai-ocr | 372 | 372 | ✓ Match |
| 06-hybrid.pdf | stache-tools-ocr | 373 | 373 | ✓ Match |

## Detailed Analysis

### 01-text-based.pdf

**stache-ai-ocr**:
- Time: 32.05ms → 32.20ms (+0.5%)
- Text length: 928 → 928 chars

**stache-tools-ocr**:
- Time: 3.30ms → 3.08ms (-6.7%)
- Text length: 929 → 929 chars
- OCR used: False → False

### 02-empty.pdf

**stache-ai-ocr**:
- Time: 1.36ms → 1.32ms (-2.9%)
- Text length: 0 → 0 chars

**stache-tools-ocr**:
- Time: 0.85ms → 0.87ms (+2.4%)
- Text length: 0 → 0 chars
- OCR used: False → False

### 03-single-page.pdf

**stache-ai-ocr**:
- Time: 3.22ms → 3.11ms (-3.4%)
- Text length: 156 → 156 chars

**stache-tools-ocr**:
- Time: 0.80ms → 0.77ms (-3.8%)
- Text length: 157 → 157 chars
- OCR used: False → False

### 04-scanned.pdf

**stache-ai-ocr**:
- Time: 1.12ms → 1.12ms (+0.0%)
- Text length: 0 → 0 chars

**stache-tools-ocr**:
- Time: 0.75ms → 0.72ms (-4.0%)
- Text length: 0 → 0 chars
- OCR used: False → False

### 05-large-multipage.pdf

**stache-ai-ocr**:
- Time: 111.90ms → 115.97ms (+3.6%)
- Text length: 6276 → 6276 chars

**stache-tools-ocr**:
- Time: 8.63ms → 8.72ms (+1.0%)
- Text length: 6287 → 6287 chars
- OCR used: False → False

### 06-hybrid.pdf

**stache-ai-ocr**:
- Time: 6.01ms → 6.05ms (+0.7%)
- Text length: 372 → 372 chars

**stache-tools-ocr**:
- Time: 1.10ms → 1.07ms (-2.7%)
- Text length: 373 → 373 chars
- OCR used: False → False

## Conclusions

✅ **All checks passed** - No performance or accuracy regressions detected.

### Key Findings:
- Performance is stable across all test files (±30% threshold)
- Text extraction accuracy matches baseline
- OCR heuristic behavior is consistent
- Enhanced implementation maintains backward compatibility

### Thresholds Used:
- Performance regression threshold: 30% increase in execution time
- Accuracy regression threshold: Text length mismatch (exact match expected)
