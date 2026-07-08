# Data Model

## 基本方針

- 中間成果物の正本は JSON
- 最終配布物は `csv.gz`
- JSON では読順、断片、補完履歴、信頼度を保持する

## 1. カラム数メタ情報

ファイル: `output/split/<電話帳名>/column_count.json`

```json
{
  "layoutScope": "page",
  "columnImageFormat": "webp",
  "columnImageResizeScale": 0.75,
  "webpQuality": 90,
  "webpLossless": false,
  "pageCount": 25,
  "columnCountHistogram": {
    "2": 2,
    "4": 23
  },
  "pages": [
    {
      "page": "0029.png",
      "columnCount": 4,
      "savedFiles": [
        "output/split/昭和38年2月1日大阪市50音別電話番号簿/0029-01.webp"
      ],
      "inference": {
        "mode": "page",
        "inferredColumnCount": 4
      },
      "quality": {}
    }
  ],
  "mostCommonColumnCount": 4
}
```

各ページを入力ファイル名順に処理し、ページごとの推定結果とカラム数ヒストグラムを保存する。

## 2. ページ分割メタ情報

ファイル: `output/split/<電話帳名>/<page>.columns.json`

```json
{
  "input": "data/昭和38年2月1日大阪市50音別電話番号簿/0030.png",
  "cropRect": {
    "y1": 20,
    "y2": 7012,
    "x1": 18,
    "x2": 4980
  },
  "columnCount": 4,
  "columns": [
    {"x1": 120, "y1": 0, "x2": 1260, "y2": 6980},
    {"x1": 1260, "y1": 0, "x2": 2410, "y2": 6980}
  ],
  "inference": {
    "mode": "page",
    "inferredColumnCount": 4
  },
  "quality": {
    "pageInkRatio": 0.08942,
    "widthCoefficientOfVariation": 0.01431,
    "medianColumnInkRatio": 0.09125,
    "maxEdgeInkRatio": 0.04127,
    "maxEdgeTextInkRatio": 0.01852,
    "flags": [],
    "columns": [
      {
        "column": 1,
        "x1": 120,
        "x2": 1260,
        "width": 1140,
        "relativeWidth": 0.9948,
        "inkRatio": 0.09231,
        "leftEdgeInkRatio": 0.01245,
        "rightEdgeInkRatio": 0.02614,
        "leftEdgeTextInkRatio": 0.01245,
        "rightEdgeTextInkRatio": 0.01852
      }
    ]
  }
}
```

`quality.flags` には次のような診断フラグが入る。

- `uneven_column_widths`: カラム幅のばらつきが大きい
- `possible_blank_or_underfilled_column`: 他列に比べて黒画素が極端に少ない列がある
- `possible_text_cut_at_column_edge`: カラム端の黒画素接触が多く、本文を切っている疑いがある。長い縦罫線らしい画素列は除外して判定する

## 3. 分割 QC 集計

ファイル: `output/split/<電話帳名>/split_quality.json`

```json
{
  "pageCount": 5,
  "skippedPageCount": 1,
  "skippedPages": [
    {
      "page": "0001.png",
      "reason": "本文領域の検出に失敗しました。"
    }
  ],
  "suspiciousPageCount": 1,
  "flagCounts": {
    "possible_text_cut_at_column_edge": 1
  },
  "suspiciousPages": [
    {
      "page": "0030.png",
      "columnCount": 4,
      "flags": ["possible_text_cut_at_column_edge"],
      "pageInkRatio": 0.08942,
      "widthCoefficientOfVariation": 0.01431,
      "medianColumnInkRatio": 0.09125,
      "maxEdgeInkRatio": 0.24127,
      "maxEdgeTextInkRatio": 0.18294
    }
  ],
  "pages": []
}
```

## 4. カラム OCR 中間 JSON

ファイル: `output/ocr_columns/<電話帳名>/<page>-<column>.ocr.json`

```json
{
  "book": "昭和38年2月1日大阪市50音別電話番号簿",
  "page": 30,
  "column": 2,
  "image": "output/split/昭和38年2月1日大阪市50音別電話番号簿/0030-02.webp",
  "imageSha256": "0123456789abcdef...",
  "promptVersion": "ocr-target-image-with-prev-tail-v1",
  "ocrOutputSchema": "compact",
  "context": {
    "mode": "target_image_with_previous_tail",
    "previousOcrJson": "output/ocr_columns/昭和38年2月1日大阪市50音別電話番号簿/0030-01.ocr.json",
    "previousOcrSha256": "abcdef0123456789...",
    "previousOcrTail": {
      "page": 30,
      "column": 1,
      "tailSegments": [
        {
          "segmentId": "0030-01-0071",
          "sequence": 71,
          "cleanText": "前カラム末尾の後段判定用テキスト",
          "phones": ["5678"],
          "names": ["山田商店"],
          "addresses": ["南久宝寺町"],
          "reviewFlags": ["ends_mid_entry"],
          "endsMidEntry": true
        }
      ]
    },
    "nextImage": ""
  },
  "model": "gemini-3-flash-preview",
  "segments": [
    {
      "segmentId": "0030-02-0001",
      "sequence": 1,
      "rawText": "北久宝寺町三ノ丁目二十三 田中商店 1234",
      "cleanText": "北久宝寺町三ノ丁目二十三 田中商店 1234",
      "indentLevel": 0,
      "startsMidEntry": false,
      "endsMidEntry": false,
      "entryHints": {
        "phone": "1234",
        "name": "田中商店",
        "address": "北久宝寺町三ノ丁目二十三"
      },
      "phones": ["1234", "5678"],
      "names": ["田中商店"],
      "addresses": ["北久宝寺町三ノ丁目二十三"],
      "reviewFlags": ["multi_phone"],
      "continuityFromPrevious": {
        "sameEntry": false,
        "previousSegmentId": "",
        "mergedCleanText": "",
        "confidence": 0.0,
        "reason": ""
      },
      "confidence": 0.84
    }
  ]
}
```

`rawText` は画像で見える文字列に近い形を残す。`cleanText` は点線リーダー、装飾罫線、ページ番号、索引だけの文字などを除去した後段処理用の文字列である。`indentLevel` は通常行を 0、直前の上位行にぶら下がるインデント行を 1、その下位を 2 として論理的な字下げ段数を入れる。`entryHints` は既存の CSV 変換との互換用に単一の最有力候補を入れる。`phones`, `names`, `addresses` は OCR で見えた候補をできるだけ落とさず保持するための配列で、複数電話番号や複数住所の展開は後続ステージで扱う。`continuityFromPrevious` は先頭 segment が直前カラム末尾と同一 entry かを表す。`sameEntry=true` の場合でも、前カラムにだけ存在する文字は `rawText`, `cleanText`, `phones`, `names`, `addresses` へ転記しない。`reviewFlags` には `starts_mid_entry`, `ends_mid_entry`, `continued_from_previous`, `multi_phone`, `multi_address`, `possible_ad_entry`, `low_confidence_ocr`, `uncertain_layout` などを入れる。

同じ OCR 出力ディレクトリには `manifest.json` も保存する。

```json
{
  "book": "昭和38年2月1日大阪市50音別電話番号簿",
  "splitDir": "output/split/昭和38年2月1日大阪市50音別電話番号簿",
  "model": "gemini-3-flash-preview",
  "promptVersion": "ocr-target-image-with-prev-tail-v1",
  "ocrOutputSchema": "compact",
  "ocrInputMode": "target_image_with_previous_tail",
  "processMode": "sync",
  "columnCountMetadata": "output/split/昭和38年2月1日大阪市50音別電話番号簿/column_count.json",
  "imageCount": 20
}
```

同じ OCR 出力ディレクトリには `ocr_quality.json` も保存する。

```json
{
  "promptVersion": "ocr-target-image-with-prev-tail-v1",
  "ocrOutputSchema": "compact",
  "columnCount": 20,
  "segmentCount": 1420,
  "emptyColumnCount": 0,
  "segmentsWithoutPhone": 12,
  "lowConfidenceSegments": 3,
  "multiPhoneSegments": 18,
  "midEntrySegments": 4,
  "continuedFromPreviousSegments": 2,
  "flaggedSegments": 25,
  "suspiciousColumnCount": 2,
  "suspiciousColumns": [
    {
      "file": "0030-02.ocr.json",
      "page": 30,
      "column": 2,
      "segmentCount": 71,
      "segmentsWithoutPhone": 8,
      "lowConfidenceSegments": 1,
      "multiPhoneSegments": 3,
      "midEntrySegments": 1,
      "continuedFromPreviousSegments": 1,
      "flags": ["many_segments_without_phone", "low_confidence_segments", "mid_entry_segments", "continued_from_previous_segments"]
    }
  ],
  "columns": []
}
```

## 5. 将来の連結後エントリ JSON

ファイル: `output/stitched_entries/<電話帳名>/entries.stitched.json`

```json
{
  "book": "昭和38年2月1日大阪市50音別電話番号簿",
  "entries": [
    {
      "entryId": "0030-02-0007",
      "readingOrder": {
        "page": 30,
        "column": 2,
        "sequence": 7
      },
      "rawFragments": [
        {
          "page": 30,
          "column": 2,
          "segmentId": "0030-02-0007",
          "text": "東区北久宝寺町三ノ"
        },
        {
          "page": 30,
          "column": 3,
          "segmentId": "0030-03-0001",
          "text": "丁目二十三 田中商店 1234"
        }
      ],
      "mergedText": "東区北久宝寺町三ノ丁目二十三 田中商店 1234",
      "continuity": {
        "continuedFromPrevious": false,
        "continuedToNext": true,
        "mergeConfidence": 0.79
      }
    }
  ]
}
```

## 6. 将来の正規化後 JSON

ファイル: `output/normalized_entries/<電話帳名>/entries.normalized.json`

```json
{
  "book": "昭和38年2月1日大阪市50音別電話番号簿",
  "entries": [
    {
      "entryId": "0030-02-0007",
      "source": {
        "mergedText": "東区北久宝寺町三ノ丁目二十三 田中商店 1234"
      },
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
          "expandedTo": "三丁目",
          "reason": "大阪市の丁目表記に正規化"
        }
      ],
      "confidence": {
        "ocr": 0.84,
        "stitch": 0.79,
        "normalize": 0.76
      },
      "reviewFlags": [
        "cross_column_merge",
        "address_expanded"
      ]
    }
  ]
}
```

## 7. 最終 CSV 行

最終出力は次の 6 列だけを持つ。

```text
電話番号,名前,都道府県,市区町村,町域,番地
```

現行実装の `src/export_csv.py` は 5, 6 の独立ステージをまだ持たず、4 の OCR JSON から直接この 6 列へ軽量変換する。
