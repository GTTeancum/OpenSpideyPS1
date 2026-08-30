# tools/

## RecompOne

The recompiler and runtime both games in this repository build against, from
<https://github.com/BlackLabelHQ/RecompOne> at commit `132378d`, plus local fixes.

The upstream `.git` was removed so the source is tracked here as ordinary files —
the port depends on specific fixes and a bare clone of upstream will not build it.
`recompone-spiderman-changes.patch` is the diff against `132378d`, kept so the local
changes stay legible and can be sent upstream. All of them are game-agnostic; see the
"Fixes made to RecompOne" section of `../spiderman/README.md` for what each one is for.

Rebuild with:

```bash
dotnet build -c Release tools/RecompOne/RecompOne.sln
```

## enginematch.py

Carries hand-identified function names from one game to another built on the same engine.

Two titles from the same studio and generation share most of their engine, but every
address moves, so a byte compare finds nothing and every name recovered by hand for one
port would have to be recovered by hand again for the next. This matches on *instruction
shape* instead: each word reduced to the opcode, the register fields and — for SPECIAL
— the function code, with branch displacements, immediates and the 26-bit target of
`j`/`jal` dropped. What survives is the register allocation and control flow the compiler
produced, which a relink does not change.

It is game-agnostic: both executables and the symbol file are arguments, and it writes a
new symbol file rather than touching either game's tree.

```bash
python tools/enginematch.py \
  --from spiderman/extracted/SLUS_008.75  --from-size B6800 \
  --syms spiderman/config/funcmaps/manual.json \
  --to   spiderman2/extracted/SLUS_013.78  --to-size BF800 \
  --out  new_manual.json
```

It reports a score and the margin over the runner-up for each name, and refuses to guess
at functions too short to be distinctive. **A score is not a verification** — every name
it places still has to be read at its new address before it is trusted. Moving Spider-Man's
map onto Spider-Man 2 placed nine names at a perfect score; see
`../spiderman2/README.md` for how they were then confirmed.
