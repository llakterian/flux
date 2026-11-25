#!/usr/bin/env bash
# FLUX one-take screen+audio recorder (DirectMeds application, Nov 28 2026)
#
# Usage:
#   ./record_take.sh --cue                  # print the timed shot list only
#   ./record_take.sh --minutes 55           # record for 55 minutes
#   ./record_take.sh --out FILE.mp4
#   ./record_take.sh --source NAME          # force a pactl source
#   ./record_take.sh --gain -8              # extra input gain in dB (default -8)
#   ./record_take.sh --audio narration.wav  # mux pre-recorded narration
#   ./record_take.sh --normalise FILE.mp4   # loudness-normalise an existing take
#
# What it does:
#   1. picks a usable microphone (prefers USB/headset/webcam, never a monitor)
#   2. runs a 3-second level check: warns if SILENT (<-45 dB) or CLIPPING
#   3. records the screen with ffmpeg x11grab + the chosen mic (or a WAV),
#      with an input-gain trim and a limiter so a hot laptop mic does not clip
#   4. writes an .mp4 next to the build book and prints the path
#
# No OBS on this machine; ffmpeg + kooha + vokoscreenNG are available.

set -uo pipefail

DURATION_MIN=60
OUT="/home/c0bw3b/work/flux/flux_take_$(date +%Y%m%d_%H%M).mp4"
SRC=""
WAV=""
GAIN_DB=-8
GEOMETRY=""
CUE_ONLY=0
NORMALISE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --minutes)    DURATION_MIN="$2"; shift 2 ;;
    --out)        OUT="$2"; shift 2 ;;
    --source)     SRC="$2"; shift 2 ;;
    --gain)       GAIN_DB="$2"; shift 2 ;;
    --audio)      WAV="$2"; shift 2 ;;
    --normalise)  NORMALISE="$2"; shift 2 ;;
    --cue)        CUE_ONLY=1; shift ;;
    *) echo "unknown arg: $1"; exit 2 ;;
  esac
done

print_cues() {
  cat <<'CUE'
────────────────────────────────────────────────────────────────────────
 FLUX one-take — shot list (target ~58 min, hard ceiling 60)
 DirectMeds · Sambu Leonard · fluxharness · DEADLINE Sat 28 Nov 2026
────────────────────────────────────────────────────────────────────────
 0:00  Intro (3 min) — AGENTS.md on screen. The question: how do you know an
       agent is dependable? Two halves of the harness: deterministic guardrails
       first, LLM judge only where regex can't. The hard rule: a judge that
       disagrees with a guardrail does not override it.
       Which rule is free? Which one needs a human to write?
 3:00  contracts.py (5 min) — typed handoffs between Scout → Architect → Critic.
       No shared dict, no stringly-typed state. Show ItemCap and FailureOnShortfall.
 8:00  workflow.py (7 min) — the three system prompts verbatim. Note the repair
       round: one retry, using the model's own error text.
15:00  config.py + llm.py (5 min) — thin client, .env.example, json signature
       (system, user) that chats then parses.
20:00  guardrails.py (7 min) — the free half. Walk the ten rules, say why each
       is cheap. Deterministic means same answer every run.
27:00  judge.py + scoring.py (5 min) — the paid half. 40/60 guardrail/composition.
       The stack is two-tier by cost: pay only for taste.
32:00  runner.py + run.py (5 min) — the black-box driver; the CLI is one line.
37:00  dataset + tests (5 min) — `pytest -q` → 28 green. Mutants in the suite.
42:00  Live (13 min) — the money shot, in this order:
         python run.py run --idea "a page that tracks plant watering"
            63 s, 3 calls, verdict + "critic revised N field(s)", call/token
            totals. Point at the trace.
         python run.py eval
            ~16 min: 8 cases, per-case overall/guard/comp/feas/taste, baseline
            line. WHILE IT RUNS: split screen — AGENTS.md / guardrails.py on the
            other side, narrate. Planned beats: the hard rule → two-tier stack →
            baseline policy → judge variance (it is real: say it out loud) →
            what the trace JSON holds.
         python run.py eval --mutant --limit 3
            overall collapses to 0.000, pass rate 0%. Mutant mode skips the
            baseline comparison, so no false jitter — pure proof.
            SAY: "I weakened the workflow with a realistic simplify PR — trimmed
            the Critic's revision, told the Architect to be brief. The rig scores
            it zero. An eval suite that can't catch that is decoration."
       If the mutant prints a WorkflowError (observed on the "watering" case:
            "[critic] confidence must be a number in [0,1]"), that IS the proof —
            say so: "the mutant does not just score worse, it breaks the contract
            the guardrails are supposed to catch. Either way the case fails and
            the rig turns red instead of quietly passing it."
       If a REGRESSION line appears on the clean eval, own it: "judge variance
       above the 0.03 threshold; the baseline only moves when scores are
       equal-or-better."
55:00  Wrap (3 min) — AGENTS.md again + .env.example. One line per watch
       criterion: how you talk to AI, how you orchestrate, how you decide, taste.
       Close: "This is the harness work the FLUX team does — evals and guardrails
       that keep agents fast, correct and cost-efficient. I'd like to build yours."
58:00  STOP. Attach to the staged Gmail draft (EMAIL_TO_BEN.txt) with the CV.
────────────────────────────────────────────────────────────────────────
CUE
}

if [[ "$CUE_ONLY" == "1" ]]; then
  print_cues
  exit 0
fi

command -v ffmpeg >/dev/null || { echo "ERROR: ffmpeg not installed"; exit 1; }
command -v pactl  >/dev/null || { echo "ERROR: pactl (pipewire/pulse) not available"; exit 1; }
export DISPLAY="${DISPLAY:-:0}"
FPS=30

if [[ -n "$NORMALISE" ]]; then
  echo "==> normalising $NORMALISE"
  ffmpeg -y -i "$NORMALISE" \
    -c:v copy -af "loudnorm=I=-16:TP=-1.5:LRA=11" \
    -c:a aac -b:a 160k "${NORMALISE%.mp4}_norm.mp4"
  echo "==> done: ${NORMALISE%.mp4}_norm.mp4"
  exit 0
fi

if [[ -z "$GEOMETRY" ]]; then
  GEOMETRY="$(xrandr 2>/dev/null | awk '/\*/ {print $1; exit}')"
  GEOMETRY="${GEOMETRY:-1366x768}"
fi

echo "==> screen: $GEOMETRY @ ${FPS}fps   (native, 1080p not available on this laptop)"
DURATION_SEC="$(awk "BEGIN{printf \"%d\", ${DURATION_MIN}*60}")"
echo "==> target length: ${DURATION_MIN} min (${DURATION_SEC}s) -> $OUT"
print_cues

if [[ -z "$WAV" ]]; then
  if [[ -z "$SRC" ]]; then
    # prefer real microphones; never a monitor output
    SRC="$(pactl list short sources 2>/dev/null \
           | awk '$2 !~ /monitor/ {print $2}' \
           | grep -Ei 'usb|headset|headphone|webcam|microphone|mic|blue|yeti|audio_input' \
           | head -1)"
    if [[ -z "$SRC" ]]; then
      SRC="$(pactl list short sources 2>/dev/null | awk '$2 !~ /monitor/ {print $2}' | head -1)"
    fi
  fi
  if [[ -z "$SRC" ]]; then
    echo "ERROR: no microphone source found."
    echo "       Check: pactl list short sources"
    echo "       If you record narration separately, use: $0 --audio narration.wav"
    exit 1
  fi
  echo "==> microphone source: $SRC"

  echo "==> level check (3s, speak now)…"
  LEVELS="$(ffmpeg -hide_banner -f pulse -i "$SRC" -t 3 -af volumedetect -f null - 2>&1 \
            | grep -E 'mean_volume|max_volume')"
  echo "$LEVELS" | sed 's/^/    /'
  MEAN="$(echo "$LEVELS" | awk -F': ' '/mean_volume/ {print $2}' | awk '{print $1}')"
  MAX="$(echo "$LEVELS"  | awk -F': ' '/max_volume/  {print $2}' | awk '{print $1}')"
  if [[ -n "$MEAN" && "$MEAN" == "-inf" ]]; then
    echo "    WARNING: mic is SILENT — plug in / select the mic, then re-run."
  elif [[ -n "$MAX" ]] && awk "BEGIN{exit !($MAX >= -0.5)}"; then
    echo "    NOTE: mic is HOT (max ${MAX} dB) — trimming input by ${GAIN_DB} dB and limiting."
    echo "          Better still: talk 15-20 cm from the mic, or use a headset."
  fi
fi

echo "==> recording in 5 seconds..."
sleep 5

# The laptop mic sits at max 0.0 dB, so trim the input and cap the peaks.
# Without this, every loud syllable hard-clips and the take is unusable.
AFILTERS="volume=${GAIN_DB}dB,alimiter=limit=0.95:attack=5:release=80,highpass=f=70"

if [[ -n "$WAV" ]]; then
  echo "==> using pre-recorded audio: $WAV"
  ffmpeg -y -f x11grab -framerate "$FPS" -video_size "$GEOMETRY" -i "$DISPLAY.0" \
         -i "$WAV" \
         -c:v libx264 -preset veryfast -crf 20 -pix_fmt yuv420p \
         -c:a aac -b:a 160k -ac 2 -shortest "$OUT"
else
  ffmpeg -y -f x11grab -framerate "$FPS" -video_size "$GEOMETRY" -i "$DISPLAY.0" \
         -f pulse -i "$SRC" -af "$AFILTERS" \
         -c:v libx264 -preset veryfast -crf 20 -pix_fmt yuv420p \
         -c:a aac -b:a 160k -ac 2 \
         -t "$DURATION_SEC" "$OUT"
fi

echo "==> done: $OUT"
ls -lh "$OUT" 2>/dev/null
echo "==> sanity: ffprobe duration / streams"
ffprobe -v error -show_entries format=duration,size -show_entries stream=codec_name,width,height,channels,sample_rate \
        -of default=noprint_wrappers=1 "$OUT" 2>/dev/null
echo "==> normalise the audio:  $0 --normalise '$OUT'"
echo "==> then attach to the staged Gmail draft (EMAIL_TO_BEN.txt) with the CV."