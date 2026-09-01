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

# animation: a word written stroke by stroke; the letter being written; a short title film
$A animate "\$RELATION.CAUSE.INFERRED.CONTESTED :ARG0 (\$EVENT.PAST.PUNCTUAL) :ARG1 (\$STATE.NEGATE.BAD :SCOPE \$PROCESS)" \
   --gif $OUT/10-one-word.gif --mp4 $OUT/10-one-word.mp4 --cell 160 --fps 20 --seconds 3.5
$A animate -f examples/document.txt --mp4 $OUT/11-document-written.mp4 --cell 64 --fps 18 --width 1280
$A animate --title-sequence "We suspect the deploy caused the outage." --mp4 $OUT/12-title-sequence.mp4 --fps 20

ls $OUT

# options: English captions under the words; the same word alive (pulse) and traced; the palettes
$A render examples/complex.txt --captions --no-translit --png $OUT/04b-complex-captions.png --cell 80 --title "complex thoughts — with English captions"
$A animate "\$RELATION.CAUSE.INFERRED.CONTESTED :ARG0 (\$EVENT.PAST.PUNCTUAL) :ARG1 (\$STATE.NEGATE.BAD :SCOPE \$PROCESS)" --mode pulse --palette neon --gif $OUT/13-pulse.gif --cell 140 --fps 15 --seconds 4
$A animate "\$RELATION.CAUSE.INFERRED.CONTESTED :ARG0 (\$EVENT.PAST.PUNCTUAL) :ARG1 (\$STATE.NEGATE.BAD :SCOPE \$PROCESS)" --mode trace --gif $OUT/14-trace.gif --cell 140 --fps 15 --seconds 4
uv run python - <<'PY'
from PIL import Image, ImageDraw, ImageFont
from alp import script
from alp.composition import parse
c = parse('$RELATION.CAUSE.INFERRED.CONTESTED :ARG0 ($EVENT.PAST.PUNCTUAL) :ARG1 ($STATE.NEGATE.BAD :SCOPE $PROCESS)')
rows = []
for name in script.PALETTES:
    im = script.render_word(c, script.CharStyle(cell=110, palette=name))
    rows.append((name, im))
W = max(im.width for _, im in rows) + 160; H = sum(im.height + 16 for _, im in rows) + 16
out = Image.new("RGB", (W, H), script.THEMES["dark"]["bg"]); d = ImageDraw.Draw(out)
try: f = ImageFont.truetype("DejaVuSans.ttf", 18)
except Exception: f = ImageFont.load_default()
y = 8
for name, im in rows:
    d.text((12, y + im.height // 2 - 10), name, font=f, fill=script.THEMES["dark"]["text"])
    out.paste(im, (150, y)); y += im.height + 16
out.save("examples/output/15-palettes.png")
PY
ls $OUT | wc -l
