#!/usr/bin/env python3
"""parse_mob_v2.py -- corrected mob-behaviour extraction.
Aggro radius measured ONLY in the idle window (player fixed, so mob heading is
meaningful). Chase episodes are strict (mob must enter <=12 and stay <=18, be
sustained-toward). Adds crowding (mobs within 12 / within 2) and player speed in
chase windows. Usage: python parse_mob_v2.py mob_XXXX.jsonl grid_2706.txt"""
import sys, json, math, statistics as st
from collections import defaultdict

def euc(ax,ay,bx,by): return math.hypot(ax-bx,ay-by)
def cheb(ax,ay,bx,by): return max(abs(ax-bx),abs(ay-by))
GAP=350; SPD_GLITCH=25.0

def load(path):
    meta,frames=None,[]
    for line in open(path,encoding='utf-8',errors='replace'):
        line=line.strip()
        if not line: continue
        try: o=json.loads(line)
        except: continue
        if 'meta' in o: meta=o['meta']; continue
        if 'mark' in o: continue
        if o.get('px') is None or 'mobs' not in o: continue
        mobs={m['id']:(m['x'],m['y'],m.get('v')) for m in o['mobs'] if m.get('x') is not None}
        frames.append({'t':o['t'],'px':o['px'],'py':o['py'],'mobs':mobs})
    frames.sort(key=lambda f:f['t'])
    return meta,frames

def load_grid(path):
    rows=[r.rstrip('\n') for r in open(path,encoding='utf-8',errors='replace') if not r.startswith('#') and r.strip()]
    h=len(rows); w=len(rows[0]) if rows else 0
    def blk(x,y):
        x=int(round(x)); y=int(round(y))
        return True if (x<0 or y<0 or y>=h or x>=w) else rows[y][x]!='0'
    return w,h,blk

def stats(a):
    if not a: return None
    a=sorted(a)
    return {'n':len(a),'med':round(st.median(a),2),'mean':round(st.mean(a),2),
            'p10':round(a[int(0.10*(len(a)-1))],2),'p90':round(a[int(0.90*(len(a)-1))],2),'max':round(a[-1],2)}

def main():
    jl,gp=sys.argv[1],sys.argv[2]
    meta,frames=load(jl); w,h,blk=load_grid(gp)
    Px,Py=frames[0]['px'],frames[0]['py']
    idle_end=len(frames)
    for i,f in enumerate(frames):
        if cheb(f['px'],f['py'],Px,Py)>3: idle_end=i; break
    idle_t=frames[max(0,idle_end-1)]['t']
    print(f"frames={len(frames)} span={frames[-1]['t']/1000:.0f}s  idle_window=0..{idle_end} (~{idle_t/1000:.0f}s @ player {Px,Py})")

    tracks=defaultdict(list); vnum={}
    for f in frames:
        for mid,(x,y,v) in f['mobs'].items():
            tracks[mid].append((f['t'],x,y))
            if v is not None: vnum[mid]=v
    pp={f['t']:(f['px'],f['py']) for f in frames}

    # ---- AGGRO RADIUS from idle window (player fixed) ----
    aggro_R=[]; aggro_mobs=0
    for mid,tr in tracks.items():
        seg=[(t,x,y) for t,x,y in tr if t<=idle_t]
        if len(seg)<6: continue
        ds=[euc(x,y,Px,Py) for _,x,y in seg]
        dmin=min(ds)
        if dmin>4: continue            # never reached player => never aggroed
        aggro_mobs+=1
        ai=next(i for i,d in enumerate(ds) if d<=4)
        k=ai; runmax=ds[ai]
        while k>0 and ds[k-1] >= ds[k]-1.5:   # walk back through the approach (noise-tolerant)
            k-=1; runmax=max(runmax,ds[k])
        aggro_R.append(runmax)
    print(f"\n=== AGGRO RADIUS (idle window; {aggro_mobs} mobs reached you) ===")
    print("  trigger distance tiles:",stats(aggro_R))

    # ---- IDLE WANDER (far mobs in idle window, never aggroed) ----
    moves=0; vt=0.0; wmax=defaultdict(float); home={}
    for mid,tr in tracks.items():
        seg=[(t,x,y) for t,x,y in tr if t<=idle_t]
        ds=[euc(x,y,Px,Py) for _,x,y in seg]
        if not ds or min(ds)<=15: continue
        for k in range(1,len(seg)):
            t0,x0,y0=seg[k-1]; t1,x1,y1=seg[k]; dt=t1-t0
            if dt<=0 or dt>GAP: continue
            vt+=dt/1000.0
            if (x0,y0)!=(x1,y1): moves+=1
            hm=home.setdefault(mid,(x1,y1)); wmax[mid]=max(wmax[mid],euc(x1,y1,hm[0],hm[1]))
    rate=moves/max(1e-9,vt)
    print(f"\n=== IDLE WANDER (far, never-aggroed mobs) ===")
    print(f"  tile-steps/s: {rate:.2f}  (~1 step every {1000/max(1e-9,rate):.0f} ms)")
    print(f"  wander radius/mob tiles:",stats(list(wmax.values())))

    # ---- STRICT CHASE EPISODES ----
    CMAX,PROOF,MINMS=18,12,1500
    mob_s=[]; ply_s=[]; durs=[]; dmins=[]; chasing_at=defaultdict(set)
    def flush(run):
        if len(run)<3: return
        ts,te=run[0][0],run[-1][0]; dur=te-ts
        ds=[euc(x,y,pp[t][0],pp[t][1]) for t,x,y in run]
        if dur<MINMS or min(ds)>PROOF: return
        tw=mv=0
        for k in range(1,len(run)):
            t0,x0,y0=run[k-1]; t1,x1,y1=run[k]
            if (x0,y0)!=(x1,y1):
                mv+=1; px,py=pp[t1]
                if (x1-x0)*(px-x0)+(y1-y0)*(py-y0)>0: tw+=1
        if mv<3 or tw/max(1,mv)<0.55: return
        mp=pl=0.0
        for k in range(1,len(run)):
            t0,x0,y0=run[k-1]; t1,x1,y1=run[k]
            d=euc(x0,y0,x1,y1)
            if d/((t1-t0)/1000.0)<=SPD_GLITCH: mp+=d
            a,b=pp[t0],pp[t1]; pl+=euc(a[0],a[1],b[0],b[1])
        mob_s.append(mp/(dur/1000.0)); ply_s.append(pl/(dur/1000.0))
        durs.append(dur); dmins.append(min(ds))
        for t,_,_ in run: chasing_at[t].add(run_mid[0])
    run_mid=[None]
    for mid,tr in tracks.items():
        run_mid[0]=mid
        i=0
        while i<len(tr):
            j=i
            while j+1<len(tr) and (tr[j+1][0]-tr[j][0])<=GAP: j+=1
            seg=tr[i:j+1]; i=j+1
            run=[]
            for (t,x,y) in seg:
                if euc(x,y,pp[t][0],pp[t][1])<=CMAX: run.append((t,x,y))
                else: flush(run); run=[]
            flush(run)
    maxch=max((len(s) for s in chasing_at.values()),default=0)
    print(f"\n=== STRICT CHASE EPISODES (enter <=12, hold <=18, >=1.5s, toward) ===")
    print(f"  episodes={len(durs)}  max simultaneous chasers={maxch}")
    print(f"  duration ms (persistence/leash proxy):",stats(durs))
    print(f"  closest approach tiles:",stats(dmins))
    print(f"  MOB speed   tiles/s:",stats(mob_s))
    print(f"  PLAYER speed tiles/s (same windows):",stats(ply_s))
    if mob_s and ply_s:
        print(f"  -> mob/player speed ratio (median): {stats(mob_s)['med']/max(1e-9,stats(ply_s)['med']):.2f}"
              f"  (>=1 mob keeps up/gains; <1 you can kite)")

    # ---- CROWDING (Chebyshev, matches aggro=12) ----
    mA=mM=0; aSer=[]
    for f in frames:
        px,py=f['px'],f['py']; a=m=0
        for mid,(x,y,v) in f['mobs'].items():
            d=cheb(x,y,px,py)
            if d<=12: a+=1
            if d<=2: m+=1
        mA=max(mA,a); mM=max(mM,m); aSer.append(a)
    print(f"\n=== CROWDING ===")
    print(f"  max mobs within aggro(12): {mA}   max within melee(<=2): {mM}")
    print(f"  mobs-within-12 distribution:",stats(aSer))

    out={'aggro_radius_tiles':stats(aggro_R),'idle_step_rate_per_s':round(rate,2),
         'idle_wander_radius':stats(list(wmax.values())),'chase_episodes':len(durs),
         'chase_dur_ms':stats(durs),'chase_dmin_tiles':stats(dmins),
         'mob_speed_tiles_s':stats(mob_s),'player_speed_tiles_s':stats(ply_s),
         'max_simultaneous_chasers':maxch,'max_within_aggro12':mA,'max_within_melee2':mM}
    json.dump(out,open('mob_sim_params_v2.json','w'),indent=2)
    print("\n[written] mob_sim_params_v2.json")

if __name__=='__main__': main()
