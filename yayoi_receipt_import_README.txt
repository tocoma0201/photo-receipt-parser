このPythonスクリプトは、領収書/レシート画像から弥生青色申告用の3ファイルを生成します。

前提:
1. Python 3.11 以上推奨
2. Tesseract OCR 本体をインストール
3. Pythonライブラリをインストール

インストール例:
pip install pillow pytesseract

WindowsでTesseractをPATHに通していない場合:
python yayoi_receipt_export.py Photos-3-001.zip --example エクスポートファイル例.txt --tesseract-cmd "C:\Program Files\Tesseract-OCR\tesseract.exe"

通常実行:
python yayoi_receipt_export.py Photos-3-001.zip --example エクスポートファイル例.txt

出力:
output_yayoi/
  エクスポート.txt
  スキップログ.txt
  リネーム.bat

注意:
- OCRは誤認識します。税務用途では必ず目視確認してください
- 文字コードは参考ファイルに合わせて cp932 優先で保存します
- 勘定科目ルール:
  - ガソリンスタンドっぽい → 旅費交通費 / ガソリン代
  - マッサージっぽい → 接待交際費 / マッサージ代
  - 散髪っぽい → 接待交際費 / 散髪代
  - その他 → 雑費 / オファー待ち受け代
