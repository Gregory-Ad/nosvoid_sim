#!/usr/bin/env python3
"""
parse_mob_telemetry.py -- turn a CE mob-telemetry JSONL (10 Hz position poll of
map 2706) into mob-behaviour parameters for the offline sim.
stdlib only.  Usage: python parse_mob_telemetry.py mob_XXXX.jsonl grid_2706.txt
"""
import sys, json, math, statistics as st
from collections import defaultdict, deque

def euc(ax, ay, bx, by): return math.hypot(ax - bx, ay - by)
def cheb(ax, ay, bx, by): return max(abs(ax - bx), abs(ay - by))

GAP_MS = 350
WIN = 8
SPD_GLITCH = 25.0


def load(path):
    meta, frames, marks = None, [], []
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            if 'meta' in o:
                meta = o['meta']; continue
            if 'mark' in o:
                marks.append(o); continue
            if 't' in o and 'mobs' in o and o.get('px') is not None:
                mobs = {}
                for m in o['mobs']:
                    if m.get('x') is None or m.get('y') is None:
                        continue
                    mobs[m['id']] = (m['x'], m['y'], m.get('v'), m.get('hp'))
                frames.append({'t': o['t'], 'px': o['px'], 'py': o['py'],
                               'php': o.get('php'), 'tgt': o.get('tgt', 0), 'mobs': mobs})
    frames.sort(key=lambda fr: fr['t'])
    return meta, frames, marks


def load_grid(path):
    rows = []
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            if line.startswith('#'):
                continue
            line = line.rstrip('\n')
            if line:
                rows.append(line)
    h = len(rows); w = len(rows[0]) if rows else 0
    def blocked(x, y):
        x = int(round(x)); y = int(round(y))
        if x < 0 or y < 0 or y >= h or x >= w:
            return True
        return rows[y][x] != '0'
    return w, h, blocked


def line_blocked(x0, y0, x1, y1, blocked):
    x0, y0, x1, y1 = int(round(x0)), int(round(y0)), int(round(x1)), int(round(y1))
    dx, dy = abs(x1 - x0), abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy
    x, y = x0, y0
    first = True
    while True:
        if not first and not (x == x1 and y == y1):
            if blocked(x, y):
                return True
        first = False
        if x == x1 and y == y1:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy; x += sx
        if e2 < dx:
            err += dx; y += sy
    return False


def stats(a):
    if not a:
        return None
    a = sorted(a)
    return {'n': len(a), 'med': round(st.median(a), 2), 'mean': round(st.mean(a), 2),
            'p10': round(a[int(0.10 * (len(a) - 1))], 2),
            'p90': round(a[int(0.90 * (len(a) - 1))], 2), 'max': round(a[-1], 2)}


def main():
    jl = sys.argv[1] if len(sys.argv) > 1 else 'mob.jsonl'
    gp = sys.argv[2] if len(sys.argv) > 2 else 'grid_2706.txt'
    meta, frames, marks = load(jl)
    w, h, blocked = load_grid(gp)
    print(f"frames={len(frames)}  span={frames[0]['t']/1000:.1f}..{frames[-1]['t']/1000:.1f}s"
          f"  grid={w}x{h}  marks={len(marks)}")
    if meta:
        print("meta:", meta)

    p0 = (frames[0]['px'], frames[0]['py'])
    idle_end = len(frames)
    for i, fr in enumerate(frames):
        if cheb(fr['px'], fr['py'], p0[0], p0[1]) > 3:
            idle_end = i; break
    print(f"\n[idle window] frames 0..{idle_end} (~{frames[max(0,idle_end-1)]['t']/1000:.1f}s, player fixed at {p0})")

    on_wall = tot = 0
    for fr in frames[::5]:
        for mid, (x, y, v, hp) in fr['mobs'].items():
            tot += 1
            if blocked(x, y):
                on_wall += 1
    print(f"[grid sanity] mob samples on blocked tiles: {on_wall}/{tot} "
          f"({100*on_wall/max(1,tot):.1f}%)  (high% => coord/grid misalignment)")

    last = {}
    win = defaultdict(lambda: deque(maxlen=WIN))
    pursuing = {}
    ep = {}
    vnum_of = {}

    idle_path = idle_time = idle_move_time = 0.0
    idle_still_frames = idle_move_frames = 0
    wander_home = {}
    wander_max = defaultdict(float)

    aggro_onset = []
    episodes = []
    pursuers_per_t = defaultdict(int)

    def close_ep(mid, t_end, how, d_end):
        e = ep.pop(mid, None)
        if e and (t_end - e['start']) > 0:
            episodes.append((mid, e['start'], t_end, e['dmin'], e['dmax'],
                             t_end - e['start'], how, d_end))
        pursuing[mid] = False

    for fi, fr in enumerate(frames):
        t, px, py = fr['t'], fr['px'], fr['py']
        for mid, (x, y, v, hp) in fr['mobs'].items():
            if v is not None:
                vnum_of[mid] = v
            ls = last.get(mid)
            last[mid] = (t, x, y)
            d1 = euc(x, y, px, py)
            if ls is None:
                continue
            t0, x0, y0 = ls
            dt = t - t0
            if dt <= 0 or dt > GAP_MS:
                if pursuing.get(mid):
                    close_ep(mid, t0, 'gap', euc(x0, y0, px, py))
                win[mid].clear()
                continue
            dts = dt / 1000.0
            step = euc(x0, y0, x, y)
            spd = step / dts
            moved = (x0, y0) != (x, y)
            proj = (x - x0) * (px - x0) + (y - y0) * (py - y0)
            toward = moved and proj > 0
            win[mid].append((moved, toward, d1))

            wmoved = sum(1 for m, _, _ in win[mid] if m)
            wtoward = sum(1 for _, tw, _ in win[mid] if tw)
            d_start = win[mid][0][2]
            net_appr = d_start - d1
            is_pursue = (wmoved >= 4 and (wtoward / max(1, wmoved)) >= 0.70
                         and (d1 < 15 or net_appr > 0))

            if fi < idle_end and d1 > 15 and not is_pursue:
                idle_time += dts
                if moved and spd <= SPD_GLITCH:
                    idle_path += step; idle_move_time += dts; idle_move_frames += 1
                else:
                    idle_still_frames += 1
                hm = wander_home.setdefault(mid, (x, y))
                wander_max[mid] = max(wander_max[mid], euc(x, y, hm[0], hm[1]))

            was = pursuing.get(mid, False)
            if is_pursue:
                pursuers_per_t[t] += 1
                if not was:
                    pursuing[mid] = True
                    ep[mid] = {'start': t, 'path': 0.0, 'dmin': d1, 'dmax': max(d1, d_start)}
                    aggro_onset.append(d_start)
                e = ep[mid]
                if spd <= SPD_GLITCH:
                    e['path'] += step
                e['dmin'] = min(e['dmin'], d1)
                e['dmax'] = max(e['dmax'], d1)
            else:
                if was:
                    close_ep(mid, t, 'ended', d1)

    for mid in list(ep.keys()):
        t_last = last[mid][0]
        close_ep(mid, t_last, 'open', 0.0)

    print("\n=== IDLE WANDER (player stationary, mob >15 tiles away) ===")
    if idle_move_time > 0:
        print(f"  speed while moving : {idle_path/idle_move_time:.2f} tiles/s")
    print(f"  net wander rate    : {idle_path/max(1e-9,idle_time):.2f} tiles/s (incl. pauses)")
    tot_idle = idle_move_frames + idle_still_frames
    print(f"  still fraction     : {idle_still_frames/max(1,tot_idle):.2f}"
          f"   ({idle_move_frames} moving / {idle_still_frames} still frames)")
    wr = stats(list(wander_max.values()))
    print(f"  wander radius/mob  : {wr}")

    print("\n=== AGGRO TRIGGER (player-mob dist at pursuit onset, tiles) ===")
    print(" ", stats(aggro_onset))

    print("\n=== MAX SIMULTANEOUS PURSUERS (bounded by mobs-in-view) ===")
    if pursuers_per_t:
        vals = sorted(pursuers_per_t.values())
        print(f"  max={max(vals)}  median-when-active={st.median(vals)}  "
              f"frames-with-any-pursuit={len(vals)}")
    else:
        print("  none detected")

    print("\n=== PURSUIT EPISODES ===")
    how_ct = defaultdict(int)
    for e in episodes:
        how_ct[e[6]] += 1
    print(f"  total={len(episodes)}  " + "  ".join(f"{k}={v}" for k, v in how_ct.items()))
    ended = [e for e in episodes if e[6] == 'ended' and e[5] >= 800]
    if ended:
        print("  [ended-in-view, >=0.8s] duration ms      :", stats([e[5] for e in ended]))
        print("  [ended-in-view] closest approach (tiles) :", stats([e[3] for e in ended]))
        print("  [ended-in-view] dist when it stopped     :", stats([e[7] for e in ended]),
              "<- leash proxy (ambiguous vs player-escaped)")
    longest = sorted(episodes, key=lambda e: e[5], reverse=True)[:6]
    print("  longest (mid,vnum,dur_ms,dmin,how):",
          [(e[0], vnum_of.get(e[0]), e[5], round(e[3], 1), e[6]) for e in longest])

    long_ids = {(e[0], e[1], e[2]) for e in longest if e[5] >= 1200}
    tracks = defaultdict(list)
    for fr in frames:
        for mid, (x, y, v, hp) in fr['mobs'].items():
            tracks[mid].append((fr['t'], x, y))
    pp = {fr['t']: (fr['px'], fr['py']) for fr in frames}

    chase_speeds = []
    path_ok = path_steps = chord_blocked = 0
    samples = []
    for (mid, t0, t1) in long_ids:
        seg = [(t, x, y) for (t, x, y) in tracks[mid] if t0 <= t <= t1]
        if len(seg) < 3:
            continue
        plen = 0.0
        for j in range(1, len(seg)):
            tt0, xx0, yy0 = seg[j-1]; tt1, xx1, yy1 = seg[j]
            ddt = tt1 - tt0
            if ddt <= 0 or ddt > GAP_MS:
                continue
            d = euc(xx0, yy0, xx1, yy1)
            if d / (ddt/1000.0) <= SPD_GLITCH:
                plen += d
            path_steps += 1
            if not blocked(xx1, yy1):
                path_ok += 1
            if tt1 in pp and line_blocked(xx1, yy1, pp[tt1][0], pp[tt1][1], blocked):
                chord_blocked += 1
        dur = (seg[-1][0] - seg[0][0]) / 1000.0
        if dur > 0:
            chase_speeds.append(plen / dur)
        samples.append((mid, [(x, y) for _, x, y in seg][:30]))

    print("\n=== CHASE SPEED (episode-averaged, tiles/s) ===")
    print(" ", stats(chase_speeds))

    print("\n=== PATHING vs WALLS (longest pursuit episodes) ===")
    print(f"  pursuit-path tiles on walkable cells : {path_ok}/{path_steps}")
    print(f"  frames w/ straight line mob->player wall-blocked : {chord_blocked}"
          f"  (mob kept pathing => it routes around walls)")
    for mid, coords in samples[:3]:
        print(f"  path mob {mid} (vnum {vnum_of.get(mid)}): {coords}")

    cs = stats(chase_speeds)
    isp = (idle_path/idle_move_time) if idle_move_time > 0 else None
    out = {
        'idle_speed_tiles_s_moving': round(isp, 2) if isp else None,
        'idle_still_fraction': round(idle_still_frames/max(1, tot_idle), 3),
        'wander_radius_tiles': wr,
        'aggro_trigger_dist_tiles': stats(aggro_onset),
        'chase_speed_tiles_s': cs,
        'max_simultaneous_pursuers': (max(pursuers_per_t.values()) if pursuers_per_t else 0),
        'pursuit_episodes': len(episodes),
        'pursuit_path_walkable': [path_ok, path_steps],
        'chord_blocked_frames': chord_blocked,
        'leash_dist_when_stopped_tiles': stats([e[7] for e in ended]) if ended else None,
        'notes': "n=in-view not alive; player never targeted; speeds episode-averaged.",
    }
    if cs:
        out['suggest_mob_step_ms_chase'] = round(1000.0 / cs['med'])
    if isp:
        out['suggest_mob_step_ms_idle'] = round(1000.0 / isp)
    with open('mob_sim_params.json', 'w') as f:
        json.dump(out, f, indent=2)
    print("\n[written] mob_sim_params.json\n")
    print(json.dumps(out, indent=2))


if __name__ == '__main__':
    main()
