"""Country normalization for aggregate reporting.

The student record stores a free-text nationality, entered from source
documents. A map needs ISO 3166-1 alpha-2 codes, so the values are matched
against an explicit name/alias table. Matching is exact after case and
whitespace folding: a name is never guessed from a phone code, a language or a
student's name. Values that do not match stay in the unmapped bucket.

Only aggregate counts leave this module. It never returns a student.
"""

from __future__ import annotations

import re

# Official short names and the common variants found in international
# admission files. Keys are folded with ``normalize_key`` before lookup.
_COUNTRY_NAMES: dict[str, str] = {
    "afghanistan": "AF", "albania": "AL", "algeria": "DZ", "andorra": "AD",
    "angola": "AO", "antigua and barbuda": "AG", "argentina": "AR",
    "armenia": "AM", "australia": "AU", "austria": "AT", "azerbaijan": "AZ",
    "bahamas": "BS", "bahrain": "BH", "bangladesh": "BD", "barbados": "BB",
    "belarus": "BY", "belgium": "BE", "belize": "BZ", "benin": "BJ",
    "bhutan": "BT", "bolivia": "BO", "bosnia and herzegovina": "BA",
    "botswana": "BW", "brazil": "BR", "brunei": "BN", "brunei darussalam": "BN",
    "bulgaria": "BG", "burkina faso": "BF", "burundi": "BI", "cabo verde": "CV",
    "cape verde": "CV", "cambodia": "KH", "cameroon": "CM", "canada": "CA",
    "central african republic": "CF", "chad": "TD", "chile": "CL", "china": "CN",
    "colombia": "CO", "comoros": "KM", "congo": "CG", "congo brazzaville": "CG",
    "republic of the congo": "CG", "democratic republic of the congo": "CD",
    "democratic republic of congo": "CD", "dr congo": "CD", "costa rica": "CR",
    "cote d ivoire": "CI", "côte d ivoire": "CI", "ivory coast": "CI",
    "croatia": "HR", "cuba": "CU", "cyprus": "CY", "czechia": "CZ",
    "czech republic": "CZ", "denmark": "DK", "djibouti": "DJ", "dominica": "DM",
    "dominican republic": "DO", "ecuador": "EC", "egypt": "EG",
    "el salvador": "SV", "equatorial guinea": "GQ", "eritrea": "ER",
    "estonia": "EE", "eswatini": "SZ", "swaziland": "SZ", "ethiopia": "ET",
    "fiji": "FJ", "finland": "FI", "france": "FR", "gabon": "GA",
    "gambia": "GM", "georgia": "GE", "germany": "DE", "ghana": "GH",
    "greece": "GR", "grenada": "GD", "guatemala": "GT", "guinea": "GN",
    "guinea bissau": "GW", "guyana": "GY", "haiti": "HT", "honduras": "HN",
    "hungary": "HU", "iceland": "IS", "india": "IN", "indonesia": "ID",
    "iran": "IR", "iraq": "IQ", "ireland": "IE", "israel": "IL", "italy": "IT",
    "jamaica": "JM", "japan": "JP", "jordan": "JO", "kazakhstan": "KZ",
    "kenya": "KE", "kiribati": "KI", "kuwait": "KW", "kyrgyzstan": "KG",
    "laos": "LA", "latvia": "LV", "lebanon": "LB", "lesotho": "LS",
    "liberia": "LR", "libya": "LY", "liechtenstein": "LI", "lithuania": "LT",
    "luxembourg": "LU", "madagascar": "MG", "malawi": "MW", "malaysia": "MY",
    "maldives": "MV", "mali": "ML", "malta": "MT", "marshall islands": "MH",
    "mauritania": "MR", "mauritius": "MU", "mexico": "MX", "micronesia": "FM",
    "moldova": "MD", "monaco": "MC", "mongolia": "MN", "montenegro": "ME",
    "morocco": "MA", "mozambique": "MZ", "myanmar": "MM", "burma": "MM",
    "namibia": "NA", "nauru": "NR", "nepal": "NP", "netherlands": "NL",
    "holland": "NL", "new zealand": "NZ", "nicaragua": "NI", "niger": "NE",
    "nigeria": "NG", "north korea": "KP", "north macedonia": "MK",
    "macedonia": "MK", "norway": "NO", "oman": "OM", "pakistan": "PK",
    "palau": "PW", "palestine": "PS", "panama": "PA", "papua new guinea": "PG",
    "paraguay": "PY", "peru": "PE", "philippines": "PH", "poland": "PL",
    "portugal": "PT", "qatar": "QA", "romania": "RO", "russia": "RU",
    "russian federation": "RU", "rwanda": "RW", "saint kitts and nevis": "KN",
    "saint lucia": "LC", "saint vincent and the grenadines": "VC",
    "samoa": "WS", "san marino": "SM", "sao tome and principe": "ST",
    "saudi arabia": "SA", "senegal": "SN", "serbia": "RS", "seychelles": "SC",
    "sierra leone": "SL", "singapore": "SG", "slovakia": "SK", "slovenia": "SI",
    "solomon islands": "SB", "somalia": "SO", "south africa": "ZA",
    "south korea": "KR", "korea": "KR", "republic of korea": "KR",
    "south sudan": "SS", "spain": "ES", "sri lanka": "LK", "sudan": "SD",
    "suriname": "SR", "sweden": "SE", "switzerland": "CH", "syria": "SY",
    "taiwan": "TW", "tajikistan": "TJ", "tanzania": "TZ", "thailand": "TH",
    "timor leste": "TL", "east timor": "TL", "togo": "TG", "tonga": "TO",
    "trinidad and tobago": "TT", "tunisia": "TN", "turkiye": "TR", "turkey": "TR",
    "turkmenistan": "TM", "tuvalu": "TV", "uganda": "UG", "ukraine": "UA",
    "united arab emirates": "AE", "uae": "AE", "united kingdom": "GB",
    "uk": "GB", "great britain": "GB", "britain": "GB", "england": "GB",
    "scotland": "GB", "wales": "GB", "united states": "US", "united states of america": "US",
    "usa": "US", "us": "US", "uruguay": "UY", "uzbekistan": "UZ",
    "vanuatu": "VU", "vatican city": "VA", "venezuela": "VE", "vietnam": "VN",
    "viet nam": "VN", "yemen": "YE", "zambia": "ZM", "zimbabwe": "ZW",
    # Common adjectival forms used in nationality fields.
    "american": "US", "british": "GB", "chinese": "CN", "indian": "IN",
    "indonesian": "ID", "japanese": "JP", "korean": "KR", "south korean": "KR",
    "malaysian": "MY", "pakistani": "PK", "filipino": "PH", "filipina": "PH",
    "thai": "TH", "vietnamese": "VN", "bangladeshi": "BD", "nepali": "NP",
    "sri lankan": "LK", "iranian": "IR", "iraqi": "IQ", "syrian": "SY",
    "lebanese": "LB", "jordanian": "JO", "saudi": "SA", "emirati": "AE",
    "qatari": "QA", "kuwaiti": "KW", "omani": "OM", "bahraini": "BH",
    "yemeni": "YE", "egyptian": "EG", "moroccan": "MA", "algerian": "DZ",
    "tunisian": "TN", "libyan": "LY", "sudanese": "SD", "ethiopian": "ET",
    "eritrean": "ER", "somali": "SO", "kenyan": "KE", "ugandan": "UG",
    "tanzanian": "TZ", "rwandan": "RW", "burundian": "BI", "nigerian": "NG",
    "ghanaian": "GH", "ivorian": "CI", "senegalese": "SN", "malian": "ML",
    "cameroonian": "CM", "congolese": "CD", "angolan": "AO", "zambian": "ZM",
    "zimbabwean": "ZW", "south african": "ZA", "mozambican": "MZ",
    "turkish": "TR", "russian": "RU", "ukrainian": "UA", "polish": "PL",
    "german": "DE", "french": "FR", "italian": "IT", "spanish": "ES",
    "portuguese": "PT", "dutch": "NL", "belgian": "BE", "swiss": "CH",
    "austrian": "AT", "swedish": "SE", "norwegian": "NO", "danish": "DK",
    "finnish": "FI", "irish": "IE", "greek": "GR", "croatian": "HR",
    "serbian": "RS", "bulgarian": "BG", "romanian": "RO", "hungarian": "HU",
    "czech": "CZ", "slovak": "SK", "slovenian": "SI", "australian": "AU",
    "new zealander": "NZ", "canadian": "CA", "mexican": "MX", "brazilian": "BR",
    "argentinian": "AR", "chilean": "CL", "colombian": "CO", "peruvian": "PE",
    "venezuelan": "VE", "ecuadorian": "EC", "bolivian": "BO", "uruguayan": "UY",
}


def normalize_key(value: str) -> str:
    """Fold punctuation, diacritics and whitespace for a stable lookup."""
    cleaned = (
        value.strip()
        .casefold()
        .replace("&", " and ")
        .replace(".", " ")
        .replace("-", " ")
        .replace("’", " ")
        .replace("'", " ")
    )
    return re.sub(r"\s+", " ", cleaned).strip()


def country_code(value: str | None) -> str | None:
    """Return the ISO alpha-2 code for an exact known country value."""
    if value is None:
        return None
    return _COUNTRY_NAMES.get(normalize_key(value))


__all__ = ["country_code", "normalize_key"]
