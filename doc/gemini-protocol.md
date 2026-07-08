# Gemini Protocol

## 目的

Gemini を使う処理は 3 段階に分ける。

1. カラム OCR
2. エントリ連結
3. 住所・名称正規化

各段階の責務を分離し、1 回のプロンプトに複数の曖昧性を押し込まない。

## モデル方針

2026-04-29 時点の推奨:

- 一次 OCR
  - 既定: `gemini-3-flash-preview`
  - 精度優先: `gemini-3.1-pro-preview`
- 連結と補完
  - `gemini-3.1-pro-preview`
- 安定運用重視の代替
  - 利用可能な stable モデルを実測して選ぶ

一次 OCR は件数が多いため、通常運用では Flash と compact スキーマを既定にする。精査対象だけを再OCRする場合や、レイアウトが難しい電話帳では `--model gemini-3.1-pro-preview` を指定する。

## 1. Column OCR Protocol

### Column OCR Input

- 対象カラム画像
- 直前カラム OCR JSON の末尾 segment 要約
- 電話帳名
- ページ番号
- カラム番号
- 構造化 JSON スキーマ

### Column OCR Instructions

- `rawText`, `cleanText`, `phones`, `names`, `addresses` は対象カラム画像だけから読む
- 各 segment は `entryType` を必ず持つ。通常リスト行は `directory_entry`、広告枠・宣伝ブロックは `ad_block`、分類見出しは `category_heading` とする
- 直前カラム OCR 末尾は、先頭 segment が前カラム最後の entry と同一かどうかの判定だけに使う
- 前カラム末尾にだけ存在する文字は転記しない
- 次カラムは渡さない
- 広告、罫線、索引、点線だけの行は原則除外する。残す場合でも、語句ではなく紙面レイアウトで判断し、広告は `entryType=ad_block`、見出しは `entryType=category_heading` とする
- 住所読取の補助として、大阪市区・近隣自治体の略称をプロンプトに含める。例: `尼,若王寺中ノ坪` が `尼若王寺中ノ坪` のように見える場合でも、略称と町名の組み合わせとして読めるようにする
- 番号左側のカーリーブラケットは、複数番号が左側の 1 つの名前に対応することを示す。番号右側のカーリーブラケットは、複数番号が右側の 1 つの住所に対応することを示す。両方が組み合わさる場合は、1 つの名前に複数番号、1 つの名前に複数住所、1 つの住所に複数番号が対応しうる。可能なら 1 つの logical segment として `phones`, `names`, `addresses` に対応関係が分かるよう保持し、`reviewFlags` に `multi_phone_brace_group` を付ける
- 出力は JSON のみ
- Gemini の構造化出力 schema を使う
- `startsMidEntry` と `endsMidEntry` を必ず返す
- `continuityFromPrevious` を必ず返し、`sameEntry=true` は先頭 segment だけが使える

### Column OCR Output Example

```json
{
  "segments": [
    {
      "segmentId": "0030-02-0001",
      "sequence": 1,
      "rawText": "...",
      "cleanText": "...",
      "startsMidEntry": false,
      "endsMidEntry": true,
      "entryHints": {
        "phone": "...",
        "name": "...",
        "address": "..."
      },
      "phones": ["..."],
      "names": ["..."],
      "addresses": ["..."],
      "reviewFlags": ["ends_mid_entry"],
      "continuityFromPrevious": {
        "sameEntry": false,
        "previousSegmentId": "",
        "mergedCleanText": "",
        "confidence": 0.0,
        "reason": ""
      },
      "confidence": 0.81
    }
  ]
}
```

`rawText` は画像に近い文字列、`cleanText` は点線リーダーや紙面ノイズを除去した文字列である。`entryHints` は単一候補を期待する既存処理向けの互換フィールドである。複数の電話番号、名称、住所候補が見える場合は、`phones`, `names`, `addresses` 配列にすべて保持する。カラムまたぎやページまたぎの疑い、複数候補、不確実な広告エントリなどは `reviewFlags` に残す。先頭 segment が直前カラム末尾と同一 entry なら `continuityFromPrevious.sameEntry=true` とし、`reviewFlags` に `continued_from_previous` を追加する。

## 2. Entry Stitch Protocol

### Stitch Input

- 読順に並んだ隣接 segment
- 直前と直後の segment
- 電話帳名
- ページ・カラム位置

### Stitch Instructions

- 2 つの断片が同一エントリの続きか判定する
- 同一であれば統合結果を返す
- 同一でなければ別エントリとして扱う
- 判定理由と信頼度を返す

### Stitch Output Example

```json
{
  "sameEntry": true,
  "mergedText": "東区北久宝寺町三丁目二十三 田中商店 1234",
  "reason": "前断片が住所途中で終わり、後断片が丁目表記で始まっているため",
  "confidence": 0.79
}
```

## 3. Normalize Protocol

### Normalize Input

- 統合済みエントリ
- 電話帳名
- 既知の区名・町域辞書
- 同じ電話帳内で既に確定した地名候補

### Normalize Instructions

- 住所を `都道府県, 市区町村, 町域, 番地` に分解する
- 大阪市の略記や丁目表記を補完する
- 不確実な補完は `reviewFlags` に残す
- 元文字列を捨てない

### Normalize Output Example

```json
{
  "normalized": {
    "電話番号": "1234",
    "名前": "田中商店",
    "都道府県": "大阪府",
    "市区町村": "大阪市東区",
    "町域": "北久宝寺町三丁目",
    "番地": "23"
  },
  "expansions": [
    {
      "field": "町域",
      "source": "三ノ丁目",
      "expandedTo": "三丁目"
    }
  ],
  "reviewFlags": []
}
```

## 実装ルール

- すべての Gemini 応答は JSON のみを期待する
- 破損した JSON に備えて再試行と抽出処理を入れる
- モデル補完結果には必ず根拠を残す
- 低信頼結果は後段へそのまま渡し、早い段階で捨てない
