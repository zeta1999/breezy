# Copyright (C) 2006 Jelmer Vernooij <jelmer@samba.org>

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
"""Cache of the Subversion history log."""

from bzrlib.errors import NoSuchRevision
import bzrlib.ui as ui

import os

from svn.core import SubversionException, Pool
from transport import SvnRaTransport
import svn.core

import base64

try:
    import sqlite3
except ImportError:
    from pysqlite2 import dbapi2 as sqlite3

def _escape_commit_message(message):
    """Replace xml-incompatible control characters."""
    if message is None:
        return None
    import re
    # FIXME: RBC 20060419 this should be done by the revision
    # serialiser not by commit. Then we can also add an unescaper
    # in the deserializer and start roundtripping revision messages
    # precisely. See repository_implementations/test_repository.py
    
    # Python strings can include characters that can't be
    # represented in well-formed XML; escape characters that
    # aren't listed in the XML specification
    # (http://www.w3.org/TR/REC-xml/#NT-Char).
    message, _ = re.subn(
        u'[^\x09\x0A\x0D\u0020-\uD7FF\uE000-\uFFFD]+',
        lambda match: match.group(0).encode('unicode_escape'),
        message)
    return message


class LogWalker(object):
    """Easy way to access the history of a Subversion repository."""
    def __init__(self, transport=None, cache_db=None, last_revnum=None):
        """Create a new instance.

        :param transport:   SvnRaTransport to use to access the repository.
        :param cache_db:    Optional sql database connection to use. Doesn't 
                            cache if not set.
        :param last_revnum: Last known revnum in the repository. Will be 
                            determined if not specified.
        """
        assert isinstance(transport, SvnRaTransport)

        if last_revnum is None:
            last_revnum = transport.get_latest_revnum()

        self.last_revnum = last_revnum

        self.transport = SvnRaTransport(transport.base)

        if cache_db is None:
            self.db = sqlite3.connect(":memory:")
        else:
            self.db = cache_db

        self.db.executescript("""
          create table if not exists revision(revno integer unique, author text, message text, date text);
          create unique index if not exists revision_revno on revision (revno);
          create table if not exists changed_path(rev integer, action text, path text, copyfrom_path text, copyfrom_rev integer);
          create index if not exists path_rev on changed_path(rev);
          create index if not exists path_rev_path on changed_path(rev, path);
        """)
        self.db.commit()
        self.saved_revnum = self.db.execute("SELECT MAX(revno) FROM revision").fetchone()[0]
        if self.saved_revnum is None:
            self.saved_revnum = 0

    def fetch_revisions(self, to_revnum):
        """Fetch information about all revisions in the remote repository
        until to_revnum.

        :param to_revnum: End of range to fetch information for
        """
        to_revnum = max(self.last_revnum, to_revnum)

        pb = ui.ui_factory.nested_progress_bar()

        def rcvr(orig_paths, rev, author, date, message, pool):
            pb.update('fetching svn revision info', rev, to_revnum)
            if orig_paths is None:
                orig_paths = {}
            for p in orig_paths:
                copyfrom_path = orig_paths[p].copyfrom_path
                if copyfrom_path:
                    copyfrom_path = copyfrom_path.strip("/")

                self.db.execute(
                     "insert into changed_path (rev, path, action, copyfrom_path, copyfrom_rev) values (?, ?, ?, ?, ?)", 
                     (rev, p.strip("/"), orig_paths[p].action, copyfrom_path, orig_paths[p].copyfrom_rev))

            if message is not None:
                message = base64.b64encode(message)

            self.db.execute("replace into revision (revno, author, date, message) values (?,?,?,?)", (rev, author, date, message))

            self.saved_revnum = rev
            if self.saved_revnum % 1000 == 0:
                self.db.commit()

        pool = Pool()
        try:
            try:
                self.transport.get_log("/", self.saved_revnum, to_revnum, 
                               0, True, True, rcvr, pool)
            finally:
                pb.finished()
        except SubversionException, (_, num):
            if num == svn.core.SVN_ERR_FS_NO_SUCH_REVISION:
                raise NoSuchRevision(branch=self, 
                    revision="Revision number %d" % to_revnum)
            raise
        self.db.commit()
        pool.destroy()

    def follow_path(self, path, revnum):
        """Return iterator over all the revisions between revnum and 
        0 named path or inside path.

        :param path:   Branch path to start reporting (in revnum)
        :param revnum:        Start revision.

        :return: An iterators that yields tuples with (path, paths, revnum)
        where paths is a dictionary with all changes that happened in path 
        in revnum.
        """
        assert revnum >= 0

        if revnum == 0 and path == "":
            return

        path = path.strip("/")

        while revnum > 0:
            revpaths = self.get_revision_paths(revnum, path)

            if revpaths != {}:
                yield (path, revpaths, revnum)

            if revpaths.has_key(path):
                if revpaths[path][1] is None:
                    if revpaths[path][0] in ('A', 'R'):
                        # this path didn't exist before this revision
                        return
                else:
                    # In this revision, this path was copied from 
                    # somewhere else
                    revnum = revpaths[path][2]
                    path = revpaths[path][1]
                    continue
            revnum -= 1

    def get_revision_paths(self, revnum, path=None):
        """Obtain dictionary with all the changes in a particular revision.

        :param revnum: Subversion revision number
        :param path: optional path under which to return all entries
        :returns: dictionary with paths as keys and 
                  (action, copyfrom_path, copyfrom_rev) as values.
        """

        if revnum == 0:
            return {'': ('A', None, -1)}
                
        if revnum > self.saved_revnum:
            self.fetch_revisions(revnum)

        query = "select path, action, copyfrom_path, copyfrom_rev from changed_path where rev="+str(revnum)
        if path is not None and path != "":
            query += " and (path='%s' or path like '%s/%%')" % (path, path)

        paths = {}
        for p, act, cf, cr in self.db.execute(query):
            paths[p] = (act, cf, cr)
        return paths

    def get_revision_info(self, revnum):
        """Obtain basic information for a specific revision.

        :param revnum: Revision number.
        :returns: Tuple with author, log message and date of the revision.
        """
        assert revnum >= 1
        if revnum > self.saved_revnum:
            self.fetch_revisions(revnum)
        (author, message, date) = self.db.execute("select author, message, date from revision where revno="+ str(revnum)).fetchone()
        return (author, _escape_commit_message(base64.b64decode(message)), date)

    def find_latest_change(self, path, revnum, recurse=False):
        """Find latest revision that touched path.

        :param path: Path to check for changes
        :param revnum: First revision to check
        """
        if revnum > self.saved_revnum:
            self.fetch_revisions(revnum)

        if recurse:
            extra = " or path like '%s/%%'" % path.strip("/")
        else:
            extra = ""
        query = "select rev from changed_path where (path='%s' or ('%s' like (path || '/%%') and (action = 'R' or action = 'A'))%s) and rev <= %d order by rev desc limit 1" % (path.strip("/"), path.strip("/"), extra, revnum)

        row = self.db.execute(query).fetchone()
        if row is None and path == "":
            return 0

        if row is None:
            return None

        return row[0]

    def touches_path(self, path, revnum):
        """Check whether path was changed in specified revision.

        :param path:  Path to check
        :param revnum:  Revision to check
        """
        if revnum > self.saved_revnum:
            self.fetch_revisions(revnum)
        if revnum == 0:
            return (path == "")
        return (self.db.execute("select 1 from changed_path where path='%s' and rev=%d" % (path, revnum)).fetchone() is not None)

    def find_children(self, path, revnum):
        """Find all children of path in revnum."""
        # TODO: Find children by walking history, or use 
        # cache?

        try:
            (dirents, _, _) = self.transport.get_dir(
                path.lstrip("/").encode('utf8'), revnum, kind=True)
        except SubversionException, (_, num):
            if num == svn.core.SVN_ERR_FS_NOT_DIRECTORY:
                return
            raise

        for p in dirents:
            yield os.path.join(path, p)
            # This needs to be != svn.core.svn_node_file because 
            # some ra backends seem to return negative values for .kind.
            # however, dirents[p].node seems to contain semi-random 
            # values.
            for c in self.find_children(os.path.join(path, p), revnum):
                yield c

    def get_previous(self, path, revnum):
        """Return path,revnum pair specified pair was derived from.

        :param path:  Path to check
        :param revnum:  Revision to check
        """
        assert revnum >= 0
        if revnum > self.saved_revnum:
            self.fetch_revisions(revnum)
        if revnum == 0:
            return (None, -1)
        row = self.db.execute("select action, copyfrom_path, copyfrom_rev from changed_path where path='%s' and rev=%d" % (path, revnum)).fetchone()
        if row[2] == -1:
            if row[0] == 'A':
                return (None, -1)
            return (path, revnum-1)
        return (row[1], row[2])
