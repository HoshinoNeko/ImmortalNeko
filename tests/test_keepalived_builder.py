import hashlib
import io
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from scripts import build_test_keepalived as builder


class KeepalivedBuilderTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve();self.archive=self.root/'fixture.tar.gz'
        with tarfile.open(self.archive,'w:gz') as archive:
            data=b'#!/bin/sh\nexit 0\n'
            member=tarfile.TarInfo(f'keepalived-{builder.VERSION}/configure')
            member.size=len(data);member.mode=0o755;archive.addfile(member,io.BytesIO(data))
        self.digest=hashlib.sha256(self.archive.read_bytes()).hexdigest()
        self.calls=[];self.compile_fails=False;self.make_binary=True

    def runner(self,args,**kwargs):
        self.assertTrue(kwargs['check']);self.calls.append(args)
        if args[0]=='curl':
            shutil.copyfile(self.archive,args[-1])
        elif args[0]=='./configure':
            self.assertIn('--prefix='+str(self.root/'.work/tools'/f'keepalived-{builder.VERSION}'),args)
        elif args==['make','-j2']:
            if self.compile_fails:raise subprocess.CalledProcessError(2,args)
            if self.make_binary:
                binary=kwargs['cwd']/'keepalived/keepalived'
                binary.parent.mkdir();binary.write_bytes(b'fixture executable\n');binary.chmod(0o751)
        else:
            self.fail('Unexpected build/install command: '+repr(args))
        return subprocess.CompletedProcess(args,0)

    def build(self):
        with patch.object(builder,'SHA256',self.digest),patch.object(builder.subprocess,'run',side_effect=self.runner):
            return builder.build(self.root)

    def test_stages_only_built_binary_and_preserves_execute_permissions(self):
        target=self.build()
        self.assertEqual(target,self.root/'.work/tools'/f'keepalived-{builder.VERSION}'/'sbin/keepalived')
        self.assertEqual(target.read_bytes(),b'fixture executable\n')
        self.assertEqual(target.stat().st_mode & 0o777,0o751)
        self.assertEqual([args[0] for args in self.calls],['curl','./configure','make'])
        self.assertEqual(list(target.parent.parent.rglob('*')),[target.parent,target])

    def test_failed_compilation_does_not_publish_a_binary(self):
        self.compile_fails=True
        with self.assertRaises(subprocess.CalledProcessError):self.build()
        self.assertFalse((self.root/'.work/tools').exists())

    def test_missing_built_executable_is_reported_before_staging(self):
        self.make_binary=False
        with self.assertRaisesRegex(SystemExit,'did not produce an executable'):self.build()
        self.assertFalse((self.root/'.work/tools').exists())

    def test_checksum_failure_stops_before_extracting_or_building(self):
        self.digest='0'*64
        with self.assertRaisesRegex(SystemExit,'checksum mismatch'):self.build()
        self.assertEqual([args[0] for args in self.calls],['curl'])
        self.assertFalse((self.root/'.work/ha-integration'/f'keepalived-{builder.VERSION}').exists())
