// Ghidra postScript: elenca i chiamanti (call sites) di una lista di funzioni.
// Uso: -postScript DolCallers.java <addr1> [<addr2> ...]
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;
import ghidra.program.model.address.Address;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.RefType;

public class DolCallers extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        for (String s : args) {
            Address a = currentProgram.getAddressFactory().getAddress(s);
            Function fn = getFunctionAt(a);
            String nm = fn != null ? fn.getName() : "?";
            println("== chiamanti di " + nm + " @ " + s + " ==");
            for (Reference r : getReferencesTo(a)) {
                if (r.getReferenceType().isCall() || r.getReferenceType().isFlow()
                        || r.getReferenceType() == RefType.DATA) {
                    Function c = getFunctionContaining(r.getFromAddress());
                    println("  " + r.getFromAddress() + "  " +
                            (c != null ? c.getName() + " @ " + c.getEntryPoint() : "?") +
                            "  [" + r.getReferenceType() + "]");
                }
            }
        }
    }
}
