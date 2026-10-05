from django.test import TestCase

class TestBasicsTestCase(TestCase):
    def setUp(self):
        pass

    def test_tests_working(self):
        self.assertNotEqual('foo', 'bar') # pylint: disable=redundant-unittest-assert
