# Copyright (C) 2010 Canonical Ltd
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

import os
import sys

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
from fnmatch import fnmatch
import re
from cStringIO import StringIO

from termcolor import color_string, re_color_string, FG

from bzrlib.workingtree import WorkingTree
from bzrlib.revision import Revision
from bzrlib.revisionspec import (
    RevisionSpec,
    RevisionSpec_revid,
    RevisionSpec_revno,
    RevisionInfo,
    )
from bzrlib import (
    bzrdir,
    diff,
    errors,
    lazy_regex,
    osutils,
    revision as _mod_revision,
    textfile,
    trace,
    )
""")

_terminal_encoding = osutils.get_terminal_encoding()
_user_encoding = osutils.get_user_encoding()


class _RevisionNotLinear(Exception):
    """Raised when a revision is not on left-hand history."""


def _rev_on_mainline(rev_tuple):
    """returns True is rev tuple is on mainline"""
    if len(rev_tuple) == 1:
        return True
    return rev_tuple[1] == 0 and rev_tuple[2] == 0


# NOTE: _linear_view_revisions is basided on
# bzrlib.log._linear_view_revisions.
# This should probably be a common public API
def _linear_view_revisions(branch, start_rev_id, end_rev_id):
    # requires that start is older than end
    repo = branch.repository
    for revision_id in repo.iter_reverse_revision_history(end_rev_id):
        revno = branch.revision_id_to_dotted_revno(revision_id)
        revno_str = '.'.join(str(n) for n in revno)
        if revision_id == start_rev_id:
            yield revision_id, revno_str, 0
            break
        yield revision_id, revno_str, 0


# NOTE: _graph_view_revisions is copied from
# bzrlib.log._graph_view_revisions.
# This should probably be a common public API
def _graph_view_revisions(branch, start_rev_id, end_rev_id,
                          rebase_initial_depths=True):
    """Calculate revisions to view including merges, newest to oldest.

    :param branch: the branch
    :param start_rev_id: the lower revision-id
    :param end_rev_id: the upper revision-id
    :param rebase_initial_depth: should depths be rebased until a mainline
      revision is found?
    :return: An iterator of (revision_id, dotted_revno, merge_depth) tuples.
    """
    # requires that start is older than end
    view_revisions = branch.iter_merge_sorted_revisions(
        start_revision_id=end_rev_id, stop_revision_id=start_rev_id,
        stop_rule="with-merges")
    if not rebase_initial_depths:
        for (rev_id, merge_depth, revno, end_of_merge
             ) in view_revisions:
            yield rev_id, '.'.join(map(str, revno)), merge_depth
    else:
        # We're following a development line starting at a merged revision.
        # We need to adjust depths down by the initial depth until we find
        # a depth less than it. Then we use that depth as the adjustment.
        # If and when we reach the mainline, depth adjustment ends.
        depth_adjustment = None
        for (rev_id, merge_depth, revno, end_of_merge
             ) in view_revisions:
            if depth_adjustment is None:
                depth_adjustment = merge_depth
            if depth_adjustment:
                if merge_depth < depth_adjustment:
                    # From now on we reduce the depth adjustement, this can be
                    # surprising for users. The alternative requires two passes
                    # which breaks the fast display of the first revision
                    # though.
                    depth_adjustment = merge_depth
                merge_depth -= depth_adjustment
            yield rev_id, '.'.join(map(str, revno)), merge_depth


def compile_pattern(pattern, flags=0):
    patternc = None
    try:
        # use python's re.compile as we need to catch re.error in case of bad pattern
        lazy_regex.reset_compile()
        patternc = re.compile(pattern, flags)
    except re.error, e:
        raise errors.BzrError("Invalid pattern: '%s'" % pattern)
    return patternc


def is_fixed_string(s):
    if re.match("^([A-Za-z0-9_]|\s)*$", s):
        return True
    return False


def grep_diff(opts):
    wt, branch, relpath = \
        bzrdir.BzrDir.open_containing_tree_or_branch('.')
    branch.lock_read()
    try:
        if opts.revision:
            start_rev = opts.revision[0]
        else:
            opts.revision = [RevisionSpec.from_string('last:1')]
            start_rev = opts.revision[0]
        start_revid = start_rev.as_revision_id(branch)
        if start_revid == 'null:':
            return
        srevno_tuple = branch.revision_id_to_dotted_revno(start_revid)
        if len(opts.revision) == 2:
            end_rev = opts.revision[1]
            end_revid = end_rev.as_revision_id(branch)
            if end_revid == None:
                end_revno, end_revid = branch.last_revision_info()
            erevno_tuple = branch.revision_id_to_dotted_revno(end_revid)

            grep_mainline = (_rev_on_mainline(srevno_tuple) and
                _rev_on_mainline(erevno_tuple))

            # ensure that we go in reverse order
            if srevno_tuple > erevno_tuple:
                srevno_tuple, erevno_tuple = erevno_tuple, srevno_tuple
                start_revid, end_revid = end_revid, start_revid

            # Optimization: Traversing the mainline in reverse order is much
            # faster when we don't want to look at merged revs. We try this
            # with _linear_view_revisions. If all revs are to be grepped we
            # use the slower _graph_view_revisions
            if opts.levels==1 and grep_mainline:
                given_revs = _linear_view_revisions(branch, start_revid, end_revid)
            else:
                given_revs = _graph_view_revisions(branch, start_revid, end_revid)
        else:
            # We do an optimization below. For grepping a specific revison
            # We don't need to call _graph_view_revisions which is slow.
            # We create the start_rev_tuple for only that specific revision.
            # _graph_view_revisions is used only for revision range.
            start_revno = '.'.join(map(str, srevno_tuple))
            start_rev_tuple = (start_revid, start_revno, 0)
            given_revs = [start_rev_tuple]
        repo = branch.repository
        diff_pattern = re.compile("^[+\-].*(" + opts.pattern + ")")
        file_pattern = re.compile("=== (modified|added) file '.*'", re.UNICODE)
        for revid, revno, merge_depth in given_revs:
            if opts.levels == 1 and merge_depth != 0:
                # with level=1 show only top level
                continue

            rev_spec = RevisionSpec_revid.from_string("revid:"+revid)
            new_rev = repo.get_revision(revid)
            new_tree = rev_spec.as_tree(branch)
            if len(new_rev.parent_ids) == 0:
                ancestor_id = _mod_revision.NULL_REVISION
            else:
                ancestor_id = new_rev.parent_ids[0]
            old_tree = repo.revision_tree(ancestor_id)
            s = StringIO()
            diff.show_diff_trees(old_tree, new_tree, s,
                old_label='', new_label='')
            display_revno = True
            display_file = False
            file_header = None
            text = s.getvalue()
            for line in text.splitlines():
                if file_pattern.search(line):
                    file_header = line
                    display_file = True
                if diff_pattern.search(line):
                    if display_revno:
                        print "===", "revno:"+revno, "==="
                        display_revno = False
                    if display_file:
                        print "  " + file_header
                        display_file = False
                    print "    " + line
    finally:
        branch.unlock()


def versioned_grep(opts):
    wt, branch, relpath = \
        bzrdir.BzrDir.open_containing_tree_or_branch('.')
    branch.lock_read()
    try:
        start_rev = opts.revision[0]
        start_revid = start_rev.as_revision_id(branch)
        if start_revid == None:
            start_rev = RevisionSpec_revno.from_string("revno:1")
            start_revid = start_rev.as_revision_id(branch)
        srevno_tuple = branch.revision_id_to_dotted_revno(start_revid)

        if len(opts.revision) == 2:
            end_rev = opts.revision[1]
            end_revid = end_rev.as_revision_id(branch)
            if end_revid == None:
                end_revno, end_revid = branch.last_revision_info()
            erevno_tuple = branch.revision_id_to_dotted_revno(end_revid)

            grep_mainline = (_rev_on_mainline(srevno_tuple) and
                _rev_on_mainline(erevno_tuple))

            # ensure that we go in reverse order
            if srevno_tuple > erevno_tuple:
                srevno_tuple, erevno_tuple = erevno_tuple, srevno_tuple
                start_revid, end_revid = end_revid, start_revid

            # Optimization: Traversing the mainline in reverse order is much
            # faster when we don't want to look at merged revs. We try this
            # with _linear_view_revisions. If all revs are to be grepped we
            # use the slower _graph_view_revisions
            if opts.levels==1 and grep_mainline:
                given_revs = _linear_view_revisions(branch, start_revid, end_revid)
            else:
                given_revs = _graph_view_revisions(branch, start_revid, end_revid)
        else:
            # We do an optimization below. For grepping a specific revison
            # We don't need to call _graph_view_revisions which is slow.
            # We create the start_rev_tuple for only that specific revision.
            # _graph_view_revisions is used only for revision range.
            start_revno = '.'.join(map(str, srevno_tuple))
            start_rev_tuple = (start_revid, start_revno, 0)
            given_revs = [start_rev_tuple]

        # GZ 2010-06-02: Shouldn't be smuggling this on opts, but easy for now
        opts.outputter = _Outputter(opts, use_cache=True)

        for revid, revno, merge_depth in given_revs:
            if opts.levels == 1 and merge_depth != 0:
                # with level=1 show only top level
                continue

            rev = RevisionSpec_revid.from_string("revid:"+revid)
            tree = rev.as_tree(branch)
            for path in opts.path_list:
                path_for_id = osutils.pathjoin(relpath, path)
                id = tree.path2id(path_for_id)
                if not id:
                    trace.warning("Skipped unknown file '%s'." % path)
                    continue

                if osutils.isdir(path):
                    path_prefix = path
                    dir_grep(tree, path, relpath, opts, revno, path_prefix)
                else:
                    versioned_file_grep(tree, id, '.', path, opts, revno)
    finally:
        branch.unlock()


def workingtree_grep(opts):
    revno = opts.print_revno = None # for working tree set revno to None

    tree, branch, relpath = \
        bzrdir.BzrDir.open_containing_tree_or_branch('.')
    if not tree:
        msg = ('Cannot search working tree. Working tree not found.\n'
            'To search for specific revision in history use the -r option.')
        raise errors.BzrCommandError(msg)

    # GZ 2010-06-02: Shouldn't be smuggling this on opts, but easy for now
    opts.outputter = _Outputter(opts)

    tree.lock_read()
    try:
        for path in opts.path_list:
            if osutils.isdir(path):
                path_prefix = path
                dir_grep(tree, path, relpath, opts, revno, path_prefix)
            else:
                _file_grep(open(path).read(), path, opts, revno)
    finally:
        tree.unlock()


def _skip_file(include, exclude, path):
    if include and not _path_in_glob_list(path, include):
        return True
    if exclude and _path_in_glob_list(path, exclude):
        return True
    return False


def dir_grep(tree, path, relpath, opts, revno, path_prefix):
    # setup relpath to open files relative to cwd
    rpath = relpath
    if relpath:
        rpath = osutils.pathjoin('..',relpath)

    from_dir = osutils.pathjoin(relpath, path)
    if opts.from_root:
        # start searching recursively from root
        from_dir=None
        recursive=True

    to_grep = []
    to_grep_append = to_grep.append
    # GZ 2010-06-05: The cache dict used to be recycled every call to dir_grep
    #                and hits manually refilled. Could do this again if it was
    #                for a good reason, otherwise cache might want purging.
    outputter = opts.outputter
    for fp, fc, fkind, fid, entry in tree.list_files(include_root=False,
        from_dir=from_dir, recursive=opts.recursive):

        if _skip_file(opts.include, opts.exclude, fp):
            continue

        if fc == 'V' and fkind == 'file':
            if revno != None:
                # If old result is valid, print results immediately.
                # Otherwise, add file info to to_grep so that the
                # loop later will get chunks and grep them
                cache_id = tree.inventory[fid].revision
                if cache_id in outputter.cache:
                    # GZ 2010-06-05: Not really sure caching and re-outputting
                    #                the old path is really the right thing,
                    #                but it's what the old code seemed to do
                    outputter.write_cached_lines(cache_id, revno)
                else:
                    to_grep_append((fid, (fp, fid)))
            else:
                # we are grepping working tree.
                if from_dir == None:
                    from_dir = '.'

                path_for_file = osutils.pathjoin(tree.basedir, from_dir, fp)
                if opts.files_with_matches or opts.files_without_match:
                    # Optimize for wtree list-only as we don't need to read the
                    # entire file
                    file = open(path_for_file, 'r', buffering=4096)
                    _file_grep_list_only_wtree(file, fp, opts, path_prefix)
                else:
                    file_text = open(path_for_file, 'r').read()
                    _file_grep(file_text, fp, opts, revno, path_prefix)

    if revno != None: # grep versioned files
        for (path, fid), chunks in tree.iter_files_bytes(to_grep):
            path = _make_display_path(relpath, path)
            _file_grep(chunks[0], path, opts, revno, path_prefix,
                tree.inventory[fid].revision)


def _make_display_path(relpath, path):
    """Return path string relative to user cwd.

    Take tree's 'relpath' and user supplied 'path', and return path
    that can be displayed to the user.
    """
    if relpath:
        # update path so to display it w.r.t cwd
        # handle windows slash separator
        path = osutils.normpath(osutils.pathjoin(relpath, path))
        path = path.replace('\\', '/')
        path = path.replace(relpath + '/', '', 1)
    return path


def versioned_file_grep(tree, id, relpath, path, opts, revno, path_prefix = None):
    """Create a file object for the specified id and pass it on to _file_grep.
    """

    path = _make_display_path(relpath, path)
    file_text = tree.get_file_text(id)
    _file_grep(file_text, path, opts, revno, path_prefix)


def _path_in_glob_list(path, glob_list):
    for glob in glob_list:
        if fnmatch(path, glob):
            return True
    return False


def _file_grep_list_only_wtree(file, path, opts, path_prefix=None):
    # test and skip binary files
    if '\x00' in file.read(1024):
        if opts.verbose:
            trace.warning("Binary file '%s' skipped." % path)
        return

    file.seek(0) # search from beginning

    found = False
    if opts.fixed_string:
        pattern = opts.pattern.encode(_user_encoding, 'replace')
        for line in file:
            if pattern in line:
                found = True
                break
    else: # not fixed_string
        for line in file:
            if opts.patternc.search(line):
                found = True
                break

    if (opts.files_with_matches and found) or \
        (opts.files_without_match and not found):
        if path_prefix and path_prefix != '.':
            # user has passed a dir arg, show that as result prefix
            path = osutils.pathjoin(path_prefix, path)
        opts.outputter.get_writer(path, None, None)()


class _Outputter(object):
    """Precalculate formatting based on options given

    The idea here is to do this work only once per run, and finally return a
    function that will do the minimum amount possible for each match.
    """
    def __init__(self, opts, use_cache=False):
        self.outf = opts.outf
        if use_cache:
            # self.cache is used to cache results for dir grep based on fid.
            # If the fid is does not change between results, it means that
            # the result will be the same apart from revno. In such a case
            # we avoid getting file chunks from repo and grepping. The result
            # is just printed by replacing old revno with new one.
            self.cache = {}
        else:
            self.cache = None
        no_line = opts.files_with_matches or opts.files_without_match

        if opts.show_color:
            pat = opts.pattern.encode(_user_encoding, 'replace')
            if no_line:
                self.get_writer = self._get_writer_plain
            elif opts.fixed_string:
                self._old = pat
                self._new = color_string(pat, FG.BOLD_RED)
                self.get_writer = self._get_writer_fixed_highlighted
            else:
                flags = opts.patternc.flags
                self._sub = re.compile(pat.join(("((?:",")+)")), flags).sub
                self._highlight = color_string("\\1", FG.BOLD_RED)
                self.get_writer = self._get_writer_regexp_highlighted
            path_start = FG.MAGENTA
            path_end = FG.NONE
            sep = color_string(':', FG.BOLD_CYAN)
            rev_sep = color_string('~', FG.BOLD_YELLOW)
        else:
            self.get_writer = self._get_writer_plain
            path_start = path_end = ""
            sep = ":"
            rev_sep = "~"

        parts = [path_start, "%(path)s"]
        if opts.print_revno:
            parts.extend([rev_sep, "%(revno)s"])
        self._format_initial = "".join(parts)
        parts = []
        if no_line:
            if not opts.print_revno:
                parts.append(path_end)
        else:
            if opts.line_number:
                parts.extend([sep, "%(lineno)s"])
            parts.extend([sep, "%(line)s"])
        parts.append(opts.eol_marker)
        self._format_perline = "".join(parts)

    def _get_writer_plain(self, path, revno, cache_id):
        """Get function for writing uncoloured output"""
        per_line = self._format_perline
        start = self._format_initial % {"path":path, "revno":revno}
        write = self.outf.write
        if self.cache is not None and cache_id is not None:
            result_list = []
            self.cache[cache_id] = path, result_list
            add_to_cache = result_list.append
            def _line_cache_and_writer(**kwargs):
                """Write formatted line and cache arguments"""
                end = per_line % kwargs
                add_to_cache(end)
                write(start + end)
            return _line_cache_and_writer
        def _line_writer(**kwargs):
            """Write formatted line from arguments given by underlying opts"""
            write(start + per_line % kwargs)
        return _line_writer

    def write_cached_lines(self, cache_id, revno):
        """Write cached results out again for new revision"""
        cached_path, cached_matches = self.cache[cache_id]
        start = self._format_initial % {"path":cached_path, "revno":revno}
        write = self.outf.write
        for end in cached_matches:
            write(start + end)

    def _get_writer_regexp_highlighted(self, path, revno, cache_id):
        """Get function for writing output with regexp match highlighted"""
        _line_writer = self._get_writer_plain(path, revno, cache_id)
        sub, highlight = self._sub, self._highlight
        def _line_writer_regexp_highlighted(line, **kwargs):
            """Write formatted line with matched pattern highlighted"""
            return _line_writer(line=sub(highlight, line), **kwargs)
        return _line_writer_regexp_highlighted

    def _get_writer_fixed_highlighted(self, path, revno, cache_id):
        """Get function for writing output with search string highlighted"""
        _line_writer = self._get_writer_plain(path, revno, cache_id)
        old, new = self._old, self._new
        def _line_writer_fixed_highlighted(line, **kwargs):
            """Write formatted line with string searched for highlighted"""
            return _line_writer(line=line.replace(old, new), **kwargs)
        return _line_writer_fixed_highlighted


def _file_grep(file_text, path, opts, revno, path_prefix=None, cache_id=None):
    # test and skip binary files
    if '\x00' in file_text[:1024]:
        if opts.verbose:
            trace.warning("Binary file '%s' skipped." % path)
        return

    if path_prefix and path_prefix != '.':
        # user has passed a dir arg, show that as result prefix
        path = osutils.pathjoin(path_prefix, path)

    # GZ 2010-06-07: There's no actual guarentee the file contents will be in
    #                the user encoding, but we have to guess something and it
    #                is a reasonable default without a better mechanism.
    file_encoding = _user_encoding
    pattern = opts.pattern.encode(_user_encoding, 'replace')

    writeline = opts.outputter.get_writer(path, revno, cache_id)

    if opts.files_with_matches or opts.files_without_match:
        if opts.fixed_string:
            if sys.platform > (2, 5):
                found = pattern in file_text
            else:
                for line in file_text.splitlines():
                    if pattern in line:
                        found = True
                        break
                else:
                    found = False
        else:
            search = opts.patternc.search
            if "$" not in pattern:
                found = search(file_text) is not None
            else:
                for line in file_text.splitlines():
                    if search(line):
                        found = True
                        break
                else:
                    found = False
        if (opts.files_with_matches and found) or \
                (opts.files_without_match and not found):
            writeline()
    elif opts.fixed_string:
        # Fast path for no match, search through the entire file at once rather
        # than a line at a time. However, we don't want this without Python 2.5
        # as the quick string search algorithm wasn't implemented till then:
        # <http://effbot.org/zone/stringlib.htm>
        if sys.version_info > (2, 5):
            i = file_text.find(pattern)
            if i == -1:
                return
            b = file_text.rfind("\n", 0, i) + 1
            if opts.line_number:
                start = file_text.count("\n", 0, b) + 1
            file_text = file_text[b:]
        else:
            start = 1
        if opts.line_number:
            for index, line in enumerate(file_text.splitlines()):
                if pattern in line:
                    line = line.decode(file_encoding, 'replace')
                    writeline(lineno=index+start, line=line)
        else:
            for line in file_text.splitlines():
                if pattern in line:
                    line = line.decode(file_encoding, 'replace')
                    writeline(line=line)
    else:
        # Fast path on no match, the re module avoids bad behaviour in most
        # standard cases, but perhaps could try and detect backtracking
        # patterns here and avoid whole text search in those cases
        search = opts.patternc.search
        if "$" not in pattern:
            # GZ 2010-06-05: Grr, re.MULTILINE can't save us when searching
            #                through revisions as bazaar returns binary mode
            #                and trailing \r breaks $ as line ending match
            m = search(file_text)
            if m is None:
                return
            b = file_text.rfind("\n", 0, m.start()) + 1
            if opts.line_number:
                start = file_text.count("\n", 0, b) + 1
            file_text = file_text[b:]
        else:
            start = 1
        if opts.line_number:
            for index, line in enumerate(file_text.splitlines()):
                if search(line):
                    line = line.decode(file_encoding, 'replace')
                    writeline(lineno=index+start, line=line)
        else:
            for line in file_text.splitlines():
                if search(line):
                    line = line.decode(file_encoding, 'replace')
                    writeline(line=line)

