# Group 11 - Explaining Network Incidents in SDN Through Log Analysis Using Mistral 7B

Eris MUSTAFA · Shrikant NIMKAR - Security of SDN, Université du Luxembourg

Complete, reproducible project package: a controlled SDN testbed, labelled
incident generation, log preprocessing, a local Mistral 7B explanation
prototype, a rule-based baseline, and a three-condition evaluation.

## Two ways to deploy

| Option | Where | See |
| --- | --- | --- |
| A. **Local PC / macOS with Docker Desktop (recommended)** | ONOS + Mininet lab in containers, Ollama + Mistral 7B natively on the host; SSH access via PuTTY (port 2222) | `LOCAL_SETUP.md`, `Dockerfile`, `docker-compose.yml` |
| B. Course Mininet VM (Labs 1-3 style) | Everything inside the VM; works only if the VM has >= 4-5 GB RAM | steps below |

The course VM as configured (1 vCPU, 1 GB RAM, ~2 GB free disk) cannot run
ONOS plus Mistral 7B; use option A unless you can enlarge the VM.

## Package contents

| File | Purpose |
| --- | --- |
| `topo_group11.py` | Mininet topology: 4 switches (ring, one redundant route), 6 hosts, remote ONOS. |
| `collect_evidence.py` | ONOS REST snapshots, OVS dumps, Karaf log windows, ping/iperf3 probes. |
| `run_experiment.py` | Orchestrator: 4 core scenarios x 6 runs + 6 negative controls (+ optional cases). |
| `preprocess_logs.py` | Raw evidence -> structured JSON incident record. |
| `baseline_explain.py` | Rule-based baseline explanations. |
| `mistral_explain.py` | Mistral 7B via Ollama, fixed prompt, raw vs structured conditions. |
| `evaluate.py` | Rubric metrics, per-run and condition-level comparison, human rubric template. |
| `Dockerfile` / `entrypoint.sh` / `docker-compose.yml` | Option A testbed (ONOS + privileged Mininet lab with SSH). |
| `LOCAL_SETUP.md` | Full option A guide: Windows/macOS, PuTTY, Ollama on host. |

## Option B: course Mininet VM (only with enough RAM)

Ubuntu Mininet VM (mininet@mininet-vm), Mininet + Open vSwitch + Docker +
iperf3 installed:

```bash
sudo apt update
sudo apt install -y mininet openvswitch-switch curl iperf3 docker.io
sudo docker network create --subnet 10.0.0.0/24 sdn-net
sudo docker run -d --name onos --net sdn-net --ip 10.0.0.10 \
     -p 8181:8181 -p 8101:8101 -p 6653:6653 onosproject/onos:latest
```

Activate the required ONOS applications (lesson from Lab 1: do this BEFORE
ping tests, otherwise pingall fails with 100% loss):

```bash
curl -sS -u onos:rocks -X POST http://127.0.0.1:8181/onos/v1/applications/org.onosproject.openflow-base/active
curl -sS -u onos:rocks -X POST http://127.0.0.1:8181/onos/v1/applications/org.onosproject.openflow/active
curl -sS -u onos:rocks -X POST http://127.0.0.1:8181/onos/v1/applications/org.onosproject.fwd/active
curl -sS -u onos:rocks http://127.0.0.1:8181/onos/v1/devices | python3 -m json.tool
```

Install Ollama and the model (RAM permitting; quantised by default):

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull mistral          # or a specific quantised tag for low-RAM machines
ollama run mistral "ready?"  # smoke test
```

## Running the campaign (same in both options)

```bash
sudo mn -c                                   # clean stale state
sudo python3 run_experiment.py --scenario link_failure --runs 1   # pilot run
sudo python3 run_experiment.py               # full matrix: 30 runs
python3 preprocess_logs.py
python3 baseline_explain.py
OLLAMA_URL=http://host.docker.internal:11434 python3 mistral_explain.py   # option A
# (option B: omit OLLAMA_URL, model runs inside the VM)
python3 evaluate.py
# fill runs/rubric_human_template.csv jointly (usefulness/clarity 1-5),
# resolving disagreements against the stored raw evidence
```

Outputs: `runs/evaluation_summary.csv`, `runs/evaluation_comparison.csv`.

## Environment variables (both options)

| Variable | Default | Meaning |
| --- | --- | --- |
| `ONOS_BASE` | `http://10.0.0.10:8181/onos/v1` | ONOS REST base (same in VM and container) |
| `ONOS_CONTAINER` | `onos` | container name for `docker logs` Karaf capture |
| `KARAF_LOG_FILE` | unset | if set, read a mounted karaf.log file instead of docker logs |
| `OLLAMA_URL` | `http://127.0.0.1:11434` | Ollama base URL (use `http://host.docker.internal:11434` in option A) |
| `OLLAMA_MODEL` | `mistral` | model tag, e.g. a smaller quantisation |

## Notes

- All disruptive actions stay inside the emulated network; the traffic-flood
  scenario is rate-limited and 15 s long.
- Software versions frozen after the compatibility check: same Ubuntu 20.04 /
  Mininet / OVS 2.13 stack in both options, so results stay comparable with
  the lab series.
- Keep `runs/` under version control together with the scripts.
