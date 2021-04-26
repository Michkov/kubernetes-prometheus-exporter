FROM registry.fedoraproject.org/fedora:latest

LABEL maintainer="Michal Kovarik" \
      summary="A prometheus exporter for kubernetes." \
      distribution-scope="public"

RUN dnf install -y --setopt=tsflags=nodocs \
                python3-pip \
    && dnf clean all

COPY requirements.txt /usr/local/requirements.txt
RUN pip3 install --no-dependencies -r /usr/local/requirements.txt

COPY kubernetes-prometheus-exporter.py /usr/local/bin/.

USER 1001
EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/kubernetes-prometheus-exporter.py"]
