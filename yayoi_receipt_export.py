#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
弥生青色申告用エクスポートファイル生成ツール
- Google Cloud Vision API で OCR
- 日付 / 金額 / 店舗候補を抽出
- 勘定科目・摘要を自動判定
- 同一案件と思われる重複レシートを統合
- エクスポート.txt / スキップログ.txt / 成功ログ.txt を出力
- 処理成功した画像は MMDD_ を付けてその場でリネーム

2026-04-06 修正版:
- ZIP展開先を毎回クリーンアップ
- _work/extracted_images に前回実行分が残っていても混ざらない
- 既に MMDD_ が付いているファイルへ再付与しない
- OCR 呼び出しに timeout / retry を追加
- 進捗表示を追加
- cp932 へ書けない文字が混ざってもログ出力で落ちないよう修正
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import shutil
import sys
import time
import zipfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

import google.auth
from google.api_core import exceptions as gapi_exceptions
from google.cloud import vision
from google.oauth2 import service_account


NORMAL_PRICE_MIN = 100
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
DEFAULT_ACCOUNT_CASH = "現金"
DEFAULT_TAX_IN = "課対仕入込10%適格"
DEFAULT_TAX_OUT = "対象外"

OCR_TIMEOUT_SEC = 30
OCR_RETRY_COUNT = 2
OCR_RETRY_SLEEP_SEC = 2.0

TOTAL_WORDS_STRONG = [
    "合計", "総合計", "税込合計", "領収金額", "ご利用額",
    "お支払額", "請求額", "現計", "今回請求額", "合計金額",
    "取引金額", "金額", "ご請求額",
]
TOTAL_WORDS_WEAK = ["税込", "税込額", "総額", "お買上", "お買い上げ"]
BAD_AMOUNT_WORDS = [
    "税", "内税", "外税", "消費税", "消費税等", "税額",
    "小計", "値引", "割引", "釣銭", "お預り", "預り",
    "ポイント", "うち", "対象額", "適用税率",
]
ID_LIKE_WORDS = [
    "取引id", "取引 id", "取引番号", "加盟店取引番号",
    "モバイル決済取引", "レシートno", "レシートNo", "領収No",
    "レジ no", "レジ No", "posno", "pos no", "pos番号",
    "tel", "電話", "登録番号", "端末", "会員番号", "伝票番号",
    "承認番号", "店舗コード", "店コード", "発券 no", "受付番号",
]
GENERIC_VENDOR_WORDS = {
    "領収書", "領収証", "領収 証", "領収 証明書", "内訳", "加盟店名",
    "ご利用日", "売上", "納品書", "納品書(領収書)", "支払票", "支払票(売上)",
    "お客様控え", "金額", "合計", "小計", "取引金額", "登録番号", "ブランド",
    "端末番号", "係員", "売場", "摘要", "但し", "様", "樣", "紙",
}
GENERIC_VENDOR_PREFIXES = (
    "登録番号", "電話", "tel", "〒", "レジ", "pos", "貴no", "責", "no.",
    "取引", "伝票", "端末", "ブランド", "ご利用日", "精算", "発券", "店舗コード",
)
RECEIPT_HINT_WORDS = [
    "合計", "領収", "レシート", "税込", "税抜", "現金", "クレジット",
    "tel", "電話", "店", "発行", "お預り", "釣銭", "売上", "取引",
    "登録番号", "事業者登録番号", "小計", "pos", "no.", "責", "円",
    "営業時間", "店コード", "利用日時", "取引id", "支払", "paypay",
    "qr決済", "qr 決済", "バーコード決済", "領収書", "領収証",
]
GAS_WORDS = [
    "eneos", "enejet", "enejett", "enekey", "m-enekey", "エネオス", "エネジェット",
    "出光", "idemitsu", "cosmo", "コスモ", "apollostation",
    "キグナス", "昭和シェル", "shell", "ガソリン", "レギュラー", "ハイオク", "軽油",
    "セルフ", "油", "l-", "給油", "燃料", "ss", "ドクタードライブ",
]
MASSAGE_WORDS = [
    "マッサージ", "もみほぐし", "ほぐし", "整体", "リラク", "リラクゼーション",
    "ボディケア", "足つぼ", "てもみ", "手もみ", "りらくる",
]
HAIRCUT_WORDS = [
    "理容", "美容", "カット", "ヘア", "散髪", "床屋", "バーバー",
    "barber", "qb", "qbhouse", "qbハウス",
]
HOME_CENTER_WORDS = [
    "コーナン", "olympic", "オリンピック", "カインズ", "コメリ",
    "ビバホーム", "島忠", "ホーマック", "dcm", "ケーヨー",
    "ハンズマン", "ホームセンター", "オートバックス", "autobacs",
]

DATE_PATTERNS = [
    re.compile(r"(20\d{2})[\/\-.年 ]\s*(\d{1,2})[\/\-.月 ]\s*(\d{1,2})日?"),
    re.compile(r"(令和|R|Ｒ)\s*([0-9]{1,2})[\/\-.年 ]\s*(\d{1,2})[\/\-.月 ]\s*(\d{1,2})日?"),
    re.compile(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)"),
    re.compile(r"(?<!\d)26年\s*(\d{1,2})月\s*(\d{1,2})日"),
    re.compile(r"(?<!\d)8年\s*(\d{1,2})月\s*(\d{1,2})日"),
]
AMOUNT_FALLBACK_PATTERN = re.compile(r"([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{2,6})")
CURRENCY_PATTERN = re.compile(r"(?:Y|¥|￥|\\)\s*([0-9][0-9,]{0,10})")

_VISION_CLIENT: vision.ImageAnnotatorClient | None = None


@dataclass
class ReceiptResult:
    filename: str
    original_filename: str
    payment_date: date
    amount: int
    debit_account: str
    summary: str
    memo: str
    ocr_text: str
    vendor: str = ""
    renamed_filename: str = ""
    time_text: str = ""
    vendor_key: str = ""
    strong_candidates: list[tuple[int, int]] = field(default_factory=list)
    weak_candidates: list[int] = field(default_factory=list)
    fallback_candidates: list[int] = field(default_factory=list)
    amount_reason: str = ""


@dataclass
class SkipResult:
    filename: str
    reason: str
    hint: str = ""


def log(message: str) -> None:
    print(message, flush=True)


def safe_text_for_encoding(text: str, encoding: str) -> str:
    if not text:
        return text
    return text.encode(encoding, errors="replace").decode(encoding)


def create_vision_client() -> vision.ImageAnnotatorClient:
    quota_project = "photo-receipt-parser"
    cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")

    if cred_path:
        credentials = service_account.Credentials.from_service_account_file(cred_path)
        return vision.ImageAnnotatorClient(credentials=credentials)

    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
        quota_project_id=quota_project,
    )
    if hasattr(credentials, "with_quota_project"):
        credentials = credentials.with_quota_project(quota_project)
    return vision.ImageAnnotatorClient(credentials=credentials)


def get_vision_client() -> vision.ImageAnnotatorClient:
    global _VISION_CLIENT
    if _VISION_CLIENT is None:
        log("Vision API クライアントを初期化中...")
        _VISION_CLIENT = create_vision_client()
        log("Vision API クライアント初期化完了")
    return _VISION_CLIENT


def read_example_encoding(example_path: Path) -> str:
    raw = example_path.read_bytes()
    for enc in ("cp932", "shift_jis", "utf-8-sig", "utf-8"):
        try:
            raw.decode(enc)
            return enc
        except UnicodeDecodeError:
            continue
    return "cp932"


def ensure_clean_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def iter_images(input_path: Path, work_dir: Path) -> list[Path]:
    if input_path.is_dir():
        return sorted([p for p in input_path.rglob("*") if p.suffix.lower() in IMAGE_EXTS])

    if input_path.is_file() and input_path.suffix.lower() == ".zip":
        extract_dir = work_dir / "extracted_images"
        log(f"ZIP 展開先を初期化: {extract_dir}")
        ensure_clean_dir(extract_dir)
        log(f"ZIP 展開中: {input_path}")
        with zipfile.ZipFile(input_path, "r") as zf:
            zf.extractall(extract_dir)
        return sorted([p for p in extract_dir.rglob("*") if p.suffix.lower() in IMAGE_EXTS])

    raise ValueError(f"入力が画像フォルダまたは zip ではありません: {input_path}")


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    replacements = {
        "¥": "Y", "￥": "Y", "　": " ",
        "合 計": "合計", "総 合計": "総合計",
        "領収証": "領収書", "領 収証": "領収書", "領 収書": "領収書",
        "レシ一ト": "レシート", "レシ一卜": "レシート",
        "セフン": "セブン", "マアルフン": "イレブン",
        "ファミリ一マ一ト": "ファミリーマート", "ロ一ソン": "ローソン",
        "キッチン オリジフ": "キッチンオリジン",
        "Eneje": "EneJet", "Enejet": "EneJet", "EneJet": "EneJett",
        "FneKey": "EneKey", "FreKey": "EneKey", "M-FneKey": "M-EneKey",
        "O26": "2026", "o26": "2026", "２０２６": "2026", "２O２６": "2026",
        "20264 ": "2026年4月 ", "20264": "2026年4月",
        "2A": "2月", "3A": "3月", "4A": "4月", "5A": "5月", "6A": "6月",
        "7A": "7月", "8A": "8月", "9A": "9月",
        "（": "(", "）": ")", "【": "[", "】": "]",
        "<QR 決済>": "QR決済", "<QR決済>": "QR決済",
        "「支払票 (売上)]": "支払票(売上)", "[支払票(売上)]": "支払票(売上)",
        "金亮": "金額", "金売": "金額",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)

    text = re.sub(r"合\s*\n\s*計", "合計", text)
    text = re.sub(r"ご\s*\n\s*利\s*\n?\s*用\s*\n?\s*額", "ご利用額", text)
    text = re.sub(r"取\s*\n\s*引\s*\n?\s*金\s*\n?\s*額", "取引金額", text)
    text = re.sub(r"(?<!\d)(\d)[\.,]\s+(\d{3})(?!\d)", r"\1,\2", text)
    text = re.sub(r"(?<!\d)(\d),\s+(\d{3})(?!\d)", r"\1,\2", text)
    # ご利用日時: 2026/02 \n /01 14:48:08 のような分断を救済
    text = re.sub(
        r'(ご利用日時[:：]?\s*\d{4}/\d{1,2})\s*\n\s*/\s*(\d{1,2})',
        r'\1/\2',
        text
    )
    # ご利用日時: 2026/02 \n /01 -> 2026/02/01
    #text = re.sub(
    #    r'(\d{4}/\d{1,2})\s*\n\s*/\s*(\d{1,2})',
    #    r'\1/\2',
    #    text
    #)    
    # 02 /01 -> 02/01
    text = re.sub(r'(\d{1,2})\s*/\s*(\d{1,2})(?!\d)', r'\1/\2', text)

    lines = [ln.strip() for ln in text.split("\n")]
    return "\n".join(lines)

def normalize_text_for_date(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("　", " ")
    #text = text.replace("Я", "2")   # OCR 月の誤認識対応
    #text = text.replace("B", "8")   # OCR 日の誤認識対応    
    #text = re.sub(r"(\d{4}/\d{1,2})\s*\n\s*/\s*(\d{1,2})", r"\1/\2", text)
    text = re.sub(r"(\d{4})\s*#\s*(\d{1,2})\s*#\s*(\d{1,2})", r"\1/\2/\3", text)
    text = re.sub(r"(\d{4}/\d{1,2})\s*\n\s*/\s*(\d{1,2})", r"\1/\2", text)    
    lines = [ln.strip() for ln in text.split("\n")]
    return "\n".join(lines)

def normalize_text_for_amount(text: str) -> str:
    text = normalize_text(text)
    text = re.sub(r'(?<!\d)(\d)[\.,]\s+(\d{3})(?!\d)', r'\1,\2', text)
    text = re.sub(r'(?<!\d)(\d),\s+(\d{3})(?!\d)', r'\1,\2', text)
    return text    


def run_ocr(image_path: Path) -> str:
    with image_path.open("rb") as f:
        content = f.read()

    image = vision.Image(content=content)
    client = get_vision_client()
    last_error: Exception | None = None

    for attempt in range(1, OCR_RETRY_COUNT + 1):
        try:
            response = client.text_detection(image=image, timeout=OCR_TIMEOUT_SEC)
            if response.error.message:
                raise RuntimeError(response.error.message)
            text = response.text_annotations[0].description if response.text_annotations else ""
            return text

        except (
            gapi_exceptions.DeadlineExceeded,
            gapi_exceptions.ServiceUnavailable,
            gapi_exceptions.InternalServerError,
            gapi_exceptions.ResourceExhausted,
            gapi_exceptions.Unknown,
        ) as e:
            last_error = e
            if attempt < OCR_RETRY_COUNT:
                log(f"OCR 一時エラー {image_path.name} ({attempt}/{OCR_RETRY_COUNT}) : {type(e).__name__} -> 再試行")
                time.sleep(OCR_RETRY_SLEEP_SEC)
                continue
            raise RuntimeError(f"OCR一時エラー: {type(e).__name__}: {e}") from e

        except Exception as e:
            last_error = e
            raise RuntimeError(f"OCR失敗: {type(e).__name__}: {e}") from e

    if last_error is not None:
        raise RuntimeError(str(last_error))
    return ""


def clean_for_date(text: str) -> str:
    t = text

    # OCR崩れの月日補正
    t = re.sub(r"(\d{4})年\s*0?(\d{1,2})\D+\s*0?(\d{1,2})日", r"\1年\2月\3日", t)
    t = re.sub(r"(\d{4})[/-]\s*0?(\d{1,2})[/-]\s*0?(\d{1,2})", r"\1/\2/\3", t)

    return t


def extract_date(text: str) -> Optional[date]:
    t = clean_for_date(text)
    candidates: list[date] = []

    for m in DATE_PATTERNS[0].finditer(t):
        try:
            y, mo, dd = map(int, m.groups())
            candidates.append(date(y, mo, dd))
        except ValueError:
            pass

    for m in DATE_PATTERNS[1].finditer(t):
        try:
            _, ry, mo, dd = m.groups()
            candidates.append(date(2018 + int(ry), int(mo), int(dd)))
        except ValueError:
            pass

    for m in DATE_PATTERNS[2].finditer(t):
        try:
            y, mo, dd = map(int, m.groups())
            candidates.append(date(y, mo, dd))
        except ValueError:
            pass

    for m in DATE_PATTERNS[3].finditer(t):
        try:
            mo, dd = map(int, m.groups())
            candidates.append(date(2026, mo, dd))
        except ValueError:
            pass

    for m in DATE_PATTERNS[4].finditer(t):
        try:
            mo, dd = map(int, m.groups())
            candidates.append(date(2026, mo, dd))
        except ValueError:
            pass

    today = date.today()
    valid = [d for d in candidates if date(2020, 1, 1) <= d <= today]
    if valid:
        return valid[-1]

    # 年がOCR誤読でも、月日だけ明示されていれば拾う
    md_patterns = [
        re.compile(r'(?<!\d)(\d{1,2})月\s*(\d{1,2})日'),
        re.compile(r'(?<!\d)(\d{1,2})/(\d{1,2})(?!\d)'),
        re.compile(r'(?<!\d)(\d{1,2})-(\d{1,2})(?!\d)'),
    ]

    for pat in md_patterns:
        for m in pat.finditer(t):
            try:
                mo = int(m.group(1))
                dd = int(m.group(2))
                d = date(today.year, mo, dd)
                if 1 <= mo <= 12 and 1 <= dd <= 31:
                    return d
            except ValueError:
                pass

    # 最後の救済: 連結した YYYYMMDD だけ拾う
    for m in re.finditer(r'(20\d{2})(\d{2})(\d{2})', t):
        try:
            y = int(m.group(1))
            mo = int(m.group(2))
            dd = int(m.group(3))
            d = date(y, mo, dd)
            if date(2020, 1, 1) <= d <= today:
                return d
        except ValueError:
            pass

    return None

def extract_time(text: str) -> str:
    patterns = [
        re.compile(r"([01]?\d|2[0-3])[:時 ]([0-5]\d)"),
        re.compile(r"\b([01]\d|2[0-3])([0-5]\d)\b"),
    ]
    for pat in patterns:
        for m in pat.finditer(text):
            hh, mm = m.groups()
            h = int(hh)
            m2 = int(mm)
            if 0 <= h <= 23 and 0 <= m2 <= 59:
                return f"{h:02d}:{m2:02d}"
    return ""


def parse_amount_int(s: str) -> Optional[int]:
    s = s.replace(",", "").strip()
    if not s.isdigit():
        return None
    n = int(s)
    return n if n > 0 else None


def normalize_line(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip()


def looks_like_tax_or_subtotal_line(line: str) -> bool:
    lower = line.lower()
    return any(w.lower() in lower for w in BAD_AMOUNT_WORDS)


def looks_like_id_line(line: str) -> bool:
    lower = line.lower()
    return any(word.lower() in lower for word in ID_LIKE_WORDS) or bool(re.search(r"\d{10,}", line))


def looks_like_date_line(line: str) -> bool:
    lower = line.lower()
    return (
        bool(re.search(r"20\d{2}[\/\-.年]", lower))
        or bool(re.search(r"(令和|r|Ｒ)\s*\d{1,2}[\/\-.年]", line))
        or bool(re.search(r"\d{1,2}:\d{2}", line))
    )


def looks_like_percent_tax_line(line: str) -> bool:
    return "%" in line or "％" in line or "税率" in line or "適用税率" in line or "対象" in line


def collect_amounts_from_line(line: str) -> list[tuple[int, bool]]:
    found: list[tuple[int, bool]] = []
    for m in CURRENCY_PATTERN.finditer(line):
        amount = parse_amount_int(m.group(1))
        if amount is not None and 1 <= amount <= 300000:
            found.append((amount, True))
    if found:
        return found
    for m in AMOUNT_FALLBACK_PATTERN.finditer(line):
        amount = parse_amount_int(m.group(1))
        if amount is not None and 1 <= amount <= 300000:
            found.append((amount, False))
    return found


def score_strong_amount(
    amount: int,
    has_currency: bool,
    freq: int,
    src_line: str,
    block_label: str,
    block_max_amount: int,
) -> int:
    score = 0
    if has_currency:
        score += 35
    score += min(freq, 3) * 12
    if amount >= NORMAL_PRICE_MIN:
        score += 15
    if amount >= 500:
        score += 5
    if amount < 50:
        score -= 140
    elif amount < 100:
        score -= 45

    if 100 <= amount <= 999 and block_max_amount >= 1000:
        score -= 140
    if amount >= 1000:
        score += 60
    if looks_like_tax_or_subtotal_line(src_line):
        score -= 70
    if looks_like_percent_tax_line(src_line):
        score -= 45
    if looks_like_id_line(src_line) or looks_like_date_line(src_line):
        score -= 120
    if "合計" in block_label or "総合計" in block_label:
        score += 25
    elif "金額" in block_label or "ご利用額" in block_label or "取引金額" in block_label:
        score += 18
    if "合計" in src_line or "総合計" in src_line:
        score += 25
    if "ご利用額" in src_line or "取引金額" in src_line:
        score += 15
    if "お預り" in src_line or "釣" in src_line:
        score -= 100
    return score


def extract_amount_candidates(text: str) -> tuple[list[tuple[int, int]], list[int], list[int]]:
    lines = [normalize_line(ln) for ln in text.split("\n") if normalize_line(ln)]
    strong_with_priority: list[tuple[int, int]] = []
    weak_candidates: list[int] = []
    fallback_candidates: list[int] = []

    for i, line in enumerate(lines):
        lower = line.lower()
        matched_label = next((word for word in TOTAL_WORDS_STRONG if word.lower() in lower), None)
        if not matched_label:
            continue

        block = lines[i:min(i + 8, len(lines))]
        candidates_detail: list[tuple[int, bool, str]] = []
        for blk_line in block:
            if looks_like_id_line(blk_line):
                continue
            if looks_like_date_line(blk_line) and "金額" not in line:
                continue
            if looks_like_tax_or_subtotal_line(blk_line) and "合計" not in blk_line and "ご利用額" not in blk_line and "取引金額" not in blk_line and "金額" not in blk_line:
                continue
            for amount, has_currency in collect_amounts_from_line(blk_line):
                candidates_detail.append((amount, has_currency, blk_line))

        if not candidates_detail:
            continue

        freq: dict[int, int] = {}
        for amount, _, _ in candidates_detail:
            freq[amount] = freq.get(amount, 0) + 1

        block_max_amount = max(amount for amount, _, _ in candidates_detail)

        best_amount = None
        best_score = -10**9
        for amount, has_currency, src_line in candidates_detail:
            score = score_strong_amount(
                amount,
                has_currency,
                freq[amount],
                src_line,
                line,
                block_max_amount,
            )
            if src_line == line:
                score += 8
            if score > best_score:
                best_score = score
                best_amount = amount

        if best_amount is not None and best_score >= -10:
            strong_with_priority.append((best_amount, best_score))

    for line in lines:
        lower = line.lower()
        if not any(word.lower() in lower for word in TOTAL_WORDS_WEAK):
            continue
        if looks_like_id_line(line) or looks_like_date_line(line) or looks_like_tax_or_subtotal_line(line) or looks_like_percent_tax_line(line):
            continue
        for amount, _ in collect_amounts_from_line(line):
            if amount >= 10:
                weak_candidates.append(amount)

    for line in lines:
        if looks_like_id_line(line) or looks_like_date_line(line):
            continue
        for amount, has_currency in collect_amounts_from_line(line):
            if amount < 10 or amount > 300000:
                continue
            if looks_like_tax_or_subtotal_line(line) and amount < 100:
                continue
            if looks_like_percent_tax_line(line) and amount < 100:
                continue
            if has_currency or amount >= 100:
                fallback_candidates.append(amount)

    return strong_with_priority, weak_candidates, fallback_candidates


def choose_amount(text: str) -> tuple[Optional[int], list[tuple[int, int]], list[int], list[int], str]:
    strong, weak, fallback = extract_amount_candidates(text)
    if strong:
        strong_sorted = sorted(strong, key=lambda x: (-x[1], -x[0]))
        return strong_sorted[0][0], strong_sorted, weak, fallback, "strong"
    filtered_weak = [x for x in weak if x >= 100 or (not fallback and x >= 10)]
    if filtered_weak:
        return filtered_weak[0], strong, filtered_weak, fallback, "weak"
    filtered_fallback = [x for x in fallback if x >= 100]
    if filtered_fallback:
        return filtered_fallback[0], strong, weak, fallback, "fallback"
    if fallback:
        return fallback[0], strong, weak, fallback, "fallback"
    return None, strong, weak, fallback, ""


def looks_like_receipt(text: str) -> bool:
    lower = text.lower()

    if any(w.lower() in lower for w in GAS_WORDS):
        return True
            
    score = sum(1 for marker in RECEIPT_HINT_WORDS if marker.lower() in lower)
    if extract_date(text):
        score += 2
    amount, _, _, _, _ = choose_amount(text)
    if amount is not None:
        score += 2
    if "qr決済" in lower or "paypay" in lower:
        score += 1
    return score >= 3


def clean_vendor_text(line: str) -> str:
    line = normalize_line(line)
    line = re.sub(r"^[0OUuIi1]+\s+", "", line)
    line = re.sub(r"^[=\-—ー~]+\s*", "", line)
    line = re.sub(r"\s+", " ", line)
    return line.strip(" []()<>「」『』")


def is_generic_vendor_line(line: str) -> bool:
    raw = clean_vendor_text(line)
    if not raw:
        return True
    lower = raw.lower()
    if raw in GENERIC_VENDOR_WORDS:
        return True
    if any(lower.startswith(p.lower()) for p in GENERIC_VENDOR_PREFIXES):
        return True
    if looks_like_date_line(raw) or looks_like_id_line(raw):
        return True
    if re.search(r"^\d+$", raw):
        return True
    if "適用税率" in raw or ("対象" in raw and "店" not in raw):
        return True
    return len(raw) <= 1


def normalize_vendor_name(name: str) -> str:
    name = clean_vendor_text(name)
    name = re.sub(r"^7i\s*", "セブン-イレブン ", name, flags=re.I)
    name = re.sub(r"^U\s*", "", name)
    name = re.sub(r"^0\s+", "", name)
    name = re.sub(r"\s+", " ", name).strip()
    if "familymart" in name.lower():
        return "FamilyMart"
    if "lawson" in name.lower():
        return "LAWSON"
    if "enejett" in name.lower() or "enejet" in name.lower():
        return "EneJett"
    if "セブン" in name:
        return "セブン-イレブン"
    if "横浜ブルク13" in name or "ヨコハマブルク" in name:
        return "横浜ブルク13"
    return name


def extract_vendor(text: str) -> str:
    lines = [normalize_line(ln) for ln in text.split("\n") if normalize_line(ln)]
    if not lines:
        return ""

    for i, line in enumerate(lines[:12]):
        if "加盟店名" in line:
            for j in range(i + 1, min(i + 6, len(lines))):
                cand = clean_vendor_text(lines[j])
                if not is_generic_vendor_line(cand) and not re.search(r"^\d{2,4}-\d{2,4}-\d{2,5}$", cand):
                    return normalize_vendor_name(cand)

    candidates: list[str] = []
    for line in lines[:10]:
        cand = clean_vendor_text(line)
        if not is_generic_vendor_line(cand):
            candidates.append(cand)

    for cand in candidates:
        lower = cand.lower()
        if any(k in lower for k in [
            "familymart", "lawson", "enejet", "enejett", "eneos", "セブン",
            "タイムズ", "ブルク", "ムービル", "コーナン", "オートバックス",
            "マクドナルド", "kfc", "ガスト", "ハックドラッグ", "welcia",
        ]):
            return normalize_vendor_name(cand)

    if candidates:
        return normalize_vendor_name(candidates[0])

    for line in lines[:5]:
        cand = clean_vendor_text(line)
        if cand:
            return normalize_vendor_name(cand)
    return ""


def vendor_key(vendor: str) -> str:
    v = normalize_vendor_name(vendor).lower()
    return re.sub(r"\s+", "", v)


def classify_receipt(text: str, vendor: str) -> tuple[str, str]:
    lower = text.lower()
    vendor_lower = vendor.lower()
    if any(w.lower() in lower or w.lower() in vendor_lower for w in GAS_WORDS):
        return "旅費交通費", "ガソリン代"
    if any(w.lower() in lower or w.lower() in vendor_lower for w in MASSAGE_WORDS):
        return "接待交際費", "マッサージ代"
    if any(w.lower() in lower or w.lower() in vendor_lower for w in HAIRCUT_WORDS):
        return "接待交際費", "散髪代"
    if any(w.lower() in lower or w.lower() in vendor_lower for w in HOME_CENTER_WORDS):
        return "雑費", "修理用、部品、工具代"
    return "雑費", "オファー待ち受け代"


def to_reiwa_string(d: date) -> str:
    return f"R.{d.year - 2018:02d}/{d.month:02d}/{d.day:02d}"


def build_prefixed_name(payment_date: date, current_name: str) -> str:
    base_name = re.sub(r"^(?:\d{4}_)+", "", current_name)
    return f"{payment_date.month:02d}{payment_date.day:02d}_{base_name}"


def make_export_row(seq: int, result: ReceiptResult) -> list[object]:
    return [
        "2000", seq, "", to_reiwa_string(result.payment_date),
        result.debit_account, "", "", DEFAULT_TAX_IN, result.amount, 0,
        DEFAULT_ACCOUNT_CASH, "", "", DEFAULT_TAX_OUT, result.amount, 0,
        result.summary, "", "", 0, "", result.memo, "0", "0", "no",
    ]


def rename_file_if_needed(image_path: Path, payment_date: date) -> tuple[Path, str]:
    new_name = build_prefixed_name(payment_date, image_path.name)
    if image_path.name == new_name:
        return image_path, image_path.name

    new_path = image_path.with_name(new_name)
    if new_path.exists():
        if new_path.resolve() == image_path.resolve():
            return image_path, image_path.name
        return new_path, new_path.name

    image_path.rename(new_path)
    return new_path, new_path.name

def process_image(image_path: Path) -> ReceiptResult | SkipResult:
    original_name = image_path.name

    try:
        raw_text = run_ocr(image_path)
    except Exception as e:
        return SkipResult(original_name, str(e))

    if not raw_text.strip():
        return SkipResult(original_name, "OCR結果が空です")

    date_text = normalize_text_for_date(raw_text)
    amount_text = normalize_text_for_amount(raw_text)

    # まず日付だけ先に取る
    payment_date = extract_date(date_text)

    # 日付が取れたら、成否に関係なく先にリネーム
    renamed_path = image_path
    renamed_filename = image_path.name
    if payment_date:
        try:
            renamed_path, renamed_filename = rename_file_if_needed(image_path, payment_date)
        except Exception:
            renamed_path = image_path
            renamed_filename = image_path.name

    if not looks_like_receipt(raw_text):
        return SkipResult(
            renamed_filename,
            f"領収書・レシートと判定できませんでした (date={payment_date})",
            raw_text[:220].replace("\n", " | "),
        )

    if not payment_date:
        hint_raw = raw_text[:220].replace("\n", " | ")
        hint_date = date_text[:220].replace("\n", " | ")
        return SkipResult(
            renamed_filename,
            "支払日付を抽出できませんでした",
            f"date=None | RAW: {hint_raw} | DATE: {hint_date}",
        )

    amount, strong, weak, fallback, reason = choose_amount(amount_text)
    if amount is None:
        return SkipResult(
            renamed_filename,
            "金額を抽出できませんでした",
            raw_text[:220].replace("\n", " | "),
        )

    vendor = extract_vendor(raw_text)
    time_text = extract_time(raw_text)
    debit_account, summary = classify_receipt(raw_text, vendor)

    return ReceiptResult(
        filename=renamed_path.name,
        original_filename=original_name,
        payment_date=payment_date,
        amount=amount,
        debit_account=debit_account,
        summary=summary,
        memo=renamed_filename,
        ocr_text=raw_text,
        vendor=vendor,
        renamed_filename=renamed_filename,
        time_text=time_text,
        vendor_key=vendor_key(vendor),
        strong_candidates=strong,
        weak_candidates=weak,
        fallback_candidates=fallback,
        amount_reason=reason,
    )

def deduplicate_results(results: list[ReceiptResult]) -> list[ReceiptResult]:
    merged: dict[tuple[str, str, str, int], ReceiptResult] = {}
    for r in results:
        key = (r.vendor_key or vendor_key(r.vendor), r.payment_date.isoformat(), r.time_text, r.amount)
        if key not in merged:
            merged[key] = r
            continue
        base = merged[key]
        memo_parts = [x for x in base.memo.split("\n") if x.strip()]
        if r.renamed_filename and r.renamed_filename not in memo_parts:
            memo_parts.append(r.renamed_filename)
        base.memo = "\n".join(memo_parts)
    return sorted(merged.values(), key=lambda x: (x.payment_date, x.time_text, x.vendor, x.amount, x.filename))


def write_export(results: list[ReceiptResult], output_dir: Path, encoding: str) -> Path:
    output_path = output_dir / "エクスポート.txt"
    with output_path.open("w", encoding=encoding, newline="") as f:
        writer = csv.writer(f, lineterminator="\r\n")
        for seq, r in enumerate(results, start=1):
            row = [safe_text_for_encoding(str(v), encoding) if isinstance(v, str) else v for v in make_export_row(seq, r)]
            writer.writerow(row)
    return output_path


def write_skip_log(skips: list[SkipResult], output_dir: Path) -> Path:
    output_path = output_dir / "スキップログ.txt"
    with output_path.open("w", encoding="utf-8", newline="") as f:
        for s in skips:
            line = f"{s.filename}\t{s.reason}"
            if s.hint:
                line += f"\t{s.hint}"
            f.write(line + "\r\n")
    return output_path

def write_success_log(results: list[ReceiptResult], output_dir: Path) -> Path:
    output_path = output_dir / "成功ログ.txt"
    with output_path.open("w", encoding="utf-8", newline="") as f:
        for r in results:
            blocks = [
                "==============================",
                f"ファイル名: {r.filename}",
                f"元ファイル名: {r.original_filename}",
                f"日付: {r.payment_date.isoformat()}",
                f"金額: {r.amount}",
                f"勘定科目: {r.debit_account}",
                f"摘要: {r.summary}",
                f"店名: {r.vendor}",
                f"時刻: {r.time_text}",
                f"メモ: {r.memo}",
                "------------------------------",
                "[金額候補]",
                f"strong: {r.strong_candidates}",
                f"weak: {r.weak_candidates}",


                f"fallback: {r.fallback_candidates}",
                f"chosen: {r.amount} ({r.amount_reason})",
                "------------------------------",
                "[OCR]",
                r.ocr_text.rstrip(),
                "==============================",
                "",
            ]
            for block in blocks:
                f.write(block + "\r\n")
    return output_path


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="レシート画像から弥生青色申告向けファイルを生成")
    parser.add_argument("input_path", help="画像フォルダ または ZIP")
    parser.add_argument("--example", required=True, help="参考エクスポートファイルのパス")
    parser.add_argument("--output-dir", default="output_yayoi", help="出力先ディレクトリ")
    parser.add_argument("--work-dir", default=None, help="作業ディレクトリ")
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    input_path = Path(args.input_path)
    example_path = Path(args.example)
    output_dir = Path(args.output_dir)

    if args.work_dir:
        work_dir = Path(args.work_dir)
    else:
        work_dir = output_dir / "_work"

    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    log("開始します")
    encoding = read_example_encoding(example_path)
    log(f"文字コード: {encoding}")

    images = iter_images(input_path, work_dir)
    log(f"対象画像数: {len(images)}")

    successes: list[ReceiptResult] = []
    skips: list[SkipResult] = []

    for idx, image_path in enumerate(images, start=1):
        log(f"[{idx}/{len(images)}] OCR処理中: {image_path.name}")
        result = process_image(image_path)
        if isinstance(result, SkipResult):
            skips.append(result)
            log(f"  -> スキップ: {result.reason}")
        else:
            successes.append(result)
            log(f"  -> 成功: {result.payment_date.isoformat()} / {result.amount} / {result.vendor}")

    deduped = deduplicate_results(successes)
    write_export(deduped, output_dir, encoding)
    write_skip_log(skips, output_dir)
    write_success_log(deduped, output_dir)

    log(f"処理画像数: {len(images)}")
    log(f"成功件数: {len(successes)}")
    log(f"重複統合後: {len(deduped)}")
    log(f"スキップ件数: {len(skips)}")
    log(f"出力先: {output_dir}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
