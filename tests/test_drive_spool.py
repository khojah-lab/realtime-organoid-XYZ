import contextlib
import datetime as dt
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock,patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from services import drive_spool as s

class SpoolTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        for key,value in [('SPOOL',self.root/'drive'),('DB',self.root/'drive.sqlite3')]:
            p=patch.object(s,key,value);p.start();self.addCleanup(p.stop)
        s.control()
        self.taken=s.LA_TZ.localize(dt.datetime(2026,11,14,12,0))
        self.name='top_right_20261114_120000.jpg'

    def enabled(self):
        s.request_enabled(True);s.activate(lambda day: None)

    def save(self,scan=None):
        scan=scan or s.begin_scan();s.capture(scan,self.name,'top_right',self.taken,b'original jpeg')
        return s.SPOOL/scan/self.name

    def test_enable_prepares_only_and_never_imports_history(self):
        (self.root/'images').mkdir();(self.root/'images'/'old.jpg').write_bytes(b'old')
        prepare=MagicMock();s.request_enabled(True)
        self.assertFalse(s.control()['enabled']);s.activate(prepare)
        prepare.assert_called_once();self.assertTrue(s.control()['enabled'])
        self.assertEqual(s.status()['total'],0)

    def test_enable_during_scan_applies_to_next_full_scan(self):
        old=s.begin_scan();self.enabled()
        self.assertFalse(s.capture(old,self.name,'top_right',self.taken,b'jpeg'))
        new=s.begin_scan();p=self.save(new);self.assertTrue(p.exists())
        s.request_enabled(False)
        self.assertTrue(s.capture(new,'top_left_20261114_120001.jpg','top_left',self.taken,b'jpeg'))
        self.assertFalse(s.capture(s.begin_scan(),self.name,'top_right',self.taken,b'jpeg'))

    def test_off_drains_existing_and_cleans_only_drive_after_ten_minutes(self):
        self.enabled();p=self.save();aws=self.root/'aws.jpg';aws.write_bytes(b'original jpeg')
        s.request_enabled(False)
        with patch.object(s.time,'time',return_value=1000):s.upload_one(lambda *a:'id')
        s.cleanup(now=1599);self.assertTrue(p.exists())
        s.cleanup(now=1600);self.assertFalse(p.exists());self.assertTrue(aws.exists())

    def test_failed_upload_persists_and_retry_then_cleanup(self):
        self.enabled();p=self.save()
        with patch.object(s.time,'time',return_value=1000):s.upload_one(MagicMock(side_effect=OSError('offline')))
        s.cleanup(now=999999);self.assertTrue(p.exists())
        with patch.object(s.time,'time',return_value=1059):self.assertFalse(s.upload_one(lambda *a:'id'))
        with patch.object(s.time,'time',return_value=1060):self.assertTrue(s.upload_one(lambda *a:'id'))
        self.assertEqual(s.status()['pending'],0)

    def test_pause_does_not_change_acceptance_or_delete_unverified(self):
        self.enabled();p=self.save();s.request_paused(True)
        self.assertTrue(s.control()['enabled']);self.assertFalse(s.upload_one(lambda *a:'id'))
        s.cleanup(now=10**12);self.assertTrue(p.exists())
        s.request_paused(False);self.assertTrue(s.upload_one(lambda *a:'id'))

    def test_disable_during_remote_validation_cannot_reenable(self):
        s.request_enabled(True)
        s.activate(lambda day:s.request_enabled(False))
        self.assertFalse(s.control()['enabled'])

    def test_authorization_failure_blocks_new_scans(self):
        s.request_enabled(True);s.activate(MagicMock(side_effect=RuntimeError('wrong owner')))
        self.assertFalse(s.control()['enabled']);self.assertIn('wrong owner',s.status()['error'])
        self.assertFalse(s.capture(s.begin_scan(),self.name,'top_right',self.taken,b'jpeg'))

    def test_cross_midnight_routes_by_capture_day(self):
        self.enabled();scan=s.begin_scan()
        s.capture(scan,self.name,'top_right',self.taken,b'jpeg')
        tomorrow=self.taken+dt.timedelta(days=1)
        s.capture(scan,'top_left_20261115_000000.jpg','top_left',tomorrow,b'jpeg')
        seen=[]
        while s.upload_one(lambda path,row:seen.append(row['day']) or 'id'):pass
        self.assertEqual(set(seen),{'2026-11-14','2026-11-15'})

    def test_changed_file_and_path_escape_block_deletion(self):
        self.enabled();p=self.save();s.upload_one(lambda *a:'id');p.write_bytes(b'changed')
        s.cleanup(now=10**12);self.assertTrue(p.exists());self.assertTrue(s.status()['errors'])
        with self.assertRaises(ValueError):s.safe_path('../aws.jpg')

    def test_recover_only_registered_complete_copies(self):
        self.enabled();p=self.save()
        with s.connect() as db:db.execute('UPDATE photos SET ready=0')
        temp=p.with_suffix('.part');p.rename(temp)
        random=s.SPOOL/'unregistered.jpg';random.write_bytes(b'old')
        s.recover();self.assertTrue(p.exists());self.assertFalse(temp.exists())
        self.assertEqual(s.status()['total'],1);self.assertTrue(random.exists())

    def test_web_controls_validated_and_panel_rendered(self):
        from flask import Flask,render_template
        spec=importlib.util.spec_from_file_location('drive_routes_test',ROOT/'routes/drive_storage_routes.py')
        mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
        app=Flask(__name__,template_folder=str(ROOT/'templates'));app.secret_key='test';app.register_blueprint(mod.drive_storage_bp)
        client=app.test_client()
        self.assertEqual(client.post('/drive-storage/control',json={'enabled':True}).status_code,403)
        token=client.get('/drive-storage/status').json['csrf'];headers={'X-Drive-CSRF':token}
        with patch.object(mod.storage_manager,'set_mode') as choose:
            self.assertEqual(client.post('/drive-storage/control',json={'mode':'both'},headers=headers).status_code,200)
            choose.assert_called_once_with('both')
        self.assertEqual(client.post('/drive-storage/control',json={'paused':'false'},headers=headers).status_code,400)
        headers['Origin']='https://other.example'
        self.assertEqual(client.post('/drive-storage/control',json={'enabled':False},headers=headers).status_code,403)
        with app.test_request_context('/'):
            self.assertIn('Image storage',render_template('main.html'))

    def test_drive_queue_survives_independent_aws_failure(self):
        from services import storage_manager as manager
        roots={k:self.root/k for k in ('original','aws','drive')}
        with patch.object(manager,'DB',self.root/'new.db'),patch.object(manager,'ROOTS',roots),patch.object(manager,'space',return_value={'critical':False}):
            with manager.connect() as db: db.execute("UPDATE settings SET mode='both'")
            sid=manager.begin_scan()
            manager.capture(sid,self.name,self.taken,b'jpeg')
            original_publish=manager.publish
            def fail_aws(path,data):
                if path.parent==roots['aws']: raise OSError('AWS staging failed')
                original_publish(path,data)
            with patch.object(manager,'publish',side_effect=fail_aws):
                manager.process_one('aws',lambda *a:'aws')
                manager.process_one('drive',lambda *a:'drive')
            with manager.connect() as db:
                jobs={r['provider']:r['verified'] for r in db.execute('SELECT * FROM jobs')}
            self.assertIsNone(jobs['aws'])
            self.assertIsNotNone(jobs['drive'])
            self.assertTrue((roots['original']/self.name).exists())

if __name__=='__main__':unittest.main()
