"""Render chart fallback tables into PNG images for WeChat articles."""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from bs4 import Tag
from PIL import Image, ImageDraw, ImageFont


BACKGROUND = (255, 255, 255)
BORDER = (221, 221, 221)
HEADER_BG = (246, 248, 250)
ALT_ROW_BG = (250, 250, 250)
TEXT = (51, 51, 51)
CAPTION = (68, 68, 68)
PADDING_X = 14
PADDING_Y = 10
OUTER_PADDING = 24
MAX_WIDTH = 960
MIN_COL_WIDTH = 96
MAX_COL_WIDTH = 280


def _font_candidates(*, bold: bool = False) -> list[str]:
    if os.name == "nt":
        return [
            r"C:\Windows\Fonts\msyhbd.ttc" if bold else r"C:\Windows\Fonts\msyh.ttc",
            r"C:\Windows\Fonts\simhei.ttf",
            r"C:\Windows\Fonts\simsun.ttc",
            r"C:\Windows\Fonts\arialbd.ttf" if bold else r"C:\Windows\Fonts\arial.ttf",
        ]
    return [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]


def _load_font(size: int, *, bold: bool = False):
    for candidate in _font_candidates(bold=bold):
        if Path(candidate).exists():
            try:
                return ImageFont.truetype(candidate, size=size)
            except Exception:
                continue
    return ImageFont.load_default()


def _measure(draw: ImageDraw.ImageDraw, text: str, font) -> tuple[int, int]:
    sample = text or " "
    box = draw.textbbox((0, 0), sample, font=font)
    return box[2] - box[0], box[3] - box[1]


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font, width: int) -> list[str]:
    text = str(text or "")
    if not text:
        return [""]
    lines: list[str] = []
    for paragraph in text.splitlines() or [text]:
        paragraph = paragraph or ""
        current = ""
        for char in paragraph:
            candidate = f"{current}{char}"
            if current and _measure(draw, candidate, font)[0] > width:
                lines.append(current)
                current = char
            else:
                current = candidate
        lines.append(current)
    return lines or [""]


def _extract_table(table: Tag) -> tuple[str, list[str], list[list[str]]]:
    caption = ""
    caption_node = table.find("caption", recursive=False)
    if caption_node is not None:
        caption = _normalize_text(caption_node.get_text(" ", strip=True))

    rows = []
    for tr in table.find_all("tr"):
        cells = tr.find_all(["th", "td"], recursive=False)
        if cells:
            rows.append(cells)

    if not rows:
        return caption, [], []

    header: list[str] = []
    if any(cell.name.lower() == "th" for cell in rows[0]):
        header = [_normalize_text(cell.get_text(" ", strip=True)) for cell in rows[0]]
        rows = rows[1:]

    body = [[_normalize_text(cell.get_text(" ", strip=True)) for cell in row] for row in rows]
    width = max([len(header), *[len(row) for row in body]] or [0])
    if width:
        header = header + [""] * (width - len(header))
        body = [row + [""] * (width - len(row)) for row in body]
    return caption, header, body


def _fit_widths(widths: list[int], target: int) -> list[int]:
    if not widths:
        return widths
    total = sum(widths)
    if total <= target:
        return widths
    scale = target / total
    adjusted = [max(MIN_COL_WIDTH, min(MAX_COL_WIDTH, int(width * scale))) for width in widths]
    while sum(adjusted) > target:
        idx = max(range(len(adjusted)), key=lambda i: adjusted[i])
        if adjusted[idx] <= MIN_COL_WIDTH:
            break
        adjusted[idx] -= 1
    return adjusted


def render_chart_fallback_table_to_png(table: Tag, *, caption: str = "") -> Path | None:
    table_caption, header, body = _extract_table(table)
    column_count = max([len(header), *[len(row) for row in body]] or [0])
    if column_count <= 0:
        return None

    caption = _normalize_text(caption or table_caption)
    measure_image = Image.new("RGB", (16, 16), BACKGROUND)
    measure_draw = ImageDraw.Draw(measure_image)
    caption_font = _load_font(24, bold=True)
    header_font = _load_font(17, bold=True)
    body_font = _load_font(16, bold=False)

    content_width = MAX_WIDTH - OUTER_PADDING * 2 - (column_count + 1)
    desired_widths: list[int] = []
    for index in range(column_count):
        candidates = []
        if header:
            candidates.append(header[index])
        candidates.extend(row[index] for row in body)
        widest = 0
        for value in candidates:
            font = header_font if header and value == header[index] else body_font
            widest = max(widest, _measure(measure_draw, value, font)[0])
        desired_widths.append(min(MAX_COL_WIDTH, max(MIN_COL_WIDTH, widest + PADDING_X * 2)))

    column_widths = _fit_widths(desired_widths, content_width)
    body_line_h = _measure(measure_draw, "Ag", body_font)[1] + 6
    header_line_h = _measure(measure_draw, "Ag", header_font)[1] + 6
    caption_line_h = _measure(measure_draw, "Ag", caption_font)[1] + 8

    def row_height(row: list[str], *, font) -> int:
        height = 0
        for idx, cell in enumerate(row):
            lines = _wrap_text(measure_draw, cell, font, max(40, column_widths[idx] - PADDING_X * 2))
            line_h = header_line_h if font == header_font else body_line_h
            height = max(height, len(lines) * line_h + PADDING_Y * 2)
        return max(height, (header_line_h if font == header_font else body_line_h) + PADDING_Y * 2)

    caption_lines = _wrap_text(measure_draw, caption, caption_font, MAX_WIDTH - OUTER_PADDING * 2) if caption else []
    total_height = OUTER_PADDING * 2
    if caption_lines:
        total_height += len(caption_lines) * caption_line_h + 12
    if header:
        total_height += row_height(header, font=header_font) + 1
    for row in body:
        total_height += row_height(row, font=body_font) + 1

    image_width = OUTER_PADDING * 2 + sum(column_widths) + column_count + 1
    image = Image.new("RGB", (image_width, total_height), BACKGROUND)
    draw = ImageDraw.Draw(image)
    y = OUTER_PADDING

    if caption_lines:
        for line in caption_lines:
            text_w, _ = _measure(draw, line, caption_font)
            x = max(OUTER_PADDING, (image_width - text_w) // 2)
            draw.text((x, y), line, font=caption_font, fill=CAPTION)
            y += caption_line_h
        y += 12

    x_positions = [OUTER_PADDING]
    for width in column_widths:
        x_positions.append(x_positions[-1] + width + 1)
    table_right = x_positions[-1]

    def draw_row(row: list[str], *, font, bg):
        nonlocal y
        current_height = row_height(row, font=font)
        draw.rectangle([OUTER_PADDING, y, table_right, y + current_height], fill=bg)
        line_h = header_line_h if font == header_font else body_line_h
        for idx, cell in enumerate(row):
            x0 = x_positions[idx]
            x1 = x_positions[idx + 1]
            draw.rectangle([x0, y, x1, y + current_height], outline=BORDER, width=1)
            lines = _wrap_text(draw, cell, font, max(40, column_widths[idx] - PADDING_X * 2))
            text_y = y + PADDING_Y
            for line in lines:
                draw.text((x0 + PADDING_X, text_y), line, font=font, fill=TEXT)
                text_y += line_h
        y += current_height + 1

    if header:
        draw_row(header, font=header_font, bg=HEADER_BG)
    for index, row in enumerate(body):
        draw_row(row, font=body_font, bg=BACKGROUND if index % 2 == 0 else ALT_ROW_BG)

    fd, temp_name = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        image.save(temp_path, format="PNG")
        return temp_path
    except Exception:
        temp_path.unlink(missing_ok=True)
        return None
