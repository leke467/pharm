#!/usr/bin/env python
import os
import sys


def main():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc

    # On Railway, if the dashboard pre-deploy or start command calls makemigrations / runserver,
    # automatically run production migrations + bootstrap and launch Gunicorn on 0.0.0.0:$PORT.
    if os.environ.get('RAILWAY_ENVIRONMENT'):
        cmd = sys.argv[1] if len(sys.argv) > 1 else ''
        if cmd == 'makemigrations':
            execute_from_command_line([sys.argv[0], 'migrate', '--noinput'])
            from bootstrap_railway import bootstrap
            bootstrap()
            return
        if cmd == 'runserver':
            execute_from_command_line([sys.argv[0], 'migrate', '--noinput'])
            from bootstrap_railway import bootstrap
            bootstrap()
            port = os.environ.get('PORT', '8000')
            os.execvp(
                'gunicorn',
                [
                    'gunicorn',
                    'config.wsgi:application',
                    '--bind',
                    f'0.0.0.0:{port}',
                    '--workers',
                    '3',
                    '--threads',
                    '2',
                    '--timeout',
                    '120',
                ],
            )

    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
