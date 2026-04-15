import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

REPO_ROOT = Path(__file__).resolve().parents[3]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from clawradar.orchestrator import topic_radar_orchestrate


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the ClawRadar topic radar workflow from the skill wrapper")
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
    parser.add_argument("--request-id", default="req-openclaw-topic-radar")
    parser.add_argument("--trigger-source", default="manual")
    parser.add_argument("--execution-mode", default="full_pipeline")
    parser.add_argument("--write-executor", default="external_writer")
    parser.add_argument("--delivery-target-mode", default="archive_only")
    parser.add_argument("--delivery-target", default="archive://clawradar")
    parser.add_argument("--delivery-channel", default="")
    parser.add_argument("--decision-status", default="")
    parser.add_argument("--runs-root", default="")
    parser.add_argument("--full-result", action="store_true", help="Print the full workflow result instead of a compact summary")
    return parser.parse_args()


def _load_json(path: str) -> Any:
    payload_path = Path(path).resolve()
    return json.loads(payload_path.read_text(encoding="utf-8"))


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
    payload = _load_json(args.payload_file) if args.payload_file else _build_payload(args)
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
