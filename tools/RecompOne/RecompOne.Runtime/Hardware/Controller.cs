namespace RecompOne.Runtime.Hardware;

public static class Controller
{
    public const ushort Select = 1 << 0;
    public const ushort L3 = 1 << 1;
    public const ushort R3 = 1 << 2;
    public const ushort Start = 1 << 3;
    public const ushort Up = 1 << 4;
    public const ushort Right = 1 << 5;
    public const ushort Down = 1 << 6;
    public const ushort Left = 1 << 7;
    public const ushort L2 = 1 << 8;
    public const ushort R2 = 1 << 9;
    public const ushort L1 = 1 << 10;
    public const ushort R1 = 1 << 11;
    public const ushort Triangle = 1 << 12;
    public const ushort Circle = 1 << 13;
    public const ushort Cross = 1 << 14;
    public const ushort Square = 1 << 15;

    public static ushort State = 0xFFFF;

    /// <summary>
    /// Buttons held by an automated script, as an active-high mask, merged into the
    /// host state every poll.
    ///
    /// A test harness cannot just write the pad buffers itself: the runtime refreshes
    /// them from this state on its own schedule, so an injected press survives only
    /// until the next refresh. Feeding the script in here instead means every consumer
    /// -- libpad, the BIOS pad path, anything else -- sees it, and sees it for exactly
    /// as long as the script says.
    /// </summary>
    public static ushort ScriptHeld;
    /// <summary>Private process-local test mode; ignore physical pads, not host UI.</summary>
    public static bool ScriptExclusive;
    public static byte   RightX = 0x80;
    public static byte   RightY = 0x80;
    public static byte   LeftX = 0x80;
    public static byte   LeftY = 0x80;

    public static ushort State2 = 0xFFFF;
    public static bool   Connected2;
    public static byte   RightX2 = 0x80;
    public static byte   RightY2 = 0x80;
    public static byte   LeftX2 = 0x80;
    public static byte   LeftY2 = 0x80;

    /// <summary>
    /// Replay override. When Active, these replace the host device state outright at
    /// the end of every poll -- unlike <see cref="ScriptHeld"/>, which can only force a
    /// button down. A replay has to be able to say "nothing is pressed" and to steer
    /// the sticks, so it needs the whole state, not a merge.
    /// </summary>
    public static bool  ReplayActive;
    public static ushort ReplayState = 0xFFFF;
    public static byte  ReplayLeftX = 0x80, ReplayLeftY = 0x80;
    public static byte  ReplayRightX = 0x80, ReplayRightY = 0x80;

    /// <summary>Apply replay/test state after polling devices. Normal play is unchanged.</summary>
    public static void ApplyInputOverrides()
    {
        if (ReplayActive)
        {
            State = ReplayState;
            LeftX = ReplayLeftX;
            LeftY = ReplayLeftY;
            RightX = ReplayRightX;
            RightY = ReplayRightY;
        }
        else if (ScriptExclusive)
        {
            State = 0xFFFF;
            LeftX = LeftY = RightX = RightY = 0x80;
        }
        State &= (ushort)~ScriptHeld;
        if (ScriptExclusive)
        {
            State2 = 0xFFFF;
            LeftX2 = LeftY2 = RightX2 = RightY2 = 0x80;
            Connected2 = false;
        }
    }
}
