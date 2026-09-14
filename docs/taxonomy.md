# Facet vocabulary

A closed vocabulary. The model can only choose from these lists, so facets stay
filterable instead of turning into free-form tags.

## component — what it is

| value | when |
|---|---|
| `accordion` | sections that expand and collapse, usually mutually exclusive |
| `card` | a bounded, groupable unit of content |
| `nav` | navigation: bars, menus, tabs, breadcrumbs |
| `modal` | a layer on top that blocks what's underneath (drawers included) |
| `table` | tabular data, with or without sorting and filters |
| `form` | data entry, validation, multi-step |
| `timeline` | a sequence ordered by time or progress |
| `hero` | the opening block of a page |
| `sidebar` | a persistent side panel |
| `carousel` | content rotating in a fixed space |
| `tooltip` | ephemeral contextual information on hover or focus |
| `command-palette` | search with actions, ⌘K style |
| `chart` | data visualization |
| `other` | doesn't fit — check whether a new value is needed |

## motion — how it moves

`fade` opacity · `slide` movement along one axis · `scale` size ·
`morph` one element turns into another keeping its identity ·
`stagger` several elements with a delay between them · `parallax` layers
moving at different speeds on scroll · `spring` physics, bounce or overshoot ·
`reveal` content appearing as it enters the viewport · `none` static

`morph` vs `scale`: if the element changes shape or function it's morph; if it
only grows or shrinks, scale.

## layout — how it's arranged

`grid` a regular grid · `split` two major areas · `stacked` vertical stack ·
`bento` a grid of unequal cells · `full-bleed` edge to edge · `centered` a
centered column with margins · `asymmetric` deliberate imbalance

`bento` vs `grid`: bento has cells of different sizes by design.

## density — how much information per screen

`sparse` lots of air, little content · `balanced` the usual middle ground ·
`dense` a lot of information packed together, dashboard or terminal style

## color

`monochrome` a single hue family · `high-contrast` sharp jumps ·
`pastel` low saturation, high lightness · `dark` dark background ·
`vibrant` high saturation · `muted` subdued, desaturated

## source

Set automatically from where the capture came from: `x`, `instagram`,
`linkedin`, `web`.

## Style — one set per capture, one value per trait

These describe the visual language of the whole post, not of one pattern. The
palette isn't here: it's measured from pixels, because a vision model makes up
hex codes.

| trait | values |
|---|---|
| `typography` | `geometric-sans` pure circular shapes · `grotesk` neutral, Helvetica or Inter style · `humanist-sans` strokes with calligraphic modulation · `serif` · `mono` · `display` expressive, for headlines |
| `radius` | `none` sharp corners · `subtle` 2–4px · `rounded` clearly rounded · `pill` fully rounded ends |
| `spacing` | `tight` · `comfortable` · `airy` |
| `depth` | `flat` no shadows · `soft-shadow` diffuse shadows · `layered` several elevations · `glass` translucent with blur |
| `motion_feel` | `snappy` short and crisp · `smooth` soft, no bounce · `springy` with overshoot · `none` |

`typography` is the family, not the font: the model can't identify it.

---

## Adding values

Only when something shows up three or four times and fits nothing existing. A
vocabulary that grows with every capture stops being useful for filtering. Two
places to change: the `FACETS` or `STYLE` dictionary in `worker/pipeline.py`
(the prompt and the validation are built from it) and this table.
