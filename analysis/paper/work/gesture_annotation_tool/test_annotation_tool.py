"""Isolated checks using synthetic sessions; no study data or network required."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import annotation_store
import study_annotation_server as app

SID = 'S999_L_hand_gestures_20000101_000000'


class AnnotationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root/'annotation_sessions.json').write_text(json.dumps({'sessions': [
            {'session_id': SID, 'participant_id': 'S999', 'hand': 'L', 'frame_count': 1000, 'fps': 30}]}))
        videos = self.root/'video_proxies'/SID
        videos.mkdir(parents=True)
        for k in range(5):
            (videos/f'cam{k}_480p_v2.mp4').write_bytes(bytes(range(256))*2)
        captured = {}
        class FakeServer:
            def __init__(self, address, handler):
                captured.update(address=address, handler=handler)
            def serve_forever(self):
                pass
        with patch.object(app, 'ThreadingHTTPServer', FakeServer), patch.object(sys, 'argv', [
            'server', '--root', str(self.root), '--port', '8765']), contextlib.redirect_stdout(io.StringIO()):
            app.main()
        self.handler = captured['handler']
        self.assertEqual(captured['address'], ('127.0.0.1', 8765))
        self.out = self.root/'annotations'

    def request(self, path, data=None, headers=None):
        h = object.__new__(self.handler)
        h.path = path
        h.headers = {'Host': '127.0.0.1:8765', **(headers or {})}
        result = {'headers': {}}
        h.reply = lambda status, payload, kind='application/json': result.update(status=status, data=payload)
        h.send_response = lambda status: result.update(status=status)
        h.send_header = lambda name, value: result['headers'].update({name: value})
        h.end_headers = lambda: None
        h.wfile = io.BytesIO()
        if data is None:
            h.do_GET()
        else:
            payload = json.dumps(data).encode()
            h.rfile = io.BytesIO(payload)
            h.headers.update({'Content-Length': str(len(payload)), 'Content-Type': 'application/json'})
            h.headers.setdefault('Origin', 'http://127.0.0.1:8765')
            h.do_POST()
        result['body'] = h.wfile.getvalue()
        return result

    def payload(self):
        rows = []
        for i, slot in enumerate(s for s in app.SLOTS if s['gesture'] not in annotation_store.WRIST):
            rows.append(dict(slot, start_frame=i*20, end_frame=i*20+9))
        return dict(session_id=SID, rows=rows, reference_camera=2, views_reviewed=True, base_version=None)

    def test_preview_manifest_without_capture_files(self):
        sessions = self.request('/sessions')['data']['sessions']
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]['frame_count'], 1000)
        self.assertEqual(sessions[0]['annotation']['state'], 'not_started')

    def test_session_mapping_composes_physical_and_recorded_order(self):
        metadata=self.root/SID/'metadata'
        metadata.mkdir(parents=True)
        (metadata/'camera_mapping.txt').write_text('1,0,2,4,3\n')
        result=self.request('/sessions')['data']['sessions'][0]
        self.assertEqual([v['recorded_camera'] for v in result['camera_views']], [3,0,4,2,1])
        self.assertEqual(result['camera_views'][2]['label'], 'C2 (center)')
        self.assertEqual(result['camera_views'][2]['recorded_camera'], 4)
        self.assertTrue(result['camera_mapping_verified'])

    def test_absent_mapping_never_guesses_center(self):
        result=self.request('/sessions')['data']['sessions'][0]
        self.assertFalse(result['camera_mapping_verified'])
        self.assertTrue(all(v['display_camera'] is None for v in result['camera_views']))

    def test_refresh_discovers_new_folders_and_lists_raw_only_sessions(self):
        sid='S998_R_hand_gestures_20000101_000000'
        (self.root/sid/'raw').mkdir(parents=True)
        first=self.request('/sessions')['data']
        self.assertEqual(first['pending_sessions'][0]['session_id'],sid)
        videos=self.root/'video_proxies'/sid;videos.mkdir(parents=True)
        for k in range(5):(videos/f'cam{k}_480p_v2.mp4').write_bytes(b'synthetic')
        path=self.root/'annotation_sessions.json';d=json.loads(path.read_text())
        d['sessions'].append(dict(session_id=sid,participant_id='S998',hand='R',frame_count=1000,fps=30,display_to_recorded=[1,4,2,0,3]));path.write_text(json.dumps(d))
        second=self.request('/sessions')['data']
        self.assertEqual(len(second['sessions']),2)
        self.assertEqual(second['pending_sessions'],[])
        self.assertEqual(next(s for s in second['sessions'] if s['session_id']==sid)['camera_views'][2]['recorded_camera'],2)

    def test_save_restore_and_identical_resave(self):
        data = self.payload()
        saved = self.request('/save', data)
        self.assertEqual(saved['status'], 200)
        self.assertTrue(saved['data']['annotation']['hand_complete'])
        self.assertEqual(saved['data']['annotation']['hand_windows'], 29)
        restored = self.request('/annotations?session='+SID)['data']
        self.assertEqual(len(restored['rows']), 33)
        self.assertEqual(restored['reference_camera'], 2)
        again = self.request('/save', data)
        self.assertTrue(again['data']['already_saved'])
        self.assertEqual(len(list((self.out/SID).glob('*.csv'))), 1)
        self.assertFalse(list((self.out/SID).glob('*.pending')))

    def test_conflicting_browser_is_not_saved_and_versions_survive(self):
        data = self.payload()
        saved = self.request('/save', data)['data']
        data['rows'][0]['start_frame'] += 1
        self.assertEqual(self.request('/save', data)['status'], 409)
        data['base_version'] = saved['annotation']['latest_version']
        self.assertEqual(self.request('/save', data)['status'], 200)
        self.assertEqual(len(list((self.out/SID).glob('*.csv'))), 2)
        old = self.request('/annotations?session='+SID+'&version='+saved['annotation']['latest_version'])
        self.assertEqual(old['data']['rows'][0]['start_frame'], 0)

    def test_overlap_out_of_bounds_and_duplicate_are_rejected(self):
        for mutation in ('overlap', 'bounds', 'duplicate'):
            data = self.payload()
            if mutation == 'overlap': data['rows'][1]['start_frame'] = 0
            elif mutation == 'bounds': data['rows'][-1]['end_frame'] = 1000
            else: data['rows'].append(dict(data['rows'][0]))
            self.assertEqual(self.request('/save', data)['status'], 400)
        self.assertEqual(len(list(self.out.glob('S*/*.csv'))), 0)

    def test_candidates_require_manual_review(self):
        data = self.payload()
        data['rows'][0].update(suggested=True, reviewed=False)
        self.assertEqual(self.request('/save', data)['status'], 400)
        data['rows'][0]['reviewed'] = True
        self.assertEqual(self.request('/save', data)['status'], 200)

    def test_localhost_origin_and_host_checks(self):
        self.assertEqual(self.request('/sessions', headers={'Host': 'remote.example'})['status'], 403)
        self.assertEqual(self.request('/save', self.payload(), {'Origin': 'https://remote.example'})['status'], 400)
        result = self.request('/save', self.payload(), {'Host': 'localhost:8765', 'Origin': 'http://localhost:8765'})
        self.assertEqual(result['status'], 200)

    def test_camera_range_streaming_and_invalid_requests(self):
        response = self.request('/video?session='+SID+'&camera=2', headers={'Range': 'bytes=10-19'})
        self.assertEqual(response['status'], 206)
        self.assertEqual(response['headers']['Content-Range'], 'bytes 10-19/512')
        self.assertEqual(response['body'], bytes(range(10,20)))
        self.assertEqual(self.request('/video?session='+SID+'&camera=5')['status'], 400)
        self.assertEqual(self.request('/video?session=../../etc&camera=0')['status'], 400)

    def test_corrupt_saved_csv_is_flagged(self):
        self.request('/save', self.payload())
        path = next((self.out/SID).glob('*.csv'))
        path.write_text(path.read_text()+'corrupt')
        state = self.request('/sessions')['data']['sessions'][0]['annotation']
        self.assertEqual(state['state'], 'invalid')
        self.assertFalse(state['hand_complete'])


if __name__ == '__main__':
    unittest.main()
