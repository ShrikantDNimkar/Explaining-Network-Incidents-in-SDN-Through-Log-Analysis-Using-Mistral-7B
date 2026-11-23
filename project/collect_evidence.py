#!/usr/bin/env python3
"""
Group 11 - Security of SDN Project
Evidence collection helpers.

Gathers, for a given time window:
  - ONOS REST snapshots (devices, links, hosts, flows, topology)
  - OVS snapshots (ovs-vsctl show, dump-flows, dump-ports per switch)
  - ONOS Karaf log window (docker logs --since, or a mounted karaf.log file)
  - ping and iperf3 measurement results
Everything is written into a per-run evidence directory.

Works in both deployments:
  - Mininet VM (Labs 1-3) and Docker Desktop lab container, because ONOS
    always answers at 10.0.0.10:8181 on network sdn-net.
The functions are import-only (no side effects on import).
"""

import base64
import json
import os
import subprocess
import urllib.error
import urllib.request
from datetime import datetime

# ONOS always answers at 10.0.0.10:8181 on sdn-net in both deployments.
# Override with environment variables if your setup differs.
ONOS_BASE = os.environ.get("ONOS_BASE", "http://10.0.0.10:8181/onos/v1")
ONOS_USER = os.environ.get("ONOS_USER", "onos")
ONOS_PASS = os.environ.get("ONOS_PASS", "rocks")
ONOS_CONTAINER = os.environ.get("ONOS_CONTAINER", "onos")
SWITCHES = ["s1", "s2", "s3", "s4"]


def iso_now():
    """ISO-8601 UTC timestamp usable by `docker logs --since`."""
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def local_now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------- ONOS REST

def onos_get(endpoint):
    """GET an ONOS REST endpoint and return parsed JSON (or None on error)."""
    url = "{}/{}".format(ONOS_BASE, endpoint)
    req = urllib.request.Request(url)
    token = base64.b64encode("{}:{}".format(ONOS_USER, ONOS_PASS).encode()).decode()
    req.add_header("Authorization", "Basic " + token)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        return {"error": str(exc)}


def snapshot_onos(out_dir, phase):
    """Save devices/links/hosts/flows/topology REST state for one phase."""
    payload = {}
    for entity in ("devices", "links", "hosts", "flows", "topology"):
        payload[entity] = onos_get(entity)
    path = os.path.join(out_dir, "rest_{}.json".format(phase))
    with open(path, "w") as fh:
        json.dump({"phase": phase, "captured_at": iso_now(), "state": payload}, fh,
                  indent=2)
    return payload


def onos_device_availability(rest_snapshot):
    """Return {device_id: available} from a devices REST snapshot."""
    devices = (rest_snapshot or {}).get("devices") or {}
    out = {}
    for dev in devices.get("devices", []):
        out[dev.get("id")] = bool(dev.get("available"))
    return out


def onos_link_pairs(rest_snapshot):
    """Return a set of frozenset({'s1','s2'}) switch pairs from a links snapshot."""
    links = (rest_snapshot or {}).get("links") or {}
    out = set()
    for link in links.get("links", []):
        src = link.get("src", {}).get("device", "")
        dst = link.get("dst", {}).get("device", "")
        if src.startswith("of:") and dst.startswith("of:"):

            def dp(name):
                return "s{}".format(int(name.replace("of:", ""), 16))
            out.add(frozenset((dp(src), dp(dst))))
    return out


def onos_host_ips(rest_snapshot):
    """Return the set of host IPs currently known by ONOS."""
    hosts = (rest_snapshot or {}).get("hosts") or {}
    out = set()
    for host in hosts.get("hosts", []):
        for ip in host.get("ipAddresses", []):
            out.add(ip.split("/")[0])
    return out


# ---------------------------------------------------------------- OVS state

def sh(cmd, timeout=20):
    """Run a shell command, return (stdout+stderr text, return code)."""
    try:
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                               timeout=timeout)
        return (proc.stdout or "") + (proc.stderr or ""), proc.returncode
    except subprocess.TimeoutExpired:
        return "", 124


def snapshot_ovs(out_dir, phase, switches=SWITCHES):
    """Save ovs-vsctl show and per-switch flow/port dumps for one phase."""
    dump = {}
    dump["ovs_vsctl_show"] = sh("ovs-vsctl show")[0]
    for sw in switches:
        dump["flows_{}".format(sw)] = sh(
            "ovs-ofctl -O OpenFlow13 dump-flows {}".format(sw))[0]
        dump["ports_{}".format(sw)] = sh(
            "ovs-ofctl -O OpenFlow13 dump-ports {}".format(sw))[0]
    path = os.path.join(out_dir, "ovs_{}.txt".format(phase))
    with open(path, "w") as fh:
        fh.write("# captured {} phase {}\n".format(iso_now(), phase))
        for key, val in dump.items():
            fh.write("\n===== {} =====\n{}\n".format(key, val))
    return dump


# ------------------------------------------------------------- Karaf log

def snapshot_karaf(out_dir, since_iso, container=None):
    """Save the ONOS Karaf log window since a timestamp.

    Two modes:
      - DOCKER (default): `docker logs --since <iso> onos`, using the Docker
        CLI. Works on the Mininet VM and inside the lab container when the
        Docker socket is mounted (Docker Desktop setup).
      - FILE: if env KARAF_LOG_FILE is set, copy the tail of a mounted
        karaf.log file instead (no Docker CLI needed).
    """
    container = container or ONOS_CONTAINER
    log_file = os.environ.get("KARAF_LOG_FILE")
    if log_file and os.path.exists(log_file):
        text, rc = _karaf_from_file(log_file, since_iso), 0
    else:
        cmd = "docker logs --since {} {} 2>&1".format(since_iso, container)
        text, rc = sh(cmd, timeout=60)
    path = os.path.join(out_dir, "karaf_window.log")
    with open(path, "w") as fh:
        fh.write(text)
    return rc, len(text.splitlines())


def _karaf_from_file(log_file, since_iso):
    """Read a mounted karaf.log and keep lines dated after `since_iso`."""
    keep, started = [], False
    stamp = since_iso[:23].replace("T", " ").replace("Z", "")
    with open(log_file, errors="replace") as fh:
        for line in fh:
            if not started and stamp[:10] in line and stamp[11:19] in line:
                started = True
            if started:
                keep.append(line)
    return "".join(keep[-3000:])


# ------------------------------------------------------------- Measurements

def ping_pair(net, src, dst_ip, count=5):
    """Run ping from a Mininet host to an IP; return parsed result dict."""
    out = net[src].cmd("ping -c {} -i 0.2 {}".format(count, dst_ip)).strip()
    sent, recv, loss_pct, rtt = count, 0, 100.0, None
    if "bytes from" in out:
        recv = out.count(" bytes from ")
        loss_pct = round(100.0 * (sent - min(recv, sent)) / sent, 1)
    stats = [ln for ln in out.splitlines() if "rtt min/avg/max" in ln]
    if stats:
        try:
            rtt = stats[0].split("=")[1].strip().split()[0].split("/")[1]  # avg ms
        except (IndexError, ValueError):
            pass
    return {
        "time": iso_now(), "src": src, "dst": dst_ip,
        "output_tail": "\n".join(out.splitlines()[-3:]),
        "sent": sent, "received": recv, "loss_pct": loss_pct, "avg_rtt_ms": rtt,
    }


def iperf_tcp(net, client, server_ip, seconds=5, port=5201, udp=False):
    """Run an iperf3 test from a Mininet host; return parsed metrics."""
    proto = "-u" if udp else ""
    out = net[client].cmd(
        "iperf3 -c {} -p {} -t {} {} -J 2>/dev/null".format(
            server_ip, port, seconds, proto))
    result = {
        "time": iso_now(), "client": client, "server": server_ip,
        "udp": udp, "raw_head": "\n".join(out.splitlines()[:2]),
    }
    try:
        j = json.loads(out)
        end = j.get("end", {})
        if udp:
            report = end.get("sum", {})
            result.update({
                "throughput_mbps": round(report.get("bits_per_second", 0) / 1e6, 2),
                "lost_pct": round(
                    100.0 * report.get("lost_packets", 0) /
                    max(report.get("packets", 1), 1), 2),
                "jitter_ms": report.get("jitter_ms"),
            })
        else:
            report = end.get("sum_received", end.get("sum", {}))
            result.update({
                "throughput_mbps": round(report.get("bits_per_second", 0) / 1e6, 2),
                "retransmits": report.get("retransmits"),
            })
    except (ValueError, TypeError):
        result["error"] = "iperf3 JSON parse failed"
    return result


def app_log(out_dir, line):
    """Append an orchestrator action to the run's experiment log."""
    with open(os.path.join(out_dir, "experiment_log.txt"), "a") as fh:
        fh.write("{} | {}\n".format(iso_now(), line))
