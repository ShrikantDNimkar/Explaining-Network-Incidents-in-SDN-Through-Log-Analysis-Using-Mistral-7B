#!/usr/bin/env python3
"""
Group 11 - Security of SDN Project
Incident generation and evidence collection orchestrator.

Builds the Group 11 topology, then executes the experiment matrix from the
proposal:
  - 4 core incident scenarios x 6 runs with varied parameters = 24 incidents
  - 6 normal-operation runs (negative controls)
  - optional scenarios (forwarding misconfig, traffic flood) behind --optional

For every run it stores the injected fault separately from the evidence shown
to the model (ground_truth.json), and writes raw evidence to runs/<run_id>/raw/.

Prerequisites (see README.md / LOCAL_SETUP.md):
  - ONOS container running at 10.0.0.10 on Docker network sdn-net
  - org.onosproject.openflow-base, org.onosproject.openflow, org.onosproject.fwd ACTIVE
  - iperf3 installed in the environment (hosts inherit it)

Usage:
  sudo python3 run_experiment.py                 # full matrix (30 runs)
  sudo python3 run_experiment.py --scenario link_failure --runs 1
  sudo python3 run_experiment.py --optional      # also run the 2 optional cases
"""

import argparse
import json
import os
import time

from mininet.log import setLogLevel
from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch

from collect_evidence import (app_log, iperf_tcp, ping_pair, sh,
                              snapshot_karaf, snapshot_onos, snapshot_ovs)
from topo_group11 import Group11Topo, HOSTS

RUNS_DIR = "runs"

# Probe traffic: two host pairs that traverse the ring in both directions.
PROBE_PAIRS = [("h1", "10.1.0.4"), ("h2", "10.1.0.3")]
IPERF_PORT = 5201

# ------------------------------------------------------------------ scenario tables

LINK_VARIANTS = [
    {"link": ("s1", "s2")},
    {"link": ("s2", "s3")},
    {"link": ("s3", "s4")},
    {"link": ("s4", "s1")},
    {"link": ("s1", "s2")},
    {"link": ("s3", "s4")},
]

SWITCH_VARIANTS = [
    {"switch": "s2", "isolates": ["h2", "h5"]},
    {"switch": "s3", "isolates": ["h3", "h6"]},
    {"switch": "s4", "isolates": ["h4"]},
    {"switch": "s2", "isolates": ["h2", "h5"]},
    {"switch": "s3", "isolates": ["h3", "h6"]},
    {"switch": "s4", "isolates": ["h4"]},
]

CONGESTION_VARIANTS = [
    {"intf": "s2-eth1", "delay_ms": 100, "loss_pct": 5},
    {"intf": "s2-eth1", "delay_ms": 200, "loss_pct": 10},
    {"intf": "s1-eth1", "delay_ms": 100, "loss_pct": 5},
    {"intf": "s1-eth1", "delay_ms": 200, "loss_pct": 10},
    {"intf": "s3-eth1", "delay_ms": 150, "loss_pct": 8},
    {"intf": "s3-eth1", "delay_ms": 250, "loss_pct": 15},
]

HOST_VARIANTS = [
    {"host": "h5"}, {"host": "h6"}, {"host": "h1"},
    {"host": "h4"}, {"host": "h2"}, {"host": "h3"},
]

MISCONFIG_VARIANTS = [
    {"switch": "s2", "victim": "h5"},
    {"switch": "s3", "victim": "h6"},
    {"switch": "s2", "victim": "h5"},
    {"switch": "s1", "victim": "h1"},
    {"switch": "s3", "victim": "h3"},
]

FLOOD_VARIANTS = [
    {"src": "h5", "pps": 300}, {"src": "h5", "pps": 600},
    {"src": "h6", "pps": 300}, {"src": "h2", "pps": 300},
    {"src": "h6", "pps": 600},
]


# ------------------------------------------------------------------ helpers

def wait(seconds, out_dir, why):
    app_log(out_dir, "wait {}s ({})".format(seconds, why))
    time.sleep(seconds)


def probes(net, out_dir, probes_log, label):
    for src, dst_ip in PROBE_PAIRS:
        entry = ping_pair(net, src, dst_ip)
        entry["label"] = label
        probes_log.append(entry)
        app_log(out_dir, "ping {}->{} [{}] loss={}%".format(
            src, dst_ip, label, entry["loss_pct"]))
    return probes_log


def evidence_pass(net, out_dir, raw_dir, phase, switches=("s1", "s2", "s3", "s4")):
    snapshot_onos(raw_dir, phase)
    snapshot_ovs(raw_dir, phase, list(switches))
    app_log(out_dir, "evidence snapshot phase {}".format(phase))


# ------------------------------------------------------------------ injections

def inject_and_restore(kind, variant, net):
    """Return (inject_fn, restore_fn, description). All restore cleanly."""
    if kind == "link_failure":
        a, b = variant["link"]

        def do_inject():
            net.configLinkStatus(a, b, "down")

        def do_restore():
            net.configLinkStatus(a, b, "up")
        return do_inject, do_restore, "link {}-{}".format(a, b)

    if kind == "switch_failure":
        sw = variant["switch"]

        def do_inject():
            net.get(sw).stop()

        def do_restore():
            net.get(sw).start(net.controllers)
        return do_inject, do_restore, "switch {}".format(sw)

    if kind == "congestion":
        # handled by congestion_case() because the injected state combines
        # a tc netem constraint with a competing UDP flow
        raise ValueError("congestion is handled by congestion_case()")

    if kind == "host_disconnection":
        host = variant["host"]

        def do_inject():
            net.get(host).cmd("ip link set {}-eth0 down".format(host))

        def do_restore():
            net.get(host).cmd("ip link set {}-eth0 up".format(host))
        return do_inject, do_restore, "host {}".format(host)

    if kind == "forwarding_misconfig":
        sw, victim = variant["switch"], variant["victim"]
        victim_ip = HOSTS[victim][0].split("/")[0]

        def do_inject():
            sh("ovs-ofctl -O OpenFlow13 add-flow {sw} "
               "'priority=50000,ip,nw_src={ip},actions=drop'".format(sw=sw, ip=victim_ip))

        def do_restore():
            sh("ovs-ofctl -O OpenFlow13 del-flows {sw} "
               "'priority=50000,ip,nw_src={ip}'".format(sw=sw, ip=victim_ip))
        return do_inject, do_restore, "drop rule on {} for {}".format(sw, victim_ip)

    if kind == "traffic_flood":
        src, pps = variant["src"], variant["pps"]
        script = (
            "python3 -c \"import time, random\n"
            "from scapy.all import IP,UDP,Ether,sendp\n"
            "for _ in range({pps}*10):\n"
            "    sendp(Ether()/IP(src='10.1.0.{n}',dst='10.1.0.255')/"
            "UDP(dport=random.randint(1024,65535)), inter=1.0/{pps}, verbose=0)\" "
        ).format(pps=pps, n=int(src[1:]) % 254)

        def do_inject():
            sh("timeout 15 " + script)
        return (lambda: None), do_inject, \
            "rate-limited UDP burst {} pps from {}".format(pps, src)

    if kind == "normal":
        return (lambda: None), (lambda: None), "no injection (negative control)"

    raise ValueError("unknown scenario " + kind)


def congestion_case(variant, net):
    """Proper inject/restore pair for the congestion scenario."""
    intf, delay, loss = variant["intf"], variant["delay_ms"], variant["loss_pct"]

    def do_inject():
        sh("tc qdisc add dev {i} root netem delay {d}ms loss {l}%"
           .format(i=intf, d=delay, l=loss))
        iperf_tcp(net, "h2", "10.1.0.3", seconds=40, port=IPERF_PORT, udp=True)

    def do_restore():
        sh("tc qdisc del dev {i} root".format(i=intf))
    return do_inject, do_restore, \
        "netem delay={}ms loss={}% on {}".format(delay, loss, intf)


# ------------------------------------------------------------------ single run

def run_one(net, kind, variant, run_id, since_iso):
    from collect_evidence import iso_now

    out_dir = os.path.join(RUNS_DIR, run_id)
    raw_dir = os.path.join(out_dir, "raw")
    os.makedirs(raw_dir, exist_ok=True)
    app_log(out_dir, "run {} started, scenario={}".format(run_id, kind))

    probes_log = []

    # ---- baseline phase -------------------------------------------------
    evidence_pass(net, out_dir, raw_dir, "baseline")
    probes(net, out_dir, probes_log, "baseline")
    iperf = iperf_tcp(net, "h1", "10.1.0.4", seconds=5, port=IPERF_PORT)
    probes_log.append({"label": "baseline_iperf", **iperf})

    # ---- inject ---------------------------------------------------------
    if kind == "congestion":
        inject, restore, description = congestion_case(variant, net)
    else:
        inject, restore, description = inject_and_restore(kind, variant, net)

    t_inject = iso_now()
    inject()
    app_log(out_dir, "INJECTED: {} at {}".format(description, t_inject))

    # ---- observation phase ---------------------------------------------
    wait(10, out_dir, "post-inject stabilisation")
    evidence_pass(net, out_dir, raw_dir, "post_inject_10s")
    probes(net, out_dir, probes_log, "post_inject_10s")

    wait(20, out_dir, "mid observation")
    evidence_pass(net, out_dir, raw_dir, "post_inject_30s")

    wait(20, out_dir, "late observation")
    evidence_pass(net, out_dir, raw_dir, "post_inject_50s")
    probes(net, out_dir, probes_log, "post_inject_50s")
    iperf = iperf_tcp(net, "h1", "10.1.0.4", seconds=5, port=IPERF_PORT)
    probes_log.append({"label": "post_inject_iperf", **iperf})

    # ---- restore and recovery check --------------------------------------
    t_restore = iso_now()
    restore()
    app_log(out_dir, "RESTORED at {}".format(t_restore))
    wait(15, out_dir, "recovery stabilisation")
    recovery = probes(net, out_dir, probes_log, "recovery")
    evidence_pass(net, out_dir, raw_dir, "recovery")

    recovered = all(p["loss_pct"] < 50 for p in recovery if p.get("dst"))

    # ---- karaf log window -----------------------------------------------
    rc, lines = snapshot_karaf(raw_dir, since_iso)
    app_log(out_dir, "karaf window: rc={} lines={}".format(rc, lines))

    with open(os.path.join(raw_dir, "probes.json"), "w") as fh:
        json.dump(probes_log, fh, indent=2)

    # ---- ground truth (kept apart from model evidence) -------------------
    gt = {
        "run_id": run_id,
        "scenario": kind,
        "injected_action": description,
        "variant": variant,
        "inject_time": t_inject,
        "restore_time": t_restore,
        "observed_outcome": {
            "recovered_after_restore": bool(recovered),
            "baseline_loss_pct": [p["loss_pct"] for p in probes_log
                                  if p.get("label") == "baseline"],
            "post_inject_loss_pct": [p["loss_pct"] for p in probes_log
                                     if p.get("label") == "post_inject_10s"],
        },
    }
    if kind == "switch_failure":
        gt["affected_nodes"] = [variant["switch"]] + list(variant["isolates"])
    elif kind == "link_failure":
        gt["affected_nodes"] = list(variant["link"])
    elif kind in ("host_disconnection", "forwarding_misconfig", "traffic_flood"):
        gt["affected_nodes"] = [variant.get("host",
                                            variant.get("victim",
                                                        variant.get("src")))]
    elif kind == "congestion":
        gt["affected_nodes"] = [variant["intf"].split("-")[0]]
    else:
        gt["affected_nodes"] = []
    with open(os.path.join(out_dir, "ground_truth.json"), "w") as fh:
        json.dump(gt, fh, indent=2)
    print("[{}] done: {} (recovered={})".format(run_id, description, recovered))
    return gt


# ------------------------------------------------------------------ main

SCENARIO_MATRIX = {
    "link_failure": LINK_VARIANTS,
    "switch_failure": SWITCH_VARIANTS,
    "congestion": CONGESTION_VARIANTS,
    "host_disconnection": HOST_VARIANTS,
    "normal": [{} for _ in range(6)],
}

OPTIONAL_MATRIX = {
    "forwarding_misconfig": MISCONFIG_VARIANTS,
    "traffic_flood": FLOOD_VARIANTS,
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", choices=list(SCENARIO_MATRIX) + list(OPTIONAL_MATRIX))
    ap.add_argument("--runs", type=int, default=6, help="runs per scenario")
    ap.add_argument("--start-run", type=int, default=1,
                    help="1-based variant index to start from")
    ap.add_argument("--optional", action="store_true",
                    help="run the optional scenarios as well")
    args = ap.parse_args()

    setLogLevel("error")
    net = Mininet(
        topo=Group11Topo(),
        controller=lambda name: RemoteController(name, ip="10.0.0.10", port=6653),
        switch=OVSSwitch,
    )
    net.start()
    print("Waiting 25s for ONOS to discover hosts/links...")
    time.sleep(25)

    loss = net.pingAll()
    if loss > 0:
        print("WARNING: pingAll loss = {}% - check that "
              "org.onosproject.fwd is ACTIVE before trusting incident runs. "
              "Continuing anyway.".format(loss))

    # iperf3 servers on the two probe destinations
    net["h4"].cmd("pkill iperf3; iperf3 -s -p {} -D".format(IPERF_PORT))
    net["h3"].cmd("pkill iperf3; iperf3 -s -p {} -D".format(IPERF_PORT))

    from collect_evidence import iso_now
    since = iso_now()

    plans = []
    if args.scenario:
        matrix = dict(SCENARIO_MATRIX)
        matrix.update(OPTIONAL_MATRIX)
        start = args.start_run
        variants = matrix[args.scenario][start - 1 : start - 1 + args.runs]
        plans = [(args.scenario, start + i, v) for i, v in enumerate(variants)]
    else:
        for kind, variants in SCENARIO_MATRIX.items():
            plans += [(kind, i + 1, v) for i, v in enumerate(variants)]
        if args.optional:
            for kind, variants in OPTIONAL_MATRIX.items():
                plans += [(kind, i + 1, v) for i, v in enumerate(variants)]

    # run all normal controls first, then incidents
    plans.sort(key=lambda p: 0 if p[0] == "normal" else 1)
    results = []
    for kind, idx, variant in plans:
        run_id = "{}_r{:02d}".format(kind, idx)
        results.append(run_one(net, kind, variant, run_id, since))
        wait(10, os.path.join(RUNS_DIR, run_id), "cooldown")

    with open(os.path.join(RUNS_DIR, "experiment_matrix.json"), "w") as fh:
        json.dump([r for r in results], fh, indent=2)
    net.stop()
    print("\nAll runs complete. Evidence in {}/".format(RUNS_DIR))


if __name__ == "__main__":
    main()
