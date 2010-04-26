import os

from twisted.internet.defer import Deferred

from landscape.package.changer import find_changer_command, PackageChanger
from landscape.package.releaseupgrader import (
    ReleaseUpgrader, find_release_upgrader_command)
from landscape.package.store import PackageStore

from landscape.manager.packagemanager import PackageManager
from landscape.tests.helpers import (
    LandscapeTest, EnvironSaverHelper, ManagerHelper)


class PackageManagerTest(LandscapeTest):
    """Tests for the temperature plugin."""

    helpers = [EnvironSaverHelper, ManagerHelper]

    def setUp(self):
        """Initialize test helpers and create a sample thermal zone."""
        super(PackageManagerTest, self).setUp()
        self.package_store = PackageStore(os.path.join(self.data_path,
                                                       "package/database"))
        self.package_manager = PackageManager()

    def test_create_default_store_upon_message_handling(self):
        """
        If the package sqlite database file doesn't exist yet, it is created
        upon message handling.
        """
        filename = os.path.join(self.broker_service.config.data_path,
                                "package/database")
        os.unlink(filename)
        self.assertFalse(os.path.isfile(filename))

        self.manager.add(self.package_manager)
        self.package_manager.spawn_handler = lambda x: None
        message = {"type": "release-upgrade"}
        self.package_manager.handle_release_upgrade(message)
        self.assertTrue(os.path.isfile(filename))

    def test_dont_spawn_changer_if_message_not_accepted(self):
        """
        The L{PackageManager} spawns a L{PackageChanger} run only if the
        appropriate message type is accepted.
        """
        self.manager.add(self.package_manager)

        package_manager_mock = self.mocker.patch(self.package_manager)
        package_manager_mock.spawn_handler(PackageChanger)
        self.mocker.count(0)

        self.mocker.replay()

        return self.package_manager.run()

    def test_dont_spawn_release_upgrader_if_message_not_accepted(self):
        """
        The L{PackageManager} spawns a L{ReleaseUpgrader} run only if the
        appropriate message type is accepted.
        """
        self.manager.add(self.package_manager)

        package_manager_mock = self.mocker.patch(self.package_manager)
        package_manager_mock.spawn_handler(ReleaseUpgrader)
        self.mocker.count(0)

        self.mocker.replay()

        return self.package_manager.run()

    def test_spawn_handler_on_registration_when_already_accepted(self):
        package_manager_mock = self.mocker.patch(self.package_manager)
        package_manager_mock.spawn_handler(PackageChanger)

        # Slightly tricky as we have to wait for the result of run(),
        # but we don't have its deferred yet.  To handle it, we create
        # our own deferred, and register a callback for when run()
        # returns, chaining both deferreds at that point.
        deferred = Deferred()

        def run_has_run(run_result_deferred):
            return run_result_deferred.chainDeferred(deferred)

        package_manager_mock.run()
        self.mocker.passthrough(run_has_run)

        self.mocker.replay()

        service = self.broker_service
        service.message_store.set_accepted_types(["change-packages-result"])
        self.manager.add(self.package_manager)

        return deferred

    def test_spawn_changer_on_run_if_message_accepted(self):
        """
        The L{PackageManager} spawns a L{PackageChanger} run if messages
        of type C{"change-packages-result"} are accepted.
        """
        service = self.broker_service
        service.message_store.set_accepted_types(["change-packages-result"])

        package_manager_mock = self.mocker.patch(self.package_manager)
        package_manager_mock.spawn_handler(PackageChanger)
        self.mocker.count(2) # Once for registration, then again explicitly.
        self.mocker.replay()

        self.manager.add(self.package_manager)
        return self.package_manager.run()

    def test_run_on_package_data_changed(self):
        """
        The L{PackageManager} spawns a L{PackageChanger} run if an event
        of type C{"package-data-changed"} is fired.
        """

        service = self.broker_service
        service.message_store.set_accepted_types(["change-packages-result"])

        package_manager_mock = self.mocker.patch(self.package_manager)
        package_manager_mock.spawn_handler(PackageChanger)
        self.mocker.count(2) # Once for registration, then again explicitly.
        self.mocker.replay()

        self.manager.add(self.package_manager)
        return self.manager.reactor.fire("package-data-changed")[0]

    def test_spawn_release_upgrader_on_run_if_message_accepted(self):
        """
        The L{PackageManager} spawns a L{ReleaseUpgrader} run if messages
        of type C{"operation-result"} are accepted.
        """
        service = self.broker_service
        service.message_store.set_accepted_types(["operation-result"])

        package_manager_mock = self.mocker.patch(self.package_manager)
        package_manager_mock.spawn_handler(ReleaseUpgrader)
        self.mocker.count(2) # Once for registration, then again explicitly.
        self.mocker.replay()

        self.manager.add(self.package_manager)
        return self.package_manager.run()

    def test_change_packages_handling(self):
        self.manager.add(self.package_manager)

        package_manager_mock = self.mocker.patch(self.package_manager)
        package_manager_mock.spawn_handler(PackageChanger)
        self.mocker.replay()

        message = {"type": "change-packages"}
        self.manager.dispatch_message(message)
        task = self.package_store.get_next_task("changer")
        self.assertTrue(task)
        self.assertEquals(task.data, message)

    def test_release_upgrade_handling(self):
        """
        The L{PackageManager.handle_release_upgrade} method is registered has
        handler for messages of type C{"release-upgrade"}, and queues a task
        in the appropriate queue.
        """
        self.manager.add(self.package_manager)

        package_manager_mock = self.mocker.patch(self.package_manager)
        package_manager_mock.spawn_handler(ReleaseUpgrader)
        self.mocker.replay()

        message = {"type": "release-upgrade"}
        self.manager.dispatch_message(message)
        task = self.package_store.get_next_task("release-upgrader")
        self.assertTrue(task)
        self.assertEquals(task.data, message)

    def test_spawn_changer(self):
        """
        The L{PackageManager.spawn_handler} method executes the correct command
        when passed the L{PackageChanger} class as argument.
        """
        command = self.makeFile("#!/bin/sh\necho 'I am the changer!' >&2\n")
        os.chmod(command, 0755)
        find_command_mock = self.mocker.replace(find_changer_command)
        find_command_mock()
        self.mocker.result(command)
        self.mocker.replay()

        self.package_store.add_task("changer", "Do something!")

        self.manager.add(self.package_manager)
        result = self.package_manager.spawn_handler(PackageChanger)

        def got_result(result):
            log = self.logfile.getvalue()
            self.assertIn("I am the changer!", log)
            self.assertNotIn(command, log)

        return result.addCallback(got_result)

    def test_spawn_release_upgrader(self):
        """
        The L{PackageManager.spawn_handler} method executes the correct command
        when passed the L{ReleaseUpgrader} class as argument.
        """
        command = self.makeFile("#!/bin/sh\necho 'I am the upgrader!' >&2\n")
        os.chmod(command, 0755)
        find_command_mock = self.mocker.replace(find_release_upgrader_command)
        find_command_mock()
        self.mocker.result(command)
        self.mocker.replay()

        self.package_store.add_task("release-upgrader", "Do something!")

        self.manager.add(self.package_manager)
        result = self.package_manager.spawn_handler(ReleaseUpgrader)

        def got_result(result):
            log = self.logfile.getvalue()
            self.assertIn("I am the upgrader!", log)
            self.assertNotIn(command, log)

        return result.addCallback(got_result)

    def test_spawn_handler_without_output(self):
        find_command_mock = self.mocker.replace(find_changer_command)
        find_command_mock()
        self.mocker.result("/bin/true")
        self.mocker.replay()

        self.package_store.add_task("changer", "Do something!")

        self.manager.add(self.package_manager)
        result = self.package_manager.spawn_handler(PackageChanger)

        def got_result(result):
            log = self.logfile.getvalue()
            self.assertNotIn("changer output", log)

        return result.addCallback(got_result)

    def test_spawn_handler_copies_environment(self):
        command = self.makeFile("#!/bin/sh\necho VAR: $VAR\n")
        os.chmod(command, 0755)
        find_command_mock = self.mocker.replace(find_changer_command)
        find_command_mock()
        self.mocker.result(command)
        self.mocker.replay()

        self.manager.add(self.package_manager)

        self.package_store.add_task("changer", "Do something!")

        os.environ["VAR"] = "HI!"

        result = self.package_manager.spawn_handler(PackageChanger)

        def got_result(result):
            log = self.logfile.getvalue()
            self.assertIn("VAR: HI!", log)
            self.assertNotIn(command, log)

        return result.addCallback(got_result)

    def test_spawn_handler_passes_quiet_option(self):
        command = self.makeFile("#!/bin/sh\necho OPTIONS: $@\n")
        os.chmod(command, 0755)
        find_command_mock = self.mocker.replace(find_changer_command)
        find_command_mock()
        self.mocker.result(command)
        self.mocker.replay()

        self.manager.add(self.package_manager)

        self.package_store.add_task("changer", "Do something!")

        result = self.package_manager.spawn_handler(PackageChanger)

        def got_result(result):
            log = self.logfile.getvalue()
            self.assertIn("OPTIONS: --quiet", log)
            self.assertNotIn(command, log)

        return result.addCallback(got_result)

    def test_spawn_handler_wont_run_without_tasks(self):
        command = self.makeFile("#!/bin/sh\necho RUN!\n")
        os.chmod(command, 0755)

        self.manager.add(self.package_manager)

        result = self.package_manager.spawn_handler(PackageChanger)

        def got_result(result):
            log = self.logfile.getvalue()
            self.assertNotIn("RUN!", log)

        return result.addCallback(got_result)

    def test_spawn_handler_doesnt_chdir(self):
        command = self.makeFile("#!/bin/sh\necho RUN\n")
        os.chmod(command, 0755)
        cwd = os.getcwd()
        self.addCleanup(os.chdir, cwd)
        dir = self.makeDir()
        os.chdir(dir)
        os.chmod(dir, 0)

        find_command_mock = self.mocker.replace(find_changer_command)
        find_command_mock()
        self.mocker.result(command)
        self.mocker.replay()

        self.manager.add(self.package_manager)

        self.package_store.add_task("changer", "Do something!")

        result = self.package_manager.spawn_handler(PackageChanger)

        def got_result(result):
            log = self.logfile.getvalue()
            self.assertIn("RUN", log)
            # restore permissions to the dir so tearDown can clean it up
            os.chmod(dir, 0766)

        return result.addCallback(got_result)

    def test_change_package_locks_handling(self):
        """
        The L{PackageManager.handle_change_package_locks} method is registered
        as handler for messages of type C{"change-package-locks"}, and queues
        a package-changer task in the appropriate queue.
        """
        self.manager.add(self.package_manager)

        package_manager_mock = self.mocker.patch(self.package_manager)
        package_manager_mock.spawn_handler(PackageChanger)
        self.mocker.replay()

        message = {"type": "change-package-locks"}
        self.manager.dispatch_message(message)
        task = self.package_store.get_next_task("changer")
        self.assertTrue(task)
        self.assertEquals(task.data, message)
