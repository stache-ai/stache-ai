#!/usr/bin/env python3
"""
Baseline metrics collection for stache-ai-ocr and stache-tools-ocr.

Runs both OCR loaders against the test PDF corpus and collects performance metrics.
"""

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Setup paths
SCRIPT_DIR = Path(__file__).parent
TEST_DIR = SCRIPT_DIR.parent
FIXTURES_DIR = TEST_DIR / "fixtures" / "pdfs"
OUTPUT_FILE = TEST_DIR / "baseline-metrics.json"

# Add stache-ai-ocr to path
SRC_DIR = TEST_DIR.parent / "src"
sys.path.insert(0, str(SRC_DIR))

# Add stache-tools-ocr to path
STACHE_TOOLS_OCR_SRC = Path("/mnt/devbuntu/dev/stache-tools-ocr/src")
sys.path.insert(0, str(STACHE_TOOLS_OCR_SRC))

# Import loaders
from stache_ai_ocr.loaders import OcrPdfLoader as AiOcrLoader
from stache_tools_ocr.loaders import OcrPdfLoader as ToolsOcrLoader

def measure_performance(loader_func, *args, **kwargs):
    """Measure execution time and capture result/errors."""
    start = time.perf_counter()
    try:
        result = loader_func(*args, **kwargs)
        elapsed_ms = (time.perf_counter() - start) * 1000
        return {
            "time_ms": round(elapsed_ms, 2),
            "result": result,
            "success": True,
            "error": None
        }
    except Exception as e:
        elapsed_ms = (time.perf_counter() - start) * 1000
        return {
            "time_ms": round(elapsed_ms, 2),
            "result": None,
            "success": False,
            "error": str(e)
        }

def collect_metrics():
    """Collect baseline metrics for all PDF test files."""

    if not FIXTURES_DIR.exists():
        print(f"ERROR: Fixtures directory not found: {FIXTURES_DIR}")
        sys.exit(1)

    # Find all PDFs
    pdf_files = sorted(FIXTURES_DIR.glob("*.pdf"))

    if not pdf_files:
        print(f"ERROR: No PDF files found in {FIXTURES_DIR}")
        sys.exit(1)

    print(f"Found {len(pdf_files)} PDF files to test")

    # Initialize loaders
    ai_loader = AiOcrLoader()
    tools_loader = ToolsOcrLoader()

    results = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "test_files": []
    }

    # Process each PDF
    for pdf_path in pdf_files:
        filename = pdf_path.name
        print(f"\nProcessing: {filename}")

        # Test stache-ai-ocr
        print(f"  Testing stache-ai-ocr...", end="", flush=True)
        ai_result = measure_performance(ai_loader.load, str(pdf_path))
        print(f" ({ai_result['time_ms']}ms)")

        # Test stache-tools-ocr
        print(f"  Testing stache-tools-ocr...", end="", flush=True)
        with open(pdf_path, 'rb') as f:
            tools_result = measure_performance(tools_loader.load, f, filename)
        print(f" ({tools_result['time_ms']}ms)")

        # Build metrics for this file
        file_metrics = {
            "filename": filename,
            "stache_ai_ocr": {
                "time_ms": ai_result["time_ms"],
                "text_length": len(ai_result["result"]) if ai_result["success"] and ai_result["result"] else 0,
                "success": ai_result["success"],
                "error": ai_result["error"]
            },
            "stache_tools_ocr": {
                "time_ms": tools_result["time_ms"],
                "text_length": 0,
                "ocr_used": False,
                "success": tools_result["success"],
                "error": tools_result["error"]
            }
        }

        # Extract additional metadata from stache-tools-ocr if successful
        if tools_result["success"] and tools_result["result"]:
            loaded_doc = tools_result["result"]
            file_metrics["stache_tools_ocr"]["text_length"] = len(loaded_doc.text)
            if loaded_doc.metadata:
                file_metrics["stache_tools_ocr"]["ocr_used"] = loaded_doc.metadata.get("ocr_used", False)

        results["test_files"].append(file_metrics)

    # Write results to JSON
    OUTPUT_FILE.write_text(json.dumps(results, indent=2))
    print(f"\n\nMetrics saved to: {OUTPUT_FILE}")

    # Print summary
    print("\n" + "="*80)
    print("BASELINE METRICS SUMMARY")
    print("="*80)
    print(f"Timestamp: {results['timestamp']}")
    print(f"Python: {results['python_version']}")
    print(f"Files tested: {len(results['test_files'])}")
    print("\n" + "-"*80)

    for file_metrics in results["test_files"]:
        print(f"\n{file_metrics['filename']}:")
        ai = file_metrics["stache_ai_ocr"]
        tools = file_metrics["stache_tools_ocr"]

        print(f"  stache-ai-ocr:")
        print(f"    Status: {'✓ SUCCESS' if ai['success'] else '✗ FAILED'}")
        print(f"    Time: {ai['time_ms']}ms")
        print(f"    Text length: {ai['text_length']} chars")
        if ai["error"]:
            print(f"    Error: {ai['error']}")

        print(f"  stache-tools-ocr:")
        print(f"    Status: {'✓ SUCCESS' if tools['success'] else '✗ FAILED'}")
        print(f"    Time: {tools['time_ms']}ms")
        print(f"    Text length: {tools['text_length']} chars")
        print(f"    OCR used: {tools['ocr_used']}")
        if tools["error"]:
            print(f"    Error: {tools['error']}")

    print("\n" + "="*80)
    return results

if __name__ == "__main__":
    try:
        collect_metrics()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
