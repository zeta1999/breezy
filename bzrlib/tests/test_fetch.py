# Copyright (C) 2005 by Canonical Ltd

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

import os
import sys

from bzrlib.branch import Branch
from bzrlib.bzrdir import BzrDir
from bzrlib.builtins import merge
import bzrlib.errors
from bzrlib.tests import TestCaseWithTransport
from bzrlib.tests.HTTPTestUtil import TestCaseWithWebserver
from bzrlib.tests.test_revision import make_branches
from bzrlib.trace import mutter
from bzrlib.workingtree import WorkingTree


def has_revision(branch, revision_id):
    return branch.repository.has_revision(revision_id)

def fetch_steps(self, br_a, br_b, writable_a):
    """A foreign test method for testing fetch locally and remotely."""
     
    # TODO RBC 20060201 make this a repository test.
    repo_b = br_b.repository
    self.assertFalse(repo_b.has_revision(br_a.revision_history()[3]))
    self.assertTrue(repo_b.has_revision(br_a.revision_history()[2]))
    self.assertEquals(len(br_b.revision_history()), 7)
    self.assertEquals(br_b.fetch(br_a, br_a.revision_history()[2])[0], 0)
    # branch.fetch is not supposed to alter the revision history
    self.assertEquals(len(br_b.revision_history()), 7)
    self.assertFalse(repo_b.has_revision(br_a.revision_history()[3]))

    # fetching the next revision up in sample data copies one revision
    self.assertEquals(br_b.fetch(br_a, br_a.revision_history()[3])[0], 1)
    self.assertTrue(repo_b.has_revision(br_a.revision_history()[3]))
    self.assertFalse(has_revision(br_a, br_b.revision_history()[6]))
    self.assertTrue(br_a.repository.has_revision(br_b.revision_history()[5]))

    # When a non-branch ancestor is missing, it should be unlisted...
    # as its not reference from the inventory weave.
    br_b4 = self.make_branch('br_4')
    count, failures = br_b4.fetch(br_b)
    self.assertEqual(count, 7)
    self.assertEqual(failures, [])

    self.assertEqual(writable_a.fetch(br_b)[0], 1)
    self.assertTrue(has_revision(br_a, br_b.revision_history()[3]))
    self.assertTrue(has_revision(br_a, br_b.revision_history()[4]))
        
    br_b2 = self.make_branch('br_b2')
    self.assertEquals(br_b2.fetch(br_b)[0], 7)
    self.assertTrue(has_revision(br_b2, br_b.revision_history()[4]))
    self.assertTrue(has_revision(br_b2, br_a.revision_history()[2]))
    self.assertFalse(has_revision(br_b2, br_a.revision_history()[3]))

    br_a2 = self.make_branch('br_a2')
    self.assertEquals(br_a2.fetch(br_a)[0], 9)
    self.assertTrue(has_revision(br_a2, br_b.revision_history()[4]))
    self.assertTrue(has_revision(br_a2, br_a.revision_history()[3]))
    self.assertTrue(has_revision(br_a2, br_a.revision_history()[2]))

    br_a3 = self.make_branch('br_a3')
    # pulling a branch with no revisions grabs nothing, regardless of 
    # whats in the inventory.
    self.assertEquals(br_a3.fetch(br_a2)[0], 0)
    for revno in range(4):
        self.assertFalse(
            br_a3.repository.has_revision(br_a.revision_history()[revno]))
    self.assertEqual(br_a3.fetch(br_a2, br_a.revision_history()[2])[0], 3)
    # pull the 3 revisions introduced by a@u-0-3
    fetched = br_a3.fetch(br_a2, br_a.revision_history()[3])[0]
    self.assertEquals(fetched, 3, "fetched %d instead of 3" % fetched)
    # InstallFailed should be raised if the branch is missing the revision
    # that was requested.
    self.assertRaises(bzrlib.errors.InstallFailed, br_a3.fetch, br_a2, 'pizza')
    # InstallFailed should be raised if the branch is missing a revision
    # from its own revision history
    br_a2.append_revision('a-b-c')
    self.assertRaises(bzrlib.errors.InstallFailed, br_a3.fetch, br_a2)

    # TODO: jam 20051218 Branch should no longer allow append_revision for revisions
    #       which don't exist. So this test needs to be rewritten
    #       RBC 20060403 the way to do this is to uncommit the revision from the
    #           repository after the commit

    #TODO: test that fetch correctly does reweaving when needed. RBC 20051008
    # Note that this means - updating the weave when ghosts are filled in to 
    # add the right parents.


class TestFetch(TestCaseWithTransport):

    def test_fetch(self):
        #highest indices a: 5, b: 7
        br_a, br_b = make_branches(self)
        fetch_steps(self, br_a, br_b, br_a)

    def test_fetch_self(self):
        wt = self.make_branch_and_tree('br')
        self.assertEqual(wt.branch.fetch(wt.branch), (0, []))


class TestMergeFetch(TestCaseWithTransport):

    def test_merge_fetches_unrelated(self):
        """Merge brings across history from unrelated source"""
        wt1 = self.make_branch_and_tree('br1')
        br1 = wt1.branch
        wt1.commit(message='rev 1-1', rev_id='1-1')
        wt1.commit(message='rev 1-2', rev_id='1-2')
        wt2 = self.make_branch_and_tree('br2')
        br2 = wt2.branch
        wt2.commit(message='rev 2-1', rev_id='2-1')
        merge(other_revision=['br1', -1], base_revision=['br1', 0],
              this_dir='br2')
        self._check_revs_present(br2)

    def test_merge_fetches(self):
        """Merge brings across history from source"""
        wt1 = self.make_branch_and_tree('br1')
        br1 = wt1.branch
        wt1.commit(message='rev 1-1', rev_id='1-1')
        dir_2 = br1.bzrdir.sprout('br2')
        br2 = dir_2.open_branch()
        wt1.commit(message='rev 1-2', rev_id='1-2')
        dir_2.open_workingtree().commit(message='rev 2-1', rev_id='2-1')
        merge(other_revision=['br1', -1], base_revision=[None, None], 
              this_dir='br2')
        self._check_revs_present(br2)

    def _check_revs_present(self, br2):
        for rev_id in '1-1', '1-2', '2-1':
            self.assertTrue(br2.repository.has_revision(rev_id))
            rev = br2.repository.get_revision(rev_id)
            self.assertEqual(rev.revision_id, rev_id)
            self.assertTrue(br2.repository.get_inventory(rev_id))


class TestMergeFileHistory(TestCaseWithTransport):

    def setUp(self):
        super(TestMergeFileHistory, self).setUp()
        wt1 = self.make_branch_and_tree('br1')
        br1 = wt1.branch
        self.build_tree_contents([('br1/file', 'original contents\n')])
        wt1.add('file', 'this-file-id')
        wt1.commit(message='rev 1-1', rev_id='1-1')
        dir_2 = br1.bzrdir.sprout('br2')
        br2 = dir_2.open_branch()
        wt2 = dir_2.open_workingtree()
        self.build_tree_contents([('br1/file', 'original from 1\n')])
        wt1.commit(message='rev 1-2', rev_id='1-2')
        self.build_tree_contents([('br1/file', 'agreement\n')])
        wt1.commit(message='rev 1-3', rev_id='1-3')
        self.build_tree_contents([('br2/file', 'contents in 2\n')])
        wt2.commit(message='rev 2-1', rev_id='2-1')
        self.build_tree_contents([('br2/file', 'agreement\n')])
        wt2.commit(message='rev 2-2', rev_id='2-2')

    def test_merge_fetches_file_history(self):
        """Merge brings across file histories"""
        br2 = Branch.open('br2')
        merge(other_revision=['br1', -1], base_revision=[None, None], 
              this_dir='br2')
        for rev_id, text in [('1-2', 'original from 1\n'),
                             ('1-3', 'agreement\n'),
                             ('2-1', 'contents in 2\n'),
                             ('2-2', 'agreement\n')]:
            self.assertEqualDiff(
                br2.repository.revision_tree(
                    rev_id).get_file_text('this-file-id'), text)


class TestHttpFetch(TestCaseWithWebserver):
    # FIXME RBC 20060124 this really isn't web specific, perhaps an
    # instrumented readonly transport? Can we do an instrumented
    # adapter and use self.get_readonly_url ?

    def test_fetch(self):
        #highest indices a: 5, b: 7
        br_a, br_b = make_branches(self)
        br_rem_a = Branch.open(self.get_readonly_url('branch1'))
        fetch_steps(self, br_rem_a, br_b, br_a)

    def _count_log_matches(self, target, logs):
        """Count the number of times the target file pattern was fetched in an http log"""
        log_pattern = '%s HTTP/1.1" 200 - "-" "bzr/%s' % \
            (target, bzrlib.__version__)
        c = 0
        for line in logs:
            # TODO: perhaps use a regexp instead so we can match more
            # precisely?
            if line.find(log_pattern) > -1:
                c += 1
        return c

    def test_weaves_are_retrieved_once(self):
        self.build_tree(("source/", "source/file", "target/"))
        wt = self.make_branch_and_tree('source')
        branch = wt.branch
        wt.add(["file"], ["id"])
        wt.commit("added file")
        print >>open("source/file", 'w'), "blah"
        wt.commit("changed file")
        target = BzrDir.create_branch_and_repo("target/")
        source = Branch.open(self.get_readonly_url("source/"))
        self.assertEqual(target.fetch(source), (2, []))
        log_pattern = '%%s HTTP/1.1" 200 - "-" "bzr/%s' % bzrlib.__version__
        # this is the path to the literal file. As format changes 
        # occur it needs to be updated. FIXME: ask the store for the
        # path.
        self.log("web server logs are:")
        http_logs = self.get_readonly_server().logs
        self.log('\n'.join(http_logs))
        self.assertEqual(1, self._count_log_matches('weaves/ce/id.weave', http_logs))
        self.assertEqual(1, self._count_log_matches('inventory.weave', http_logs))
        # this r-h check test will prevent regressions, but it currently already 
        # passes, before the patch to cache-rh is applied :[
        self.assertEqual(1, self._count_log_matches('revision-history', http_logs))
        # FIXME naughty poking in there.
        self.get_readonly_server().logs = []
        # check there is nothing more to fetch
        source = Branch.open(self.get_readonly_url("source/"))
        self.assertEqual(target.fetch(source), (0, []))
        # should make just two requests
        http_logs = self.get_readonly_server().logs
        self.log("web server logs are:")
        self.log('\n'.join(http_logs))
        self.assertEqual(1, self._count_log_matches('branch-format', http_logs))
        self.assertEqual(1, self._count_log_matches('branch/format', http_logs))
        self.assertEqual(1, self._count_log_matches('repository/format', http_logs))
        self.assertEqual(1, self._count_log_matches('revision-history', http_logs))
        self.assertEqual(4, len(http_logs))
