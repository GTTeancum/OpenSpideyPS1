using Recompiled;
using RecompOne.Runtime.Assets;
using RecompOne.Runtime.Context;
using RecompOne.Runtime.Memory;

void Check(bool value,string name)
{
    if (!value) throw new Exception(name);
    Console.WriteLine("PASS: "+name);
}
var memory=new PSMemory(0x800000);
var context=new CpuContext { A0=0x17000,RA=0x80061280 };
// Initialize an empty arena without touching any installed game data.
string root=Path.Combine(Path.GetTempPath(),"sm1-packets-"+Guid.NewGuid());
Directory.CreateDirectory(Path.Combine(root,"wad"));
try
{
    Environment.SetEnvironmentVariable("SPIDEY_ASSET_DIR",null);
    Environment.SetEnvironmentVariable("SPIDEY_PACKET_TRACE","1");
    LooseWadOverrides.Initialize(root);
    Check(FramePackets.TryAllocate(context),"first retail packet callsite redirects");
    uint a=context.V0;
    context.RA=0x80061298;
    Check(FramePackets.TryAllocate(context),"second retail packet callsite redirects");
    uint b=context.V0;
    Check(b-a==FramePackets.Capacity,"two disjoint fixed-size allocations");
    context.RA=0;Check(!FramePackets.TryAllocate(context),"unrelated allocation stays native");
    context.A0=0x4000;context.RA=0x8006124C;
    Check(!FramePackets.TryAllocate(context),"ordering table stays native");
    context.GP=0x800B47F4;
    memory.WriteU32(0x800B54A8,0x80090000);
    foreach(uint pool in new[]{a,b})
    {
        memory.WriteU32(0x80090074,pool);
        FramePackets.SetLimit(context,memory);
        uint start=pool&0x7fffffff;
        Check(memory.ReadU32(0x800B4FE8)==start+FramePackets.Capacity-256,"selected buffer preserves safety slack");
        memory.WriteU32(0x800B54B0,start+120000);
        FramePackets.Audit(memory);
    }
    foreach(uint cursor in new[]{(b&0x7fffffff)-8,(b&0x7fffffff)+FramePackets.Capacity-100})
    {
        memory.WriteU32(0x800B54B0,cursor);
        bool rejected=false;
        try { FramePackets.Audit(memory); }
        catch(InvalidOperationException) { rejected=true; }
        Check(rejected,"invalid or exhausted packet cursor rejected");
    }
    Check(LooseWadOverrides.TryFree(a)&&LooseWadOverrides.TryFree(b),"both pools release through tracked allocator");
    uint merged=LooseWadOverrides.AllocateScratch(FramePackets.Capacity*2,"coalescing check");
    Check(merged==a,"released adjacent pools coalesce");
    Check(LooseWadOverrides.TryFree(merged),"coalesced allocation releases");
}
finally { Directory.Delete(root,true); }
