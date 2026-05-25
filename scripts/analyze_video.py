"""
TikTok 视频广告素材分析与多市场文案生成脚本。

Usage:
  python analyze_video.py --extraction-json temp_frames/extraction_result.json --notes notes.json --market jp --output report
"""

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


MARKET_CONFIG = {
    "jp": {
        "label": "日本",
        "language_label": "日语",
        "accepted_languages": {"jp"},
        "accepted_regions": {"jp"},
        "currency_code": "JPY",
        "currency_symbol": "¥",
        "cta_profile": "プロフィールへ",
        "cta_primary": "今すぐチェック",
        "cta_more": "詳細はこちら",
        "price_placeholder": "¥2,980",
    },
    "th": {
        "label": "泰国",
        "language_label": "泰语/英语",
        "accepted_languages": {"th", "en"},
        "accepted_regions": {"th"},
        "currency_code": "THB",
        "currency_symbol": "฿",
        "cta_profile": "ดูในโปรไฟล์",
        "cta_primary": "ดูเพิ่มเติม",
        "cta_more": "เช็กราคาเลย",
        "price_placeholder": "฿590",
    },
    "id": {
        "label": "印尼",
        "language_label": "印尼语/英语",
        "accepted_languages": {"id", "en"},
        "accepted_regions": {"id"},
        "currency_code": "IDR",
        "currency_symbol": "Rp",
        "cta_profile": "Lihat Profil",
        "cta_primary": "Lihat Selengkapnya",
        "cta_more": "Cek Sekarang",
        "price_placeholder": "Rp199.000",
    },
}

LANGUAGE_ALIASES = {
    "zh": {"zh", "cn", "chinese", "中文", "普通话", "mandarin"},
    "jp": {"jp", "ja", "japanese", "日语", "日本语", "日本語"},
    "th": {"th", "thai", "泰语", "ภาษาไทย"},
    "id": {"id", "indonesian", "bahasa", "bahasa indonesia", "印尼语"},
    "en": {"en", "english", "英语"},
}

REGION_ALIASES = {
    "cn": {"cn", "china", "中国", "mainland", "zh"},
    "jp": {"jp", "japan", "日本"},
    "th": {"th", "thailand", "泰国"},
    "id": {"id", "indonesia", "印尼", "印度尼西亚"},
}

DISALLOWED_PATTERNS = [
    r"100%",
    r"100％",
    r"保证",
    r"绝对",
    r"絶対",
    r"必ず",
    r"No\.1",
    r"销量第一",
    r"販売数.*突破",
    r"顧客満足度",
    r"満足度.*100",
    r"五百万|500万|5百万",
    r"治疗",
    r"预防",
    r"药效",
    r"治る",
    r"改善",
    r"矯正",
    r"永久",
    r"完璧",
    r"医師.*推奨",
    r"歯科医.*推奨",
    r"FDA",
    r"CE認証",
    r"best in the world",
]

# 购买意图触发词：用于标题评分和生成逻辑。
# 原则：强化“买前确认/现在行动/不买损失/适合谁买”，但不编造价格、库存、折扣、销量。
PURCHASE_INTENT_PATTERNS = [
    r"買う前|購入前|買ってから|チェック|プロフィール|詳細|今だけ|在庫|見逃し|損|失敗|後悔|まだ|知らない|だけ見て|正直|レビュー|口コミ|高い.*買う前",
    r"ก่อนซื้อ|เช็ก|โปร|พลาด|รีบ|ดูเพิ่มเติม|ของหมด|ลด",
    r"sebelum beli|cek|promo|jangan sampai|rugi|stok|lihat|review",
    r"buy|shop|check|before you buy|need this|don.t miss|regret|still using|limited|review",
]
AB_TEST_LIBRARY = {
    "钩子强度": ("痛点开场", "结果开场", "反差开场"),
    "卖点清晰度": ("单一卖点聚焦", "三卖点连发", "对比式卖点"),
    "证明可信度": ("真人演示", "评论截图", "前后对比"),
    "优惠驱动力": ("直接报现价", "原价对比", "限时折扣"),
    "CTA压迫感": ("查看详情", "主页链接", "库存倒计时"),
    "节奏/完播率": ("15 秒快剪", "30 秒标准版", "45 秒强销售版"),
    "互动驱动": ("提问式结尾", "投票式结尾", "评论区领取"),
    "合规性": ("弱化绝对词", "补充真实演示", "删除高风险措辞"),
}

HOOK_ANGLES = {
    "beauty": {
        "pain": ["グラデが苦手な人だけ見て", "朝のメイクでまだ迷ってる？", "メイク直しが面倒な人へ"],
        "contrast": ["パレット派、ちょっと待って", "3色重ねる前に見て", "正直、期待してなかった"],
        "curiosity": ["このスティック、何が違う？", "このツヤ感の理由", "使い方、意外と簡単"],
        "scarcity": ["見逃し注意", "今だけチェックしたい", "気になるなら早めに見て"],
        "benefit": ["時短メイクしたい人へ", "ひと塗りで雰囲気変わる", "毎朝ラクにしたい人へ"],
        "purchase": ["買う前にこれだけ見て", "高いコスメ買う前にチェック", "レビュー見る前にここ確認"],
    },
    "fashion": {
        "pain": ["夏のデニム、重くない？", "パンツのライン気になる人へ", "ラクなのにきれいに見せたい人へ"],
        "contrast": ["デニムなのに、この落ち感", "普通のデニムと何が違うの？", "ゆるいのに、だらしなく見えない"],
        "curiosity": ["この揺れ感、ちょっと気になる", "シルエットがきれいな理由", "買う前に落ち感だけ見て"],
        "scarcity": ["気になる人は早めにチェック", "夏コーデ用に先に見て", "詳細だけ先に確認して"],
        "benefit": ["ラフなのに上品に見える", "サラッと履きやすい", "脚長見えを狙える"],
        "purchase": ["買う前にシルエットだけ見て", "ワイドパンツ選びで失敗する前に", "夏用デニム探してる人へ"],
    },
    "home": {
        "pain": ["まだその作業で時間使ってる？", "片付けが面倒な人だけ見て", "家事のストレス減らしたい人へ"],
        "contrast": ["これ、地味にすごい", "使う前は半信半疑だった", "普通の道具とここが違う"],
        "curiosity": ["何がそんなにラクなの？", "人気の理由ここだった", "使い方、意外とシンプル"],
        "scarcity": ["見逃し注意", "気になるなら早めにチェック", "今だけなら確認して"],
        "benefit": ["毎日の手間を減らしたい人へ", "置くだけでラクになる", "時短したい人にちょうどいい"],
        "purchase": ["買う前にこれだけ見て", "高い便利グッズ買う前にチェック", "失敗する前にここ確認"],
    },
    "food": {
        "pain": ["小腹が空く人だけ見て", "甘いもの我慢しすぎてない？", "毎日のおやつ迷ってる？"],
        "contrast": ["正直、味は期待してなかった", "この食感ちょっと意外", "普通のおやつと違った"],
        "curiosity": ["人気の理由ここだった", "どんな味か気になる人へ", "一回チェックしたい味"],
        "scarcity": ["見逃し注意", "気になるなら早めにチェック", "今だけなら確認して"],
        "benefit": ["手軽に楽しみたい人へ", "ちょっとしたご褒美に", "毎日続けやすい"],
        "purchase": ["買う前にこれだけ見て", "まとめ買い前にチェック", "レビュー見る前にここ確認"],
    },
    "oral_care": {
        "pain": ["笑う時、口元隠してない？", "写真で口閉じがちな人へ", "食事の時ちょっと気になる人へ"],
        "contrast": ["入れ歯っぽく見えないの、正直ずるい", "ちょっと待って、装着後の差が強い", "普通に笑った時の見え方が違う"],
        "curiosity": ["食事シーンまで見せるの気になる", "この自然な見え方、何が違う？", "買う前に装着シーンだけ見て"],
        "scarcity": ["見逃し注意", "気になるなら早めにチェック", "今の条件だけ先に見て"],
        "benefit": ["口元の印象を先にチェック", "笑顔の見え方が気になる人へ", "自宅で試しやすいの助かる"],
        "purchase": ["買う前に装着シーンだけ見て", "試す前にここだけ確認", "後払いで確認しやすい"],
    },
    "general": {
        "pain": ["まだそれで我慢してる？", "同じ悩みある人だけ見て", "買ってから後悔したくない人へ"],
        "contrast": ["正直、期待してなかった", "これ、思ったより違った", "普通の商品とここが違う"],
        "curiosity": ["人気の理由ここだった", "何が違うのかだけ見て", "レビューで多かった声"],
        "scarcity": ["見逃し注意", "気になるなら早めにチェック", "今だけなら確認して"],
        "benefit": ["毎日使いやすい", "ラクに続けやすい", "選ばれる理由がある"],
        "purchase": ["買う前にこれだけ見て", "高い買い物する前にチェック", "失敗する前にここ確認"],
    },
}


def load_json(path: Optional[Path]) -> Dict[str, Any]:
    if not path:
        return {}
    if not path.exists():
        raise FileNotFoundError(f"JSON file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    stripped = str(value).strip()
    return [stripped] if stripped else []


def normalize_language(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    for normalized, aliases in LANGUAGE_ALIASES.items():
        if text in aliases:
            return normalized
    return text


def normalize_region(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    for normalized, aliases in REGION_ALIASES.items():
        if text in aliases:
            return normalized
    return text


def truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict, tuple, set)):
        return bool(value)
    return bool(value)


def clamp(score: int, min_value: int = 1, max_value: int = 5) -> int:
    return max(min_value, min(max_value, score))


def unique_keep_order(items: Sequence[str]) -> List[str]:
    seen = set()
    result: List[str] = []
    for item in items:
        text = item.strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def get_copy_requirements(notes: Dict[str, Any]) -> Dict[str, Any]:
    requirements = notes.get("copy_requirements")
    return requirements if isinstance(requirements, dict) else {}


def get_title_intensity(notes: Dict[str, Any]) -> str:
    requirements = get_copy_requirements(notes)
    intensity = str(requirements.get("title_intensity") or notes.get("title_intensity") or "aggressive").strip().lower()
    if intensity not in {"safe", "aggressive", "hard_sell"}:
        return "aggressive"
    return intensity


def has_japanese_script(text: Any) -> bool:
    return bool(re.search(r"[ぁ-んァ-ヶー]", str(text or "")))


def jp_fragment(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    return text if has_japanese_script(text) else fallback


def compact_jp_text(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[「」『』\[\]（）()<>《》]", "", text)
    return text.strip()


def normalize_tk_char_limit(notes: Dict[str, Any], default_limit: int = 100) -> int:
    requirements = get_copy_requirements(notes)
    for key in ["short_copy_char_limit", "tk_char_limit", "copy_char_limit", "char_limit"]:
        raw = requirements.get(key, notes.get(key))
        if raw in (None, ""):
            continue
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            continue
        if limit > 0:
            return limit
    return default_limit


def extract_video_script(notes: Dict[str, Any]) -> str:
    requirements = get_copy_requirements(notes)
    candidates = [
        notes.get("video_script"),
        notes.get("script"),
        notes.get("transcript"),
        notes.get("voiceover_text"),
        requirements.get("video_script"),
        requirements.get("script"),
        requirements.get("transcript"),
        requirements.get("source_script"),
    ]
    for candidate in candidates:
        text = compact_jp_text(candidate)
        if text:
            return text
    return ""


def detect_risky_script_claims(text: str) -> List[str]:
    if not text:
        return []
    risk_map = [
        ("销量/爆量", r"販売数|突破|五百万|500万|5百万|売上|爆売れ"),
        ("满意度", r"顧客満足度|満足度.*100|100%|100％"),
        ("医师/认证", r"医師.*推奨|歯科医.*推奨|FDA|CE認証|認証"),
        ("医疗效果", r"治る|改善|矯正|薬効|医療|発癌|無毒"),
        ("绝对化", r"絶対|必ず|永久|完璧|No\.1|絶不"),
    ]
    matched = []
    for label, pattern in risk_map:
        if re.search(pattern, text, flags=re.IGNORECASE):
            matched.append(label)
    return unique_keep_order(matched)


def build_jp_fashion_short_copy_candidates(notes: Dict[str, Any], product_hint: str, pain_hint: str, benefit_hint: str, proof_hint: str, offer_hint: str) -> List[str]:
    script = extract_video_script(notes)
    blob = " ".join([product_hint, script] + as_list(notes.get("selling_points")) + as_list(notes.get("pain_points")))
    is_denim = bool(re.search(r"デニム|denim|ジーンズ|ワイドパンツ|天絲|テンセル", blob, flags=re.IGNORECASE))
    has_shipping = bool(re.search(r"送料無料|送料.*無料", script)) or "送料無料" in offer_hint
    candidates = []
    if is_denim:
        candidates.extend([
            "とろける落ち感✨動くたびふわっと揺れる💃ハイウエストで脚長見え👖#天絲デニム #夏コーデ #着痩せ",
            "快適×おしゃれ🌿サラサラ肌触り💫大人カジュアルにぴったり👖#テンセルデニム #ワイドパンツ #脚長",
            "ラフなのに上品✨ハイウエストで美脚見え👖動くたび揺れるふんわりドレープ💃#天絲デニム #大人カジュアル #夏コーデ",
            "肉感を拾いにくい美シルエット💖動くたび揺れるドレープ感💃大人の余裕を演出🌿#テンセルデニム #着痩せ #ワイドパンツ",
            "普通デニムと差が出る💫とろける落ち感で美脚見え👖動きやすさも抜群✨#天絲デニム #大人カジュアル #夏",
            "サラサラ肌触りで夏も快適☀️ふわっと揺れるドレープ感💃ハイウエストで脚長見え👖#テンセルデニム #夏コーデ #ワイドパンツ",
            "夏コーデの主役に🌿とろける落ち感で軽やか💫ハイウエストで脚長見え👖#テンセルデニム #ワイドパンツ #夏コーデ",
            "普通デニムとの差を実感💖動くたびふわっと揺れるドレープ感💃ハイウエストで美脚見え👖#天絲デニム #大人カジュアル #脚長",
            "快適×美脚👖サラサラ肌触りで夏も涼しげ🌿動くたび揺れるふんわりドレープ💃#テンセルデニム #着痩せ #夏コーデ",
            "とろっと揺れるドレープ感💃ラフなのにきれい見え✨夏に履きたい軽やかデニム👖#天絲デニム #ワイドパンツ #大人カジュアル",
        ])
        if has_shipping:
            candidates.append("送料無料もチェック👀サラサラ肌触りで夏も快適🌿ふわっと揺れるワイドデニム👖#テンセルデニム #夏コーデ #脚長")
    else:
        candidates.extend([
            f"着た時の見え方、想像より大事👀 {product_hint}は写真より動画で見た方がわかる。先にチェック✨",
            f"普通に見えて、着ると雰囲気が変わるやつ👀 {proof_hint}で{benefit_hint}を確認してから選びたい。",
            f"コーデ迷子なら一回見て👀 合わせやすさと着た時の見え方、動画で先に確認してみて✨",
        ])
    return candidates


def build_jp_short_tk_copies(notes: Dict[str, Any], category: str, product_hint: str, pain_hint: str, benefit_hint: str, proof_hint: str, offer_hint: str) -> List[str]:
    limit = normalize_tk_char_limit(notes, 100)
    script = extract_video_script(notes)
    flags = {
        "postpay": bool(re.search(r"後払い|前払い.*不要|商品到着後|満足.*支払い|受け取.*後.*支払い", script)),
        "trial": bool(re.search(r"試着|試せる|まずは.*受け取|満足.*してから", script)),
        "refund": bool(re.search(r"返品|交換|全額返金", script)),
        "shipping": bool(re.search(r"送料無料|送料.*無料", script)),
        "offer": bool(re.search(r"OFF|オフ|割引|セール|特別価格|キャンペーン|限定|無料", script)) or offer_hint != "今だけの条件",
        "proof_scene": bool(re.search(r"使用|着用|装着|食事|レビュー|口コミ|比較|前後|ビフォー|動画|シーン", script)),
        "home_scene": bool(re.search(r"自宅|家で|1分|一分|受け取", script)),
    }
    oral_product = "シリコン義歯" if category == "oral_care" and re.search(r"シリコン", script) else product_hint
    display_product = oral_product if category == "oral_care" else product_hint

    category_candidates = {
        "fashion": build_jp_fashion_short_copy_candidates(notes, product_hint, pain_hint, benefit_hint, proof_hint, offer_hint),
        "beauty": [
            f"{pain_hint}が気になる人へ👀 {product_hint}の使用シーンを先にチェック。{benefit_hint}の見え方を、買う前に動画で確認してみて✨",
            f"説明だけだとわかりにくいから、まずは動画で確認👀 {product_hint}の使い方と{benefit_hint}が気になる人にちょうどいい✨",
            f"正直、こういうのは使うシーンを見てから決めたい👀 {benefit_hint}が気になる人は、詳細を見る前に動画チェック✨",
        ],
        "home": [
            f"その手間、まだ続ける？👀 {product_hint}の使用シーンを見ると、暮らしでどう使えるかイメージしやすい✨",
            f"地味だけど、こういうのが毎日助かる👀 {benefit_hint}が気になる人は、買う前に使い方をチェック✨",
            f"説明より動画の方が早いかも👀 {product_hint}で手間がどう変わるか、使用シーンを先に確認してみて✨",
        ],
        "food": [
            f"これ、味が気になるやつ👀 {product_hint}は食べるシーンまで見てから判断して。気になる人は詳細チェック🍴",
            f"小腹対策に迷ってるなら一回見て🍴 {benefit_hint}や食べた時の雰囲気を、動画で先に確認👀",
            f"写真だけじゃ伝わりにくいから、食べるシーンまでチェック👀 {product_hint}が気になる人は詳細へ🍴",
        ],
        "oral_care": [
            f"人前で笑うのをためらっていませんか？🦷 {oral_product}の装着シーンと口元の見え方を、まずは動画でチェック✨",
            f"食事シーンまで見せているのが気になる👀 {oral_product}の見え方や使う雰囲気を、買う前に確認してみて🦷",
            f"口元の印象が気になる人へ😊 {oral_product}は動画で見え方を確認しやすい。まずは詳細をチェック🦷✨",
        ],
        "general": [
            f"ちょっと待って、これ思ったより気になる👀 {product_hint}は買う前に動画で確認。気になる人は詳細をチェック✨",
            f"{pain_hint}が気になる人へ👀 {product_hint}の{benefit_hint}を、説明より先に使用シーンで見てみて✨",
            f"普通の商品に見えて、使うと違いがわかりやすいかも👀 {proof_hint}を先に確認してから詳細へ✨",
        ],
    }
    candidates = list(category_candidates.get(category, category_candidates["general"]))
    if flags["postpay"]:
        candidates.insert(0, f"前払いなしで試せるのはやっぱり安心👀 まず受け取って、使ってから判断。{display_product}が気になる人は詳細チェック✨")
    if flags["trial"]:
        candidates.insert(0, f"試してから決められるの、普通にありがたい👀 {display_product}の使い心地や見え方を、先に動画で確認してみて✨")
    if flags["refund"]:
        candidates.insert(0, f"返品交換ありなら、初めてでも試しやすい👀 {display_product}が気になる人は、買う前に詳細を確認✨")
    if flags["shipping"]:
        candidates.insert(0, f"送料無料なら見ておきたい👀 {display_product}の使い方や見え方を、動画で先にチェックしてから詳細へ✨")
    if flags["offer"]:
        candidates.insert(0, f"{offer_hint}なら先に見たい👀 {display_product}が気になる人は、今の条件と詳細をチェック✨")
    if flags["proof_scene"]:
        candidates.insert(0, f"{proof_hint}まで見せているのが気になる👀 {display_product}は買う前に動画で確認してから判断して✨")
    if flags["home_scene"]:
        candidates.insert(0, f"自宅で試せるなら見ておきたい👀 {display_product}の使い方や見え方を、まずは動画で確認✨")

    # Keep only compact, non-duplicated, <= limit variants.
    natural_suffix = {
        "beauty": "使用感のイメージも先に見ておくと安心。",
        "fashion": "",
        "home": "毎日の手間に合うか先に見ておくと安心。",
        "food": "食べるシーンも見てから選ぶと安心。",
        "oral_care": "食事や会話のシーンもあわせてチェック🦷",
        "general": "使用シーンも見てから判断すると安心。",
    }
    result: List[str] = []
    seen = set()
    for text in candidates:
        text = compact_jp_text(text)
        if not text or text in seen:
            continue
        suffix = natural_suffix.get(category, natural_suffix["general"])
        if suffix and len(text) < 70 and len(text + suffix) <= limit:
            text = f"{text}{suffix}"
        if len(text) > limit:
            text = text[:limit].rstrip("、。,.!！?？ ")
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result[:5]


def has_thai_script(text: Any) -> bool:
    return bool(re.search(r"[\u0E00-\u0E7F]", str(text or "")))


def has_latin_text(text: Any) -> bool:
    return bool(re.search(r"[A-Za-z]", str(text or "")))


def th_fragment(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    return text if has_thai_script(text) else fallback


def th_name_fragment(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    return text if has_thai_script(text) or has_latin_text(text) else fallback


def id_fragment(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    return text if has_latin_text(text) else fallback


def format_price_if_present(value: Any, market: str) -> str:
    if value in (None, ""):
        return ""
    return format_price(value, market)


def get_offer_detail(notes: Dict[str, Any]) -> str:
    offer = notes.get("offer", {}) if isinstance(notes.get("offer"), dict) else {}
    return str(offer.get("detail") or notes.get("offer_detail") or "").strip()


def has_offer_evidence(notes: Dict[str, Any]) -> bool:
    offer = notes.get("offer", {}) if isinstance(notes.get("offer"), dict) else {}
    return truthy(offer.get("present")) or bool(get_offer_detail(notes))


def format_price(value: Any, market: str) -> str:
    config = MARKET_CONFIG[market]
    if value in (None, ""):
        return config["price_placeholder"]
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return str(value)

    if market == "jp":
        return f"¥{int(amount):,}"
    if market == "th":
        return f"฿{int(amount):,}"
    return f"Rp{int(amount):,}"


def extract_timestamp(frame_name: str) -> Optional[float]:
    match = re.search(r"_(\d+(?:\.\d+)?)s\.jpg$", frame_name)
    if not match:
        return None
    return float(match.group(1))


def market_from_args(raw_market: str) -> str:
    market = raw_market.strip().lower()
    if market not in MARKET_CONFIG:
        raise ValueError(f"Unsupported market: {market}")
    return market


def get_duration(extraction_data: Dict[str, Any], notes: Dict[str, Any]) -> float:
    if notes.get("duration_override") not in (None, ""):
        try:
            return float(notes["duration_override"])
        except (TypeError, ValueError):
            pass
    metadata = extraction_data.get("metadata", {})
    try:
        return float(metadata.get("duration", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def score_hook(notes: Dict[str, Any], frame_files: Sequence[str]) -> Tuple[int, str]:
    hook = notes.get("hook", {}) if isinstance(notes.get("hook"), dict) else {}
    hook_type = str(hook.get("type") or notes.get("hook_type") or "").strip().lower()
    hook_detail = str(hook.get("detail") or notes.get("hook_detail") or "").strip()
    has_hook = truthy(hook.get("present")) or bool(hook_type or hook_detail)
    first_ts = None
    if frame_files:
        first_ts = extract_timestamp(Path(frame_files[0]).name)

    score = 1
    reasons: List[str] = []
    if has_hook:
        score += 2
        reasons.append("已识别到明确开场钩子")
    else:
        reasons.append("缺少明确钩子描述")

    if hook_type in {"pain", "pain_point", "result", "contrast", "curiosity", "offer"}:
        score += 1
        reasons.append(f"钩子类型为 {hook_type}")

    if first_ts is not None and first_ts <= 3.0:
        score += 1
        reasons.append(f"首个关键帧位于 {first_ts:.1f}s，符合前 3 秒抢注意力要求")
    elif first_ts is not None:
        reasons.append(f"首个关键帧位于 {first_ts:.1f}s，钩子可能偏晚")
    else:
        reasons.append("未获得关键帧时间戳，钩子判断可信度有限")

    return clamp(score), "；".join(reasons)


def score_selling_points(notes: Dict[str, Any]) -> Tuple[int, str]:
    selling_points = as_list(notes.get("selling_points"))
    count = len(selling_points)
    if count >= 3:
        return 5, f"识别到 {count} 个卖点，信息较完整：{' / '.join(selling_points[:3])}"
    if count == 2:
        return 4, f"已有 2 个清晰卖点：{' / '.join(selling_points)}"
    if count == 1:
        return 3, f"仅识别到 1 个卖点：{selling_points[0]}，建议补充更多利益点"
    return 1, "缺少明确卖点输入，难以形成有效转化表达"


def score_proof(notes: Dict[str, Any]) -> Tuple[int, str]:
    proof = as_list(notes.get("proof"))
    proof_blob = " ".join(proof).lower()
    score = 1 if not proof else 3
    if any(keyword in proof_blob for keyword in ["演示", "demo", "试穿", "试用", "真人"]):
        score += 1
    if any(keyword in proof_blob for keyword in ["对比", "before", "after", "评价", "评论"]):
        score += 1
    if proof:
        return clamp(score), f"已提供证明素材：{' / '.join(proof[:3])}"
    return 1, "缺少演示、评价或前后对比等证明内容"


def score_offer(notes: Dict[str, Any], market: str) -> Tuple[int, str]:
    offer = notes.get("offer", {}) if isinstance(notes.get("offer"), dict) else {}
    offer_detail = str(offer.get("detail") or notes.get("offer_detail") or "").strip()
    price_sale = notes.get("price_sale")
    price_original = notes.get("price_original")
    score = 1
    reasons: List[str] = []

    if truthy(offer.get("present")) or offer_detail:
        score += 2
        reasons.append("存在明确优惠或活动信息")
    if price_sale not in (None, ""):
        score += 1
        reasons.append(f"已提供现价 {format_price(price_sale, market)}")
    if price_original not in (None, "") and price_sale not in (None, ""):
        score += 1
        reasons.append("具备原价与现价对比")

    if reasons:
        return clamp(score), "；".join(reasons)
    return 1, "缺少价格、折扣或限时信息，优惠驱动力偏弱"


def score_cta(notes: Dict[str, Any]) -> Tuple[int, str]:
    cta = notes.get("cta", {}) if isinstance(notes.get("cta"), dict) else {}
    cta_detail = str(cta.get("detail") or notes.get("cta_detail") or "").strip()
    has_cta = truthy(cta.get("present")) or bool(cta_detail)
    score = 1
    reasons: List[str] = []

    if has_cta:
        score += 2
        reasons.append("存在明确 CTA")
        if re.search(r"限时|库存|今天|马上|立即|link|profile|check|now", cta_detail, re.IGNORECASE):
            score += 2
            reasons.append("CTA 具有一定紧迫感")
        else:
            score += 1
            reasons.append("CTA 明确但压迫感一般")
        return clamp(score), "；".join(reasons)

    return 1, "缺少行动号召，用户可能看完但不执行下一步"


def score_pace(notes: Dict[str, Any], extraction_data: Dict[str, Any]) -> Tuple[int, str]:
    duration = get_duration(extraction_data, notes)
    frame_count = len(extraction_data.get("frame_files", []) or [])
    pace_hint = str(notes.get("pace") or notes.get("pace_hint") or "").strip().lower()

    score = 2
    reasons: List[str] = [f"素材时长约 {duration:.1f}s", f"关键帧数量 {frame_count} 张"]

    if 12 <= duration <= 35:
        score += 2
        reasons.append("时长处于 TikTok 转化素材常见优区间")
    elif duration <= 45:
        score += 1
        reasons.append("时长仍可接受")
    else:
        reasons.append("时长偏长，可能影响完播率")

    if 6 <= frame_count <= 15:
        score += 1
        reasons.append("信息密度看起来较均衡")

    if pace_hint in {"fast", "tight", "snappy", "快", "紧凑"}:
        score += 1
        reasons.append("人工标注节奏较紧凑")

    return clamp(score), "；".join(reasons)


def score_interaction(notes: Dict[str, Any]) -> Tuple[int, str]:
    interaction = notes.get("interaction", {}) if isinstance(notes.get("interaction"), dict) else {}
    detail = str(interaction.get("detail") or notes.get("interaction_detail") or "").strip()
    has_interaction = truthy(interaction.get("present")) or bool(detail)
    hook_type = str((notes.get("hook") or {}).get("type") or "").strip().lower() if isinstance(notes.get("hook"), dict) else ""

    score = 1
    reasons: List[str] = []
    if has_interaction:
        score += 3
        reasons.append("存在评论、讨论或提问诱因")
    if hook_type in {"curiosity", "question"}:
        score += 1
        reasons.append("钩子自带互动属性")

    if reasons:
        return clamp(score), "；".join(reasons)
    return 1, "当前更偏直投素材，互动驱动较弱"


def score_compliance(notes: Dict[str, Any]) -> Tuple[int, str]:
    risks = as_list(notes.get("compliance_risks"))
    blob_parts: List[str] = []
    for key in ["extra_notes", "offer_detail", "cta_detail"]:
        if notes.get(key):
            blob_parts.append(str(notes[key]))

    offer = notes.get("offer", {}) if isinstance(notes.get("offer"), dict) else {}
    cta = notes.get("cta", {}) if isinstance(notes.get("cta"), dict) else {}
    hook = notes.get("hook", {}) if isinstance(notes.get("hook"), dict) else {}
    blob_parts.extend([str(offer.get("detail") or ""), str(cta.get("detail") or ""), str(hook.get("detail") or "")])

    blob = " ".join(blob_parts)
    matched = [pattern for pattern in DISALLOWED_PATTERNS if re.search(pattern, blob, re.IGNORECASE)]
    penalty = len(risks) + len(matched)
    score = clamp(5 - penalty)

    if penalty == 0:
        return 5, "当前输入中未发现明显高风险措辞"

    parts = []
    if risks:
        parts.append(f"人工标记风险：{' / '.join(risks)}")
    if matched:
        parts.append(f"疑似敏感表达：{' / '.join(matched)}")
    return score, "；".join(parts)


def build_scores(notes: Dict[str, Any], extraction_data: Dict[str, Any], market: str) -> Tuple[List[Dict[str, Any]], int]:
    frame_files = extraction_data.get("frame_files", []) or []
    score_map = [
        ("钩子强度", score_hook(notes, frame_files)),
        ("卖点清晰度", score_selling_points(notes)),
        ("证明可信度", score_proof(notes)),
        ("优惠驱动力", score_offer(notes, market)),
        ("CTA压迫感", score_cta(notes)),
        ("节奏/完播率", score_pace(notes, extraction_data)),
        ("互动驱动", score_interaction(notes)),
        ("合规性", score_compliance(notes)),
    ]
    rows = [{"dimension": name, "score": score, "analysis": analysis} for name, (score, analysis) in score_map]
    total_score = sum(item["score"] for item in rows)
    return rows, total_score


def total_score_summary(total_score: int) -> str:
    if total_score >= 32:
        return "优秀素材，可直接进入测试"
    if total_score >= 25:
        return "良好素材，建议补强弱项后测试"
    if total_score >= 20:
        return "一般素材，建议优化后再投放"
    return "较弱素材，建议重做结构或重拍"


def build_confidence(notes: Dict[str, Any], extraction_data: Dict[str, Any]) -> int:
    """Estimate analysis confidence from both field coverage and observable evidence quality."""
    frame_count = len(extraction_data.get("frame_files", []) or [])
    metadata = extraction_data.get("metadata", {}) if isinstance(extraction_data.get("metadata"), dict) else {}
    languages = notes.get("languages", {}) if isinstance(notes.get("languages"), dict) else {}
    localization = notes.get("localization_signals", {}) if isinstance(notes.get("localization_signals"), dict) else {}

    checks = [
        (truthy(notes.get("hook")) or truthy(notes.get("hook_detail")), 12),
        (len(as_list(notes.get("selling_points"))) >= 2, 12),
        (bool(as_list(notes.get("proof"))), 10),
        (truthy(notes.get("offer")) or truthy(notes.get("offer_detail")) or notes.get("price_sale") not in (None, ""), 10),
        (truthy(notes.get("cta")) or truthy(notes.get("cta_detail")), 8),
        (any(normalize_language(value) for value in languages.values()), 10),
        (any(value not in (None, "") for value in localization.values()), 10),
        (truthy(metadata.get("duration")) and truthy(metadata.get("width")) and truthy(metadata.get("height")), 12),
        (frame_count >= 6, 10),
        (bool(extraction_data.get("audio_file")) or metadata.get("has_audio") is False, 6),
    ]
    return min(100, sum(weight for passed, weight in checks if passed))


def build_localization(notes: Dict[str, Any], extraction_data: Dict[str, Any], market: str) -> Dict[str, Any]:
    config = MARKET_CONFIG[market]
    languages = notes.get("languages", {}) if isinstance(notes.get("languages"), dict) else {}
    signals = notes.get("localization_signals", {}) if isinstance(notes.get("localization_signals"), dict) else {}

    voiceover = normalize_language(languages.get("voiceover"))
    subtitles = normalize_language(languages.get("subtitles"))
    onscreen = normalize_language(languages.get("onscreen_text"))
    model_region = normalize_region(signals.get("model_region"))
    music_style = normalize_region(signals.get("music_style"))
    currency = str(signals.get("currency") or notes.get("currency") or "").upper()
    needs_recut = bool(signals.get("needs_recut"))
    duration = get_duration(extraction_data, notes)

    accepted_languages = config["accepted_languages"]
    reasons: List[str] = []
    checklist: List[str] = []

    language_values = [value for value in [voiceover, subtitles, onscreen] if value]
    has_cn_signal = "zh" in language_values or model_region == "cn" or music_style == "cn" or currency in {"CNY", "RMB"}
    language_ok = bool(language_values) and all(value in accepted_languages for value in language_values)
    region_ok = model_region in config["accepted_regions"] if model_region else False
    music_ok = music_style in config["accepted_regions"] if music_style else False
    currency_ok = currency == config["currency_code"] if currency else False

    if duration > 45 or needs_recut:
        status = "不建议"
        reasons.append("素材时长或结构提示需要重剪，直接投放风险较高")
        checklist.append("优先裁切到 15-45 秒，并重新组织钩子与 CTA")
    elif language_ok and not has_cn_signal and region_ok and currency_ok:
        status = "直接可投"
        reasons.append("语言、地区风格、货币信息与目标市场基本一致")
    else:
        status = "需本地化"
        reasons.append("仍存在语言、模特风格、货币或表达方式与目标市场不一致的问题")

    if voiceover and voiceover not in accepted_languages:
        checklist.append(f"重录 {config['language_label']} 旁白")
    if subtitles and subtitles not in accepted_languages:
        checklist.append(f"改写为 {config['language_label']} 字幕")
    if onscreen == "zh":
        checklist.append(f"替换画面中文字为 {config['language_label']}")
    if not region_ok:
        checklist.append("替换或补充更贴近本地市场的模特 / UGC 画面")
    if not music_ok:
        checklist.append("替换更贴近本地市场的 BGM 风格")
    if currency and not currency_ok:
        checklist.append(f"改用 {config['currency_symbol']} 价格表达")
    if not truthy(notes.get("cta")) and not truthy(notes.get("cta_detail")):
        checklist.append(f"补充本地化 CTA，如 {config['cta_profile']}")
    if duration > 45:
        checklist.append("缩短到 15-45 秒以提升完播率")

    checklist = unique_keep_order(checklist)
    if not checklist and status == "直接可投":
        checklist.append("保持现有结构，优先做不同钩子版本 A/B 测试")

    return {
        "status": status,
        "reasons": reasons,
        "checklist": checklist,
        "signals": {
            "voiceover": voiceover,
            "subtitles": subtitles,
            "onscreen_text": onscreen,
            "model_region": model_region,
            "music_style": music_style,
            "currency": currency,
        },
    }


def infer_category(notes: Dict[str, Any]) -> str:
    category = str(notes.get("category") or "").strip().lower()
    blob = " ".join(
        as_list(notes.get("selling_points"))
        + as_list(notes.get("pain_points"))
        + [str(notes.get("product_name") or ""), extract_video_script(notes)]
    )
    if category in {"oral_care", "dental", "dentures", "口腔", "口元", "假牙", "義歯", "入れ歯"}:
        return "oral_care"
    if category in {"fashion", "服装", "服飾", "衣服", "穿搭"}:
        return "fashion"
    if category in {"beauty", "美妆", "美容", "护肤", "コスメ"}:
        return "beauty"
    if category in {"home", "家居", "生活", "工具", "日用品"}:
        return "home"
    if category in {"food", "食品", "饮食", "グルメ"}:
        return "food"
    if category:
        # Unknown user-entered category should not block stronger product/script signals.
        if any(keyword in blob for keyword in ["假牙", "入れ歯", "義歯", "歯", "口元", "笑顔", "噛", "インスタントスマイル"]):
            return "oral_care"
        return category
    if any(keyword in blob for keyword in ["透气", "穿搭", "版型", "显瘦", "面料"]):
        return "fashion"
    if any(keyword in blob for keyword in ["肌肤", "成分", "上妆", "护肤", "glowing"]):
        return "beauty"
    if any(keyword in blob for keyword in ["收纳", "清洁", "厨房", "家务"]):
        return "home"
    if any(keyword in blob for keyword in ["假牙", "入れ歯", "義歯", "歯", "口元", "笑顔", "噛", "インスタントスマイル"]):
        return "oral_care"
    if any(keyword in blob for keyword in ["口感", "健康", "营养", "美味"]):
        return "food"
    return "general"


JP_BEAUTY_RULES = {
    "preferred_phrases": ["え、まだ…？", "ちょっと待って", "見逃し注意", "気になるならチェック", "〜かも", "〜しやすい"],
    "avoid_phrases": ["絶対", "必ず", "100%", "No.1", "崩れない", "一日中キープ", "防水", "治る", "改善"],
    "title_principles": [
        "先说痛点/反差/价格，不先说完整商品说明。",
        "日语用轻压迫：見て / チェック / かも，比命令式更适合日本用户。",
        "美妆类避免未确认功效：防水、持久、不脱妆、改善等。",
        "标题末尾带 2-3 个关键词标签，避免 hashtag 过多稀释重点。",
    ],
}


def append_tags(title: str, tags: Sequence[str], max_tags: int = 3) -> str:
    clean_tags = [tag if tag.startswith("#") else f"#{tag}" for tag in tags if str(tag).strip()]
    return f"{title} {' '.join(clean_tags[:max_tags])}".strip()


def title_without_tags(title: str) -> str:
    return re.sub(r"\s*#\S+", "", title).strip()


def score_title(title: str, notes: Dict[str, Any], market: str, category: str) -> Dict[str, Any]:
    core = title_without_tags(title)
    reasons: List[str] = []
    warnings: List[str] = []
    score = 40

    if re.search(r"え、|まだ|ちょっと待って|なぜ|何が違う|正直|意外|知らない|レビュー|口コミ|[？?]", core):
        score += 14
        reasons.append("停手钩子/好奇心强")
    if re.search(r"悩|苦手|面倒|我慢|失敗|損|後悔|気になる|ムレ|締めつけ|ライン|買う前|知らないと", core):
        score += 14
        reasons.append("痛点或损失厌恶明确")
    if re.search(r"今だけ|限定|OFF|セール|価格|在庫|見逃し|早め|チャンス|特別|โปร|promo|stok|limited", core, re.I):
        score += 12
        reasons.append("优惠/紧迫感/行动窗口明确")
    if any(re.search(pattern, core, re.IGNORECASE) for pattern in PURCHASE_INTENT_PATTERNS):
        score += 14
        reasons.append("买前确认或购买意图强")
    if re.search(r"チェック|見て|確認|プロフィール|詳細|買う前|購入前|ดู|เช็ก|cek|lihat|check|shop", core, re.IGNORECASE):
        score += 8
        reasons.append("轻 CTA 清晰")
    if any(point and point in core for point in as_list(notes.get("selling_points"))):
        score += 8
        reasons.append("承接了明确卖点")
    if str(notes.get("product_name") or "") and str(notes.get("product_name")) in core:
        score += 4
        reasons.append("商品识别清楚")

    hashtag_count = len(re.findall(r"#\S+", title))
    if 2 <= hashtag_count <= 3:
        score += 6
        reasons.append("hashtag 数量适中")
    elif hashtag_count == 0:
        score -= 8
        warnings.append("缺少 hashtag")
    elif hashtag_count > 4:
        score -= 8
        warnings.append("hashtag 过多，容易稀释重点")

    length = len(core)
    if market == "jp":
        product_name = str(notes.get("product_name") or "").strip()
        if 9 <= length <= 40:
            score += 6
            reasons.append("长度适合 JP TikTok")
        elif length < 7:
            score -= 6
            warnings.append("标题过短，信息差不足")
        elif length > 48:
            score -= 12
            warnings.append("标题过长，停手感下降")
        if product_name and core.startswith(product_name):
            score -= 6
            warnings.append("商品名开头广告感偏强")
        if re.search(r"今すぐ買って|絶対買う|買わないと損|必ず買う|即買い", core):
            score -= 10
            warnings.append("命令或压迫过强，可能引起日本用户反感")
    risk_patterns = DISALLOWED_PATTERNS[:]
    if market == "jp" and category == "beauty":
        risk_patterns += [re.escape(item) for item in JP_BEAUTY_RULES["avoid_phrases"]]
    for pattern in risk_patterns:
        if re.search(pattern, title, flags=re.IGNORECASE):
            score -= 25
            warnings.append(f"疑似高风险或未承接表达：{pattern}")

    return {
        "title": title,
        "score": clamp(score, 0, 100),
        "reasons": reasons or ["信息完整但缺少强点击触发点"],
        "warnings": unique_keep_order(warnings),
    }


def infer_title_angle(title: str) -> str:
    core = title_without_tags(title).lower()
    if re.search(r"買う前|購入前|ก่อนซื้อ|sebelum beli|before you buy|cek ini dulu|เช็กอันนี้", core, re.I):
        return "buy_before"
    if re.search(r"損|後悔|失敗|พลาด|เสียเงิน|เสียเวลา|rugi|nyesel|salah beli|buang uang", core, re.I):
        return "loss_aversion"
    if re.search(r"レビュー|口コミ|รีวิว|review|proof|หลักฐาน|bukti", core, re.I):
        return "proof_first"
    if re.search(r"価格|ราคา|harga|off|promo|โปร|セール|特別", core, re.I):
        return "price_offer"
    if re.search(r"見逃し|早め|今だけ|limited|stok|stock|รีบ", core, re.I):
        return "urgency"
    if re.search(r"正直|意外|何が違う|なぜ|ทำไม|kenapa|ternyata|nggak nyangka", core, re.I):
        return "curiosity"
    return "general"


def parse_metric(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    is_percent = text.endswith("%")
    text = text.rstrip("%").replace(",", "")
    try:
        number = float(text)
    except ValueError:
        return None
    if is_percent or number > 1:
        return number / 100
    return number


def parse_number(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().rstrip("%").replace(",", "")
    try:
        return float(text)
    except ValueError:
        return None


def normalize_performance_records(raw: Any) -> List[Dict[str, Any]]:
    if not raw:
        return []
    if isinstance(raw, dict):
        for key in ["records", "titles", "items", "data"]:
            if isinstance(raw.get(key), list):
                raw = raw[key]
                break
        else:
            raw = [raw]
    if not isinstance(raw, list):
        return []

    records: List[Dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("ad_title") or item.get("creative_name") or "").strip()
        angle = str(item.get("angle") or item.get("title_angle") or "").strip() or infer_title_angle(title)
        ctr = parse_metric(item.get("ctr") or item.get("click_rate") or item.get("click_through_rate"))
        cvr = parse_metric(item.get("cvr") or item.get("conversion_rate"))
        roas = parse_number(item.get("roas"))
        cpa = parse_number(item.get("cpa") or item.get("cost_per_action"))
        score = 0.0
        signals = []
        if ctr is not None:
            score += ctr * 100
            signals.append(f"CTR {ctr:.2%}")
        if cvr is not None:
            score += cvr * 180
            signals.append(f"CVR {cvr:.2%}")
        if roas is not None:
            score += roas * 8
            signals.append(f"ROAS {roas:.2f}")
        if cpa is not None:
            score -= min(cpa, 20)
            signals.append(f"CPA {cpa:.2f}")
        if signals:
            records.append({"angle": angle, "score": score, "signals": signals, "title": title})
    return records


def build_performance_calibration(raw: Any) -> Dict[str, Any]:
    records = normalize_performance_records(raw)
    if not records:
        return {"used": False, "angle_bonuses": {}, "notes": ["未提供可用历史投放数据，标题排序使用规则评分。"]}
    by_angle: Dict[str, List[float]] = {}
    examples: Dict[str, List[str]] = {}
    for record in records:
        by_angle.setdefault(record["angle"], []).append(float(record["score"]))
        if record.get("title"):
            examples.setdefault(record["angle"], []).append(record["title"])
    averaged = {angle: sum(scores) / len(scores) for angle, scores in by_angle.items() if scores}
    ranked = sorted(averaged.items(), key=lambda item: item[1], reverse=True)
    bonuses: Dict[str, int] = {}
    for index, (angle, _) in enumerate(ranked[:4]):
        bonuses[angle] = max(2, 8 - index * 2)
    return {
        "used": True,
        "angle_bonuses": bonuses,
        "ranked_angles": [{"angle": angle, "score": round(score, 2), "examples": examples.get(angle, [])[:3]} for angle, score in ranked],
        "notes": ["已用历史 CTR/CVR/ROAS/CPA 对标题角度做轻量加权；仍需人工确认样本量和投放条件是否相近。"],
    }


def build_title_scores(
    copy_bundle: Dict[str, Any],
    notes: Dict[str, Any],
    market: str,
    category: str,
    performance_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    titles = copy_bundle.get("titles") or []
    scored = [score_title(title, notes, market, category) for title in titles]
    calibration = build_performance_calibration(performance_data)
    bonuses = calibration.get("angle_bonuses", {}) if calibration.get("used") else {}
    if bonuses:
        for item in scored:
            angle = infer_title_angle(item["title"])
            item["angle"] = angle
            bonus = int(bonuses.get(angle, 0))
            if bonus:
                item["score"] = clamp(int(item["score"]) + bonus, 0, 100)
                item["performance_bonus"] = bonus
                item["reasons"].append(f"历史数据角度加权 +{bonus}")
    ranked = sorted(scored, key=lambda item: item["score"], reverse=True)
    strong_risk_pattern = re.compile("|".join(DISALLOWED_PATTERNS), re.IGNORECASE)
    rejected = [item for item in ranked if item["score"] < 55 or strong_risk_pattern.search(item["title"])]
    needs_review = [
        item for item in ranked
        if item not in rejected and (item["warnings"] or item["score"] < 70)
    ]
    approved = [item for item in ranked if item not in rejected and item not in needs_review]
    return {
        "ranked": ranked,
        "top5": ranked[:5],
        "approved": approved[:10],
        "needs_review": needs_review[:10],
        "rejected": rejected[:10],
        "performance_calibration": calibration,
        "scoring_rules": [
            "停手感：疑问、反差、正直、意外、レビュー、口コミ等信息缺口加分。",
            "点击欲：買う前、知らないと損、後悔、失敗、だけ見て等买前确认和损失厌恶加分。",
            "转化相关：价格、OFF、今だけ、見逃し、チェック、プロフィール等行动线索加分。",
            "广告感控制：商品名开头、标题过长、过度命令式表达扣分。",
            "合规安全：绝对化、功效型、未确认价格/库存/销量表达扣分。",
            "标题分级：70分以上优先测试；55-69分或轻微 warning 需人工确认；55分以下或命中强风险词不建议优先使用。",
        ],
    }


def build_landing_page_check(notes: Dict[str, Any], market: str) -> Dict[str, Any]:
    landing = notes.get("landing_page") if isinstance(notes.get("landing_page"), dict) else {}
    if not landing:
        return {
            "status": "未提供落地页解析",
            "checks": [],
            "recommendations": ["可先运行 scripts/fetch_landing_page.py 生成 landing_page JSON，再放入 notes.landing_page。"],
        }
    text = " ".join(str(v) for v in [landing.get("title"), landing.get("product_name_guess"), landing.get("text_excerpt"), landing.get("image_alts")] if v)
    checks: List[Dict[str, str]] = []
    currency_symbol = MARKET_CONFIG[market]["currency_symbol"]

    def add_check(name: str, ok: bool, detail: str) -> None:
        checks.append({"item": name, "status": "一致" if ok else "需确认", "detail": detail})

    product_name = str(notes.get("product_name") or "").strip()
    add_check("商品名", bool(product_name and product_name in text), f"notes 商品名：{product_name or '未填写'}")
    prices = landing.get("prices") or []
    sale_price = format_price(notes.get("price_sale"), market) if notes.get("price_sale") not in (None, "") else ""
    normalized_sale = sale_price.replace(currency_symbol, "").replace("¥", "").replace("￥", "").replace("฿", "").replace("Rp", "").replace(",", "").strip()
    price_ok = bool(sale_price and any(normalized_sale in p.replace("¥", "").replace("￥", "").replace("฿", "").replace("Rp", "").replace(",", "") for p in prices))
    add_check("价格", price_ok, f"notes 价格：{sale_price or '未填写'}；页面价格：{', '.join(prices[:5]) or '未提取到'}")
    offer_detail = str((notes.get("offer") or {}).get("detail") or notes.get("offer_detail") or "").strip()
    discounts = landing.get("discounts") or []
    offer_ok = bool(offer_detail and offer_detail.lower().replace(" ", "") in " ".join(discounts).lower().replace(" ", ""))
    add_check("优惠", offer_ok, f"notes 优惠：{offer_detail or '未填写'}；页面优惠：{', '.join(discounts[:5]) or '未提取到'}")
    cta_detail = str((notes.get("cta") or {}).get("detail") or notes.get("cta_detail") or "").strip()
    ctas = landing.get("ctas") or []
    add_check("CTA", bool(cta_detail and cta_detail in " ".join(ctas + [text])), f"notes CTA：{cta_detail or '未填写'}；页面 CTA：{', '.join(ctas[:5]) or '未提取到'}")
    covered = [point for point in as_list(notes.get("selling_points")) if point and point in text]
    add_check("卖点承接", bool(covered), f"页面承接卖点：{', '.join(covered) or '未明显承接'}")
    status = "一致性较好" if all(item["status"] == "一致" for item in checks[:4]) else "存在需确认项"
    return {"status": status, "checks": checks, "recommendations": ["广告标题/主文案只使用落地页能承接的价格、折扣、功能。", "如视频出现防水、持久、不脱妆等功能，必须确认页面有明确承接。"]}


def build_editing_advice(notes: Dict[str, Any], extraction_data: Dict[str, Any], scores: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    duration = get_duration(extraction_data, notes)
    product_name = str(notes.get("product_name") or "产品").strip()
    weakest = [row["dimension"] for row in sorted(scores, key=lambda item: item["score"])[:3]]
    offer = str((notes.get("offer") or {}).get("detail") or notes.get("offer_detail") or "").strip()
    cta = str((notes.get("cta") or {}).get("detail") or notes.get("cta_detail") or "今すぐチェック").strip()
    short_cut = [
        {"time": "0-2s", "content": "强反差钩子：え、まだそのまま続けるの？", "purpose": "先让用户停手，不要先铺垫"},
        {"time": "2-5s", "content": f"产品近景：{product_name}", "purpose": "快速让用户知道卖什么"},
        {"time": "5-9s", "content": "使用过程/真人演示/核心卖点", "purpose": "建立功能理解"},
        {"time": "9-12s", "content": "效果/色号/套餐信息", "purpose": "给选择理由"},
        {"time": "12-15s", "content": f"价格/优惠 {offer} + CTA：{cta}", "purpose": "收口转化"},
    ]
    standard_cut = [
        {"time": "0-3s", "content": "痛点或反差钩子", "purpose": "提升停留"},
        {"time": "3-8s", "content": "产品结构/功能揭秘", "purpose": "解释为什么值得看"},
        {"time": "8-15s", "content": "使用演示 + 细节近景", "purpose": "补证明"},
        {"time": "15-21s", "content": "色号/规格/套餐", "purpose": "降低选择成本"},
        {"time": "21-25s", "content": f"价格、保障、{cta}", "purpose": "行动号召"},
    ]
    fixes: List[str] = []
    if "钩子强度" in weakest:
        fixes.append("把产品结果/价格/痛点前置到 0-2 秒，避免先出现无信息量空镜。")
    if "证明可信度" in weakest:
        fixes.append("补真人使用、前后对比或评论截图；没有证明会像纯卖货。")
    if "CTA压迫感" in weakest:
        fixes.append("结尾 3 秒固定出现：价格/优惠 + 保障 + 明确 CTA。")
    if duration > 35:
        fixes.append("当前视频偏长，建议先剪 15 秒强转化版用于冷启动测试。")
    if not fixes:
        fixes.append("当前结构可测，优先做 3 个不同前 3 秒钩子的 A/B 版本。")
    return {
        "short_15s": short_cut,
        "standard_25s": standard_cut,
        "priority_fixes": unique_keep_order(fixes),
        "cover_advice": ["封面优先选产品近景 + 使用效果同屏，不要纯产品静物。", "封面字控制在 10-16 个日文字符，例如：まだ何色も重ねてるの？", "如果有价格优势，封面角落可放 ¥价格 或 50%OFF，但不要遮挡产品。"],
    }


def build_jp_fashion_title_groups(tags: Sequence[str], tag_limit: int, product_hint: str = "") -> Dict[str, List[str]]:
    def tagged(text: str, tag: str = "") -> str:
        preferred = [tag] + [t for t in tags if t != tag] if tag else list(tags)
        return append_tags(text, preferred, tag_limit)

    is_denim = bool(re.search(r"デニム|denim|ジーンズ|ワイドパンツ", product_hint, flags=re.IGNORECASE))
    if not is_denim:
        return {
            "着用感共感型": [
                tagged("ラクなのに、ちゃんと見える"),
                tagged("着た時のシルエットが大事"),
                tagged("普段コーデにちょうどいい"),
                tagged("ゆるいのに、だらしなく見えない"),
                tagged("見た目よりずっとラク"),
            ],
            "購入前チェック型": [
                tagged("買う前にシルエットだけ見て"),
                tagged("サイズ選びで失敗する前に"),
                tagged("写真だけで選ぶ前に見て"),
                tagged("着回しできるか先に確認"),
                tagged("気になる人は詳細チェック"),
            ],
        }

    return {
        "スクロール停止型": [
            tagged("え、これ本当にデニム？", "#デニム"),
            tagged("夏にデニム無理って思ってた", "#夏コーデ"),
            tagged("この揺れ方、デニムっぽくない", "#ワイドパンツ"),
            tagged("普通のデニムと見え方が違う", "#デニム"),
            tagged("ワイドなのに重く見えないの反則", "#ワイドパンツ"),
        ],
        "買う前確認型": [
            tagged("買う前に、この落ち感だけ見て", "#購入前チェック"),
            tagged("写真だけで選ぶ前にシルエット見て", "#購入前チェック"),
            tagged("ワイドパンツ選びで失敗する前に", "#ワイドパンツ"),
            tagged("ハイウエスト派ならここ見て", "#ハイウエスト"),
            tagged("夏用デニム探してるなら先に見て", "#夏服"),
        ],
        "悩み共感型": [
            tagged("夏のデニム、重いと思ってた人へ", "#夏コーデ"),
            tagged("デニムのゴワつき苦手な人へ", "#デニム"),
            tagged("脚のライン拾うパンツ苦手なら", "#レディースパンツ"),
            tagged("ワイドパンツが野暮ったく見える人へ", "#ワイドパンツ"),
            tagged("ラクだけど手抜きに見せたくない日", "#大人カジュアル"),
        ],
        "落ち感反差型": [
            tagged("デニムなのに、とろっと落ちる", "#デニム"),
            tagged("動くたび、ふわっと揺れる感じ", "#大人カジュアル"),
            tagged("この落ち感、思ったよりきれい", "#ワイドパンツ"),
            tagged("サラッと履けるデニム探してた", "#夏服"),
            tagged("見た目よりずっと軽く見える", "#デニム"),
        ],
        "シルエット訴求型": [
            tagged("なんか、脚のラインきれいに見える", "#脚長見え"),
            tagged("ゆるいのに、だらしなく見えない", "#大人カジュアル"),
            tagged("これ一本でゆるっときれい見え", "#着回し"),
            tagged("ハイウエストでバランス取りやすい", "#ハイウエスト"),
            tagged("大人っぽく履けるワイドデニム", "#ワイドパンツ"),
        ],
        "軽CTA型": [
            tagged("気になる人は詳細だけ見て", "#デニム"),
            tagged("夏コーデに合うか先に確認", "#夏コーデ"),
            tagged("普段着に使えるか動画で見て", "#着回し"),
            tagged("ラフなのに上品、これ気になる", "#大人カジュアル"),
            tagged("詳細見る前に動き方だけ見て", "#購入前チェック"),
        ],
    }


def build_jp_fashion_descriptions(product_hint: str, offer_line: str, config: Dict[str, Any]) -> List[str]:
    return [
        "最初の3秒は『え、これ本当にデニム？』で止めて、落ち感の映像にすぐつなぐ。",
        "売り込みより先に、歩いた時の揺れ・ハイウエストの見え方・横からのシルエットを見せる。",
        "『マイナス5kg』など強い断定は避けて、『すっきり見え』『脚長見え』に置き換える。",
        f"結尾は説明を増やさず『気になる人は{config['cta_more']}』で軽く押す。{offer_line}".strip(),
        "封面は全身シルエット＋短い一言。例：え、これデニム？",
    ]


def build_jp_fashion_bodies(product_hint: str, benefit_hint: str, second_benefit_hint: str, proof_hint: str, offer_line: str, config: Dict[str, Any]) -> Dict[str, str]:
    return {
        "short": "\n\n".join([
            "え、これ本当にデニム？",
            "とろっと落ちるシルエットで、夏でも重く見えにくい。",
            f"気になる人は{config['cta_more']}👀",
        ]),
        "standard": "\n".join([
            "夏のデニム、重いと思ってた人へ。",
            "",
            "サラッとした落ち感で、ラフなのに上品見え。",
            "歩いた時の揺れ方と、ハイウエストのシルエットを先に見て。",
            "",
            offer_line or "気になる人は詳細をチェック。",
            f"👇 {config['cta_more']}",
        ]).strip(),
        "hard_sell": "\n".join([
            "写真だけでワイドデニム選ぶ前に見て。",
            "",
            "デニムなのに、とろっと落ちる感じ。",
            "ゆるいのに、だらしなく見えにくい。",
            "夏コーデに合わせやすい一本。",
            "",
            offer_line or "今の条件は詳細で確認。",
            f"気になる人は先に{config['cta_more']}。",
        ]).strip(),
    }


def build_jp_copy(notes: Dict[str, Any], category: str, config: Dict[str, Any]) -> Dict[str, Any]:
    landing = notes.get("landing_page") if isinstance(notes.get("landing_page"), dict) else {}
    landing_product_name = str(landing.get("product_name_guess") or "").strip()
    product_name = str(notes.get("product_name") or landing_product_name or "この商品").strip()
    pain_points = as_list(notes.get("pain_points"))
    selling_points = as_list(notes.get("selling_points"))
    proof_points = as_list(notes.get("proof"))
    audience = str(notes.get("target_audience") or "気になる人").strip()
    offer_detail = get_offer_detail(notes)
    has_sale_price = notes.get("price_sale") not in (None, "")
    has_original_price = notes.get("price_original") not in (None, "")
    sale_price = format_price(notes.get("price_sale"), "jp") if has_sale_price else ""
    original_price = format_price(notes.get("price_original"), "jp") if has_original_price else ""
    intensity = get_title_intensity(notes)

    category_map = {
        "beauty": {
            "product": "コスメ",
            "pain": "メイクの悩み",
            "benefit": "時短",
            "benefit2": "仕上がり",
            "proof": "レビュー",
        },
        "fashion": {
            "product": "ファッションアイテム",
            "pain": "着た時の悩み",
            "benefit": "見え方",
            "benefit2": "合わせやすさ",
            "proof": "着用シーン",
        },
        "home": {
            "product": "便利グッズ",
            "pain": "手間",
            "benefit": "時短",
            "benefit2": "使いやすさ",
            "proof": "使用シーン",
        },
        "food": {
            "product": "商品",
            "pain": "小腹",
            "benefit": "手軽さ",
            "benefit2": "満足感",
            "proof": "食べた感想",
        },
        "oral_care": {
            "product": "インスタントスマイル",
            "pain": "笑う時の口元",
            "benefit": "自然な見え方",
            "benefit2": "自宅で試しやすい",
            "proof": "装着シーン",
        },
        "general": {
            "product": "この商品",
            "pain": "悩み",
            "benefit": "使いやすさ",
            "benefit2": "わかりやすさ",
            "proof": "レビュー",
        },
    }
    labels = category_map.get(category, category_map["general"])
    category_defaults = {
        "beauty": {
            "pain": ["メイクが面倒", "時間が足りない"],
            "selling": ["使いやすい", "毎日続けやすい"],
            "proof": ["使用シーン"],
        },
        "fashion": {
            "pain": ["締めつけが苦手", "ラインが気になる"],
            "selling": ["着心地がラク", "毎日合わせやすい"],
            "proof": ["着用シーン"],
        },
        "home": {
            "pain": ["手間がかかる", "片付けが面倒"],
            "selling": ["使いやすい", "時短しやすい"],
            "proof": ["使用シーン"],
        },
        "food": {
            "pain": ["小腹が気になる", "おやつ選びに迷う"],
            "selling": ["手軽に楽しめる", "続けやすい"],
            "proof": ["食べた感想"],
        },
        "oral_care": {
            "pain": ["笑う時の口元が気になる", "食事の時に不安がある"],
            "selling": ["自然な見え方", "自宅で試しやすい"],
            "proof": ["装着シーン", "食事シーン"],
        },
        "general": {
            "pain": ["悩みがある", "買ってから後悔したくない"],
            "selling": ["使いやすい", "わかりやすい"],
            "proof": ["レビュー"],
        },
    }
    defaults = category_defaults.get(category, category_defaults["general"])
    pain_points = pain_points or defaults["pain"]
    selling_points = selling_points or defaults["selling"]
    proof_points = proof_points or defaults["proof"]
    pain = pain_points[0]
    benefit = selling_points[0]
    second_benefit = selling_points[1] if len(selling_points) > 1 else benefit
    proof = proof_points[0]
    tags = {
        "beauty": ["#コスメ", "#時短メイク", "#メイク"],
        "fashion": ["#夏コーデ", "#デニム", "#ワイドパンツ", "#大人カジュアル", "#脚長見え", "#着回し", "#夏服", "#ハイウエスト", "#レディースパンツ", "#購入前チェック"],
        "home": ["#便利グッズ", "#暮らし", "#時短"],
        "food": ["#グルメ", "#おやつ", "#新商品"],
        "oral_care": ["#インスタントスマイル", "#入れ歯", "#口元ケア"],
        "general": ["#TikTok商品", "#話題", "#おすすめ"],
    }.get(category, ["#TikTok商品", "#話題", "#おすすめ"])
    tag_limit = int((get_copy_requirements(notes).get("title_hashtag_count") or notes.get("title_hashtag_count") or 3))
    tag_limit = max(1, min(tag_limit, 3))
    angles = HOOK_ANGLES.get(category, HOOK_ANGLES["general"])

    product_hint = jp_fragment(product_name, labels["product"])
    pain_hint = jp_fragment(pain, labels["pain"])
    benefit_hint = jp_fragment(benefit, labels["benefit"])
    second_benefit_hint = jp_fragment(second_benefit, labels["benefit2"])
    proof_hint = jp_fragment(proof, labels["proof"])
    offer_hint = jp_fragment(offer_detail, "今だけの条件")
    audience_hint = jp_fragment(audience, "気になる人")

    def variant(safe: str, aggressive: str, hard_sell: str) -> str:
        if intensity == "safe":
            return safe
        if intensity == "hard_sell":
            return hard_sell
        return aggressive

    def tagged(text: str) -> str:
        return append_tags(text, tags, tag_limit)

    title_groups = {
        "買う前確認型": [
            tagged("買う前にこれだけ見て"),
            tagged(f"{product_hint}、買う前にここ確認"),
            tagged(f"高い{labels['product']}買う前にチェック"),
            tagged(f"{pain_hint}なら先に見て"),
            tagged("レビュー前にここだけ確認"),
            tagged(variant("気になる人だけ見て", "買う前にこれだけ見て", "買う前にこれだけ見て")),
        ],
        "損失回避型": [
            tagged(variant("まだそれで我慢してる？", "まだそれで損してるかも", "そのままだと後悔しやすい")),
            tagged(variant("気づかないうちに遠回りしてるかも", "知らないと後悔しやすいポイント", "今さら知ると損しやすい")),
            tagged(variant(f"{pain_hint}で迷ってる人へ", f"{pain_hint}で損してるかも", f"{pain_hint}を放置すると遠回り")),
            tagged(variant(f"{benefit_hint}を先に知っておけばよかった", f"{benefit_hint}を先に知っておけばよかった", f"{benefit_hint}を知らないと損")),
            tagged("正直、期待してなかった"),
            tagged(f"{audience_hint}だけ見て"),
        ],
        "反転驚き型": [
            tagged(f"{angles['contrast'][0]}"),
            tagged(f"{angles['contrast'][1]}"),
            tagged(f"{angles['curiosity'][0]}"),
            tagged(f"{angles['curiosity'][1]}"),
            tagged(f"え、{product_hint}ってこうなの？"),
            tagged("レビューより先に見て"),
        ],
        "証明前置型": [
            tagged(f"{proof_hint}で見えたこと"),
            tagged(f"{proof_hint}を先に見て"),
            tagged("レビューで多かった悩み"),
            tagged(f"{product_hint}の違い、ここだった"),
            tagged("使ってみたら意外だった"),
            tagged(f"{product_hint}の実力、先に確認"),
        ],
        "価格オファー型": [
            tagged(f"{original_price}→{sale_price}、今だけチェック" if has_sale_price and has_original_price else "価格は詳細で確認"),
            tagged(f"{offer_hint}"),
            tagged("買う前に価格だけ確認"),
            tagged("今の条件、先に見て"),
            tagged("お得条件は詳細で確認"),
            tagged("特典があるうちに見て"),
        ],
        "緊迫限定型": [
            tagged("見逃し注意"),
            tagged("気になるなら早めにチェック"),
            tagged("今だけなら先に見て"),
            tagged("後でいいや、で損しやすい"),
            tagged("比較するなら今のうち"),
            tagged(variant("気になる人は保存", "気になるなら早めにチェック", "今すぐ確認")),
        ],
    }

    if category == "oral_care":
        title_groups = {
            "口元痛点型": [
                tagged("笑う時、口元隠してない？"),
                tagged("写真で口閉じがちな人へ"),
                tagged("食事の時ちょっと気になる人へ"),
                tagged("そのまま隠してるの、もったいない"),
                tagged("口元の印象、先に見て"),
                tagged("気になる人だけ見て"),
            ],
            "反差証明型": [
                tagged("入れ歯っぽく見えないの、正直ずるい"),
                tagged("ちょっと待って、装着後の差が強い"),
                tagged("普通に笑った時の見え方が違う"),
                tagged("食事シーンまで見せるの気になる"),
                tagged("買う前に装着シーンだけ見て"),
                tagged("レビューより先に見て"),
            ],
            "損失回避型": [
                tagged(variant("そのまま我慢してる？", "まだ口元を隠してる？", "そのままだと後悔しやすい")),
                tagged(variant("気づかないうちに遠回りしてるかも", "知らないと後悔しやすいポイント", "今さら知ると損しやすい")),
                tagged(variant("口元の悩みで迷ってる人へ", "口元の悩みで損してるかも", "口元の悩みを放置すると遠回り")),
                tagged(variant("自然な見え方を先に知っておけばよかった", "自然な見え方を先に見ておけばよかった", "自然な見え方を知らないと損")),
                tagged("正直、期待してなかった"),
                tagged("気になる人だけ見て"),
            ],
            "証明前置型": [
                tagged("装着シーンで見えたこと"),
                tagged("食事シーンを先に見て"),
                tagged("レビューで多かった悩み"),
                tagged("自然な見え方、ここだった"),
                tagged("自宅で試しやすいの助かる"),
                tagged("この商品の実力、先に確認"),
            ],
            "価格オファー型": [
                tagged(f"{original_price}→{sale_price}、今だけチェック" if has_sale_price and has_original_price else "前払いなしで試せるの、先に見て"),
                tagged(f"{offer_hint}"),
                tagged("買う前に価格だけ確認"),
                tagged("今の条件、先に見て"),
                tagged("お得条件は詳細で確認"),
                tagged("特典があるうちに見て"),
            ],
            "緊迫限定型": [
                tagged("見逃し注意"),
                tagged("気になるなら早めにチェック"),
                tagged("今だけなら先に見て"),
                tagged("後でいいや、で損しやすい"),
                tagged("比較するなら今のうち"),
                tagged("気になる人は保存"),
            ],
        }

    if category == "fashion":
        title_groups = build_jp_fashion_title_groups(tags, tag_limit, product_hint)

    all_titles = unique_keep_order([title for group in title_groups.values() for title in group])
    if category == "oral_care":
        top_titles = unique_keep_order([
            title_groups["口元痛点型"][0],
            title_groups["反差証明型"][0],
            title_groups["損失回避型"][2],
            title_groups["証明前置型"][0],
            title_groups["価格オファー型"][0],
        ])
    elif category == "fashion":
        top_titles = unique_keep_order([
            title_groups["スクロール停止型"][0],
            title_groups["買う前確認型"][0],
            title_groups["悩み共感型"][0],
            title_groups["落ち感反差型"][0],
            title_groups["シルエット訴求型"][0],
        ])
    else:
        top_titles = unique_keep_order([
            title_groups["買う前確認型"][0],
            title_groups["損失回避型"][1],
            title_groups["反転驚き型"][0],
            title_groups["証明前置型"][0],
            title_groups["価格オファー型"][0],
        ])

    price_line = ""
    if has_sale_price and has_original_price:
        price_line = f"通常価格 {original_price}、今は {sale_price}。"
    elif has_sale_price:
        price_line = f"今の価格は {sale_price}。"
    elif has_original_price:
        price_line = f"参考価格は {original_price}。"

    offer_line = f"{offer_detail}。" if offer_detail else ""
    source_script = extract_video_script(notes)
    risky_script_claims = detect_risky_script_claims(source_script)
    short_tk_copies = build_jp_short_tk_copies(notes, category, product_hint, pain_hint, benefit_hint, proof_hint, offer_hint)

    descriptions = [
        f"{pain_hint}を感じていた人に。{product_hint}なら、{benefit_hint}。",
        f"{proof_hint}を見せる構成で、広告感を抑えつつクリック理由を作る。",
        f"{price_line}{offer_line} 買う前に迷っている人ほど反応しやすい設計にする。",
        f"{audience_hint}に向けて、最初の3秒は反差・損失・買う前確認で止めるのがおすすめ。",
        f"詳しくは {config['cta_profile']}。{config['cta_primary']}。",
    ]
    short_price = price_line or "価格はプロフィールで確認"
    bodies = {
        "short": "\n\n".join([
            "え、まだそのまま続けるの？",
            f"{product_hint}なら、{benefit_hint}。",
            short_price,
            f"👇 {config['cta_more']}",
        ]),
        "standard": "\n".join([
            f"{pain_hint}で迷っていた人へ。",
            "",
            f"{product_hint}は、{benefit_hint}。さらに{second_benefit_hint}。",
            f"{proof_hint}で見せると、ひと目で伝わりやすい構成に。",
            "",
            price_line or "価格は詳細で確認。",
            offer_line or "",
            "",
            f"👇 {config['cta_profile']}",
        ]).strip(),
        "hard_sell": "\n".join([
            "正直、これは見逃し注意。",
            "",
            f"{pain_hint}をそのままにしていませんか？",
            f"{product_hint}なら、{benefit_hint}。",
            f"さらに{second_benefit_hint}。",
            "",
            f"✅ {benefit_hint}",
            f"✅ {second_benefit_hint}",
            f"✅ {proof_hint}",
            "",
            price_line or "価格は詳細で確認。",
            offer_line or "",
            "",
            f"気になるなら、先に {config['cta_profile']} で確認。",
        ]).strip(),
    }
    if category == "fashion":
        descriptions = build_jp_fashion_descriptions(product_hint, offer_line, config)
        bodies = build_jp_fashion_bodies(product_hint, benefit_hint, second_benefit_hint, proof_hint, offer_line, config)
    ctas = [
        config["cta_primary"],
        f"{config['cta_more']}で確認",
        "買う前にチェック",
        f"{config['cta_profile']} で見る",
        "気になるなら先に見る",
    ]

    return {
        "titles": all_titles[:30],
        "top_titles": top_titles,
        "title_groups": {key: unique_keep_order(value) for key, value in title_groups.items()},
        "descriptions": unique_keep_order(descriptions)[:5],
        "bodies": bodies,
        "tk_short_copies": short_tk_copies,
        "script_claims_removed": risky_script_claims,
        "ctas": unique_keep_order(ctas)[:5],
        "hashtags": tags,
        "title_intensity": intensity,
        "copy_rules": [
            "标题优先写用户状态、损失厌恶、买前确认和证明前置，不要一上来说明书式介绍。",
            "默认强度为 aggressive，可在 notes.copy_requirements.title_intensity 中切换 safe / aggressive / hard_sell。",
            "价格、折扣、功能只使用 notes 或落地页确认的信息，不编造库存、销量和夸大功效。",
            "日本市场尽量避免过度命令式，多用『かも』『見て』『チェック』降低冒犯感。",
            "标题末尾默认带 2-3 个 #关键词；可用 notes.copy_requirements.title_hashtag_count 控制为 1-3 个。",
            "如果 notes 里提供了视频文案或旁白，优先抽成 100 字以内的 TikTok 正文，不要逐句直译。",
            "短文案里可加入 1-3 个 emoji，但不要把 emoji 当成句子主体。",
            "出现销量、认证、医师推荐、100% 等高风险说法时，必须先过滤再输出。",
        ],
    }


def build_copy(notes: Dict[str, Any], market: str) -> Dict[str, Any]:
    category = infer_category(notes)
    if market == "jp":
        return build_jp_copy(notes, category, MARKET_CONFIG[market])
    if market == "th":
        return build_th_copy(notes, category, MARKET_CONFIG[market])
    return build_id_copy(notes, category, MARKET_CONFIG[market])


def build_th_copy(notes: Dict[str, Any], category: str, config: Dict[str, Any]) -> Dict[str, Any]:
    product_name = str(notes.get("product_name") or "สินค้านี้").strip()
    pain_points = as_list(notes.get("pain_points")) or ["ปัญหานี้"]
    selling_points = as_list(notes.get("selling_points")) or ["ใช้งานง่าย", "สะดวกขึ้น"]
    proof_points = as_list(notes.get("proof")) or ["รีวิวจริง"]
    audience = str(notes.get("target_audience") or "คนที่กำลังมองหาอยู่").strip()
    offer_detail = get_offer_detail(notes)
    sale_price = format_price_if_present(notes.get("price_sale"), "th")
    original_price = format_price_if_present(notes.get("price_original"), "th")
    intensity = get_title_intensity(notes)
    has_prices = bool(sale_price or original_price)
    has_offer = has_offer_evidence(notes)

    product = th_name_fragment(product_name, "สินค้านี้")
    pain = th_fragment(pain_points[0], "ปัญหานี้")
    benefit = th_fragment(selling_points[0], "ใช้งานง่าย")
    second_benefit = th_fragment(selling_points[1] if len(selling_points) > 1 else selling_points[0], "สะดวกขึ้น")
    proof = th_fragment(proof_points[0], "รีวิวจริง")
    audience_hint = th_fragment(audience, "คนที่กำลังมองหาอยู่")
    offer_hint = th_fragment(offer_detail, "โปรนี้")

    def variant(safe: str, aggressive: str, hard_sell: str) -> str:
        if intensity == "safe":
            return safe
        if intensity == "hard_sell":
            return hard_sell
        return aggressive

    tags = {
        "beauty": ["#บิวตี้", "#TikTok", "#ของดี"],
        "fashion": ["#แฟชั่น", "#ของดี", "#TikTok"],
        "home": ["#ของใช้ดีๆ", "#ชีวิตง่ายขึ้น", "#TikTok"],
        "food": ["#ของกิน", "#อร่อย", "#TikTok"],
        "general": ["#TikTokFinds", "#ของดี", "#ต้องมี"],
    }.get(category, ["#TikTokFinds", "#ของดี", "#ต้องมี"])

    def tagged(text: str) -> str:
        return append_tags(text, tags)

    price_line = ""
    if sale_price and original_price:
        price_line = f"ราคาเดิม {original_price} ตอนนี้ {sale_price}"
    elif sale_price:
        price_line = f"ตอนนี้ {sale_price}"
    elif original_price:
        price_line = f"ราคาอ้างอิง {original_price}"

    title_groups = {
        "ก่อนซื้อเช็กก่อน": [
            tagged("ก่อนซื้อ ลองเช็กอันนี้"),
            tagged(f"{product} ก่อนซื้อควรรู้"),
            tagged(f"{pain}อยู่ใช่ไหม ลองดู"),
            tagged("ซื้อก่อนดูทีหลังมักพลาด"),
            tagged("รีวิวก่อนตัดสินใจ"),
            tagged(variant("คนที่กำลังดูอยู่", "ก่อนซื้อ ลองเช็กอันนี้", "ก่อนซื้อ ลองเช็กอันนี้")),
        ],
        "หลีกเลี่ยงความพลาด": [
            tagged(variant("ยังใช้วิธีเดิมอยู่ไหม", "ยังเสียเวลาจากเรื่องเดิมอยู่ไหม", "ปล่อยไว้แบบเดิมอาจเสียโอกาส")),
            tagged(variant(f"{pain} ทำให้ลำบากอยู่หรือเปล่า", f"ถ้ายังเจอ {pain} อยู่ ลองดู", f"ถ้ายังเจอ {pain} อยู่ อย่าพลาด")),
            tagged(variant("รู้ก่อนซื้อ จะได้ไม่พลาด", "รู้ก่อนซื้อ จะได้ไม่เสียเงิน", "รู้ก่อนซื้อ จะได้ไม่เสียเวลา")),
            tagged("อย่าเพิ่งซื้อถ้ายังไม่ดูคลิปนี้"),
            tagged(f"{audience_hint}ควรดู"),
            tagged("ซื้อผิดชิ้นทีเดียวคุ้มไหม"),
        ],
        "กลับตาลปัตร": [
            tagged(f"ทำไมคนถึงเปลี่ยนมาใช้ {product}"),
            tagged("ตอนแรกไม่คิดว่าจะต่างขนาดนี้"),
            tagged(f"{proof} แล้วเข้าใจทันที"),
            tagged("ของธรรมดาที่ไม่ธรรมดา"),
            tagged("ลองแล้วถึงรู้ว่าต่าง"),
            tagged("รีวิวแล้วค่อยตัดสินใจ"),
        ],
        "ราคาและโปร": [
            tagged(f"{price_line} ลองเช็กก่อน" if price_line else "ราคาดีแค่ไหนต้องดูเอง"),
            tagged(f"{offer_hint}"),
            tagged("ก่อนซื้อ ลองดูโปรนี้"),
            tagged("โปรคุ้มไหม เช็กก่อน"),
            tagged("ถ้าจะซื้อ ดูราคาก่อน"),
            tagged("อย่าซื้อก่อนเห็นโปร"),
        ],
        "ยืนยันด้วยหลักฐาน": [
            tagged(f"{proof} ที่เห็นแล้วเข้าใจ"),
            tagged("รีวิวจริงก่อนตัดสินใจ"),
            tagged("คนใช้จริงพูดไว้แบบนี้"),
            tagged(f"{product} ต่างจากที่คิด"),
            tagged(f"{proof} ทำให้ดูน่าเชื่อขึ้น"),
            tagged("ดูหลักฐานก่อนซื้อ"),
        ],
        "เร่งเบาๆ": [
            tagged("ถ้ากำลังจะซื้อ ลองดูคลิปนี้"),
            tagged("เช็กก่อนจะได้ไม่เสียเงิน"),
            tagged("อย่าซื้อก่อนดูอันนี้"),
            tagged("ของดีควรดูให้ครบ"),
            tagged("ถ้ากำลังลังเล ลองดู"),
            tagged("ตอนนี้แค่เช็กก่อน"),
        ],
    }

    all_titles = unique_keep_order([title for group in title_groups.values() for title in group])
    top_titles = unique_keep_order([
        title_groups["ก่อนซื้อเช็กก่อน"][0],
        title_groups["หลีกเลี่ยงความพลาด"][1],
        title_groups["กลับตาลปัตร"][0],
        title_groups["ยืนยันด้วยหลักฐาน"][0],
        title_groups["ราคาและโปร"][0],
    ])

    descriptions = [
        f"ถ้าคุณกำลังเจอ {pain} ลองดู {product} ที่ช่วยให้ {benefit}",
        f"{proof} ช่วยให้ภาพรวมดูน่าเชื่อขึ้น และลดความรู้สึกเหมือนโฆษณา",
        f"{price_line or 'ราคาควรเช็กในโปรไฟล์'} {offer_detail}".strip(),
        f"{audience_hint} เหมาะกับการเปิดด้วยคำถาม การเปรียบเทียบ และการชวนเช็กก่อนซื้อ",
        f"ดูรายละเอียดเพิ่มที่ {config['cta_profile']} — {config['cta_primary']}",
    ]
    bodies = {
        "short": "\n".join([
            "ก่อนซื้อ ลองเช็กอันนี้",
            "",
            f"{product} ช่วยให้ {benefit}",
            price_line or "ราคาดูในโปรไฟล์",
            "",
            f"👇 {config['cta_more']}",
        ]).strip(),
        "standard": "\n".join([
            f"{pain} อยู่ใช่ไหม?",
            "",
            f"{product} เด่นเรื่อง {benefit} และ {second_benefit}",
            f"มี {proof} ช่วยเพิ่มความน่าเชื่อถือ",
            "",
            price_line or "ราคาควรเช็กก่อนตัดสินใจ",
            offer_detail or "",
            "",
            f"👇 {config['cta_profile']}",
        ]).strip(),
        "hard_sell": "\n".join([
            "ถ้าอยากซื้อ อย่าเพิ่งรีบ",
            "",
            f"{pain} ถ้ายังเจออยู่ ลองดู {product}",
            f"ช่วยให้ {benefit} และ {second_benefit}",
            "",
            f"✅ {benefit}",
            f"✅ {second_benefit}",
            f"✅ {proof}",
            "",
            price_line or "ราคาควรเช็กเอง",
            offer_detail or "",
            "",
            f"ถ้าสนใจ ไปเช็กที่ {config['cta_profile']}",
        ]).strip(),
    }
    ctas = [
        config["cta_primary"],
        f"{config['cta_more']}ก่อนซื้อ",
        "เช็กราคาก่อน",
        f"{config['cta_profile']} เพื่อดูรายละเอียด",
        "ถ้ากำลังลังเล ลองดู",
    ]

    copy_rules = [
        "标题优先做买前确认、避坑、反转、证明前置，不要一上来说明书式介绍。",
        "没有价格/优惠证据时，不写默认价格、库存、倒计时或『买完会更划算』。",
        "默认强度为 aggressive，可在 notes.copy_requirements.title_intensity 中切换 safe / aggressive / hard_sell。",
        "如果是泰语素材，尽量让旁白/字幕/标题语言一致，不要混入中文口吻。",
    ]
    if has_prices:
        copy_rules.append("只有 notes 或落地页确认了价格，才写价格对比。")
    if has_offer:
        copy_rules.append("只有 notes 或落地页确认了优惠，才写优惠刺激。")

    return {
        "titles": all_titles[:30],
        "top_titles": top_titles,
        "title_groups": {key: unique_keep_order(value) for key, value in title_groups.items()},
        "descriptions": unique_keep_order(descriptions)[:5],
        "bodies": bodies,
        "ctas": unique_keep_order(ctas)[:5],
        "hashtags": tags,
        "title_intensity": intensity,
        "copy_rules": unique_keep_order(copy_rules),
    }


def build_id_copy(notes: Dict[str, Any], category: str, config: Dict[str, Any]) -> Dict[str, Any]:
    product_name = str(notes.get("product_name") or "produk ini").strip()
    pain_points = as_list(notes.get("pain_points")) or ["masalah ini"]
    selling_points = as_list(notes.get("selling_points")) or ["lebih praktis", "lebih nyaman"]
    proof_points = as_list(notes.get("proof")) or ["review asli"]
    audience = str(notes.get("target_audience") or "orang yang lagi cari").strip()
    offer_detail = get_offer_detail(notes)
    sale_price = format_price_if_present(notes.get("price_sale"), "id")
    original_price = format_price_if_present(notes.get("price_original"), "id")
    intensity = get_title_intensity(notes)
    has_prices = bool(sale_price or original_price)
    has_offer = has_offer_evidence(notes)

    product = id_fragment(product_name, "produk ini")
    pain = id_fragment(pain_points[0], "masalah ini")
    benefit = id_fragment(selling_points[0], "lebih praktis")
    second_benefit = id_fragment(selling_points[1] if len(selling_points) > 1 else selling_points[0], "lebih nyaman")
    proof = id_fragment(proof_points[0], "review asli")
    audience_hint = id_fragment(audience, "orang yang lagi cari")
    offer_hint = id_fragment(offer_detail, "promo ini")

    def variant(safe: str, aggressive: str, hard_sell: str) -> str:
        if intensity == "safe":
            return safe
        if intensity == "hard_sell":
            return hard_sell
        return aggressive

    tags = {
        "beauty": ["#BeautyTok", "#Skincare", "#TikTokFinds"],
        "fashion": ["#OOTD", "#Fashion", "#TikTokFinds"],
        "home": ["#HomeHack", "#UsefulFinds", "#TikTokFinds"],
        "food": ["#FoodTok", "#Snack", "#TikTokFinds"],
        "general": ["#TikTokFinds", "#WajibCek", "#ProdukBagus"],
    }.get(category, ["#TikTokFinds", "#WajibCek", "#ProdukBagus"])

    def tagged(text: str) -> str:
        return append_tags(text, tags)

    price_line = ""
    if sale_price and original_price:
        price_line = f"Harga normal {original_price}, sekarang {sale_price}"
    elif sale_price:
        price_line = f"Sekarang {sale_price}"
    elif original_price:
        price_line = f"Harga referensi {original_price}"

    title_groups = {
        "cek sebelum beli": [
            tagged("Sebelum beli, cek ini dulu"),
            tagged(f"{product}, cek dulu sebelum beli"),
            tagged(f"Kalau lagi cari {product}, lihat ini"),
            tagged(f"{pain} masih bikin ribet?"),
            tagged("Cek review dulu baru putuskan"),
            tagged(variant("Kalau lagi cari produk baru", "Sebelum beli, cek ini dulu", "Sebelum beli, cek ini dulu")),
        ],
        "hindari salah beli": [
            tagged(variant("Masih pakai cara lama?", "Masih buang waktu untuk hal yang sama?", "Kalau dibiarkan bisa rugi waktu")),
            tagged(variant(f"{pain} bikin repot?", f"Kalau masih kena {pain}, coba lihat", f"Kalau masih kena {pain}, jangan salah pilih")),
            tagged(variant("Biar nggak salah beli", "Biar nggak nyesel setelah beli", "Biar nggak buang uang")),
            tagged("Jangan beli dulu sebelum lihat ini"),
            tagged(f"{audience_hint} cocok lihat"),
            tagged("Sekali salah pilih malah repot"),
        ],
        "efek balik": [
            tagged(f"Kenapa banyak yang pindah ke {product}"),
            tagged("Awalnya nggak nyangka bedanya sejauh ini"),
            tagged(f"{proof} bikin paham"),
            tagged("Barang biasa yang ternyata beda"),
            tagged("Coba dulu baru ngerti"),
            tagged("Review dulu baru yakin"),
        ],
        "harga dan promo": [
            tagged(f"{price_line} kalau mau cek dulu" if price_line else "Harga cek di detail"),
            tagged(f"{offer_hint}"),
            tagged("Sebelum beli, cek promo ini"),
            tagged("Promo ini layak dilihat"),
            tagged("Kalau mau beli, lihat harga dulu"),
            tagged("Jangan skip sebelum lihat promo"),
        ],
        "bukti dulu": [
            tagged(f"{proof} yang bikin lebih yakin"),
            tagged("Review asli sebelum beli"),
            tagged("Orang yang sudah pakai bilang begini"),
            tagged(f"{product} ternyata beda"),
            tagged(f"{proof} membantu percaya"),
            tagged("Lihat bukti dulu baru beli"),
        ],
        "dorong ringan": [
            tagged("Kalau mau beli, lihat ini dulu"),
            tagged("Cek dulu biar nggak rugi"),
            tagged("Jangan beli sebelum tahu ini"),
            tagged("Kalau masih ragu, tonton dulu"),
            tagged("Produk bagus itu harus dicek"),
            tagged("Sekarang tinggal cek cepat"),
        ],
    }

    all_titles = unique_keep_order([title for group in title_groups.values() for title in group])
    top_titles = unique_keep_order([
        title_groups["cek sebelum beli"][0],
        title_groups["hindari salah beli"][1],
        title_groups["efek balik"][0],
        title_groups["bukti dulu"][0],
        title_groups["harga dan promo"][0],
    ])

    descriptions = [
        f"Kalau kamu lagi kena {pain}, coba lihat {product} yang bantu {benefit}.",
        f"{proof} bikin pesan terasa lebih nyata dan nggak terlalu seperti iklan.",
        f"{price_line or 'Harga sebaiknya dicek di detail'} {offer_detail}".strip(),
        f"{audience_hint} biasanya lebih responsif ke format cek sebelum beli, bukan penjelasan panjang.",
        f"Lihat detail lengkap di {config['cta_profile']} — {config['cta_primary']}.",
    ]
    bodies = {
        "short": "\n".join([
            "Sebelum beli, cek ini dulu",
            "",
            f"{product} bantu {benefit}",
            price_line or "Harga cek di detail",
            "",
            f"👇 {config['cta_more']}",
        ]).strip(),
        "standard": "\n".join([
            f"{pain} masih terasa?",
            "",
            f"{product} unggul di {benefit} dan {second_benefit}",
            f"Ada {proof} buat bantu trust.",
            "",
            price_line or "Harga cek dulu sebelum ambil keputusan",
            offer_detail or "",
            "",
            f"👇 {config['cta_profile']}",
        ]).strip(),
        "hard_sell": "\n".join([
            "Kalau mau beli, jangan buru-buru.",
            "",
            f"Masih kena {pain}?",
            f"{product} bantu {benefit} dan {second_benefit}.",
            "",
            f"✅ {benefit}",
            f"✅ {second_benefit}",
            f"✅ {proof}",
            "",
            price_line or "Harga cek dulu",
            offer_detail or "",
            "",
            f"Kalau tertarik, buka {config['cta_profile']}",
        ]).strip(),
    }
    ctas = [
        config["cta_primary"],
        f"{config['cta_more']} dulu",
        "Cek harga dulu",
        f"{config['cta_profile']} untuk detail",
        "Kalau ragu, lihat dulu",
    ]

    copy_rules = [
        "标题优先做买前确认、避坑、反转、证明前置，不要一上来说明书式介绍。",
        "没有价格/优惠证据时，不写默认价格、库存、倒计时或『买完会更划算』。",
        "默认强度为 aggressive，可在 notes.copy_requirements.title_intensity 中切换 safe / aggressive / hard_sell。",
        "如果是印尼素材，尽量让旁白/字幕/标题语言一致，不要混入中文口吻。",
    ]
    if has_prices:
        copy_rules.append("只有 notes 或落地页确认了价格，才写价格对比。")
    if has_offer:
        copy_rules.append("只有 notes 或落地页确认了优惠，才写优惠刺激。")

    return {
        "titles": all_titles[:30],
        "top_titles": top_titles,
        "title_groups": {key: unique_keep_order(value) for key, value in title_groups.items()},
        "descriptions": unique_keep_order(descriptions)[:5],
        "bodies": bodies,
        "ctas": unique_keep_order(ctas)[:5],
        "hashtags": tags,
        "title_intensity": intensity,
        "copy_rules": unique_keep_order(copy_rules),
    }


def build_ab_tests(score_rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    weakest = sorted(score_rows, key=lambda item: item["score"])[:4]
    matrix: List[Dict[str, Any]] = []
    for row in weakest:
        variants = AB_TEST_LIBRARY.get(row["dimension"], ("版本A", "版本B", "版本C"))
        matrix.append(
            {
                "variable": row["dimension"],
                "version_a": variants[0],
                "version_b": variants[1],
                "version_c": variants[2],
                "reason": f"当前得分 {row['score']}/5，需要优先测试更强版本。",
            }
        )
    return matrix


def build_next_actions(score_rows: Sequence[Dict[str, Any]], localization: Dict[str, Any]) -> List[str]:
    weakest = sorted(score_rows, key=lambda item: item["score"])[:3]
    actions = []
    for row in weakest:
        actions.append(f"优先补强 {row['dimension']}：{row['analysis']}")
    actions.extend(localization.get("checklist", [])[:3])
    return unique_keep_order(actions)


def build_execution_summary(result: Dict[str, Any]) -> Dict[str, Any]:
    total_score = int(result.get("total_score") or 0)
    localization = result.get("localization", {}) if isinstance(result.get("localization"), dict) else {}
    localization_status = str(localization.get("status") or "")
    title_top = (result.get("title_scores", {}) or {}).get("top5", [])
    top_title = title_top[0]["title"] if title_top else ""
    weakest = sorted(result.get("scores", []) or [], key=lambda item: item.get("score", 0))[:3]
    landing_check = result.get("landing_page_check", {}) if isinstance(result.get("landing_page_check"), dict) else {}
    landing_status = str(landing_check.get("status") or "")
    editing = result.get("editing_advice", {}) if isinstance(result.get("editing_advice"), dict) else {}

    if "不建议" in localization_status or total_score < 20:
        decision = "暂缓投放，先重剪或重做素材结构"
    elif "需本地化" in localization_status:
        decision = "先本地化，再小预算测试"
    elif total_score >= 32:
        decision = "可进入小预算 A/B 测试"
    else:
        decision = "补强弱项后测试"

    actions = []
    if top_title:
        actions.append(f"首测标题：{top_title}")
    actions.extend(editing.get("priority_fixes", [])[:2])
    actions.extend(localization.get("checklist", [])[:2])
    if "确认" in landing_status:
        actions.append("先修正视频/落地页不一致点，再放量。")

    risks = []
    for row in weakest:
        if row.get("dimension") == "合规性" and row.get("score", 5) < 5:
            risks.append(row.get("analysis", "存在合规风险，需要人工复核。"))
    for item in (landing_check.get("checks") or []):
        if item.get("status") != "一致":
            risks.append(f"落地页需确认：{item.get('item')} - {item.get('detail')}")
    title_warnings = []
    for item in title_top[:3]:
        title_warnings.extend(item.get("warnings", []))
    risks.extend(title_warnings[:3])

    return {
        "decision": decision,
        "top_title": top_title,
        "weakest_dimensions": [{"dimension": row.get("dimension"), "score": row.get("score"), "analysis": row.get("analysis")} for row in weakest],
        "first_actions": unique_keep_order(actions)[:6],
        "risks_to_check": unique_keep_order(risks)[:6],
    }


def build_report_markdown(result: Dict[str, Any]) -> str:
    score_lines = [
        "| 维度 | 评分 | 分析 |",
        "|------|------|------|",
    ]
    for row in result["scores"]:
        score_lines.append(f"| {row['dimension']} | {row['score']}/5 | {row['analysis']} |")

    ab_lines = [
        "| 变量 | 版本A | 版本B | 版本C | 原因 |",
        "|------|-------|-------|-------|------|",
    ]
    for row in result["ab_tests"]:
        ab_lines.append(
            f"| {row['variable']} | {row['version_a']} | {row['version_b']} | {row['version_c']} | {row['reason']} |"
        )

    copy_bundle = result["copy"]
    localization = result["localization"]
    metadata = result.get("metadata", {})
    execution = result.get("execution_summary", {}) if isinstance(result.get("execution_summary"), dict) else {}
    execution_actions = "\n".join(f"- {item}" for item in execution.get("first_actions", [])) or "- 暂无"
    execution_risks = "\n".join(f"- {item}" for item in execution.get("risks_to_check", [])) or "- 暂无"
    performance = (result.get("title_scores", {}) or {}).get("performance_calibration", {}) if isinstance(result.get("title_scores"), dict) else {}
    performance_lines = ""
    if isinstance(performance, dict) and performance.get("used"):
        ranked_angles = performance.get("ranked_angles") or []
        performance_lines = (
            "\n\n### 2.1 历史数据校准\n"
            + "\n".join(
                f"- {item.get('angle')}：{item.get('score')}｜{', '.join(item.get('examples', []))}"
                for item in ranked_angles[:4]
            )
            + ("\n" + "\n".join(f"- {note}" for note in performance.get("notes", [])) if performance.get("notes") else "")
            + "\n"
        )

    sections = [
        f"## 📦 素材概览\n\n- 产品：{result['product_name']}\n- 市场：{result['market_label']}\n- 时长：{metadata.get('duration', 0):.1f}s\n- 关键帧：{result['frames_extracted']} 张\n- 分析可信度：{result['confidence']}%",
        "## 🚀 投放执行摘要\n\n"
        + f"- 投放判断：**{execution.get('decision', '待确认')}**\n"
        + f"- 首测标题：{execution.get('top_title') or '暂无'}\n"
        + "- 先做动作：\n"
        + execution_actions
        + "\n- 风险复核：\n"
        + execution_risks,
        "## 📊 8维评分\n\n" + "\n".join(score_lines) + f"\n\n**总分：{result['total_score']}/40 - {result['summary']}**",
        "## 🌍 本地化状态\n\n"
        + f"- 状态：**{localization['status']}**\n"
        + "- 判断依据：\n"
        + "\n".join(f"  - {reason}" for reason in localization["reasons"])
        + "\n- 改造清单：\n"
        + "\n".join(f"  - {item}" for item in localization["checklist"]),
        "## 🎯 多市场文案\n\n"
        + ("### 0. 推荐 TOP 标题\n" + "\n".join(f"- {item['title']}（{item['score']}分）" for item in result.get("title_scores", {}).get("top5", [])) + "\n\n" if result.get("title_scores", {}).get("top5") else "")
        + ("### 1. 分类型钩子标题\n" + "\n".join(
            f"\n#### {group}\n" + "\n".join(f"- {item}" for item in items)
            for group, items in copy_bundle.get("title_groups", {}).items()
        ) + "\n\n" if copy_bundle.get("title_groups") else "### 1. 标题\n" + "\n".join(f"- {item}" for item in copy_bundle["titles"]) + "\n\n")
        + "### 2. 标题评分与淘汰\n"
        + ("\n".join(f"- {item['title']}：{item['score']}分｜{', '.join(item['reasons'])}" for item in result.get("title_scores", {}).get("ranked", [])[:10]) if result.get("title_scores", {}).get("ranked") else "")
        + ("\n\n不建议优先用：\n" + "\n".join(f"- {item['title']}（{item['score']}分）" for item in result.get("title_scores", {}).get("rejected", [])[:5]) if result.get("title_scores", {}).get("rejected") else "")
        + performance_lines
        + "\n\n### 3. 描述\n"
        + "\n".join(f"- {item}" for item in copy_bundle["descriptions"])
        + ("\n\n### 4. 100字以内TK文案\n" + "\n".join(f"- {item}" for item in copy_bundle.get("tk_short_copies", [])) if copy_bundle.get("tk_short_copies") else "")
        + ("\n\n已过滤高风险旁白点：" + "、".join(copy_bundle.get("script_claims_removed", [])) if copy_bundle.get("script_claims_removed") else "")
        + "\n\n### 5. 正文\n"
        + f"\n#### 短版\n\n{copy_bundle['bodies']['short']}\n"
        + f"\n#### 标准版\n\n{copy_bundle['bodies']['standard']}\n"
        + f"\n#### 强销售版\n\n{copy_bundle['bodies']['hard_sell']}\n"
        + "\n### 6. CTA\n"
        + "\n".join(f"- {item}" for item in copy_bundle["ctas"])
        + "\n\n### 7. Hashtags\n"
        + " ".join(copy_bundle["hashtags"])
        + ("\n\n### 8. 文案规则\n" + "\n".join(f"- {item}" for item in copy_bundle.get("copy_rules", [])) if copy_bundle.get("copy_rules") else "")
        + ("\n\n### 9. 落地页一致性\n" + "\n".join(f"- {row['item']}：{row['status']}｜{row['detail']}" for row in result.get("landing_page_check", {}).get("checks", [])) + ("\n" + "\n".join(f"- {item}" for item in result.get("landing_page_check", {}).get("recommendations", [])) if result.get("landing_page_check", {}).get("recommendations") else "") if result.get("landing_page_check") else "")
        + ("\n\n### 10. 剪辑建议\n" + "\n".join(f"- {step['time']}: {step['content']}（{step['purpose']}）" for step in result.get("editing_advice", {}).get("short_15s", [])) if result.get("editing_advice") else "")
        + ("\n\n### 11. 封面建议\n" + "\n".join(f"- {item}" for item in result.get("editing_advice", {}).get("cover_advice", [])) if result.get("editing_advice") else "")
        + ("\n\n### 12. JP 美妆规则\n" + "\n".join(f"- {item}" for item in (result.get("jp_beauty_rules", {}) or {}).get("title_principles", [])) if result.get("jp_beauty_rules") else ""),
        "## 🧪 A/B 测试矩阵\n\n" + "\n".join(ab_lines),
        "## ✅ 下一步建议\n\n" + "\n".join(f"- {item}" for item in result["next_actions"]),
    ]
    return "\n\n".join(sections) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="TikTok 视频广告素材分析与多市场文案生成")
    parser.add_argument("--extraction-json", required=True, help="extract_frames.py 生成的 extraction_result.json")
    parser.add_argument("--notes", default=None, help="结构化观察笔记 JSON，可选")
    parser.add_argument("--market", default="jp", help="目标市场：jp / th / id")
    parser.add_argument("--landing-page-json", default=None, help="fetch_landing_page.py 生成的落地页 JSON，可选")
    parser.add_argument("--performance-json", default=None, help="历史投放表现 JSON，可选；用于按 CTR/CVR/ROAS/CPA 校准标题角度")
    parser.add_argument("--output", default=None, help="输出目录（默认：extraction_result.json 同目录下的 report）")
    args = parser.parse_args()

    market = market_from_args(args.market)
    extraction_json_path = Path(args.extraction_json)
    notes_path = Path(args.notes) if args.notes else None
    output_dir = Path(args.output) if args.output else extraction_json_path.parent / "report"
    output_dir.mkdir(parents=True, exist_ok=True)

    extraction_data = load_json(extraction_json_path)
    notes = load_json(notes_path) if notes_path else {}
    if args.landing_page_json:
        notes["landing_page"] = load_json(Path(args.landing_page_json))
    performance_data = load_json(Path(args.performance_json)) if args.performance_json else {}
    scores, total_score = build_scores(notes, extraction_data, market)
    localization = build_localization(notes, extraction_data, market)
    copy_bundle = build_copy(notes, market)
    category = infer_category(notes)
    title_scores = build_title_scores(copy_bundle, notes, market, category, performance_data)
    landing_page_check = build_landing_page_check(notes, market)
    editing_advice = build_editing_advice(notes, extraction_data, scores)
    confidence = build_confidence(notes, extraction_data)
    ab_tests = build_ab_tests(scores)
    next_actions = build_next_actions(scores, localization)

    result = {
        "market": market,
        "market_label": MARKET_CONFIG[market]["label"],
        "product_name": str(notes.get("product_name") or "未命名产品").strip(),
        "metadata": extraction_data.get("metadata", {}),
        "frames_extracted": len(extraction_data.get("frame_files", []) or []),
        "confidence": confidence,
        "scores": scores,
        "total_score": total_score,
        "summary": total_score_summary(total_score),
        "localization": localization,
        "copy": copy_bundle,
        "title_scores": title_scores,
        "landing_page_check": landing_page_check,
        "editing_advice": editing_advice,
        "jp_beauty_rules": JP_BEAUTY_RULES if market == "jp" and category == "beauty" else None,
        "ab_tests": ab_tests,
        "next_actions": next_actions,
        "notes_used": bool(notes_path),
        "source_files": {
            "extraction_json": str(extraction_json_path),
            "notes": str(notes_path) if notes_path else None,
            "landing_page_json": str(Path(args.landing_page_json)) if args.landing_page_json else None,
            "performance_json": str(Path(args.performance_json)) if args.performance_json else None,
        },
    }
    result["execution_summary"] = build_execution_summary(result)

    report_json_path = output_dir / "report.json"
    report_md_path = output_dir / "report.md"
    report_json_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    report_md_path.write_text(build_report_markdown(result), encoding="utf-8")

    print(json.dumps({
        "status": "ok",
        "market": market,
        "output_dir": str(output_dir),
        "report_json": str(report_json_path),
        "report_md": str(report_md_path),
        "total_score": total_score,
        "summary": result["summary"],
        "localization_status": localization["status"],
        "confidence": confidence,
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
