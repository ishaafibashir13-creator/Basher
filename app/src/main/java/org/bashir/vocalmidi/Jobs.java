package org.bashir.vocalmidi;

import android.content.Context;
import android.os.Handler;
import android.os.Looper;
import com.chaquo.python.Python;
import com.chaquo.python.PyObject;
import com.chaquo.python.android.AndroidPlatform;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class Jobs {
    public static final ExecutorService worker = Executors.newSingleThreadExecutor();
    public static final Handler main = new Handler(Looper.getMainLooper());
    public static volatile boolean busy = false;
    public static volatile String status = "Выберите вокал и MIDI. Всё обрабатывается на устройстве.";
    public static Runnable listener;
    public static synchronized PyObject engine(Context context) {
        if (!Python.isStarted()) Python.start(new AndroidPlatform(context.getApplicationContext()));
        return Python.getInstance().getModule("engine");
    }
    public static void update(String value) {
        status = value;
        main.post(() -> { if (listener != null) listener.run(); });
    }
    public static String error(Throwable e) {
        String message = e.getMessage();
        return message == null ? e.getClass().getSimpleName() : message;
    }
}
