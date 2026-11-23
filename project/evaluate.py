#!/usr/bin/env python3
"""
Group 11 - Security of SDN Project
Evaluation: compare the three conditions against ground truth.

  1. baseline           (baseline_explain.py  -> explanations/baseline.json)
  2. mistral_raw        (mistral_explain.py   -> explanations/mistral_raw.json)
  3. mistral_structured (mistral_explain.py   -> explanations/mistral_structured.json)

Metrics per the proposal rubric:
  - incident identification: category matches ground truth (a justified
    "insufficient_evidence"/"no_incident" counts for normal runs)
  - grounding: the affected element(s) from ground truth are named in the
    explanation (0-2, automatic heuristic; human review confirms)
  - unsupported assertions: entities (switches/hosts/links) mentioned that
    never appear in the evidence (automatic heuristic + human review)
  - usefulness and clarity: 1-5, joint human score (template CSV emitted)
  - runtime cost: elapsed ms per explanation

Outputs:
  runs/evaluation_summary.csv    - per-run metric table
  runs/evaluation_comparison.csv - condition-level comparison
  runs/rubric_human_template.csv - blank rubric for both students

Usage:
  python3 evaluate.py
"""

import csv
import glob
import json
import os
import re

RUNS_DIR = "runs"
CONDITIONS = ["baseline", "mistral_raw", "mistral_structured"]
GROUND_TRUTH_CATEGORY = {
    "normal": "no_incident",
    "link_failure": "link_failure",
    "switch_failure": "switch_failure",
    "congestion": "congestion",
    "host_disconnection": "host_disconnection",
    "forwarding_misconfig": "forwarding_misconfig",
    "traffic_flood": "traffic_flood",
}

ENTITY_RE = re.compile(r"\b(s\d+|h\d+|10\.1\.0\.\d+)\b")


def load(path):
    with open(path) as fh:
        return json.load(fh)


def explanation_text(exp):
    if isinstance(exp.get("explanation"), dict):  # baseline
        return json.dumps(exp["explanation"])
    return exp.get("explanation_text", "")


def parse_category(text):
    m = re.search(r'"incident_category"\s*:\s*"([^"]+)"', text)
    if m:
        return m.group(1)
    lowered = text.lower()
    for cat in GROUND_TRUTH_CATEGORY.values():
        if cat in lowered:
            return cat
    return "insufficient_evidence"


def identify_ok(gt_scenario, predicted):
    expected = GROUND_TRUTH_CATEGORY[gt_scenario]
    if expected == "no_incident":
        return predicted in ("no_incident", "no_incident_detected",
                             "insufficient_evidence")
    return predicted == expected


def grounding_score(gt, text):
    affected = set(gt.get("affected_nodes", []))
    if not affected:  # negative control: correct = no strong claim
        strong = re.search(
            r"\b(failure|disconnection|congestion|down|flood|misconfig)", text,
            re.I)
        return 2 if not strong else 0
    hits = sum(1 for a in affected if a.lower() in text.lower())
    if hits == len(affected):
        return 2
    if hits:
        return 1
    return 0


def unsupported_count(record, text):
    mentioned = set(ENTITY_RE.findall(text.lower()))
    evidence_text = json.dumps(record).lower()
    unsupported = [e for e in mentioned if e not in evidence_text]
    return len(unsupported)


def main():
    rows = []
    for run_dir in sorted(glob.glob(os.path.join(RUNS_DIR, "*_r*"))):
        gt_path = os.path.join(run_dir, "ground_truth.json")
        rec_path = os.path.join(run_dir, "incident_record.json")
        if not (os.path.exists(gt_path) and os.path.exists(rec_path)):
            continue
        gt = load(gt_path)
        record = load(rec_path)
        for cond in CONDITIONS:
            exp_path = os.path.join(run_dir, "explanations", cond + ".json")
            row = {
                "run_id": gt["run_id"], "scenario": gt["scenario"],
                "condition": cond,
                "identification_correct": None,
                "grounding_0_2": None,
                "unsupported_assertions": None,
                "usefulness_human_1_5": "",
                "clarity_human_1_5": "",
                "runtime_ms": "", "notes": "",
            }
            if not os.path.exists(exp_path):
                rows.append(row)
                continue
            exp = load(exp_path)
            text = explanation_text(exp)
            predicted = parse_category(text)
            row["predicted_category"] = predicted
            row["identification_correct"] = int(
                identify_ok(gt["scenario"], predicted))
            row["grounding_0_2"] = grounding_score(gt, text)
            row["unsupported_assertions"] = unsupported_count(record, text)
            row["runtime_ms"] = exp.get("elapsed_ms")
            rows.append(row)

    # per-run CSV
    with open(os.path.join(RUNS_DIR, "evaluation_summary.csv"), "w",
              newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else
                           ["run_id"])
        w.writeheader()
        w.writerows(rows)

    # condition comparison
    comparison = []
    for cond in CONDITIONS:
        rs = [r for r in rows if r["condition"] == cond]
        done = [r for r in rs if r["identification_correct"] is not None]
        n = len(done)
        comparison.append({
            "condition": cond,
            "n_runs": len(rs),
            "identification_accuracy_pct": round(
                100.0 * sum(r["identification_correct"] for r in done) / n, 1)
            if n else "",
            "avg_grounding_0_2": round(
                sum(r["grounding_0_2"] for r in done) / n, 2) if n else "",
            "avg_unsupported_assertions": round(
                sum(r["unsupported_assertions"] for r in done) / n, 2)
            if n else "",
            "avg_runtime_ms": round(
                sum(r["runtime_ms"] for r in done) / n, 0) if n else "",
        })
    with open(os.path.join(RUNS_DIR, "evaluation_comparison.csv"), "w",
              newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(comparison[0].keys()))
        w.writeheader()
        w.writerows(comparison)

    # blank human rubric for the two students
    with open(os.path.join(RUNS_DIR, "rubric_human_template.csv"), "w",
              newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["run_id", "condition", "usefulness_1_5 (joint)",
                    "clarity_1_5 (joint)", "unsupported_assertions_confirmed",
                    "notes_evidence_checked"])
        for r in rows:
            w.writerow([r["run_id"], r["condition"], "", "", "", ""])

    print("Per-run metrics written to {}/evaluation_summary.csv".format(RUNS_DIR))
    for c in comparison:
        print(c)
    print("Fill {}/rubric_human_template.csv jointly, then re-run to merge."
          .format(RUNS_DIR))


if __name__ == "__main__":
    main()
