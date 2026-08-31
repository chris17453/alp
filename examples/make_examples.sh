#!/usr/bin/env sh
# Regenerate everything in examples/output/.  Run from the repo root: sh examples/make_examples.sh
set -e
OUT=examples/output
rm -rf "$OUT"; mkdir -p "$OUT"
A="uv run alp"

# 1. the script itself: glyph key (the only English), raw glyph sheet as SVG
$A key --png $OUT/glyph-key.png --pdf $OUT/glyph-key.pdf --svg $OUT/glyph-sheet.svg
$A inventory > $OUT/inventory.txt

# 2. Appendix A compositions written by hand, hashed and drawn as blocks
$A compose '$PROPERTY.HIGH.PUNCTUAL.REQUIRED' --png $OUT/urgency.png > $OUT/urgency.txt
$A compose '$MOMENT.FUTURE.PUNCTUAL.BOUNDED' --png $OUT/deadline.png > $OUT/deadline.txt
$A compose '$STATE.NEGATE.NOW.BAD :SCOPE $PROCESS' --png $OUT/outage.png > $OUT/outage.txt
$A compose '$PROCESS.INCREASE.FUTURE :ARG0 $AGENT :ARG1 $SIGN' --png $OUT/escalate.png > $OUT/escalate.txt
$A compose '$RELATION.CAUSE.INFERRED.CONTESTED :ARG0 ($EVENT.PAST.PUNCTUAL) :ARG1 ($STATE.NEGATE.BAD :SCOPE $PROCESS)' \
   --png $OUT/root-cause.png --pdf $OUT/root-cause.pdf > $OUT/root-cause.txt
$A compose '$QUANTITY.UNBOUNDED.UNKNOWN :SCOPE $GROUP :MEASURE $ENTITY' --png $OUT/blast-radius.png > $OUT/blast-radius.txt

# 3. English -> compound symbols.  Script only (no English) and, separately, with the English key beside each block.
$A translate -f examples/incident.txt --stats -v > $OUT/incident-translation.txt
$A render examples/incident.txt --png $OUT/incident-script.png --pdf $OUT/incident-script.pdf --linear $OUT/incident-linear.png --title "incident — script"
$A render examples/incident.txt --english --png $OUT/incident-script-with-english.png --title "incident — script with English key"
$A render examples/story.txt --png $OUT/story-script.png --linear $OUT/story-linear.png --title "story — script"
$A render examples/story.txt --english --pdf $OUT/story-script-with-english.pdf --title "story — script with English key"
$A translate -f examples/story.txt --stats > $OUT/story-translation.txt

# 4. English -> full ALP stream: binary, text, audit, back to English
$A encode -f examples/incident.txt --author ops --stream incident-demo --clock 1788186000 --stats \
   -o $OUT/incident.alpb 2> $OUT/incident-encode.log
$A export $OUT/incident.alpb -o $OUT/incident.alpt
$A render $OUT/incident.alpt --pdf $OUT/incident-audit.pdf --png $OUT/incident-audit.png --title "incident stream audit"
$A decode $OUT/incident.alpb --events > $OUT/incident-decoded.txt
$A decode $OUT/incident.alpb --readings >> $OUT/incident-decoded.txt
$A verify $OUT/incident.alpt > $OUT/incident-verify.txt
$A stats $OUT/incident.alpb > $OUT/incident-stats.txt
$A forks $OUT/incident.alpb > $OUT/incident-forks.txt 2>&1
$A export $OUT/incident.alpb --archive -o $OUT/incident-archive-sid256.alpt

# 5. the RFC Appendix D worked conversation (every event type, a fork, a repair, a model swap)
uv run python examples/build_conversation.py --alpb $OUT/appendix-d.alpb --png $OUT/appendix-d.png --pdf $OUT/appendix-d.pdf > $OUT/appendix-d.alpt

ls -la $OUT
