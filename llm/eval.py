"""
LLM Classification Eval
=======================
Measures accuracy of the incident classifier against manually-labeled records.

Usage:
    python llm/eval.py

Results are printed to stdout and saved to llm/eval_results.json.
Add ~50 ground-truth records to GROUND_TRUTH below before running.
"""

import json
from collections import defaultdict

from classifier import classify_incident, get_engine
from dotenv import load_dotenv
import instructor
import openai
import os
import pandas as pd
from loguru import logger

load_dotenv()

# ---------------------------------------------------------------------------
# Ground truth — populate with manually labeled incident_ids from your DB
# Format: (incident_id, expected_severity, expected_root_cause)
# ---------------------------------------------------------------------------
GROUND_TRUTH = [
    # ("abc123", "high",     "slip_trip_fall"),
    # ("def456", "critical", "equipment_failure"),
    # ("ghi789", "medium",   "ergonomic"),
    # Add ~47 more...
]


def run_eval():
    if not GROUND_TRUTH:
        logger.warning("GROUND_TRUTH is empty — add labeled records to llm/eval.py first.")
        return

    engine = get_engine()
    client = instructor.from_openai(openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY")))

    ids = [row[0] for row in GROUND_TRUTH]
    placeholders = ", ".join(f"'{i}'" for i in ids)

    df = pd.read_sql(
        f"""
        SELECT f.*, e.establishment_name, e.naics_description
        FROM analytics_marts.fct_incidents f
        JOIN analytics_marts.dim_establishment e USING (establishment_id)
        WHERE f.incident_id IN ({placeholders})
        """,
        engine,
    )

    ground_truth_map = {row[0]: (row[1], row[2]) for row in GROUND_TRUTH}

    severity_correct = 0
    root_cause_correct = 0
    both_correct = 0
    total = 0

    per_class_severity = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    per_class_root = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})

    for _, row in df.iterrows():
        incident_id = row["incident_id"]
        expected_sev, expected_root = ground_truth_map[incident_id]

        try:
            result = classify_incident(client, row.to_dict())
        except Exception as e:
            logger.warning(f"Skipping {incident_id}: {e}")
            continue

        predicted_sev = result["severity"]
        predicted_root = result["root_cause_category"]
        total += 1

        # Accuracy
        sev_ok = predicted_sev == expected_sev
        root_ok = predicted_root == expected_root
        if sev_ok:
            severity_correct += 1
        if root_ok:
            root_cause_correct += 1
        if sev_ok and root_ok:
            both_correct += 1

        # Per-class stats
        for cls in set([expected_sev, predicted_sev]):
            if cls == predicted_sev == expected_sev:
                per_class_severity[cls]["tp"] += 1
            elif cls == predicted_sev:
                per_class_severity[cls]["fp"] += 1
            elif cls == expected_sev:
                per_class_severity[cls]["fn"] += 1

        for cls in set([expected_root, predicted_root]):
            if cls == predicted_root == expected_root:
                per_class_root[cls]["tp"] += 1
            elif cls == predicted_root:
                per_class_root[cls]["fp"] += 1
            elif cls == expected_root:
                per_class_root[cls]["fn"] += 1

    if total == 0:
        logger.error("No matching incidents found in DB for ground truth IDs.")
        return

    results = {
        "n": total,
        "severity_accuracy": round(severity_correct / total, 3),
        "root_cause_accuracy": round(root_cause_correct / total, 3),
        "both_correct_accuracy": round(both_correct / total, 3),
        "per_class_severity": dict(per_class_severity),
        "per_class_root_cause": dict(per_class_root),
    }

    print("\n── EHS LLM Eval Results ──────────────────────────")
    print(f"  n                    : {total}")
    print(f"  Severity accuracy    : {results['severity_accuracy']:.1%}")
    print(f"  Root cause accuracy  : {results['root_cause_accuracy']:.1%}")
    print(f"  Both correct         : {results['both_correct_accuracy']:.1%}")
    print("──────────────────────────────────────────────────\n")

    output_path = "llm/eval_results.json"
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    logger.success(f"Results saved to {output_path}")

    return results


if __name__ == "__main__":
    run_eval()
