# Copyright (C) 2005, 2006 Canonical

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

from bzrlib.inventory import InventoryEntry
from bzrlib.trace import mutter

class TreeDelta(object):
    """Describes changes from one tree to another.

    Contains four lists:

    added
        (path, id, kind)
    removed
        (path, id, kind)
    renamed
        (oldpath, newpath, id, kind, text_modified, meta_modified)
    modified
        (path, id, kind, text_modified, meta_modified)
    unchanged
        (path, id, kind)

    Each id is listed only once.

    Files that are both modified and renamed are listed only in
    renamed, with the text_modified flag true. The text_modified
    applies either to the the content of the file or the target of the
    symbolic link, depending of the kind of file.

    Files are only considered renamed if their name has changed or
    their parent directory has changed.  Renaming a directory
    does not count as renaming all its contents.

    The lists are normally sorted when the delta is created.
    """
    def __init__(self):
        self.added = []
        self.removed = []
        self.renamed = []
        self.modified = []
        self.unchanged = []

    def __eq__(self, other):
        if not isinstance(other, TreeDelta):
            return False
        return self.added == other.added \
               and self.removed == other.removed \
               and self.renamed == other.renamed \
               and self.modified == other.modified \
               and self.unchanged == other.unchanged

    def __ne__(self, other):
        return not (self == other)

    def __repr__(self):
        return "TreeDelta(added=%r, removed=%r, renamed=%r, modified=%r," \
            " unchanged=%r)" % (self.added, self.removed, self.renamed,
            self.modified, self.unchanged)

    def has_changed(self):
        return bool(self.modified
                    or self.added
                    or self.removed
                    or self.renamed)

    def touches_file_id(self, file_id):
        """Return True if file_id is modified by this delta."""
        for l in self.added, self.removed, self.modified:
            for v in l:
                if v[1] == file_id:
                    return True
        for v in self.renamed:
            if v[2] == file_id:
                return True
        return False
            

    def show(self, to_file, show_ids=False, show_unchanged=False):
        def show_list(files):
            for item in files:
                path, fid, kind = item[:3]

                if kind == 'directory':
                    path += '/'
                elif kind == 'symlink':
                    path += '@'

                if len(item) == 5 and item[4]:
                    path += '*'

                if show_ids:
                    print >>to_file, '  %-30s %s' % (path, fid)
                else:
                    print >>to_file, ' ', path
            
        if self.removed:
            print >>to_file, 'removed:'
            show_list(self.removed)
                
        if self.added:
            print >>to_file, 'added:'
            show_list(self.added)

        extra_modified = []

        if self.renamed:
            print >>to_file, 'renamed:'
            for (oldpath, newpath, fid, kind,
                 text_modified, meta_modified) in self.renamed:
                if text_modified or meta_modified:
                    extra_modified.append((newpath, fid, kind,
                                           text_modified, meta_modified))
                if meta_modified:
                    newpath += '*'
                if show_ids:
                    print >>to_file, '  %s => %s %s' % (oldpath, newpath, fid)
                else:
                    print >>to_file, '  %s => %s' % (oldpath, newpath)
                    
        if self.modified or extra_modified:
            print >>to_file, 'modified:'
            show_list(self.modified)
            show_list(extra_modified)
            
        if show_unchanged and self.unchanged:
            print >>to_file, 'unchanged:'
            show_list(self.unchanged)



def compare_trees(old_tree, new_tree, want_unchanged=False, specific_files=None):
    """Describe changes from one tree to another.

    Returns a TreeDelta with details of added, modified, renamed, and
    deleted entries.

    The root entry is specifically exempt.

    This only considers versioned files.

    want_unchanged
        If true, also list files unchanged from one version to
        the next.

    specific_files
        If true, only check for changes to specified names or
        files within them.  Any unversioned files given have no effect
        (but this might change in the future).
    """
    # NB: show_status depends on being able to pass in non-versioned files and
    # report them as unknown
    old_tree.lock_read()
    try:
        new_tree.lock_read()
        try:
            return _compare_trees(old_tree, new_tree, want_unchanged,
                                  specific_files)
        finally:
            new_tree.unlock()
    finally:
        old_tree.unlock()


def _compare_trees(old_tree, new_tree, want_unchanged, specific_files):

    from osutils import is_inside_any
    
    old_inv = old_tree.inventory
    new_inv = new_tree.inventory
    delta = TreeDelta()
    mutter('start compare_trees')

    # TODO: Rather than iterating over the whole tree and then filtering, we
    # could diff just the specified files (if any) and their subtrees.  
    # Perhaps should take a list of file-ids instead?   Need to indicate any
    # ids or names which were not found in the trees.

    old_files = old_tree.list_files()
    new_files = new_tree.list_files()

    more_old = True
    more_new = True

    added = {}
    removed = {}

    def get_next(iter):
        try:
            return iter.next()
        except StopIteration:
            return None, None, None, None, None
    old_path, old_class, old_kind, old_file_id, old_entry = get_next(old_files)
    new_path, new_class, new_kind, new_file_id, new_entry = get_next(new_files)


    def check_matching(old_path, old_entry, new_path, new_entry):
        """We have matched up 2 file_ids, check for changes."""
        assert old_entry.kind == new_entry.kind

        if old_entry.kind == 'root_directory':
            return

        if specific_files:
            if (not is_inside_any(specific_files, old_path)
                and not is_inside_any(specific_files, new_path)):
                return

        # temporary hack until all entries are populated before clients 
        # get them
        old_entry._read_tree_state(old_path, old_tree)
        new_entry._read_tree_state(new_path, new_tree)
        text_modified, meta_modified = new_entry.detect_changes(old_entry)
        
        # If the name changes, or the parent_id changes, we have a rename
        # (if we move a parent, that doesn't count as a rename for the file)
        if (old_entry.name != new_entry.name 
            or old_entry.parent_id != new_entry.parent_id):
            delta.renamed.append((old_path,
                                  new_path,
                                  old_entry.file_id, old_entry.kind,
                                  text_modified, meta_modified))
        elif text_modified or meta_modified:
            delta.modified.append((new_path, new_entry.file_id, new_entry.kind,
                                   text_modified, meta_modified))
        elif want_unchanged:
            delta.unchanged.append((new_path, new_entry.file_id, new_entry.kind))


    def handle_old(path, entry):
        """old entry without a new entry match"""
        if entry.file_id in added:
            # Actually this is a rename, we found a new file_id earlier
            # at a different location, so it is no-longer added
            x_new_path, x_new_entry = added.pop(entry.file_id)
            check_matching(path, entry, x_new_path, x_new_entry)
        else:
            # We have an old_file_id which doesn't line up with a new_file_id
            # So this file looks to be removed
            assert entry.file_id not in removed
            removed[entry.file_id] = path, entry

    def handle_new(path, entry):
        """new entry without an old entry match"""
        if entry.file_id in removed:
            # We saw this file_id earlier at an old different location
            # it is no longer removed, just renamed
            x_old_path, x_old_entry = removed.pop(entry.file_id)
            check_matching(x_old_path, x_old_entry, path, entry)
        else:
            # We have a new file which does not match an old file
            # mark it as added
            assert entry.file_id not in added
            added[entry.file_id] = path, entry

    while old_path or new_path:
        # list_files() returns files in alphabetical path sorted order
        if old_path == new_path:
            if old_file_id == new_file_id:
                # This is the common case, the files are in the same place
                # check if there were any content changes

                if old_file_id is None:
                    # We have 2 unversioned files, no deltas possible???
                    pass
                else:
                    check_matching(old_path, old_entry, new_path, new_entry)
            else:
                # The ids don't match, so we have to handle them both
                # separately.
                if old_file_id is not None:
                    handle_old(old_path, old_entry)

                if new_file_id is not None:
                    handle_new(new_path, new_entry)

            # The two entries were at the same path, so increment both sides
            old_path, old_class, old_kind, old_file_id, old_entry = get_next(old_files)
            new_path, new_class, new_kind, new_file_id, new_entry = get_next(new_files)
        elif new_path is None or (old_path is not None and old_path < new_path):
            # Assume we don't match, only process old_path
            if old_file_id is not None:
                handle_old(old_path, old_entry)
            # old_path came first, so increment it, trying to match up
            old_path, old_class, old_kind, old_file_id, old_entry = get_next(old_files)
        elif new_path is not None:
            # new_path came first, so increment it, trying to match up
            if new_file_id is not None:
                handle_new(new_path, new_entry)
            new_path, new_class, new_kind, new_file_id, new_entry = get_next(new_files)

    # Now we have a set of added and removed files, mark them all
    for old_path, old_entry in removed.itervalues():
        if specific_files:
            if not is_inside_any(specific_files, old_path):
                continue
        delta.removed.append((old_path, old_entry.file_id, old_entry.kind))
    for new_path, new_entry in added.itervalues():
        if specific_files:
            if not is_inside_any(specific_files, new_path):
                continue
        delta.added.append((new_path, new_entry.file_id, new_entry.kind))

    delta.removed.sort()
    delta.added.sort()
    delta.renamed.sort()
    delta.modified.sort()
    delta.unchanged.sort()

    return delta
