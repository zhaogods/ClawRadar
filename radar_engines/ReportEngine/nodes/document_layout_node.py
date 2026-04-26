"""
根据模板目录与多源报告，生成整本报告的标题/目录/主题设计。
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from loguru import logger

from ..core import TemplateSection
from ..prompts import (
    SYSTEM_PROMPT_DOCUMENT_LAYOUT,
    build_document_layout_prompt,
)
from ..utils.json_parser import RobustJSONParser, JSONParseError
from .base_node import BaseNode

MAX_TITLE_CHARS = 64
MAX_TITLE_RETRY_ATTEMPTS = 3
TITLE_FALLBACK_TEXT = "未命名报告"


def _utf8_length(text: str) -> int:
    return len(str(text or "").encode("utf-8"))


def _normalize_title_text(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip(" \t\r\n：:｜|丨/／,，;；。！？!?-—–_")


def _build_title_constraints() -> Dict[str, Any]:
    return {
        "channel": "wechat_draft",
        "max_chars": MAX_TITLE_CHARS,
        "max_utf8_bytes": MAX_TITLE_CHARS * 4,
        "rewrite_when_over_limit": True,
        "allow_truncate_as_business_fallback": False,
        "require_semantic_completeness": True,
    }


def _title_candidates(text: Any) -> List[str]:
    base = _normalize_title_text(text)
    if not base:
        return []

    variants = [base]
    without_brackets = _normalize_title_text(
        re.sub(r"（[^）]{0,30}）|\([^)]{0,30}\)|【[^】]{0,30}】|\[[^\]]{0,30}\]", "", base)
    )
    if without_brackets:
        variants.append(without_brackets)

    candidates: List[str] = []
    seen = set()
    suffixes = (
        "深度观察报告",
        "深度观察",
        "分析报告",
        "观察报告",
        "专题报告",
        "舆情洞察报告",
        "热点追踪",
        "情况说明",
        "详细说明",
        "重大更新说明",
        "报告标题",
        "超长版本",
    )
    split_pattern = r"[：:｜|丨/／—\-–,，;；。！？!?]\s*"

    for item in variants:
        current = item
        while current:
            normalized = _normalize_title_text(current)
            if normalized and normalized not in seen:
                seen.add(normalized)
                candidates.append(normalized)

            updated = normalized
            for suffix in suffixes:
                if updated.endswith(suffix) and len(updated) > len(suffix) + 2:
                    updated = _normalize_title_text(updated[: -len(suffix)])
                    break
            if updated == normalized:
                break
            current = updated

        segments = [_normalize_title_text(part) for part in re.split(split_pattern, item) if _normalize_title_text(part)]
        if segments and segments[0] not in seen:
            seen.add(segments[0])
            candidates.append(segments[0])

    return candidates


def _regenerate_layout_title(
    text: Any,
    *,
    fallback: str = TITLE_FALLBACK_TEXT,
    extra_candidates: Optional[List[str]] = None,
) -> str:
    candidates: List[str] = []
    seen = set()

    def add_candidate(value: Any) -> None:
        for candidate in _title_candidates(value):
            if candidate and candidate not in seen:
                seen.add(candidate)
                candidates.append(candidate)

    add_candidate(text)
    for candidate in extra_candidates or []:
        add_candidate(candidate)
    add_candidate(fallback)

    for candidate in candidates:
        if len(candidate) <= MAX_TITLE_CHARS:
            return candidate

    normalized_fallback = _normalize_title_text(fallback) or TITLE_FALLBACK_TEXT
    return normalized_fallback[:MAX_TITLE_CHARS].rstrip() or TITLE_FALLBACK_TEXT


class DocumentLayoutNode(BaseNode):
    """
    负责生成全局标题、目录与Hero设计。

    结合模板切片、报告摘要与论坛讨论，指导整本书的视觉与结构基调。
    """

    def __init__(self, llm_client):
        """记录LLM客户端并设置节点名字，供BaseNode日志使用"""
        super().__init__(llm_client, "DocumentLayoutNode")
        # 初始化鲁棒JSON解析器，启用所有修复策略
        self.json_parser = RobustJSONParser(
            enable_json_repair=True,
            enable_llm_repair=False,  # 可以根据需要启用LLM修复
            max_repair_attempts=3,
        )

    def run(
        self,
        sections: List[TemplateSection],
        template_markdown: str,
        reports: Dict[str, str],
        forum_logs: str,
        query: str,
        template_overview: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """
        综合模板+多源内容，生成全书的标题、目录结构与主题色板。

        参数:
            sections: 模板切片后的章节列表。
            template_markdown: 模板原文，用于LLM理解上下文。
            reports: 三个引擎的内容映射。
            forum_logs: 论坛讨论摘要。
            query: 用户查询词。
            template_overview: 预生成的模板概览，可复用以减少提示词长度。

        返回:
            dict: 包含 title/subtitle/toc/hero/themeTokens 等设计信息的字典。
        """
        # 将模板原文、切片结构与多源报告一并喂给LLM，便于其理解层级与素材
        payload = {
            "query": query,
            "template": {
                "raw": template_markdown,
                "sections": [section.to_dict() for section in sections],
            },
            "templateOverview": template_overview
            or {
                "title": sections[0].title if sections else "",
                "chapters": [section.to_dict() for section in sections],
            },
            "reports": reports,
            "forumLogs": forum_logs,
            "titleConstraints": _build_title_constraints(),
        }

        fallback_title = _normalize_title_text(query) or _normalize_title_text(payload["templateOverview"].get("title")) or TITLE_FALLBACK_TEXT
        extra_candidates = [query, payload["templateOverview"].get("title")]
        retry_feedback = None

        for attempt in range(1, MAX_TITLE_RETRY_ATTEMPTS + 1):
            attempt_payload = dict(payload)
            if retry_feedback:
                attempt_payload["titleRewriteFeedback"] = retry_feedback
            user_message = build_document_layout_prompt(attempt_payload)
            response = self.llm_client.stream_invoke_to_string(
                SYSTEM_PROMPT_DOCUMENT_LAYOUT,
                user_message,
                temperature=0.3,
                top_p=0.9,
            )
            design = self._parse_response(response)
            raw_title = design.get("title")
            normalized_title = _normalize_title_text(raw_title)
            if normalized_title and len(normalized_title) <= MAX_TITLE_CHARS:
                design["title"] = normalized_title
                logger.info("文档标题/目录设计已生成")
                return design

            regenerated_title = _regenerate_layout_title(
                raw_title,
                fallback=fallback_title,
                extra_candidates=extra_candidates,
            )
            if attempt < MAX_TITLE_RETRY_ATTEMPTS:
                logger.warning(
                    "文档设计title超出微信标题限制，触发重生成（第 {attempt}/{total} 次）: {title}",
                    attempt=attempt,
                    total=MAX_TITLE_RETRY_ATTEMPTS,
                    title=normalized_title or raw_title,
                )
                retry_feedback = {
                    "reason": "title exceeds wechat draft limit or is not semantically complete",
                    "maxChars": MAX_TITLE_CHARS,
                    "maxUtf8Bytes": MAX_TITLE_CHARS * 4,
                    "previousTitle": normalized_title or str(raw_title or "").strip(),
                    "requiredAction": "请直接重写一个更短且语义完整的标题，不要截断上一版标题。",
                    "suggestedDirection": regenerated_title,
                }
                continue

            logger.warning(
                "文档设计title连续超限，已使用语义重写结果作为最终防御边界: {before} -> {after}",
                before=normalized_title or raw_title,
                after=regenerated_title,
            )
            design["title"] = regenerated_title
            layout_notes = design.get("layoutNotes")
            if isinstance(layout_notes, list):
                layout_notes.append("标题在多次超限后已由系统执行语义重写压缩，未使用截断。")
            logger.info("文档标题/目录设计已生成")
            return design

        raise ValueError("文档标题生成失败：无法得到符合微信标题约束的结果")

    def _parse_response(self, raw: str) -> Dict[str, Any]:
        """
        解析LLM返回的JSON文本，若失败则抛出友好错误。

        使用鲁棒JSON解析器进行多重修复尝试：
        1. 清理markdown标记和思考内容
        2. 本地语法修复（括号平衡、逗号补全、控制字符转义等）
        3. 使用json_repair库进行高级修复
        4. 可选的LLM辅助修复

        参数:
            raw: LLM原始返回字符串，允许带```包裹、思考内容等。

        返回:
            dict: 结构化的设计稿。

        异常:
            ValueError: 当响应为空或JSON解析失败时抛出。
        """
        try:
            result = self.json_parser.parse(
                raw,
                context_name="文档设计",
                # 目录字段已更名为 tocPlan，这里跟随最新Schema校验
                expected_keys=["title", "tocPlan", "hero", "summaryPack"],
            )
            # 验证关键字段的类型，标题长度约束由 run() 中的重生成流程统一处理
            raw_title = result.get("title")
            if not isinstance(raw_title, str):
                logger.warning("文档设计缺少title字段或类型错误，使用空标题等待后续重生成")
                result["title"] = ""
            else:
                result["title"] = _normalize_title_text(raw_title)

            # 处理tocPlan字段
            toc_plan = result.get("tocPlan", [])
            if not isinstance(toc_plan, list):
                logger.warning("文档设计缺少tocPlan字段或类型错误，使用空列表")
                result["tocPlan"] = []
            else:
                # 清理tocPlan中的description字段
                result["tocPlan"] = self._clean_toc_plan_descriptions(toc_plan)

            if not isinstance(result.get("hero"), dict):
                logger.warning("文档设计缺少hero字段或类型错误，使用空对象")
                result.setdefault("hero", {})

            result["summaryPack"] = self._normalize_summary_pack(result.get("summaryPack"), hero=result.get("hero"))

            return result
        except JSONParseError as exc:
            # 转换为原有的异常类型以保持向后兼容
            raise ValueError(f"文档设计JSON解析失败: {exc}") from exc

    def _clean_toc_plan_descriptions(self, toc_plan: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        清理tocPlan中每个条目的description字段，移除可能的JSON片段。

        参数:
            toc_plan: 原始的目录计划列表

        返回:
            List[Dict[str, Any]]: 清理后的目录计划列表
        """
        import re

        def clean_text(text: Any) -> str:
            """清理文本中的JSON片段"""
            if not text or not isinstance(text, str):
                return ""

            cleaned = text

            # 移除以逗号+空白+{开头的不完整JSON对象
            cleaned = re.sub(r',\s*\{[^}]*$', '', cleaned)

            # 移除以逗号+空白+[开头的不完整JSON数组
            cleaned = re.sub(r',\s*\[[^\]]*$', '', cleaned)

            # 移除孤立的 { 加上后续内容（如果没有匹配的 }）
            open_brace_pos = cleaned.rfind('{')
            if open_brace_pos != -1:
                close_brace_pos = cleaned.rfind('}')
                if close_brace_pos < open_brace_pos:
                    cleaned = cleaned[:open_brace_pos].rstrip(',，、 \t\n')

            # 移除孤立的 [ 加上后续内容（如果没有匹配的 ]）
            open_bracket_pos = cleaned.rfind('[')
            if open_bracket_pos != -1:
                close_bracket_pos = cleaned.rfind(']')
                if close_bracket_pos < open_bracket_pos:
                    cleaned = cleaned[:open_bracket_pos].rstrip(',，、 \t\n')

            # 移除看起来像JSON键值对的片段
            cleaned = re.sub(r',?\s*"[^"]+"\s*:\s*"[^"]*$', '', cleaned)
            cleaned = re.sub(r',?\s*"[^"]+"\s*:\s*[^,}\]]*$', '', cleaned)

            # 清理末尾的逗号和空白
            cleaned = cleaned.rstrip(',，、 \t\n')

            return cleaned.strip()

        cleaned_plan = []
        for entry in toc_plan:
            if not isinstance(entry, dict):
                continue

            # 清理description字段
            if "description" in entry:
                original_desc = entry["description"]
                cleaned_desc = clean_text(original_desc)

                if cleaned_desc != original_desc:
                    logger.warning(
                        f"清理目录项 '{entry.get('display', 'unknown')}' 的description字段中的JSON片段:\n"
                        f"  原文: {original_desc[:100]}...\n"
                        f"  清理后: {cleaned_desc[:100]}..."
                    )
                    entry["description"] = cleaned_desc

            cleaned_plan.append(entry)

        return cleaned_plan
    def _normalize_summary_pack(self, summary_pack: Any, *, hero: Dict[str, Any]) -> Dict[str, str]:
        def clean_text(value: Any) -> str:
            if isinstance(value, dict):
                return ""
            if isinstance(value, list):
                return " ".join(str(item).strip() for item in value if str(item).strip())
            return re.sub(r"\s+", " ", str(value or "")).strip()

        fallback_summary = clean_text((hero or {}).get("summary"))
        if not isinstance(summary_pack, dict):
            return {
                "generic": fallback_summary,
                "short": fallback_summary,
                "wechat": fallback_summary,
                "sourceHint": "hero.summary" if fallback_summary else "",
            }

        generic = clean_text(summary_pack.get("generic"))
        short = clean_text(summary_pack.get("short"))
        wechat = clean_text(summary_pack.get("wechat"))
        source_hint = clean_text(summary_pack.get("sourceHint"))

        if not generic:
            generic = fallback_summary
        if not short:
            short = generic or fallback_summary
        if not wechat:
            wechat = short or generic or fallback_summary
        if not source_hint and fallback_summary:
            source_hint = "hero.summary"

        return {
            "generic": generic,
            "short": short,
            "wechat": wechat,
            "sourceHint": source_hint,
        }


__all__ = ["DocumentLayoutNode"]
