#!/bin/bash
# Additive to the existing dedicated Oracle Linux VM. Oracle/gateway unchanged.
set -eu
dnf -q -y install python3.11 python3.11-pip unixODBC
if ! rpm -q packages-microsoft-prod; then
    dnf -q -y install https://packages.microsoft.com/config/rhel/9/packages-microsoft-prod.rpm
fi
ACCEPT_EULA=Y dnf -q -y install msodbcsql18
if ! id msflix-demo; then
    useradd --system --home-dir /var/lib/msflix-demo --shell /sbin/nologin msflix-demo
fi
install -d -m 0755 /opt/msflix-demo /opt/msflix-demo/releases
install -d -m 0750 -o root -g msflix-demo /etc/msflix-demo
install -d -m 0700 -o msflix-demo -g msflix-demo /var/lib/msflix-demo
if [ ! -x /opt/msflix-demo/venv/bin/python ]; then
    python3.11 -m venv /opt/msflix-demo/venv
fi
/opt/msflix-demo/venv/bin/python -m pip --disable-pip-version-check install --quiet \
    'azure-identity>=1.25,<2' 'confluent-kafka>=2.11,<3' 'pyodbc>=5.2,<6' \
    'azure-storage-file-datalake>=12.19,<13' 'pyarrow>=19,<23' 'deltalake==1.6.6'
/opt/msflix-demo/venv/bin/python -c 'import pyodbc, azure.identity, confluent_kafka, pyarrow, deltalake; print({"drivers":pyodbc.drivers(),"delta":deltalake.__version__,"python_ready":True})'
