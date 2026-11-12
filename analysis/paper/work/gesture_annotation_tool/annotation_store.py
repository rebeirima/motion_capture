"""Read versioned gesture CSVs without changing annotations or inferring labels."""
from pathlib import Path
import csv,json,hashlib
WRIST={'wrist_left_to_right','wrist_flip'}
PROTOCOL=['baseline','open']+[f'finger_{i}' for i in range(1,5)]+[f'thumb_touch_{i}' for i in range(1,5)]+['thumb','L','box','claw','fist','wrist_left_to_right','wrist_flip']
SLOTS=[{'gesture':g,'repetition':r} for g in PROTOCOL for r in range(1,2 if g=='baseline' else 3)]
HAND={(s['gesture'],s['repetition']) for s in SLOTS if s['gesture'] not in WRIST}
ALL={(s['gesture'],s['repetition']) for s in SLOTS}
def load_version(path,session):
 path=Path(path);meta_path=path.with_suffix('.json');meta=json.loads(meta_path.read_text()) if meta_path.exists() else {}
 if meta.get('csv_sha256') and hashlib.sha256(path.read_bytes()).hexdigest()!=meta['csv_sha256']:raise ValueError('CSV differs from its saved hash')
 with path.open(newline='') as f:raw=list(csv.DictReader(f))
 if not raw:raise ValueError('No saved windows')
 seen=set();typed=[]
 for r in raw:
  if r['session_id']!=session['session_id'] or r['participant_id']!=session['participant_id'] or r['hand']!=session['hand']:raise ValueError('Session/hand identity mismatch')
  g=r['gesture'];rep=int(r['repetition']);key=(g,rep);start=int(r['start_frame']);end=int(r['end_frame'])
  if key not in ALL or key in seen:raise ValueError('Unknown or repeated gesture slot')
  if not 0<=start<=end<session['frame_count']:raise ValueError('Saved boundary exceeds this video')
  seen.add(key);x=dict(r,repetition=rep,start_frame=start,end_frame=end,reference_recorded_camera=int(r['reference_recorded_camera']));typed.append(x)
 ordered=sorted(typed,key=lambda r:r['start_frame'])
 if any(b['start_frame']<=a['end_frame'] for a,b in zip(ordered,ordered[1:])):raise ValueError('Saved windows overlap')
 cameras={r['reference_recorded_camera'] for r in typed}
 if len(cameras)!=1 or not cameras<=set(range(5)):raise ValueError('Invalid reference camera')
 byslot={(r['gesture'],r['repetition']):r for r in typed};rows=[]
 for slot in SLOTS:
  r=byslot.get((slot['gesture'],slot['repetition']));out=dict(slot,start_frame=None,end_frame=None)
  if r:
   assisted=r.get('annotation_source','').startswith('candidate');out.update(start_frame=r['start_frame'],end_frame=r['end_frame'],suggested=assisted,reviewed=True,suggestion_id=r.get('suggestion_id',''))
  rows.append(out)
 return {'rows':rows,'reference_camera':next(iter(cameras)),'views_reviewed':bool(meta.get('other_views_reviewed',False)),'path':str(path),'version':path.name,'saved_utc':meta.get('saved_utc'),'windows':len(typed),'hand_windows':len(seen&HAND),'hand_complete':HAND<=seen,'wrist_windows':len(seen-HAND),'csv_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'typed_csv_rows':typed}
def public_payload(v):return {k:value for k,value in v.items() if k!='typed_csv_rows'}
def versions(folder,session):
 valid=[];invalid=[]
 for path in sorted(Path(folder).glob('gesture_windows_*.csv')):
  try:valid.append(load_version(path,session))
  except (OSError,ValueError,KeyError,TypeError) as e:invalid.append({'version':path.name,'error':str(e)})
 return valid,invalid
def summary(folder,session):
 valid,invalid=versions(folder,session)
 if not valid:return {'state':'invalid' if invalid else 'not_started','hand_windows':0,'hand_complete':False,'windows':0,'wrist_windows':0,'version_count':0,'invalid_versions':invalid,'latest_version':None,'most_complete_version':None,'versions':[]}
 latest=valid[-1];best=max(valid,key=lambda v:(v['hand_windows'],v['windows'],v['version']))
 return {'state':'complete' if latest['hand_complete'] else 'partial','hand_windows':latest['hand_windows'],'hand_complete':latest['hand_complete'],'windows':latest['windows'],'wrist_windows':latest['wrist_windows'],'version_count':len(valid),'invalid_versions':invalid,'latest_version':latest['version'],'most_complete_version':best['version'],'most_complete_hand_windows':best['hand_windows'],'saved_utc':latest['saved_utc'],'versions':[{k:v[k] for k in ['version','hand_windows','windows','hand_complete','saved_utc']} for v in valid]}
def get_saved(folder,session,version=None):
 valid,invalid=versions(folder,session)
 if not valid:return None
 if version=='most_complete':return max(valid,key=lambda v:(v['hand_windows'],v['windows'],v['version']))
 if version in [None,'latest']:return valid[-1]
 for v in valid:
  if v['version']==version:return v
 raise ValueError('Unknown saved version')
def signature(rows,views_reviewed=False):
 fields=['gesture','repetition','start_frame','end_frame','reference_recorded_camera','annotation_source','suggestion_id','manually_reviewed']
 def val(row,k):
  if k=='manually_reviewed':return str(row.get(k,True)).lower()=='true'
  if k=='annotation_source':return row.get(k,'manual synchronized-video review')
  return row.get(k,'')
 return (bool(views_reviewed),tuple(sorted(tuple(val(r,k) for k in fields) for r in rows)))
def same_as_latest(folder,session,rows,views_reviewed):
 v=get_saved(folder,session)
 if v and signature(v['typed_csv_rows'],v['views_reviewed'])==signature(rows,views_reviewed):return v
 return None
