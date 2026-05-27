import logging

class BundleFederationFailure(Exception):
    pass

class DataServerManager(models.Manager):
    def default_server(self):
        # TODO: Implement based on settings variable.

        return None

    def federate_points(self, server_url, points, timeout=None):
        if len(points) == 0:
            return 0

        if timeout is None:
            try:
                timeout = settings.PDK_REMOTE_BUNDLE_TIMEOUT
            except AttributeError:
                timeout = 300

        payload = {
            'payload': json.dumps(points, indent=2)
        }

        try:
            bundle_post = requests.post(server_url, data=payload, timeout=timeout)

            if bundle_post.status_code >= 200 and bundle_post.status_code < 300:
                return len(points)

            message = 'Received HTTP status code %s for %s.' % (bundle_post.status_code, server_url)

            raise BundleFederationFailure(message)

        except requests.exceptions.Timeout:
            message = 'Unable to transmit data to %s (timeout=%s).' % (server_url, timeout)

            logging.error(message)

            raise BundleFederationFailure(message)

class DataServer(models.Model):
    name = models.CharField(max_length=1024, unique=True)
    upload_url = models.URLField(max_length=1024, unique=True)
    source_metadata_url = models.URLField(max_length=1024, null=True, blank=True)

    request_key = models.CharField(max_length=1024, default='', null=True, blank=True)

    def __str__(self):
        return str(self.name)

