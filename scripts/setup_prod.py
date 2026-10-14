"""Prepare (and optionally start) a production deployment.

- Creates .env.prod from .env.prod.example if it does not exist.
- Generates the Django secret key and the database password while they still have their example values.
- Checks that no required value is still an example and that the PostgreSQL and Django settings match.
- With --start, builds and starts the production stack with Docker Compose.

Values that are already set are never overwritten.
"""
import argparse
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Markers of the example values in .env.prod.example.
PLACEHOLDER_MARKERS = ('GENERATE', 'HERE', 'YOUR', 'yourdomain')

REQUIRED = (
    'DJANGO_SECRET_KEY', 'DJANGO_ALLOWED_HOSTS',
    'POSTGRES_DB', 'POSTGRES_USER', 'POSTGRES_PASSWORD',
    'DB_NAME', 'DB_USER', 'DB_PASSWORD', 'DB_HOST', 'DB_PORT',
    'CELERY_BROKER_URL', 'ANNOTATION_BASE',
)
OPTIONAL = {
    'DJANGO_CSRF_TRUSTED_ORIGINS': 'needed to serve a public domain over HTTPS',
    'DEFAULT_FROM_EMAIL': 'needed for email notifications',
    'SENDGRID_API_KEY': 'needed for email notifications',
}

# Django reads DB_*, the PostgreSQL container reads POSTGRES_*: they must describe the same database.
MUST_MATCH = (('DB_NAME', 'POSTGRES_DB'), ('DB_USER', 'POSTGRES_USER'), ('DB_PASSWORD', 'POSTGRES_PASSWORD'))


def is_placeholder(value):
    return not value or any(marker in value for marker in PLACEHOLDER_MARKERS)


def read_env(path):
    values = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            values[key.strip()] = value.strip()
    return values


def set_values(path, updates):
    """Replace the value of existing keys, keeping the rest of the file as it is."""
    lines = path.read_text(encoding='utf-8').splitlines()
    for index, line in enumerate(lines):
        key = line.split('=', 1)[0].strip()
        if '=' in line and not line.lstrip().startswith('#') and key in updates:
            lines[index] = f'{key}={updates[key]}'
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def generate_missing_secrets(env_file):
    values = read_env(env_file)
    updates = {}
    if is_placeholder(values.get('DJANGO_SECRET_KEY')):
        updates['DJANGO_SECRET_KEY'] = secrets.token_urlsafe(50)
    if is_placeholder(values.get('POSTGRES_PASSWORD')) and is_placeholder(values.get('DB_PASSWORD')):
        updates['POSTGRES_PASSWORD'] = updates['DB_PASSWORD'] = secrets.token_urlsafe(32)
    if updates:
        set_values(env_file, updates)
        print(f"Generated {', '.join(sorted(updates))}")


def check(env_file):
    """Return the list of problems that prevent starting; print warnings for optional values."""
    values = read_env(env_file)
    errors = [f'{key} is missing or still has its example value' for key in REQUIRED if is_placeholder(values.get(key))]
    errors += [f'{a} and {b} must be equal' for a, b in MUST_MATCH if values.get(a) != values.get(b)]
    if values.get('DJANGO_DEBUG') != '0':
        errors.append('DJANGO_DEBUG must be 0 in production')
    for key, needed_for in OPTIONAL.items():
        if is_placeholder(values.get(key)):
            print(f'Warning: {key} is not set ({needed_for})')
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--env-file', type=Path, default=PROJECT_ROOT / '.env.prod')
    parser.add_argument('--start', action='store_true', help='build and start the production stack')
    args = parser.parse_args()

    env_file = args.env_file
    if not env_file.exists():
        shutil.copyfile(PROJECT_ROOT / '.env.prod.example', env_file)
        print(f'Created {env_file.name} from .env.prod.example')

    generate_missing_secrets(env_file)

    errors = check(env_file)
    if errors:
        print(f'\nEdit {env_file} before deploying:')
        for error in errors:
            print(f'  - {error}')
        return 1
    print(f'\n{env_file.name} is ready.')

    command = ['docker', 'compose', '--env-file', str(env_file), '-f', 'docker-compose.prod.yml',
               '-p', 'cocos-prod', 'up', '--build', '-d']
    if not args.start:
        print('Start the stack with: python scripts/setup_prod.py --start')
        return 0
    if not shutil.which('docker'):
        print('docker not found')
        return 1
    return subprocess.run(command, cwd=PROJECT_ROOT / 'docker', check=False).returncode


if __name__ == '__main__':
    sys.exit(main())
