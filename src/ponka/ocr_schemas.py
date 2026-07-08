"""Structured output schemas for OCR requests."""

OCR_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "segmentId": {"type": "string"},
                    "sequence": {"type": "integer"},
                    "entryType": {
                        "type": "string",
                        "enum": ["directory_entry", "ad_block", "category_heading"],
                    },
                    "rawText": {"type": "string"},
                    "cleanText": {"type": "string"},
                    "indentLevel": {"type": "integer"},
                    "startsMidEntry": {"type": "boolean"},
                    "endsMidEntry": {"type": "boolean"},
                    "entryHints": {
                        "type": "object",
                        "properties": {
                            "phone": {"type": "string"},
                            "name": {"type": "string"},
                            "address": {"type": "string"},
                        },
                        "required": ["phone", "name", "address"],
                    },
                    "phones": {"type": "array", "items": {"type": "string"}},
                    "names": {"type": "array", "items": {"type": "string"}},
                    "addresses": {"type": "array", "items": {"type": "string"}},
                    "reviewFlags": {"type": "array", "items": {"type": "string"}},
                    "continuityFromPrevious": {
                        "type": "object",
                        "properties": {
                            "sameEntry": {"type": "boolean"},
                            "previousSegmentId": {"type": "string"},
                            "mergedCleanText": {"type": "string"},
                            "confidence": {"type": "number"},
                            "reason": {"type": "string"},
                        },
                        "required": [
                            "sameEntry",
                            "previousSegmentId",
                            "mergedCleanText",
                            "confidence",
                            "reason",
                        ],
                    },
                    "confidence": {"type": "number"},
                },
                "required": [
                    "segmentId",
                    "sequence",
                    "entryType",
                    "rawText",
                    "cleanText",
                    "indentLevel",
                    "startsMidEntry",
                    "endsMidEntry",
                    "entryHints",
                    "phones",
                    "names",
                    "addresses",
                    "reviewFlags",
                    "continuityFromPrevious",
                    "confidence",
                ],
            },
        },
    },
    "required": ["segments"],
}

COMPACT_OCR_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "r": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "t": {"type": "string", "enum": ["d", "a", "h"]},
                    "x": {"type": "string"},
                    "i": {"type": "integer"},
                    "p": {"type": "array", "items": {"type": "string"}},
                    "n": {"type": "array", "items": {"type": "string"}},
                    "a": {"type": "array", "items": {"type": "string"}},
                    "f": {"type": "array", "items": {"type": "string"}},
                    "s": {"type": "boolean"},
                    "e": {"type": "boolean"},
                },
                "required": ["t", "x", "i", "p", "n", "a"],
            },
        },
    },
    "required": ["r"],
}

SLIM_OCR_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "entryType": {
                        "type": "string",
                        "enum": ["directory_entry", "ad_block", "category_heading"],
                    },
                    "cleanText": {"type": "string"},
                    "indentLevel": {"type": "integer"},
                    "phones": {"type": "array", "items": {"type": "string"}},
                    "names": {"type": "array", "items": {"type": "string"}},
                    "addresses": {"type": "array", "items": {"type": "string"}},
                    "reviewFlags": {"type": "array", "items": {"type": "string"}},
                    "startsMidEntry": {"type": "boolean"},
                    "endsMidEntry": {"type": "boolean"},
                },
                "required": [
                    "entryType",
                    "cleanText",
                    "indentLevel",
                    "phones",
                    "names",
                    "addresses",
                    "reviewFlags",
                ],
            },
        },
    },
    "required": ["segments"],
}
