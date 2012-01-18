#    __init__.py -- The plugin for bzr
#    Copyright (C) 2005 Jamie Wilkinson <jaq@debian.org> 
#                  2006, 2007 James Westby <jw+debian@jameswestby.net>
#                  2007 Reinhard Tartler <siretart@tauware.de>
#                  2008 Canonical Ltd.
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
#

"""bzr-builddeb - manage packages in a Bazaar branch."""

from __future__ import absolute_import

import os

import bzrlib
from bzrlib.commands import plugin_cmds
from bzrlib.directory_service import (
    AliasDirectory,
    directories,
    )

from bzrlib.plugins.builddeb.info import (
    bzr_plugin_version as version_info,
    )


try:
    from bzrlib.i18n import load_plugin_translations
except ImportError: # No translations for bzr < 2.5
    gettext = lambda x: x
else:
    translation = load_plugin_translations("bzr-builddeb")
    gettext = translation.ugettext

commands = {
        "builddeb_do": ["bd-do"],
        "builddeb": ["bd"],
        "get_orig_source": [],
        "dep3_patch": [],
        "dh_make": ["dh_make"],
        "import_dsc": [],
        "import_upstream": [],
        "mark_uploaded": [],
        "merge_package": [],
        "merge_upstream": ["mu"],
        }

for command, aliases in commands.iteritems():
    plugin_cmds.register_lazy('cmd_' + command, aliases, 
        "bzrlib.plugins.builddeb.cmds")

builddeb_dir = '.bzr-builddeb'
default_conf = os.path.join(builddeb_dir, 'default.conf')
def global_conf():
    from bzrlib.config import config_dir
    return os.path.join(config_dir(), 'builddeb.conf')
local_conf = os.path.join(builddeb_dir, 'local.conf')
new_local_conf = 'debian/local.conf.local'
new_conf = 'debian/bzr-builddeb.conf'

default_build_dir = '../build-area'
default_orig_dir = '..'
default_result_dir = '..'


directories.register_lazy("apt:", 'bzrlib.plugins.builddeb.directory',
        'VcsDirectory',
        "Directory that uses Debian Vcs-* control fields to look up branches")

branch_aliases = getattr(AliasDirectory, "branch_aliases", None)
if branch_aliases is not None:
    def upstream_branch_alias(b):
        from bzrlib.plugins.builddeb.util import debuild_config
        b.lock_read()
        try:
            tree = b.basis_tree()
            config = debuild_config(tree, False)
            return directories.dereference(config.upstream_branch)
        finally:
            b.unlock()
    branch_aliases.register("upstream", upstream_branch_alias,
        help="upstream branch (for packaging branches)")


def debian_changelog_commit_message(commit, start_message):
    if start_message is not None:
        return start_message
    cl_path = "debian/changelog"
    if not commit.work_tree.has_filename(cl_path):
        return start_message
    if commit.work_tree.path2id(cl_path) is None:
        return start_message
    if cl_path in commit.exclude:
        return start_message
    if commit.specific_files and cl_path not in commit.specific_files:
        return start_message
    changes = []
    for change in commit.work_tree.iter_changes(commit.work_tree.basis_tree(),
            specific_files=[cl_path]):
        # Content not changed
        if not change[2]:
            return start_message
        # Not versioned in new tree
        if not change[3][1]:
            return start_message
        # Not a file in one tree
        if change[6][0] != 'file' or change[6][1] != 'file':
            return start_message
        old_text = commit.work_tree.basis_tree().get_file(change[0],
                path=change[1][0]).readlines()
        new_text = commit.work_tree.get_file(change[0],
                path=change[1][1]).readlines()
        import difflib
        sequencematcher = difflib.SequenceMatcher
        for group in sequencematcher(None, old_text,
                new_text).get_grouped_opcodes(0):
            j1, j2 = group[0][3], group[-1][4]
            for line in new_text[j1:j2]:
                if line.startswith("  "):
                    changes.append(line)
    if not changes:
        return start_message
    from bzrlib.plugins.builddeb.util import strip_changelog_message
    changes = strip_changelog_message(changes)
    return "".join(changes)


def debian_changelog_commit(commit, start_message):
    """hooked into bzrlib.msgeditor set_commit_message.
     Set the commit message from debian/changelog and set any LP: #1234 to bug
     fixed tags."""
    from bzrlib.plugins.builddeb.util import (
        debuild_config, find_bugs_fixed)

    t = commit.work_tree
    config = debuild_config(t, False)
    if config.commit_message_from_changelog == False:
        return None

    changes = debian_changelog_commit_message(commit, start_message)
    if changes is None:
        return None

    bugs_fixed = find_bugs_fixed([changes], commit.work_tree.branch)
    commit.builder._revprops["bugs"] = "\n".join(bugs_fixed)

    # Debian Policy Manual states that debian/changelog must be UTF-8
    return changes.decode("utf-8")


def changelog_merge_hook_factory(merger):
    from bzrlib.plugins.builddeb import merge_changelog
    return merge_changelog.ChangeLogFileMerge(merger)


def debian_tag_name(branch, revid):
    from bzrlib.plugins.builddeb.config import BUILD_TYPE_MERGE
    from bzrlib.plugins.builddeb.errors import MissingChangelogError
    from bzrlib.plugins.builddeb.import_dsc import (DistributionBranch,
        DistributionBranchSet)
    from bzrlib.plugins.builddeb.util import debuild_config, find_changelog
    t = branch.repository.revision_tree(revid)
    config = debuild_config(t, False)
    try:
        (changelog, top_level) = find_changelog(t, config.build_type == BUILD_TYPE_MERGE)
    except MissingChangelogError:
        # Not a debian package
        return None
    if changelog.distributions == 'UNRELEASED':
        # The changelog still targets 'UNRELEASED', so apparently hasn't been 
        # uploaded. XXX: Give a warning of some sort here?
        return None
    db = DistributionBranch(branch, None)
    dbs = DistributionBranchSet()
    dbs.add_branch(db)
    return db.tag_name(changelog.version)


def start_commit_check_quilt(tree):
    """start_commit hook which checks the state of quilt patches.
    """
    if tree.path2id("debian/patches") is None:
        # No patches to worry about
        return
    from bzrlib.plugins.builddeb.merge_quilt import start_commit_quilt_patches
    start_commit_quilt_patches(tree)


def pre_merge(merger):
    pre_merge_fix_ancestry(merger)
    pre_merge_quilt(merger)


def pre_merge_quilt(merger):
    if getattr(merger, "_no_quilt_unapplying", False):
        return
    if (merger.other_tree.path2id("debian/patches") is None and
        merger.this_tree.path2id("debian/patches") is None and
        merger.working_tree.path2id("debian/patches") is None):
        return

    from bzrlib import trace
    from bzrlib.plugins.builddeb.util import debuild_config
    config = debuild_config(merger.working_tree, merger.working_tree)
    merger.debuild_config = config
    if not config.quilt_smart_merge:
        trace.mutter("skipping smart quilt merge, not enabled.")
        return

    import shutil
    from bzrlib.plugins.builddeb.errors import QuiltUnapplyError
    from bzrlib.plugins.builddeb.quilt import quilt_pop_all, QuiltError
    from bzrlib.plugins.builddeb.merge_quilt import tree_unapply_patches
    trace.note("Unapplying quilt patches to prevent spurious conflicts")
    merger._quilt_tempdirs = []
    series_file_id = merger.working_tree.path2id("debian/patches/series")
    if series_file_id is not None:
        merger._old_quilt_series = merger.working_tree.get_file_lines(series_file_id)
    if series_file_id is not None:
        quilt_pop_all(working_dir=merger.working_tree.basedir)
    try:
        merger.this_tree, this_dir = tree_unapply_patches(merger.this_tree,
            merger.this_branch)
    except QuiltError, e:
        shutil.rmtree(this_dir)
        raise QuiltUnapplyError("this", e.msg)
    else:
        if this_dir is not None:
            merger._quilt_tempdirs.append(this_dir)
    try:
        merger.base_tree, base_dir = tree_unapply_patches(merger.base_tree,
            merger.this_branch)
    except QuiltError, e:
        shutil.rmtree(base_dir)
        raise QuiltUnapplyError("base", e.msg)
    else:
        if base_dir is not None:
            merger._quilt_tempdirs.append(base_dir)
    other_branch = getattr(merger, "other_branch", None)
    if other_branch is None:
        other_branch = merger.this_branch
    try:
        merger.other_tree, other_dir = tree_unapply_patches(merger.other_tree,
            other_branch)
    except QuiltError, e:
        shutil.rmtree(other_dir)
        raise QuiltUnapplyError("other", e.msg)
    else:
        if other_dir is not None:
            merger._quilt_tempdirs.append(other_dir)


def post_merge_quilt_cleanup(merger):
    import shutil
    for dir in getattr(merger, "_quilt_tempdirs", []):
        shutil.rmtree(dir)
    config = getattr(merger, "debuild_config", None)
    if config is None:
        # If there is no debuild config, then pre_merge didn't get far enough.
        return
    policy = config.quilt_tree_policy
    if policy is None:
        return
    from bzrlib.plugins.builddeb.merge_quilt import post_process_quilt_patches
    post_process_quilt_patches(
        merger.working_tree,
        getattr(merger, "_old_quilt_series", []), policy)


def post_build_tree_quilt(tree):
    from bzrlib.plugins.builddeb.util import debuild_config
    config = debuild_config(tree, tree)
    policy = config.quilt_tree_policy
    if policy is None:
        return
    from bzrlib.plugins.builddeb.merge_quilt import post_process_quilt_patches
    from bzrlib import trace
    trace.note("Applying quilt patches.");
    post_process_quilt_patches(tree, [], policy)


def pre_merge_fix_ancestry(merger):
    from bzrlib.plugins.builddeb.config import BUILD_TYPE_NATIVE
    from bzrlib.plugins.builddeb.util import debuild_config
    from bzrlib.plugins.builddeb.merge_package import fix_ancestry_as_needed
    from bzrlib.workingtree import WorkingTree
    if not isinstance(merger.this_tree, WorkingTree):
        return
    if getattr(merger, "other_branch", None) is None:
        return
    if (not merger.this_tree.path2id("debian/changelog") or
        not merger.other_tree.path2id("debian/changelog")):
        return
    this_config = debuild_config(merger.this_tree, merger.this_tree)
    other_config = debuild_config(merger.other_tree, merger.other_tree)
    if not (this_config.build_type == BUILD_TYPE_NATIVE or
            other_config.build_type == BUILD_TYPE_NATIVE):
        from bzrlib import trace
        from bzrlib.plugins.builddeb.errors import PackageVersionNotPresent
        try:
            fix_ancestry_as_needed(merger.this_tree, merger.other_branch,
                source_revid=merger.other_tree.get_revision_id())
        except PackageVersionNotPresent, e:
            trace.warning("Not fixing branch ancestry, missing pristine tar "
                "data for version %s", e.version)


try:
    from bzrlib.hooks import install_lazy_named_hook
except ImportError: # Compatibility with bzr < 2.4
    from bzrlib import (
        branch as _mod_branch,
        errors,
        merge,
        msgeditor,
        )
    msgeditor.hooks.install_named_hook("commit_message_template",
            debian_changelog_commit_message,
            "Use changes documented in debian/changelog to suggest "
            "the commit message")
    if getattr(merge, 'ConfigurableFileMerger', None) is None:
        raise ImportError(
            'need at least bzr 2.1.0rc2 (you use %r)', bzrlib.version_info)
    else:
        merge.Merger.hooks.install_named_hook(
            'merge_file_content', changelog_merge_hook_factory,
            'Debian Changelog file merge')
    try:
        _mod_branch.Branch.hooks.install_named_hook("automatic_tag_name",
             debian_tag_name,
             "Automatically determine tag names from Debian version")
    except errors.UnknownHook:
        pass # bzr < 2.2 doesn't have this hook.
else:
    install_lazy_named_hook(
        "bzrlib.msgeditor", "hooks", "commit_message_template",
            debian_changelog_commit_message,
            "Use changes documented in debian/changelog to suggest "
            "the commit message")
    if bzrlib.version_info[0] >= 2 and bzrlib.version_info[1] >= 4:
        install_lazy_named_hook(
            "bzrlib.msgeditor", "hooks", "set_commit_message",
                debian_changelog_commit,
                "Use changes documented in debian/changelog to set "
                "the commit message and bugs fixed")
    install_lazy_named_hook(
        "bzrlib.merge", "Merger.hooks",
        'merge_file_content', changelog_merge_hook_factory,
        'Debian Changelog file merge')
    install_lazy_named_hook(
        "bzrlib.branch", "Branch.hooks",
        "automatic_tag_name", debian_tag_name,
         "Automatically determine tag names from Debian version")
    install_lazy_named_hook(
        "bzrlib.merge", "Merger.hooks",
        'pre_merge', pre_merge,
        'Debian quilt patch (un)applying and ancestry fixing')
    install_lazy_named_hook(
        "bzrlib.merge", "Merger.hooks",
        'post_merge', post_merge_quilt_cleanup,
        'Cleaning up quilt temporary directories')
    install_lazy_named_hook(
        "bzrlib.mutabletree", "MutableTree.hooks",
        'post_build_tree', post_build_tree_quilt,
        'Applying quilt patches.')
    install_lazy_named_hook(
        "bzrlib.mutabletree", "MutableTree.hooks",
        "start_commit", start_commit_check_quilt,
        "Check for (un)applied quilt patches")

try:
    from bzrlib.revisionspec import revspec_registry
    revspec_registry.register_lazy("package:",
        "bzrlib.plugins.builddeb.revspec", "RevisionSpec_package")
    revspec_registry.register_lazy("upstream:",
        "bzrlib.plugins.builddeb.revspec", "RevisionSpec_upstream")
except ImportError:
    from bzrlib.revisionspec import SPEC_TYPES
    from bzrlib.plugins.builddeb.revspec import (
        RevisionSpec_package,
        RevisionSpec_upstream,
        )
    SPEC_TYPES.extend([RevisionSpec_package, RevisionSpec_upstream])

try:
    from bzrlib.tag import tag_sort_methods
except ImportError:
    pass # bzr tags --sort= can not be extended
else:
    tag_sort_methods.register_lazy("debversion",
        "bzrlib.plugins.builddeb.tagging", "sort_debversion",
        "Sort like Debian versions.")


def load_tests(standard_tests, module, loader):
    return loader.loadTestsFromModuleNames(['bzrlib.plugins.builddeb.tests'])
