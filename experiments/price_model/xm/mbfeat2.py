"""MacBook listing -> structured spec extraction, cross-marketplace.

v2 of scratchpad mbfeat.py. Same public API (`extract(name, desc) -> dict`).
No marketplace branching anywhere: the differences between Bazos / Sbazar / Vinted text are
handled as (a) extra normalisation of formatting variants and (b) a wider synonym vocabulary
(cs / pl / en) in the same regexes. Changes vs v1 are tagged  # v2:
"""
import re, unicodedata

def strip_diacritics(s: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c))

def norm(s: str) -> str:
    s = (s or '').lower()
    s = strip_diacritics(s)
    s = s.replace('”','"').replace('“','"').replace('’',"'").replace('´',"'")
    s = re.sub(r"''", '"', s)
    s = s.replace(',', '.')          # 15,4" -> 15.4"
    # v2: en/em dash and minus behave as a separator, not as part of a token
    #     ("MacBook Air 13- 256 GB", 120 Bazos + 12 Vinted rows).
    s = re.sub(r'[\u2010-\u2015\u2212]', '-', s)
    # v2: Polish "2017r." / "2012r" year suffix -- no \b between the digit and the r,
    #     so YEAR never fired on those (5 Vinted rows).
    s = re.sub(r'(?<=\d{4})\s*r\b\.?', ' ', s)
    # v2: hyphen glues a size to its unit in en text ("14-inch", 17 rows).
    s = re.sub(r'(\d)\s*-\s*(inch|in\b|palc|cali|cale)', r'\1 \2', s)
    # v2: compact chip spellings "m2pro" / "m4max" (44 Bazos+Sbazar rows) -- the \b in
    #     APPLE_CHIP cannot see a boundary between "2" and "pro".
    s = re.sub(r'\bm([1-9])(pro|max|ultra)\b', r'm\1 \2', s)
    s = re.sub(r'\s+', ' ', s)
    return s

# ---------- product family ----------
NON_MACBOOK = re.compile(r'\b(imac|mac ?mini|mac ?studio|mac ?pro\b(?! ?1[0-9])|ipad|iphone|apple watch)\b')
OTHER_BRAND = re.compile(r'\b(asus|lenovo|thinkpad|legion|dell|xps|inspiron|latitude|hp\b|spectre|elitebook|probook|'
                         r'msi|acer|aspire|travelmate|nitro|samsung galaxy book|huawei matebook|razer|gigabyte|'
                         r'vivobook|zenbook|zephyrus|omen|victus|ideapad|yoga|surface|chromebook|fujitsu|toshiba)\b')
MACBOOK = re.compile(r'\b(macbook|mac ?book|mcb\b|makbook|mabook)\b')

def product_kind(t):
    if MACBOOK.search(t): return 'macbook'
    if NON_MACBOOK.search(t): return 'other_apple'
    if OTHER_BRAND.search(t): return 'other_brand'
    return 'unknown'

def family(t):
    # order matters: "MacBook Pro" beats bare "pro"
    if re.search(r'macbook\s*air|mac ?book ?air|\bmba\b|air\b', t): air = True
    else: air = False
    pro = bool(re.search(r'macbook\s*pro|mac ?book ?pro|\bmbp\b', t))
    if pro and not re.search(r'macbook\s*air', t): return 'pro'
    if air: return 'air'
    if re.search(r'macbook\s*neo|\bneo\b', t): return 'neo'   # v2: 2026 model line, 41 rows
    if re.search(r'macbook\s*(retina|12)', t): return 'macbook12'
    if MACBOOK.search(t): return 'macbook_unspec'
    return 'na'

# ---------- chip ----------
# v2: [1-9] not [1-4] -- M5 shipped and is 50 Bazos / 14 Sbazar rows here; a hard-coded
#     generation ceiling silently drops every new chip the day Apple ships it.
APPLE_CHIP = re.compile(r'\bm([1-9])(?:\s*(pro|max|ultra))?\b')
INTEL_CHIP = re.compile(r'\b(?:intel\s*)?(?:core\s*)?i([357])\b')
def chip(t):
    m = APPLE_CHIP.search(t)
    if m:
        gen = int(m.group(1)); var = m.group(2) or 'base'
        return ('apple', gen, var)
    m = INTEL_CHIP.search(t)
    if m: return ('intel', int(m.group(1)), 'base')
    if re.search(r'\bcore ?2 ?duo\b|\bc2d\b', t): return ('intel', 2, 'c2d')
    if re.search(r'\bi9\b', t): return ('intel', 9, 'base')
    return (None, None, None)

# ---------- year ----------
DATEISH = re.compile(r'\b(?:do|az do|plati do|zaruka do|koupeno|zakoupeno)\s*'
                     r'(?:\d{1,2}\s*[./]\s*)?(?:\d{1,2}\s*[./]\s*)?(20[0-3]\d)\b'
                     r'|\b\d{1,2}\s*/\s*(?:20)?[0-3]\d\b')

YEAR = re.compile(r'\b(200[5-9]|201\d|202[0-6])\b')

def year(name_t, full_t):
    """Model year. Prefer the title (sellers put the model year there); strip warranty/purchase
    dates first so 'zaruka do 04/2027' never wins."""
    for src_t in (DATEISH.sub(' ', name_t), DATEISH.sub(' ', full_t)):
        ys = [int(y) for y in YEAR.findall(src_t)]
        ys = [y for y in ys if 2006 <= y <= 2026]
        if ys:
            return min(ys) if len(set(ys)) > 1 else ys[0]
    return None

# ---------- screen ----------
# v2: cali/cale (pl), zoll (de) added; hyphen already removed in norm().
SCREEN = re.compile(r'\b(1[1-7](?:\.\d)?)\s*(?:"|palc\w*|inch|in\b|cal[ie]?\b|zoll|\'\')')
SCREEN_LOOSE = re.compile(r'\bmacbook\s*(?:air|pro)?\s*(1[1-7](?:\.\d)?)\b')
def screen(t):
    for rx in (SCREEN, SCREEN_LOOSE):
        m = rx.search(t)
        if m:
            v = float(m.group(1))
            if 11 <= v <= 17: return v
    return None

# ---------- storage / ram ----------
PLAUS_RAM = {2,4,6,8,12,16,18,24,32,36,48,64,96,128}
PLAUS_SSD = {64,120,121,128,240,250,251,256,320,480,500,512,750,1000,1024,2000,2048,4000,4096,8000,8192}

TOKEN = re.compile(r'(\d{1,4}(?:\.\d)?)\s*(tb|gb)\b')
TOKEN_LOOSE = re.compile(r'(\d{1,4}(?:\.\d)?)\s*(tb|gb)?\b')
# v2: pamiec/pamieci (pl, post-diacritic-strip), memory (en)
RAM_WORD = re.compile(r'\b(ram|pameti|pamet|operacni|rammky|ramka|pamiec\w*|memory)\b')
# v2: dysk\w* (pl), storage/drive (en)
SSD_WORD = re.compile(r'\b(ssd|disk\w*|uloziste|hdd|flash|nvme|dysk\w*|storage|drive)\b')

def _to_gb(val, unit):
    v = float(val)
    if unit == 'tb':
        return int(round(v * 1000))
    return int(round(v))

UNITLESS_LABELLED = re.compile(
    r'\b(\d{1,4})\s*(?:gb\b)?\s*(ram|pamet\w*|pameti|pamiec\w*|memory|ssd|disk\w*|dysk\w*|hdd|nvme)\b')


def _tokens(t):
    """All capacity tokens with an explicit gb/tb unit, as (value_gb, start, end).

    v2: also accepts a bare number immediately followed by its own label -- "8 ram / 256 ssd"
    (Vinted/Polish habit) produced no tokens at all under v1, since TOKEN requires gb|tb.
    """
    out = []
    spans = []
    for m in TOKEN.finditer(t):
        out.append((_to_gb(m.group(1), m.group(2)), m.start(), m.end()))
        spans.append((m.start(), m.end()))
    for m in UNITLESS_LABELLED.finditer(t):
        if any(s <= m.start() < e for s, e in spans):
            continue
        out.append((int(m.group(1)), m.start(), m.start() + len(m.group(1))))
    out.sort(key=lambda x: x[1])
    return out

def ram_ssd(t):
    """Return (ram_gb, ssd_gb).

    Labels are searched only in the gap between this token and its neighbours, never across
    another token -- "8gb. 512gb ssd" must not label the 8 as an SSD.
    """
    t = DATEISH.sub(' ', t)
    toks = _tokens(t)
    ram = ssd = None
    labelled = {}
    for i, (val, s, e) in enumerate(toks):
        prev_end = toks[i - 1][2] if i else max(0, s - 18)
        next_start = toks[i + 1][1] if i + 1 < len(toks) else min(len(t), e + 18)
        left = t[max(prev_end, s - 18):s]
        right = t[e:min(next_start, e + 18)]
        # the gap AFTER the number is the stronger signal: in "16gb ram / 512gb ssd" the
        # left gap of 512 is " ram / ", which would otherwise mislabel it.
        def _lab(seg):
            if RAM_WORD.search(seg):
                return 'ram'
            if SSD_WORD.search(seg):
                return 'ssd'
            return None
        lab = _lab(right) or _lab(left)
        if lab:
            labelled[i] = lab
            if lab == 'ram' and ram is None and val in PLAUS_RAM:
                ram = val
            elif lab == 'ssd' and ssd is None and val >= 32:
                ssd = val

    # slash / pipe / dash pairs: "8/256gb", "16 | 512", "8-256 gb"
    if ram is None or ssd is None:
        for m in re.finditer(r'\b(\d{1,3})\s*(?:gb)?\s*[/|]\s*(\d{1,4})\s*(gb|tb)?\b', t):
            a = int(m.group(1))
            bgb = _to_gb(int(m.group(2)), m.group(3) or 'gb')
            if a in PLAUS_RAM and bgb in PLAUS_SSD and a < bgb:
                if ram is None:
                    ram = a
                if ssd is None:
                    ssd = bgb
                break

    # unlabelled leftovers, by plausibility
    if ram is None or ssd is None:
        free = [val for i, (val, s, e) in enumerate(toks) if i not in labelled]
        if ssd is None:
            # v2: floor 120 not 240. A lone "128GB" in a MacBook title is storage, but
            # 128 is also in PLAUS_RAM, so v1 mislabelled it as RAM (no 128 GB-RAM Air
            # exists). Labelled tokens still win -- a real "128GB RAM" is caught above.
            big = [v for v in free if v >= 120 and v in PLAUS_SSD]
            if big:
                ssd = max(big)
        if ram is None:
            small = [v for v in free if v in PLAUS_RAM and v <= 128 and (ssd is None or v < ssd)]
            if small:
                ram = max(small)

    if ram is not None and ssd is not None and ram >= ssd:
        ram = None
    if ssd is not None and not (32 <= ssd <= 8192):
        ssd = None
    return ram, ssd

# ---------- condition / seller signals ----------
def flags(t):
    f = {}
    f['warranty']    = bool(re.search(r'\bzaruk\w*|\bzaruc\w*|warranty|applecare|gwarancj\w*', t))  # v2: pl
    f['new']         = bool(re.search(r'\bnov[yaey]\w*\b|nerozbalen|zapecet|nepouzit'
                                      r'|\bnow[yaey]\w*\b|nieuzywan\w*|\bsealed\b|\bbrand new\b', t))  # v2: pl/en
    f['defect']      = bool(re.search(r'\bnefunk\w*|\bvadn\w*|\bvada\b|\brozbit\w*|\bposkozen\w*|\bpraskl\w*|'
                                      r'\bna dily\b|\bnejde\b|\bnezapin\w*|\bnenabij\w*|\bzatopen\w*|'
                                      r'\bpolit\w*|\brozlit\w*|\bnahradni dily\b|\bk oprave\b'
                                      # v2: pl/en -- "Uszkodzony / Na czesci", "for parts", "faulty"
                                      r'|uszkodzon\w*|\bna czesci\b|niesprawn\w*|zepsut\w*|usterk\w*'
                                      r'|do naprawy|\bbroken\b|\bdamaged\b|for parts|\bfaulty\b'
                                      r'|not working|\bdefect\w*', t))
    f['battery_new'] = bool(re.search(r'nova baterie|vymenena baterie|nova bat\.|baterie vymenena', t))
    f['vat_dph']     = bool(re.search(r'\bdph\b|fakturu?\b|na firmu|ico\b', t))
    f['cz_kbd']      = bool(re.search(r'\bcz\b|ceska klavesnice|cz klavesnice|klavesnice cz', t))
    f['us_kbd']      = bool(re.search(r'\bus\b(?! ?\d)|us klavesnice|klavesnice us|americka klavesnice', t))
    f['touchbar']    = bool(re.search(r'touch ?bar', t))
    f['retina']      = bool(re.search(r'retina', t))
    f['top_word']    = bool(re.search(r'\btop\b|perfekt\w*|bezvad\w*|jako nov\w*|100 ?%|bez skrab|nepouzivan'
                                      r'|\bsprawn\w*|jak now\w*|idealn\w*|stan bardzo dobry'
                                      r'|\bmint\b|\bexcellent\b|\bflawless\b', t))  # v2: pl/en
    f['scratches']   = bool(re.search(r'skraban\w*|odrenin\w*|oder\w*|promackl|dulek|kosmetick\w* vad'
                                      r'|\brys[ay]\w*|zarysowan\w*|wgniecen\w*|\bscratch\w*|\bdent\w*', t))  # v2: pl/en
    f['urgent']      = bool(re.search(r'\bspech\w*|rychle|ihned k odberu|nutny? prodej|akce\b|sleva\b', t))
    f['box']         = bool(re.search(r'original\w* balen|kompletni balen|v krabici|s krabici|puvodni balen', t))
    f['swap']        = bool(re.search(r'vymen\w*|protiucet|vykup', t))
    # battery health %
    m = re.search(r'(\d{2,3})\s*%\s*(?:kapacit|zdrav|baterie|stav|bat)|baterie[^.]{0,20}?(\d{2,3})\s*%|'
                  r'kondice[^.]{0,15}?(\d{2,3})\s*%|zdravi[^.]{0,15}?(\d{2,3})\s*%', t)
    bh = None
    if m:
        for g in m.groups():
            if g and 40 <= int(g) <= 100: bh = int(g); break
    f['battery_pct'] = bh
    # charge cycles
    m = re.search(r'(\d{1,4})\s*(?:nabijec\w*\s*)?cykl\w*|cykl\w*\D{0,12}(\d{1,4})', t)
    cy = None
    if m:
        for g in m.groups():
            if g is not None and 0 <= int(g) <= 5000: cy = int(g); break
    f['cycles'] = cy
    return f

def extract(name: str, desc: str) -> dict:
    t = norm(f"{name} || {desc or ''}")
    tn = norm(name or '')
    out = {'kind': product_kind(t), 'family': family(t)}
    br, gen, var = chip(t)
    out['chip_brand'], out['chip_gen'], out['chip_variant'] = br, gen, var
    out['year'] = year(tn, t)
    out['screen'] = screen(t)
    ram, ssd = ram_ssd(t)
    out['ram_gb'], out['ssd_gb'] = ram, ssd
    out.update(flags(t))
    return out
