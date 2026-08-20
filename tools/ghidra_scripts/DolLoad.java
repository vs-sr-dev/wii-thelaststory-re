// Ghidra preScript (Java): loads a GameCube/Wii DOL, mapping the sections to
// their correct addresses, then lets auto-analysis run.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSpace;
import ghidra.program.model.mem.Memory;
import ghidra.program.model.mem.MemoryBlock;
import java.io.FileInputStream;
import java.nio.file.Files;
import java.nio.file.Paths;

public class DolLoad extends GhidraScript {

    private static long u32(byte[] d, int o) {
        return ((d[o] & 0xffL) << 24) | ((d[o + 1] & 0xffL) << 16)
             | ((d[o + 2] & 0xffL) << 8) | (d[o + 3] & 0xffL);
    }

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        String dolPath = (args.length > 0) ? args[0]
                : "extract/sys/main.dol";
        byte[] d = Files.readAllBytes(Paths.get(dolPath));

        Memory mem = currentProgram.getMemory();
        for (MemoryBlock b : mem.getBlocks()) {
            mem.removeBlock(b, monitor);
        }
        AddressSpace space = currentProgram.getAddressFactory().getDefaultAddressSpace();

        // 7 text sections + 11 data
        for (int i = 0; i < 18; i++) {
            boolean isText = i < 7;
            int base = isText ? 0x00 : 0x1C - 7 * 4;   // data is indexed from i=7
            int idx = i;
            long off, addr, size;
            if (isText) {
                off  = u32(d, 0x00 + i * 4);
                addr = u32(d, 0x48 + i * 4);
                size = u32(d, 0x90 + i * 4);
            } else {
                int j = i - 7;
                off  = u32(d, 0x1C + j * 4);
                addr = u32(d, 0x64 + j * 4);
                size = u32(d, 0xAC + j * 4);
            }
            if (size == 0) continue;
            String name = (isText ? "text" : "data") + (isText ? i : (i - 7));
            Address start = space.getAddress(addr & 0xFFFFFFFFL);
            FileInputStream fis = new FileInputStream(dolPath);
            fis.skip(off);
            MemoryBlock blk = mem.createInitializedBlock(name, start, fis, size, monitor, false);
            blk.setRead(true);
            blk.setWrite(!isText);
            blk.setExecute(isText);
            fis.close();
            println(String.format("block %-6s @ %08x size 0x%x", name, addr, size));
        }

        // BSS: in the DOL the declared range can overlap data sections that are
        // already mapped (data6/data7), so only create BSS in the free gaps.
        long bssAddr = u32(d, 0xD8);
        long bssSize = u32(d, 0xDC);
        if (bssSize != 0) {
            long cur = bssAddr & 0xFFFFFFFFL;
            long end = cur + bssSize;
            int part = 0;
            while (cur < end) {
                Address a = space.getAddress(cur);
                MemoryBlock hit = mem.getBlock(a);
                if (hit != null) {
                    cur = hit.getEnd().getOffset() + 1;   // skip the occupied block
                    continue;
                }
                // extend the gap up to the next block, or to end
                long gapEnd = end;
                for (MemoryBlock b : mem.getBlocks()) {
                    long bs = b.getStart().getOffset();
                    if (bs > cur && bs < gapEnd) gapEnd = bs;
                }
                mem.createUninitializedBlock("bss" + (part++), a, gapEnd - cur, false);
                println(String.format("block bss    @ %08x size 0x%x", cur, gapEnd - cur));
                cur = gapEnd;
            }
        }

        long entry = u32(d, 0xE0) & 0xFFFFFFFFL;
        Address ep = space.getAddress(entry);
        currentProgram.getSymbolTable().addExternalEntryPoint(ep);
        createLabel(ep, "_start", true);
        println(String.format("entry @ %08x", entry));
    }
}
