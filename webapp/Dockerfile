# Relay's web app (development and test image; Relay itself runs as one container: ../Dockerfile). Build context = the repository root: the app also ships the genbi toolkit (to check the agent's work
# and build the PBIP) and the custom visuals.
FROM python:3.12-slim
# Node runs the Visual Atlas brand engine (report themes from a brand color, look and palette).
RUN apt-get update && apt-get install -y --no-install-recommends nodejs && rm -rf /var/lib/apt/lists/* \
    && useradd -m -u 1000 app
# Microsoft Fabric connector: unixODBC + Microsoft's ODBC Driver 18, from Microsoft's own Debian repository (their
# setup package installs the signing key). If the driver is not published for this Debian release the build goes on;
# Fabric connections then report the missing driver.
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates unixodbc \
    && . /etc/os-release \
    && (curl -fsSL -o /tmp/ms.deb "https://packages.microsoft.com/config/debian/${VERSION_ID}/packages-microsoft-prod.deb" \
        && dpkg -i /tmp/ms.deb && apt-get update && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
        || echo "msodbcsql18 is not available for Debian ${VERSION_ID}: Fabric connections will not work") \
    && rm -rf /var/lib/apt/lists/* /tmp/ms.deb
WORKDIR /srv
COPY webapp/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY genbi_kit /opt/genbi/genbi_kit
COPY custom_visuals /opt/genbi/visuals
COPY webapp/app ./app
COPY webapp/static ./static
RUN mkdir -p /data/projects /data/state /data/backups /data/llm /data/orch && chown -R app:app /data
# Same uid as the agent, so both can write the shared project folders.
USER app
ENV PYTHONPATH=/opt/genbi GENBI_VISUALS=/opt/genbi/visuals WORKSPACES=/data/projects PYTHONUNBUFFERED=1
# The commit this image was built from: Relay Doctor bases its fixes on the live commit (doctor\doctor.py deploy and
# the Doctor's own builds pass it; `docker compose build` passes RELAY_COMMIT when it is set).
ARG RELAY_COMMIT=
LABEL relay.commit=$RELAY_COMMIT
ENV RELAY_COMMIT=$RELAY_COMMIT
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
