#!/usr/bin/env python3
"""
analyze_mob_ai.py  -  NosVoid mob-AI extractor (read-only, offline).

Reads Frida `mv`-capture JSONL files and derives a data-grounded model of mob
behaviour: idle-wander step/timing/directionality, plus a chase/aggro probe
(toward-player rate by distance, chase-lag, approach-onset events).

This is a TRANSPARENT statistical extractor - no neural net, no black box.
Every number it prints can be traced to the packet stream. It exists so you
can re-run it yourself on your own captures and confirm the numbers.

PACKET FORMATS (verified):
  player move :  mv 1 <charId> <x> <y> <speed>     -> x = field[3], y = field[4]
  mob   move  :  mv 3 <mobId>  <x> <y> <speed>     -> x = field[3], y = field[4]
  (NOTE: the mover id sits in field[2]; using it as x was the bug we caught.)

USAGE:
  python analyze_mob_ai.py                       # all nosvoid_aggro*.jsonl in cwd
  python analyze_mob_ai.py file1.jsonl file2...  # explicit files
  python analyze_mob_ai.py --dir C:\\path\\to\\captures
Only the Python standard library is used.
"""
import json, glob, sys, os, argparse, bisect, statistics, collections


def cheb(a, b):
    """Chebyshev (8-direction / chessboard) distance - the metric NosTale uses."""
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def load(path):
    """Parse one JSONL capture -> list of (timestamp_ms, tokens[]). Tolerates \\r\\n and junk lines."""
    rows = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            if "t" in o and "raw" in o:
                rows.append((o["t"], o["raw"].split()))
    rows.sort()
    return rows


def per_file(rows, acc):
    """Accumulate stats from ONE file into `acc` (kept per-file so timestamps never mix across captures)."""
    # player position timeline (held-last between updates)
    pmoves = [(t, int(f[3]), int(f[4])) for t, f in rows
              if len(f) >= 5 and f[0] == "mv" and f[1] == "1"]
    pts = [t for t, _, _ in pmoves]

    def player_at(t):
        i = bisect.bisect_right(pts, t) - 1
        return (pmoves[i][1], pmoves[i][2]) if i >= 0 else None

    # mob destination streams, keyed by mob id
    mob = collections.defaultdict(list)
    for t, f in rows:
        if len(f) >= 5 and f[0] == "mv" and f[1] == "3":
            mob[int(f[2])].append((t, int(f[3]), int(f[4])))

    acc["mobs"].update(mob.keys())
    acc["player_updates"] += len(pmoves)

    for mid, seq in mob.items():
        seq.sort()
        prevdir = None
        ds = []  # (t, x, y, dist_to_player) for onset detection
        for i, (t, x, y) in enumerate(seq):
            p = player_at(t)
            ds.append((t, x, y, cheb((x, y), p) if p else None))
            if i == 0:
                continue
            (t0, x0, y0) = seq[i - 1]
            dt = t - t0
            dx, dy = x - x0, y - y0
            s = max(abs(dx), abs(dy))
            if s == 0 or dt <= 0 or dt > 20000:
                continue
            acc["steps"].append(s)
            acc["dts"].append(dt)
            d = (0 if dx == 0 else (1 if dx > 0 else -1),
                 0 if dy == 0 else (1 if dy > 0 else -1))
            if prevdir is not None:
                acc["persist"] += (d == prevdir)
                acc["turns"] += (d != prevdir)
            prevdir = d
            p0 = player_at(t0)
            if p0:
                before = cheb((x0, y0), p0)
                after = cheb((x, y), p0)
                acc["dist_toward"].append((before, 1 if after < before else 0))
                if before <= 12:
                    acc["chase_lag"].append(cheb((x, y), p0))
        # approach-onset events: a run of consecutive destinations whose distance to
        # the player strictly decreases, starting >=6 and reaching <=3 (mob closed in).
        i = 0
        while i < len(ds):
            if ds[i][3] is None:
                i += 1
                continue
            j = i
            while j + 1 < len(ds) and ds[j + 1][3] is not None and ds[j + 1][3] < ds[j][3]:
                j += 1
            if j > i and ds[j][3] is not None and ds[j][3] <= 3 and ds[i][3] >= 6:
                acc["onsets"].append(ds[i][3])
            i = max(j, i + 1)


def quant(xs, ps=(0, 25, 50, 75, 90, 100)):
    xs = sorted(xs)
    n = len(xs)
    return {p: xs[min(n - 1, int(p / 100 * n))] for p in ps}


def main():
    ap = argparse.ArgumentParser(description="NosVoid mob-AI extractor")
    ap.add_argument("files", nargs="*", help="JSONL capture files (default: nosvoid_aggro*.jsonl)")
    ap.add_argument("--dir", default=".", help="directory to search when no files are given")
    args = ap.parse_args()

    files = args.files or sorted(glob.glob(os.path.join(args.dir, "nosvoid_aggro*.jsonl")))
    if not files:
        print("No capture files found. Pass files explicitly or use --dir.")
        sys.exit(1)

    acc = {"mobs": set(), "player_updates": 0, "steps": [], "dts": [],
           "persist": 0, "turns": 0, "dist_toward": [], "chase_lag": [], "onsets": []}
    print("=" * 64)
    print("NosVoid mob-AI extractor")
    print("=" * 64)
    for f in files:
        rows = load(f)
        per_file(rows, acc)
        print(f"  loaded {os.path.basename(f):28s} {len(rows):>7} packets")

    steps, dts = acc["steps"], acc["dts"]
    print(f"\npooled: {len(acc['mobs'])} mobs | {len(steps)} mob-moves "
          f"| {acc['player_updates']} player-pos updates")
    if not steps:
        print("No mob moves parsed - check the files contain `mv 3` lines.")
        return

    print("\n--- IDLE WANDER MODEL ----------------------------------------")
    print(f"  hop length (tiles)   : {quant(steps)}  mean {statistics.mean(steps):.2f}")
    print(f"     most common hops  : {collections.Counter(steps).most_common(5)}")
    print(f"  new-dest interval ms : {quant(dts)}  median {int(statistics.median(dts))}")
    pt = acc["persist"] + acc["turns"]
    if pt:
        print(f"  direction persistence: {acc['persist']/pt:.2f}  "
              f"(~0.13 = uniform-random heading, >0.5 = directed travel)")

    print("\n--- CHASE / AGGRO PROBE --------------------------------------")
    print("  toward-player rate by distance (->100% = locked-on chase):")
    print(f"    {'dist':>9} {'n':>6} {'toward':>8}")
    for lo, hi in [(0, 4), (5, 8), (9, 11), (12, 12), (13, 14),
                   (15, 18), (19, 25), (26, 40), (41, 300)]:
        sub = [tw for dd, tw in acc["dist_toward"] if lo <= dd <= hi]
        if sub:
            print(f"    {str(lo)+'-'+str(hi):>9} {len(sub):>6} {round(100*sum(sub)/len(sub)):>6}%")
    if acc["chase_lag"]:
        print(f"  chase-lag (dest vs player, player<=12): {quant(acc['chase_lag'])} "
              f"mean {statistics.mean(acc['chase_lag']):.1f}")
    if acc["onsets"]:
        o = sorted(acc["onsets"])
        print(f"  approach-onset events: n={len(o)}  start-dist "
              f"min {o[0]} / median {o[len(o)//2]} / max {o[-1]}")
    print("\n  CAVEAT: if the player MOVED during these captures, the chase numbers are")
    print("  player-driven and noisy - they do NOT override the aggro radius (~12,")
    print("  distance-only through walls) established by the designed approach tests.")
    print("  The IDLE WANDER block above is the robust, reusable output.")


if __name__ == "__main__":
    main()
