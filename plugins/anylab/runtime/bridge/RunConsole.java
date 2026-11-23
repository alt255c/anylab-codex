import java.io.FileOutputStream;
import java.io.PrintStream;
import java.lang.instrument.Instrumentation;

/** Capture model JVM output before experiment initialization, including errors. */
public final class RunConsole {
    public static void premain(String path, Instrumentation instrumentation) throws Exception {
        final PrintStream log = new PrintStream(new FileOutputStream(path, true), true, "UTF-8");
        System.setOut(log);
        System.setErr(log);
        Thread.setDefaultUncaughtExceptionHandler((thread, error) -> {
            log.println("Uncaught exception on " + thread.getName());
            error.printStackTrace(log);
        });
    }
}
