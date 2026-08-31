#!/usr/bin/env sh
# Regenerate everything in examples/output/.  Run from the repo root: sh examples/make_examples.sh
set -e
OUT=examples/output
mkdir -p "$OUT"
A="uv run alp"

# 1. the primitive inventory chart
$A inventory --png $OUT/inventory.png --pdf $OUT/inventory.pdf > $OUT/inventory.txt

# 2. single compositions from the RFC's Appendix A, hashed and drawn
$A compose '$PROPERTY.HIGH.PUNCTUAL.REQUIRED' --gloss "urgency" --png $OUT/urgency.png > $OUT/urgency.txt
$A compose '$MOMENT.FUTURE.PUNCTUAL.BOUNDED' --gloss "deadline" --png $OUT/deadline.png > $OUT/deadline.txt
$A compose '$STATE.NEGATE.NOW.BAD :SCOPE $PROCESS' --gloss "outage" --png $OUT/outage.png > $OUT/outage.txt
$A compose '$RELATION.CAUSE.INFERRED.CONTESTED :ARG0 ($EVENT.PAST.PUNCTUAL ~"deploy 4471") :ARG1 $STATE' \
   --gloss "suspected root cause" --png $OUT/root-cause.png --pdf $OUT/root-cause.pdf > $OUT/root-cause.txt
$A compose '$QUANTITY.UNBOUNDED.UNKNOWN :SCOPE $GROUP :MEASURE $ENTITY' --gloss "unknown blast radius" --png $OUT/blast-radius.png > $OUT/blast-radius.txt

# 3. English -> compositions, with the residue metric
$A translate -f examples/incident.txt --stats -v --png $OUT/incident-translation.png --pdf $OUT/incident-translation.pdf > $OUT/incident-translation.txt

# 4. English -> full ALP stream: binary, text, images, and back to English
$A encode -f examples/incident.txt --author ops --stream incident-demo --clock 1788186000 --stats \
   -o $OUT/incident.alpb --png $OUT/incident-symbols.png --pdf $OUT/incident-symbols.pdf 2> $OUT/incident-encode.log
$A export $OUT/incident.alpb -o $OUT/incident.alpt
$A render $OUT/incident.alpt --pdf $OUT/incident-audit.pdf --png $OUT/incident-audit.png --title "incident stream audit"
$A decode $OUT/incident.alpb --events > $OUT/incident-decoded.txt
$A decode $OUT/incident.alpb --readings >> $OUT/incident-decoded.txt
$A verify $OUT/incident.alpt > $OUT/incident-verify.txt
$A stats $OUT/incident.alpb > $OUT/incident-stats.txt
$A export $OUT/incident.alpb --archive -o $OUT/incident-archive-sid256.alpt

# 5. the RFC Appendix D worked conversation (every event type, a fork, a repair, a model swap)
uv run python examples/build_conversation.py --alpb $OUT/appendix-d.alpb --png $OUT/appendix-d.png --pdf $OUT/appendix-d.pdf > $OUT/appendix-d.alpt

ls -la $OUT
