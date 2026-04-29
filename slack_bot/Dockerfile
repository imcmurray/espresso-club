FROM python:3.12-slim

WORKDIR /app
COPY slack_bot/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY slack_bot/ /app/

CMD ["python3", "-u", "bot.py"]
