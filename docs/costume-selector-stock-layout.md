# Costume selector stock-layout reference

The SM1 selector preserves retail styling with the user's requested column alignment.

- `shell:func_80261C70` calls `main:func_80016424` with X=24, Y=75,
  font=1, and a seventh argument of **10 pixels of row pitch**. That argument
  is not the entry capacity; the retail list allocation already holds 40 entries.
- The port moves the list's first text line from Y=75 to Y=70 to match the right
  column, displaying eleven rows at the retail 10-pixel pitch. The last baseline
  is Y=170, inside the aligned frame ending at Y=175. Further entries scroll.
  `func_800168C4` returns a 100-pixel row span, versus the original ten-row span of 90.
- The original listbox frame was shorter than the right panel. At the user's
  request, `Costume.AlignViewerFrame` now gives it the right panel's Y=58 and
  height=117, aligning both top and bottom edges. This deliberate retail-layout
  frame change leaves width, font and spacing unchanged; the text alignment above
  is applied separately by `Costume.ConfigureViewerList`.
  The earlier spacing regression came from passing costume count as row pitch.
- The right column retains the retail text draw path: font=1, X=355, initial Y=70,
  line pitch=10, original shadow and reveal behavior.
- `spiderman/extracted/wad/charbio.dat` uses color token 2 followed by heading
  RGB (105,105,0) or body RGB (68,68,100). Imported and mod descriptions use those
  exact values, not full-intensity yellow/white.

Validation: `SuitModRegression` includes actual retail
constructor/height functions and description palette checks. Native modern-renderer
captures in `proof_render/magenta-man/selection-03` show stock selection
(`frame_01874.png`), Magenta Man (`frame_02924.png`), and restored stock selection
(`frame_04074.png`). All three were inspected individually. The one-process smoke
test exited normally; no host input or desktop capture was used.

After the requested frame alignment, all 82 regression assertions passed. Native
captures `proof_render/magenta-man/aligned-boxes/frame_01865.png` and
`frame_02065.png` were each inspected: both frames share the same top and bottom
edges, with the existing text spacing and colors unchanged. The test exited normally.

The subsequent first-line alignment and eleven-row window passed all 82 regression
assertions. Native captures in `proof_render/magenta-man/aligned-text-eleven-rows`
(`frame_01817.png`, `frame_02867.png`, `frame_04017.png`) were inspected individually:
the first text lines align, the eleventh row clears the bottom border, and selecting
Magenta Man then scrolling back to stock works. The single-process test exited normally.
