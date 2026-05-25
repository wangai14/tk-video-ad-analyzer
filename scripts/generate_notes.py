"""
Semi-automatic notes draft generator for TikTok video ad analysis.

Usage:
  python generate_notes.py --extraction-json output/extraction_result.json --output notes.json

Optional:
  --landing-page-json landing_page.json
  --transcript transcript.txt
  --transcribe
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional


CATEGORY_KEYWORDS = {
    "fashion": ["内衣", "bra", "bra", "shirt", "dress", "fashion", "wear", "wire", "wireless", "着痩せ", "透气", "舒适", "tight"],
    "beauty": ["beauty", "makeup", "skincare", "lip", "eye", "glow", "肌肤", "化妆", "护肤", "唇", "眼影"],
    "home": ["home", "house", "kitchen", "clean", "storage", "organize", "收纳", "清洁", "厨房", "家务"],
    "food": ["food", "snack", "drink", "tea", "coffee", "eat", "맛", "口感", "健康", "营养"],
}

PAIN_KEYWORDS = {
    "fashion": [("締めつけ", "被勒得难受"), ("tight", "太紧"), ("hot", "闷热"), ("sweat", "不透气"), ("line", "显痕"), ("wire", "钢圈不舒服")],
    "beauty": [("dry", "干"), ("oil", "出油"), ("smudge", "晕妆"), ("cakey", "卡粉"), ("slow", "步骤太多")],
    "home": [("mess", "乱"), ("clutter", "收纳难"), ("dirty", "难清洁"), ("waste", "浪费时间"), ("heavy", "不方便")],
    "food": [("hungry", "容易饿"), ("sweet", "太甜"), ("bitter", "口感不稳"), ("health", "吃得不安心"), ("snack", "零食选择少")],
}

BENEFIT_KEYWORDS = {
    "fashion": [("comfortable", "更舒适"), ("breathable", "更透气"), ("smooth", "更顺滑"), ("support", "有支撑"), ("hidden", "不易显痕")],
    "beauty": [("quick", "更省时"), ("easy", "更容易"), ("glow", "更自然"), ("blend", "更好晕染"), ("clean", "更干净")],
    "home": [("easy", "更方便"), ("save time", "更省时间"), ("organized", "更整洁"), ("simple", "更好用"), ("practical", "更实用")],
    "food": [("delicious", "更好吃"), ("healthy", "更安心"), ("easy", "更方便"), ("tasty", "更好入口"), ("satisfy", "更有满足感")],
}

CTA_KEYWORDS = [
    "click",
    "check",
    "profile",
    "shop",
    "buy",
    "learn more",
    "ดูเพิ่มเติม",
    "Lihat Selengkapnya",
    "今すぐ",
    "詳細",
    "プロフィール",
]


def load_json(path: Optional[Path]) -> Dict[str, Any]:
    if not path:
        return {}
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def load_text(path: Optional[Path]) -> str:
    if not path:
        return ""
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    return path.read_text(encoding="utf-8-sig", errors="replace")


def collect_text(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (int, float)):
        return [str(value)]
    if isinstance(value, list):
        result: List[str] = []
        for item in value:
            result.extend(collect_text(item))
        return result
    if isinstance(value, dict):
        result = []
        preferred_keys = ["text", "transcript", "ocr", "caption", "subtitle", "texts", "items", "frames", "segments"]
        for key in preferred_keys:
            if key in value:
                result.extend(collect_text(value[key]))
        return result
    return []


def load_ocr_text(path: Optional[Path]) -> str:
    if not path:
        return ""
    raw = load_json(path)
    return normalize_text(" ".join(collect_text(raw)))


def unique_keep_order(items: List[str]) -> List[str]:
    seen = set()
    result = []
    for item in items:
        clean = item.strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        result.append(clean)
    return result


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def detect_category(text: str, landing: Dict[str, Any]) -> str:
    blob = " ".join([
        text,
        str(landing.get("title") or ""),
        str(landing.get("meta", {}).get("title") or ""),
        str(landing.get("product_name_guess") or ""),
    ]).lower()
    scores = {}
    for category, keywords in CATEGORY_KEYWORDS.items():
        scores[category] = sum(1 for kw in keywords if kw.lower() in blob)
    return max(scores.items(), key=lambda item: item[1])[0] if scores and max(scores.values()) > 0 else "general"


def detect_language(text: str) -> str:
    if re.search(r"[\u3040-\u30ff]", text):
        return "jp"
    if re.search(r"[\u0E00-\u0E7F]", text):
        return "th"
    if re.search(r"[가-힣]", text):
        return "kr"
    if re.search(r"[A-Za-z]", text):
        return "en"
    return "zh"


def detect_currency(landing: Dict[str, Any], fallback_market: str) -> str:
    text = " ".join([
        str(landing.get("text_excerpt") or ""),
        " ".join(landing.get("prices") or []),
        " ".join(landing.get("discounts") or []),
    ])
    if "¥" in text or "円" in text:
        return "JPY"
    if "฿" in text:
        return "THB"
    if "Rp" in text:
        return "IDR"
    if fallback_market == "jp":
        return "JPY"
    if fallback_market == "th":
        return "THB"
    if fallback_market == "id":
        return "IDR"
    return "CNY"


def detect_product_name(extraction: Dict[str, Any], landing: Dict[str, Any]) -> str:
    landing_guess = str(landing.get("product_name_guess") or "").strip()
    if landing_guess:
        return landing_guess
    if landing.get("json_ld_product_names"):
        return str(landing["json_ld_product_names"][0]).strip()
    title = str(landing.get("title") or landing.get("meta", {}).get("title") or "").strip()
    if title:
        return re.split(r"[-|｜|·]", title)[0].strip()
    video_path = Path(str(extraction.get("video_path") or "video")).stem
    return video_path.replace("_", " ").strip() or "商品"


def detect_keywords(text: str, keyword_map: List[tuple]) -> List[str]:
    found = []
    blob = text.lower()
    for needle, label in keyword_map:
        if needle.lower() in blob:
            found.append(label)
    return unique_keep_order(found)


def infer_pain_points(text: str, category: str) -> List[str]:
    matches = detect_keywords(text, PAIN_KEYWORDS.get(category, []))
    if matches:
        return matches[:3]
    if category == "fashion":
        return ["普通商品穿着不够舒服", "容易闷热或显痕"]
    if category == "beauty":
        return ["步骤太多", "上手麻烦"]
    if category == "home":
        return ["处理起来费时间", "不够方便"]
    if category == "food":
        return ["想吃得更安心", "选择不够简单"]
    return ["有一个用户会在意的痛点"]


def infer_selling_points(text: str, category: str) -> List[str]:
    matches = detect_keywords(text, BENEFIT_KEYWORDS.get(category, []))
    if matches:
        return matches[:3]
    if category == "fashion":
        return ["更舒适", "更透气", "更自然"]
    if category == "beauty":
        return ["更省时", "更容易上手"]
    if category == "home":
        return ["更方便", "更实用"]
    if category == "food":
        return ["更好吃", "更方便"]
    return ["更容易理解", "更值得点击"]


def infer_proof(text: str) -> List[str]:
    candidates = [
        ("review", "レビュー/评论"),
        ("testimonial", "用户评价"),
        ("before", "前后对比"),
        ("after", "前后对比"),
        ("demo", "真人演示"),
        ("使用", "使用演示"),
        ("test", "测试"),
        ("comment", "评论截图"),
    ]
    return unique_keep_order([label for needle, label in candidates if needle.lower() in text.lower()])[:3] or ["真人演示"]


def infer_hook(text: str, product_name: str, pain_points: List[str]) -> Dict[str, Any]:
    blob = text.lower()
    hook_type = "benefit"
    detail = ""
    if "?" in text or "why" in blob or "なぜ" in text or "どう" in text:
        hook_type = "curiosity"
        detail = "以问题或信息差开场"
    if any(word in blob for word in ["still", "まだ", "yet", "我慢", "买前", "before"]):
        hook_type = "pain"
        detail = "以用户现状或痛点开场"
    if any(word in blob for word in ["review", "前后", "对比", "compare", "versus"]):
        hook_type = "contrast"
        detail = "以前后对比制造停手感"
    if any(word in blob for word in ["discount", "off", "sale", "promo", "price", "ราคา", "โปร"]):
        hook_type = "offer"
        detail = "先报价格/优惠再引导点击"
    if not detail:
        detail = f"围绕 {pain_points[0] if pain_points else product_name} 进行开场"
    return {"present": True, "type": hook_type, "detail": detail}


def infer_cta(text: str) -> Dict[str, Any]:
    lower = text.lower()
    hits = [kw for kw in CTA_KEYWORDS if kw.lower() in lower]
    return {
        "present": bool(hits),
        "detail": hits[0] if hits else "请在文案中补充明确 CTA",
    }


def infer_localization_signals(text: str, landing: Dict[str, Any], market: str) -> Dict[str, Any]:
    currency = detect_currency(landing, market)
    language = detect_language(text)
    return {
        "model_region": market if market in {"jp", "th", "id"} else "",
        "music_style": market if market in {"jp", "th", "id"} else "",
        "currency": currency,
        "needs_recut": False,
        "notes": f"语言推测：{language}",
    }


def ensure_list(values: List[str]) -> List[str]:
    return unique_keep_order([value for value in values if value])


def maybe_transcribe(audio_file: Optional[str], model: str = "base") -> str:
    if not audio_file:
        return ""
    whisper_cmd = shutil.which("whisper")
    if not whisper_cmd:
        return ""
    temp_dir = Path(audio_file).parent / "_transcript"
    temp_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [whisper_cmd, audio_file, "--model", model, "--output_format", "txt", "--output_dir", str(temp_dir)],
        capture_output=True,
        check=False,
    )
    candidates = sorted(temp_dir.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        return ""
    return candidates[0].read_text(encoding="utf-8", errors="replace")


def build_notes(
    extraction: Dict[str, Any],
    landing: Dict[str, Any],
    transcript_text: str,
    ocr_text: str,
    market: str,
) -> Dict[str, Any]:
    merged_text = normalize_text(" ".join(filter(None, [
        transcript_text,
        ocr_text,
        str(landing.get("text_excerpt") or ""),
        " ".join(landing.get("prices") or []),
        " ".join(landing.get("discounts") or []),
        " ".join(landing.get("ctas") or []),
        " ".join(landing.get("guarantees") or []),
        " ".join(landing.get("image_alts") or []),
        " ".join(item.get("text", "") for item in landing.get("links", []) if isinstance(item, dict)),
    ])))
    category = detect_category(merged_text, landing)
    product_name = detect_product_name(extraction, landing)
    pain_points = infer_pain_points(merged_text, category)
    selling_points = infer_selling_points(merged_text, category)
    proof = infer_proof(merged_text)
    hook = infer_hook(merged_text, product_name, pain_points)
    cta = infer_cta(merged_text)
    offer_detail = " / ".join(unique_keep_order([item for item in (landing.get("discounts") or []) if item])) or ""
    prices = landing.get("prices") or []
    price_sale = None
    price_original = None
    if prices:
        price_sale = prices[0]
        if len(prices) > 1:
            price_original = prices[1]
    language = detect_language(transcript_text or merged_text)
    notes = {
        "product_name": product_name,
        "category": category,
        "target_audience": "",
        "pain_points": pain_points,
        "hook": hook,
        "selling_points": selling_points,
        "proof": proof,
        "offer": {
            "present": bool(offer_detail),
            "detail": offer_detail,
        },
        "price_original": price_original,
        "price_sale": price_sale,
        "cta": cta,
        "interaction": {
            "present": bool(re.search(r"\?|comment|review|评论|留言|ถาม|ถามว่า", merged_text, re.IGNORECASE)),
            "detail": "互动或提问内容已识别" if re.search(r"\?|comment|review|评论|留言|ถาม|ถามว่า", merged_text, re.IGNORECASE) else "",
        },
        "languages": {
            "voiceover": language,
            "subtitles": language,
            "onscreen_text": language,
        },
        "localization_signals": infer_localization_signals(merged_text, landing, market),
        "compliance_risks": [],
        "extra_notes": "自动草稿生成，请结合关键帧与原视频再人工确认。",
        "copy_requirements": {
            "title_intensity": "aggressive",
            "click_triggers": ["买前确认", "损失厌恶", "避坑", "反转", "证明前置"],
            "avoid_ad_feel": True,
            "title_style": ["买前确认型", "损失厌恶型", "反转型", "证明前置型"],
            "must_append_hashtags": True,
        },
        "draft_confidence": 0.56 if transcript_text or landing else 0.35,
        "source_evidence": {
            "extraction_json": str(extraction.get("source_files", {}).get("extraction_json") or extraction.get("video_path") or ""),
            "landing_page_used": bool(landing),
            "transcript_used": bool(transcript_text),
            "ocr_used": bool(ocr_text),
            "audio_file": extraction.get("audio_file"),
        },
    }
    return notes


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a draft notes.json from extraction and landing-page data")
    parser.add_argument("--extraction-json", required=True, help="extract_frames.py 生成的 extraction_result.json")
    parser.add_argument("--landing-page-json", default=None, help="fetch_landing_page.py 生成的落地页 JSON，可选")
    parser.add_argument("--transcript", default=None, help="人工整理的转写文本或 whisper 输出文本，可选")
    parser.add_argument("--ocr-json", default=None, help="外部 OCR 工具输出的 JSON，可选；会抽取 text/transcript/ocr/caption 等字段")
    parser.add_argument("--transcribe", action="store_true", help="如果存在 audio_file，自动尝试调用 whisper CLI 转写")
    parser.add_argument("--market", default="jp", help="目标市场：jp / th / id，用于本地化信号默认值")
    parser.add_argument("--output", default=None, help="输出 notes.json 路径，默认与 extraction_json 同目录")
    args = parser.parse_args()

    extraction_path = Path(args.extraction_json)
    extraction = load_json(extraction_path)
    landing = load_json(Path(args.landing_page_json)) if args.landing_page_json else {}
    transcript_text = load_text(Path(args.transcript)) if args.transcript else ""
    ocr_text = load_ocr_text(Path(args.ocr_json)) if args.ocr_json else ""
    if args.transcribe and not transcript_text:
        transcript_text = maybe_transcribe(extraction.get("audio_file"))

    notes = build_notes(extraction, landing, transcript_text, ocr_text, args.market)
    output_path = Path(args.output) if args.output else extraction_path.parent / "notes.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(notes, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "status": "ok",
        "output": str(output_path),
        "product_name": notes["product_name"],
        "category": notes["category"],
        "draft_confidence": notes["draft_confidence"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
