from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from studio_build import preview_frame_times


class PreviewFrames(TestCase):
    def test_metro_photos_are_taken_late_in_each_hold(self):
        frames = preview_frame_times({"two_d_seconds":12,"station_hold_seconds":[5,10],
                                     "transition_seconds":3})
        self.assertEqual(frames, [("План",6), ("Ракурс 1",16), ("Ракурс 2",28)])

    def test_conveyor_uses_reported_stop_times(self):
        frames = preview_frame_times({"2d_seconds":15,"station_start_seconds":[15,31],
                                     "hold_seconds":[10,2]})
        self.assertEqual(frames[1:], [("Ракурс 1",23), ("Ракурс 2",32.6)])

    def test_short_station_phase_is_sampled_before_next_phase(self):
        tour = {"two_d_seconds":4,"station_start_seconds":[10]}
        with TemporaryDirectory() as folder:
            trace = Path(folder)/"tour-events.csv"
            trace.write_text("fuel;14;10;0\nleave;15;10.5;0\n", encoding="utf-8")
            self.assertEqual(preview_frame_times(tour, trace)[1], ("Ракурс 1",10.325))
