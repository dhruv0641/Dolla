import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from flowx_os.assets.storage import ManagedAssetStore
from flowx_os.assets.probing import MediaProbeService, MediaProbeError, ProbePolicy, parse_probe, _run


class MediaProbeTests(unittest.TestCase):
    def test_invalid_metadata_fails_closed(self):
        for duration in ('NaN', 'Infinity', '0', '-1', None):
            with self.subTest(duration=duration), self.assertRaises(MediaProbeError):
                parse_probe(json.dumps({'format':{'duration':duration},'streams':[]}).encode())
        with self.assertRaises(MediaProbeError):
            parse_probe(b'not-json')

    def test_rotation_and_pixel_aspect_are_respected(self):
        raw={'format':{'duration':'2'},'streams':[{'codec_type':'video','codec_name':'h264','width':720,'height':480,'sample_aspect_ratio':'4:3','side_data_list':[{'rotation':90}]}]}
        _, streams=parse_probe(json.dumps(raw).encode())
        self.assertEqual((streams[0].width,streams[0].height),(480,720))
        self.assertAlmostEqual(streams[0].display_aspect_ratio,0.5)

    def test_subprocess_timeout_and_output_cap(self):
        with self.assertRaisesRegex(MediaProbeError,'TIMEOUT'):
            _run([sys.executable,'-c','import time; time.sleep(10)'],timeout=.1,output_limit=1024)
        with self.assertRaisesRegex(MediaProbeError,'OUTPUT_LIMIT'):
            _run([sys.executable,'-c','import sys; sys.stderr.write("x"*20000)'],timeout=5,output_limit=1024)
        with self.assertRaisesRegex(MediaProbeError,'TOOL_FAILED'):
            _run([sys.executable,'-c','import sys; sys.exit(2)'],timeout=5,output_limit=1024)

    def test_policy_rejects_nonfinite_limits(self):
        for value in (float('nan'),float('inf'),-1,True):
            with self.assertRaises(ValueError):
                ProbePolicy(expected_duration_seconds=value)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'FFmpeg tools unavailable')
    def test_real_video_audio_decode_and_policy_failures(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); source=root/'fixture.mp4'
            subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','color=c=blue:s=160x90:r=10','-f','lavfi','-i','sine=frequency=440:sample_rate=44100','-t','0.5','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(source)],check=True,timeout=20)
            asset=ManagedAssetStore(root).store(asset_id=uuid4(),source_path=source,mime_type='video/mp4')
            service=MediaProbeService(root)
            report=service.inspect(asset,ProbePolicy(expected_duration_seconds=.5,expected_aspect_ratio=16/9,require_audio=True))
            self.assertTrue(report.passed,report)
            self.assertTrue(report.to_metadata()['media_probe']['decode_verified'])
            failed=service.inspect(asset,ProbePolicy(expected_duration_seconds=10,expected_aspect_ratio=1,max_width=100,video_codecs=('vp9',),audio_codecs=('opus',)))
            self.assertEqual(set(failed.violations),{'DURATION_MISMATCH','ASPECT_RATIO_MISMATCH','DIMENSIONS_EXCEEDED','VIDEO_CODEC_UNSUPPORTED','AUDIO_CODEC_UNSUPPORTED'})
            source.write_bytes(source.read_bytes()[:len(source.read_bytes())//2])
            corrupt=ManagedAssetStore(root).store(asset_id=uuid4(),source_path=source,mime_type='video/mp4')
            with self.assertRaises(MediaProbeError):
                service.inspect(corrupt,ProbePolicy(require_audio=True))
            asset.path.write_bytes(b'changed')
            with self.assertRaisesRegex(MediaProbeError,'INTEGRITY_MISMATCH'):
                service.inspect(asset)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'FFmpeg tools unavailable')
    def test_real_audio_and_playlist_refusal(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); source=root/'fixture.wav'
            subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','sine=frequency=440:sample_rate=44100','-t','0.2',str(source)],check=True,timeout=20)
            store=ManagedAssetStore(root)
            asset=store.store(asset_id=uuid4(),source_path=source,mime_type='audio/wav')
            service=MediaProbeService(root)
            self.assertTrue(service.inspect(asset,ProbePolicy(require_video=False,require_audio=True)).passed)
            self.assertIn('VIDEO_REQUIRED',service.inspect(asset).violations)
            source.write_bytes(b'#EXTM3U\nhttp://localhost/private\n')
            text_asset=store.store(asset_id=uuid4(),source_path=source,mime_type='text/plain')
            with patch('flowx_os.assets.probing._run') as runner:
                with self.assertRaisesRegex(MediaProbeError,'TYPE_UNSUPPORTED'):
                    service.inspect(text_asset)
                runner.assert_not_called()

    def test_forged_path_and_decode_failure(self):
        from dataclasses import replace
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); source=root/'fixture.mp4'
            source.write_bytes(b'\0\0\0\x18ftyp'+b'0'*32)
            asset=ManagedAssetStore(root).store(asset_id=uuid4(),source_path=source,mime_type='video/mp4')
            service=MediaProbeService(root)
            with self.assertRaisesRegex(MediaProbeError,'PATH_UNSAFE'):
                service.inspect(replace(asset,path=source))
            metadata=json.dumps({'format':{'duration':'1'},'streams':[{'codec_type':'video','codec_name':'h264','width':160,'height':90}]}).encode()
            with patch('flowx_os.assets.probing._run',return_value=metadata) as runner:
                report=service.inspect(asset,ProbePolicy(max_width=100))
                self.assertFalse(report.decode_verified)
                self.assertEqual(runner.call_count,1)
            with patch('flowx_os.assets.probing._run',side_effect=[metadata,b'frame=0\nout_time_us=0\nprogress=end\n']):
                with self.assertRaisesRegex(MediaProbeError,'DECODE_EMPTY'):
                    service.inspect(asset)
            long_metadata=json.loads(metadata)
            long_metadata['format']['duration']='8'
            with patch('flowx_os.assets.probing._run',side_effect=[json.dumps(long_metadata).encode(),b'frame=1\nout_time_us=1000000\nprogress=end\n']):
                report=service.inspect(asset,ProbePolicy(expected_duration_seconds=8))
                self.assertFalse(report.passed)
                self.assertEqual(report.decoded_duration_seconds,1)
                self.assertIn('DECODE_DURATION_MISMATCH',report.violations)
                self.assertIn('DECODE_EXPECTED_DURATION_MISMATCH',report.violations)
            with patch('flowx_os.assets.probing._run',side_effect=[metadata,MediaProbeError('MEDIA_TOOL_FAILED')]):
                with self.assertRaisesRegex(MediaProbeError,'TOOL_FAILED'):
                    service.inspect(asset)

if __name__=='__main__':
    unittest.main()
