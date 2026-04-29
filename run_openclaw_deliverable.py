import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from clawradar.orchestrator import topic_radar_orchestrate
from clawradar.publish_only import publish_existing_output


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
    parser.add_argument("--delivery-channel", choices=["archive_only", "feishu", "wechat"], default="archive_only")
    parser.add_argument("--delivery-target", default="")
    parser.add_argument("--notification-channel", choices=["", "pushplus"], default="")
    parser.add_argument("--notification-target", default="")
    parser.add_argument("--notify-on", nargs="*", default=[])
    parser.add_argument("--pushplus-token", default="")
    parser.add_argument("--publish-only", action="store_true")
    parser.add_argument("--publish-file", default="")
    parser.add_argument("--target-event-id", default="")
    parser.add_argument("--force-republish", action="store_true")
    return parser.parse_args()


def _build_notification_options(args: argparse.Namespace) -> dict:
    options: dict = {}
    pushplus_token = str(getattr(args, "pushplus_token", "") or "").strip()
    if pushplus_token:
        options["pushplus"] = {"token": pushplus_token}
    return options


def _build_payload(args: argparse.Namespace) -> dict:
    delivery_channel = getattr(args, "delivery_channel", "archive_only")
    delivery_target = getattr(args, "delivery_target", "")
    notification_channel = str(getattr(args, "notification_channel", "") or "").strip()
    notification_target = str(getattr(args, "notification_target", "") or "").strip()
    notify_on = list(getattr(args, "notify_on", []) or [])
    notification_options = _build_notification_options(args)
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

    entry_options = {
        "input": input_options,
        "write": {
            "executor": "external_writer",
        },
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
    if notification_channel or notification_target or notify_on or notification_options:
        entry_options["notification"] = {
            "channel": notification_channel,
            "target": notification_target,
            "notify_on": notify_on,
            **notification_options,
        }

    payload = {
        "request_id": args.request_id,
        "trigger_source": args.trigger_source,
        "entry_options": entry_options,
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
    runs_root = Path(args.runs_root) if args.runs_root else None
    notification_options = _build_notification_options(args)
    if args.publish_only:
        result = publish_existing_output(
            runs_root=runs_root,
            publish_file=Path(args.publish_file) if args.publish_file else None,
            delivery_channel=args.delivery_channel,
            delivery_target=args.delivery_target,
            target_event_id=args.target_event_id or None,
            force_republish=args.force_republish,
            notification_channel=args.notification_channel or None,
            notification_target=args.notification_target or None,
            notification_options=notification_options or None,
            notify_on=args.notify_on or None,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    payload = _build_payload(args)
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
        "notification_result": result.get("notification_result"),
        "notification_receipt": result.get("notification_receipt"),
        "output_manifest": result.get("output_manifest"),
        "errors": result.get("errors"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
