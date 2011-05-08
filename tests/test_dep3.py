#    test_dep3.py -- Testsuite for builddeb dep3.py
#    Copyright (C) 2011 Canonical Ltd.
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

from cStringIO import StringIO

import rfc822

from bzrlib.tests import TestCase

from bzrlib.plugins.builddeb.dep3 import (
    write_dep3_bug_line,
    write_dep3_patch_header,
    )


class Dep3HeaderTests(TestCase):

    def dep3_header(self, description=None, bugs=None, authors=None,
            revision_id=None, last_update=None):
        f = StringIO()
        write_dep3_patch_header(f, description=description, bugs=bugs,
            authors=authors, revision_id=revision_id, last_update=last_update)
        f.seek(0)
        return rfc822.Message(f)

    def test_description(self):
        ret = self.dep3_header(description="This patch fixes the foobar")
        self.assertEquals("This patch fixes the foobar", ret["Description"])

    def test_last_updated(self):
        ret = self.dep3_header(last_update=1304840034)
        self.assertEquals("2011-05-08", ret["Last-Update"])

    def test_revision_id(self):
        ret = self.dep3_header(revision_id="myrevid")
        self.assertEquals("myrevid", ret["X-Bzr-Revision-Id"])

    def test_authors(self):
        authors = [
            "Jelmer Vernooij <jelmer@canonical.com>",
            "James Westby <james.westby@canonical.com>"]
        ret = self.dep3_header(authors=authors)
        self.assertEquals([
            ("Jelmer Vernooij", "jelmer@canonical.com"),
            ("James Westby", "james.westby@canonical.com")],
            ret.getaddrlist("Author"))

    def test_write_bug_fix_only(self):
        # non-fixed bug lines are ignored
        f = StringIO()
        write_dep3_bug_line(f, "http://bar/", "pending")
        self.assertEquals("", f.getvalue())

    def test_write_normal_bug(self):
        f = StringIO()
        write_dep3_bug_line(f, "http://bugzilla.samba.org/bug.cgi?id=42",
            "fixed")
        self.assertEquals("Bug: http://bugzilla.samba.org/bug.cgi?id=42\n",
            f.getvalue())

    def test_write_debian_bug(self):
        f = StringIO()
        write_dep3_bug_line(f, "http://bugs.debian.org/234354", "fixed")
        self.assertEquals("Bug-Debian: http://bugs.debian.org/234354\n",
            f.getvalue())
