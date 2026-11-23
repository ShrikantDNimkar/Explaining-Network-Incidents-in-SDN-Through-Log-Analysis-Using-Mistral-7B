#!/usr/bin/env python3
"""
Group 11 - Security of SDN Project
Mistral 7B (Ollama) incident explanation generator.

Runs a locally deployed, instruction-tuned Mistral 7B model via the Ollama
REST API and produces an explanation for each incident under two conditions:
  A) mistral_raw        - prompt contains raw Karaf log excerpts + ping summaries
  B) mistral_structured - prompt contains the preprocessed JSON incident record

The prompt template is fixed for repeatability. The model must separate
observed events from possible explanations and acknowledge insufficient
evidence. No fine-tuning is performed.

Deployment notes:
  - When the scripts run in the Docker Desktop lab container and Ollama runs
    natively on the host, use OLLAMA_URL=http://host.docker.internal:11434
    (or the --ollama-url flag). Default is http://127.0.0.1:11434.
  - Set OLLAMA_HOST=0.0.0.0 on the host machine so the container can reach it.

Usage:
  python3 mistral_explain.py                     # every run
  python3 mistral_explain.py runs/link_failure_r01
  OLLAMA_URL=http://host.docker.internal:11434 python3 mistral_explain.py
"""

import argparse
import glob
import json
import os
import socket
import time
import urllib.error
import urllib.request

OLLAMA_URL = os.environ.get(
    "OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/") + "/api/chat"
DEFAULT_MODEL = os.environ.get("OLLAMA_MODEL", "mistral")

SYSTEM_PROMPT = """You are a network incident analyst for a small SDN testbed.
The network has 4 OpenFlow 1.3 switches (s1, s2, s3, s4) in a ring and 6 hosts
(h1 10.1.0.1, h2 10.1.0.2, h3 10.1.0.3, h4 10.1.0.4, h5 10.1.0.5, h6 10.1.0.6)
managed by an ONOS controller. You are given evidence from one observation
window that may or may not contain an incident. Possible incident categories
are: link_failure, switch_failure, congestion, host_disconnection,
forwarding_misconfig, traffic_flood, or no_incident (evidence may also be
insufficient).

Answer ONLY with a JSON object with these keys:
- "incident_category": one of the categories above, or "insufficient_evidence"
- "observed_events": list of facts you can see in the evidence
- "network_impact": which hosts/paths are affected, based ONLY on evidence
- "likely_cause": the most probable explanation, marked as explanation
- "evidence_cited": short quotes or references that support your reasoning
- "operator_checks": 2-4 concrete next steps for the operator
- "uncertainty": what the evidence does NOT show; say so explicitly

Rules: never invent events, hosts, links, timestamps or measurements that are
not in the evidence. Distinguish clearly between observed facts and
explanations. If the evidence is insufficient for a conclusion, say so in
"uncertainty" and choose "insufficient_evidence" or "no_incident" honestly."""


def chat(model, user_msg, temperature=0.0, url=None):
    payload = json.dumps({
        "model": model,
        "stream": False,
        "options": {"temperature": temperature, "num_ctx": 4096,
                    "num_predict": 700},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
    }).encode()
    req = urllib.request.Request(url or OLLAMA_URL, data=payload,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=int(os.environ.get("MISTRAL_TIMEOUT_S", "1800"))) as resp:
        data = json.loads(resp.read().decode())
    elapsed = time.time() - t0
    return data["message"]["content"], elapsed, data.get("eval_count", 0)


def build_raw_prompt(record):
    """Condition A evidence: verbatim excerpts + measurement summary."""
    excerpt = "\n".join(record.get("raw_log_excerpt", [])[:80])
    pings = record.get("connectivity", {}).get("pings", {})
    ping_lines = []
    for label, entries in pings.items():
        for e in entries:
            ping_lines.append("{}: {} -> {} loss={}% rtt={}".format(
                label, e.get("src"), e.get("dst"),
                e.get("loss_pct"), e.get("avg_rtt_ms")))
    iperf_lines = []
    for i in record.get("connectivity", {}).get("iperf", []):
        iperf_lines.append("{}: tput={} lost={}% retrans={}".format(
            i.get("label"), i.get("throughput_mbps"),
            i.get("lost_pct"), i.get("retransmits")))
    return ("Evidence for run {}: raw controller log excerpt and measurements "
            "follow. Analyse the incident.\n\n--- RAW LOG EXCERPT ---\n{}\n\n"
            "--- PING MEASUREMENTS ---\n{}\n\n--- IPERF3 MEASUREMENTS ---\n{}\n"
            .format(record.get("run_id"), excerpt or "(no signal lines captured)",
                    "\n".join(ping_lines) or "(none)",
                    "\n".join(iperf_lines) or "(none)"))


def build_structured_prompt(record):
    """Condition B evidence: the preprocessed JSON record (without excerpts)."""
    slim = {k: v for k, v in record.items() if k != "raw_log_excerpt"}
    return ("Evidence for run {}: a structured incident record in JSON follows. "
            "Analyse the incident.\n\n"
            "--- STRUCTURED INCIDENT RECORD (JSON) ---\n{}"
            .format(record.get("run_id"),
                    json.dumps(slim, indent=1)[:9000]))


def save(run_dir, condition, explanation, elapsed, evals):
    dest = os.path.join(run_dir, "explanations")
    os.makedirs(dest, exist_ok=True)
    with open(os.path.join(dest, "{}.json".format(condition)), "w") as fh:
        json.dump({
            "condition": condition, "elapsed_ms": int(elapsed * 1000),
            "eval_count_tokens": evals, "explanation_text": explanation,
        }, fh, indent=2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dirs", nargs="*")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--ollama-url", default=None,
                    help="Ollama base URL, e.g. http://host.docker.internal:11434 "
                         "(default: env OLLAMA_URL or http://127.0.0.1:11434)")
    ap.add_argument("--condition", choices=["raw", "structured", "both"],
                    default="both")
    args = ap.parse_args()

    url = args.ollama_url.rstrip("/") + "/api/chat" if args.ollama_url else None

    targets = args.run_dirs or sorted(glob.glob(os.path.join("runs", "*_r*")))
    for run_dir in targets:
        rec_path = os.path.join(run_dir, "incident_record.json")
        if not os.path.exists(rec_path):
            continue
        record = json.load(open(rec_path))
        conditions = {
            "raw": ("mistral_raw", build_raw_prompt),
            "structured": ("mistral_structured", build_structured_prompt),
        }
        todo = (["raw", "structured"] if args.condition == "both"
                else [args.condition])
        for key in todo:
            name, builder = conditions[key]
            try:
                text, elapsed, evals = chat(args.model, builder(record), url=url)
                save(run_dir, name, text, elapsed, evals)
                print("{} [{}]: {:.1f}s".format(record["run_id"], name, elapsed))
            except (urllib.error.URLError, socket.timeout, KeyError, ValueError) as exc:
                print("{} [{}]: FAILED - is Ollama running at {}? ({})".format(
                    record["run_id"], name, (args.ollama_url or OLLAMA_URL), exc))


if __name__ == "__main__":
    main()
