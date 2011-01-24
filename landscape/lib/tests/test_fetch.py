import os

import pycurl

from twisted.internet.defer import FirstError

from landscape.lib.fetch import (
    fetch, fetch_async, fetch_many_async, fetch_to_files,
    url_to_filename, HTTPCodeError, PyCurlError)
from landscape.tests.helpers import LandscapeTest


class CurlStub(object):

    def __init__(self, result=None, infos=None, error=None):
        self.result = result
        self.infos = infos
        if self.infos is None:
            self.infos = {pycurl.HTTP_CODE: 200}
        self.options = {}
        self.performed = False
        self.error = error

    def getinfo(self, what):
        if what in self.infos:
            return self.infos[what]
        raise RuntimeError("Stub doesn't know about %d info" % what)

    def setopt(self, option, value):
        if isinstance(value, unicode):
            raise AssertionError("setopt() doesn't accept unicode values")
        if self.performed:
            raise AssertionError("setopt() can't be called after perform()")
        self.options[option] = value

    def perform(self):
        if self.error:
            raise self.error
        if self.performed:
            raise AssertionError("Can't perform twice")
        self.options[pycurl.WRITEFUNCTION](self.result)
        self.performed = True


class CurlManyStub(object):

    def __init__(self, url_results):
        self.curls = {}
        for url in url_results:
            result = url_results[url]
            if isinstance(result, str):
                body = result
                http_code = 200
            else:
                body = result[0]
                http_code = result[1]
            self.curls[url] = CurlStub(body, {pycurl.HTTP_CODE: http_code})
        self.current = None

    def getinfo(self, what):
        if not self.current.performed:
            raise AssertionError("getinfo() can't be called before perform()")
        result = self.current.getinfo(what)
        self.current = None
        return result

    def setopt(self, option, value):
        if option is pycurl.URL:
            self.current = self.curls[value]
        self.current.setopt(option, value)

    def perform(self):
        self.current.perform()


class Any(object):

    def __eq__(self, other):
        return True


class FetchTest(LandscapeTest):

    def test_basic(self):
        curl = CurlStub("result")
        result = fetch("http://example.com", curl=curl)
        self.assertEquals(result, "result")
        self.assertEquals(curl.options,
                          {pycurl.URL: "http://example.com",
                           pycurl.FOLLOWLOCATION: True,
                           pycurl.MAXREDIRS: 5,
                           pycurl.CONNECTTIMEOUT: 30,
                           pycurl.LOW_SPEED_LIMIT: 1,
                           pycurl.LOW_SPEED_TIME: 600,
                           pycurl.NOSIGNAL: 1,
                           pycurl.WRITEFUNCTION: Any(),
                           pycurl.DNS_CACHE_TIMEOUT: 0,
                           pycurl.ENCODING: "gzip,deflate"})

    def test_post(self):
        curl = CurlStub("result")
        result = fetch("http://example.com", post=True, curl=curl)
        self.assertEquals(result, "result")
        self.assertEquals(curl.options,
                          {pycurl.URL: "http://example.com",
                           pycurl.FOLLOWLOCATION: True,
                           pycurl.MAXREDIRS: 5,
                           pycurl.CONNECTTIMEOUT: 30,
                           pycurl.LOW_SPEED_LIMIT: 1,
                           pycurl.LOW_SPEED_TIME: 600,
                           pycurl.NOSIGNAL: 1,
                           pycurl.WRITEFUNCTION: Any(),
                           pycurl.POST: True,
                           pycurl.DNS_CACHE_TIMEOUT: 0,
                           pycurl.ENCODING: "gzip,deflate"})

    def test_post_data(self):
        curl = CurlStub("result")
        result = fetch("http://example.com", post=True, data="data", curl=curl)
        self.assertEquals(result, "result")
        self.assertEquals(curl.options[pycurl.READFUNCTION](), "data")
        self.assertEquals(curl.options,
                          {pycurl.URL: "http://example.com",
                           pycurl.FOLLOWLOCATION: True,
                           pycurl.MAXREDIRS: 5,
                           pycurl.CONNECTTIMEOUT: 30,
                           pycurl.LOW_SPEED_LIMIT: 1,
                           pycurl.LOW_SPEED_TIME: 600,
                           pycurl.NOSIGNAL: 1,
                           pycurl.WRITEFUNCTION: Any(),
                           pycurl.POST: True,
                           pycurl.POSTFIELDSIZE: 4,
                           pycurl.READFUNCTION: Any(),
                           pycurl.DNS_CACHE_TIMEOUT: 0,
                           pycurl.ENCODING: "gzip,deflate"})

    def test_cainfo(self):
        curl = CurlStub("result")
        result = fetch("https://example.com", cainfo="cainfo", curl=curl)
        self.assertEquals(result, "result")
        self.assertEquals(curl.options,
                          {pycurl.URL: "https://example.com",
                           pycurl.FOLLOWLOCATION: True,
                           pycurl.MAXREDIRS: 5,
                           pycurl.CONNECTTIMEOUT: 30,
                           pycurl.LOW_SPEED_LIMIT: 1,
                           pycurl.LOW_SPEED_TIME: 600,
                           pycurl.NOSIGNAL: 1,
                           pycurl.WRITEFUNCTION: Any(),
                           pycurl.CAINFO: "cainfo",
                           pycurl.DNS_CACHE_TIMEOUT: 0,
                           pycurl.ENCODING: "gzip,deflate"})

    def test_cainfo_on_http(self):
        curl = CurlStub("result")
        result = fetch("http://example.com", cainfo="cainfo", curl=curl)
        self.assertEquals(result, "result")
        self.assertTrue(pycurl.CAINFO not in curl.options)

    def test_headers(self):
        curl = CurlStub("result")
        result = fetch("http://example.com",
                       headers={"a": "1", "b": "2"}, curl=curl)
        self.assertEquals(result, "result")
        self.assertEquals(curl.options,
                          {pycurl.URL: "http://example.com",
                           pycurl.FOLLOWLOCATION: True,
                           pycurl.MAXREDIRS: 5,
                           pycurl.CONNECTTIMEOUT: 30,
                           pycurl.LOW_SPEED_LIMIT: 1,
                           pycurl.LOW_SPEED_TIME: 600,
                           pycurl.NOSIGNAL: 1,
                           pycurl.WRITEFUNCTION: Any(),
                           pycurl.HTTPHEADER: ["a: 1", "b: 2"],
                           pycurl.DNS_CACHE_TIMEOUT: 0,
                           pycurl.ENCODING: "gzip,deflate"})

    def test_timeouts(self):
        curl = CurlStub("result")
        result = fetch("http://example.com", connect_timeout=5,
                       total_timeout=30, curl=curl)
        self.assertEquals(result, "result")
        self.assertEquals(curl.options,
                          {pycurl.URL: "http://example.com",
                           pycurl.FOLLOWLOCATION: True,
                           pycurl.MAXREDIRS: 5,
                           pycurl.CONNECTTIMEOUT: 5,
                           pycurl.LOW_SPEED_LIMIT: 1,
                           pycurl.LOW_SPEED_TIME: 30,
                           pycurl.NOSIGNAL: 1,
                           pycurl.WRITEFUNCTION: Any(),
                           pycurl.DNS_CACHE_TIMEOUT: 0,
                           pycurl.ENCODING: "gzip,deflate"})

    def test_unicode(self):
        """
        The L{fetch} function converts the C{url} parameter to C{str} before
        passing it to curl.
        """
        curl = CurlStub("result")
        result = fetch(u"http://example.com", curl=curl)
        self.assertEquals(result, "result")
        self.assertEquals(curl.options[pycurl.URL], "http://example.com")
        self.assertTrue(isinstance(curl.options[pycurl.URL], str))

    def test_non_200_result(self):
        curl = CurlStub("result", {pycurl.HTTP_CODE: 404})
        try:
            fetch("http://example.com", curl=curl)
        except HTTPCodeError, error:
            self.assertEquals(error.http_code, 404)
            self.assertEquals(error.body, "result")
        else:
            self.fail("HTTPCodeError not raised")

    def test_http_error_str(self):
        self.assertEquals(str(HTTPCodeError(501, "")),
                          "Server returned HTTP code 501")

    def test_http_error_repr(self):
        self.assertEquals(repr(HTTPCodeError(501, "")),
                          "<HTTPCodeError http_code=501>")

    def test_pycurl_error(self):
        curl = CurlStub(error=pycurl.error(60, "pycurl error"))
        try:
            fetch("http://example.com", curl=curl)
        except PyCurlError, error:
            self.assertEquals(error.error_code, 60)
            self.assertEquals(error.message, "pycurl error")
        else:
            self.fail("PyCurlError not raised")

    def test_pycurl_error_str(self):
        self.assertEquals(str(PyCurlError(60, "pycurl error")),
                          "Error 60: pycurl error")

    def test_pycurl_error_repr(self):
        self.assertEquals(repr(PyCurlError(60, "pycurl error")),
                          "<PyCurlError args=(60, 'pycurl error')>")

    def test_create_curl(self):
        curls = []

        def pycurl_Curl():
            curl = CurlStub("result")
            curls.append(curl)
            return curl
        Curl = pycurl.Curl
        try:
            pycurl.Curl = pycurl_Curl
            result = fetch("http://example.com")
            curl = curls[0]
            self.assertEquals(result, "result")
            self.assertEquals(curl.options,
                              {pycurl.URL: "http://example.com",
                               pycurl.FOLLOWLOCATION: True,
                               pycurl.MAXREDIRS: 5,
                               pycurl.CONNECTTIMEOUT: 30,
                               pycurl.LOW_SPEED_LIMIT: 1,
                               pycurl.LOW_SPEED_TIME: 600,
                               pycurl.NOSIGNAL: 1,
                               pycurl.WRITEFUNCTION: Any(),
                               pycurl.DNS_CACHE_TIMEOUT: 0,
                               pycurl.ENCODING: "gzip,deflate"})
        finally:
            pycurl.Curl = Curl

    def test_async_fetch(self):
        curl = CurlStub("result")
        d = fetch_async("http://example.com/", curl=curl)
        def got_result(result):
            self.assertEquals(result, "result")
        return d.addCallback(got_result)

    def test_async_fetch_with_error(self):
        curl = CurlStub("result", {pycurl.HTTP_CODE: 501})
        d = fetch_async("http://example.com/", curl=curl)
        def got_error(failure):
            self.assertEquals(failure.value.http_code, 501)
            self.assertEquals(failure.value.body, "result")
            return failure
        d.addErrback(got_error)
        self.assertFailure(d, HTTPCodeError)
        return d

    def test_fetch_many_async(self):
        """
        L{fetch_many_async} retrieves multiple URLs, and returns a
        C{DeferredList} firing its callback when all the URLs have
        successfully completed.
        """
        url_results = {"http://good/": "good",
                       "http://better/": "better"}

        def callback(result, url):
            self.assertIn(result, url_results.values())
            self.assertIn(url, url_results)
            url_results.pop(url)

        def errback(failure, url):
            self.fail()

        curl = CurlManyStub(url_results)
        d = fetch_many_async(url_results.keys(), callback=callback,
                             errback=errback, curl=curl)

        def completed(result):
            self.assertEquals(url_results, {})

        return d.addCallback(completed)

    def test_fetch_many_async_with_error(self):
        """
        L{fetch_many_async} aborts as soon as one URL fails.
        """
        url_results = {"http://right/": "right",
                       "http://wrong/": ("wrong", 501),
                       "http://impossilbe/": "impossible"}
        failed_urls = []

        def errback(failure, url):
            failed_urls.append(url)
            self.assertEquals(failure.value.body, "wrong")
            self.assertEquals(failure.value.http_code, 501)
            return failure

        curl = CurlManyStub(url_results)
        result = fetch_many_async(url_results.keys(), callback=None,
                                  errback=errback, curl=curl)

        def check_failure(failure):
            self.assertTrue(isinstance(failure.subFailure.value,
                                       HTTPCodeError))
            self.assertEquals(failed_urls, ["http://wrong/"])

        self.assertFailure(result, FirstError)
        return result.addCallback(check_failure)

    def test_url_to_filename(self):
        """
        L{url_to_filename} extracts the filename part of an URL, optionally
        prepending a directory path to it.
        """
        self.assertEquals(url_to_filename("http://some/file"), "file")
        self.assertEquals(url_to_filename("http://some/file/"), "file")
        self.assertEquals(url_to_filename("http://some/file", directory="dir"),
                          os.path.join("dir", "file"))

    def test_fetch_to_files(self):
        """
        L{fetch_to_files} fetches a list of URLs and save their content
        in the given directory.
        """
        url_results = {"http://good/file": "file",
                       "http://even/better-file": "better-file"}
        directory = self.makeDir()
        curl = CurlManyStub(url_results)

        result = fetch_to_files(url_results.keys(), directory, curl=curl)

        def check_files(ignored):
            for result in url_results.itervalues():
                fd = open(os.path.join(directory, result))
                self.assertEquals(fd.read(), result)
                fd.close()

        result.addCallback(check_files)
        return result

    def test_fetch_to_files_with_trailing_slash(self):
        """
        L{fetch_to_files} discards trailing slashes from the final component
        of the given URLs when saving them as files.
        """
        directory = self.makeDir()
        curl = CurlStub("data")

        result = fetch_to_files(["http:///with/slash/"], directory, curl=curl)

        def check_files(ignored):
            os.path.exists(os.path.join(directory, "slash"))

        result.addCallback(check_files)
        return result

    def test_fetch_to_files_with_errors(self):
        """
        L{fetch_to_files} optionally logs an error message as soon as one URL
        fails, and aborts.
        """
        url_results = {"http://im/right": "right",
                       "http://im/wrong": ("wrong", 404),
                       "http://im/not": "not"}
        directory = self.makeDir()
        messages = []
        logger = lambda message: messages.append(message)
        curl = CurlManyStub(url_results)

        result = fetch_to_files(url_results.keys(), directory, logger=logger,
                                curl=curl)

        def check_messages(failure):
            self.assertEquals(len(messages), 1)
            self.assertEquals(messages[0],
                              "Couldn't fetch file from http://im/wrong "
                              "(Server returned HTTP code 404)")
            messages.pop()

        def check_files(ignored):
            self.assertEquals(messages, [])
            self.assertFalse(os.path.exists(os.path.join(directory, "wrong")))

        result.addErrback(check_messages)
        result.addCallback(check_files)
        return result

    def test_fetch_to_files_with_non_existing_directory(self):
        """
        The deferred list returned by L{fetch_to_files} results in a failure
        if the destination directory doesn't exist.
        """
        url_results = {"http://im/right": "right"}
        directory = "i/dont/exist/"
        curl = CurlManyStub(url_results)

        result = fetch_to_files(url_results.keys(), directory, curl=curl)

        def check_error(failure):
            error = str(failure.value.subFailure.value)
            self.assertEquals(error, "[Errno 2] No such file or directory: "
                              "'i/dont/exist/right'")
            self.assertFalse(os.path.exists(os.path.join(directory, "right")))

        result.addErrback(check_error)
        return result
