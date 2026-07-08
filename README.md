# 大阪市電話番号簿デジタル化ツール

このプロジェクトは、電話帳画像から最終的な `csv.gz` を生成するための 3 段階ツールです。

1. `src/split_columns.py`: ページ画像をカラム画像へ分割
2. `src/ocr_columns.py`: 分割済みカラム画像を Gemini で OCR
3. `src/export_csv.py`: OCR JSON を最終 `csv.gz` に変換

入力は `data/` 配下の電話帳ディレクトリです。中間成果物と最終成果物はすべて `output/` 配下に保存します。

## 前提条件

- Python 3.10 以降
- `opencv-python`
- `Pillow`
- `google-genai`

```bash
pip install opencv-python Pillow google-genai
```

## 使い方

1. `data/` 配下に電話帳ごとのディレクトリを置き、その中に PNG を入れます。
2. `config.example.json` を `config.json` にコピーし、Gemini 認証を設定します。Agent Platform や Google Cloud 上では、既定の `gemini.auth: "adc"` で Application Default Credentials を使います。
3. 電話帳ごとの固定設定が必要な場合は、その電話帳ディレクトリに `phonebook.config.json` を置きます。
4. プロジェクトルートで次を順に実行します。

```bash
python src/split_columns.py
python src/ocr_columns.py
python src/export_csv.py
```

`split_columns.py` は `output/split` を一旦クリアしてから再生成します。既定では OCR 入力用に、カラム画像を 75% 縮小の WebP 品質 90 で保存します。`ocr_columns.py` は既定で compact スキーマを使い、API 応答を短い JSON にしてから従来形式へ展開して保存します。

詳細設計は `doc/` を参照してください。

Gemini は既定で Vertex AI の Application Default Credentials を使います。Agent Platform など実行環境側にアプリケーションのデフォルト認証情報がある場合は、`project` と `location` を設定するか、`GOOGLE_CLOUD_PROJECT` / `GOOGLE_CLOUD_LOCATION` を環境変数で渡してください。

```json
{
  "gemini": {
    "auth": "adc",
    "project": "YOUR_GOOGLE_CLOUD_PROJECT",
    "location": "global",
    "ocrModel": "gemini-3.1-flash-preview"
  }
}
```

ローカルで Gemini Developer API の API キーを使う場合は、従来どおり `gemini.apiKey` を設定できます。

```json
{
  "gemini": {
    "apiKey": "YOUR_GEMINI_API_KEY",
    "ocrModel": "gemini-3.1-flash-preview"
  }
}
```

`config.json` はローカル設定ファイルです。API キーを入れる場合は公開リポジトリに含めず、誤って公開した場合はキーを失効して再発行してください。

### 電話帳ごとの設定

電話帳特有の分割条件や住所正規化辞書は、対象電話帳ディレクトリ直下の `phonebook.config.json` に置きます。

```json
{
  "schemaVersion": 1,
  "split": {
    "fixedColumnCount": 4
  }
}
```

`split_columns.py` は `split.fixedColumnCount`, `split.columnFormat`, `split.resizeScale`, `split.webpQuality`, `split.webpLossless`, `split.skipFailedPages` を読みます。CLI オプションを指定した場合は、設定ファイルより CLI が優先されます。

### よく使うオプション

```bash
python src/split_columns.py --debug
python src/split_columns.py --columns 4 --book "昭和38年2月1日大阪市50音別電話番号簿"
python src/split_columns.py --column-format png --resize-scale 1.0
python src/ocr_columns.py --book "昭和38年2月1日大阪市50音別電話番号簿"
python src/ocr_columns.py --schema standard
python src/export_csv.py --book "昭和38年2月1日大阪市50音別電話番号簿"
```

- `--columns`: カラム数が既知の場合に固定する。固定数に必要な縦罫線が検出できないページはスキップする
- `--column-format`, `--resize-scale`, `--webp-quality`: カラム画像の保存形式と縮小率を変える。既定は `webp`, `0.75`, `90`
- `--schema`: OCR の API 応答スキーマを変える。既定は `compact`
- `--debug`: 分割範囲のオーバーレイ画像を保存する
- `--book`: 指定した電話帳ディレクトリだけを処理する

`ocr_columns.py` は既存の `*.ocr.json` を上書きしません。AI OCR は実行ごとに結果が揺れ、API コストも発生するため、再OCRしたいカラムだけ対象 JSON を削除してから実行してください。

## 出力

- `output/split/<電話帳名>/`: 分割画像、`column_count.json`、`split_quality.json`、`<page>.columns.json`
- `output/ocr_columns/<電話帳名>/`: `*.ocr.json`、`manifest.json`、`ocr_quality.json`
- `output/csv/`: `ISO日付-地域-電話帳種類.csv.gz`

最終 CSV ヘッダは次の 6 列です。

```text
電話番号,名前,都道府県,市区町村,町域,番地
```

## 実装メモ

- 外枠の影や余白をクロップしてから判定します。
- 二値化は CLAHE と Otsu を使います。
- カラムの内部境界は縦罫線だけを根拠に検出します。縦罫線が取れないページは分割せずスキップします。
- 既定では入力ファイル名順に、各ページの縦罫線からカラム数と境界を推定します。
- カラム画像は左右に少し余裕を持たせて切り出し、既定では 75% 縮小の WebP 品質 90 で保存します。
- 分割後はページごとに幅、黒画素量、端の黒画素接触を記録し、疑わしいページを `split_quality.json` に集約します。
- カラム分割できないページは既定でスキップし、理由を `split_quality.json` の `skippedPages` に残します。
- 一次 OCR は対象カラム画像を読み、前カラム OCR の末尾だけを先頭 fragment の継続判定に使います。次カラムや前カラム画像全体は渡しません。
- OCR は Gemini の構造化出力を使い、既定では compact 応答を従来形式へ展開して、点線や紙面ノイズを除いた `cleanText`、複数候補配列、`reviewFlags` を保存します。
- 既存の OCR JSON は自動再生成しません。再OCRしたい場合は対象ファイルを明示的に削除します。
- Windows の日本語パスに対応するため、画像の入出力は `cv2.imdecode(np.fromfile(...))` と `cv2.imencode(...).tofile(...)` を使います。
- 現行の CSV 出力は OCR JSON から直接軽量変換します。独立した連結・住所正規化ステージは将来拡張です。
- 電話番号がない entry は最終 CSV に出力しません。
