#!/bin/bash
pip install -r requirements.txt


python manage.py makemigrations

# Apply migrations (ensure your database schema is up-to-date)
python manage.py migrate

# Create a superuser non-interactively
# Set environment variables for username, email, and password
export DJANGO_SUPERUSER_USERNAME="admin"
export DJANGO_SUPERUSER_EMAIL="admin@mail.com"
export DJANGO_SUPERUSER_PASSWORD="NewP@ssword123"

# Execute createsuperuser with --noinput flag
python manage.py createsuperuser --noinput

# Optional: Unset the environment variables after creation for security
unset DJANGO_SUPERUSER_USERNAME
unset DJANGO_SUPERUSER_EMAIL
unset DJANGO_SUPERUSER_PASSWORD

echo "Django superuser created successfully."
python manage.py collectstatic --no-input --clear
