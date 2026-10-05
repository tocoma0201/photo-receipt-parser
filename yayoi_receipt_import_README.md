# yayoi_receipt_import.py

このPythonスクリプトは、領収書/レシート画像から弥生青色申告用の3ファイルを生成します。

## 前提

1.  Python 3.11 以上推奨
2.  Tesseract OCR 本体をインストール
3.  Pythonライブラリをインストール

インストール例:

``` bash
pip install pillow pytesseract
```

WindowsでTesseractをPATHに通していない場合:

``` bash
python yayoi_receipt_import.py data/Photos-202607141752.zip --tesseract-cmd "C:\Program Files\Tesseract-OCR\tesseract.exe"
```

## 通常実行

``` bash
python yayoi_receipt_import.py data/Photos-202607141752.zip
```

## 出力

``` text
output_yayoi/
  インポート.txt
  スキップログ.txt
  リネーム.bat
```

## 注意

-   OCRは誤認識します。税務用途では必ず目視確認してください
-   文字コードは参考ファイルに合わせて cp932 優先で保存します
-   勘定科目ルール:
    -   ガソリンスタンドっぽい → 旅費交通費 / ガソリン代
    -   マッサージっぽい → 接待交際費 / マッサージ代
    -   散髪っぽい → 接待交際費 / 散髪代
    -   その他 → 雑費 / オファー待ち受け代

### メモリオーバーで実行できない時

## 過去ログを削除する

``` bash
rm -rf ~/.codeoss/data/logs/*
df -h ~
```

## キャッシュほ削除する

``` bash
rm -rf ~/.codeoss/data/CachedExtensionVSIXs/*
rm -rf ~/.codeoss/data/CachedExtensionVSIXs/.[!.]* 2>/dev/null
df -h ~
```
