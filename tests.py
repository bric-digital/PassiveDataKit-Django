import asyncio

from django.test import TestCase

from .decorators import handle_named_lock

@handle_named_lock(lock_name='sleep_func')
async def sleep_func(sleep_for=10):
    await asyncio.sleep(sleep_for)

    return True

class TestNamedLockDecorator(TestCase):
    def setUp(self):
        pass

    def test_tests_working(self):
        async def run_tests():
            task_run = asyncio.create_task(handle_named_lock())

            task_bail = asyncio.create_task(handle_named_lock())

            self.assertNotEqual(await task_bail, None)
            self.assertNotEqual(await task_bail, True)

        asyncio.run(run_tests())
