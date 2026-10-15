# 弥生レシート 3パス運用

従来の `yayoi_receipt_import.py` が一度に行っていた処理を、OCR・人間確認・最終生成の3段階に分離する。

## Pass 1: OCR → 中間JSON

```bash
python yayoi_receipt_scan.py data/import_yayoi/images --output-dir data/output_yayoi
```

ZIPを直接入力することもできる。

```bash
python yayoi_receipt_scan.py data/Photos-YYYYMMDD.zip --output-dir data/output_yayoi
```

出力:

```text
data/output_yayoi/receipt_work.json
```

この段階では画像ファイル名を変更しない。1画像を1レコードとして保存し、OCR全文、日付、時刻、金額、店名、勘定科目、摘要などを保持する。

## Pass 2: 画像を見ながら確認・編集

```bash
python yayoi_receipt_review.py data/output_yayoi/receipt_work.json --host 0.0.0.0 --port 8080
```

Cloud Shell の Web Preview で port 8080 を開く。

画面では1画像ずつ次を確認・編集できる。

- 支払日
- 時刻
- 金額
- 店名
- 勘定科目
- 摘要
- このレシートを使用する / 使用しない
- 確認済み / 未確認

`confirmed`（確認済み）は人間の作業進捗だけに使用する。Pass 3 は `confirmed` を参照しないため、1枚も確認していなくてもインポート生成できる。

`use=false` の画像だけがPass 3の対象外になる。画像そのものは削除しない。

編集内容は「保存」または「確認して次へ」で即座に `receipt_work.json` へ保存されるため、途中で終了して後日再開できる。「未確認だけ」を有効にすると未確認レシートだけを順番に確認できる。

## Pass 3: 中間JSON → 弥生インポート + 画像名同期

```bash
python yayoi_receipt_generate.py data/output_yayoi/receipt_work.json
```

`use=true` かつ日付・金額が有効なレコードから `import_YYYYMMDD.txt` を生成する。

同一の店名・日付・時刻・金額は従来と同様に1取引へ統合する。確認用に統合せず出力したい場合は `--no-deduplicate` を指定できる。

画像ファイル名はJSONの現在の日付に同期する。

```text
IMG20261004031551.jpg
  ↓ 2026-07-14
0714_IMG20261004031551.jpg
  ↓ JSONで2026-07-15へ修正して再生成
0715_IMG20261004031551.jpg
```

既存の `MMDD_` は追加ではなく置換されるので、Pass 2 → Pass 3 を何度繰り返しても日付を修正できる。リネーム後の画像名はJSONにも書き戻される。

## データの位置づけ

`receipt_work.json` を正本とし、`import_YYYYMMDD.txt` はいつでも再生成できる派生物として扱う。

```text
画像
  ↓
Pass 1: OCR・解析
  ↓
receipt_work.json
  ↕
Pass 2: 人間による確認・修正（任意）
  ↓
Pass 3: 生成
  ├─ import_YYYYMMDD.txt
  └─ 画像ファイル名をJSONの日付へ同期
```

従来の `yayoi_receipt_import.py` は比較・移行確認のため、このブランチでは残している。
