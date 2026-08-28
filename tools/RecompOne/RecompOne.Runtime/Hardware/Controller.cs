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
}
