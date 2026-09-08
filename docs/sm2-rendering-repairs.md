# SM2 perspective and widescreen repairs

SM2 now applies the shared precise-projection repairs to its native world geometry
and object selection. Previously, subdivision used rounded camera coordinates and
integer edge expansion, bending texture lines where neighboring faces subdivided
differently. Its object bounds tests also retained the narrower view. Repeating
boundary pixels in the compositor concealed some missing geometry but stretched
surfaces; SM2 no longer enables that completion pass by default.

The following native routines were compared against SM1 before sharing hooks:

| Operation | SM1 | SM2 | Native comparison |
| --- | --- | --- | --- |
| Object frustum | 8007B1B4 | 800877F4 | Same 1,508-byte routine apart from relocated globals and branches |
| Subdivision corners | 8007D2D8 | 80089918 | Identical 100-byte routine |
| Subdivision grid | 8007D33C | 8008997C | Same 356-byte routine apart from its scratch-output companion address |
| Edge expansion | 8007D534 | 80089B74 | Identical 72-byte routine |

Native packet words and subdivision CPU outputs remain intact. The host keeps
precise projective coordinates beside them. Horizontal bounds planes match the
current projection; vertical and behind-camera rejection remain active. The shared
GTE repairs also preserve near-camera projection, screen-register provenance, and
thin-triangle winding in SM2.

## Verification

After regenerating each game's code, run:

```powershell
dotnet run --project tools/RecompOne/tests/RenderingRegression -c Release
dotnet run --project tools/RecompOne/tests/Sm2RenderingRegression -c Release
```

Both suites pass. They exercise each game's actual native routines, including
subdivision clamps and projective midpoints, packed edge borrowing, shared edges
at near and distant depths, ray/plane texture samples, thin joint triangles, and
4:3 versus widened bounds admission with exact GTE matrix restoration.

Native GPU captures on 2026-09-08 reproduced the stepped crate seams in the old
SM2 Shocker warehouse build. Inspected repaired warehouse views in 16:9 and 4:3,
plus outdoor e1m0 rooftop views before and after movement, retain straight crate
edges and continuous visible roofs/parapets. All nine captured stills were inspected;
this is sampled scene verification, not an exhaustive review of every animation
frame or level. Combat moved the camera differently between runs, so the warehouse
stills are not exact matched-pose comparisons.

A small dotted floor line appeared in one repaired warehouse still. A subsequent
native triangle trace found overlapping floor coverage at the suspected boundaries,
and the traced still was continuous. Its appearance across every camera pose has
not been established; do not treat this as proof that every possible seam is gone.

Ordinary late gameplay measurements were approximately 28–29.5 presented FPS
against the 30 FPS target. The first detailed perspective-trace run was slower;
normal launches leave those diagnostics disabled. Capture was limited to a few
stills per run, with no concurrent video encoding. Proof media and local build
artifacts remain excluded from Git.
