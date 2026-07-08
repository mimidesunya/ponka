# Pipeline

## 目的

最終成果物として、次のヘッダを持つ `csv.gz` を生成する。

```text
電話番号,名前,都道府県,市区町村,町域,番地
```

ただし電話帳の原資料には、カラムまたぎ、略語、省略、途中切れがあるため、途中段階では JSON を正本として扱う。

## 処理段階

### 1. Column Split

担当: `src/split_columns.py`

入力:

- `data/<電話帳名>/*.png`

出力:

- `output/split/<電話帳名>/column_count.json`
- `output/split/<電話帳名>/split_quality.json`
- `output/split/<電話帳名>/<page>-<column>.webp`
- `output/split/<電話帳名>/<page>.columns.json`

役割:

- 既定では入力ファイル名順に、ページごとのカラム数 2 / 3 / 4 を自動推定する
- カラム数が既知の場合は `--columns` で固定し、不要な候補探索を省く
- カラムの内部境界は縦罫線だけを根拠に検出する
- 各ページを読順に沿ったカラム画像へ、左右に少し余裕を持たせて分割する
- カラム画像は既定で 75% 縮小の WebP 品質 90 とし、OCR コストと可読性のバランスを取る
- 縦罫線で境界を認識できないページは既定でスキップし、`split_quality.json` の `skippedPages` に理由を残す
- 後続処理に必要な幾何メタ情報を残す
- 分割品質の簡易 QC 指標を出力し、疑わしいページを後で確認できるようにする

### 2. Column OCR

担当: `src/ocr_columns.py`

入力:

- `output/split/<電話帳名>/<page>-<column>.webp`
- `output/split/<電話帳名>/column_count.json`
- `output/split/<電話帳名>/<page>.columns.json`

出力:

- `output/ocr_columns/<電話帳名>/<page>-<column>.ocr.json`
- `output/ocr_columns/<電話帳名>/manifest.json`
- `output/ocr_columns/<電話帳名>/ocr_quality.json`

役割:

- Gemini で各カラム画像を書き起こす
- 既定では compact スキーマを使い、API 応答を短い JSON にして保存時に従来形式へ展開する
- 一次 OCR では対象カラム画像を読み、前カラム OCR 末尾だけを先頭 fragment の継続判定に使う
- 次カラムや前カラム画像全体は渡さず、画像外の文字は OCR 結果へ転記しない
- カラム内の行断片を JSON として抽出する
- 途中開始や途中終了の兆候を残す
- モデル、プロンプト版、画像 SHA-256、前 OCR JSON SHA-256 を記録し、古い OCR JSON の混入を防ぐ
- OCR 品質の簡易集計を残す

### 3. Export

担当: `src/export_csv.py`

入力:

- `output/ocr_columns/<電話帳名>/*.ocr.json`

出力:

- `output/csv/ISO日付-地域-電話帳種類.csv.gz`

役割:

- OCR JSON から最終列へ写像する
- OCR が返した候補から電話番号と住所を軽く正規化する
- 電話番号がない entry は CSV に出力しない
- 空値や不確定値の扱いを統一する
- UTF-8 の CSV を gzip 圧縮して保存する

## ディレクトリ構成案

```text
ponka/
├── data/
├── output/
│   ├── split/
│   ├── ocr_columns/
│   └── csv/
├── doc/
├── config.example.json
├── config.json
└── src/
```

`config.json` はローカル秘密情報を含むため、公開用には `config.example.json` だけを使う。

## 設計原則

- 各段階は 1 つの責務だけを持つ
- 中間成果物は再利用できる JSON として保存する
- CSV は最終派生物であり、正本ではない
- AI による補完は必ず痕跡を残す
- エラーが出た段階から再実行できるようにする
