import java.io.FileOutputStream;
import java.io.PrintStream;
import java.lang.instrument.Instrumentation;
import java.nio.charset.StandardCharsets;
import java.util.Base64;

/** Capture model JVM output before experiment initialization, including errors. */
public final class RunConsole {
    public static void premain(String path, Instrumentation instrumentation) throws Exception {
        if (path.startsWith("utf8:")) {
            path = new String(Base64.getUrlDecoder().decode(path.substring(5)), StandardCharsets.UTF_8);
        }
        final PrintStream log = new PrintStream(new FileOutputStream(path, true), true, "UTF-8");
        System.setOut(log);
        System.setErr(log);
        Thread.setDefaultUncaughtExceptionHandler((thread, error) -> {
            log.println("Uncaught exception on " + thread.getName());
            error.printStackTrace(log);
        });
    }
}
