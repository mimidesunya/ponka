"""Historical address normalization helpers for Osaka phonebooks.

The OCR stage keeps candidates as text. This module performs deterministic,
dictionary-based expansion of common municipality and ward abbreviations used in
the source phonebooks.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class AddressProfile:
    wards: set[str]
    cities: set[str]
    towns_villages: dict[str, str]
    municipality_abbreviations: dict[str, str]


OSAKA_CITY_WARDS_1963 = {
    "北区",
    "都島区",
    "福島区",
    "此花区",
    "東区",
    "西区",
    "港区",
    "大正区",
    "天王寺区",
    "南区",
    "大淀区",
    "浪速区",
    "西淀川区",
    "東淀川区",
    "東成区",
    "生野区",
    "旭区",
    "城東区",
    "阿倍野区",
    "住吉区",
    "東住吉区",
    "西成区",
}


OSAKA_CITY_WARDS_1968_03_01 = set(OSAKA_CITY_WARDS_1963)


OSAKA_CITIES_1963_02_01 = {
    "大阪市",
    "堺市",
    "岸和田市",
    "豊中市",
    "池田市",
    "吹田市",
    "泉大津市",
    "高槻市",
    "貝塚市",
    "守口市",
    "枚方市",
    "茨木市",
    "八尾市",
    "泉佐野市",
    "富田林市",
    "寝屋川市",
    "河内長野市",
    "松原市",
    "大東市",
    "和泉市",
    "箕面市",
    "柏原市",
    "羽曳野市",
    "布施市",
    "枚岡市",
    "河内市",
}


OSAKA_CITIES_1968_03_01 = {
    city
    for city in OSAKA_CITIES_1963_02_01
    if city not in {"布施市", "河内市", "枚岡市"}
} | {
    "門真市",
    "摂津市",
    "高石市",
    "藤井寺市",
    "東大阪市",
}


OSAKA_TOWNS_VILLAGES_1963_02_01 = {
    "島本": "三島郡島本町",
    "島本町": "三島郡島本町",
    "三島": "三島郡三島町",
    "三島町": "三島郡三島町",
    "能勢": "豊能郡能勢町",
    "能勢町": "豊能郡能勢町",
    "東能勢": "豊能郡東能勢村",
    "東能勢村": "豊能郡東能勢村",
    "門真": "北河内郡門真町",
    "門真町": "北河内郡門真町",
    "四條畷": "北河内郡四條畷町",
    "四條畷町": "北河内郡四條畷町",
    "交野": "北河内郡交野町",
    "交野町": "北河内郡交野町",
    "高石": "泉北郡高石町",
    "高石町": "泉北郡高石町",
    "忠岡": "泉北郡忠岡町",
    "忠岡町": "泉北郡忠岡町",
    "熊取": "泉南郡熊取町",
    "熊取町": "泉南郡熊取町",
    "田尻": "泉南郡田尻町",
    "田尻町": "泉南郡田尻町",
    "岬": "泉南郡岬町",
    "岬町": "泉南郡岬町",
    "泉南": "泉南郡泉南町",
    "泉南町": "泉南郡泉南町",
    "南海": "泉南郡南海町",
    "南海町": "泉南郡南海町",
    "東鳥取": "泉南郡東鳥取町",
    "東鳥取町": "泉南郡東鳥取町",
    "太子": "南河内郡太子町",
    "太子町": "南河内郡太子町",
    "河南": "南河内郡河南町",
    "河南町": "南河内郡河南町",
    "美原": "南河内郡美原町",
    "美原町": "南河内郡美原町",
    "千早赤阪": "南河内郡千早赤阪村",
    "千早赤阪村": "南河内郡千早赤阪村",
    "狭山": "南河内郡狭山町",
    "狭山町": "南河内郡狭山町",
    "美陵": "南河内郡美陵町",
    "美陵町": "南河内郡美陵町",
}


OSAKA_TOWNS_VILLAGES_1968_03_01 = {
    key: value
    for key, value in OSAKA_TOWNS_VILLAGES_1963_02_01.items()
    if value
    not in {
        "三島郡三島町",
        "北河内郡門真町",
        "泉北郡高石町",
        "南河内郡美陵町",
    }
}


OSAKA_DISTRICT_ABBREVIATIONS = {
    "北河": "北河内郡",
    "北河内": "北河内郡",
    "北河内郡": "北河内郡",
    "南河": "南河内郡",
    "南河内": "南河内郡",
    "南河内郡": "南河内郡",
    "泉北": "泉北郡",
    "泉北郡": "泉北郡",
    "泉南": "泉南郡",
    "泉南郡": "泉南郡",
    "三島郡": "三島郡",
    "豊能": "豊能郡",
    "豊能郡": "豊能郡",
}


OSAKA_CITY_WARD_ABBREVIATIONS = {
    "北": "大阪市北区",
    "大淀": "大阪市大淀区",
    "都": "大阪市都島区",
    "都島": "大阪市都島区",
    "福": "大阪市福島区",
    "福島": "大阪市福島区",
    "此": "大阪市此花区",
    "此花": "大阪市此花区",
    "東": "大阪市東区",
    "西": "大阪市西区",
    "港": "大阪市港区",
    "大": "大阪市大正区",
    "大正": "大阪市大正区",
    "天": "大阪市天王寺区",
    "天王寺": "大阪市天王寺区",
    "南": "大阪市南区",
    "浪": "大阪市浪速区",
    "浪速": "大阪市浪速区",
    "西淀": "大阪市西淀川区",
    "西淀川": "大阪市西淀川区",
    "東淀": "大阪市東淀川区",
    "東淀川": "大阪市東淀川区",
    "東成": "大阪市東成区",
    "生": "大阪市生野区",
    "生野": "大阪市生野区",
    "旭": "大阪市旭区",
    "城": "大阪市城東区",
    "城東": "大阪市城東区",
    "阿": "大阪市阿倍野区",
    "阿倍野": "大阪市阿倍野区",
    "住": "大阪市住吉区",
    "住吉": "大阪市住吉区",
    "東住": "大阪市東住吉区",
    "東住吉": "大阪市東住吉区",
    "西成": "大阪市西成区",
}


OSAKA_MUNICIPALITY_ABBREVIATIONS = {
    "堺": "堺市",
    "岸和田": "岸和田市",
    "豊": "豊中市",
    "豊中": "豊中市",
    "池田": "池田市",
    "吹": "吹田市",
    "吹田": "吹田市",
    "泉大津": "泉大津市",
    "高槻": "高槻市",
    "貝塚": "貝塚市",
    "守": "守口市",
    "守口": "守口市",
    "枚方": "枚方市",
    "茨木": "茨木市",
    "八尾": "八尾市",
    "泉佐野": "泉佐野市",
    "富田林": "富田林市",
    "寝屋川": "寝屋川市",
    "河内長野": "河内長野市",
    "松原": "松原市",
    "大東": "大東市",
    "和泉": "和泉市",
    "箕面": "箕面市",
    "柏原": "柏原市",
    "羽曳野": "羽曳野市",
    "布": "布施市",
    "布施": "布施市",
    "河内": "河内市",
    "枚岡": "枚岡市",
}


OSAKA_MUNICIPALITY_ABBREVIATIONS_1968_03_01 = {
    **{
        key: value
        for key, value in OSAKA_MUNICIPALITY_ABBREVIATIONS.items()
        if value not in {"布施市", "河内市", "枚岡市"}
    },
    "門真": "門真市",
    "摂津": "摂津市",
    "三島": "摂津市",
    "高石": "高石市",
    "藤": "藤井寺市",
    "藤井寺": "藤井寺市",
    "美陵": "藤井寺市",
    "東大阪": "東大阪市",
    "布": "東大阪市",
    "布施": "東大阪市",
    "河内": "東大阪市",
    "枚岡": "東大阪市",
}


NEIGHBORING_MUNICIPALITY_ABBREVIATIONS = {
    "尼": ("兵庫県", "尼崎市"),
    "尼崎": ("兵庫県", "尼崎市"),
    "伊丹": ("兵庫県", "伊丹市"),
    "西宮": ("兵庫県", "西宮市"),
    "芦屋": ("兵庫県", "芦屋市"),
    "神戸": ("兵庫県", "神戸市"),
}


ADDRESS_PROFILES = {
    "1963-02-01": AddressProfile(
        wards=OSAKA_CITY_WARDS_1963,
        cities=OSAKA_CITIES_1963_02_01,
        towns_villages=OSAKA_TOWNS_VILLAGES_1963_02_01,
        municipality_abbreviations=OSAKA_MUNICIPALITY_ABBREVIATIONS,
    ),
    "1968-03-01": AddressProfile(
        wards=OSAKA_CITY_WARDS_1968_03_01,
        cities=OSAKA_CITIES_1968_03_01,
        towns_villages=OSAKA_TOWNS_VILLAGES_1968_03_01,
        municipality_abbreviations=OSAKA_MUNICIPALITY_ABBREVIATIONS_1968_03_01,
    ),
}


def address_profile_for_date(as_of: str | None = None) -> AddressProfile:
    if as_of and as_of >= "1968-03-01":
        return ADDRESS_PROFILES["1968-03-01"]
    return ADDRESS_PROFILES["1963-02-01"]


def normalize_text(text: str) -> str:
    return unicodedata.normalize("NFKC", text).strip()


def split_address_fields(address: str, as_of: str | None = None) -> tuple[str, str, str, str]:
    """Return prefecture, municipality, area, lot number.

    Handles common historical abbreviations such as ``東,内淡路1-28`` and
    ``布,中小阪483``. Unknown forms fall back to the previous light parser.
    """
    normalized = normalize_text(address).replace("、", ",").replace("，", ",")
    normalized = re.sub(r"\s+", "", normalized)
    if not normalized:
        return "大阪府", "大阪市", "", ""

    profile = address_profile_for_date(as_of)
    expanded_fields = expand_address_prefix(normalized, profile)
    if expanded_fields is not None:
        return expanded_fields

    prefecture = "大阪府"
    municipality = "大阪市"
    area = normalized

    city_ward_match = re.search(r"(?:大阪市)?([^\s,]{1,12}?区)", normalized)
    if city_ward_match:
        municipality = f"大阪市{city_ward_match.group(1)}"
        area = normalized[city_ward_match.end() :].strip(",")

    area, lot_number = split_lot_number(area)
    return prefecture, municipality, area, lot_number


def split_prefix(address: str) -> tuple[str, str]:
    if "," not in address:
        return split_prefix_without_separator(address)
    prefix, rest = address.split(",", 1)
    return prefix.strip(), rest.strip()


def split_prefix_candidates(address: str, profile: AddressProfile | None = None) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    if "," in address:
        candidates.append(split_prefix(address))
    candidates.append(split_prefix_without_separator(address, profile))

    unique: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for prefix, rest in candidates:
        if prefix and (prefix, rest) not in seen:
            unique.append((prefix, rest))
            seen.add((prefix, rest))
    return unique


def expand_address_prefix(address: str, profile: AddressProfile) -> tuple[str, str, str, str] | None:
    for prefix, rest in split_prefix_candidates(address, profile):
        district_expanded = expand_district_prefix(prefix, rest, profile)
        if district_expanded is not None:
            prefecture, municipality, expanded_rest = district_expanded
            area, lot_number = split_lot_number(expanded_rest)
            return prefecture, municipality, area, lot_number

        expanded = expand_prefix(prefix, profile)
        if expanded is not None:
            prefecture, municipality = expanded
            expanded_rest = drop_repeated_prefix(rest, prefix, profile)
            area, lot_number = split_lot_number(expanded_rest)
            return prefecture, municipality, area, lot_number

    return None


def split_prefix_without_separator(address: str, profile: AddressProfile | None = None) -> tuple[str, str]:
    for prefix in prefix_candidates_by_length_for_profile(profile or address_profile_for_date()):
        if address.startswith(prefix) and address != prefix:
            return prefix, address[len(prefix) :].strip()
    return "", address


def prefix_candidates_by_length(as_of: str | None = None) -> list[str]:
    profile = address_profile_for_date(as_of)
    return prefix_candidates_by_length_for_profile(profile)


def prefix_candidates_by_length_for_profile(profile: AddressProfile) -> list[str]:
    prefixes = set(profile.wards)
    prefixes.update(profile.cities)
    prefixes.update(OSAKA_CITY_WARD_ABBREVIATIONS)
    prefixes.update(profile.municipality_abbreviations)
    prefixes.update(profile.towns_villages)
    prefixes.update(profile.towns_villages.values())
    prefixes.update(OSAKA_DISTRICT_ABBREVIATIONS)
    prefixes.update(NEIGHBORING_MUNICIPALITY_ABBREVIATIONS)
    return sorted(prefixes, key=len, reverse=True)


def expand_district_prefix(prefix: str, rest: str, profile: AddressProfile) -> tuple[str, str, str] | None:
    district = OSAKA_DISTRICT_ABBREVIATIONS.get(prefix)
    if not district:
        return None

    for town_prefix, municipality in sorted(
        profile.towns_villages.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        if not municipality.startswith(district):
            continue
        if rest.startswith(town_prefix):
            return "大阪府", municipality, rest[len(town_prefix) :].strip(",")

    return None


def expand_prefix(prefix: str, profile: AddressProfile | None = None) -> tuple[str, str] | None:
    profile = profile or address_profile_for_date()
    if prefix.startswith("大阪市"):
        ward = prefix.removeprefix("大阪市")
        if ward in profile.wards:
            return "大阪府", f"大阪市{ward}"
    if prefix in profile.wards:
        return "大阪府", f"大阪市{prefix}"
    if prefix in OSAKA_CITY_WARD_ABBREVIATIONS:
        return "大阪府", OSAKA_CITY_WARD_ABBREVIATIONS[prefix]
    if prefix in profile.cities:
        return "大阪府", prefix
    if prefix in profile.municipality_abbreviations:
        return "大阪府", profile.municipality_abbreviations[prefix]
    if prefix in profile.towns_villages:
        return "大阪府", profile.towns_villages[prefix]
    if prefix in set(profile.towns_villages.values()):
        return "大阪府", prefix
    if prefix in NEIGHBORING_MUNICIPALITY_ABBREVIATIONS:
        return NEIGHBORING_MUNICIPALITY_ABBREVIATIONS[prefix]
    return None


def drop_repeated_prefix(rest: str, prefix: str, profile: AddressProfile | None = None) -> str:
    candidates = [prefix, local_municipality_name(prefix)]
    expanded = expand_prefix(prefix, profile)
    if expanded is not None:
        candidates.append(local_municipality_name(expanded[1]))
    for candidate in sorted({item for item in candidates if len(item) >= 2}, key=len, reverse=True):
        if rest.startswith(candidate):
            return rest[len(candidate) :].strip(",")
    return rest


def local_municipality_name(municipality: str) -> str:
    local_name = municipality.rsplit("郡", 1)[-1]
    for suffix in ("市", "町", "村", "区"):
        if local_name.endswith(suffix):
            return local_name[: -len(suffix)]
    return local_name


def split_lot_number(area: str) -> tuple[str, str]:
    lot_match = re.search(r"([0-9]+(?:-[0-9]+)*)$", area)
    if not lot_match:
        return area, ""
    lot_number = lot_match.group(1)
    return area[: lot_match.start()].strip(), lot_number
