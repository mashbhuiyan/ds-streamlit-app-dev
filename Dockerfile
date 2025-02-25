FROM python:3.11

WORKDIR /usr/src/app

COPY requirements.txt ./

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# This port should be the same as API_APP_PORT (environment variable)
EXPOSE 5000

ENTRYPOINT ["./start_server_and_scripts.sh"]