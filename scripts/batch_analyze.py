"""
Batch runner for TikTok video ad analysis.

Usage:
  python batch_analyze.py --input-dir outputs --market jp --output batch_report
"""

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def find_optional(path: Path, names: List[str]) -> Optional[Path]:
    for name in names:
        candidate = path / name
        if candidate.exists():
            return candidate
    return None


def safe_name(path: Path) -> str:
    parts = [part for part in path.parts[-3:] if part not in {":", "\\"}]
    name = "_".join(parts).replace(" ", "_")
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in name)[:120] or "item"


def summarize_report(report: Dict[str, Any], report_path: Path) -> Dict[str, Any]:
    title_scores = report.get("title_scores", {}) if isinstance(report.get("title_scores"), dict) else {}
    top_titles = title_scores.get("top5") or []
    execution = report.get("execution_summary", {}) if isinstance(report.get("execution_summary"), dict) else {}
    weakest = execution.get("weakest_dimensions") or []
    return {
        "product_name": report.get("product_name", ""),
        "market": report.get("market", ""),
        "total_score": report.get("total_score", 0),
        "summary": report.get("summary", ""),
        "confidence": report.get("confidence", 0),
        "localization_status": (report.get("localization") or {}).get("status", ""),
        "decision": execution.get("decision", ""),
        "top_title": top_titles[0].get("title", "") if top_titles else "",
        "top_title_score": top_titles[0].get("score", "") if top_titles else "",
        "weakest": " / ".join(str(item.get("dimension", "")) for item in weakest),
        "report_json": str(report_path),
        "report_md": str(report_path.with_suffix(".md")),
    }


def run_item(
    extraction_json: Path,
    output_root: Path,
    market: str,
    notes_name: str,
    landing_name: str,
    performance_json: Optional[Path],
) -> Dict[str, Any]:
    script = Path(__file__).with_name("analyze_video.py")
    item_output = output_root / safe_name(extraction_json.parent)
    item_output.mkdir(parents=True, exist_ok=True)
    notes_path = find_optional(extraction_json.parent, [notes_name, "analysis_notes.json"])
    landing_path = find_optional(extraction_json.parent, [landing_name, "landing_page.json"])
    cmd = [
        sys.executable,
        str(script),
        "--extraction-json",
        str(extraction_json),
        "--market",
        market,
        "--output",
        str(item_output),
    ]
    if notes_path:
        cmd.extend(["--notes", str(notes_path)])
    if landing_path:
        cmd.extend(["--landing-page-json", str(landing_path)])
    if performance_json:
        cmd.extend(["--performance-json", str(performance_json)])

    subprocess.run(cmd, check=True)
    report_path = item_output / "report.json"
    return summarize_report(load_json(report_path), report_path)


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch analyze multiple extraction_result.json files")
    parser.add_argument("--input-dir", required=True, help="递归搜索 extraction_result.json 的目录")
    parser.add_argument("--market", default="jp", help="目标市场：jp / th / id")
    parser.add_argument("--output", default="batch_report", help="批量报告输出目录")
    parser.add_argument("--notes-name", default="notes.json", help="每个素材目录里的 notes 文件名")
    parser.add_argument("--landing-name", default="landing_page.json", help="每个素材目录里的 landing page 文件名")
    parser.add_argument("--performance-json", default=None, help="可选，统一使用的历史投放表现 JSON")
    parser.add_argument("--limit", type=int, default=0, help="最多分析多少条，0 表示不限制")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output_root = Path(args.output)
    output_root.mkdir(parents=True, exist_ok=True)
    performance_json = Path(args.performance_json) if args.performance_json else None
    extraction_files = sorted(input_dir.rglob("extraction_result.json"))
    if args.limit > 0:
        extraction_files = extraction_files[: args.limit]

    rows: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []
    for extraction_json in extraction_files:
        try:
            rows.append(run_item(
                extraction_json=extraction_json,
                output_root=output_root,
                market=args.market,
                notes_name=args.notes_name,
                landing_name=args.landing_name,
                performance_json=performance_json,
            ))
        except Exception as exc:
            errors.append({"extraction_json": str(extraction_json), "error": str(exc)})

    rows = sorted(rows, key=lambda item: (int(item.get("total_score") or 0), int(item.get("confidence") or 0)), reverse=True)
    summary = {
        "status": "ok" if not errors else "partial",
        "input_dir": str(input_dir),
        "market": args.market,
        "items_analyzed": len(rows),
        "errors": errors,
        "rows": rows,
    }
    summary_json = output_root / "batch_summary.json"
    summary_csv = output_root / "batch_summary.csv"
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(summary_csv, rows)
    print(json.dumps({
        "status": summary["status"],
        "items_analyzed": len(rows),
        "errors": len(errors),
        "summary_json": str(summary_json),
        "summary_csv": str(summary_csv),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
