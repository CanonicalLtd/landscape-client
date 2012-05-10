from landscape.package.skeleton import (
    build_skeleton_apt, DEB_PROVIDES,
    DEB_NAME_PROVIDES, DEB_REQUIRES, DEB_OR_REQUIRES, DEB_UPGRADES,
    DEB_CONFLICTS)

from landscape.package.tests.helpers import (
    AptFacadeHelper, HASH1, create_simple_repository, create_deb,
    PKGNAME_MINIMAL, PKGDEB_MINIMAL, HASH_MINIMAL, PKGNAME_SIMPLE_RELATIONS,
    PKGDEB_SIMPLE_RELATIONS, HASH_SIMPLE_RELATIONS, PKGNAME_VERSION_RELATIONS,
    PKGDEB_VERSION_RELATIONS, HASH_VERSION_RELATIONS,
    PKGNAME_MULTIPLE_RELATIONS, PKGDEB_MULTIPLE_RELATIONS,
    HASH_MULTIPLE_RELATIONS, PKGNAME_OR_RELATIONS, PKGDEB_OR_RELATIONS,
    HASH_OR_RELATIONS)
from landscape.tests.helpers import LandscapeTest


class SkeletonTestHelper(object):
    """A helper to set up a repository for the skeleton tests."""

    def set_up(self, test_case):
        test_case.skeleton_repository_dir = test_case.makeDir()
        create_simple_repository(test_case.skeleton_repository_dir)
        create_deb(
            test_case.skeleton_repository_dir, PKGNAME_MINIMAL, PKGDEB_MINIMAL)
        create_deb(
            test_case.skeleton_repository_dir, PKGNAME_SIMPLE_RELATIONS,
            PKGDEB_SIMPLE_RELATIONS)
        create_deb(
            test_case.skeleton_repository_dir, PKGNAME_VERSION_RELATIONS,
            PKGDEB_VERSION_RELATIONS)
        create_deb(
            test_case.skeleton_repository_dir, PKGNAME_MULTIPLE_RELATIONS,
            PKGDEB_MULTIPLE_RELATIONS)
        create_deb(
            test_case.skeleton_repository_dir, PKGNAME_OR_RELATIONS,
            PKGDEB_OR_RELATIONS)


class SkeletonAptTest(LandscapeTest):
    """C{PackageSkeleton} tests for apt packages."""

    helpers = [AptFacadeHelper, SkeletonTestHelper]

    def setUp(self):
        super(SkeletonAptTest, self).setUp()
        self.facade.add_channel_deb_dir(self.skeleton_repository_dir)
        # Don't use reload_channels(), since that causes the test setup
        # depending on build_skeleton_apt working correctly, which makes
        # it harder to to TDD for these tests.
        self.facade._cache.open(None)
        self.facade._cache.update(None)
        self.facade._cache.open(None)

    def get_package(self, name):
        """Return the package with the specified name."""
        # Don't use get_packages(), since that causes the test setup
        # depending on build_skeleton_apt working correctly, which makes
        # it harder to to TDD for these tests.
        package = self.facade._cache[name]
        return package.candidate

    def build_skeleton(self, *args, **kwargs):
        """Build the skeleton to be tested."""
        return build_skeleton_apt(*args, **kwargs)

    def test_build_skeleton(self):
        """
        C{build_skeleton} builds a C{PackageSkeleton} from a package. If
        with_info isn't passed, C{section}, C{summary}, C{description},
        C{size} and C{installed_size} will be C{None}.
        """
        pkg1 = self.get_package("name1")
        skeleton = self.build_skeleton(pkg1)
        self.assertEqual("name1", skeleton.name)
        self.assertEqual("version1-release1", skeleton.version)
        self.assertEqual(None, skeleton.section)
        self.assertEqual(None, skeleton.summary)
        self.assertEqual(None, skeleton.description)
        self.assertEqual(None, skeleton.size)
        self.assertEqual(None, skeleton.installed_size)
        relations = [
            (DEB_PROVIDES, "providesname1"),
            (DEB_NAME_PROVIDES, "name1 = version1-release1"),
            (DEB_REQUIRES, "prerequirename1 = prerequireversion1"),
            (DEB_REQUIRES, "requirename1 = requireversion1"),
            (DEB_UPGRADES, "name1 < version1-release1"),
            (DEB_CONFLICTS, "conflictsname1 = conflictsversion1")]
        self.assertEqual(relations, skeleton.relations)
        self.assertEqual(HASH1, skeleton.get_hash(), HASH1)

    def test_build_skeleton_without_unicode(self):
        """
        If C{with_unicode} isn't passed to C{build_skeleton}, the name
        and version of the skeleton are byte strings. The hash doesn't
        change, though.
        """
        pkg1 = self.get_package("name1")
        skeleton = self.build_skeleton(pkg1)
        self.assertTrue(isinstance(skeleton.name, str))
        self.assertTrue(isinstance(skeleton.version, str))
        self.assertEqual(HASH1, skeleton.get_hash())

    def test_build_skeleton_with_unicode(self):
        """
        If C{with_unicode} is passed to C{build_skeleton}, the name
        and version of the skeleton are unicode strings.
        """
        pkg1 = self.get_package("name1")
        skeleton = self.build_skeleton(pkg1, with_unicode=True)
        self.assertTrue(isinstance(skeleton.name, unicode))
        self.assertTrue(isinstance(skeleton.version, unicode))
        self.assertEqual(HASH1, skeleton.get_hash())

    def test_build_skeleton_with_info(self):
        """
        If C{with_info} is passed to C{build_skeleton}, C{section},
        C{summary}, C{description} and the size fields will be extracted
        from the package.
        """
        pkg1 = self.get_package("name1")
        skeleton = self.build_skeleton(pkg1, with_info=True)
        self.assertEqual("Group1", skeleton.section)
        self.assertEqual("Summary1", skeleton.summary)
        self.assertEqual("Description1", skeleton.description)
        self.assertEqual(1038, skeleton.size)
        self.assertEqual(28672, skeleton.installed_size)

    def test_build_skeleton_with_unicode_and_extra_info(self):
        """
        If C{with_unicode} and C{with_info} are passed to
        C{build_skeleton}, the name, version and the extra info of the
        skeleton are unicode strings.
        """
        pkg1 = self.get_package("name1")
        skeleton = self.build_skeleton(pkg1, with_unicode=True, with_info=True)
        self.assertTrue(isinstance(skeleton.name, unicode))
        self.assertTrue(isinstance(skeleton.version, unicode))
        self.assertTrue(isinstance(skeleton.section, unicode))
        self.assertTrue(isinstance(skeleton.summary, unicode))
        self.assertTrue(isinstance(skeleton.description, unicode))
        self.assertEqual(HASH1, skeleton.get_hash())

    def test_build_skeleton_minimal(self):
        """
        A package that has only the required fields will still have some
        relations defined.
        """
        minimal_package = self.get_package("minimal")
        skeleton = self.build_skeleton(minimal_package)
        self.assertEqual("minimal", skeleton.name)
        self.assertEqual("1.0", skeleton.version)
        self.assertEqual(None, skeleton.section)
        self.assertEqual(None, skeleton.summary)
        self.assertEqual(None, skeleton.description)
        self.assertEqual(None, skeleton.size)
        self.assertEqual(None, skeleton.installed_size)
        relations = [
            (DEB_NAME_PROVIDES, "minimal = 1.0"),
            (DEB_UPGRADES, "minimal < 1.0")]
        self.assertEqual(relations, skeleton.relations)
        self.assertEqual(HASH_MINIMAL, skeleton.get_hash())

    def test_build_skeleton_minimal_with_info(self):
        """
        If some fields that C{with_info} wants aren't there, they will
        be either an empty string or None, depending on which field.
        """
        package = self.get_package("minimal")
        skeleton = self.build_skeleton(package, True)
        self.assertEqual("", skeleton.section)
        self.assertEqual(
            "A minimal package with no dependencies or other relations.",
            skeleton.summary)
        self.assertEqual("", skeleton.description)
        self.assertEqual(558, skeleton.size)
        self.assertEqual(None, skeleton.installed_size)

    def test_build_skeleton_simple_relations(self):
        """
        Relations that are specified in the package control file can be
        simple, i.e. not specifying a version.
        """
        package = self.get_package("simple-relations")
        skeleton = self.build_skeleton(package)
        self.assertEqual("simple-relations", skeleton.name)
        self.assertEqual("1.0", skeleton.version)
        relations = [
            (DEB_PROVIDES, "provide1"),
            (DEB_NAME_PROVIDES, "simple-relations = 1.0"),
            (DEB_REQUIRES, "depend1"),
            (DEB_REQUIRES, "predepend1"),
            (DEB_UPGRADES, "simple-relations < 1.0"),
            (DEB_CONFLICTS, "break1"),
            (DEB_CONFLICTS, "conflict1")]
        self.assertEqual(relations, skeleton.relations)
        self.assertEqual(HASH_SIMPLE_RELATIONS, skeleton.get_hash())

    def test_build_skeleton_version_relations(self):
        """
        Relations that are specified in the package control file can be
        version dependent.
        """
        package = self.get_package("version-relations")
        skeleton = self.build_skeleton(package)
        self.assertEqual("version-relations", skeleton.name)
        self.assertEqual("1.0", skeleton.version)
        relations = [
            (DEB_PROVIDES, "provide1"),
            (DEB_NAME_PROVIDES, "version-relations = 1.0"),
            (DEB_REQUIRES, "depend1 = 2.0"),
            (DEB_REQUIRES, "predepend1 <= 2.0"),
            (DEB_UPGRADES, "version-relations < 1.0"),
            (DEB_CONFLICTS, "break1 > 2.0"),
            (DEB_CONFLICTS, "conflict1 < 2.0")]
        self.assertEqual(relations, skeleton.relations)
        self.assertEqual(HASH_VERSION_RELATIONS, skeleton.get_hash())

    def test_build_skeleton_multiple_relations(self):
        """
        The relations in the package control can have multiple values.
        In that case, one relation for each value is created in the
        skeleton.
        """
        package = self.get_package("multiple-relations")
        skeleton = self.build_skeleton(package)
        self.assertEqual("multiple-relations", skeleton.name)
        self.assertEqual("1.0", skeleton.version)
        relations = [
            (DEB_PROVIDES, "provide1"),
            (DEB_PROVIDES, "provide2"),
            (DEB_NAME_PROVIDES, "multiple-relations = 1.0"),
            (DEB_REQUIRES, "depend1 = 2.0"),
            (DEB_REQUIRES, "depend2"),
            (DEB_REQUIRES, "predepend1 <= 2.0"),
            (DEB_REQUIRES, "predepend2"),
            (DEB_OR_REQUIRES, "depend3 | depend4 > 2.0"),
            (DEB_UPGRADES, "multiple-relations < 1.0"),
            (DEB_CONFLICTS, "break1 > 2.0"),
            (DEB_CONFLICTS, "break2"),
            (DEB_CONFLICTS, "conflict1 < 2.0"),
            (DEB_CONFLICTS, "conflict2")]
        self.assertEqual(relations, skeleton.relations)
        self.assertEqual(HASH_MULTIPLE_RELATIONS, skeleton.get_hash())

    def test_build_skeleton_or_relations(self):
        """
        The Depend and Pre-Depend fields can have an or relation. That
        is considered to be a single relation, with a special type.
        """
        package = self.get_package("or-relations")
        skeleton = self.build_skeleton(package)
        self.assertEqual("or-relations", skeleton.name)
        self.assertEqual("1.0", skeleton.version)
        relations = [
            (DEB_NAME_PROVIDES, "or-relations = 1.0"),
            (DEB_OR_REQUIRES, "depend1 = 2.0 | depend2"),
            (DEB_OR_REQUIRES, "predepend1 <= 2.0 | predepend2"),
            (DEB_UPGRADES, "or-relations < 1.0")]
        self.assertEqual(relations, skeleton.relations)
        self.assertEqual(HASH_OR_RELATIONS, skeleton.get_hash())
