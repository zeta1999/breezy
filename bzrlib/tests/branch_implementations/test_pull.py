# Copyright (C) 2004, 2005 Canonical Ltd
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

"""Tests for branch.pull behaviour."""

import os

from bzrlib.branch import Branch
from bzrlib import errors
from bzrlib.tests import TestCaseWithTransport


class TestPull(TestCaseWithTransport):

    def test_pull_convergence_simple(self):
        # when revisions are pulled, the left-most accessible parents must 
        # become the revision-history.
        parent = self.make_branch_and_tree('parent')
        parent.commit('1st post', rev_id='P1', allow_pointless=True)
        mine = parent.bzrdir.sprout('mine').open_workingtree()
        mine.commit('my change', rev_id='M1', allow_pointless=True)
        parent.merge_from_branch(mine.branch)
        parent.commit('merge my change', rev_id='P2')
        mine.pull(parent.branch)
        self.assertEqual(['P1', 'P2'], mine.branch.revision_history())

    def test_pull_merged_indirect(self):
        # it should be possible to do a pull from one branch into another
        # when the tip of the target was merged into the source branch
        # via a third branch - so its buried in the ancestry and is not
        # directly accessible.
        parent = self.make_branch_and_tree('parent')
        parent.commit('1st post', rev_id='P1', allow_pointless=True)
        mine = parent.bzrdir.sprout('mine').open_workingtree()
        mine.commit('my change', rev_id='M1', allow_pointless=True)
        other = parent.bzrdir.sprout('other').open_workingtree()
        other.merge_from_branch(mine.branch)
        other.commit('merge my change', rev_id='O2')
        parent.merge_from_branch(other.branch)
        parent.commit('merge other', rev_id='P2')
        mine.pull(parent.branch)
        self.assertEqual(['P1', 'P2'], mine.branch.revision_history())

    def test_pull_updates_checkout_and_master(self):
        """Pulling into a checkout updates the checkout and the master branch"""
        master_tree = self.make_branch_and_tree('master')
        rev1 = master_tree.commit('master')
        checkout = master_tree.branch.create_checkout('checkout')

        other = master_tree.branch.bzrdir.sprout('other').open_workingtree()
        rev2 = other.commit('other commit')
        # now pull, which should update both checkout and master.
        checkout.branch.pull(other.branch)
        self.assertEqual([rev1, rev2], checkout.branch.revision_history())
        self.assertEqual([rev1, rev2], master_tree.branch.revision_history())

    def test_pull_raises_specific_error_on_master_connection_error(self):
        master_tree = self.make_branch_and_tree('master')
        checkout = master_tree.branch.create_checkout('checkout')
        other = master_tree.branch.bzrdir.sprout('other').open_workingtree()
        # move the branch out of the way on disk to cause a connection
        # error.
        os.rename('master', 'master_gone')
        # try to pull, which should raise a BoundBranchConnectionFailure.
        self.assertRaises(errors.BoundBranchConnectionFailure,
                checkout.branch.pull, other.branch)
