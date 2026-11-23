#!/usr/bin/env python3
"""
Group 11 - Security of SDN Project
Log preprocessing: turn raw evidence into a short structured JSON record.

For every run directory it reads:
  raw/rest_baseline.json, raw/rest_post_inject_*.json, raw/rest_recovery.json
  raw/karaf_window.log, raw/ovs_post_inject_*.txt, raw/probes.json

and writes incident_record.json: timestamp-aligned events, de-duplicated
controller messages, device/link/host summaries, connectivity measurements
and flow statistics. Original raw excerpts are kept in the record so model
explanations can be checked against the source material.

Usage:
  python3 preprocess_logs.py            # process every run under runs/
  python3 preprocess_logs.py runs/link_failure_r01
"""

import glob
import json
import os
import re
import sys

from collect_evidence import (onos_device_availability, onos_host_ips,
                              onos_link_pairs)

# Controller/Karaf log lines that carry incident signal. Broad on purpose:
# ONOS builds log different details per version, so we keep the patterns
# generic and store the matched line verbatim for verification.
SIGNAL_PATTERNS = [
    r"(?i)device.*(?:disconnect|unavailable|removed|down)",
    r"(?i)(?:link|edge).*(?:down|removed|failed|lost)",
    r"(?i)(?:host).*(?:removed|down|failed|detached)",
    r"(?i)topology.*(?:change|event)",
    r"(?i)(?:flow).*(?:failed|error|removed)",
    r"(?i)(?:exception|error|warn).*(?:device|switch|port|channel)",
]

NOISE_PATTERNS = [
    r"^\s*$",
    r"(?:DEBUG|TRACE)",
    r"(?:lifecycle|component|activator|feature|karaf|shell)",
]


def load_json(path):
    with open(path) as fh:
        return json.load(fh)


def parse_karaf(path):
    """Extract signal lines from the Karaf log window, de-duplicated."""
    if not os.path.exists(path):
        return []
    signal = [re.compile(p, re.I) for p in SIGNAL_PATTERNS]
    noise = [re.compile(p, re.I) for p in NOISE_PATTERNS]
    seen, events = set(), []
    with open(path, errors="replace") as fh:
        for line in fh:
            line = line.rstrip()
            if not line or any(n.search(line) for n in noise):
                continue
            if not any(s.search(line) for s in signal):
                continue
            m = re.match(r"(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}[.,]?\d*)", line)
            ts = m.group(1) if m else ""
            key = re.sub(r"[\d.:]+", "", line)[-120:]
            if key in seen:
                continue
            seen.add(key)
            events.append({"timestamp": ts, "message": line[:400]})
    return events[:60]  # cap the structured record size


def parse_ovs_phases(raw_dir):
    """Total flow count and drop rules per phase, per switch."""
    summary = {}
    for path in sorted(glob.glob(os.path.join(raw_dir, "ovs_post_inject_*.txt"))):
        phase = re.search(r"ovs_(post_inject_[\w]+)\.txt", path).group(1)
        text = open(path, errors="replace").read()
        flows = {}
        for sw in ("s1", "s2", "s3", "s4"):
            section = re.search(
                r"===== flows_{} =====\n(.*?)(?=\n=====|\Z)".format(sw),
                text, re.S)
            body = section.group(1) if section else ""
            rules = [ln for ln in body.splitlines() if "cookie=" in ln]
            flows[sw] = {
                "total_rules": len(rules),
                "drop_rules": sum(1 for r in rules if ",action" not in r
                                  or "actions=drop" in r or "drop" in r),
            }
        summary[phase] = flows
    return summary


def rest_phase_summaries(raw_dir):
    """Availability / links / hosts per REST phase."""
    out = {}
    for phase in ("baseline", "post_inject_10s", "post_inject_30s",
                  "post_inject_50s", "recovery"):
        path = os.path.join(raw_dir, "rest_{}.json".format(phase))
        if not os.path.exists(path):
            continue
        snap = load_json(path)["state"]
        out[phase] = {
            "devices_available": onos_device_availability(snap),
            "link_pairs": sorted(
                ["-".join(sorted(p)) for p in onos_link_pairs(snap)]),
            "host_ips": sorted(onos_host_ips(snap)),
            "flow_count_total": len(
                ((snap.get("flows") or {}).get("flows") or [])),
        }
    return out


def connectivity_summary(raw_dir):
    path = os.path.join(raw_dir, "probes.json")
    if not os.path.exists(path):
        return {}
    probes = load_json(path)
    pings, iperfs = {}, []
    for p in probes:
        if "loss_pct" in p:
            pings.setdefault(p.get("label"), []).append(
                {"src": p["src"], "dst": p["dst"], "loss_pct": p["loss_pct"],
                 "avg_rtt_ms": p.get("avg_rtt_ms")})
        else:
            iperfs.append({"label": p.get("label"),
                           "throughput_mbps": p.get("throughput_mbps"),
                           "lost_pct": p.get("lost_pct"),
                           "retransmits": p.get("retransmits"),
                           "udp": p.get("udp", False)})
    return {"pings": pings, "iperf": iperfs}


def build_record(run_dir):
    raw_dir = os.path.join(run_dir, "raw")

    # raw excerpt condition: last 80 signal-bearing lines, verbatim
    karaf_events = parse_karaf(os.path.join(raw_dir, "karaf_window.log"))
    record = {
        "run_id": os.path.basename(run_dir.rstrip("/")),
        "karaf_events": karaf_events,
        "controller_state_by_phase": rest_phase_summaries(raw_dir),
        "ovs_flow_summary": parse_ovs_phases(raw_dir),
        "connectivity": connectivity_summary(raw_dir),
        "raw_log_excerpt": [e["message"] for e in karaf_events[:80]],
    }
    out = os.path.join(run_dir, "incident_record.json")
    with open(out, "w") as fh:
        json.dump(record, fh, indent=2)
    return out


def main():
    if len(sys.argv) > 1:
        targets = [sys.argv[1]]
    else:
        targets = sorted(glob.glob(os.path.join("runs", "*_r*")))
    for run_dir in targets:
        if not os.path.isdir(run_dir):
            continue
        out = build_record(run_dir)
        n = len(json.load(open(out))["karaf_events"])
        print("processed {}: {} signal events -> {}".format(
            os.path.basename(run_dir), n, out))


if __name__ == "__main__":
    main()
