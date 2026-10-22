package org.bashir.vocalmidi;

import android.app.*;
import android.content.*;
import android.database.Cursor;
import android.media.*;
import android.net.Uri;
import android.os.*;
import android.provider.OpenableColumns;
import android.text.InputType;
import android.view.*;
import android.widget.*;
import com.arthenica.ffmpegkit.*;
import org.json.*;
import java.io.*;
import java.util.*;

public class MainActivity extends Activity {
    private static final int AUDIO=1, MIDI=2, EXPORT=3;
    private LinearLayout root;
    private TextView status, vocalName, midiName, playback;
    private Spinner tracks, policy, mode, sensitivity;
    private EditText offset, transpose;
    private CheckBox mute, manual;
    private Button editManual;
    private Button playVocal, playMidi, render, playResult, export, cancel, pause;
    private final List<View> locked = new ArrayList<>();
    private final List<Integer> trackIds = new ArrayList<>();
    private MediaPlayer player;
    private AudioManager audio;
    private AudioManager.OnAudioFocusChangeListener focusListener;
    private SharedPreferences prefs;
    private String shownTracks="";
    private File file(String name) { return new File(getFilesDir(), name); }
    private int dp(int n) { return (int)(getResources().getDisplayMetrics().density*n+.5f); }

    @Override public void onCreate(Bundle b) {
        super.onCreate(b);
        prefs = getSharedPreferences("project", MODE_PRIVATE);
        audio = (AudioManager)getSystemService(AUDIO_SERVICE);
        focusListener = change -> { if (change < 0) stopPlayback(); };
        ScrollView scroll = new ScrollView(this);
        root = new LinearLayout(this); root.setOrientation(LinearLayout.VERTICAL); root.setPadding(dp(20),dp(12),dp(20),dp(24));
        scroll.addView(root); setContentView(scroll);
        scroll.setOnApplyWindowInsetsListener((v, insets) -> {
            v.setPadding(insets.getSystemWindowInsetLeft(), insets.getSystemWindowInsetTop(), insets.getSystemWindowInsetRight(), insets.getSystemWindowInsetBottom());
            return insets;
        });
        heading("Вокал и MIDI");
        text("Подгонка времени вокала под MIDI с Rubber Band R3 или высоты голоса с PyWORLD. Лучше всего работает с чистым одиночным вокалом без музыки. До 10 минут на запись.");
        heading("1. Исходные файлы");
        locked.add(button("Выбрать исходный вокал", () -> pick(AUDIO)));
        vocalName = text("");
        playVocal = button("Слушать исходный вокал", () -> play(file("vocal.wav"), "Исходный вокал"));
        locked.add(playVocal);
        locked.add(button("Выбрать MIDI-файл", () -> pick(MIDI)));
        midiName = text("");
        heading("2. Мелодия");
        tracks = spinner("Дорожка MIDI", new String[]{"Сначала выберите MIDI"});
        policy = spinner("Если звучит несколько нот", new String[]{"Самая высокая нота", "Самая низкая нота", "Последняя начавшаяся нота"});
        policy.setSelection(prefs.getInt("policy",0));
        transpose = field("Транспозиция, полутонов: от −24 до 24", "0", false);
        transpose.setText(prefs.getString("transpose","0"));
        playMidi = button("Слушать выбранную мелодию", this::preview); locked.add(playMidi);
        text("Прослушивание использует простой синтезированный тембр и выбранное правило аккордов. Ударный канал не предлагается. Педаль и pitch bend в MIDI не учитываются.");
        heading("3. Подгонка вокала");
        mode = spinner("Режим обработки", new String[]{"Ритм MIDI — Rubber Band R3", "Высота по MIDI — прежний ритм", "Нарезка и ритм, затем тюнинг MIDI"});
        mode.setSelection(prefs.getInt("mode",2));
        sensitivity = spinner("Поиск атак вокала (для выравнивания)", new String[]{"Обычное", "Меньше разрезов — тихий вокал", "Больше разрезов — явные паузы"});
        sensitivity.setSelection(prefs.getInt("sensitivity",0));
        text("Rubber Band R3 растягивает и сжимает длительность вокала под MIDI, сохраняя высоту. Фразы обрабатываются непрерывно, без обрезки окончаний между нотами. Один слог может приходиться на несколько нот. MIDI может содержать другую мелодию. Результат заканчивается по более короткому файлу; сдвиг MIDI учитывается. Транспозиция влияет на прослушивание MIDI и режим высоты.");
        offset = field("Сдвиг MIDI относительно вокала, секунд", "0", true);
        offset.setText(prefs.getString("offset","0"));
        text("Положительный сдвиг задерживает MIDI. Границы фраз сопоставляются автоматически по атакам, паузам и длительностям. Слишком сильное растяжение или сжатие может давать артефакты. Для точной настройки на конкретной записи прослушайте результат и при необходимости измените сдвиг или чувствительность.");
        mute = new CheckBox(this); mute.setText("Соблюдать паузы MIDI"); mute.setMinHeight(dp(56)); root.addView(mute); locked.add(mute);
        mute.setChecked(prefs.getBoolean("mute",true));
        manual=new CheckBox(this);manual.setText("Использовать ручную разметку в режиме ритма и ритма с тюнингом");manual.setMinHeight(dp(56));root.addView(manual);locked.add(manual);
        manual.setChecked(prefs.getBoolean("manualEnabled",false));
        manual.setOnCheckedChangeListener((view,checked)->prefs.edit().putBoolean("manualEnabled",checked).apply());
        editManual=button("Ручная нарезка и выравнивание — редактор для TalkBack",()->{
            if(Jobs.busy)return;
            try{double n=Double.parseDouble(offset.getText().toString().replace(',','.'));if(!Double.isFinite(n)||Math.abs(n)>600)throw new IllegalArgumentException();}
            catch(Exception e){Jobs.update("Проверьте сдвиг MIDI: от −600 до 600 секунд");return;}
            stopPlayback();saveSettings();startActivity(new Intent(this,ManualEditorActivity.class).putExtra("track",trackValue()));
        });locked.add(editManual);
        text("Ручной редактор: границы в секундах, позиции в долях MIDI, пошаговые кнопки и прослушивание без работы с волной. Для полного результата выберите режим «Нарезка и ритм, затем тюнинг MIDI»: сначала изменяется время, затем высота. Транспозиция применяется на этапе тюнинга.");
        render = button("Обработать вокал", this::render); locked.add(render);
        cancel = button("Отменить обработку", () -> {
            try { file("cancel").createNewFile(); Jobs.update("Отмена запрошена. Завершается текущий фрагмент."); }
            catch (IOException e) { Jobs.update("Не удалось отменить: "+Jobs.error(e)); }
        });
        status = text(Jobs.status); status.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
        heading("4. Результат и проигрыватель");
        playResult = button("Слушать последний готовый результат", () -> play(file("result.wav"),"Результат")); locked.add(playResult);
        export = button("Сохранить результат как WAV", this::export); locked.add(export);
        playback = text("Воспроизведение остановлено"); playback.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
        pause = button("Пауза или продолжение", this::pausePlayback);
        button("Назад на 10 секунд", () -> seek(-10000));
        button("Вперёд на 10 секунд", () -> seek(10000));
        button("Остановить воспроизведение", this::stopPlayback);
        button("Справка и ограничения", () -> new AlertDialog.Builder(this).setTitle("Как получить лучший результат")
            .setMessage("1. Выберите чистую запись одного голоса и MIDI.\n2. Выберите дорожку и послушайте мелодию.\n3. Совместите начало нот с голосом с помощью сдвига.\n4. Запустите обработку и сохраните WAV.\n\nPyWORLD меняет высоту звучащих участков голоса, сохраняя спектральную огибающую. Согласные и дыхание остаются непитчевыми. Большие интервалы могут звучать искусственно. В режиме ритма работает Rubber Band 4.0.0 R3/Finer: длительности фраз растягиваются или сжимаются, высота голоса сохраняется. Согласные и переходы обрабатываются непрерывно. Выравнивание опирается на атаки, паузы и длительности; MIDI может быть с другой мелодией. Разное число событий не требует обрезки каждого слога: одна фраза может охватывать несколько нот. Опция пауз заглушает только реальные паузы MIDI, без разрывов между соседними легато-нотами. Результат ограничен более коротким файлом. Сильные изменения темпа могут давать артефакты; автоматическое определение атак зависит от записи. Режим «Нарезка и ритм, затем тюнинг MIDI» выполняет оба этапа по порядку. В ручном редакторе задайте границы исходных фрагментов и их места в долях MIDI; одна доля — четвертная нота, темп и его изменения учитываются. Сохраните разметку, вернитесь и запустите обработку. Паузы между ручными фрагментами заполняются тишиной.\n\nFFmpeg определяет формат по содержимому, а не расширению. При ошибке есть дополнительная попытка чтения как MP3. Зашифрованные, повреждённые и неизвестные форматы могут не открыться.\n\nВокал смешивается в моно 32 кГц, результат — WAV PCM16. Максимум 10 минут и 512 МБ исходного файла. MIDI: тип 0/1 и RIFF RMID, до 8 МБ.\n\nВсе операции локальные, разрешение на интернет отсутствует. Последний результат остаётся до успешной следующей обработки. Элементы имеют текстовые подписи для TalkBack; проверка на вашем устройстве всё равно необходима.")
            .setPositiveButton("Закрыть",null).show());
        refresh();
    }
    private TextView text(String value) { TextView v = new TextView(this); v.setText(value); v.setTextSize(17); v.setTextColor(0xff202124); v.setPadding(0,dp(8),0,dp(8)); root.addView(v); return v; }
    private void heading(String value) { TextView v = text(value); v.setTextSize(23); v.setTypeface(null,android.graphics.Typeface.BOLD); if (Build.VERSION.SDK_INT>=28) v.setAccessibilityHeading(true); }
    private Button button(String label, Runnable action) { Button b=new Button(this); b.setText(label); b.setAllCaps(false); b.setTextSize(17); b.setMinHeight(dp(56)); root.addView(b,new LinearLayout.LayoutParams(-1,-2)); b.setOnClickListener(v->action.run()); return b; }
    private Spinner spinner(String label, String[] values) { TextView title=text(label); Spinner s=new Spinner(this); s.setId(View.generateViewId()); title.setLabelFor(s.getId()); s.setPrompt(label); s.setContentDescription(label); s.setMinimumHeight(dp(56)); root.addView(s,new LinearLayout.LayoutParams(-1,-2)); setItems(s,values); locked.add(s); return s; }
    private void setItems(Spinner s, String[] values) { ArrayAdapter<String> a = new ArrayAdapter<>(this,android.R.layout.simple_spinner_item,values); a.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item); s.setAdapter(a); }
    private EditText field(String label,String initial,boolean decimal) { TextView title=text(label); EditText e=new EditText(this); e.setId(View.generateViewId()); title.setLabelFor(e.getId()); e.setText(initial); e.setSingleLine(true); e.setTextSize(18); e.setMinHeight(dp(56)); e.setInputType(InputType.TYPE_CLASS_NUMBER|InputType.TYPE_NUMBER_FLAG_SIGNED|(decimal?InputType.TYPE_NUMBER_FLAG_DECIMAL:0)); root.addView(e); locked.add(e); return e; }
    @Override protected void onStart() { super.onStart(); Jobs.listener=this::refresh; refresh(); }
    @Override protected void onStop() { saveSettings(); Jobs.listener=null; stopPlayback(); super.onStop(); }
    private void saveSettings() { prefs.edit().putInt("trackIndex",tracks.getSelectedItemPosition()).putInt("policy",policy.getSelectedItemPosition()).putString("offset",offset.getText().toString()).putString("transpose",transpose.getText().toString()).putBoolean("mute",mute.isChecked()).putInt("mode",mode.getSelectedItemPosition()).putInt("sensitivity",sensitivity.getSelectedItemPosition()).apply(); }
    private void refresh() {
        if (status==null) return;
        status.setText(Jobs.status);
        manual.setChecked(prefs.getBoolean("manualEnabled",false));
        vocalName.setText("Вокал: "+prefs.getString("audioName","не выбран"));
        midiName.setText("MIDI: "+prefs.getString("midiName","не выбран"));
        String json=prefs.getString("tracks","");
        if (!json.equals(shownTracks)) {
            try { JSONArray arr=new JSONArray(json); String[] labels=new String[arr.length()]; trackIds.clear();
                for(int i=0;i<arr.length();i++) { JSONObject t=arr.getJSONObject(i); trackIds.add(t.getInt("id")); labels[i]="Дорожка "+(t.getInt("id")+1)+": "+t.getString("name")+", нот: "+t.getInt("count")+", секунд: "+Math.round(t.getDouble("duration")); }
                setItems(tracks,labels); tracks.setSelection(Math.max(0,Math.min(labels.length-1,prefs.getInt("trackIndex",0)))); shownTracks=json;
            } catch(JSONException ignored) {}
        }
        boolean free=!Jobs.busy;
        for(View v:locked) v.setEnabled(free);
        playVocal.setEnabled(free&&file("vocal.wav").exists());
        playMidi.setEnabled(free&&!trackIds.isEmpty());
        render.setEnabled(free&&file("vocal.wav").exists()&&!trackIds.isEmpty());
        editManual.setEnabled(free&&file("vocal.wav").exists()&&!trackIds.isEmpty());
        playResult.setEnabled(free&&file("result.wav").exists()); export.setEnabled(playResult.isEnabled());
        cancel.setEnabled(Jobs.busy&&RenderState.processing);
    }
    private void pick(int request) { stopPlayback(); Intent i=new Intent(Intent.ACTION_OPEN_DOCUMENT); i.addCategory(Intent.CATEGORY_OPENABLE); i.setType("*/*"); startActivityForResult(i,request); }
    private String displayName(Uri uri) { try(Cursor c=getContentResolver().query(uri,new String[]{OpenableColumns.DISPLAY_NAME},null,null,null)) { if(c!=null&&c.moveToFirst()) return c.getString(0); } catch(Exception ignored) {} return "Выбранный файл"; }
    private void copy(Uri uri, File target, long limit) throws IOException { try(InputStream in=getContentResolver().openInputStream(uri); OutputStream out=new FileOutputStream(target)) { if(in==null) throw new IOException("Файл недоступен"); byte[] buffer=new byte[65536]; long total=0; int n; while((n=in.read(buffer))!=-1) { total+=n; if(total>limit) throw new IOException("Файл превышает допустимый размер"); out.write(buffer,0,n); } } }
    @Override protected void onActivityResult(int req,int result,Intent data) {
        super.onActivityResult(req,result,data); if(result!=RESULT_OK||data==null||data.getData()==null) return;
        Uri uri=data.getData(); if(Jobs.busy) { Jobs.update("Дождитесь завершения текущей операции"); return; }
        Jobs.busy=true; Jobs.update(req==EXPORT?"Сохранение WAV…":"Чтение выбранного файла…");
        Jobs.worker.execute(()->{
            File temp=file("import.tmp"); File decoded=file("decoded.tmp.wav");
            try {
                if(req==EXPORT) { try(InputStream in=new FileInputStream(file("result.wav"));OutputStream out=getContentResolver().openOutputStream(uri,"wt")) { if(out==null) throw new IOException("Не удалось открыть место сохранения"); byte[] b=new byte[65536];int n;while((n=in.read(b))!=-1)out.write(b,0,n); } Jobs.update("WAV сохранён"); }
                else {
                    String name=displayName(uri); copy(uri,temp,req==MIDI?8L*1024*1024:512L*1024*1024);
                    if(req==MIDI) {
                        String json=Jobs.engine(this).callAttr("inspect_midi",temp.getPath()).toString();
                        if(!temp.renameTo(file("melody.mid"))) throw new IOException("Не удалось сохранить MIDI");
                        prefs.edit().remove("manualPlan").putBoolean("manualEnabled",false).putString("tracks",json).putString("midiName",name).putInt("trackIndex",0).apply();
                        Jobs.update("MIDI загружен. Выберите дорожку и послушайте её.");
                    } else {
                        Jobs.update("Декодирование аудио с помощью FFmpeg…");
                        String[] args={"-nostdin","-y","-v","error","-probesize","50000000","-analyzeduration","30000000","-i",temp.getPath(),"-map","0:a:0","-vn","-t","601","-ac","1","-ar","32000","-c:a","pcm_s16le",decoded.getPath()};
                        FFmpegSession s=FFmpegKit.executeWithArguments(args);
                        if(!ReturnCode.isSuccess(s.getReturnCode())) {
                            ArrayList<String> raw=new ArrayList<>(Arrays.asList(args)); int i=raw.indexOf("-i"); raw.add(i,"mp3");raw.add(i,"-f");
                            s=FFmpegKit.executeWithArguments(raw.toArray(new String[0]));
                        }
                        if(!ReturnCode.isSuccess(s.getReturnCode())||!decoded.exists()||decoded.length()<6444) throw new IOException("Аудио не распознано. Файл повреждён, защищён или формат не поддерживается.");
                        if(decoded.length()>32000L*2*600+4096) throw new IOException("Вокал длиннее 10 минут. Сначала укоротите запись.");
                        if(!decoded.renameTo(file("vocal.wav"))) throw new IOException("Не удалось сохранить вокал");
                        prefs.edit().remove("manualPlan").putBoolean("manualEnabled",false).putString("audioName",name).apply(); Jobs.update("Вокал загружен и готов к прослушиванию.");
                    }
                }
            } catch(Throwable e) { Jobs.update("Ошибка: "+Jobs.error(e)); }
            finally { temp.delete();decoded.delete();Jobs.busy=false;Jobs.update(Jobs.status); }
        });
    }
    private int transposeValue() { int n=Integer.parseInt(transpose.getText().toString().trim()); if(n< -24||n>24)throw new IllegalArgumentException();return n; }
    private String policyValue() { return new String[]{"high","low","last"}[policy.getSelectedItemPosition()]; }
    private int trackValue() { return trackIds.get(tracks.getSelectedItemPosition()); }
    private void preview() {
        if(Jobs.busy)return;
        final int tr,shift;final String p;
        try { tr=trackValue();shift=transposeValue();p=policyValue(); }catch(Exception e){Jobs.update("Введите транспозицию целым числом от −24 до 24");return;}
        stopPlayback();saveSettings();Jobs.busy=true;Jobs.update("Подготовка прослушивания мелодии…");
        Jobs.worker.execute(()->{try{Jobs.engine(this).callAttr("preview",file("melody.mid").getPath(),tr,p,shift,file("preview.wav").getPath());Jobs.main.post(()->{if(!isFinishing()&&!isDestroyed()&&Jobs.listener!=null)play(file("preview.wav"),"Мелодия MIDI");});Jobs.update("Мелодия готова к прослушиванию");}catch(Throwable e){Jobs.update("Ошибка: "+Jobs.error(e));}finally{Jobs.busy=false;Jobs.update(Jobs.status);}});
    }
    private void render() {
        if(Jobs.busy)return;
        final double seconds;final int shift;
        try {seconds=Double.parseDouble(offset.getText().toString().trim().replace(',','.'));shift=transposeValue();if(!Double.isFinite(seconds)||Math.abs(seconds)>600)throw new IllegalArgumentException();}
        catch(Exception e){Jobs.update("Проверьте числа: сдвиг от −600 до 600 секунд, транспозиция от −24 до 24");return;}
        if(manual.isChecked()&&mode.getSelectedItemPosition()!=1&&prefs.getString("manualPlan","").isEmpty()){Jobs.update("Сначала откройте ручной редактор и сохраните разметку");return;}
        stopPlayback();saveSettings();
        file("cancel").delete();
        Intent i=new Intent(this,RenderService.class).putExtra("track",trackValue()).putExtra("policy",policyValue()).putExtra("offset",seconds).putExtra("transpose",shift).putExtra("mute",mute.isChecked()).putExtra("mode",new String[]{"rhythm","pitch","both"}[mode.getSelectedItemPosition()]).putExtra("manual",manual.isChecked()).putExtra("sensitivity",new double[]{.12,.06,.24}[sensitivity.getSelectedItemPosition()]);
        Jobs.busy=true;RenderState.processing=true;Jobs.update("Запуск обработки…");
        try{if(Build.VERSION.SDK_INT>=26)startForegroundService(i);else startService(i);}catch(Exception e){Jobs.busy=false;RenderState.processing=false;Jobs.update("Не удалось запустить обработку: "+Jobs.error(e));}
    }
    private void export() {Intent i=new Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("audio/wav").putExtra(Intent.EXTRA_TITLE,"vocal-midi.wav");startActivityForResult(i,EXPORT);}
    private void play(File f,String title) {stopPlayback();try{if(audio.requestAudioFocus(focusListener,AudioManager.STREAM_MUSIC,AudioManager.AUDIOFOCUS_GAIN_TRANSIENT)!=AudioManager.AUDIOFOCUS_REQUEST_GRANTED){Jobs.update("Не удалось получить доступ к воспроизведению");return;}player=new MediaPlayer();player.setAudioAttributes(new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA).setContentType(AudioAttributes.CONTENT_TYPE_MUSIC).build());player.setDataSource(f.getPath());player.setOnPreparedListener(mp->{mp.start();playback.setText("Играет: "+title);});player.setOnCompletionListener(mp->stopPlayback());player.setOnErrorListener((mp,w,e)->{stopPlayback();Jobs.update("Ошибка проигрывателя");return true;});player.prepareAsync();}catch(Exception e){stopPlayback();Jobs.update("Ошибка воспроизведения: "+Jobs.error(e));}}
    private void pausePlayback() {if(player==null)return;try{if(player.isPlaying()){player.pause();playback.setText("Пауза");}else{player.start();playback.setText("Воспроизведение продолжено");}}catch(IllegalStateException ignored){}}
    private void seek(int ms) {if(player==null)return;try{int p=Math.max(0,Math.min(player.getDuration(),player.getCurrentPosition()+ms));player.seekTo(p);playback.setText("Позиция: "+(p/1000)+" секунд");}catch(IllegalStateException ignored){}}
    private void stopPlayback() {if(player!=null){player.release();player=null;}if(audio!=null)audio.abandonAudioFocus(focusListener);if(playback!=null)playback.setText("Воспроизведение остановлено");}
}
