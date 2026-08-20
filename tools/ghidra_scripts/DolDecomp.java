// Ghidra postScript (Java): decompiles a list of functions (by address) into a file.
// Usage: -postScript DolDecomp.java <outfile> <addr1> <addr2> ...
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.listing.Function;
import ghidra.program.model.address.Address;
import java.io.PrintWriter;

public class DolDecomp extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        String outfile = args[0];
        DecompInterface di = new DecompInterface();
        di.openProgram(currentProgram);
        PrintWriter pw = new PrintWriter(outfile, "UTF-8");
        for (int i = 1; i < args.length; i++) {
            Address a = currentProgram.getAddressFactory().getAddress(args[i]);
            Function fn = getFunctionContaining(a);
            if (fn == null) {
                pw.println("// no function @ " + args[i]);
                continue;
            }
            pw.println("// ===== " + fn.getName() + " @ " +
                    fn.getEntryPoint() + " =====");
            DecompileResults res = di.decompileFunction(fn, 60, monitor);
            if (res.decompileCompleted()) {
                pw.println(res.getDecompiledFunction().getC());
            } else {
                pw.println("// decompilation failed: " + res.getErrorMessage());
            }
            pw.println();
        }
        pw.close();
        println("wrote " + outfile);
    }
}
