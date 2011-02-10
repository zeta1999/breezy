#    test_upstream.py -- Test getting the upstream source
#    Copyright (C) 2009 Canonical Ltd.
#
#    This file is part of bzr-builddeb.
#
#    bzr-builddeb is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    bzr-builddeb is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with bzr-builddeb; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

# We have a bit of a problem with testing the actual uscan etc. integration,
# so just mock them.

"""Tests for the upstream module."""


import os
import tarfile
import zipfile

from bzrlib.revision import (
    Revision,
    )
from bzrlib.tests import (
    Feature,
    TestCase,
    TestCaseWithTransport,
    )
from bzrlib.plugins.builddeb.config import (
    DebBuildConfig,
    )
from bzrlib.plugins.builddeb.errors import (
    MissingUpstreamTarball,
    PackageVersionNotPresent,
    WatchFileMissing,
    )
from bzrlib.plugins.builddeb.upstream import (
    AptSource,
    PristineTarSource,
    StackedUpstreamSource,
    TarfileSource,
    UpstreamProvider,
    UpstreamSource,
    UScanSource,
    Version,
    )
from bzrlib.plugins.builddeb.upstream.branch import (
    get_export_upstream_revision,
    get_snapshot_revision,
    UpstreamBranchSource,
    _upstream_branch_version,
    upstream_tag_to_version,
    upstream_version_add_revision
    )


# Unless bug #712474 is fixed and available in the minimum bzrlib required, we
# can't use:
# svn_plugin = tests.ModuleAvailableFeature('bzrlib.plugins.svn')
class SvnPluginAvailable(Feature):

    def feature_name(self):
        return 'bzr-svn plugin'

    def _probe(self):
        try:
            import bzrlib.plugins.svn
            return True
        except ImportError:
            return False
svn_plugin = SvnPluginAvailable()


class MockSources(object):

    def __init__(self, versions):
        self.restart_called_times = 0
        self.lookup_called_times = 0
        self.lookup_package = None
        self.versions = versions
        self.version = None

    def restart(self):
        self.restart_called_times += 1

    def lookup(self, package):
        self.lookup_called_times += 1
        assert not self.lookup_package or self.lookup_package == package
        self.lookup_package = package
        if self.lookup_called_times <= len(self.versions):
            self.version = self.versions[self.lookup_called_times-1]
            return True
        else:
            self.version = None
            return False


class MockAptPkg(object):

    def __init__(self, sources):
        self.init_called_times = 0
        self.get_pkg_source_records_called_times = 0
        self.sources = sources

    def init(self):
        self.init_called_times += 1

    def SourceRecords(self):
        self.get_pkg_source_records_called_times += 1
        return self.sources


class MockAptCaller(object):

    def __init__(self, work=False):
        self.work = work
        self.called = 0
        self.package = None
        self.version_str = None
        self.target_dir = None

    def call(self, package, version_str, target_dir):
        self.package = package
        self.version_str = version_str
        self.target_dir = target_dir
        self.called += 1
        return self.work


class AptSourceTests(TestCase):

    def test_get_apt_command_for_source(self):
        self.assertEqual("apt-get source -y --only-source --tar-only "
                "apackage=someversion",
                AptSource()._get_command("apackage", "someversion"))

    def test_apt_provider_no_package(self):
        caller = MockAptCaller()
        sources = MockSources([])
        apt_pkg = MockAptPkg(sources)
        src = AptSource()
        src._run_apt_source = caller.call
        self.assertRaises(PackageVersionNotPresent, src.fetch_tarball,
            "apackage", "0.2", "target", _apt_pkg=apt_pkg)
        self.assertEqual(1, apt_pkg.init_called_times)
        self.assertEqual(1, apt_pkg.get_pkg_source_records_called_times)
        self.assertEqual(1, sources.restart_called_times)
        self.assertEqual(1, sources.lookup_called_times)
        self.assertEqual("apackage", sources.lookup_package)
        self.assertEqual(0, caller.called)

    def test_apt_provider_wrong_version(self):
        caller = MockAptCaller()
        sources = MockSources(["0.1-1"])
        apt_pkg = MockAptPkg(sources)
        src = AptSource()
        src._run_apt_source = caller.call
        self.assertRaises(PackageVersionNotPresent, src.fetch_tarball,
            "apackage", "0.2", "target", _apt_pkg=apt_pkg)
        self.assertEqual(1, apt_pkg.init_called_times)
        self.assertEqual(1, apt_pkg.get_pkg_source_records_called_times)
        self.assertEqual(1, sources.restart_called_times)
        self.assertEqual(2, sources.lookup_called_times)
        self.assertEqual("apackage", sources.lookup_package)
        self.assertEqual(0, caller.called)

    def test_apt_provider_right_version(self):
        caller = MockAptCaller(work=True)
        sources = MockSources(["0.1-1", "0.2-1"])
        apt_pkg = MockAptPkg(sources)
        src = AptSource()
        src._run_apt_source = caller.call
        src.fetch_tarball("apackage", "0.2", "target",
            _apt_pkg=apt_pkg)
        self.assertEqual(1, apt_pkg.init_called_times)
        self.assertEqual(1, apt_pkg.get_pkg_source_records_called_times)
        self.assertEqual(1, sources.restart_called_times)
        # Only called twice means it stops when the command works.
        self.assertEqual(2, sources.lookup_called_times)
        self.assertEqual("apackage", sources.lookup_package)
        self.assertEqual(1, caller.called)
        self.assertEqual("apackage", caller.package)
        self.assertEqual("0.2-1", caller.version_str)
        self.assertEqual("target", caller.target_dir)

    def test_apt_provider_right_version_command_fails(self):
        caller = MockAptCaller()
        sources = MockSources(["0.1-1", "0.2-1"])
        apt_pkg = MockAptPkg(sources)
        src = AptSource()
        src._run_apt_source = caller.call
        self.assertRaises(PackageVersionNotPresent, src.fetch_tarball,
            "apackage", "0.2", "target",
            _apt_pkg=apt_pkg)
        self.assertEqual(1, apt_pkg.init_called_times)
        self.assertEqual(1, apt_pkg.get_pkg_source_records_called_times)
        self.assertEqual(1, sources.restart_called_times)
        # Only called twice means it stops when the command fails.
        self.assertEqual(2, sources.lookup_called_times)
        self.assertEqual("apackage", sources.lookup_package)
        self.assertEqual(1, caller.called)
        self.assertEqual("apackage", caller.package)
        self.assertEqual("0.2-1", caller.version_str)
        self.assertEqual("target", caller.target_dir)


class RecordingSource(UpstreamSource):

    def __init__(self, succeed, latest=None):
        self._succeed = succeed
        self._specific_versions = []
        self._latest = latest

    def get_latest_version(self, package, current_version):
        return self._latest

    def fetch_tarball(self, package, version, target_dir):
        self._specific_versions.append((package, version, target_dir))
        if not self._succeed:
            raise PackageVersionNotPresent(package, version, self)
        return self._tarball_path(package, version, target_dir)

    def __repr__(self):
        return "%s()" % self.__class__.__name__


class StackedUpstreamSourceTests(TestCase):

    def test_fetch_tarball_first_wins(self):
        a = RecordingSource(False)
        b = RecordingSource(True)
        c = RecordingSource(False)
        stack = StackedUpstreamSource([a, b, c])
        stack.fetch_tarball("mypkg", "1.0", "bla")
        self.assertEquals([("mypkg", "1.0", "bla")], b._specific_versions)
        self.assertEquals([("mypkg", "1.0", "bla")], a._specific_versions)
        self.assertEquals([], c._specific_versions)

    def test_get_latest_version_first_wins(self):
        a = RecordingSource(False, latest="1.1")
        b = RecordingSource(False, latest="1.2")
        stack = StackedUpstreamSource([a, b])
        self.assertEquals("1.1", stack.get_latest_version("mypkg", "1.0"))

    def test_repr(self):
        self.assertEquals("StackedUpstreamSource([])",
                repr(StackedUpstreamSource([])))
        self.assertEquals("StackedUpstreamSource([RecordingSource()])",
                repr(StackedUpstreamSource([RecordingSource(False)])))

    def test_none(self):
        a = RecordingSource(False)
        b = RecordingSource(False)
        stack = StackedUpstreamSource([a, b])
        self.assertRaises(PackageVersionNotPresent,
                stack.fetch_tarball, "pkg", "1.0", "bla")
        self.assertEquals([("pkg", "1.0", "bla")], b._specific_versions)
        self.assertEquals([("pkg", "1.0", "bla")], a._specific_versions)


class UScanSourceTests(TestCaseWithTransport):

    def setUp(self):
        super(UScanSourceTests, self).setUp()
        self.tree = self.make_branch_and_tree('.')

    def test_export_watchfile_none(self):
        src = UScanSource(self.tree, False)
        self.assertRaises(WatchFileMissing, src._export_watchfile)

    def test_export_watchfile_larstiq(self):
        src = UScanSource(self.tree, True)
        self.build_tree(['watch'])
        self.assertRaises(WatchFileMissing, src._export_watchfile)
        self.tree.add(['watch'])
        self.assertTrue(src._export_watchfile() is not None)

    def test_export_watchfile(self):
        src = UScanSource(self.tree, False)
        self.build_tree(['debian/', 'debian/watch'])
        self.assertRaises(WatchFileMissing, src._export_watchfile)
        self.tree.smart_add(['debian/watch'])
        self.assertTrue(src._export_watchfile() is not None)

    def test__xml_report_extract_upstream_version(self):
        self.assertEquals("1.2.9",
            UScanSource._xml_report_extract_upstream_version("""
<dehs>
<package>tdb</package>
<debian-uversion>1.2.8</debian-uversion>
<debian-mangled-uversion>1.2.8</debian-mangled-uversion>
<upstream-version>1.2.9</upstream-version>
<upstream-url>ftp://ftp.samba.org/pub/tdb/tdb-1.2.9.tar.gz</upstream-url>
<status>Newer version available</status>
</dehs>"""))

    def test__xml_report_extract_upstream_version_warnings(self):
        self.assertIs(None,
            UScanSource._xml_report_extract_upstream_version("""
<dehs>
<package>tdb</package>
<warnings>uscan warning: Unable to determine current version
in debian/watch, skipping:
ftp://ftp.samba.org/pub/tdb/tdb-(.+).tar.gz</warnings>
</dehs>
"""))


class UpstreamBranchSourceTests(TestCaseWithTransport):
    """Tests for UpstreamBranchSource."""

    def setUp(self):
        super(UpstreamBranchSourceTests, self).setUp()
        self.tree = self.make_branch_and_tree('.')

    def test_fetch_tarball(self):
        self.tree.commit("msg")
        self.tree.branch.tags.set_tag("1.0", self.tree.branch.last_revision())
        source = UpstreamBranchSource(self.tree.branch,
            {"1.0": self.tree.branch.last_revision()})
        os.mkdir("mydir")
        self.assertEquals("mydir/foo_1.0.orig.tar.gz",
            source.fetch_tarball("foo", "1.0", "mydir"))
        self.failUnlessExists("mydir/foo_1.0.orig.tar.gz")

    def test_fetch_tarball_not_found(self):
        source = UpstreamBranchSource(self.tree.branch)
        self.tree.commit("msg")
        self.assertRaises(PackageVersionNotPresent,
            source.fetch_tarball, "foo", "1.0", "mydir")

    def test_get_latest_version(self):
        self.tree.commit("msg")
        self.tree.branch.tags.set_tag("2.1", self.tree.branch.last_revision())
        source = UpstreamBranchSource(self.tree.branch,
            {"2.1": self.tree.branch.last_revision()})
        self.assertEquals("2.1", source.get_latest_version("foo", "1.0"))
        self.tree.commit("msg")
        self.assertEquals("2.1+bzr2", source.get_latest_version("foo", "1.0"))

    def test_version_as_revision(self):
        revid1 = self.tree.commit("msg")
        self.tree.branch.tags.set_tag("2.1", self.tree.branch.last_revision())
        config = DebBuildConfig(
            [('user.conf', True), ('default.conf', False)],
            branch=self.tree.branch)
        source = UpstreamBranchSource(self.tree.branch,
            {"2.1": self.tree.branch.last_revision()},
            config=config)
        revid2 = self.tree.commit("msg")
        self.assertEquals(revid2,
            source.version_as_revision("foo", "2.1+bzr2"))
        self.assertEquals(revid1, source.version_as_revision("foo", "2.1"))


class TestUpstreamBranchVersion(TestCase):
    """Test that the upstream version of a branch can be determined correctly.
    """

    def get_suffix(self, version_string, revid):
        revno = self.revhistory.index(revid)+1
        if "bzr" in version_string:
            return "%sbzr%d" % (version_string.split("bzr")[0], revno)
        return "%s+bzr%d" % (version_string, revno)

    def test_snapshot_none_existing(self):
      self.revhistory = ["somerevid"]
      self.assertEquals(Version("1.2+bzr1"),
          _upstream_branch_version(self.revhistory, {}, "bla", "1.2", self.get_suffix))

    def test_snapshot_nothing_new(self):
      self.revhistory = []
      self.assertEquals(Version("1.2"),
          _upstream_branch_version(self.revhistory, {}, "bla", "1.2", self.get_suffix))

    def test_new_tagged_release(self):
      """Last revision is tagged - use as upstream version."""
      self.revhistory = ["somerevid"]
      self.assertEquals(Version("1.3"),
          _upstream_branch_version(self.revhistory, {"somerevid": ["1.3"]}, "bla", "1.2", self.get_suffix))

    def test_refresh_snapshot_pre(self):
      self.revhistory = ["oldrevid", "somerevid"]
      self.assertEquals(Version("1.3~bzr2"),
          _upstream_branch_version(self.revhistory, {}, "bla", "1.3~bzr1", self.get_suffix))

    def test_refresh_snapshot_post(self):
      self.revhistory = ["oldrevid", "somerevid"]
      self.assertEquals(Version("1.3+bzr2"),
          _upstream_branch_version(self.revhistory, {}, "bla", "1.3+bzr1", self.get_suffix))

    def test_new_tag_refresh_snapshot(self):
      self.revhistory = ["oldrevid", "somerevid", "newrevid"]
      self.assertEquals(Version("1.3+bzr3"),
            _upstream_branch_version(self.revhistory,
                {"somerevid": ["1.3"]}, "bla", "1.2+bzr1", self.get_suffix))


class TestUpstreamTagToVersion(TestCase):

    def test_prefix(self):
        self.assertEquals(Version("5.0"), upstream_tag_to_version("release-5.0"))

    def test_gibberish(self):
        self.assertIs(None, upstream_tag_to_version("blabla"))

    def test_vprefix(self):
        self.assertEquals(Version("2.0"), upstream_tag_to_version("v2.0"))

    def test_plain(self):
        self.assertEquals(Version("2.0"), upstream_tag_to_version("2.0"))

    def test_package_prefix(self):
        self.assertEquals(Version("42.0"), upstream_tag_to_version("bla-42.0", "bla"))


class TestUpstreamVersionAddRevision(TestCaseWithTransport):
    """Test that updating the version string works."""

    def setUp(self):
        super(TestUpstreamVersionAddRevision, self).setUp()
        self.revnos = {}
        self.svn_revnos = {"somesvnrev": 45}
        self.revnos = {"somerev": 42, "somesvnrev": 12}
        self.repository = self

    def revision_id_to_revno(self, revid):
        return self.revnos[revid]

    def get_revision(self, revid):
        rev = Revision(revid)
        if revid in self.svn_revnos:
            self.requireFeature(svn_plugin)
            # Fake a bzr-svn revision
            rev.foreign_revid = ("uuid", "bp", self.svn_revnos[revid])
            from bzrlib.plugins.svn import mapping
            rev.mapping = mapping.mapping_registry.get_default()()
        return rev

    def test_update_plus_rev(self):
        self.assertEquals("1.3+bzr42",
          upstream_version_add_revision(self, "1.3+bzr23", "somerev"))

    def test_update_tilde_rev(self):
        self.assertEquals("1.3~bzr42",
          upstream_version_add_revision(self, "1.3~bzr23", "somerev"))

    def test_new_rev(self):
        self.assertEquals("1.3+bzr42",
          upstream_version_add_revision(self, "1.3", "somerev"))

    def test_svn_new_rev(self):
        self.assertEquals("1.3+svn45",
          upstream_version_add_revision(self, "1.3", "somesvnrev"))

    def test_svn_plus_rev(self):
        self.assertEquals("1.3+svn45",
          upstream_version_add_revision(self, "1.3+svn3", "somesvnrev"))

    def test_svn_tilde_rev(self):
        self.assertEquals("1.3~svn45",
            upstream_version_add_revision(self, "1.3~svn800", "somesvnrev"))


class GetExportUpstreamRevisionTests(TestCase):

    def test_snapshot_rev(self):
        config = DebBuildConfig([])
        self.assertEquals("34",
            get_export_upstream_revision(config, "0.1+bzr34"))

    def test_export_upstream_rev(self):
        config = DebBuildConfig([
            ({"BUILDDEB": {"export-upstream-revision": "tag:foobar"}}, True)])
        self.assertEquals("tag:foobar",
            get_export_upstream_revision(config, "0.1"))

    def test_export_upstream_rev_var(self):
        config = DebBuildConfig([({"BUILDDEB":
            {"export-upstream-revision": "tag:foobar-$UPSTREAM_VERSION"}},
            True)])
        self.assertEquals("tag:foobar-0.1",
            get_export_upstream_revision(config, "0.1"))

    def test_export_upstream_rev_not_set(self):
        config = DebBuildConfig([])
        self.assertEquals(None,
            get_export_upstream_revision(config, "0.1"))


class GetRevisionSnapshotTests(TestCase):

    def test_with_snapshot(self):
        self.assertEquals("30", get_snapshot_revision("0.4.4~bzr30"))

    def test_with_snapshot_plus(self):
        self.assertEquals("30", get_snapshot_revision("0.4.4+bzr30"))

    def test_without_snapshot(self):
        self.assertEquals(None, get_snapshot_revision("0.4.4"))

    def test_non_numeric_snapshot(self):
        self.assertEquals(None, get_snapshot_revision("0.4.4~bzra"))

    def test_with_svn_snapshot(self):
        self.assertEquals("svn:4242", get_snapshot_revision("0.4.4~svn4242"))

    def test_with_svn_snapshot_plus(self):
        self.assertEquals("svn:2424", get_snapshot_revision("0.4.4+svn2424"))


class PristineTarSourceTests(TestCaseWithTransport):

    def setUp(self):
        super(PristineTarSourceTests, self).setUp()
        self.tree = self.make_branch_and_tree('unstable')
        root_id = self.tree.path2id("")
        self.source = PristineTarSource(self.tree, self.tree.branch)

    def test_upstream_tag_name(self):
        upstream_v_no = "0.1"
        self.assertEqual(self.source.tag_name(upstream_v_no),
                "upstream-" + upstream_v_no)

    def test_version(self):
        self.assertEquals(['upstream-3.3', 'upstream-debian-3.3',
            'upstream-ubuntu-3.3', 'upstream/3.3'],
            self.source.possible_tag_names("3.3"))


class TarfileSourceTests(TestCaseWithTransport):
    """Tests for TarfileSource."""

    def setUp(self):
        super(TarfileSourceTests, self).setUp()
        tar = tarfile.open("foo-1.0.tar.gz", "w:gz")
        tar.close()

    def test_version(self):
        source = TarfileSource("foo-1.0.tar.gz", "1.0")
        self.assertEquals("1.0", source.get_latest_version("foo", "0.9"))

    def test_fetch_tarball(self):
        source = TarfileSource("foo-1.0.tar.gz", "1.0")
        os.mkdir("bar")
        self.assertEquals("bar/foo_1.0.orig.tar.gz",
            source.fetch_tarball("foo", "1.0", "bar"))
        self.failUnlessExists("bar/foo_1.0.orig.tar.gz")

    def test_fetch_tarball_repack(self):
        zf = zipfile.ZipFile("bla-2.0.zip", "w")
        zf.writestr('avoid', 'empty zip to make the repacker happy\n')
        zf.close()
        source = TarfileSource("bla-2.0.zip", "2.0")
        os.mkdir("bar")
        self.assertEquals("bar/foo_2.0.orig.tar.gz",
            source.fetch_tarball("foo", "2.0", "bar"))
        self.failUnlessExists("bar/foo_2.0.orig.tar.gz")

    def test_fetch_tarball_not_present(self):
        source = TarfileSource("foo-1.0.tar.gz", "1.0")
        os.mkdir("bar")
        self.assertRaises(PackageVersionNotPresent,
            source.fetch_tarball, "foo", "0.9", "bar")


class _MissingUpstreamProvider(UpstreamProvider):
    """For tests"""

    def __init__(self):
        pass

    def provide(self, target_dir):
        raise MissingUpstreamTarball("test_tarball")


class _TouchUpstreamProvider(UpstreamProvider):
    """For tests"""

    def __init__(self, desired_tarball_name):
        self.desired_tarball_name = desired_tarball_name

    def provide(self, target_dir):
        f = open(os.path.join(target_dir, self.desired_tarball_name), "wb")
        f.write("I am a tarball, honest\n")
        f.close()


class _SimpleUpstreamProvider(UpstreamProvider):
    """For tests"""

    def __init__(self, package, version, store_dir):
        self.package = package
        self.version = version
        self.store_dir = store_dir

    def provide(self, target_dir):
        path = (self.already_exists_in_target(target_dir)
                or self.provide_from_store_dir(target_dir))
        if path is not None:
            return path
        raise MissingUpstreamTarball(self._tarball_names()[0])