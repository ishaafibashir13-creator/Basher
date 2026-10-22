package org.bashir.vocalmidi;
import android.app.*;
import android.content.*;
import android.os.*;
import android.view.*;
import android.widget.*;
import com.chaquo.python.*;
import com.arthenica.ffmpegkit.*;
import java.io.*;

/** Instrumented smoke test; only included in the test APK. */
public class SmokeTest extends Instrumentation {
    @Override public void onCreate(Bundle args) { super.onCreate(args); start(); }
    @Override public void onStart() {
        Bundle result=new Bundle();
        try {
            Context c=getTargetContext();
            File audio=new File(c.getFilesDir(),"fixture.unknown");
            try(InputStream in=getContext().getAssets().open("mp3-in-matroska.data"); OutputStream out=new FileOutputStream(audio)){byte[] b=new byte[8192];int n;while((n=in.read(b))!=-1)out.write(b,0,n);}
            File decoded=new File(c.getFilesDir(),"vocal.wav");
            FFmpegSession s=FFmpegKit.executeWithArguments(new String[]{"-y","-i",audio.getPath(),"-ac","1","-ar","32000","-c:a","pcm_s16le",decoded.getPath()});
            if(!ReturnCode.isSuccess(s.getReturnCode()))throw new AssertionError("FFmpeg container decode failed: "+s.getFailStackTrace());
            PyObject e=Jobs.engine(c);
            PyObject globals=Python.getInstance().getModule("builtins").callAttr("dict");
            Python.getInstance().getModule("builtins").callAttr("exec",
                "import os, wave, numpy as np, mido, pyworld\n"+
                "d="+"'"+c.getFilesDir().getPath()+"'\n"+
                "m=mido.MidiFile(); t=mido.MidiTrack(); m.tracks.append(t)\n"+
                "t.append(mido.Message('note_on',note=69,velocity=100));t.append(mido.Message('note_off',note=69,time=576));m.save(d+'/melody.mid')\n", globals);
            String midi=new File(c.getFilesDir(),"melody.mid").getPath();
            String info=e.callAttr("inspect_midi",midi).toString();
            c.getSharedPreferences("project",0).edit().putString("tracks",info).putString("audioName","Тестовый вокал").putString("midiName","Тестовая мелодия").commit();
            e.callAttr("preview",midi,0,"high",0,new File(c.getFilesDir(),"preview.wav").getPath());
            e.callAttr("render",decoded.getPath(),midi,0,"high",0,0,false,new File(c.getFilesDir(),"result.wav").getPath(),new File(c.getFilesDir(),"cancel").getPath());
            Python.getInstance().getModule("builtins").callAttr("exec",
                "with wave.open(d+'/result.wav') as w: y=np.frombuffer(w.readframes(w.getnframes()),dtype='<i2').astype(float)\n"+
                "assert len(y)>16000\n"+
                "s=y[4000:16000]; f=np.fft.rfftfreq(len(s),1/32000); peak=f[np.argmax(abs(np.fft.rfft(s*np.hanning(len(s)))))]\n"+
                "assert abs(peak-440)<12, str(peak)\n", globals);
            // Replace the decoded fixture with two clearly separated vocal units.
            Python.getInstance().getModule("builtins").callAttr("exec",
                "import engine, rhythm\n"+
                "x=np.zeros(64000); t=np.arange(6400)/32000\n"+
                "x[6400:12800]=.4*np.sin(2*np.pi*220*t); x[32000:38400]=.4*np.sin(2*np.pi*330*t)\n"+
                "engine.write_wav(d+'/vocal.wav', x)\n"+
                "m=mido.MidiFile(); t=mido.MidiTrack(); m.tracks.append(t)\n"+
                "t.extend([mido.Message('note_on',note=60,time=96),mido.Message('note_off',note=60,time=384),mido.Message('note_on',note=62,time=288),mido.Message('note_off',note=62,time=384)]); m.save(d+'/melody.mid')\n",
                globals);
            c.getSharedPreferences("project",0).edit().putInt("mode",0).putInt("sensitivity",0)
                .putString("offset","0").putBoolean("mute",false)
                .putString("tracks",e.callAttr("inspect_midi",midi).toString()).commit();
            Intent intent=new Intent(c,MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            Activity activity=startActivitySync(intent);
            waitForIdleSync();
            runOnMainSync(()->checkView(activity.getWindow().getDecorView()));
            runOnMainSync(()->{
                Button button=findButton(activity.getWindow().getDecorView(),"Обработать вокал");
                if(button==null||!button.isEnabled())throw new AssertionError("Render action unavailable");
                button.performClick();
            });
            long deadline=System.currentTimeMillis()+180000;
            while(Jobs.busy&&System.currentTimeMillis()<deadline)Thread.sleep(200);
            if(Jobs.busy||!Jobs.status.startsWith("Готово"))throw new AssertionError("Service render: "+Jobs.status);
            Python.getInstance().getModule("builtins").callAttr("exec",
                "units=rhythm.detect_units(d+'/vocal.wav',.12,d+'/cancel')\n"+
                "with wave.open(d+'/vocal.wav') as w: x=np.frombuffer(w.readframes(w.getnframes()),'<i2')\n"+
                "with wave.open(d+'/result.wav') as w: y=np.frombuffer(w.readframes(w.getnframes()),'<i2')\n"+
                "assert len(y)==38400\n"+
                "for (a,b),pos in zip(units,[3200,25600]): np.testing.assert_array_equal(x[a+256:b-256],y[pos+256:pos+b-a-256])\n", globals);
            result.putString("stream","PASS: Android FFmpeg MP3-in-Matroska with unknown extension; embedded PyWORLD; MIDI preview; 440 Hz render; Activity and button labels; rhythm foreground service through UI button; unchanged sample interiors and exact MIDI placement.\n");
            finish(-1,result);
        }catch(Throwable ex){result.putString("stream","FAIL: "+android.util.Log.getStackTraceString(ex));finish(0,result);}
    }
    private void checkView(View v) {
        if(v instanceof Button && ((Button)v).getText().length()==0)throw new AssertionError("Unlabelled button");
        if(v instanceof EditText && v.getId()==View.NO_ID)throw new AssertionError("Unlabelled field");
        if(v instanceof ViewGroup){ViewGroup g=(ViewGroup)v;for(int i=0;i<g.getChildCount();i++)checkView(g.getChildAt(i));}
    }
    private Button findButton(View v,String text) {
        if(v instanceof Button&&((Button)v).getText().toString().equals(text))return (Button)v;
        if(v instanceof ViewGroup){ViewGroup g=(ViewGroup)v;for(int i=0;i<g.getChildCount();i++){Button b=findButton(g.getChildAt(i),text);if(b!=null)return b;}}
        return null;
    }
}
