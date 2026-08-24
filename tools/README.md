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
