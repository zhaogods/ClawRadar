import argparse
import importlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

REPO_MARKERS = (
    ("clawradar", "orchestrator.py"),
    ("run_openclaw_deliverable.py",),
)

REAL_SOURCE_MINIMAL_MODULES = (
    "httpx",
    "sqlalchemy",
    "loguru",
    "pydantic",
    "pydantic_settings",
    "dotenv",
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the ClawRadar topic radar workflow from the skill wrapper")
    parser.add_argument("--repo-root", default="", help="Repository root containing clawradar/ and run_openclaw_deliverable.py")
    parser.add_argument("--payload-file", default="", help="Path to a full JSON payload file")
    parser.add_argument(
        "--input-mode",
        choices=["real_source", "user_topic", "inline_candidates", "inline_normalized", "inline_topic_cards"],
        default="user_topic",
    )
    parser.add_argument("--topic", default="")
    parser.add_argument("--company", default="")
    parser.add_argument("--track", default="")
    parser.add_argument("--summary", default="")
    parser.add_argument("--keywords", nargs="*", default=[])
    parser.add_argument("--source-ids", nargs="*", default=["weibo"])
    parser.add_argument("--topic-candidates-file", default="", help="Path to a JSON file containing topic_candidates")
    parser.add_argument("--normalized-events-file", default="", help="Path to a JSON file containing normalized_events")
    parser.add_argument("--topic-cards-file", default="", help="Path to a JSON file containing topic_cards")
    parser.add_argument("--scored-events-file", default="", help="Path to a JSON file containing scored_events")
    parser.add_argument("--content-bundle-file", default="", help="Path to a JSON file containing one content_bundle")
    parser.add_argument("--content-bundles-file", default="", help="Path to a JSON file containing content_bundles")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--request-id", default="req-clawradar-topic-radar")
    parser.add_argument("--trigger-source", default="manual")
    parser.add_argument("--execution-mode", default="full_pipeline")
    parser.add_argument("--write-executor", default="external_writer")
    parser.add_argument("--delivery-target-mode", default="archive_only")
    parser.add_argument("--delivery-target", default="archive://clawradar")
    parser.add_argument("--delivery-channel", default="")
    parser.add_argument("--decision-status", default="")
    parser.add_argument("--runs-root", default="")
    parser.add_argument("--check-only", action="store_true", help="Run environment preflight only and print the readiness report")
    parser.add_argument("--skip-preflight", action="store_true", help="Skip the skill preflight checks and run the workflow directly")
    parser.add_argument("--full-result", action="store_true", help="Print the full workflow result instead of a compact summary")
    return parser.parse_args()


def _looks_like_repo_root(path: Path) -> bool:
    return (path / "clawradar" / "orchestrator.py").is_file() and (path / "run_openclaw_deliverable.py").is_file()


def _find_repo_root(start: Path) -> Path | None:
    current = start.resolve()
    for candidate in [current, *current.parents]:
        if _looks_like_repo_root(candidate):
            return candidate
    return None


def _resolve_repo_root(cli_value: str) -> Path:
    if cli_value:
        candidate = Path(cli_value).resolve()
        if _looks_like_repo_root(candidate):
            return candidate
        raise SystemExit(f"--repo-root does not point to a ClawRadar repository: {candidate}")

    env_value = os.environ.get("CLAWRADAR_REPO_ROOT", "").strip()
    if env_value:
        candidate = Path(env_value).resolve()
        if _looks_like_repo_root(candidate):
            return candidate
        raise SystemExit(f"CLAWRADAR_REPO_ROOT does not point to a ClawRadar repository: {candidate}")

    cwd_match = _find_repo_root(Path.cwd())
    if cwd_match is not None:
        return cwd_match

    script_match = _find_repo_root(Path(__file__).resolve().parent)
    if script_match is not None:
        return script_match

    raise SystemExit(
        "Could not locate the ClawRadar repository root. Run this script from inside the repository, "
        "or pass --repo-root, or set CLAWRADAR_REPO_ROOT."
    )


def _load_orchestrator(repo_root: Path):
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    from clawradar.orchestrator import topic_radar_orchestrate

    return topic_radar_orchestrate


def _load_json(path: str) -> Any:
    payload_path = Path(path).resolve()
    return json.loads(payload_path.read_text(encoding="utf-8"))


def _selected_input_mode(payload: Dict[str, Any], args: argparse.Namespace) -> str:
    entry_options = payload.get("entry_options") if isinstance(payload.get("entry_options"), dict) else {}
    input_options = entry_options.get("input") if isinstance(entry_options.get("input"), dict) else {}
    selected = str(input_options.get("mode") or "").strip()
    if selected:
        return selected
    if isinstance(payload.get("user_topic"), dict):
        return "user_topic"
    if payload.get("topic_cards"):
        return "inline_topic_cards"
    if payload.get("normalized_events"):
        return "inline_normalized"
    if payload.get("topic_candidates"):
        return "inline_candidates"
    return args.input_mode


def _selected_write_executor(payload: Dict[str, Any], args: argparse.Namespace) -> str:
    entry_options = payload.get("entry_options") if isinstance(payload.get("entry_options"), dict) else {}
    write_options = entry_options.get("write") if isinstance(entry_options.get("write"), dict) else {}
    return str(write_options.get("executor") or args.write_executor or "external_writer").strip()


def _has_inline_artifacts_in_payload(payload: Dict[str, Any]) -> bool:
    return any(
        [
            payload.get("topic_candidates"),
            payload.get("normalized_events"),
            payload.get("topic_cards"),
            payload.get("scored_events"),
            payload.get("content_bundle"),
            payload.get("content_bundles"),
        ]
    )


def _needs_real_source(payload: Dict[str, Any], args: argparse.Namespace) -> bool:
    execution_mode = str(args.execution_mode or payload.get("execution_mode") or "full_pipeline").strip()
    if execution_mode in {"write_only", "deliver_only"}:
        return False
    if execution_mode == "resume" and _has_inline_artifacts_in_payload(payload):
        return False
    return _selected_input_mode(payload, args) in {"real_source", "user_topic"} and not _has_inline_artifacts_in_payload(payload)


def _needs_external_writer(payload: Dict[str, Any], args: argparse.Namespace) -> bool:
    execution_mode = str(args.execution_mode or payload.get("execution_mode") or "full_pipeline").strip()
    if execution_mode in {"crawl_only", "topics_only", "score_only", "deliver_only"}:
        return False
    if execution_mode == "resume" and (payload.get("content_bundle") or payload.get("content_bundles")):
        return False
    return _selected_write_executor(payload, args) == "external_writer"


def _import_check(module_name: str) -> str | None:
    try:
        importlib.import_module(module_name)
        return None
    except Exception as exc:
        return f"{module_name}: {exc}"


def _check_real_source_capability() -> Dict[str, Any]:
    missing = [error for error in (_import_check(module_name) for module_name in REAL_SOURCE_MINIMAL_MODULES) if error]
    capability_error = _import_check("radar_engines.MindSpider.BroadTopicExtraction.get_today_news")
    ok = not missing and capability_error is None
    return {
        "name": "real_source",
        "required": True,
        "ok": ok,
        "message": "real_source capability is ready" if ok else "real_source capability is unavailable",
        "details": missing + ([capability_error] if capability_error else []),
        "install_hints": [
            "python -m pip install httpx sqlalchemy loguru pydantic pydantic-settings python-dotenv",
            "python -m pip install -r radar_engines/requirements.txt",
        ] if not ok else [],
    }


def _check_external_writer_capability() -> Dict[str, Any]:
    details = []
    ok = True
    try:
        from clawradar.writing import _get_report_engine_agent_factory

        _get_report_engine_agent_factory()
    except Exception as exc:
        ok = False
        details.append(str(exc))
    return {
        "name": "external_writer",
        "required": True,
        "ok": ok,
        "message": "external_writer capability is ready" if ok else "external_writer capability is unavailable",
        "details": details,
        "install_hints": [
            "python -m pip install -r radar_engines/requirements.txt",
            "Configure the required API keys in .env or radar_engines/.env before using external_writer.",
        ] if not ok else [],
    }


def _run_preflight(repo_root: Path, payload: Dict[str, Any], args: argparse.Namespace) -> Dict[str, Any]:
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    checks = []
    if _needs_real_source(payload, args):
        checks.append(_check_real_source_capability())
    if _needs_external_writer(payload, args):
        checks.append(_check_external_writer_capability())

    ready = all(item["ok"] for item in checks) if checks else True
    return {
        "ready": ready,
        "repo_root": repo_root.as_posix(),
        "execution_mode": str(args.execution_mode or payload.get("execution_mode") or "full_pipeline").strip(),
        "selected_input_mode": _selected_input_mode(payload, args),
        "selected_write_executor": _selected_write_executor(payload, args),
        "checks": checks,
    }


def _build_base_payload(args: argparse.Namespace) -> Dict[str, Any]:
    return {
        "request_id": args.request_id,
        "trigger_source": args.trigger_source,
        "entry_options": {
            "write": {
                "executor": args.write_executor,
            },
            "delivery": {
                "target_mode": args.delivery_target_mode,
                "target": args.delivery_target,
            },
            "degrade": {
                "input_unavailable": "fail",
                "write_unavailable": "fail",
                "delivery_unavailable": "fail",
            },
        },
    }


def _has_inline_artifacts(args: argparse.Namespace) -> bool:
    return any(
        [
            args.topic_candidates_file,
            args.normalized_events_file,
            args.topic_cards_file,
            args.scored_events_file,
            args.content_bundle_file,
            args.content_bundles_file,
        ]
    )


def _build_payload(args: argparse.Namespace) -> Dict[str, Any]:
    payload = _build_base_payload(args)

    if args.delivery_channel:
        payload["delivery_channel"] = args.delivery_channel

    if args.decision_status:
        payload["decision_status"] = args.decision_status

    # Downstream artifact mode: let the caller continue from existing files.
    if _has_inline_artifacts(args):
        if args.topic_candidates_file:
            payload["topic_candidates"] = _load_json(args.topic_candidates_file)
            payload["entry_options"]["input"] = {"mode": "inline_candidates", "limit": args.limit}
        if args.normalized_events_file:
            payload["normalized_events"] = _load_json(args.normalized_events_file)
            payload["entry_options"]["input"] = {"mode": "inline_normalized", "limit": args.limit}
        if args.topic_cards_file:
            payload["topic_cards"] = _load_json(args.topic_cards_file)
            payload["entry_options"]["input"] = {"mode": "inline_topic_cards", "limit": args.limit}
        if args.scored_events_file:
            payload["scored_events"] = _load_json(args.scored_events_file)
        if args.content_bundle_file:
            payload["content_bundle"] = _load_json(args.content_bundle_file)
            payload.setdefault("decision_status", "publish_ready")
            payload.setdefault("delivery_target", args.delivery_target)
        if args.content_bundles_file:
            payload["content_bundles"] = _load_json(args.content_bundles_file)
            payload.setdefault("decision_status", "publish_ready")
            payload.setdefault("delivery_target", args.delivery_target)
        if args.execution_mode == "deliver_only":
            payload.setdefault("decision_status", "publish_ready")
            payload.setdefault("delivery_target", args.delivery_target)
        return payload

    input_options = {
        "mode": args.input_mode,
        "limit": args.limit,
    }

    if args.input_mode == "real_source":
        input_options["source_ids"] = args.source_ids
    elif args.input_mode == "user_topic":
        input_options.update(
            {
                "topic": args.topic,
                "company": args.company,
                "track": args.track,
                "summary": args.summary,
                "keywords": args.keywords,
            }
        )
        payload["user_topic"] = {
            "topic": args.topic,
            "company": args.company,
            "track": args.track,
            "summary": args.summary,
            "keywords": args.keywords,
        }

    payload["entry_options"]["input"] = input_options
    return payload


def main() -> None:
    args = _parse_args()
    repo_root = _resolve_repo_root(args.repo_root)
    payload = _load_json(args.payload_file) if args.payload_file else _build_payload(args)
    preflight = _run_preflight(repo_root, payload, args)

    if args.check_only:
        print(json.dumps(preflight, ensure_ascii=False, indent=2))
        return

    if not preflight["ready"] and not args.skip_preflight:
        print(json.dumps(preflight, ensure_ascii=False, indent=2))
        raise SystemExit(2)

    topic_radar_orchestrate = _load_orchestrator(repo_root)
    runs_root = Path(args.runs_root) if args.runs_root else None

    result = topic_radar_orchestrate(
        payload,
        execution_mode=args.execution_mode,
        runs_root=runs_root,
    )

    if args.full_result:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    summary = {
        "run_status": result.get("run_status"),
        "final_stage": result.get("final_stage"),
        "decision_status": result.get("decision_status"),
        "output_root": result.get("output_root"),
        "entry_resolution": result.get("entry_resolution"),
        "run_summary": result.get("run_summary"),
        "delivery_receipt": result.get("delivery_receipt"),
        "errors": result.get("errors"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
