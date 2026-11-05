import contextlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from scripts.collect_device import ARTIFACTS, collect, ssh_arguments
from scripts.fwlib import BuildError


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.destination=self.root/'private/device-new'
        self.commands=[]
    def runner(self,args,stdout,stderr,timeout,check):
        self.commands.append(args)
        remote=args[-1]
        if remote=='tar -C / -czf - etc/config':
            with tarfile.open(fileobj=stdout,mode='w:gz') as archive:
                data=b"config interface 'wan'\n option password 'test-secret-do-not-print'\n"
                member=tarfile.TarInfo('etc/config/network');member.size=len(data)
                archive.addfile(member,io.BytesIO(data))
        elif remote=='ubus call system board':stdout.write(b'{"board_name":"test-board"}')
        elif remote=='ubus call network.interface dump':stdout.write(b'{"interface":[]}')
        elif remote.startswith('if command -v opkg') and 'list-installed' not in remote:stdout.write(b'opkg\n')
        elif 'list-installed' in remote:stdout.write(b'luci - 1\n')
        else:stdout.write(b'test-output\n')
        return subprocess.CompletedProcess(args,0)
    def test_complete_snapshot_is_private_and_never_prints_values(self):
        output=io.StringIO()
        with contextlib.redirect_stdout(output):
            result=collect('root@example.test',22,self.destination,workspace=self.root,runner=self.runner)
        self.assertNotIn('test-secret',output.getvalue())
        self.assertEqual(json.loads((result/'snapshot.json').read_text())['status'],'complete')
        self.assertEqual(result.stat().st_mode & 0o777,0o700)
        self.assertTrue(all(p.stat().st_mode & 0o777==0o600 for p in result.iterdir()))
        self.assertEqual(len(self.commands),len(ARTIFACTS))
        self.assertTrue((result/'SHA256SUMS').is_file())
    def test_ssh_failure_leaves_explicit_failed_snapshot(self):
        def fail(args,**kwargs):return subprocess.CompletedProcess(args,255)
        with self.assertRaises(BuildError):collect('root@example.test',22,self.destination,workspace=self.root,runner=fail)
        self.assertEqual(json.loads((self.destination/'snapshot.json').read_text())['status'],'failed')
    def test_transport_timeout_is_not_a_successful_snapshot(self):
        def timeout(args,**kwargs):raise subprocess.TimeoutExpired('ssh',90)
        with self.assertRaises(subprocess.TimeoutExpired):collect('root@example.test',22,self.destination,workspace=self.root,runner=timeout)
        self.assertEqual(json.loads((self.destination/'snapshot.json').read_text())['status'],'failed')
    def test_public_destination_is_rejected_before_connecting(self):
        with self.assertRaises(BuildError):collect('root@example.test',22,self.root/'files/leak',workspace=self.root,runner=self.runner)
        self.assertEqual(self.commands,[])
    def test_existing_snapshot_is_never_overwritten(self):
        self.destination.mkdir(parents=True)
        with self.assertRaises(BuildError):collect('root@example.test',22,self.destination,workspace=self.root,runner=self.runner)
        self.assertEqual(self.commands,[])
    def test_symlink_destination_is_rejected(self):
        (self.root/'private').mkdir();(self.root/'outside').mkdir()
        (self.root/'private/alias').symlink_to(self.root/'outside',target_is_directory=True)
        with self.assertRaises(BuildError):collect('root@example.test',22,self.root/'private/alias/new',workspace=self.root,runner=self.runner)
        self.assertEqual(self.commands,[])
    def test_host_options_and_invalid_ports_are_rejected(self):
        for host in ('-oProxyCommand=anything','root@host;touch /tmp/x','host name'):
            with self.assertRaises(BuildError):ssh_arguments(host,22)
        with self.assertRaises(BuildError):ssh_arguments('root@example.test',70000)
        self.assertIn('2222',ssh_arguments('root@example.test',2222))
    def test_archive_parent_escape_is_rejected(self):
        from scripts.collect_device import validate_archive
        archive=self.root/'bad.tar.gz'
        with tarfile.open(archive,'w:gz') as stream:
            info=tarfile.TarInfo('etc/config/../../outside');info.size=1
            stream.addfile(info,io.BytesIO(b'x'))
        with self.assertRaises(BuildError):validate_archive(archive)
