package org.bashir.vocalmidi;
import android.app.*;
import android.content.*;
import android.os.*;
import android.view.*;
import android.widget.*;
import com.chaquo.python.*;
import com.arthenica.ffmpegkit.*;
import java.io.*;

/** Real Android/native-library smoke test, included only in the test APK. */
public class SmokeTest extends Instrumentation {
    @Override public void onCreate(Bundle args) { super.onCreate(args); start(); }
    @Override public void onStart() {
        Bundle result=new Bundle();
        try {
            Context c=getTargetContext();
            File audio=new File(c.getFilesDir(),"fixture.unknown");
            try(InputStream in=getContext().getAssets().open("mp3-in-matroska.data");OutputStream out=new FileOutputStream(audio)){
                byte[] b=new byte[8192];int n;while((n=in.read(b))!=-1)out.write(b,0,n);
            }
            FFmpegSession s=FFmpegKit.executeWithArguments(new String[]{"-y","-i",audio.getPath(),"-ac","1","-ar","32000","-c:a","pcm_s16le",new File(c.getFilesDir(),"decoded.wav").getPath()});
            if(!ReturnCode.isSuccess(s.getReturnCode()))throw new AssertionError("FFmpeg decode failed");
            PyObject engine=Jobs.engine(c);
            PyObject globals=Python.getInstance().getModule("builtins").callAttr("dict");
            Python.getInstance().getModule("builtins").callAttr("exec",
                "import wave, numpy as np, mido, rhythm, engine, vocalmidi_rubberband\n"+
                "d='"+c.getFilesDir().getPath()+"'\n"+
                "x=np.zeros(64000);t=np.arange(12800)/32000\n"+
                "x[6400:19200]=.3*np.sin(2*np.pi*220*t);x[32000:44800]=.3*np.sin(2*np.pi*330*t)\n"+
                "engine.write_wav(d+'/vocal.wav',x)\n"+
                "m=mido.MidiFile();tr=mido.MidiTrack();m.tracks.append(tr)\n"+
                "tr.extend([mido.Message('note_on',note=64,time=96),mido.Message('note_off',note=64,time=672),mido.Message('note_on',note=69,time=192),mido.Message('note_off',note=69,time=768)]);m.save(d+'/melody.mid')\n",globals);
            String midi=new File(c.getFilesDir(),"melody.mid").getPath();
            c.getSharedPreferences("project",0).edit()
                .putString("tracks",engine.callAttr("inspect_midi",midi).toString())
                .putString("audioName","Тестовый вокал").putString("midiName","Тестовый MIDI")
                .putInt("mode",0).putInt("sensitivity",0).putString("offset","0")
                .putString("transpose","0").putBoolean("mute",true).commit();
            Activity activity=startActivitySync(new Intent(c,MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
            waitForIdleSync();
            runOnMainSync(()->{
                Button button=findButton(activity.getWindow().getDecorView(),"Обработать вокал");
                if(button==null||!button.isEnabled())throw new AssertionError("Render action unavailable");
                button.performClick();
            });
            long deadline=System.currentTimeMillis()+240000;
            while(Jobs.busy&&System.currentTimeMillis()<deadline)Thread.sleep(200);
            if(Jobs.busy||!Jobs.status.startsWith("Готово")||!Jobs.status.contains("Rubber Band R3"))throw new AssertionError("Service render: "+Jobs.status);
            Python.getInstance().getModule("builtins").callAttr("exec",
                "with wave.open(d+'/result.wav') as w: assert w.getnframes()==57600; y=np.frombuffer(w.readframes(w.getnframes()),'<i2').astype(float)/32768\n"+
                "env=np.sqrt(np.mean(y.reshape(-1,160)**2,axis=1));active=env>.03;edges=np.diff(np.r_[False,active,False].astype(int)); starts=np.flatnonzero(edges==1)*.005\n"+
                "np.testing.assert_allclose(starts,[.1,1.],atol=.025)\n"+
                "for a,b,freq in [(.3,.6,220),(1.2,1.6,330)]:\n"+
                " s=y[round(a*32000):round(b*32000)]; f=np.fft.rfftfreq(len(s),1/32000); peak=f[np.argmax(abs(np.fft.rfft(s*np.hanning(len(s)))))]; assert abs(peak-freq)<8,str(peak)\n",globals);
            result.putString("stream","PASS: FFmpeg; native Rubber Band 4.0.0 R3; continuous MIDI warp through UI/service; measured onset timing and preserved pitch.\n");
            finish(-1,result);
        }catch(Throwable ex){result.putString("stream","FAIL: "+android.util.Log.getStackTraceString(ex));finish(0,result);}
    }
    private Button findButton(View v,String text) {
        if(v instanceof Button&&((Button)v).getText().toString().equals(text))return (Button)v;
        if(v instanceof ViewGroup){ViewGroup g=(ViewGroup)v;for(int i=0;i<g.getChildCount();i++){Button b=findButton(g.getChildAt(i),text);if(b!=null)return b;}}
        return null;
    }
}
