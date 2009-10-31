# Copyright (C) 2005, 2006, 2009 Canonical Ltd
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


"""Inventory/revision serialization."""


from bzrlib import registry


class Serializer(object):
    """Inventory and revision serialization/deserialization."""

    squashes_xml_invalid_characters = False

    def write_inventory(self, inv, f):
        """Write inventory to a file.

        Note: this is a *whole inventory* operation, and should only be used
        sparingly, as it does not scale well with large trees.
        """
        raise NotImplementedError(self.write_inventory)

    def write_inventory_to_string(self, inv):
        """Produce a simple string representation of an inventory.

        Note: this is a *whole inventory* operation, and should only be used
        sparingly, as it does not scale well with large trees.

        The requirement for the contents of the string is that it can be passed
        to read_inventory_from_string and the result is an identical inventory
        in memory.

        (All serializers as of 2009-07-29 produce XML, but this is not mandated
        by the interface.)
        """
        raise NotImplementedError(self.write_inventory_to_string)

    def read_inventory_from_string(self, string, revision_id=None,
                                   entry_cache=None):
        """Read string into an inventory object.

        :param string: The serialized inventory to read.
        :param revision_id: If not-None, the expected revision id of the
            inventory. Some serialisers use this to set the results' root
            revision. This should be supplied for deserialising all
            from-repository inventories so that xml5 inventories that were
            serialised without a revision identifier can be given the right
            revision id (but not for working tree inventories where users can
            edit the data without triggering checksum errors or anything).
        :param entry_cache: An optional cache of InventoryEntry objects. If
            supplied we will look up entries via (file_id, revision_id) which
            should map to a valid InventoryEntry (File/Directory/etc) object.
        """
        raise NotImplementedError(self.read_inventory_from_string)

    def read_inventory(self, f, revision_id=None):
        """See read_inventory_from_string."""
        raise NotImplementedError(self.read_inventory)

    def write_revision(self, rev, f):
        raise NotImplementedError(self.write_revision)

    def write_revision_to_string(self, rev):
        raise NotImplementedError(self.write_revision_to_string)

    def read_revision(self, f):
        raise NotImplementedError(self.read_revision)

    def read_revision_from_string(self, xml_string):
        raise NotImplementedError(self.read_revision_from_string)


class SerializerRegistry(registry.Registry):
    """Registry for serializer objects"""


format_registry = SerializerRegistry()
format_registry.register_lazy('4', 'bzrlib.xml4', 'serializer_v4')
format_registry.register_lazy('5', 'bzrlib.xml5', 'serializer_v5')
format_registry.register_lazy('6', 'bzrlib.xml6', 'serializer_v6')
format_registry.register_lazy('7', 'bzrlib.xml7', 'serializer_v7')
format_registry.register_lazy('8', 'bzrlib.xml8', 'serializer_v8')
format_registry.register_lazy('9', 'bzrlib.chk_serializer',
    'chk_serializer_255_bigpage')
format_registry.register_lazy('10', 'bzrlib.chk_serializer',
    'chk_bencode_serializer')
