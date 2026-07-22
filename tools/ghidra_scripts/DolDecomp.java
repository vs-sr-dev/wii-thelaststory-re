// Ghidra postScript (Java): decompila una lista di funzioni (per indirizzo) in un file.
// Uso: -postScript DolDecomp.java <outfile> <addr1> <addr2> ...
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
                pw.println("// nessuna funzione @ " + args[i]);
                continue;
            }
            pw.println("// ===== " + fn.getName() + " @ " +
                    fn.getEntryPoint() + " =====");
            DecompileResults res = di.decompileFunction(fn, 60, monitor);
            if (res.decompileCompleted()) {
                pw.println(res.getDecompiledFunction().getC());
            } else {
                pw.println("// decompile fallito: " + res.getErrorMessage());
            }
            pw.println();
        }
        pw.close();
        println("scritto " + outfile);
    }
}
