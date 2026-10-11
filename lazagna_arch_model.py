from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, Union
import xml.etree.ElementTree as ET


def _set_attrs(elem: ET.Element, obj, *attr_names):
    # skips none fields so we don't fill XML with empty attributes
    for name in attr_names:
        val = getattr(obj, name, None)
        if val is not None:
            elem.set(name, str(val))


@dataclass
class Port:
    name: str
    num_pins: int = 1
    equivalent: Optional[str] = None

    def to_xml(self, tag: str) -> ET.Element:
        elem = ET.Element(tag)
        elem.set("name", self.name)
        if tag != "port":
            elem.set("num_pins", str(self.num_pins))
        if self.equivalent:
            elem.set("equivalent", self.equivalent)
        return elem


# the three interconnect types map directly to the three XML tags VTR supports
@dataclass
class Direct:
    name: str
    input: str
    output: str

    def to_xml(self) -> ET.Element:
        elem = ET.Element("direct")
        elem.set("name", self.name)
        elem.set("input", self.input)
        elem.set("output", self.output)
        return elem


@dataclass
class Mux:
    name: str
    input: str
    output: str

    def to_xml(self) -> ET.Element:
        elem = ET.Element("mux")
        elem.set("name", self.name)
        elem.set("input", self.input)
        elem.set("output", self.output)
        return elem


@dataclass
class Complete:
    name: str
    input: str
    output: str

    def to_xml(self) -> ET.Element:
        elem = ET.Element("complete")
        elem.set("name", self.name)
        elem.set("input", self.input)
        elem.set("output", self.output)
        return elem


Interconnect = Direct | Mux | Complete


@dataclass
class Mode:
    name: str
    children: list[PbType] = field(default_factory=list)
    interconnect: list[Interconnect] = field(default_factory=list)
    disable_packing: bool = False
    # using field(default_factory=list) everywhere to avoid the shared mutable default gotcha

    def to_xml(self) -> ET.Element:
        elem = ET.Element("mode")
        elem.set("name", self.name)
        if self.disable_packing:
            elem.set("disable_packing", "true")
        for child in self.children:
            elem.append(child.to_xml())
        if self.interconnect:
            ic_elem = ET.SubElement(elem, "interconnect")
            for ic in self.interconnect:
                ic_elem.append(ic.to_xml())
        return elem


# Timing annotations live inside a pb_type. Without them VTR's timing-driven
# packer aborts with "Found no primitive combinational delay for edge", since it
# can't find a delay value for a LUT in->out path or an FF's register timing.
@dataclass
class DelayConstant:
    # combinational delay from in_port -> out_port (port names are pb-qualified, e.g. "lut6.in")
    in_port: str
    out_port: str
    max: float

    def to_xml(self) -> ET.Element:
        elem = ET.Element("delay_constant")
        elem.set("max", str(self.max))
        elem.set("in_port", self.in_port)
        elem.set("out_port", self.out_port)
        return elem


@dataclass
class TSetup:
    port: str
    clock: str
    value: float

    def to_xml(self) -> ET.Element:
        elem = ET.Element("T_setup")
        elem.set("value", str(self.value))
        elem.set("port", self.port)
        elem.set("clock", self.clock)
        return elem


@dataclass
class TClockToQ:
    port: str
    clock: str
    max: float

    def to_xml(self) -> ET.Element:
        elem = ET.Element("T_clock_to_Q")
        elem.set("max", str(self.max))
        elem.set("port", self.port)
        elem.set("clock", self.clock)
        return elem


TimingAnnotation = DelayConstant | TSetup | TClockToQ


@dataclass
class PbType:
    name: str
    num_pb: int = 1
    blif_model: Optional[str] = None
    input_ports: list[Port] = field(default_factory=list)
    output_ports: list[Port] = field(default_factory=list)
    clock_ports: list[Port] = field(default_factory=list)
    children: list[PbType] = field(default_factory=list)
    interconnect: list[Interconnect] = field(default_factory=list)
    modes: list[Mode] = field(default_factory=list)
    timing: list[TimingAnnotation] = field(default_factory=list)
    # using field(default_factory=list) everywhere to avoid the shared mutable default gotcha

    # Controls how this block's pins are placed on its physical tile sides.
    #   "spread"     -> VTR distributes pins around the tile (fine for interior blocks like CLB/DSP/BRAM)
    #   "all_sides"  -> every pin is replicated on all four sides; required for IO blocks, which sit on
    #                   every edge of the FPGA and must be able to reach the routing fabric from whichever
    #                   edge they land on. A "spread" IO tile breaks the routing resource graph because a
    #                   pin can end up on a side with no adjacent channel ("pin doesn't exist to be
    #                   connected to class 0").
    #   "custom"     -> caller supplies an explicit {side: [port_names]} mapping in pin_locations_custom.
    pin_placement: str = "spread"
    pin_locations_custom: dict[str, list[str]] = field(default_factory=dict)

    @classmethod
    def primitive(
        cls,
        name: str,
        blif_model: str,
        inputs: list[Port],
        outputs: list[Port],
        clocks: Optional[list[Port]] = None,
        num_pb: int = 1,
        timing: Optional[list[TimingAnnotation]] = None,
    ) -> PbType:
        return cls(
            name=name,
            num_pb=num_pb,
            blif_model=blif_model,
            input_ports=inputs,
            output_ports=outputs,
            clock_ports=clocks or [],
            timing=timing or [],
        )

    @classmethod
    def container(
        cls,
        name: str,
        inputs: list[Port],
        outputs: list[Port],
        children: list[PbType],
        interconnect: list[Interconnect],
        clocks: Optional[list[Port]] = None,
        num_pb: int = 1,
    ) -> PbType:
        return cls(
            name=name,
            num_pb=num_pb,
            input_ports=inputs,
            output_ports=outputs,
            clock_ports=clocks or [],
            children=children,
            interconnect=interconnect,
        )

    def _collect_primitives(self, acc: list[PbType]) -> None:
        # only grab custom models, VTR built-ins start with "."
        if self.blif_model and not self.blif_model.startswith("."):
            acc.append(self)
        for child in self.children:
            child._collect_primitives(acc)
        for mode in self.modes:
            for child in mode.children:
                child._collect_primitives(acc)

    def to_xml(self, is_top_level: bool = False) -> ET.Element:
        elem = ET.Element("pb_type")
        elem.set("name", self.name)
        if not is_top_level:
            elem.set("num_pb", str(self.num_pb))
        if self.blif_model:
            elem.set("blif_model", self.blif_model)
        for p in self.input_ports:
            elem.append(p.to_xml("input"))
        for p in self.output_ports:
            elem.append(p.to_xml("output"))
        for p in self.clock_ports:
            elem.append(p.to_xml("clock"))
        # timing annotations must come after the port declarations
        for t in self.timing:
            elem.append(t.to_xml())
        for child in self.children:
            elem.append(child.to_xml())
        if self.interconnect:
            ic_elem = ET.SubElement(elem, "interconnect")
            for ic in self.interconnect:
                ic_elem.append(ic.to_xml())
        for mode in self.modes:
            elem.append(mode.to_xml())
        return elem


@dataclass
class SingleLayout:
    type: str
    x: int
    y: int
    priority: int = 1

    def to_xml(self) -> ET.Element:
        elem = ET.Element("single")
        elem.set("type", self.type)
        elem.set("priority", str(self.priority))
        elem.set("x", str(self.x))
        elem.set("y", str(self.y))
        return elem


@dataclass
class ColLayout:
    type: str
    priority: int = 1
    startx: Optional[str] = None
    repeatx: Optional[str] = None
    starty: Optional[str] = None
    incry: Optional[str] = None

    def to_xml(self) -> ET.Element:
        elem = ET.Element("col")
        elem.set("type", self.type)
        elem.set("priority", str(self.priority))
        _set_attrs(elem, self, "startx", "repeatx", "starty", "incry")
        return elem


@dataclass
class RowLayout:
    type: str
    priority: int = 1
    starty: Optional[str] = None
    repeaty: Optional[str] = None
    startx: Optional[str] = None
    incrx: Optional[str] = None

    def to_xml(self) -> ET.Element:
        elem = ET.Element("row")
        elem.set("type", self.type)
        elem.set("priority", str(self.priority))
        _set_attrs(elem, self, "starty", "repeaty", "startx", "incrx")
        return elem


@dataclass
class FillLayout:
    type: str
    priority: int = 1

    def to_xml(self) -> ET.Element:
        elem = ET.Element("fill")
        elem.set("type", self.type)
        elem.set("priority", str(self.priority))
        return elem


@dataclass
class PerimeterLayout:
    type: str
    priority: int = 1

    def to_xml(self) -> ET.Element:
        elem = ET.Element("perimeter")
        elem.set("type", self.type)
        elem.set("priority", str(self.priority))
        return elem


@dataclass
class RegionLayout:
    type: str
    priority: int = 1
    startx: Optional[str] = None
    endx: Optional[str] = None
    repeatx: Optional[str] = None
    incrx: Optional[str] = None
    starty: Optional[str] = None
    endy: Optional[str] = None
    repeaty: Optional[str] = None
    incry: Optional[str] = None

    def to_xml(self) -> ET.Element:
        elem = ET.Element("region")
        elem.set("type", self.type)
        elem.set("priority", str(self.priority))
        _set_attrs(elem, self, "startx", "endx", "repeatx", "incrx",
                   "starty", "endy", "repeaty", "incry")
        return elem


@dataclass
class CornersLayout:
    type: str
    priority: int = 1

    def to_xml(self) -> ET.Element:
        elem = ET.Element("corners")
        elem.set("type", self.type)
        elem.set("priority", str(self.priority))
        return elem


LayerDirective = SingleLayout | ColLayout | RowLayout | FillLayout | PerimeterLayout | RegionLayout | CornersLayout


def _grid_to_singles(grid: list[list[list[str]]], priority: int = 10) -> list[tuple[int, SingleLayout]]:
    directives: list[tuple[int, SingleLayout]] = []
    for layer_idx, layer in enumerate(grid):
        for row_idx, row in enumerate(layer):
            for col_idx, block_type in enumerate(row):
                if block_type:
                    directives.append((layer_idx, SingleLayout(
                        type=block_type,
                        x=col_idx,
                        y=row_idx,
                        priority=priority,
                    )))
    return directives


@dataclass
class FixedLayout:
    name: str
    width: int
    height: int
    _directives: list[tuple[int, LayerDirective]] = field(default_factory=list)

    def add_directive(self, directive: LayerDirective, layer: int = 0) -> FixedLayout:
        self._directives.append((layer, directive))
        return self

    def from_grid(self, grid: list[list[list[str]]], priority: int = 10) -> FixedLayout:
        self._directives.extend(_grid_to_singles(grid, priority))
        return self

    def to_xml(self) -> ET.Element:
        elem = ET.Element("fixed_layout")
        elem.set("name", self.name)
        elem.set("width", str(self.width))
        elem.set("height", str(self.height))

        layers: dict[int, list[LayerDirective]] = {}
        for layer_num, directive in self._directives:
            layers.setdefault(layer_num, []).append(directive)

        for die_num in sorted(layers):
            layer_elem = ET.SubElement(elem, "layer")
            layer_elem.set("die", str(die_num))
            for d in layers[die_num]:
                layer_elem.append(d.to_xml())

        return elem


@dataclass
class AutoLayout:
    aspect_ratio: float = 1.0
    directives: list[LayerDirective] = field(default_factory=list)

    def add_directive(self, directive: LayerDirective) -> AutoLayout:
        self.directives.append(directive)
        return self

    def to_xml(self) -> ET.Element:
        elem = ET.Element("auto_layout")
        elem.set("aspect_ratio", str(self.aspect_ratio))
        for d in self.directives:
            elem.append(d.to_xml())
        return elem


@dataclass
class Layout:
    auto: Optional[AutoLayout] = None
    fixed: Optional[FixedLayout] = None

    def to_xml(self) -> ET.Element:
        elem = ET.Element("layout")
        if self.auto:
            elem.append(self.auto.to_xml())
        if self.fixed:
            elem.append(self.fixed.to_xml())
        return elem


@dataclass
class Sizing:
    R_minW_nmos: float = 6065.520020
    R_minW_pmos: float = 18138.500000

    def to_xml(self) -> ET.Element:
        elem = ET.Element("sizing")
        elem.set("R_minW_nmos", str(self.R_minW_nmos))
        elem.set("R_minW_pmos", str(self.R_minW_pmos))
        return elem


@dataclass
class SwitchBlock:
    type: str = "wilton"
    fs: int = 3

    def to_xml(self) -> ET.Element:
        elem = ET.Element("switch_block")
        elem.set("type", self.type)
        elem.set("fs", str(self.fs))
        return elem


@dataclass
class ChanWidthDistr:
    x_distr: str = "uniform"
    x_peak: float = 1.0
    y_distr: str = "uniform"
    y_peak: float = 1.0

    def to_xml(self) -> ET.Element:
        elem = ET.Element("chan_width_distr")
        x = ET.SubElement(elem, "x")
        x.set("distr", self.x_distr)
        x.set("peak", str(self.x_peak))
        y = ET.SubElement(elem, "y")
        y.set("distr", self.y_distr)
        y.set("peak", str(self.y_peak))
        return elem


@dataclass
class Device:
    sizing: Sizing = field(default_factory=Sizing)
    grid_logic_tile_area: float = 0.0
    chan_width_distr: ChanWidthDistr = field(default_factory=ChanWidthDistr)
    switch_block: SwitchBlock = field(default_factory=SwitchBlock)
    connection_block_input_switch_name: Optional[str] = None
    default_fc_in_type: str = "frac"
    default_fc_in_val: float = 0.15
    default_fc_out_type: str = "frac"
    default_fc_out_val: float = 0.10

    def to_xml(self) -> ET.Element:
        elem = ET.Element("device")
        elem.append(self.sizing.to_xml())
        area = ET.SubElement(elem, "area")
        area.set("grid_logic_tile_area", str(self.grid_logic_tile_area))
        elem.append(self.chan_width_distr.to_xml())
        elem.append(self.switch_block.to_xml())
        if self.connection_block_input_switch_name:
            cb = ET.SubElement(elem, "connection_block")
            cb.set("input_switch_name", self.connection_block_input_switch_name)
        fc = ET.SubElement(elem, "default_fc")
        fc.set("in_type", self.default_fc_in_type)
        fc.set("in_val", str(self.default_fc_in_val))
        fc.set("out_type", self.default_fc_out_type)
        fc.set("out_val", str(self.default_fc_out_val))
        return elem


@dataclass
class Switch:
    name: str
    type: str
    R: float = 0.0
    Cin: float = 0.0
    Cout: float = 0.0
    Tdel: Optional[float] = None
    buf_size: Optional[str] = None

    def to_xml(self) -> ET.Element:
        elem = ET.Element("switch")
        elem.set("type", self.type)
        elem.set("name", self.name)
        elem.set("R", str(self.R))
        elem.set("Cin", str(self.Cin))
        elem.set("Cout", str(self.Cout))
        if self.Tdel is not None:
            elem.set("Tdel", str(self.Tdel))
        if self.buf_size is not None:
            elem.set("buf_size", str(self.buf_size))
        return elem


@dataclass
class Segment:
    name: str
    length: int
    freq: float
    Rmetal: float
    Cmetal: float
    type: str = "unidir"
    sb_pattern: Optional[str] = None
    cb_pattern: Optional[str] = None
    mux_name: Optional[str] = None

    def to_xml(self) -> ET.Element:
        elem = ET.Element("segment")
        elem.set("name", self.name)
        elem.set("length", str(self.length))
        elem.set("freq", str(self.freq))
        elem.set("Rmetal", str(self.Rmetal))
        elem.set("Cmetal", str(self.Cmetal))
        elem.set("type", self.type)
        sb = ET.SubElement(elem, "sb")
        sb.set("type", "pattern")
        sb.text = self.sb_pattern if self.sb_pattern is not None else " ".join(["1"] * (self.length + 1))
        cb = ET.SubElement(elem, "cb")
        cb.set("type", "pattern")
        cb.text = self.cb_pattern if self.cb_pattern is not None else " ".join(["1"] * self.length)
        if self.mux_name:
            mux = ET.SubElement(elem, "mux")
            mux.set("name", self.mux_name)
        return elem


@dataclass
class Architecture:
    layout: Layout = field(default_factory=Layout)
    device: Device = field(default_factory=Device)
    switch_list: list[Switch] = field(default_factory=list)
    segment_list: list[Segment] = field(default_factory=list)
    complexblocklist: list[PbType] = field(default_factory=list)

    # these exist so you can override the inferred output if you really need to,
    # but in most cases you should just let the inference handle it
    _tiles_override: Optional[list] = field(default=None, repr=False)
    _models_override: Optional[list] = field(default=None, repr=False)

    def _infer_models(self) -> list[ET.Element]:
        seen: set[str] = set()  # dedup in case the same custom primitive shows up in multiple blocks
        elems: list[ET.Element] = []
        primitives: list[PbType] = []
        for pb in self.complexblocklist:
            pb._collect_primitives(primitives)
        for prim in primitives:
            if prim.blif_model and prim.blif_model not in seen:
                seen.add(prim.blif_model)
                m = ET.Element("model")
                m.set("name", prim.blif_model)
                if prim.input_ports:
                    inp = ET.SubElement(m, "input_ports")
                    for p in prim.input_ports:
                        inp.append(p.to_xml("port"))
                if prim.output_ports:
                    out = ET.SubElement(m, "output_ports")
                    for p in prim.output_ports:
                        out.append(p.to_xml("port"))
                elems.append(m)
        return elems

    def _infer_tiles(self) -> list[ET.Element]:
        elems: list[ET.Element] = []
        for pb in self.complexblocklist:
            t = ET.Element("tile")
            t.set("name", pb.name)
            t.set("width", "1")
            t.set("height", "1")
            sub = ET.SubElement(t, "sub_tile")
            sub.set("name", pb.name)
            sub.set("capacity", str(pb.num_pb))
            for p in pb.input_ports:
                sub.append(p.to_xml("input"))
            for p in pb.output_ports:
                sub.append(p.to_xml("output"))
            for p in pb.clock_ports:
                sub.append(p.to_xml("clock"))
            eq = ET.SubElement(sub, "equivalent_sites")
            site = ET.SubElement(eq, "site")
            site.set("pb_type", pb.name)
            site.set("pin_mapping", "direct")
            fc = ET.SubElement(sub, "fc")
            fc.set("in_type", "frac")
            fc.set("in_val", "0.15")
            fc.set("out_type", "frac")
            fc.set("out_val", "0.10")
            self._emit_pin_locations(sub, pb)
            elems.append(t)
        return elems

    @staticmethod
    def _emit_pin_locations(sub: ET.Element, pb: PbType) -> None:
        # NOTE: the VTR parser looks for the element named "pinlocations" (one word).
        # Emitting "pin_locations" makes VTR silently ignore it (it's an optional child)
        # and fall back to default placement, which breaks IO routing.
        pinloc = ET.SubElement(sub, "pinlocations")

        if pb.pin_placement == "spread":
            pinloc.set("pattern", "spread")
            return

        pinloc.set("pattern", "custom")
        sides = ["left", "top", "right", "bottom"]

        if pb.pin_placement == "all_sides":
            # Replicate every pin (sub_tile-qualified) on all four sides. VTR addresses
            # pins as <sub_tile_name>.<port_name>; bus ports are placed whole.
            all_ports = pb.input_ports + pb.output_ports + pb.clock_ports
            pin_refs = [f"{sub.get('name')}.{p.name}" for p in all_ports]
            text = " ".join(pin_refs)
            for side in sides:
                loc = ET.SubElement(pinloc, "loc")
                loc.set("side", side)
                loc.text = text
            return

        if pb.pin_placement == "custom":
            for side, port_names in pb.pin_locations_custom.items():
                loc = ET.SubElement(pinloc, "loc")
                loc.set("side", side)
                loc.text = " ".join(f"{sub.get('name')}.{n}" for n in port_names)
            return

        raise ValueError(
            f"Unknown pin_placement '{pb.pin_placement}' on pb_type '{pb.name}' "
            f"(expected 'spread', 'all_sides', or 'custom')"
        )

    def to_xml(self) -> str:
        root = ET.Element("architecture")

        model_elems = self._models_override if self._models_override is not None else self._infer_models()
        models_container = ET.SubElement(root, "models")
        for m in model_elems:
            models_container.append(m)

        tile_elems = self._tiles_override if self._tiles_override is not None else self._infer_tiles()
        if tile_elems:
            tiles_container = ET.SubElement(root, "tiles")
            for t in tile_elems:
                tiles_container.append(t)

        root.append(self.layout.to_xml())
        root.append(self.device.to_xml())

        if self.switch_list:
            sl = ET.SubElement(root, "switchlist")
            for s in self.switch_list:
                sl.append(s.to_xml())

        if self.segment_list:
            segl = ET.SubElement(root, "segmentlist")
            for seg in self.segment_list:
                segl.append(seg.to_xml())

        if self.complexblocklist:
            cbl = ET.SubElement(root, "complexblocklist")
            for pb in self.complexblocklist:
                cbl.append(pb.to_xml(is_top_level=True))

        ET.indent(root, space="  ")
        return ET.tostring(root, encoding="unicode", xml_declaration=False)


@dataclass
class GridOptions:
    width_3d: int = 10
    height_3d: int = 10
    width_2d: int = 15
    height_2d: int = 15
    channel_width: int = 50


@dataclass
class ArchitectureEntry:
    type: str = "3d_sb"
    arch_file: Optional[str] = None


@dataclass
class BenchmarkOptions:
    directory: str = "{lazagna_root}/benchmarks/and2_or2"
    is_verilog: bool = False


@dataclass
class PlacementOptions:
    algorithm: list[str] = field(default_factory=lambda: ["cube_bb"])


@dataclass
class SeedOptions:
    mode: str = "fixed"   # "fixed" | "random" | "list"
    value: Union[int, list[int]] = 1   # list mode: the exact seeds, e.g. [1, 2, 3]

    @classmethod
    def from_list(cls, seeds) -> "SeedOptions":
        seeds = [int(s) for s in seeds]
        return cls(mode="fixed", value=seeds[0]) if len(seeds) == 1 else cls(mode="list", value=seeds)

    def count(self) -> int:
        return len(self.value) if self.mode == "list" else (int(self.value) if self.mode == "random" else 1)


@dataclass
class SwitchBlock3DOptions:
    connectivity: list[float] = field(default_factory=lambda: [1.0])
    connection_type: list[str] = field(default_factory=lambda: ["subset"])
    switch_name: str = "3D_SB_switch"
    segment_name: str = "3D_SB_connection"
    input_pattern: list[int] = field(default_factory=list)
    output_pattern: list[int] = field(default_factory=list)
    location_pattern: list[str] = field(default_factory=lambda: ["repeated_interval"])
    grid_csv_path: str = ""


@dataclass
class InterlayerDelayOptions:
    vertical_connectivity: int = 1
    delay_ratio: list[float] = field(default_factory=lambda: [0.739])
    base_delay_switch: str = "L4_driver"
    update_arch_delay: bool = True
    switch_pairs: dict = field(default_factory=lambda: {
        "L4_driver": "L4_inter_layer_driver",
        "L16_driver": "L16_inter_layer_driver",
        "ipin_cblock": "ipin_inter_layer_cblock",
    })


@dataclass
class AdvancedOptions:
    additional_vpr_options: str = ""
    # Stop after VPR: skips OpenFPGA fabric/Verilog/bitstream generation, which is most of
    # the runtime and contributes nothing to CPD/WL.
    vpr_only: bool = False


@dataclass
class ExperimentOptions:
    experiment_name: str = "default_experiment"
    grid: GridOptions = field(default_factory=GridOptions)
    architectures: list[ArchitectureEntry] = field(default_factory=lambda: [ArchitectureEntry()])
    benchmarks: BenchmarkOptions = field(default_factory=BenchmarkOptions)
    placement: PlacementOptions = field(default_factory=PlacementOptions)
    seeds: SeedOptions = field(default_factory=SeedOptions)
    switch_block_3d: SwitchBlock3DOptions = field(default_factory=SwitchBlock3DOptions)
    interlayer_delay: InterlayerDelayOptions = field(default_factory=InterlayerDelayOptions)
    advanced: AdvancedOptions = field(default_factory=AdvancedOptions)

    def to_dict(self) -> dict:
        """Emit the NESTED v2 YAML schema consumed by the current lab flow
        (lazagna/main.py -> yaml_file_processing_v2.get_run_params_from_yaml_v2).
        The schema is documented in setup_files/defaults.yaml. Only
        experiment_name is strictly required; everything else deep-merges over
        defaults.yaml, but we emit a full config so runs are self-contained.

        NOTE: the previous FLAT schema (width/type_sb/percent_connectivity/...)
        was for the old yaml_file_processing.py. The lab moved main.py to v2
        (commit "Updated YAML configuration"), which requires this nested form
        and rejects the flat one with "'experiment_name' is required"."""
        sb = self.switch_block_3d
        il = self.interlayer_delay

        architectures = []
        for a in self.architectures:
            entry = {"type": a.type}
            if a.arch_file:
                entry["arch_file"] = a.arch_file
            architectures.append(entry)

        sb_block: dict = {
            "connectivity": sb.connectivity,
            "connection_type": sb.connection_type,
            "switch_name": sb.switch_name,
            "segment_name": sb.segment_name,
            "location_pattern": sb.location_pattern,
        }
        # Emit explicit patterns only when set; empty is v2's default (proven by
        # the lab's simple_test.yaml, which omits them).
        if sb.input_pattern:
            sb_block["input_pattern"] = sb.input_pattern
        if sb.output_pattern:
            sb_block["output_pattern"] = sb.output_pattern
        if sb.grid_csv_path:
            sb_block["grid_csv_path"] = sb.grid_csv_path

        return {
            "experiment_name": self.experiment_name,
            "grid": {
                "width_3d": self.grid.width_3d,
                "height_3d": self.grid.height_3d,
                "width_2d": self.grid.width_2d,
                "height_2d": self.grid.height_2d,
                "channel_width": self.grid.channel_width,
            },
            "architectures": architectures,
            "benchmarks": {
                "directory": self.benchmarks.directory,
                "is_verilog": self.benchmarks.is_verilog,
            },
            "placement": {
                "algorithm": self.placement.algorithm,
            },
            "seeds": {
                "mode": self.seeds.mode,
                "value": self.seeds.value,
            },
            "switch_block_3d": sb_block,
            "interlayer_delay": {
                "vertical_connectivity": il.vertical_connectivity,
                "delay_ratio": il.delay_ratio,
                "base_delay_switch": il.base_delay_switch,
                "update_arch_delay": il.update_arch_delay,
                "switch_pairs": il.switch_pairs,
            },
            "advanced": {
                "additional_vpr_options": self.advanced.additional_vpr_options,
                "vpr_only": self.advanced.vpr_only,
            },
        }


def run_lazagna(arch: Architecture, opts: ExperimentOptions, lazagna_root: Optional[str] = None,
                timeout_s: Optional[int] = None, num_workers: Optional[int] = None) -> dict:
    """num_workers: parallel flow runs inside main.py (-j). Defaults to one per seed, since
    each seed is an independent run and they otherwise execute one after another."""
    import os
    import signal
    import subprocess
    import tempfile
    import hashlib
    import yaml

    root = lazagna_root or os.environ.get("LAZAGNA_ROOT", ".")

    with tempfile.TemporaryDirectory() as tmp:
        arch_xml = arch if isinstance(arch, str) else arch.to_xml()
        arch_hash = hashlib.sha1(arch_xml.encode("utf-8")).hexdigest()[:12]
        arch_path = os.path.join(tmp, "arch_" + arch_hash + ".xml")
        yaml_path = os.path.join(tmp, "experiment.yaml")

        with open(arch_path, "w") as f:
            f.write(arch_xml)

        config = opts.to_dict()
        # v2 schema: the generated arch lives inside architectures[0].arch_file
        # (there is no top-level arch_file). run_lazagna renders exactly one arch.
        if config.get("architectures"):
            config["architectures"][0]["arch_file"] = arch_path
        else:
            config["architectures"] = [{"type": "3d_sb", "arch_file": arch_path}]

        with open(yaml_path, "w") as f:
            yaml.dump(config, f, default_flow_style=False)

        # Own process group so a timeout kills yosys/VPR grandchildren too, not just main.py
        # (plain subprocess.run(timeout=...) leaves them orphaned and burning CPU).
        proc = subprocess.Popen(
            ["python3", os.path.join(root, "lazagna", "main.py"), "-f", yaml_path,
             "-j", str(num_workers or max(1, opts.seeds.count()))],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            start_new_session=True,
        )
        try:
            out, err = proc.communicate(timeout=timeout_s)
            rc = proc.returncode
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            out, err = proc.communicate()
            rc = -9
            err = (err or "") + f"\n[run_lazagna] TIMEOUT after {timeout_s}s, process group killed"

        return {
            "returncode": rc,
            "stdout": out,
            "stderr": err,
        }


if __name__ == "__main__":
    lut6 = PbType.primitive(
        name="lut6",
        blif_model=".names",
        inputs=[Port("in", num_pins=6)],
        outputs=[Port("out", num_pins=1)],
        timing=[DelayConstant(in_port="lut6.in", out_port="lut6.out", max=261e-12)],
    )

    ff = PbType.primitive(
        name="ff",
        blif_model=".latch",
        inputs=[Port("D", num_pins=1)],
        outputs=[Port("Q", num_pins=1)],
        clocks=[Port("clk", num_pins=1)],
        timing=[
            TSetup(port="ff.D", clock="clk", value=66e-12),
            TClockToQ(port="ff.Q", clock="clk", max=124e-12),
        ],
    )

    adder = PbType.primitive(
        name="adder",
        blif_model="adder",  # custom, so it'll show up in <models>
        inputs=[Port("a"), Port("b"), Port("cin")],
        outputs=[Port("cout"), Port("sumout")],
    )

    clb = PbType.container(
        name="clb",
        inputs=[Port("I", num_pins=10)],
        outputs=[Port("O", num_pins=4)],
        clocks=[Port("clk")],
        children=[lut6, ff],
        interconnect=[
            Direct("lut_in", input="clb.I[0:5]", output="lut6.in[0:5]"),
            Direct("ff_in",  input="lut6.out[0]", output="ff.D[0]"),
            Mux("clb_out",   input="lut6.out[0] ff.Q[0]", output="clb.O[0]"),
        ],
    )

    inpad = PbType.primitive(
        name="inpad",
        blif_model=".input",
        inputs=[],
        outputs=[Port("inpad")],
    )

    outpad = PbType.primitive(
        name="outpad",
        blif_model=".output",
        inputs=[Port("outpad")],
        outputs=[],
    )

    io = PbType(
        name="io",
        num_pb=1,
        input_ports=[Port("outpad")],
        output_ports=[Port("inpad")],
        pin_placement="all_sides",  # IO sits on every edge; pins must reach the fabric from any side
        modes=[
            Mode(
                name="inpad",
                children=[inpad],
                interconnect=[Direct("io_inpad", input="inpad.inpad", output="io.inpad")],
            ),
            Mode(
                name="outpad",
                children=[outpad],
                interconnect=[Direct("io_outpad", input="io.outpad", output="outpad.outpad")],
            ),
        ],
    )

    fixed = (
        FixedLayout(name="main", width=30, height=30)
        .add_directive(PerimeterLayout(type="io", priority=10))
        .add_directive(FillLayout(type="clb", priority=1))
    )

    arch = Architecture(
        layout=Layout(fixed=fixed),
        device=Device(
            sizing=Sizing(R_minW_nmos=6065.52, R_minW_pmos=18138.50),
            switch_block=SwitchBlock(type="wilton", fs=3),
            connection_block_input_switch_name="ipin_cbar",
        ),
        switch_list=[
            Switch("ipin_cbar", "mux", R=551.0, Cin=7.7e-16, Cout=0.0, Tdel=5.8e-11),
            Switch("buffer", "buffer", R=0.0, Cin=0.0, Cout=0.0, Tdel=5.8e-11),
        ],
        segment_list=[
            Segment("L4", length=4, freq=1.0, Rmetal=101.0, Cmetal=22.5e-15, mux_name="ipin_cbar"),
        ],
        complexblocklist=[io, clb],
    )

    print(arch.to_xml())
