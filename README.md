# Group 11 - SDN Incident Explanation with Mistral 7B (Docker Package)

**Project:** Explaining Network Incidents in SDN Through Log Analysis Using Mistral 7B
**Team:** Eris Mustafa, Shrikant Nimkar
**Course:** Security of Software Defined Networking, Université du Luxembourg

This package runs the complete project in a consistent, reproducible Docker
environment: an emulated SDN topology (4 OVS switches in a ring, 6 hosts) under
the ONOS controller, a 30-run incident campaign (link failure, switch failure,
congestion, host disconnection, plus normal controls), and an analysis pipeline
that explains each incident three ways: a rule-based baseline and Mistral 7B on
raw and on structured evidence.

## One-time preparation

1. Requirements: a Linux machine with **Docker Engine + Compose v2** and
   about 10 GB of free disk space. Any standard Ubuntu/Debian kernel already
   ships the Open vSwitch datapath the emulation needs; no custom kernel is
   required on native Linux. 8 GB RAM is enough unless you also run the CPU
   Mistral calls on the same machine (then 16 GB is comfortable).
2. Nothing else to copy: this repository already contains the project
   scripts in `project/` and the recorded 30-run evidence in `project/runs/`,
   so `analysis` replays the recorded evidence out of the box. You only
   need `experiment` if you want to re-run the campaign yourself.
3. Ollama (the LLM server for Mistral 7B) is provisioned **automatically**:
   when a mode needs it and it is missing, the launcher installs it, sets
   `OLLAMA_HOST=0.0.0.0`, and pulls the `mistral` model. You can also do it
   explicitly first:

       ./group11 setup-ollama

4. Verify everything is ready:

       ./group11 check

## Running

Full experiment, testbed to final evaluation (campaign about 1.5 h, Mistral
stage several hours on CPU):

    ./group11 experiment

Analysis-only replay of the recorded 30-run evidence (about 6.5 h for the 60
Mistral calls on a 4-core laptop CPU; the rest is minutes):

    ./group11 analysis

Both modes are resumable: if interrupted, re-run the same command and it
continues where it stopped.

Convenience commands:

    ./group11 up | down          start/stop the testbed
    ./group11 shell              root shell inside the lab container
    ./group11 logs [onos|sdn-lab]  follow container logs
    ssh -p 2222 mininet@localhost  interactive lab access (mininet/mininet)

## What each mode does

| Mode | Steps |
|---|---|
| `experiment` | build images, start ONOS + lab, activate `openflow-base`/`openflow`/`fwd`, run the 30-run campaign (ONOS restart before every family and before every switch_failure run, per the project protocol), audit all 30 runs against acceptance criteria, regenerate the experiment matrix, preprocess evidence, rule baseline, Mistral stage (60 calls), evaluate. |
| `analysis` | start the lab container only, preprocess the recorded evidence, rule baseline, Mistral stage (60 calls), evaluate. |

## Running on macOS

macOS is supported through Docker Desktop. Versions from 4.27 through the 4.x
line had the Open vSwitch datapath **built into the VM kernel**, so no custom
kernel and no extra VM were needed. **Current Docker Desktop versions
(verified on 29.x) no longer ship that kernel module**, which means
`./group11 experiment` (live Mininet topology) cannot run on such a Mac: the
launcher detects it, prints a NOTE, and `experiment` exits early with
guidance. `./group11 up`, `check`, and `analysis` work on every version, and
`analysis` (the full Mistral replay) is the intended Mac workflow.

One-time Mac preparation:

1. Install a current Docker Desktop. In Settings > Resources give the VM at
   least 8 GB of memory. On Apple silicon keep Settings > General >
   "Use Rosetta for x86_64/amd64 emulation" enabled (it is the default).
2. The upstream ONOS image has no arm64 build. docker-compose.yml pins
   `platform: linux/amd64`, so on Apple silicon the controller runs under
   Rosetta and warms up noticeably slower (up to about 3 minutes); the
   launcher's activation retry covers it. If you ever see "ONOS applications
   did not reach ACTIVE state" on a Mac, simply re-run `./group11 up`.
3. Install the native Mac Ollama app (https://ollama.com/download or
   `brew install --cask ollama`), quit it, run
   `launchctl setenv OLLAMA_HOST 0.0.0.0`, start it again, then
   `ollama pull mistral`. On Apple silicon Ollama uses Metal, so the Mistral
   stage is faster than on an x86 CPU laptop.
4. macOS ships without `python3` until the Command Line Tools are present:
   if a dialog offers them, accept it, or run `xcode-select --install` once.
5. If macOS asks whether to allow incoming connections for Ollama on port
   11434, click Allow.

Everything else is identical: `./group11 check`, `./group11 up` (ONOS GUI at
http://localhost:8181), or `./group11 analysis` to replay the recorded
evidence without re-running the campaign. On Docker Desktop versions without
the Open vSwitch module, run the campaign on your Linux host and replay it
on the Mac. The launcher detects macOS automatically (controller reached
via the published port, datapath probed inside the Docker VM).

End-to-end verified on Debian-based Linux (Kali rolling, Ubuntu 22.04 VM);
the analysis replay is verified on Apple silicon (M1 Pro, Docker Desktop
with Rosetta emulation, Ollama on Apple Metal). If anything misbehaves on
your platform, open an issue.

## Reproduction notes

Reference results were produced on the original host (Windows/WSL2, custom
kernel). The campaign has since been repeated end to end on a second Linux
host (Kali rolling), and the analysis stage was replayed from scratch on
Apple silicon (M1 Pro, MacBook Pro 16, Docker Desktop + native Ollama on
Apple Metal, 60 fresh Mistral 7B calls):

- `mistral_raw`: 25/30 identification accuracy, identical to the report; all
  30 raw classifications matched the recorded run.
- `mistral_structured`: 23/30 vs 24/30 in the report. The single differing
  run (normal_r01) committed to `congestion` on a no-incident run where the
  recorded run correctly abstained (`insufficient_evidence`); both cited the
  same observed events, so the divergence is sampling-level, not input drift.
- Runtime: about 24 s per raw call and 31 s per structured call on Metal,
  roughly 10-15x faster than the CPU reference (242 s / 453 s).
- The baseline is deterministic and reproduced exactly (26/30, 86.7%).

Fresh Apple silicon outputs live in `runs/<run>/explanations/`; the recorded
report originals are preserved per run in `runs/<run>/explanations_report/`.

## Results

All outputs land in `project/runs/`:

- `evaluation_summary.csv` - per-run metrics and per-condition averages
- `experiment_matrix.json` - ground truth of the 30 runs
- `<scenario>_r*/` - raw evidence, incident records, and the three
  explanation files per run (`baseline.json`, `mistral_raw.json`,
  `mistral_structured.json`)
- `rubric_human_template.csv` - the joint human rubric (90 rows); it is the
  one manual step and cannot be automated. After filling it, re-run
  `./group11 experiment` (or `./group11 shell` then `python3 evaluate.py`)
  to merge the human columns.

Reference results from the project report:

| Condition | Identification accuracy | Avg grounding (0-2) | Avg runtime |
|---|---|---|---|
| Baseline (rules) | 26/30 (86.7%) | 0.93 | < 1 ms |
| Mistral-raw | 25/30 (83.3%) | 0.60 | 242 s |
| Mistral-structured | 24/30 (80.0%) | 0.53 | 453 s |

## Package contents

```
README.md            this file
Dockerfile           lab image: ubuntu:20.04, Mininet 2.3.0, OVS, docker CLI, iperf, sshd:2222
entrypoint.sh        lab container entrypoint (module load, OVS start, sshd)
docker-compose.yml   ONOS (10.0.0.10) + privileged sdn-lab (10.0.0.20) on sdn-net
group11              one-command launcher (all modes)
project/             project scripts, recorded 30-run evidence and results
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| `host kernel has no Open vSwitch datapath` | `sudo apt-get install -y linux-modules-extra-$(uname -r) openvswitch-switch` and re-run. |
| Port 8181 or 2222 already in use | edit the `ports:` lines in `docker-compose.yml`. |
| `Ollama is installed but still unreachable` | ensure `OLLAMA_HOST=0.0.0.0` (systemd override is at `/etc/systemd/system/ollama.service.d/override.conf`), restart Ollama, and check the firewall (`sudo ufw status`; Docker's bridge must be allowed). |
| Mistral calls very slow | normal on CPU (about 2-8 min per call); the iGPU on the reference laptop could not accelerate it either. |
| Results owned by root | the lab container runs as root; inspect with `sudo` or `sudo chown -R $USER project/runs` afterwards. |
| Running under WSL2 | stock WSL2 kernels lack Open vSwitch entirely; use a custom WSL2 kernel as documented in the project report, then run this package inside it. |
| `docker compose` reports "not a docker command" | on Debian/Kali install the `docker-compose` package (Compose v2) and register it: `sudo ln -s /usr/bin/docker-compose /usr/local/lib/docker/cli-plugins/docker-compose`. On Ubuntu the package is `docker-compose-v2`. |

## Security notes

- Ollama with `OLLAMA_HOST=0.0.0.0` listens on all interfaces and has no
  authentication: only run it on a trusted network (home/office LAN), and stop
  it when not experimenting.
- The lab container is privileged and mounts the Docker socket: that is what
  Mininet's kernel datapath and the ONOS Karaf log capture require. Run this
  package on a machine you control.
