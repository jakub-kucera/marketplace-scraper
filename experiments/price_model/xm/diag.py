import sys; sys.path.insert(0,'.'); import mbfeat
cases = [
 'MacBook air 15','MacBook Air 15" M2','MacBook Pro 14-inch (M3 Pro, 18GB/512GB)',
 'MacBook Pro i7 15 cali 16 GB RAM Touchbar Radeon Pro 4GB Dysk 512gb',
 'MacBook Air 2017r. 8GB RAM','MacBook PRO 16 M2PRO/32GB/1TB',
 'Macbook Air 13 M5 24/512 CZ. 22m zaruka. STAV NOVE',
 'MacBook Pro 14 M5 Pro 48GB 1TB Nano Záruka 2030',
 'Apple MacBook Pro 13" 2017 (A1708) - Uszkodzony / Na części',
 'MacBook Air 13– 256 GB','MacBook Air M1 - sprawny','Laptop MacBook 12',
 'MacBook Air 13 cali 2019 128GB','Apple MacBook Neo (2026) 8GB / 256GB / CZ - 100%',
 'MacBook Air 13 2012r  / i7 / 8 ram / 256 ssd /',
 'MacBook Pro 13 2017','macbook air 2020 13”',
]
for c in cases:
    r = mbfeat.extract(c, '')
    print(f"{c[:58]:<58} chip={r['chip_brand']}{r['chip_gen'] or ''}{'' if r['chip_variant'] in (None,'base') else r['chip_variant']:<5} yr={r['year']} scr={r['screen']} ram={r['ram_gb']} ssd={r['ssd_gb']} def={r['defect']}")
