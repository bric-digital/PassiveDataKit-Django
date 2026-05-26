import time

from threading import Thread

from django.test import TestCase

from .decorators import handle_named_lock

RESULTS = {}

@handle_named_lock(lock_name='sleep_func')
def sleep_func(self, sleep_for=10):
    time.sleep(sleep_for)

    return True

# https://medium.com/@birenmer/threading-the-needle-returning-values-from-python-threads-with-ease-ace21193c148

class CustomThread(Thread):
    def __init__(self, group=None, target=None, name=None, args=(), kwargs={}, verbose=None):
        # Initializing the Thread class
        super().__init__(group, target, name, args, kwargs)
        self._return = None

    # Overriding the Thread.run function
    def run(self):
        if self._target is not None:
            self._return = self._target(*self._args, **self._kwargs)

    def join(self):
        super().join()
        return self._return

    def value(self):
        return self._return

class TestNamedLockDecorator(TestCase):
    def setUp(self):
        pass

    def test_handle_named_lock_working(self):
        to_pass = CustomThread(target=sleep_func)
        to_fail = CustomThread(target=sleep_func)

        to_pass.start()
        to_fail.start()

        to_fail.join()
        to_pass.join()

        self.assertEqual(to_pass.value(), True)
        self.assertEqual(to_fail.value(), None)
