# Always-on perspective-correct texturing

The shared RecompOne renderer applies perspective-correct texture interpolation to
camera-projected geometry in both Spider-Man games. This is renderer behavior, not a
game option or compatibility toggle.

## Data path

1. Each GTE projection couples its packed `SXY` result with the corresponding camera-space `SZ` value and its pre-rounded 16.16 screen X/Y in the GTE screen FIFO.
2. Recompiled direct register moves, loads, and stores preserve that complete vertex tag while a projected coordinate is assembled into a GPU packet. Arithmetic may safely retain an unambiguous depth tag, but clears subpixel X/Y because the packed coordinate was deliberately modified.
3. Main RAM and the PS1 scratchpad retain exact `{word value, depth, subpixel X/Y}` provenance. DMA and ordering-table submission transfer it beside the GP0 command FIFO, so reused screen coordinates cannot inherit an unrelated vertex's projection.
4. Textured GPU polygons use perspective correction only when every authored vertex carries exact packet provenance. No screen-coordinate reverse lookup is used as a rendering fallback; that approach is ambiguous and can bend otherwise-correct world geometry.
5. GL backends render exact GTE screen coordinates before PS1 integer snapping and place camera depth in clip-space `w`, which makes the GPU interpolate `u/w`, `v/w`, and `1/w`; vertex color is compensated so the games' original affine Gouraud lighting does not change.
6. The software rasterizer evaluates the equivalent barycentric quotient per pixel.

Screen-space HUD, sprites, menus, video, and CPU-authored effects have no camera-space
depth and retain their authored 2D interpolation. A polygon with incomplete provenance
also keeps its original mapping rather than mixing real and invented depth within one
polygon. Neither case is a user-selectable renderer mode.

## Shipping renderer policy

Shipping builds contain only the OpenGL 4.5 and OpenGL 3.3 core renderers. The legacy
OpenGL 2.1 renderer is excluded at compile time and has no user-facing selector. A
developer must explicitly build with `/p:EnableLegacyRenderer=true` and set
`RECOMPONE_REFERENCE_RENDERER=gl21` to use it for reference.

## Verification

- Release builds pass for the shared runtime and both game ports.
- SM1 level `l1a1` completed native in-process 4:3 and 16:9 gameplay captures on the OpenGL 4.5 renderer at 4x render scale with FXAA.
- SM2 level `e1m4` completed a native in-process 16:9 gameplay capture on the same renderer and settings; its HUD-free side completion no longer copies HUD or searches arbitrarily across scene pixels.
- Runtime traces recorded hundreds of thousands of depth-corrected textured triangles in each game and confirmed that the large SM1 rooftop/building packets retain exact scratchpad-staged depth.
- Adjacent SM1 rooftop frames confirm that pre-rounded screen coordinates remove the whole-pixel parapet stepping that becomes conspicuous at 4x internal resolution; native 4:3 controls and SM2 16:9/4:3 captures retain intact HUD and compass rendering.
- Every captured frame was inspected at full resolution for UV foldover, diagonal seams, shader/color changes, HUD distortion, and unstable geometry. The suitability of SM2's boundary continuation across every level remains part of the separate widescreen audit.

Set `RECOMP_PERSPECTIVE_TRACE=1` only when diagnostic triangle counts are needed. It
does not enable or disable perspective correction.
