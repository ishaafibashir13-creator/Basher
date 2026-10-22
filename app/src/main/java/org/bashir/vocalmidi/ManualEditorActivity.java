package org.bashir.vocalmidi;

import android.app.*;
import android.content.*;
import android.media.*;
import android.os.*;
import android.text.InputType;
import android.view.*;
import android.widget.*;
import org.json.*;
import java.io.*;
import java.util.*;

/** A text-first fragment editor: every operation works without seeing a waveform. */
public class ManualEditorActivity extends Activity {
    private LinearLayout root;
    private TextView status, summary;
    private Spinner fragments, step;
    private CheckBox metronome;
    private EditText sourceStart,sourceEnd,targetStart,targetEnd;
    private final List<View> controls=new ArrayList<>();
    private JSONArray segments=new JSONArray();
    private SharedPreferences prefs;
    private MidiGrid grid;
    private double sourceLength,outputLength,offset;
    private int track,selected;
    private boolean loading=true,updating=false,working=false,visible=false,ready=false;
    private String undo;
    private MediaPlayer player;
    private AudioManager audio;
    private AudioManager.OnAudioFocusChangeListener focus;
    private boolean original=false,prepared=false;
    private int playbackEnd;
    private final Handler handler=new Handler(Looper.getMainLooper());
    private final Runnable stopAtEnd=new Runnable(){public void run(){
        try {if(player!=null&&prepared&&player.isPlaying()&&player.getCurrentPosition()>=playbackEnd){player.pause();say("Фрагмент прослушан. Позиция "+fmt(player.getCurrentPosition()/1000.)+" секунд");}
        }catch(IllegalStateException ignored){}
        if(player!=null)handler.postDelayed(this,30);
    }};
    private File file(String name){return new File(getFilesDir(),name);}
    private int dp(int n){return Math.round(n*getResources().getDisplayMetrics().density);}
    private static String fmt(double n){return String.format(Locale.US,"%.9f",n).replaceAll("0+$","").replaceAll("\\.$","");}
    @Override public void onCreate(Bundle state){
        super.onCreate(state);prefs=getSharedPreferences("project",MODE_PRIVATE);
        audio=(AudioManager)getSystemService(AUDIO_SERVICE);focus=c->{if(c<0)stop();};
        ScrollView scroll=new ScrollView(this);root=new LinearLayout(this);root.setOrientation(LinearLayout.VERTICAL);root.setPadding(dp(20),dp(12),dp(20),dp(24));scroll.addView(root);setContentView(scroll);
        scroll.setOnApplyWindowInsetsListener((v,insets)->{v.setPadding(insets.getSystemWindowInsetLeft(),insets.getSystemWindowInsetTop(),insets.getSystemWindowInsetRight(),insets.getSystemWindowInsetBottom());return insets;});
        TextView title=text("Ручная нарезка и выравнивание");title.setTextSize(24);if(Build.VERSION.SDK_INT>=28)title.setAccessibilityHeading(true);
        text("Все действия доступны кнопками и числовыми полями. Жесты по волне не нужны. Доля 1 — начало MIDI; одна доля равна четвертной ноте, включая размер 6/8. Дробная часть: 1,5 — середина первой доли. Изменения BPM учитываются. Пустоты между фрагментами станут тишиной; неуказанные участки исходника не попадут в результат.");
        summary=text("Чтение темпа MIDI…");
        fragments=spinner("Выбранный фрагмент",new String[]{"Загрузка"});
        fragments.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener(){
            public void onItemSelected(AdapterView<?> a,View v,int position,long id){
                if(updating||loading||position==selected)return;
                if(!saveCurrent(false)){updateList();return;}stop();selected=position;show();
            }
            public void onNothingSelected(AdapterView<?> a){}
        });
        button("Предыдущий фрагмент",()->select(-1));button("Следующий фрагмент",()->select(1));
        heading("Границы исходного вокала");
        sourceStart=field("Начало в исходном вокале, секунд");sourceEnd=field("Конец в исходном вокале, секунд");
        button("Начало исходника раньше на 10 миллисекунд",()->adjust(sourceStart,-.01));
        button("Начало исходника позже на 10 миллисекунд",()->adjust(sourceStart,.01));
        button("Конец исходника раньше на 10 миллисекунд",()->adjust(sourceEnd,-.01));
        button("Конец исходника позже на 10 миллисекунд",()->adjust(sourceEnd,.01));
        heading("Положение и длительность в MIDI");
        targetStart=field("Начальная доля MIDI, начиная с 1");targetEnd=field("Конечная доля MIDI, начиная с 1");
        step=spinner("Шаг сетки MIDI",new String[]{"Четверть — 1 доля","Восьмая — половина доли","Шестнадцатая — четверть доли"});step.setSelection(prefs.getInt("manualStep",2));
        button("Передвинуть фрагмент раньше на шаг сетки",()->move(-1));
        button("Передвинуть фрагмент позже на шаг сетки",()->move(1));
        button("Конец MIDI раньше на шаг сетки",()->adjust(targetEnd,-stepValue()));
        button("Конец MIDI позже на шаг сетки",()->adjust(targetEnd,stepValue()));
        button("Привязать начало и конец к ближайшей сетке",this::snap);
        heading("Прослушивание и установка границ на слух");
        text("Сначала слушайте исходный фрагмент. На паузе можно точно поставить границы по текущей позиции проигрывателя. Разделение создаёт два соседних фрагмента; затем их можно двигать и менять длительность независимо.");
        button("Слушать исходный фрагмент",()->listenSource(false,false));
        button("Слушать вокруг начала исходного фрагмента",()->listenSource(true,false));
        button("Слушать вокруг конца исходного фрагмента",()->listenSource(true,true));
        button("Пауза или продолжение прослушивания",this::pause);
        button("Позиция прослушивания раньше на 0,1 секунды",()->seek(-100));
        button("Позиция прослушивания позже на 0,1 секунды",()->seek(100));
        button("Позиция прослушивания раньше на 1 секунду",()->seek(-1000));
        button("Позиция прослушивания позже на 1 секунду",()->seek(1000));
        button("Поставить начало исходника в позицию прослушивания",()->mark(sourceStart));
        button("Поставить конец исходника в позицию прослушивания",()->mark(sourceEnd));
        button("Разделить фрагмент в позиции прослушивания",this::split);
        metronome=new CheckBox(this);metronome.setText("Метроном по четвертным долям MIDI в выровненном прослушивании");metronome.setMinHeight(dp(56));metronome.setChecked(true);root.addView(metronome);controls.add(metronome);
        button("Слушать выровненный фрагмент без тюнинга",this::preview);
        button("Остановить прослушивание",this::stop);
        heading("Фрагменты и сохранение разметки");
        button("Сохранить изменения фрагмента",()->saveCurrent(true));
        button("Добавить фрагмент после выбранного",this::add);
        button("Удалить выбранный фрагмент",this::delete);
        button("Отменить последнее изменение",this::undo);
        button("Сохранить разметку и использовать её",()->{if(saveCurrent(false)&&validateAll()){persist(true);say("Разметка сохранена и включена. Вернитесь назад и выберите режим ритма или ритма с тюнингом.");}});
        button("Сохранить и вернуться",()->{if(saveCurrent(false)&&validateAll()){persist(true);finish();}});
        status=text("Загрузка…");status.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);lock(true);
        if(Jobs.busy){say("Сначала дождитесь завершения обработки на главном экране");return;}
        try{offset=Double.parseDouble(prefs.getString("offset","0").replace(',','.'));if(!Double.isFinite(offset))throw new IllegalArgumentException();track=getIntent().getIntExtra("track",0);}catch(Exception e){say("Проверьте сдвиг MIDI на главном экране");return;}
        working=true;Jobs.busy=true;
        Jobs.worker.execute(()->{
            try{
                Jobs.engine(this);
                String json=com.chaquo.python.Python.getInstance().getModule("manual").callAttr("inspect",file("vocal.wav").getPath(),file("melody.mid").getPath(),track,offset).toString();
                JSONObject info=new JSONObject(json);
                handler.post(()->{try{
                    sourceLength=info.getDouble("source_seconds");outputLength=info.getDouble("output_seconds");JSONArray arr=info.getJSONArray("grid");double[][] values=new double[arr.length()][3];
                    for(int i=0;i<arr.length();i++)for(int j=0;j<3;j++)values[i][j]=arr.getJSONArray(i).getDouble(j);grid=new MidiGrid(values);
                    String plan=prefs.getString("manualPlan","");
                    if(!plan.isEmpty())segments=new JSONObject(plan).getJSONArray("segments");
                    if(segments.length()==0){double q0=Math.max(0,grid.quarter(-offset)),q1=grid.quarter(outputLength-offset);segments.put(segment(0,sourceLength,q0,q1));}
                    selected=Math.max(0,Math.min(segments.length()-1,prefs.getInt("manualSelected",0)));
                    ready=true;loading=false;summary.setText("Начальный темп: "+fmt(grid.initialBpm())+" BPM. Изменений темпа: "+grid.changes()+". Вокал: "+fmt(sourceLength)+" секунд. Результат: "+fmt(outputLength)+" секунд. Конечная доля: "+fmt(grid.quarter(outputLength-offset)+1)+".");show();say("Разметка загружена. Фрагментов: "+segments.length());
                }catch(Exception e){say("Не удалось прочитать разметку: "+Jobs.error(e));}finally{working=false;lock(false);}});
            }catch(Throwable e){handler.post(()->{working=false;say("Ошибка: "+Jobs.error(e));});}
            finally{Jobs.busy=false;Jobs.update(Jobs.status);}
        });
    }
    private TextView text(String value){TextView v=new TextView(this);v.setText(value);v.setTextSize(17);v.setPadding(0,dp(8),0,dp(8));root.addView(v);return v;}
    private void heading(String value){TextView v=text(value);v.setTextSize(21);v.setTypeface(null,android.graphics.Typeface.BOLD);if(Build.VERSION.SDK_INT>=28)v.setAccessibilityHeading(true);}
    private Button button(String label,Runnable action){Button v=new Button(this);v.setText(label);v.setAllCaps(false);v.setTextSize(17);v.setMinHeight(dp(56));root.addView(v,new LinearLayout.LayoutParams(-1,-2));controls.add(v);v.setOnClickListener(w->{try{action.run();}catch(Exception e){say("Ошибка: "+Jobs.error(e));}});return v;}
    private EditText field(String label){TextView title=text(label);EditText v=new EditText(this);v.setId(View.generateViewId());title.setLabelFor(v.getId());v.setSingleLine(true);v.setTextSize(18);v.setMinHeight(dp(56));v.setInputType(InputType.TYPE_CLASS_NUMBER|InputType.TYPE_NUMBER_FLAG_DECIMAL|InputType.TYPE_NUMBER_FLAG_SIGNED);root.addView(v);controls.add(v);return v;}
    private Spinner spinner(String label,String[] items){TextView title=text(label);Spinner v=new Spinner(this);v.setId(View.generateViewId());title.setLabelFor(v.getId());v.setContentDescription(label);v.setMinimumHeight(dp(56));root.addView(v);controls.add(v);items(v,items);return v;}
    private void items(Spinner v,String[] values){ArrayAdapter<String> adapter=new ArrayAdapter<>(this,android.R.layout.simple_spinner_item,values);adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);v.setAdapter(adapter);}
    private void say(String value){if(status!=null)status.setText(value);}
    private void lock(boolean value){for(View v:controls)v.setEnabled(!value&&ready);}
    private double value(EditText field){try{double n=Double.parseDouble(field.getText().toString().trim().replace(',','.'));if(!Double.isFinite(n))throw new IllegalArgumentException();field.setError(null);return n;}catch(Exception e){field.setError("Введите число");field.requestFocus();throw new IllegalArgumentException("Проверьте выделенное числовое поле");}}
    private double stepValue(){return new double[]{1,.5,.25}[step.getSelectedItemPosition()];}
    private JSONObject segment(double a,double b,double q,double r)throws JSONException{return new JSONObject().put("source_start",a).put("source_end",b).put("target_start_q",q).put("target_end_q",r);}
    private JSONObject candidate()throws JSONException{return segment(value(sourceStart),value(sourceEnd),value(targetStart)-1,value(targetEnd)-1);}
    private void validate(JSONObject s,int index)throws JSONException{
        double a=s.getDouble("source_start"),b=s.getDouble("source_end"),q=s.getDouble("target_start_q"),r=s.getDouble("target_end_q");
        long sa=Math.round(a*32000),sb=Math.round(b*32000),ta=Math.round((grid.seconds(q)+offset)*32000),tb=Math.round((grid.seconds(r)+offset)*32000);
        if(!Double.isFinite(a+b+q+r)||sa<0||sb>Math.round(sourceLength*32000)||sb-sa<320||q<0||r<=q||ta<0||tb>Math.round(outputLength*32000)||tb-ta<320)
            throw new IllegalArgumentException("Фрагмент "+(index+1)+": проверьте границы. Длительность не меньше 0,01 секунды; конец результата не дальше "+fmt(outputLength)+" секунд.");
    }
    private String snapshot(){return segments.toString();}
    private void persist(boolean enable){prefs.edit().putString("manualPlan","{\"schema\":1,\"segments\":"+segments+"}").putInt("manualSelected",selected).putInt("manualStep",step.getSelectedItemPosition()).putBoolean("manualEnabled",enable||prefs.getBoolean("manualEnabled",false)).apply();}
    private boolean saveCurrent(boolean announce){if(!ready||segments.length()==0)return false;try{JSONObject s=candidate();validate(s,selected);if(!s.toString().equals(segments.getJSONObject(selected).toString())){undo=snapshot();segments.put(selected,s);}persist(false);if(announce){updateList();say("Фрагмент "+(selected+1)+" сохранён. "+description(s));}return true;}catch(Exception e){say(Jobs.error(e));return false;}}
    private boolean validateAll(){try{for(int i=0;i<segments.length();i++){JSONObject s=segments.getJSONObject(i);validate(s,i);for(int j=0;j<i;j++){JSONObject t=segments.getJSONObject(j);if(s.getDouble("target_start_q")<t.getDouble("target_end_q")-1e-9&&t.getDouble("target_start_q")<s.getDouble("target_end_q")-1e-9)throw new IllegalArgumentException("Фрагменты "+(j+1)+" и "+(i+1)+" перекрываются в MIDI. Передвиньте их границы.");}}return true;}catch(Exception e){say(Jobs.error(e));return false;}}
    private String description(JSONObject s)throws JSONException{return "Исходник "+fmt(s.getDouble("source_start"))+" — "+fmt(s.getDouble("source_end"))+" секунд; MIDI, доли "+fmt(s.getDouble("target_start_q")+1)+" — "+fmt(s.getDouble("target_end_q")+1);}
    private void updateList(){try{updating=true;String[] labels=new String[segments.length()];for(int i=0;i<labels.length;i++)labels[i]="Фрагмент "+(i+1)+". "+description(segments.getJSONObject(i));items(fragments,labels);fragments.setSelection(selected);}catch(Exception e){say(Jobs.error(e));}finally{updating=false;}}
    private void show(){try{JSONObject s=segments.getJSONObject(selected);sourceStart.setText(fmt(s.getDouble("source_start")));sourceEnd.setText(fmt(s.getDouble("source_end")));targetStart.setText(fmt(s.getDouble("target_start_q")+1));targetEnd.setText(fmt(s.getDouble("target_end_q")+1));updateList();}catch(Exception e){say(Jobs.error(e));}}
    private void select(int delta){if(!saveCurrent(false))return;int n=selected+delta;if(n<0||n>=segments.length()){say("Достигнут край списка фрагментов");return;}stop();selected=n;show();try{say("Фрагмент "+(selected+1)+". "+description(segments.getJSONObject(selected)));}catch(Exception ignored){}}
    private void adjust(EditText field,double delta){field.setText(fmt(value(field)+delta));say("Новое значение: "+field.getText()+". Нажмите сохранить фрагмент.");}
    private void move(int direction){double a=value(targetStart),b=value(targetEnd),delta=direction*stepValue();targetStart.setText(fmt(a+delta));targetEnd.setText(fmt(b+delta));say("MIDI: с доли "+targetStart.getText()+" до "+targetEnd.getText()+". Нажмите сохранить фрагмент.");}
    private void snap(){double d=stepValue();targetStart.setText(fmt(Math.round((value(targetStart)-1)/d)*d+1));targetEnd.setText(fmt(Math.round((value(targetEnd)-1)/d)*d+1));say("Границы привязаны к сетке. Доли "+targetStart.getText()+" — "+targetEnd.getText()+". Нажмите сохранить фрагмент.");}
    private void add(){if(segments.length()>=2000){say("Максимум 2000 фрагментов");return;}if(!saveCurrent(false))return;try{JSONObject s=segments.getJSONObject(selected);double a=s.getDouble("source_end"),q=s.getDouble("target_end_q"),r=Math.min(q+stepValue(),grid.quarter(outputLength-offset)),b=Math.min(sourceLength,a+grid.seconds(r)-grid.seconds(q));JSONObject next=segment(a,b,q,r);validate(next,segments.length());undo=snapshot();segments.put(next);selected=segments.length()-1;persist(false);show();say("Добавлен фрагмент "+(selected+1));}catch(Exception e){say("Нет места после фрагмента. Разделите существующий или укоротите его. "+Jobs.error(e));}}
    private void delete(){if(segments.length()<=1){say("Оставьте хотя бы один фрагмент. Его границы можно изменить.");return;}stop();undo=snapshot();segments.remove(selected);selected=Math.min(selected,segments.length()-1);persist(false);show();say("Фрагмент удалён. Доступна отмена последнего изменения.");}
    private void undo(){if(undo==null){say("Нет изменения для отмены");return;}try{stop();String old=snapshot();segments=new JSONArray(undo);undo=old;selected=Math.min(selected,segments.length()-1);persist(false);show();say("Изменение отменено");}catch(Exception e){say(Jobs.error(e));}}
    private void split(){if(segments.length()>=2000){say("Максимум 2000 фрагментов");return;}if(!original||!prepared||player==null){say("Сначала запустите исходный фрагмент и поставьте прослушивание на паузу");return;}if(!saveCurrent(false))return;try{double at=player.getCurrentPosition()/1000.;JSONObject s=segments.getJSONObject(selected);double a=s.getDouble("source_start"),b=s.getDouble("source_end"),q=s.getDouble("target_start_q"),r=s.getDouble("target_end_q");double middle=grid.quarter(grid.seconds(q)+(grid.seconds(r)-grid.seconds(q))*(at-a)/(b-a));JSONObject left=segment(a,at,q,middle),right=segment(at,b,middle,r);validate(left,selected);validate(right,selected+1);undo=snapshot();JSONArray result=new JSONArray();for(int i=0;i<segments.length();i++){if(i==selected){result.put(left);result.put(right);}else result.put(segments.getJSONObject(i));}segments=result;stop();persist(false);show();say("Фрагмент разделён. Следующий фрагмент доступен кнопкой Следующий.");}catch(Exception e){say("Разделение: "+Jobs.error(e));}}
    private void listenSource(boolean around,boolean end){double a=value(sourceStart),b=value(sourceEnd);if(a<0||b<=a||b>sourceLength){say("Проверьте границы исходного фрагмента");return;}if(around){double center=end?b:a;a=Math.max(0,center-.35);b=Math.min(sourceLength,center+.35);}play(file("vocal.wav"),a,b,true);}
    private void play(File path,double a,double b,boolean source){stop();try{if(audio.requestAudioFocus(focus,AudioManager.STREAM_MUSIC,AudioManager.AUDIOFOCUS_GAIN_TRANSIENT)!=AudioManager.AUDIOFOCUS_REQUEST_GRANTED){say("Звук занят другим приложением");return;}original=source;playbackEnd=(int)Math.round(b*1000);player=new MediaPlayer();player.setAudioAttributes(new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA).setContentType(AudioAttributes.CONTENT_TYPE_MUSIC).build());player.setDataSource(path.getPath());player.setOnPreparedListener(p->{prepared=true;p.setOnSeekCompleteListener(mp->{mp.setOnSeekCompleteListener(null);mp.start();handler.post(stopAtEnd);});p.seekTo((int)Math.round(a*1000));say(source?"Играет исходный фрагмент":"Играет выровненный фрагмент");});player.setOnCompletionListener(p->{p.pause();say("Прослушивание завершено");});player.setOnErrorListener((p,w,e)->{stop();say("Ошибка воспроизведения");return true;});player.prepareAsync();}catch(Exception e){stop();say(Jobs.error(e));}}
    private void pause(){if(player==null||!prepared)return;try{if(player.isPlaying()){player.pause();say("Пауза. Позиция "+fmt(player.getCurrentPosition()/1000.)+" секунд");}else if(player.getCurrentPosition()<playbackEnd){player.start();say("Прослушивание продолжено");}else say("Конец фрагмента. Перемотайте назад или запустите его заново.");}catch(Exception e){say(Jobs.error(e));}}
    private void seek(int delta){if(player==null||!prepared)return;try{player.pause();int position=Math.max(0,Math.min(player.getDuration(),player.getCurrentPosition()+delta));player.seekTo(position);say("Пауза. Позиция "+fmt(position/1000.)+" секунд");}catch(Exception e){say(Jobs.error(e));}}
    private void mark(EditText field){if(player==null||!prepared||!original){say("Границы отмечаются только при прослушивании исходного вокала");return;}player.pause();field.setText(fmt(player.getCurrentPosition()/1000.));say("Граница: "+field.getText()+" секунд. Нажмите сохранить фрагмент.");}
    private void preview(){if(!saveCurrent(false))return;stop();try{String segment=segments.getJSONObject(selected).toString();final boolean click=metronome.isChecked();working=true;Jobs.busy=true;lock(true);file("manual-cancel").delete();say("Подготовка выровненного фрагмента…");Jobs.worker.execute(()->{try{String json=com.chaquo.python.Python.getInstance().getModule("manual").callAttr("preview",file("vocal.wav").getPath(),file("melody.mid").getPath(),track,offset,segment,file("manual-preview.wav").getPath(),file("manual-cancel").getPath(),click).toString();double seconds=new JSONObject(json).getDouble("seconds");handler.post(()->{if(visible)play(file("manual-preview.wav"),0,seconds,false);});}catch(Throwable e){handler.post(()->say("Прослушивание: "+Jobs.error(e)));}finally{Jobs.busy=false;Jobs.update(Jobs.status);handler.post(()->{working=false;lock(false);});}});}catch(Exception e){working=false;Jobs.busy=false;lock(false);say(Jobs.error(e));}}
    private void stop(){handler.removeCallbacks(stopAtEnd);if(player!=null){player.release();player=null;}prepared=false;original=false;if(audio!=null)audio.abandonAudioFocus(focus);}
    @Override protected void onStart(){super.onStart();visible=true;}
    @Override protected void onStop(){visible=false;if(ready&&!working)saveCurrent(false);stop();if(working)try{file("manual-cancel").createNewFile();}catch(IOException ignored){}super.onStop();}
}
