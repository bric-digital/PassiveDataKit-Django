# pylint: disable=pointless-string-statement

import logging
import sys
import time
import tempfile
import traceback

from lockfile import FileLock, AlreadyLocked, LockTimeout

import pglock

from django.conf import settings
from django.utils import timezone
from django.utils.text import slugify

'''
A decorator for management commands (or any class method) to ensure that there is
only ever one process running the method at any one time.
Requires lockfile - (pip install lockfile)
Author: Ross Lawley
Via: http://rosslawley.co.uk/archive/old/2010/10/18/locking-django-management-commands/
'''

# Lock timeout value - how long to wait for the lock to become available.
# Default behavior is to never wait for the lock to be available (fail fast)
LOCK_WAIT_TIMEOUT = getattr(settings, 'DEFAULT_LOCK_WAIT_TIMEOUT', -1)

def handle_lock(handle):
    '''
    Decorate the handle method with a file lock to ensure there is only ever
    one process running at any one time.
    '''
    def wrapper(self, *args, **options):
        lock_prefix = ''

        try:
            lock_prefix = settings.SITE_URL.split('//')[1].replace('/', '').replace('.', '-')
        except AttributeError:
            try:
                lock_prefix = settings.ALLOWED_HOSTS[0].replace('.', '-')
            except IndexError:
                lock_prefix = 'pdk_lock'

        lock_prefix = slugify(lock_prefix)

        start_time = time.time()
        verbosity = options.get('verbosity', 0)
        if verbosity == 0:
            level = logging.ERROR
        elif verbosity == 1:
            level = logging.WARN
        elif verbosity == 2:
            level = logging.INFO
        else:
            level = logging.DEBUG

        logging.basicConfig(level=level, format='%(message)s')
        logging.debug('-' * 72)

        lock_name = self.__module__.split('.').pop()
        lock = FileLock('%s/%s__%s' % (tempfile.gettempdir(), lock_prefix, lock_name))

        logging.debug('%s: Acquiring lock...', lock_name)

        try:
            lock.acquire(LOCK_WAIT_TIMEOUT)
        except AlreadyLocked:
            logging.debug('%s: Lock already in place. Quitting.', lock_name)
            return
        except LockTimeout:
            logging.debug('%s: Waiting for the lock timed out. Quitting.', lock_name)
            return

        logging.debug('%s: Lock acquired.', lock_name)

        try:
            handle(self, *args, **options)
        except: # pylint: disable=bare-except
            logging.error('%s: Command Failed', lock_name)
            logging.error('==' * 72)
            logging.error(traceback.format_exc())
            logging.error('==' * 72)

        logging.debug('%s: Releasing lock...', lock_name)
        lock.release()
        logging.debug('%s: Lock released.', lock_name)

        logging.debug('%s: Done in %.2f seconds', lock_name, (time.time() - start_time))
        return

    return wrapper


'''
Logs timestamp to Nagios monitoring system for last run of scheduled job.
'''
def log_scheduled_event(handle):
    def wrapper(self, *args, **options):
        try:
            from nagios_monitor.models import ScheduledEvent # pylint: disable=import-error, import-outside-toplevel, bad-option-value

            event_name = self.__module__.split('.').pop()

            try:
                event_prefix = settings.SITE_URL.split('//')[1].replace('/', '').replace('.', '-')
            except AttributeError:
                try:
                    event_prefix = settings.ALLOWED_HOSTS[0].replace('.', '-')
                except IndexError:
                    event_prefix = 'pdk_scheduled_event'

            event_prefix = slugify(event_prefix)

            ScheduledEvent.log_event(event_prefix + '_' + event_name, timezone.now())

        except ImportError:
            # nagios_monitor app not installed
            pass

        handle(self, *args, **options)

    return wrapper

'''
Grabs a Postgres database lock to ensure exclusive execution of wrapped code paths.
'''
def handle_named_lock(lock_name='passive_data_kit.named_lock'):
    def decorator_repeat(handle):
        if sys.version_info < (3, 7): # Fall back to coarse file locking on Python 3.6 and lower
            return handle_lock(handle)

        def wrapper(*args, **options):
            start_time = time.time()
            result = None
            verbosity = options.get('verbosity', 0)

            if verbosity == 0:
                level = logging.ERROR
            elif verbosity == 1:
                level = logging.WARN
            elif verbosity == 2:
                level = logging.INFO
            else:
                level = logging.DEBUG

            logging.basicConfig(level=level, format='%(message)s')
            logging.debug('-' * 72)
            logging.debug('%s: Acquiring DB advisory lock...', lock_name)

            lock_acquired = pglock.advisory(lock_name, timeout=0)

            if lock_acquired is False:
                logging.debug('%s: DB advisory lock already in place. Quitting.', lock_name)

                return None

            logging.debug('%s: DB advisory lock acquired.', lock_name)

            try:
                result = handle(*args, **options)
            except: # pylint: disable=bare-except
                logging.error('%s: Command Failed', lock_name)
                logging.error('==' * 72)
                logging.error(traceback.format_exc())
                logging.error('==' * 72)
            finally:
                try:
                    lock_acquired.release()

                    logging.debug('%s: DB advisory lock released.', lock_name)
                except Exception: # pylint: disable=broad-except
                    logging.exception('%s: Failed to release DB advisory lock cleanly.', lock_name,)

                logging.debug('%s: Done in %.2f seconds', lock_name, (time.time() - start_time))

            return result

        return wrapper

    return decorator_repeat
