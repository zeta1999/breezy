# Copyright (C) 2007 Canonical Ltd
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Tests for interfacing with a Git Repository"""

import dulwich
from dulwich.repo import (
    Repo as GitRepo,
    )
import os

from bzrlib import (
    errors,
    revision,
    )
from bzrlib.repository import (
    InterRepository,
    Repository,
    )

from bzrlib.plugins.git import (
    dir,
    repository,
    tests,
    )
from bzrlib.plugins.git.mapping import (
    default_mapping,
    )
from bzrlib.plugins.git.object_store import (
    BazaarObjectStore,
    )
from bzrlib.plugins.git.push import (
    MissingObjectsIterator,
    )

class TestGitRepositoryFeatures(tests.TestCaseInTempDir):
    """Feature tests for GitRepository."""

    def _do_commit(self):
        builder = tests.GitBranchBuilder()
        builder.set_file('a', 'text for a\n', False)
        commit_handle = builder.commit('Joe Foo <joe@foo.com>', u'message')
        mapping = builder.finish()
        return mapping[commit_handle]

    def test_open_existing(self):
        GitRepo.init(self.test_dir)

        repo = Repository.open('.')
        self.assertIsInstance(repo, repository.GitRepository)

    def test_has_git_repo(self):
        GitRepo.init(self.test_dir)

        repo = Repository.open('.')
        self.assertIsInstance(repo._git, dulwich.repo.BaseRepo)

    def test_has_revision(self):
        GitRepo.init(self.test_dir)
        commit_id = self._do_commit()
        repo = Repository.open('.')
        self.assertFalse(repo.has_revision('foobar'))
        revid = default_mapping.revision_id_foreign_to_bzr(commit_id)
        self.assertTrue(repo.has_revision(revid))

    def test_has_revisions(self):
        GitRepo.init(self.test_dir)
        commit_id = self._do_commit()
        repo = Repository.open('.')
        self.assertEquals(set(), repo.has_revisions(['foobar']))
        revid = default_mapping.revision_id_foreign_to_bzr(commit_id)
        self.assertEquals(set([revid]), repo.has_revisions(['foobar', revid]))

    def test_get_revision(self):
        # GitRepository.get_revision gives a Revision object.

        # Create a git repository with a revision.
        GitRepo.init(self.test_dir)
        commit_id = self._do_commit()

        # Get the corresponding Revision object.
        revid = default_mapping.revision_id_foreign_to_bzr(commit_id)
        repo = Repository.open('.')
        rev = repo.get_revision(revid)
        self.assertIsInstance(rev, revision.Revision)

    def test_get_revision_unknown(self):
        GitRepo.init(self.test_dir)

        repo = Repository.open('.')
        self.assertRaises(errors.NoSuchRevision, repo.get_revision, "bla")

    def simple_commit(self):
        # Create a git repository with some interesting files in a revision.
        GitRepo.init(self.test_dir)
        builder = tests.GitBranchBuilder()
        builder.set_file('data', 'text\n', False)
        builder.set_file('executable', 'content', True)
        builder.set_link('link', 'broken')
        builder.set_file('subdir/subfile', 'subdir text\n', False)
        commit_handle = builder.commit('Joe Foo <joe@foo.com>', u'message',
            timestamp=1205433193)
        mapping = builder.finish()
        return mapping[commit_handle]

    def test_pack(self):
        commit_id = self.simple_commit()
        repo = Repository.open('.')
        repo.pack()

    def test_revision_tree(self):
        commit_id = self.simple_commit()
        revid = default_mapping.revision_id_foreign_to_bzr(commit_id)
        repo = Repository.open('.')
        tree = repo.revision_tree(revid)
        self.assertEquals(tree.get_revision_id(), revid)
        self.assertEquals("text\n", tree.get_file_text(tree.path2id("data")))


class TestGitRepository(tests.TestCaseWithTransport):

    def _do_commit(self):
        builder = tests.GitBranchBuilder()
        builder.set_file('a', 'text for a\n', False)
        commit_handle = builder.commit('Joe Foo <joe@foo.com>', u'message')
        mapping = builder.finish()
        return mapping[commit_handle]

    def setUp(self):
        tests.TestCaseWithTransport.setUp(self)
        dulwich.repo.Repo.create(self.test_dir)
        self.git_repo = Repository.open(self.test_dir)

    def test_supports_rich_root(self):
        repo = self.git_repo
        self.assertEqual(repo.supports_rich_root(), True)

    def test_get_signature_text(self):
        self.assertRaises(errors.NoSuchRevision, self.git_repo.get_signature_text, revision.NULL_REVISION)

    def test_has_signature_for_revision_id(self):
        self.assertEquals(False, self.git_repo.has_signature_for_revision_id(revision.NULL_REVISION))

    def test_all_revision_ids_none(self):
        self.assertEquals(set([]), self.git_repo.all_revision_ids())

    def test_get_known_graph_ancestry(self):
        cid = self._do_commit()
        revid = default_mapping.revision_id_foreign_to_bzr(cid)
        g = self.git_repo.get_known_graph_ancestry([revid])
        self.assertEquals(frozenset([revid]),
            g.heads([revision.NULL_REVISION, revid]))
        self.assertEquals([revid],
            g.merge_sort(revid))

    def test_all_revision_ids(self):
        commit_id = self._do_commit()
        self.assertEquals(
                set([default_mapping.revision_id_foreign_to_bzr(commit_id)]),
                self.git_repo.all_revision_ids())

    def assertIsNullInventory(self, inv):
        self.assertEqual(inv.root, None)
        self.assertEqual(inv.revision_id, revision.NULL_REVISION)
        self.assertEqual(list(inv.iter_entries()), [])

    def test_revision_tree_none(self):
        # GitRepository.revision_tree(None) returns the null tree.
        repo = self.git_repo
        tree = repo.revision_tree(revision.NULL_REVISION)
        self.assertEqual(tree.get_revision_id(), revision.NULL_REVISION)

    def test_get_parent_map_null(self):
        self.assertEquals({revision.NULL_REVISION: ()}, 
                           self.git_repo.get_parent_map([revision.NULL_REVISION]))


class GitRepositoryFormat(tests.TestCase):

    def setUp(self):
        super(GitRepositoryFormat, self).setUp()
        self.format = repository.GitRepositoryFormat()

    def test_get_format_description(self):
        self.assertEquals("Git Repository", self.format.get_format_description())


class RevisionGistImportTests(tests.TestCaseWithTransport):

    def setUp(self):
        tests.TestCaseWithTransport.setUp(self)
        self.git_path = os.path.join(self.test_dir, "git")
        os.mkdir(self.git_path)
        dulwich.repo.Repo.create(self.git_path)
        self.git_repo = Repository.open(self.git_path)
        self.bzr_tree = self.make_branch_and_tree("bzr")

    def get_inter(self):
        return InterRepository.get(self.bzr_tree.branch.repository, 
                                   self.git_repo)

    def object_iter(self):
        store = BazaarObjectStore(self.bzr_tree.branch.repository, default_mapping)
        store_iterator = MissingObjectsIterator(store, self.bzr_tree.branch.repository)
        return store, store_iterator

    def import_rev(self, revid, parent_lookup=None):
        store, store_iter = self.object_iter()
        store._cache.idmap.start_write_group()
        try:
            return store_iter.import_revision(revid, roundtrip=False)
        except:
            store._cache.idmap.abort_write_group()
            raise
        else:
            store._cache.idmap.commit_write_group()

    def test_pointless(self):
        revid = self.bzr_tree.commit("pointless", timestamp=1205433193,
                timezone=0,
                  committer="Jelmer Vernooij <jelmer@samba.org>")
        self.assertEquals("2caa8094a5b794961cd9bf582e3e2bb090db0b14", 
                self.import_rev(revid))
        self.assertEquals("2caa8094a5b794961cd9bf582e3e2bb090db0b14", 
                self.import_rev(revid))


class ForeignTestsRepositoryFactory(object):

    def make_repository(self, transport):
        return dir.LocalGitControlDirFormat().initialize_on_transport(transport).open_repository()