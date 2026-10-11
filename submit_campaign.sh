#!/bin/bash
# ============================================================================
# LaZagna turnkey launcher for PACE Phoenix (parallel campaign, v2).
# Run from a LOGIN node, in the cloned repo dir (project or scratch storage, NOT $HOME):
#
#     bash submit_campaign.sh
#
# To characterize the benchmarks first (synthesis + pack only, no place or route, so it is
# cheap), which tells us which designs actually stress a 12.5/12.5/75 architecture:
#
#     CHARACTERIZE=1 bash submit_campaign.sh
#
# It will:
#   1. auto-detect your charge account (override: ACCOUNT=gts-<PI> bash submit_campaign.sh)
#   2. if lazagna.sif is missing, submit the image build job (build_lazagna.sbatch)
#      NOTE: after a repo update (git pull), delete the old lazagna.sif first — the image
#      bakes in the repo code, so a stale .sif runs stale code.
#   3. submit the WORKER ARRAY (default 16 parallel jobs) — all workers contribute trials
#      to the shared optuna studies (eltwise columns + 3 clma sampler studies) through
#      JournalStorage files in the shared work dir. ~16x fewer wall-clock hours than one job.
#   4. submit the EXTRAS job (smoke test + 2D-vs-3D + conv/lstm, the 64G phases)
#   5. submit the COLLECT job (afterany) -> $WORK_ROOT/campaign_summary.md
#
# Tuning (env vars): ACCOUNT, QUEUE (inferno), N_WORKERS (16), SEEDS (3),
#   TRIALS_COLUMNS (35), TRIALS_SAMPLER (15, or 60 when BATCHES is set), STUDIES
#   (comma-separated, e.g. "columns,tpe"; default all four), BATCHES (batch-width ablation,
#   e.g. "1 10 25 50 100"), WORK_ROOT (default ./campaign_work/<timestamp>).
#
# RQ3 ablation:  BATCHES="1 10 25 50 100" STUDIES="tpe,nsga2,random" bash submit_campaign.sh
# Light first run:  N_WORKERS=2 SEEDS=1 TRIALS_COLUMNS=2 TRIALS_SAMPLER=2 bash submit_campaign.sh
# ============================================================================
set -euo pipefail
cd "$(dirname "$0")"
HERE="$PWD"

QUEUE="${QUEUE:-inferno}"
N_WORKERS="${N_WORKERS:-16}"
# RQ3 batch-width ablation. Set BATCHES to a space-separated list to submit one worker array
# per width, each writing its own suffixed study (e.g. clma_sampler_tpe_b25). Ismael asked for
# 1 10 25 50 100. Unset means a single array at N_WORKERS, as before.
BATCHES="${BATCHES:-}"
# Wall time per worker job. The default directive in worker_array.sbatch is 16 h, which is fine
# at wide batches but NOT at batch 1: 60 trials x 3 samplers x ~15 min is roughly 45 h of
# sequential work. A CLI --time overrides the directive, so low-batch arms get more room.
WALL="${WALL:-}"
# 15 trials per sampler was not enough to separate TPE from random in the 2026-08-14 run
# (spread between samplers was smaller than seed noise), so the ablation defaults higher.
[ -n "$BATCHES" ] && TRIALS_SAMPLER="${TRIALS_SAMPLER:-60}"

# --- 1. Charge account -------------------------------------------------------
ACCT="${ACCOUNT:-}"
if [ -z "$ACCT" ]; then
  ACCT="$(sacctmgr -nP show assoc user="$USER" format=account 2>/dev/null | grep -im1 '^gts-' || true)"
  [ -z "$ACCT" ] && ACCT="$(sacctmgr -nP show assoc user="$USER" format=account 2>/dev/null | awk 'NF{print;exit}')"
fi
if [ -z "$ACCT" ]; then
  echo "Could not auto-detect a charge account."
  echo "Find it with:  pace-quota    (or: sacctmgr -nP show assoc user=$USER format=account)"
  echo "Then re-run:   ACCOUNT=gts-<PI> bash submit_campaign.sh"
  exit 1
fi
echo "Charge account: $ACCT   queue: $QUEUE   workers: $N_WORKERS"

# --- Characterization-only mode ------------------------------------------------
# Same account auto-detect and the same image, just the cheap synth+pack pass. Run this
# before committing a full campaign so the placement study is pointed at designs where
# hard blocks are actually contended.
if [ -n "${CHARACTERIZE:-}" ]; then
  [ -e "$HERE/characterize.sbatch" ] || { echo "FATAL: missing characterize.sbatch"; exit 1; }
  SIF="$HERE/lazagna.sif"
  DEP=""
  if [ ! -f "$SIF" ]; then
    echo "lazagna.sif not found -> queuing build first..."
    BID="$(sbatch --parsable -A "$ACCT" -q "$QUEUE" build_lazagna.sbatch)"
    echo "  build job: $BID"
    DEP="--dependency=afterok:$BID"
  fi
  # One array task per design (count from characterize.py's default list unless CHAR_DESIGNS set).
  if [ -n "${CHAR_DESIGNS:-}" ]; then
    NDES="$(echo "$CHAR_DESIGNS" | tr ',' ' ' | wc -w)"
  else
    NDES="$(python3 -c "import re;s=open('campaign/characterize.py').read();b=s[s.index('DEFAULT_DESIGNS'):s.index(']',s.index('DEFAULT_DESIGNS'))];print(len(re.findall(r'\"(?:koios|vtr)/',b)))")"
  fi
  CHENV="ALL"
  CHID="$(sbatch --parsable -A "$ACCT" -q "$QUEUE" $DEP --array=0-$((NDES-1)) \
          --export="$CHENV" characterize.sbatch)"
  SUMID="$(sbatch --parsable -A "$ACCT" -q "$QUEUE" --dependency=afterany:$CHID \
          --array=0 --time=00:20:00 --mem=4G --export="$CHENV,SUMMARIZE=1" characterize.sbatch)"
  echo "  characterization array: $CHID ($NDES designs)"
  echo "  summary job:            $SUMID"
  echo
  echo "Submitted. Watch with:  squeue -u $USER"
  echo "Table prints to         characterize_${SUMID}_0.out"
  exit 0
fi

# --- 2. Sanity: required files ----------------------------------------------
for f in lazagna.def build_lazagna.sbatch worker_array.sbatch extras.sbatch collect.sbatch \
         campaign/worker.py campaign/phase_2dvs3d.py campaign/binds.sh \
         campaign/collect_results.py; do
  [ -e "$HERE/$f" ] || { echo "FATAL: missing $f in $HERE"; exit 1; }
done

# --- 3. Work dir for this campaign run ----------------------------------------
WORK_ROOT="${WORK_ROOT:-$HERE/campaign_work/$(date +%Y%m%d_%H%M%S)}"
mkdir -p "$WORK_ROOT"/{journal,bench}
echo "Work dir: $WORK_ROOT"

# Tunables travel via an env file, NOT sbatch --export (which splits on commas and
# would mangle values like STUDIES="columns,tpe"). Jobs source this if present.
ENVF="$WORK_ROOT/campaign.env"
: > "$ENVF"
for v in SEEDS TRIALS_COLUMNS TRIALS_SAMPLER STUDIES KEEP_RRG CW HB_GRID HB_CW \
         FIDELITY TARGET_UTIL TALL COLUMNS_DESIGN PROMOTE_TOP PROMOTE_RANDOM DESIGNS_2DVS3D; do  # CW defaults to 300 in-code
  if [ -n "${!v:-}" ]; then printf '%s=%q\n' "$v" "${!v}" >> "$ENVF"; fi
done
[ -s "$ENVF" ] && { echo "Tunables ($ENVF):"; cat "$ENVF"; }

# --- 4. Build the image if needed -------------------------------------------
SIF="$HERE/lazagna.sif"
DEP=""
if [ ! -f "$SIF" ]; then
  echo "lazagna.sif not found -> queuing build (build_lazagna.sbatch)..."
  BID="$(sbatch --parsable -A "$ACCT" -q "$QUEUE" build_lazagna.sbatch)"
  echo "  build job: $BID"
  DEP="--dependency=afterok:$BID"
else
  echo "lazagna.sif present -> skipping build. (After a git pull: rm lazagna.sif to force rebuild.)"
fi

# --- 5. Submit workers + extras + collect -------------------------------------
EXPORTS="ALL,WORK_ROOT=$WORK_ROOT"   # only WORK_ROOT rides --export; tunables via campaign.env

WORKER_IDS=""
if [ -n "$BATCHES" ]; then
  echo "  batch ablation: widths [$BATCHES], $TRIALS_SAMPLER trials per sampler per width"
  for B in $BATCHES; do
    # Sequential work per worker scales as trials/batch, so give narrow arms a longer wall.
    if [ -n "$WALL" ]; then
      W="$WALL"
    elif [ "$B" -le 2 ]; then W="72:00:00"
    elif [ "$B" -le 10 ]; then W="36:00:00"
    else W="16:00:00"
    fi
    JID="$(sbatch --parsable -A "$ACCT" -q "$QUEUE" $DEP --time="$W" \
            --array=0-$((B-1)) --export="$EXPORTS,BATCH=$B" worker_array.sbatch)"
    echo "    batch $B: job $JID ($B concurrent workers, wall $W)"
    WORKER_IDS="$WORKER_IDS:$JID"
  done
else
  JID="$(sbatch --parsable -A "$ACCT" -q "$QUEUE" $DEP \
          --array=0-$((N_WORKERS-1)) --export="$EXPORTS" worker_array.sbatch)"
  echo "  worker array: $JID (${N_WORKERS} jobs)"
  WORKER_IDS=":$JID"
fi
WID="${WORKER_IDS#:}"

EID="$(sbatch --parsable -A "$ACCT" -q "$QUEUE" $DEP --export="$EXPORTS" extras.sbatch)"
echo "  extras job:   $EID"

CID="$(sbatch --parsable -A "$ACCT" -q "$QUEUE" \
        --dependency="afterany${WORKER_IDS}:$EID" --export="$EXPORTS" collect.sbatch)"
echo "  collect job:  $CID (runs after workers + extras)"

echo
echo "Submitted. Watch with:  squeue -u $USER"
echo "Summary lands in:       $WORK_ROOT/campaign_summary.md"
echo "Study progress:         grep complete worker_*.out | tail"
