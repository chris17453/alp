#!/usr/bin/env sh
# Regenerate examples/output/ — a curated set.  Run from the repo root: sh examples/make_examples.sh
set -e
OUT=examples/output
rm -rf "$OUT"; mkdir -p "$OUT"
A="uv run alp"

# the script
$A chart --png $OUT/01-character-chart.png                                   # heads, scaling, every class as a transformation, literals
$A key   --png $OUT/02-key.png                                               # every primitive drawn with the script, with its name and sense
$A render "\$RELATION.CAUSE.INFERRED.CONTESTED :ARG0 (\$EVENT.PAST.PUNCTUAL) :ARG1 (\$STATE.NEGATE.BAD :SCOPE \$PROCESS)" \
         --png $OUT/03-one-word.png --cell 180 --title "one word: deploy is the suspected, disputed cause of the outage"

# English -> script
$A render examples/complex.txt  --png $OUT/04-complex-script.png --svg $OUT/04-complex-script.svg --cell 72 --title "complex thoughts"
$A render examples/complex.txt  --english --style each --png $OUT/05-complex-with-english.png --cell 96 --title "complex thoughts — with English"
$A translate -f examples/complex.txt --stats -v > $OUT/05-complex-translation.txt

# a document transcript (both directions: English -> ALP -> English)
$A transcribe -f examples/document.txt -o $OUT --name 06-document --clock 1788186000 --cell 64 --title "document — transcript" > /dev/null
rm -f $OUT/06-document-script.png

# the protocol
$A encode -f examples/incident.txt --author ops --stream incident-demo --clock 1788186000 -o $OUT/07-incident.alpb
$A export $OUT/07-incident.alpb -o $OUT/07-incident.alpt
$A render $OUT/07-incident.alpt --pdf $OUT/07-incident-audit.pdf --title "incident — stream audit"
$A verify $OUT/07-incident.alpt > $OUT/07-incident-verify.txt
uv run python examples/two_agents.py --alpt $OUT/08-two-agents.alpt --png $OUT/08-two-agents.png > $OUT/08-two-agents.log
uv run python examples/build_conversation.py > $OUT/09-appendix-d.alpt

ls $OUT
