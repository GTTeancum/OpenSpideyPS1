using RecompOne.Recompiler.Disasm;

namespace RecompOne.Recompiler.Analysis;

public static class LabelManager
{
    public static HashSet<uint> Collect(MipsFunction func)
    {
        var labels = new HashSet<uint>();

        foreach (var instr in func.Instructions)
        {
            if (!instr.HasDelaySlot) continue;

            uint op = instr.Word >> 26;

            if (op is 1 or 4 or 5 or 6 or 7) //these: REGIMM, BEQ, BNE, BLEZ, BGTZ
            {
                uint t = instr.BranchTarget;
                if (t >= func.Start && t < func.End) labels.Add(t);
            }
            else if (op == 2) //internal function goto
            {
                uint t = instr.JumpTarget;
                if (t >= func.Start && t < func.End) labels.Add(t);
            }
        }

        // Hand-written assembly calls its own local subroutines with `jal`, so the
        // matching `jr ra` returns to a point *inside* this function rather than to
        // its caller. Those return sites need labels; see LocalReturns.
        foreach (uint r in LocalReturns(func)) labels.Add(r);

        foreach (var jtbl in func.JumpTables)
            foreach (uint entry in jtbl.Entries)
                if (entry >= func.Start && entry < func.End)
                    labels.Add(entry);

        return labels;
    }

    /// <summary>
    /// Addresses a `jr ra` in this function can land on without leaving it: the
    /// instruction after each `jal` that calls one of the function's own *interior*
    /// entry points.
    ///
    /// A compiler never emits these -- it calls out and returns out -- but hand-written
    /// routines routinely fall into a shared tail through `jal` and come back through
    /// `jr ra`. Treating that `jr ra` as a function return skips the epilogue, so the
    /// frame is never popped and the caller reads its saved registers back from the
    /// wrong addresses.
    ///
    /// A `jal` to the function's own first instruction is recursion, not this idiom:
    /// it makes a fresh frame and its `jr ra` has to be a real return. Including those
    /// return sites turns every recursive call into a jump back into the *caller's*
    /// frame, which pops the stack once per level too often.
    /// </summary>
    public static HashSet<uint> LocalReturns(MipsFunction func)
    {
        var sites = new HashSet<uint>();
        foreach (var instr in func.Instructions)
        {
            if ((instr.Word >> 26) != 3) continue;             // jal
            uint target = instr.JumpTarget;
            if (target <= func.Start || target >= func.End) continue;   // > Start: not recursion
            uint back = instr.Vram + 8;                        // past the delay slot
            if (back >= func.Start && back < func.End) sites.Add(back);
        }
        return sites;
    }

    /// <summary>
    /// The `jr ra` instructions in this function that return to one of its own interior
    /// entry points rather than to its caller.
    ///
    /// The two are told apart by what precedes them. A real return reloads `ra` from
    /// the frame first -- that is what an epilogue *is* -- while a local subroutine
    /// leaves `ra` exactly as the `jal` that called it set it, and so has no reload in
    /// front of it. Restricting the dispatch to the second case matters: rewriting an
    /// ordinary return into a jump back into the function turns it into a loop.
    /// </summary>
    public static HashSet<uint> LocalReturnJrs(MipsFunction func)
    {
        var result = new HashSet<uint>();
        if (System.Environment.GetEnvironmentVariable("RECOMPONE_NO_LOCALRET") != null) return result;
        if (LocalReturns(func).Count == 0) return result;

        var instrs = func.Instructions;
        for (int i = 0; i < instrs.Length; i++)
        {
            uint w = instrs[i].Word;
            if ((w >> 26) != 0 || (w & 0x3F) != 8) continue;      // not jr
            if (((w >> 21) & 31) != 31) continue;                 // not jr ra

            // Far enough back to cover a full epilogue. Restoring ra, s0-s7, fp and at
            // plus the stack adjustment is a dozen instructions on its own, and a window
            // that stops short of the `lw ra` reads a perfectly ordinary return as a
            // local one.
            bool raReloaded = false;
            for (int k = System.Math.Max(0, i - 24); k < i; k++)
            {
                uint p = instrs[k].Word;
                if ((p >> 26) == 0x23 && ((p >> 16) & 31) == 31) { raReloaded = true; break; }
            }
            if (!raReloaded) result.Add(instrs[i].Vram);
        }
        return result;
    }
}
