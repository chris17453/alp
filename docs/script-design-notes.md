# What Chinese characters do right — and what the ALP script does not (yet)

A study of hanzi as an engineered writing system, held against the current
ALP character composer (`src/alp/script.py`).  Each point ends with the
concrete change it implies.

## 1. Components deform to fit; they are not shrunk into corners

In hanzi a component has **positional allomorphs**.  木 is a full square on
its own; as a left-hand radical it narrows to 朩 and gives up 2/3 of the
width; 火 flattens to 灬 at the bottom; 水 becomes the three drops 氵; 人 becomes
亻 on the left and 𠆢 on top.  The component keeps its identity through its
stroke *topology*, and the character keeps its **even ink** through
proportional reshaping.

The ALP composer keeps every component at a fixed size in a fixed zone.  A bare
head floats in an empty box; a loaded head is crowded at the same size.  That
is the whitespace problem you are seeing: the box is sized for the worst case
and most characters are far below it.

**Change:** the head must claim the whole em-box when it is alone and give up
space proportionally as components arrive — and the components must be drawn
as reshaped strokes of the head's scale, not miniature icons at a constant
size.  Left radical: narrow tall form.  Crown: flattened wide form.  Ground:
wide low form.

## 2. A character is one of ~12 structures, not one grid

Every hanzi is one of a small set of composition structures — the Ideographic
Description Characters: ⿰ left–right, ⿱ top–bottom, ⿲ three across, ⿳ three
down, ⿴ full enclosure, ⿵ enclosure open at the bottom, ⿶ open at the top, ⿷
open on the right, ⿸ upper-left hook, ⿹ upper-right, ⿺ lower-left, ⿻ overlaid.
The structure is chosen by what the character contains, and each structure has
canonical proportions (⿰ splits roughly 1:2 or 1:1; ⿱ splits by stroke count).

The ALP composer has exactly one structure for everything: centre head with
all eight zones reserved.  A character with only a temporal modifier still
pays for the crown, the radical column, the connector column and the role row.

**Change:** select a structure per character from the classes present —
head only → ⿻ (head fills the box); head + illocution → ⿰; head + valence →
⿱; head + modal → ⿴; head + temporal → ⿱ with the ground as the lower part;
head + roles → ⿳ — and lay out with that structure's proportions.  Unused
zones do not exist.

## 3. Strokes touch; nothing floats

In a hanzi, strokes **join** at defined points (the stroke order dictates
where), and the white space inside is counted as deliberately as the black
(布白, "arranging the white").  Two strokes are never closer than one stroke
width unless they meet.  A mark that does not connect to the body reads as a
separate character — which is exactly the failure mode here: the small marks
around the head look like debris rather than parts.

**Change:** every modifier stroke must either be attached to the head/enclosure
(share a point with it) or sit on a shared guide (the headline, the ground
line, the vertical axis).  The connector starts *on* the enclosure edge; the
left radical's foot sits *on* the ground line; inner marks sit *on* the
horizontal midline.  Marks that cannot attach are not drawn as marks — they
become a second character (see 5).

## 4. A closed stroke inventory with modulation

There are eight basic strokes (永字八法: dot, horizontal, vertical, hook,
rising, falling-left, falling-right, bend) with **weight modulation** — the
entry and exit of a stroke are shaped, a horizontal is thinner than a vertical,
a 捺 swells to its tail.  This gives every character the same rhythm at every
size, and lets a reader tell strokes apart by *shape* before counting them.

The ALP composer draws one weight everywhere plus a wedge on long strokes, and
its "form alphabet" of tiny bars/boxes has no modulation at all, so at 56 px
the marks collapse into similar grey specks.

**Change:** define the ALP stroke set once (horizontal, vertical, two
diagonals, hook, dot, arc, wave) with entry/exit shaping and a horizontal /
vertical weight ratio (about 0.75), and build *every* component from it —
heads, enclosures, marks, numerals.  Drop the form alphabet.

## 5. Complexity goes into more characters, not denser ones

Hanzi stroke counts cluster between 6 and 14; the writing system refuses to
make one character carry a paragraph.  Complex meanings are **compounds** —
two- or three-character words (电脑, 计算机), each character simple.  The
compound is the unit of meaning; the character is the unit of legibility.

The ALP composer tries to put every modifier of a composition into one cell,
and spills only when a zone is full.  A composition with five modifiers and
four roles becomes one unreadable cell.

**Change:** an ink budget per character (≈12 stroke-equivalents).  Beyond it
the composition is written as a compound: the head with its first-class
modifiers (scalar, epistemic, modal) in the first character, temporal +
valence in a second, roles in the following ones — with a fixed, learnable
order, joined under the word headline.  This is agglutination done the hanzi
way rather than the everything-in-one-box way.

## 6. The invisible grid is used, not just the box

Learners write on 米字格 paper: a square with its two axes and two diagonals.
Every stroke lands on or relative to those lines; the eye of a reader
reconstructs them.  That is what makes a character readable *without* a
printed box — the internal alignments imply the box.

The ALP composer aligns to a 17-unit grid but its zones do not sit on the 米
lines; the marks are at arbitrary offsets, so nothing implies the frame.

**Change:** snap all attachment points to the 米 grid: vertical axis, horizontal
axis, the two diagonals, and the thirds.  Symmetric heads centred on the axes;
crown and ground centred on the vertical axis and as wide as the head;
radical and connector on the horizontal axis.  Then the faint box becomes
optional.

## 7. Category radical at a conventional place, identity everywhere else

About 80 % of hanzi are 形声 (semantic radical + phonetic component).  The
radical is small, conventional, and *always in the same place for that
radical*; the rest of the character carries the distinguishing information.

ALP inverts this: the category (head) is the large centrepiece and the
distinguishing information (modifiers) is small.  For a reader scanning a line
that is backwards — you want to *find* the distinguishing part.

**Change (optional, larger):** allow the head to take the radical position
(left third, narrow allomorph) when the character carries three or more
modifiers, letting the modifier body occupy the right two-thirds at full
scale.  Bare heads stay full-size.

## 8. Simplification, not omission, at small sizes

Small hanzi are not drawn with details removed; the *strokes are simplified*
(printed forms, 楷 → 宋 conventions) so the topology survives.  The current LOD
rule deletes inner detail below 5 units, which is fine, but the surviving
silhouette is then drawn at the same hairline weight.

**Change:** weight scales *up* relative to size as the character shrinks
(a minimum stroke of ~1/12 em), and inner counters below ~2 px are closed
rather than drawn.

## 9. Curves are strokes, not decoration

撇 and 捺 (the falling strokes), 钩 (hooks) and 弯 (bends) are among the most
frequent strokes; a character without a curve is rare.  Curvature is a primary
identity cue.  The ALP composer added arcs for enclosures and a few marks; the
heads themselves are all straight except PLACE, MOMENT and GROUP.

**Change:** give the stroke set's diagonals a slight curve and taper, and let
at least four heads carry a curved stroke as part of their silhouette
(PROCESS's chevron as a bent stroke, SIGN's pennant tail as a 捺, AGENT's roof
as two falling strokes, EVENT's spark with hooked points).

## 10. Uniform advance, no whitespace bookkeeping

Because every character has even ink and a full box, hanzi text is set on a
plain grid with no kerning, and the reader never has to decide where one
character ends.  The headline added to ALP words is the Devanagari answer to
the same problem; it works, but it is compensating for uneven ink.  Once 1–6
above are done, the headline can become a light word-join rather than a
structural crutch.

---

## Status

Done in `script.py` (commit history has the steps): modulated stroke set
(heng/shu/pie/na/dian, horizontal:vertical ≈ 0.78, minimum weight 1/22 em);
structure selection — bands exist only for present components and the head
takes the largest remaining square; attachment — crown, ground, radical and
connector are sized from and placed on the head/enclosure edge; ink budget
(6 components) with a fixed compound split (head-shaping marks in the first
character, surroundings and role row in the second, head shown as a seed);
inner marks scale with the head; word headline.

Open: curved heads (9), radical-position variant (7), demoting the headline
(10), and the literal characters (numerals, units) which still use the old
form alphabet.

## Order of work

1. Stroke set with modulation (4) — everything else is drawn with it.
2. Structure selection + proportional layout + allomorphs (1, 2, 6).
3. Attachment rule (3).
4. Ink budget and compound splitting (5).
5. Curved heads (9), small-size weighting (8).
6. Revisit the radical-position variant (7) and demote the headline (10).

Each step keeps SIDs and ALP/T unchanged: this is rendering only.  The
transliteration remains the normative form; the script is a projection of it.
