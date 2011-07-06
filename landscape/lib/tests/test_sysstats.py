import os
import re

from landscape.lib.sysstats import (
    MemoryStats, CommandError, get_logged_in_users, get_thermal_zones)
from landscape.tests.helpers import LandscapeTest, EnvironSaverHelper


SAMPLE_MEMORY_INFO = """
MemTotal:      1546436 kB
MemFree:         23452 kB
Buffers:         41656 kB
Cached:         807628 kB
SwapCached:      17572 kB
Active:        1030792 kB
Inactive:       426892 kB
HighTotal:           0 kB
HighFree:            0 kB
LowTotal:      1546436 kB
LowFree:         23452 kB
SwapTotal:     1622524 kB
SwapFree:      1604936 kB
Dirty:            1956 kB
Writeback:           0 kB
Mapped:         661772 kB
Slab:            54980 kB
CommitLimit:   2395740 kB
Committed_AS:  1566888 kB
PageTables:       2728 kB
VmallocTotal:   516088 kB
VmallocUsed:      5660 kB
VmallocChunk:   510252 kB
"""


class MemoryStatsTest(LandscapeTest):

    def test_get_memory_info(self):
        filename = self.makeFile(SAMPLE_MEMORY_INFO)
        memstats = MemoryStats(filename)
        self.assertEqual(memstats.total_memory, 1510)
        self.assertEqual(memstats.free_memory, 503)
        self.assertEqual(memstats.used_memory, 1007)
        self.assertEqual(memstats.total_swap, 1584)
        self.assertEqual(memstats.free_swap, 1567)
        self.assertEqual(memstats.used_swap, 17)
        self.assertEqual("%.2f" % memstats.free_memory_percentage, "33.31")
        self.assertEqual("%.2f" % memstats.free_swap_percentage, "98.93")
        self.assertEqual("%.2f" % memstats.used_memory_percentage, "66.69")
        self.assertEqual("%.2f" % memstats.used_swap_percentage, "1.07")

    def test_get_memory_info_without_swap(self):
        sample = re.subn(r"Swap(Free|Total): *\d+ kB", r"Swap\1:       0",
                         SAMPLE_MEMORY_INFO)[0]
        filename = self.makeFile(sample)
        memstats = MemoryStats(filename)
        self.assertEqual(memstats.total_swap, 0)
        self.assertEqual(memstats.free_swap, 0)
        self.assertEqual(memstats.used_swap, 0)
        self.assertEqual(memstats.used_swap_percentage, 0)
        self.assertEqual(memstats.free_swap_percentage, 0)
        self.assertEqual(type(memstats.used_swap_percentage), float)
        self.assertEqual(type(memstats.free_swap_percentage), float)


class FakeWhoQTest(LandscapeTest):

    helpers = [EnvironSaverHelper]

    def fake_who(self, users):
        dirname = self.makeDir()
        os.environ["PATH"] = "%s:%s" % (dirname, os.environ["PATH"])

        self.who_path = os.path.join(dirname, "who")
        who = open(self.who_path, "w")
        who.write("#!/bin/sh\n")
        who.write("test x$1 = x-q || echo missing-parameter\n")
        who.write("echo %s\n" % users)
        who.write("echo '# users=%d'\n" % len(users.split()))
        who.close()

        os.chmod(self.who_path, 0770)


class LoggedInUsersTest(FakeWhoQTest):

    def test_one_user(self):
        self.fake_who("joe")
        result = get_logged_in_users()
        result.addCallback(self.assertEqual, ["joe"])
        return result

    def test_one_user_multiple_times(self):
        self.fake_who("joe joe joe joe")
        result = get_logged_in_users()
        result.addCallback(self.assertEqual, ["joe"])
        return result

    def test_many_users(self):
        self.fake_who("joe moe boe doe")
        result = get_logged_in_users()
        result.addCallback(self.assertEqual, ["boe", "doe", "joe", "moe"])
        return result

    def test_command_error(self):
        self.fake_who("")
        who = open(self.who_path, "w")
        who.write("#!/bin/sh\necho ERROR 1>&2\nexit 1\n")
        who.close()
        result = get_logged_in_users()

        def assert_failure(failure):
            failure.trap(CommandError)
            self.assertEqual(str(failure.value), "ERROR\n")
        result.addErrback(assert_failure)
        return result


class ThermalZoneTest(LandscapeTest):

    def setUp(self):
        super(ThermalZoneTest, self).setUp()
        self.thermal_zone_path = self.makeDir()

    def get_thermal_zones(self):
        return list(get_thermal_zones(self.thermal_zone_path))

    def write_thermal_zone(self, name, temperature):
        zone_path = os.path.join(self.thermal_zone_path, name)
        if not os.path.isdir(zone_path):
            os.mkdir(zone_path)
        file = open(os.path.join(zone_path, "temperature"), "w")
        file.write("temperature:             " + temperature)
        file.close()


class GetThermalZonesTest(ThermalZoneTest):

    def test_non_existent_thermal_zone_directory(self):
        thermal_zones = list(get_thermal_zones("/non-existent/thermal_zone"))
        self.assertEqual(thermal_zones, [])

    def test_empty_thermal_zone_directory(self):
        self.assertEqual(self.get_thermal_zones(), [])

    def test_one_thermal_zone(self):
        self.write_thermal_zone("THM0", "50 C")
        thermal_zones = self.get_thermal_zones()
        self.assertEqual(len(thermal_zones), 1)

        self.assertEqual(thermal_zones[0].name, "THM0")
        self.assertEqual(thermal_zones[0].temperature, "50 C")
        self.assertEqual(thermal_zones[0].temperature_value, 50)
        self.assertEqual(thermal_zones[0].temperature_unit, "C")
        self.assertEqual(thermal_zones[0].path,
                         os.path.join(self.thermal_zone_path, "THM0"))

    def test_two_thermal_zones(self):
        self.write_thermal_zone("THM0", "50 C")
        self.write_thermal_zone("THM1", "51 C")
        thermal_zones = self.get_thermal_zones()
        self.assertEqual(len(thermal_zones), 2)
        self.assertEqual(thermal_zones[0].temperature, "50 C")
        self.assertEqual(thermal_zones[0].temperature_value, 50)
        self.assertEqual(thermal_zones[0].temperature_unit, "C")
        self.assertEqual(thermal_zones[1].temperature, "51 C")
        self.assertEqual(thermal_zones[1].temperature_value, 51)
        self.assertEqual(thermal_zones[1].temperature_unit, "C")

    def test_badly_formatted_temperature(self):
        self.write_thermal_zone("THM0", "SOMETHING BAD")
        thermal_zones = self.get_thermal_zones()
        self.assertEqual(len(thermal_zones), 1)
        self.assertEqual(thermal_zones[0].temperature, "SOMETHING BAD")
        self.assertEqual(thermal_zones[0].temperature_value, None)
        self.assertEqual(thermal_zones[0].temperature_unit, None)

    def test_badly_formatted_with_missing_space(self):
        self.write_thermal_zone("THM0", "SOMETHINGBAD")
        thermal_zones = self.get_thermal_zones()
        self.assertEqual(len(thermal_zones), 1)
        self.assertEqual(thermal_zones[0].temperature, "SOMETHINGBAD")
        self.assertEqual(thermal_zones[0].temperature_value, None)
        self.assertEqual(thermal_zones[0].temperature_unit, None)

    def test_temperature_file_with_missing_label(self):
        self.write_thermal_zone("THM0", "SOMETHINGBAD")
        temperature_path = os.path.join(self.thermal_zone_path,
                                        "THM0/temperature")
        file = open(temperature_path, "w")
        file.write("bad-label: foo bar\n")
        file.close()
        thermal_zones = self.get_thermal_zones()
        self.assertEqual(len(thermal_zones), 1)
        self.assertEqual(thermal_zones[0].temperature, None)
        self.assertEqual(thermal_zones[0].temperature_value, None)
        self.assertEqual(thermal_zones[0].temperature_unit, None)
