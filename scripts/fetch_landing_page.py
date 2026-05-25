"""
落地页信息提取脚本。

Usage:
  python fetch_landing_page.py "https://example.com/detail/xxx" --output landing_page.json

说明：
- 仅使用 Python 标准库
- 提取页面 title、可见文本、价格、折扣、CTA、保障信息等基础字段
- 不执行页面 JS；适合作为落地页一致性校验的保守输入
"""

import argparse
import gzip
import html
import ipaddress
import json
import re
import socket
import sys
import zlib
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.skip_stack: List[str] = []
        self.text_parts: List[str] = []
        self.title_parts: List[str] = []
        self.in_title = False
        self.images: List[Dict[str, str]] = []
        self.links: List[Dict[str, str]] = []
        self.meta: Dict[str, str] = {}
        self.json_ld: List[str] = []
        self.current_link: Optional[str] = None
        self.current_link_text: List[str] = []
        self.current_script_type: Optional[str] = None
        self.current_script_parts: List[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        attr = dict(attrs)
        if tag in {"script", "style", "noscript", "svg"}:
            self.skip_stack.append(tag)
        if tag == "script" and str(attr.get("type") or "").lower() == "application/ld+json":
            self.current_script_type = "application/ld+json"
            self.current_script_parts = []
        if tag == "title":
            self.in_title = True
        if tag == "meta":
            key = str(attr.get("property") or attr.get("name") or "").strip().lower()
            content = str(attr.get("content") or "").strip()
            if key and content:
                self.meta[key] = content
        if tag == "img":
            alt = str(attr.get("alt") or "").strip()
            src = str(attr.get("src") or "").strip()
            if alt or src:
                self.images.append({"alt": alt, "src": src})
                if alt:
                    self.text_parts.append(alt)
        if tag == "a":
            self.current_link = str(attr.get("href") or "").strip()
            self.current_link_text = []

    def handle_endtag(self, tag: str) -> None:
        if self.skip_stack and self.skip_stack[-1] == tag:
            self.skip_stack.pop()
        if tag == "title":
            self.in_title = False
        if tag == "script" and self.current_script_type == "application/ld+json":
            content = "".join(self.current_script_parts).strip()
            if content:
                self.json_ld.append(content)
            self.current_script_type = None
            self.current_script_parts = []
        if tag == "a" and self.current_link is not None:
            text = " ".join(self.current_link_text).strip()
            self.links.append({"text": text, "href": self.current_link})
            self.current_link = None
            self.current_link_text = []

    def handle_data(self, data: str) -> None:
        if self.current_script_type == "application/ld+json":
            self.current_script_parts.append(data)
            return
        if self.skip_stack:
            return
        text = html.unescape(data).strip()
        if not text:
            return
        if self.in_title:
            self.title_parts.append(text)
        self.text_parts.append(text)
        if self.current_link is not None:
            self.current_link_text.append(text)


def normalize_text(text: str) -> str:
    text = re.sub(r"[\t\r\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" {2,}", " ", text)
    return text.strip()


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


def extract_prices(text: str) -> List[str]:
    patterns = [
        r"[¥￥]\s?\d{1,3}(?:,\d{3})*(?:\.\d+)?",
        r"\d{1,3}(?:,\d{3})*\s?円",
        r"฿\s?\d{1,3}(?:,\d{3})*",
        r"Rp\s?\d{1,3}(?:[.,]\d{3})*",
        r"[¥￥]\s*\n\s*\d{1,3}(?:,\d{3})*",
        r"\d{1,3}(?:,\d{3})*\s?[¥￥]",
    ]
    prices: List[str] = []
    for pattern in patterns:
        prices.extend(re.findall(pattern, text, flags=re.IGNORECASE))
    normalized = [re.sub(r"\s+", "", item) for item in prices]
    return unique_keep_order(normalized)


def extract_discounts(text: str) -> List[str]:
    patterns = [r"\d{1,2}\s?%\s?OFF", r"\d{1,2}\s?％\s?OFF", r"半額", r"送料無料", r"特別価格", r"通常価格"]
    values: List[str] = []
    for pattern in patterns:
        values.extend(re.findall(pattern, text, flags=re.IGNORECASE))
    return unique_keep_order(values)


def extract_ctas(text: str) -> List[str]:
    candidates = [
        "今すぐ購入", "今すぐチェック", "詳細はこちら", "プロフィールへ", "カートに入れる",
        "購入する", "Buy Now", "Shop Now", "ดูเพิ่มเติม", "Lihat Selengkapnya",
    ]
    return [item for item in candidates if item.lower() in text.lower()]


def extract_guarantees(text: str) -> List[str]:
    candidates = ["送料無料", "7日間返品交換", "返品交換", "品質保証", "保証", "返金", "配送"]
    return [item for item in candidates if item in text]


def is_private_host(hostname: str) -> bool:
    try:
        addresses = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise ValueError(f"无法解析落地页域名：{hostname}") from exc

    for item in addresses:
        ip_text = item[4][0]
        try:
            ip = ipaddress.ip_address(ip_text)
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
            return True
    return False


def validate_public_http_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("仅支持 http/https 落地页 URL")
    if not parsed.hostname:
        raise ValueError("落地页 URL 缺少 hostname")
    if is_private_host(parsed.hostname):
        raise ValueError("拒绝抓取 localhost、内网或保留地址，避免 SSRF 风险")


def fetch_html(url: str, timeout: int = 20) -> str:
    validate_public_http_url(url)
    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 TikTokAdAnalyzer/1.0",
            "Accept-Encoding": "identity",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    with urlopen(req, timeout=timeout) as response:
        final_url = response.geturl()
        if final_url != url:
            validate_public_http_url(final_url)
        raw = response.read()
        encoding = (response.headers.get("content-encoding") or "").lower()
        gzip_pos = raw.find(b"\x1f\x8b")
        if gzip_pos >= 0:
            try:
                decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
                raw = decompressor.decompress(raw[gzip_pos:])
            except zlib.error:
                try:
                    raw = gzip.decompress(raw[gzip_pos:])
                except gzip.BadGzipFile:
                    # Some CDNs incorrectly mark identity HTML as gzip or include gzip-like bytes in text.
                    pass
        elif encoding == "deflate":
            try:
                raw = zlib.decompress(raw)
            except zlib.error:
                raw = zlib.decompress(raw, -zlib.MAX_WBITS)
        content_type = response.headers.get("content-type", "")
        match = re.search(r"charset=([^;]+)", content_type, re.I)
        charset = match.group(1).strip() if match else "utf-8"
        return raw.decode(charset, errors="replace")


def fetch_html_rendered(url: str, timeout: int = 20) -> str:
    validate_public_http_url(url)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("未安装 Playwright，无法使用 --render-js。请先安装 playwright 后再试。") from exc

    def guard_route(route, request) -> None:
        try:
            validate_public_http_url(request.url)
        except Exception:
            route.abort()
            return
        route.continue_()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(ignore_https_errors=True)
        context.route("**/*", guard_route)
        page = context.new_page()
        page.set_default_timeout(timeout * 1000)
        page.goto(url, wait_until="networkidle", timeout=timeout * 1000)
        final_url = page.url
        if final_url != url:
            validate_public_http_url(final_url)
        content = page.content()
        context.close()
        browser.close()
        return content


def parse_json_ld_product_names(json_ld_items: List[str]) -> List[str]:
    names: List[str] = []
    for raw in json_ld_items:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            item = stack.pop()
            if not isinstance(item, dict):
                continue
            item_type = item.get("@type")
            item_types = item_type if isinstance(item_type, list) else [item_type]
            if any(str(value).lower() == "product" for value in item_types) and item.get("name"):
                names.append(str(item["name"]))
            graph = item.get("@graph")
            if isinstance(graph, list):
                stack.extend(graph)
    return unique_keep_order(names)


def parse_landing_page(url: str, render_js: bool = False, timeout: int = 20) -> Dict:
    raw_html = fetch_html_rendered(url, timeout) if render_js else fetch_html(url, timeout)
    parser = TextExtractor()
    parser.feed(raw_html)
    text = normalize_text("\n".join(parser.text_parts))
    title = normalize_text(" ".join(parser.title_parts))
    meta_title = parser.meta.get("og:title") or parser.meta.get("twitter:title") or ""
    meta_description = parser.meta.get("description") or parser.meta.get("og:description") or parser.meta.get("twitter:description") or ""
    json_ld_product_names = parse_json_ld_product_names(parser.json_ld)
    image_alts = unique_keep_order([img["alt"] for img in parser.images if img.get("alt")])
    links = [
        {"text": item.get("text", ""), "href": urljoin(url, item.get("href", ""))}
        for item in parser.links[:50]
        if item.get("href")
    ]

    product_name = json_ld_product_names[0] if json_ld_product_names else ""
    if not product_name:
        product_name = (meta_title or title).split("-")[0].strip() if (meta_title or title) else ""
    if not product_name and image_alts:
        product_name = image_alts[0]

    price_source = text + "\n" + raw_html

    return {
        "url": url,
        "title": title,
        "meta": {
            "title": meta_title,
            "description": meta_description,
            "og_image": parser.meta.get("og:image") or parser.meta.get("twitter:image") or "",
        },
        "product_name_guess": product_name,
        "json_ld_product_names": json_ld_product_names[:10],
        "prices": extract_prices(price_source),
        "discounts": extract_discounts(text),
        "ctas": extract_ctas(text),
        "guarantees": extract_guarantees(text),
        "image_alts": image_alts[:20],
        "links": links,
        "text_excerpt": text[:4000],
        "text_length": len(text),
        "render_mode": "playwright" if render_js else "static",
        "limitations": (
            ["已使用 Playwright 渲染页面；仍可能遗漏登录后、地区定向或异步接口返回的价格/库存。"]
            if render_js
            else ["未执行页面 JavaScript；动态渲染的价格、库存和优惠可能无法提取。"]
        ),
    }


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="落地页信息提取")
    parser.add_argument("url", help="落地页 URL")
    parser.add_argument("--output", "-o", default=None, help="输出 JSON 路径")
    parser.add_argument("--render-js", action="store_true", help="使用 Playwright 渲染页面后再提取；需要安装 Playwright")
    parser.add_argument("--timeout", type=int, default=20, help="请求超时时间，默认 20 秒")
    args = parser.parse_args()

    try:
        result = parse_landing_page(args.url, render_js=args.render_js, timeout=args.timeout)
    except Exception as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False))
        sys.exit(1)

    content = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content, encoding="utf-8-sig")
    print(content)


if __name__ == "__main__":
    main()
