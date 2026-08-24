# RecompOne

<p align="center">
  <img src="https://github.com/user-attachments/assets/6d9a8f86-322c-4cd2-a3d3-ba68ba2d37e9" alt="logo" width="400">
</p>

RecompOne is a tool to statically recompile PlayStation 1 executables into C# code. it also provides a runtime layer that translates the PS1 hardware environment into something modern PCs can run natively.

This project is inspired by [N64Recomp](https://github.com/N64Recomp/N64Recomp) and [XenonRecomp](https://github.com/hedge-dev/XenonRecomp), which are similar tools for N64 and Xbox 360 respectively

[![Discord](https://discord.com/api/guilds/1525942688728481983/widget.png?style=banner2)](https://discord.gg/65g8ZEPnbR)


## How it works

Static recompilation is similar to emulation in that it recreates the internal state of the hardware, the difference is that instead of fetching, decoding, and executing each instruction at runtime, the recompiler translates all MIPS operations into code ahead of time.

the generated code operates on a `CpuContext` and a memory interface. this `CpuContext` encapsulates the state the CPU would be in and the runtime simulates what the PS1 hardware would be doing and translates it into something modern hardware can understand

For example, an add instruction:
```asm
addiu t0, t0, 0x10
```
becomes:
```csharp
c.T0 = c.T0 + 0x10u;
```

and a memory read:
```asm
lw t0, 0x10(sp)
```
becomes:
```csharp
c.T0 = mem.Read32(c.SP + 0x10u);
```

The runtime simulates what the game expects such as BIOS functions, MMIO, GPU commands, CD-ROM, and so on, simillar to an emulator but unlike one no BIOS or other proprietary files are required. only the game files are needed to run it. RecompOne does not dependend on Sony components.

## Building

RecompOne is a .NET project, You'll need the [.NET SDK 10](https://dotnet.microsoft.com/download) installed, then you can compile and run the recompiler, the runtime is not supposed to be ran, its a library that you have to include in your recompiled game.

## How do i create a port?

Creating a port for a game is an involved process, but you can find instructions on how to get started on [our wiki](https://github.com/BlackLabelHQ/RecompOne/wiki/How-to-recompile-a-game%3F)

## Contributing

Contributions are welcome. Bug reports, feature suggestions, and code are all appreciated.

Currently i'm the only maintainer, so my available time is limited. if you submit a PR please ensure it's solid code you can stand behind, any form of AI-generated PRs will not be accepted.

## Stance on AI

This project is proudly made by humans. AI was not involved in writing the code, and it never will be. AI PRs will be rejected, no exceptions.

This project does not support vibe-coded ports. AI can be a useful research tool, but it does not replace the human judgment needed to understand and correctly implement what you are building. **Code you don't understand is not code you wrote**.

You do you, but we will not provide help or promote ports produced that way.
