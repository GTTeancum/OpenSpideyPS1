using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using RecompOne.Recompiler.Analysis;
using RecompOne.Recompiler.CodeGen;
using RecompOne.Recompiler.Disasm;
using RecompOne.Runtime.Context;
using RecompOne.Runtime.Memory;
using System.Reflection;

// A local BAL reaches a helper that shares its caller's recovered symbol range.
// The hook must execute once and resume the caller's saved-stack epilogue.
uint[] words = [0x27BDFFF8, 0xAFBF0004, 0x24100007, 0x0411000C, 0,
    0x26100001, 0x8FBF0004, 0x27BD0008, 0x03E00008, 0,
    0, 0, 0, 0, 0, 0, 0x26100002, 0x03E00008, 0];
var instructions = words.Select((w, i) => new MipsInstruction(w, 0x1000u + (uint)i * 4)).ToArray();
int failures = 0;
foreach (bool hooked in new[] { false, true })
{
    var fn = new MipsFunction { Start = 0x1000, End = 0x104C, Instructions = instructions, EmittedName = "Run" };
    var ctx = new FunctionContext { FuncStart = fn.Start, FuncEnd = fn.End,
        Labels = [0x1040, 0x1014], LocalReturns = [0x1014], LocalReturnJrs = [0x1044] };
    if (hooked) ctx.InteriorHooks[0x1040] = "Fixture.Hook";
    string source = "using RecompOne.Runtime.Context; using RecompOne.Runtime.Memory; public static class Fixture { " +
        "public static int Calls; public static void Hook(CpuContext c, IMemory m) { Calls++; c.S0 += 2; }" +
        FunctionEmitter.Emit(fn, ctx) + "}";
    var paths = ((string)AppContext.GetData("TRUSTED_PLATFORM_ASSEMBLIES")!).Split(Path.PathSeparator)
        .Append(typeof(CpuContext).Assembly.Location).Distinct();
    var compilation = CSharpCompilation.Create("InteriorHook" + hooked,
        [CSharpSyntaxTree.ParseText(source)], paths.Select(p => MetadataReference.CreateFromFile(p)),
        new CSharpCompilationOptions(OutputKind.DynamicallyLinkedLibrary));
    using var output = new MemoryStream();
    var result = compilation.Emit(output);
    if (!result.Success) throw new Exception(string.Join("\n", result.Diagnostics));
    var type = Assembly.Load(output.ToArray()).GetType("Fixture")!;
    var memory = new PSMemory(0x800000);
    var cpu = new CpuContext { SP = 0x80011000, RA = 0x80012000 };
    type.GetMethod("Run")!.Invoke(null, [cpu, memory]);
    int calls = (int)type.GetField("Calls")!.GetValue(null)!;
    bool pass = calls == (hooked ? 1 : 0) && cpu.S0 == 10 && cpu.SP == 0x80011000 && cpu.RA == 0x80012000;
    Console.WriteLine($"Interior hook={hooked}: calls={calls}, result={cpu.S0}, SP={cpu.SP:X8}, RA={cpu.RA:X8} {(pass ? "PASS" : "FAIL")}");
    if (!pass) failures++;
}
foreach (var instruction in instructions) instruction.Dispose();
return failures == 0 ? 0 : 1;
