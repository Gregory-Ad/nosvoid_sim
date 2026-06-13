import sys, json, math, statistics as st
from collections import defaultdict
def euc(ax,ay,bx,by): return math.hypot(ax-bx,ay-by)

jl=sys.argv[1]
frames=[]; meta=None
for line in open(jl,encoding='utf-8',errors='replace'):
    try:o=json.loads(line)
    except:continue
    if 'meta' in o: meta=o['meta']; continue
    if 'mark' in o: continue
    if o.get('px') is None: continue
    frames.append(o)
frames.sort(key=lambda f:f['t'])
print("frames",len(frames),"span",round(frames[-1]['t']/1000,1),"s")

# coarse timeline to see phases
print("\n=== TIMELINE (every ~2s) ===")
for f in frames[::40]:
    print(f"  t={f['t']/1000:5.1f}s pos=({f['px']:3},{f['py']:3}) hp%={f.get('php')} n={f.get('n')}")

# HITS via percent drops
ph=[(f['t'],f.get('php')) for f in frames if f.get('php') is not None]
downs=[]
for i in range(1,len(ph)):
    t0,a=ph[i-1]; t1,b=ph[i]
    if a is None or b is None: continue
    if b<a: downs.append((t1,a-b))
print("\n=== HITS (HP%% drops) ===")
print(" num %-drops",len(downs))
if len(downs)>=2:
    sizes=sorted(d for _,d in downs)
    print(" %-drop sizes:",sizes)
    times=[t for t,_ in downs]
    iv=sorted(times[i]-times[i-1] for i in range(1,len(times)))
    print(" inter-drop intervals ms: n",len(iv)," min",iv[0]," med",st.median(iv))
    print(" all intervals:",iv)
    base=[x for x in iv if 200<=x<=st.median(iv)*1.6]
    if base: print(" CADENCE estimate (swing period) ~",round(st.median(base)),"ms (tightest cluster; misses->multiples)")
else:
    print(" too few drops to time cadence (mob missed most swings or healed)")

# AGGRO onset from positions
pos={f['t']:(f['px'],f['py']) for f in frames}
track=defaultdict(list)
for f in frames:
    for m in f['mobs']:
        if m.get('x') is None: continue
        track[m['id']].append((f['t'],m['x'],m['y']))
cands=[]
for mid,tr in track.items():
    tr.sort()
    ds=[(t,euc(x,y,pos[t][0],pos[t][1])) for t,x,y in tr]
    if not ds: continue
    dmin=min(d for _,d in ds)
    if dmin>3: continue
    ai=next(i for i,(t,d) in enumerate(ds) if d<=3)
    k=ai; runmax=ds[ai][1]
    while k>0 and ds[k-1][1]>=ds[k][1]-1.5:
        k-=1; runmax=max(runmax,ds[k][1])
    cands.append((mid,round(runmax,1),round(dmin,1),ds[k][0]))
cands.sort(key=lambda c:c[3])
print("\n=== AGGRO ONSET (mobs reaching melee dist<=3) ===")
for mid,onset,dmin,t in cands[:12]:
    print(f"  mob {mid}: trigger~{onset} tiles (dmin {dmin}) at t={t/1000:.1f}s")
if cands:
    print("  median trigger distance:",st.median([c[1] for c in cands]),"tiles (n=",len(cands),")")
else:
    print("  (no mob reached melee)")
