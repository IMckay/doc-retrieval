"""Export extraction metrics as a JSON summary file."""

import json
from collections import Counter
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from doc_retrieval.converter.llm_formatter import FormattedPage


def write_metrics(
    output_path: Path,
    pages: list[FormattedPage],
    errors: Sequence[tuple[str, str, str]],
    skipped: list[str],
    skipped_categories: list[str],
    timings: list,
    pipeline_start: float,
    pipeline_end: float,
    discovery_duration: float,
    output_duration: float,
    base_url: str,
    cache_hits: int = 0,
    cache_misses: int = 0,
) -> Path:
    """Write extraction metrics to a JSON file next to the output.

    Returns the path to the written metrics file.
    """
    total_time = pipeline_end - pipeline_start

    # Quality scores
    scores = [p.quality_score for p in pages]
    avg_score = sum(scores) // len(scores) if scores else 0

    # Content sizes
    page_sizes = [len(p.markdown) for p in pages]
    total_output = sum(page_sizes)

    # Extraction methods
    method_counts: Counter[str] = Counter()
    for t in timings:
        if hasattr(t, "extraction_method") and t.extraction_method:
            method_counts[t.extraction_method] += 1

    # Error categories
    error_categories: Counter[str] = Counter()
    for _url, _msg, cat in errors:
        cat_val = cat.value if hasattr(cat, "value") else str(cat)
        error_categories[cat_val] += 1

    # Timing stats
    done_timings = [t for t in timings if hasattr(t, "status") and t.status.value == "done"]
    fetch_times = [t.fetch_duration for t in done_timings if t.fetch_duration]
    extract_times = [t.extract_duration for t in done_timings if t.extract_duration]
    convert_times = [t.convert_duration for t in done_timings if t.convert_duration]

    def _timing_stats(times: list[float]) -> dict:
        if not times:
            return {"count": 0}
        return {
            "count": len(times),
            "avg": round(sum(times) / len(times), 3),
            "total": round(sum(times), 3),
            "min": round(min(times), 3),
            "max": round(max(times), 3),
        }

    metrics = {
        "base_url": base_url,
        "extracted_at": datetime.now().isoformat(),
        "total_duration_seconds": round(total_time, 2),
        "pages": {
            "total_discovered": len(pages) + len(errors) + len(skipped) + len(skipped_categories),
            "extracted": len(pages),
            "errors": len(errors),
            "skipped": len(skipped),
            "skipped_categories": len(skipped_categories),
        },
        "output": {
            "total_bytes": total_output,
            "avg_page_bytes": total_output // len(pages) if pages else 0,
        },
        "quality": {
            "avg_score": avg_score,
            "low": sum(1 for s in scores if s < 30),
            "medium": sum(1 for s in scores if 30 <= s < 60),
            "high": sum(1 for s in scores if s >= 60),
        },
        "timing": {
            "discovery_seconds": round(discovery_duration, 3),
            "output_seconds": round(output_duration, 3),
            "fetch": _timing_stats(fetch_times),
            "extract": _timing_stats(extract_times),
            "convert": _timing_stats(convert_times),
        },
        "extraction_methods": dict(method_counts.most_common()),
        "error_categories": dict(error_categories.most_common()),
        "cache": {
            "hits": cache_hits,
            "misses": cache_misses,
        },
    }

    # Write alongside the output
    if output_path.is_dir():
        metrics_path = output_path / "metrics.json"
    else:
        metrics_path = output_path.parent / "metrics.json"

    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return metrics_path
