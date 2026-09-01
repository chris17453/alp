#!/usr/bin/env sh
# Regenerate everything in examples/output/.  Run from the repo root: sh examples/make_examples.sh
set -e
OUT=examples/output
rm -rf "$OUT"; mkdir -p "$OUT"
A="uv run alp"

# 1. the script itself
$A chart --png $OUT/character-chart.png --pdf $OUT/character-chart.pdf
$A key --png $OUT/glyph-key.png --svg $OUT/glyph-sheet.svg
$A inventory > $OUT/inventory.txt

# 2. single compositions (RFC Appendix A) as characters, large
for pair in "urgency:\$PROPERTY.HIGH.PUNCTUAL.REQUIRED" "deadline:\$MOMENT.FUTURE.PUNCTUAL.BOUNDED" \
            "outage:\$STATE.NEGATE.NOW.BAD :SCOPE \$PROCESS" "escalate:\$PROCESS.INCREASE.FUTURE :ARG0 \$AGENT :ARG1 \$SIGN" \
            "root-cause:\$RELATION.CAUSE.INFERRED.CONTESTED :ARG0 (\$EVENT.PAST.PUNCTUAL) :ARG1 (\$STATE.NEGATE.BAD :SCOPE \$PROCESS)" \
            "blast-radius:\$QUANTITY.UNBOUNDED.UNKNOWN :SCOPE \$GROUP :MEASURE \$ENTITY"; do
  name=${pair%%:*}; comp=${pair#*:}
  $A compose "$comp" --png $OUT/$name.png --cell 160 --style each > $OUT/$name.txt
done

# 3. English -> script.  Running text (compact), then the same with the English key.
$A render examples/incident.txt --png $OUT/incident-script.png --pdf $OUT/incident-script.pdf --cell 64 --title "incident"
$A render examples/incident.txt --english --style each --png $OUT/incident-script-with-english.png --cell 96 --title "incident — with English"
$A render examples/story.txt    --png $OUT/story-script.png --cell 64 --title "story"
$A render examples/story.txt    --english --style each --pdf $OUT/story-script-with-english.pdf --cell 96 --title "story — with English"
$A render examples/complex.txt  --png $OUT/complex-script.png --cell 64 --title "complex thoughts"
$A render examples/complex.txt  --english --style each --png $OUT/complex-script-with-english.png --cell 96 --title "complex thoughts — with English"
$A translate -f examples/incident.txt --stats -v > $OUT/incident-translation.txt
$A translate -f examples/story.txt --stats > $OUT/story-translation.txt
$A translate -f examples/complex.txt --stats -v > $OUT/complex-translation.txt
$A render examples/story.txt --style block --png $OUT/story-blocks-expanded.png --title "story — expanded §6.2 blocks"

# 4. English -> full ALP stream: binary, text, conversation view, audit, back to English
$A encode -f examples/incident.txt --author ops --stream incident-demo --clock 1788186000 --stats -o $OUT/incident.alpb 2> $OUT/incident-encode.log
$A export $OUT/incident.alpb -o $OUT/incident.alpt
$A render $OUT/incident.alpt --png $OUT/incident-conversation.png --no-blocks --cell 56 --title "incident — conversation"
$A render $OUT/incident.alpt --pdf $OUT/incident-audit.pdf --title "incident — stream audit"
$A decode $OUT/incident.alpb --events > $OUT/incident-decoded.txt
$A decode $OUT/incident.alpb --readings >> $OUT/incident-decoded.txt
$A verify $OUT/incident.alpt > $OUT/incident-verify.txt
$A stats $OUT/incident.alpb > $OUT/incident-stats.txt
$A forks $OUT/incident.alpb > $OUT/incident-forks.txt 2>&1
$A export $OUT/incident.alpb --archive -o $OUT/incident-archive-sid256.alpt

# 5. the RFC Appendix D worked conversation
uv run python examples/build_conversation.py --alpb $OUT/appendix-d.alpb --png $OUT/appendix-d.png --pdf $OUT/appendix-d.pdf > $OUT/appendix-d.alpt

ls $OUT | wc -l

# 6. a document transcript: script, script+English, ALP/T, ALP/B, text
$A transcribe -f examples/document.txt -o $OUT --name document --clock 1788186000 --cell 56 --title "document — transcript" > $OUT/document-transcribe.log
ls $OUT | wc -l

# 7. two agents running the protocol
uv run python examples/two_agents.py --alpt $OUT/two-agents.alpt --alpb $OUT/two-agents.alpb --png $OUT/two-agents.png --pdf $OUT/two-agents.pdf > $OUT/two-agents.log
$A render examples/complex.txt --svg $OUT/complex-script.svg --png /dev/null 2>/dev/null || true
ls $OUT | wc -l
