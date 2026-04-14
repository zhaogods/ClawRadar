"""
Report Engine渲染器集合。

提供 HTMLRenderer、MarkdownRenderer 与 PDFRenderer。
PDF 相关依赖较重，因此这里采用惰性导出，避免 HTML-only 路径在导入时
被可选 PDF 依赖阻塞。
"""

__all__ = [
    "HTMLRenderer",
    "PDFRenderer",
    "MarkdownRenderer",
    "PDFLayoutOptimizer",
    "PDFLayoutConfig",
    "PageLayout",
    "KPICardLayout",
    "CalloutLayout",
    "TableLayout",
    "ChartLayout",
    "GridLayout",
]


def __getattr__(name):
    if name == "HTMLRenderer":
        from .html_renderer import HTMLRenderer

        return HTMLRenderer
    if name == "MarkdownRenderer":
        from .markdown_renderer import MarkdownRenderer

        return MarkdownRenderer
    if name in {
        "PDFRenderer",
        "PDFLayoutOptimizer",
        "PDFLayoutConfig",
        "PageLayout",
        "KPICardLayout",
        "CalloutLayout",
        "TableLayout",
        "ChartLayout",
        "GridLayout",
    }:
        from .pdf_renderer import PDFRenderer
        from .pdf_layout_optimizer import (
            PDFLayoutOptimizer,
            PDFLayoutConfig,
            PageLayout,
            KPICardLayout,
            CalloutLayout,
            TableLayout,
            ChartLayout,
            GridLayout,
        )

        exports = {
            "PDFRenderer": PDFRenderer,
            "PDFLayoutOptimizer": PDFLayoutOptimizer,
            "PDFLayoutConfig": PDFLayoutConfig,
            "PageLayout": PageLayout,
            "KPICardLayout": KPICardLayout,
            "CalloutLayout": CalloutLayout,
            "TableLayout": TableLayout,
            "ChartLayout": ChartLayout,
            "GridLayout": GridLayout,
        }
        return exports[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
