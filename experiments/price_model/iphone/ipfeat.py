"""iPhone listing text -> structured specs.

Same shape and same constraints as `bazos/pricing/features.py` (the shipped MacBook
extractor): pure regex over `Ad.name + Ad.short_description`, standard library only,
because the serving path evaluates a JSON coefficient manifest in pure Python on an
ARM64 Pi. No numpy, no lookup table, no network.

Query 19 carries **no** `full_description` (load_full_description is OFF) and 62.6% of its
`short_description` rows end at Bazos's 254-character cap, so title + preview is the entire
text budget. Everything below is written for that budget.

The structural bet, stated so it can be falsified (§ordinal-vs-dummies in the study):
an iPhone title encodes its product POSITIONALLY -- `iPhone 15 Pro Max 256GB` is
generation 15 (an integer that interpolates to a generation never seen in training), a tier
on an ordered ladder, and a log-ordinal storage. That is the `rtx 3070` case from
PC_PRICE_MODEL.md §4, not the `Deore` case from CATEGORY_PRICE_MODELS.md §4.1.

Parsing traps that are load-bearing here, each observed in the live corpus:

- **Generation and tier must be parsed jointly from one model phrase, never by independent
  regexes.** A bare `pro` appears in 56.9% of blobs and `max` in 21.2%; matched
  independently they attach to whatever the seller said last. `iPhone 12 mini` must not read
  as a base 12, and `Pro Max` must beat a bare `Pro`.
- **`se` is the Czech reflexive pronoun.** `\bse\b` hits 18.3% of blobs ("se 100% kondici
  baterie") against a true iPhone-SE share near 3%. SE is only SE directly after an iPhone
  anchor.
- **The Roman generations break a naive `\d+`**: X, XR, XS, XS Max are generations 10-10.5
  and carry no digit at all.
- **Date-shaped substrings must be stripped before any number is read.** `zaruka do
  04/2027`, `V ZARUCE do 9/4/2027` and `zakoupen ... do 12.11.2026 je v zaruce` otherwise
  produce a 4 GB phone, a grade 9/10 and a 2026% battery.
- **A capacity must be bound to its model phrase.** Trade-in offers ("Na vymenu mohu
  nabidnout 16 pro Max 256GB"), the seller's street number ("Hradecka 161") and the original
  purchase price ("za 17 990 Kc") all sit in the same blob as the real spec.
- **The negated form is a family, not a word.** `bez poskozeni` contains `poskozen`,
  `nikde neni prasklý` contains `prask`, `bez zamku aktivace` contains `zamk`, and
  `Neblokovany na operatora` contains `blokovan`. PC_PRICE_MODEL.md §4.4 measured an
  unnegated damage flag reading as +16% on price; a flag with an inverted sign is worse than
  no flag because it manufactures fake underpricing on exactly the ads that deserve a
  discount.

A nonsense spec produces a nonsense prediction, which lands in the underpriced tail by
construction -- so these are correctness bugs for the alert, not cosmetic ones.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any


def strip_diacritics(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def norm(s: str) -> str:
    """Lowercase, de-accent, unify quote and dash glyphs.

    Commas, slashes, pipes and newlines are PRESERVED -- they are clause barriers
    (PC_PRICE_MODEL.md §4.3). Only runs of horizontal whitespace collapse; a newline becomes
    a single `\\n` so the dealer template's `Stav:`/`Barva:`/`Baterie:` lines stay separable.
    """
    s = s or ""
    if not isinstance(s, str):
        s = ""
    s = s.lower()
    s = strip_diacritics(s)
    s = s.replace("”", '"').replace("“", '"').replace("’", "'").replace("´", "'")
    s = s.replace("–", "-").replace("—", "-").replace(" ", " ")
    s = re.sub(r"\r\n?", "\n", s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{2,}", "\n", s)
    return s


#: Anything date-shaped. Stripped before every numeric read.
DATEISH = re.compile(
    r"\b(?:do|az do|plati do|zaruka do|v zaruce do|koupeno|zakoupeno|zakoupen|vystaven)\s*"
    r"(?:\d{1,2}\s*[./]\s*)?(?:\d{1,2}\s*[./]\s*)?(20[0-3]\d)\b"
    r"|\b\d{1,2}\s*[./]\s*\d{1,2}\s*[./]\s*(?:20)?\d{2}\b"
    r"|\b\d{1,2}\s*/\s*20[0-3]\d\b"
    r"|\b(?:leden|unor|brezen|duben|kveten|cerven|cervenec|srpen|zari|rijen|listopad|prosinec"
    r"|lednu|unoru|breznu|dubnu|kvetnu|cervnu|cervenci|srpnu|zari|rijnu|listopadu|prosinci)"
    r"\s*20[0-3]\d\b"
)

#: A price in the text ("za 17 990 Kc", "Cena: 9300", "12000,- Kc"). Removed before capacity
#: parsing so a four-digit amount can never be read as a capacity.
PRICEISH = re.compile(r"\b\d{1,3}(?:[ .]\d{3})+\s*(?:,-\s*)?(?:kc|czk)\b"
                      r"|\b\d{3,6}\s*(?:,-|kc\b|czk\b)"
                      r"|\bza\s+\d{1,3}(?:[ .]\d{3})+\b|\bcena\s*:?\s*\d{3,6}\b")


# ---------------------------------------------------------------- product family
#: The anchor a model phrase must follow. `apple` is accepted because a handful of sellers
#: write `Apple 17 Pro 256Gb` with no `iPhone` anywhere in the title.
ANCHOR = re.compile(r"\b(?:iphone|i ?phone|ifon|ajfon|apple)(?![a-z])\s*\(?\s*")
IPHONE = re.compile(r"\b(?:iphone|i phone|ifon|ajfon)\b")

#: Non-iPhone Apple products. Only decides `kind` when no iPhone model phrase parses.
OTHER_APPLE = re.compile(r"\b(?:ipad|macbook|mac ?mini|imac|apple ?watch|airpod|ipod|air ?tag|homepod)\b")
OTHER_BRAND = re.compile(
    r"\b(?:samsung|galaxy|xiaomi|redmi|poco|huawei|honor|oneplus|oppo|vivo|realme|nokia|motorola|sony xperia)\b"
)

#: The subject of the ad is an accessory or a part, not a phone. Anchored on what is being
#: SOLD: `obal na iphone 17` is a case, `iphone 13 + obal` is a phone with a case thrown in.
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
#: The same intent stated only in the description, where it needs a SELLING verb next to it.
#: `repasovany original displej` (a refurbished screen fitted to a working phone) and
#: `zadny repas` (a denial) both contain the vocabulary and are not parts ads; the three
#: description-only phrasings that ARE parts ads all name the sale.
PARTS_DESC = re.compile(r"(?:prodam|prodavam|nabizim)[^.\n]{0,70}?"
                        r"(?:\bna dily\b|\bna opravu\b|\bnahradni dily\b|\bna nahradni dily\b)")
#: Want-to-buy. 0.9% of this corpus, and their prices are BIDS, not asks -- the single most
#: important contamination class for a price model, because a bid is a different quantity.
WTB = re.compile(r"\bkoupim\b|\bkupim\b|\bodkoupim\b|\bvykup\w*|\bvykoup\w*|\bhledam\s+(?:iphone|apple|koupi)")


# ---------------------------------------------------------------- model phrase
#: Generation ladder position. The Roman generations are placed by release order so the
#: ordinal stays monotone in time: X (2017) 10.0, XR (2018) 10.2, XS (2018) 10.5.
_GEN_NUM = {
    "4": 4.0, "4s": 4.5, "5": 5.0, "5s": 5.5, "5c": 5.2, "6": 6.0, "6s": 6.5,
    "7": 7.0, "8": 8.0, "x": 10.0, "xr": 10.2, "xs": 10.5,
    "11": 11.0, "12": 12.0, "13": 13.0, "14": 14.0, "15": 15.0, "16": 16.0, "17": 17.0,
}
#: SE is NOT on the main ladder -- it is a body from one era with a chip from another. It is
#: placed by its CHIP, which is what the market prices: SE1 (A9 = 6s), SE2020 (A13 = 11),
#: SE2022 (A15 = 13). That mapping is the interpolation bet applied to the one sub-line that
#: would otherwise need three free dummies.
_SE_GEN = {"2016": 6.5, "2020": 11.0, "2022": 13.0, "1": 6.5, "2": 11.0, "3": 13.0}
_SE_DEFAULT = 11.0

#: The `e` line (16e, 17e) is the SE's successor: current chip, cut-down body.
#: Generation comes from its own digits, so it needs no special case here.

_MODEL_TOKEN = re.compile(
    r"(?:"
    r"(?P<se>se)(?:\s*\(?\s*(?P<seyear>2016|2020|2022)\s*\)?|\s*(?:gen\.?\s*)?(?P<segen>[123])\b)?"
    r"|(?P<air>air)"
    r"|(?P<xsmax>xs\s*max)"
    r"|(?P<roman>xs|xr|x)(?![a-z0-9])"
    r"|(?P<num>1[0-7]|[4-9])(?P<nsuf>s|c)?(?![0-9])"
    r")"
)

#: Tier tokens, consumed left to right straight after the generation token. `pro max` is
#: matched as one alternative BEFORE bare `pro` so "Pro Max" can never be read as "Pro".
#: `(?![a-z])` rather than `\b`: `iphone16pro128 gb` is one unspaced token, and a word
#: boundary between `pro` and `128` does not exist.
_TIER_TOKEN = re.compile(r"(?P<sp>\s*)(?:(?P<promax>pro\s*max(?![a-z]))|(?P<pro>pro(?![a-z]))"
                         r"|(?P<max>max(?![a-z]))|(?P<plus>plus(?![a-z]))|(?P<mini>mini(?![a-z]))"
                         r"|(?P<air>air(?![a-z]))|(?P<e>e(?![a-z0-9])))")
#: A tier word may only be consumed across these; anything else ends the model phrase.
_TIER_STOP = re.compile(r"[,|;/\n(]")

TIER_ORDER = {"e": 0, "se": 0, "mini": 1, "base": 2, "plus": 3, "max": 3, "air": 4, "pro": 5, "pro max": 6}


def _parse_model_at(t: str, pos: int):
    """Parse one model phrase starting at `pos`. Returns (gen, gen_label, tier, end) or None."""
    m = _MODEL_TOKEN.match(t, pos)
    if not m:
        return None
    gen = None
    label = None
    tier = "base"
    if m.group("se"):
        y = m.group("seyear") or m.group("segen")
        gen = _SE_GEN.get(y, _SE_DEFAULT) if y else _SE_DEFAULT
        label = "se" + (y or "")
        tier = "se"
    elif m.group("air"):
        # `iPhone Air` with no digits: the only Air is the 2025 one, contemporaneous with 17.
        gen, label, tier = 17.0, "air", "air"
    elif m.group("xsmax"):
        gen, label, tier = 10.5, "xs", "max"
    elif m.group("roman"):
        r = m.group("roman")
        gen, label = _GEN_NUM[r], r
    else:
        key = m.group("num") + (m.group("nsuf") or "")
        if key not in _GEN_NUM:
            key = m.group("num")
            if key not in _GEN_NUM:
                return None
        gen, label = _GEN_NUM[key], key

    end = m.end()
    # consume tier words, stopping at the first clause barrier
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
            if tier in ("base",):
                tier = "plus"
            else:
                break
        elif tm.group("mini"):
            tier = "mini"
        elif tm.group("air"):
            tier = "air"
        elif tm.group("e"):
            # `16e`: only when glued straight to the digits, never after a space.
            if tm.group("sp") or tier != "base":
                break
            tier = "e"
            label = label + "e"
        end = tm.end()
    return gen, label, tier, end


def model(t: str):
    """(generation, gen_label, tier, tier_ord, phrase_end) from the FIRST parseable model
    phrase after an iPhone/Apple anchor. First, not best: sellers state the product first and
    trade-in offers / comparisons second."""
    for a in ANCHOR.finditer(t):
        got = _parse_model_at(t, a.end())
        if got:
            gen, label, tier, end = got
            return gen, label, tier, TIER_ORDER[tier], end
    return None, None, None, None, None


# ---------------------------------------------------------------- storage
PLAUS_GB = {16, 32, 64, 128, 256, 512, 1024, 2048}
_CAP_UNIT = re.compile(r"(?<![\d.,])(\d{1,4})\s*(tb|gb|gigabajt\w*|giga|g)\b")
_CAP_LABEL = re.compile(r"\b(?:pamet|pameti|kapacita|uloziste|ulozisti|velikost|storage)\b\s*:?\s*"
                        r"(?:uloziste\s*:?\s*)?(\d{1,4})\s*(tb|gb|g)?\b")


def _to_gb(v: str, unit: str | None) -> int:
    n = int(v)
    if unit == "tb":
        return n * 1024
    return n


def storage(t: str, phrase_end: int | None):
    """Capacity in GB.

    Resolution order, and the order is the whole point:
      1. a capacity glued to the model phrase (`iPhone 15 Pro 256GB`, `... Max 256`),
      2. an explicitly labelled capacity (`Pamet: 256GB`),
      3. the single most common unit-bearing plausible capacity in the blob.

    Falling straight to (3) is what binds a trade-in offer's capacity to the ad's own phone.
    """
    t = PRICEISH.sub(" ", DATEISH.sub(" ", t))

    if phrase_end is not None:
        window = t[phrase_end:phrase_end + 22]
        m = _CAP_UNIT.search(window)
        if m and _to_gb(m.group(1), m.group(2)) in PLAUS_GB:
            return _to_gb(m.group(1), m.group(2))
        # bare digits straight after the model phrase: "iPhone 17 Pro Max 256"
        m = re.match(r"[\s-]*(\d{2,4})(?![\d%])", window)
        if m and int(m.group(1)) in PLAUS_GB:
            return int(m.group(1))

    m = _CAP_LABEL.search(t)
    if m:
        v = _to_gb(m.group(1), m.group(2))
        if v in PLAUS_GB:
            return v

    vals = [_to_gb(a, b) for a, b in _CAP_UNIT.findall(t)]
    vals = [v for v in vals if v in PLAUS_GB]
    if vals:
        # mode, ties broken by first appearance -- a repeated capacity is the ad's own
        return max(sorted(set(vals), key=vals.index), key=vals.count)
    return None


# ---------------------------------------------------------------- battery
_BAT_WORD = r"(?:bater\w*|batk\w*|baterk\w*|kondic\w*|zdrav\w*|kapacit\w*|bat\b|akum\w*)"
_BAT_PATTERNS = [
    re.compile(_BAT_WORD + r"[^%\n]{0,24}?(\d{2,3})\s*%"),
    re.compile(r"(\d{2,3})\s*%\s*" + _BAT_WORD),
    re.compile(r"(\d{2,3})\s*%\s*bat\b"),
]
#: The dealer template writes the health as a bare percentage between separators:
#: `iPhone 13 - 256GB - 100% - 12M ZARUKA`. Accepted in the TITLE only, and only when the
#: percentage is not qualifying a word that means something else (`100% funkcni`,
#: `100% original`, `100% TOP`).
_BARE_PCT = re.compile(r"(?<![\d,.])(\d{2,3})\s*%"
                       r"(?!\s*(?:funkc|origin|top|spolehl|cist|zaruk|dph|nov|stav|perfekt|ok\b|sleva))")


def battery(title_t: str, blob_t: str):
    """(battery_pct, battery_replaced). Percentage is clamped to 40-100: anything outside is
    a warranty month count, a discount or a storage figure that leaked through."""
    pct = None
    for src in (title_t, blob_t):
        s = PRICEISH.sub(" ", DATEISH.sub(" ", src))
        for rx in _BAT_PATTERNS:
            for m in rx.finditer(s):
                v = int(m.group(1))
                if 40 <= v <= 100:
                    pct = v
                    break
            if pct is not None:
                break
        if pct is not None:
            break
    if pct is None:
        m = _BARE_PCT.search(DATEISH.sub(" ", title_t))
        if m and 40 <= int(m.group(1)) <= 100:
            pct = int(m.group(1))
    replaced = bool(re.search(
        r"nov[aá]\s*(?:origin\w*\s*)?bater\w*|vymen\w*\s*bater\w*|bater\w*\s*(?:byla\s*)?vymen\w*"
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


# ---------------------------------------------------------------- condition
#: Letter grade. The trailing sign counts only when glued to the letter -- `stav A - ani
#: jeden skrabanec` is a grade A followed by a dash, not an A-.
_GRADE_LETTER = re.compile(r"\bstav\w*\s*:?\s*(a\+\+|a\+|a-|b\+|b-|[abc])(?![a-z])")
_GRADE_TEN = re.compile(r"(?<![\d/.,])(\d{1,2})\s*/\s*10\b")


def condition_grade(t: str):
    """(letter_grade, grade_ten). Two different dealer conventions, kept apart: a letter
    grade is one shop's template and a /10 is another's, so pooling them into one scale would
    encode which shop wrote the ad rather than what the phone is like."""
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


# ---------------------------------------------------------------- warranty
_WARRANTY_NEAR = re.compile(
    r"(?:zaruk\w*|zaruc\w*|zaruce)\D{0,18}?(\d{1,2})\s*(?:m\b|mes\w*|měs\w*)"
    r"|(\d{1,2})\s*(?:m\b|mes\w*)\D{0,14}?(?:zaruk\w*|zaruc\w*)"
    r"|(?:zaruk\w*|zaruc\w*)\D{0,14}?(\d{1,2})\s*(?:rok\w*|let\w*|rok)"
    r"|(\d{1,2})\s*(?:rok\w*|let\w*)\s*(?:zaruk\w*|zaruc\w*)"
)
_WARRANTY_ROK = re.compile(r"\b(?:1\s*)?rok\w*\s*zaruk\w*|zaruk\w*\s*(?:na\s*)?(?:1\s*)?rok\b|rocni zaruk\w*")


def warranty_months(t: str):
    t = DATEISH.sub(" ", t)
    m = _WARRANTY_NEAR.search(t)
    if m:
        g = [x for x in m.groups() if x is not None]
        if g:
            v = int(g[0])
            if re.search(r"rok|let", m.group(0)):
                v *= 12
            if 1 <= v <= 60:
                return v
    if _WARRANTY_ROK.search(t):
        return 12
    return None


# ---------------------------------------------------------------- flags
#: ⚠️ KNOWN DEFECT, LEFT IN ON PURPOSE so the figures in
#: docs/research/IPHONE_PRICE_MODEL.md reproduce. `zadn\w*` is here for Czech `zadny`/`zadne`
#: ("none"), but `strip_diacritics` collapses `zadni` ("rear") onto the same stem -- so
#: "zadni sklo je prasklé" (THE BACK GLASS IS CRACKED) reads as a negation and `damage` is
#: suppressed. Measured on query 19: 6 of 26 crack-word rows missed, 5 of them pass the gate,
#: and 2 of the 25 gated -25% alert flags are cracked phones the gate exists to stop.
#:
#: Do NOT fix this by deleting the alternative -- 15 of the 17 `zadn`+damage co-occurrences are
#: genuine negations ("zadne skrabance"), and one row ("displej ani zadni sklo nejsou prasklé")
#: needs both readings at once. The disambiguator is the intervening copula: `zadny` is followed
#: directly by a noun, while `zadni X *je* prasklé` puts a verb between. Any real fix needs that
#: test, plus the negated-form discipline in bazos/pricing/estimators/macbook.py's _DAMAGE
#: comment -- which has the OPPOSITE failure (no negation handling at all, so it over-declines).
_NEG = r"(?:bez|zadn\w*|nema|neni|nebyl\w*|nikde neni|krome)\s+(?:\w+\s+){0,2}"


def _neg_aware(t: str, body: str) -> bool:
    """True only for a NON-negated hit.

    Two negation channels, and both are live in this corpus: a separate negating word to the
    left (`bez poskozeni`, `nikde neni prasklý`, `zadne skrabance`) and the `ne-` prefix glued
    to the stem (`neposkozen`, `neblokovany`). The prefix test has to exempt stems that
    legitimately start with `ne` -- `nefunkcni` IS damage. An unnegated damage flag reads as
    +16% on price (PC_PRICE_MODEL.md §4.4); a flag with an inverted sign is worse than none.
    """
    rx = re.compile(body)
    for m in rx.finditer(t):
        s = m.start()
        left = t[max(0, s - 40):s]
        if re.search(_NEG + r"$", left):
            continue
        if not m.group(0).startswith("ne") and t[max(0, s - 2):s] == "ne" and not (
                s >= 3 and t[s - 3].isalpha()):
            continue
        return True
    return False


_DAMAGE_BODY = (r"prask\w*|rozbit\w*|poskozen\w*|nefunk\w*|vadn\w*|\bvada\b|\bvady\b|rozlit\w*|zatopen\w*"
                r"|nejde\b|nezapin\w*|nenabij\w*|na dily\b|na opravu\b|k oprave\b|roztrisk\w*")
_SCRATCH_BODY = r"skraban\w*|skrabanc\w*|oder\w*|odrenin\w*|promackl\w*|dulek|kosmetick\w* vad\w*|opotreb\w*"


def flags(t: str, title_t: str) -> dict[str, Any]:
    f: dict[str, Any] = {}
    f["damage"] = _neg_aware(t, _DAMAGE_BODY)
    f["scratches"] = _neg_aware(t, _SCRATCH_BODY)
    f["mint_words"] = bool(re.search(r"jako nov\w*|\btop stav\w*|perfektn\w* stav|bezvad\w*|zanovn\w*"
                                     r"|vyborn\w* stav|bez jedin\w* skraban|nepouzivan\w*", t))
    f["sealed_new"] = bool(re.search(r"zapecet\w*|nerozbalen\w*|neotevren\w*|pouze rozbalen\w*|jen rozbalen\w*"
                                     r"|nova pecet|neporusen\w* pecet", t))
    f["new_word"] = bool(re.search(r"\bnov[yaé]\s*(?:apple\s*)?iphone\b|\biphone\s+nov[yaé]\b|zcela nov\w*"
                                   r"|uplne nov\w*|telefon je nov\w*|\bje novy\b|nov[yaé] nerozbal\w*"
                                   r"|nepouzit\w*|novy kus", t))
    f["warranty"] = bool(re.search(r"zaruk\w*|zaruc\w*|zaruce|applecare", t))
    f["invoice"] = bool(re.search(r"faktur\w*|doklad o koupi|ucten\w*|zarucni list|paragon", t))
    f["vat_dph"] = bool(re.search(r"\bdph\b|na firmu|\bico\b|odpoctu dph", t))
    f["esim"] = bool(re.search(r"\besim\b|e-sim|e sim\b", t))
    f["box"] = bool(re.search(r"krabic\w*|original\w* balen\w*|kompletn\w* balen\w*|puvodn\w* balen\w*"
                              r"|komplet balen\w*", t))
    f["icloud_clear"] = bool(re.search(r"odhlasen\w*|smazan\w* a odhlasen|bez zamku|bez icloud|odhlaseny z icloud", t))
    #: `na operatora` is deliberately NOT a member: it is the object of both `blokovany na
    #: operatora` and `NEblokovany na operatora`, and the negation lives on the verb it is
    #: separated from. `blokovan\w*` already catches both and the `ne-` prefix test settles it.
    #: `(?:za)?blokovan` rather than `blokovan`: the prefixed form `neni ZAblokovany` puts the
    #: negating word two characters further left than the bare stem's match position, so the
    #: left-context test misses it unless the prefix is part of the match.
    f["locked"] = _neg_aware(t, r"(?:za)?blokovan\w*|(?:za)?zamcen\w*|zamek aktivace|icloud lock|operator lock")
    f["cz_region"] = bool(re.search(r"\bcz\s*distribuc\w*|ceska distribuc\w*|ceske distribuce|cz verze|\bcz\b", t))
    f["eu_region"] = bool(re.search(r"\beu\s*verz\w*|\beu\b(?!\w)", t))
    f["usa_region"] = bool(re.search(r"\busa\b|\bus verz\w*|americk\w* verz\w*", t))
    f["swap"] = bool(re.search(r"vymen\w*\s*za|prodam nebo vymen\w*|mozna vymena|protiucet", t))
    f["urgent"] = bool(re.search(r"\bspech\w*|rychl\w* jednan|ihned k odberu|nutn\w* prodej|\bsleva\b|akce\b", t))
    f["dealer_pickup"] = bool(re.search(r"prodejn\w*|na adrese|po - pa|otevirac\w*|nasi prodejn", t))
    f["multi_unit"] = bool(re.search(r"vice kusu|vice ks\b|dva kusy|tri kusy|\d\s*ks\b|cena za kus|skladem"
                                     r"|na sklade|vice kusu k dispozici|\d+\s*kusy", t))
    f["bundle_other"] = bool(re.search(r"\+\s*airpod|\+\s*apple ?watch|a apple ?watch|\+\s*ipad|\+\s*macbook", title_t))
    return f


# ---------------------------------------------------------------- colour
_COLORS = [
    ("black", r"cern\w*|black|midnight|space black|graphite|grafit\w*|temn\w* seda"),
    ("white", r"\bbil\w*|white|starlight|hvezdn\w*"),
    ("silver", r"stribrn\w*|silver"),
    ("gold", r"zlat\w*|\bgold\b"),
    ("blue", r"modr\w*|\bblue\b|sierra|pacific|ultramarine|denim"),
    ("green", r"zelen\w*|\bgreen\b|alpine"),
    ("pink", r"ruzov\w*|\bpink\b|\brose\b"),
    ("purple", r"fialov\w*|purple|lavender|levandul\w*|deep purple"),
    ("red", r"cerven\w*|\bred\b|product red"),
    ("orange", r"oranzov\w*|orange|cosmic orange"),
    ("yellow", r"zlut\w*|yellow"),
    ("grey", r"\bsed\w*|\bgrey\b|\bgray\b|space grey|space gray|vesmirn\w*"),
    ("titan_natural", r"prirodn\w* titan|natural titanium|prirodni titan"),
    ("titan_desert", r"desert titan\w*|pouctn\w* titan"),
    ("titan_white", r"white titanium|bil\w* titan"),
    ("titan_black", r"black titanium|cern\w* titan"),
]
_COLORS_RX = [(name, re.compile(rx)) for name, rx in _COLORS]


def color(t: str):
    """First colour mentioned in the title, else in the blob. Titanium variants are matched
    before the plain colours they contain."""
    for name, rx in reversed(_COLORS_RX):
        if name.startswith("titan") and rx.search(t):
            return name
    for name, rx in _COLORS_RX:
        if rx.search(t):
            return name
    return None


# ---------------------------------------------------------------- classification
def product_kind(title_t: str, blob_t: str, gen) -> str:
    """What is actually being sold. Order matters: a want-to-buy ad that names a phone is
    still a bid, and a case listing that names a phone is still a case."""
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


# ---------------------------------------------------------------- entry point
FIELDS_NUM = ["generation", "tier_ord", "storage_gb", "battery_pct", "cycles", "grade_ten", "warranty_months"]
FIELDS_CAT = ["gen_label", "tier", "color", "grade_letter"]
FIELDS_BOOL = ["battery_replaced", "damage", "scratches", "mint_words", "sealed_new", "new_word",
               "warranty", "invoice", "vat_dph", "esim", "box", "icloud_clear", "locked",
               "cz_region", "eu_region", "usa_region", "swap", "urgent", "dealer_pickup", "multi_unit", "bundle_other"]


def extract(name: str, desc: str = "") -> dict:
    title_t = norm(name or "")
    blob_t = norm(f"{name or ''} || {desc or ''}")

    gen, label, tier, tier_ord, end = model(title_t)
    src_for_model = "title"
    if gen is None:
        gen, label, tier, tier_ord, end = model(blob_t)
        src_for_model = "desc" if gen is not None else None
        end_blob = end
    else:
        end_blob = None

    out: dict[str, Any] = {
        "generation": gen,
        "gen_label": label,
        "tier": tier,
        "tier_ord": tier_ord,
        "model_src": src_for_model,
    }
    out["kind"] = product_kind(title_t, blob_t, gen)

    st = storage(title_t, end if src_for_model == "title" else None)
    if st is None:
        st = storage(blob_t, end_blob)
    out["storage_gb"] = st

    pct, replaced = battery(title_t, blob_t)
    out["battery_pct"] = pct
    out["battery_replaced"] = replaced
    out["cycles"] = cycles(blob_t)

    letter, ten = condition_grade(blob_t)
    out["grade_letter"] = letter
    out["grade_ten"] = ten
    out["warranty_months"] = warranty_months(blob_t)
    out["color"] = color(title_t) or color(blob_t)
    out.update(flags(blob_t, title_t))
    return out
