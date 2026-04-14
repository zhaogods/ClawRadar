import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from clawradar.orchestrator import topic_radar_orchestrate


def main() -> None:
    payload = {
        "request_id": "req-local-real-source-demo",
        "trigger_source": "manual",
        "entry_options": {
            "input": {
                "mode": "real_source",
                "source_ids": ["weibo"],
                "limit": 5,
            },
            "write": {
                "enabled": False,
            },
            "delivery": {
                "enabled": False,
                "target_mode": "archive_only",
            },
            "degrade": {
                "input_unavailable": "fail",
            },
        },
    }

    result = topic_radar_orchestrate(payload)

    summary = {
        "run_status": result.get("run_status"),
        "final_stage": result.get("final_stage"),
        "decision_status": result.get("decision_status"),
        "entry_resolution": result.get("entry_resolution"),
        "artifact_summary": result.get("artifact_summary"),
        "processed_event_ids": result.get("processed_event_ids"),
        "errors": result.get("errors"),
    }

    print("==== SUMMARY ====")
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    print("\n==== SCORED EVENTS ====")
    scored_events = result.get("scored_events", [])
    if not scored_events:
        print("[]")
        return

    for event in scored_events:
        print(json.dumps({
            "event_id": event.get("event_id"),
            "event_title": event.get("event_title"),
            "status": event.get("status"),
            "scorecard": event.get("scorecard"),
            "source_url": event.get("trace", {}).get("source_url"),
            "source_type": event.get("trace", {}).get("source_type"),
        }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
