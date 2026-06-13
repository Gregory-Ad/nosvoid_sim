import json
frames=[]
for line in open("mob_20260613_205049.jsonl",encoding="utf-8",errors="replace"):
    try:o=json.loads(line)
    except:continue
    if o.get("px") is None or "mobs" not in o:continue
    ids=[m["id"] for m in o["mobs"]]
    frames.append((o["t"],len(ids),min(ids) if ids else None,max(ids) if ids else None))
# show transitions in n (alive-in-view count) over the whole session, compressed
prev=None
print("t(s)   n   id_min  id_max   <- only when n changes by >3")
for t,n,lo,hi in frames:
    if prev is None or abs(n-prev)>3:
        print(f"{t/1000:6.1f} {n:3d}   {lo}   {hi}")
        prev=n
print("\nLAST 6 frames:")
for t,n,lo,hi in frames[-6:]:
    print(f"{t/1000:6.1f} n={n} id_min={lo} id_max={hi}")
