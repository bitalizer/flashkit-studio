"""Thin wrappers over flashkit ops that mutate ``StudioState``.

Each entry point catches exceptions and surfaces them through the
status bar so panel code never sees a raised exception.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from flashkit.abc.disasm import decode_instructions, resolve_instructions
from flashkit.decompile import decompile_class, list_classes
from flashkit.workspace.workspace import Workspace

from . import settings
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
        # Route through Workspace so reference / inheritance / field-access
        # indexes are available to every panel (references, hierarchy,
        # callers) without re-scanning bytecode per query.
        workspace = Workspace()
        resource = (workspace.load_swz(p) if p.suffix.lower() == ".swz"
                    else workspace.load_swf(p))
        elapsed = time.perf_counter() - t0
    except Exception as exc:  # noqa: BLE001
        log.exception("open_swf failed")
        state.set_status(f"Failed to open {p.name}: {exc}", error=True)
        return False

    classes = _list_classes_flat(resource.abc_blocks)
    state.add_resource(LoadedResource(
        path=p, resource=resource, workspace=workspace, classes=classes,
    ))
    settings.push_recent_swf(p)
    state.recent_changed.emit()
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

    # For pool views (strings, multinames) the filter is part of the
    # key so we don't return a stale unfiltered result after the user
    # types into the filter input.
    filter_key = (state.pool_filter
                  if view_key in ("strings", "multinames") else "")
    key = (state.active_resource_index or 0,
           cls.full_name, view_key, filter_key)
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
            text = _render_strings(abc, state.pool_filter)
        elif view_key == "multinames":
            text = _render_multinames(abc, state.pool_filter)
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


def _render_strings(abc, pool_filter: str = "") -> str:
    q = pool_filter.lower()
    matched = 0
    lines = [""]  # header goes after counting so it can show N/total
    for i, s in enumerate(abc.string_pool):
        if q and q not in s.lower():
            continue
        matched += 1
        preview = (s[:200] + "…") if len(s) > 200 else s
        preview = (preview.replace("\n", "\\n")
                   .replace("\r", "\\r")
                   .replace("\t", "\\t"))
        lines.append(f'  [{i:4d}]  "{preview}"')
    total = len(abc.string_pool)
    if q:
        lines[0] = f"// String pool  ({matched} of {total} match '{pool_filter}')"
    else:
        lines[0] = f"// String pool  ({total} entries)"
    return "\n".join(lines)


def _render_multinames(abc, pool_filter: str = "") -> str:
    from flashkit.info.member_info import resolve_multiname
    q = pool_filter.lower()
    matched = 0
    lines = [""]
    for i in range(len(abc.multiname_pool)):
        try:
            name = resolve_multiname(abc, i)
        except Exception:
            name = "<error>"
        if q and q not in name.lower():
            continue
        matched += 1
        lines.append(f"  [{i:4d}]  {name}")
    total = len(abc.multiname_pool)
    if q:
        lines[0] = f"// Multiname pool  ({matched} of {total} match '{pool_filter}')"
    else:
        lines[0] = f"// Multiname pool  ({total} entries)"
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


# ── outline / symbol index ──────────────────────────────────────────────


@dataclass(frozen=True)
class Symbol:
    """One entry in the global symbol palette.

    ``kind`` is one of ``"class"``, ``"method"``, ``"field"`` — enough
    for the palette to prefix rows with a glyph and for the jump
    handler to know whether to scroll to a member after opening the
    class. ``member`` is the bare name for methods/fields, ``None``
    for classes.
    """
    kind: str
    class_full_name: str
    class_short_name: str
    package: str
    member: Optional[str]
    label: str


@dataclass(frozen=True)
class OutlineEntry:
    """One row in the outline pane for the current class."""
    kind: str          # "field" | "method" | "getter" | "setter"
    name: str
    type_name: str     # return type for methods, field type for fields
    is_static: bool


def list_members(resource, full_name: str) -> list[OutlineEntry]:
    """Return outline rows for the class with qualified name ``full_name``
    on ``resource``. Looks up the already-resolved ``ClassInfo`` built
    at load time. Empty list when the name doesn't match any class."""
    for ci in resource.classes:
        if ci.qualified_name != full_name:
            continue
        out: list[OutlineEntry] = []
        for f in ci.all_fields:
            out.append(OutlineEntry(
                kind="field", name=f.name, type_name=f.type_name,
                is_static=f.is_static,
            ))
        for m in ci.all_methods:
            kind = ("getter" if m.is_getter
                    else "setter" if m.is_setter
                    else "method")
            out.append(OutlineEntry(
                kind=kind, name=m.name, type_name=m.return_type,
                is_static=m.is_static,
            ))
        return out
    return []


def build_symbol_index(state: StudioState) -> list[Symbol]:
    """Collect every class, method, and field in the active resource
    into a flat list suitable for fuzzy matching in the palette.

    Classes are expanded to include their members so typing
    ``onTick`` finds ``SomeClass.onTick`` even without knowing which
    class owns it. The list is rebuilt on demand — SWFs with tens of
    thousands of symbols still take under a second on a modern
    machine.
    """
    r = state.active_resource()
    if r is None:
        return []
    out: list[Symbol] = []
    for ci in r.resource.classes:
        short = ci.name
        pkg = ci.package
        full = ci.qualified_name
        out.append(Symbol(
            kind="class", class_full_name=full, class_short_name=short,
            package=pkg, member=None, label=full,
        ))
        for f in ci.all_fields:
            out.append(Symbol(
                kind="field", class_full_name=full, class_short_name=short,
                package=pkg, member=f.name, label=f"{short}.{f.name}",
            ))
        for m in ci.all_methods:
            out.append(Symbol(
                kind="method", class_full_name=full, class_short_name=short,
                package=pkg, member=m.name, label=f"{short}.{m.name}",
            ))
    return out


# ── find in all files ──────────────────────────────────────────────────


@dataclass(frozen=True)
class FindHit:
    class_full_name: str
    class_short_name: str
    line_number: int     # 1-based
    line_text: str


# ── references ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RefRow:
    """One row in the References panel."""
    source_class: str
    source_member: str
    ref_kind: str
    offset: int


def references_to_member(state: StudioState, class_full_name: str,
                         member: str, kind: str) -> list[RefRow]:
    """Collect every place the given method/field is read, written, or
    called from. ``kind`` is ``"method"`` / ``"field"`` so we pick the
    right Workspace query."""
    r = state.active_resource()
    if r is None:
        return []
    ws = r.workspace
    rows: list[RefRow] = []
    if kind == "field":
        for reader in ws.field_readers(class_full_name, member):
            src_class, _, src_member = reader.rpartition(".")
            rows.append(RefRow(src_class or class_full_name,
                               src_member or reader, "field_read", -1))
        for writer in ws.field_writers(class_full_name, member):
            src_class, _, src_member = writer.rpartition(".")
            rows.append(RefRow(src_class or class_full_name,
                               src_member or writer, "field_write", -1))
    # Also include references-to-name hits — call sites for methods and
    # coerce/instantiation hits that touch the name.
    for ref in ws.references_to(member):
        rows.append(RefRow(ref.source_class, ref.source_member,
                           ref.ref_kind, ref.offset))
    # De-duplicate on (class, member, kind).
    seen: set[tuple[str, str, str]] = set()
    out: list[RefRow] = []
    for row in rows:
        key = (row.source_class, row.source_member, row.ref_kind)
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    out.sort(key=lambda r_: (r_.source_class, r_.source_member))
    return out


def references_to_class(state: StudioState,
                        class_full_name: str) -> list[RefRow]:
    """Every class that mentions ``class_full_name`` — instantiations,
    coerce-to-type, param/return types, etc."""
    r = state.active_resource()
    if r is None:
        return []
    ws = r.workspace
    out: list[RefRow] = []
    # Try the qualified name first, then the short name.
    seen: set[tuple[str, str, str]] = set()
    short = class_full_name.rpartition(".")[2]
    for target in (class_full_name, short):
        for ref in ws.references_to(target):
            key = (ref.source_class, ref.source_member, ref.ref_kind)
            if key in seen:
                continue
            seen.add(key)
            out.append(RefRow(ref.source_class, ref.source_member,
                              ref.ref_kind, ref.offset))
    out.sort(key=lambda r_: (r_.source_class, r_.source_member))
    return out


# ── class hierarchy ───────────────────────────────────────────────────


@dataclass(frozen=True)
class HierarchyRow:
    """Row in the hierarchy panel — one class plus its depth from the
    target class (0 = the class itself, negative = ancestor, positive
    = descendant)."""
    class_full_name: str
    depth: int
    relation: str     # "self" | "super" | "sub"


def class_hierarchy(state: StudioState,
                    class_full_name: str) -> list[HierarchyRow]:
    r = state.active_resource()
    if r is None:
        return []
    ws = r.workspace
    rows: list[HierarchyRow] = []

    # Ancestors (immediate parent first, walking up).
    parents = ws.get_ancestors(class_full_name)
    for i, p in enumerate(parents):
        rows.append(HierarchyRow(p, -(i + 1), "super"))
    rows.reverse()  # root first.
    rows.append(HierarchyRow(class_full_name, 0, "self"))

    # Descendants — BFS one level at a time.
    frontier = ws.get_subclasses(class_full_name)
    depth = 1
    while frontier:
        next_frontier: list[str] = []
        for name in sorted(frontier):
            rows.append(HierarchyRow(name, depth, "sub"))
            next_frontier.extend(ws.get_subclasses(name))
        frontier = next_frontier
        depth += 1
    return rows


# ── per-method disassembly ────────────────────────────────────────────


def render_method_disasm(state: StudioState,
                         class_full_name: str,
                         method_index: int) -> str:
    """Raw bytes alongside mnemonics for one method body. Used by the
    per-method hex view."""
    r = state.active_resource()
    if r is None:
        return ""
    cls = next((c for c in r.classes if c.full_name == class_full_name),
               None)
    if cls is None:
        return ""
    abc = r.resource.abc_blocks[cls.abc_index]
    body = None
    for b in abc.method_bodies:
        if getattr(b, "method", -1) == method_index:
            body = b
            break
    if body is None:
        return f"// method {method_index} has no body"
    try:
        instrs = decode_instructions(body.code)
        resolved = resolve_instructions(abc, instrs)
    except Exception as exc:  # noqa: BLE001
        return f"// decode error: {exc}"
    lines: list[str] = []
    lines.append(f"// method #{method_index}  ({len(body.code)} bytes)")
    lines.append("")
    code = body.code
    for r_ in resolved:
        start = r_.offset
        end = (resolved[resolved.index(r_) + 1].offset
               if resolved.index(r_) + 1 < len(resolved)
               else len(code))
        raw = code[start:end]
        hex_col = " ".join(f"{b:02x}" for b in raw[:8])
        if len(raw) > 8:
            hex_col += " …"
        ops = ", ".join(r_.operands) if r_.operands else ""
        lines.append(
            f"  {r_.offset:04X}  {hex_col:<27}  {r_.mnemonic:<16}  {ops}"
        )
    return "\n".join(lines)


# ── SWF asset listing ─────────────────────────────────────────────────


# Tag types we export as standalone files.
_BITMAP_TAGS = {6, 21, 35}              # DefineBits variants (JPEG payload)
_LOSSLESS_TAGS = {20, 36}               # DefineBitsLossless (zlib BGRA)
_SOUND_TAGS = {14, 46}                  # DefineSound(+2)
_FONT_TAGS = {10, 48, 75}               # DefineFont / Font2 / Font3
_BINARY_TAGS = {87}                     # DefineBinaryData


@dataclass(frozen=True)
class AssetEntry:
    """Row in the sidebar's Assets section."""
    tag_index: int       # position in Resource.swf_tags
    kind: str            # "bitmap" | "sound" | "font" | "binary"
    name: str            # short label for the row
    char_id: int
    size_bytes: int


def list_assets(state: StudioState) -> list[AssetEntry]:
    r = state.active_resource()
    if r is None or r.resource.swf_tags is None:
        return []
    out: list[AssetEntry] = []
    for i, tag in enumerate(r.resource.swf_tags):
        tt = tag.tag_type
        if tt in _BITMAP_TAGS | _LOSSLESS_TAGS:
            kind = "bitmap"
        elif tt in _SOUND_TAGS:
            kind = "sound"
        elif tt in _FONT_TAGS:
            kind = "font"
        elif tt in _BINARY_TAGS:
            kind = "binary"
        else:
            continue
        payload = tag.payload or b""
        char_id = (int.from_bytes(payload[:2], "little")
                   if len(payload) >= 2 else -1)
        out.append(AssetEntry(
            tag_index=i, kind=kind,
            name=f"{kind}_{char_id if char_id >= 0 else i}",
            char_id=char_id,
            size_bytes=len(payload),
        ))
    return out


def export_asset(state: StudioState, entry: AssetEntry,
                 out_path: Path) -> bool:
    """Write the raw tag payload (minus the char-id prefix when
    applicable) to disk. Full format decoding (PNG, WAV, TTF) is a
    bigger job — this gives you the embedded bytes as-is, which is
    enough for JPEG bitmaps (.jpg) and DefineBinaryData (.bin)."""
    r = state.active_resource()
    if r is None or r.resource.swf_tags is None:
        return False
    if not (0 <= entry.tag_index < len(r.resource.swf_tags)):
        return False
    tag = r.resource.swf_tags[entry.tag_index]
    payload = tag.payload or b""
    # Strip the 2-byte char-id prefix for everything except binary —
    # binary-data tags also have a reserved u32 after char-id, but
    # users mostly want the full blob anyway.
    if entry.kind == "bitmap" and tag.tag_type in _BITMAP_TAGS:
        data = payload[2:]
    elif entry.kind == "binary":
        data = payload[6:]  # char_id (u16) + reserved (u32)
    else:
        data = payload[2:]
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(data)
        return True
    except OSError as exc:
        log.warning("export_asset(%s): %s", entry.name, exc)
        return False


def find_in_all(
    state: StudioState,
    needle: str,
    *,
    case_sensitive: bool = False,
    limit: int = 2000,
    progress_cb=None,
) -> list[FindHit]:
    """Decompile every class in the active SWF and collect line-level
    matches for ``needle``. Results from the render cache are reused
    when available so a warm cache makes this near-instant.

    ``progress_cb(done, total)`` is invoked every few classes so the
    UI can paint a progress bar without blocking the event loop.
    ``limit`` caps the number of hits returned — large matches don't
    fill the palette with useless lines.
    """
    r = state.active_resource()
    if r is None or not needle:
        return []

    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        pattern = re.compile(re.escape(needle), flags)
    except re.error:
        return []

    hits: list[FindHit] = []
    total = len(r.classes)
    for i, cls in enumerate(r.classes):
        if progress_cb and (i % 25 == 0):
            progress_cb(i, total)
        key = (state.active_resource_index or 0, cls.full_name, "source")
        text = _CACHE.get(key)
        if text is None:
            abc = r.resource.abc_blocks[cls.abc_index]
            try:
                text = decompile_class(abc, name=cls.full_name)
            except Exception:  # noqa: BLE001
                continue
            _CACHE[key] = text
        for lineno, line in enumerate(text.split("\n"), start=1):
            if pattern.search(line):
                hits.append(FindHit(
                    class_full_name=cls.full_name,
                    class_short_name=cls.name,
                    line_number=lineno,
                    line_text=line.rstrip(),
                ))
                if len(hits) >= limit:
                    if progress_cb:
                        progress_cb(total, total)
                    return hits
    if progress_cb:
        progress_cb(total, total)
    return hits
