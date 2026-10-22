package org.bashir.vocalmidi;

import android.app.*;
import android.content.*;
import android.content.pm.ServiceInfo;
import android.os.*;
import java.io.*;

public class RenderService extends Service {
    private PowerManager.WakeLock wake;
    private boolean active;
    public IBinder onBind(Intent intent) { return null; }
    private Notification notification(String text) {
        PendingIntent open = PendingIntent.getActivity(this, 0, new Intent(this, MainActivity.class), PendingIntent.FLAG_IMMUTABLE);
        Notification.Builder builder = Build.VERSION.SDK_INT >= 26
            ? new Notification.Builder(this, "render") : new Notification.Builder(this);
        return builder.setSmallIcon(android.R.drawable.ic_media_play)
            .setContentTitle("Вокал и MIDI").setContentText(text).setContentIntent(open).setOngoing(true).build();
    }
    public void progress(int percent) {
        // Speak no more than one change per ten percent.
        int ten = percent / 10 * 10;
        String text = "Обработка вокала: " + ten + " процентов";
        if (!Jobs.status.equals(text)) Jobs.update(text);
    }
    @Override public int onStartCommand(Intent intent, int flags, int id) {
        if (active || intent == null) return START_NOT_STICKY;
        active = true;
        NotificationManager nm = getSystemService(NotificationManager.class);
        if (Build.VERSION.SDK_INT >= 26) nm.createNotificationChannel(new NotificationChannel("render", "Обработка вокала", NotificationManager.IMPORTANCE_LOW));
        Notification n;
        if (Build.VERSION.SDK_INT >= 26) n = notification("Подготовка обработки");
        else n = new Notification.Builder(this).setSmallIcon(android.R.drawable.ic_media_play).setContentTitle("Обработка вокала").build();
        if (Build.VERSION.SDK_INT >= 35) startForeground(1, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROCESSING);
        else if (Build.VERSION.SDK_INT >= 29) startForeground(1, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC);
        else startForeground(1, n);
        wake = ((PowerManager)getSystemService(POWER_SERVICE)).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "vocalmidi:render");
        wake.acquire(60 * 60 * 1000L);
        Jobs.busy = true;
        Jobs.update("Подготовка обработки. Можно свернуть приложение.");
        File cancel = new File(getFilesDir(), "cancel");
        Jobs.worker.execute(() -> {
            File temp = new File(getFilesDir(), "result.tmp.wav");
            try {
                String details = "";
                if (intent.getBooleanExtra("rhythm", false)) {
                    Jobs.engine(this); // Initialize the shared Python runtime.
                    com.chaquo.python.PyObject result = com.chaquo.python.Python.getInstance().getModule("rhythm").callAttr("render",
                        new File(getFilesDir(), "vocal.wav").getPath(),
                        new File(getFilesDir(), "melody.mid").getPath(), intent.getIntExtra("track", 0),
                        intent.getDoubleExtra("offset", 0), intent.getBooleanExtra("mute", false),
                        temp.getPath(), cancel.getPath(), this, intent.getDoubleExtra("sensitivity", .12), intent.getStringExtra("policy"));
                    org.json.JSONObject info = new org.json.JSONObject(result.toString());
                    details = " Rubber Band R3. Нот MIDI: " + info.getInt("notes")
                        + ", вокальных событий: " + info.getInt("source_events") + ".";
                } else Jobs.engine(this).callAttr("render", new File(getFilesDir(), "vocal.wav").getPath(),
                    new File(getFilesDir(), "melody.mid").getPath(), intent.getIntExtra("track", 0),
                    intent.getStringExtra("policy"), intent.getDoubleExtra("offset", 0),
                    intent.getIntExtra("transpose", 0), intent.getBooleanExtra("mute", false),
                    temp.getPath(), cancel.getPath(), this);
                if (cancel.exists()) throw new IOException("Обработка отменена");
                File dest = new File(getFilesDir(), "result.wav");
                if (!temp.renameTo(dest)) throw new IOException("Не удалось сохранить результат");
                Jobs.busy = false;
                Jobs.update("Готово. Результат можно прослушать и сохранить в WAV." + details);
            } catch (Throwable e) {
                temp.delete();
                Jobs.busy = false;
                Jobs.update(cancel.exists() ? "Обработка отменена. Предыдущий результат сохранён." : "Ошибка обработки: " + Jobs.error(e));
            } finally {
                RenderState.processing = false;
                cancel.delete();
                Jobs.main.post(() -> { if (wake != null && wake.isHeld()) wake.release(); stopForeground(true); active=false; stopSelf(id); });
            }
        });
        return START_NOT_STICKY;
    }
    @Override public void onTimeout(int startId, int fgsType) {
        try { new File(getFilesDir(), "cancel").createNewFile(); } catch (IOException ignored) {}
        stopForeground(true); stopSelf();
        Jobs.update("Android остановил длительную обработку. Попробуйте более короткую запись.");
    }
    @Override public void onDestroy() {
        if (wake != null && wake.isHeld()) wake.release();
        super.onDestroy();
    }
}
