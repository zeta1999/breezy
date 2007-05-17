# Copyright (C) 2006-2007 Jelmer Vernooij <jelmer@samba.org>

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

from bzrlib.branch import Branch, PullResult
from bzrlib.bzrdir import BzrDir
from bzrlib.errors import DivergedBranches
from bzrlib.workingtree import WorkingTree

from copy import copy
from repository import MAPPING_VERSION
import os
from tests import TestCaseWithSubversionRepository

class TestNativeCommit(TestCaseWithSubversionRepository):
    def test_simple_commit(self):
        self.make_client('d', 'dc')
        self.build_tree({'dc/foo/bla': "data"})
        self.client_add("dc/foo")
        wt = self.open_checkout("dc")
        revid = wt.commit(message="data")
        self.assertEqual(wt.branch.generate_revision_id(1), revid)
        self.client_update("dc")
        self.assertEqual(wt.branch.generate_revision_id(1), 
                wt.branch.last_revision())
        wt = WorkingTree.open("dc")
        new_inventory = wt.branch.repository.get_inventory(
                            wt.branch.last_revision())
        self.assertTrue(new_inventory.has_filename("foo"))
        self.assertTrue(new_inventory.has_filename("foo/bla"))

    def test_commit_message(self):
        self.make_client('d', 'dc')
        self.build_tree({'dc/foo/bla': "data"})
        self.client_add("dc/foo")
        wt = self.open_checkout("dc")
        revid = wt.commit(message="data")
        self.assertEqual(wt.branch.generate_revision_id(1), revid)
        self.assertEqual(
                wt.branch.generate_revision_id(1), wt.branch.last_revision())
        new_revision = wt.branch.repository.get_revision(
                            wt.branch.last_revision())
        self.assertEqual(wt.branch.last_revision(), new_revision.revision_id)
        self.assertEqual("data", new_revision.message)

    def test_commit_message_nordic(self):
        self.make_client('d', 'dc')
        self.build_tree({'dc/foo/bla': "data"})
        self.client_add("dc/foo")
        wt = self.open_checkout("dc")
        revid = wt.commit(message=u"\xe6\xf8\xe5")
        self.assertEqual(revid, wt.branch.generate_revision_id(1))
        self.assertEqual(
                wt.branch.generate_revision_id(1), wt.branch.last_revision())
        new_revision = wt.branch.repository.get_revision(
                            wt.branch.last_revision())
        self.assertEqual(wt.branch.last_revision(), new_revision.revision_id)
        self.assertEqual(u"\xe6\xf8\xe5", new_revision.message.decode("utf-8"))

    def test_commit_update(self):
        self.make_client('d', 'dc')
        self.build_tree({'dc/foo/bla': "data"})
        self.client_add("dc/foo")
        wt = self.open_checkout("dc")
        wt.set_pending_merges(["some-ghost-revision"])
        wt.commit(message="data")
        self.assertEqual(
                wt.branch.generate_revision_id(1),
                wt.branch.last_revision())

    def test_commit_parents(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/foo/bla': "data"})
        self.client_add("dc/foo")
        wt = self.open_checkout("dc")
        wt.set_pending_merges(["some-ghost-revision"])
        wt.commit(message="data")
        self.assertEqual([wt.branch.generate_revision_id(0), "some-ghost-revision"],
                         wt.branch.repository.revision_parents(
                             wt.branch.last_revision()))
        self.assertEqual("some-ghost-revision\n", 
                self.client_get_prop(repos_url, "bzr:merge", 1))

    def test_commit_revision_id(self):
        repos_url = self.make_client('d', 'dc')
        wt = self.open_checkout("dc")
        self.build_tree({'dc/foo/bla': "data", 'dc/bla': "otherdata"})
        wt.add('bla')
        wt.commit(message="data")

        branch = Branch.open(repos_url)
        builder = branch.get_commit_builder([branch.last_revision()], revision_id="my-revision-id")
        tree = branch.repository.revision_tree(branch.last_revision())
        new_tree = copy(tree)
        ie = new_tree.inventory.root
        ie.revision = None
        builder.record_entry_contents(ie, [tree.inventory], '', new_tree)
        builder.finish_inventory()
        builder.commit("foo")

        self.assertEqual("my-revision-id", 
                self.client_get_prop("dc", "bzr:revision-id-v%d" % MAPPING_VERSION, 2))

    def test_mwh(self):
        repo = self.make_client('d', 'sc')
        def mv(*mvs):
            for a, b in mvs:
                self.client_copy(a, b)
                self.client_delete(a)
            self.client_commit('sc', '.')
            self.client_update('sc')
        self.build_tree({'sc/de/foo':'data', 'sc/de/bar':'DATA'})
        self.client_add('sc/de')
        self.client_commit('sc', 'blah') #1
        self.client_update('sc')
        os.mkdir('sc/de/trunk')
        self.client_add('sc/de/trunk')
        mv(('sc/de/foo', 'sc/de/trunk'), ('sc/de/bar', 'sc/de/trunk')) #2
        mv(('sc/de', 'sc/pyd'))  #3
        self.client_delete('sc/pyd/trunk/foo')
        self.client_commit('sc', '.') #4
        self.client_update('sc')

        self.make_checkout(repo + '/pyd/trunk', 'pyd')
        self.assertEqual("DATA", open('pyd/bar').read())

        olddir = BzrDir.open("pyd")
        os.mkdir('bc')
        newdir = olddir.sprout("bc")
        newdir.open_branch().pull(olddir.open_branch())
        wt = newdir.open_workingtree()
        self.assertEqual("DATA", open('bc/bar').read())
        open('bc/bar', 'w').write('data')
        wt.commit(message="Commit from Bzr")
        olddir.open_branch().pull(newdir.open_branch())

        self.client_update('pyd')
        self.assertEqual("data", open('pyd/bar').read())
        

class TestPush(TestCaseWithSubversionRepository):
    def setUp(self):
        super(TestPush, self).setUp()
        self.repos_url = self.make_client('d', 'sc')

        self.build_tree({'sc/foo/bla': "data"})
        self.client_add("sc/foo")
        self.client_commit("sc", "foo")

        self.olddir = self.open_checkout_bzrdir("sc")
        os.mkdir("dc")
        self.newdir = self.olddir.sprout("dc")

    def test_empty(self):
        self.assertEqual(0, int(self.olddir.open_branch().pull(
                                self.newdir.open_branch())))

    def test_empty_result(self):
        result = self.olddir.open_branch().pull(self.newdir.open_branch())
        self.assertIsInstance(result, PullResult)
        self.assertEqual(result.old_revno, self.olddir.open_branch().revno())
        self.assertEqual(result.master_branch, None)
        self.assertEqual(result.target_branch.bzrdir.transport.base, self.olddir.transport.base)
        self.assertEqual(result.source_branch.bzrdir.transport.base, self.newdir.transport.base)

    def test_child(self):
        self.build_tree({'sc/foo/bar': "data"})
        self.client_add("sc/foo/bar")
        self.client_commit("sc", "second message")

        self.assertEqual(0, int(self.olddir.open_branch().pull(
                                self.newdir.open_branch())))

    def test_diverged(self):
        self.build_tree({'sc/foo/bar': "data"})
        self.client_add("sc/foo/bar")
        self.client_commit("sc", "second message")

        olddir = BzrDir.open("sc")

        self.build_tree({'dc/file': 'data'})
        wt = self.newdir.open_workingtree()
        wt.add('file')
        wt.commit(message="Commit from Bzr")

        self.assertRaises(DivergedBranches, 
                          olddir.open_branch().pull,
                          self.newdir.open_branch())

    def test_change(self):
        self.build_tree({'dc/foo/bla': 'other data'})
        wt = self.newdir.open_workingtree()
        wt.commit(message="Commit from Bzr")

        self.olddir.open_branch().pull(self.newdir.open_branch())

        repos = self.olddir.find_repository()
        inv = repos.get_inventory(repos.generate_revision_id(2, ""))
        self.assertEqual(repos.generate_revision_id(2, ""),
                         inv[inv.path2id('foo/bla')].revision)
        self.assertTrue(wt.branch.last_revision() in 
          repos.revision_parents(repos.generate_revision_id(2, "")))
        self.assertEqual(repos.generate_revision_id(2, ""),
                        self.olddir.open_branch().last_revision())
        self.assertEqual("other data", 
            repos.revision_tree(repos.generate_revision_id(2, "")).get_file_text( inv.path2id("foo/bla")))

    def test_simple(self):
        self.build_tree({'dc/file': 'data'})
        wt = self.newdir.open_workingtree()
        wt.add('file')
        wt.commit(message="Commit from Bzr")

        self.olddir.open_branch().pull(self.newdir.open_branch())

        repos = self.olddir.find_repository()
        inv = repos.get_inventory(repos.generate_revision_id(2, ""))
        self.assertTrue(inv.has_filename('file'))
        self.assertTrue(wt.branch.last_revision() in 
            repos.revision_parents(
                repos.generate_revision_id(2, "")))
        self.assertEqual(repos.generate_revision_id(2, ""),
                        self.olddir.open_branch().last_revision())

    def test_pull_after_push(self):
        self.build_tree({'dc/file': 'data'})
        wt = self.newdir.open_workingtree()
        wt.add('file')
        wt.commit(message="Commit from Bzr")

        self.olddir.open_branch().pull(self.newdir.open_branch())

        repos = self.olddir.find_repository()
        inv = repos.get_inventory(repos.generate_revision_id(2, ""))
        self.assertTrue(inv.has_filename('file'))
        self.assertTrue(wt.branch.last_revision() in 
                         repos.revision_parents(repos.generate_revision_id(2, "")))
        self.assertEqual(repos.generate_revision_id(2, ""),
                        self.olddir.open_branch().last_revision())

        self.newdir.open_branch().pull(self.olddir.open_branch())

        self.assertEqual(repos.generate_revision_id(2, ""),
                        self.newdir.open_branch().last_revision())

    def test_message(self):
        self.build_tree({'dc/file': 'data'})
        wt = self.newdir.open_workingtree()
        wt.add('file')
        wt.commit(message="Commit from Bzr")

        self.olddir.open_branch().pull(self.newdir.open_branch())

        repos = self.olddir.find_repository()
        self.assertEqual("Commit from Bzr",
            repos.get_revision(repos.generate_revision_id(2, "")).message)

    def test_message_nordic(self):
        self.build_tree({'dc/file': 'data'})
        wt = self.newdir.open_workingtree()
        wt.add('file')
        wt.commit(message=u"\xe6\xf8\xe5")

        self.olddir.open_branch().pull(self.newdir.open_branch())

        repos = self.olddir.find_repository()
        self.assertEqual(u"\xe6\xf8\xe5",
            repos.get_revision(repos.generate_revision_id(2, "")).message.decode("utf-8"))


    def test_multiple(self):
        self.build_tree({'dc/file': 'data'})
        wt = self.newdir.open_workingtree()
        wt.add('file')
        wt.commit(message="Commit from Bzr")

        self.build_tree({'dc/file': 'data2', 'dc/adir': None})
        wt.add('adir')
        wt.commit(message="Another commit from Bzr")

        self.olddir.open_branch().pull(self.newdir.open_branch())

        repos = self.olddir.find_repository()

        self.assertEqual(repos.generate_revision_id(3, ""), 
                        self.olddir.open_branch().last_revision())

        inv = repos.get_inventory(repos.generate_revision_id(2, ""))
        self.assertTrue(inv.has_filename('file'))
        self.assertFalse(inv.has_filename('adir'))

        inv = repos.get_inventory(repos.generate_revision_id(3, ""))
        self.assertTrue(inv.has_filename('file'))
        self.assertTrue(inv.has_filename('adir'))

        self.assertTrue(wt.branch.last_revision() in 
             repos.get_ancestry(repos.generate_revision_id(3, "")))

class TestPushNested(TestCaseWithSubversionRepository):
    def setUp(self):
        super(TestPushNested, self).setUp()
        self.repos_url = self.make_client('d', 'sc')

        self.build_tree({'sc/foo/trunk/bla': "data"})
        self.client_add("sc/foo")
        self.client_commit("sc", "foo")

        self.olddir = self.open_checkout_bzrdir("sc/foo/trunk")
        os.mkdir("dc")
        self.newdir = self.olddir.sprout("dc")

    def test_simple(self):
        self.build_tree({'dc/file': 'data'})
        wt = self.newdir.open_workingtree()
        wt.add('file')
        wt.commit(message="Commit from Bzr")
        self.olddir.open_branch().pull(self.newdir.open_branch())
        repos = self.olddir.find_repository()
        self.client_update("sc")
        self.assertTrue(os.path.exists("sc/foo/trunk/file"))
        self.assertFalse(os.path.exists("sc/foo/trunk/filel"))
