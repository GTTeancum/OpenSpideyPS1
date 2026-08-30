using System;
using RecompOne.Runtime.Context;
using RecompOne.Runtime.Memory;
using RecompOne.Runtime.Sdk;

namespace Recompiled;

/// <summary>
/// Spider-Man initialises input through libpad's multitap entry point, PadInitMtap at
/// 0x8008AFBC, rather than PadInitDirect, which is the variant the runtime
/// reimplements. It passes two 34-byte buffers 0x22 apart -- only slot 0 of each port
/// -- so the direct-mode implementation gives exactly the layout it expects.
///
/// The obvious move, replacing PadInitMtap outright, does not work: besides handing
/// libpad the buffers, the real function installs a table of six state-machine
/// handlers at 0x800B1264..0x800B1278, and the game calls through that table directly
/// (0x8008AD48 loads slot 0x800B1278 and jumps to it). Replacing the initialiser left
/// those slots zero and the first pad poll called address 0.
///
/// So the original runs untouched and the runtime's direct-mode init is layered on
/// top of it: libpad keeps its own state and its vtable, and the runtime learns where
/// the buffers are.
/// </summary>
public static class PadPatches
{
    /// <summary>Port A / port B pad buffers, as handed to PadInitMtap.</summary>
    public static uint Buf1, Buf2;

    /// <summary>
    /// Present the pad as a DualShock so the sticks are read. SPIDEY_ANALOG=0 goes back
    /// to a digital pad.
    ///
    /// The game does ask for analog mode itself -- it calls PadSetMainMode(0, 1, 0) once
    /// it sees a stable pad -- but that call goes to its own statically linked libpad,
    /// not to the runtime, and the state machine behind it is not the one driving the
    /// buffers here. So the request never arrives and the pad stayed digital, which is
    /// why the sticks did nothing: the stick bytes were always written, and an
    /// identifier of 0x41 tells the game not to look at them.
    /// </summary>
    static bool Analog => Environment.GetEnvironmentVariable("SPIDEY_ANALOG") != "0";

    static uint _pendBuf1, _pendBuf2;

    /// <summary>pre-hook on PadInitMtap(u_char *pad1, u_char *pad2)</summary>
    public static void PadInitMtapEnter(CpuContext c, IMemory m)
    {
        _pendBuf1 = c.A0;
        _pendBuf2 = c.A1;
    }

    /// <summary>post-hook on PadInitMtap: register the same buffers with the runtime.</summary>
    public static void PadInitMtapExit(CpuContext c, IMemory m)
    {
        Buf1 = _pendBuf1;
        Buf2 = _pendBuf2;

        // PadInitDirect reads its arguments and returns a value; the game is mid-call
        // in PadInitMtap, so put the context back exactly as it was found.
        uint a0 = c.A0, a1 = c.A1, v0 = c.V0;
        c.A0 = Buf1;
        c.A1 = Buf2;
        LibPad.PadInitDirect(c, m);
        c.A0 = a0;
        c.A1 = a1;
        c.V0 = v0;

        // After PadInitDirect, which resets it.
        LibPad.Analog = Analog;
    }

    // int PadChkMtap(void) -- no multitap is emulated
    public static void PadChkMtap(CpuContext c, IMemory m) => c.V0 = 0;
}
