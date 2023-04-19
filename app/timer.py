# timer.py

import time


class TimerError(Exception):
    """A custom exception used to report errors in use of Timer class"""


class Timer:
    steps = {}

    def __init__(self,
                 name="Timer",
                 logger=print
                 ):
        self.name = name
        self._start_time = None
        self.logger = logger
        self._last_step = None

    def start(self):
        """Start a new timer"""
        if self._start_time is not None:
            raise TimerError(f"Timer is running. Use .stop() to stop it")

        self._start_time = time.perf_counter()
        self._last_step = self._start_time
        self.steps = {}

    def time_step(self, name: str):
        sample = time.perf_counter()
        step_elapsed_time = sample - self._last_step
        self._last_step = sample

        self._set_step(name, step_elapsed_time)

        if self.logger:
            self.logger("{0}:{1} - {2:.4f}".format(self.name, name, step_elapsed_time))

        return step_elapsed_time

    def stop(self):
        """Stop the timer, and report the elapsed time"""
        if self._start_time is None:
            raise TimerError(f"Timer is not running. Use .start() to start it")

        sample = time.perf_counter()
        total_elapsed_time = sample - self._start_time
        step_elapsed_time = sample - self._last_step
        self._start_time = None
        self._last_step = None

        self._set_step("Stopped", step_elapsed_time)
        self._set_step("Total_Elapsed", total_elapsed_time)

        if self.logger:
            self.logger("{0}:{1} - {2:.4f}".format(self.name, "Stopped", step_elapsed_time))
            self.logger("{0}:{1} - {2:.4f}".format(self.name, "Total_Elapsed", total_elapsed_time))

        return total_elapsed_time

    def _set_step(self, name: str, value: float):
        self.steps.setdefault(name, value)
