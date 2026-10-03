ARG CONTROL_BASE_IMAGE=python:3.12-slim
FROM ${CONTROL_BASE_IMAGE}

ARG PIP_INDEX_URL=https://pypi.org/simple
WORKDIR /app
COPY control/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt -i "${PIP_INDEX_URL}"
COPY control /app/control
ENV PYTHONPATH=/app
EXPOSE 8000
CMD ["python", "-m", "control.gateway"]
