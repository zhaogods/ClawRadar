"""
Report Engine。

一个智能报告生成AI代理实现，聚合 Query/Media/Insight 三个子引擎的
Markdown 与论坛讨论，最终落地结构化HTML报告。
"""

__version__ = "1.0.0"
__author__ = "Report Engine Team"

__all__ = ["ReportAgent", "create_agent"]


def __getattr__(name):
    if name in {"ReportAgent", "create_agent"}:
        from .agent import ReportAgent, create_agent

        exports = {
            "ReportAgent": ReportAgent,
            "create_agent": create_agent,
        }
        return exports[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
