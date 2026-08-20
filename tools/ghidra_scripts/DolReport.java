// Ghidra postScript (Java): exports the function list and the references to key strings.
// Usage: analyzeHeadless <proj> TLS -process main.dol -noanalysis \
//        -scriptPath tools/ghidra_scripts -postScript DolReport.java <outdir>
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.address.Address;
import java.io.PrintWriter;
import java.util.*;

public class DolReport extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        String outdir = (args.length > 0) ? args[0] : "ghidra_out";
        FunctionManager fm = currentProgram.getFunctionManager();

        int nf = 0;
        PrintWriter pf = new PrintWriter(outdir + "/functions.txt", "UTF-8");
        for (Function fn : fm.getFunctions(true)) {
            pf.printf("%08x  %8d  %s%n", fn.getEntryPoint().getOffset(),
                    fn.getBody().getNumAddresses(), fn.getName());
            nf++;
        }
        pf.close();
        println("functions: " + nf);

        String[] keys = {"DebugMenu", "BootSequence", "DebugMenuType", "Neko",
                "ai_table.csv", "boot/", ".pkh", "chnkdata", "wii text",
                "SequenceDebugMenu", "Tools_", "config.ini", "revision.txt"};

        PrintWriter ps = new PrintWriter(outdir + "/string_refs.txt", "UTF-8");
        DataIterator di = currentProgram.getListing().getDefinedData(true);
        // pre-collect the defined strings
        List<Object[]> strs = new ArrayList<>();
        while (di.hasNext()) {
            Data dt = di.next();
            Object v = dt.getValue();
            if (v == null) continue;
            if (!(v instanceof String)) continue;
            strs.add(new Object[]{dt.getAddress(), (String) v});
        }
        println("defined strings: " + strs.size());

        for (String kw : keys) {
            ps.println("=== \"" + kw + "\" ===");
            for (Object[] s : strs) {
                String sv = (String) s[1];
                if (!sv.contains(kw)) continue;
                Address at = (Address) s[0];
                Reference[] refs = getReferencesTo(at);
                String disp = sv.length() > 50 ? sv.substring(0, 50) : sv;
                if (refs.length == 0) {
                    ps.printf("  %08x  (no xref)  %s%n", at.getOffset(), disp);
                }
                for (Reference r : refs) {
                    Function fn = fm.getFunctionContaining(r.getFromAddress());
                    ps.printf("  %08x  %-28s  %s%n", r.getFromAddress().getOffset(),
                            fn != null ? fn.getName() : "?", disp);
                }
            }
            ps.println();
        }
        ps.close();
        println("wrote functions.txt and string_refs.txt to " + outdir);
    }
}
