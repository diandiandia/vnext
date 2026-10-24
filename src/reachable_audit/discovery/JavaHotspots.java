import com.sun.source.tree.*;
import com.sun.source.util.*;
import java.io.*;
import java.net.URI;
import java.nio.ByteBuffer;
import java.nio.charset.*;
import java.util.*;
import javax.tools.*;

/** Trusted parse-only helper. No analyze(), generate(), class loading, or target IO. */
public final class JavaHotspots {
    private static final Set<String> METHODS = Set.of(
        "exec", "start", "readObject", "readUnshared",
        "readAllBytes", "transferTo", "getNextEntry"
    );

    private static String encode(String value) {
        return Base64.getEncoder().encodeToString(value.getBytes(StandardCharsets.UTF_8));
    }

    private static final class Source extends SimpleJavaFileObject {
        private final String text;
        Source(String text) {
            super(URI.create("string:///Input.java"), JavaFileObject.Kind.SOURCE);
            this.text = text;
        }
        @Override public CharSequence getCharContent(boolean ignored) { return text; }
    }

    public static void main(String[] args) throws Exception {
        JavaCompiler compiler = ToolProvider.getSystemJavaCompiler();
        if (compiler == null) throw new IllegalStateException("JDK compiler unavailable");
        BufferedReader input = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.US_ASCII));
        int remaining = Integer.parseInt(input.readLine());
        String request;
        while ((request = input.readLine()) != null) {
            String[] fields = request.split("\t", -1);
            String path = fields[0];
            List<String> candidates = new ArrayList<>();
            int[] count = {0};
            boolean[] syntaxError = {false};
            String error = "";
            try (StandardJavaFileManager manager = compiler.getStandardFileManager(null, Locale.ROOT, StandardCharsets.UTF_8)) {
                String source = StandardCharsets.UTF_8.newDecoder()
                    .onMalformedInput(CodingErrorAction.REPORT)
                    .onUnmappableCharacter(CodingErrorAction.REPORT)
                    .decode(ByteBuffer.wrap(Base64.getDecoder().decode(fields[1]))).toString();
                manager.setLocation(StandardLocation.CLASS_PATH, List.of());
                manager.setLocation(StandardLocation.SOURCE_PATH, List.of());
                manager.setLocation(StandardLocation.ANNOTATION_PROCESSOR_PATH, List.of());
                DiagnosticListener<JavaFileObject> diagnostics = diagnostic -> {
                    if (diagnostic.getKind() == Diagnostic.Kind.ERROR) syntaxError[0] = true;
                };
                JavacTask task = (JavacTask) compiler.getTask(
                    new StringWriter(), manager, diagnostics, List.of("-proc:none"),
                    null, List.of(new Source(source))
                );
                Iterable<? extends CompilationUnitTree> units = task.parse();
                if (syntaxError[0]) {
                    error = "Java syntax error (parse-only; JDK source level)";
                } else {
                    SourcePositions positions = Trees.instance(task).getSourcePositions();
                    final int budget = remaining;
                    for (CompilationUnitTree unit : units) {
                        new TreeScanner<Void, Void>() {
                            @Override public Void visitMethodInvocation(MethodInvocationTree node, Void ignored) {
                                ExpressionTree select = node.getMethodSelect();
                                String method = select instanceof MemberSelectTree
                                    ? ((MemberSelectTree) select).getIdentifier().toString()
                                    : select instanceof IdentifierTree
                                        ? ((IdentifierTree) select).getName().toString() : "";
                                if (METHODS.contains(method)) {
                                    count[0]++;
                                    if (candidates.size() < budget) {
                                        long position = positions.getStartPosition(unit, node);
                                        candidates.add("C\t" + path + "\t"
                                            + unit.getLineMap().getLineNumber(position) + "\t"
                                            + unit.getLineMap().getColumnNumber(position)
                                            + "\tunresolved-receiver." + method);
                                    }
                                }
                                return super.visitMethodInvocation(node, ignored);
                            }
                        }.scan(unit, null);
                    }
                }
            } catch (CharacterCodingException exception) {
                error = "Java source is not valid UTF-8";
            }
            System.out.println("F\t" + path + "\t" + count[0] + "\t" + encode(error));
            for (String candidate : candidates) System.out.println(candidate);
            remaining -= candidates.size();
        }
    }
}
