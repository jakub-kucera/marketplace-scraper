"""Desktop-PC listing -> structured spec extraction (Czech marketplace text).

Design note: GPU and CPU tier/generation are parsed OUT OF THE MODEL NAME rather than looked
up in a table. "rtx 3070" already encodes vendor, generation (30) and tier (70) positionally,
and the naming is stable across a decade, so an ordinal feature falls out with no external
data to maintain. A spec table is only needed for things the name does NOT encode -- chiefly
VRAM, which varies within a model (RTX 3060 ships 8GB and 12GB).
"""
import re, unicodedata

def norm(s: str) -> str:
    s = (s or '').lower()
    s = ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c))
    s = s.replace('–', '-').replace('—', '-')
    # commas / slashes / pipes stay as BARRIERS. "rx 6700 xt, 32gb" is a GPU and then system
    # RAM; flattening the comma turns 32GB of RAM into 32GB of VRAM on the card.
    s = re.sub(r'[|/;+]', ',', s)
    return re.sub(r'\s+', ' ', s)

# ---------- what is this listing ----------
NOT_A_PC = re.compile(r'\b(bitmain|antminer|asic|miner\b|whatsminer|iphone|ipad|apple watch)\b')
LAPTOP   = re.compile(r'\b(macbook|notebook|laptop|thinkpad|ideapad|vivobook|zenbook|legion \d|nitro \d)\b')
APPLE_DESK = re.compile(r'\b(imac|mac ?pro|mac ?mini|mac ?studio)\b')
MONITOR_ONLY = re.compile(r'^\s*(lcd|monitor|herni monitor)\b')

def kind(t: str) -> str:
    if NOT_A_PC.search(t): return 'not_pc'
    if MONITOR_ONLY.search(t): return 'monitor'
    if LAPTOP.search(t) and not re.search(r'\b(herni pc|sestava|desktop|skrin)\b', t): return 'laptop'
    # Apple desktops price on a different curve entirely and almost never name a discrete
    # GPU; leaving them in "desktop" was ~4% of rows the model could only guess at.
    if APPLE_DESK.search(t): return 'apple_desktop'
    return 'desktop'

# ---------- GPU ----------
#: vendor, series-number, optional suffix. The number carries generation and tier positionally:
#: 3070 -> gen 30, tier 70;  9070 -> gen 90, tier 70 (AMD RX 9000);  1660 -> gen 16, tier 60.
GPU = re.compile(
    r'\b(rtx|gtx|rx|radeon|arc)\s*-?\s*(\d{3,4})\s*'
    r'(ti\s*super|ti|super|xtx|xt|gre|s|x)?\b')
#: workstation / compute cards -- a different price curve, worth flagging rather than tiering
GPU_PRO = re.compile(r'\b(quadro|radeon pro|firepro|tesla|nvidia rtx a\d|\bw\d{4}\b)')
#: only across spaces -- a comma or slash means the number belongs to the next component
GPU_VRAM = re.compile(r'\b(rtx|gtx|rx|arc)[ -]*\d{3,4}[ ]*(?:ti|super|xtx|xt|gre)?[ ]*(\d{1,2})\s*gb\b')

#: "2080s" is Super and "580x" is the AMD X-suffix -- both are commonly written unspaced.
_SUFFIX_ALIAS = {'s': 'super', 'x': 'xt'}
_SUFFIX_RANK = {None: 0, 'gre': 1, 'super': 2, 'xt': 2, 'ti': 3, 'ti super': 4, 'xtx': 4}

def gpu(t: str):
    m = GPU.search(t)
    if not m:
        return {'gpu_pro': True} if GPU_PRO.search(t) else {}
    vendor_tok, num, suf = m.group(1), m.group(2), (m.group(3) or None)
    suf = re.sub(r'\s+', ' ', suf) if suf else None
    suf = _SUFFIX_ALIAS.get(suf, suf)
    if vendor_tok == 'radeon':
        vendor_tok = 'rx'
    n = int(num)
    if len(num) == 4:
        gen, tier = n // 100, n % 100
    else:                       # 3-digit AMD (rx 580, rx 480)
        gen, tier = n // 100 * 10, n % 100
    vendor = 'nvidia' if vendor_tok in ('rtx', 'gtx') else ('amd' if vendor_tok == 'rx' else 'intel')
    out = {'gpu_vendor': vendor, 'gpu_series': vendor_tok, 'gpu_num': n,
           'gpu_gen': gen, 'gpu_tier': tier, 'gpu_suffix': suf,
           'gpu_suffix_rank': _SUFFIX_RANK.get(suf, 0),
           'gpu_model': f"{vendor_tok} {n}" + (f" {suf}" if suf else "")}
    mv = GPU_VRAM.search(t)
    if mv:
        v = int(mv.group(2))
        if v in (2,3,4,6,8,10,11,12,16,20,24,32): out['gpu_vram'] = v
    return out

# ---------- CPU ----------
INTEL = re.compile(r'\bi([3579])\s*-?\s*(\d{4,5})\s*([a-z]{0,2})\b')
RYZEN = re.compile(r'\bryzen\s*([3579])\s*(\d{4})\s*([a-z0-9]{0,3})\b')
RYZEN_BARE = re.compile(r'\bryzen\s*([3579])\b')
INTEL_BARE = re.compile(r'\bi([3579])\b')
ULTRA = re.compile(r'\bcore\s*ultra\s*([579])\s*(\d{3})?\b')

def cpu(t: str):
    m = INTEL.search(t)
    if m:
        tier, num, suf = int(m.group(1)), int(m.group(2)), (m.group(3) or None)
        gen = num // 1000 if num >= 10000 else num // 1000   # 12400 -> 12, 9400 -> 9
        return {'cpu_vendor':'intel','cpu_tier':tier,'cpu_gen':gen,'cpu_num':num,
                'cpu_suffix':suf,'cpu_model':f"i{tier}-{num}{suf or ''}"}
    m = RYZEN.search(t)
    if m:
        tier, num, suf = int(m.group(1)), int(m.group(2)), (m.group(3) or None)
        return {'cpu_vendor':'amd','cpu_tier':tier,'cpu_gen':num//1000,'cpu_num':num,
                'cpu_suffix':suf,'cpu_model':f"ryzen {tier} {num}{suf or ''}",
                'cpu_x3d': bool(suf and 'x3d' in suf)}
    m = ULTRA.search(t)
    if m:
        return {'cpu_vendor':'intel','cpu_tier':int(m.group(1)),'cpu_gen':14,
                'cpu_num':int(m.group(2)) if m.group(2) else None,'cpu_model':f"ultra {m.group(1)}"}
    if re.search(r'\bthreadripper\b', t): return {'cpu_vendor':'amd','cpu_tier':9,'cpu_model':'threadripper'}
    if re.search(r'\bxeon\b', t): return {'cpu_vendor':'intel','cpu_model':'xeon'}
    m = RYZEN_BARE.search(t)
    if m: return {'cpu_vendor':'amd','cpu_tier':int(m.group(1)),'cpu_model':f"ryzen {m.group(1)}"}
    m = INTEL_BARE.search(t)
    if m: return {'cpu_vendor':'intel','cpu_tier':int(m.group(1)),'cpu_model':f"i{m.group(1)}"}
    return {}

# ---------- memory / storage ----------
RAM_LABEL = re.compile(r'(\d{1,3})\s*gb\s*(?:ddr[45]|ram|pameti?)|(?:ram|pamet)\s*:?\s*(\d{1,3})\s*gb')
DDR = re.compile(r'\bddr([45])\b')
PLAUS_RAM = {4,6,8,12,16,24,32,48,64,96,128,192,256}
STORE = re.compile(r'(\d{1,4})\s*(gb|tb)\s*(ssd|nvme|m\.?2|hdd)|(ssd|nvme|m\.?2|hdd)\s*:?\s*(\d{1,4})\s*(gb|tb)')

def memory(t: str):
    out = {}
    m = DDR.search(t)
    if m: out['ddr'] = int(m.group(1))
    ram = None
    for mm in RAM_LABEL.finditer(t):
        v = int(mm.group(1) or mm.group(2))
        if v in PLAUS_RAM: ram = v; break
    if ram is None:                       # bare "32gb" with no label, common in titles
        cand = [int(x) for x in re.findall(r'\b(\d{1,3})\s*gb\b', t)]
        cand = [c for c in cand if c in PLAUS_RAM and c <= 256]
        # a bare GB next to a GPU token is VRAM, not RAM -- drop those
        vram = {int(x) for x in re.findall(r'(?:rtx|gtx|rx|arc)[ -]*\d{3,4}[ ]*(?:ti|super|xtx|xt)?[ ]*(\d{1,2})\s*gb', t)}
        cand = [c for c in cand if c not in vram or c >= 16]
        if cand: ram = max(cand)
    if ram: out['ram_gb'] = ram
    ssd = hdd = 0
    for mm in STORE.finditer(t):
        if mm.group(1):
            v, unit, dev = int(mm.group(1)), mm.group(2), mm.group(3)
        else:
            dev, v, unit = mm.group(4), int(mm.group(5)), mm.group(6)
        gb = v * 1000 if unit == 'tb' else v
        if gb < 60 or gb > 32000: continue
        if 'hdd' in dev: hdd += gb
        else: ssd += gb
    if ssd: out['ssd_gb'] = ssd
    if hdd: out['hdd_gb'] = hdd
    return out

# ---------- condition / extras ----------
def flags(t: str):
    return {
      'gaming':   bool(re.search(r'\bherni\b|\bgaming\b', t)),
      'warranty': bool(re.search(r'zaruk|zaruc', t)),
      'new':      bool(re.search(r'\bnov[yaey]\w*\b|nerozbalen|nepouzit', t)),
      'defect':   bool(re.search(r'\bnefunk\w*|\bvadn\w*|\bna dily\b|\bposkozen\w*|\bnejde\b', t)),
      'with_monitor': bool(re.search(r'\bmonitor\b|\blcd\b', t)),
      'prebuilt': bool(re.search(r'\b(alienware|lynx|hp omen|dell|acer predator|msi codex|hyperx)\b', t)),
      'watercool': bool(re.search(r'vodni chlaz|aio|liquid', t)),
      'wifi':     bool(re.search(r'\bwifi\b|\bwi-fi\b', t)),
    }

def extract(name, short, full=None):
    t = norm(f"{name} || {short or ''} || {full or ''}")
    out = {'kind': kind(t)}
    out.update(gpu(t)); out.update(cpu(t)); out.update(memory(t)); out.update(flags(t))
    return out
