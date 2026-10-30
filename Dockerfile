FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN python manage.py collectstatic --noinput || true
EXPOSE 8000
CMD ["sh","-c","python manage.py migrate && gunicorn inventory_management.wsgi:application -b 0.0.0.0:8000 --workers 3"]
