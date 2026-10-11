#!/usr/bin/env python3
"""Merge the write ports of every multi-write-port memory into ONE write port.

Called from yosys.ys between memory inference and BRAM mapping:
    write_rtlil in.il ; exec -- python3 merge_write_ports.py in.il out.il ; read_rtlil out.il

Why. The architecture's BRAM (spram) has a single port, so a memory written from two ports
(true dual-port, e.g. Koios dpram, HLS memcore_ram, VTR dual_port_ram) cannot map to it
and Yosys falls back to flip-flops + LUTs. Study assumption: designs never write from
both ports in the same cycle. Under that assumption the write ports are equivalent to
one write port whose address/data/enable come from whichever port is writing. (Which port
would win a simultaneous write is irrelevant under the assumption; the code gives it to the
lowest PORTID, which Yosys assigns in reverse source order.) Read ports are left alone;
BRAM mapping handles them as before.

Works on the $memwr_v2 cells Yosys produces after `proc`, before memory_collect. At that
point read ports are plain $memrd cells with no per-write-port masks, so removing write
ports needs no other fix-ups. Write ports of one memory are merged only when they share
clock, clock enable and polarity;
anything else is left untouched and reported. Signal expressions are copied verbatim, so
no RTLIL sigspec parsing is needed.
"""
import re
import sys
from collections import defaultdict


def parse_cells(lines):
    """Yield (start, end, attr_start, name, params, conns) for each $memwr_v2 cell."""
    i = 0
    while i < len(lines):
        m = re.match(r"^(\s*)cell \$memwr_v2 (\S+)\s*$", lines[i])
        if m:
            a = i
            while a > 0 and lines[a - 1].strip().startswith("attribute "):
                a -= 1
            params, conns = {}, {}
            j = i + 1
            while lines[j].strip() != "end":
                t = lines[j].strip()
                if t.startswith("parameter "):
                    k, v = t[len("parameter "):].split(" ", 1)
                    params[k] = v
                elif t.startswith("connect "):
                    k, v = t[len("connect "):].split(" ", 1)
                    conns[k] = v
                j += 1
            yield i, j, a, m.group(2), params, conns
            i = j
        i += 1


def module_ranges(lines):
    """[(start, end_line_index)] of every `module` ... `end` block."""
    out, start = [], None
    for i, l in enumerate(lines):
        if l.startswith("module "):
            start = i
        elif l.rstrip() == "end" and start is not None:
            out.append((start, i))
            start = None
    return out


def main(src, dst):
    lines = open(src).read().split("\n")
    mods = module_ranges(lines)
    by_mem = defaultdict(list)
    for c in parse_cells(lines):
        mod = next(k for k, (s, e) in enumerate(mods) if s < c[0] < e)
        by_mem[(mod, c[4]["\\MEMID"])].append(c)

    drop = set()           # line indices to delete
    edits = {}             # line index -> replacement line
    # RTLIL needs a wire declared before any cell uses it: new wires go right after the
    # `module` line, new cells before the module's `end`.
    wire_ins = defaultdict(list)  # module start index -> lines to insert after it
    inserts = defaultdict(list)   # module end index -> lines to insert before it
    uid = 0
    merged = skipped = 0
    for (mod, memid), cells in by_mem.items():
        if len(cells) < 2:
            continue
        cells.sort(key=lambda c: int(c[4].get("\\PORTID", "0")))
        key = lambda c: (c[5].get("\\CLK"), c[4].get("\\CLK_ENABLE"), c[4].get("\\CLK_POLARITY"))
        if len({key(c) for c in cells}) != 1 or cells[0][4].get("\\CLK_ENABLE") != "1'1":
            skipped += 1
            print(f"merge_write_ports: SKIP {memid}: write ports on different/no clocks")
            continue
        abits = int(cells[0][4]["\\ABITS"])
        width = int(cells[0][4]["\\WIDTH"])
        if any(int(c[4]["\\WIDTH"]) != width or int(c[4]["\\ABITS"]) != abits for c in cells):
            skipped += 1
            print(f"merge_write_ports: SKIP {memid}: write ports of different width")
            continue

        # Fold from the lowest-priority port up: acc = sel_i ? port_i : acc.
        ADDR, DATA, EN = "\\ADDR", "\\DATA", "\\EN"
        addr, data, en = cells[-1][5][ADDR], cells[-1][5][DATA], cells[-1][5][EN]
        new = inserts[mods[mod][1]]
        wires = wire_ins[mods[mod][0]]
        for c in reversed(cells[:-1]):
            uid += 1
            p = f"$merge_wp${uid}"
            any_en, a_o, d_o, e_o = (f"\\{p}$any", f"\\{p}$addr", f"\\{p}$data", f"\\{p}$en")
            wires += [f"  wire {any_en}", f"  wire width {abits} {a_o}",
                      f"  wire width {width} {d_o}", f"  wire width {width} {e_o}"]
            new += [f"  cell $reduce_or {p}$or", "    parameter \\A_SIGNED 0",
                    f"    parameter \\A_WIDTH {width}", "    parameter \\Y_WIDTH 1",
                    f"    connect \\A {c[5][EN]}", f"    connect \\Y {any_en}", "  end"]
            for nm, w, hi, lo, out in (("a", abits, c[5][ADDR], addr, a_o),
                                       ("d", width, c[5][DATA], data, d_o),
                                       ("e", width, c[5][EN], en, e_o)):
                new += [f"  cell $mux {p}$mux{nm}", f"    parameter \\WIDTH {w}",
                        f"    connect \\A {lo}", f"    connect \\B {hi}",
                        f"    connect \\S {any_en}", f"    connect \\Y {out}", "  end"]
            addr, data, en = a_o, d_o, e_o

        # Keep the highest-priority cell, rewired to the merged signals; drop the others.
        keep = cells[0]
        for li in range(keep[0] + 1, keep[1]):
            t = lines[li].strip()
            for port, sig in ((ADDR, addr), (DATA, data), (EN, en)):
                if t.startswith(f"connect {port} "):
                    indent = lines[li][:len(lines[li]) - len(lines[li].lstrip())]
                    edits[li] = f"{indent}connect {port} {sig}"
        for c in cells[1:]:
            drop.update(range(c[2], c[1] + 1))
        merged += 1
        print(f"merge_write_ports: {memid}: merged {len(cells)} write ports into 1")

    out = []
    for i, l in enumerate(lines):
        if i in inserts:
            out += inserts[i]
        if i in drop:
            continue
        out.append(edits.get(i, l))
        if i in wire_ins:
            out += wire_ins[i]
    open(dst, "w").write("\n".join(out))
    print(f"merge_write_ports: {merged} memories merged, {skipped} skipped")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
