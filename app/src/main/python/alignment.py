"""Monotonic many-to-one/one-to-many alignment; no forced equal slice counts."""
import math
import functools
import numpy as np
from vocal_analysis import check_cancel


def midi_events(notes, length, offset, rate=32000, policy='high'):
    chosen={}
    for a,b,p,v in notes:
        start=max(0,round((a+offset)*rate));end=min(length,round((b+offset)*rate))
        if end<=start or start>=length:continue
        old=chosen.get(start)
        if old is None or (policy=='high' and p>old['pitch']) or (policy=='low' and p<old['pitch']) or policy=='last':
            chosen[start]={'start':start,'end':end,'pitch':float(p)}
    result=[chosen[k] for k in sorted(chosen)]
    for i in range(len(result)-1):result[i]['end']=min(result[i]['end'],result[i+1]['start'])
    return result


def temporal_groups(source,target):
    # Fallback for extreme melismas or very large tracks. Additional MIDI notes
    # stay inside a continuous source vowel; they do not create chopped repeats.
    m,n=len(source),len(target)
    if m<=n:
        src_span=max(1,source[-1]['end']-source[0]['start'])
        dst_span=max(1,target[-1]['end']-target[0]['start'])
        cuts=[0]
        starts=np.array([x['start'] for x in target])
        for i in range(1,m):
            ideal=target[0]['start']+(source[i]['start']-source[0]['start'])/src_span*dst_span
            j=int(np.argmin(np.abs(starts-ideal)))
            cuts.append(max(cuts[-1]+1,min(n-(m-i),j)))
        cuts.append(n)
        return [(i,i+1,cuts[i],cuts[i+1]) for i in range(m)]
    rev=temporal_groups(target,source)
    return [(a,b,i,j) for i,j,a,b in rev]


def align_groups(source,target,cancel):
    m,n=len(source),len(target)
    if max(m,n)>8*min(m,n) or m*n>600000:return temporal_groups(source,target)
    src_total=max(1,source[-1]['end']-source[0]['start'])
    dst_total=max(1,target[-1]['end']-target[0]['start'])
    @functools.lru_cache(None)
    def feature(which,i,k):
        events=source if which==0 else target
        total=src_total if which==0 else dst_total
        return ((events[i]['start']-events[0]['start'])/total,
                max(1,events[i+k-1]['end']-events[i]['start'])/total)
    dp=np.full((m+1,n+1),np.inf);dp[0,0]=0
    back=np.zeros((m+1,n+1,2),dtype=np.int8)
    transitions=[(1,k) for k in range(1,9)]+[(k,1) for k in range(2,9)]
    band=max(16,round(n*.15))
    for i in range(m):
        check_cancel(cancel)
        for j in range(max(0,round(i*n/m)-band),min(n,round(i*n/m)+band)+1):
            if not np.isfinite(dp[i,j]) or j==n:continue
            for a,b in transitions:
                if i+a>m or j+b>n:continue
                sp,sd=feature(0,i,a);tp,td=feature(1,j,b)
                cost=abs(math.log(sd/td))*.45+abs(sp-tp)*4+.09*(a+b-2)
                score=dp[i,j]+cost
                if score<dp[i+a,j+b]:dp[i+a,j+b]=score;back[i+a,j+b]=(a,b)
    if not np.isfinite(dp[m,n]):return temporal_groups(source,target)
    groups=[];i,j=m,n
    while i or j:
        a,b=map(int,back[i,j]);groups.append((i-a,i,j-b,j));i-=a;j-=b
    return list(reversed(groups))


def time_map(source,target,groups):
    input_start=source[0]['start'];input_end=source[-1]['end']
    output_start=target[0]['start'];output_end=target[-1]['end']
    candidates=[]
    for a,b,i,j in groups:
        candidates.extend([(source[a]['start']-input_start,target[i]['start']-output_start,2),
                           (source[b-1]['end']-input_start,target[j-1]['end']-output_start,1)])
    ni,no=input_end-input_start,output_end-output_start
    by_source={}
    for a,b,priority in candidates:
        if 0<a<ni and 0<b<no and (a not in by_source or priority>by_source[a][1]):by_source[a]=(b,priority)
    anchors=[(0,0)]
    # Very close or coincident onset/end points are one boundary. Keep attacks
    # in preference to offsets and never send zero/negative slopes to Rubber Band.
    for a,(b,priority) in sorted(by_source.items()):
        if a-anchors[-1][0]>=160 and b-anchors[-1][1]>=160 and ni-a>=160 and no-b>=160:
            anchors.append((a,b))
    anchors.append((ni,no))
    return input_start,input_end,output_start,output_end,anchors
