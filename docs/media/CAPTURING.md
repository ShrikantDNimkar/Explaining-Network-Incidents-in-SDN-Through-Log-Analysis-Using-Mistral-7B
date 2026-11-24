# Capturing screenshots and the demo video

Short guide for adding the visual material referenced by the README gallery.
Everything lives in this folder (`docs/media/`), so the README embeds are
plain relative links.

## What to capture

| File name | What it shows | Capture on | Command / tool |
|---|---|---|---|
| `onos-gui-topology.png` | ONOS GUI with the 4-switch ring and 6 hosts visible | Linux host (Kali/WSL2) where the topology actually runs | browser at http://localhost:8181 (onos/rocks), then screenshot |
| `campaign-progress.png` | the 30-run campaign running (run IDs scrolling, audit output) | Linux host | `./group11 experiment` terminal |
| `analysis-complete.png` | the full analysis pipeline finishing ("PIPELINE COMPLETE" + evaluation block) | any machine (Mac is fine) | `./group11 analysis` terminal |
| `evaluation-summary.png` | the evaluation numbers open in a spreadsheet or CSV viewer | any machine | `project/runs/evaluation_summary.csv` |
| `group11-usage.png` | the launcher usage/help output (works on all platforms) | any machine | `./group11` |
| `group11-demo.mp4` | 60-90 s demo video (see below) | Linux host for testbed + Mac for analysis or one Linux machine for everything | screen recording |

Note on capturing the ONOS GUI: capture it on the Linux host where
`./group11 up` produced a real Mininet topology. On a Mac with current
Docker Desktop the GUI opens but shows an empty topology (no OVS kernel
datapath), which is not the shot you want.

## How to capture

**macOS**

- Screenshot a region: `Cmd+Shift+4`, drag, file lands on the Desktop as
  `Screenshot ... .png`; rename it to the file name from the table above.
- Record the screen: `Cmd+Shift+5`, "Record Entire Screen" or "Record
  Selected Portion", stop from the menu-bar icon. Result is a `.mov`.
- Downscale a screenshot (built-in, no extra tools):

      sips -Z 900 Screenshot.png

  (`-Z 900` makes the longest side 900 px: readable on GitHub, small file.)

**Kali / Linux desktop**

- Screenshot region: `Shift+PrtScn` (GNOME) or Applications → Accessories →
  Screenshot / `flameshot` / `scrot -s`.
- Record the screen: install `obs-studio` (best for a narrated demo) or use
  GNOME's built-in recorder (`Ctrl+Alt+Shift+R`, records to WebM).

Trim to the essentials, keep each PNG under about 1 MB and use PNG, not JPEG,
for terminal text (it stays crisp and compresses better).

## Demo video contents (suggested 60-90 s script)

1. Terminal: `./group11 check`, everything green (5-10 s).
2. Terminal: `./group11 up`, then switch to the ONOS GUI showing the ring
   (10-15 s).
3. Campaign snippet: `./group11 experiment` progress lines scrolling, cut
   to the audit summary (15-20 s).
4. Analysis in progress: Mistral call lines appearing (`congestion_r01
   [mistral_raw]: 21.9s` style) (10-15 s).
5. End: the evaluation block with baseline / raw / structured accuracies
   and "PIPELINE COMPLETE" (10 s).

## Sizes and where big files go

- GitHub blocks files over 100 MB and warns over 50 MB. A 60-90 s screen
  recording at 1080p is typically 10-40 MB: fine to commit directly.
- If your video is larger (or you just prefer), attach it to a GitHub
  **Release** instead (Releases → Draft a new release → attach), then link
  it from the README. That keeps the clone small.
- Convert/trim if needed. On macOS, QuickTime can trim (`Cmd+T`). With
  ffmpeg (brew install ffmpeg):

      ffmpeg -i recording.mov -vf scale=1280:-2 -c:v libx264 -crf 28 -preset medium -c:a aac group11-demo.mp4

## After capturing: commit and embed

```bash
git add docs/media/
git commit -m "Docs: add screenshots and demo video"
git push
```

Then open README.md, remove the HTML comment marks around the image lines
in "Screenshots and demo video" for each file that now exists, and commit
that too. GitHub renders images inline; a committed `.mp4` shows as a player
when the file is opened on GitHub and as a link inside the README (linking
the Release asset gives the same behaviour without cloning cost).
