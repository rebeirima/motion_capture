#!/usr/bin/env python3
"""Local gesture annotation: Python 3.10+, optional FFmpeg for MKV previews.

Run: python study_annotation_server.py --root /path/to/recordings
Open http://127.0.0.1:8765. Saves immutable CSV versions under --out.
This app is loopback-only. Do not expose it to the internet.
"""
import annotation_store
import argparse, os, csv, hashlib, json, mimetypes, re, shutil, subprocess, threading, uuid
from datetime import datetime, timezone
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlsplit,parse_qs

PROTOCOL=['baseline','open']+[f'finger_{i}' for i in range(1,5)]+[f'thumb_touch_{i}' for i in range(1,5)]+['thumb','L','box','claw','fist','wrist_left_to_right','wrist_flip']
SLOTS=[{'gesture':g,'repetition':r} for g in PROTOCOL for r in range(1,2 if g=='baseline' else 3)]
# Paper C0..C4 arc positions use these calibration-camera indices.
# This is the same DISPLAY_CAL order used by the paper-analysis code.
DISPLAY_CALIBRATION=[4,1,3,2,0]
FRAME_COUNT_CACHE={}

def camera_views(source,derived,manifest):
    mapping=manifest.get('display_to_recorded')
    provenance='transfer manifest'
    if mapping is None:
        for folder in [derived,source]:
            path=folder/'metadata/camera_mapping.txt'
            if path.exists():
                calibrated=[int(x) for x in re.findall(r'-?\d+',path.read_text())]
                if len(calibrated)!=5 or sorted(calibrated)!=list(range(5)):
                    raise ValueError(f'Invalid camera mapping for {source.name}')
                mapping=[calibrated[c] for c in DISPLAY_CALIBRATION]
                provenance='session calibration-to-recorded mapping'
                break
    if mapping is None:
        return ([{'display_camera':None,'recorded_camera':k,'label':f'Recorded cam{k} (position unverified)'} for k in range(5)],False,'unavailable')
    if len(mapping)!=5 or any(type(x) is not int for x in mapping) or sorted(mapping)!=list(range(5)):
        raise ValueError(f'Invalid display-to-recorded camera map for {source.name}')
    return ([{'display_camera':c,'recorded_camera':k,'label':f'C{c}'+(' (center)' if c==2 else '')} for c,k in enumerate(mapping)],True,provenance)

def discover(root,processing=None):
    root=Path(root).resolve();processing=Path(processing).resolve() if processing else root
    manifest_path=root/'annotation_sessions.json'
    manifest={}
    if manifest_path.exists():
        payload=json.loads(manifest_path.read_text())
        for item in payload['sessions']:
            sid=item['session_id']
            if not re.fullmatch(r'S\d+_[LR]_hand_gestures_\d+_\d+',sid):raise ValueError('Invalid session manifest ID')
            if type(item['frame_count']) is not int or item['frame_count']<=0 or item.get('fps',30)!=30:raise ValueError('Invalid manifest timeline')
            if sid in manifest:raise ValueError('Duplicate manifest session')
            manifest[sid]=item
    candidates={p.name:p for p in root.glob('S*_hand_gestures_*') if p.is_dir()}
    for sid in manifest:candidates.setdefault(sid,root/sid)
    sessions={}
    for source in sorted(candidates.values()):
        if not re.fullmatch(r'S\d+_[LR]_hand_gestures_\d+_\d+',source.name):continue
        derived=processing/source.name; folder=derived if all((derived/f'aligned/cam{k}.mkv').exists() for k in range(5)) else source
        has_aligned=all((folder/f'aligned/cam{k}.mkv').exists() for k in range(5))
        has_previews=all((root/'video_proxies'/source.name/f'cam{k}_480p_v2.mp4').exists() for k in range(5))
        if not has_aligned and not has_previews:continue
        state=derived/'processing_state.json'; n=manifest.get(source.name,{}).get('frame_count')
        if n is None and state.exists(): n=json.loads(state.read_text()).get('stages',{}).get('alignment',{}).get('shared_frames')
        if n is None:
            # Read NPZ frame count without importing scientific dependencies.
            import zipfile,struct
            p=source/'mediapipe_3d/mediapipe_hand_3d_standard.npz'
            if p.exists():
                with zipfile.ZipFile(p) as z:
                    payload=z.read('p3ds.npy'); header_length=int.from_bytes(payload[8:10],'little'); header=payload[10:10+header_length].decode(); match=re.search(r"'shape':\s*\((\d+),",header)
                    if match:n=int(match.group(1))
        cache_key=tuple((str(folder/f'aligned/cam{k}.mkv'),(folder/f'aligned/cam{k}.mkv').stat().st_mtime_ns) for k in range(5)) if has_aligned else None
        if n is None and cache_key in FRAME_COUNT_CACHE:n=FRAME_COUNT_CACHE[cache_key]
        if n is None and has_aligned:
            # Valid for separately transferred aligned MKVs without NPZ/state files.
            # Count actual frames; never infer counts from duration or resample.
            if not shutil.which('ffprobe'):continue
            counts=[]
            for k in range(5):
                cmd=['ffprobe','-v','error','-select_streams','v:0','-count_frames','-show_entries','stream=nb_read_frames,r_frame_rate','-of','json',str(folder/f'aligned/cam{k}.mkv')]
                streams=json.loads(subprocess.check_output(cmd))['streams'];stream=streams[0]
                from fractions import Fraction
                if Fraction(stream['r_frame_rate'])!=30:raise ValueError('Expected a 30 fps aligned video; do not resample annotation media')
                counts.append(int(stream['nb_read_frames']))
            n=min(counts);FRAME_COUNT_CACHE[cache_key]=n
        if not n:continue
        views,mapped,provenance=camera_views(source,derived,manifest.get(source.name,{}))
        tokens=source.name.split('_');sessions[source.name]={'session_id':source.name,'participant_id':tokens[0],'hand':tokens[1],'frame_count':n,'fps':30,'aligned_folder':str(folder/'aligned'),'camera_views':views,'camera_mapping_verified':mapped,'camera_mapping_source':provenance}
    return sessions
def prepare_proxy(source, folder, k):
    """Create a small H.264 preview with the same 30 fps frame sequence."""
    folder.mkdir(parents=True,exist_ok=True)
    p=folder/f'cam{k}_480p_v2.mp4'
    if p.exists():return p
    if not shutil.which('ffmpeg'):raise ValueError('Install FFmpeg or supply precomputed video_proxies; see README.')
    tmp=folder/f'cam{k}_{uuid.uuid4().hex[:8]}.partial.mp4'
    cmd=['ffmpeg','-nostdin','-n','-v','error','-i',str(source),'-map','0:v:0','-an',
         '-vf','scale=854:-2','-c:v','libx264','-threads','2','-preset','veryfast','-crf','25',
         '-profile:v','baseline','-level:v','3.1','-pix_fmt','yuv420p','-bf','0',
         '-g','30','-fps_mode','passthrough','-movflags','+faststart',str(tmp)]
    subprocess.run(cmd,capture_output=True,check=True)
    tmp.rename(p)
    (folder/f'cam{k}_480p_v2_source.json').write_text(json.dumps({
        'source':str(source),'source_bytes':source.stat().st_size,
        'source_mtime_ns':source.stat().st_mtime_ns,'command':cmd,
        'method':'854-pixel-wide H.264 baseline preview; no frame resampling; annotation restricted to shared range'
    },indent=2))
    return p
def load_video_set(root,path):
    sessions={};root=Path(root).resolve()
    for info in json.loads(Path(path).read_text())['sessions']:
        sid=info['session_id'];k=info['recorded_camera'];mapping=info['display_to_recorded']
        if not re.fullmatch(r'S\d+_[LR]_hand_gestures_\d+_\d+',sid) or sid in sessions:raise ValueError('Invalid or duplicate video identity')
        if len(mapping)!=5 or sorted(mapping)!=list(range(5)) or type(k) is not int or mapping[2]!=k or info['physical_camera']!='C2':raise ValueError('Video does not match its physical C2 mapping')
        video=(root/info['filename']).resolve()
        if not video.is_relative_to(root):raise ValueError('Video path must stay inside the supplied folder')
        if not video.is_file() or hashlib.sha256(video.read_bytes()).hexdigest()!=info['sha256']:raise ValueError('Video missing or checksum differs; run launch.py to download the supplied set')
        if info['fps']!=30 or type(info['frame_count']) is not int or info['frame_count']<1:raise ValueError('Invalid annotation timeline')
        sessions[sid]=dict(session_id=sid,participant_id=sid.split('_')[0],hand=sid.split('_')[1],frame_count=info['frame_count'],fps=30,aligned_folder=str(root),single_video=str(video),camera_mapping_verified=True,camera_views=[dict(display_camera=2,recorded_camera=k,label='C2 (center)')])
    if not sessions:raise ValueError('The supplied video set is empty')
    return sessions

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--root',required=True,type=Path);ap.add_argument('--processing',type=Path);ap.add_argument('--out',type=Path);ap.add_argument('--suggestions',type=Path);ap.add_argument('--single-video',type=Path);ap.add_argument('--video-set',type=Path);ap.add_argument('--port',type=int,default=8765);a=ap.parse_args()
    root=a.root.resolve();processing=a.processing.resolve() if a.processing else root;out=a.out.resolve() if a.out else root/'annotations'
    if not root.is_dir():raise SystemExit('Recording folder does not exist.')
    if not 1<=a.port<=65535:raise SystemExit('Port must be between 1 and 65535.')
    suggestions=a.suggestions.resolve() if a.suggestions else root/'suggestions'
    if out==root or out==processing:raise SystemExit('Choose a separate annotations subfolder, not the recording root.')
    for capture in root.glob('S*_hand_gestures_*'):
        if out==capture or capture in out.parents:raise SystemExit('Do not save annotations inside a capture session.')
    out.mkdir(parents=True,exist_ok=True);proxy=out/'video_proxies';proxy.mkdir(exist_ok=True);lock=threading.Lock();save_lock=threading.Lock();html=Path(__file__).with_name('study_annotation_tool.html').read_bytes()
    if a.video_set:
        supplied_set=load_video_set(root,a.video_set)
        def get_sessions():return supplied_set
    elif a.single_video:
        video=a.single_video.resolve();info=json.loads(video.with_name('example_info.json').read_text())
        sid=info['session_id']
        if not re.fullmatch(r'S\d+_[LR]_hand_gestures_\d+_\d+',sid):raise SystemExit('Invalid video session identity')
        if info['fps']!=30 or hashlib.sha256(video.read_bytes()).hexdigest()!=info['sha256']:raise SystemExit('Video differs from its supplied timeline/checksum metadata')
        k=info['recorded_camera']
        if type(k) is not int or k not in range(5):raise SystemExit('Invalid recorded camera')
        if info.get('physical_camera')!='C2' or len(info.get('display_to_recorded',[]))!=5 or info['display_to_recorded'][2]!=k:raise SystemExit('The supplied camera mapping does not identify this video as physical C2')
        single={sid:dict(session_id=sid,participant_id=sid.split('_')[0],hand=sid.split('_')[1],frame_count=info['frames'],fps=30,aligned_folder=str(video.parent),single_video=str(video),camera_mapping_verified=True,camera_views=[dict(display_camera=2,recorded_camera=k,label='C2 (center)')])}
        def get_sessions():return single
    else:
        def get_sessions():return discover(root,processing)
    session_cache=get_sessions()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,fmt,*args):pass
        def reply(self,status,data,kind='application/json'):
            if not isinstance(data,bytes):data=json.dumps(data).encode()
            self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('X-Frame-Options','DENY');self.end_headers();self.wfile.write(data)
        def do_GET(self):
            if self.headers.get('Host','') not in {f'127.0.0.1:{a.port}',f'localhost:{a.port}'}:return self.reply(403,{'error':'Localhost access only'})
            u=urlsplit(self.path);q=parse_qs(u.query)
            if u.path=='/':return self.reply(200,Path(__file__).with_name('study_annotation_tool.html').read_bytes(),'text/html; charset=utf-8')
            if u.path=='/sessions':
                listing=[dict(s) for s in get_sessions().values()]
                listing.sort(key=lambda s:(int(s['participant_id'][1:]),s['hand'],s['session_id']))
                for item in listing:item['annotation']=annotation_store.summary(out/item['session_id'],item)
                known={s['session_id'] for s in listing}
                pending=[{'session_id':p.name,'participant_id':p.name.split('_')[0],'hand':p.name.split('_')[1],'reason':'Aligned videos or synchronized previews not yet prepared'} for p in sorted(root.glob('S*_hand_gestures_*')) if re.fullmatch(r'S\d+_[LR]_hand_gestures_\d+_\d+',p.name) and p.name not in known]
                return self.reply(200,{'sessions':listing,'slots':SLOTS,'pending_sessions':pending})
            if u.path=='/annotations':
                try:
                    sid=q['session'][0];session=get_sessions()[sid]
                    version=annotation_store.get_saved(out/sid,session,q.get('version',['latest'])[0])
                    if version is None:return self.reply(404,{'error':'No saved annotations for this hand.'})
                    return self.reply(200,annotation_store.public_payload(version))
                except Exception as e:return self.reply(400,{'error':str(e)})
            if u.path=='/suggestions':
                try:
                    sid=q['session'][0];sessions=get_sessions();session=sessions[sid]
                    path=suggestions/(sid+'.json')
                    if not path.exists():return self.reply(404,{'error':'No candidate holds prepared for this session yet.'})
                    draft=json.loads(path.read_text())
                    if draft['frame_count']!=session['frame_count']:raise ValueError('Suggestion/video frame counts differ')
                    return self.reply(200,draft)
                except Exception as e:return self.reply(400,{'error':str(e)})
            if u.path!='/video':return self.reply(404,{'error':'Not found'})
            try:
                sessions=get_sessions();sid=q['session'][0];k=int(q['camera'][0]);s=sessions[sid]
                if k not in [v['recorded_camera'] for v in s['camera_views']]:raise ValueError('This camera is not included in the supplied recording')
                source=Path(s['aligned_folder'])/f'cam{k}.mkv';folder=proxy/sid
                supplied=root/'video_proxies'/sid/f'cam{k}_480p_v2.mp4'
                if s.get('single_video'):p=Path(s['single_video'])
                elif supplied.exists():p=supplied
                else:
                    with lock:p=prepare_proxy(source,folder,k)
                size=p.stat().st_size;start=0;end=size-1;partial=False
                r=self.headers.get('Range')
                if r:
                    m=re.fullmatch(r'bytes=(\d+)-(\d*)',r)
                    if not m:return self.reply(416,{'error':'Unsupported range'})
                    start=int(m.group(1));end=min(int(m.group(2)) if m.group(2) else end,end);partial=True
                    if start>end:return self.reply(416,{'error':'Range outside file'})
                self.send_response(206 if partial else 200);self.send_header('Content-Type','video/mp4');self.send_header('Accept-Ranges','bytes');self.send_header('Content-Length',str(end-start+1))
                if partial:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
                self.end_headers()
                with p.open('rb') as f:
                    f.seek(start);remaining=end-start+1
                    while remaining:
                        b=f.read(min(262144,remaining))
                        if not b:break
                        self.wfile.write(b);remaining-=len(b)
            except (BrokenPipeError,ConnectionResetError):pass
            except Exception as e:self.reply(400,{'error':str(e)})
        def do_POST(self):
            if self.headers.get('Host','') not in {f'127.0.0.1:{a.port}',f'localhost:{a.port}'}:return self.reply(403,{'error':'Localhost access only'})
            if self.path!='/save':return self.reply(404,{'error':'Not found'})
            try:
                if self.headers.get('Content-Type','').split(';')[0]!='application/json':raise ValueError('JSON request required')
                origin=self.headers.get('Origin')
                if origin and origin not in {f'http://127.0.0.1:{a.port}',f'http://localhost:{a.port}'}:raise ValueError('Local annotation page required')
                size=int(self.headers.get('Content-Length','0'))
                if size<=0 or size>65536:raise ValueError('Payload too large')
                data=json.loads(self.rfile.read(size));sessions=get_sessions();s=sessions[data['session_id']];rows=data['rows']
                if not isinstance(rows,list) or len(rows)>len(SLOTS):raise ValueError('Invalid annotation rows')
                if type(data.get('reference_camera')) is not int or data['reference_camera'] not in range(5):raise ValueError('Invalid reference camera')
                allowed={(x['gesture'],x['repetition']) for x in SLOTS};seen=set();valid=[]
                for r in rows:
                    if type(r.get('gesture')) is not str or type(r.get('repetition')) is not int:raise ValueError('Invalid gesture slot')
                    slot=(r['gesture'],r['repetition'])
                    if slot not in allowed or slot in seen:raise ValueError('Unknown/duplicate protocol slot')
                    seen.add(slot);start=r.get('start_frame');end=r.get('end_frame')
                    if start is None and end is None:continue
                    if type(start) is not int or type(end) is not int or not 0<=start<=end<s['frame_count']:raise ValueError(f'Invalid/incomplete frame range: {slot}')
                    if r.get('suggested') and r.get('reviewed') is not True:raise ValueError(f'Review suggested hold before saving: {slot}')
                    valid.append({'participant_id':s['participant_id'],'hand':s['hand'],'session_id':s['session_id'],'gesture':r['gesture'],'repetition':r['repetition'],'start_frame':start,'end_frame':end,'start_time_s':start/30,'end_time_s':end/30,'number_of_frames':end-start+1,'reference_recorded_camera':int(data['reference_camera']),'annotation_source':'candidate interval manually reviewed' if r.get('suggested') else 'manual synchronized-video review','suggestion_id':r.get('suggestion_id',''),'manually_reviewed':True,'fps':30})
                ordered=sorted(valid,key=lambda r:r['start_frame'])
                for x,y in zip(ordered,ordered[1:]):
                    if y['start_frame']<=x['end_frame']:raise ValueError('Overlapping windows; adjust boundaries before saving')
                if not valid:raise ValueError('No complete windows to save')
                with save_lock:
                    previous=annotation_store.same_as_latest(out/s['session_id'],s,valid,bool(data.get('views_reviewed')))
                    if previous:
                        return self.reply(200,{'path':previous['path'],'windows':previous['windows'],'complete':previous['windows']==33,'already_saved':True,'annotation':annotation_store.summary(out/s['session_id'],s)})
                    latest=annotation_store.get_saved(out/s['session_id'],s)
                    if 'base_version' not in data or data['base_version']!=(latest['version'] if latest else None):
                        return self.reply(409,{'error':'Another saved version exists. Your browser draft is preserved. Load the latest saved CSV and reconcile edits before saving.'})
                    folder=out/s['session_id'];folder.mkdir(exist_ok=True);stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')+'_'+uuid.uuid4().hex[:6];p=folder/f'gesture_windows_{stamp}.csv'
                    pending=p.with_suffix('.pending')
                    with pending.open('x',newline='') as f:
                        w=csv.DictWriter(f,fieldnames=list(valid[0]));w.writeheader();w.writerows(valid);f.flush();os.fsync(f.fileno())
                    meta={'session_id':s['session_id'],'shared_frames':s['frame_count'],'protocol_slots':33,'complete_windows':len(valid),'all_slots_annotated':len(valid)==33,'other_views_reviewed':bool(data.get('views_reviewed')),'source_aligned_folder':s['aligned_folder'],'csv_sha256':hashlib.sha256(pending.read_bytes()).hexdigest(),'saved_utc':datetime.now(timezone.utc).isoformat(),'clinical_validation':False,'reviewed_assisted_windows':sum(r.get('suggested',False) for r in rows if r.get('start_frame') is not None and r.get('end_frame') is not None)}
                    p.with_suffix('.json').write_text(json.dumps(meta,indent=2));pending.rename(p);return self.reply(200,{'path':str(p),'windows':len(valid),'complete':len(valid)==33,'already_saved':False,'annotation':annotation_store.summary(out/s['session_id'],s)})
            except Exception as e:return self.reply(400,{'error':str(e)})
    server=ThreadingHTTPServer(('127.0.0.1',a.port),Handler)
    print(f'{len(session_cache)} sessions available. Saved CSVs reload; 29/29 hand windows marks a completed hand.',flush=True);print(f'Annotation tool: http://127.0.0.1:{a.port}',flush=True);print(f'Versioned CSVs: {out}',flush=True)
    server.serve_forever()
if __name__=='__main__':main()
