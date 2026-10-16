#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pass 1: レシート画像をOCRし、中間JSONを生成してPass 2を起動する。"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import yayoi_receipt_import as core


def scan_image(path: Path, image_root: Path) -> dict:
    record = {
        "id": path.name,
        "image": str(path.relative_to(image_root)).replace("\\", "/"),
        "original_filename": path.name,
        "date": "",
        "time": "",
        "amount": None,
        "vendor": "",
        "debit_account": "雑費",
        "summary": "オファー待ち受け代",
        "confirmed": False,
        "use": True,
        "warning": "",
        "ocr_text": "",
        "ocr_date_text": "",
        "ocr_amount_text": "",
        "amount_reason": "",
    }
    try:
        ocr = core.run_ocr(path)
    except Exception as exc:
        record["warning"] = f"OCRエラー: {exc}"
        return record

    raw = ocr.raw_text
    amount_raw = ocr.amount_text
    record["ocr_text"] = raw
    date_text = core.normalize_text_for_date(raw)
    amount_text = core.normalize_text_for_amount(amount_raw)
    record["ocr_date_text"] = date_text
    record["ocr_amount_text"] = amount_text

    payment_date = core.extract_date(date_text)
    amount, _strong, _weak, _fallback, reason = core.choose_amount(amount_text)
    vendor = core.extract_vendor(raw)
    debit_account, summary = core.classify_receipt(raw, vendor)

    if payment_date:
        record["date"] = payment_date.isoformat()
        if core.is_suspicious_date(payment_date):
            record["warning"] = f"日付要確認: {payment_date.isoformat()}"
    else:
        record["warning"] = "支払日付を抽出できませんでした"

    record["time"] = core.extract_time(raw)
    record["amount"] = amount
    record["vendor"] = vendor
    record["debit_account"] = debit_account
    record["summary"] = summary
    record["amount_reason"] = reason

    if amount is None:
        record["warning"] = (record["warning"] + " / " if record["warning"] else "") + "金額を抽出できませんでした"
    elif amount < core.NORMAL_PRICE_MIN or amount > core.NORMAL_PRICE_MAX:
        record["warning"] = (record["warning"] + " / " if record["warning"] else "") + "金額が通常範囲外です"

    if not core.looks_like_receipt(raw):
        record["warning"] = (record["warning"] + " / " if record["warning"] else "") + "レシート判定できませんでした"

    return record


def run_review(json_path: Path) -> int:
    review_script = Path(__file__).with_name("yayoi_receipt_review.py")
    print(f"Pass 2を起動します: {json_path}", flush=True)
    return subprocess.call([
        sys.executable,
        str(review_script),
        str(json_path),
        "--host", "0.0.0.0",
        "--port", "8080",
    ])


def main() -> int:
    p = argparse.ArgumentParser(description="レシートOCRと確認画面の起動")
    p.add_argument("input_path", nargs="?", help="画像フォルダ または ZIP。省略時は既存JSONを使用")
    p.add_argument("--output-dir", default="data/import_yayoi")
    p.add_argument("--json", default="receipt_work.json")
    args = p.parse_args()

    output_dir = Path(args.output_dir)
    json_path = output_dir / args.json

    if args.input_path is None:
        if not json_path.is_file():
            p.error(f"入力ファイルが指定されておらず、中間JSONも見つかりません: {json_path}")
        return run_review(json_path)

    input_path = Path(args.input_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    if input_path.is_file() and input_path.suffix.lower() == ".zip":
        images_dir = output_dir / "images"
        images = core.iter_images(input_path, output_dir)
        image_root = images_dir
    elif input_path.is_dir():
        images = core.iter_images(input_path, output_dir)
        image_root = input_path
    else:
        raise ValueError(f"入力が画像フォルダまたはZIPではありません: {input_path}")

    records = []
    for i, path in enumerate(images, 1):
        print(f"[{i}/{len(images)}] OCR処理中: {path.name}", flush=True)
        records.append(scan_image(path, image_root))

    work = {
        "version": 1,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "image_dir": str(image_root.resolve()),
        "receipts": records,
    }
    json_path.write_text(json.dumps(work, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"中間JSON: {json_path}")
    print(f"画像数: {len(records)}")
    return run_review(json_path)


if __name__ == "__main__":
    raise SystemExit(main())
