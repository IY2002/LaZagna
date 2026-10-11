from __future__ import annotations
import re

from layout_space import LayoutSpec, CLB, DSP, BRAM, IO

BLOCK_NAME_MAP = {
    CLB: "clb",
    DSP: "complex_dsp",
    BRAM: "spram",
    IO: "io",
}

def tile_heights(xml: str) -> dict[str, int]:
    """Height of every <tile> in an arch XML (default 1)."""
    out = {}
    for m in re.finditer(r"<tile\b([^>]*)>", xml):
        attrs = m.group(1)
        name = re.search(r'name="([^"]+)"', attrs)
        h = re.search(r'height="(\d+)"', attrs)
        if name:
            out[name.group(1)] = int(h.group(1)) if h else 1
    return out


def _layer_singles(layer: list[list[str]], heights: dict[str, int]) -> list[tuple[str, int, int]]:
    """(vpr_type, x, y) anchors for the hard blocks of one layer.

    Walks each interior column bottom-up. A hard block of height h is anchored at y and
    covers y..y+h-1, so the walk skips its rows; a block that would run past the top of the
    interior is dropped (those rows fall back to the CLB fill). With 1x1 blocks this
    reduces to one <single> per hard-block cell, as before."""
    h_grid, w_grid = len(layer), len(layer[0])
    out = []
    for x in range(1, w_grid - 1):
        y = 1
        while y < h_grid - 1:
            generic = layer[y][x]
            mapped = BLOCK_NAME_MAP.get(generic) if generic and generic != CLB else None
            if mapped is None or mapped == "io":
                y += 1
                continue
            bh = heights.get(mapped, 1)
            if y + bh - 1 <= h_grid - 2:
                out.append((mapped, x, y))
                y += bh
            else:
                y += 1
    return out


def _grid_to_layout_xml(grid: list[list[list[str]]], width: int, height: int,
                        layout_name: str = "generated", heights: dict[str, int] | None = None,
                        layers: int = 2) -> str:
    """layers=1 writes a single-die layout (no <layer> wrapper) for the 2D templates."""
    heights = heights or {}
    lines = ['  <layout tileable="false">']
    lines.append(f'    <fixed_layout name="{layout_name}" width="{width}" height="{height}">')
    for die_idx, layer in enumerate(grid[:layers]):
        ind = "        " if layers > 1 else "      "
        if layers > 1:
            lines.append(f'      <layer die="{die_idx}">')
        lines.append(f'{ind}<perimeter type="io" priority="100"/>')
        lines.append(f'{ind}<corners type="EMPTY" priority="101"/>')
        lines.append(f'{ind}<fill type="clb" priority="10"/>')
        for mapped, x, y in _layer_singles(layer, heights):
            lines.append(f'{ind}<single type="{mapped}" x="{x}" y="{y}" priority="20"/>')
        if layers > 1:
            lines.append('      </layer>')
    lines.append('    </fixed_layout>')
    lines.append('  </layout>')
    return "\n".join(lines)


def block_counts(xml: str) -> dict[str, int]:
    """Count hard blocks in a rendered arch (one <single> per placed block)."""
    m = re.search(r"<layout\b.*?</layout>", xml, re.S)
    out: dict[str, int] = {}
    for t in re.findall(r'<single type="([^"]+)"', m.group(0) if m else ""):
        out[t] = out.get(t, 0) + 1
    return out

def render_arch_from_template(template_path: str, spec: LayoutSpec,
                              width: int, height: int, layers: int = 2) -> str:
    """Read a template arch XML and return it with the <layout> block swapped.
    Tile heights come from the template, so tall DSP/BRAM tiles are stacked correctly."""
    with open(template_path) as f:
        xml = f.read()

    grid = spec.build(width, height)
    new_layout = _grid_to_layout_xml(grid, width, height, heights=tile_heights(xml), layers=layers)

    pattern = re.compile(r"[ \t]*<layout\b.*?</layout>", re.DOTALL)
    if not pattern.search(xml):
        raise ValueError(f"no <layout> block found in template {template_path}")
    return pattern.sub(new_layout, xml, count=1)

if __name__ == "__main__":

    import sys
    import xml.etree.ElementTree as ET
    from layout_space import NAMED_LAYOUTS

    template = sys.argv[1] if len(sys.argv) > 1 else (
        "arch_files/vtr_3d_cb_arch_dsp_bram_10x10_delay_ratio_0.739.xml"
    )
    for name, spec in NAMED_LAYOUTS.items():
        out = render_arch_from_template(template, spec, 10, 10)
        ET.fromstring(out)
        n_single = out.count("<single ")
        print(f"{name:9s} valid XML, {n_single} explicit block placements")
