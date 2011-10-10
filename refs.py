# Copyright (C) 2010 Jelmer Vernooij <jelmer@samba.org>
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

"""Conversion between refs and Bazaar revision pointers."""

from dulwich.repo import (
    RefsContainer,
    )

from bzrlib import (
    errors,
    osutils,
    )

is_tag = lambda x: x.startswith("refs/tags/")


def extract_tags(refs):
    """Extract the tags from a refs dictionary.

    :param refs: Refs to extract the tags from.
    :return: Dictionary mapping tag names to SHA1s of the actual object
        and unpeeled object SHA1s.
    """
    ret = {}
    for k, v in refs.iteritems():
        if is_tag(k) and not k.endswith("^{}"):
            try:
                peeled = refs[k+"^{}"]
                unpeeled = v
            except KeyError:
                peeled = v
                unpeeled = None
            try:
                tagname = ref_to_tag_name(k)
            except UnicodeDecodeError:
                pass
            else:
                ret[tagname] = (peeled, unpeeled)
    return ret


def branch_name_to_ref(name, default=None):
    """Map a branch name to a ref.

    :param name: Branch name
    :return: ref string
    """
    if name is None:
        return default
    if name == "HEAD":
        return osutils.safe_utf8(name)
    if not name.startswith("refs/"):
        return "refs/heads/%s" % osutils.safe_utf8(name)
    else:
        return osutils.safe_utf8(name)


def tag_name_to_ref(name):
    """Map a tag name to a ref.

    :param name: Tag name
    :return: ref string
    """
    return "refs/tags/%s" % osutils.safe_utf8(name)


def ref_to_branch_name(ref):
    """Map a ref to a branch name

    :param ref: Ref
    :return: A branch name
    """
    if ref in (None, "HEAD"):
        return ref
    if ref.startswith("refs/heads/"):
        return osutils.safe_unicode(ref[len("refs/heads/"):])
    raise ValueError("unable to map ref %s back to branch name" % ref)


def ref_to_tag_name(ref):
    if ref.startswith("refs/tags/"):
        return ref[len('refs/tags/'):].decode("utf-8")
    raise ValueError("unable to map ref %s back to tag name" % ref)


class BazaarRefsContainer(RefsContainer):

    def __init__(self, dir, object_store):
        self.dir = dir
        self.object_store = object_store

    def set_symbolic_ref(self, name, other):
        if name == "HEAD":
            pass # FIXME: Switch default branch
        else:
            raise NotImplementedError(
                "Symbolic references not supported for anything other than "
                "HEAD")

    def _get_revid_by_tag_name(self, tag_name):
        for branch in self.dir.list_branches():
            try:
                # FIXME: This is ambiguous!
                return branch.tags.lookup_tag(tag_name)
            except errors.NoSuchTag:
                pass
        return None

    def _get_revid_by_branch_name(self, branch_name):
        try:
            branch = self.dir.open_branch(branch_name)
        except errors.NoColocatedBranchSupport:
            if branch_name in ("HEAD", "master"):
                branch = self.dir.open_branch()
            else:
                raise
        return branch.last_revision()

    def read_loose_ref(self, ref):
        try:
            branch_name = ref_to_branch_name(ref)
        except ValueError:
            tag_name = ref_to_tag_name(ref)
            revid = self._get_revid_by_tag_name(tag_name)
        else:
            revid = self._get_revid_by_branch_name(branch_name)
        return self.object_store._lookup_revision_sha1(revid)

    def allkeys(self):
        keys = set()
        for branch in self.dir.list_branches():
            repo = branch.repository
            if repo.has_revision(branch.last_revision()):
                ref = branch_name_to_ref(branch.name, "refs/heads/master")
                keys.add(ref)
                if branch.name is None:
                    keys.add("HEAD")
            for tag_name, revid in branch.tags.get_tag_dict().iteritems():
                if repo.has_revision(revid):
                    keys.add(tag_name_to_ref(tag_name))
        return keys

    def __delitem__(self, ref):
        try:
            branch_name = ref_to_branch_name(ref)
        except ValueError:
            return # FIXME: Cope with tags!
        self.dir.destroy_branch(branch_name)

    def __setitem__(self, ref, sha):
        try:
            branch_name = ref_to_branch_name(ref)
        except ValueError:
            # FIXME: Cope with tags!
            return
        try:
            target_branch = self.repo_dir.open_branch(branch_name)
        except errors.NotBranchError:
            target_branch = self.repo.create_branch(branch_name)

        rev_id = self.mapping.revision_id_foreign_to_bzr(sha)
        target_branch.lock_write()
        try:
            target_branch.generate_revision_history(rev_id)
        finally:
            target_branch.unlock()