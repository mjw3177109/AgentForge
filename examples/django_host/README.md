# Demo host

Start with python -m pip install -e ".[django]" from repository root,
then python examples/django_host/manage.py migrate,
python examples/django_host/manage.py createsuperuser,
python examples/django_host/manage.py runserver 127.0.0.1:8000.

Admin: http://127.0.0.1:8000/admin/
Dashboard: http://127.0.0.1:8000/agentforge/

Default allowlisted roots are EMPTY; the development host does not access
your projects until the environment is explicitly configured.

DO NOT DEPLOY THIS SETTINGS MODULE TO PRODUCTION.
