# Copyright (C) 2009 Canonical Ltd
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Pyrex implementation of _read_stanza_*."""

#python2.4 support
cdef extern from "python-compat.h":
    pass

cdef extern from "Python.h":
    ctypedef int Py_ssize_t # Required for older pyrex versions
    struct _PyObject:
        pass
    ctypedef _PyObject PyObject
    char *PyString_AS_STRING(object s)
    Py_ssize_t PyString_GET_SIZE(object t) except -1
    object PyUnicode_DecodeUTF8(char *string, Py_ssize_t length, char *errors)
    Py_ssize_t PyUnicode_GET_SIZE(object t) except -1
    int PyUnicode_Resize(PyObject **o, Py_ssize_t size) except -1
    object PyString_FromStringAndSize(char *s, Py_ssize_t len)
    int PyString_CheckExact(object)
    int PyUnicode_CheckExact(object)
    void Py_INCREF(object)
    void Py_DECREF(object)
    object PyList_GetItem(object, int)
    int PyList_SetItem(object, int, object) except -1
    int PyList_Size(object) except -1
    object PyUnicode_Join(object, object)
    object PyUnicode_AsASCIIString(object)
    int PyList_Append(object, object) except -1    


from bzrlib.rio import Stanza

cdef int _valid_tag_char(char c):
    return (c == c'_' or c == c'-' or 
            (c >= c'a' and c <= c'z') or
            (c >= c'A' and c <= c'Z') or
            (c >= c'0' and c <= c'9'))


def _valid_tag(tag):
    cdef char *c_tag
    cdef Py_ssize_t c_len
    cdef int i
    if not PyString_CheckExact(tag):
        raise TypeError(tag)
    c_tag = PyString_AS_STRING(tag)
    c_len = PyString_GET_SIZE(tag)
    for i from 0 <= i < c_len:
        if not _valid_tag_char(c_tag[i]):
            return False
    return True

cdef object _join_utf8_strip(object entries):
    """Join a set of unicode strings and strip the last character."""
    cdef PyObject *c_ret
    cdef Py_ssize_t size
    # TODO: This creates a new object just without the last character. 
    # Ideally, we should just resize it by -1
    entries[-1] = entries[-1][:-1]
    return PyUnicode_Join(unicode(""), entries)


cdef object _split_first_line(char *line, int len):
    cdef int i
    for i from 0 <= i < len:
        if line[i] == c':':
            if line[i+1] != c' ':
                raise ValueError("invalid tag in line %r" % line)
            return (PyString_FromStringAndSize(line, i),
                    PyUnicode_DecodeUTF8(line+i+2, len-i-2, "strict"))
    raise ValueError('tag/value separator not found in line %r' % line)


def _read_stanza_utf8(line_iter):
    cdef char *c_line, *colon
    cdef Py_ssize_t c_len
    pairs = []
    tag = None
    accum_value = []

    # TODO: jam 20060922 This code should raise real errors rather than
    #       using 'assert' to process user input, or raising ValueError
    #       rather than a more specific error.
    for line in line_iter:
        if line is None:
            break # end of file
        if not PyString_CheckExact(line):
            raise TypeError("%r is not a line" % line)
        c_line = PyString_AS_STRING(line)
        c_len = PyString_GET_SIZE(line)
        if c_len < 1:
            break       # end of file
        if c_len == 1 and c_line[0] == c"\n":
            break       # end of stanza
        if c_line[0] == c'\t': # continues previous value
            if tag is None:
                raise ValueError('invalid continuation line %r' % line)
            new_value = PyUnicode_DecodeUTF8(c_line+1, c_len-1, "strict")
        else: # new tag:value line
            if tag is not None:
                PyList_Append(pairs, (tag, _join_utf8_strip(accum_value)))
            accum_value = []
            (tag, new_value) = _split_first_line(c_line, c_len)
            if not _valid_tag(tag):
                raise ValueError("invalid rio tag %r" % (tag,))
        accum_value.append(new_value)
    if tag is not None: # add last tag-value
        PyList_Append(pairs, (tag, _join_utf8_strip(accum_value)))
        return Stanza.from_pairs(pairs)
    else:     # didn't see any content
        return None


def _read_stanza_unicode(unicode_iter):
    cdef int colon_index
    pairs = []
    tag = None
    accum_value = []

    # TODO: jam 20060922 This code should raise real errors rather than
    #       using 'assert' to process user input, or raising ValueError
    #       rather than a more specific error.
    for line in unicode_iter:
        if line is None or line == unicode(''):
            break       # end of file
        if line == unicode('\n'):
            break       # end of stanza
        if line[0] == unicode('\t'): # continues previous value
            if tag is None:
                raise ValueError('invalid continuation line %r' % line)
            PyList_Append(accum_value, line[1:])
        else: # new tag:value line
            if tag is not None:
                PyList_Append(pairs, (tag, _join_utf8_strip(accum_value)))
            try:
                colon_index = line.index(unicode(': '))
            except ValueError:
                raise ValueError('tag/value separator not found in line %r'
                                 % line)
            tag = PyUnicode_AsASCIIString(line[0:colon_index])
            if not _valid_tag(tag):
                raise ValueError("invalid rio tag %r" % (tag,))
            accum_value = [line[colon_index+2:]]

    if tag is not None: # add last tag-value
        PyList_Append(pairs, (tag, _join_utf8_strip(accum_value)))
        return Stanza.from_pairs(pairs)
    else:     # didn't see any content
        return None


