"""Thin wrappers over flashkit ops that mutate ``StudioState``.

Each entry point catches exceptions and surfaces them through the
status bar so panel code never sees a raised exception.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from flashkit.abc.disasm import decode_instructions, resolve_instructions
from flashkit.decompile import decompile_class, list_classes
from flashkit.workspace.resource import load_swf, load_swz

from .state import ClassEntry, LoadedResource, StudioState

log = logging.getLogger(__name__)


# ── SWF loading ──────────────────────────────────────────────────────────


def open_swf(state: StudioState, path: str | Path) -> bool:
    p = Path(path).resolve()
    if not p.exists():
        state.set_status(f"File not found: {p}", error=True)
        return False

    for i, r in enumerate(state.resources):
        if r.path == p:
            state.set_active_resource(i)
            state.set_status(f"Already open: {p.name}")
            return True

    state.set_status(f"Loading {p.name}…", busy=True)
    try:
        t0 = time.perf_counter()
        resource = (load_swz(p) if p.suffix.lower() == ".swz"
                    else load_swf(p))
        elapsed = time.perf_counter() - t0
    except Exception as exc:  # noqa: BLE001
        log.exception("open_swf failed")
        state.set_status(f"Failed to open {p.name}: {exc}", error=True)
        return False

    classes = _list_classes_flat(resource.abc_blocks)
    state.add_resource(LoadedResource(
        path=p, resource=resource, classes=classes,
    ))
    state.set_status(
        f"Opened {p.name} — {len(classes)} classes, "
        f"{len(resource.abc_blocks)} ABC blocks, {elapsed:.2f}s",
    )
    return True


def _list_classes_flat(abc_blocks) -> list[ClassEntry]:
    out: list[ClassEntry] = []
    for abc_idx, abc in enumerate(abc_blocks):
        for info in list_classes(abc):
            out.append(ClassEntry(
                abc_index=abc_idx,
                class_index=info["index"],
                name=info["name"],
                package=info.get("package", "") or "",
                full_name=info["full_name"],
                is_interface=info.get("is_interface", False),
                trait_count=info.get("trait_count", 0),
            ))
    out.sort(key=lambda c: (c.package, c.name))
    return out


# ── content generation ──────────────────────────────────────────────────


_CACHE: dict[tuple[int, str, str], str] = {}


def render_view(state: StudioState, view_key: str) -> str:
    r = state.active_resource()
    cls = state.active_class()
    abc = state.active_abc()
    if r is None or cls is None or abc is None:
        return ""

    key = (state.active_resource_index or 0, cls.full_name, view_key)
    if key in _CACHE:
        return _CACHE[key]

    try:
        if view_key == "source":
            t0 = time.perf_counter()
            text = decompile_class(abc, name=cls.full_name)
            state.set_status(f"Decompiled {cls.full_name} in {(time.perf_counter()-t0)*1000:.1f}ms")
        elif view_key == "disasm":
            text = _render_disasm(abc, cls)
        elif view_key == "traits":
            text = _render_traits(abc, cls)
        elif view_key == "strings":
            text = _render_strings(abc)
        elif view_key == "multinames":
            text = _render_multinames(abc)
        else:
            text = f"// unknown view: {view_key}"
    except Exception as exc:  # noqa: BLE001
        log.exception("render_view(%s) failed", view_key)
        text = f"// error: {exc}"
        state.set_status(f"{view_key} error: {exc}", error=True)
    _CACHE[key] = text
    return text


def _render_disasm(abc, cls: ClassEntry) -> str:
    instance = abc.instances[cls.class_index]
    class_meta = abc.classes[cls.class_index]
    lines: list[str] = []
    lines.append(f"// Class: {cls.full_name}")
    lines.append(f"// Instance traits: {len(instance.traits)}  "
                 f"Class traits: {len(class_meta.traits)}")
    lines.append("")

    method_refs: list[tuple[str, int]] = []
    method_refs.append((f"{cls.name} constructor", instance.iinit))
    method_refs.append((f"{cls.name} static init", class_meta.cinit))
    for t in list(instance.traits) + list(class_meta.traits):
        mi = getattr(t, "method_idx", None) or getattr(t, "disp_id", 0)
        if mi and 0 <= mi < len(abc.methods):
            try:
                name = abc.multiname_name(t.name)
            except Exception:
                name = f"trait[{t.name}]"
            method_refs.append((name, mi))

    for name, mi in method_refs:
        if not (0 <= mi < len(abc.methods)):
            continue
        body = None
        for b in abc.method_bodies:
            if getattr(b, "method", -1) == mi:
                body = b
                break
        if body is None:
            continue
        lines.append(f"// ── {name}  (method #{mi}) ──")
        try:
            instrs = decode_instructions(body.code)
            resolved = resolve_instructions(abc, instrs)
            for r in resolved:
                ops = ", ".join(r.operands) if r.operands else ""
                lines.append(f"  {r.offset:04X}  {r.mnemonic:<16}  {ops}")
        except Exception as exc:  # noqa: BLE001
            lines.append(f"  // decode error: {exc}")
        lines.append("")

    return "\n".join(lines)


def _render_strings(abc) -> str:
    lines = [f"// String pool  ({len(abc.string_pool)} entries)"]
    for i, s in enumerate(abc.string_pool):
        preview = (s[:200] + "…") if len(s) > 200 else s
        preview = (preview.replace("\n", "\\n")
                   .replace("\r", "\\r")
                   .replace("\t", "\\t"))
        lines.append(f'  [{i:4d}]  "{preview}"')
    return "\n".join(lines)


def _render_multinames(abc) -> str:
    from flashkit.info.member_info import resolve_multiname
    lines = [f"// Multiname pool  ({len(abc.multiname_pool)} entries)"]
    for i in range(len(abc.multiname_pool)):
        try:
            name = resolve_multiname(abc, i)
        except Exception:
            name = "<error>"
        lines.append(f"  [{i:4d}]  {name}")
    return "\n".join(lines)


def _render_traits(abc, cls: ClassEntry) -> str:
    from flashkit.abc.constants import (
        TRAIT_SLOT, TRAIT_METHOD, TRAIT_GETTER, TRAIT_SETTER,
        TRAIT_CLASS, TRAIT_FUNCTION, TRAIT_CONST,
    )
    kinds = {
        TRAIT_SLOT: "slot", TRAIT_METHOD: "method",
        TRAIT_GETTER: "getter", TRAIT_SETTER: "setter",
        TRAIT_CLASS: "class", TRAIT_FUNCTION: "function",
        TRAIT_CONST: "const",
    }
    instance = abc.instances[cls.class_index]
    class_meta = abc.classes[cls.class_index]
    lines: list[str] = [f"// {cls.full_name}", ""]

    def dump(header, traits):
        lines.append(f"// {header}  ({len(traits)} traits)")
        for t in traits:
            try:
                name = abc.multiname_name(t.name)
            except Exception:
                name = f"trait[{t.name}]"
            type_idx = getattr(t, "type_name", 0)
            try:
                tn = abc.multiname_name(type_idx) if type_idx else "*"
            except Exception:
                tn = "*"
            kind = kinds.get(t.kind, f"kind#{t.kind}")
            lines.append(f"  {kind:<9}  {name:<40}  : {tn}")
        lines.append("")

    dump("Instance traits", instance.traits)
    dump("Class traits", class_meta.traits)
    return "\n".join(lines)


# ── export ───────────────────────────────────────────────────────────────


def export_all(state: StudioState, out_dir: str | Path) -> int:
    r = state.active_resource()
    if r is None:
        state.set_status("No SWF selected to export", error=True)
        return 0
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written = 0
    t0 = time.perf_counter()
    for cls in r.classes:
        abc = r.resource.abc_blocks[cls.abc_index]
        try:
            src = decompile_class(abc, name=cls.full_name)
        except Exception as exc:  # noqa: BLE001
            log.warning("export_all: %s failed: %s", cls.full_name, exc)
            continue
        rel_path = cls.full_name.replace(":", ".").replace(".", "/") + ".as"
        dest = out / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(src, encoding="utf-8")
        written += 1
    state.set_status(
        f"Exported {written}/{len(r.classes)} classes to {out}  "
        f"({time.perf_counter()-t0:.2f}s)",
    )
    return written


def export_selection(state: StudioState, out_dir: str | Path) -> int:
    r = state.active_resource()
    cls = state.active_class()
    abc = state.active_abc()
    if r is None or cls is None or abc is None:
        state.set_status("No class selected to export", error=True)
        return 0
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    try:
        src = decompile_class(abc, name=cls.full_name)
    except Exception as exc:  # noqa: BLE001
        state.set_status(f"Export failed: {exc}", error=True)
        return 0
    rel_path = cls.full_name.replace(":", ".").replace(".", "/") + ".as"
    dest = out / rel_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(src, encoding="utf-8")
    state.set_status(f"Exported {cls.full_name} to {dest}")
    return 1
