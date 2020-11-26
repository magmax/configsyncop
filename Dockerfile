FROM python:3.8
ADD configsyncop.py .
ADD requirements.txt .
RUN pip install -r requirements.txt
ENTRYPOINT ["kopf", "run", "configsyncop.py"]
