# Windows native runtime payload

Release x64 Microsoft Visual C++ runtime, version 14.44.35112, copied from Visual Studio 2022 Community's `VC/Redist/MSVC/14.44.35112/x64/Microsoft.VC143.CRT` redistributable directory. Copyright Microsoft Corporation. These unmodified components remain subject to the Microsoft Visual Studio redistribution license; they are not covered by this repository's source license.

Redistribution reference: https://learn.microsoft.com/en-us/visualstudio/releases/2022/redistribution

`Runtime.props` puts the three required libraries into each game's single-file bundle. `BundledNativeRuntime` loads the extracted copies by absolute path before GLFW, native file dialogs, or OpenAL initialize. No separate VC++ installer or loose DLLs are required in the download. Windows, UCRT and graphics-driver libraries are still system dependencies.

When updating, use Microsoft's release x64 redistributable directory, update all three files together, inspect native imports, publish both games, and verify each running process loaded these libraries from its own bundle extraction directory. Never copy debug runtimes or System32 files into the release.
