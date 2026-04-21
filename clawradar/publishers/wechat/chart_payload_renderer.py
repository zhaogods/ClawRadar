from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from bs4 import Tag


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _activate_windows_dll_paths() -> None:
    if os.name != 'nt' or not hasattr(os, 'add_dll_directory'):
        return

    prefixes = []
    for candidate in (Path(sys.executable).resolve().parent, Path(sys.prefix)):
        if candidate not in prefixes:
            prefixes.append(candidate)

    for prefix in prefixes:
        dll_dir = prefix / 'Library' / 'bin'
        if dll_dir.exists():
            current_path = os.environ.get('PATH', '')
            dll_text = str(dll_dir)
            if dll_text not in current_path.split(os.pathsep):
                os.environ['PATH'] = dll_text + os.pathsep + current_path
            try:
                os.add_dll_directory(str(dll_dir))
            except (FileNotFoundError, OSError):
                continue


def _ensure_windows_cairo_alias() -> None:
    if os.name != 'nt':
        return

    for prefix in (Path(sys.executable).resolve().parent, Path(sys.prefix)):
        dll_dir = prefix / 'Library' / 'bin'
        if not dll_dir.exists():
            continue
        source = dll_dir / 'cairo.dll'
        alias = dll_dir / 'libcairo-2.dll'
        if source.exists() and not alias.exists():
            try:
                os.link(source, alias)
            except OSError:
                try:
                    import shutil
                    shutil.copyfile(source, alias)
                except OSError:
                    continue


def _root_node(node: Tag) -> Tag:
    current = node
    while getattr(current, 'parent', None) is not None:
        current = current.parent
    return current


@lru_cache(maxsize=1)
def _load_chart_converter_factory():
    module_path = _repo_root() / 'radar_engines' / 'ReportEngine' / 'renderers' / 'chart_to_svg.py'
    if not module_path.exists():
        return None

    spec = importlib.util.spec_from_file_location('clawradar_wechat_chart_to_svg', module_path)
    if spec is None or spec.loader is None:
        return None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, 'create_chart_converter', None)


@lru_cache(maxsize=1)
def _get_chart_converter():
    factory = _load_chart_converter_factory()
    if factory is None:
        return None
    try:
        return factory()
    except Exception:
        return None


def _chart_config_script(node: Tag) -> Optional[Tag]:
    config_ids: list[str] = []
    for canvas in node.find_all('canvas'):
        config_id = str(canvas.get('data-config-id') or '').strip()
        if config_id:
            config_ids.append(config_id)

    if not config_ids:
        return None

    root = _root_node(node)
    for config_id in config_ids:
        script = node.find('script', id=config_id)
        if script is not None:
            return script
        if root is not node:
            script = root.find('script', id=config_id)
            if script is not None:
                return script
    return None


def extract_chart_payload(node: Tag) -> Optional[dict[str, Any]]:
    script = _chart_config_script(node)
    if script is None:
        return None

    raw_payload = (script.string or script.get_text('', strip=True) or '').strip()
    if not raw_payload:
        return None

    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError:
        return None

    if not isinstance(payload, dict):
        return None

    widget_type = str(payload.get('widgetType') or '').strip().lower()
    if not widget_type.startswith('chart.js'):
        return None
    return payload


def render_chart_payload_to_png(
    payload: dict[str, Any],
    *,
    width: int = 800,
    height: int = 500,
    dpi: int = 100,
) -> Path | None:
    converter = _get_chart_converter()
    if converter is None:
        return None

    try:
        _activate_windows_dll_paths()
        _ensure_windows_cairo_alias()
        import cairosvg
    except Exception:
        return None

    try:
        svg = converter.convert_widget_to_svg(payload, width=width, height=height, dpi=dpi)
    except Exception:
        return None
    if not svg:
        return None

    fd, temp_name = tempfile.mkstemp(suffix='.png')
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        cairosvg.svg2png(
            bytestring=svg.encode('utf-8'),
            write_to=str(temp_path),
            output_width=width,
            output_height=height,
        )
        return temp_path
    except Exception:
        temp_path.unlink(missing_ok=True)
        return None


def render_chart_container_to_png(
    node: Tag,
    *,
    width: int = 800,
    height: int = 500,
    dpi: int = 100,
) -> Path | None:
    payload = extract_chart_payload(node)
    if payload is None:
        return None
    return render_chart_payload_to_png(payload, width=width, height=height, dpi=dpi)


__all__ = [
    'extract_chart_payload',
    'render_chart_container_to_png',
    'render_chart_payload_to_png',
]
