using RecompOne.Runtime.Bios;
using RecompOne.Runtime.Context;
using RecompOne.Runtime.Dispatch;
using RecompOne.Runtime.Memory;

namespace RecompOne.Runtime;

public static class Interrupts
{
    static bool _inHandler;
    static readonly bool[] _pending = new bool[16];

    public static void Deliver(int irq, CpuContext cpu, IMemory mem)
    {
        if ((uint)irq >= _pending.Length) return;

        if (_inHandler) { _pending[irq] = true; return; }

        _inHandler = true;
        try
        {
            Dispatch(irq, cpu, mem);

            bool again = true;
            while (again)
            {
                again = false;
                for (int i = 0; i < _pending.Length; i++)
                {
                    if (!_pending[i]) continue;
                    _pending[i] = false;
                    Dispatch(i, cpu, mem);
                    again = true;
                }
            }
        }
        finally
        {
            _inHandler = false;
        }
    }

    static void Dispatch(int irq, CpuContext cpu, IMemory mem)
    {
        uint intrEnv = BiosB.IntrEnvInInterruptAddr;
        if (intrEnv == 0) return;

        uint handler = mem.ReadU32(intrEnv + 2u + (uint)irq * 4u);
        if (handler == 0) return;

        //takes a snap, apparently interrupt callbacks dont operate at the same context? could be wrong in mips3000, need to check furter TODO, seens to be accurate
        var snap = cpu.Snapshot();
        mem.WriteU16(intrEnv, 1);
        Dispatcher.Call(cpu, mem, handler);
        mem.WriteU16(intrEnv, 0);
        cpu.Restore(snap);
    }
}
