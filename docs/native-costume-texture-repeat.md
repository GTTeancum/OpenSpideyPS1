# Native costume texture repeat

The Dreamcast-body SM2 suit mappings include coordinates beyond a source texture's
width or height. Blender's image repeat mode makes those coordinates valid. The
native game instead relocates byte UVs into a shared texture atlas; coordinates
outside a subtexture can then sample a different page. A correct Blender render
therefore does not, by itself, prove that the native packed actor renders correctly.

`dreamcast/tools/pack_sm2_costume_to_dc.py` audits all emitted face corners, including
alternate hands and wing/seam faces. Where needed, it expands an indexed page with
exact periodic copies of the original pixels. It does not clamp UVs, move vertices,
change bindings, rescale the artwork, or alter palette colors. This is a compatibility
encoding for native byte-UV models, not a new limit on host HD texture replacements.

Texture records retain their semantic indices and ordinal order. The retail loader
requires their payloads to be physically contiguous after the pointer table; merely
appending a relocated record is invalid even if a standalone parser accepts it.

Both costume builders use this path. SM1 embeds the expanded library in each actor
and writes a matching companion library. SM2 uses its shared actor with nineteen
expanded libraries; its separate Bag Man and Peter Parker Dreamcast actors remain
on their existing special-topology path. Wing visibility still comes from each
suit's authored texture, not a blanket wingless conversion policy.

The default winged suit has its own checked-in oracle map,
`dreamcast/manifests/sm1-sm2-costume-native-maps/sp2default.json`. Default builds must
regenerate it into a native actor, not copy a previous proof conversion implicitly.

## Regression and release checks

```powershell
python -m unittest discover -s dreamcast/tools -p test_native_texture_repeat.py -v
python dreamcast/tools/build_sm1_sm2_costumes.py
python dreamcast/tools/build_sm2_spider_man_costume_pack.py
```

The regression suite covers packed 4/8-bit texels, periodic equality, palettes,
semantic indices versus record order, all four quad corners, boundary coordinates,
idempotence, preserved geometry, and malformed containers. The coverage auditor
independently compares every expanded texel with its source and checks that no
native face still needs more page coverage. Structural reports are not visual passes.

Review exported native models in Blender and verify native gameplay captures before
updating ship bundles. Copy reviewed SM1 imported actors/companions into the
`dreamcast/converted/all-characters` staging directory, then rebuild embedded assets
and both executables as described in `docs/first-run-installation.md`. Verify installed
file hashes against the new bundle manifest; old captures are not evidence for a new
asset hash. No environment replacement is involved.
