import hashlib
import logging
import struct
import time
import traceback
from functools import wraps

from django.db import connection


BUNDLE_PROCESSING_LOCK_NAME = 'passive_data_kit.DataBundle.DataPoint.bundle_processing.v1'


def _lock_key(lock_name):
    digest = hashlib.blake2s(  # pylint: disable=no-member
        lock_name.encode('utf-8'),
        digest_size=8,
    ).digest()

    return struct.unpack('>ii', digest[:8])


def _ensure_postgresql():
    if connection.vendor != 'postgresql':
        raise RuntimeError('Bundle-processing DB advisory locks require PostgreSQL.')


def _try_acquire(lock_name):
    _ensure_postgresql()
    connection.ensure_connection()
    key_one, key_two = _lock_key(lock_name)

    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_try_advisory_lock(%s, %s)', [key_one, key_two])
        return bool(cursor.fetchone()[0])


def _release(lock_name):
    _ensure_postgresql()
    connection.ensure_connection()
    key_one, key_two = _lock_key(lock_name)

    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_advisory_unlock(%s, %s)', [key_one, key_two])
        return bool(cursor.fetchone()[0])


def is_bundle_processing_lock_active():  # pylint: disable=invalid-name
    acquired = _try_acquire(BUNDLE_PROCESSING_LOCK_NAME)

    if acquired:
        _release(BUNDLE_PROCESSING_LOCK_NAME)
        return False

    return True


def handle_bundle_processing_lock(handle):
    @wraps(handle)
    def wrapper(self, *args, **options):
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
        logging.debug('%s: Acquiring DB advisory lock...', BUNDLE_PROCESSING_LOCK_NAME)

        if _try_acquire(BUNDLE_PROCESSING_LOCK_NAME) is False:
            logging.debug(
                '%s: DB advisory lock already in place. Quitting.',
                BUNDLE_PROCESSING_LOCK_NAME,
            )
            return None

        logging.debug('%s: DB advisory lock acquired.', BUNDLE_PROCESSING_LOCK_NAME)

        try:
            result = handle(self, *args, **options)
        except: # pylint: disable=bare-except
            logging.error('%s: Command Failed', BUNDLE_PROCESSING_LOCK_NAME)
            logging.error('==' * 72)
            logging.error(traceback.format_exc())
            logging.error('==' * 72)
        finally:
            try:
                _release(BUNDLE_PROCESSING_LOCK_NAME)
                logging.debug('%s: DB advisory lock released.', BUNDLE_PROCESSING_LOCK_NAME)
            except Exception: # pylint: disable=broad-except
                logging.exception(
                    '%s: Failed to release DB advisory lock cleanly.',
                    BUNDLE_PROCESSING_LOCK_NAME,
                )

            logging.debug(
                '%s: Done in %.2f seconds',
                BUNDLE_PROCESSING_LOCK_NAME,
                (time.time() - start_time),
            )

        return result

    return wrapper
