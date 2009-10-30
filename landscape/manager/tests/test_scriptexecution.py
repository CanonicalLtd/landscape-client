import pwd
import os
import sys
import tempfile
import stat

from twisted.internet.defer import gatherResults
from twisted.internet.error import ProcessDone
from twisted.python.failure import Failure

from landscape.manager.scriptexecution import (
    ScriptExecutionPlugin, ProcessTimeLimitReachedError, PROCESS_FAILED_RESULT,
    UBUNTU_PATH, get_user_info, UnknownInterpreterError)
from landscape.manager.manager import SUCCEEDED, FAILED
from landscape.tests.helpers import (
    LandscapeTest, LandscapeIsolatedTest, ManagerHelper,
    StubProcessFactory, DummyProcess)
from landscape.tests.mocker import ANY, ARGS


def get_default_environment():
    username = pwd.getpwuid(os.getuid())[0]
    uid, gid, home = get_user_info(username)
    return  {
        "PATH": UBUNTU_PATH,
        "USER": username,
        "HOME": home,
        }


class RunScriptTests(LandscapeTest):

    helpers = [ManagerHelper]

    def setUp(self):
        super(RunScriptTests, self).setUp()
        self.plugin = ScriptExecutionPlugin()
        self.manager.add(self.plugin)

    def test_basic_run(self):
        """
        The plugin returns a Deferred resulting in the output of basic
        commands.
        """
        result = self.plugin.run_script("/bin/sh", "echo hi")
        result.addCallback(self.assertEquals, "hi\n")
        return result

    def test_other_interpreter(self):
        """Non-shell interpreters can be specified."""
        result = self.plugin.run_script("/usr/bin/python", "print 'hi'")
        result.addCallback(self.assertEquals, "hi\n")
        return result

    def test_other_interpreter_env(self):
        """
        Non-shell interpreters don't have their paths set by the shell, so we
        need to check that other interpreters have environment variables set.
        """
        result = self.plugin.run_script(
            sys.executable,
            "import os\nprint os.environ")

        def check_environment(results):
            for string in get_default_environment().keys():
                self.assertIn(string, results)
        result.addCallback(check_environment)
        return result

    def test_concurrent(self):
        """Scripts run with the ScriptExecutionPlugin plugin are run concurrently."""
        fifo = self.makeFile()
        os.mkfifo(fifo)
        # If the first process is blocking on a fifo, and the second process
        # wants to write to the fifo, the only way this will complete is if
        # run_script is truly async
        d1 = self.plugin.run_script("/bin/sh", "cat " + fifo)
        d2 = self.plugin.run_script("/bin/sh", "echo hi > " + fifo)
        d1.addCallback(self.assertEquals, "hi\n")
        d2.addCallback(self.assertEquals, "")
        return gatherResults([d1, d2])

    def test_accented_run_in_code(self):
        """
        Scripts can contain accented data both in the code and in the
        result.
        """
        accented_content = u"\N{LATIN SMALL LETTER E WITH ACUTE}"
        result = self.plugin.run_script(
            u"/bin/sh", u"echo %s" % (accented_content,))
        result.addCallback(
            self.assertEquals, "%s\n" % (accented_content.encode("utf-8"),))
        return result

    def test_accented_run_in_interpreter(self):
        """
        Scripts can also contain accents in the interpreter.
        """
        accented_content = u"\N{LATIN SMALL LETTER E WITH ACUTE}"
        result = self.plugin.run_script(
            u"/bin/echo %s" % (accented_content,), u"")

        def check(result):
            self.assertTrue(
                "%s " % (accented_content.encode("utf-8"),) in result)
        result.addCallback(check)
        return result

    def test_set_umask_appropriately(self):
        """
        We should be setting the umask to 0022 before executing a script, and
        restoring it to the previous value when finishing.
        """
        mock_umask = self.mocker.replace("os.umask")
        mock_umask(0022)
        self.mocker.result(0077)
        mock_umask(0077)
        self.mocker.replay()
        result = self.plugin.run_script("/bin/sh", "umask")
        result.addCallback(self.assertEquals, "0022\n")
        return result

    def test_restore_umask_in_event_of_error(self):
        """
        We set the umask before executing the script, in the event that there's
        an error setting up the script, we want to restore the umask.
        """
        mock_umask = self.mocker.replace("os.umask")
        mock_umask(0022)
        self.mocker.result(0077)
        mock_mkdtemp = self.mocker.replace("tempfile.mkdtemp", passthrough=False)
        mock_mkdtemp()
        self.mocker.throw(OSError("Fail!"))
        mock_umask(0077)
        self.mocker.replay()
        self.assertRaises(OSError, self.plugin.run_script, "/bin/sh", "umask",
                          attachments={u"file1": "some data"})

    def test_run_with_attachments(self):
        result = self.plugin.run_script(
            u"/bin/sh",
            u"ls $LANDSCAPE_ATTACHMENTS && cat $LANDSCAPE_ATTACHMENTS/file1",
            attachments={u"file1": "some data"})

        def check(result):
            self.assertEquals(result, "file1\nsome data")
        result.addCallback(check)
        return result

    def test_self_remove_script(self):
        """
        If a script removes itself, it doesn't create an error when the script
        execution plugin tries to remove the script file.
        """
        result = self.plugin.run_script("/bin/sh", "echo hi && rm $0")
        result.addCallback(self.assertEquals, "hi\n")
        return result

    def test_self_remove_attachments(self):
        """
        If a script removes its attachments, it doesn't create an error when
        the script execution plugin tries to remove the attachments directory.
        """
        result = self.plugin.run_script(
            u"/bin/sh",
            u"ls $LANDSCAPE_ATTACHMENTS && rm -r $LANDSCAPE_ATTACHMENTS",
            attachments={u"file1": "some data"})

        def check(result):
            self.assertEquals(result, "file1\n")
        result.addCallback(check)
        return result

    def _run_script(self, username, uid, gid, path):
        # ignore the call to chown!
        mock_chown = self.mocker.replace("os.chown", passthrough=False)
        mock_chown(ARGS)

        factory = StubProcessFactory()
        self.plugin.process_factory = factory

        self.mocker.replay()

        result = self.plugin.run_script("/bin/sh", "echo hi", user=username)

        self.assertEquals(len(factory.spawns), 1)
        spawn = factory.spawns[0]
        self.assertEquals(spawn[4], path)
        self.assertEquals(spawn[5], uid)
        self.assertEquals(spawn[6], gid)
        result.addCallback(self.assertEquals, "foobar")

        protocol = spawn[0]
        protocol.childDataReceived(1, "foobar")
        for fd in (0, 1, 2):
            protocol.childConnectionLost(fd)
        protocol.processEnded(Failure(ProcessDone(0)))
        return result

    def test_user(self):
        """
        Running a script as a particular user calls
        C{IReactorProcess.spawnProcess} with an appropriate C{uid} argument,
        with the user's primary group as the C{gid} argument and with the user
        home as C{path} argument.
        """
        uid = os.getuid()
        info = pwd.getpwuid(uid)
        username = info.pw_name
        gid = info.pw_gid
        path = info.pw_dir

        return self._run_script(username, uid, gid, path)

    def test_user_no_home(self):
        """
        When the user specified to C{run_script} doesn't have a home, the
        script executes in '/'.
        """
        mock_getpwnam = self.mocker.replace("pwd.getpwnam", passthrough=False)
        class pwnam(object):
            pw_uid = 1234
            pw_gid = 5678
            pw_dir = self.makeFile()

        self.expect(mock_getpwnam("user")).result(pwnam)

        return self._run_script("user", 1234, 5678, "/")

    def test_user_with_attachments(self):
        uid = os.getuid()
        info = pwd.getpwuid(uid)
        username = info.pw_name
        gid = info.pw_gid
        path = info.pw_dir

        mock_chown = self.mocker.replace("os.chown", passthrough=False)
        mock_chown(ANY, uid, gid)
        self.mocker.count(3)

        factory = StubProcessFactory()
        self.plugin.process_factory = factory

        self.mocker.replay()

        result = self.plugin.run_script("/bin/sh", "echo hi", user=username,
            attachments={u"file 1": "some data"})

        self.assertEquals(len(factory.spawns), 1)
        spawn = factory.spawns[0]
        self.assertIn("LANDSCAPE_ATTACHMENTS", spawn[3].keys())
        attachment_dir = spawn[3]["LANDSCAPE_ATTACHMENTS"]
        self.assertEquals(stat.S_IMODE(os.stat(attachment_dir).st_mode), 0700)
        filename = os.path.join(attachment_dir, "file 1")
        self.assertEquals(stat.S_IMODE(os.stat(filename).st_mode), 0600)

        protocol = spawn[0]
        protocol.childDataReceived(1, "foobar")
        for fd in (0, 1, 2):
            protocol.childConnectionLost(fd)
        protocol.processEnded(Failure(ProcessDone(0)))
        def check(data):
            self.assertEquals(data, "foobar")
            self.assertFalse(os.path.exists(attachment_dir))
        return result.addCallback(check)

    def test_limit_size(self):
        """Data returned from the command is limited."""
        factory = StubProcessFactory()
        self.plugin.process_factory = factory
        self.plugin.size_limit = 100
        result = self.plugin.run_script("/bin/sh", "")
        result.addCallback(self.assertEquals, "x"*100)

        protocol = factory.spawns[0][0]
        protocol.childDataReceived(1, "x"*200)
        for fd in (0, 1, 2):
            protocol.childConnectionLost(fd)
        protocol.processEnded(Failure(ProcessDone(0)))

        return result

    def test_limit_time(self):
        """
        The process only lasts for a certain number of seconds.
        """
        result = self.plugin.run_script("/bin/sh", "cat", time_limit=500)
        self.manager.reactor.advance(501)
        self.assertFailure(result, ProcessTimeLimitReachedError)
        return result

    def test_limit_time_accumulates_data(self):
        """
        Data from processes that time out should still be accumulated and
        available from the exception object that is raised.
        """
        factory = StubProcessFactory()
        self.plugin.process_factory = factory
        result = self.plugin.run_script("/bin/sh", "", time_limit=500)
        protocol = factory.spawns[0][0]
        protocol.makeConnection(DummyProcess())
        protocol.childDataReceived(1, "hi\n")
        self.manager.reactor.advance(501)
        protocol.processEnded(Failure(ProcessDone(0)))
        def got_error(f):
            self.assertTrue(f.check(ProcessTimeLimitReachedError))
            self.assertEquals(f.value.data, "hi\n")
        result.addErrback(got_error)
        return result

    def test_time_limit_canceled_after_success(self):
        """
        The timeout call is cancelled after the script terminates.
        """
        factory = StubProcessFactory()
        self.plugin.process_factory = factory
        result = self.plugin.run_script("/bin/sh", "", time_limit=500)
        protocol = factory.spawns[0][0]
        transport = DummyProcess()
        protocol.makeConnection(transport)
        protocol.childDataReceived(1, "hi\n")
        protocol.processEnded(Failure(ProcessDone(0)))
        self.manager.reactor.advance(501)
        self.assertEquals(transport.signals, [])

    def test_cancel_doesnt_blow_after_success(self):
        """
        When the process ends successfully and is immediately followed by the
        timeout, the output should still be in the failure and nothing bad will
        happen!
        [regression test: killing of the already-dead process would blow up.]
        """
        factory = StubProcessFactory()
        self.plugin.process_factory = factory
        result = self.plugin.run_script("/bin/sh", "", time_limit=500)
        protocol = factory.spawns[0][0]
        protocol.makeConnection(DummyProcess())
        protocol.childDataReceived(1, "hi")
        protocol.processEnded(Failure(ProcessDone(0)))
        self.manager.reactor.advance(501)
        def got_result(output):
            self.assertEquals(output, "hi")
        result.addCallback(got_result)
        return result

    def test_script_is_owned_by_user(self):
        """
        This is a very white-box test. When a script is generated, it must be
        created such that data NEVER gets into it before the file has the
        correct permissions. Therefore os.chmod and os.chown must be called
        before data is written.
        """
        username = pwd.getpwuid(os.getuid())[0]
        uid, gid, home = get_user_info(username)

        mock_chown = self.mocker.replace("os.chown", passthrough=False)
        mock_chmod = self.mocker.replace("os.chmod", passthrough=False)
        mock_mkstemp = self.mocker.replace("tempfile.mkstemp",
                                           passthrough=False)
        mock_fdopen = self.mocker.replace("os.fdopen", passthrough=False)
        process_factory = self.mocker.mock()
        self.plugin.process_factory = process_factory

        self.mocker.order()

        self.expect(mock_mkstemp()).result((99, "tempo!"))

        script_file = mock_fdopen(99, "w")
        mock_chmod("tempo!", 0700)
        mock_chown("tempo!", uid, gid)
        # The contents are written *after* the permissions have been set up!
        script_file.write("#!/bin/sh\ncode")
        script_file.close()
        process_factory.spawnProcess(
            ANY, ANY, uid=uid, gid=gid, path=ANY,
            env=get_default_environment())
        self.mocker.replay()
        # We don't really care about the deferred that's returned, as long as
        # those things happened in the correct order.
        self.plugin.run_script("/bin/sh", "code",
                               user=pwd.getpwuid(uid)[0])

    def test_script_removed(self):
        """
        The script is removed after it is finished.
        """
        mock_mkstemp = self.mocker.replace("tempfile.mkstemp",
                                           passthrough=False)
        fd, filename = tempfile.mkstemp()
        self.expect(mock_mkstemp()).result((fd, filename))
        self.mocker.replay()
        d = self.plugin.run_script("/bin/sh", "true")
        d.addCallback(lambda ign: self.assertFalse(os.path.exists(filename)))
        return d

    def test_unknown_interpreter(self):
        """
        If the script is run with an unknown interpreter, it raises a
        meaningful error instead of crashing in execvpe.
        """
        d = self.plugin.run_script("/bin/cantpossiblyexist", "stuff")
        def cb(ignore):
            self.fail("Should not be there")
        def eb(failure):
            failure.trap(UnknownInterpreterError)
            self.assertEquals(
                failure.value.interpreter,
                "/bin/cantpossiblyexist")
        return d.addCallback(cb).addErrback(eb)


class ScriptExecutionMessageTests(LandscapeIsolatedTest):
    helpers = [ManagerHelper]

    def setUp(self):
        super(ScriptExecutionMessageTests, self).setUp()
        self.broker_service.message_store.set_accepted_types(
            ["operation-result"])
        self.manager.config.script_users = "ALL"

    def _verify_script(self, executable, interp, code):
        """
        Given spawnProcess arguments, check to make sure that the temporary
        script has the correct content.
        """
        data = open(executable, "r").read()
        self.assertEquals(data, "#!%s\n%s" % (interp, code))

    def _send_script(self, interpreter, code, operation_id=123,
                     user=pwd.getpwuid(os.getuid())[0],
                     time_limit=None):
        return self.manager.dispatch_message(
            {"type": "execute-script",
             "interpreter": interpreter,
             "code": code,
             "operation-id": operation_id,
             "username": user,
             "time-limit": time_limit,
             "attachments": {}})

    def test_success(self):
        """
        When a C{execute-script} message is received from the server, the
        specified script will be run and an operation-result will be sent back
        to the server.
        """
        # Let's use a stub process factory, because otherwise we don't have
        # access to the deferred.
        factory = StubProcessFactory()

        # ignore the call to chown!
        mock_chown = self.mocker.replace("os.chown", passthrough=False)
        mock_chown(ARGS)

        self.manager.add(ScriptExecutionPlugin(process_factory=factory))

        self.mocker.replay()
        result = self._send_script(sys.executable, "print 'hi'")

        self._verify_script(factory.spawns[0][1], sys.executable, "print 'hi'")
        self.assertMessages(
            self.broker_service.message_store.get_pending_messages(), [])

        # Now let's simulate the completion of the process
        factory.spawns[0][0].childDataReceived(1, "hi!\n")
        factory.spawns[0][0].processEnded(Failure(ProcessDone(0)))

        def got_result(r):
            self.assertMessages(
                self.broker_service.message_store.get_pending_messages(),
                [{"type": "operation-result",
                  "operation-id": 123,
                  "status": SUCCEEDED,
                  "result-text": u"hi!\n"}])
        result.addCallback(got_result)
        return result

    def test_user(self):
        """A user can be specified in the message."""
        username = pwd.getpwuid(os.getuid())[0]
        uid, gid, home = get_user_info(username)

        # ignore the call to chown!
        mock_chown = self.mocker.replace("os.chown", passthrough=False)
        mock_chown(ARGS)

        def spawn_called(protocol, filename, uid, gid, path, env):
            protocol.childDataReceived(1, "hi!\n")
            protocol.processEnded(Failure(ProcessDone(0)))
            self._verify_script(filename, sys.executable, "print 'hi'")
        process_factory = self.mocker.mock()
        process_factory.spawnProcess(
            ANY, ANY, uid=uid, gid=gid, path=ANY,
            env=get_default_environment())
        self.mocker.call(spawn_called)
        self.mocker.replay()

        self.manager.add(
            ScriptExecutionPlugin(process_factory=process_factory))

        result = self._send_script(sys.executable, "print 'hi'", user=username)
        return result

    def test_timeout(self):
        """
        If a L{ProcessTimeLimitReachedError} is fired back, the
        operation-result should have a failed status.
        """
        factory = StubProcessFactory()
        self.manager.add(ScriptExecutionPlugin(process_factory=factory))

        # ignore the call to chown!
        mock_chown = self.mocker.replace("os.chown", passthrough=False)
        mock_chown(ARGS)

        self.mocker.replay()
        result = self._send_script(sys.executable, "bar", time_limit=30)
        self._verify_script(factory.spawns[0][1], sys.executable, "bar")

        protocol = factory.spawns[0][0]
        protocol.makeConnection(DummyProcess())
        protocol.childDataReceived(2, "ONOEZ")
        self.manager.reactor.advance(31)
        protocol.processEnded(Failure(ProcessDone(0)))

        def got_result(r):
            self.assertMessages(
                self.broker_service.message_store.get_pending_messages(),
                [{"type": "operation-result",
                  "operation-id": 123,
                  "status": FAILED,
                  "result-text": u"ONOEZ",
                  "result-code": 102}])
        result.addCallback(got_result)
        return result

    def test_configured_users(self):
        """
        Messages which try to run a script as a user that is not allowed should
        be rejected.
        """
        self.manager.add(ScriptExecutionPlugin())
        self.manager.config.script_users = "landscape, nobody"
        result = self._send_script(sys.executable, "bar", user="whatever")
        def got_result(r):
            self.assertMessages(
                self.broker_service.message_store.get_pending_messages(),
                [{"type": "operation-result",
                  "operation-id": 123,
                  "status": FAILED,
                  "result-text": u"Scripts cannot be run as user whatever."}])
        result.addCallback(got_result)
        return result

    def test_urgent_response(self):
        """Responses to script execution messages are urgent."""
        username = pwd.getpwuid(os.getuid())[0]
        uid, gid, home = get_user_info(username)

        # ignore the call to chown!
        mock_chown = self.mocker.replace("os.chown", passthrough=False)
        mock_chown(ARGS)

        def spawn_called(protocol, filename, uid, gid, path, env):
            protocol.childDataReceived(1, "hi!\n")
            protocol.processEnded(Failure(ProcessDone(0)))
            self._verify_script(filename, sys.executable, "print 'hi'")
        process_factory = self.mocker.mock()
        process_factory.spawnProcess(
            ANY, ANY, uid=uid, gid=gid, path=ANY,
            env=get_default_environment())
        self.mocker.call(spawn_called)

        self.mocker.replay()

        self.manager.add(ScriptExecutionPlugin(process_factory=process_factory))

        def got_result(r):
            self.assertTrue(self.broker_service.exchanger.is_urgent())
            self.assertMessages(
                self.broker_service.message_store.get_pending_messages(),
                [{"type": "operation-result",
                  "operation-id": 123,
                  "result-text": u"hi!\n",
                  "status": SUCCEEDED}])

        result = self._send_script(sys.executable, "print 'hi'")
        result.addCallback(got_result)
        return result

    def test_binary_output(self):
        """
        If a script outputs non-printable characters not handled by utf-8, they
        are replaced during the encoding phase but the script succeeds.
        """
        username = pwd.getpwuid(os.getuid())[0]
        uid, gid, home = get_user_info(username)

        mock_chown = self.mocker.replace("os.chown", passthrough=False)
        mock_chown(ARGS)

        def spawn_called(protocol, filename, uid, gid, path, env):
            protocol.childDataReceived(1,
            "\x7fELF\x01\x01\x01\x00\x00\x00\x95\x01")
            protocol.processEnded(Failure(ProcessDone(0)))
            self._verify_script(filename, sys.executable, "print 'hi'")
        process_factory = self.mocker.mock()
        process_factory.spawnProcess(
            ANY, ANY, uid=uid, gid=gid, path=ANY,
            env=get_default_environment())
        self.mocker.call(spawn_called)

        self.mocker.replay()

        self.manager.add(ScriptExecutionPlugin(process_factory=process_factory))

        def got_result(r):
            self.assertTrue(self.broker_service.exchanger.is_urgent())
            [message] = self.broker_service.message_store.get_pending_messages()
            self.assertEquals(
                message["result-text"],
                 u"\x7fELF\x01\x01\x01\x00\x00\x00\ufffd\x01")

        result = self._send_script(sys.executable, "print 'hi'")
        result.addCallback(got_result)
        return result

    def test_parse_error_causes_operation_failure(self):
        """
        If there is an error parsing the message, an operation-result will be
        sent (assuming operation-id *is* successfully parsed).
        """
        self.log_helper.ignore_errors(KeyError)
        self.manager.add(ScriptExecutionPlugin())

        self.manager.dispatch_message(
            {"type": "execute-script", "operation-id": 444})

        if sys.version_info[:2] < (2, 6):
            expected_message = [{"type": "operation-result",
                                 "operation-id": 444,
                                 "result-text": u"KeyError: 'username'",
                                 "status": FAILED}]
        else:
            expected_message = [{"type": "operation-result",
                                 "operation-id": 444,
                                 "result-text": u"KeyError: username",
                                 "status": FAILED}]

        self.assertMessages(
            self.broker_service.message_store.get_pending_messages(),
            expected_message)

        self.assertTrue("KeyError: 'username'" in self.logfile.getvalue())

    def test_non_zero_exit_fails_operation(self):
        """
        If a script exits with a nen-zero exit code, the operation associated
        with it should fail, but the data collected should still be sent.
        """
        # Mock a bunch of crap so that we can run a real process
        self.mocker.replace("os.chown", passthrough=False)(ARGS)
        self.mocker.replace("os.setuid", passthrough=False)(ARGS)
        self.mocker.count(0, None)
        self.mocker.replace("os.setgid", passthrough=False)(ARGS)
        self.mocker.count(0, None)
        self.mocker.replace(
            "twisted.python.util.initgroups", passthrough=False)(ARGS)
        self.mocker.count(0, None)
        self.mocker.replay()

        self.manager.add(ScriptExecutionPlugin())
        result = self._send_script("/bin/sh", "echo hi; exit 1")

        def got_result(ignored):
            self.assertMessages(
                self.broker_service.message_store.get_pending_messages(),
                [{"type": "operation-result",
                  "operation-id": 123,
                  "result-text": "hi\n",
                  "result-code": PROCESS_FAILED_RESULT,
                  "status": FAILED}])
        return result.addCallback(got_result)

    def test_unknown_error(self):
        """
        When a completely unknown error comes back from the process protocol,
        the operation fails and the formatted failure is included in the
        response message.
        """
        factory = StubProcessFactory()

        # ignore the call to chown!
        mock_chown = self.mocker.replace("os.chown", passthrough=False)
        mock_chown(ARGS)

        self.manager.add(ScriptExecutionPlugin(process_factory=factory))

        self.mocker.replay()
        result = self._send_script(sys.executable, "print 'hi'")

        self._verify_script(factory.spawns[0][1], sys.executable, "print 'hi'")
        self.assertMessages(
            self.broker_service.message_store.get_pending_messages(), [])

        failure = Failure(RuntimeError("Oh noes!"))
        factory.spawns[0][0].result_deferred.errback(failure)

        def got_result(r):
            self.assertMessages(
                self.broker_service.message_store.get_pending_messages(),
                [{"type": "operation-result",
                  "operation-id": 123,
                  "status": FAILED,
                  "result-text": str(failure)}])
        result.addCallback(got_result)
        return result
