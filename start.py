import argparse
import io
import json
import logging
import os
import re
import sys
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any, Callable, Iterator

from clawradar.orchestrator import topic_radar_orchestrate
from clawradar.publish_only import publish_existing_output
from clawradar.real_source import DEFAULT_REAL_SOURCE_IDS


RUN_MODE_OPTIONS = [
    (False, "运行完整流程", "按输入模式生成并交付一次完整结果。"),
    (True, "仅重发已有内容", "基于已有输出重新投递，不重新执行前面的流程。"),
]

INPUT_MODE_OPTIONS = [
    ("real_source", "实时热点源", "从预设来源抓取热点内容并继续处理。"),
    ("user_topic", "用户自定义主题", "围绕你提供的主题词、公司和关键词生成内容。"),
]

DELIVERY_CHANNEL_OPTIONS = [
    ("archive_only", "仅归档", "只落盘保存结果，不发送到外部渠道。"),
    ("feishu", "飞书", "将结果发送到飞书目标地址。"),
    ("wechat", "微信草稿", "将结果发送到微信草稿箱或对应目标。"),
]

SOURCE_ID_OPTIONS = [
    ("weibo", "微博", "适合看实时热点与舆情。"),
    ("zhihu", "知乎", "适合看话题讨论和长文本观点。"),
    ("36kr", "36Kr", "适合看公司、投融资和科技行业新闻。"),
]

DEEP_CRAWL_PLATFORM_OPTIONS = [
    ("xhs", "小红书", "生活/美妆/时尚/旅游"),
    ("dy", "抖音", "娱乐/音乐/美食/科技"),
    ("ks", "快手", "生活/搞笑/农村/手工"),
    ("bili", "B站", "科技/游戏/动漫/学习"),
    ("wb", "微博", "热点/新闻/娱乐/明星"),
    ("tieba", "贴吧", "游戏/动漫/兴趣/讨论"),
    ("zhihu", "知乎", "知识/学习/科技/职场"),
]

LOG_MODE_OPTIONS = [
    ("concise", "简洁", "默认收起底层详细日志，但保留写作引擎关键日志。"),
    ("verbose", "详细", "显示下游详细日志，适合排查问题。"),
]

STAGE_LABELS = {
    "crawl": "抓取",
    "ingest": "规整",
    "topics": "主题整理",
    "score": "评分",
    "deep_crawl": "深爬",
    "write": "撰写",
    "deliver": "发布",
    "notify": "通知",
}

CONCISE_WRITING_LOG_KEYWORDS = (
    "ReportEngine",
    "Report Agent",
    "开始生成报告",
    "选择报告模板",
    "选择模板:",
    "使用用户自定义模板",
    "模板选择结果",
    "模板选择完成",
    "文档标题/目录设计",
    "文档标题/目录设计完成",
    "章节字数规划",
    "章节字数规划已生成",
    "生成章节",
    "章节 ",
    " 已完成",
    "report_saved",
    "报告已保存到",
    "报告生成完成",
    "html_rendered",
)


class _RuntimeLogBuffer:
    def __init__(self, *, show_writing_logs: bool = False, visible_stream: Any = None) -> None:
        self._buffer = io.StringIO()
        self._line_buffer = ""
        self._show_writing_logs = show_writing_logs
        self._visible_stream = visible_stream or sys.__stdout__
        self._header_printed = False

    def write(self, text: str) -> int:
        if not text:
            return 0
        self._buffer.write(text)
        if self._show_writing_logs:
            self._line_buffer += text
            while "\n" in self._line_buffer:
                line, self._line_buffer = self._line_buffer.split("\n", 1)
                self._emit_visible_line(line)
        return len(text)

    def flush(self) -> None:
        if hasattr(self._visible_stream, "flush"):
            self._visible_stream.flush()

    def finalize(self) -> None:
        if self._show_writing_logs and self._line_buffer:
            self._emit_visible_line(self._line_buffer)
            self._line_buffer = ""
        self.flush()

    def getvalue(self) -> str:
        return self._buffer.getvalue()

    def _emit_visible_line(self, line: str) -> None:
        if not _should_show_concise_log_line(line):
            return
        if not self._header_printed:
            self._visible_stream.write("\n[写作引擎日志]\n")
            self._header_printed = True
        self._visible_stream.write(line + "\n")


def _should_show_concise_log_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    return any(keyword in stripped for keyword in CONCISE_WRITING_LOG_KEYWORDS)


# ─────────────── prompt helpers ───────────────

def _print_section(title: str) -> None:
    print(f"\n=== {title} ===")


def _prompt_text(label: str, description: str, default: str = "", required: bool = False) -> str:
    suffix = f" [默认: {default}]" if default else ""
    while True:
        print(f"- {label}：{description}{suffix}")
        value = input("  请输入: ").strip()
        resolved = value or default
        if required and not resolved.strip():
            print(f"  {label} 为必填项，请重新输入。")
            continue
        return resolved


def _prompt_menu(label: str, description: str, options: list[tuple[object, str, str]], default_index: int = 1):
    while True:
        print(f"- {label}：{description}")
        for index, (_, option_label, option_desc) in enumerate(options, start=1):
            default_mark = "（默认）" if index == default_index else ""
            print(f"  {index}. {option_label} - {option_desc}{default_mark}")
        raw_value = input("  请输入序号: ").strip()
        if not raw_value:
            return options[default_index - 1][0]
        if raw_value.isdigit():
            selected_index = int(raw_value)
            if 1 <= selected_index <= len(options):
                return options[selected_index - 1][0]
        print("  序号无效，请输入列表中的数字。")


def _prompt_int(label: str, description: str, default: int, minimum: int = 1) -> int:
    while True:
        print(f"- {label}：{description} [默认: {default}]")
        value = input("  请输入数字: ").strip()
        if not value:
            return default
        try:
            resolved = int(value)
        except ValueError:
            print("  请输入整数。")
            continue
        if resolved < minimum:
            print(f"  {label} 不能小于 {minimum}。")
            continue
        return resolved


def _prompt_multi_menu(
    label: str,
    description: str,
    options: list[tuple[str, str, str]],
    default_values: list[str],
    required: bool = False,
) -> list[str]:
    option_map = {str(index): value for index, (value, _, _) in enumerate(options, start=1)}
    default_indexes = [
        str(index)
        for index, (value, _, _) in enumerate(options, start=1)
        if value in default_values
    ]
    default_hint = ",".join(default_indexes)

    while True:
        print(f"- {label}：{description}")
        for index, (_, option_label, option_desc) in enumerate(options, start=1):
            default_mark = "（默认）" if str(index) in default_indexes else ""
            print(f"  {index}. {option_label} - {option_desc}{default_mark}")
        print(f"  可输入多个序号，使用英文逗号分隔；直接回车使用默认值 [{default_hint}]。")
        raw_value = input("  请输入序号: ").strip()
        if not raw_value:
            resolved = list(default_values)
        else:
            indexes = [item for item in re.split(r"[\s,]+", raw_value) if item]
            if any(index not in option_map for index in indexes):
                print("  序号无效，请重新输入。")
                continue
            resolved = []
            for index in indexes:
                value = option_map[index]
                if value not in resolved:
                    resolved.append(value)
        if required and not resolved:
            print(f"  {label} 至少选择一项。")
            continue
        return resolved


def _default_delivery_target(delivery_channel: str) -> str:
    if delivery_channel == "wechat":
        return "wechat://draft-box/clawradar-review"
    return ""


def _validate_delivery_target(delivery_channel: str, delivery_target: str) -> str:
    if delivery_channel != "archive_only" and not delivery_target.strip():
        raise ValueError('当交付渠道不是"仅归档"时，delivery_target 为必填项。')
    return delivery_target


# ─────────────── output helpers ───────────────

def _print_key_value(label: str, value: Any) -> None:
    resolved = value if value not in (None, "", [], {}) else "-"
    print(f"- {label}：{resolved}")


def _print_json_block(title: str, payload: Any) -> None:
    print(f"\n[{title}]")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


@contextmanager
def _runtime_output_buffer(log_mode: str) -> Iterator[_RuntimeLogBuffer]:
    buffer = _RuntimeLogBuffer(show_writing_logs=log_mode == "concise")
    if log_mode != "concise":
        yield buffer
        return

    previous_disable = logging.root.manager.disable
    loguru_logger = None
    loguru_sink_ids: list[int] = []
    try:
        from loguru import logger as imported_logger

        loguru_logger = imported_logger
        loguru_logger.remove()
        loguru_sink_ids.append(loguru_logger.add(buffer, level="INFO", format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | {name}:{function}:{line} - {message}"))
    except Exception:
        loguru_logger = None

    logging.disable(logging.CRITICAL)
    try:
        with redirect_stdout(buffer), redirect_stderr(buffer):
            yield buffer
    finally:
        buffer.finalize()
        logging.disable(previous_disable)
        if loguru_logger is not None:
            for sink_id in loguru_sink_ids:
                loguru_logger.remove(sink_id)


def _execute_with_log_mode(log_mode: str, runner: Callable[[], dict[str, Any]]) -> tuple[dict[str, Any], str]:
    with _runtime_output_buffer(log_mode) as buffer:
        result = runner()
    return result, buffer.getvalue()


def _print_event_overview(result: dict[str, Any]) -> None:
    event_statuses = result.get("event_statuses") or []
    if not event_statuses:
        return
    print("\n[事件概览]")
    for index, event in enumerate(event_statuses, start=1):
        print(f"{index}. {event.get('event_title') or event.get('event_id') or '-'}")
        print(f"   评分结论：{event.get('decision_status') or '-'}")
        evidence = event.get("evidence") if isinstance(event.get("evidence"), dict) else {}
        deep_crawl = evidence.get("deep_crawl") if isinstance(evidence, dict) else None
        if deep_crawl:
            platforms = deep_crawl.get("platforms", [])
            summary = deep_crawl.get("summary", {})
            print(f"   深爬增强：{len(platforms)} 个平台 → {summary.get('total_notes', '-')} 条笔记")
        print(f"   撰写状态：{event.get('write_status') or '-'}")
        print(f"   发布状态：{event.get('deliver_status') or '-'}")
        stage_reasons = event.get("stage_reasons") if isinstance(event.get("stage_reasons"), dict) else {}
        if stage_reasons.get("write"):
            print(f"   未撰写原因：{stage_reasons['write']}")
        if stage_reasons.get("deliver"):
            print(f"   未发布原因：{stage_reasons['deliver']}")


def _print_pipeline_result(result: dict[str, Any]) -> None:
    _print_section("执行结果")
    _print_key_value("任务状态", result.get("run_status"))
    _print_key_value("最终阶段", result.get("final_stage"))
    _print_key_value("整体结论", result.get("decision_status"))
    _print_key_value("输出目录", result.get("output_root"))

    stage_statuses = result.get("stage_statuses") if isinstance(result.get("stage_statuses"), dict) else {}
    run_summary = result.get("run_summary") if isinstance(result.get("run_summary"), dict) else {}
    if run_summary:
        print("\n[运行摘要]")
        _print_key_value("输入模式", run_summary.get("mode"))
        _print_key_value("运行 ID", run_summary.get("run_id"))
        _print_key_value("候选数", run_summary.get("candidate_count"))
        _print_key_value("可发布数", run_summary.get("publish_ready_count"))
        _print_key_value("撰写成功数", run_summary.get("write_success_count"))
        _print_key_value("发布成功数", run_summary.get("deliver_success_count"))
        dc_applied = run_summary.get("deep_crawl_applied")
        dc_platforms = run_summary.get("deep_crawl_platform_count", 0)
        dc_notes = run_summary.get("deep_crawl_notes_count", 0)
        if dc_applied:
            _print_key_value("深爬增强", f"已启用 → {dc_platforms} 平台, {dc_notes} 条笔记")
        else:
            dc_stage = stage_statuses.get("deep_crawl") if isinstance(stage_statuses, dict) else None
            dc_status = (dc_stage or {}).get("status", "") if isinstance(dc_stage, dict) else ""
            if dc_status == "failed":
                dc_errors = (dc_stage or {}).get("errors") if isinstance(dc_stage, dict) else []
                dc_error_msg = ""
                if isinstance(dc_errors, list) and dc_errors:
                    first_err = dc_errors[0] if isinstance(dc_errors[0], dict) else {}
                    dc_error_msg = first_err.get("message", "") or ""
                _print_key_value("深爬增强", f"已开启但失败" + (f"（{dc_error_msg}）" if dc_error_msg else ""))
            elif dc_status == "skipped":
                dc_skip = (dc_stage or {}).get("skipped_reason", "") if isinstance(dc_stage, dict) else ""
                _print_key_value("深爬增强", f"已开启但跳过（{dc_skip}）" if dc_skip else "已开启但跳过")
            else:
                _print_key_value("深爬增强", "未启用")

    if stage_statuses:
        print("\n[阶段状态]")
        for stage_name in ("crawl", "ingest", "topics", "score", "deep_crawl", "write", "deliver", "notify"):
            stage_info = stage_statuses.get(stage_name)
            if not isinstance(stage_info, dict):
                continue
            status = stage_info.get("status") or "-"
            skipped_reason = stage_info.get("skipped_reason")
            stage_label = STAGE_LABELS.get(stage_name, stage_name)
            line = f"- {stage_label}（{stage_name}）：{status}"
            if skipped_reason:
                line += f"（原因：{skipped_reason}）"
            print(line)

    decision_status = result.get("decision_status")
    write_stage = stage_statuses.get("write") if isinstance(stage_statuses.get("write"), dict) else {}
    deliver_stage = stage_statuses.get("deliver") if isinstance(stage_statuses.get("deliver"), dict) else {}
    if decision_status != "publish_ready":
        print("\n[提示]")
        print(f"- 本次整体结论为 {decision_status or '-'}，因此不会进入撰写和发布阶段。")
        if write_stage.get("skipped_reason"):
            print(f"- 撰写阶段跳过原因：{write_stage['skipped_reason']}")
        if deliver_stage.get("skipped_reason"):
            print(f"- 发布阶段跳过原因：{deliver_stage['skipped_reason']}")

    _print_event_overview(result)

    errors = result.get("errors") or []
    if errors:
        _print_json_block("错误详情", errors)


def _print_publish_only_result(result: dict[str, Any]) -> None:
    _print_section("重发结果")
    _print_key_value("任务状态", result.get("run_status"))
    _print_key_value("跳过原因", result.get("skip_reason"))

    publish_source = result.get("publish_source") if isinstance(result.get("publish_source"), dict) else {}
    if publish_source:
        print("\n[重发来源]")
        _print_key_value("来源类型", publish_source.get("kind"))
        _print_key_value("来源文件", publish_source.get("path"))
        _print_key_value("运行目录", publish_source.get("run_root"))

    publish_record = result.get("publish_record") if isinstance(result.get("publish_record"), dict) else {}
    if publish_record:
        print("\n[发布记录]")
        _print_key_value("渠道", publish_record.get("channel"))
        _print_key_value("目标", publish_record.get("target"))
        _print_key_value("事件 ID", publish_record.get("event_id"))
        _print_key_value("消息文件", publish_record.get("message_path"))
        _print_key_value("归档文件", publish_record.get("archive_path"))

    errors = result.get("errors") or []
    if errors:
        _print_json_block("错误详情", errors)


# ─────────────── notification ───────────────

NOTIFY_ON_OPTIONS = [
    ("run_completed", "任务完成", "编排完成且无发布失败时通知。"),
    ("run_failed", "任务失败", "编排执行失败时通知。"),
    ("publish_succeeded", "发布成功", "存在交付事件且全部发布成功时通知。"),
    ("publish_failed", "发布失败", "存在交付事件且有失败时通知。"),
]


def _collect_notification_args() -> argparse.Namespace:
    notification_channel = _prompt_menu(
        "notification_channel",
        "选择通知方式。",
        [
            ("", "不通知", "不发送额外状态通知。"),
            ("pushplus", "PushPlus", "通过 PushPlus 发送运行/发布摘要通知。"),
        ],
        default_index=2,
    )
    if not notification_channel:
        return argparse.Namespace(
            notification_channel="",
            notification_target="",
            notify_on=[],
            pushplus_token="",
        )

    notification_target = _prompt_text(
        "notification_target",
        "通知目标地址；PushPlus 使用 pushplus://default 或 pushplus://topic/<topic>。",
        default="pushplus://default",
        required=True,
    )
    notify_on = _prompt_multi_menu(
        "notify_on",
        "选择哪些结果会触发通知。",
        NOTIFY_ON_OPTIONS,
        default_values=["run_completed", "run_failed", "publish_succeeded", "publish_failed"],
        required=True,
    )
    return argparse.Namespace(
        notification_channel=notification_channel,
        notification_target=notification_target,
        notify_on=notify_on,
        pushplus_token="",
    )


# ─────────────── deep crawl config ───────────────

def _collect_deep_crawl_args() -> dict | None:
    enabled = _prompt_menu(
        "deep_crawl_enabled",
        "是否启用社媒深爬（DeepSentimentCrawling）？首次使用会自动建表，需已配置 .env 数据库和 Playwright。",
        [
            (False, "否", "跳过深爬阶段，仅使用基础热点搜索。"),
            (True, "是", "启用深爬阶段，从数据库取关键词在指定平台深度搜索。"),
        ],
        default_index=1,
    )
    if not enabled:
        return None

    platforms = _prompt_multi_menu(
        "deep_crawl_platforms",
        "选择要深爬的社媒平台。",
        DEEP_CRAWL_PLATFORM_OPTIONS,
        default_values=["xhs", "dy", "ks", "bili", "wb", "tieba", "zhihu"],
        required=True,
    )
    max_keywords = _prompt_int("deep_crawl_max_keywords", "每平台最大关键词数", default=50, minimum=5)
    max_notes = _prompt_int("deep_crawl_max_notes", "每平台最大采集笔记数", default=50, minimum=5)
    server_mode = _prompt_menu(
        "deep_crawl_server_mode",
        "是否运行在 Linux 云服务器（无物理显示器）？启用后：Xvfb 虚拟显示 + --no-sandbox。",
        [
            (False, "否", "本地 GUI 环境，浏览器有物理显示器，无需 Xvfb。"),
            (True, "是", "云服务器，自动启动 Xvfb 虚拟显示（需 apt install xvfb），浏览器行为与桌面一致。"),
        ],
        default_index=1,
    )
    login_type = _prompt_menu(
        "deep_crawl_login_type",
        "选择社媒平台登录方式。（服务器模式下 QR 码通过终端字符渲染，手机可直接扫码。）",
        [
            ("qrcode", "扫码登录", "二维码扫码登录。无 GUI 时终端显示 Unicode QR 码。"),
            ("phone", "手机号登录", "通过手机验证码登录（需外部 SMS Redis）。"),
            ("cookie", "Cookie 登录", "通过浏览器 Cookie 登录（需提前从桌面浏览器导出）。"),
        ],
        default_index=0,
    )
    test_mode = _prompt_menu(
        "deep_crawl_test_mode",
        "是否使用测试模式（少爬一些，适合验证配置）？",
        [
            (False, "否", "正常爬取。"),
            (True, "是", "测试模式，减少爬取量以快速验证。"),
        ],
        default_index=1,
    )
    return {
        "enabled": True,
        "platforms": platforms,
        "max_keywords": max_keywords,
        "max_notes": max_notes,
        "login_type": login_type,
        "test_mode": test_mode,
        "server_mode": server_mode,
    }


# ─────────────── publish only ───────────────

def _collect_publish_only_args() -> argparse.Namespace:
    _print_section("仅重发已有内容")
    runs_root = _prompt_text("runs_root", "输出根目录；留空时使用项目默认 outputs 目录。")
    publish_file = _prompt_text(
        "publish_file",
        "要重发的 content_bundles.json 或 payload_snapshot.json 文件路径；留空时自动选择最新输出。",
    )
    delivery_channel = _prompt_menu("delivery_channel", "交付方式。", DELIVERY_CHANNEL_OPTIONS, default_index=3)
    delivery_target = _prompt_text(
        "delivery_target",
        "交付目标地址；当选择飞书或微信时必填。",
        default=_default_delivery_target(delivery_channel),
        required=delivery_channel != "archive_only",
    )
    target_event_id = _prompt_text("target_event_id", "指定要重发的事件 ID；不填则自动选最近一条。")
    force_republish = _prompt_menu(
        "force_republish",
        "是否强制重发，即使检测到内容可能已发过。",
        [
            (False, "否", "按默认保护逻辑处理，避免重复发送。"),
            (True, "是", "跳过重复保护，强制重新发送。"),
        ],
        default_index=1,
    )
    notification_args = _collect_notification_args()
    return argparse.Namespace(
        runs_root=runs_root,
        publish_file=publish_file,
        delivery_channel=delivery_channel,
        delivery_target=_validate_delivery_target(delivery_channel, delivery_target),
        target_event_id=target_event_id,
        force_republish=force_republish,
        notification_channel=notification_args.notification_channel,
        notification_target=notification_args.notification_target,
        notify_on=notification_args.notify_on,
        pushplus_token=notification_args.pushplus_token,
    )


# ─────────────── full pipeline ───────────────

def _collect_run_args() -> argparse.Namespace:
    _print_section("运行完整流程")
    input_mode = _prompt_menu("input_mode", "选择本次内容生成方式。", INPUT_MODE_OPTIONS, default_index=1)
    topic = ""
    company = ""
    track = ""
    summary = ""
    keywords: list[str] = []
    source_ids = list(DEFAULT_REAL_SOURCE_IDS)
    persist = False

    if input_mode == "real_source":
        source_ids = _prompt_multi_menu(
            "source_ids",
            "选择热点来源。至少保留一个来源。",
            SOURCE_ID_OPTIONS,
            default_values=list(DEFAULT_REAL_SOURCE_IDS),
            required=True,
        )
        persist = _prompt_menu(
            "persist",
            "是否持久化热点数据到数据库（用于后续深爬关键词提取）？首次自动建表。",
            [
                (False, "否", "不持久化，仅用本次采集结果。"),
                (True, "是", "持久化到数据库，首次自动建表，供后续深爬使用。"),
            ],
            default_index=1,
        )
    else:
        topic = _prompt_text("topic", "主题名称，用于驱动检索与写作。", required=True)
        company = _prompt_text("company", "关联公司名称；用于增强上下文，不知道可留空。")
        track = _prompt_text("track", "主题赛道或方向，例如 AI Agent、具身智能。")
        summary = _prompt_text("summary", "补充背景说明，帮助模型更准确理解主题。")
        keywords_text = _prompt_text(
            "keywords",
            "补充关键词，多个词用空格或英文逗号分隔；用于提升检索覆盖。",
        )
        keywords = [item for item in re.split(r"[\s,]+", keywords_text) if item]

    limit = _prompt_int("limit", "本次最多处理多少条候选内容。", 5, minimum=1)
    request_id = _prompt_text(
        "request_id",
        "本次任务唯一标识，用于输出目录追踪。",
        default="req-clawradar-deliverable",
        required=True,
    )
    trigger_source = _prompt_text(
        "trigger_source",
        "触发来源标记，便于后续排查；通常保留默认值即可。",
        default="manual",
        required=True,
    )
    execution_mode = _prompt_text(
        "execution_mode",
        "执行模式；通常保留 full_pipeline。",
        default="full_pipeline",
        required=True,
    )
    runs_root = _prompt_text("runs_root", "输出根目录；留空时使用项目默认 outputs 目录。")
    delivery_channel = _prompt_menu("delivery_channel", "选择结果交付方式。", DELIVERY_CHANNEL_OPTIONS, default_index=3)
    delivery_target = _prompt_text(
        "delivery_target",
        "交付目标地址；当选择飞书或微信时必填。",
        default=_default_delivery_target(delivery_channel),
        required=delivery_channel != "archive_only",
    )

    _print_section("高级选项")
    deep_crawl_config = _collect_deep_crawl_args()
    entry_options_json = _prompt_text(
        "entry_options_json",
        "entry_options JSON 覆盖（高级）；直接回车跳过。",
        default="",
    )
    notification_args = _collect_notification_args()

    return argparse.Namespace(
        input_mode=input_mode,
        topic=topic,
        company=company,
        track=track,
        summary=summary,
        keywords=keywords,
        source_ids=source_ids,
        persist=persist,
        limit=limit,
        request_id=request_id,
        trigger_source=trigger_source,
        execution_mode=execution_mode,
        runs_root=runs_root,
        delivery_channel=delivery_channel,
        delivery_target=_validate_delivery_target(delivery_channel, delivery_target),
        deep_crawl_config=deep_crawl_config,
        entry_options_json=entry_options_json,
        notification_channel=notification_args.notification_channel,
        notification_target=notification_args.notification_target,
        notify_on=notification_args.notify_on,
        pushplus_token=notification_args.pushplus_token,
    )


# ─────────────── payload builder ───────────────

def _build_payload(args: argparse.Namespace) -> dict:
    """Build orchestrator payload from collected args. Mirrors run_clawradar_deliverable._build_payload."""
    delivery_channel = getattr(args, "delivery_channel", "archive_only")
    delivery_target = getattr(args, "delivery_target", "")
    notification_channel = str(getattr(args, "notification_channel", "") or "").strip()
    notification_target = str(getattr(args, "notification_target", "") or "").strip()
    notify_on = list(getattr(args, "notify_on", []) or [])
    pushplus_token = str(getattr(args, "pushplus_token", "") or "").strip()
    version = getattr(args, "__version", None)
    version_meta = {} if not version else {"__version": version}

    notification_options: dict = {}
    if pushplus_token:
        notification_options["pushplus"] = {"token": pushplus_token}

    input_options: dict = {"mode": args.input_mode, "limit": args.limit}
    if args.input_mode == "real_source":
        input_options["source_ids"] = args.source_ids
        if getattr(args, "persist", False):
            input_options["persist"] = True
    else:
        input_options.update({
            "topic": args.topic,
            "company": args.company,
            "track": args.track,
            "summary": args.summary,
            "keywords": args.keywords,
        })

    entry_options: dict = {
        "input": input_options,
        "write": {"executor": "external_writer"},
        "delivery": {
            "target_mode": delivery_channel,
            "target": delivery_target or ("archive://clawradar" if delivery_channel == "archive_only" else ""),
        },
        "degrade": {
            "input_unavailable": "fail",
            "write_unavailable": "fail",
            "delivery_unavailable": "fail",
        },
    }

    deep_crawl_config = getattr(args, "deep_crawl_config", None)
    if isinstance(deep_crawl_config, dict) and deep_crawl_config.get("enabled"):
        entry_options["deep_crawl"] = deep_crawl_config

    if notification_channel or notification_target or notify_on or notification_options:
        entry_options["notification"] = {
            "channel": notification_channel,
            "target": notification_target,
            "notify_on": notify_on,
            **notification_options,
        }

    # Allow JSON override of entry_options (advanced users)
    entry_options_json = str(getattr(args, "entry_options_json", "") or "").strip()
    if entry_options_json:
        try:
            override = json.loads(entry_options_json)
            if isinstance(override, dict):
                for key, value in override.items():
                    entry_options[key] = value
        except json.JSONDecodeError as exc:
            print(f"[WARN] entry_options_json parse failed: {exc}")

    payload: dict = {
        "request_id": args.request_id,
        "trigger_source": args.trigger_source,
        "entry_options": entry_options,
        **version_meta,
    }
    if args.input_mode == "user_topic":
        payload["user_topic"] = {
            "topic": args.topic,
            "company": args.company,
            "track": args.track,
            "summary": args.summary,
            "keywords": args.keywords,
        }
    return payload


# ─────────────── main ───────────────

def main() -> None:
    print("ClawRadar 交互式启动")
    print('说明：按提示输入序号即可；带"默认"的项目可直接回车。')
    publish_only = _prompt_menu("运行模式", "选择要执行的操作。", RUN_MODE_OPTIONS, default_index=1)
    log_mode = _prompt_menu("日志模式", "选择运行时日志展示方式。", LOG_MODE_OPTIONS, default_index=1)

    if log_mode == "concise":
        print("说明：运行中将收起多数底层详细日志，但会保留写作引擎关键日志。")
    else:
        print("说明：运行中将显示详细引擎日志，适合排查问题。")

    if publish_only:
        args = _collect_publish_only_args()
        result, captured_output = _execute_with_log_mode(
            log_mode,
            lambda: publish_existing_output(
                runs_root=Path(args.runs_root) if args.runs_root else None,
                publish_file=Path(args.publish_file) if args.publish_file else None,
                delivery_channel=args.delivery_channel,
                delivery_target=args.delivery_target,
                target_event_id=args.target_event_id or None,
                force_republish=args.force_republish,
                notification_channel=args.notification_channel or None,
                notification_target=args.notification_target or None,
                notification_options={"pushplus": {"token": args.pushplus_token}} if args.pushplus_token else None,
                notify_on=args.notify_on or None,
            ),
        )
        if captured_output:
            print("\n" + "=" * 60)
            print("  引擎详细日志")
            print("=" * 60)
            print(captured_output)
        _print_publish_only_result(result)
        return

    args = _collect_run_args()
    dc_config = getattr(args, "deep_crawl_config", None) or {}
    if dc_config.get("server_mode"):
        os.environ["CLAWRADAR_SERVER_MODE"] = "1"
    payload = _build_payload(args)
    result, captured_output = _execute_with_log_mode(
        log_mode,
        lambda: topic_radar_orchestrate(
            payload,
            execution_mode=args.execution_mode,
            runs_root=Path(args.runs_root) if args.runs_root else None,
        ),
    )
    if captured_output:
        print("\n" + "=" * 60)
        print("  引擎详细日志")
        print("=" * 60)
        print(captured_output)
    _print_pipeline_result(result)


if __name__ == "__main__":
    main()
