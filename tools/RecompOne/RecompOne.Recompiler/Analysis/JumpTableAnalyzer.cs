using System.Buffers.Binary;
using RecompOne.Recompiler.Symbols;

namespace RecompOne.Recompiler.Analysis;

//still not sure if this works for all cases, seens to do, loosely based on n64recomp, but stupider
public static class JumpTableAnalyzer
{
    struct RegState
    {
        public uint PrevLui;
        public int  PrevAddiuLo;
        public bool ValidLui;
        public bool ValidAddiu;
        public bool ValidAddend;
        public bool ValidLoaded;
        public uint TableVram;

        public void Invalidate() => this = default;
    }

    public static List<JumpTable> Analyze(MipsFunction func, FunctionInfo elf)
    {
        var regs = new RegState[32];
        var result = new List<JumpTable>();

        foreach (var instr in func.Instructions)
        {
            uint op = instr.Word >> 26;
            uint fn = instr.Word & 0x3F;
            int  rs = instr.Rs, rt = instr.Rt, rd = instr.Rd;

            switch (op)
            {
                case 0:
                    switch (fn)
                    {
                        case 32: case 33:
                            if (rd != 0) Addu(regs, rs, rt, rd);
                            break;
                        case 37:
                            if (rd != 0)
                            {
                                if      (rs == 0) regs[rd] = regs[rt];
                                else if (rt == 0) regs[rd] = regs[rs];
                                else              regs[rd].Invalidate();
                            }
                            break;
                        case 8:
                            if (rs != 31 && regs[rs].ValidLoaded)
                            {
                                var entries = ReadEntries(elf, regs[rs].TableVram, func);
                                if (entries.Length > 0)
                                    result.Add(new JumpTable { JrVram = instr.Vram, Entries = entries });
                            }
                            break;
                        default:
                            if (rd != 0) regs[rd].Invalidate();
                            break;
                    }
                    break;

                case 8: case 9:
                {
                    var temp = regs[rs];
                    if (!temp.ValidAddiu)
                    { temp.PrevAddiuLo = (int)instr.ImmS; temp.ValidAddiu = true; }
                    else
                        temp.Invalidate();
                    if (rt != 0) regs[rt] = temp;
                    break;
                }

                case 15:
                    if (rt != 0)
                    {
                        regs[rt].Invalidate();
                        regs[rt].PrevLui = (uint)instr.ImmU << 16;
                        regs[rt].ValidLui = true;
                    }
                    break;

                case 35:
                    if (rt != 0)
                    {
                        var baseReg = regs[rs];
                        regs[rt].Invalidate();
                        if (rs != 29 && baseReg.ValidLui && (baseReg.ValidAddend || baseReg.ValidAddiu))
                        {
                            short imm = instr.ImmS;
                            bool  nonzero = imm != 0;
                            if (!(nonzero && baseReg.ValidAddiu))
                            {
                                uint lo16 = nonzero ? (uint)(int)imm : (uint)baseReg.PrevAddiuLo;
                                regs[rt].TableVram = baseReg.PrevLui + lo16;
                                regs[rt].ValidLoaded = true;
                            }
                        }
                    }
                    break;

                case 2: 
                case 4: 
                case 5:
                case 6: 
                case 7: break;
                case 3: 
                    regs[31].Invalidate(); 
                    break;
                case 16: 
                case 18:
                case 40:
                case 41: 
                case 42:
                case 43:
                case 46: break;
                default:
                    if (rt != 0) regs[rt].Invalidate();
                    break;
            }
        }

        return result;
    }

    static void Addu(RegState[] regs, int rs, int rt, int rd)
    {
        bool rsLui = regs[rs].ValidLui;
        bool rtLui = regs[rt].ValidLui;
        if (rsLui != rtLui)
        {
            int luiSrc = rsLui ? rs : rt;
            regs[rd] = regs[luiSrc];
            regs[rd].ValidAddend = true;
        }
        else if (rs == 0) 
            regs[rd] = regs[rt];
        else if (rt == 0)
            regs[rd] = regs[rs];
        else              
            regs[rd].Invalidate();
    }

    const int MaxEntries = 4096;

    // A switch table does not have to stay inside the function: a case that is just a
    // tail jump lands on the next function, and stopping at the first such entry threw
    // away every case after it. Those became the runtime's indirect fallback, which
    // fails on any input that selects one. Keep reading while the words are plausible
    // code addresses for this module and let the emitter decide how to reach each one.
    static uint[] ReadEntries(FunctionInfo elf, uint tableVram, MipsFunction func)
    {
        var  entries = new List<uint>();
        uint vram = tableVram;
        uint textLo = elf.TextBase;
        uint textHi = elf.TextBase + (uint)elf.TextData.Length;
        bool sawOwn = false;

        while (entries.Count < MaxEntries && TryReadWord(elf, vram, out uint word))
        {
            bool own = word >= func.Start && word < func.End;
            bool code = (word & 3) == 0 && word >= textLo && word < textHi;
            if (!own && !code) break;
            // A table that never targets its own function is not a switch we recognised.
            sawOwn |= own;
            entries.Add(word);
            vram += 4;
        }
        return sawOwn ? entries.ToArray() : [];
    }

    static bool TryReadWord(FunctionInfo elf, uint vram, out uint value)
    {
        foreach (var sec in elf.DataSections)
        {
            if (sec.IsZero) continue;
            uint secEnd = sec.Va + (uint)sec.Data.Length;
            if (vram >= sec.Va && vram + 4 <= secEnd)
            {
                value = BinaryPrimitives.ReadUInt32LittleEndian(sec.Data.AsSpan((int)(vram - sec.Va)));
                return true;
            }
        }
        //shouldnt this be in rodata?
        if (vram >= elf.TextBase && vram + 4 <= elf.TextBase + (uint)elf.TextData.Length)
        {
            value = BinaryPrimitives.ReadUInt32LittleEndian(elf.TextData.AsSpan((int)(vram - elf.TextBase)));
            return true;
        }
        value = 0;
        return false;
    }
}
