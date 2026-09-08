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
dotnet run --project tools/RecompOne/tests/InteriorHookRegression -c Release
```

The two rendering suites and the hook execution regression pass. They exercise
each game's actual native routines, including
subdivision clamps and projective midpoints, packed edge borrowing, shared edges
at near and distant depths, ray/plane texture samples, thin joint triangles, and
4:3 versus widened bounds admission with exact GTE matrix restoration.

Native GPU captures on 2026-09-08 reproduced the stepped crate seams in the old
SM2 Shocker warehouse build. A solid-floor diagnostic then exposed an intermittent
crack left by the first repair. The remaining cause was the host projection using
rounded IR/SZ coordinates and the native approximate reciprocal. Host X/Y and depth
now come from the same unrounded homogeneous GTE transform; native registers and
flags remain intact. A rotated-edge regression fails before this change and passes
afterward, with identical native screen words. This also removes the normal
reciprocal approximation from perspective texture interpolation.

The matched warehouse pose at frame 4498 shows the floor crack before the exact
projection and a continuous floor afterward. In the unobstructed floor rectangle
x=340..599, y=645..704, nonwhite pixels fall from 363 to zero. Both neighboring
captures, 4502 and 4506, were inspected and remain continuous. Four normal-texture
warehouse captures were also inspected. These are native GPU readbacks; the solid
floor mode changes only material flags/color, leaving submitted geometry intact.
Two outdoor widescreen views retain visible roof/parapet coverage before and after
the camera turns. Two 4:3 warehouse views also retain continuous crate edges.
This establishes the reproduced defects, not every animation frame or level.

Overlapping native symbol ranges also permit local jumps into hooked helpers.
The recompiler now invokes the hooked entry on those paths and resumes the native
return address inside the enclosing function. Its execution regression verifies
one hook invocation, the caller's remaining work, restored stack, and preserved
return address. This routing correction alone did not remove the captured floor
crack; the homogeneous projection change did. Regenerate both games to receive
the routing correction.

Ordinary late gameplay measurements were approximately 28–29.5 presented FPS
against the 30 FPS target. The first detailed perspective-trace run was slower;
normal launches leave those diagnostics disabled. Capture was limited to a few
stills per run, with no concurrent video encoding. Proof media and local build
artifacts remain excluded from Git.
