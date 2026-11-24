# Quickstart: reproduce the project in three commands

New to this repository? This page is the shortest path from a clean machine
to reproducing the project's results. [README.md](README.md) has the full
details (all modes, troubleshooting, security notes), and
[ARCHITECTURE.md](ARCHITECTURE.md) explains how the pieces fit together.

## What the project does

A small emulated SDN (4 OpenFlow switches in a ring, 6 hosts, ONOS controller)
runs a labelled incident campaign: 30 runs covering link failure, switch
failure, congestion, host disconnection, and normal controls. For every run,
telemetry (ONOS REST snapshots, OVS dumps, Karaf controller log windows,
ping and iperf probes) is reduced to one `incident_record.json`, and three
explainers then identify and explain the incident:

1. a deterministic **rule-based baseline**,
2. **Mistral 7B on raw evidence** (Karaf log excerpts + ping summaries),
3. **Mistral 7B on structured evidence** (the preprocessed incident record).

An automated rubric scores each explanation (identification accuracy,
grounding, unsupported assertions); usefulness and clarity are scored by humans.

## Choose your path

| Path | Command | Works on | Wall-clock time |
|---|---|---|---|
| **Replay the recorded evidence (start here)** | `./group11 analysis` | any Linux or macOS machine with Docker | minutes of setup + Mistral stage: 2-8 h on a 4-core CPU, under 1 h on Apple silicon (Metal) |
| Full campaign on your own testbed | `./group11 experiment` | Linux only (needs the Open vSwitch kernel module; any stock Ubuntu/Debian/Kali kernel has it) | campaign ~1.5-2 h + Mistral stage |

Both paths are resumable: if one is interrupted, re-run the same command and
it continues where it stopped. The recorded 30-run evidence ships in the
repository (`project/runs/`), so the replay needs no testbed at all.

## Step by step

### 1. Clone and prepare

```bash
git clone https://github.com/ShrikantDNimkar/Explaining-Network-Incidents-in-SDN-Through-Log-Analysis-Using-Mistral-7B.git
cd Explaining-Network-Incidents-in-SDN-Through-Log-Analysis-Using-Mistral-7B
chmod +x group11
```

Requirements: Docker Engine + Compose v2, about 10 GB of free disk (Docker
images, the Mistral model alone is 4.4 GB), 8 GB RAM.

On **macOS**: use Docker Desktop (enable "Use Rosetta emulation for
amd64" and give the VM at least 8 GB), install the native Ollama app, quit it,
run `launchctl setenv OLLAMA_HOST 0.0.0.0`, start it again, then
`ollama pull mistral`. See [README.md](README.md#running-on-macos) for the
full Mac notes (current Docker Desktop versions cannot run `experiment`).

On **Linux**, Ollama is provisioned automatically by the launcher, including
the model pull; you can also do it explicitly with `./group11 setup-ollama`.

### 2. Verify

```bash
./group11 check
```

This confirms Docker is usable, checks the kernel datapath, and reports
whether the testbed and Ollama are ready.

### 3. Run

```bash
./group11 analysis
```

The first run builds the lab image (a few minutes), then (on a fresh
checkout) it preprocesses the 30 recorded runs, computes the baseline, makes
60 Mistral calls, and evaluates everything. Progress of each Mistral call is
echoed live.

### 4. Read the results

Everything lands in `project/runs/`:

- `evaluation_summary.csv`: per-run metrics and per-condition averages.
- `<scenario>_r*/incident_record.json`: the structured evidence per run.
- `<scenario>_r*/explanations/`: the three explanations per run
  (`baseline.json`, `mistral_raw.json`, `mistral_structured.json`).
  The recorded report originals are kept in `explanations_report/` next to them.
- `experiment_matrix.json`: ground truth of all 30 runs.

Reference identification accuracy from the project report:
baseline 86.7%, Mistral-raw 83.3%, Mistral-structured 80.0%
(26/30, 25/30, 24/30). See [README.md](README.md#reproduction-notes) for how
these reproduced on other machines, and [ARCHITECTURE.md](ARCHITECTURE.md)
for how the metrics are computed.

The one manual step, if you want the full report metrics: fill the joint
human rubric `project/runs/rubric_human_template.csv` (usefulness, clarity)
and re-run the evaluation as printed at the end of the pipeline.

## Going further

- Want to produce your own evidence instead of the recorded one?
  Run `./group11 experiment` on a Linux host; it regenerates the whole
  campaign and then reuses the same pipeline.
- Want to watch the SDN live? `./group11 up` on Linux, then open the ONOS
  GUI at http://localhost:8181 (onos/rocks), or
  `ssh -p 2222 mininet@localhost` (mininet/mininet) into the lab.
- Curious what happens inside a run (phases, injections, evidence files)?
  Read [ARCHITECTURE.md](ARCHITECTURE.md#the-evidence-timeline).
