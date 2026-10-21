"""iPhone listing text -> structured specs.

Pure regex over `Ad.name + Ad.short_description`, standard library only, for the same reason
`features.py` is: this runs inside `run_filter` on a Raspberry Pi.

Ported from `experiments/price_model/iphone/ipfeat.py`, which is the measured version behind
`docs/research/IPHONE_PRICE_MODEL.md`. Two deliberate differences from that file, both
required by that doc's §8 and `docs/backlog/PRICE_MODEL_DEFECTS.md` §13:

- **The generation axis is live, not a frozen table.** A numeric generation is read off its
  own digits and its release date derived, so an iPhone 19 prices itself the day it appears.
  Frozen levels under-priced a held-out generation by 73.8% and made it invisible to a −25%
  alert — a failure that is silent until launch day and then mutes the most expensive items
  in the feed (research §5.1).
- **The `zadn` negation defect is fixed here.** The experiment keeps it so its published
  figures reproduce; shipping it would pass cracked phones into the alert the gate exists to
  stop. See `_neg_aware`.

The extractor is at its information ceiling, which is the unusual part: generation misses
1 real listing in 655, and of the rows with no storage, **not one contains a GB or TB token
anywhere** (research §3). Widening a regex here buys nothing; the missing text is missing.
"""
import math
import re
from datetime import date
from typing import Any

from bazos.pricing.features import strip_diacritics


def norm(s: str) -> str:
    """Lowercase, de-accent, unify quote and dash glyphs.

    Commas, slashes, pipes and newlines are **preserved** — they are clause barriers, and
    the dealer template's `Stav:` / `Baterie:` lines stay separable only if newlines survive.
    This is why it is not `features.norm`, which collapses all whitespace.
    """
    s = (s or "").lower()
    s = strip_diacritics(s)
    s = s.replace("”", '"').replace("“", '"').replace("’", "'").replace("´", "'")
    s = s.replace("–", "-").replace("—", "-").replace(" ", " ")
    s = re.sub(r"\r\n?", "\n", s)
    s = re.sub(r"[ \t]+", " ", s)
    return re.sub(r"\n{2,}", "\n", s)


#: Anything date-shaped, stripped before every numeric read: `zaruka do 04/2027` otherwise
#: parses as 4 GB and a warranty of 2027 months.
DATEISH = re.compile(
    r"\b(?:do|az do|plati do|zaruka do|v zaruce do|koupeno|zakoupeno|zakoupen|vystaven)\s*"
    r"(?:\d{1,2}\s*[./]\s*)?(?:\d{1,2}\s*[./]\s*)?(20[0-3]\d)\b"
    r"|\b\d{1,2}\s*[./]\s*\d{1,2}\s*[./]\s*(?:20)?\d{2}\b"
    r"|\b\d{1,2}\s*/\s*20[0-3]\d\b"
    r"|\b(?:leden|unor|brezen|duben|kveten|cerven|cervenec|srpen|zari|rijen|listopad|prosinec"
    r"|lednu|unoru|breznu|dubnu|kvetnu|cervnu|cervenci|srpnu|rijnu|listopadu|prosinci)"
    r"\s*20[0-3]\d\b"
)

#: A price in the text, removed before capacity parsing so a four-digit amount can never be
#: read as a capacity.
PRICEISH = re.compile(r"\b\d{1,3}(?:[ .]\d{3})+\s*(?:,-\s*)?(?:kc|czk)\b"
                      r"|\b\d{3,6}\s*(?:,-|kc\b|czk\b)"
                      r"|\bza\s+\d{1,3}(?:[ .]\d{3})+\b|\bcena\s*:?\s*\d{3,6}\b")

# ------------------------------------------------------------------ product family
#: `apple` is an accepted anchor because a handful of sellers write `Apple 17 Pro 256Gb` with
#: no `iPhone` anywhere in the title.
ANCHOR = re.compile(r"\b(?:iphone|i ?phone|ifon|ajfon|apple)(?![a-z])\s*\(?\s*")
IPHONE = re.compile(r"\b(?:iphone|i phone|ifon|ajfon)\b")

OTHER_APPLE = re.compile(r"\b(?:ipad|macbook|mac ?mini|imac|apple ?watch|airpod|ipod|air ?tag|homepod)\b")
OTHER_BRAND = re.compile(
    r"\b(?:samsung|galaxy|xiaomi|redmi|poco|huawei|honor|oneplus|oppo|vivo|realme|nokia|motorola|sony xperia)\b"
)

#: Anchored on what is being SOLD: `obal na iphone 17` is a case, `iphone 13 + obal` is a
#: phone with a case thrown in.
ACCESSORY_SUBJECT = re.compile(
    r"^\s*(?:prodam\s+|prodavam\s+|nabizim\s+)?"
    r"(?:obal|kryt|pouzdro|pouzdra|sklo|sklicko|tvrzene sklo|folie|klavesnic\w*|clicks|"
    r"nabijeck\w*|kabel|adapter|powerbank|magsafe|drzak|stojan|sluchatk\w*|"
    r"displej\w*|lcd|baterie|baterk\w*|dily|nahradni dily|zadni sklo)\b"
)
ACCESSORY_FOR = re.compile(
    r"\b(?:obal|kryt|pouzdro|sklo|sklicko|folie|klavesnice|nabijecka|kabel|adapter|displej|lcd|baterie)"
    r"\s+(?:na|pro|k)\s+(?:apple\s*)?iphone\b"
)
PARTS = re.compile(r"\bna dily\b|\bna opravu\b|\bna repas\b|\brepas\b|\bdisplej\w*\s*="
                   r"|\bnahradni dily\b|zakladni deska|maticni deska|motherboard|logic board")
#: The same intent stated only in the description needs a SELLING verb next to it:
#: `repasovany original displej` (a refurbished screen in a working phone) and `zadny repas`
#: (a denial) both carry the vocabulary and are not parts ads.
PARTS_DESC = re.compile(r"(?:prodam|prodavam|nabizim)[^.\n]{0,70}?"
                        r"(?:\bna dily\b|\bna opravu\b|\bnahradni dily\b|\bna nahradni dily\b)")
#: Want-to-buy, and the single most important contamination class: their price is a **bid**,
#: not an ask, and they sit at the top of the distribution where they drag predictions up.
WTB = re.compile(r"\bkoupim\b|\bkupim\b|\bodkoupim\b|\bvykup\w*|\bvykoup\w*|\bhledam\s+(?:iphone|apple|koupi)")
#: The iPhone 18 launch filled the category with resold places in the pre-order queue. The
#: ask is a deposit of ~1 000 CZK against a ~35 000 CZK phone, so every one reads as a
#: 97%-below-market deal, and they were the largest single defect measured on this corpus.
RESERVATION = re.compile(r"rezervac\w*|prenechani|prenecham|predobjednav\w*|objednavk\w*|objednan\w* iphone"
                         r"|k vyzvednuti|\bzaloh[ay]\b|\bzalohu\b|\bod \d{1,2}\s*\.\s*\d{1,2}\s*\.")
#: The seller marked it sold and left it up, usually at a stale price.
SOLD = re.compile(r"\bprodano\b|\brezervovano\b|\bstazeno\b|\bjiz prodano\b")
#: Several phones for one price.
MULTIPACK = re.compile(r"\b([2-9])\s*[x×]\s*(?:apple\s*)?iphone|^\s*([2-9])\s*[x×]\b")

# ------------------------------------------------------------------ model phrase
#: Release month of each generation whose name does not carry its own position. Everything
#: numeric from 11 up is derived instead (see `_release`), which is what keeps a new
#: generation priceable the day it ships.
_RELEASE: dict[str, tuple[int, int]] = {
    "4": (2010, 6), "4s": (2011, 10), "5": (2012, 9), "5c": (2013, 9), "5s": (2013, 9),
    "6": (2014, 9), "6s": (2015, 9), "7": (2016, 9), "8": (2017, 9),
    "x": (2017, 11), "xr": (2018, 10), "xs": (2018, 9),
}
#: Generation ordinal for the lettered names, placed by release order so the axis stays
#: monotone in time: X (2017) 10.0, XR (2018) 10.2, XS (2018) 10.5.
_GEN_ORD: dict[str, float] = {
    "4": 4.0, "4s": 4.5, "5": 5.0, "5c": 5.2, "5s": 5.5, "6": 6.0, "6s": 6.5,
    "7": 7.0, "8": 8.0, "x": 10.0, "xr": 10.2, "xs": 10.5,
}
#: SE is a body from one era with a chip from another, and the market prices the chip:
#: SE1 ≈ 6s (A9), SE2020 ≈ 11 (A13), SE2022 ≈ 13 (A15). Mapping it onto an existing
#: generation is the interpolation bet applied to the one sub-line that would otherwise need
#: three free dummies.
_SE_EQUIV = {"2016": "6s", "2020": "11", "2022": "13", "1": "6s", "2": "11", "3": "13"}
_SE_DEFAULT = "11"
#: The only `iPhone Air` is the 2025 one, contemporaneous with the 17.
_AIR_EQUIV = "17"

#: First numeric generation whose release is derived rather than tabulated. Apple skipped 9,
#: so below this the spacing is irregular and has to be written down.
_DERIVED_FROM = 11
#: Generation N ships in September of `_EPOCH + N` for N >= `_DERIVED_FROM`: 11 -> 2019,
#: 17 -> 2025, 18 -> 2026. Verified against every generation from 11 to 18.
_EPOCH = 2008

_MODEL_TOKEN = re.compile(
    r"(?:"
    r"(?P<se>se)(?:\s*\(?\s*(?P<seyear>2016|2020|2022)\s*\)?|\s*(?:gen\.?\s*)?(?P<segen>[123])\b)?"
    r"|(?P<air>air)"
    r"|(?P<xsmax>xs\s*max)"
    r"|(?P<roman>xs|xr|x)(?![a-z0-9])"
    r"|(?P<num>\d{1,2})(?P<nsuf>s|c)?(?![0-9])"
    r")"
)
#: `pro max` is matched before bare `pro` so "Pro Max" can never be read as "Pro".
#: `(?![a-z])` rather than `\b`: `iphone16pro128 gb` is one unspaced token and there is no
#: word boundary between `pro` and `128`.
_TIER_TOKEN = re.compile(r"(?P<sp>\s*)(?:(?P<promax>pro\s*max(?![a-z]))|(?P<pro>pro(?![a-z]))"
                         r"|(?P<max>max(?![a-z]))|(?P<plus>plus(?![a-z]))|(?P<mini>mini(?![a-z]))"
                         r"|(?P<air>air(?![a-z]))|(?P<e>e(?![a-z0-9])))")
#: A tier word may only be consumed across these; anything else ends the model phrase.
#: ⚠️ **A tier word separated from the generation by a capacity is deliberately not
#: consumed**, so `iPhone 18 512GB pro` reads as a base 18. Searching the whole title for a
#: tier word instead would fix it and open a worse hole: in Czech `pro` is the preposition
#: "for". Measured on 7 323 titles, one has a tier word after a capacity and none has the
#: preposition there -- and the errors are not symmetric, because reading a base phone as a
#: Pro over-predicts ~30% and turns a fair ask into a deal. Re-measure both directions
#: before changing this.
_TIER_STOP = re.compile(r"[,|;/\n(]")

TIER_ORDER = {"e": 0, "se": 0, "mini": 1, "base": 2, "plus": 3, "max": 3, "air": 4, "pro": 5, "pro max": 6}

#: Outside this range a parsed number is not a generation. The upper bound is deliberately
#: generous rather than tight to the newest model: a generation this does not know is priced
#: by interpolation, which is the whole point of the ordinal, and the gate that matters is
#: `storage`, not this.
_GEN_MIN, _GEN_MAX = 4, 30


def _release(label: str) -> tuple[int, int] | None:
    """(year, month) this generation went on sale, or None if the label is not one."""
    if label in _RELEASE:
        return _RELEASE[label]
    digits = label.rstrip("e")
    if digits.isdigit() and _DERIVED_FROM <= int(digits) <= _GEN_MAX:
        return _EPOCH + int(digits), 9
    return None


def _gen_ordinal(label: str) -> float | None:
    if label in _GEN_ORD:
        return _GEN_ORD[label]
    digits = label.rstrip("e")
    return float(digits) if digits.isdigit() else None


def gen_age_months(label: str | None, today: date | None = None) -> float | None:
    """Months from this generation's release to now, or None for an unknown label.

    A live feature, not a frozen level. The alternative — one dummy per generation — collapses
    to the intercept on a generation the training set never saw, which is exactly the day the
    feed fills with the newest and most expensive phones (research §3.1, §5.1). Clamped at 0
    so a pre-release listing does not get a negative age.
    """
    if not label:
        return None
    released = _release(label.removeprefix("se"))
    if released is None:
        return None
    today = today or date.today()
    year, month = released
    return max(0.0, float((today.year - year) * 12 + (today.month - month)))


def _parse_model_at(t: str, pos: int):
    """Parse one model phrase at `pos`. Returns (gen_ordinal, label, tier, end) or None."""
    m = _MODEL_TOKEN.match(t, pos)
    if not m:
        return None
    tier = "base"
    if m.group("se"):
        y = m.group("seyear") or m.group("segen")
        label = "se" + _SE_EQUIV.get(y, _SE_DEFAULT) if y else "se" + _SE_DEFAULT
        tier = "se"
    elif m.group("air"):
        label, tier = _AIR_EQUIV, "air"
    elif m.group("xsmax"):
        label, tier = "xs", "max"
    elif m.group("roman"):
        label = m.group("roman")
    else:
        key = m.group("num") + (m.group("nsuf") or "")
        if _gen_ordinal(key) is None:
            key = m.group("num")
        ordinal = _gen_ordinal(key)
        if ordinal is None or not (_GEN_MIN <= ordinal <= _GEN_MAX):
            return None
        label = key

    end = m.end()
    seen_pro = tier == "se"
    for _ in range(3):
        if end < len(t) and _TIER_STOP.match(t[end]):
            break
        tm = _TIER_TOKEN.match(t, end)
        if not tm:
            break
        if tm.group("promax"):
            tier, seen_pro = "pro max", True
        elif tm.group("pro"):
            tier, seen_pro = "pro", True
        elif tm.group("max"):
            tier = "pro max" if seen_pro else "max"
        elif tm.group("plus"):
            if tier != "base":
                break
            tier = "plus"
        elif tm.group("mini"):
            tier = "mini"
        elif tm.group("air"):
            tier = "air"
        elif tm.group("e"):
            # `16e`: only when glued straight to the digits, never after a space.
            if tm.group("sp") or tier != "base":
                break
            tier, label = "e", label + "e"
        end = tm.end()
    return _gen_ordinal(label.removeprefix("se")), label, tier, end


def model(t: str):
    """(generation, gen_label, tier, tier_ord, phrase_end) from the FIRST parseable phrase
    after an iPhone/Apple anchor.

    First, not best: sellers state the product first and trade-in offers or comparisons
    second, so the earliest phrase is the subject of the ad.
    """
    for anchor in ANCHOR.finditer(t):
        got = _parse_model_at(t, anchor.end())
        if got:
            gen, label, tier, end = got
            return gen, label, tier, TIER_ORDER[tier], end
    return None, None, None, None, None


# ------------------------------------------------------------------ storage
PLAUS_GB = {16, 32, 64, 128, 256, 512, 1024, 2048}
#: `mb` is accepted as a synonym for `gb`, which is wrong arithmetic and right extraction: no
#: iPhone has ever shipped with 256 MB of storage, so `iPhone 17 Pro 256 MB` states a
#: capacity in the only unit it can mean. `PLAUS_GB` is what makes it safe -- only the eight
#: real capacities are accepted, so a genuine small-MB number cannot leak in. Measured on
#: 7 236 listings: 7 write a capacity in MB and 4 of them declined for "missing storage",
#: two of which were iPhone 17 Pros that a deal alert would then have fired on as declines.
_CAP_UNIT = re.compile(r"(?<![\d.,])(\d{1,4})\s*(tb|gb|mb|gigabajt\w*|giga|g)\b")
_CAP_LABEL = re.compile(r"\b(?:pamet|pameti|kapacita|uloziste|ulozisti|velikost|storage)\b\s*:?\s*"
                        r"(?:uloziste\s*:?\s*)?(\d{1,4})\s*(tb|gb|g)?\b")


def _to_gb(v: str, unit: str | None) -> int:
    return int(v) * 1024 if unit == "tb" else int(v)


def storage(t: str, phrase_end: int | None):
    """Capacity in GB, or None.

    Resolution order, and the order is the point: a capacity glued to the model phrase, then
    an explicitly labelled one, then the most common unit-bearing plausible value in the
    text. Falling straight to the last is what binds a trade-in offer's capacity to the ad's
    own phone.
    """
    t = PRICEISH.sub(" ", DATEISH.sub(" ", t))

    if phrase_end is not None:
        window = t[phrase_end:phrase_end + 22]
        m = _CAP_UNIT.search(window)
        if m and _to_gb(m.group(1), m.group(2)) in PLAUS_GB:
            return _to_gb(m.group(1), m.group(2))
        m = re.match(r"[\s-]*(\d{2,4})(?![\d%])", window)
        if m and int(m.group(1)) in PLAUS_GB:
            return int(m.group(1))

    m = _CAP_LABEL.search(t)
    if m:
        value = _to_gb(m.group(1), m.group(2))
        if value in PLAUS_GB:
            return value

    values = [v for v in (_to_gb(a, b) for a, b in _CAP_UNIT.findall(t)) if v in PLAUS_GB]
    if values:
        # mode, ties broken by first appearance -- a repeated capacity is the ad's own
        return max(sorted(set(values), key=values.index), key=values.count)
    return None


def storage_variants(t: str) -> int:
    """How many distinct plausible capacities the text offers.

    More than one means a dealer ad covering several configurations: the ask is the cheapest
    variant and whichever capacity parsed is the wrong one for it. Both tails of the residual
    distribution were full of these.
    """
    t = PRICEISH.sub(" ", DATEISH.sub(" ", t))
    return len({v for v in (_to_gb(a, b) for a, b in _CAP_UNIT.findall(t)) if v in PLAUS_GB})


# ------------------------------------------------------------------ battery
_BAT_WORD = r"(?:bater\w*|batk\w*|baterk\w*|kondic\w*|zdrav\w*|kapacit\w*|bat\b|akum\w*)"
_BAT_PATTERNS = [
    re.compile(_BAT_WORD + r"[^%\n]{0,24}?(\d{2,3})\s*%"),
    re.compile(r"(\d{2,3})\s*%\s*" + _BAT_WORD),
    re.compile(r"(\d{2,3})\s*%\s*bat\b"),
]
#: The dealer template writes health as a bare percentage between separators:
#: `iPhone 13 - 256GB - 100% - 12M ZARUKA`. Title only, and only where the percentage is not
#: qualifying a word that means something else (`100% funkcni`, `100% original`).
_BARE_PCT = re.compile(r"(?<![\d,.])(\d{2,3})\s*%"
                       r"(?!\s*(?:funkc|origin|top|spolehl|cist|zaruk|dph|nov|stav|perfekt|ok\b|sleva))")


def battery(title_t: str, blob_t: str):
    """(battery_pct, battery_replaced).

    Clamped to 40-100: outside that it is a warranty month count, a discount or a capacity
    that leaked through. 45.3% of stated values are exactly 100% and the minimum stated is
    70%, so this is a ceiling-censored, self-selected measurement — stated batteries are good
    batteries (research §6.1).
    """
    pct = None
    for src in (title_t, blob_t):
        s = PRICEISH.sub(" ", DATEISH.sub(" ", src))
        for rx in _BAT_PATTERNS:
            for m in rx.finditer(s):
                value = int(m.group(1))
                if 40 <= value <= 100:
                    pct = value
                    break
            if pct is not None:
                break
        if pct is not None:
            break
    if pct is None:
        bare = _BARE_PCT.search(DATEISH.sub(" ", title_t))
        if bare and 40 <= int(bare.group(1)) <= 100:
            pct = int(bare.group(1))
    replaced = bool(re.search(
        r"nov[aa]\s*(?:origin\w*\s*)?bater\w*|vymen\w*\s*bater\w*|bater\w*\s*(?:byla\s*)?vymen\w*"
        r"|nova bat\b|vymena bater\w*", blob_t))
    return pct, replaced


_CYCLES = re.compile(r"(\d{1,4})\s*(?:nabijec\w*\s*)?cykl\w*|cykl\w*\D{0,12}(\d{1,4})")


def cycles(t: str):
    m = _CYCLES.search(DATEISH.sub(" ", t))
    if m:
        for g in m.groups():
            if g is not None and 0 <= int(g) <= 3000:
                return int(g)
    return None


# ------------------------------------------------------------------ condition
#: The trailing sign counts only when glued to the letter: `stav A - ani jeden skrabanec` is
#: a grade A followed by a dash, not an A-.
_GRADE_LETTER = re.compile(r"\bstav\w*\s*:?\s*(a\+\+|a\+|a-|b\+|b-|[abc])(?![a-z])")
_GRADE_TEN = re.compile(r"(?<![\d/.,])(\d{1,2})\s*/\s*10\b")


def condition_grade(t: str):
    """(letter_grade, grade_ten).

    Two dealer conventions, kept apart: a letter grade is one shop's template and a /10 is
    another's, so pooling them would encode which shop wrote the ad rather than what the
    phone is like.
    """
    t = DATEISH.sub(" ", t)
    letter = None
    m = _GRADE_LETTER.search(t)
    if m:
        letter = m.group(1)
    ten = None
    m = _GRADE_TEN.search(t)
    if m and 1 <= int(m.group(1)) <= 10:
        ten = int(m.group(1))
    return letter, ten


# ------------------------------------------------------------------ warranty
_WARRANTY_NEAR = re.compile(
    r"(?:zaruk\w*|zaruc\w*|zaruce)\D{0,18}?(\d{1,2})\s*(?:m\b|mes\w*)"
    r"|(\d{1,2})\s*(?:m\b|mes\w*)\D{0,14}?(?:zaruk\w*|zaruc\w*)"
    r"|(?:zaruk\w*|zaruc\w*)\D{0,14}?(\d{1,2})\s*(?:rok\w*|let\w*)"
    r"|(\d{1,2})\s*(?:rok\w*|let\w*)\s*(?:zaruk\w*|zaruc\w*)"
)
_WARRANTY_ROK = re.compile(r"\b(?:1\s*)?rok\w*\s*zaruk\w*|zaruk\w*\s*(?:na\s*)?(?:1\s*)?rok\b|rocni zaruk\w*")


def warranty_months(t: str):
    t = DATEISH.sub(" ", t)
    m = _WARRANTY_NEAR.search(t)
    if m:
        stated = [x for x in m.groups() if x is not None]
        if stated:
            value = int(stated[0])
            if re.search(r"rok|let", m.group(0)):
                value *= 12
            if 1 <= value <= 60:
                return value
    if _WARRANTY_ROK.search(t):
        return 12
    return None


# ------------------------------------------------------------------ flags
#: Negating words that take no disambiguation. `ani` and `nejsou` are members because
#: `displej ani zadni sklo nejsou prasklé` has to read as a denial.
_NEG_PLAIN = re.compile(r"(?:bez|nema|neni|nejsou|nebyl\w*|nikde neni|krome|ani)\s+(?:\w+\s+){0,2}$")
#: `zadn\w*` is the ambiguous one, and this is the defect the experiment leaves unfixed.
#: `strip_diacritics` collapses Czech `zadny`/`zadne` ("none") onto `zadni` ("rear"), so
#: "zadni sklo je prasklé" — THE BACK GLASS IS CRACKED — read as a negation and suppressed
#: the damage flag. Deleting the alternative is not the fix either: 15 of 17 `zadn`+damage
#: co-occurrences are genuine denials ("zadne skrabance").
#: **The disambiguator is the intervening copula**, which is what this pair encodes: a
#: denial puts the noun straight after (`zadne skrabance`), while the rear-glass reading
#: needs a verb between (`zadni sklo *je* prasklé`). A *negated* copula (`nejsou`) is still a
#: denial, and `\bjsou\b` deliberately does not match inside `nejsou`.
_NEG_ZADN = re.compile(r"zadn\w*(?P<between>\s+(?:\w+\s+){0,2})$")
_COPULA = re.compile(r"\b(?:je|jsou|byl|byla|bylo|byly|ma|maji)\b")

_DAMAGE_BODY = (r"prask\w*|rozbit\w*|poskozen\w*|nefunk\w*|vadn\w*|\bvada\b|\bvady\b|rozlit\w*|zatopen\w*"
                r"|nejde\b|nezapin\w*|nenabij\w*|na dily\b|na opravu\b|k oprave\b|roztrisk\w*")
_SCRATCH_BODY = r"skraban\w*|skrabanc\w*|oder\w*|odrenin\w*|promackl\w*|dulek|kosmetick\w* vad\w*|opotreb\w*"


def _neg_aware(t: str, body: str) -> bool:
    """True only for a NON-negated hit.

    Two negation channels, both live in this corpus: a separate negating word to the left
    (`bez poskozeni`, `zadne skrabance`) and the `ne-` prefix glued to the stem
    (`neposkozen`). The prefix test exempts stems that legitimately start with `ne` —
    `nefunkcni` IS damage. A flag with an inverted sign is worse than no flag, because an
    unnegated damage flag reads as +16% on price.
    """
    for m in re.finditer(body, t):
        start = m.start()
        left = t[max(0, start - 40):start]
        if _NEG_PLAIN.search(left):
            continue
        zadn = _NEG_ZADN.search(left)
        if zadn and not _COPULA.search(zadn.group("between")):
            continue
        if not m.group(0).startswith("ne") and t[max(0, start - 2):start] == "ne" and not (
                start >= 3 and t[start - 3].isalpha()):
            continue
        return True
    return False


def flags(t: str, title_t: str) -> dict[str, Any]:
    f: dict[str, Any] = {}
    f["damage"] = _neg_aware(t, _DAMAGE_BODY)
    f["scratches"] = _neg_aware(t, _SCRATCH_BODY)
    f["mint_words"] = bool(re.search(r"jako nov\w*|\btop stav\w*|perfektn\w* stav|bezvad\w*|zanovn\w*"
                                     r"|vyborn\w* stav|bez jedin\w* skraban|nepouzivan\w*", t))
    f["sealed_new"] = bool(re.search(r"zapecet\w*|nerozbalen\w*|neotevren\w*|pouze rozbalen\w*|jen rozbalen\w*"
                                     r"|nova pecet|neporusen\w* pecet", t))
    f["new_word"] = bool(re.search(r"\bnov[ya]\s*(?:apple\s*)?iphone\b|\biphone\s+nov[ya]\b|zcela nov\w*"
                                   r"|uplne nov\w*|telefon je nov\w*|\bje novy\b|nov[ya] nerozbal\w*"
                                   r"|nepouzit\w*|novy kus", t))
    f["warranty"] = bool(re.search(r"zaruk\w*|zaruc\w*|applecare", t))
    f["invoice"] = bool(re.search(r"faktur\w*|doklad o koupi|ucten\w*|zarucni list|paragon", t))
    f["vat_dph"] = bool(re.search(r"\bdph\b|na firmu|\bico\b|odpoctu dph", t))
    f["esim"] = bool(re.search(r"\besim\b|e-sim|e sim\b", t))
    f["box"] = bool(re.search(r"krabic\w*|original\w* balen\w*|kompletn\w* balen\w*|puvodn\w* balen\w*"
                              r"|komplet balen\w*", t))
    f["icloud_clear"] = bool(re.search(r"odhlasen\w*|smazan\w* a odhlasen|bez zamku|bez icloud|odhlaseny z icloud", t))
    #: `na operatora` is deliberately not a member: it is the object of both `blokovany na
    #: operatora` and `NEblokovany na operatora`, and the negation lives on the verb it is
    #: separated from. `(?:za)?blokovan` rather than `blokovan` because the prefixed form
    #: `neni ZAblokovany` puts the negating word two characters further left than the bare
    #: stem's match position.
    #:
    #: `(?<!od)` because `odblokovany` means *un*locked, and `_neg_aware` knows only the `ne-`
    #: channel. The lookbehind sits on this one stem rather than becoming a second prefix in
    #: `_neg_aware`, because `od` is not a negator in general - `_SCRATCH_BODY`'s own
    #: `oder\w*`/`odrenin\w*` begin with it, and exempting them would silently drop every
    #: scratch. Measured 2026-10-22: 10 of 32 `locked` flags over 8,761 production iPhone ads
    #: were ads saying `odblokovany`, each docked 15% - the direction that hides a deal.
    f["locked"] = _neg_aware(
        t, r"(?<!od)(?:za)?blokovan\w*|(?:za)?zamcen\w*|zamek aktivace|icloud lock|operator lock")
    f["cz_region"] = bool(re.search(r"\bcz\s*distribuc\w*|ceska distribuc\w*|ceske distribuce|cz verze", t))
    f["usa_region"] = bool(re.search(r"\busa\b|\bus verz\w*|americk\w* verz\w*", t))
    f["swap"] = bool(re.search(r"vymen\w*\s*za|prodam nebo vymen\w*|mozna vymena|protiucet", t))
    f["urgent"] = bool(re.search(r"\bspech\w*|rychl\w* jednan|ihned k odberu|nutn\w* prodej|\bsleva\b|akce\b", t))
    f["dealer_pickup"] = bool(re.search(r"prodejn\w*|na adrese|po - pa|otevirac\w*|nasi prodejn", t))
    f["multi_unit"] = bool(re.search(r"vice kusu|vice ks\b|dva kusy|tri kusy|cena za kus|skladem|na sklade", t))
    f["bundle_other"] = bool(re.search(r"\+\s*airpod|\+\s*apple ?watch|a apple ?watch|\+\s*ipad|\+\s*macbook",
                                       title_t))
    return f


# ------------------------------------------------------------------ classification
def product_kind(title_t: str, blob_t: str, gen) -> str:
    """What is actually being sold.

    Order matters: a want-to-buy ad that names a phone is still a bid, and a case listing
    that names a phone is still a case.
    """
    if WTB.search(title_t) or WTB.search(blob_t[:160]):
        return "wtb"
    if ACCESSORY_SUBJECT.search(title_t) or ACCESSORY_FOR.search(title_t):
        return "accessory"
    if PARTS.search(title_t) or PARTS_DESC.search(blob_t):
        return "parts"
    if gen is None:
        if OTHER_APPLE.search(title_t) and not IPHONE.search(title_t):
            return "other_apple"
        if OTHER_BRAND.search(title_t):
            return "other_brand"
        if IPHONE.search(blob_t):
            return "iphone_unspec"
        return "unknown"
    if OTHER_APPLE.search(title_t) and not IPHONE.search(title_t):
        return "other_apple"
    return "iphone"


def extract(name: str, desc: str = "", today: date | None = None) -> dict[str, Any]:
    """Everything this package knows how to read out of one iPhone listing."""
    title_t = norm(name or "")
    blob_t = norm(f"{name or ''} || {desc or ''}")

    gen, label, tier, tier_ord, end = model(title_t)
    source = "title" if gen is not None else None
    end_blob = None
    if gen is None:
        gen, label, tier, tier_ord, end_blob = model(blob_t)
        source = "desc" if gen is not None else None

    out: dict[str, Any] = {
        "generation": gen,
        "gen_label": label,
        "gen_age_m": gen_age_months(label, today),
        "tier": tier,
        "tier_ord": tier_ord,
        "model_src": source,
    }
    out["kind"] = product_kind(title_t, blob_t, gen)

    gb = storage(title_t, end if source == "title" else None)
    if gb is None:
        gb = storage(blob_t, end_blob)
    out["storage_gb"] = gb
    # log2 rather than log: the capacities are powers of two, so a unit step is one doubling
    # and the coefficient reads directly as "price per doubling" (research §3.1).
    out["storage_log2"] = None if not gb else math.log2(gb)
    out["storage_variants"] = storage_variants(title_t)

    pct, replaced = battery(title_t, blob_t)
    out["battery_pct"] = pct
    out["battery_replaced"] = replaced
    out["cycles"] = cycles(blob_t)

    letter, ten = condition_grade(blob_t)
    out["grade_letter"] = letter
    out["grade_ten"] = ten
    out["warranty_months"] = warranty_months(blob_t)

    out.update(flags(blob_t, title_t))
    out["reservation"] = bool(RESERVATION.search(blob_t))
    out["marked_sold"] = bool(SOLD.search(title_t))
    out["multipack"] = bool(MULTIPACK.search(title_t))
    return out
