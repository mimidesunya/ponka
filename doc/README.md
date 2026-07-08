# Documentation Index

このディレクトリは開発者向けの詳細文書を置く場所です。

## 文書一覧

- `pipeline.md`
  - 現行の 3 段階パイプラインと将来拡張を含む処理フロー
- `data-model.md`
  - 中間 JSON と最終 `csv.gz` のデータ形式
- `gemini-protocol.md`
  - Gemini に渡す入力単位、対象カラム画像と前 OCR 末尾を使う一次 OCR 契約、将来の連結・正規化段階の出力契約
- `export-format.md`
  - 最終成果物としての `csv.gz` 仕様、OCR JSON 直接変換、昭和期住所略記辞書、将来の正規化 JSON からの変換ルール

## 前提

- カラム分割は `src/split_columns.py` が担当する
- OCR と CSV エクスポートは別プログラムとして実装済み
- 中間成果物の正本は JSON とし、最終成果物だけを `csv.gz` にする
- 現行実装は 3 段階構成で、独立したエントリ連結・住所正規化ステージは未実装
