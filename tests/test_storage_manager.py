import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
from services import storage_manager as s

class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name)
        for key,val in [('DB',root/'state.db'),('ROOTS',{k:root/k for k in ('original','aws','drive')})]:
            p=patch.object(s,key,val);p.start();self.addCleanup(p.stop)
        p=patch('services.drive_spool.control',return_value={'enabled':False});p.start();self.addCleanup(p.stop)
        p=patch.object(s,'space',return_value={'critical':False});p.start();self.addCleanup(p.stop)
        self.taken=dt.datetime.now(dt.timezone.utc)-dt.timedelta(days=8)
        self.name='top_right_20261114_120000.jpg'

    def capture(self,mode='both'):
        with s.connect() as db: db.execute('UPDATE settings SET mode=?',(mode,))
        sid=s.begin_scan();s.capture(sid,self.name,self.taken,b'full original');s.finish_scan(sid)
        return sid

    def test_scan_snapshot(self):
        sid=s.begin_scan()
        with s.connect() as db: db.execute("UPDATE settings SET mode='both'")
        s.capture(sid,self.name,self.taken,b'full original')
        with s.connect() as db:
            self.assertEqual([r[0] for r in db.execute('SELECT provider FROM jobs')],['aws'])

    def test_required_success_before_original_cleanup(self):
        self.capture();s.process_one('aws',lambda p,r:'key');s.cleanup('aws')
        self.assertFalse(s.safe('aws',self.name).exists())
        self.assertTrue(s.safe('original',self.name).exists())
        s.process_one('drive',lambda p,r:'id');s.cleanup('drive')
        self.assertFalse(s.safe('original',self.name).exists())
        self.assertTrue(s.safe('drive',self.name).exists())
        s.cleanup('drive',s.time.time()+601)
        self.assertFalse(s.safe('drive',self.name).exists())

    def test_retention_and_legacy_preservation(self):
        self.taken=dt.datetime.now(dt.timezone.utc);self.capture('aws')
        old=s.ROOTS['original']/'old.jpg';old.write_bytes(b'legacy')
        s.process_one('aws',lambda p,r:'key');s.cleanup('aws')
        self.assertTrue(s.safe('original',self.name).exists())
        s.cleanup('aws',self.taken.timestamp()+s.RETENTION+1)
        self.assertFalse(s.safe('original',self.name).exists());self.assertTrue(old.exists())

    def test_failure_retry_pause_and_restart(self):
        self.capture('drive');s.pause('drive',True)
        self.assertFalse(s.process_one('drive',lambda p,r:'id'))
        s.pause('drive',False)
        def fail(p,r): raise RuntimeError('offline')
        s.process_one('drive',fail);s.cleanup('drive')
        self.assertTrue(s.safe('original',self.name).exists())
        self.assertTrue(s.safe('drive',self.name).exists())
        self.assertFalse(s.process_one('drive',lambda p,r:'id'))
        with s.connect() as db: db.execute('UPDATE jobs SET next_try=0')
        self.assertTrue(s.process_one('drive',lambda p,r:'id'))

    def test_waive_only_with_other_verified_backup(self):
        self.capture();self.assertEqual(s.waive_preview('aws')['count'],0)
        s.process_one('drive',lambda p,r:'id')
        preview=s.waive_preview('aws');self.assertEqual(preview['count'],1)
        with self.assertRaises(ValueError): s.waive('aws','stale-token')
        s.waive('aws',preview['token']);s.cleanup('drive')
        self.assertFalse(s.safe('original',self.name).exists())
        self.assertFalse(s.process_one('aws',lambda p,r:'key'))

    def test_changed_original_is_retained(self):
        self.capture('aws');s.process_one('aws',lambda p,r:'key')
        s.safe('original',self.name).write_bytes(b'changed')
        s.cleanup('aws');self.assertTrue(s.safe('original',self.name).exists())

    def test_critical_space_blocks_new_scan(self):
        with patch.object(s,'space',return_value={'critical':True}):
            with self.assertRaises(RuntimeError): s.begin_scan()

    def test_drive_only_never_creates_aws_job(self):
        self.capture('drive');self.assertFalse(s.process_one('aws',lambda p,r:'key'))
        self.assertFalse(s.ROOTS['aws'].exists())

    def test_crash_after_original_publication_recovers(self):
        self.capture('aws')
        with s.connect() as db: db.execute('UPDATE originals SET ready=0')
        s.process_one('aws',lambda p,r:'key')
        with s.connect() as db: self.assertEqual(db.execute('SELECT ready FROM originals').fetchone()[0],1)

    def test_s3_verification_reads_content_not_metadata(self):
        self.capture('aws')
        client=MagicMock();client.get_object.return_value={'Body':MagicMock()}
        client.get_object.return_value['Body'].read.side_effect=[b'wrong bytes',b'']
        with patch('services.cloud_storage.get_client',return_value=client): s.process_one('aws')
        with s.connect() as db: self.assertIsNone(db.execute('SELECT verified FROM jobs').fetchone()[0])
        self.assertTrue(s.safe('original',self.name).exists())

if __name__=='__main__': unittest.main()
