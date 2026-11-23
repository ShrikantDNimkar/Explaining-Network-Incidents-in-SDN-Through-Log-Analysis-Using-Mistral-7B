#!/usr/bin/env python3
"""
Group 11 - Security of SDN Project
Rule-based baseline explanation generator.

Maps recognisable controller state and connectivity measurements to a short
incident description, using only the structured incident record. The baseline
establishes whether Mistral 7B adds diagnostic value beyond straightforward
rules.

Rules, in priority order:
  1. a device with available=false after injection  -> switch failure
  2. missing ring link pair vs baseline              -> link failure
  3. probe pings fail to ONE destination IP only and
     that host is absent from ONOS hosts            -> host disconnection
  4. pings pass but RTT/loss/iperf degrade vs
     baseline threshold                             -> congestion
  5. nothing detected                               -> no incident / normal

Usage:
  python3 baseline_explain.py            # every run that has a record
"""

import glob
import json
import os
import sys
import time

RING_LINKS = {frozenset(p) for p in
              [("s1", "s2"), ("s2", "s3"), ("s3", "s4"), ("s4", "s1")]}
HOST_IPS = {"h1": "10.1.0.1", "h2": "10.1.0.2", "h3": "10.1.0.3",
            "h4": "10.1.0.4", "h5": "10.1.0.5", "h6": "10.1.0.6"}

CATEGORY = "category"
EVIDENCE = "evidence"
CHECKS = "operator_checks"


def _device_down(rec):
    for phase, state in rec.get("controller_state_by_phase", {}).items():
        if phase == "baseline":
            continue
        avail = state.get("devices_available") or {}
        for dev, ok in avail.items():
            if ok is False:
                return dev, phase
    return None, None


def _missing_links(rec):
    phases = rec.get("controller_state_by_phase", {})
    base = {frozenset(p.split("-")) for p in phases.get("baseline", {})
            .get("link_pairs", [])}
    if not base:
        return [], None
    for phase, state in phases.items():
        if phase == "baseline":
            continue
        cur = {frozenset(p.split("-")) for p in state.get("link_pairs", [])}
        missing = base - cur
        if missing:
            return ["-".join(sorted(m)) for m in missing], phase
    return [], None


def _host_vanished(rec):
    phases = rec.get("controller_state_by_phase", {})
    base_hosts = set(phases.get("baseline", {}).get("host_ips", []))
    pings = rec.get("connectivity", {}).get("pings", {})
    failed_dsts = set()
    for label, entries in pings.items():
        if label.startswith("post_inject"):
            for e in entries:
                if e["loss_pct"] >= 90:
                    failed_dsts.add(e["dst"])
    for phase, state in phases.items():
        if phase == "baseline":
            continue
        gone = base_hosts - set(state.get("host_ips", []))
        for ip in gone:
            if ip in failed_dsts:
                return ip, phase
    return None, None


def _degraded(rec):
    pings = rec.get("connectivity", {}).get("pings", {})
    base_rtt, post_rtt = [], []
    base_loss, post_loss = [], []
    for label, entries in pings.items():
        for e in entries:
            (base_rtt if label == "baseline" else
             post_rtt if label.startswith("post_inject") else []).append(
                float(e.get("avg_rtt_ms") or 0))
            (base_loss if label == "baseline" else
             post_loss if label.startswith("post_inject") else []).append(
                float(e.get("loss_pct") or 0))
    iperfs = rec.get("connectivity", {}).get("iperf", [])
    base_tput = [i["throughput_mbps"] for i in iperfs
                 if i["label"] == "baseline_iperf"]
    post_tput = [i["throughput_mbps"] for i in iperfs
                 if i["label"] == "post_inject_iperf"]
    reasons = []
    if post_rtt and base_rtt and max(post_rtt) > 5 * max(max(base_rtt), 1):
        reasons.append("RTT increased from ~{:.0f} ms to ~{:.0f} ms".format(
            max(base_rtt), max(post_rtt)))
    if post_loss and min(post_loss) > 5:
        reasons.append("ping loss reached {}%".format(min(post_loss)))
    if post_tput and base_tput and min(post_tput) < 0.5 * max(base_tput):
        reasons.append("TCP throughput dropped from {:.2f} to {:.2f} Mbit/s".format(
            max(base_tput), min(post_tput)))
    return reasons


def explain(record):
    dev, phase = _device_down(record)
    if dev:
        return {
            CATEGORY: "switch_failure",
            "network_impact": "The controller lost the OpenFlow device {}; "
                              "traffic needing that switch is interrupted.".format(dev),
            "likely_cause": "Switch stopped or lost its control channel "
                            "(device unavailable in phase {}).".format(phase),
            EVIDENCE: ["ONOS device {} available=false".format(dev)],
            CHECKS: ["Check the switch process/service on the Mininet host",
                     "Look for control-channel errors in the Karaf log"],
        }

    links, phase = _missing_links(record)
    if links:
        return {
            CATEGORY: "link_failure",
            "network_impact": "Switch-to-switch link(s) {} left the topology; "
                              "traffic must use the redundant path.".format(
                                  ", ".join(links)),
            "likely_cause": "A switch-to-switch link was disabled.",
            EVIDENCE: ["link pairs {} absent in phase {}".format(links, phase)],
            CHECKS: ["Verify interface state on both endpoints with ip link",
                     "Confirm the alternate path carries the traffic "
                     "(tracepath / flow counters)"],
        }

    ip, phase = _host_vanished(record)
    if ip:
        host = [h for h, a in HOST_IPS.items() if a == ip][0]
        return {
            CATEGORY: "host_disconnection",
            "network_impact": "Host {} ({}) stopped responding.".format(host, ip),
            "likely_cause": "The host interface went down or the host was "
                            "removed from the ONOS host store.",
            EVIDENCE: ["{} absent from hosts in phase {}".format(ip, phase),
                       "ping loss >= 90% to {}".format(ip)],
            CHECKS: ["Check the host interface state (ip link)",
                     "Check host link/cable in the topology"],
        }

    reasons = _degraded(record)
    if reasons:
        return {
            CATEGORY: "congestion",
            "network_impact": "Traffic is degraded but not interrupted.",
            "likely_cause": "Competing traffic on a constrained link "
                            "(delay/loss/throughput degradation).",
            EVIDENCE: reasons,
            CHECKS: ["Inspect switch port counters for the busy link",
                     "Repeat iperf3 to confirm sustained degradation"],
        }

    return {
        CATEGORY: "no_incident_detected",
        "network_impact": "No fault indicators found in the record.",
        "likely_cause": "No recognisable incident pattern; evidence may be "
                        "insufficient for a stronger statement.",
        EVIDENCE: [],
        CHECKS: ["None required for the observed evidence"],
    }


def main():
    targets = sys.argv[1:] or sorted(glob.glob(os.path.join("runs", "*_r*")))
    for run_dir in targets:
        rec_path = os.path.join(run_dir, "incident_record.json")
        if not os.path.exists(rec_path):
            continue
        record = json.load(open(rec_path))
        t0 = time.time()
        out = explain(record)
        elapsed_ms = int((time.time() - t0) * 1000)
        dest = os.path.join(run_dir, "explanations")
        os.makedirs(dest, exist_ok=True)
        with open(os.path.join(dest, "baseline.json"), "w") as fh:
            json.dump({"condition": "baseline", "elapsed_ms": elapsed_ms,
                       "explanation": out}, fh, indent=2)
        print("{}: {} ({} ms)".format(record["run_id"], out[CATEGORY],
                                      elapsed_ms))


if __name__ == "__main__":
    main()
