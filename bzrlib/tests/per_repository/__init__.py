# Copyright (C) 2006-2010 Canonical Ltd
# Authors: Robert Collins <robert.collins@canonical.com>
#          and others
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


"""Repository implementation tests for bzr.

These test the conformance of all the repository variations to the expected API.
Specific tests for individual formats are in the tests/test_repository.py file
rather than in tests/per_branch/*.py.
"""

from bzrlib import (
    repository,
    )
from bzrlib.remote import RemoteRepositoryFormat
from bzrlib.tests import (
    default_transport,
    multiply_tests,
    test_server,
    )
from bzrlib.tests.per_controldir.test_controldir import TestCaseWithControlDir
from bzrlib.transport import memory


def formats_to_scenarios(formats, transport_server, transport_readonly_server,
    vfs_transport_factory=None):
    """Transform the input formats to a list of scenarios.

    :param formats: A list of (scenario_name_suffix, repo_format)
        where the scenario_name_suffix is to be appended to the format
        name, and the repo_format is a RepositoryFormat subclass
        instance.
    :returns: Scenarios of [(scenario_name, {parameter_name: value})]
    """
    result = []
    for scenario_name_suffix, repository_format in formats:
        scenario_name = repository_format.__class__.__name__
        scenario_name += scenario_name_suffix
        scenario = (scenario_name,
            {"transport_server":transport_server,
             "transport_readonly_server":transport_readonly_server,
             "bzrdir_format":repository_format._matchingbzrdir,
             "repository_format":repository_format,
             })
        # Only override the test's vfs_transport_factory if one was
        # specified, otherwise just leave the default in place.
        if vfs_transport_factory:
            scenario[1]['vfs_transport_factory'] = vfs_transport_factory
        result.append(scenario)
    return result


def all_repository_format_scenarios():
    """Return a list of test scenarios for parameterising repository tests.
    """
    all_formats = repository.format_registry._get_all()
    # format_scenarios is all the implementations of Repository; i.e. all disk
    # formats plus RemoteRepository.
    format_scenarios = formats_to_scenarios(
        [('', format) for format in all_formats],
        default_transport,
        # None here will cause a readonly decorator to be created
        # by the TestCaseWithTransport.get_readonly_transport method.
        None)
    format_scenarios.extend(formats_to_scenarios(
        [('-default', RemoteRepositoryFormat())],
        test_server.SmartTCPServer_for_testing,
        test_server.ReadonlySmartTCPServer_for_testing,
        memory.MemoryServer))
    format_scenarios.extend(formats_to_scenarios(
        [('-v2', RemoteRepositoryFormat())],
        test_server.SmartTCPServer_for_testing_v2_only,
        test_server.ReadonlySmartTCPServer_for_testing_v2_only,
        memory.MemoryServer))
    return format_scenarios


class TestCaseWithRepository(TestCaseWithControlDir):

    def make_repository(self, relpath, shared=False, format=None):
        if format is None:
            # Create a repository of the type we are trying to test.
            made_control = self.make_bzrdir(relpath)
            repo = self.repository_format.initialize(made_control,
                    shared=shared)
            if getattr(self, "repository_to_test_repository", None):
                repo = self.repository_to_test_repository(repo)
            return repo
        else:
            return super(TestCaseWithRepository, self).make_repository(
                relpath, shared=shared, format=format)


def load_tests(standard_tests, module, loader):
    prefix = 'bzrlib.tests.per_repository.'
    test_repository_modules = [
        'test_add_fallback_repository',
        'test_break_lock',
        'test_check',
        'test_commit_builder',
        'test_fetch',
        'test_fileid_involved',
        'test_get_parent_map',
        'test_has_same_location',
        'test_has_revisions',
        'test_is_write_locked',
        'test_iter_reverse_revision_history',
        'test_merge_directive',
        'test_pack',
        'test_reconcile',
        'test_refresh_data',
        'test_repository',
        'test_revision',
        'test_statistics',
        'test_write_group',
        ]
    # Parameterize per_repository test modules by format.
    submod_tests = loader.loadTestsFromModuleNames(
        [prefix + module_name for module_name in test_repository_modules])
    format_scenarios = all_repository_format_scenarios()
    return multiply_tests(submod_tests, format_scenarios, standard_tests)
