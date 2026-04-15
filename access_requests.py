import json


USER_IDENTIFIER_KIND_API_TOKEN = 'api-client'  # nosec B105
USER_IDENTIFIER_KIND_DJANGO_USER = 'django-user'


def build_django_user_identifier(user):
    return json.dumps({
        'kind': USER_IDENTIFIER_KIND_DJANGO_USER,
        'user_pk': user.pk,
        'username': str(user.username),
    }, sort_keys=True, separators=(',', ':'))


def build_token_identifier(token_value):
    return json.dumps({
        'kind': USER_IDENTIFIER_KIND_API_TOKEN,
        'token': str(token_value or ''),
    }, sort_keys=True, separators=(',', ':'))


def parse_user_identifier(value):
    raw_value = str(value or '')

    if raw_value.strip() == '':
        return {
            'kind': '',
            'raw_value': raw_value,
        }

    try:
        parsed = json.loads(raw_value)

        if isinstance(parsed, dict):
            parsed['raw_value'] = raw_value

            return parsed
    except (TypeError, ValueError):
        pass

    if raw_value.startswith('api_token: '):
        return {
            'kind': USER_IDENTIFIER_KIND_API_TOKEN,
            'token': raw_value[len('api_token: '):],
            'raw_value': raw_value,
        }

    if ': ' in raw_value:
        user_pk, username = raw_value.split(': ', 1)

        if user_pk.isdigit():
            return {
                'kind': USER_IDENTIFIER_KIND_DJANGO_USER,
                'user_pk': int(user_pk),
                'username': username,
                'raw_value': raw_value,
            }

    return {
        'kind': '',
        'raw_value': raw_value,
    }


def format_user_identifier(value):
    parsed = parse_user_identifier(value)

    if parsed.get('kind') == USER_IDENTIFIER_KIND_DJANGO_USER:
        return '#%s %s' % (parsed.get('user_pk', ''), parsed.get('username', ''))

    if parsed.get('kind') == USER_IDENTIFIER_KIND_API_TOKEN:
        return 'api_token %s' % parsed.get('token', '')

    return parsed.get('raw_value', '')
