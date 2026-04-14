import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from clawradar.orchestrator import topic_radar_orchestrate


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run OpenClaw one-day deliverable flow")
    parser.add_argument("--input-mode", choices=["real_source", "user_topic"], default="real_source")
    parser.add_argument("--topic", default="")
    parser.add_argument("--company", default="")
    parser.add_argument("--track", default="")
    parser.add_argument("--summary", default="")
    parser.add_argument("--keywords", nargs="*", default=[])
    parser.add_argument("--source-ids", nargs="*", default=["weibo"])
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--request-id", default="req-openclaw-deliverable")
    parser.add_argument("--trigger-source", default="manual")
    parser.add_argument("--execution-mode", default="full_pipeline")
    parser.add_argument("--runs-root", default="")
    return parser.parse_args()


def _build_payload(args: argparse.Namespace) -> dict:
    input_options = {
        "mode": args.input_mode,
        "limit": args.limit,
    }
    if args.input_mode == "real_source":
        input_options["source_ids"] = args.source_ids
    else:
        input_options.update(
            {
                "topic": args.topic,
                "company": args.company,
                "track": args.track,
                "summary": args.summary,
                "keywords": args.keywords,
            }
        )

    payload = {
        "request_id": args.request_id,
        "trigger_source": args.trigger_source,
        "entry_options": {
            "input": input_options,
            "write": {
                "executor": "external_writer",
            },
            "delivery": {
                "target_mode": "archive_only",
                "target": "archive://openclaw_p0",
            },
            "degrade": {
                "input_unavailable": "fail",
                "write_unavailable": "fail",
                "delivery_unavailable": "fail",
            },
        },
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



def main() -> None:
    args = _parse_args()
    payload = _build_payload(args)
    runs_root = Path(args.runs_root) if args.runs_root else None
    result = topic_radar_orchestrate(
        payload,
        execution_mode=args.execution_mode,
        runs_root=runs_root,
    )

    summary = {
        "run_status": result.get("run_status"),
        "final_stage": result.get("final_stage"),
        "decision_status": result.get("decision_status"),
        "output_root": result.get("output_root"),
        "entry_resolution": result.get("entry_resolution"),
        "run_summary": result.get("run_summary"),
        "delivery_receipt": result.get("delivery_receipt"),
        "output_manifest": result.get("output_manifest"),
        "errors": result.get("errors"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
